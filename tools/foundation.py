"""Additive foundation qualification using the existing runner and evaluator.

No native work runs on the host. Dependency/source/instance identities and named
inventories are mandatory; local success never grants independent approval.
"""
from pathlib import Path
import json
import re
from evidence import GateError, read_json, file_hash, passed, atomic_json
from policy import exact_ids

F_IDS = [f'F{i:02}' for i in range(1, 21)]
DEPENDENCY_PROFILES = {'gcc-O0', 'gcc-O2', 'clang-O0', 'clang-O2', 'asan', 'ubsan',
                       'msan', 'tsan', 'coverage', 'fuzz'}
NORMAL_PROFILES = {'gcc-O0', 'gcc-O2', 'clang-O0', 'clang-O2', 'asan', 'ubsan',
                   'integer', 'msan', 'tsan', 'coverage', 'hardened', 'fuzz'}
CONTRACT_GROUPS = {'sizes', 'text', 'bytes', 'lists', 'maps', 'errors', 'cleanup'}


def analysis_flags(profile):
    if profile not in {'gcc-O0', 'clang-O0'}:
        raise GateError('unapproved foundation analyzer dependency profile')
    prefix = '/opt/foundation/' + profile
    return ['-std=c17', '-I/src/fuzz', '-I/src/foundation/include',
            '-I/src/foundation/tests', '-isystem', prefix + '/include/glib-2.0',
            '-isystem', prefix + '/lib/glib-2.0/include',
            '-DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_70',
            '-DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_70']


def input_gate(root, *, artifacts=True):
    lock = read_json(root / 'foundation.lock.json')
    from schema_check import validate
    validate(root, 'foundation-api-policy', read_json(root / 'safety/foundation-api-policy.json'))
    if (lock.get('glib_version') != '2.90.0' or lock.get('minimum_api') != '2.70' or
            lock.get('allocation_profile') != 'glib-fail-stop'):
        raise GateError('foundation dependency/API/allocation policy changed')
    if len(lock['inputs']) != 7 or len({row['name'] for row in lock['inputs']}) != 7:
        raise GateError('foundation input inventory incomplete')
    for row in lock['inputs']:
        if not re.fullmatch(r'[0-9a-f]{64}', row['sha256']) or file_hash(root / row['path']) != row['sha256']:
            raise GateError('foundation retained input identity mismatch')
    if len(lock['notices']) < 16:
        raise GateError('foundation required licensing evidence missing')
    for path, expected in lock['notices'].items():
        if file_hash(root / path) != expected:
            raise GateError('foundation notice identity mismatch')
    if file_hash(root / lock['recipe']) != lock['recipe_sha256']:
        raise GateError('foundation build recipe changed')
    adaptation = read_json(root / 'container/glib-test-compat.json')
    if lock['local_patches'] != [adaptation]:
        raise GateError('foundation upstream adaptation identity changed')
    for key in ['adapter', 'patch']:
        if file_hash(root / adaptation[key]) != adaptation[key + '_sha256']:
            raise GateError('foundation upstream adaptation material changed')
    if artifacts:
        if lock['status'] != 'ARTIFACTS_QUALIFIED' or set(lock['profiles']) != DEPENDENCY_PROFILES:
            raise GateError('mandatory foundation dependency profile unqualified')
        if lock['sdk_image_id'] != read_json(root / 'toolchain.lock.json')['image_id']:
            raise GateError('foundation SDK/toolchain image mismatch')
    return {'status': 'PASS', 'glib_version': lock['glib_version'],
            'source_sha256': next(r['sha256'] for r in lock['inputs'] if r['name'] == 'glib'),
            'lock_sha256': file_hash(root / 'foundation.lock.json'),
            'api_policy_sha256': file_hash(root / 'safety/foundation-api-policy.json'),
            'allocation_profile': lock['allocation_profile'], 'profiles': sorted(lock['profiles'])}


