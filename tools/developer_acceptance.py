"""Trusted outer aggregation; source-bound developer feedback is not authority."""
from pathlib import Path
import copy
import hashlib
import json

from evidence import GateError,read_json,file_hash,atomic_json,bounded,passed
from policy import source_identity,baseline_identity,validate_fresh_report
from developer_report import qualification

MAINTENANCE={'two-exports','fresh-child-combined','no-grandchildren','portable-payload','runtime-exclusion'}


def load(root,path,expected_digest=None):
    path=Path(path)
    if (not path.is_relative_to(root/'artifacts/developer/runs') or
            path.name!='qualification.json' or any(p.is_symlink() for p in [path,*path.parents])):
        raise GateError('developer prequalification must be this actual worktree owned run')
    if expected_digest and file_hash(path)!=expected_digest:
        raise GateError('developer prequalification outer digest changed')
    value=read_json(path)
    from schema_check import validate
    validate(root,'developer-report',value)
    inventory=read_json(root/'safety/developer-fixtures.json')
    qualification(value,inventory,source_identity(root)[0],read_json(root/'developer.lock.json')['image_id'])
    expected={'worktree':hashlib.sha256(str(root.resolve()).encode()).hexdigest(),
        'inputs':{p:file_hash(root/p) for p in ['developer.lock.json','toolchain.lock.json',
            'foundation.lock.json','safety/developer-policy.json','safety/developer-fixtures.json',
            'safety/container-policy.json']}}
    if value.get('binding')!=expected or path.parent.name!=value['run_id']:
        raise GateError('developer prequalification worktree/policy binding changed')
    receipts=value.get('receipt_hashes',{})
    required={p for case in value['cases'] for row in case['subchecks'] for p in row['evidence_paths']}
    required.update(p for row in value['pipeline_variants'] for p in row['evidence_paths'])
    required.update(row['evidence_path'] for row in value['commands'])
    if set(receipts)!=required or not receipts:
        raise GateError('developer prequalification receipt inventory changed')
    for name,sha in receipts.items():
        p=Path(name)
        if (not p.is_relative_to(root/'artifacts/developer/runs') or
                any(x.is_symlink() for x in [p,*p.parents]) or not p.is_file() or file_hash(p)!=sha):
            raise GateError('developer prequalification receipt missing or changed')
    for case in value['cases']:
        for row in case['subchecks']:
            if case['id']=='E12' and row['name'] in MAINTENANCE:continue
            if row['status']!='PASS' or row['control']!='PASS':
                raise GateError('mandatory local developer experiment did not pass')
    if any(r['status']!='PASS' or r['control']!='PASS' for r in value['pipeline_variants']):
        raise GateError('mandatory developer negative variant did not pass')
    if value['scripted_workflow_trial']!='PASSED':
        raise GateError('developer public workflow rehearsal did not pass')
    return value


