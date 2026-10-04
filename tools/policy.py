"""Inventory, provenance and independent-baseline binding (no self approval)."""
from pathlib import Path
import json
import re
import shlex
from evidence import GateError, read_json, file_hash, digest

C_IDS = [f'C{i:02}' for i in range(1, 35)]
P_IDS = [f'P{i:02}' for i in range(1, 17)]

def exact_ids(rows, ids):
    actual = [r.get('id') for r in rows]
    if len(actual) != len(set(actual)) or sorted(actual) != sorted(ids):
        raise GateError(f'inventory mismatch: expected {ids}, got {actual}')

def source_files(root):
    excluded = {'.git', '.cache', 'artifacts', 'build', '.direnv', '.codex', '__pycache__', '.pytest_cache'}
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(part in excluded for part in rel.parts) or rel.name in {'.envrc', '.env', '.env.local'}:
            continue
        if path.is_symlink():
            raise GateError(f'symlink input is forbidden: {rel}')
        if path.is_file():
            result[str(rel)] = file_hash(path)
    return result

def source_identity(root):
    inventory = source_files(root)
    return digest(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()), inventory

def inventory_gate(root, expected_contract=None):
    contract = read_json(root/'safety/contract.json')
    fixtures = read_json(root/'safety/fixtures.json')
    from schema_check import validate
    validate(root, 'contract', contract)
    validate(root, 'source-inventory', read_json(root/'safety/source-inventory.json'))
    validate(root, 'benchmark', read_json(root/'safety/benchmark-manifest.json'))
    validate(root, 'starter-export', read_json(root/'starter-export.json'))
    validate(root, 'toolchain', read_json(root/'toolchain.lock.json'))
    configuration_gate(root)
    exact_ids(contract['cases'], C_IDS)
    exact_ids(contract['sabotage'], P_IDS)
    exact_ids(fixtures['cases'], C_IDS)
    if expected_contract is not None and contract != expected_contract:
        raise GateError('protected contract changed')
    if contract['mode'] == 'bootstrap' and any(p.suffix in {'.c', '.h'} for folder in ['src','include'] for p in (root/folder).rglob('*')):
        raise GateError('bootstrap mode selected despite application sources')
    if contract['mode'] != 'bootstrap':
        raise GateError('production contract transition is not approved in this candidate')
    known = set()
    for record in fixtures['cases']:
        for source in record['bad_sources'] + record['good_sources']:
            known.add(source)
            p = root/source
            if not p.is_file() or p.is_symlink():
                raise GateError('missing fixture: ' + source)
            if record['source_hashes'].get(source) != file_hash(p):
                raise GateError('fixture hash mismatch: ' + source)
        if record['trigger_input']:
            known.add(record['trigger_input'])
            if not (root/record['trigger_input']).is_file():
                raise GateError('missing regression input')
    declared = read_json(root/'safety/source-inventory.json')['files']
    actual = {str(p.relative_to(root)) for p in root.rglob('*.c') if not any(x in p.relative_to(root).parts for x in ['third_party','.git','.cache','artifacts','build'])}
    if actual != set(declared):
        raise GateError('first-party source/target inventory mismatch: ' + str(sorted(actual ^ set(declared))))
    for p in actual:
        if file_hash(root/p) != declared[p]['sha256']:
            raise GateError('source fingerprint changed: ' + p)
    if read_json(root/'safety/exceptions.json')['approved_exceptions']:
        raise GateError('no independently authorized exceptions supplied')
    return {'status':'PASS','sources':sorted(actual),'cases':len(fixtures['cases'])}