def fixture_inventory(root):
    value = read_json(root / 'safety/foundation-fixtures.json')
    from schema_check import validate
    validate(root, 'foundation-fixtures', value)
    exact_ids(value['cases'], F_IDS)
    if value['allocation_profile'] != 'glib-fail-stop' or value['coverage']['line'] != 90 or value['coverage']['branch'] != 85:
        raise GateError('foundation policy/coverage weakened')
    for row in value['cases']:
        if row['required_control'] is not True or not row['subchecks'] or len(set(row['subchecks'])) != len(row['subchecks']):
            raise GateError('foundation control/subcheck inventory invalid')
        if 'runtime_source' in row and file_hash(root / row['runtime_source']) != row['source_sha256']:
            raise GateError('foundation runtime fixture changed')
    pipeline = value['pipeline_subcases']
    parents = ['P01', 'P02', 'P04', 'P07', 'P10', 'P11', 'P15', 'P16']
    if sorted(r['parent'] for r in pipeline) != parents:
        raise GateError('foundation pipeline subcase inventory incomplete')
    for row in pipeline:
        if not row['variants'] or len(set(row['variants'])) != len(row['variants']):
            raise GateError('foundation pipeline variant inventory invalid')
    return value


def boundary_inventory(root):
    from schema_check import validate
    policy = read_json(root / 'safety/foundation-api-policy.json')
    validate(root, 'foundation-api-policy', policy)
    inventory = read_json(root / 'safety/source-inventory.json')['files']
    if set(policy['boundaries']) != set(policy['boundary_inventory']):
        raise GateError('foundation boundary policy inventory incomplete')
    for path, expected in policy['boundary_inventory'].items():
        actual = inventory.get(path)
        if actual is None or any(actual.get(key) != value for key, value in expected.items()):
            raise GateError('foundation boundary source/role/target mismatch')
        if file_hash(root / path) != actual['sha256']:
            raise GateError('foundation boundary source identity changed')
    return {'status': 'PASS', 'sources': sorted(policy['boundaries'])}


def dependency_profile(build):
    key = build['directory'].removeprefix('build/')
    match = re.match(r'^(ordinary|strict|warnings|gcc-analyzer|asan|ubsan|integer|msan|tsan|coverage|hardened|fuzz)-(gcc|clang)-(O[02])(?:-|$)', key)
    if match is None:
        raise GateError('unknown foundation build profile identity')
    profile, compiler, optimization = match.groups()
    if profile in {'ordinary', 'strict', 'warnings'}:
        return compiler + '-' + optimization
    return {'integer': 'ubsan', 'hardened': 'clang-O2', 'gcc-analyzer': 'gcc-O0'}.get(profile, profile)


def loaded_binding(q, build, result):
    if result.get('input_binding') != expected_binding(q):
        raise GateError('foundation execution source/dependency/runner/instance binding changed')
    profile = dependency_profile(build)
    lock = read_json(q.root / 'foundation.lock.json')
    record = lock['profiles'][profile]
    actual = re.findall(r'^DEPENDENCY_LOADED (\S+)$', result['output'], re.M)
    expected = ['/opt/foundation/' + profile + '/lib/' + name
                for name in ['libglib-2.0.so.0', 'libpcre2-8.so.0']]
    if sorted(actual) != sorted(expected) or len(actual) != len(set(actual)):
        raise GateError('actual loaded dependency profile mismatch')
    # Observe image bytes through the already qualified builder. The fresh
    # native job uses that exact read-only image with no environment fallback.
    script = ('import hashlib,json,sys;'
              'print(json.dumps({p:hashlib.sha256(open(p,"rb").read()).hexdigest() for p in sys.argv[1:]}))')
    observed = q.runner.run(['python3', '-c', script, *expected], label='foundation-loaded-library-hashes')
    if not passed(observed):
        raise GateError('actual loaded library bytes unavailable')
    hashes = json.loads(observed['output'])
    for path in expected:
        if hashes[path] != record['files']['lib/' + Path(path).name]:
            raise GateError('actual loaded library bytes substituted')
    link = build.get('links')
    required = '/opt/foundation/' + profile + '/lib/libglib-2.0.so'
    if link is None or not passed(link) or required not in link['output']:
        raise GateError('foundation actual link dependency unavailable')
    return {'status': 'PASS', 'profile': profile, 'loaded_paths': expected,
            'library_hashes': hashes, 'link_input': required,
            'image_id': q.runner.lock['image_id'],
            'input_binding': dict(result['input_binding']),
            'generated_header_sha256': record['files']['lib/glib-2.0/include/glibconfig.h'],
            'evidence_paths': [result['evidence_path'], observed['evidence_path'], link['evidence_path']]}


