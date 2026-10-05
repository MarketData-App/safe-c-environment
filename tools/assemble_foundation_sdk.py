"""Assemble verified SDK data atop the exact existing toolchain, without RUN.

Native dependency builds/tests take place in finite qualified Docker jobs. This
trusted adapter validates their collected archives and adds only those bytes.
It never fetches a base image, installs host packages, or executes candidate code.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from evidence import Runner, GateError, passed, read_json, file_hash, atomic_json

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {'gcc-O0', 'gcc-O2', 'clang-O0', 'clang-O2', 'asan', 'ubsan',
            'msan', 'tsan', 'coverage', 'fuzz'}
TESTS = {'bytes', 'string', 'array-test', 'hash', 'error', 'autoptr',
         'utf8-validate', 'overflow', 'refcount'}


def unpack(archive, destination, profile):
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 1024 or sum(x.size for x in members) > 256 * 1024 * 1024:
            raise GateError('SDK archive storage bound exceeded')
        names = [x.name for x in members]
        if len(set(names)) != len(names):
            raise GateError('duplicate SDK archive member')
        for member in members:
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise GateError('unsafe SDK archive member')
            if not (member.name.startswith(('include/glib-2.0/', 'lib/', 'metadata/')) or
                    member.name in {'build.json', 'compilation-audit.json'}):
                raise GateError('unapproved SDK archive member')
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())
        record = read_json(destination / 'build.json')
    if record['profile'] != profile or record['glib_version'] != '2.90.0':
        raise GateError('SDK profile/version mismatch')
    if record['recipe_sha256'] != file_hash(ROOT / 'container/build-foundation.py'):
        raise GateError('SDK recipe changed after build')
    adaptation = read_json(ROOT / 'container/glib-test-compat.json')
    if record['test_source_adaptation'] != adaptation:
        raise GateError('SDK upstream test adaptation changed after build')
    for name, expected in record['files'].items():
        if file_hash(destination / name) != expected:
            raise GateError('SDK file identity mismatch')
    if set(record['files']) != set(names) - {'build.json'}:
        raise GateError('SDK file inventory incomplete')
    if type(record['pcre_upstream_tests']['exit_code']) is not int or record['pcre_upstream_tests']['exit_code'] != 0:
        raise GateError('PCRE2 upstream tests failed or unexecuted')
    # The retained package contains both phase receipts and native Meson rows.
    # Check both exact inventories; neither a duplicate nor a zero-exit wrapper
    # can replace the actual test verdict.
    receipts = record['upstream_core_tests']['executed']
    expected_mode = 'no-undefined' if profile == 'tsan' else 'default'
    if record['upstream_core_tests'].get('mode') != expected_mode:
        raise GateError('SDK upstream test mode mismatch')
    executed = [r for r in receipts if 'phase' in r]
    native = [r for r in receipts if 'name' in r]
    if len(receipts) != 2 * len(TESTS) or len(native) != len(TESTS):
        raise GateError('SDK upstream native verdict inventory incomplete')
    if {r['name'].split(':')[-1] for r in native} != TESTS:
        raise GateError('SDK upstream native test identity mismatch')
    if any(type(r['returncode']) is not int or r['returncode'] != 0 or r['result'] != 'OK' for r in native):
        raise GateError('SDK actual upstream native test failed')
    for result in native:
        command = result['command']
        if not isinstance(command, list) or ('no-undefined' in command) != (profile == 'tsan'):
            raise GateError('SDK native upstream test mode not observed')
    if set(record['upstream_core_tests']['required']) != TESTS or len(executed) != len(TESTS):
        raise GateError('SDK upstream test inventory incomplete')
    for result in executed:
        if type(result['exit_code']) is not int or result['exit_code'] != 0:
            raise GateError('SDK upstream test failed')
    if {r['phase'].removeprefix('upstream-' + profile + '-') for r in executed} != TESTS:
        raise GateError('SDK upstream test identity mismatch')
    audit = read_json(destination / 'compilation-audit.json')
    for component in ['glib', 'pcre2']:
        if len(audit[component]) < 20 or len({r['source'] for r in audit[component]}) != len(audit[component]):
            raise GateError('SDK compilation audit incomplete')
    needed = {lib for row in record['needed_libraries'].values() for lib in row}
    if not needed <= {'libpcre2-8.so.0', 'libc.so.6', 'libm.so.6'}:
        raise GateError('unsupported SDK dynamic closure')
    files = {name: file_hash(destination / name) for name in names}
    return {'files': files, 'build_ids': record['build_ids'],
            'needed_libraries': record['needed_libraries'],
            'compiler_sha256': record['compiler_sha256'], 'flags': record['flags'],
            'prefix': record['prefix'], 'archive_sha256': file_hash(archive),
            'upstream_core_tests': {'ids': sorted(TESTS), 'status': 'PASS',
                                    'mode': expected_mode},
            'compile_audit_sha256': files['compilation-audit.json']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    summary = read_json(args.evidence / 'summary.json')
    if summary.get('all_complete') is not True or set(summary['required']) != PROFILES:
        raise GateError('all ten SDK profiles are mandatory')
    rows = summary['profiles']
    if len(rows) != len(PROFILES) or {row['profile'] for row in rows} != PROFILES:
        raise GateError('SDK profile inventory mismatch')
    current = read_json(ROOT / 'toolchain.lock.json')
    lock = read_json(ROOT / 'foundation.lock.json')
    if current['image_id'] != lock['base_toolchain_image']:
        raise GateError('SDK assembly requires the original exact base toolchain')
    context = Path(tempfile.mkdtemp(prefix='safe-c-sdk-data-'))
    runner = Runner(ROOT, args.evidence / 'assembly', current,
                    Path(tempfile.mkdtemp(prefix='safe-c-sdk-observation-')))
    try:
        profiles = {}
        for row in rows:
            archive = Path(row['archive']).resolve()
            if row['status'] != 'PASS' or not archive.is_relative_to(args.evidence.resolve()) or file_hash(archive) != row['sha256']:
                raise GateError('SDK collected archive identity mismatch')
            profile = row['profile']
            profiles[profile] = unpack(archive, context / 'foundation' / profile, profile)
            compiler = 'gcc' if profile.startswith('gcc') else 'clang'
            if profiles[profile]['compiler_sha256'] != current['tools'][compiler]['sha256']:
                raise GateError('SDK compiler identity mismatch')
        # Read retained base-package licensing as data inside a qualified job.
        copied = runner.run(['python3', '-c',
            'import shutil;shutil.copyfile("/usr/share/doc/libffi8/copyright","/work/libffi-copyright")'],
            label='foundation-libffi-notice')
        if not passed(copied):
            raise GateError('foundation incidental dependency notice unavailable')
        notice = runner.fetch('libffi-copyright', args.evidence / 'assembly/libffi-copyright')
        destination = ROOT / 'third_party/foundation-notices/libffi-copyright'
        shutil.copyfile(notice, destination)
        lock['notices'][str(destination.relative_to(ROOT))] = file_hash(destination)
        launcher = runner.launcher
        base_tag = 'safe-c-foundation-base:' + current['image_id'].split(':')[1][:24]
        tagged = launcher.docker(['tag', current['image_id'], base_tag])
        if not passed(tagged) or launcher.json(['image', 'inspect', base_tag])[0]['Id'] != current['image_id']:
            raise GateError('SDK base image tagging failed')
        (context / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY foundation /opt/foundation\n')
        content = hashlib.sha256(json.dumps(profiles, sort_keys=True).encode()).hexdigest()
        tag = 'safe-c-foundation-sdk:' + content[:24]
        built = launcher.docker(['build', '--pull=false', '--network=none', '--tag', tag,
                                  str(context)], timeout=120, limit=4194304)
        atomic_json(args.evidence / 'assembly/image-build.json', built)
        if not passed(built):
            raise GateError('SDK data image assembly failed')
        image = launcher.json(['image', 'inspect', tag])[0]
        if image['Size'] > launcher.value['aggregate']['owned_image_bytes'] or image['Config'].get('Entrypoint') or image['Config'].get('Volumes'):
            raise GateError('SDK image metadata or storage bound mismatch')
        lock.update(status='ARTIFACTS_QUALIFIED', profiles=profiles,
                    recipe_sha256=file_hash(ROOT / lock['recipe']),
                    sdk_image_id=image['Id'], sdk_image_registry_digest=None,
                    local_patches=[read_json(ROOT / 'container/glib-test-compat.json')],
                    profile_equivalence={'integer': 'ubsan: unsigned wrap checking is first-party only',
                                         'hardened': 'clang-O2', 'gcc-analyzer': 'gcc-O0'})
        current['image_id'] = current['image_manifest'] = image['Id']
        current['foundation'] = {'lock': 'foundation.lock.json', 'base_toolchain_image': lock['base_toolchain_image']}
        atomic_json(ROOT / 'foundation.lock.json', lock)
        atomic_json(ROOT / 'toolchain.lock.json', current)
        print(json.dumps({'status': 'ARTIFACTS_QUALIFIED', 'profiles': len(profiles),
                          'image_id': image['Id'], 'foundation_acceptance': 'PENDING'}))
    finally:
        runner.close()
        shutil.rmtree(runner.scratch)
        shutil.rmtree(context)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__}))
        raise SystemExit(1)
