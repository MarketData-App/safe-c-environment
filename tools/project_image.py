"""EX-1: the project bench image: the qualified developer image plus one data layer of the project's pinned wheels.

Trusted host adapter. It reads JSON and files only and never imports project code. A project that binds a third-party
lock with wheels (tools/project_third_party.py) runs every bench job in this image (bench.BenchSession.select_image).

Build (offline, from pinned local files, through the protected launcher):
1. verify every part, provenance record and notice of the lock on the host (project_third_party.verify_files);
2. the extraction job container/project-wheels.py in the dependency-build profile (toolchain image, no network) with
   /inputs = the lock and the wheel parts; it writes chunked layer archives, a manifest and the wheel license files;
3. verify each archive and each member on the host (unpack), and each wheel notice digest against the lock; T6-R2: then
   write each host member (a wheel member above the container file bound that the lock declares; the job hashed it and
   never wrote it) from the sha256-verified wheel parts, in bounded chunks, with its size and sha256 checked
   (stream_host_members); the layer file and byte bounds and the added-bytes rule count host members;
4. evict nothing but this project's own older bench images, then count the cache images of both kinds
   (runtime_cache.cache_ids) against max_owned_images;
5. a data-only `docker build --pull=false --network=none` (FROM the developer image, COPY layer /, labels only; the
   method of the pinned developer assembler); verify the labels, the inherited layers plus one layer, no entrypoint,
   volume or health check, and the added bytes.

The image key is the sha256 of the developer image id, the lock sha256, the recipe sha256 and this file's sha256; the
tag is safe-c-project-bench:<key[:24]>. The lock sha256 binds the host member declarations, and the recipe and assembler
sha256 bind the code of both routes. An existing tag is reused only when it passes the same image checks. The image
is a cache kind of tools/runtime_cache.py. There is no network step here; the only online step is the explicit,
owner-approved `tools/acquire_bench_wheels.py fetch-project`."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from evidence import GateError, Runner, atomic_json, file_hash, loads_capped, passed, read_json
import bench_model as bm
import project_third_party as ptp

ROOT = Path(__file__).resolve().parents[1]
RECIPE = 'container/project-wheels.py'
ASSEMBLER = 'tools/project_image.py'
LABEL_KEY = 'org.safe-c.project-bench'
KEY_LABEL = 'org.safe-c.project-bench-key'
NAME_KEY = 'org.safe-c.project-name'
RUNTIME_LABEL_KEY = 'org.safe-c.project-runtime'
TAG_PREFIX = 'safe-c-project-bench:'
ARCHIVE_RE = re.compile(r'^layer-[0-9]+\.tar\.gz$')
FILE_MODES = (0o444, 0o555)
BLOCK = 4096
METADATA_ALLOWANCE = 1048576      # the manifest, config and directory entries of the new layer (measured: about 40 KiB)
ELF_MAGIC = b'\x7fELF'            # EX1-A02 (a): the recipe's elf_files record is checked against these bytes
READ_CHUNK = 1048576              # T6-R2: one read of a host member stream


def image_key(root, developer_image_id, lock_sha256):
    value = {'developer_image_id': developer_image_id, 'lock_sha256': lock_sha256,
             'recipe_sha256': file_hash(Path(root) / RECIPE), 'assembler_sha256': file_hash(Path(root) / ASSEMBLER)}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def selection(root, project_dir):
    """None (no project, no lock, or a lock without wheels), or the image selection of the project: its bench name, lock,
    lock sha256, image key and tag, the developer image id and the coordinator plan entry."""
    if project_dir is None:
        return None
    lock = bm.third_party_lock(root, project_dir)
    if lock is None or not lock['wheels']:
        return None
    decl = bm.project_bench(root, project_dir)
    developer = read_json(Path(root) / 'developer.lock.json')['image_id']
    key = image_key(root, developer, decl['third_party']['sha256'])
    return {'project_dir': project_dir, 'name': decl['name'], 'lock': lock, 'lock_sha256': decl['third_party']['sha256'],
            'key': key, 'tag': TAG_PREFIX + key[:24], 'developer_image_id': developer, 'plan': ptp.plan_entry(lock)}


def image_problem(obj, base, sel):
    """None, or why the inspected image `obj` is not the project bench image of `sel` on the developer image `base`."""
    config = obj.get('Config') or {}
    labels = config.get('Labels') or {}
    if labels.get(LABEL_KEY) != '1' or labels.get(KEY_LABEL) != sel['key'] or labels.get(NAME_KEY) != sel['name']:
        return 'labels differ'
    if RUNTIME_LABEL_KEY in labels:
        return 'carries the runtime cache label'
    layers, inherited = obj['RootFS']['Layers'], base['RootFS']['Layers']
    if len(layers) != len(inherited) + 1 or layers[:len(inherited)] != inherited:
        return 'not the developer layers plus one layer'
    if any(config.get(k) for k in ('Entrypoint', 'Volumes', 'Healthcheck')):
        return 'entrypoint, volume or health check present'
    if config.get('User') != (base.get('Config') or {}).get('User'):
        return 'user differs from the developer image'
    return None


def _inspect(docker, ref):
    result = docker(['image', 'inspect', ref])
    if not passed(result):
        return None
    try:
        rows = loads_capped(result['output'])
    except ValueError:
        raise GateError('image inspect malformed') from None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise GateError('image inspect malformed')
    return rows[0]


def declared_host_members(lock):
    """T6-R2: {layer path: (wheel row, declaration)} of every host member that the lock declares."""
    rows = {}
    for wheel in lock['wheels']:
        for decl in wheel.get('host_members', []):
            target = ptp.LAYER_ROOT + str(decl['member'])
            if target in rows:
                raise GateError('project layer host member declared twice: ' + target)
            rows[target] = (wheel, decl)
    return rows


def check_host_record(hosts, declared, files):
    """T6-R2: the manifest record `hosts` equals the lock declarations `declared`: the same layer paths, each a safe path under
    the layer root that is no `files` entry, with the member name, wheel, size and sha256 of its declaration and a layer file
    mode, above the container file bound and at most the host member bound. GateError on the first difference."""
    if set(hosts) != set(declared):
        raise GateError('project layer host members differ from the lock')
    for target, (wheel, decl) in sorted(declared.items()):
        row = hosts[target]
        if (target.startswith('/') or any(p in ('', '.', '..') for p in target.split('/')) or not target.startswith(ptp.LAYER_ROOT)
                or target in files):
            raise GateError('unsafe project layer host member: ' + target)
        if (not isinstance(row, dict) or set(row) != {'name', 'wheel', 'bytes', 'sha256', 'mode'} or row['name'] != decl['member']
                or row['wheel'] != wheel['name'] or type(row['bytes']) is not int or row['bytes'] != decl['bytes']
                or row['sha256'] != decl['sha256'] or row['mode'] not in FILE_MODES):
            raise GateError('project layer host member differs from the lock: ' + target)
        if row['bytes'] <= ptp.PART_MAX_BYTES:
            raise GateError('project layer host member not oversized: ' + target)
        if row['bytes'] > ptp.HOST_MEMBER_MAX_BYTES:
            raise GateError('project layer host member bound: ' + target)


def member_chunks(stream, row, target):
    """T6-R2: the bytes of one host member from `stream`, in chunks of at most READ_CHUNK bytes. GateError above the host
    member bound or above the declared size during the stream, and for a size or sha256 difference at its end."""
    hasher, count = hashlib.sha256(), 0
    while True:
        chunk = stream.read(READ_CHUNK)
        if not chunk:
            break
        count += len(chunk)
        if count > ptp.HOST_MEMBER_MAX_BYTES:
            raise GateError('project layer host member bound: ' + target)
        if count > row['bytes']:
            raise GateError('project layer host member identity mismatch: ' + target)
        hasher.update(chunk)
        yield chunk
    if count != row['bytes'] or hasher.hexdigest() != row['sha256']:
        raise GateError('project layer host member identity mismatch: ' + target)


def verified_wheel(wheel, inputs):
    """T6-R2: the bytes of a wheel row of tracked parts, joined from the extraction inputs; each part (a regular file of at
    most the container file bound) and the whole wheel must have the size and sha256 of the lock."""
    if not wheel['parts']:
        raise GateError('a host member needs a wheel of tracked parts: ' + wheel['name'])
    data = b''
    for part in wheel['parts']:
        path = Path(inputs) / PurePosixPath(part['path']).name
        if path.is_symlink() or not path.is_file():
            raise GateError('project wheel part is missing from the inputs: ' + part['path'])
        with open(path, 'rb') as f:
            piece = f.read(ptp.PART_MAX_BYTES + 1)
        if len(piece) != part['bytes'] or len(piece) > ptp.PART_MAX_BYTES or hashlib.sha256(piece).hexdigest() != part['sha256']:
            raise GateError('project wheel part changed: ' + part['path'])
        data += piece
    if len(data) != wheel['bytes'] or len(data) > ptp.ITEM_MAX_BYTES or hashlib.sha256(data).hexdigest() != wheel['sha256']:
        raise GateError('project wheel differs from the lock: ' + wheel['name'])
    return data


def stream_host_members(lock, hosts, inputs, destination):
    """T6-R2: writes each host member of the checked record `hosts` (check_host_record) as a new regular file under
    destination, streamed from the verified wheel bytes (verified_wheel) by member_chunks, then sets its mode. The wheel
    holds the member exactly once, with the declared size and a regular mode that gives the recorded mode. A refused member
    leaves no file. Returns the layer paths whose first bytes are the ELF magic."""
    wheels = {w['name']: w for w in lock['wheels']}
    elf = set()
    for name in sorted({row['wheel'] for row in hosts.values()}):
        try:
            source = zipfile.ZipFile(io.BytesIO(verified_wheel(wheels[name], inputs)))
        except zipfile.BadZipFile:
            raise GateError('project wheel is no zip archive: ' + name) from None
        with source:
            infos = source.infolist()
            for target in sorted(t for t, row in hosts.items() if row['wheel'] == name):
                row = hosts[target]
                found = [i for i in infos if i.filename == row['name']]
                if len(found) != 1 or found[0].file_size != row['bytes']:
                    raise GateError('project layer host member identity mismatch: ' + target)
                mode = found[0].external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or mode & 0o6000 or (0o555 if mode & 0o111 else 0o444) != row['mode']:
                    raise GateError('project layer host member mode differs from the wheel: ' + target)
                out = destination / target
                try:
                    for parent in reversed(out.relative_to(destination).parents):
                        if str(parent) != '.':
                            (destination / parent).mkdir(mode=0o755, exist_ok=True)
                            (destination / parent).chmod(0o755)
                    sink = open(out, 'xb')
                except OSError:
                    raise GateError('unsafe project layer host member: ' + target) from None
                head = b''
                try:
                    with sink, source.open(found[0]) as stream:
                        for chunk in member_chunks(stream, row, target):
                            if len(head) < 4:
                                head += chunk[:4 - len(head)]
                            sink.write(chunk)
                except Exception as error:
                    out.unlink(missing_ok=True)
                    if isinstance(error, GateError):
                        raise
                    raise GateError('project layer host member unreadable: ' + target) from None
                out.chmod(row['mode'])
                if head == ELF_MAGIC:
                    elf.add(target)
    return elf


def unpack(directory, manifest, destination, lock, inputs=None):
    """Verifies the collected manifest and archives and writes the layer under destination; T6-R2: then the host members that
    the lock declares, streamed from the verified wheel parts in `inputs` (stream_host_members). Returns (bytes, files) of
    the layer, host members included."""
    files, hosts = manifest.get('files'), manifest.get('host_members')
    if (manifest.get('status') != 'PROJECT_WHEELS_EXTRACTED' or manifest.get('wheel_code_executed') is not False or
            not isinstance(files, dict) or not isinstance(hosts, dict) or len(files) + len(hosts) > ptp.LAYER_MAX_FILES or
            not isinstance(manifest.get('archives'), list)):
        raise GateError('project wheel extraction manifest incomplete')
    want = sorted(ptp.dist_info_name(w['name'], w['version']).lower() for w in lock['wheels'])
    if sorted(str(d).lower() for d in manifest.get('dist_info') or []) != want:
        raise GateError('project wheel dist-info set differs from the lock')
    check_host_record(hosts, declared_host_members(lock), files)
    if hosts and inputs is None:
        raise GateError('project layer host members need the verified wheel inputs')
    total = sum(row['bytes'] for row in hosts.values())     # T6-R2: the layer byte bound counts host members first
    if total > ptp.LAYER_MAX_BYTES:
        raise GateError('project layer total bound exceeded')
    seen, elf_found = set(), set()
    for row in manifest['archives']:
        if not isinstance(row, dict) or not ARCHIVE_RE.fullmatch(str(row.get('name'))):
            raise GateError('unsafe project layer archive name')
        archive = directory / row['name']
        if (archive.stat().st_size != row['bytes'] or row['bytes'] > ptp.PART_MAX_BYTES or file_hash(archive) != row['sha256']):
            raise GateError('project layer archive identity mismatch')
        members = []
        with tarfile.open(archive) as source:
            for member in source:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or not member.isfile() or member.name not in files or
                        member.name in seen or member.mode & 0o6000 or not member.name.startswith(ptp.LAYER_ROOT)):
                    raise GateError('unsafe project layer member')
                record = files[member.name]
                if member.size != record['bytes'] or member.size > ptp.PART_MAX_BYTES or record['mode'] not in FILE_MODES:
                    raise GateError('project layer file bound mismatch')
                total += member.size
                if total > ptp.LAYER_MAX_BYTES:
                    raise GateError('project layer total bound exceeded')
                data = source.extractfile(member).read(member.size + 1)
                if len(data) != member.size or hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise GateError('project layer file identity mismatch')
                if data[:4] == ELF_MAGIC:
                    elf_found.add(member.name)
                target = destination / member.name
                for parent in reversed(target.relative_to(destination).parents):
                    if str(parent) != '.':
                        (destination / parent).mkdir(mode=0o755, exist_ok=True)
                        (destination / parent).chmod(0o755)
                target.write_bytes(data)
                target.chmod(record['mode'])
                members.append(member.name)
                seen.add(member.name)
        if members != row['files']:
            raise GateError('project layer chunk inventory mismatch')
    if seen != set(files):
        raise GateError('project layer inventory incomplete')
    if hosts:
        elf_found |= stream_host_members(lock, hosts, inputs, destination)
    # EX1-A02 (a): the extraction's ELF record names exactly the layer files (host members included) that start with the
    # ELF magic bytes, each with a wheel of the lock.
    elf = manifest.get('elf_files')
    wheels = {w['name'] for w in lock['wheels']}
    if not isinstance(elf, dict) or set(elf) != elf_found or any(owner not in wheels for owner in elf.values()):
        raise GateError('project layer ELF record differs from the layer bytes')
    return total, len(files) + len(hosts)


def check_notices(manifest, lock):
    """Each wheel's license file (found by the extraction job in its dist-info directory) has the lock notice sha256."""
    notices = manifest.get('notices') or {}
    for wheel in lock['wheels']:
        found = notices.get(wheel['name'])
        if not isinstance(found, dict) or found.get('sha256') != wheel['notice']['sha256']:
            raise GateError('wheel notice differs from the license file in the wheel: ' + wheel['name'])


