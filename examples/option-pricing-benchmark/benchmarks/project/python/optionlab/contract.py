"""Workload contract option-chain-greeks v1: columnar Market Data chain input (spec 3.1, 3.2)."""
import json, math, re
STATUSES=('INVALID_INPUT','EXPIRED','NO_BID','CROSSED','MODEL_DOMAIN','BELOW_MIN','ABOVE_MAX','NOT_CONVERGED','OK')
ALL_MODELS=('bsm','bjs','crr');MODELS=ALL_MODELS;FIELDS=('iv','price','delta','gamma','theta','vega','rho')
MODELS4=('bsm','bjs','crr','baw')     # Amendment G1.7: the BAW-era model set (the four-model panel keeps it until Task A6)
MODELS5=('bsm','bjs','crr','baw','alo')     # Amendment I1.3, I6: bit and record order of every mask (bit 1 << MODELS5.index(m); alo bit 16)
# baw: py-reference since G-BAW2 part A (Task 5); py-optimized and py-library since part B (Task 6).
# alo: named by G-ALO-CO part 2 (Task A2, Amendment I13.1); py-reference since G-ALO2 part A (Task A4); py-optimized,
# py-library since G-ALO2 part B (Task A5): PART_B_PENDING is empty, check_variant_models refuses nothing.
PENDING_MODELS={}
PART_B_PENDING={}

def check_variant_models(models):
    """The model list of a py-optimized or py-library run (check_models), refusing a model of PART_B_PENDING with its text."""
    models=check_models(models)
    for m in models:
        if m in PART_B_PENDING:raise ValueError(PART_B_PENDING[m])
    return models

def selector_models(selector):
    """Amendment G4: the models of a case selector. 'all' is ALL_MODELS (mask 7); one name of MODELS5 is that model; a
    pending model raises ValueError(PENDING_MODELS[selector])."""
    if selector=='all':return ALL_MODELS
    if isinstance(selector,str) and selector in PENDING_MODELS:raise ValueError(PENDING_MODELS[selector])
    if isinstance(selector,str) and selector in MODELS5:return (selector,)
    raise ValueError('unknown selector')

def check_models(models):
    """A model list of a per-model run: a non-empty tuple or list of distinct MODELS5 names (none pending), returned in
    MODELS5 order; anything else raises ValueError (a pending model with its PENDING_MODELS text)."""
    if not isinstance(models,(tuple,list)) or not models:raise ValueError('models: a non-empty list of model names required')
    if any(not isinstance(m,str) or m not in MODELS5 for m in models) or len(set(models))!=len(models):raise ValueError('models: unknown or repeated model name')
    for m in models:
        if m in PENDING_MODELS:raise ValueError(PENDING_MODELS[m])
    return tuple(m for m in MODELS5 if m in models)
SECONDS_PER_YEAR=31536000;MAX_CONTRACTS=20000;MAX_INPUT_BYTES=32*1024*1024
NUMERIC=('strike','expiration','updated','bid','ask','mid','underlyingPrice','openInterest','iv','delta','gamma','theta','vega')
REQUIRED_KEYS=('optionSymbol','side')+NUMERIC

class ChainError(ValueError):
    """Whole-input rejection. The message holds a record index and a fixed key name only, never record content."""
    def __init__(self,index,key):
        self.index=index;self.key=key
        super().__init__(f'record {index}: {key}' if index is not None else f'chain: {key}')

def _no_constant(_token):
    raise ChainError(None,'input is not JSON')

