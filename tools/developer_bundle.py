"""Retained source bytes and typed original-job replay manifests; host data only."""
import json
from pathlib import Path
import re
import shutil
import shlex

from evidence import GateError, atomic_json, file_hash, read_json, RUNTIME_ENV
from policy import source_identity
from schema_check import validate
from developer_state import safe_directory

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 2048
COMPATIBILITY = ['toolchain.lock.json', 'foundation.lock.json', 'developer.lock.json',
                 'safety/container-policy.json', 'safety/developer-policy.json',
                 'safety/foundation-api-policy.json']


def relative_path(value):
    path = Path(value)
    if (not value or path.is_absolute() or '..' in path.parts or
            any(c in value for c in '\0\n\r') or str(path) != value):
        raise GateError('retained bundle path rejected')
    return path


def capture(root, runner, result, request, executed=None):
    directory = runner.run_dir / 'bundle'
    directory.mkdir(exist_ok=True)
    objects = root / 'artifacts/developer/objects'
    safe_directory(objects)
    objects.mkdir(parents=True, exist_ok=True)
    identity, source = source_identity(runner.snapshot)
    if identity != result['source_identity'] or len(source) > MAX_FILES:
        raise GateError('retained source snapshot identity or count mismatch')
    rows, total = {}, 0
    for name, digest in source.items():
        path = runner.snapshot / relative_path(name)
        size = path.stat().st_size
        total += size
        if size > 32 * 1024 * 1024 or total > MAX_BYTES:
            raise GateError('retained source bytes exceed bundle budget')
        destination = objects / digest
        safe_directory(destination)
        if destination.exists():
            if not destination.is_file() or file_hash(destination) != digest:
                raise GateError('retained source object changed')
        else:
            shutil.copy2(path, destination)
            if file_hash(destination) != digest:
                raise GateError('source object changed during retention')
        rows[name] = {'sha256': digest, 'bytes': size, 'executable': bool(path.stat().st_mode & 0o111)}
    native = result['result']
    demo_files={}
    if runner.fixture_root is not None:
        for name,digest in runner.input_binding['developer_demo'].items():
            path=runner.fixture_snapshot/name
            destination=objects/digest
            safe_directory(destination)
            if not destination.exists():shutil.copy2(path,destination)
            if file_hash(destination)!=digest:raise GateError('retained demo source object changed')
            demo_files[name]={'sha256':digest,'bytes':path.stat().st_size,'executable':False}
    selected = native.get('selected_test')
    binary = None
    ctest = None
    if selected:
        fetched = runner.fetch('developer-build/' + selected['target'], directory / 'binary')
        binary = {'path': 'binary', 'sha256': file_hash(fetched), 'bytes': fetched.stat().st_size}
        fetched = runner.fetch('developer-build/CTestTestfile.cmake', directory / 'CTestTestfile.cmake')
        ctest = {'path': 'CTestTestfile.cmake', 'sha256': file_hash(fetched), 'bytes': fetched.stat().st_size}
    manifest = {'schema_version': 1, 'run_id': result['run_id'], 'source_identity': identity,
                'source_files': rows, 'source_bytes': total, 'demo_files':demo_files, 'profile': request['profile'],
                'image_id': runner.lock['image_id'], 'compatibility': {p: file_hash(root/p) for p in COMPATIBILITY},
                'operation': request['operation'], 'request': request,
                'test': selected, 'binary': binary, 'ctest': ctest,
                'fuzz_job':None,
                'argv': executed['command'] if executed else [],
                'environment': dict(executed.get('environment',RUNTIME_ENV) if executed else RUNTIME_ENV), 'cwd': '/work',
                'observed': {'status': result['status'], 'exit_code': executed['exit_code'] if executed else None,
                             'failure': executed['failure'] if executed else None},
                'finding_id': 'DEV-RUN-' + result['run_id'] if result['status'] != 'PASS' else None,
                'evidence_paths': result['evidence_paths'],
                'original_replay_available': selected is not None,
                'reason': None if selected else 'No executable selected test was produced; source bytes retained for investigation.'}
    validate(root, 'developer-bundle', manifest)
    atomic_json(directory / 'manifest.json', manifest)
    if manifest['finding_id']:
        from ledger import Ledger
        units={'tools/developer_bundle.py':['detector receipt accounting; independent review not claimed']}
        ledger=Ledger(identity,units)
        ledger.add({'id':manifest['finding_id'],'origin':'developer selected operation detector',
            'source_identity':identity,'location':('CTest/'+selected['id'] if selected else request['operation']),
            'property':'Selected operation preserves its actual incomplete or failed outcome.',
            'severity':'investigation','rationale':'Advisory feedback requires investigation; no application acceptance claim.',
            'reproducer':'./tools/safety dev replay --run-id '+result['run_id']+' --snapshot original',
            'state':'OPEN','attempts':0,'history':[],'verification':None})
        ledger.account([{'unit':'tools/developer_bundle.py','question':units['tools/developer_bundle.py'][0],
                         'locations':[81]}],identity)
        finding={'schema_version':1,'source_identity':identity,'units':ledger.units,
                 'findings':list(ledger.findings.values()),'review':ledger.review}
        validate(root,'ledger',finding)
        atomic_json(directory.parent/'findings.json',finding)
    return {'path': str(directory/'manifest.json'), 'sha256': file_hash(directory/'manifest.json'),
            'original_replay_available': manifest['original_replay_available'],
            'finding_id': manifest['finding_id']}