def admit(docker, sel, max_images):
    """Removes this project's own older bench images (no force; an image in use stays), then GateError when the cache
    images of both kinds already reach max_owned_images. Returns the count before the new image."""
    from runtime_cache import cache_ids
    old = docker(['image', 'ls', '--no-trunc', '--filter', 'label=' + LABEL_KEY + '=1',
                  '--filter', 'label=' + NAME_KEY + '=' + sel['name'], '--format', '{{.ID}}'])
    for image_id in sorted(set(old['output'].split())) if passed(old) else []:
        docker(['image', 'rm', image_id], timeout=30)
    count = len(cache_ids(docker))
    if count >= max_images:
        raise GateError(f'owned cache-image bound: {count} cache images exist; max_owned_images {max_images} leaves no room for a '
                        'new one; evict unused caches with tools/runtime_cache.py')
    return count


def build_image(launcher, sel, base, context, payload_bytes, payload_files):
    """The data-only image build of a verified layer under context/layer; returns the inspected image."""
    docker = launcher.docker
    developer = sel['developer_image_id']
    base_tag = 'safe-c-developer:base-' + developer.split(':')[1][:24]
    tagged = docker(['tag', developer, base_tag])
    found = _inspect(docker, base_tag) if passed(tagged) else None
    if found is None or found.get('Id') != developer:
        raise GateError('exact developer base tagging failed')
    (context / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY layer /\n'
                                        'LABEL ' + LABEL_KEY + '=1 ' + NAME_KEY + '=' + sel['name'] + ' ' + KEY_LABEL + '=' + sel['key'] + '\n')
    built = docker(['build', '--pull=false', '--network=none', '--tag', sel['tag'], str(context)], timeout=300, limit=4194304)
    if not passed(built):
        raise GateError('project bench image assembly failed')
    obj = _inspect(docker, sel['tag'])
    problem = 'missing after the build' if obj is None else image_problem(obj, base, sel)
    added = None if obj is None else obj.get('Size', 0) - base.get('Size', 0)
    if problem is None and (added is None or added > 2 * (payload_bytes + BLOCK * payload_files) + METADATA_ALLOWANCE):
        problem = 'added bytes exceed two times the payload'
    if problem is not None:
        if obj is not None:
            docker(['image', 'rm', obj['Id']], timeout=30)
        raise GateError('project bench image check failed: ' + problem)
    return obj