def finding_gate(result, case, rule, source, *, origin=False):
    """A designated fixture finding is separate from ordinary workload success."""
    text = result['output']
    if (type(result.get('exit_code')) is not int or result['exit_code'] == 0 or
            result.get('failure') is not None or result.get('evidence_complete') is not True or
            result.get('binary_unchanged') is not True):
        raise GateError('foundation workload infrastructure/status cannot qualify a finding')
    if source not in text:
        raise GateError('foundation finding is not attributable to the intended fixture')
    markers = {
        'leak': ('LeakSanitizer', 'F01_MISSING_CLEANUP_ACCOUNTING'),
        'heap-use-after-free': ('ERROR: AddressSanitizer', 'heap-use-after-free'),
        'uninitialized-value': ('WARNING: MemorySanitizer', 'use-of-uninitialized-value'),
        'data-race': ('WARNING: ThreadSanitizer', 'data race'),
    }
    if rule not in markers or not all(marker in text for marker in markers[rule]):
        raise GateError('foundation designated rule is absent')
    if origin and 'Uninitialized value was created by' not in text:
        raise GateError('foundation uninitialized finding lacks origin evidence')
    return {'status': 'PASS', 'case_id': case, 'rule': rule,
            'exit_code': result['exit_code'], 'source': source,
            'evidence_path': result['evidence_path'],
            'binary_sha256': result['binary_sha256'], 'origin_required': origin}


def fail_stop_gate(result, static_hash):
    text = result['output']
    if (type(result.get('exit_code')) is not int or result['exit_code'] not in {-5, -6, 133, 134} or
            result.get('failure') is not None or result.get('evidence_complete') is not True or
            result.get('binary_unchanged') is not True):
        raise GateError('unrelated termination/container OOM/timeout is not GLib fail-stop evidence')
    if text.count('F19_BACKEND_NULL') != 1 or not re.search(r'failed to allocate 37 bytes', text):
        raise GateError('real GLib backend/fatal path is absent')
    if not re.fullmatch(r'[0-9a-f]{64}', static_hash):
        raise GateError('same-source static GLib test-link identity absent')
    return {'status': 'PASS', 'case_id': 'F19', 'rule': 'glib-fail-stop',
            'exit_code': result['exit_code'], 'static_library_sha256': static_hash,
            'binary_sha256': result['binary_sha256'], 'evidence_path': result['evidence_path'],
            'scope': 'same-source ordinary static test-link variant; shared-image fault injection not claimed'}


def expected_binding(q):
    from containment import expected_binding as container_expected
    value = container_expected(q.root, q.runner.launcher.runner_identity,
                               q.runner.lock['image_id'], q.runner.launcher.value)
    value.update(dependency=file_hash(q.root / 'foundation.lock.json'),
                 api_policy=file_hash(q.root / 'safety/foundation-api-policy.json'),
                 fixture_inventory=file_hash(q.root / 'safety/foundation-fixtures.json'))
    return value


def new_report(q):
    q.runner.start()
    spec = fixture_inventory(q.root)
    return {'schema_version': 1, 'status': 'BLOCKED', 'binding': expected_binding(q),
            'allocation_profile': 'glib-fail-stop',
            'cases': [{'id': row['id'], 'status': 'BLOCKED', 'detector': row['detector'],
                       'bad': 'BLOCKED', 'control': 'BLOCKED',
                       'subchecks': [{'name': name, 'status': 'BLOCKED', 'control': 'BLOCKED',
                                      'evidence_paths': []} for name in row['subchecks']],
                       'evidence_paths': [], 'observations': {}} for row in spec['cases']],
            'profiles': [], 'coverage': {'status': 'BLOCKED'}, 'fuzz': {'status': 'BLOCKED'},
            'runtime': {'status': 'BLOCKED'},
            'sabotage': [{'parent': row['parent'], 'name': row['name'] + '/' + variant,
                          'status': 'BLOCKED', 'control': 'BLOCKED', 'evidence_paths': []}
                         for row in spec['pipeline_subcases'] for variant in row['variants']],
            'application_release_ready': False, 'application_coverage': 'NOT_APPLICABLE',
            'independent_enforcement': 'UNSEALED'}


