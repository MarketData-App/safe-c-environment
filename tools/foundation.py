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
    validate(root, 'foundation-lock', lock)
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
    for name in ['foundation-contract-checks','foundation-mutants']:
        from schema_check import validate
        validate(root,name,read_json(root/'safety'/(name+'.json')))
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
    if build['directory'] in {'adapter/foundation-good','adapter/foundation-bad'}:
        if build.get('dependency_profile')!='fuzz':raise GateError('CFL foundation dependency profile missing')
        return 'fuzz'
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


def ordinary_gate(result):
    """Normal validation cannot reinterpret a negative experiment as success."""
    if not passed(result) or result.get('evidence_complete') is not True:
        raise GateError('foundation ordinary workload failed or evidence is incomplete')
    if result.get('binary_unchanged', True) is not True:
        raise GateError('foundation ordinary workload binary changed')
    if re.search(r'GLib[^\n]*(?:CRITICAL|WARNING)|(?:ERROR|WARNING): (?:AddressSanitizer|MemorySanitizer|ThreadSanitizer)|LeakSanitizer|runtime error:|CONTRACT_FAILED|FOUNDATION_ORACLE_FAILED', result['output']):
        raise GateError('foundation ordinary workload emitted a diagnostic')
    return True


def functional_gate(result, property_id):
    if not (result.get('exit_code') == 1 and result.get('failure') is None and
            result.get('evidence_complete') is True and result.get('binary_unchanged') is True and
            result['output'].count('CONTRACT_FAILED ' + property_id + '\n') == 1):
        raise GateError('foundation designated functional observation missing')
    return True


def sdk_gate(root, observed):
    locked = read_json(root / 'foundation.lock.json')['profiles']
    if set(observed) != set(locked):
        raise GateError('foundation SDK profile inventory mismatch')
    if any(observed[name] != record['files'] for name, record in locked.items()):
        raise GateError('foundation SDK header/library/configuration identity mismatch')
    return True


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
    from schema_check import validate
    validate(root, 'foundation-report', value)
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
    runtime = value['runtime']
    if runtime.get('status') == 'PASS':
        if runtime.get('input_binding') != expected:
            raise GateError('foundation runtime binding mismatched')
        receipt = read_json(Path(runtime['evidence_path']))
        for key in ['runtime_image_id', 'binary_sha256', 'image_members', 'input_binding']:
            if runtime.get(key) != receipt.get(key):
                raise GateError('foundation runtime artifact identity mismatched')
    if value['coverage'].get('status') == 'PASS':
        cov = value['coverage']
        if cov.get('denominator') != ['foundation/src/sc-foundation.c', 'foundation/include/sc-foundation.h']:
            raise GateError('foundation coverage denominator mismatched')
        for category, minimum in [('lines', 90), ('branches', 85)]:
            count = cov['totals'][category]['count']
            covered = cov['totals'][category]['covered']
            if count <= 0 or covered < 0 or covered > count or 100 * covered / count < minimum:
                raise GateError('foundation actual coverage below contract')
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
observed={}
for profile,row in lock['profiles'].items():
 observed[profile]={}
 for name,expected in row['files'].items():
  path=pathlib.Path('/opt/foundation')/profile/name
  actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
  observed[profile][name]=actual
  if actual!=expected:errors.append(profile+'/'+name)
