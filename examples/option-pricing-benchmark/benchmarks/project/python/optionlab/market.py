"""Amendment C: SOFR rate and per-expiry carry-implied dividend yields from put-call parity (owner chain, local runs only).
The local domain is not qualified by the section 3.3-3.4 derivations or the oracle grid.

Privacy (spec 12; controller rule of Task 18b): the estimator and the pricing use every accepted pair, but the public
aggregate block withholds (null) every value computed from fewer than MIN_PUBLIC_PAIRS pairs: q of a parity-median
expiry, a `nearest` q copied from a withheld estimate, the MAD and the exercise-bias quantities. Counts, methods, flags,
dates and T_e stay public.

The New York date and business-date rule are the Task 18a rule of the framework tools/bench_market.py (commit 34512cd), which
FR3 removed; the holiday lists are pinned by the example test HolidayCalendarTests.

EX-6 (no network step): the risk-free rate is the dated SOFR constant of the protocol (optionlab.protocol.sofr(), oracle.json
market_constants.sofr: day, percent, source, url). `protocol_rate()` is the only reader. The model rate is the continuous ACT/365
rate r = 365 ln(1 + R/360) of the percent R/100 (continuous_rate), as the removed market step computed it; the protocol field
`rate` (percent/100 = 0.0389) is the simple ACT/360 rate and is not the model rate. There is no environment, argument or file
override and no network access."""
import datetime, math
from optionlab import protocol
from optionlab.numeric import median
Q_LO,Q_HI,MIN_PAIRS,MIN_T,BAND,ASSUMED_Q,EXDIV_T,EXDIV_JUMP=-0.05,0.15,3,7/365,0.05,0.012,30/365,0.05
MIN_PUBLIC_PAIRS=5;MAX_EXPIRIES=64

# ---- the Task 18a calendar (the framework tools/bench_market.py left in FR3; HolidayCalendarTests pins this copy) ----
SUPPORTED_YEARS=(2025,2026,2027)
FED_HOLIDAYS=frozenset({
    '2025-01-01','2025-01-20','2025-02-17','2025-05-26','2025-06-19','2025-07-04','2025-09-01','2025-10-13','2025-11-11','2025-11-27','2025-12-25',
    '2026-01-01','2026-01-19','2026-02-16','2026-05-25','2026-06-19','2026-07-04','2026-09-07','2026-10-12','2026-11-11','2026-11-26','2026-12-25',
    '2027-01-01','2027-01-18','2027-02-15','2027-05-31','2027-06-19','2027-07-05','2027-09-06','2027-10-11','2027-11-11','2027-11-25','2027-12-25'})
SIFMA_CLOSURES=frozenset()

def _nth_sunday(year,month,n):
    d=datetime.date(year,month,1);d+=datetime.timedelta(days=(6-d.weekday())%7);return d+datetime.timedelta(weeks=n-1)

def new_york_date(epoch):
    """US Eastern date: EDT (UTC-4) from the second Sunday of March 02:00 EST to the first Sunday of November 02:00 EDT."""
    utc=datetime.datetime.fromtimestamp(epoch,datetime.timezone.utc);y=utc.year
    start=datetime.datetime.combine(_nth_sunday(y,3,2),datetime.time(7),datetime.timezone.utc)
    end=datetime.datetime.combine(_nth_sunday(y,11,1),datetime.time(6),datetime.timezone.utc)
    return (utc-datetime.timedelta(hours=4 if start<=utc<end else 5)).date()

def continuous_rate(percent):
    """The continuous ACT/365 model rate of an overnight simple ACT/360 rate of `percent` percent: 365 ln(1 + R/360), R = percent/100."""
    return 365*math.log1p(percent/100/360)

def protocol_rate():
    """The protocol SOFR constant as the rate record of the market block: {effective_date, percent_rate, continuous_rate}. The only
    source of the market rate of an owner-chain run (no network, environment variable, argument or other file)."""
    s=protocol.sofr();percent=float(s['percent'])
    if isinstance(s['percent'],bool) or not math.isfinite(percent):raise ValueError('protocol SOFR percent is not a finite number')
    return {'effective_date':s['day'],'percent_rate':percent,'continuous_rate':continuous_rate(percent)}

def expected_effective(day):
    """The SOFR effective date of a snapshot date: the day when it is a business day, else the previous business day
    (weekends, FED_HOLIDAYS, SIFMA_CLOSURES). ValueError outside SUPPORTED_YEARS."""
    if day.year not in SUPPORTED_YEARS:raise ValueError('snapshot year outside the supported holiday calendar')
    while day.weekday()>=5 or day.isoformat() in FED_HOLIDAYS or day.isoformat() in SIFMA_CLOSURES:
        day-=datetime.timedelta(days=1)
        if day.year not in SUPPORTED_YEARS:raise ValueError('snapshot year outside the supported holiday calendar')
    return day

