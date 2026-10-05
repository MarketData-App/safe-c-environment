"""Outer-controller transfer of locked image data; never launch a workload."""
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid

from evidence import GateError, read_json, atomic_json, passed
from container_policy import Launcher

ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=3*1024**3
MAX_MEMBERS=4096
MAX_METADATA=1024**2
SECONDS=120
DOCKER_SETTINGS=['DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY',
                 'DOCKER_CERT_PATH','DOCKER_API_VERSION','DOCKER_CONFIG']


def regular(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]) or not path.is_file():
        raise GateError('regular image archive required')
    if not 0<path.stat().st_size<=MAX_BYTES:
        raise GateError('image archive byte bound exceeded')
    return path


def stream_copy(source,destination,*,maximum=MAX_BYTES):
    total=0;sha=hashlib.sha256();start=time.monotonic()
    while block:=source.read(1024**2):
        total+=len(block)
        if total>maximum or time.monotonic()-start>SECONDS:
            raise GateError('image data transfer bound exceeded')
        sha.update(block);destination.write(block)
    return total,sha.hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise GateError('duplicate image metadata key')
        result[key]=value
    return result


def metadata(archive,member):
    if member.size>MAX_METADATA:raise GateError('image metadata byte bound exceeded')
    return json.loads(archive.extractfile(member).read(),object_pairs_hook=unique)


