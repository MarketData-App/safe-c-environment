"""Registered-workload interface (spec 11.1, Amendment A). Framework code: it imports a project module only by the
`module:object` name of a case manifest. Kinds: function, service (import), offline-job (bounded subprocess).

Pool methods (POOL_METHODS; Amendment E, one chunk per worker per request over a fixed-seed permutation). A pooled
workload has three obligations:
(a) `chunks(prepared, workers)` returns the chunks of `benchlab.pools.chunk_indices(n, workers, limit)`, in that order (L2
    requests first, then one chunk per worker inside each request), with `limit` the adapter's `request_limit`;
(b) a dict chunk carries `index`: its ascending absolute row positions (a list or a 1-D integer array). run_pool
    refuses a dict chunk without it, and records len(index) as the chunk size. A non-dict chunk is a sequence of rows;
(c) `combine(parts)` scatters each part back to the input positions of its chunk (out[index] = part), so the output
    order equals the input order. The parts arrive in chunk order, but chunk order is not row order.
`run_chunk(chunk)` runs in the worker. It must return what `combine` needs to scatter, usually the chunk's `index`.

One construction path (G-ALO-CO, Amendment I item I13.1): `construct_adapter` is the only code that calls an adapter
factory. A pooled adapter gets the keyword `request_limit` (the records per request, 14,336 under the current policy),
read by `request_limit()` from SAFE_C_BENCH_REQUEST_LIMIT (set by the coordinator from the plan or the protected policy)
and from the policy file of the repository that holds this package; it stores the value and passes it to the pools."""
import importlib, json, os, re, subprocess, tempfile
from pathlib import Path
KINDS=('function','service','offline-job')
ADAPTER_METHODS=('load','prepare','run','work_units','validate')
FRAMEWORK_METHODS=('synthesize','slice','slice_result','materialize','reference','digest')
POOL_METHODS=('chunks','run_chunk','combine');POOLED=('py-threads','py-processes')
SELECTOR_RE=re.compile(r'^[a-z0-9-]{1,16}$')
REQUEST_LIMIT_ENV='SAFE_C_BENCH_REQUEST_LIMIT'      # G-ALO-CO: the coordinator sets it for every child (container/bench-coordinator.py)
POLICY_FILE=Path(__file__).resolve().parents[4]/'safety/performance-policy.json'   # the repository that contains benchlab
HELPER_NOTE='construct adapters through benchlab.workload.construct_adapter'
_DECIMAL=re.compile(r'^[1-9][0-9]{0,9}$')

def params_from_manifest(case):return {k:v['value'] for k,v in case['parameters'].items()}

def pooled_variants(case):return [v['id'] for v in case['variants'] if v['id'] in POOLED and v['status']=='implemented']

def _positive(value):return not isinstance(value,bool) and isinstance(value,int) and value>0

def _request_limit():
    """The request limit: SAFE_C_BENCH_REQUEST_LIMIT if set, else pools.request_limit of POLICY_FILE. Both present and
    different, a malformed value, or neither present raise ValueError naming the helper."""
    raw=os.environ.get(REQUEST_LIMIT_ENV)
    if raw is not None and not _DECIMAL.fullmatch(raw):raise ValueError(f'request_limit: {REQUEST_LIMIT_ENV} is not a positive decimal integer; {HELPER_NOTE}')
    env=int(raw) if raw is not None else None;policy=None
    if POLICY_FILE.is_file():
        try:policy=json.loads(POLICY_FILE.read_text())['pools']['request_limit']
        except (ValueError,KeyError,TypeError):raise ValueError(f'request_limit: the policy file holds no pools.request_limit; {HELPER_NOTE}') from None
        if not _positive(policy):raise ValueError(f'request_limit: the policy pools.request_limit is not a positive integer; {HELPER_NOTE}')
    if env is None and policy is None:raise ValueError(f'request_limit: neither {REQUEST_LIMIT_ENV} nor the policy file gives the limit; {HELPER_NOTE}')
    if env is not None and policy is not None and env!=policy:raise ValueError(f'request_limit: {REQUEST_LIMIT_ENV}={env} differs from the policy {policy}; {HELPER_NOTE}')
    return env if env is not None else policy

request_limit=_request_limit

