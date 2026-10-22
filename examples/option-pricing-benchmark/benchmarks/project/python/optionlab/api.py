"""The service entry of the option example (EX-11, plan Task 21, spec 11.3): one function that a service calls to price a
decoded columnar chain.

    price_chain(chain, *, models=('bsm','bjs','crr'), backend='python', workers=None) -> dict

`chain` is the decoded columnar chain of optionlab.contract (n, side, S, K, T, bid, ask) with a per-row `r` and `q` column
(optionlab.contract.with_rates adds them); the function never reads a scalar case rate. `models` is a non-empty subset of
MODELS5 (bsm, bjs, crr, baw, alo); exactly the selected models are computed and nothing else. The result has the
`optionlab.reference.run` shape (`{'n', 'models': {model: columns}}`), with the models in MODELS5 order.

Backends (ruling R49 item a; owner decision 2026-10-16: the example has single-threaded variants only):
- `python`: py-reference, in this process.
- `c-worker`: route stdio, one cold pl-worker per call (c-serial, threads 0): the worker starts inside the call, prices the
  chain, and is shut down and reaped before the call returns. The route is the safest one (a separate process behind a
  framed pipe; a defect of the C code cannot corrupt the caller). The shm and inproc routes are benchmark rows of the
  lab, never a service call.
- Any other backend (python-processes, a shm or inproc route) raises ValueError, and so does any `workers` value other than
  None: a service call runs on one thread of one process.

The C call is built only through optionlab.native_codec and optionlab.backends (cold_price); the case parameters come from
the adapter that benchlab.workload.construct_adapter builds. The request limit of the C backend is
benchlab.workload.request_limit(): a chain larger than the limit goes to the worker in several requests.

Every argument is checked before any work starts, so a refusal never starts a process."""
import json, math
from optionlab.contract import MODELS5, check_models, rows

BACKENDS=('python','c-worker')
ADAPTER='optionlab.adapter:OptionChainGreeks'
COLUMNS=('side','S','K','T','bid','ask','r','q')
_ADAPTER=None

def _adapter():
    """The case adapter (built once, only through benchlab.workload.construct_adapter; not pooled: single-threaded rows)."""
    global _ADAPTER
    if _ADAPTER is None:
        from benchlab.workload import construct_adapter
        from optionlab.params import CASE_FILE
        raw={k:v['value'] for k,v in json.loads(CASE_FILE.read_text())['parameters'].items()}
        _ADAPTER=construct_adapter(ADAPTER,raw,selector='all',pooled=False)
    return _ADAPTER

def _check_chain(chain):
    """The chain to price: ValueError unless chain is a decoded columnar chain with n rows of every column, including the per-row r and q.
    The returned chain is `chain` itself, or a copy whose market columns hold +inf or -inf for an int beyond binary64 (_check_values)."""
    if not isinstance(chain,dict):raise ValueError('chain: a decoded columnar chain (a dict) is required')
    n=chain.get('n')
    if isinstance(n,bool) or not isinstance(n,int) or n<0:raise ValueError('chain: n must be a non-negative integer')
    for key in ('r','q'):
        if key not in chain:raise ValueError('chain: the per-row columns r and q are required (optionlab.contract.with_rates)')
    for key in COLUMNS:
        col=chain.get(key)
        if not isinstance(col,(list,tuple)) or len(col)!=n:raise ValueError(f'chain: column {key} must hold n={n} values')
    fixed=_check_values(chain,n)
    if not fixed:return chain
    out=dict(chain)
    for key,rows_ in fixed.items():
        col=list(chain[key])
        for i,v in rows_.items():col[i]=v
        out[key]=col
    return out

def _number(v):return isinstance(v,(int,float)) and not isinstance(v,bool)

def _check_values(chain,n):
    """ValueError (row index and field name) for a value the models cannot take: side must be an int (not bool; a code other than
    0 or 1 is an INVALID_INPUT row, as in the reference, the C decode and optionlab.contract.load_chain, which gives -1 for an
    unknown side); S, K, T, bid and ask must be real numbers (a non-finite one is an INVALID_INPUT row, as in the reference); r and q
    must be finite numbers (the rule of optionlab.contract.with_rates). An int beyond binary64 is non-finite: in r or q it is the
    ValueError; in S, K, T, bid or ask it becomes +inf or -inf as in load_chain (the dict returned: column -> {row: value}). The
    same for both backends; nothing is priced before."""
    fixed={}
    for i in range(n):
        v=chain['side'][i]
        if isinstance(v,bool) or not isinstance(v,int):raise ValueError(f'chain row {i} field side: an int side code is required (0 call, 1 put)')
        for key in ('S','K','T','bid','ask'):
            v=chain[key][i]
            if not _number(v):raise ValueError(f'chain row {i} field {key}: a real number is required')
            if isinstance(v,int):
                try:float(v)
                except OverflowError:fixed.setdefault(key,{})[i]=math.inf if v>0 else -math.inf
        for key in ('r','q'):
            v=chain[key][i]
            if not _number(v):raise ValueError(f'chain row {i} field {key}: a finite number is required')
            try:finite=math.isfinite(v)
            except OverflowError:finite=False
            if not finite:raise ValueError(f'chain row {i} field {key}: a finite number is required')
    return fixed

def _check_arguments(chain,models,backend,workers):
    """The validated (models tuple in MODELS5 order, the chain to price); ValueError for any refused argument. Nothing starts before this."""
    if not isinstance(backend,str) or backend not in BACKENDS:raise ValueError(f'backend: one of {", ".join(BACKENDS)} (single-threaded; no shm, inproc or process pool)')
    if workers is not None:raise ValueError('workers: only None (a service call runs on one thread of one process)')
    models=check_models(models)
    return models,_check_chain(chain)

def price_chain(chain,*,models=('bsm','bjs','crr'),backend='python',workers=None):
    """The result of `chain` for the selected `models` on `backend`, in the reference.run shape (see the module text)."""
    models,chain=_check_arguments(chain,models,backend,workers)
    adapter=_adapter()
    if backend=='python':
        from optionlab import reference
        return reference.run(rows(chain),adapter.params,models=models)
    from optionlab import backends, native_codec as nc
    mask=nc.mask_of(models)
    raw=backends.cold_price('c-serial','direct','stdio',backends.prepare(chain,'stdio'),models=mask)
    return nc.materialize(raw['records'],raw['n'],raw['mask'],echo=raw['echo'])