def load(root, run_id, lock):
    directory = root / 'artifacts/developer/runs' / run_id / 'bundle'
    safe_directory(directory)
    manifest = read_json(directory/'manifest.json')
    validate(root,'developer-bundle',manifest)
    parent = read_json(directory.parent/'result.json')
    if (manifest['run_id'] != run_id or parent['run_id'] != run_id or
            parent['source_identity'] != manifest['source_identity'] or
            parent['profile'] != manifest['profile'] or
            parent['status'] != manifest['observed']['status'] or
            parent.get('bundle',{}).get('sha256') != file_hash(directory/'manifest.json')):
        raise GateError('failure bundle/parent identity mismatch')
    allowed_images={lock['image_id'],read_json(root/'toolchain.lock.json')['image_id']}
    if manifest['image_id'] not in allowed_images or manifest['compatibility'] != {p:file_hash(root/p) for p in COMPATIBILITY}:
        raise GateError('original profile/image/policy is changed or revoked; original replay blocked')
    for record in [manifest['binary'],manifest['ctest']]:
        if record is None:
            continue
        path=directory/relative_path(record['path'])
        safe_directory(path)
        if not path.is_file() or path.stat().st_size!=record['bytes'] or file_hash(path)!=record['sha256']:
            raise GateError('retained replay executable or test definition changed or missing')
    if manifest['test']:
        selected=manifest['test']
        if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',selected['target']) or
                not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,127}',selected['id']) or
                selected['command'][0]!='/work/developer-build/'+selected['target']):
            raise GateError('retained selected test command rejected')
        expected=['ctest','--test-dir','/work/developer-build','--no-tests=error','-R',
                  '^'+re.escape(selected['id'])+'$','--output-on-failure',
                  '--output-junit','/work/selected-ctest.xml']
        environment=dict(RUNTIME_ENV)
        if manifest['profile']=='coverage':environment['LLVM_PROFILE_FILE']='/work/selected.profraw'
        if manifest['argv']!=expected or manifest['environment']!=environment or manifest['cwd']!='/work':
            raise GateError('retained replay argv/environment/cwd rejected')
    if manifest['fuzz_job']:
        fuzz=manifest['fuzz_job']
        expected=['/work/adapter/'+fuzz['variant']+'/parser_fuzzer','/src/fuzz/regressions/C32','-runs=1']
        if (fuzz['variant'] not in {'bad','good'} or manifest['argv']!=expected or
                manifest['profile']!='fuzz' or manifest['test'] is not None or
                manifest['environment']!=RUNTIME_ENV or fuzz['input']!='fuzz/regressions/C32' or
                manifest['source_files'][fuzz['input']]['sha256']!=fuzz['input_sha256']):
            raise GateError('retained fuzz regression scope/argv/input rejected')
    return manifest,directory