def extract(root, run_dir, sel, inputs):
    """The offline extraction job; returns (collected directory, manifest)."""
    lock = read_json(Path(root) / 'toolchain.lock.json')
    scratch = Path(tempfile.mkdtemp(prefix='safe-c-project-wheels-'))
    out = run_dir / 'extraction'
    runner = Runner(Path(root), out, lock, scratch, build_profile='dependency-build', input_root=inputs)
    try:
        result = runner.run(['python3', '/src/' + RECIPE], timeout=600, label='project-wheels')
        atomic_json(out / 'extraction.json', {k: result.get(k) for k in ('exit_code', 'failure', 'evidence_path')})
        if not passed(result):
            raise GateError('project wheel extraction job failed; read its evidence by exit code and error_type')
        manifest_path = runner.fetch('project-wheels/manifest.json', out / 'manifest.json')
        manifest = read_json(manifest_path)
        for row in manifest.get('archives') or []:
            if not isinstance(row, dict) or not ARCHIVE_RE.fullmatch(str(row.get('name'))):
                raise GateError('unsafe project layer archive name')
            runner.fetch('project-wheels/' + row['name'], out / row['name'])
        # The license file of each wheel, kept for the owner's notice review (an acquisition copies it into the lock).
        for wheel in sel['lock']['wheels']:
            found = (manifest.get('notices') or {}).get(wheel['name'])
            leaf = PurePosixPath(str((found or {}).get('path', ''))).name
            if re.fullmatch(r'[A-Za-z0-9._-]{1,80}', leaf) and leaf not in ('.', '..'):
                runner.fetch('project-wheels/notices/' + wheel['name'] + '/' + leaf, out / 'notices' / wheel['name'] / leaf)
    finally:
        runner.close()
        shutil.rmtree(scratch, ignore_errors=True)
    return out, manifest


