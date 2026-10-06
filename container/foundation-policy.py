"""Finite native AST reduction for the existing trusted policy evaluator.

Run inside the qualified builder. Native compiler output and the complete AST
stay opaque on disk; stdout contains only rule IDs, identifiers and file paths.
The exact SDK public/generated headers are imported through an actual Clang PCH
so unrelated GLib header declarations are not treated as application API uses.
"""
from pathlib import Path
import json
import re
import subprocess
import sys

sys.path.insert(0, '/src/tools')
from qualification import ast_banned_calls, ast_foundation_uses


def main():
    arguments = sys.argv[1:]
    if len(arguments) < 3:
        raise ValueError('typed_policy_arguments')
    source, profile, label = arguments[:3]
    extra = arguments[3:]
    includes = []
    while extra:
        if len(extra) < 2 or extra[0] != '--include':
            raise ValueError('typed_policy_arguments')
        directory_argument = extra[1]
        if not directory_argument.startswith('/src/') or '..' in Path(directory_argument).parts:
            raise ValueError('typed_policy_include_under_src_required')
        includes.append('-I' + directory_argument)
        extra = extra[2:]
    if '..' in Path(source).parts or Path(source).is_absolute():
        raise ValueError('relative_source_required')
    if not label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('typed_policy_label_required')
    lock = json.loads(Path('/src/foundation.lock.json').read_text())
    if profile not in lock['profiles']:
        raise ValueError('locked_policy_profile_required')
    prefix = Path('/opt/foundation') / profile
    directory = Path('/work/foundation-policy') / label
    directory.mkdir(parents=True, exist_ok=True)
    flags = ['-std=c17', '-I/src/foundation/include', '-I/src/foundation/tests', '-I/src/fuzz',
             *includes,
             '-isystem', str(prefix / 'include/glib-2.0'),
             '-isystem', str(prefix / 'lib/glib-2.0/include'),
             '-DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_70',
             '-DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_70']
    # A PCH must see the primary source's feature-test macro before libc headers.
    # Match only its leading definition, with the same empty replacement text.
    primary=Path('/src',source)
    policy_source=source
    if source.startswith('@probe:'):
        import importlib.util,hashlib
        name=source.removeprefix('@probe:')
        module_spec=importlib.util.spec_from_file_location('protected_probes','/src/container/foundation-policy-probe.py')
        module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
        definitions=module.definitions()
        if name not in definitions:raise ValueError('inventoried_policy_probe_required')
        primary=Path('/work/foundation-probes')/name/'probe.c'
        if primary.is_symlink() or primary.read_text()!=definitions[name]['source']:raise ValueError('probe_identity_changed')
        policy_source='foundation/src/impostor.c' if name=='renamed-application' else 'foundation-probes/'+name+'/probe.c'
    leading = primary.read_text().split('#include', 1)[0]
    if re.search(r'^\s*#\s*define\s+_GNU_SOURCE\s*$', leading, re.M):
        flags.append('-D_GNU_SOURCE=')
    pch = directory / 'public.pch'
    commands = [
        ['clang', *flags, '-x', 'c-header', '/src/foundation/include/sc-foundation.h', '-o', str(pch)],
        ['clang', *flags, '-include-pch', str(pch), '-Xclang', '-ast-dump=json',
         '-fsyntax-only', str(primary)],
    ]
    for index, command in enumerate(commands):
        output = directory / ('native-' + str(index) + '.json')
        errors = directory / ('native-' + str(index) + '.log')
        with output.open('wb') as stream, errors.open('wb') as diagnostics:
            result = subprocess.run(command, stdout=stream, stderr=diagnostics, timeout=45)
        if result.returncode or output.stat().st_size > 32 * 1024 * 1024:
            print(json.dumps({'status': 'BLOCKED', 'source': source,
                              'exit_code': result.returncode, 'file_path': str(errors)}))
            return 2
    tree = json.loads(output.read_text())
    policy = json.loads(Path('/src/safety/foundation-api-policy.json').read_text())
    inventory = json.loads(Path('/src/safety/source-inventory.json').read_text())['files']
    findings = ast_foundation_uses(tree, policy, policy_source, inventory)
    for name in ast_banned_calls(tree):
        findings.append({'rule': 'existing-api-policy', 'name': name, 'source': source})
    print(json.dumps({'status': 'FAIL' if findings else 'PASS', 'source': source,
                      'profile': profile, 'findings': findings,
                      'ast_path': str(output), 'pch_path': str(pch)}))
    return 1 if findings else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(error).__name__}))
        raise SystemExit(2)
