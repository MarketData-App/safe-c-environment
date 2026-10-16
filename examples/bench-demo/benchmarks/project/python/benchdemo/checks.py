"""The declared checks of the bench-demo project (Amendment A item 4). The framework `check` job runs
`python -m benchdemo.checks <name> <out_dir> [args]`; the last stdout line is one JSON row, and the framework decides the
status from the exit code and that row (container check_result).

demo-agreement (before_run): every implemented direct variant gives the reference result on a synthetic dataset, and the
reference keeps the definitional anchors and the request bounds of specs/project/bd_digest.md.
demo-vectors (before_run false, a generation tool): writes the generated C vector block (benchdemo.vectors) to the output
directory as bd_vectors.inc.
demo-native (before_run false; run with `bench check --native`, FR6 N3; the bench.json `native` agreement check that
bench run runs with the run's native build before any timing, FR6 N4): the three-version agreement. For each request of a
fixed set (n = 1, n = 14,336, k = 0, k = 1,000,000, seed 0, and the N3 requests) it computes the native Python version
(benchdemo.reference), the C kernel bd-kernel through the kernel handshake (its canonical FNV-1a digest checked) and the
Python bridge to C over each route (bd-worker stdio and shm, libbd_inproc.so in a caller child), and proves that every
output is byte-identical: the sha256 of each version's output per request is written to native-agreement.json."""
import hashlib, json, os, sys, tempfile
from pathlib import Path
from benchlab.workload import load_case_adapter
from benchdemo import reference as r, vectors
CASE_PATH=Path(__file__).resolve().parents[2]/'cases'/'demo-digest.json'
ROWS=8;SEED=20261007;VARIANTS=('py-reference','py-optimized');VECTOR_FILE='bd_vectors.inc'

def load_case():
    with open(CASE_PATH) as f:return json.load(f)

def synthetic(adapter,rows,seed=SEED):
    """The loaded synthetic dataset of `rows` records (written to a temporary file and read back through `load`)."""
    data=adapter.synthesize(rows,seed)
    with tempfile.TemporaryDirectory() as t:
        p=Path(t)/'demo.bin';p.write_bytes(data)
        return adapter.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})

def refusal(request):
    """The status name that check_request raises for `request`, or None when it is valid."""
    try:r.check_request(request)
    except ValueError as exc:return str(exc)
    return None

def anchors():
    """The number of failed definitional anchors: k = 0 keeps the offset basis and the (mapped) seed, and the request
    bounds give the specified status names."""
    rec=lambda s,k:r.encode_request([(s,k)])
    cases=((r.digest_record(0,0)==(r.FNV_OFFSET,r.ZERO_SEED)),(r.digest_record(1,0)==(r.FNV_OFFSET,1)),
           (r.digest_record(0,1)==r.digest_record(r.ZERO_SEED,1)),
           (refusal(b'')=='BD_EMPTY_REQUEST'),(refusal(rec(1,0)) is None),(refusal(rec(1,0)[:-1])=='BD_PARTIAL_RECORD'),
           (refusal(rec(1,r.STEPS_MAX)) is None),(refusal(rec(1,r.STEPS_MAX+1))=='BD_STEPS_TOO_LARGE'),
           (refusal(rec(1,0)*r.RECORDS_MAX) is None),(refusal(rec(1,0)*(r.RECORDS_MAX+1))=='BD_TOO_MANY_RECORDS'))
    return sum(1 for ok in cases if not ok)

def agreement(out_dir,args):
    """before_run: every implemented direct variant gives the reference result on a synthetic dataset of ROWS records,
    and the reference keeps its anchors."""
    if args:return {'status':'FAIL','reason':'demo-agreement takes no arguments'}
    adapter=load_case_adapter(load_case());data=synthetic(adapter,ROWS);ref=adapter.reference(data);bad=0
    for variant in VARIANTS:
        got=adapter.materialize(adapter.run(adapter.prepare(data,variant,1),variant,1))
        if not adapter.validate(got,ref,data)['eligible']:bad+=1
    failed=anchors()
    return {'status':'PASS' if bad==0 and failed==0 else 'FAIL',
            'counts':{'rows':ROWS,'variants':len(VARIANTS),'mismatched_variants':bad,'failed_anchors':failed}}