def validate_report(root, value, expected, *, complete=True):
    if (value.get('schema_version') != 1 or
            value.get('allocation_profile') != 'glib-fail-stop' or
            value.get('application_release_ready') is not False or
            value.get('application_coverage') != 'NOT_APPLICABLE' or
            value.get('independent_enforcement') != 'UNSEALED'):
        raise GateError('foundation report contract/readiness changed')
    if value.get('status') not in {'PASS', 'FAIL', 'BLOCKED'}:
        raise GateError('foundation aggregate status is invalid')
    if value.get('binding') != expected:
        raise GateError('foundation source/dependency/profile/runner/instance binding is stale')
    spec = fixture_inventory(root)
    exact_ids(value['cases'], F_IDS)
    table = {row['id']: row for row in spec['cases']}
    for row in value['cases']:
        required = table[row['id']]
        names = [sub['name'] for sub in row['subchecks']]
        if len(names) != len(set(names)) or set(names) != set(required['subchecks']):
            raise GateError('foundation named subcheck missing/duplicate/mismatched')
        if row['detector'] != required['detector']:
            raise GateError('foundation designated detector changed')
        if row['status'] not in {'PASS', 'FAIL', 'BLOCKED'} or row['control'] not in {'PASS', 'FAIL', 'BLOCKED'} or row['bad'] not in {'PASS', 'FAIL', 'BLOCKED'}:
            raise GateError('foundation status is invalid')
        for sub in row['subchecks']:
            if sub['status'] not in {'PASS', 'FAIL', 'BLOCKED'} or sub['control'] not in {'PASS', 'FAIL', 'BLOCKED'}:
                raise GateError('foundation subcheck status is invalid')
        if row['status'] == 'PASS' and (row['bad'] != 'PASS' or row['control'] != 'PASS' or
                any(sub['status'] != 'PASS' or sub['control'] != 'PASS' or not sub['evidence_paths']
                    for sub in row['subchecks']) or not row['observations'] or not row['evidence_paths']):
            raise GateError('foundation pass lacks a named negative/control/evidence result')
    wanted = {(r['parent'], r['name'] + '/' + variant) for r in spec['pipeline_subcases'] for variant in r['variants']}
    actual = [(r['parent'], r['name']) for r in value['sabotage']]
    if len(actual) != len(set(actual)) or set(actual) != wanted:
        raise GateError('foundation pipeline variant missing/duplicate/mismatched')
    for row in value['sabotage']:
        if row['status'] not in {'PASS', 'FAIL', 'BLOCKED'} or row['control'] not in {'PASS', 'FAIL', 'BLOCKED'}:
            raise GateError('foundation pipeline status is invalid')
        if row['status'] == 'PASS' and (row['control'] != 'PASS' or not row['evidence_paths']):
            raise GateError('foundation pipeline pass lacks control/evidence')
    profiles = value['profiles']
    names = [row['name'] for row in profiles]
    if len(names) != len(set(names)) or not set(names) <= NORMAL_PROFILES:
        raise GateError('foundation normal profile duplicate/unknown')
    for row in profiles:
        if row['status'] not in {'PASS', 'FAIL', 'BLOCKED'}:
            raise GateError('foundation normal profile status invalid')
        if row['status'] == 'PASS':
            if (len(row['controls']) != len(CONTRACT_GROUPS) or
                    set(row['controls']) != CONTRACT_GROUPS or
                    row['build_audit'].get('status') != 'PASS' or
                    not row.get('evidence_paths') or
                    not re.fullmatch(r'[0-9a-f]{64}', row.get('binary_sha256', '')) or
                    not re.fullmatch(r'[0-9a-f]{64}', row.get('recipe_binary_sha256', ''))):
                raise GateError('foundation normal profile lacks executed controls/artifacts')
            profile = {'integer': 'ubsan', 'hardened': 'clang-O2'}.get(row['name'], row['name'])
            locked = read_json(root / 'foundation.lock.json')['profiles'][profile]
            if row['dependency_profile'] != profile:
                raise GateError('foundation normal profile dependency changed')
            for key in ['library_binding', 'recipe_library_binding']:
                observed = row[key]
                paths = ['/opt/foundation/' + profile + '/lib/' + name
                         for name in ['libglib-2.0.so.0', 'libpcre2-8.so.0']]
                hashes = {path: locked['files']['lib/' + Path(path).name] for path in paths}
                if (observed.get('status') != 'PASS' or observed.get('profile') != profile or
                        observed.get('loaded_paths') != paths or
                        observed.get('library_hashes') != hashes or
                        observed.get('image_id') != expected['image'] or
                        observed.get('input_binding') != expected or
                        observed.get('generated_header_sha256') != locked['files']['lib/glib-2.0/include/glibconfig.h']):
                    raise GateError('foundation linked/loaded dependency evidence mismatched')
    if value['status'] == 'PASS' and complete:
        if set(names) != NORMAL_PROFILES or any(row['status'] != 'PASS' for row in profiles):
            raise GateError('foundation mandatory normal profile incomplete')
        if any(r['status'] != 'PASS' or r['control'] != 'PASS' for r in value['cases'] + value['sabotage']):
            raise GateError('foundation aggregate masks a failed case/control')
        for name in ['coverage', 'fuzz', 'runtime']:
            if value[name]['status'] != 'PASS':
                raise GateError('foundation required integration lane is incomplete')
        if value.get('application_release_ready') is not False or value['allocation_profile'] != 'glib-fail-stop':
            raise GateError('foundation readiness/allocation policy changed')
    return True


