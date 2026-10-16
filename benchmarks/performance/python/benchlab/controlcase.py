"""Framework control workloads (Amendment A): a bounded CPU spin (the GIL stays held), a finite wait (the GIL is released)
and touched memory. Deterministic results, exact validation; no project code.

Amendment G2.6 framework control: the spin control has the test selector `hang`, whose `run` blocks without a timeout
(a threading.Event that nobody sets). Only the `call-deadline` selftest suite plans it; no case point uses it."""
import hashlib, json, threading, time
MAX_BYTES=33554432;POOLED=('py-threads','py-processes')

class Control:
    MODE=None;SELECTORS=('all',)
    def __init__(self,params,selector='all',request_limit=None):
        if selector not in self.SELECTORS:raise ValueError(f'{type(self).__name__} has no selector {selector!r}')
        self.params=dict(params);self.selector=selector;name=f'{type(self).__module__}:{type(self).__name__}'
        self.request_limit=request_limit      # G-ALO-CO: set by benchlab.workload.construct_adapter; pooled prepare refuses None
        self.bench_ref=(name,self.params,selector,request_limit)
    def synthesize(self,rows,seed):
        if isinstance(rows,bool) or not isinstance(rows,int) or rows<0:raise ValueError('rows must be a non-negative integer')
        return json.dumps({'kind':self.MODE,'seeds':[(seed*1000003+i)%4294967296 for i in range(rows)]},separators=(',',':')).encode()
    def load(self,dataset_ref):
        with open(dataset_ref['path'],'rb') as f:data=f.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('dataset exceeds 32 MiB')
        if hashlib.sha256(data).hexdigest()!=dataset_ref['sha256']:raise ValueError('dataset digest mismatch')
        doc=json.loads(data);seeds=doc.get('seeds') if isinstance(doc,dict) else None
        if not isinstance(doc,dict) or doc.get('kind')!=self.MODE or not isinstance(seeds,list) or not all(type(s) is int and 0<=s<4294967296 for s in seeds):
            raise ValueError(f'not a {self.MODE} control dataset')
        return seeds
    def slice(self,data,n):
        if n<0 or n>len(data):raise ValueError('slice outside the dataset')
        return data[:n]
    def take(self,data,index):
        """Base Task 18 (G7.3): the one-row request of dataset row `index` (a panel trial calls it outside each call wall)."""
        if type(index) is not int or not 0<=index<len(data):raise ValueError('row outside the dataset')
        return data[index:index+1]
    def row_status(self,result):
        """The status of a one-row result for the panel status check (H21.4): a control has one status, OK, for one value."""
        return 'OK' if len(result.get('values',[]))==1 else 'ROW_COUNT'
    def prepare(self,data,variant,workers=1):
        prepared={'seeds':list(data)}
        if variant in POOLED:       # spec 5 / Amendment E: gathered by index before the interval, one chunk per worker per request
            if self.request_limit is None:raise ValueError('request_limit not set: construct the adapter through benchlab.workload.construct_adapter')
            from benchlab.pools import chunk_indices
            seeds=prepared['seeds'];prepared['chunks']=[{'index':idx,'seeds':[seeds[i] for i in idx]} for idx in chunk_indices(len(seeds),workers,self.request_limit)]
        return prepared
    def chunks(self,prepared,workers):return prepared['chunks']
    def run_chunk(self,chunk):
        """A gathered chunk {'index', 'seeds'} gives {'index', 'values'}; a plain seed list gives its value list."""
        if isinstance(chunk,dict):return {'index':chunk['index'],'values':[self.unit(s) for s in chunk['seeds']]}
        return [self.unit(s) for s in chunk]
    def combine(self,parts):
        """Gathered parts scatter back to their input positions (out[i] = value); plain parts concatenate in order."""
        if not parts or not isinstance(parts[0],dict):return [x for part in parts for x in part]
        out=[None]*sum(len(p['index']) for p in parts)
        for p in parts:
            if len(p['values'])!=len(p['index']):raise ValueError('a part holds one value per index position')
            for i,v in zip(p['index'],p['values']):
                if not 0<=i<len(out):raise ValueError('a part index lies outside the input positions')
                out[i]=v
        if any(v is None for v in out):raise ValueError('chunks do not cover every input position')
        return out
    def run(self,prepared,variant,workers,pool=None):
        if self.selector=='hang':threading.Event().wait()      # G2.6 test selector: blocks until the coordinator kills the group
        if variant not in POOLED:return self.run_chunk(prepared['seeds'])
        from benchlab.pools import start_pool, run_pool
        if pool is not None:return run_pool(self,prepared,workers,pool)
        with start_pool(variant,workers,self.bench_ref) as fresh:return run_pool(self,prepared,workers,fresh)
    def materialize(self,raw):return {'values':list(raw)}
    def work_units(self,result):return len(result['values'])
    def reference(self,data):return self.materialize(self.run_chunk(list(data)))
    def slice_result(self,result,n,data):return {'values':result['values'][:n]}
    def validate(self,result,reference,data):
        ok=result==reference;count=len(result.get('values',[]))!=len(reference['values'])
        return {'eligible':ok,'failures':{} if ok else {'values':1},'reduction':'MATCH' if ok else 'ROW_COUNT' if count else 'MISMATCH'}
    def digest(self,result):return hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def _param(self,key):
        value=self.params[key]
        if isinstance(value,bool) or not isinstance(value,int) or value<0:raise ValueError(f'invalid control parameter: {key} must be a non-negative integer')
        return value

class Spin(Control):
    MODE='spin';SELECTORS=('all','hang')
    def unit(self,seed):
        h=seed.to_bytes(8,'little')
        for _ in range(self._param('rounds')):h=hashlib.sha256(h).digest()      # short input: hashlib keeps the GIL
        return int.from_bytes(h[:8],'little')

class Wait(Control):
    MODE='wait'
    def unit(self,seed):time.sleep(self._param('wait_us')/1e6);return seed^0x5A5A5A5A

class Touch(Control):
    MODE='touch'
    def unit(self,seed):
        buf=bytearray(self._param('touch_kib')*1024)
        for i in range(0,len(buf),4096):buf[i]=(seed+i)&0xFF
        return (seed+sum(buf[::4096]))%4294967296