def inspect_archive(path,expected):
    """Validate Docker-save data and config identities without extracting layers."""
    wanted=set(expected)
    if len(wanted)!=2 or any(not re.fullmatch(r'sha256:[0-9a-f]{64}',p) for p in wanted):
        raise GateError('exactly two immutable image identities required')
    start=time.monotonic()
    with tarfile.open(path,'r:') as archive:
        members={};total=0
        for member in archive:
            name=PurePosixPath(member.name)
            if (name.is_absolute() or '..' in name.parts or str(name)!=member.name or
                    member.name in members or not (member.isfile() or member.isdir())):
                raise GateError('image archive member rejected')
            if member.size<0 or member.offset_data+member.size>path.stat().st_size:
                raise GateError('image archive member truncated')
            members[member.name]=member;total+=member.size
            if len(members)>MAX_MEMBERS or total>MAX_BYTES or time.monotonic()-start>SECONDS:
                raise GateError('image archive inventory bound exceeded')
        if 'manifest.json' not in members or not members['manifest.json'].isfile():
            raise GateError('Docker-save manifest required')
        rows=metadata(archive,members['manifest.json'])
        if not isinstance(rows,list) or len(rows)!=2:raise GateError('image manifest inventory mismatch')
        found=set();allowed={'manifest.json'};docker_layers={}
        for row in rows:
            if not isinstance(row,dict) or not {'Config','Layers','RepoTags'}<=set(row):
                raise GateError('image manifest row malformed')
            config_name=row['Config'];layers=row['Layers']
            if not isinstance(config_name,str) or config_name not in members or not members[config_name].isfile():
                raise GateError('image config missing')
            config_member=members[config_name]
            if config_member.size>MAX_METADATA:raise GateError('image config byte bound exceeded')
            content=archive.extractfile(config_member).read()
            identity='sha256:'+hashlib.sha256(content).hexdigest()
            if identity in found:raise GateError('duplicate runnable image config')
            found.add(identity);config=json.loads(content,object_pairs_hook=unique)
            settings=config.get('config',{})
            if (config.get('architecture')!='amd64' or config.get('os')!='linux' or
                    any(settings.get(k) for k in ['Entrypoint','Volumes','Healthcheck'])):
                raise GateError('image runtime configuration rejected')
            if not isinstance(layers,list) or not layers or len(set(layers))!=len(layers):
                raise GateError('image layer inventory malformed')
            if any(not isinstance(p,str) or p not in members or not members[p].isfile() for p in layers):
                raise GateError('image layer missing')
            if len(config.get('rootfs',{}).get('diff_ids',[]))!=len(layers):
                raise GateError('image layer/config inventory disagreement')
            allowed.update([config_name,*layers])
            docker_layers[identity]=layers
        if 'index.json' in members:
            allowed.update(['index.json','oci-layout']);visited={};runnable=set()
            def blob(descriptor,*,as_json=False):
                digest=descriptor.get('digest','')
                if not re.fullmatch('sha256:[0-9a-f]{64}',digest):raise GateError('image descriptor digest malformed')
                name='blobs/sha256/'+digest[7:]
                allowed.add(name)
                if name not in members or not members[name].isfile():raise GateError('image descriptor member missing')
                member=members[name]
                if descriptor.get('size')!=member.size:raise GateError('image descriptor size mismatch')
                if name not in visited:
                    sha=hashlib.sha256();reader=archive.extractfile(member)
                    while block:=reader.read(1024**2):
                        sha.update(block)
                        if time.monotonic()-start>SECONDS:raise GateError('image validation deadline exceeded')
                    if sha.hexdigest()!=digest[7:]:raise GateError('image descriptor identity mismatch')
                    visited[name]=member.size
                if not as_json:return name
                return metadata(archive,member)
            def image_manifest(descriptor,*,attestation=False):
                value=blob(descriptor,as_json=True)
                if value.get('schemaVersion')!=2 or 'config' not in value or 'layers' not in value:
                    raise GateError('image manifest shape unsupported')
                config=value['config'];body=blob(config,as_json=True)
                settings=body.get('config',{})
                if any(settings.get(k) for k in ['Entrypoint','Volumes','Healthcheck']):
                    raise GateError('OCI runtime configuration rejected')
                layer_names=[blob(row) for row in value['layers']]
                if attestation:
                    if body!={} or any(row.get('mediaType')!='application/vnd.in-toto+json' for row in value['layers']):
                        raise GateError('attestation data shape unsupported')
                elif (body.get('architecture')!='amd64' or body.get('os')!='linux' or
                        config['digest'] not in found or docker_layers[config['digest']]!=layer_names):
                    raise GateError('OCI and Docker runtime image references disagree')
                else:runnable.add(config['digest'])
            index=metadata(archive,members['index.json']);roots=index.get('manifests',[])
            if len(roots)!=2 or {r.get('digest') for r in roots}!=wanted:
                raise GateError('locked OCI root inventory mismatch')
            for root in roots:
                value=blob(root,as_json=True)
                children=value.get('manifests')
                if children is None:
                    image_manifest(root);continue
                natives=[r for r in children if r.get('platform')=={'architecture':'amd64','os':'linux'}]
                if len(natives)!=1:raise GateError('exactly one native platform per locked root required')
                image_manifest(natives[0])
                for child in children:
                    if child is natives[0]:continue
                    annotations=child.get('annotations',{})
                    if (child.get('platform')!={'architecture':'unknown','os':'unknown'} or
                            annotations.get('vnd.docker.reference.type')!='attestation-manifest' or
                            annotations.get('vnd.docker.reference.digest')!=natives[0]['digest']):
                        raise GateError('unregistered image platform rejected')
                    image_manifest(child,attestation=True)
            if runnable!=found:
                raise GateError('OCI and Docker config inventory disagreement')
            if 'oci-layout' not in members or metadata(archive,members['oci-layout'])!={'imageLayoutVersion':'1.0.0'}:
                raise GateError('OCI layout unsupported')
        elif found!=wanted:
            raise GateError('locked config image inventory incomplete')
        if any(member.isfile() and name not in allowed for name,member in members.items()):
            raise GateError('unregistered archive payload rejected')
    return {'image_ids':sorted(wanted),'config_ids':sorted(found),'members':len(members),'expanded_bytes':path.stat().st_size}


@contextmanager
def verified(archive,expected_digest,expected_images):
    if not re.fullmatch('[0-9a-f]{64}',expected_digest or ''):
        raise GateError('external archive SHA-256 required')
    archive=regular(archive)
    with tempfile.TemporaryDirectory(prefix='safe-c-image-transfer-') as temporary:
        directory=Path(temporary);copy=directory/'input.gz';expanded=directory/'images.tar'
        with archive.open('rb') as source,copy.open('xb') as output:
            size,sha=stream_copy(source,output)
        if sha!=expected_digest:raise GateError('image archive digest mismatch')
        with gzip.open(copy,'rb') as source,expanded.open('xb') as output:
            stream_copy(source,output)
        value=inspect_archive(expanded,expected_images)
        value.update(archive_sha256=sha,archive_bytes=size)
        yield expanded,value


def images(root):
    return [read_json(root/name)['image_id'] for name in ['toolchain.lock.json','developer.lock.json']]


