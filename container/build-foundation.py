"""Offline dependency recipe, executed only inside the qualified Docker builder.

Upstream has its own warning policy. No first-party flags are disabled here.
Every phase and its scratch storage have independent finite Docker ceilings.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

PROFILES = {
    'gcc-O0': ('gcc', '-O0 -g'),
    'gcc-O2': ('gcc', '-O2 -g -fstack-protector-strong'),
    'clang-O0': ('clang', '-O0 -g'),
    'clang-O2': ('clang', '-O2 -g -fstack-protector-strong'),
    'asan': ('clang', '-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all'),
    'ubsan': ('clang', '-O1 -g -fsanitize=undefined -fno-sanitize-recover=all'),
    'msan': ('clang', '-O1 -g -fsanitize=memory -fsanitize-memory-track-origins=2'),
    'tsan': ('clang', '-O1 -g -fsanitize=thread'),
    'coverage': ('clang', '-O0 -g -fprofile-instr-generate -fcoverage-mapping'),
    'fuzz': ('clang', '-O1 -g -fsanitize=address,undefined,fuzzer-no-link -fno-sanitize-recover=all'),
}
UPSTREAM_TESTS = ['bytes', 'string', 'array-test', 'hash', 'error', 'autoptr',
                  'utf8-validate', 'overflow', 'refcount']
ROOT = Path('/work/dependency')
INPUTS = Path('/src/container/foundation-inputs')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(label, argv, env=None, timeout=500):
    log = ROOT / (label + '.log')
    with log.open('wb') as stream:
        result = subprocess.run(argv, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    row = {'phase': label, 'exit_code': result.returncode,
           'command': argv, 'log': str(log), 'log_sha256': sha(log)}
    (ROOT / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    print(json.dumps({k: row[k] for k in ['phase', 'exit_code', 'log']}), flush=True)
    if result.returncode:
        raise RuntimeError(label)
    return row

def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((INPUTS / 'acquisition.json').read_text())
    for row in manifest['inputs']:
        source = Path('/src') / row['path']
        if sha(source) != row['sha256']:
            raise ValueError('retained_input_changed')
        if source.suffix == '.deb':
            run('extract-' + row['name'], ['dpkg-deb', '-x', str(source), str(ROOT / 'tools')])
        elif source.suffix == '.whl':
            with zipfile.ZipFile(source) as archive:
                archive.extractall(ROOT / 'meson')
        elif source.name.endswith(('.tar.xz', '.tar.bz2')):
            with tarfile.open(source) as archive:
                archive.extractall(ROOT, filter='data')
    (ROOT / 'meson-run.py').write_text("import sys\nsys.path.insert(0, '/work/dependency/meson')\nfrom mesonbuild.mesonmain import main\nraise SystemExit(main())\n")
    toolroot = ROOT / 'tools'
    for p in (toolroot / 'usr/lib/x86_64-linux-gnu/pkgconfig').glob('*.pc'):
        p.write_text(p.read_text().replace('prefix=/usr', 'prefix=' + str(toolroot / 'usr')))
    # Incidental GObject/GIO configuration dependencies remain the already locked
    # system runtime bytes. They are neither linked nor approved by the core API.
    for name, target in [('libffi.so', 'libffi.so.8'), ('libz.so', 'libz.so.1')]:
        p = toolroot / 'usr/lib/x86_64-linux-gnu' / name
        p.unlink(missing_ok=True)
        p.symlink_to('/usr/lib/x86_64-linux-gnu/' + target)
    wrapper = ROOT / 'pkg-config'
    wrapper.write_text('#!/bin/sh\nexec /lib64/ld-linux-x86-64.so.2 --library-path ' +
                       str(toolroot / 'usr/lib/x86_64-linux-gnu') + ' ' +
                       str(toolroot / 'usr/bin/pkgconf') + ' "$@"\n')
    wrapper.chmod(0o555)
    print(json.dumps({'phase': 'prepare', 'inputs_verified': len(manifest['inputs'])}))

def settings(profile):
    cc, flags = PROFILES[profile]
    prefix = Path('/opt/foundation') / profile
    pc = ROOT / ('pcre-' + profile)
    build = ROOT / ('glib-' + profile)
    env = dict(os.environ)
    env.update(PYTHONPATH=str(ROOT / 'meson'), CC=cc, CXX='clang++' if cc == 'clang' else 'g++',
               CFLAGS=flags + ' -fno-omit-frame-pointer -fno-strict-aliasing',
               CXXFLAGS=flags + ' -fno-omit-frame-pointer -fno-strict-aliasing',
               PKG_CONFIG=str(ROOT / 'pkg-config'), PKG_CONFIG_PATH='',
               PKG_CONFIG_LIBDIR=str(pc / 'install/lib/pkgconfig') + ':' +
               str(ROOT / 'tools/usr/lib/x86_64-linux-gnu/pkgconfig'),
               LDFLAGS=flags + ' -Wl,-z,relro,-z,now,-rpath,' + str(prefix / 'lib'))
    return cc, flags, prefix, pc, build, env

def meson(*args):
    return ['python3', str(ROOT / 'meson-run.py'), *map(str, args)]

def pcre_configure(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    run('pcre-configure-' + profile, ['cmake', '-S', str(ROOT / 'pcre2-10.46'),
        '-B', str(pc), '-G', 'Ninja', '-DCMAKE_C_COMPILER=' + cc,
        '-DCMAKE_C_FLAGS=' + flags, '-DCMAKE_INSTALL_PREFIX=' + str(pc / 'install'),
        '-DCMAKE_INSTALL_LIBDIR=lib', '-DBUILD_SHARED_LIBS=ON',
        '-DPCRE2_BUILD_PCRE2_8=ON', '-DPCRE2_BUILD_PCRE2_16=OFF',
        '-DPCRE2_BUILD_PCRE2_32=OFF', '-DPCRE2_BUILD_PCRE2GREP=OFF',
        '-DPCRE2_BUILD_TESTS=ON', '-DPCRE2_SUPPORT_JIT=OFF'], env)

def pcre_build(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    run('pcre-build-' + profile, ['cmake', '--build', str(pc), '--parallel', '2'], env)
    run('pcre-install-' + profile, ['cmake', '--install', str(pc)], env)

def glib_configure(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    run('glib-configure-' + profile, meson('setup', build, ROOT / 'glib-2.90.0',
        '--prefix=' + str(prefix), '--libdir=lib', '--wrap-mode=nofallback',
        '--buildtype=plain', '-Ddefault_library=both', '-Db_lundef=false',
        '-Dintrospection=disabled', '-Ddocumentation=false', '-Dman-pages=disabled',
        '-Dsysprof=disabled', '-Dlibelf=disabled', '-Dlibmount=disabled',
        '-Dselinux=disabled', '-Dxattr=false', '-Ddtrace=disabled',
        '-Dsystemtap=disabled', '-Dnls=disabled', '-Dtests=true'), env)

def glib_build(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    run('glib-build-' + profile, ['ninja', '-C', str(build), '-j2',
                                'glib/libglib-2.0.so.0.9000.0', 'glib/libglib-2.0.a'], env)

def upstream_build(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    run('upstream-build-' + profile, ['ninja', '-C', str(build), '-j2',
        *['glib/tests/' + name for name in UPSTREAM_TESTS]], env)

def upstream_test(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    for name in UPSTREAM_TESTS:
        run('upstream-' + profile + '-' + name, [str(build / 'glib/tests' / name)], env, timeout=45)

def package(profile):
    cc, flags, prefix, pc, build, env = settings(profile)
    stage = ROOT / ('package-' + profile)
    stage.mkdir(exist_ok=True)
    def copy(source, relative):
        p = stage / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, p)
        p.chmod(0o644)
    with (ROOT / ('installed-' + profile + '.json')).open('wb') as output:
        subprocess.run(meson('introspect', '--installed', build), env=env, stdout=output, check=True)
    installed = json.loads((ROOT / ('installed-' + profile + '.json')).read_text())
    for source, dest in installed.items():
        if isinstance(dest, str) and dest.startswith(str(prefix)):
            rel = Path(dest).relative_to(prefix)
            if str(rel).startswith('include/glib-2.0/') or str(rel) == 'lib/glib-2.0/include/glibconfig.h':
                copy(Path(source), rel)
    for filename in ['libglib-2.0.so', 'libglib-2.0.so.0', 'libglib-2.0.so.0.9000.0']:
        copy(build / 'glib/libglib-2.0.so.0.9000.0', 'lib/' + filename)
    copy(build / 'glib/libglib-2.0.a', 'lib/libglib-2.0.a')
    for filename in ['libpcre2-8.so', 'libpcre2-8.so.0']:
        copy(next((pc / 'install/lib').glob('libpcre2-8.so.0.*')), 'lib/' + filename)
    copy(build / 'meson-private/glib-2.0.pc', 'lib/pkgconfig/glib-2.0.pc')
    inputs = json.loads((INPUTS / 'acquisition.json').read_text())
    record = {'profile': profile, 'compiler': cc, 'flags': env['CFLAGS'],
              'prefix': str(prefix), 'glib_version': '2.90.0', 'minimum_api': '2.70',
              'meson_version': '1.9.2', 'aliasing': '-fno-strict-aliasing',
              'implicit_downloads': False, 'direct_dependency': 'glib-2.0',
              'runtime_closure': ['libglib-2.0.so.0', 'libpcre2-8.so.0', 'libc.so.6', 'ld-linux-x86-64.so.2'],
              'incidental_config_dependencies': ['system libffi 3.4.8-2', 'system zlib 1.3.1'],
              'upstream_core_tests': UPSTREAM_TESTS,
              'sources': inputs['inputs'], 'recipe_sha256': sha(Path(__file__)),
              'files': {str(p.relative_to(stage)): sha(p) for p in stage.rglob('*') if p.is_file()}}
    (stage / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    archive = ROOT / ('profile-' + profile + '.tar.gz')
    with tarfile.open(archive, 'w:gz') as t:
        for p in sorted(stage.rglob('*')):
            if p.is_file():
                t.add(p, arcname=str(p.relative_to(stage)))
    print(json.dumps({'phase': 'package', 'profile': profile, 'archive': str(archive),
                      'sha256': sha(archive), 'files': len(record['files'])}))

def main():
    if len(sys.argv) != 3 or sys.argv[2] not in PROFILES:
        raise ValueError('typed_recipe_arguments')
    phase, profile = sys.argv[1:]
    actions = {'prepare': lambda p: prepare(), 'pcre-configure': pcre_configure,
               'pcre-build': pcre_build, 'glib-configure': glib_configure,
               'glib-build': glib_build, 'upstream-build': upstream_build,
               'upstream-test': upstream_test, 'package': package}
    actions[phase](profile)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__}), flush=True)
        sys.exit(1)
