#!/usr/bin/env python3
"""Block commits that add personal information or credentials.

Personal values are never stored in this repository. They are derived on the
committing machine (login name, home path, host name, non-noreply Git emails)
and read from untracked private pattern files, one regular expression per line:
  .git/info/personal-patterns
  ~/.config/safe-c-environment/personal-patterns
Only added lines are checked. Findings print the path, line and category, with
the matched value masked. The commit author and committer emails must be
GitHub noreply addresses.
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
    'user-home-path': r'(?:/home|/Users)/(?!runner\b|user\b|\$|\{|<)[A-Za-z0-9._-]+',
    'email-address': r'\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org|net)\b)'
                     r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
}
# Vendored upstream copies legitimately carry upstream author names and contacts.
VENDORED = ('third_party/',)
VENDORED_RULES = {'email-address', 'local-identity'}
SELF = '.githooks/personal_info_check.py'
NOREPLY = r'(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com'


def git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, check=False).stdout


def local_values():
    values = set()
    try:
        values.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    values.add(Path.home().name)
    for name in (socket.gethostname(), socket.getfqdn()):
        values.update(name.split('.')[:1] + [name])
    for email in git('config', '--get-all', 'user.email').split() + [os.environ.get('GIT_AUTHOR_EMAIL', '')]:
        if email and not email.endswith('@users.noreply.github.com'):
            values.add(email)
    return sorted(v for v in values if len(v) >= 3 and v not in {'root', 'runner', 'localhost', 'user'})


def private_patterns():
    rows = []
    gitdir = git('rev-parse', '--git-dir').strip() or '.git'
    for path in (Path(gitdir) / 'info' / 'personal-patterns',
                 Path.home() / '.config' / 'safe-c-environment' / 'personal-patterns'):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        rows += [line.strip() for line in lines if line.strip() and not line.lstrip().startswith('#')]
    return rows


def rules():
    compiled = [(name, re.compile(rx)) for name, rx in GENERIC.items()]
    compiled += [('local-identity', re.compile(r'(?<![A-Za-z0-9])' + re.escape(v) + r'(?![A-Za-z0-9])', re.I))
                 for v in local_values()]
    for rx in private_patterns():
        try:
            compiled.append(('private-pattern', re.compile(rx, re.I)))
        except re.error:
            print('personal-info-check: invalid private pattern ignored', file=sys.stderr)
    return compiled


def staged_lines():
    path, number = None, 0
    for line in git('diff', '--cached', '--no-color', '--no-ext-diff', '-U0', '--diff-filter=ACMR').splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('@@'):
            number = int(re.search(r'\+(\d+)', line).group(1)) - 1
        elif line.startswith('+') and path:
            number += 1
            yield path, number, line[1:]


def tree_lines():
    for path in git('ls-files', '-z').split('\0'):
        try:
            text = Path(path).read_text(errors='strict')
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            yield path, number, line


def identity_findings():
    findings = []
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        match = re.search(r'<([^>]*)>', git('var', role))
        email = match.group(1) if match else ''
        if not re.fullmatch(NOREPLY, email):
            findings.append(f'{role.split("_")[1].lower()}: identity-not-noreply ({mask(email) if email else "missing"})')
    return findings


def mask(value):
    return value[0] + '*' * (len(value) - 1) if len(value) > 1 else '*'


def scan(lines):
    active, findings = rules(), []
    for path, number, line in lines:
        if path == SELF:
            continue
        for name, rx in active:
            if name in VENDORED_RULES and path.startswith(VENDORED):
                continue
            match = rx.search(line)
            if match:
                findings.append(f'{path}:{number}: {name} ({mask(match.group(0))})')
    return findings


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--staged', action='store_true', help='check added lines in the index (default)')
    mode.add_argument('--tree', action='store_true', help='check every tracked file')
    mode.add_argument('--message', metavar='FILE', help='check a commit message file')
    args = parser.parse_args()
    if args.tree:
        findings = scan(tree_lines())
    elif args.message:
        text = Path(args.message).read_text(errors='replace')
        findings = scan(('COMMIT_MSG', n, l) for n, l in enumerate(text.splitlines(), 1) if not l.startswith('#'))
    else:
        findings = identity_findings() + scan(staged_lines())
    for row in findings[:200]:
        print(f'personal-info-check: {row}', file=sys.stderr)
    if findings:
        print(f'personal-info-check: BLOCKED, {len(findings)} finding(s). Remove the values; '
              'do not bypass with --no-verify.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
