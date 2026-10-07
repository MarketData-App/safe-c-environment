#!/usr/bin/env python3
"""Block commits, tags and pushes that add personal information or credentials.

Personal values are never stored in this repository. They are derived on the
committing machine (login name, home path, host name, non-noreply Git emails)
and read from untracked private pattern files, one regular expression per line:
  <git common dir>/info/personal-patterns
  ~/.config/safe-c-environment/personal-patterns
The complete content and name of every added or changed file is checked, not
only the changed lines; merge commits are compared with every parent and
submodule entries are skipped. Archives are expanded member by member (zip, tar,
gzip, xz and bzip2 with every stream, nested to a finite depth within one
decompression budget), and the container bytes and metadata (tar owner, group,
link target and pax records, zip comments, gzip header names) are checked too;
a corrupt or truncated stream, an undecodable member, a zip local-header
signature at an offset that the central directory does not list (also inside a
stored member's own bytes), and an exceeded member cap, depth limit or budget are
findings. Text is read as
UTF-8, UTF-16 or UTF-32 with or without a byte-order mark; other binary content
is read as printable runs and searched byte-wise for local values. Commit
author/committer and tag tagger emails must be GitHub noreply addresses (GitHub's
web-flow committer is also accepted), and their names and messages are checked
like content. Content of a file under third_party/ or container/foundation-inputs/,
or of an upstream archive (.whl, .zip, .tar.*), is exempt only when a lock file of
the same revision binds that path to that sha256; names are always checked and
first-party files get every rule. A first-party (unpinned) zip, tar, gzip, xz or
bzip2 file is itself a finding. Findings print the path, line and category;
every matched value, also one inside a printed path or label, is masked, archive
metadata is labelled by index and output is reduced to printable characters.

Modes: --staged (pre-commit, pre-merge-commit), --message FILE (commit-msg),
--push [REMOTE] (pre-push; covers merges, cherry-picks, rebases and tags),
--history (every commit and tag reachable from HEAD and tags) and --tree
(every tracked file).
"""
from pathlib import Path
import argparse
import getpass
import hashlib
import bz2
import io
import json
import lzma
import os
import re
import socket
import subprocess
import sys
import tarfile
import zipfile
import zlib

GENERIC = {
    'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'aws-key': r'\bAKIA[0-9A-Z]{16}\b',
    'private-key': r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'model-provider-key': r'\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}',
    'slack-token': r'\bxox[abposr]-[A-Za-z0-9-]{10,}',
    'user-home-path': r'(?:/[Hh][Oo][Mm][Ee]|/Users)/(?!(?:runner|user)(?![A-Za-z0-9._-])|\$|\{|<)[A-Za-z0-9._-]+',
    'email-address': r'(?i)\b(?!noreply@github\.com(?![A-Za-z0-9.-])|git@)[A-Za-z0-9._%+-]+@'
                     r'(?!(?:users\.noreply\.github\.com|example\.(?:com|org|net))(?![A-Za-z0-9.-]))'
                     r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
}
VENDORED = ('third_party/', 'container/foundation-inputs/')
UPSTREAM_ARCHIVES = ('.whl', '.zip', '.tar.gz', '.tgz', '.tar.xz', '.tar.bz2', '.tar.zst')
LOCKS = ('upstream.lock.json', 'developer.lock.json', 'foundation.lock.json', 'toolchain.lock.json')
NOREPLY = re.compile(r'(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com', re.I)
WEB_FLOW = 'noreply@github.com'
ZERO = re.compile(r'^0+$')
PRINTABLE = re.compile(rb'[\x20-\x7e]{8,}')
SHORT_RUNS = re.compile(rb'[\x20-\x7e]{3,}')
MAX_DEPTH = 4
CHUNK = 4 * 1024
GZIP, XZ, BZIP2 = b'\x1f\x8b', b'\xfd7zXZ\x00', b'BZh'
MEMBER_CAP = 4096
GITLINK = '160000'
DIGEST = re.compile(r'(?:sha256:)?[0-9a-f]{64}')
DECOMPRESSED_LIMIT = 64 * 1024 * 1024