def upstream_gate(root):
    lock = read_json(root/'upstream.lock.json')
    from schema_check import validate
    validate(root, 'upstream', lock)
    if not lock['files']:
        raise GateError('empty upstream inventory')
    for row in lock['files']:
        if not re.fullmatch('[0-9a-f]{40}', row['revision']):
            raise GateError('floating upstream revision')
        p = root/row['local_path']
        if not p.is_file() or file_hash(p) != row['local_sha256'] or row['original_sha256'] != row['local_sha256']:
            raise GateError('retained original modified: ' + str(p))
        if not row['license_evidence'] or any(not (root/e).is_file() for e in row['license_evidence']):
            raise GateError('missing license evidence: ' + row['id'])
    for row in lock['adaptations']:
        for field, hashfield in [('original_path','original_sha256'),('local_path','local_sha256'),('patch_path','patch_sha256')]:
            if file_hash(root/row[field]) != row[hashfield]:
                raise GateError('adaptation modified: ' + row[field])
        if set(row['control_sources']) != set(row['control_hashes']):raise GateError('adaptation control inventory changed')
        for source, expected in row['control_hashes'].items():
            if file_hash(root/source)!=expected:raise GateError('adaptation control changed: '+source)
    for distribution in lock['distributions']:
        if file_hash(root/distribution['retained_path']) != distribution['sha256']:raise GateError('retained Python distribution changed')
    if any(not re.fullmatch(r'.+@sha256:[0-9a-f]{64}',value) for value in lock['remote_images'].values()):raise GateError('floating remote compiler/runtime image')
    if not (root/'third_party/NOTICE.md').is_file() or file_hash(root/'third_party/NOTICE.md')!=lock['notice_sha256']:
        raise GateError('missing NOTICE')
    return {'status':'PASS','originals':len(lock['files']),'adaptations':len(lock['adaptations'])}

def export_inventory(root):
    manifest = read_json(root/'starter-export.json')
    files = manifest['files']
    if not files or len(files) != len(set(files)):
        raise GateError('invalid export inventory')
    for rel in files:
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or not (root/p).is_file() or (root/p).is_symlink():
            raise GateError('unsafe/missing export path: ' + rel)
    return files

def payload_hashes(root):
    hashes = {}
    for rel in export_inventory(root):
        if rel == 'starter-baseline.lock.json':
            continue
        if rel == 'starter.json':
            value = read_json(root/rel)
            value.pop('project_name'); value.pop('namespace')
            hashes[rel] = digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
        else:
            hashes[rel] = file_hash(root/rel)
    return hashes

def baseline_identity(root):
    return digest(json.dumps(payload_hashes(root),sort_keys=True,separators=(',',':')).encode())

def baseline_gate(candidate, baseline, expected):
    if not expected or baseline_identity(baseline) != expected:
        raise GateError('external expected baseline identity missing or mismatched')
    if read_json(candidate/'starter-export.json') != read_json(baseline/'starter-export.json'):
        raise GateError('export manifest changed')
    starter=read_json(candidate/'starter.json')
    origin=read_json(candidate/'starter-baseline.lock.json')
    expected_origin={'schema_version':1,'kind':'starter-candidate','origin_digest':None,'independent_approval':False,'substitutions':{}}
    if origin.get('kind')=='project-instance':
        expected_origin.update(kind='project-instance',origin_digest=expected,substitutions={key:starter[key] for key in ['project_name','namespace']})
    if origin!=expected_origin:raise GateError('unauthorized origin / substitution metadata')
    actual, trusted = payload_hashes(candidate), payload_hashes(baseline)
    if actual != trusted:
        raise GateError('protected baseline payload changed: ' + ', '.join(k for k in trusted if actual.get(k)!=trusted[k]))
    return {'status':'PASS','baseline_digest':expected,'authority':'externally supplied; protection must be independently verified'}

def validate_fresh_report(report, source_hash, image, policy_hash):
    if report['source_identity'] != source_hash or report['image_id'] != image or report['policy_identity'] != policy_hash:
        raise GateError('stale/copied evidence input identity mismatch')
    exact_ids(report['cases'],C_IDS)
    exact_ids(report['sabotage'],P_IDS)
    return True

