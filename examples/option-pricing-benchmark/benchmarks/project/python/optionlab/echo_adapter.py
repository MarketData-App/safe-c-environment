"""The echo control of the option example (task EX-10, ruling R43 item h; label "overhead calibration"): an empty kernel on
the option request records, so that a run measures the caller-boundary cost of each route without any pricing work.

Variants: py-reference, an in-process empty kernel that returns the echo result; c-serial, pl-worker --echo (status 255 for
bsm, bjs and crr, NOT_REQUESTED for baw and alo, mask 7) on the routes stdio and shm (optionlab.backends.NativeRows with
NATIVE_ECHO). libpl_inproc.so has no echo mode (its batch runs with the echo off; specs/project/inproc.md), so the case
declares no inproc route and this adapter refuses one; the C ABI is unchanged.

The dataset is the option chain of optionlab.synthetic with the pricing parameters of the option case manifest
(optionlab.params.CASE): the echo rows send the same request records as the option rows of the same size and seed. The
per-row r and q columns are the case assumptions for every dataset (they only enter the request bytes). The echo result has
the reference.run shape with the status ECHO, flags 0 and NaN values; `digest` is the SHA-256 of a canonical JSON form of
the result (reference.canonical_result admits the statuses of spec 3.3 only, not ECHO)."""
import hashlib, json, math, struct
from optionlab.backends import NativeRows
from optionlab.contract import ALL_MODELS, FIELDS, MAX_INPUT_BYTES, decode_chain_origin, slice_chain, with_rates
from optionlab.params import CASE

LABEL='overhead calibration'
ECHO='ECHO'

class EchoControl(NativeRows):
    """The echo control case adapter (selector all only; the mask 7 of the three-model chain)."""
    NATIVE_ECHO=True;ROUTES_ALLOWED=('stdio','shm')
    def __init__(self,params,selector='all',request_limit=None):
        if selector!='all':raise ValueError('the echo control runs the selector all only')
        self.selector='all';self.models=ALL_MODELS;self.raw=dict(params);self.params=CASE;self.request_limit=request_limit
        self.bench_ref=('optionlab.echo_adapter:EchoControl',self.raw);self.market=None
        self._native_init()
    def synthesize(self,n,seed):
        from optionlab.synthetic import generate
        return json.dumps(generate(n,seed,self.params)).encode()
    def load(self,dataset_ref):
        with open(dataset_ref['path'],'rb') as f:data=f.read(MAX_INPUT_BYTES+1)
        if hashlib.sha256(data).hexdigest()!=dataset_ref['sha256']:raise ValueError('dataset digest mismatch')
        chain,synthetic=decode_chain_origin(data);chain['synthetic']=synthetic
        return with_rates(chain,self.params.rate,self.params.dividend_yield)
    def slice(self,chain,n):return slice_chain(chain,n)
    def slice_result(self,result,n,chain):return {'n':n,'models':{m:{k:v[:n] for k,v in col.items()} for m,col in result['models'].items()}}
    def echo_result(self,n):
        """The echo result of n rows: status ECHO, flags 0 and NaN values for bsm, bjs and crr."""
        if isinstance(n,bool) or not isinstance(n,int) or n<0:raise ValueError('echo row count rejected')
        return {'n':n,'models':{m:{'status':[ECHO]*n,'flags':[0]*n,**{f:[math.nan]*n for f in FIELDS}} for m in self.models}}
    def prepare(self,chain,variant,workers=1):
        if isinstance(variant,str) and variant.startswith('c-'):return self.native_prepare(chain,variant,workers)
        if variant!='py-reference':raise ValueError('unknown variant')
        return {'n':chain['n']}
    def run(self,prepared,variant,workers,pool=None):
        if isinstance(variant,str) and variant.startswith('c-'):return self.native_run(prepared,variant,workers)
        if variant!='py-reference':raise ValueError('unknown variant')
        return self.echo_result(prepared['n'])            # the in-process empty kernel
    def materialize(self,raw):
        if isinstance(raw,dict) and 'records' in raw:return self.native_materialize(raw)
        return raw
    def reference(self,chain):return self.echo_result(chain['n'])
    def _echo_rows(self,result):
        """Per row: 1 when every selected model holds ECHO, flags 0 and seven NaN values (malformed columns count 0)."""
        n=result.get('n') if isinstance(result,dict) else None
        models=result.get('models') if isinstance(result,dict) else None
        if isinstance(n,bool) or not isinstance(n,int) or n<0 or not isinstance(models,dict):return []
        out=[1]*n
        for m in self.models:
            col=models.get(m)
            if not isinstance(col,dict) or any(not isinstance(col.get(k),list) or len(col[k])!=n for k in ('status','flags',*FIELDS)):return [0]*n
            for i in range(n):
                v=[col[f][i] for f in FIELDS]
                ok=(col['status'][i]==ECHO and type(col['flags'][i]) is int and col['flags'][i]==0
                    and all(isinstance(x,float) and math.isnan(x) for x in v))
                if not ok:out[i]=0
        return out
    def work_units(self,result):return sum(self._echo_rows(result))
    def validate(self,result,reference,chain):
        """Eligible when the result holds exactly the selected models with n = the chain rows = the reference rows, and every
        row is an echo row."""
        n=chain['n'];rows=self._echo_rows(result);failures={}
        if not isinstance(result,dict) or result.get('n')!=n or reference.get('n')!=n:failures['row-count']=1
        elif sorted(result['models'])!=sorted(self.models):failures['models']=1
        bad=len(rows)-sum(rows)
        if bad:failures['echo']=bad
        return {'eligible':not failures,'failures':failures,'reduction':'NOT_RUN'}
    def digest(self,result):
        """SHA-256 of the canonical JSON form: sorted keys, no spaces, NaN as null, every other number as the hex digits of its
        big-endian binary64 bits (-0.0 as 0.0), statuses and flags as they are."""
        def value(x):
            if isinstance(x,bool) or not isinstance(x,(int,float)):raise ValueError('echo digest: a value is not a number')
            x=float(x)
            if math.isnan(x):return None
            return struct.pack('>d',0.0 if x==0.0 else x).hex()
        doc={'n':result['n'],'models':{m:{'status':list(col['status']),'flags':list(col['flags']),**{f:[value(x) for x in col[f]] for f in FIELDS}}
                                       for m,col in result['models'].items()}}
        return hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
