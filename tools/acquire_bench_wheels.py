"""Explicit acquisition of the bench wheels: the only network step of Phase 1. Never run by checks.

fetch:   resolve each pinned version on PyPI, download over HTTPS, verify sha256, retain under
         third_party/developer/wheels/ (pieces of at most 32 MiB) and write provenance.
extract: confined offline extraction job (developer-package.py) with /inputs = retained inputs.
promote: copy a qualified candidate lock and payload into developer.lock.json and third_party/."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, sys, tempfile
from evidence import GateError, Runner, atomic_json, bounded, file_hash, passed, read_json
from evidence import loads_capped

ROOT=Path(__file__).resolve().parents[1]
# FR4 (owner decision 2026-10-13): the framework image holds the wheels that framework code imports, and only those.
PINS={'numpy':'2.3.3','pyperf':'2.9.0','psutil':'7.1.0'}
PART=32*1024*1024
FREE_GATE=int(9.8*2**30)
WHEELS=Path('third_party/developer/wheels');SELECTION=Path('third_party/developer/provenance/wheel-selection.json')

def free_bytes(path):
    s=os.statvfs(path);return s.f_bavail*s.f_frsize

def compatible(filename):
    if not filename.endswith('.whl'):return False
    py,abi,plat=filename[:-4].split('-')[-3:]
    if (py,abi,plat)==('py3','none','any'):return True
    linux=any(p.endswith('_x86_64') and p.startswith(('manylinux_2_','manylinux2014_','manylinux2010_','manylinux1_')) for p in plat.split('.'))
    return linux and ((py,abi)==('cp313','cp313') or (abi=='abi3' and py.startswith('cp3') and int(py[3:])<=13))

def choose(release,name,version):
    files=[f for f in release.get('urls',[]) if f.get('packagetype')=='bdist_wheel' and compatible(f['filename']) and not f.get('yanked')]
    if len(files)!=1:raise GateError(f'{name} {version}: {len(files)} compatible wheels; exactly one is required')
    f=files[0]
    if not f['url'].startswith('https://files.pythonhosted.org/'):raise GateError(name+': unexpected wheel host')
    return {'name':name,'version':version,'filename':f['filename'],'url':f['url'],'sha256':f['digests']['sha256'],'bytes':f['size']}

def split_parts(path,part=PART,base=WHEELS):
    data=Path(path).read_bytes()
    if len(data)<=part:return [{'path':str(base/Path(path).name),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}]
    rows=[]
    for n,start in enumerate(range(0,len(data),part)):
        chunk=data[start:start+part];target=Path(path).with_name(Path(path).name+f'.part-{n:02d}');target.write_bytes(chunk)
        rows.append({'path':str(base/target.name),'sha256':hashlib.sha256(chunk).hexdigest(),'bytes':len(chunk)})
    Path(path).unlink();return rows

def join_parts(paths):return b''.join(Path(p).read_bytes() for p in paths)

def curl(url,output=None):
    argv=['/usr/bin/curl','--fail','--silent','--show-error','--location','--proto','=https','--max-filesize',str(64*1024*1024),url]
    if output:argv[1:1]=['--output',str(output)]
    r=bounded(argv,timeout=300,limit=8*1024*1024)
    if not passed(r):raise GateError('download failed: '+url.split('/')[2])
    return r['output']

def fetch(root):
    if free_bytes(root)<FREE_GATE:raise GateError('BLOCKED: wheel acquisition needs at least 9.8 GiB free; owner disk action required')
    (root/WHEELS).mkdir(parents=True,exist_ok=True);rows=[]
    for name,version in PINS.items():
        row=choose(loads_capped(curl(f'https://pypi.org/pypi/{name}/{version}/json')),name,version)
        target=root/WHEELS/row['filename'];curl(row['url'],target)
        if target.stat().st_size!=row['bytes'] or file_hash(target)!=row['sha256']:
            target.unlink();raise GateError(name+': downloaded wheel digest mismatch')
        row['parts']=split_parts(target);rows.append(row)
    atomic_json(root/SELECTION,{'schema_version':1,'index':'https://pypi.org/pypi/<name>/<version>/json','wheels':rows,
        'sanitizer_boundary':'wheel native code runs only inside bench containers; it is never linked into first-party C, so sanitizer qualification does not apply',
        'consumers':[{'consumer':'bench jobs (tools/bench.py) on the developer image','migration':'bench doctor PASS on the new image_id'},
                     {'consumer':'dev commands (tools/developer.py) on the developer image','migration':'developer suite and live trial requalified in Task 20'}]})
    print(json.dumps({'status':'FETCHED','wheels':len(rows),'bytes':sum(r['bytes'] for r in rows)}))

def extract(root,work):
    """Offline confined extraction in the dependency-build profile; /inputs holds every retained input."""
    inputs=work/'inputs';inputs.mkdir(parents=True)
    for sub in ['provenance','archives','wheels']:
        for p in (root/'third_party/developer'/sub).glob('*'):
            if p.is_file():shutil.copy2(p,inputs/p.name)
    lock=read_json(root/'toolchain.lock.json');scratch=Path(tempfile.mkdtemp(prefix='safe-c-wheel-extract-'))
    runner=Runner(root,work/'extraction',lock,scratch,build_profile='dependency-build',input_root=inputs)
    try:
        r=runner.run(['python3','/src/container/developer-package.py'],timeout=600,label='developer-extraction')
        atomic_json(work/'extraction'/'extraction.json',r)
        if not passed(r):raise GateError('extraction job failed; read its evidence by exit code and error_type')
        manifest=runner.fetch('developer-acquisition/manifest.json',work/'extraction'/'manifest.json')
        listing=read_json(manifest)
        for row in listing['archives']:runner.fetch('developer-acquisition/'+row['name'],work/'extraction'/row['name'])
        for name,row in listing['notices'].items():
            if name in PINS:
                leaf=Path(row['path']).name
                runner.fetch('developer-acquisition/notices/'+name+'/'+leaf,work/'extraction'/'notices'/name/leaf)
    finally:
        runner.close();shutil.rmtree(scratch,ignore_errors=True)
    print(json.dumps({'status':'EXTRACTED','extraction':str(work/'extraction'),'inputs':str(inputs)}))

NOTICE_REVIEW_FIELDS=('owner','license_tags','review_status')

def _promote_notice(lock,name,path,sha256):
    """R1B-01 (approval P1-R1-01): a promoted notice keeps the owner, license tags and review status of its existing entry
    ({**old, path, sha256}); an entry without all three (a new wheel included) is refused, so review fields are never lost.
    T28-APP-02: when the notice sha256 changes, review_status resets to PENDING (no review carries over to unreviewed text)."""
    old=(lock.get('notices') or {}).get(name)
    if not isinstance(old,dict) or not all(old.get(k) for k in NOTICE_REVIEW_FIELDS):
        raise GateError('notice entry needs owner, license_tags and review_status before promotion')
    lock['notices'][name]={**old,'path':path,'sha256':sha256,**({'review_status':'PENDING'} if sha256!=old.get('sha256') else {})}

def promote(root,candidate_path,extraction):
    candidate=read_json(candidate_path);lock=read_json(root/'developer.lock.json')
    for name in candidate['payload']['notices']:          # R1B-01: refuse before any file changes, not halfway through
        if name in PINS:_promote_notice({'notices':dict(lock.get('notices') or {})},name,'','')
    payload=root/'third_party/developer/payload'
    for p in payload.glob('development-layer-*.tar.gz'):p.unlink()
    for row in candidate['payload']['archives']:shutil.copy2(extraction/row['name'],payload/row['name'])
    shutil.copy2(extraction/'manifest.json',payload/'manifest.json')
    selection=read_json(root/SELECTION)
    inputs=[r for r in lock['inputs'] if r['kind'] not in ('development-payload','payload-manifest','python-wheel-part') and r['path']!=str(SELECTION)]
    inputs+=[{'path':str(Path('third_party/developer/payload')/r['name']),'kind':'development-payload','bytes':r['bytes'],'sha256':r['sha256']} for r in candidate['payload']['archives']]
    inputs+=[{'path':'third_party/developer/payload/manifest.json','kind':'payload-manifest','bytes':(payload/'manifest.json').stat().st_size,'sha256':file_hash(payload/'manifest.json')}]
    inputs+=[{'path':p['path'],'kind':'python-wheel-part','bytes':p['bytes'],'sha256':p['sha256']} for w in selection['wheels'] for p in w['parts']]
    inputs+=[{'path':str(SELECTION),'kind':'provenance-data','bytes':(root/SELECTION).stat().st_size,'sha256':file_hash(root/SELECTION)}]
    lock['payload_chunks']=[{'bytes':r['bytes'],'files':r['files'],'name':r['name'],'path':str(Path('third_party/developer/payload')/r['name']),'sha256':r['sha256']} for r in candidate['payload']['archives']]
    # FR4: a notice entry whose package or wheel left the payload leaves the lock with it
    lock['notices']={name:row for name,row in lock['notices'].items() if name in candidate['payload']['notices']}
    lock.update(image_id=candidate['image_id'],inputs=inputs,bench_python=dict(PINS),status='ACQUIRED_UNQUALIFIED',independent_approval='PENDING',
                extraction_recipe_sha256=file_hash(root/lock['extraction_recipe']),assembly_recipe_sha256=file_hash(root/lock['assembly_recipe']))
    for name,row in candidate['payload']['notices'].items():
        if name in PINS:
            target=root/'third_party/developer/notices'/name/Path(row['path']).name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(extraction/'notices'/name/Path(row['path']).name,target)
            _promote_notice(lock,name,str(target.relative_to(root)),file_hash(target))
    atomic_json(root/'developer.lock.json',lock)
    print(json.dumps({'status':'PROMOTED','image_id':candidate['image_id'],'inputs':len(inputs)}))

def main(argv=None):
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='op',required=True)
    sub.add_parser('fetch');e=sub.add_parser('extract');e.add_argument('--work',type=Path,required=True)
    m=sub.add_parser('promote');m.add_argument('--candidate',type=Path,required=True);m.add_argument('--extraction',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        if a.op=='fetch':fetch(ROOT)
        elif a.op=='extract':
            if not a.work.resolve().is_relative_to(ROOT/'artifacts') or a.work.exists():raise GateError('work directory must be new and under artifacts/')
            extract(ROOT,a.work.resolve())
        else:promote(ROOT,a.candidate.resolve(),a.extraction.resolve())
        return 0
    except GateError as exc:
        print(json.dumps({'status':'BLOCKED' if 'BLOCKED' in str(exc) else 'FAILED','reason':str(exc)}));return 2

if __name__=='__main__':raise SystemExit(main())
