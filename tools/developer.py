"""Typed developer orchestration; native helpers always use the protected runner."""
from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import uuid
import fcntl
import os
from contextlib import contextmanager

from evidence import GateError, Runner, atomic_json, file_hash, read_json, passed
from policy import source_identity, baseline_identity
from schema_check import validate

OPERATIONS = ['doctor', 'prepare', 'status', 'targets', 'tests', 'build', 'test',
              'nav', 'diagnose', 'replay', 'debug', 'coverage', 'selftest',
              'readiness', 'stop']


def configure_parser(parser):
    operations = parser.add_subparsers(dest='operation', required=True)
    for name in OPERATIONS:
        command = operations.add_parser(name)
        command.add_argument('--format', choices=['text', 'json'], default='text')
        command.add_argument('--profile', default='debug')
        if name in {'build', 'debug'}:
            command.add_argument('--target')
        if name == 'test':
            command.add_argument('--id', dest='test_id', required=True)
        if name in {'diagnose', 'replay', 'debug', 'coverage'}:
            command.add_argument('--run-id')
        if name == 'replay':
            command.add_argument('--snapshot', choices=['original'], required=True)
        if name == 'debug':
            command.add_argument('--recipe', choices=['breakpoint', 'crash'], required=True)
            command.add_argument('--location')
            command.add_argument('--value', action='append', dest='values', default=[])
            command.add_argument('--argument', action='append', dest='arguments', default=[])
            command.add_argument('--steps', type=int, default=0)
        if name == 'nav':
            command.add_argument('--kind', required=True,
                                 choices=['definition', 'references', 'hover',
                                          'document-symbols', 'workspace-symbols', 'diagnostics'])
            command.add_argument('--file')
            command.add_argument('--line', type=int)
            command.add_argument('--column', type=int)
            command.add_argument('--tu')
            command.add_argument('--symbol')


def inputs(root):
    policy = read_json(root / 'safety/developer-policy.json')
    lock = read_json(root / 'developer.lock.json')
    validate(root, 'developer-policy', policy)
    validate(root, 'developer-lock', lock)
    toolchain = read_json(root / 'toolchain.lock.json')
    if (lock['base_image_id'] != toolchain['image_id'] or
            lock['toolchain_lock_sha256'] != file_hash(root / 'toolchain.lock.json') or
            lock['foundation_lock_sha256'] != file_hash(root / 'foundation.lock.json')):
        raise GateError('developer base/toolchain/dependency identity mismatch')
    for path, key in [(lock['extraction_recipe'], 'extraction_recipe_sha256'),
                      (lock['assembly_recipe'], 'assembly_recipe_sha256')]:
        if file_hash(root / path) != lock[key]:
            raise GateError('developer acquisition recipe changed; requalification required')
    seen = set()
    for row in lock['inputs']:
        path = Path(row['path'])
        if path.is_absolute() or '..' in path.parts or str(path) in seen:
            raise GateError('developer input path or inventory invalid')
        seen.add(str(path))
        try:
            if (any(p.is_symlink() for p in [root / path, *(root / path).parents]) or
                    (root / path).stat().st_size != row['bytes'] or
                    file_hash(root / path) != row['sha256']):
                raise GateError('developer retained input changed')
        except OSError as error:
            raise GateError('developer retained input missing') from error
    for row in lock['notices'].values():
        if file_hash(root / row['path']) != row['sha256']:
            raise GateError('developer retained notice changed')
    from foundation import input_gate
    input_gate(root)
    if any(p.suffix in {'.c', '.h'} for folder in ['src', 'include']
           for p in (root / folder).rglob('*')):
        raise GateError('application development is not authorized by developer tooling')
    return policy, lock, toolchain


