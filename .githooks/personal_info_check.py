#!/usr/bin/env python3
"""Block commits, tags and pushes that add personal information or credentials.

Personal values are never stored in this repository. They are derived on the
committing machine (login name, home path, host name, non-noreply Git emails)
and read from untracked private pattern files, one regular expression per line:
  <git common dir>/info/personal-patterns
  ~/.config/safe-c-environment/personal-patterns
The complete content and name of every added or changed file is checked, not
only the changed lines; merge commits are compared with every parent. UTF-16
and gzip content is decoded, and other binary content is reduced to printable
runs. Commit author/committer and tag tagger emails must be GitHub noreply
addresses (GitHub's web-flow committer is also accepted), and their names and
messages are checked like content. Content of a file under third_party/ is
exempt only while its bytes match a sha256 pinned in a lock file of the same
revision (the reviewed upstream artifact); its name is still checked, and any
changed or unpinned vendored file gets every rule. Findings print the path, line and category,
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
import io
import json
import os
import re
import socket
import subprocess
import sys
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
DIGEST = re.compile(r'(?:sha256:)?[0-9a-f]{64}')
DECOMPRESSED_LIMIT = 64 * 1024 * 1024


def git(*args, binary=False, check=True):
    result = subprocess.run(['git', '-c', 'core.quotePath=false', *args], capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError('git ' + args[0] + ' failed')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


def inflate(data):
    """Bounded gzip inflation that keeps partial output of truncated, multi-member
    or trailing-data streams."""
    out, rest = bytearray(), data
    while rest[:2] == b'\x1f\x8b' and len(out) <= DECOMPRESSED_LIMIT:
        engine = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out += engine.decompress(rest, DECOMPRESSED_LIMIT + 1 - len(out))
        except zlib.error:
            break
        if not engine.eof:
            break
        rest = engine.unused_data
    if len(out) > DECOMPRESSED_LIMIT:
        raise ValueError('decompressed content exceeds the finite limit')
    return bytes(out)


def unzip(data):
    """Bounded concatenation of zip member names and contents."""
    out = bytearray()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist()[:4096]:
                out += info.filename.encode() + b'\n'
                with archive.open(info) as member:
                    out += member.read(DECOMPRESSED_LIMIT + 1 - len(out)) + b'\n'
                if len(out) > DECOMPRESSED_LIMIT:
                    raise ValueError('decompressed content exceeds the finite limit')
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error, NotImplementedError, RuntimeError):
        pass
    return bytes(out)


def decode(data, depth=0):
    """Readable text of a blob: nested gzip and zip (finite), UTF-16/UTF-32 with or
    without a byte-order mark, and printable runs of other binary content."""
    if depth < 4:
        inner = inflate(data) if data[:2] == b'\x1f\x8b' else unzip(data) if data[:4] == b'PK\x03\x04' else b''
        if inner:
            return decode(inner, depth + 1) + '\n' + decode(data, 4)
    parts = [data.decode('utf-8', errors='replace')]
    for bom, codec in ((b'\xff\xfe\x00\x00', 'utf-32'), (b'\x00\x00\xfe\xff', 'utf-32'),
                       (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16')):
        if data.startswith(bom):
            parts.append(data.decode(codec, errors='replace'))
            break
    if b'\0' in data:
        # Binary content: printable runs, also from 2- and 4-byte strides so UTF-16
        # and UTF-32 text without a byte-order mark is still read.
        strides = [data] + [data[k::2] for k in range(2)] + [data[k::4] for k in range(4)]
        parts = [run.decode('ascii') for part in strides for run in PRINTABLE.findall(part)]
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
        self.text(label, decode(data))
        if b'\0' in data:
            for rx in self.raw:
                match = rx.search(data)
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
        listing = git('diff-tree', '-r', '-z', '--no-commit-id', '--name-only', '--diff-filter=ACMRT',
                      '--no-renames', *base, sha)
        for path in sorted(set(filter(None, listing.split('\0')))):
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
            for path in filter(None, git('ls-tree', '-r', '-z', '--name-only', obj).split('\0')):
                self.blob(f'tagged-tree {obj[:12]}:{path}', path, obj)
        return obj


def staged(scanner):
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        match = re.search(r'^(.*) <([^>]*)>', git('var', role))
        scanner.identity('index', role.split('_')[1].lower(), match.group(2) if match else '',
                         match.group(1) if match else '')
    listing = git('diff', '--cached', '-z', '--name-only', '--diff-filter=ACMRT', '--no-renames')
    for path in filter(None, listing.split('\0')):
        scanner.blob(path, path, ':')


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
            for path in filter(None, git('ls-files', '-z').split('\0')):
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