def gate_accounting(rows, required):
    names = [row['name'] for row in rows]
    if len(names) != len(set(names)):
        raise GateError('duplicate gate execution')
    missing = sorted(set(required) - set(names))
    if missing:
        raise GateError('mandatory gates missing: ' + ', '.join(missing))
    return {'status': 'PASS', 'expected': list(required), 'executed': names}

def build_audit(commands, sources, profile):
    flags={'asan':'-fsanitize=address,undefined','ubsan':'-fsanitize=undefined','integer':'-fsanitize=undefined,unsigned-integer-overflow,implicit-integer-conversion','msan':'-fsanitize=memory','tsan':'-fsanitize=thread','fuzz':'-fsanitize=address,undefined,fuzzer-no-link','coverage':'-fcoverage-mapping'}
    found=set()
    for row in commands:
        argv=row.get('arguments') or shlex.split(row['command'])
        rel=row['file'].removeprefix('/src/')
        found.add(rel)
        if '-std=c17' not in argv:
            raise GateError('non-C17 translation unit: '+rel)
        if profile!='ordinary' and not rel.startswith('safety/qualification/'):
            required=['-Wall','-Wextra','-Wpedantic','-Werror','-Wconversion','-Wsign-conversion','-Wshadow','-Wformat=2','-Wformat-security','-Wundef','-Wstrict-prototypes','-Wmissing-prototypes','-Wvla','-Wcast-qual','-Wwrite-strings','-Werror=implicit-function-declaration','-Werror=incompatible-pointer-types']
            if any(flag not in argv for flag in required):raise GateError('mandatory warning flags missing: '+rel)
        if profile in flags and flags[profile] not in argv:
            raise GateError('uninstrumented translation unit: '+rel)
        if any(x.startswith('-fno-sanitize') and x!='-fno-sanitize-recover=all' for x in argv):
            raise GateError('sanitizer disable flag')
    if not set(sources).issubset(found):
        raise GateError('sources missing from compilation database')
    return {'status':'PASS','translation_units':sorted(found),'profile':profile}

def lit_accounting(value, ids):
    rows=value['tests']
    actual=[r['name'].split(' :: ')[-1].removesuffix('.test') for r in rows]
    if sorted(actual)!=sorted(ids) or len(actual)!=len(set(actual)):
        raise GateError('lit inventory missing/duplicate/filtered')
    if any(r['code']!='PASS' for r in rows):
        raise GateError('lit non-PASS/retry status')
    return True

def validate_lit_options(options):
    forbidden={'-n','--no-execute','--ignore-fail','--allow-empty-runs','--filter','--filter-out','--num-shards','--run-shard','--max-failures','--retry-count','--no-progress-bar'}
    if any(option.split('=')[0] in forbidden for option in options):
        raise GateError('prohibited lit execution/filter/retry option')
    return True

def configuration_gate(root):
    safety=(root/'cmake/Safety.cmake').read_text()
    required=['-Werror','-Wconversion','-Wsign-conversion','-Wvla','-fsanitize=address,undefined','-fsanitize=memory','-fsanitize=thread','-fno-sanitize-recover=all']
    if any(flag not in safety for flag in required):
        raise GateError('required warning/instrumentation configuration weakened')
    config=(root/'.clang-tidy').read_text()
    if "Checks: '-*,clang-analyzer-core.*,clang-analyzer-unix.*,bugprone-sizeof-expression'" not in config or "WarningsAsErrors: '*'" not in config:
        raise GateError('required clang-tidy check configuration changed')
    for folder in ['src','include','tests/integration','fuzz']:
        for p in (root/folder).rglob('*'):
            if p.suffix not in {'.c','.h'}:continue
            text=p.read_text()
            if re.search(r'\bno_sanitize\b|sanitize-ignorelist|__SANITIZE_|__has_feature\s*\(\s*(address_sanitizer|memory_sanitizer|thread_sanitizer)',text):
                raise GateError('unauthorized sanitizer suppression or behavior branch: '+str(p))
    return {'status':'PASS'}
