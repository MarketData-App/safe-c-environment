"""Single allowlisted payload, immutable safety files, no inherited acceptance."""
from pathlib import Path
import json
import os
import re
import shutil
import tempfile
import gzip
import tarfile
from evidence import GateError, atomic_json, bounded, file_hash, read_json
from policy import export_inventory, baseline_identity, baseline_gate, source_identity, validate_fresh_report

def package_candidate(root, identity):
    version=read_json(root/'starter.json')['version']
    release=root/'artifacts/releases'/('safe-c-'+version+'-'+identity[:16]+'.tar.gz')
    release.parent.mkdir(parents=True,exist_ok=True)
    with release.open('wb') as raw, gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as zipped, tarfile.open(fileobj=zipped,mode='w') as archive:
        for relative in export_inventory(root):
            info=archive.gettarinfo(str(root/relative),arcname=relative)
            info.uid=info.gid=info.mtime=0;info.uname=info.gname=''
            with (root/relative).open('rb') as source:archive.addfile(info,source)
    result={'path':str(release),'sha256':file_hash(release),'payload_digest':identity,'version':version,'exported_files':len(export_inventory(root)),'source_identity':source_identity(root)[0],'state':'CANDIDATE_UNSEALED'}
    atomic_json(release.with_suffix('.manifest.json'),result)
    return result

EXAMPLE='examples/hello-world/'
EXAMPLE_PATHS=('src/','include/','tests/project/','fuzz/project/','specs/project/','review/')
CI_TEMPLATE='ci/project-ci.yml'
CI_WORKFLOW='.github/workflows/project-ci.yml'
MANIFEST='framework-manifest.json'

def project_payload(root):
    """Child-relative project file -> exported example source file."""
    payload={};exported=export_inventory(root)
    for rel in exported:
        tail=rel[len(EXAMPLE):] if rel.startswith(EXAMPLE) else None
        if tail is not None and (tail=='project.json' or tail.startswith(EXAMPLE_PATHS)):payload[tail]=rel
    if 'project.json' not in payload:raise GateError('starter example project is missing: '+EXAMPLE+'project.json')
    if CI_TEMPLATE not in exported:raise GateError('project CI workflow template is missing: '+CI_TEMPLATE)
    payload[CI_WORKFLOW]=CI_TEMPLATE
    # The qualified framework manifest goes to the child root; it is not a source input.
    if (root/MANIFEST).is_symlink():raise GateError('symlink input is forbidden: '+MANIFEST)
    if (root/MANIFEST).is_file():payload[MANIFEST]=MANIFEST
    collisions=sorted(set(payload)&set(exported))
    if collisions:raise GateError('project payload collides with exported framework files: '+', '.join(collisions))
    return payload

def instance_files(root):
    # Child source identity: policy.source_files excludes the copied framework manifest.
    return (set(export_inventory(root))|set(project_payload(root)))-{MANIFEST}

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
        from containment import fresh_container_evidence
        fresh_container_evidence(root,report,read_json(root/'toolchain.lock.json'))
        if report['local_state']!='PASS' or not report['commands'][-1].endswith('ci'):
            raise GateError('starter candidate has no complete current local qualification; run ci')
        # A child without the manifest BLOCKS at its first project check. The maintenance
        # path (verify_starter inside ci) runs before the manifest can exist.
        if (root/MANIFEST).is_symlink():raise GateError('symlink input is forbidden: '+MANIFEST)
        if not (root/MANIFEST).is_file():
            raise GateError(MANIFEST+' is missing; run ./tools/safety framework manifest after a passing ci')
        from project_model import check_manifest
        if check_manifest(root):raise GateError('framework-manifest.json does not match the framework files; run framework manifest')
    origin=baseline_identity(root)
    files=export_inventory(root)
    payload=project_payload(root)
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.starter-stage-',dir=destination.parent))
    try:
        for rel in files:
            p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,p)
        for rel,source in payload.items():
            p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/source,p)
        project=read_json(stage/'project.json');project['name']=name;atomic_json(stage/'project.json',project)
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
    bundle=package_candidate(root,identity)
    instance_root=root/'artifacts/instances'/run_dir.name
    instance_root.mkdir(parents=True,exist_ok=True)
    first=instance_root/'first project with space';second=instance_root/'second-project'
    rows=[instantiate(root,first,'first-project',maintenance=True),instantiate(root,second,'second-project',maintenance=True)]
    expected_files=instance_files(root)
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
    developer_args=[str(root/'tools/safety'),'--candidate',str(first),'dev','selftest','--format','json']
    developer_result=bounded(developer_args,timeout=1200,limit=4*1024*1024)
    atomic_json(run_dir/'starter-child-developer-command.opaque.json',developer_result)
    try:
        developer_feedback=json.loads(developer_result['output'])
        developer_path=first/'artifacts/developer/runs'/developer_feedback['run_id']/'qualification.json'
        from developer_acceptance import load as developer_load
        developer_digest=file_hash(developer_path)
        developer_load(first,developer_path,developer_digest)
        # Standalone developer selftest honestly leaves the five outer E12 rows
        # pending; only this actual child's subsequent combined CI completes them.
        developer_ok=developer_result['failure'] is None and developer_feedback['status']=='BLOCKED'
    except (GateError,KeyError,ValueError,OSError):developer_ok=False
    if not developer_ok:raise GateError('fresh child local developer prequalification did not complete')
    args=[str(root/'tools/safety'),'--candidate',str(first),'--baseline',str(root),'--expected-baseline',identity,
          '--instance','--developer-evidence',str(developer_path),'--developer-evidence-sha256',developer_digest,'ci']
    result=bounded(args,timeout=1200,limit=4*1024*1024)
    atomic_json(run_dir/'starter-child-command.json',result)
    child_report=read_json(first/'artifacts/bootstrap-report.json') if (first/'artifacts/bootstrap-report.json').exists() else None
    full_ok=result['exit_code']==0 and result['failure'] is None and child_report and child_report['local_state']=='PASS'
    no_grandchildren=not list((first/'artifacts/instances').glob('*/*/starter-baseline.lock.json'))
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
    ok=bool(full_ok) and no_grandchildren and pair['status']=='PASS' and tamper_rejected and copied_parent_rejected and unchanged
    return {'status':'PASS' if ok else 'FAIL','starter_version':read_json(root/'starter.json')['version'],'payload_digest':identity,'bundle':bundle,'instances':rows,'first_child_full_qualification':'PASS' if full_ok else 'FAIL','first_child_no_grandchildren':no_grandchildren,'first_child_developer_prequalification':{'path':str(developer_path),'sha256':developer_digest},'first_child_report':str(first/'artifacts/bootstrap-report.json'),'first_child_source_identity':child_report['source_identity'] if child_report else None,'second_child_pair':pair,'nonempty_destination_refused':unchanged,'protected_policy_tampering_rejected':tamper_rejected,'copied_parent_evidence_rejected':copied_parent_rejected,'retained_inputs':'offline: pinned local image and retained files; no acquisition during child qualification','release_authority':'UNSEALED; owner licensing and independent approval pending','evidence_paths':[str(run_dir/'starter-child-command.json'),str(run_dir/'starter-child-developer-command.opaque.json')]}