def doctor(q):
    inputs = input_gate(q.root)
    script = '''import hashlib,json,pathlib,sys
lock=json.load(open('/src/foundation.lock.json'))
errors=[]
for profile,row in lock['profiles'].items():
 for name,expected in row['files'].items():
  path=pathlib.Path('/opt/foundation')/profile/name
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:errors.append(profile+'/'+name)
print(json.dumps({'status':'FAIL' if errors else 'PASS','mismatched_paths':errors,'profiles':sorted(lock['profiles'])}))
sys.exit(bool(errors))'''
    identities = q.runner.run(['python3', '-c', script], label='foundation-sdk-inputs')
    build = q.build('strict')
    controls = []
    if q.built(build):
        for name in ['sizes', 'bytes', 'cleanup']:
            result = q.executable(build, 'foundation_contracts', [name], label='foundation-doctor-' + name)
            binding = loaded_binding(q, build, result)
            controls.append({'name': name, 'status': 'PASS' if passed(result) else 'FAIL',
                             'library_binding': binding, 'evidence_path': result['evidence_path']})
    ok = passed(identities) and q.built(build) and len(controls) == 3 and all(r['status'] == 'PASS' for r in controls)
    return {'status': 'PASS' if ok else 'BLOCKED', 'inputs': inputs,
            'sdk_evidence_path': identities['evidence_path'], 'controls': controls,
            'build_audit': build['audit'], 'minimum_api': '2.70'}


def normal_checks(q, *, full=True):
    matrix = [('gcc-O0', 'strict', 'gcc', 0), ('gcc-O2', 'strict', 'gcc', 2),
              ('clang-O0', 'strict', 'clang', 0), ('clang-O2', 'strict', 'clang', 2)]
    if full:
        matrix += [(name, name, 'clang', 2 if name == 'hardened' else 0)
                   for name in ['asan', 'ubsan', 'integer', 'msan', 'tsan', 'coverage', 'hardened', 'fuzz']]
    rows = []
    for name, profile, compiler, optimization in matrix:
        build = q.build(profile, compiler=compiler, opt=optimization)
        row = {'name': name, 'status': 'FAIL', 'build_audit': build['audit'],
               'dependency_profile': dependency_profile(build), 'controls': [],
               'library_binding': {}, 'evidence_paths': [r['evidence_path'] for r in [build['configure'], build['build']] if r]}
        if q.built(build):
            settings = {'LLVM_PROFILE_FILE': '/work/foundation-contracts.profraw'} if profile == 'coverage' else None
            result = q.executable(build, 'foundation_contracts', env=settings, label='foundation-normal-' + name)
            row['evidence_paths'].append(result['evidence_path'])
            expected = {'sizes', 'text', 'bytes', 'lists', 'maps', 'errors', 'cleanup'}
            controls = re.findall(r'^CONTRACT_PASS (\w+)$', result['output'], re.M)
            if passed(result) and len(controls) == len(expected) and set(controls) == expected:
                row['library_binding'] = loaded_binding(q, build, result)
                row['controls'] = sorted(controls)
                row['binary_sha256'] = result['binary_sha256']
                recipe = q.executable(build, 'foundation_recipes', label='foundation-recipe-' + name)
                row['evidence_paths'].append(recipe['evidence_path'])
                if passed(recipe) and recipe['output'].count('FOUNDATION_RECIPE_PASS') == 1:
                    row['recipe_library_binding'] = loaded_binding(q, build, recipe)
                    row['recipe_binary_sha256'] = recipe['binary_sha256']
                    row['status'] = 'PASS'
            if profile == 'coverage':
                row['coverage_binary'] = build['directory'] + '/foundation_contracts'
        rows.append(row)
        print('foundation profile ' + name + ': ' + row['status'], flush=True)
    return rows


