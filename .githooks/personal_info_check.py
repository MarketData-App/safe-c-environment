#!/usr/bin/env python3
"""Block commits, tags and pushes that add personal information or credentials.

Personal values are never stored in this repository. They are derived on the
committing machine (login name, home path, host name, non-noreply Git emails)
and read from untracked private pattern files, one regular expression per line:
  <git common dir>/info/personal-patterns
  ~/.config/safe-c-environment/personal-patterns
Private path patterns (personal-path-patterns in the same two places) match
only the base name of each added or changed path, never content, so a tracked
document that mentions a name is not blocked (finding private-path-pattern,
with the path masked). Residuals of the path rule: it matches the exact base
name only (case-insensitive), so a renamed copy, an extra suffix (such as
.bak) and a directory of that name pass, and the file content is not
detected; archive member names go to the content rules only, never to the
path patterns (every first-party archive is a finding anyway); and --tree
does not apply path patterns (--staged, --push and --history do). The primary
control for a private fixture file remains its git-ignore rule and its use
inside the containers only.
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
the same revision binds that path to that sha256. Content of a file under
<project>/benchmarks/project/third_party/, where <project> is a project root of
the same revision (the repository root or examples/<name>/, with a project.json
there), is exempt only when the protected
project lock there (third_party/lock.json) of the same revision binds that exact
path to its sha256 and size in a row whose origin URL is on the upstream
allowlist (UPSTREAM_URL: PyPI files, GitHub release downloads and archives, Boost
release archives; the lock schema holds the same list): under third_party/wheels/
only a part of a PyPI wheel row whose URL names the wheel file, elsewhere a source
part, a retained upstream file, or a provenance or notice record that binds its
size. The project lock itself is never exempt, and a path that it binds to other
bytes is a finding (project-lock-mismatch). A look-alike lock outside a project
root exempts nothing. A symlink entry under a project third_party area is a
finding (project-third-party-symlink) and is never exempt. Names are always checked and
first-party files get every rule. A first-party (unpinned) zip, tar (ustar, or a
pre-POSIX tar whose first header checksum validates), gzip, xz or bzip2 file is
itself a finding. A listed zip member whose local header disagrees with its
central record (method, flag bits 0 and 3, CRC-32 and sizes), or whose deflate
stream or data descriptor does not end where the central record says, is a
finding.

Threat model: these hooks and the privacy workflow guard against accidental
commits of personal data. They are not a defence against a deliberate committer
(client hooks can be bypassed). An archive crafted on purpose so that standard
tools parse it differently from Python's zipfile and tarfile is a documented
residual. Every lock exemption trusts the lock of the same revision, and exempt
content (also archive member names) is never searched: a commit that changes a
bound file together with its lock entry passes, so the review of each lock change
is the control (for a project lock, the approver of the protected
benchmarks/project/third_party/ directory). The upstream allowlist checks the
text of the origin URL only: the hook downloads nothing, so it cannot prove that
the bound bytes came from that URL, anyone can publish a GitHub release, and a
provenance or notice record that the project wrote itself is exempt when it is
bound in such a row. A project root is known by its path and its project.json
of the same revision only: a commit that adds examples/<name>/project.json and a
lock makes that directory a project root, and the approver of the protected
directory is again the control.

Findings print the path, line and category;
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
# EX1-A03, FW-HOOK (fact F14): a file under <project>/benchmarks/project/third_party/ is pinned only by the protected
# project lock of the same project at the same revision (Scanner.project_binding).
PROJECT_AREA = 'benchmarks/project/third_party/'
PROJECT_LOCK = 'benchmarks/project/third_party/lock.json'
PROJECT_LOCK_REL = 'third_party/lock.json'
PROJECT_WHEELS = 'third_party/wheels/'
# T4-A02: a project lock counts only in a project root of the same revision: the repository root or examples/<name>/,
# with a project.json there (a JSON object). T4-A04: a symlink entry under a project third_party area is a finding.
PROJECT_FILE = 'project.json'
EXAMPLE_ROOT = re.compile(r'examples/[^/]+/')
SYMLINK = '120000'
PYPI_URL = re.compile(r'https://files\.pythonhosted\.org/[A-Za-z0-9._/+%-]+')
# FW-HOOK: the upstream origins whose bound project files are exempt from the content rules: PyPI files, GitHub release
# downloads and archives, and Boost release archives (no '..' anywhere). schemas/project-third-party.json
# $defs.exempt_origin_url holds the same pattern (a unit test keeps both equal); a row of any other origin exempts nothing.
UPSTREAM_URL = re.compile(r'https://(?!.*\.\.)(?:files\.pythonhosted\.org/[A-Za-z0-9._/+%-]+'
                          r'|github\.com/[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*/(?:releases/download|archive)/'
                          r'[A-Za-z0-9._/+%~-]+|archives\.boost\.io/release/[A-Za-z0-9._/+%~-]+)')
WHEEL_PART_SUFFIX = re.compile(r'\.part-[0-9]{2}')


def wheel_part_name(name, filename):
    """EX1-R1-02: True when `name` is the wheel `filename` or `filename` plus the fixed part suffix .part-NN."""
    return name == filename or (name.startswith(filename) and WHEEL_PART_SUFFIX.fullmatch(name[len(filename):]) is not None)


def project_area(path):
    """FW-HOOK: (project prefix, path relative to benchmarks/project) of a file under <prefix>benchmarks/project/third_party/,
    the prefix empty or ending in '/'; None for any other path and for a path that names that area twice (a lock inside
    the third-party area of another project is no project lock)."""
    head, found, tail = path.partition(PROJECT_AREA)
    if not found or (head and not head.endswith('/')) or not tail or PROJECT_AREA in tail:
        return None
    return head, 'third_party/' + tail


def project_root(head):
    """T4-A02: True for the prefix of a project root: the repository root ('') or examples/<name>/."""
    return head == '' or EXAMPLE_ROOT.fullmatch(head) is not None


def project_refs(value):
    """FW-HOOK: (row key, row, role, reference) of every file that a project lock binds: the parts and files of each
    wheel, source and retained row, and its provenance and notice record."""
    for key in ('wheels', 'sources', 'retained'):
        rows = value.get(key)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            for role in ('parts', 'files'):
                refs = row.get(role)
                for ref in refs if isinstance(refs, list) else []:
                    if isinstance(ref, dict):
                        yield key, row, role, ref
            for role in ('provenance', 'notice'):
                if isinstance(row.get(role), dict):
                    yield key, row, role, row[role]


def same_bytes(ref, digest, size, sized):
    """True when a lock reference binds these bytes: its sha256, and its size (required when `sized`, else checked when
    the reference has one; an integer only)."""
    if sized or 'bytes' in ref:
        if type(ref.get('bytes')) is not int or ref['bytes'] != size:
            return False
    return ref.get('sha256') == digest


def pypi_wheel(row):
    """EX1-A03, EX1-R1-02: a wheel row with origin kind pypi whose files.pythonhosted.org URL ends with its filename, a .whl."""
    origin, filename = row.get('origin'), row.get('filename')
    return (isinstance(origin, dict) and origin.get('kind') == 'pypi' and isinstance(origin.get('url'), str)
            and PYPI_URL.fullmatch(origin['url']) is not None and isinstance(filename, str) and bool(filename)
            and origin['url'].endswith('/' + filename) and filename.endswith('.whl'))


def upstream_row(key, row):
    """FW-HOOK: True when a lock row (key wheels, sources or retained) has an allowlisted upstream origin: a wheel row only
    as a PyPI wheel (pypi_wheel); another row with origin kind upstream-archive and an UPSTREAM_URL, or kind pypi and a
    files.pythonhosted.org URL on that list (a source row: the URL ends with its filename)."""
    if key == 'wheels':
        return pypi_wheel(row)
    origin = row.get('origin')
    if not isinstance(origin, dict) or not isinstance(origin.get('url'), str) or UPSTREAM_URL.fullmatch(origin['url']) is None:
        return False
    if origin.get('kind') == 'pypi':
        filename = row.get('filename')
        return PYPI_URL.fullmatch(origin['url']) is not None and (key != 'sources' or (
            isinstance(filename, str) and bool(filename) and origin['url'].endswith('/' + filename)))
    return origin.get('kind') == 'upstream-archive'


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


OCTAL_FIELD = re.compile(rb'[ \0]*[0-7]+[ \0]*')


def tar_header(data):
    """True for a ustar header or a pre-POSIX (v7) tar header at offset 0: the checksum
    field validates under the unsigned or the signed sum convention, the name starts
    with a printable byte, and the mode and size fields hold octal digits (or a
    base-256 size)."""
    if data[257:262] == b'ustar':
        return True
    if len(data) < 512:
        return False
    block = data[:512]
    name = block[:100].split(b'\0', 1)[0]
    if not name or any(byte < 0x20 or byte > 0x7e for byte in name):
        return False
    if not OCTAL_FIELD.fullmatch(block[100:108]) or not OCTAL_FIELD.fullmatch(block[148:156]):
        return False
    if not (OCTAL_FIELD.fullmatch(block[124:136]) or block[124] & 0x80):
        return False
    stored = int(block[148:156].strip(b' \0'), 8)
    blank = block[:148] + b' ' * 8 + block[156:]
    return stored in (sum(blank), sum(byte - 256 if byte > 127 else byte for byte in blank))


def archive_like(data):
    return (data[:2] == GZIP or data[:6] == XZ or is_bzip2(data) or data[:4] == b'PK\x03\x04'
            or b'PK\x05\x06' in data[-65558:] or tar_header(data))


def zip_header_mismatch(data, info):
    """True when the local header of a listed zip member disagrees with its central
    record: method, flag bits 0 and 3, and (bit 3 clear) CRC-32 and both sizes."""
    at = info.header_offset
    local = data[at:at + 30]
    if len(local) < 30 or local[:4] != b'PK\x03\x04':
        return True
    flags, method = int.from_bytes(local[6:8], 'little'), int.from_bytes(local[8:10], 'little')
    if method != info.compress_type or (flags ^ info.flag_bits) & 0x9:
        return True
    if flags & 8:
        return False
    crc, csize, usize = (int.from_bytes(local[i:i + 4], 'little') for i in (14, 18, 22))
    if 0xFFFFFFFF in (csize, usize):
        name = int.from_bytes(local[26:28], 'little')
        extra = data[at + 30 + name:at + 30 + name + int.from_bytes(local[28:30], 'little')]
        while len(extra) >= 4 and int.from_bytes(extra[:2], 'little') != 1:
            extra = extra[4 + int.from_bytes(extra[2:4], 'little'):]
        if len(extra) < 20:
            return True
        usize, csize = int.from_bytes(extra[4:12], 'little'), int.from_bytes(extra[12:20], 'little')
    return (crc, csize, usize) != (info.CRC, info.compress_size, info.file_size)


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


def zip_extent_mismatch(data, info, state):
    """True when a listed member's data does not end where its central record says:
    a deflated stream must end exactly at compress_size bytes after the real data
    start, and a member with flag bit 3 must be followed by a data descriptor (with
    or without signature, 4- or 8-byte sizes) that repeats the central CRC and sizes.
    Inflated output is discarded but counted against a finite bound."""
    at = info.header_offset
    local = data[at:at + 30]
    if len(local) < 30:
        return True
    start = at + 30 + int.from_bytes(local[26:28], 'little') + int.from_bytes(local[28:30], 'little')
    end = start + info.compress_size
    if end > len(data):
        return True
    if info.compress_type == zipfile.ZIP_DEFLATED:
        engine, pending, total = zlib.decompressobj(-zlib.MAX_WBITS), data[start:end], 0
        try:
            while pending and not engine.eof:
                total += len(engine.decompress(pending, CHUNK * 16))
                pending = engine.unconsumed_tail
                if total > DECOMPRESSED_LIMIT:
                    raise BudgetExceeded('zip member stream exceeds the finite limit')
        except zlib.error:
            return True
        if not engine.eof or engine.unused_data or pending:
            return True
    if info.flag_bits & 8:
        tail = data[end:end + 28]
        if tail[:4] == b'PK\x07\x08':
            tail = tail[4:]
        expected = info.CRC.to_bytes(4, 'little')
        short = expected + info.compress_size.to_bytes(4, 'little') + info.file_size.to_bytes(4, 'little') \
            if max(info.compress_size, info.file_size) < 1 << 32 else None
        wide = expected + info.compress_size.to_bytes(8, 'little') + info.file_size.to_bytes(8, 'little')
        if not ((short and tail[:12] == short) or tail[:20] == wide):
            return True
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
                if any(zip_header_mismatch(data, info) or zip_extent_mismatch(data, info, state)
                       for info in members[:MEMBER_CAP]):
                    state.problems.append('zip-header-mismatch')
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
    if len(data) >= 512 and (tar_header(data) or len(data) % 512 == 0):
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
            if tar_header(data):
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


def path_rules(errors=None):
    """Private path patterns: one regular expression per line, matched against the
    base name of an added or changed path only (never content). An unreadable file
    or an invalid line is an error line in `errors`, as for content patterns."""
    errors = [] if errors is None else errors
    compiled = []
    common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir').strip())
    for path in (common / 'info' / 'personal-path-patterns',
                 Path.home() / '.config' / 'safe-c-environment' / 'personal-path-patterns'):
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            errors.append(f'{path.name}: unreadable-private-path-patterns')
            continue
        for number, line in enumerate(lines, 1):
            if line.strip() and not line.lstrip().startswith('#'):
                try:
                    compiled.append(re.compile(line.strip(), re.I))
                except re.error:
                    errors.append(f'{path.name}:{number}: invalid-private-path-pattern')
    return compiled


def mask(value):
    return value[0] + '*' * (len(value) - 1) if len(value) > 1 else '*'


LOCK_MAX_BYTES = 64 * 1024 * 1024


def read_at(rev, path):
    """The bytes of `path` at rev (None: the working tree, a regular file only; ':' the index; else a commit or tree),
    or b'' when it is absent."""
    if rev is None:
        candidate = Path(path)
        return candidate.read_bytes() if candidate.is_file() and not candidate.is_symlink() else b''
    return git('cat-file', 'blob', f':{path}' if rev == ':' else f'{rev}:{path}', binary=True, check=False)


def lock_json(raw):
    """A lock file through a capped parse (FR3-22): at most LOCK_MAX_BYTES bytes; a malformed, too deep or too large
    document gives None (no pins, so more digests stay findings), never an exception that stops the hook."""
    if len(raw) > LOCK_MAX_BYTES:
        return None
    try:
        return json.loads(raw)
    except (ValueError, RecursionError, MemoryError):
        return None


class Scanner:
    def __init__(self):
        self.rules, self.findings, self.raw = rules()
        self.path_rules = path_rules(self.findings)
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
                value = lock_json(raw) if raw else None
                stack = [value] if value is not None else []
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

    def project_binding(self, path, data, rev):
        """EX1-A03, FW-HOOK (fact F14): (pinned, mismatch) of a file under <project>/benchmarks/project/third_party/,
        judged only against the project lock <project>/benchmarks/project/third_party/lock.json of the same rev (None the
        working tree, ':' the index, else a commit or tree), so a lock edit in the same commit decides for that commit.
        pinned (the content is exempt): under third_party/wheels/ only a part of a PyPI wheel row (EX1-A03, EX1-R1-02:
        origin kind pypi, a files.pythonhosted.org URL that ends with the row filename, a .whl; the part file name is that
        filename or that filename plus the split-part suffix .part-NN) with this exact path (relative to benchmarks/project),
        sha256 and size; any other path only as a part, a retained file, or a provenance or notice record with this exact
        path, sha256 and size (a record without its size is not exempt) of a row whose origin is upstream (upstream_row).
        The lock itself, a nested project area and every other file are never pinned.
        T4-A02: the lock counts only in a project root (project_root: the repository root or examples/<name>/) that holds
        project.json (a JSON object) at the same rev; a look-alike lock anywhere else gives (False, False).
        mismatch (the finding project-lock-mismatch): the lock binds this path, but no binding has these bytes (sha256,
        and the size where one is bound)."""
        area = project_area(path)
        if area is None or area[1] == PROJECT_LOCK_REL or not project_root(area[0]):
            return False, False
        value = lock_json(read_at(rev, area[0] + PROJECT_LOCK) or b'')
        if not isinstance(value, dict):
            return False, False
        rel, digest, size = area[1], hashlib.sha256(data).hexdigest(), len(data)
        bound = [(key, row, role, ref) for key, row, role, ref in project_refs(value) if ref.get('path') == rel]
        if not bound or not isinstance(lock_json(read_at(rev, area[0] + PROJECT_FILE) or b''), dict):
            return False, False
        mismatch = bool(bound) and not any(same_bytes(ref, digest, size, False) for _, _, _, ref in bound)
        if rel.startswith(PROJECT_WHEELS):
            leaf = rel[len(PROJECT_WHEELS):]
            pinned = '/' not in leaf and any(
                key == 'wheels' and role == 'parts' and pypi_wheel(row) and wheel_part_name(leaf, row['filename'])
                and same_bytes(ref, digest, size, True) for key, row, role, ref in bound)
        else:
            pinned = any(not (key == 'wheels' and role == 'parts') and upstream_row(key, row)
                         and same_bytes(ref, digest, size, True) for key, row, role, ref in bound)
        return pinned, mismatch

    def project_pinned(self, path, data, rev):
        """EX1-A03, FW-HOOK: True when the content of `path` is exempt through its project lock (project_binding)."""
        return self.project_binding(path, data, rev)[0]

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

    def content(self, label, path, data, rev, mode=None):
        self.name(label, path)
        if mode == SYMLINK and project_area(path) is not None:
            # T4-A04: a symlink entry under a project third_party area is a finding and is never exempt (the project tool
            # refuses links there); its link text gets every content rule below.
            self.findings.append(f'{label}: project-third-party-symlink')
        else:
            upstream = path.startswith(VENDORED) or path.endswith(UPSTREAM_ARCHIVES)
            if upstream and (path, hashlib.sha256(data).hexdigest()) in self.pinned(rev):
                return
            pinned, mismatch = self.project_binding(path, data, rev)
            if mismatch:
                self.findings.append(f'{label}: project-lock-mismatch')
            if pinned:
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

    def blob(self, label, path, rev, mode=None):
        spec = f':{path}' if rev == ':' else f'{rev}:{path}'
        # Staged, committed and tagged paths: the base name against the private path
        # patterns before the content scan; a match masks the path in every label.
        if any(rx.search(path.rsplit('/', 1)[-1]) for rx in self.path_rules):
            label = label[:len(label) - len(path)] + mask(path) if label.endswith(path) else mask(label)
            self.findings.append(f'{label}: private-path-pattern')
        self.content(label, path, git('cat-file', 'blob', spec, binary=True), rev, mode)

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
        modes = changed(listing)
        for path in sorted(modes):
            self.blob(f'{label}:{path}', path, sha, modes[path])

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
                    self.blob(f'tagged-tree {obj[:12]}:{path}', path, obj, meta.split()[0])
        return obj


def staged(scanner):
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        match = re.search(r'^(.*) <([^>]*)>', git('var', role))
        scanner.identity('index', role.split('_')[1].lower(), match.group(2) if match else '',
                         match.group(1) if match else '')
    listing = git('diff', '--cached', '-z', '--raw', '--diff-filter=ACMRT', '--no-renames')
    modes = changed(listing)
    for path in sorted(modes):
        scanner.blob(path, path, ':', modes[path])


def changed(listing):
    """{path: new mode} of a -z --raw listing, without submodule (gitlink) entries."""
    fields, paths, index = listing.split('\0'), {}, 0
    while index + 1 < len(fields):
        meta, path = fields[index], fields[index + 1]
        if not meta.startswith(':'):
            raise ValueError('unexpected raw listing record')
        if meta.split()[1] != GITLINK:
            paths[path] = meta.split()[1]
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
                    scanner.content(path, path, Path(path).read_bytes(), None, meta.split()[0])
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
