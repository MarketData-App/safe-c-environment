"""Single allowlisted payload, immutable safety files, no inherited acceptance."""
from pathlib import Path
import json
import os
import re
import shutil
import tempfile
from evidence import GateError, atomic_json, bounded, file_hash, read_json
from policy import export_inventory, baseline_identity, baseline_gate, source_identity, validate_fresh_report

def instantiate(root, destination, name, *, baseline=None, expected=None, maintenance=False):
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,62}',name):
        raise GateError('project name must be 2–63 lowercase letters/digits/hyphens, starting with a letter')
    destination=Path(destination).absolute()
    for p in [destination,*destination.parents]:
        if p.is_symlink():raise GateError('symlink destination/ancestor rejected')
    destination=destination.resolve()
    if destination==root or destination.is_relative_to(root) or root.is_relative_to(destination):
        if not maintenance:raise GateError('destination must be outside the source repository')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise GateError('destination must be absent or empty; no contents were changed')
    if baseline is not None or expected is not None:
        if baseline is None or expected is None:raise GateError('both independent baseline path and identity are required')
        baseline_gate(root,Path(baseline).resolve(),expected)
    if not maintenance:
        report=read_json(root/'artifacts/bootstrap-report.json')
        current,_=source_identity(root)
        validate_fresh_report(report,current,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
        if report['local_state']!='PASS' or not report['commands'][-1].endswith('ci'):
            raise GateError('starter candidate has no complete current local qualification; run ci')
    origin=baseline_identity(root)
    files=export_inventory(root)
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.starter-stage-',dir=destination.parent))
    try:
        for rel in files:
            p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,p)
        for directory in ['src','include','tests/unit','tests/integration','specs','artifacts']:(stage/directory).mkdir(parents=True,exist_ok=True)
        starter=read_json(stage/'starter.json');starter['project_name']=name;starter['namespace']=name.replace('-','_');atomic_json(stage/'starter.json',starter)
        atomic_json(stage/'starter-baseline.lock.json',{'schema_version':1,'kind':'project-instance','origin_digest':origin,'independent_approval':False,'substitutions':{'project_name':name,'namespace':name.replace('-','_')}})
        baseline_gate(stage,root,origin)
        if destination.exists():destination.rmdir()
        os.rename(stage,destination)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return {'status':'CREATED_UNSEALED','destination':str(destination),'name':name,'origin_digest':origin,'exported_files':len(files),'passing_evidence_inherited':False,'qualification_required':True}

def verify_starter(root,lock,run_dir, *, instance=False, expected=None, baseline=None):
    if instance:
        if not expected or not baseline:raise GateError('instance contract must be selected by the trusted outer baseline')
        value=baseline_gate(root,baseline,expected)
        origin=read_json(root/'starter-baseline.lock.json')
        if origin['kind']!='project-instance' or origin['origin_digest']!=expected:raise GateError('child origin binding changed')
        return {'status':'PASS','scope':'project-instance; maintenance export checks belong to starter CI','baseline_binding':value,'origin':origin,'independent_enforcement':'UNSEALED'}
    identity=baseline_identity(root)
    instance_root=root/'artifacts/instances'/run_dir.name
    instance_root.mkdir(parents=True,exist_ok=True)
    first=instance_root/'first project with space';second=instance_root/'second-project'
    rows=[instantiate(root,first,'first-project',maintenance=True),instantiate(root,second,'second-project',maintenance=True)]
    expected_files=set(export_inventory(root))
    for child in [first,second]:
        actual=set(source_identity(child)[1])
        if actual!=expected_files:raise GateError('exported child inventory mismatch')
        baseline_gate(child,root,identity)
        if (child/'artifacts/bootstrap-report.json').exists():raise GateError('parent acceptance report inherited')
    blocked=instance_root/'nonempty';blocked.mkdir();marker=blocked/'keep.txt';marker.write_text('must preserve');before=file_hash(marker)
    rejected=False
    try:instantiate(root,blocked,'refused-project',maintenance=True)
    except GateError:rejected=True
    unchanged=rejected and file_hash(marker)==before and sorted(x.name for x in blocked.iterdir())==['keep.txt']
    if not unchanged:raise GateError('nonempty destination was not safely refused')
    # Full fresh child qualification uses this exact trusted evaluator and immutable
    # external identity. --instance removes only recursive maintenance export work.
    args=[str(root/'tools/safety'),'--candidate',str(first),'--baseline',str(root),'--expected-baseline',identity,'--instance','ci']
    result=bounded(args,timeout=1200,limit=4*1024*1024)
    atomic_json(run_dir/'starter-child-command.json',result)
    child_report=read_json(first/'artifacts/bootstrap-report.json') if (first/'artifacts/bootstrap-report.json').exists() else None
    full_ok=result['exit_code']==0 and result['failure'] is None and child_report and child_report['local_state']=='PASS'
    # Second child must exercise its actual normal defect/control adapters too.
    from evidence import Runner
    from qualification import Qualifier
    runner=Runner(second,run_dir/'second-child',lock,instance_root/'capture')
    try:pair=Qualifier(second,runner).qualify_case('C01')
    finally:runner.close()
    baseline_gate(second,root,identity)
    policy=second/'cmake/Safety.cmake';original=policy.read_text();policy.write_text(original.replace('-Werror','-Wno-error'))
    tamper_rejected=False
    try:baseline_gate(second,root,identity)
    except GateError:tamper_rejected=True
    policy.write_text(original)
    # A copied parent report cannot certify the actual child identity.
    from cli import initial_report
    copied=initial_report(root,lock);copied['cases']=read_json(root/'safety/fixtures.json')['cases']
    copied_parent_rejected=False
    try:validate_fresh_report(copied,source_identity(second)[0],lock['image_id'],file_hash(root/'safety/contract.json'))
    except GateError:copied_parent_rejected=True
    ok=bool(full_ok) and pair['status']=='PASS' and tamper_rejected and copied_parent_rejected and unchanged
    return {'status':'PASS' if ok else 'FAIL','starter_version':read_json(root/'starter.json')['version'],'payload_digest':identity,'instances':rows,'first_child_full_qualification':'PASS' if full_ok else 'FAIL','first_child_report':str(first/'artifacts/bootstrap-report.json'),'first_child_source_identity':child_report['source_identity'] if child_report else None,'second_child_pair':pair,'nonempty_destination_refused':unchanged,'protected_policy_tampering_rejected':tamper_rejected,'copied_parent_evidence_rejected':copied_parent_rejected,'retained_inputs':'offline: pinned local image and retained files; no acquisition during child qualification','release_authority':'UNSEALED; owner licensing and independent approval pending','evidence_paths':[str(run_dir/'starter-child-command.json')]}