def coverage(q, profiles):
    row = next((r for r in profiles if r['name'] == 'coverage'), None)
    if row is None or row['status'] != 'PASS':
        return {'status': 'BLOCKED', 'reason': 'foundation coverage profile is incomplete'}
    merged = q.runner.run(['llvm-profdata', 'merge', '-sparse', '/work/foundation-contracts.profraw',
                           '-o', '/work/foundation.profdata'], label='foundation-coverage-merge')
    exported = q.runner.run(['llvm-cov', 'export', '-summary-only', '/work/' + row['coverage_binary'],
                             '-instr-profile=/work/foundation.profdata'], label='foundation-coverage-export')
    result = {'status': 'FAIL', 'denominator': ['foundation/src/sc-foundation.c', 'foundation/include/sc-foundation.h'],
              'excluded': ['upstream dependencies', 'negative fixtures', 'test harnesses', 'infrastructure demos'],
              'application_coverage': 'NOT_APPLICABLE',
              'evidence_paths': [merged['evidence_path'], exported['evidence_path']], 'files': [], 'totals': {}}
    if not passed(merged) or not passed(exported):
        return result
    data = json.loads(exported['output'])['data']
    wanted = set(result['denominator'])
    totals = {'lines': {'count': 0, 'covered': 0}, 'branches': {'count': 0, 'covered': 0}}
    for package in data:
        for file in package['files']:
            source = file['filename'].removeprefix('/src/')
            if source not in wanted:
                continue
            summary = file['summary']
            result['files'].append({'source': source, 'summary': summary})
            for category in totals:
                for name in ['count', 'covered']:
                    totals[category][name] += summary[category][name]
    if {r['source'] for r in result['files']} != wanted:
        return result
    for category in totals:
        value = totals[category]
        value['percent'] = 100 * value['covered'] / value['count'] if value['count'] else 0
    result['totals'] = totals
    result['status'] = 'PASS' if totals['lines']['count'] > 0 and totals['branches']['count'] > 0 and totals['lines']['percent'] >= 90 and totals['branches']['percent'] >= 85 else 'FAIL'
    return result


def policy_checks(q):
    from qualification import INFRA
    inventory = read_json(q.root / 'safety/source-inventory.json')['files']
    sources = [name for name, row in inventory.items()
               if name in INFRA or row['role'] == 'foundation-fuzz']
    rows = []
    for index, source in enumerate(sources):
        native = q.runner.run(['python3', '/src/container/foundation-policy.py', source,
                                'clang-O0', 'normal-' + str(index)], label='foundation-ast-' + str(index))
        value = json.loads(native['output']) if passed(native) else {'status': 'FAIL'}
        rows.append({'source': source, 'status': 'PASS' if passed(native) and value.get('status') == 'PASS' else 'FAIL',
                     'evidence_path': native['evidence_path'], 'findings': value.get('findings', [])})
    return {'status': 'PASS' if rows and all(r['status'] == 'PASS' for r in rows) else 'FAIL', 'sources': rows}