def snapshot(chain):
    """(New York date of the largest finite `updated`, count of rows whose finite `updated` has another New York date)."""
    ups=[u for u in chain['updated'] if math.isfinite(u)]
    if not ups:raise ValueError('chain has no finite updated time')
    day=new_york_date(max(ups));return day,sum(1 for u in ups if new_york_date(u)!=day)

# ---- pairs and the estimator (Amendment C item 3) ----
def eligible(chain,i):
    """Section 3.3 orders 1-4 pass (positive form: a NaN fails every comparison). NO_BID rows (bid null, 0 or negative) fail."""
    v=[chain[k][i] for k in ('S','K','T','bid','ask')]
    return chain['side'][i] in (0,1) and all(math.isfinite(x) for x in v) and v[0]>0.0 and v[1]>0.0 and v[2]>0.0 and v[3]>0.0 and v[4]>=v[3]

def quotable(b,a):m=(a+b)/2.0;return m>=0.05 and a-b<=max(0.05,0.10*m)

def _pairs(chain,r):
    """({expiration: [(K, T, C_mid, P_mid, S)]}, {expiration: skipped}): a call and a put of the same expiration and strike,
    both eligible and quotable; a pair whose rows differ in `updated` or `underlyingPrice` is skipped and counted."""
    calls={};puts={};out={};skipped={}
    for i in range(chain['n']):
        if eligible(chain,i) and quotable(chain['bid'][i],chain['ask'][i]):(calls if chain['side'][i]==0 else puts)[(chain['expiration'][i],chain['K'][i])]=i
    for key in sorted(set(calls)&set(puts)):
        c,p=calls[key],puts[key]
        if chain['updated'][c]!=chain['updated'][p] or chain['S'][c]!=chain['S'][p]:skipped[key[0]]=skipped.get(key[0],0)+1;continue
        S,K,T=chain['S'][c],key[1],chain['T'][c];F=S*math.exp(r*T)
        if T>=MIN_T and F*math.exp(-BAND)<=K<=F:out.setdefault(key[0],[]).append((K,T,(chain['bid'][c]+chain['ask'][c])/2,(chain['bid'][p]+chain['ask'][p])/2,S))
    return out,skipped

def pairs(chain,r):
    """(pairs per expiration, total skipped count)."""
    out,skipped=_pairs(chain,r);return out,sum(skipped.values())

def q_from_pair(S,K,T,r,C,P):
    x=(C-P+K*math.exp(-r*T))/S
    return -math.log(x)/T if x>0.0 else None

def estimate(chain,r):
    """{expiration: {t_years, pairs, dropped, skipped, mad, rejected_bounds, q, method, ex_dividend_suspect, source}} for
    every expiration with an eligible row. `source` is the expiration whose estimate a `nearest` row copies."""
    found,skipped=_pairs(chain,r);rows_T={}
    for i in range(chain['n']):
        if eligible(chain,i):rows_T.setdefault(chain['expiration'][i],[]).append(chain['T'][i])
    table={}
    for e,Ts in rows_T.items():
        got=[(q,T) for q,T in ((q_from_pair(S,K,T,r,C,P),T) for K,T,C,P,S in found.get(e,[])) if q is not None]
        qs=[q for q,_ in got];t=median([T for _,T in got]) if got else median(Ts)
        row={'t_years':t,'pairs':len(qs),'dropped':len(found.get(e,[]))-len(qs),'skipped':skipped.get(e,0),'mad':None,'rejected_bounds':0,'q':None,'method':None,
             'ex_dividend_suspect':False,'source':None,'_raw':None}
        if len(qs)>=MIN_PAIRS and t>=MIN_T:
            m=median(qs);row['mad']=median([abs(x-m) for x in qs]);row['_raw']=m
            if Q_LO<=m<=Q_HI:row.update(q=m,method='parity-median')
            else:row['rejected_bounds']=1
        table[e]=row
    order=sorted(table,key=lambda e:(table[e]['t_years'],e))
    raws=[(k,table[e]['_raw']) for k,e in enumerate(order) if table[e]['_raw'] is not None]
    for k,e in enumerate(order):                                       # ex-dividend flag (Amendment C item 3)
        row=table[e];raw=row['_raw']
        if raw is None or row['t_years']>EXDIV_T:continue
        # review Minor 3: the neighbouring estimates are the nearest estimated expiries on each side in T_e (an expiry
        # without an estimate between them is passed over)
        before=[x for j,x in raws if j<k];after=[x for j,x in raws if j>k]
        nb=([before[-1]] if before else [])+([after[0]] if after else [])
        row['ex_dividend_suspect']=raw>Q_HI or (bool(nb) and all(raw>x+EXDIV_JUMP for x in nb))
    good=[(table[e]['t_years'],e) for e in order if table[e]['method']=='parity-median']
    for e in order:
        row=table[e]
        if row['method']:continue
        if good:near=min(good,key=lambda g:(abs(g[0]-row['t_years']),g[0]))[1];row.update(q=table[near]['q'],method='nearest',source=near)
        else:row.update(q=ASSUMED_Q,method='assumption')
    for row in table.values():row.pop('_raw')
    return table

