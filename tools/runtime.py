"""Allowlisted image assembly: no candidate commands execute in image builders."""
from pathlib import Path
import io
import json
import tarfile
from evidence import GateError, passed, file_hash, atomic_json

def runtime_smoke(q, *,hold=False):
    build=q.build('hardened',opt=2)
    if not q.built(build):raise GateError('runtime optimized release build failed')
    tested=q.executable(build,'runtime_demo',label='runtime-release-test')
    if not passed(tested):raise GateError('runtime release artifact failed before packaging')
    binary=q.runner.fetch(build['directory']+'/runtime_demo')
    fingerprint=file_hash(binary)
    elf=q.runner.run(['readelf','--wide','-l','-d','/work/'+build['directory']+'/runtime_demo'],label='runtime-dependencies')
    if not passed(elf) or '[libc.so.6]' not in elf['output'] or '/lib64/ld-linux-x86-64.so.2' not in elf['output']:raise GateError('unsupported runtime dependency inventory')
    members={'demo':binary}
    for src,dst in [('/usr/lib/x86_64-linux-gnu/libc.so.6','lib/x86_64-linux-gnu/libc.so.6'),('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','lib64/ld-linux-x86-64.so.2')]:
        rel='runtime-assembly/'+dst
        copy=q.runner.run(['python3','-c','import pathlib,sys,shutil;p=pathlib.Path("/work")/sys.argv[2];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(sys.argv[1],p)',src,rel],label='runtime-copy-dependency')
        if not passed(copy):raise GateError('runtime dependency collection failed')
        members[dst]=q.runner.fetch(rel)
    directory=q.runner.run_dir/'runtime';directory.mkdir(parents=True,exist_ok=True)
    archive=directory/'rootfs.tar'
    with tarfile.open(archive,'w') as tar:
        for name,path in members.items():
            info=tarfile.TarInfo(name);info.mode=0o555;info.uid=info.gid=0;info.mtime=0;info.size=path.stat().st_size
            with path.open('rb') as data:tar.addfile(info,data)
    if archive.stat().st_size>8*1024*1024:raise GateError('runtime assembly archive exceeds fixed bound')
    launcher=q.runner.launcher
    # One project-owned immutable tag. Reuse the identical image; never prune
    # unrelated images/cache and never invoke Docker build/BuildKit here.
    tag='safe-c-runtime-demo:'+fingerprint[:24]
    inspection=launcher.docker(['image','inspect',tag])
    if passed(inspection):image=json.loads(inspection['output'])[0]['Id']
    else:
        listed=launcher.docker(['image','ls','--filter','label=org.safe-c.runtime-demo=1','--format','{{.ID}}'])
        if not passed(listed) or len(set(listed['output'].split()))>=launcher.value['aggregate']['max_owned_images']:raise GateError('owned runtime-image retention budget exhausted; operator must archive/remove only obsolete project images')
        imported=launcher.docker(['import','--change','USER 1001:1001','--change','WORKDIR /work','--change','ENTRYPOINT ["/demo"]','--change','CMD []','--change','LABEL org.safe-c.runtime-demo=1',str(archive),tag],timeout=30)
        if not passed(imported):raise GateError('bounded runtime image assembly failed')
        image=imported['output'].strip()
    obj=launcher.json(['image','inspect',image])[0]
    if obj['Config']['Entrypoint']!=['/demo'] or obj['Config'].get('Volumes') or obj['Config'].get('Healthcheck') or obj['Size']>8*1024*1024:raise GateError('runtime image metadata or size mismatch')
    record=launcher.create('runtime-demo',{},image=image,command=['--hold'])
    try:
        record['effective']=launcher.effective(record['container_id'],record['plan'],python_probe=False)
        # Inspect the actual final filesystem through the supported export API.
        # Container tools/shell are unnecessary; export contains no tmpfs data.
        exported=directory/'final-rootfs.tar'
        export=launcher.docker(['export','--output',str(exported),record['container_id']],timeout=15)
        if not passed(export) or exported.stat().st_size>8*1024*1024:raise GateError('runtime filesystem inventory unavailable/oversized')
        final_members={};managed={}
        with tarfile.open(exported) as tar:
            for member in tar.getmembers():
                name=member.name.removeprefix('./')
                if member.isfile():
                    if name in {'.dockerenv','dev/console','etc/hosts','etc/hostname','etc/resolv.conf'} and member.size==0:
                        managed[name]={'bytes':0,'owner':'Docker-managed marker or bind-mount placeholder'}
                        continue
                    if name not in members:raise GateError('unexpected runtime regular file: '+name)
                    from evidence import digest
                    final_members[name]=digest(tar.extractfile(member).read())
                elif member.issym() and name=='etc/mtab' and member.linkname=='/proc/mounts':
                    managed[name]={'target':member.linkname,'owner':'Docker-managed mount inventory link'}
                elif not member.isdir():raise GateError('unexpected runtime link/special file')
        expected={name:file_hash(path) for name,path in members.items()}
        if final_members!=expected or final_members['demo']!=fingerprint:raise GateError('runtime image does not contain exact tested bytes')
        logs=launcher.docker(['logs',record['container_id']],timeout=5)
        ok=passed(logs) and 'runtime-demo healthy sum=9' in logs['output']
        result={'status':'PASS' if ok else 'FAIL','binary_sha256':fingerprint,'source_identity':__import__('policy').source_identity(q.root)[0],'build_directory':build['directory'],'toolchain_image_id':q.runner.lock['image_id'],'runtime_image_id':image,'registry_digest':None,'image_members':final_members,'entrypoint':obj['Config']['Entrypoint'],'profile':'runtime-demo','container_id':record['container_id'],'container_policy_hash':record['policy_hash'],'effective':record['effective'],'release_test_evidence':tested['evidence_path'],'evidence_path':str(directory/'runtime-smoke.json'),'application_release_ready':False,'production_approval':'NOT_REQUESTED'}
        result['docker_managed_files']=managed
        if hold:return result,record
        wait=launcher.docker(['wait',record['container_id']],timeout=15)
        result['status']='PASS' if ok and passed(wait) and wait['output'].strip()=='0' else 'FAIL'
        result['lifecycle']=launcher.dispose(record)
        atomic_json(Path(result['evidence_path']),result)
        return result
    except Exception:
        launcher.dispose(record);raise
