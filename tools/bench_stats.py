"""Host statistics over recorded evidence only (spec 8.3). Pure Python."""
import math, numbers, random

def median(xs):
    s=sorted(xs);n=len(s)
    if not n:raise ValueError('median of empty data')
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0

def quantile(xs,p):
    s=sorted(xs);h=(len(s)-1)*p;lo=int(h);hi=min(lo+1,len(s)-1);return s[lo]+(h-lo)*(s[hi]-s[lo])

def summarize(xs):
    xs=list(xs)
    if not xs:return {'n':0,'median':None,'iqr':None,'min':None,'max':None}
    return {'n':len(xs),'median':median(xs),'iqr':quantile(xs,0.75)-quantile(xs,0.25),'min':min(xs),'max':max(xs)}

TIME_UNITS={'ns':1,'us':10**3,'ms':10**6,'s':10**9}
BYTE_UNITS={'B':1,'KiB':1024,'MiB':1024**2,'GiB':1024**3}

def convert(value,src,dst):
    """B02: exact unit conversion within one family (time or bytes)."""
    from fractions import Fraction
    for table in (TIME_UNITS,BYTE_UNITS):
        if src in table and dst in table:return Fraction(value)*table[src]/table[dst]
    raise ValueError('unknown or mixed units')

def _count(value):
    return not isinstance(value,bool) and isinstance(value,int) and value>0

def per_unit(total,units):
    if not _count(units):raise ValueError('invalid denominator')
    return total/units

def trial_value(inner):
    """B09: correlated inner samples of one trial collapse to one value."""
    if not inner:raise ValueError('trial without samples')
    return median(inner)

def trial_per_unit(inner,*,loops,size):
    """spec 8.2: one trial's per-unit figure = median of its inner samples / (loops x size)."""
    if not _count(loops) or not _count(size):raise ValueError('invalid loops or size')
    return per_unit(trial_value(inner),loops*size)

def per_trial_values(observations,field):
    """Non-warmup observations grouped by trial_id; each trial gives one per-unit value (inner samples are never trials).
    Task 16: trial ids carry the session and shuffled order, so two rows never share a key. Before classify, select one
    (variant, workers, mode) row and re-key its per-trial values by the trial's block; classify pairs blocks, not trial ids."""
    groups={}
    for o in observations:
        if not o['warmup']:groups.setdefault(o['trial_id'],[]).append(o)
    out={}
    for tid,obs in groups.items():
        shape={(o['loops'],o['work_units']) for o in obs}
        if len(shape)!=1:raise ValueError(f'{tid}: inner samples disagree on loops or work units')
        loops,size=shape.pop();out[tid]=trial_per_unit([o[field] for o in obs],loops=loops,size=size)
    return out

def classify(base,other,*,relative,min_abs,min_blocks,resamples=10000,seed=20261007,interval=0.95):
    """B09: paired-block outcome. Missing, unpaired, invalid or noisy evidence is INCONCLUSIVE; the caller never re-runs to change it.
    A bad parameter is a caller error (ValueError): one block can never decide an outcome."""
    if not _count(min_blocks) or min_blocks<2:raise ValueError('min_blocks must be an integer of at least 2')
    if not _count(resamples):raise ValueError('resamples must be a positive integer')
    if isinstance(interval,bool) or not isinstance(interval,numbers.Real) or not 0<interval<1:raise ValueError('interval must lie strictly between 0 and 1')
    ids=sorted(set(base)&set(other))
    if len(ids)<min_blocks or len(ids)!=len(base) or len(ids)!=len(other):return {'outcome':'INCONCLUSIVE','reason':'missing or unpaired trials','blocks':len(ids)}
    values=list(base.values())+list(other.values())
    if any(isinstance(v,bool) or not isinstance(v,numbers.Real) or not math.isfinite(v) or v<=0 for v in values):return {'outcome':'INCONCLUSIVE','reason':'invalid value or denominator','blocks':len(ids)}
    b=paired_block_bootstrap(base,other,resamples,seed,interval);moved=abs(median(other.values())-median(base.values()))>=min_abs
    if b['high']<1.0-relative and moved:out='FASTER'
    elif b['low']>1.0+relative and moved:out='SLOWER'
    elif b['low']>=1.0-relative and b['high']<=1.0+relative:out='EQUAL'
    else:out='INCONCLUSIVE'
    return {'outcome':out,**b}

