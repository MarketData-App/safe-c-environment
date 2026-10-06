#!/usr/bin/env python3
"""Block commits and pushes that add personal information or credentials.

Personal values are never stored in this repository. They are derived on the
committing machine (login name, home path, host name, non-noreply Git emails)
and read from untracked private pattern files, one regular expression per line:
  <git common dir>/info/personal-patterns
  ~/.config/safe-c-environment/personal-patterns
The complete content and name of every added or changed file is checked, not
only the changed lines. Commit author and committer emails must be GitHub
noreply addresses; GitHub's web-flow committer is also accepted. Findings print the path, line and category, with the matched
value masked.

Modes: --staged (pre-commit, pre-merge-commit), --message FILE (commit-msg),
--push (pre-push; covers merges, cherry-picks and rebases), --history (every
commit reachable from HEAD) and --tree (every tracked file).
"""
from pathlib import Path
import argparse
import getpass
import os
import re
import socket
import subprocess
import sys

GENERIC = {
    'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'aws-key': r'\bAKIA[0-9A-Z]{16}\b',
    'private-key': r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'model-provider-key': r'\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}',
    'slack-token': r'\bxox[abposr]-[A-Za-z0-9-]{10,}',
    'user-home-path': r'(?:/[Hh][Oo][Mm][Ee]|/Users)/(?!(?:runner|user)(?![A-Za-z0-9._-])|\$|\{|<)[A-Za-z0-9._-]+',
    'email-address': r'\b(?!noreply@github\.com\b)[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org|net)\b)'
                     r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
}
# Vendored upstream copies legitimately carry upstream author names and contacts.
VENDORED = ('third_party/',)
VENDORED_RULES = {'email-address', 'local-identity'}
NOREPLY = r'(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com'
WEB_FLOW = 'noreply@github.com'
ZERO = re.compile(r'^0+$')
PRINTABLE = re.compile(rb'[\x20-\x7e]{8,}')


def decode(data):
    # Binary content (NUL present) is reduced to printable runs, like strings(1),
    # so compressed bytes do not form accidental matches.
    if b'\0' in data:
        return '\n'.join(run.decode('ascii') for run in PRINTABLE.findall(data))
    return data.decode('utf-8', errors='replace')


def git(*args, binary=False):
    result = subprocess.run(['git', '-c', 'core.quotePath=false', *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError('git ' + args[0] + ' failed')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


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
        if email and not re.fullmatch(NOREPLY, email):
            values.add(email)
    return sorted(v for v in values if len(v) >= 3 and v not in {'root', 'runner', 'localhost', 'user'})


def rules():
    compiled = [(name, re.compile(rx)) for name, rx in GENERIC.items()]
    compiled += [('local-identity', re.compile(r'(?<![A-Za-z0-9])' + re.escape(v) + r'(?![A-Za-z0-9])', re.I))
                 for v in local_values()]
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
    return compiled, errors


def mask(value):
    return value[0] + '*' * (len(value) - 1) if len(value) > 1 else '*'


class Scanner:
    def __init__(self):
        self.rules, self.findings = rules()

    def text(self, label, path, text):
        for number, line in enumerate(text.splitlines(), 1):
            for name, rx in self.rules:
                if name in VENDORED_RULES and path.startswith(VENDORED):
                    continue
                match = rx.search(line)
                if match:
                    self.findings.append(f'{label}:{number}: {name} ({mask(match.group(0))})')

    def name(self, label, path):
        for name, rx in self.rules:
            match = rx.search(path)
            if match:
                self.findings.append(f'{label}: file-name {name} ({mask(match.group(0))})')

    def blob(self, label, path, spec):
        self.name(label, path)
        self.text(label, path, decode(git('cat-file', 'blob', spec, binary=True)))

    def identity(self, label, role, email):
        # GitHub's own web-flow committer (merge button, edits) is not a personal address.
        if role == 'committer' and email == WEB_FLOW:
            return
        if not re.fullmatch(NOREPLY, email or ''):
            self.findings.append(f'{label}: {role}-identity-not-noreply ({mask(email) if email else "missing"})')

    def commit(self, sha):
        label = sha[:12]
        author, committer, message = git('log', '-1', '--format=%ae%x00%ce%x00%B', sha).split('\0', 2)
        self.identity(label, 'author', author)
        self.identity(label, 'committer', committer)
        self.text(label + ':message', '', message)
        parents = git('rev-list', '--parents', '-n', '1', sha).split()[1:]
        base = ['--root'] if not parents else []
        listing = git('diff-tree', '-r', '-z', '--no-commit-id', '--name-only', '--diff-filter=ACMRT',
                      '--no-renames', *base, sha)
        for path in filter(None, listing.split('\0')):
            self.blob(f'{label}:{path}', path, f'{sha}:{path}')


def staged(scanner):
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        match = re.search(r'<([^>]*)>', git('var', role))
        scanner.identity('index', role.split('_')[1].lower(), match.group(1) if match else '')
    listing = git('diff', '--cached', '-z', '--name-only', '--diff-filter=ACMRT', '--no-renames')
    for path in filter(None, listing.split('\0')):
        scanner.blob(path, path, ':' + path)


def pushed(scanner, lines):
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or ZERO.match(parts[1]):
            continue
        local, remote = parts[1], parts[3]
        known = not ZERO.match(remote) and subprocess.run(['git', 'cat-file', '-e', remote + '^{commit}'],
                                                          capture_output=True).returncode == 0
        spec = [f'{remote}..{local}'] if known else [local, '--not', '--remotes']
        for sha in git('rev-list', *spec).split():
            scanner.commit(sha)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--staged', action='store_true', help='check the index and identity (default)')
    mode.add_argument('--message', metavar='FILE', help='check every line of a commit message file')
    mode.add_argument('--push', action='store_true', help='check commits named by pre-push standard input')
    mode.add_argument('--history', action='store_true', help='check every commit reachable from HEAD')
    mode.add_argument('--tree', action='store_true', help='check every tracked file')
    args = parser.parse_args()
    try:
        scanner = Scanner()
        if args.message:
            scanner.text('COMMIT_MSG', '', Path(args.message).read_text(errors='replace'))
        elif args.push:
            pushed(scanner, sys.stdin.read().splitlines())
        elif args.history:
            for sha in git('rev-list', 'HEAD').split():
                scanner.commit(sha)
        elif args.tree:
            for path in filter(None, git('ls-files', '-z').split('\0')):
                scanner.name(path, path)
                scanner.text(path, path, decode(Path(path).read_bytes()))
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
