"""Trusted data-only developer image assembler; no host native build/install.

The preceding extraction job is offline and confined. Ordinary checks never
invoke this explicit acquisition step. Its output remains independently unsealed.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import lzma
import re
import shutil
import tarfile
import tempfile

from evidence import Runner, GateError, atomic_json, file_hash, read_json, passed, bounded

ROOT = Path(__file__).resolve().parents[1]


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


def unpack(directory, destination):
    manifest = read_json(directory / 'manifest.json')
    if (manifest.get('status') != 'CANDIDATE_DATA_EXTRACTED' or
            manifest.get('package_scripts_executed') is not False or
            len(manifest['files']) > 4096):
        raise GateError('developer extraction manifest incomplete')
    files, seen, total = manifest['files'], set(), 0
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
                                                     'usr/share/doc/', 'usr/share/source-highlight/')))):
                    raise GateError('unsafe developer payload member')
                record = files[member.name]
                if member.size != record['bytes'] or member.size > 33554432:
                    raise GateError('developer payload file bound mismatch')
                total += member.size
                if total > 268435456:
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
        sizes = {identity: launcher.json(['image', 'inspect', identity])[0]['Size'] for identity in ids}
        base_size = launcher.json(['image', 'inspect', current['image_id']])[0]['Size']
        existing = launcher.docker(['image', 'inspect', tag])
        reused = passed(existing)
        if reused:
            image = json.loads(existing['output'])[0]
            base = launcher.json(['image', 'inspect', current['image_id']])[0]
            if image['RootFS']['Layers'][:len(base['RootFS']['Layers'])] != base['RootFS']['Layers']:
                raise GateError('existing development image does not inherit exact base layers')
        extra = 0 if reused else 1
        if (len(ids) + extra > launcher.value['aggregate']['max_owned_images'] or
                sum(sizes.values()) + extra * (base_size +
                sum(row['bytes'] for row in manifest['files'].values())) >
                launcher.value['aggregate']['owned_image_bytes']):
            raise GateError('developer image acquisition exceeds owned-image admission bound')
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
                     'owner': 'MarketDataApp', 'license_review': 'PENDING',
                     'independent_approval': 'PENDING',
                     'sanitizer_boundary': 'developer processes only; first-party compiler/GLib profiles unchanged',
                     'ordinary_image_migrated': False}
        candidate['reused_image'] = reused
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
