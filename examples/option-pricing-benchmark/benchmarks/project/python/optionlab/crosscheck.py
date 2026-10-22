"""Provider iv/greeks cross-check (never gates) and the provider unit-scale check (spec 3.6, 4).

EX-20 item 4 (plan Task 31): both read the models of the result they get, so a per-unit local summary (one model of MODELS5)
works as the `all` summary does: provider_crosscheck has one block per model of the result, and unit_scale uses the bsm part
when the result has one, else the first model of the result in MODELS5 order."""
import math
from optionlab.contract import MODELS5
from optionlab.numeric import median, quantile
CANDIDATE_SCALES=(1.0,100.0,0.01,365.0,1/365.0)
PROVIDER_FIELDS=('iv','delta','gamma','theta','vega')

def provider_crosscheck(chain,result,scale=None):
    out={}
    for m in result['models']:
        col=result['models'][m];out[m]={}
        for f in PROVIDER_FIELDS:
            s=(scale or {}).get(f,1.0)
            diffs=[abs(col[f][i]*s-chain['provider'][f][i]) for i in range(chain['n']) if col['status'][i]=='OK' and math.isfinite(chain['provider'][f][i])]
            out[m][f]={'count':len(diffs),'median':median(diffs) if diffs else None,'p90':quantile(diffs,0.9) if diffs else None}
    return out

def unit_scale(chain,result,model=None):
    """`model` None: bsm when the result holds it, else the first model of the result in MODELS5 order (a per-unit result)."""
    if model is None:model='bsm' if 'bsm' in result['models'] else next(m for m in MODELS5 if m in result['models'])
    col=result['models'][model];out={}
    for f in ('delta','gamma','theta','vega'):
        ratios=[chain['provider'][f][i]/col[f][i] for i in range(chain['n'])
                if col['status'][i]=='OK' and col[f][i]!=0 and math.isfinite(chain['provider'][f][i]) and 0.95<=chain['K'][i]/chain['S'][i]<=1.05]
        if not ratios or median(ratios)==0:
            out[f]={'scale':None,'rescaled':False};continue
        med=abs(median(ratios));best=min(CANDIDATE_SCALES,key=lambda c:abs(math.log(med/c)))
        out[f]={'scale':best,'rescaled':best!=1.0,'median_ratio':med}
    return out