def generate_vectors(out_dir,args):
    """Generation tool: writes the C vector block to out_dir/bd_vectors.inc."""
    if args:return {'status':'FAIL','reason':'demo-vectors takes no arguments'}
    block=vectors.c_block();Path(out_dir).mkdir(parents=True,exist_ok=True);(Path(out_dir)/VECTOR_FILE).write_text(block)
    return {'status':'PASS','files':[VECTOR_FILE],'counts':{'vectors':len(vectors.RECORDS),'bytes':len(block.encode())}}

AGREEMENT_FILE='native-agreement.json'

def native_requests():
    """The fixed request set of demo-native: one record (seed 0, k 0); five records with k 0, 1, 64, 7 and 1,000,000,
    seeds 0, 1, UINT64_MAX and the zero-seed constant; the largest request (14,336 records, k = i mod 31); FR6 N4: one
    record with seed 0 and k = 1,000,000, and the largest request with seed 0 and k = 0 in every record."""
    mixed=[(0,1),(1,0),(r.MASK,r.STEPS_MAX),(r.ZERO_SEED,64),(12345,7)]
    largest=[((i*0x9E3779B97F4A7C15)&r.MASK,i%31) for i in range(r.RECORDS_MAX)]
    return (('one',r.encode_request([(0,0)])),('mixed',r.encode_request(mixed)),('largest',r.encode_request(largest)),
            ('one-kmax',r.encode_request([(0,r.STEPS_MAX)])),('largest-zero',r.encode_request([(0,0)]*r.RECORDS_MAX)))

def native_agreement(out_dir,args):
    """demo-native: every route's output equals the Python reference byte for byte for every request of the set."""
    if args:return {'status':'FAIL','reason':'demo-native takes no arguments'}
    native_dir=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not native_dir:return {'status':'FAIL','reason':'demo-native needs bench check --native'}
    from benchdemo import native
    routes={route:{'matched':0,'mismatched':0,'errors':0} for route in native.ROUTES};names=[];evidence=[]
    sha=lambda b:hashlib.sha256(b).hexdigest()
    for name,request in native_requests():
        names.append(name);want=r.digest_request(request);row={'request':name,'records':len(request)//r.RECORD_IN,'sha256':{'python':sha(want)}}
        for route in native.ROUTES:
            try:got=native.route_digest(route,native_dir,request)
            except Exception as exc:
                routes[route]['errors']+=1;routes[route].setdefault('error_types',[]).append(type(exc).__name__);row['sha256'][route]=None;continue
            routes[route]['matched' if got==want else 'mismatched']+=1;row['sha256'][route]=sha(got)
        row['identical']=len(set(row['sha256'].values()))==1 and None not in row['sha256'].values();evidence.append(row)
    good=all(v['matched']==len(names) for v in routes.values()) and all(x['identical'] for x in evidence)
    counts={'requests':len(names),'routes':len(routes),'identical_requests':sum(1 for x in evidence if x['identical'])}
    for route,v in routes.items():counts.update({f'{route}_{k}':v[k] for k in ('matched','mismatched','errors')})
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    (Path(out_dir)/AGREEMENT_FILE).write_text(json.dumps({'versions':['python']+list(native.ROUTES),'requests':evidence},sort_keys=True,indent=1)+'\n')
    return {'status':'PASS' if good else 'FAIL','counts':counts,'files':[AGREEMENT_FILE],'requests':names,'routes':routes}

CHECKS={'demo-agreement':agreement,'demo-vectors':generate_vectors,'demo-native':native_agreement}

def main(argv):
    if len(argv)<3 or argv[1] not in CHECKS:print(json.dumps({'status':'FAIL','reason':'unknown check'}));return 2
    print(json.dumps(CHECKS[argv[1]](Path(argv[2]),argv[3:])));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