def construct_adapter(spec,params,*,selector='all',pooled,request_limit=None):
    """The only call of an adapter factory (G-ALO-CO). `selector` reaches the factory as the keyword `selector` only when it
    is not `all` (Amendment G4.2). A pooled adapter gets `request_limit=<int>`; a non-pooled one keeps its constructor
    (no keyword). An explicit `request_limit` must equal benchlab.workload.request_limit(). A pooled adapter must store the
    limit it got as its `request_limit` attribute (G-ALO-CO part 1 review Minor 3): ValueError otherwise."""
    module,sep,name=spec.partition(':') if isinstance(spec,str) else ('','','')
    if not sep or not module or not name:raise ValueError('adapter must be module:object')
    if not isinstance(selector,str) or not SELECTOR_RE.fullmatch(selector):raise ValueError('selector must match [a-z0-9-]{1,16}')
    limit=_request_limit()
    if request_limit is not None and (not _positive(request_limit) or request_limit!=limit):
        raise ValueError(f'request_limit: the explicit limit {request_limit!r} differs from {limit}; {HELPER_NOTE}')
    factory=getattr(importlib.import_module(module),name);kw={} if selector=='all' else {'selector':selector}
    if pooled:kw['request_limit']=limit
    adapter=factory(params,**kw)
    if pooled:
        stored=getattr(adapter,'request_limit',None)
        if not _positive(stored) or stored!=limit:raise ValueError(f'request_limit: the pooled adapter stores {stored!r}, not the limit {limit} it got; {HELPER_NOTE}')
    return adapter

def load_adapter(spec,params,pooled=False,selector='all'):
    """Amendment G4.2: a selector other than `all` reaches the factory as the keyword `selector` (an opaque string).
    G-ALO-CO: the adapter is built by construct_adapter; the bench_ref of a pooled adapter is (spec, params, selector,
    request_limit), so pool workers build the same adapter with the same limit (benchlab.pools._resolve); a direct-only
    adapter keeps (spec, params) or (spec, params, selector)."""
    adapter=construct_adapter(spec,params,selector=selector,pooled=pooled)
    need=ADAPTER_METHODS+FRAMEWORK_METHODS+(POOL_METHODS if pooled else ())
    missing=[m for m in need if not callable(getattr(adapter,m,None))]
    if missing:raise TypeError('adapter lacks '+', '.join(missing))
    if pooled:adapter.bench_ref=(spec,dict(params),selector,adapter.request_limit)   # the verified stored value (review Minor 3)
    else:adapter.bench_ref=(spec,dict(params)) if selector=='all' else (spec,dict(params),selector)
    return adapter

def load_case_adapter(case,selector='all'):
    """A selector must be declared by the case manifest (`selectors`; a case without the key accepts only `all`)."""
    if selector not in case.get('selectors',['all']):raise ValueError('selector is not declared by the case manifest')
    return load_adapter(case['adapter'],params_from_manifest(case),pooled=bool(pooled_variants(case)),selector=selector)

class OfflineJob:
    """offline-job kind: one bounded subprocess per run. Its output goes to a temporary file, never into memory; only
    the byte count (at most `limit`) is kept. A run past `timeout` seconds is killed and raises TimeoutError."""
    def __init__(self,argv,timeout,limit=1048576):self.argv=list(argv);self.timeout=timeout;self.limit=limit
    def synthesize(self,rows,seed):return b''
    def load(self,dataset_ref):return dataset_ref
    def slice(self,data,n):return data
    def prepare(self,data,variant,workers=1):return data
    def run(self,prepared,variant,workers,pool=None):
        with tempfile.TemporaryFile() as out:
            try:done=subprocess.run(self.argv,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.DEVNULL,timeout=self.timeout)
            except subprocess.TimeoutExpired:raise TimeoutError('offline job exceeded its deadline') from None
            size=os.fstat(out.fileno()).st_size
        return {'exit_code':done.returncode,'output_bytes':min(size,self.limit)}
    def materialize(self,raw):return raw
    def work_units(self,result):return 1 if result['exit_code']==0 else 0
    def reference(self,data):return {'exit_code':0}
    def slice_result(self,result,n,data):return result
    def validate(self,result,reference,data):return {'eligible':result['exit_code']==0,'failures':{} if result['exit_code']==0 else {'exit':1}}
    def digest(self,result):return '%064x'%(result['exit_code']&(2**256-1))
