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
gzip, xz and bzip2, nested to a finite depth within one decompression budget);
an undecodable member or an exceeded member cap is a finding. Text is read as
UTF-8, UTF-16 or UTF-32 with or without a byte-order mark; other binary content
is read as printable runs and searched byte-wise for local values. Commit
author/committer and tag tagger emails must be GitHub noreply addresses (GitHub's
web-flow committer is also accepted), and their names and messages are checked
like content. Content of a file under third_party/ or container/foundation-inputs/,
or of an upstream archive (.whl, .zip, .tar.*), is exempt only when a lock file of
the same revision binds that path to that sha256; names are always checked and
first-party files get every rule. Findings print the path, line and category,
with the matched value masked.

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
MEMBER_CAP = 4096
GITLINK = '160000'
DIGEST = re.compile(r'(?:sha256:)?[0-9a-f]{64}')
DECOMPRESSED_LIMIT = 64 * 1024 * 1024


def git(*args, binary=False, check=True):
    result = subprocess.run(['git', '-c', 'core.quotePath=false', *args], capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError('git ' + args[0] + ' failed')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


class Expansion:
    """Finite budget and findings shared by one archive expansion."""
    def __init__(self):
        self.used, self.problems = 0, []

    def take(self, size):
        self.used += size
        if self.used > DECOMPRESSED_LIMIT:
            raise ValueError('decompressed content exceeds the finite limit')

    def room(self):
        return DECOMPRESSED_LIMIT - self.used + 1


def inflate(data, state):
    """Bounded gzip inflation that keeps partial output of truncated, multi-member
    or trailing-data streams."""
    out, rest = bytearray(), data
    while rest[:2] == b'\x1f\x8b':
        engine = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            chunk = engine.decompress(rest, state.room())
        except zlib.error:
            break
        state.take(len(chunk))
        out += chunk
        if not engine.eof:
            break
        rest = engine.unused_data
    return bytes(out)


def unpack(data, state, engine):
    try:
        out = engine.decompress(data, max_length=state.room())
    except (OSError, EOFError, lzma.LZMAError, ValueError):
        return b''
    state.take(len(out))
    return out


def expand(data, state, depth=0):
    """(member names, leaf contents) of a blob, expanding archives member by member."""
    if depth >= MAX_DEPTH:
        return [], [data]
    inner = None
    if data[:2] == b'\x1f\x8b':
        inner = inflate(data, state)
    elif data[:6] == b'\xfd7zXZ\x00':
        inner = unpack(data, state, lzma.LZMADecompressor())
    elif data[:3] == b'BZh':
        inner = unpack(data, state, bz2.BZ2Decompressor())
    if inner:
        return expand(inner, state, depth + 1)
    names, leaves = [], []
    if data[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > MEMBER_CAP:
                    state.problems.append('archive-member-cap')
                for info in members[:MEMBER_CAP]:
                    names.append(info.filename)
                    try:
                        with archive.open(info) as member:
                            content = member.read(state.room())
                    except (NotImplementedError, RuntimeError, zipfile.BadZipFile, OSError, EOFError, zlib.error):
                        state.problems.append('undecodable-archive-member')
                        continue
                    state.take(len(content))
                    more_names, more = expand(content, state, depth + 1)
                    names += more_names
                    leaves += more
            return names, leaves
        except zipfile.BadZipFile:
            pass
    if len(data) > 262 and data[257:262] == b'ustar':
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
                count = 0
                for member in archive:
                    count += 1
                    if count > MEMBER_CAP:
                        state.problems.append('archive-member-cap')
                        break
                    names.append(member.name)
                    if member.isfile():
                        content = archive.extractfile(member).read(state.room())
                        state.take(len(content))
                        more_names, more = expand(content, state, depth + 1)
                        names += more_names
                        leaves += more
            return names, leaves
        except tarfile.TarError:
            names, leaves = [], []
    return [], [data]


def decode(data):
    """Readable text of one leaf: UTF-8, UTF-16/UTF-32 with or without a byte-order
    mark, and printable runs of other binary content."""
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
        state = Expansion()
        names, leaves = expand(data, state)
        for member in names:
            self.name(f'{label}!{member}', member)
        for problem in sorted(set(state.problems)):
            self.findings.append(f'{label}: {problem}')
        for leaf in leaves:
            self.text(label, decode(leaf))
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
        print(f'personal-info-check: {row}', file=sys.stderr)
    if scanner.findings:
        print(f'personal-info-check: BLOCKED, {len(scanner.findings)} finding(s). Remove the values; '
              'do not bypass with --no-verify.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