def ensure_selected(root, sel, run_dir, *, launcher=None, extractor=extract):
    """The image id of the selection `sel`: an existing tag that passes image_problem, or a new build. Writes
    run_dir/project-image.json. GateError on any failed step (the bench job is then BLOCKED)."""
    from container_policy import Launcher
    root = Path(root)
    run_dir = Path(run_dir) / ('project-image-' + sel['key'][:12])
    run_dir.mkdir(parents=True, exist_ok=True)
    if launcher is not None:
        return _ensure(root, sel, run_dir, launcher, extractor)
    own = Launcher(root, run_dir, read_json(root / 'toolchain.lock.json'), purpose='bench')
    try:
        return _ensure(root, sel, run_dir, own, extractor)
    finally:
        own.close()


def _ensure(root, sel, run_dir, launcher, extractor):
    base = _inspect(launcher.docker, sel['developer_image_id'])
    if base is None or base.get('Id') != sel['developer_image_id']:
        raise GateError('the qualified developer image is not present')
    record = {'schema_version': 1, 'project_dir': sel['project_dir'], 'key': sel['key'], 'tag': sel['tag'],
              'lock_sha256': sel['lock_sha256'], 'developer_image_id': sel['developer_image_id']}
    existing = _inspect(launcher.docker, sel['tag'])
    if existing is not None:
        problem = image_problem(existing, base, sel)
        if problem is not None:
            raise GateError('existing project bench image does not match its key: ' + problem)
        record.update(image_id=existing['Id'], reused=True)
        atomic_json(run_dir / 'project-image.json', record)
        return record
    lock = sel['lock']
    base_dir = bm._project_base(root, sel['project_dir'])
    ptp.verify_files(base_dir, lock)
    work = Path(tempfile.mkdtemp(prefix='safe-c-project-image-'))
    try:
        inputs = work / 'inputs'
        inputs.mkdir()
        (inputs / 'lock.json').write_text(json.dumps(lock, sort_keys=True))     # the checked lock of the selection, not a re-read
        for wheel in lock['wheels']:
            if not wheel['parts']:          # a first-party fixture wheel, built from its tracked source and checked again
                data = ptp.build_source_wheel(base_dir, wheel)
                if hashlib.sha256(data).hexdigest() != wheel['sha256']:
                    raise GateError('first-party wheel source changed during the build: ' + wheel['name'])
                (inputs / wheel['filename']).write_bytes(data)
            for part in wheel['parts']:
                copy = inputs / Path(part['path']).name
                shutil.copyfile(base_dir / part['path'], copy)
                if file_hash(copy) != part['sha256']:
                    raise GateError('third-party part changed during the build: ' + part['path'])
        collected, manifest = extractor(root, run_dir, sel, inputs)
        check_notices(manifest, lock)
        context = work / 'context'
        (context / 'layer').mkdir(parents=True)
        payload_bytes, payload_files = unpack(collected, manifest, context / 'layer', lock, inputs)
        before = admit(launcher.docker, sel, launcher.value['aggregate']['max_owned_images'])
        obj = build_image(launcher, sel, base, context, payload_bytes, payload_files)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    record.update(image_id=obj['Id'], reused=False, payload_bytes=payload_bytes, payload_files=payload_files,
                  cache_images_before=before, added_bytes=obj.get('Size', 0) - base.get('Size', 0))
    atomic_json(run_dir / 'project-image.json', record)
    return record


def ensure(root, project_dir, run_dir, **kw):
    """None for a project without wheels; else ensure_selected of its selection."""
    sel = selection(root, project_dir)
    return None if sel is None else dict(ensure_selected(root, sel, run_dir, **kw), plan=sel['plan'])
