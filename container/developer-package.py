"""Offline package-data extraction; execute only in the protected Docker job.

No package scripts run. This is candidate acquisition tooling, not acceptance.
Debian archive/package notices remain with the resulting development payload.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import subprocess
import tarfile

INPUTS = Path('/inputs')
WORK = Path('/work/developer-acquisition')
MAX_FILES = 4096
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_name(name):
    while name.startswith('./'):
        name = name[2:]
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(c in name for c in '\0\n\r'):
        raise ValueError('unsafe package path')
    return str(path)


def included(name):
    return (name in {'usr/bin/gdb', 'usr/bin/clangd-19'} or
            name.startswith(('usr/lib/', 'usr/share/gdb/', 'usr/share/doc/',
                             'usr/share/source-highlight/')))


def main():
    selection = json.loads((INPUTS / 'selection.json').read_text())
    packages = {p['Package']: p for p in selection['packages']}
    if len(packages) != len(selection['packages']) or not {'gdb', 'clangd-19'} <= set(packages):
        raise ValueError('package selection incomplete or duplicate')
    for edge in selection['dependencies']:
        target = (selection['base_packages'][edge['name']]['version']
                  if edge['resolution'] == 'existing-base' else packages[edge['name']]['Version'])
        if edge['operator']:
            checked = subprocess.run(['dpkg', '--compare-versions', target,
                                      edge['operator'], edge['version']], check=False,
                                     capture_output=True, timeout=5)
            if checked.returncode:
                raise ValueError('unsatisfied pinned dependency')
    WORK.mkdir()
    extracted = WORK / 'extracted'
    extracted.mkdir()
    owners, links, total = {}, {}, 0
    for package in packages.values():
        archive = INPUTS / PurePosixPath(package['Filename']).name
        if (archive.stat().st_size != int(package['Size']) or
                digest(archive) != package['SHA256']):
            raise ValueError('package identity mismatch')
        error_path = WORK / (package['Package'] + '.extract.opaque.log')
        with error_path.open('wb') as error:
            process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(archive)],
                                       stdout=subprocess.PIPE, stderr=error)
            try:
                with tarfile.open(fileobj=process.stdout, mode='r|') as source:
                    for member in source:
                        name = safe_name(member.name)
                        if member.isdir():
                            continue
                        if not (member.isfile() or member.issym() or member.islnk()):
                            raise ValueError('special package member')
                        if member.mode & 0o6000 or member.size > MAX_FILE:
                            raise ValueError('package mode or file bound')
                        if name in owners:
                            raise ValueError('duplicate package member')
                        owners[name] = package['Package']
                        if len(owners) > MAX_FILES:
                            raise ValueError('package file inventory bound')
                        if not included(name):
                            continue
                        destination = extracted / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if member.isfile():
                            total += member.size
                            if total > MAX_BYTES:
                                raise ValueError('package total byte bound')
                            data = source.extractfile(member).read(MAX_FILE + 1)
                            if len(data) != member.size:
                                raise ValueError('package short read')
                            destination.write_bytes(data)
                            destination.chmod(0o555 if member.mode & 0o111 else 0o444)
                        else:
                            target = (PurePosixPath(member.linkname) if member.islnk()
                                      else PurePosixPath(name).parent / member.linkname)
                            # Normalize relative aliases without creating links.
                            parts = []
                            if target.is_absolute():
                                raise ValueError('absolute package link')
                            for part in target.parts:
                                if part == '..':
                                    if not parts:
                                        raise ValueError('escaping package link')
                                    parts.pop()
                                elif part != '.':
                                    parts.append(part)
                            resolved = '/'.join(parts)
                            if not resolved.startswith('usr/'):
                                raise ValueError('external package link')
                            links[name] = resolved
                if process.wait(timeout=10):
                    raise ValueError('package extraction failed')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
    aliases = []
    for name in links:
        target = links[name]
        visited = {name}
        while target in links:
            if target in visited:
                raise ValueError('package link cycle')
            visited.add(target)
            target = links[target]
        origin = extracted / target
        if not origin.exists():
            origin = Path('/') / target
        if origin.is_dir():
            if not name.startswith('usr/share/doc/') or not target.startswith('usr/share/doc/'):
                raise ValueError('non-documentation directory alias')
            notice = (origin / 'copyright').resolve()
            if not (notice.is_relative_to(extracted / 'usr/share/doc') or
                    notice.is_relative_to('/usr/share/doc')):
                raise ValueError('external directory notice')
            if not notice.is_file() or notice.stat().st_size > MAX_FILE:
                raise ValueError('directory alias notice missing')
            data = notice.read_bytes()
            total += len(data)
            if total > MAX_BYTES or len(owners) >= MAX_FILES:
                raise ValueError('directory alias collection bound')
            destination = extracted / name / 'copyright'
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o444)
            owners[name + '/copyright'] = owners[name]
            aliases.append({'path': name, 'target': target, 'kind': 'notice-only-directory',
                            'sha256': digest(destination)})
            continue
        if not origin.is_file() or origin.stat().st_size > MAX_FILE:
            (WORK / 'rejected-alias.json').write_text(json.dumps(
                {'path': name, 'target': target, 'package': owners[name]}))
            raise ValueError('package alias target missing or oversized: ' + name + ' -> ' + target)
        data = origin.read_bytes()
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError('normalized package byte bound')
        destination = extracted / name
        destination.write_bytes(data)
        destination.chmod(0o555 if os.access(origin, os.X_OK) else 0o444)
        aliases.append({'path': name, 'target': target, 'sha256': digest(destination)})
    layer, identical = {}, []
    for path in sorted(extracted.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(extracted).as_posix()
        base = Path('/') / name
        if base.exists() or base.is_symlink():
            if not base.is_file() or digest(base) != digest(path):
                raise ValueError('development layer would change existing base bytes')
            identical.append(name)
            continue
        layer[name] = {'sha256': digest(path), 'bytes': path.stat().st_size,
                       'mode': path.stat().st_mode & 0o777, 'package': owners[name]}
    notices = {}
    for package in packages:
        path = extracted / 'usr/share/doc' / package / 'copyright'
        if not path.is_file():
            raise ValueError('package notice unavailable')
        notices[package] = {'path': path.relative_to(extracted).as_posix(),
                            'sha256': digest(path)}
    groups, current, size = [], [], 0
    for name, record in layer.items():
        if current and size + record['bytes'] > 16 * 1024 * 1024:
            groups.append(current)
            current, size = [], 0
        current.append(name)
        size += record['bytes']
    if current:
        groups.append(current)
    archives = []
    for number, names in enumerate(groups):
        archive = WORK / ('development-layer-' + str(number) + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as target:
            for name in names:
                target.add(extracted / name, arcname=name, recursive=False)
        if archive.stat().st_size > MAX_FILE:
            raise ValueError('development archive collection bound')
        archives.append({'name': archive.name, 'files': names,
                         'sha256': digest(archive), 'bytes': archive.stat().st_size})
    row = {'status': 'CANDIDATE_DATA_EXTRACTED', 'files': layer,
           'notices': notices, 'normalized_aliases': aliases,
           'identical_base_files_omitted': identical,
           'archives': archives,
           'package_scripts_executed': False,
           'independent_approval': 'PENDING'}
    (WORK / 'manifest.json').write_text(json.dumps(row, indent=2) + '\n')
    print(json.dumps({'status': row['status'], 'files': len(layer),
                      'packages': len(packages), 'archives': len(archives),
                      'archive_bytes': sum(r['bytes'] for r in archives)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1]
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__,
                          'property': str(error) if isinstance(error, ValueError) else None,
                          'errno': getattr(error, 'errno', None),
                          'location': {'file': Path(frame.filename).name, 'line': frame.lineno}}))
        raise SystemExit(1)