def _unique_pairs(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ChainError(None,'duplicate key')
        out[k]=v
    return out

SYNTHETIC_SYMBOL=re.compile(r'SYN[0-9]+[CP][0-9]{5}');SYNTHETIC_UNDERLYING='SYN'   # the exact form of every optionSymbol and underlying of optionlab.synthetic (EX-6, T11T12-A03)

def _decode(data):
    if len(data)>MAX_INPUT_BYTES:raise ChainError(None,'input exceeds 32 MiB')
    try:return json.loads(data,parse_constant=_no_constant,object_pairs_hook=_unique_pairs)
    except ChainError:raise
    except (ValueError,UnicodeDecodeError,RecursionError):raise ChainError(None,'input is not JSON') from None

def decode_chain(data):
    """Strict JSON (RFC 8259): the tokens NaN, Infinity and -Infinity and a duplicate object key reject the whole input,
    as a strict C parser does. Nesting too deep for the parser also rejects the whole input."""
    return load_chain(_decode(data))

def decode_chain_origin(data):
    """(chain, synthetic): the decoded chain and whether the dataset is positively labeled synthetic, that is, the chain is not
    empty, every optionSymbol fullmatches the generator form (SYN, expiration digits, C or P, five strike digits) and `underlying`
    is "SYN" on every row (what optionlab.synthetic writes). Any other dataset, the owner chain and a chain with a SYNA-style
    root included, is not synthetic: the adapter prices it with the protocol market rate and never with the case assumptions
    (EX-6, T9-A04 fail closed). The flag holds no record value."""
    obj=_decode(data);chain=load_chain(obj);under=obj.get('underlying')
    ok=chain['n']>0 and isinstance(under,list) and len(under)==chain['n'] and all(isinstance(u,str) and u==SYNTHETIC_UNDERLYING for u in under)
    return chain,ok and all(SYNTHETIC_SYMBOL.fullmatch(s) is not None for s in obj['optionSymbol'])

def load_chain(obj):
    if not isinstance(obj,dict):raise ChainError(None,'top level is not an object')
    if obj.get('s')!='ok':raise ChainError(None,'s')
    for key in REQUIRED_KEYS:
        if not isinstance(obj.get(key),list):raise ChainError(None,key)
    n=len(obj['optionSymbol'])
    if n>MAX_CONTRACTS:raise ChainError(None,'more than 20000 contracts')
    if any(len(obj[k])!=n for k in REQUIRED_KEYS):raise ChainError(None,'array lengths differ')
    def number(key,i):
        v=obj[key][i]
        if v is None:return math.nan
        if isinstance(v,bool) or not isinstance(v,(int,float)):raise ChainError(i,key)
        try:return float(v)
        except OverflowError:return math.inf if v>0 else -math.inf   # an integer beyond binary64 is a non-finite number: INVALID_INPUT for its row, as 1e400 is
    for i,v in enumerate(obj['optionSymbol']):
        if not isinstance(v,str):raise ChainError(i,'optionSymbol')
    side=[]
    for i,v in enumerate(obj['side']):
        if v is not None and not isinstance(v,str):raise ChainError(i,'side')
        side.append(0 if v=='call' else 1 if v=='put' else -1)
    c={k:[number(k,i) for i in range(n)] for k in NUMERIC}
    T=[(e-u)/SECONDS_PER_YEAR for e,u in zip(c['expiration'],c['updated'])]
    return {'n':n,'side':side,'S':c['underlyingPrice'],'K':c['strike'],'T':T,'bid':c['bid'],'ask':c['ask'],'provider_mid':c['mid'],
            'open_interest':c['openInterest'],'expiration':c['expiration'],'updated':c['updated'],'provider':{f:c[f] for f in ('iv','delta','gamma','theta','vega')}}

def _rate_column(value,n,key):
    """One per-row rate column: a finite binary64 number for every row, or a list of n of them (bool and text rejected)."""
    ok=lambda v:not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)
    if isinstance(value,(list,tuple)):
        if len(value)!=n or not all(ok(v) for v in value):raise ValueError(f'{key} column: {n} finite numbers required')
        return [float(v) for v in value]
    if not ok(value):raise ValueError(f'{key}: a finite number required')
    return [float(value)]*n

def with_rates(chain,r,q):
    """The chain with per-row continuous rate `r` and dividend yield `q` columns (spec 3.1: each row carries its own r and
    q). CI, tests and the synthetic chain fill them from the case parameters; owner-chain local runs fill r = SOFR and q =
    q_e of the row's expiry (Amendment C item 3). `r` and `q` are each one number for every row or a list of n numbers."""
    out=dict(chain);out['r']=_rate_column(r,chain['n'],'r');out['q']=_rate_column(q,chain['n'],'q');return out

def rates(chain,params=None,market=None):
    """(r, q) per-row lists: with `market` ({'rate': r, 'q': {expiration: q_e}}, Amendment C) r and the q_e of each row's
    expiry (optionlab.market.market_columns); else the chain's columns, or, for a chain without them, the case parameters."""
    if market is not None:
        from optionlab.market import market_columns
        return market_columns(chain,market)
    if 'r' in chain and 'q' in chain:return chain['r'],chain['q']
    if params is None:raise ValueError('chain has no per-row r and q columns and no case parameters were given')
    filled=with_rates(chain,params.rate,params.dividend_yield);return filled['r'],filled['q']

def rows(chain,params=None,market=None):
    """py-reference row tuples (side, S, K, T, bid, ask, r, q); r and q per row (see `rates`)."""
    r,q=rates(chain,params,market)
    return [(chain['side'][i],chain['S'][i],chain['K'][i],chain['T'][i],chain['bid'][i],chain['ask'][i],r[i],q[i]) for i in range(chain['n'])]

def slice_chain(chain,n):
    if not 0<=n<=chain['n']:raise ValueError('slice outside the chain')
    out={k:(v[:n] if isinstance(v,list) else v) for k,v in chain.items() if k!='provider'}
    out['provider']={k:v[:n] for k,v in chain['provider'].items()};out['n']=n;return out

def mid_differences(chain,limit=0.005):
    return sum(1 for b,a,m in zip(chain['bid'],chain['ask'],chain['provider_mid']) if math.isfinite(m) and math.isfinite(b) and math.isfinite(a) and abs((b+a)/2.0-m)>limit)