def git(*args, binary=False, check=True):
    result = subprocess.run(['git', '-c', 'core.quotePath=false', *args], capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError('git ' + args[0] + ' failed')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


class BudgetExceeded(ValueError):
    """The finite decompression budget of one blob was exceeded."""


class Expansion:
    """Finite budget and findings shared by one archive expansion."""
    def __init__(self):
        self.used, self.problems = 0, []

    def take(self, size):
        self.used += size
        if self.used > DECOMPRESSED_LIMIT:
            raise BudgetExceeded('decompressed content exceeds the finite limit')

    def room(self):
        return DECOMPRESSED_LIMIT - self.used + 1


def drain(engine, data, state):
    """Stream data through one decompressor in finite chunks within the budget.
    Returns (output, remaining input after the stream, complete); the output of
    the input chunks before the failing chunk is kept (a stream shorter than one
    chunk keeps nothing), and an error or truncation gives complete=False."""
    out = bytearray()
    for start in range(0, len(data), CHUNK):
        pending = data[start:start + CHUNK]
        try:
            while True:
                if hasattr(engine, 'unconsumed_tail'):
                    piece = engine.decompress(pending, state.room())
                    pending = engine.unconsumed_tail
                    more = bool(pending)
                else:
                    piece = engine.decompress(pending, max_length=state.room())
                    pending = b''
                    more = not engine.eof and not engine.needs_input
                state.take(len(piece))
                out += piece
                if engine.eof:
                    return bytes(out), engine.unused_data + data[start + CHUNK:], True
                if not more:
                    break
        except (zlib.error, OSError, EOFError, lzma.LZMAError):
            return bytes(out), b'', False
    return bytes(out), b'', False


def gzip_header(data):
    """(file name and comment fields, offset of the deflate data) of one gzip header."""
    flags, cursor, meta = (data[3] if len(data) > 3 else 0), 10, []
    if flags & 4 and len(data) > 12:
        cursor += 2 + int.from_bytes(data[10:12], 'little')
    for bit in (8, 16):
        if flags & bit:
            stop = data.find(b'\0', cursor)
            if stop < 0:
                break
            meta.append(data[cursor:stop].decode('latin-1'))
            cursor = stop + 1
    if flags & 2:
        cursor += 2
    return meta, cursor


def gzip_meta(data):
    return gzip_header(data)[0]


def is_bzip2(data):
    """A real bzip2 stream header: BZh, a block size digit, then a block or end-of-stream magic."""
    return (len(data) >= 10 and data[:3] == BZIP2 and data[3] in b'123456789'
            and data[4:10] in (b'1AY&SY', b'\x17rE8P\x90'))


def streams(data, state, magic, factory, meta=None):
    """Decode every concatenated stream that starts with magic."""
    out, rest, names = bytearray(), data, []
    while (is_bzip2(rest) if magic == BZIP2 else rest[:len(magic)] == magic):
        if meta:
            names += meta(rest)
        piece, after, complete = drain(factory(), rest, state)
        if not complete and magic == GZIP:
            # A damaged trailer (CRC or length) still leaves readable deflate data.
            salvage, _, _ = drain(zlib.decompressobj(-zlib.MAX_WBITS), rest[gzip_header(rest)[1]:], state)
            piece = max(piece, salvage, key=len)
        out += piece
        rest = after
        if not complete:
            state.problems.append('undecodable-archive')
            break
        rest = rest.lstrip(b'\0')
    return bytes(out), names


def archive_like(data):
    return (data[:2] == GZIP or data[:6] == XZ or is_bzip2(data) or data[:4] == b'PK\x03\x04'
            or b'PK\x05\x06' in data[-65558:] or data[257:262] == b'ustar')


def zip_unlisted(data, offsets):
    """True when any local-header signature in the zip bytes is at an offset that the
    central directory does not list. Nothing is skipped by a recorded size, so a
    stored member whose own bytes hold the signature is also reported (fail closed)."""
    cursor = data.find(b'PK\x03\x04')
    while cursor >= 0:
        if cursor not in offsets:
            return True
        cursor = data.find(b'PK\x03\x04', cursor + 1)
    return False


def expand(data, state, depth=0):
    """(member names and metadata, leaf contents, container bytes) of a blob,
    expanding archives member by member."""
    if depth >= MAX_DEPTH:
        if archive_like(data):
            state.problems.append('archive-depth-limit')
        return [], [data], []
    names, inner = [], None
    if data[:2] == GZIP:
        inner, names = streams(data, state, GZIP, lambda: zlib.decompressobj(16 + zlib.MAX_WBITS), gzip_meta)
    elif data[:6] == XZ:
        inner, names = streams(data, state, XZ, lzma.LZMADecompressor)
    elif is_bzip2(data):
        inner, names = streams(data, state, BZIP2, bz2.BZ2Decompressor)
    if inner:
        more_names, leaves, containers = expand(inner, state, depth + 1)
        return names + more_names, leaves, containers + [data]
    if names or data[:2] == GZIP or data[:6] == XZ or is_bzip2(data):
        return names, [], [data]
    leaves, containers = [], []
    if data[:4] == b'PK\x03\x04' or b'PK\x05\x06' in data[-65558:]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names.append(archive.comment.decode('latin-1'))
                members = archive.infolist()
                if len(members) > MEMBER_CAP:
                    state.problems.append('archive-member-cap')
                if zip_unlisted(data, {info.header_offset for info in members}):
                    state.problems.append('zip-unlisted-local-entry')
                for info in members[:MEMBER_CAP]:
                    names += [info.filename, info.comment.decode('latin-1'), info.extra.decode('latin-1')]
                    try:
                        with archive.open(info) as member:
                            content = member.read(state.room())
                    except (NotImplementedError, RuntimeError, zipfile.BadZipFile, OSError, EOFError, zlib.error):
                        state.problems.append('undecodable-archive-member')
                        continue
                    state.take(len(content))
                    more_names, more, more_containers = expand(content, state, depth + 1)
                    names += more_names
                    leaves += more
                    containers += more_containers
            return names, leaves, containers + [data]
        except zipfile.BadZipFile:
            if data[:4] == b'PK\x03\x04':
                state.problems.append('undecodable-archive')
                return names, leaves, containers + [data]
            names, leaves, containers = [], [], []
    if len(data) >= 512 and (data[257:262] == b'ustar' or len(data) % 512 == 0):
        count = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:', ignore_zeros=True) as archive:
                for member in archive:
                    count += 1
                    if count > MEMBER_CAP:
                        state.problems.append('archive-member-cap')
                        break
                    names += [member.name, member.uname, member.gname, member.linkname]
                    names += [f'{key}={value}' for key, value in member.pax_headers.items()]
                    if member.isfile():
                        # Regular members are slices of a buffer already counted in the
                        # budget; sparse members expand holes, so their size is counted first.
                        if member.issparse():
                            state.take(member.size)
                        content = archive.extractfile(member).read()
                        more_names, more, more_containers = expand(content, state, depth + 1)
                        names += more_names
                        leaves += more
                        containers += more_containers
        except tarfile.TarError:
            if data[257:262] == b'ustar':
                state.problems.append('undecodable-archive')
        if count:
            return names, leaves, containers + [data]
        names, leaves, containers = [], [], []
    return [], [data], []


def decode(data, short=True):
    """Readable text of one leaf: UTF-8, UTF-16/UTF-32 with or without a byte-order
    mark, and printable runs of other binary content (short runs only for leaves,
    not for compressed container bytes)."""
    parts = [data.decode('utf-8', errors='replace')]
    for bom, codec in ((b'\xff\xfe\x00\x00', 'utf-32'), (b'\x00\x00\xfe\xff', 'utf-32'),
                       (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16')):
        if data.startswith(bom):
            parts.append(data.decode(codec, errors='replace'))
            break
    if b'\0' in data:
        # Binary content: printable runs, also from 2- and 4-byte strides so UTF-16
        # and UTF-32 text without a byte-order mark is still read, and short runs of
        # the bytes themselves so short values between NUL bytes are read.
        strides = [data] + [data[k::2] for k in range(2)] + [data[k::4] for k in range(4)]
        parts = [run.decode('ascii') for part in strides for run in PRINTABLE.findall(part)]
        if short:
            parts += [run.decode('ascii') for run in SHORT_RUNS.findall(data)]
    return '\n'.join(parts)


def local_values():
    values = set()
    try:
        values.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    values.add(Path.home().name)
    for name in (socket.gethostname(), socket.getfqdn()):
        values.update([name.split('.')[0], name])
    emails = subprocess.run(['git', 'config', '--get-all', 'user.email'], capture_output=True, text=True).stdout
    for email in emails.split() + [os.environ.get('GIT_AUTHOR_EMAIL', ''), os.environ.get('GIT_COMMITTER_EMAIL', '')]:
        if email and not NOREPLY.fullmatch(email):
            values.add(email)
    return sorted(v for v in values if len(v) >= 3 and v not in {'root', 'runner', 'localhost', 'user'})


def rules():
    compiled = [(name, re.compile(rx)) for name, rx in GENERIC.items()]
    compiled += [('local-identity', re.compile(r'(?<![A-Za-z0-9])' + re.escape(v) + r'(?![A-Za-z0-9])', re.I))
                 for v in local_values()]
    # Binary content is also searched byte-wise for local values, so short values
    # between NUL bytes are found without shortening printable runs.
    raw = [re.compile(rb'(?<![A-Za-z0-9])' + re.escape(v.encode()) + rb'(?![A-Za-z0-9])', re.I) for v in local_values()]
    errors = []
    common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir').strip())
    for path in (common / 'info' / 'personal-patterns',
                 Path.home() / '.config' / 'safe-c-environment' / 'personal-patterns'):
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            errors.append(f'{path.name}: unreadable-private-patterns')
            continue
        for number, line in enumerate(lines, 1):
            if line.strip() and not line.lstrip().startswith('#'):
                try:
                    compiled.append(('private-pattern', re.compile(line.strip(), re.I)))
                except re.error:
                    errors.append(f'{path.name}:{number}: invalid-private-pattern')
    return compiled, errors, raw


def mask(value):
    return value[0] + '*' * (len(value) - 1) if len(value) > 1 else '*'


class Scanner:
    def __init__(self):
        self.rules, self.findings, self.raw = rules()
        self.pins = {}

    def pinned(self, rev):
        """(path, sha256) pairs bound together in a lock file at rev (':' index, None
        working tree, else a commit or tree): a mapping from the path to the digest,
        or one object holding both the path and the digest."""
        if rev not in self.pins:
            pairs = set()
            for lock in LOCKS:
                if rev is None:
                    raw = Path(lock).read_bytes() if Path(lock).is_file() else b''
                else:
                    raw = git('cat-file', 'blob', f'{rev}{lock}' if rev == ':' else f'{rev}:{lock}', binary=True,
                              check=False)
                try:
                    stack = [json.loads(raw)] if raw else []
                except ValueError:
                    stack = []
                while stack:
                    item = stack.pop()
                    if isinstance(item, dict):
                        texts = [v for v in item.values() if isinstance(v, str)]
                        digests = {t[-64:] for t in texts if DIGEST.fullmatch(t)}
                        for key, value in item.items():
                            if isinstance(value, str) and DIGEST.fullmatch(value):
                                pairs.add((key, value[-64:]))
                        for text in texts:
                            pairs.update((text, digest) for digest in digests)
                        stack += [v for v in item.values() if isinstance(v, (dict, list))]
                    elif isinstance(item, list):
                        stack += item
            self.pins[rev] = pairs
        return self.pins[rev]

    def text(self, label, text):
        for number, line in enumerate(text.splitlines(), 1):
            for name, rx in self.rules:
                match = rx.search(line)
                if match:
                    self.findings.append(f'{label}:{number}: {name} ({mask(match.group(0))})')

    def redact(self, row):
        """Mask every non-empty match of every rule in a printed row, labels included."""
        for _, rx in self.rules:
            row = rx.sub(lambda match: mask(match.group(0)) if match.group(0) else '', row)
        return row

    def name(self, label, path):
        for name, rx in self.rules:
            match = rx.search(path)
            if match:
                self.findings.append(f'{label}: file-name {name} ({mask(match.group(0))})')

    def content(self, label, path, data, rev):
        self.name(label, path)
        upstream = path.startswith(VENDORED) or path.endswith(UPSTREAM_ARCHIVES)
        if upstream and (path, hashlib.sha256(data).hexdigest()) in self.pinned(rev):
            return
        if archive_like(data):
            # First-party archives are not allowed: pin reviewed upstream archives in a lock.
            self.findings.append(f'{label}: unpinned-archive')
        state = Expansion()
        try:
            names, leaves, containers = expand(data, state)
        except BudgetExceeded:
            self.findings.append(f'{label}: archive-budget-exceeded')
            return
        for index, member in enumerate(names):
            if member:
                self.name(f'{label}!member{index}', member)
        for problem in sorted(set(state.problems)):
            self.findings.append(f'{label}: {problem}')
        for leaf in leaves:
            self.text(label, decode(leaf))
        for container in containers:
            self.text(label + '!container', decode(container, short=False))
        for leaf in leaves + containers:
            if b'\0' in leaf:
                for rx in self.raw:
                    match = rx.search(leaf)
                    if match:
                        self.findings.append(f'{label}: binary local-identity ({mask(match.group(0).decode("latin-1"))})')

    def blob(self, label, path, rev):
        spec = f':{path}' if rev == ':' else f'{rev}:{path}'
        self.content(label, path, git('cat-file', 'blob', spec, binary=True), rev)

    def identity(self, label, role, email, name=''):
        self.text(f'{label}: {role}-name', name)
        if role == 'committer' and email == WEB_FLOW:
            return
        if not NOREPLY.fullmatch(email or ''):
            self.findings.append(f'{label}: {role}-identity-not-noreply ({mask(email) if email else "missing"})')

    def commit(self, sha):
        label = sha[:12]
        fields = git('log', '-1', '--format=%an%x00%ae%x00%cn%x00%ce%x00%B', sha).split('\0', 4)
        self.identity(label, 'author', fields[1], fields[0])
        self.identity(label, 'committer', fields[3], fields[2])
        self.text(label + ':message', fields[4])
        header = git('cat-file', 'commit', sha).partition('\n\n')[0]
        self.text(label + ':header', '\n'.join(line for line in header.splitlines()
                                               if not line.startswith(('tree ', 'parent '))))
        parents = git('rev-list', '--parents', '-n', '1', sha).split()[1:]
        base = ['--root'] if not parents else ['-m'] if len(parents) > 1 else []
        listing = git('diff-tree', '-r', '-z', '--no-commit-id', '--raw', '--diff-filter=ACMRT',
                      '--no-renames', *base, sha)
        for path in sorted(changed(listing)):
            self.blob(f'{label}:{path}', path, sha)

    def tag(self, obj):
        """Check a tag chain and return the final non-tag object; tagged blobs and
        trees are scanned like files."""
        seen = set()
        while kind(obj) == 'tag':
            if obj in seen:
                raise ValueError('tag cycle')
            seen.add(obj)
            raw = git('cat-file', 'tag', obj)
            header, _, message = raw.partition('\n\n')
            tagger = re.search(r'^tagger (.*) <([^>]*)>', header, re.M)
            label = 'tag ' + obj[:12]
            if tagger:
                self.identity(label, 'tagger', tagger.group(2), tagger.group(1))
            else:
                self.findings.append(f'{label}: tagger-identity-not-noreply (missing)')
            self.text(label + ':message', message)
            self.text(label + ':header', '\n'.join(line for line in header.splitlines()
                                                   if not line.startswith(('object ', 'type '))))
            obj = re.search(r'^object ([0-9a-f]+)', header, re.M).group(1)
        target = kind(obj)
        if target == 'blob':
            self.content('tagged-blob ' + obj[:12], '', git('cat-file', 'blob', obj, binary=True), None)
        elif target == 'tree':
            for row in filter(None, git('ls-tree', '-r', '-z', obj).split('\0')):
                meta, _, path = row.partition('\t')
                if meta.split()[1] == 'blob':
                    self.blob(f'tagged-tree {obj[:12]}:{path}', path, obj)
        return obj


def staged(scanner):
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        match = re.search(r'^(.*) <([^>]*)>', git('var', role))
        scanner.identity('index', role.split('_')[1].lower(), match.group(2) if match else '',
                         match.group(1) if match else '')
    listing = git('diff', '--cached', '-z', '--raw', '--diff-filter=ACMRT', '--no-renames')
    for path in sorted(changed(listing)):
        scanner.blob(path, path, ':')


def changed(listing):
    """Paths of a -z --raw listing, without submodule (gitlink) entries."""
    fields, paths, index = listing.split('\0'), set(), 0
    while index + 1 < len(fields):
        meta, path = fields[index], fields[index + 1]
        if not meta.startswith(':'):
            raise ValueError('unexpected raw listing record')
        if meta.split()[1] != GITLINK:
            paths.add(path)
        index += 2
    return paths


def kind(obj):
    return git('cat-file', '-t', obj, check=False).strip()


def pushed(scanner, lines, remote):
    names = set(git('remote').split())
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or ZERO.match(parts[1]):
            continue
        obj, target = scanner.tag(parts[1]), parts[3]
        if kind(obj) != 'commit':
            continue
        exclude = [target] if not ZERO.match(target) and kind(target) == 'commit' else []
        if remote in names:
            exclude.append(f'--remotes={remote}')
        for sha in git('rev-list', obj, *(['--not', *exclude] if exclude else [])).split():
            scanner.commit(sha)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--staged', action='store_true', help='check the index and identity (default)')
    mode.add_argument('--message', metavar='FILE', help='check every line of a commit message file')
    mode.add_argument('--push', nargs='?', const='', metavar='REMOTE',
                      help='check commits and tags named by pre-push standard input')
    mode.add_argument('--history', action='store_true', help='check every commit and tag reachable from HEAD and tags')
    mode.add_argument('--tree', action='store_true', help='check every tracked file')
    args = parser.parse_args()
    try:
        scanner = Scanner()
        if args.message:
            scanner.text('COMMIT_MSG', Path(args.message).read_text(errors='replace'))
        elif args.push is not None:
            pushed(scanner, sys.stdin.read().splitlines(), args.push)
        elif args.history:
            for obj in git('for-each-ref', '--format=%(objectname)', 'refs/tags').split():
                scanner.tag(obj)
            for sha in git('rev-list', 'HEAD', '--tags').split():
                scanner.commit(sha)
        elif args.tree:
            for row in filter(None, git('ls-files', '-s', '-z').split('\0')):
                meta, _, path = row.partition('\t')
                if meta.split()[0] != GITLINK:
                    scanner.content(path, path, Path(path).read_bytes(), None)
        else:
            staged(scanner)
    except (OSError, RuntimeError, ValueError) as error:
        print(f'personal-info-check: BLOCKED, check failed ({type(error).__name__})', file=sys.stderr)
        return 2
    for row in scanner.findings[:200]:
        print('personal-info-check: ' + re.sub(r'[^\x20-\x7e]', '?', scanner.redact(row)), file=sys.stderr)
    if scanner.findings:
        print(f'personal-info-check: BLOCKED, {len(scanner.findings)} finding(s). Remove the values; '
              'do not bypass with --no-verify.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