def table_json(table):return [[e,row['q']] for e,row in sorted(table.items())]
def table_from_json(items):return {float(e):float(q) for e,q in items}

def market_columns(chain,market):
    """Per-row (r, q) lists of a chain priced with `market` = {'rate': r, 'q': {expiration: q_e}}. An eligible row needs
    its expiry's q (ValueError otherwise); a row that fails status orders 1-4 is decided before any rate is used, so it
    takes ASSUMED_Q (its output does not depend on it)."""
    table=market['q'];q=[]
    for i in range(chain['n']):
        e=chain['expiration'][i]
        if e in table:q.append(table[e])
        elif eligible(chain,i):raise ValueError('an eligible row has no market dividend yield for its expiry')
        else:q.append(ASSUMED_Q)
    return [market['rate']]*chain['n'],q

# ---- American exercise bias (Amendment C item 4) ----
def exercise_bias(chain,r,table,params):
    """Per expiry, over its accepted pairs: each side's BjS implied volatility (py-reference solve with r and q_e), the
    premium e = BjS - BSM at that volatility, dq = (e_P - e_C)/(S T e^{-q_e T}). Returns {expiration: {count, bias_median,
    bias_max, premium_spread_median}} with the median of (e_P - e_C)/S. BjS is a lower bound on the American price, so
    these numbers are lower bounds."""
    from optionlab.reference import evaluate3 as evaluate
    from optionlab.models import bjs_price, bsm_price
    found,_=_pairs(chain,r);out={}
    for e,row in table.items():
        qe=row['q'];dqs=[];spreads=[]
        for K,T,C,P,S in found.get(e,[]):
            if q_from_pair(S,K,T,r,C,P) is None:continue
            prem=[]
            for side,mid in ((0,C),(1,P)):
                st,vals,_=evaluate((side,S,K,T,mid,mid,r,qe),'bjs',params)
                if st!='OK':break
                iv=vals[0];prem.append(bjs_price(side,S,K,T,r,qe,iv)-bsm_price(side,S,K,T,r,qe,iv))
            if len(prem)!=2:continue
            d=prem[1]-prem[0];dq=d/(S*T*math.exp(-qe*T))
            if math.isfinite(d) and math.isfinite(dq):spreads.append(d/S);dqs.append(dq)
        out[e]={'count':len(dqs),'bias_median':median(dqs) if dqs else None,'bias_max':max(dqs) if dqs else None,
                'premium_spread_median':median(spreads) if spreads else None}
    return out

# ---- the aggregate block (Amendment C item 6) ----
def _round(x,digits):return None if x is None else round(x,digits)

def public(table,bias,rate):
    """The aggregate `market` block: the SOFR record (effective date, percent and continuous rate, the snapshot date and
    the updated_other_date count) and per expiry (by expiration) the New York expiration date, T_e (1e-4 years, at least
    1e-4), q (1e-6), method, flag, counts (bias_pairs: the pairs whose two BjS solves are OK), MAD and bias (1e-6). Values
    over fewer than MIN_PUBLIC_PAIRS pairs (bias: bias pairs) are null."""
    if len(table)>MAX_EXPIRIES:raise ValueError(f'more than {MAX_EXPIRIES} expiries')
    def withheld(e):
        row=table[e]
        if row['method']=='parity-median':return row['pairs']<MIN_PUBLIC_PAIRS
        if row['method']=='nearest':return withheld(row['source'])
        return False
    expiries=[]
    for e in sorted(table):
        row=table[e];b=bias.get(e) or {};small=(b.get('count') or 0)<MIN_PUBLIC_PAIRS
        expiries.append({'expiration_date':new_york_date(e).isoformat(),'t_years':max(round(row['t_years'],4),1e-4),
                         'q':None if withheld(e) else _round(row['q'],6),'method':row['method'],'ex_dividend_suspect':bool(row['ex_dividend_suspect']),
                         'pairs':row['pairs'],'skipped':row['skipped'],'dropped':row['dropped'],'mad':None if row['pairs']<MIN_PUBLIC_PAIRS else _round(row['mad'],6),
                         'rejected_bounds':row['rejected_bounds'],'bias_pairs':b.get('count') or 0,**{k:None if small else _round(b.get(k),6) for k in ('bias_median','bias_max','premium_spread_median')}})
    return {'rate':{k:rate[k] for k in ('effective_date','percent_rate','continuous_rate','updated_other_date','snapshot_date')},
            'expiries':expiries,'assumption_used':any(x['method']=='assumption' for x in expiries),'domain_qualified':False}
