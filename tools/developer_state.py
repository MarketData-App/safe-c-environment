"""Bounded regular-file build state. Acceleration data never grants acceptance."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tarfile
import uuid

from evidence import GateError, atomic_json, file_hash, read_json

CHUNK_BYTES = 16 * 1024 * 1024


def safe_directory(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise GateError('developer state directory link rejected')


def members(archive, limits):
    rows = []
    total = 0
    seen = set()
    with tarfile.open(archive, 'r:gz') as stream:
        for item in stream:
            path = Path(item.name)
            if (not item.isfile() or path.is_absolute() or '..' in path.parts or
                    not path.parts or item.name in seen or item.mode & 0o7000 or
                    item.size > CHUNK_BYTES or '\0' in item.name):
                raise GateError('developer cache member rejected')
            seen.add(item.name)
            total += item.size
            if total > limits['retained_state_bytes'] or len(seen) > limits['retained_state_files']:
                raise GateError('developer cache inventory budget exceeded')
            rows.append((item.name, item.size))
    return rows


def restore(build, incoming, namespace, limits):
    manifest = read_json(incoming / 'manifest.json')
    if manifest.get('namespace') != namespace or manifest.get('schema_version') != 1:
        raise GateError('developer cache namespace mismatch')
    expected = manifest['files']
    if (not isinstance(expected, dict) or len(expected) > limits['retained_state_files'] or
            sum(r['bytes'] for r in expected.values()) > limits['retained_state_bytes']):
        raise GateError('developer state manifest exceeds bounds')
    seen = set()
    build.mkdir(parents=True, exist_ok=True)
    for row in manifest['archives']:
        path = incoming / row['path']
        if (not __import__('re').fullmatch(r'state-[0-9]{3}\.tar\.gz', row['path']) or
                path.is_symlink() or path.stat().st_size != row['bytes'] or
                file_hash(path) != row['sha256'] or row['bytes'] > CHUNK_BYTES + 65536):
            raise GateError('developer cache archive identity rejected')
        members(path, limits)
        with tarfile.open(path, 'r:gz') as stream:
            for item in stream:
                if item.name in seen or item.name not in expected:
                    raise GateError('developer cache duplicate or unknown file')
                seen.add(item.name)
                destination = build / item.name
                safe_directory(destination)
                data = stream.extractfile(item).read(item.size + 1)
                record = expected[item.name]
                if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise GateError('developer cached file identity rejected')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                destination.chmod(item.mode & 0o777)
                __import__('os').utime(destination, (item.mtime, item.mtime))
    if seen != set(expected):
        raise GateError('developer cache missing input file')
    return manifest


def pack(build, output, namespace, limits, source):
    output.mkdir(parents=True, exist_ok=True)
    inventory, groups, group = {}, [], []
    total, chunk, index_bytes = 0, 0, 0
    for path in sorted(build.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or mode & 0o7000:
            raise GateError('developer build state contains a link or special file')
        relative = str(path.relative_to(build))
        size = path.stat().st_size
        if size > CHUNK_BYTES:
            raise GateError('developer cached individual file exceeds finite chunk bound')
        total += size
        if '/.cache/' in '/' + relative:
            index_bytes += size
        if (total > limits['retained_state_bytes'] or len(inventory) >= limits['retained_state_files'] or
                index_bytes > limits['index_bytes']):
            raise GateError('developer retained state/index budget exceeded')
        if chunk + size + 2048 > CHUNK_BYTES and group:
            groups.append(group)
            group, chunk = [], 0
        group.append(path)
        chunk += size + 2048
        inventory[relative] = {'bytes': size, 'sha256': file_hash(path)}
    if group:
        groups.append(group)
    archives = []
    for number, group in enumerate(groups):
        path = output / ('state-%03d.tar.gz' % number)
        with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT) as stream:
            for entry in group:
                stream.add(entry, arcname=str(entry.relative_to(build)), recursive=False)
        archives.append({'path': path.name, 'bytes': path.stat().st_size, 'sha256': file_hash(path)})
    manifest = {'schema_version': 1, 'namespace': namespace, 'source_files': source,
                'files': inventory, 'archives': archives, 'bytes': total,
                'index_bytes': index_bytes, 'acceptance': False}
    atomic_json(output / 'manifest.json', manifest)
    return manifest


def stage(root, namespace, runner, limits):
    directory = root / 'artifacts/developer/state' / namespace
    safe_directory(directory)
    if not directory.exists():
        return False
    manifest = read_json(directory / 'manifest.json')
    if manifest.get('namespace') != namespace or manifest.get('acceptance') is not False:
        raise GateError('developer acceleration state namespace or scope rejected')
    rows = manifest.get('archives', [])
    if len(rows) > 32 or len(manifest.get('files', {})) > limits['retained_state_files']:
        raise GateError('developer state inventory bound rejected')
    for row in rows:
        path = directory / row['path']
        safe_directory(path)
        if (not __import__('re').fullmatch(r'state-[0-9]{3}\.tar\.gz', row['path']) or
                path.stat().st_size != row['bytes'] or row['bytes'] > CHUNK_BYTES + 65536 or
                file_hash(path) != row['sha256']):
            raise GateError('developer acceleration archive changed or missing')
        members(path, limits)
        private = runner.scratch / 'state-transfer' / row['path']
        private.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,private)
        runner.restore('developer-state-input/' + row['path'], private)
    private = runner.scratch / 'state-transfer/manifest.json'
    private.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(directory/'manifest.json',private)
    runner.restore('developer-state-input/manifest.json',private)
    return True


def retain(root, namespace, runner, native, limits):
    manifest = native.get('state')
    if not manifest or manifest.get('namespace') != namespace or manifest.get('acceptance') is not False:
        raise GateError('developer state output manifest missing or mismatched')
    directory = root / 'artifacts/developer/state' / namespace
    safe_directory(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = directory.parent / ('.stage-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        if len(manifest['archives']) > 32 or manifest['bytes'] > limits['retained_state_bytes']:
            raise GateError('developer retained state exceeds policy')
        for row in manifest['archives']:
            if not __import__('re').fullmatch(r'state-[0-9]{3}\.tar\.gz', row['path']):
                raise GateError('developer state output path rejected')
            path = runner.fetch('developer-state-output/' + row['path'], runner.scratch / 'state-output' / row['path'])
            if file_hash(path) != row['sha256'] or path.stat().st_size != row['bytes']:
                raise GateError('developer state output changed during collection')
            members(path, limits)
            shutil.copy2(path, stage/row['path'])
        atomic_json(stage / 'manifest.json', manifest)
        # Under the per-profile admission lock; an interrupted replacement may
        # lose acceleration, but cannot grant a pass or mix two namespaces.
        if directory.exists():
            shutil.rmtree(directory)
        stage.rename(directory)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
