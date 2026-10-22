"""Seeded deterministic synthetic chain in the Market Data columnar schema (spec 9). CI and exports use only this.
Declared targets (per 200 rows): INVALID_INPUT, EXPIRED, NO_BID (2), CROSSED, BELOW_MIN, ABOVE_MAX. MODEL_DOMAIN and NOT_CONVERGED are
not generated: they do not occur for the case parameters inside the oracle grid (spec 3.3, pre-flight S-08).
Amendment D item 3: rounding-band rows are kept (only bound-price rows are drawn again), and every row j with j % 4 == 1
that has no target is an out-of-the-money put (K < SPOT <= F), so such puts are at least 20 % of every tier from small up."""
import hashlib, json, math, random
from optionlab.contract import MODELS
from optionlab.models import bjs_price, bsm, sigma_lo
from optionlab.reference import price_function

SIZES={'tiny':1,'small':256,'medium':1024,'large':13230}
UPDATED=1791331200
SPOT=600.0
TENOR_DAYS=(0.25,1,2,7,14,30,45,60,90,120,180,270,365,540,730,1095)
TARGETS={7:'INVALID_INPUT',23:'EXPIRED',41:'NO_BID',59:'NO_BID',77:'CROSSED',101:'BELOW_MIN',151:'ABOVE_MAX'}
KEYS=('optionSymbol','underlying','expiration','side','strike','firstTraded','dte','updated','bid','bidSize','mid','ask','askSize','last',
      'openInterest','volume','inTheMoney','intrinsicValue','extrinsicValue','underlyingPrice','iv','delta','gamma','theta','vega')

def surface(k,T):return 0.20-0.08*k+0.12*k*k+0.03/math.sqrt(T+0.02)

def ambiguous(row,params):
    """True when mid is within 1e-9*max(1, mid) of a bound price (sigma_lo or 5.0) of any model: py-reference's
    boundary_ambiguous rule (spec 3.3). Rounding-band rows are kept (Amendment D item 3)."""
    side,S,K,T,bid,ask,r,q=row;mid=(bid+ask)/2.0;band=1e-9*max(1.0,mid)
    for m in MODELS:
        price=price_function(m,params)
        for s in (sigma_lo(m,side,T,r,q,params),params.sigma_hi):
            if abs(price(side,S,K,T,r,q,s)-mid)<=band:return True
    return False

def otm_put_share(chain,params):
    """Share of rows that are out-of-the-money puts (K < F, F = S exp((r - q) T)) among all rows (Amendment D item 3)."""
    n=len(chain['strike']);k=0
    for side,K,S,e,u in zip(chain['side'],chain['strike'],chain['underlyingPrice'],chain['expiration'],chain['updated']):
        T=(e-u)/31536000.0;k+=side=='put' and K<S*math.exp((params.rate-params.dividend_yield)*T)
    return k/n if n else 0.0

def _row(j,rng,params):
    days=TENOR_DAYS[j%len(TENOR_DAYS)];T=days/365.0;side=rng.randrange(2)
    K=float(round(SPOT*(0.5+2.0*rng.random())));target=TARGETS.get(j%200)
    if target=='BELOW_MIN':K=float(round(SPOT*(0.7 if side==0 else 1.3)))
    elif target is None and j%4==1:side=1;K=float(round(SPOT*(0.7+0.28*rng.random())))   # OTM put: K < SPOT <= F (r > q)
    sig=surface(math.log(K/SPOT),T);price=bjs_price(side,SPOT,K,T,params.rate,params.dividend_yield,sig)
    spread=max(0.01,0.04*price);mid=price+rng.gauss(0.0,0.1*spread)
    bid=max(0.01,round(mid-spread/2.0,2));ask=max(bid,round(mid+spread/2.0,2));expiration=UPDATED+int(round(days*86400))
    if target=='INVALID_INPUT':K=0.0
    elif target=='EXPIRED':expiration=UPDATED
    elif target=='NO_BID':bid=0.0
    elif target=='CROSSED':ask=round(bid-0.05,2) if bid>0.06 else 0.01;bid=max(bid,ask+0.05)
    elif target=='BELOW_MIN':
        intrinsic=(SPOT-K) if side==0 else (K-SPOT);bid=ask=round(intrinsic-1.0,2)
    elif target=='ABOVE_MAX':bid=ask=round(3.0*SPOT,2)
    greeks=bsm(side,SPOT,K if K>0 else 1.0,max(T,1e-6),params.rate,params.dividend_yield,sig)
    oi=rng.randrange(5000)
    # Market Data columns the workload does not read; drawn after every priced column, so they never move a priced value.
    mid_q=round((bid+ask)/2.0,3);intrinsic=max(0.0,(SPOT-K) if side==0 else (K-SPOT))
    first=UPDATED-86400*(1+rng.randrange(400));bid_size=rng.randrange(1,500);ask_size=rng.randrange(1,500)
    last=round(max(0.0,mid_q+rng.gauss(0.0,0.05*spread)),2);volume=rng.randrange(20000)
    return target,(side,SPOT,K,T if expiration>UPDATED else 0.0,bid,ask,params.rate,params.dividend_yield),{
        'optionSymbol':f'SYN{expiration}{"CP"[side]}{int(K):05d}','underlying':'SYN','side':('call','put')[side],'strike':K,'expiration':expiration,
        'firstTraded':first,'dte':int(round((expiration-UPDATED)/86400.0)),'updated':UPDATED,
        'bid':bid,'bidSize':bid_size,'ask':ask,'askSize':ask_size,'mid':mid_q,'last':last,'underlyingPrice':SPOT,'openInterest':oi,'volume':volume,
        'inTheMoney':intrinsic>0.0,'intrinsicValue':round(intrinsic,2),'extrinsicValue':round(mid_q-intrinsic,2),
        'iv':sig,'delta':greeks[1],'gamma':greeks[2],'theta':greeks[3],'vega':greeks[4]}

def row(j,seed,params):
    """The record of row j alone (its own generator seeded from (seed, j, attempt)); `generate` is these rows in order."""
    for attempt in range(100):
        rng=random.Random(f'{seed}:{j}:{attempt}')
        target,priced,record=_row(j,rng,params)
        if target is not None or not ambiguous(priced,params):return record
    raise RuntimeError('generator could not place a non-ambiguous row')

def generate(n,seed,params):
    """Row j uses its own generator seeded from (seed, j, attempt), so prefixes are stable."""
    cols={k:[] for k in KEYS}
    for j in range(n):
        record=row(j,seed,params)
        for k in KEYS:cols[k].append(record[k])
    return {'s':'ok',**cols}

def dataset_digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def as_local_sample(data,days=1):
    """Test support for the EX-6 market step (never an owner row): the bytes of a synthetic dataset relabeled as a local dataset.
    The optionSymbol prefix SYN becomes LOC (so contract.decode_chain_origin does not label it synthetic) and `updated` and
    `expiration` move `days` days earlier (T unchanged; the default puts the snapshot on 2026-10-05, New York, the protocol SOFR
    day). Synthetic data in, synthetic data out."""
    obj=json.loads(data);shift=86400*days
    obj['optionSymbol']=['LOC'+s[3:] for s in obj['optionSymbol']]
    for k in ('updated','expiration'):obj[k]=[None if v is None else v-shift for v in obj[k]]
    return json.dumps(obj).encode()