def capture_fuzz(root,runner,result,executed,variant):
    reference=capture(root,runner,result,{'operation':'test','profile':'fuzz'},executed)
    path=Path(reference['path'])
    manifest=read_json(path)
    binary=runner.fetch('adapter/'+variant+'/parser_fuzzer',runner.run_dir/'bundle/binary')
    manifest['binary']={'path':'binary','sha256':file_hash(binary),'bytes':binary.stat().st_size}
    manifest['fuzz_job']={'variant':variant,'input':'fuzz/regressions/C32',
                          'input_sha256':manifest['source_files']['fuzz/regressions/C32']['sha256'],
                          'budget_runs':1,'minimized_input':False}
    manifest['original_replay_available']=True
    manifest['reason']=None
    validate(root,'developer-bundle',manifest)
    atomic_json(path,manifest)
    reference.update(sha256=file_hash(path),original_replay_available=True)
    return reference


def restore_source(root, manifest, destination):
    rows=manifest['source_files']
    if len(rows)>MAX_FILES or sum(r['bytes'] for r in rows.values())>MAX_BYTES:
        raise GateError('retained source inventory exceeds bounds')
    destination.mkdir(parents=True,exist_ok=True)
    for name,record in rows.items():
        relative=relative_path(name)
        source=root/'artifacts/developer/objects'/record['sha256']
        safe_directory(source)
        if not source.is_file() or source.stat().st_size!=record['bytes'] or file_hash(source)!=record['sha256']:
            raise GateError('retained original source bytes are missing or changed')
        target=destination/relative
        safe_directory(target)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        target.chmod(0o755 if record['executable'] else 0o644)
    for name in ['src','include']:(destination/name).mkdir(exist_ok=True)
    if source_identity(destination)[0]!=manifest['source_identity']:
        raise GateError('restored original source identity mismatch')
    return destination


def restore_demo(root,manifest,destination):
    records=manifest['demo_files']
    if not records:return None
    if len(records)>4:raise GateError('retained demo input inventory mismatch')
    destination.mkdir(parents=True,exist_ok=True)
    for name,record in records.items():
        relative=relative_path(name)
        source=root/'artifacts/developer/objects'/record['sha256']
        safe_directory(source)
        if not source.is_file() or file_hash(source)!=record['sha256'] or source.stat().st_size!=record['bytes'] or record['bytes']>1048576:
            raise GateError('retained original demo bytes changed or missing')
        target=destination/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    from developer_workspace import descriptor
    descriptor(root,destination)
    return destination


def diagnose(root, manifest, directory):
    from diagnostic_summary import reduce_file
    summaries=[]
    for raw in manifest['evidence_paths']:
        path=Path(raw)
        if path.is_relative_to(root/'artifacts') and path.is_file() and path.suffix=='.json':
            summaries.extend(reduce_file(path,'DEV_DIAGNOSE'))
    follow_up=['./tools/safety dev replay --run-id '+manifest['run_id']+' --snapshot original',
               './tools/safety dev debug --run-id '+manifest['run_id']+' --recipe crash']
    comparison={'available':False,'reason':'No selected CTest regression; current-source finite fuzz comparison is not exposed.'}
    if manifest['test']:
        protected=[p for p in manifest['source_files'] if p.startswith(('foundation/tests/','tests/',
                   'safety/qualification/developer/')) or p in {'CMakeLists.txt','cmake/Developer.cmake',
                   'cmake/Foundation.cmake','cmake/Safety.cmake','safety/contract.json'}]
        unchanged=bool(protected) and all((root/p).is_file() and
            file_hash(root/p)==manifest['source_files'][p]['sha256'] for p in protected)
        if unchanged:
            argv=['./tools/safety','dev','test','--id',manifest['test']['id'],'--profile',manifest['profile']]
            if manifest['request'].get('demo_workspace'):
                argv+=['--demo-workspace',manifest['request']['demo_workspace']]
            comparison={'available':True,'argv':argv,'command':shlex.join(argv),
                        'scope':'current saved candidate; separate new run and binary identity',
                        'regression_contract_unchanged':True,'original_run_id':manifest['run_id']}
            follow_up.append(comparison['command'])
        else:comparison={'available':False,'reason':'Current test/contract/build inputs differ from the frozen regression.'}
    return {'finding_id':manifest['finding_id'],'original_source_identity':manifest['source_identity'],
            'original_profile':manifest['profile'],'original_outcome':manifest['observed'],
            'diagnostics':summaries[:64], 'bundle':str(directory/'manifest.json'),
            'original_replay_available':manifest['original_replay_available'],
            'current_candidate_comparison':comparison,'follow_up':follow_up}