def namespace(root, profile):
    # Current source revisions are separate from the compatibility namespace.
    # A content edit must not destroy otherwise compatible Ninja/index state.
    origin = read_json(root/'starter-baseline.lock.json')
    fields = {'worktree': hashlib.sha256(str(root.resolve()).encode()).hexdigest(),
              'baseline': origin.get('origin_digest') or hashlib.sha256(
                  (file_hash(root/'safety/contract.json')+file_hash(root/'safety/foundation-api-policy.json')).encode()).hexdigest(), 'profile': profile,
              'toolchain': file_hash(root / 'toolchain.lock.json'),
              'dependency': file_hash(root / 'foundation.lock.json'),
              'developer': file_hash(root / 'developer.lock.json'),
              'policy': file_hash(root / 'safety/developer-policy.json'),
              'adapters': {p: file_hash(root / p) for p in
                  ['tools/developer.py', 'tools/developer_lsp.py', 'tools/developer_gdb.py',
                   'tools/developer_state.py', 'container/developer-job.py',
                   'CMakeLists.txt','cmake/Developer.cmake','cmake/Foundation.cmake','cmake/Safety.cmake']}}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest(), fields


@contextmanager
def admission(root, profile):
    key = hashlib.sha256((str(root.resolve()) + '\0' + profile).encode()).hexdigest()
    directory = root / 'artifacts/developer/admission'
    if any(p.is_symlink() for p in [directory, *directory.parents]):
        raise GateError('development admission directory link rejected')
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / (key + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError as error:
            raise GateError('development worktree/profile already has an active job') from error
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def request(args, policy):
    if args.profile not in policy['profiles']:
        raise GateError('unknown developer profile')
    value = {'operation': args.operation, 'profile': args.profile}
    for name in ['target', 'test_id', 'kind', 'file', 'line', 'column', 'tu', 'symbol',
                 'run_id', 'snapshot', 'recipe', 'location', 'values', 'arguments', 'steps']:
        if hasattr(args, name) and getattr(args, name) is not None:
            value[name] = getattr(args, name)
    if args.operation == 'build' and not value.get('target'):
        raise GateError('developer build requires a registered target')
    if args.operation in {'diagnose', 'replay', 'coverage'} and not value.get('run_id'):
        raise GateError('developer operation requires a retained run identity')
    if value.get('run_id') and not __import__('re').fullmatch(r'[0-9a-f]{32}',value['run_id']):
        raise GateError('invalid developer run identity')
    if args.operation == 'debug':
        import re
        if args.profile != 'debug':
            raise GateError('debug investigation requires the explicitly separate debug profile')
        if bool(value.get('target')) == bool(value.get('run_id')):
            raise GateError('debug requires exactly one registered target or retained run')
        if args.recipe == 'breakpoint':
            location=value.get('location','')
            path,separator,line=location.rpartition(':')
            source=Path(path)
            if (not separator or not line.isascii() or not line.isdecimal() or
                    not 1<=int(line)<=2147483647 or source.is_absolute() or '..' in source.parts or
                    source.suffix not in {'.c','.h'} or any(c in path for c in '\0\n\r')):
                raise GateError('breakpoint requires a registered source path and positive line')
        if (not 0<=args.steps<=policy['limits']['max_source_steps'] or
                len(args.values)>policy['limits']['max_values'] or
                any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*',v) for v in args.values)):
            raise GateError('debug scalar inspection or step budget rejected')
        if len(args.arguments)>16 or any(len(a.encode())>4096 or '\0' in a or '\n' in a or '\r' in a for a in args.arguments):
            raise GateError('literal debug argument bounds rejected')
    if args.operation == 'nav':
        if args.kind == 'workspace-symbols':
            if not value.get('symbol') or len(value['symbol']) > 256:
                raise GateError('workspace symbol query must contain 1–256 characters')
        else:
            if not value.get('file'):
                raise GateError('navigation requires a registered saved source/header file')
            for key in ['file', 'tu']:
                if key in value:
                    path = Path(value[key])
                    if (path.is_absolute() or '..' in path.parts or
                            path.suffix not in {'.c', '.h'} or
                            any(c in value[key] for c in '\0\n\r')):
                        raise GateError('invalid developer source path')
            if args.kind in {'definition', 'references', 'hover'}:
                if any(type(value.get(key)) is not int or not 1 <= value[key] <= 2147483647
                       for key in ['line', 'column']):
                    raise GateError('navigation coordinates are one-based Unicode scalar positions')
    return value


def stop(root, out, lock):
    from container_policy import Launcher, LABEL
    launcher = Launcher(root, out, dict(read_json(root/'toolchain.lock.json'),image_id=lock['image_id']),
                        purpose='development')
    active = root/'artifacts/developer/active'
    rows = []
    try:
        paths = sorted(active.glob('*.json')) if active.is_dir() else []
        if len(paths)>16 or any(p.is_symlink() for p in [active,*active.parents,*paths]):
            raise GateError('development registration inventory bound or link rejected')
        for path in paths:
            row=read_json(path)
            if (row.get('worktree')!=launcher.worktree_scope or
                    not __import__('re').fullmatch(r'[0-9a-f]{32}',row.get('run_id','')) or
                    row.get('image_id')!=lock['image_id']):
                raise GateError('development registration scope/image rejected')
            listed=launcher.docker(['ps','--all','--filter','label=org.safe-c.worktree='+launcher.worktree_scope,
                '--filter','label=org.safe-c.purpose=development',
                '--filter','label=org.safe-c.run='+row['run_id'],'--format','{{.ID}}'])
            if not passed(listed):raise GateError('development stop inventory unavailable')
            for identifier in listed['output'].splitlines():
                actual=launcher.json(['inspect',identifier])[0]
                labels=actual['Config'].get('Labels',{})
                host=actual['HostConfig']
                profile=labels.get('org.safe-c.profile')
                if (labels.get(LABEL)!='1' or labels.get('org.safe-c.worktree')!=launcher.worktree_scope or
                        labels.get('org.safe-c.purpose')!='development' or
                        labels.get('org.safe-c.run')!=row['run_id'] or actual['Image']!=lock['image_id'] or
                        profile not in launcher.value['profiles'] or
                        host.get('Privileged') or host.get('CapAdd') or host.get('CapDrop')!=['ALL'] or
                        host.get('PidMode')!='' or host.get('CgroupnsMode')!='private' or
                        not host.get('ReadonlyRootfs')):
                    raise GateError('development stop refused a foreign or mismatched container')
                before=actual['State']
                if before['Running']:
                    killed=launcher.docker(['kill',actual['Id']],timeout=15)
                    if not passed(killed):raise GateError('registered development cancellation failed')
                after=launcher.json(['inspect',actual['Id']])[0]['State']
                removed=launcher.docker(['rm',actual['Id']],timeout=15)
                absent=not passed(launcher.docker(['inspect',actual['Id']],timeout=15))
                complete=passed(removed) and absent and not after['Running'] and after['Pid']==0
                rows.append({'container_id':actual['Id'],'state_before':before,'state_after':after,
                             'removed':complete,'children_reaped':not after['Running'] and after['Pid']==0})
                if not complete:raise GateError('development cancellation cleanup incomplete')
            atomic_json(active/(row['run_id']+'.cancelled'),{'status':'CANCELLED','containers':rows})
            path.unlink()
        return {'status':'PASS','stopped_containers':len(rows),'cleanup':rows,'global_cleanup':False}
    finally:launcher.close()


def execute(root, args):
    policy, lock, toolchain = inputs(root)
    selected = request(args, policy)
    context, fields = namespace(root, args.profile)
    identity, _ = source_identity(root)
    run_id = uuid.uuid4().hex
    out = root / 'artifacts/developer/runs' / run_id
    out.mkdir(parents=True)
    result = {'schema_version': 1, 'operation': args.operation, 'status': 'BLOCKED',
              'run_id': run_id, 'source_identity': identity, 'profile': args.profile,
              'context_namespace': context, 'scope': 'partial_feedback',
              'acceptance': False, 'evidence_paths': [], 'result': {},
              'limitations': ['Developer feedback does not certify combined acceptance.']}
    if args.operation in {'status', 'readiness'}:
        result['result'] = {'worktree': fields['worktree'], 'configuration': fields,
                            'developer_tooling': 'BLOCKED', 'combined_local_checks': 'BLOCKED',
                            'independent_enforcement': 'PENDING',
                            'scripted_workflow_trial': 'NOT_EXECUTED',
                            'live_agent_trial': 'NOT_EXECUTED', 'handoff_ready': False,
                            'application_started': False, 'production_authorized': False,
                            'reason': 'Developer deterministic suite and workflow trials are incomplete.'}
    elif args.operation=='stop':
        result['result']=stop(root,out,lock)
        result['status']=result['result']['status']
    elif args.operation in {'doctor', 'prepare', 'targets', 'tests', 'build', 'test', 'nav', 'debug'}:
        scratch = Path(tempfile.mkdtemp(prefix='safe-c-developer-job-'))
        runner = Runner(root, out, dict(toolchain, image_id=lock['image_id']), scratch,
                        purpose='development')
        admitted = admission(root,args.profile)
        registered=root/'artifacts/developer/active'/(run_id+'.json')
        try:
            admitted.__enter__()
            runner.start()
            from developer_state import stage, retain
            selected['context_namespace']=context
            selected['state_restored']=stage(root,context,runner,policy['limits'])
            atomic_json(registered,{'run_id':run_id,'worktree':runner.launcher.worktree_scope,
                'image_id':lock['image_id'],'profile':args.profile,'namespace':context})
            outcome = runner.run(['python3', '/src/container/developer-job.py',
                                  json.dumps(selected, ensure_ascii=True)],
                                 timeout=policy['limits']['job_wall_seconds'],
                                 label='developer-' + args.operation)
            result['evidence_paths'].append(outcome['evidence_path'])
            try:
                native = json.loads(outcome['output'])
            except (ValueError, TypeError):
                raise GateError('developer helper returned invalid or incomplete structured evidence')
            result['result'] = native
            result['status'] = 'PASS' if passed(outcome) and native.get('status') == 'PASS' else 'FAIL'
            for path in native.get('artifacts', []):
                relative = Path(path)
                if relative.is_absolute() or '..' in relative.parts or not path.startswith('developer-job/'):
                    raise GateError('developer helper artifact path rejected')
                runner.fetch(path, out / relative)
                result['evidence_paths'].append(str(out / relative))
            if result['status']=='PASS':
                retain(root,context,runner,native,policy['limits'])
            if args.operation=='test' and result['status']=='PASS':
                test=native.get('selected_test',{})
                if test.get('id')!=args.test_id or not test.get('target'):
                    raise GateError('selected developer test evidence is missing or mismatched')
                import re
                runtime='test-'+policy['profiles'][args.profile]['safety_profile']
                executed=runner.run(['ctest','--test-dir','/work/developer-build',
                    '--no-tests=error','-R','^'+re.escape(args.test_id)+'$',
                    '--output-on-failure','--output-junit','/work/selected-ctest.xml'],
                    timeout=10,label='selected-developer-test',
                    ctest_targets=[test['target']],runtime_profile=runtime)
                result['evidence_paths'].append(executed['evidence_path'])
                import xml.etree.ElementTree as ET
                cases=ET.parse(out/'selected-ctest.xml').getroot().findall('.//testcase')
                complete=len(cases)==1 and cases[0].get('name')==args.test_id
                failed=any(cases[0].find(tag) is not None for tag in ['failure','error','skipped']) if complete else True
                result['status']='PASS' if passed(executed) and complete and not failed else 'FAIL'
                result['result']['test_result']={'id':args.test_id,'executed_cases':len(cases),
                    'program_result_preserved':True,'ctest_exit_code':executed['exit_code'],
                    'runtime_profile':runtime,'complete_selection':complete,
                    'binary_sha256':executed['test_binary_hashes'][test['target']]}
        finally:
            cancelled=registered.with_suffix('.cancelled')
            if cancelled.is_file():
                receipt=read_json(cancelled)
                by_id={r['container_id']:r for r in receipt['containers']}
                for record in runner.launcher.records:
                    if record['lifecycle'] is None and record['container_id'] in by_id:
                        record['lifecycle']=by_id[record['container_id']]
                        atomic_json(out/('container-'+record['container_id'][:12]+'.json'),record)
            try:
                runner.close()
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
                if registered.is_file():registered.unlink()
                admitted.__exit__(None,None,None)
    else:
        result['result'] = {'reason': 'This developer responsibility is not implemented yet.'}
    atomic_json(out / 'result.json', result)
    if args.format == 'json':
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(args.operation + ': ' + result['status'] + '; run ' + run_id +
              '; partial feedback; ' + str(out / 'result.json'))
    return 0 if result['status'] == 'PASS' else 1