def readiness(root,context,fields,selected,identity):
    axes={'developer_tooling':'BLOCKED','combined_local_checks':'BLOCKED',
          'independent_enforcement':'PENDING','scripted_workflow_trial':'NOT_EXECUTED',
          'live_agent_trial':'NOT_EXECUTED','handoff_ready':False,
          'application_started':False,'production_authorized':False}
    report_path=root/'artifacts/developer-qualification-report.json'
    report=read_json(report_path) if report_path.is_file() else None
    if report and report.get('source_identity')==identity:
        from schema_check import validate
        validate(root,'developer-report',report)
        qualification(report,read_json(root/'safety/developer-fixtures.json'),identity,read_json(root/'developer.lock.json')['image_id'])
        axes['developer_tooling']={'PASS':'PASSED','FAIL':'FAILED','BLOCKED':'BLOCKED'}[report['status']]
        axes['scripted_workflow_trial']=report['scripted_workflow_trial']
    combined_path=root/'artifacts/bootstrap-report.json'
    combined=read_json(combined_path) if combined_path.is_file() else None
    if combined and combined.get('source_identity')==identity:
        validate_fresh_report(combined,identity,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
        if combined.get('commands',[])[-1:] == ['./tools/safety ci']:
            axes['combined_local_checks']='PASSED' if combined.get('local_state')=='PASS' else 'FAILED'
        if combined.get('enforcement_state')=='VERIFIED':axes['independent_enforcement']='VERIFIED'
    trial_path=root/'artifacts/developer/live-trial.json'
    trial=read_json(trial_path) if trial_path.is_file() else None
    if trial and trial.get('tooling_identity')==tooling_identity(root):
        axes['live_agent_trial']=trial['status']
    axes['handoff_ready']=(axes['developer_tooling']=='PASSED' and axes['combined_local_checks']=='PASSED' and
        axes['independent_enforcement']=='VERIFIED' and axes['scripted_workflow_trial']=='PASSED' and
        axes['live_agent_trial']=='PASSED' and bool(combined and combined.get('starter',{}).get('status')=='PASS'))
    manifests=root/'artifacts/developer/state'/context/'manifest.json'
    state=read_json(manifests) if manifests.is_file() else None
    current=source_identity(root)[1]
    if selected.get('demo_workspace'):
        from developer_workspace import descriptor
        _,demo=descriptor(root,root/selected['demo_workspace']);current.update({'demo/'+p:d for p,d in demo.items()})
    freshness='MISSING' if state is None else 'CURRENT' if state.get('source_files')==current else 'STALE'
    results=[]
    for path in (root/'artifacts/developer/runs').glob('*/result.json'):
        value=read_json(path)
        if value.get('context_namespace')==context and value.get('source_identity')==identity:
            results.append((path.stat().st_mtime,value))
    results=sorted(results,key=lambda item:item[0],reverse=True)[:8]
    return dict(axes,worktree=fields['worktree'],configuration=fields,index_freshness=freshness,
        debugger_recipes=read_json(root/'safety/developer-policy.json')['debugger']['recipes'],
        last_results=[{'run_id':v['run_id'],'operation':v['operation'],'status':v['status']} for _,v in results],
        reason=None if axes['handoff_ready'] else 'Review the separate evidence axes; missing or stale evidence remains pending.')


def tooling_identity(root):
    paths=['AGENTS.md','docs/agent-development-quickstart.md','prompts/developer-handoff.md',
           'prompts/developer-usability-trial.md','developer.lock.json','foundation.lock.json',
           'safety/developer-policy.json','safety/qualification/developer/template.c',
           'safety/qualification/developer/control.c','safety/qualification/developer/expectations.json',
           'cmake/Developer.cmake','container/developer-job.py','container/developer-argv.py',
           'tools/cli.py','tools/developer.py','tools/developer_lsp.py','tools/developer_gdb.py',
           'tools/developer_bundle.py','tools/developer_state.py','tools/developer_report.py','tools/evidence.py',
           'tools/developer_acceptance.py','tools/developer_workspace.py','tools/developer_coverage.py',
           'specs/developer-commands.md','specs/developer-debug.md','specs/developer-demo.md',
           'schemas/developer-feedback.json','schemas/developer-bundle.json','schemas/developer-report.json',
           'safety/qualification/developer/developer-demo.h','safety/qualification/developer/generated.h.in']
    return hashlib.sha256(json.dumps({p:file_hash(root/p) for p in paths},sort_keys=True).encode()).hexdigest()


def doctor(root,out):
    record=bounded([str(Path(__file__).parent/'safety'),'--candidate',str(root),
                    'dev','doctor','--format','json'],timeout=120,limit=4194304)
    path=out/'developer-doctor.opaque.json';atomic_json(path,record)
    try:
        value=json.loads(record['output'])
        from developer_report import feedback
        from schema_check import validate
        validate(root,'developer-feedback',value);feedback(value)
        ok=passed(record) and value['status']=='PASS' and value['source_identity']==source_identity(root)[0]
    except (ValueError,KeyError,GateError):value={};ok=False
    return {'status':'PASS' if ok else 'BLOCKED','feedback':value,'evidence_paths':[str(path)]}


def project(root,value,combined,*,instance=False):
    """Complete E12 only from current trusted starter and runtime observations."""
    starter=combined['starter'];runtime=combined['containment'].get('runtime_demo',{})
    identity=source_identity(root)[0]
    qualification(value,read_json(root/'safety/developer-fixtures.json'),identity,read_json(root/'developer.lock.json')['image_id'])
    inherited=instance and starter.get('status')=='PASS' and starter.get('scope','').startswith('project-instance;')
    local=(all(r['status']=='PASS' for r in combined['cases']+combined['sabotage']) and
           combined['foundation'].get('status')=='PASS')
    from policy import export_inventory
    payload=export_inventory(root)
    lock=read_json(root/'developer.lock.json')
    payload_ok=all(row['path'] in payload and file_hash(root/row['path'])==row['sha256'] for row in lock['inputs'])
    payload_ok=payload_ok and all(row['path'] in payload and file_hash(root/row['path'])==row['sha256'] for row in lock['notices'].values())
    payload_ok=payload_ok and not any(p.startswith(('artifacts/','.agentwatch/','.direnv/','.env')) for p in payload)
    from runtime import runtime_members
    runtime_ok=(runtime.get('status')=='PASS' and runtime.get('source_identity')==identity and
                set(runtime.get('image_members',{}))==runtime_members())
    grandchildren=list((root/'artifacts/instances').glob('*/*/starter-baseline.lock.json')) if (root/'artifacts/instances').exists() else []
    checks={
        'two-exports':(inherited or (starter.get('status')=='PASS' and len(starter.get('instances',[]))==2)),
        'fresh-child-combined':(local if inherited else starter.get('first_child_full_qualification')=='PASS'),
        'no-grandchildren':(not grandchildren if instance else starter.get('first_child_no_grandchildren') is True),
        'portable-payload':payload_ok,'runtime-exclusion':runtime_ok}
    paths={
        'two-exports':starter.get('evidence_paths',[]) or [str(root/'starter-baseline.lock.json'),str(root/'starter-export.json')],
        'fresh-child-combined':([str(root/'artifacts/foundation-qualification-report.json')] if inherited else [starter.get('first_child_report','')]),
        'no-grandchildren':starter.get('evidence_paths',[]) or [str(root/'starter-baseline.lock.json')],
        'portable-payload':[str(root/'starter-export.json'),str(root/'developer.lock.json')],
        'runtime-exclusion':[runtime['evidence_path']] if runtime.get('evidence_path') else []}
    case=next(r for r in value['cases'] if r['id']=='E12')
    for row in case['subchecks']:
        if row['name'] in MAINTENANCE:
            ok=checks[row['name']] and bool(paths[row['name']])
            row.update(status='PASS' if ok else 'BLOCKED',control='PASS' if ok else 'BLOCKED',
                evidence_paths=paths[row['name']],reason=None if ok else 'Required current outer observation has not passed.',
                details={'scope':'actual instance local gates; outer parent verifies exports and child completion' if instance
                         else 'starter maintenance: two exports and actual fresh child CI'})
    for item in value['cases']:
        states=[r['status'] for r in item['subchecks']];controls=[r['control'] for r in item['subchecks']]
        item['status']='FAIL' if 'FAIL' in states else 'BLOCKED' if 'BLOCKED' in states else 'PASS'
        item['control']='FAIL' if 'FAIL' in controls else 'BLOCKED' if 'BLOCKED' in controls else 'PASS'
    states=[r['status'] for r in value['cases']+value['pipeline_variants']]
    value['status']='FAIL' if 'FAIL' in states else 'BLOCKED' if 'BLOCKED' in states else 'PASS'
    value['runtime']=runtime;value['starter']=starter
    from schema_check import validate
    validate(root,'developer-report',value)
    qualification(value,read_json(root/'safety/developer-fixtures.json'),identity,lock['image_id'])
    atomic_json(root/'artifacts/developer-qualification-report.json',value)
    lines=['# Developer qualification: '+value['status'],'',
        'Independent enforcement: PENDING. Application and production authorization: false.','',
        '| Case | Status | Control | Observations |','|---|---|---|---|']
    lines+=['| '+r['id']+' | '+r['status']+' | '+r['control']+' | '+
        '; '.join(s['name']+': '+s['status'] for s in r['subchecks'])+' |' for r in value['cases']]
    lines+=['','Pipeline variants: '+str(sum(r['status']=='PASS' for r in value['pipeline_variants']))+'/'+str(len(value['pipeline_variants'])),
        'Scripted trial: '+value['scripted_workflow_trial']+'. Live trial is recorded separately.',
        'Source: `'+identity+'`. Image: `'+lock['image_id']+'`.']
    (root/'artifacts/developer-qualification-report.md').write_text('\n'.join(lines)+'\n')
    return value