def paired_block_bootstrap(base,other,resamples=10000,seed=20261007,interval=0.95):
    """95% paired block bootstrap of the ratio of medians other/base; resamples whole blocks, never inner iterations."""
    ids=sorted(set(base)&set(other))
    if not ids or len(ids)!=len(base) or len(ids)!=len(other):raise ValueError('bootstrap needs the same blocks on both sides')
    rng=random.Random(seed);n=len(ids);stats=[]
    for _ in range(resamples):
        pick=[ids[rng.randrange(n)] for _ in range(n)];stats.append(median([other[i] for i in pick])/median([base[i] for i in pick]))
    stats.sort();tail=(1.0-interval)/2.0
    return {'ratio':float(median(other.values())/median(base.values())),'low':float(stats[int(math.floor(tail*resamples))]),
            'high':float(stats[int(math.ceil((1.0-tail)*resamples))-1]),'resamples':resamples,'seed':seed,'blocks':n}

def median_interval(values,resamples,seed,a,indices=None):
    """Amendment G8.3: one-sided bounds of the median of the block values; (L(a), U(a))."""
    ids=sorted(values);n=len(ids)
    if not n:raise ValueError('median_interval needs at least one block')
    if not _count(resamples):raise ValueError('resamples must be a positive integer')
    if isinstance(a,bool) or not isinstance(a,numbers.Real) or not 0<a<0.5:raise ValueError('tail must lie strictly between 0 and 0.5')
    if indices is None:
        rng=random.Random(seed);indices=[[rng.randrange(n) for _ in range(n)] for _ in range(resamples)]
    if len(indices)!=resamples:raise ValueError('indices must hold one list per resample')
    if any(len(pick)!=n or any(isinstance(i,bool) or not isinstance(i,int) or not 0<=i<n for i in pick) for pick in indices):raise ValueError('each resample holds n block positions in range')
    s=sorted(median([values[ids[i]] for i in pick]) for pick in indices)
    return s[int(math.floor(a*resamples))],s[int(math.ceil((1.0-a)*resamples))-1]

# ---- Amendment I15 (owner policy only): distribution-free order-statistic (sign-test) bounds for the median ----
def binomial_upper_tail(n,k):
    """P(Binomial(n, 0.5) >= k) as an exact fraction (numerator, 2**n)."""
    return sum(math.comb(n,i) for i in range(max(k,0),n+1)),2**n

def order_stat_rank(n,a):
    """k(n, a): the smallest k with P(Binomial(n, 0.5) >= k) <= a (exact integer arithmetic against the exact value of a);
    None when no k exists (a < 2**-n: the bound is unattainable)."""
    from fractions import Fraction
    if isinstance(n,bool) or not isinstance(n,int) or n<1:raise ValueError('n must be a positive integer')
    if isinstance(a,bool) or not isinstance(a,numbers.Real) or not 0<a<0.5:raise ValueError('tail must lie strictly between 0 and 0.5')
    level=Fraction(a)
    for k in range(n//2+1,n+1):
        num,den=binomial_upper_tail(n,k)
        if Fraction(num,den)<=level:return k
    return None

def order_stat_bounds(values,a):
    """(L(a), U(a)) = (x_(n+1-k), x_(k)) of the sorted block values with k = order_stat_rank(n, a); (-inf, +inf) when
    unattainable. P(median > U) <= a and P(median < L) <= a for i.i.d. block values (ties only make it conservative)."""
    s=sorted(values.values()) if isinstance(values,dict) else sorted(values);n=len(s)
    if not n:raise ValueError('order_stat_bounds needs at least one block')
    k=order_stat_rank(n,a)
    if k is None:return -math.inf,math.inf
    return s[n-k],s[k-1]
