"""Trusted data-only developer image assembler; no host native build/install.

The preceding extraction job is offline and confined. Ordinary checks never
invoke this explicit acquisition step. Its output remains independently unsealed.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time

from evidence import Runner, GateError, atomic_json, file_hash, read_json, passed, bounded

ROOT = Path(__file__).resolve().parents[1]
DEBIAN_MAX_BYTES = 268435456
DEBIAN_MAX_FILES = 4096
# Separate bench-wheel bounds (controller ruling on PLAN-T5-BOUND-01), as in container/developer-package.py.
WHEEL_ROOT = 'opt/bench-python/'
WHEEL_MAX_BYTES = 201326592
WHEEL_MAX_FILES = 1536


def payload_of(name, record):
    return 'wheels' if name.startswith(WHEEL_ROOT) else 'debian'


def verify_metadata(inputs, output):
    """Outer acquisition verifies signed bytes; it executes no candidate helper."""
    keyring = Path('/usr/share/keyrings/debian-archive-keyring.pgp')
    if not keyring.is_file():
        raise GateError('system Debian archive trust keyring unavailable for acquisition')
    verified = bounded(['/usr/bin/gpgv', '--keyring', str(keyring), '--status-fd', '1',
                        str(inputs / 'InRelease')], timeout=20, limit=1048576)
    atomic_json(output / 'signature-verification.json', verified)
    fingerprints = [line.split()[2] for line in verified['output'].splitlines()
                    if line.startswith('[GNUPG:] VALIDSIG ')]
    if not passed(verified) or not fingerprints:
        raise GateError('signed acquisition release authentication failed')
    release = (inputs / 'InRelease').read_text()
    matches = re.findall(r'^ ([0-9a-f]{64})\s+([0-9]+) main/binary-amd64/Packages.xz$', release, re.M)
    package_archive = inputs / 'Packages.xz'
    if (len(matches) != 1 or package_archive.stat().st_size > 33554432 or
            int(matches[0][1]) != package_archive.stat().st_size or
            matches[0][0] != file_hash(package_archive)):
        raise GateError('package metadata is not bound to authenticated release')
    decoder = lzma.LZMADecompressor()
    data = decoder.decompress(package_archive.read_bytes(), max_length=134217729)
    if not decoder.eof or decoder.unused_data or len(data) > 134217728:
        raise GateError('acquisition metadata decompression bound exceeded')
    selection = read_json(inputs / 'selection.json')
    selected = {p['Package']: p for p in selection['packages']}
    if len(selected) != len(selection['packages']) or not {'gdb', 'clangd-19'} <= set(selected):
        raise GateError('developer package selection incomplete or duplicate')
    checked = set()
    for block in data.decode().split('\n\n'):
        fields, key = {}, None
        for line in block.splitlines():
            if line.startswith(' ') and key:
                fields[key] += ' ' + line.strip()
            elif ': ' in line:
                key, value = line.split(': ', 1)
                fields[key] = value
        if fields.get('Package') in selected:
            name = fields['Package']
            if name in checked or fields != selected[name]:
                raise GateError('selected package differs from signed upstream metadata')
            checked.add(name)
    if checked != set(selected):
        raise GateError('selected package missing from signed metadata')
    return {'status': 'AUTHENTICATED_METADATA', 'signer_fingerprints': fingerprints,
            'keyring_sha256': file_hash(keyring),
            'verifier_sha256': file_hash(Path('/usr/bin/gpgv')),
            'inrelease_sha256': file_hash(inputs / 'InRelease'),
            'packages_sha256': file_hash(package_archive),
            'evidence_path': str(output / 'signature-verification.json')}


def chain_ids(diff_ids):
    """OCI ChainIDs: a containerd snapshot is shared exactly when its ChainID is equal."""
    chains, previous = [], None
    for diff in diff_ids:
        previous = diff if previous is None else 'sha256:' + hashlib.sha256((previous + ' ' + diff).encode()).hexdigest()
        chains.append(previous)
    return chains


def layer_measure(identity, inspect, history_sizes, blob_sizes, platform):
    """Exact containerd-store image measurement (PLAN-T5-IMAGES-01 ruling).

    On the containerd image store, `docker image inspect` Size is the snapshot usage of each
    unpacked layer (non-empty `docker history --human=false` rows, oldest first, one per
    RootFS layer) plus the content blobs of the platform manifest closure (manifest, config
    and compressed layers). `docker image save` lists every stored blob of the image,
    including the index and attestation blobs that Size omits; all of them occupy the
    store, so all of them are counted. Snapshots are keyed by ChainID and blobs by digest,
    so shared layers count once. The measurement is refused unless the snapshots plus the
    platform closure add up to the reported Size exactly."""
    layers = inspect['RootFS']['Layers']
    sizes = [int(v) for v in history_sizes if int(v) > 0]
    if len(sizes) != len(layers) or any(int(v) < 0 for v in history_sizes):
        raise GateError('owned image layer history does not match its layers: ' + identity[:19])
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', d) for d in blob_sizes) or not set(platform) <= set(blob_sizes):
        raise GateError('owned image blob inventory invalid: ' + identity[:19])
    chains = dict(zip(chain_ids(layers), sizes))
    if sum(chains.values()) + sum(blob_sizes[d] for d in set(platform)) != inspect['Size']:
        raise GateError('owned image measurement is not exact: ' + identity[:19])
    return {'id': identity, 'chains': chains, 'blobs': dict(blob_sizes), 'size': inspect['Size']}


def platform_closure(documents):
    """Digests of the linux/amd64 image manifest, its config and its layers."""
    def load(digest):
        if digest not in documents:
            raise GateError('owned image manifest unavailable')
        return json.loads(documents[digest])
    try:
        roots = load('index.json')['manifests']
        if len(roots) != 1:
            raise GateError('owned image index ambiguous')
        digest, document = roots[0]['digest'], load(roots[0]['digest'])
        if 'manifests' in document:
            images = [m for m in document['manifests']
                      if not (m.get('annotations') or {}).get('vnd.docker.reference.type') and
                      (m.get('platform') or {}).get('os') == 'linux' and
                      (m.get('platform') or {}).get('architecture') == 'amd64']
            if len(images) != 1:
                raise GateError('owned image platform manifest ambiguous')
            digest, document = images[0]['digest'], load(images[0]['digest'])
        return {digest, document['config']['digest'], *(layer['digest'] for layer in document['layers'])}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GateError('owned image manifest malformed')


def unique_bytes(measures):
    """Owned-image bytes with every snapshot (ChainID) and content blob (digest) counted once."""
    chains, blobs = {}, {}
    for row in measures:
        for key, size in row['chains'].items():
            if chains.setdefault(key, size) != size:
                raise GateError('one snapshot reports two sizes')
        for key, size in row['blobs'].items():
            if blobs.setdefault(key, size) != size:
                raise GateError('one content blob reports two sizes')
    return sum(chains.values()) + sum(blobs.values())


def admit(measures, extra_bytes, bound):
    """The unchanged owned_image_bytes bound applied to layer-deduplicated bytes."""
    total = unique_bytes(measures) + extra_bytes
    if total > bound:
        raise GateError('developer image acquisition exceeds owned-image admission bound')
    return total


def save_content(launcher, identity, timeout=600, max_members=4096, document_limit=65536,
                 popen=subprocess.Popen):
    """Stream `docker image save`; read tar headers, and the bodies of small JSON documents only.

    A watchdog kills the process group after `timeout` seconds of wall time, so a stalled
    stream ends (EOF) and the listing fails closed; the process is always reaped."""
    if launcher.prefix is None:
        launcher.connect()
    process = popen(launcher.prefix + ['image', 'save', identity], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=launcher.env, start_new_session=True)
    expired = threading.Event()

    def kill():
        try:
            os.killpg(process.pid, 9)
        except OSError:
            pass

    def expire():
        expired.set()
        kill()

    watchdog = threading.Timer(timeout, expire)
    watchdog.daemon = True
    watchdog.start()
    blobs, documents, members = {}, {}, 0
    try:
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as source:
                for member in source:
                    members += 1
                    if members > max_members:
                        raise GateError('owned image content listing bound')
                    if not member.isfile():
                        continue
                    key = None
                    if re.fullmatch(r'blobs/sha256/[0-9a-f]{64}', member.name):
                        key = 'sha256:' + member.name.rsplit('/', 1)[1]
                        blobs[key] = member.size
                    elif member.name == 'index.json':
                        key = 'index.json'
                    if key and member.size <= document_limit:
                        documents[key] = source.extractfile(member).read(document_limit + 1)
        except (tarfile.TarError, OSError, ValueError, EOFError):
            if expired.is_set():
                raise GateError('owned image content listing timed out')
            raise GateError('owned image content listing malformed')
        if expired.is_set():
            raise GateError('owned image content listing timed out')
        try:
            code = process.wait(timeout=max(1, timeout))
        except subprocess.TimeoutExpired:
            raise GateError('owned image content listing timed out')
        if expired.is_set():
            raise GateError('owned image content listing timed out')
        if code:
            raise GateError('owned image content listing failed')
    finally:
        watchdog.cancel()
        if process.poll() is None:
            kill()
        try:
            process.wait(timeout=10)
        finally:
            process.stdout.close()
    return blobs, platform_closure(documents)


def measure_owned(launcher, identity):
    try:
        inspect = launcher.json(['image', 'inspect', identity])[0]
    except (ValueError, IndexError, KeyError):
        raise GateError('owned image inspect malformed')
    history = launcher.docker(['history', '--human=false', '--no-trunc', '--format', '{{.Size}}', identity])
    if not passed(history):
        raise GateError('owned image history unavailable')
    rows = history['output'].split()
    if not rows or any(not re.fullmatch(r'[0-9]+', row) for row in rows):
        raise GateError('owned image history malformed')
    blobs, platform = save_content(launcher, identity)
    return layer_measure(identity, inspect, list(reversed(rows)), blobs, platform)


def unpack(directory, destination):
    manifest = read_json(directory / 'manifest.json')
    if (manifest.get('status') != 'CANDIDATE_DATA_EXTRACTED' or
            manifest.get('package_scripts_executed') is not False or
            sum(1 for n, r in manifest['files'].items() if payload_of(n, r) == 'debian') > DEBIAN_MAX_FILES or
            sum(1 for n, r in manifest['files'].items() if payload_of(n, r) == 'wheels') > WHEEL_MAX_FILES or
            'host_members' in manifest):
        raise GateError('developer extraction manifest incomplete')
    files, seen, total, wheel_total = manifest['files'], set(), 0, 0
    for row in manifest['archives']:
        if not re.fullmatch(r'development-layer-[0-9]+\.tar\.gz', row['name']):
            raise GateError('unsafe developer archive name')
        archive = directory / row['name']
        if (archive.stat().st_size != row['bytes'] or row['bytes'] > 33554432 or
                file_hash(archive) != row['sha256']):
            raise GateError('developer collected archive identity mismatch')
        members = []
        with tarfile.open(archive) as source:
            for member in source:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or
                        not member.isfile() or member.name not in files or
                        member.name in seen or member.mode & 0o6000 or
                        not (member.name in {'usr/bin/gdb', 'usr/bin/clangd-19'} or
                             member.name.startswith(('usr/lib/', 'usr/share/gdb/',
                                                     'usr/share/doc/', 'usr/share/source-highlight/',
                                                     'opt/bench-python/')))):
                    raise GateError('unsafe developer payload member')
                record = files[member.name]
                if member.size != record['bytes'] or member.size > 33554432:
                    raise GateError('developer payload file bound mismatch')
                kind = payload_of(member.name, record)
                if kind == 'wheels':
                    wheel_total += member.size
                else:
                    total += member.size
                if total > DEBIAN_MAX_BYTES or wheel_total > WHEEL_MAX_BYTES:
                    raise GateError('developer payload total bound exceeded')
                data = source.extractfile(member).read(member.size + 1)
                if len(data) != member.size or hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise GateError('developer payload file identity mismatch')
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(record['mode'])
                members.append(member.name)
                seen.add(member.name)
        if members != row['files']:
            raise GateError('developer chunk inventory mismatch')
    if seen != set(files):
        raise GateError('developer payload inventory incomplete')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extraction', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    extraction, inputs, output = (p.resolve() for p in
                                  [args.extraction, args.inputs, args.output])
    if (not extraction.is_relative_to(ROOT / 'artifacts') or
            not inputs.is_relative_to(ROOT / 'artifacts') or
            not output.is_relative_to(ROOT / 'artifacts') or output.exists()):
        raise GateError('new owned acquisition output and retained inputs required')
    extraction_result = read_json(extraction / 'extraction.json')
    if (not passed(extraction_result) or
            extraction_result.get('input_binding', {}).get('source') is None):
        raise GateError('source-bound confined extraction receipt required')
    output.mkdir()
    signature = verify_metadata(inputs, output)
    # Acquisition provenance never replaces independent baseline authority.
    selection = read_json(inputs / 'selection.json')
    if selection['packages_metadata_sha256'] != file_hash(inputs / 'Packages.xz'):
        raise GateError('retained package metadata changed')
    for package in selection['packages']:
        archive = inputs / PurePosixPath(package['Filename']).name
        if file_hash(archive) != package['SHA256'] or archive.stat().st_size != int(package['Size']):
            raise GateError('retained package archive changed')
    wheel_selection = (read_json(inputs / 'wheel-selection.json')
                       if (inputs / 'wheel-selection.json').is_file() else {'wheels': []})
    for wheel in wheel_selection['wheels']:
        whole = hashlib.sha256()
        for part in wheel['parts']:
            piece = inputs / PurePosixPath(part['path']).name
            if (piece.stat().st_size != part['bytes'] or part['bytes'] > 33554432 or
                    file_hash(piece) != part['sha256']):
                raise GateError('retained bench wheel part changed: ' + wheel['name'])
            whole.update(piece.read_bytes())
        if whole.hexdigest() != wheel['sha256']:
            raise GateError('retained bench wheel digest changed: ' + wheel['name'])
    context = Path(tempfile.mkdtemp(prefix='safe-c-dev-data-image-'))
    scratch = Path(tempfile.mkdtemp(prefix='safe-c-dev-image-observation-'))
    current = read_json(ROOT / 'toolchain.lock.json')
    runner = Runner(ROOT, output, current, scratch)
    try:
        runner.start()
        manifest = unpack(extraction, context / 'layer')
        launcher = runner.launcher
        content = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
        tag = 'safe-c-developer:' + content[:24]
        # Inspect unique project-tagged images as metadata, without global cleanup.
        listed = launcher.docker(['image', 'ls', '--no-trunc', '--format', '{{json .}}'])
        if not passed(listed):
            raise GateError('owned image inventory unavailable')
        ids = {json.loads(line)['ID'] for line in listed['output'].splitlines()
               if json.loads(line)['Repository'].startswith('safe-c-')}
        measures = [measure_owned(launcher, identity) for identity in sorted(ids)]
        existing = launcher.docker(['image', 'inspect', tag])
        reused = passed(existing)
        if reused:
            image = json.loads(existing['output'])[0]
            base = launcher.json(['image', 'inspect', current['image_id']])[0]
            if image['RootFS']['Layers'][:len(base['RootFS']['Layers'])] != base['RootFS']['Layers']:
                raise GateError('existing development image does not inherit exact base layers')
        extra = 0 if reused else 1
        if current['image_id'] not in ids:
            measures.append(measure_owned(launcher, current['image_id']))
        # A new image adds one snapshot and one compressed blob of the payload; each is bounded
        # by the payload bytes plus one 4 KiB block per file (snapshot block rounding).
        payload = sum(row['bytes'] + 4096 for row in manifest['files'].values())
        if len(ids) + extra > launcher.value['aggregate']['max_owned_images']:
            raise GateError('developer image acquisition exceeds owned-image admission bound')
        admitted = admit(measures, extra * 2 * payload, launcher.value['aggregate']['owned_image_bytes'])
        base_tag = 'safe-c-developer-base:' + current['image_id'].split(':')[1][:24]
        tagged = launcher.docker(['tag', current['image_id'], base_tag])
        if not passed(tagged) or launcher.json(['image', 'inspect', base_tag])[0]['Id'] != current['image_id']:
            raise GateError('exact developer base tagging failed')
        (context / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY layer /\n')
        built = (existing if reused else launcher.docker(
            ['build', '--pull=false', '--network=none', '--tag', tag, str(context)],
            timeout=120, limit=4194304))
        atomic_json(output / 'image-build.json', built)
        if not passed(built):
            raise GateError('developer data-only image assembly failed')
        image = launcher.json(['image', 'inspect', tag])[0]
        owned_after = admit([m for m in measures if m['id'] != image['Id']] + [measure_owned(launcher, image['Id'])],
                            0, launcher.value['aggregate']['owned_image_bytes'])
        if (image['Size'] > launcher.value['aggregate']['owned_image_bytes'] or
                any(image['Config'].get(key) for key in ['Entrypoint', 'Volumes', 'Healthcheck'])):
            raise GateError('developer image metadata or storage bound mismatch')
        candidate = {'schema_version': 1, 'status': 'ACQUIRED_UNQUALIFIED',
                     'base_image_id': current['image_id'], 'image_id': image['Id'],
                     'image_registry_digest': None,
                     'toolchain_lock_sha256': file_hash(ROOT / 'toolchain.lock.json'),
                     'foundation_lock_sha256': file_hash(ROOT / 'foundation.lock.json'),
                     'extraction_binding': extraction_result['input_binding'],
                     'recipe_sha256': file_hash(ROOT / 'container/developer-package.py'),
                     'payload_manifest_sha256': file_hash(extraction / 'manifest.json'),
                     'payload': manifest, 'acquisition': selection,
                     'upstream_signature': signature,
                     'owner': 'MarketData-App', 'license_review': 'PENDING',
                     'independent_approval': 'PENDING',
                     'sanitizer_boundary': 'developer processes only; first-party compiler/GLib profiles unchanged',
                     'ordinary_image_migrated': False,
                     'bench_python': {w['name']: w['version'] for w in wheel_selection['wheels']}}
        candidate['reused_image'] = reused
        candidate['owned_image_bytes'] = {'method': 'containerd snapshots by ChainID + content blobs by digest, each counted once',
                                          'admitted_projection': admitted, 'measured_after_build': owned_after,
                                          'bound': launcher.value['aggregate']['owned_image_bytes']}
        atomic_json(output / 'candidate-developer.lock.json', candidate)
        print(json.dumps({'status': candidate['status'], 'image_id': image['Id'],
                          'base_image_id': current['image_id'], 'payload_files': len(manifest['files']),
                          'lock_path': str(output / 'candidate-developer.lock.json')}))
    finally:
        runner.close()
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(context, ignore_errors=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__,
                          'property': str(error) if isinstance(error, GateError) else None}))
        raise SystemExit(1)