def runtime_fixture_checks(q):
    """Execute the designated ownership, initialization, race and backend pairs.

    This returns six component results, not an F01–F20 aggregate. Remaining
    named functional, policy, fuzz and export subchecks are independently required.
    """
    rows = []
    detectors = {'F01': ('asan', 'leak'), 'F02': ('asan', 'heap-use-after-free'),
                 'F03': ('asan', 'heap-use-after-free'),
                 'F17': ('msan', 'uninitialized-value'), 'F18': ('tsan', 'data-race')}
    manifest = {row['id']: row for row in fixture_inventory(q.root)['cases']}
    for case, (profile, rule) in detectors.items():
        row = {'id': case, 'status': 'BLOCKED', 'bad': 'BLOCKED', 'control': 'BLOCKED',
               'evidence_paths': [], 'observations': {}}
        baseline = q.build('ordinary', foundation_case=case)
        build = q.build(profile, foundation_case=case)
        row['evidence_paths'] = [result['evidence_path'] for item in [baseline, build]
                                 for result in [item['configure'], item['build'], item['links']] if result]
        if q.built(baseline) and q.built(build):
            bad = q.executable(build, case + '_bad', label=case + '-designated-negative')
            good = q.executable(build, case + '_good', label=case + '-repaired-control')
            row['evidence_paths'] += [bad['evidence_path'], good['evidence_path']]
            try:
                bad_binding = loaded_binding(q, build, bad)
                good_binding = loaded_binding(q, build, good)
                finding = finding_gate(bad, case, rule, manifest[case]['runtime_source'],
                                       origin=case == 'F17')
                row['bad'] = 'PASS'
                row['control'] = 'PASS' if passed(good) and good['binary_unchanged'] else 'FAIL'
                row['status'] = 'PASS' if row['control'] == 'PASS' else 'FAIL'
                row['observations'] = {'finding': finding, 'negative_library_binding': bad_binding,
                                       'control_library_binding': good_binding,
                                       'control_binary_sha256': good['binary_sha256'],
                                       'ordinary_fixture_build': baseline['audit']}
            except GateError:
                row['status'] = 'BLOCKED' if bad['failure'] or good['failure'] else 'FAIL'
        rows.append(row)
        print(json.dumps({'case_id': case, 'verdict': row['status']}), flush=True)
    case = 'F19'
    build = q.build('ordinary', foundation_case=case)
    row = {'id': case, 'status': 'BLOCKED', 'bad': 'BLOCKED', 'control': 'BLOCKED',
           'evidence_paths': [r['evidence_path'] for r in [build['configure'], build['build'], build['links']] if r],
           'observations': {}}
    if q.built(build):
        import shlex
        profile = dependency_profile(build)
        static_path = '/opt/foundation/' + profile + '/lib/libglib-2.0.a'
        commands = [shlex.split(line) for line in build['links']['output'].splitlines()]
        links = [args for args in commands if '-o' in args and
                 Path(args[args.index('-o') + 1]).name == 'F19_backend']
        if len(links) != 1 or static_path not in links[0] or any('libglib-2.0.so' in arg for arg in links[0]):
            raise GateError('F19 same-source static test linkage unavailable')
        static_hash = read_json(q.root / 'foundation.lock.json')['profiles'][profile]['files']['lib/libglib-2.0.a']
        bad = q.executable(build, 'F19_backend', ['--fail'], label='F19-real-backend-fail-stop')
        good = q.executable(build, 'F19_backend', ['--control'], label='F19-no-injection-control')
        row['evidence_paths'] += [bad['evidence_path'], good['evidence_path']]
        try:
            finding = fail_stop_gate(bad, static_hash)
            row['bad'] = 'PASS'
            row['control'] = 'PASS' if passed(good) and good['output'].count('F19_NO_INJECTION_PASS') == 1 and 'F19_BACKEND_NULL' not in good['output'] else 'FAIL'
            row['status'] = 'PASS' if row['control'] == 'PASS' else 'FAIL'
            row['observations'] = {'finding': finding, 'link_input': static_path,
                                   'input_binding': expected_binding(q),
                                   'control_binary_sha256': good['binary_sha256']}
        except GateError:
            row['status'] = 'BLOCKED' if bad['failure'] or good['failure'] else 'FAIL'
    rows.append(row)
    print(json.dumps({'case_id': case, 'verdict': row['status']}), flush=True)
    return rows