print(json.dumps({'status':'FAIL' if errors else 'PASS','mismatched_paths':errors,'profiles':sorted(lock['profiles']),'observed_files':observed}))
sys.exit(bool(errors))'''
    identities = q.runner.run(['python3', '-c', script], label='foundation-sdk-inputs')
    observed = json.loads(identities['output']).get('observed_files', {}) if passed(identities) else {}
    if passed(identities):
        sdk_gate(q.root, observed)
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
            'sdk_evidence_path': identities['evidence_path'], 'observed_files': observed, 'controls': controls,
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
            try:
                clean = ordinary_gate(result)
            except GateError:
                clean = False
            if clean and len(controls) == len(expected) and set(controls) == expected:
                row['library_binding'] = loaded_binding(q, build, result)
                observations=re.findall(r'^CONTRACT_CHECK (F[0-9]{2}/[a-z0-9-]+)$', result['output'], re.M)
                expected_checks={r['id'] for r in read_json(q.root/'safety/foundation-contract-checks.json')['checks']}
                if not expected_checks.issubset(set(observations)) or len(observations)!=len(set(observations)):
                    raise GateError('foundation named property observations incomplete/duplicated')
                row['contract_checks']=sorted(observations)
                row['contract_evidence_path']=result['evidence_path']
                row['controls'] = sorted(controls)
                row['binary_sha256'] = result['binary_sha256']
                recipe = q.executable(build, 'foundation_recipes', label='foundation-recipe-' + name)
                row['evidence_paths'].append(recipe['evidence_path'])
                try:
                    recipe_clean = ordinary_gate(recipe)
                except GateError:
                    recipe_clean = False
                if recipe_clean and recipe['output'].count('FOUNDATION_RECIPE_PASS') == 1:
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


def functional_mutant_checks(q):
    """The same named observation must fail before and pass after each repair."""
    definitions=read_json(q.root/'safety/foundation-mutants.json')
    if file_hash(q.root/definitions['recipe'])!=definitions['recipe_sha256']:
        raise GateError('protected mutation recipe changed')
    rows=[]
    for name,definition in definitions['mutants'].items():
        optimizations=[0,2] if name=='index-guard' else [2]
        for optimization in optimizations:
            guards=('NDEBUG','G_DISABLE_ASSERT','G_DISABLE_CHECKS') if name=='assertion-only' else ()
            row={'id':name+'-O'+str(optimization),'case_id':definition['case_id'],'status':'BLOCKED',
                 'bad':'BLOCKED','control':'BLOCKED','expected_check':definition['expected_check'],
                 'evidence_paths':[],'input_binding':expected_binding(q)}
            bad=q.build('strict',opt=optimization,guards=guards,foundation_mutant=name)
            good=q.build('strict',opt=optimization,guards=guards)
            row['evidence_paths']=[r['evidence_path'] for b in [bad,good] for r in [b['configure'],b['build'],b['links']] if r]
            if q.built(bad) and q.built(good):
                negative=q.executable(bad,'foundation_contracts',[definition['group']],label='foundation-mutant-'+name)
                repaired=q.executable(good,'foundation_contracts',[definition['group']],label='foundation-repaired-'+name)
                row['evidence_paths'] += [negative['evidence_path'],repaired['evidence_path']]
                row['mutation']=bad['mutation']
                row['negative_binary_sha256']=negative['binary_sha256'];row['control_binary_sha256']=repaired['binary_sha256']
                try:
                    functional_gate(negative, definition['expected_check'])
                    row['bad'] = 'PASS'
                except GateError:
                    row['bad'] = 'FAIL'
                row['control']='PASS' if (passed(repaired) and repaired['binary_unchanged'] and
                    repaired['output'].count('CONTRACT_CHECK '+definition['expected_check']+'\n')==1) else 'FAIL'
                row['negative_library_binding']=loaded_binding(q,bad,negative)
                row['control_library_binding']=loaded_binding(q,good,repaired)
                row['status']='PASS' if row['bad']==row['control']=='PASS' else 'FAIL'
            rows.append(row)
            print(json.dumps({'case_id':row['id'],'verdict':row['status']}),flush=True)
    guard_rows=[]
    for guards in [('NDEBUG',),('G_DISABLE_ASSERT',),('G_DISABLE_CHECKS',),('NDEBUG','G_DISABLE_ASSERT','G_DISABLE_CHECKS')]:
        build=q.build('strict',opt=2,guards=guards)
        row={'id':'+'.join(guards),'status':'BLOCKED','controls':[],'evidence_paths':[]}
        if q.built(build):
            result=q.executable(build,'foundation_contracts',label='foundation-explicit-guards')
            row['evidence_paths']=[result['evidence_path']]
            row['controls']=re.findall(r'^CONTRACT_PASS (\w+)$',result['output'],re.M)
            row['contract_checks']=re.findall(r'^CONTRACT_CHECK (F[0-9]{2}/[a-z0-9-]+)$',result['output'],re.M)
            row['library_binding']=loaded_binding(q,build,result)
            row['status']='PASS' if passed(result) and len(row['controls'])==7 and set(row['controls'])==CONTRACT_GROUPS else 'FAIL'
        guard_rows.append(row)
        print(json.dumps({'case_id':'guards-'+row['id'],'verdict':row['status']}),flush=True)
    return {'status':'PASS' if all(r['status']=='PASS' for r in rows+guard_rows) else 'FAIL','mutants':rows,'guard_controls':guard_rows}


def policy_probe_checks(q):
    """Compile real expressions through the same production AST/compiler gates."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('protected_foundation_probes',q.root/'container/foundation-policy-probe.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    definitions=module.definitions();rows=[]
    controls={}
    control_build=q.build('strict')
    if not q.built(control_build):raise GateError('foundation policy control implementation build failed')
    for name in ['approved','comment-only']:
        created=q.runner.run(['python3','/src/container/foundation-policy-probe.py',name],label='foundation-probe-source-'+name)
        observed=q.runner.run(['python3','/src/container/foundation-policy.py','@probe:'+name,'clang-O0','probe-'+name],label='foundation-probe-control-policy-'+name)
        binary='build/strict-clang-O0-policy-'+name+'/probe'
        directory=q.runner.run(['python3','-c','import pathlib,sys;pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)','/work/'+str(Path(binary).parent)],label='foundation-policy-control-directory')
        compiled=q.runner.run(['clang',*analysis_flags('clang-O0'),'-Wall','-Wextra','-Werror','-Wunused-result',
            '/work/foundation-probes/'+name+'/probe.c','/src/foundation/tests/dependency-identity.c',
            '/work/'+control_build['directory']+'/libsc_foundation.a','/opt/foundation/clang-O0/lib/libglib-2.0.so','-Wl,-rpath,/opt/foundation/clang-O0/lib','-ldl','-o','/work/'+binary],label='foundation-probe-control-build-'+name)
        ran=q.executable({'directory':str(Path(binary).parent)},'probe',label='foundation-probe-control-run-'+name) if passed(compiled) else None
        ok=all(passed(r) for r in [created,observed,directory,compiled]) and ran is not None and passed(ran) and json.loads(observed['output']).get('status')=='PASS'
        controls[name]={'status':'PASS' if ok else 'FAIL','evidence_paths':[r['evidence_path'] for r in [created,observed,directory,compiled,ran] if r], 'source_sha256':json.loads(created['output'])['source_sha256'] if passed(created) else None}
    for name,definition in definitions.items():
        if definition['rule'] is None:
            rows.append({'id':name,'status':controls[name]['status'],'control':controls[name]['status'],'evidence_paths':controls[name]['evidence_paths'],'rule':None});continue
        created=q.runner.run(['python3','/src/container/foundation-policy-probe.py',name],label='foundation-probe-source-'+name)
        source='/work/foundation-probes/'+name+'/probe.c'
        ordinary=q.runner.run(['clang',*analysis_flags('clang-O0'),'-fsyntax-only',source],label='foundation-probe-baseline-'+name)
        if name=='ignored-result':
            result=q.runner.run(['clang',*analysis_flags('clang-O0'),'-Werror=unused-result','-fsyntax-only',source],label='foundation-probe-warning-'+name)
            detected=(result['exit_code']==1 and result['failure'] is None and result['evidence_complete'] and
                source in result['output'] and '[-Werror,-Wunused-result]' in result['output'])
            observed={'rule':'unused-result'}
        else:
            result=q.runner.run(['python3','/src/container/foundation-policy.py','@probe:'+name,'clang-O0','probe-'+name],label='foundation-probe-policy-'+name)
            observed=json.loads(result['output']) if result['failure'] is None and result['output'].strip().startswith('{') else {}
            detected=(result['exit_code']==1 and result['failure'] is None and result['evidence_complete'] and observed.get('status')=='FAIL' and
                definition['rule'] in {r['rule'] for r in observed.get('findings',[])})
            if name.startswith('macro-'):detected=detected and any(r.get('macro') is True for r in observed.get('findings',[]))
        control=controls['approved']
        row={'id':name,'status':'PASS' if passed(created) and passed(ordinary) and detected and control['status']=='PASS' else 'FAIL',
             'control':control['status'],'rule':definition['rule'],'findings':observed.get('findings',[]),
             'evidence_paths':[r['evidence_path'] for r in [created,ordinary,result]]+control['evidence_paths'],
             'source_sha256':json.loads(created['output'])['source_sha256'] if passed(created) else None}
        rows.append(row);print(json.dumps({'case_id':'policy-'+name,'verdict':row['status']}),flush=True)
    return {'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL','probes':rows}


def fuzz_adapter_build(q, variant):
    """Reuse the existing ClusterFuzzLite entrypoint and its compiler variables."""
    if variant not in {'good','bad','noop','omitted'}:raise GateError('uninventoried foundation fuzz variant')
    import shlex
    directory='adapter/foundation-'+variant
    env={'CC':'clang','CXX':'clang++','CFLAGS':'-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined,fuzzer-no-link -fno-sanitize-recover=all',
         'CXXFLAGS':'-O1 -g -fsanitize=address,undefined','LIB_FUZZING_ENGINE':'-fsanitize=fuzzer',
         'OUT':'/work/'+directory,'WORK':'/work/'+directory,'SAFETY_QUALIFICATION_VARIANT':'foundation-'+variant}
    result=q.runner.run(['bash','/src/.clusterfuzzlite/build.sh'],env=env,timeout=90,label='foundation-cfl-'+variant+'-build')
    row={'directory':directory,'dependency_profile':'fuzz','result':result,'audit':False,'evidence_paths':[result['evidence_path']], 'objects':[], 'links':None}
    if not passed(result):return row
    receipt=read_json(q.runner.fetch(directory+'/adapter-build.json'))
    if receipt.get('safety_policy_sha256')!=file_hash(q.root/'cmake/Safety.cmake'):raise GateError('CFL production warning policy changed')
    if receipt['variant']!=variant or len(receipt['objects'])!=3:raise GateError('foundation CFL receipt incomplete')
    expected_sources=['foundation/src/sc-foundation.c','foundation/tests/stateful-fuzzer.c','foundation/tests/dependency-identity.c']
    audit=True
    for index,record in enumerate(receipt['objects']):
        collected=q.runner.fetch(record['object'].removeprefix('/work/'))
        if file_hash(collected)!=record['object_sha256']:raise GateError('foundation CFL object substituted')
        if variant=='good' and (record['source']!='/src/'+expected_sources[index] or record['source_sha256']!=file_hash(q.root/expected_sources[index])):
            raise GateError('foundation CFL shipping object source substituted')
        symbols=q.runner.run(['llvm-nm','--undefined-only',record['object']],label='foundation-cfl-'+variant+'-'+str(index)+'-instrumentation')
        row['evidence_paths'].append(symbols['evidence_path'])
        complete=(passed(symbols) and '__asan_report' in symbols['output'] and '__sanitizer_cov' in symbols['output'] and
                  '-fsanitize=address,undefined,fuzzer-no-link' in record['command'] and '-fno-sanitize-recover=all' in record['command'])
        if index==1:
            complete=complete and all(re.search(r'\bsc_'+domain+'_',symbols['output']) for domain in ['text','bytes','list','map'])
        row['objects'].append({'status':'PASS' if complete else 'FAIL','source':record['source'],'source_sha256':record['source_sha256'],
                              'object_sha256':record['object_sha256'],'evidence_path':symbols['evidence_path']})
        audit=audit and complete
    observed=q.runner.run(['python3','-c','import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["link_command"]))','/work/'+directory+'/adapter-build.json'],label='foundation-cfl-link-audit')
    row['evidence_paths'].append(observed['evidence_path'])
    row['links']=dict(observed,output=shlex.join(json.loads(observed['output']))) if passed(observed) else observed
    row['binary_sha256']=receipt['binary_sha256'];row['audit']=bool(audit and passed(observed));return row


def fuzz_checks(q, profile='smoke'):
    """Real stateful oracle, immutable replay, CMake path and CFL path."""
    if profile not in {'smoke','merge','extended'}:raise GateError('unknown foundation fuzz budget')
    records=[];observations=[];status=True
    seed='foundation/tests/regressions/F20'
    seed_hash=file_hash(q.root/seed)
    cmake={variant:q.build('fuzz',foundation_mutant='text-cap' if variant=='bad' else 'NONE') for variant in ['bad','good']}
    adapters={variant:fuzz_adapter_build(q,variant) for variant in ['bad','good','noop','omitted']}
    pairs=[]
    for interface in ['cmake','clusterfuzzlite']:
        pair={'interface':interface,'status':'BLOCKED','bad':'BLOCKED','control':'BLOCKED','seed_sha256':seed_hash,'seed_path':seed,'evidence_paths':[]}
        builds=cmake if interface=='cmake' else adapters
        build_ok=lambda b:q.built(b) if interface=='cmake' else b['audit']
        if all(build_ok(builds[variant]) for variant in ['bad','good']):
            for variant in ['bad','good']:
                build=builds[variant]
                result=q.executable(build,'foundation_fuzzer',['/src/'+seed,'-runs=1'],label='foundation-'+interface+'-'+variant+'-counterexample')
                pair['evidence_paths'].append(result['evidence_path'])
                binding=loaded_binding(q,build,result)
                ok=(result['exit_code']!=0 and type(result['exit_code']) is int and result['failure'] is None and result['evidence_complete'] and
                    result['output'].count('FOUNDATION_ORACLE_FAILED')==1 and result['binary_unchanged']) if variant=='bad' else passed(result) and result['binary_unchanged'] and 'FOUNDATION_ORACLE_FAILED' not in result['output']
                pair['bad' if variant=='bad' else 'control']='PASS' if ok else 'FAIL'
                pair[variant+'_library_binding']=binding
                pair[variant+'_binary_sha256']=result['binary_sha256']
            pair['status']='PASS' if pair['bad']==pair['control']=='PASS' else 'FAIL'
        pairs.append(pair);status=status and pair['status']=='PASS'
        print(json.dumps({'case_id':'foundation-fuzz-'+interface+'-pair','verdict':pair['status']}),flush=True)
    exploration={'status':'BLOCKED'}
    good=adapters['good']
    if good['audit']:
        prepared=q.runner.run(['python3','-c','import pathlib;[pathlib.Path("/work",d).mkdir(exist_ok=True) for d in ["foundation-exploration-corpus","fuzz-failures"]]'],label='foundation-fuzz-collector-directories')
        if not passed(prepared):raise GateError('foundation fuzz collector directory preparation failed')
        limits=read_json(q.root/'safety/contract.json')['budgets']
        amount=limits['smoke_executions'] if profile=='smoke' else limits[profile+'_seconds']
        budget=['-runs='+str(amount)] if profile=='smoke' else ['-max_total_time='+str(amount)]
        result=q.runner.run(['/work/'+good['directory']+'/foundation_fuzzer','/work/foundation-exploration-corpus',*budget,'-seed=12345','-max_len=256','-timeout=3','-rss_limit_mb=1024','-artifact_prefix=/work/fuzz-failures/'],timeout=45 if profile=='smoke' else amount+30,label='foundation-stateful-exploration-'+profile)
        binding=loaded_binding(q,good,result)
        executions=re.findall(r'#(\d+)\s+DONE',result['output']);edges=re.findall(r'cov: (\d+)',result['output']);features=re.findall(r'ft: (\d+)',result['output'])
        listing=q.runner.run(['python3','-c','import pathlib,json;print(json.dumps({d:[str(p.relative_to("/work")) for p in pathlib.Path("/work",d).iterdir()] for d in ["foundation-exploration-corpus","fuzz-failures"]}))'],label='foundation-fuzz-retained-inputs')
        files=json.loads(listing['output']) if passed(listing) else {};retained=[]
        for relative in files.get('foundation-exploration-corpus',[])+files.get('fuzz-failures',[]):
            if not re.fullmatch(r'(foundation-exploration-corpus|fuzz-failures)/[a-zA-Z0-9_-]+',relative):raise GateError('unsafe foundation fuzz output name')
            path=q.runner.fetch(relative,q.runner.run_dir/'foundation-fuzz-inputs'/relative)
            if path.stat().st_size>256:raise GateError('foundation corpus input exceeded bound')
            retained.append({'path':str(path),'sha256':file_hash(path),'bytes':path.stat().st_size})
        ok=passed(result) and passed(listing) and not files.get('fuzz-failures') and bool(executions and edges and features) and int(edges[-1])>30 and (int(executions[-1])>=amount if profile=='smoke' else result['seconds']>=amount)
        exploration={'status':'PASS' if ok else 'FAIL','profile':profile,'budget':amount,'budget_unit':'executions' if profile=='smoke' else 'seconds',
                     'executions':int(executions[-1]) if executions else 0,'edges':int(edges[-1]) if edges else 0,'features':int(features[-1]) if features else 0,
                     'wall_seconds':result['seconds'],'retained_corpus':retained,'library_binding':binding,'evidence_path':result['evidence_path']}
        for path in sorted((q.root/'foundation/corpus').iterdir()):
            replay=q.executable(good,'foundation_fuzzer',['/src/foundation/corpus/'+path.name,'-runs=1'],label='foundation-committed-corpus-replay')
            observations.append({'path':str(path.relative_to(q.root)),'sha256':file_hash(path),'status':'PASS' if passed(replay) else 'FAIL','evidence_path':replay['evidence_path']})
        status=status and ok and all(r['status']=='PASS' for r in observations)
    noop={'status':'PASS' if passed(adapters['noop']['result']) and not adapters['noop']['audit'] else 'FAIL','control':'PASS' if good['audit'] else 'FAIL','evidence_paths':adapters['noop']['evidence_paths']+good['evidence_paths']}
    omitted={'status':'PASS' if not passed(adapters['omitted']['result']) and adapters['omitted']['result']['failure'] is None and 'undefined reference' in adapters['omitted']['result']['output'] and all('sc_'+domain+'_' in adapters['omitted']['result']['output'] for domain in ['text','bytes','list','map']) else 'FAIL','control':'PASS' if good['audit'] else 'FAIL','evidence_paths':adapters['omitted']['evidence_paths']+good['evidence_paths']}
    status=status and noop['status']==omitted['status']=='PASS'
    return {'status':'PASS' if status else 'FAIL','pairs':pairs,'exploration':exploration,'corpus_replays':observations,'noop':noop,'omitted_adapter':omitted,
            'input_binding':expected_binding(q),'cmake_build_audits':{k:v['audit'] for k,v in cmake.items()},'adapter_object_audits':{k:v['objects'] for k,v in adapters.items()},
            'evidence_paths':list(dict.fromkeys([p for pair in pairs for p in pair['evidence_paths']]+[p for v in adapters.values() for p in v['evidence_paths']]+[exploration.get('evidence_path','')]))}
