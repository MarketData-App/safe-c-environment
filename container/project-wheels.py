"""EX-1: offline extraction of a project's pinned wheels; execute only in the protected Docker job (dependency-build).

/inputs holds lock.json (the project's checked third-party lock), every wheel part under its base name, and each
first-party fixture wheel (built by the host from its tracked source) under its filename. The job joins
the parts, checks each sha256, and extracts each wheel as data: no wheel code runs and no installer runs. Output under
/work/project-wheels: manifest.json, layer-N.tar.gz chunks (members under opt/project-python/) and notices/<name>/<file>
(the license file of each wheel's dist-info directory). tools/project_image.py verifies every byte again on the host.
EX1-A02 (a): manifest `elf_files` maps every extracted file that starts with the ELF magic bytes (an extension module, a
bundled library in <name>.libs/, an ELF program) to its wheel name; the host checks it against the layer bytes. That native
code stays outside every first-party build, analyzer, sanitizer and fuzz profile (tools/project_source.py wheel_path_hits).
T6-R2 (ruling R27), host members: a member above MAX_FILE (the container file bound) is refused unless the lock row of its
wheel declares it in `host_members` (member path, bytes, sha256; at most MAX_HOST_MEMBERS per wheel, each at most
MAX_HOST_MEMBER bytes). A declared member is read in READ_CHUNK pieces and hashed; it is never written here, so no file of
this job passes the file bound. Its size and sha256 must equal the declaration. It counts in the layer byte and file bounds
as a written file, the manifest lists it under `host_members` (not under `files` or in an archive), and `elf_files` lists
it when its first bytes are the ELF magic. The trusted host (tools/project_image.py) streams it from the verified wheel
bytes into the layer.
T6-R3 (ruling R33): a wheel data directory `<dist>.data` (its name as the dist-info rule: the lock name and version,
compared without case) may hold the scheme DATA_SCHEME only. Its files are no import files: they are not extracted, do
not count in the layer bounds, and the manifest counts them per wheel (`data_files`). Every member bound still applies
to them (entry count, path safety, special type, MAX_FILE). Any other scheme or entry of a data directory is refused. A
data directory is never a module. A lock row may declare `notice_member`, the exact member path of its license file (in
its dist-info directory or below `<dist>.data/data/`): the job then reads exactly that member (once in the zip, a regular
file, at most MAX_NOTICE bytes) as the notice; without it, the dist-info search stays (notice)."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import re
import stat
import tarfile
import zipfile

INPUTS = Path('/inputs')
WORK = Path('/work/project-wheels')
LAYER_ROOT = 'opt/project-python/'
MAX_FILE = 32 * 1024 * 1024          # one file (the container file bound)
MAX_WHEEL = 64 * 1024 * 1024         # one whole wheel
MAX_BYTES = 192 * 1024 * 1024        # the extracted layer (tools/project_third_party.py LAYER_MAX_BYTES)
MAX_FILES = 3072                     # tools/project_third_party.py LAYER_MAX_FILES
MAX_MEMBERS = 8192                   # zip entries of one wheel, excluded entries included
MAX_HOST_MEMBER = 48 * 1024 * 1024   # T6-R2: one declared host member (tools/project_third_party.py HOST_MEMBER_MAX_BYTES)
MAX_HOST_MEMBERS = 4                 # T6-R2: declared host members of one wheel (tools/project_third_party.py HOST_MEMBERS_MAX)
READ_CHUNK = 1024 * 1024             # T6-R2: one read of a host member while it is hashed
MAX_NOTICE = 1024 * 1024             # T6-R3: one declared notice member (tools/project_third_party.py RECORD_MAX_BYTES)
DATA_SCHEME = 'data'                 # T6-R3: the one admitted scheme of a wheel data directory (<dist>.data/data/)
CHUNK = 16 * 1024 * 1024
ELF_MAGIC = b'\x7fELF'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def escape(name):
    return re.sub(r'[^A-Za-z0-9.]+', '_', name)


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or name.startswith('/') or '\\' in name or path.is_absolute() or '..' in path.parts or
            '.' in name.split('/') or any(c in name for c in '\0\n\r')):
        raise ValueError('unsafe wheel member path')
    return str(path)


def member_included(name):
    parts = PurePosixPath(name).parts
    return not ('tests' in parts[1:] or '__pycache__' in parts or name.endswith('.pyc'))


def top_module(top):
    """The import name of a top-level wheel entry: a package directory, a .py module or an extension module."""
    return top.split('.')[0]


def declared_members(wheel):
    """T6-R2: {member path: declaration} of the host members that the lock row of `wheel` declares."""
    rows = wheel.get('host_members', [])
    if len(rows) > MAX_HOST_MEMBERS:
        raise ValueError('host member count bound')
    declared = {}
    for row in rows:
        if row['member'] in declared:
            raise ValueError('duplicate host member')
        declared[row['member']] = row
    return declared


def hash_member(source, info, declaration):
    """T6-R2: (sha256, first 4 bytes) of one declared member, read in READ_CHUNK pieces and never written. ValueError when its
    size or sha256 differs from the declaration."""
    hasher, count, head = hashlib.sha256(), 0, b''
    with source.open(info) as member:
        while True:
            chunk = member.read(READ_CHUNK)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_HOST_MEMBER:
                raise ValueError('host member bound')
            if count > info.file_size:
                raise ValueError('host member identity mismatch')
            if len(head) < 4:
                head += chunk[:4 - len(head)]
            hasher.update(chunk)
    if count != info.file_size or count != declaration['bytes'] or hasher.hexdigest() != declaration['sha256']:
        raise ValueError('host member identity mismatch')
    return hasher.hexdigest(), head


def data_entry(parts, is_dir, expected):
    """T6-R3: True for an entry of the wheel data directory (path segments `parts`), after its checks: the directory name
    is `expected` (without case), and the entry is the directory itself, the directory of DATA_SCHEME, or below it."""
    if not parts[0].endswith('.data'):
        return False
    if parts[0].lower() != expected:
        raise ValueError('wheel data directory name differs from the lock')
    if not ((len(parts) == 1 and is_dir) or (len(parts) >= 2 and parts[1] == DATA_SCHEME and (len(parts) > 2 or is_dir))):
        raise ValueError('wheel data directory scheme is not supported')
    return True


def notice_place(member, dist_info, data_dir):
    """T6-R3: a declared notice member lies below the dist-info directory or below `<dist>.data/data/` (names without case)."""
    head, _, rest = member.partition('/')
    if not rest or not (head.lower() == dist_info or (head.lower() == data_dir and rest.startswith(DATA_SCHEME + '/'))):
        raise ValueError('wheel notice member outside the dist-info and data directories')


def extract(data, wheel, extracted, owners, total, hosts=None):
    """Extracts one wheel into extracted/LAYER_ROOT; returns (new total, dist-info name, declared notice bytes or None,
    data files). T6-R2: records each declared host member in `hosts` (layer path: name, wheel, bytes, sha256, mode, elf)
    instead of writing it. T6-R3: leaves the files of the wheel data directory out (data_entry) and reads a declared notice
    member (notice_member)."""
    hosts = {} if hosts is None else hosts
    declared, found = declared_members(wheel), set()
    tops = set()
    stem = escape(wheel['name']) + '-' + wheel['version']
    data_dir, notice_name, notice_body, data_files = (stem + '.data').lower(), wheel.get('notice_member'), None, 0
    if notice_name is not None:
        notice_place(notice_name, (stem + '.dist-info').lower(), data_dir)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        infos = source.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError('wheel member count bound')
        for info in infos:
            name = safe_name(info.filename.rstrip('/') if info.is_dir() else info.filename)
            parts = name.split('/')
            tops.add(parts[0])
            in_data = data_entry(parts, info.is_dir(), data_dir)
            if info.is_dir():
                if name == notice_name:
                    raise ValueError('wheel notice member is a directory')
                continue
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or mode & 0o6000:
                raise ValueError('special wheel member')
            if name == notice_name:          # T6-R3: exactly the declared member, a bounded read
                if notice_body is not None:
                    raise ValueError('wheel notice member twice')
                if info.file_size > MAX_NOTICE:
                    raise ValueError('wheel notice member bound')
                with source.open(info) as member:
                    notice_body = member.read(MAX_NOTICE + 1)
                if len(notice_body) != info.file_size:
                    raise ValueError('wheel short read')
            if in_data:                      # T6-R3: no import file: bounded and counted, never extracted
                if name in declared:
                    raise ValueError('host member missing')
                if info.file_size > MAX_FILE:
                    raise ValueError('wheel file bound')
                data_files += 1
                continue
            if name in declared:
                if info.file_size <= MAX_FILE:
                    raise ValueError('host member not oversized')
                if info.file_size > MAX_HOST_MEMBER:
                    raise ValueError('host member bound')
            elif info.file_size > MAX_FILE:
                raise ValueError('wheel file bound')
            if not member_included(name):
                if name in declared:
                    raise ValueError('host member missing')
                continue
            target = LAYER_ROOT + name
            if target in owners:
                raise ValueError('duplicate wheel member')
            owners[target] = wheel['name']
            total += info.file_size
            if total > MAX_BYTES or len(owners) > MAX_FILES:
                raise ValueError('project layer bound')
            if name in declared:            # T6-R2: hashed in bounded chunks; this job never writes it
                sha256, head = hash_member(source, info, declared[name])
                hosts[target] = {'name': name, 'wheel': wheel['name'], 'bytes': info.file_size, 'sha256': sha256,
                                 'mode': 0o555 if mode & 0o111 else 0o444, 'elf': head == ELF_MAGIC}
                found.add(name)
                continue
            with source.open(info) as member:
                body = member.read(MAX_FILE + 1)
            if len(body) != info.file_size:
                raise ValueError('wheel short read')
            destination = extracted / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            destination.chmod(0o555 if mode & 0o111 else 0o444)
    if set(declared) - found:
        raise ValueError('host member missing')
    if notice_name is not None and notice_body is None:
        raise ValueError('wheel notice member missing')
    expected = stem + '.dist-info'
    infos = sorted(t for t in tops if t.endswith('.dist-info'))
    if [t.lower() for t in infos] != [expected.lower()]:
        raise ValueError('wheel dist-info name differs from the lock')
    modules = {top_module(t) for t in tops if not t.endswith(('.dist-info', '.libs', '.data'))}    # T6-R3: never .data
    if modules != set(wheel['modules']):
        raise ValueError('wheel top-level modules differ from the lock')
    return total, infos[0], notice_body, data_files


def notice(extracted, info):
    for path in sorted((extracted / LAYER_ROOT / info).rglob('*')):
        if path.is_file() and path.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING')):
            return path
    raise ValueError('wheel notice unavailable')


def main():
    lock = json.loads((INPUTS / 'lock.json').read_text())
    WORK.mkdir()
    extracted = WORK / 'extracted'
    extracted.mkdir()
    owners, total, dist_info, notices, hosts, data_files = {}, 0, [], {}, {}, {}
    for wheel in lock['wheels']:
        data = b''
        if not wheel['parts']:           # a first-party fixture wheel: the host built it from its tracked source
            data = (INPUTS / PurePosixPath(wheel['filename']).name).read_bytes()
        for part in wheel['parts']:
            piece = INPUTS / PurePosixPath(part['path']).name
            body = piece.read_bytes()
            if len(body) != part['bytes'] or len(body) > MAX_FILE or digest(body) != part['sha256']:
                raise ValueError('wheel part identity mismatch')
            data += body
        if len(data) != wheel['bytes'] or len(data) > MAX_WHEEL or digest(data) != wheel['sha256']:
            raise ValueError('wheel identity mismatch')
        total, info, declared_notice, data_files[wheel['name']] = extract(data, wheel, extracted, owners, total, hosts)
        dist_info.append(info)
        if declared_notice is None:      # the dist-info search (unchanged)
            path = notice(extracted, info)
            body, where, leaf = path.read_bytes(), path.relative_to(extracted).as_posix(), path.name
        else:                            # T6-R3: the lock-declared notice member, read in extract
            body, where, leaf = declared_notice, wheel['notice_member'], PurePosixPath(wheel['notice_member']).name
        notices[wheel['name']] = {'path': where, 'sha256': digest(body), 'declared': declared_notice is not None}
        copy = WORK / 'notices' / wheel['name'] / leaf
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(body)
    files, elf_files = {}, {}
    for name in sorted(owners):
        if name in hosts:               # T6-R2: a host member, hashed in extract and never written here
            if hosts[name].pop('elf'):
                elf_files[name] = owners[name]
            continue
        body = (extracted / name).read_bytes()
        files[name] = {'sha256': digest(body), 'bytes': len(body), 'mode': (extracted / name).stat().st_mode & 0o777}
        if body[:4] == ELF_MAGIC:       # EX1-A02 (a): native code of the wheel, found by its bytes (never by its name)
            elf_files[name] = owners[name]
    groups, current, size = [], [], 0
    for name, record in files.items():
        if current and size + record['bytes'] > CHUNK:
            groups.append(current)
            current, size = [], 0
        current.append(name)
        size += record['bytes']
    if current:
        groups.append(current)
    archives = []
    for number, names in enumerate(groups):
        archive = WORK / ('layer-' + str(number) + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as target:
            for name in names:
                target.add(extracted / name, arcname=name, recursive=False)
        if archive.stat().st_size > MAX_FILE:
            raise ValueError('project layer archive bound')
        archives.append({'name': archive.name, 'files': names, 'sha256': digest(archive.read_bytes()),
                         'bytes': archive.stat().st_size})
    row = {'status': 'PROJECT_WHEELS_EXTRACTED', 'files': files, 'elf_files': elf_files, 'archives': archives, 'notices': notices,
           'host_members': hosts, 'data_files': data_files, 'dist_info': sorted(dist_info), 'payload_bytes': total,
           'payload_files': len(files) + len(hosts),
           'bounds': {'bytes': MAX_BYTES, 'files': MAX_FILES, 'file_bytes': MAX_FILE, 'wheel_bytes': MAX_WHEEL,
                      'host_member_bytes': MAX_HOST_MEMBER, 'host_members_per_wheel': MAX_HOST_MEMBERS},
           'wheel_code_executed': False}
    (WORK / 'manifest.json').write_text(json.dumps(row, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'status': row['status'], 'files': len(files), 'host_members': len(hosts), 'archives': len(archives),
                      'payload_bytes': total, 'wheels': len(lock['wheels'])}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__,
                          'property': str(error) if isinstance(error, ValueError) else None}))
        raise SystemExit(1)