def controller(root,out):
    if any(os.environ.get(name) for name in DOCKER_SETTINGS):
        raise GateError('inherited Docker setting rejected')
    launcher=Launcher(root,out,read_json(root/'toolchain.lock.json'))
    from evidence import bounded
    context=bounded(['/usr/bin/docker','context','show'],timeout=15,limit=65536)
    if not passed(context) or context['output'].strip()!=launcher.value['runner']['context']:
        shutil.rmtree(launcher.config);raise GateError('unapproved Docker context')
    return launcher


def observed_images(launcher,expected):
    values=launcher.json(['image','inspect',*expected])
    if {v['Id'] for v in values}!=set(expected) or len(values)!=2:
        raise GateError('actual image identity mismatch')
    if any(v['Size']>MAX_BYTES or any(v['Config'].get(k) for k in ['Entrypoint','Volumes','Healthcheck']) for v in values):
        raise GateError('actual image metadata rejected')
    return [{'id':v['Id'],'bytes':v['Size']} for v in values]


def export(root,destination,out):
    destination=Path(destination)
    if not destination.is_absolute():raise GateError('absolute transfer destination required')
    if (destination.is_relative_to(root) or destination.exists() or
            any(p.is_symlink() for p in [destination,*destination.parents])):
        raise GateError('new external transfer directory required')
    if shutil.disk_usage(destination.parent).free<8*1024**3+MAX_BYTES:
        raise GateError('image transfer disk headroom unavailable')
    destination.mkdir(mode=0o700)
    launcher=controller(root,out);expected=images(root)
    raw=destination/'images.tar';compressed=destination/'images.tar.gz'
    try:
        launcher.preflight();actual=observed_images(launcher,expected)
        result=launcher.docker(['image','save','--output',str(raw),*expected],timeout=SECONDS,limit=MAX_METADATA)
        atomic_json(out/'image-save.opaque.json',result)
        if not passed(result):raise GateError('image save did not complete')
        regular(raw)
        with raw.open('rb') as source,compressed.open('xb') as target:
            with gzip.GzipFile(filename='',fileobj=target,mode='wb',compresslevel=1,mtime=0) as output:
                stream_copy(source,output)
        raw.unlink()
        with compressed.open('rb') as source,tempfile.TemporaryFile() as sink:
            size,sha=stream_copy(source,sink)
        with verified(compressed,sha,expected) as (_,record):pass
        value=dict(record,status='TRANSFERRED_UNAPPROVED',actual_images=actual,
            locks={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ['toolchain.lock.json','developer.lock.json']},
            publication_authorized=False,license_review='PENDING',runner_authorized=False,
            qualification_inherited=False,archive=str(compressed))
        atomic_json(destination/'transfer.json',value)
        return value
    except Exception:
        for path in [raw,compressed]:path.unlink(missing_ok=True)
        raise
    finally:shutil.rmtree(launcher.config)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['export','verify','load'])
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--sha256')
    args=parser.parse_args(argv)
    out=ROOT/'artifacts/image-transfer'/uuid.uuid4().hex;out.mkdir(parents=True)
    try:
        if args.operation=='export':
            if not args.destination or args.archive or args.sha256:raise GateError('export selection malformed')
            result=export(ROOT,args.destination,out)
        else:
            if not args.archive or not args.sha256 or args.destination:raise GateError('transfer selection malformed')
            with verified(args.archive,args.sha256,images(ROOT)) as (expanded,result):
                if args.operation=='load':
                    launcher=controller(ROOT,out)
                    try:
                        record=launcher.docker(['image','load','--input',str(expanded)],timeout=SECONDS,limit=MAX_METADATA)
                        atomic_json(out/'image-load.opaque.json',record)
                        if not passed(record):raise GateError('image load did not complete')
                        result['actual_images']=observed_images(launcher,images(ROOT))
                    finally:shutil.rmtree(launcher.config)
                result=dict(result,status='VERIFIED_DATA',runner_authorized=False,qualification_inherited=False)
        atomic_json(out/'result.json',result)
        print(json.dumps(result));return 0
    except Exception as error:
        result={'status':'BLOCKED','error_type':type(error).__name__,'evidence_path':str(out),
                'reason':str(error) if isinstance(error,GateError) else 'Image transfer data could not be verified.'}
        atomic_json(out/'result.json',result);print(json.dumps(result));return 1


if __name__=='__main__':raise SystemExit(main())
