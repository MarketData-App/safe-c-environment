"""Oracle fixture generator (spec 4, with the section 3.8 replacements of Task 7b); runs once per part in a bench container.
50 digits.

Part names are the job identifiers of the protected driver tools/bench_oracle.py. Since Task 7b (spec 3.8):
- part `bjs` holds the Bjerksund-Stensland 1993 closed form of section 3.4 in mpmath (the 2002 formula and its bivariate
  normal M(a, b, rho) left the definition);
- part `bvn` is retired (section 4 item 4 removed: the definition has no bivariate normal); generate('bvn') is refused and
  the fixture key stays an empty array (the protected schema schemas/bench-fixtures.json requires the key);
- part `lnphi` holds the QuantLib normal functions N(x) and n(x) against mpmath (section 4 item 8: N(x) on both sides of
  its series switch N = 1e-8 and of the density cutoff x^2 = 1380, plus a grid for item 4);
- part `greeks` keeps only the sups that the CRR bumps need (vega h_sigma, rho h_r; the h_S and theta-delta terms left);
- part `edges` has the section 3.8 item 8 rows (sigma_carry, sigma_trig, a non-finite evaluation row, the rounding-band row
  of section 3.3 with T = 1 year (round-2 item L-B), and CRR rows at the domain check), and the Amendment C item 5
  local-domain spot-check rows (`local-domain-*`; they do not qualify the local domain);
- part `baw` (Amendment G2.5, Task 5) holds the Barone-Adesi-Whaley items: `kind` 'edge' rows (item 8 list of G2.5, with
  the status, flags and exclusion reason that py-reference gives at generation, each designed property asserted here) and
  `kind` 'stencil' points (item 7 per side: the record's R7 stencil forms with the derivatives of the ideal BAW model,
  exact S* root at 50 digits, the sups of the remainder derivatives over the stencil interval, and the S* term (the
  approved erratum F7 to record R7, spec Appendix G-BAW R12; commits f893813 and 539afc3) that
  bounds the effect of the engine's S* tolerance on the differenced values);
- part `alo` (Amendment I4.4, Task A4) holds the Andersen-Lake-Offengenden item 8 rows (`kind` 'edge', with the status,
  flags and row equation that py-reference gives at generation, each designed property asserted; 'DEFECT' rows store the
  AloRunDefect kind and site of a test-only planted NaN or forced cap).
"""
import json, math, sys
import mpmath as mp
from optionlab.models import sigma_lo, crr_price, bjs_price, bsm_price, ModelDefect
from optionlab.mapping import unit
from optionlab.reference import price_function, tau_v
from optionlab.params import CASE, CaseParams
mp.mp.dps=50
PARTS=('bsm','bjs','lattice','greeks','monotonicity','edges','lnphi','baw','alo')
EPS=2.220446049250313e-16
SK_BJS=(0.3,0.6,0.9,1.0,1.1,1.5,3.0);T_BJS=(1/365/24,1/365,7/365,0.25,1.0,3.0)

def N(x):return mp.ncdf(x)
def bsm_mp(side,S,K,T,r,q,s):
    S,K,T,r,q,s=map(mp.mpf,(S,K,T,r,q,s));sq=mp.sqrt(T);d1=(mp.log(S/K)+(r-q+s*s/2)*T)/(s*sq);d2=d1-s*sq;dq=mp.e**(-q*T);dr=mp.e**(-r*T);pdf=mp.npdf(d1)
    if side==0:price=S*dq*N(d1)-K*dr*N(d2);delta=dq*N(d1);theta=-S*dq*pdf*s/(2*sq)-r*K*dr*N(d2)+q*S*dq*N(d1);rho=K*T*dr*N(d2)
    else:price=K*dr*N(-d2)-S*dq*N(-d1);delta=-dq*N(-d1);theta=-S*dq*pdf*s/(2*sq)+r*K*dr*N(-d2)-q*S*dq*N(-d1);rho=-K*T*dr*N(-d2)
    return price,delta,dq*pdf/(S*s*sq),theta/365,S*dq*pdf*sq/100,rho/100

def bjs_call_mp(S,K,T,r,b,s):
    """Bjerksund-Stensland 1993 call (spec 3.4; QuantLib 1.43 bjerksundstenslandengine.cpp:177-221, 432-482) in mpmath:
    the same branches (European call results when q <= 0 and q <= r with q = r - b; immediate exercise when S >= I; the
    European results when q_I > 12.5 or when the American value is lower; immediate exercise below (S - K)(1 + 10 eps))."""
    S,K,T,r,b,s=map(mp.mpf,(S,K,T,r,b,s));q=r-b
    euro=bsm_mp(0,S,K,T,r,q,s)[0]
    if q<=0 and q<=r:value=euro
    else:
        bT=b*T;rT=r*T;v=s*s*T;sv=mp.sqrt(v)
        beta=(mp.mpf(1)/2-bT/v)+mp.sqrt((bT/v-mp.mpf(1)/2)**2+2*rT/v);binf=beta/(beta-1)*K
        b0=K if bT==rT else max(K,rT/(rT-bT)*K);ht=-(bT+2*sv)*b0/(binf-b0);I=b0+(binf-b0)*(1-mp.e**ht)
        F=S*mp.e**bT;qI=mp.log(I/F)/sv
        def phi(g,H):
            lam=-rT+g*bT+g*(g-1)*v/2;d=-(mp.log(S/H)+bT+(g-mp.mpf(1)/2)*v)/sv;k=2*bT/v+2*g-1
            return mp.e**lam*(mp.ncdf(d)-(I/S)**k*mp.ncdf(d-2*mp.log(I/S)/sv))
        if S>=I:value=max(mp.mpf(0),S-K)
        elif qI>mp.mpf('12.5'):value=euro
        else:value=(I-K)*(S/I)**beta*(1-phi(beta,I))+S*phi(1,I)-S*phi(1,K)-K*phi(0,I)+K*phi(0,K)
        if value<euro:value=euro
    if value<(S-K)*(1+10*mp.mpf(EPS)):value=max(mp.mpf(0),S-K)
    return value

def bjs_mp(side,S,K,T,r,q,s):return bjs_call_mp(S,K,T,r,r-q,s) if side==0 else bjs_call_mp(K,S,T,q,q-r,s)

def bjs_grid(params):
    out=[]
    for side in (0,1):
        for sk in SK_BJS:
            for T in T_BJS:
                lo=sigma_lo('bjs',side,T,params.rate,params.dividend_yield,params)
                for s in sorted({lo,lo*1.5,0.1,0.3,1.0,2.5,5.0}):
                    if s>=lo:out.append((side,100.0*sk,100.0,T,s,lo))
    return out

def _worker_dps(_):return mp.mp.dps

def _bjs_value(args):
    if mp.mp.dps!=50:raise RuntimeError('oracle worker precision is not 50 digits')
    return float(bjs_mp(*args))

def sup(f,a,b,n=9):return float(max(abs(f(a+(b-a)*mp.mpf(i)/(n-1))) for i in range(n)))

def generate(part,params=CASE):
    r,q=params.rate,params.dividend_yield
    if part=='bsm':
        rows=[]
        for side in (0,1):
            for sk in (0.5,0.8,1.0,1.25,2.0):
                for T in (1/365/24,7/365,0.25,1.0,3.0):
                    for s in (0.01,0.1,0.3,1.0,3.0):
                        for rr in (0.0,0.04):
                            for qq in (0.0,0.012):
                                v=bsm_mp(side,100*sk,100,T,rr,qq,s)
                                rows.append(dict(side=side,S=100*sk,K=100.0,T=T,r=rr,q=qq,sigma=s,**{k:float(x) for k,x in zip(('price','delta','gamma','theta','vega','rho'),v)}))
        return rows
    if part=='bjs':   # rows in grid order; the work is spread over the container CPUs (one job must end within the session holder life)
        import multiprocessing, os
        grid=bjs_grid(params);workers=max(1,min(4,len(os.sched_getaffinity(0))))
        pool=multiprocessing.get_context('spawn').Pool(workers)
        try:values=pool.map(_bjs_value,[(side,S,K,T,r,q,s) for side,S,K,T,s,lo in grid],chunksize=1)
        finally:pool.close();pool.join()
        rows=[]
        for (side,S,K,T,s,lo),v in zip(grid,values):
            b=(r-q) if side==0 else (q-r)
            rows.append({'side':side,'S':S,'K':K,'T':T,'sigma':s,'sigma_lo':lo,'carry_binding':lo==math.sqrt(2*(abs(b)+params.h_r)/params.kappa_cap),'value':v})
        return rows
    if part=='lattice':
        rows=[]
        for side,S,K,T,s,lo in bjs_grid(params):
            if T<1/365 or s<0.05:continue
            avg=lambda n:(crr_price(side,S,K,T,r,q,s,n)+crr_price(side,S,K,T,r,q,s,n+1))/2.0
            a1,a2=avg(1000),avg(2000);aref=2.0*a2-a1
            rows.append({'side':side,'S':S,'K':K,'T':T,'sigma':s,'a_ref':aref,'eps_ref':abs(aref-a2)+1e-9,
                         'euro':{str(n):crr_price(side,S,K,T,r,q,s,n,american=False) for n in (100,200,400,800)},'bsm':float(bsm_mp(side,S,K,T,r,q,s)[0])})
        return rows
    if part=='greeks':
        rows=[]   # spec 3.8 item 7: only the CRR bumps (vega h_sigma, rho h_r) are checked; their sups over the bump intervals
        pts=[(side,100*sk,T,s) for side in (0,1) for sk in (0.8,1.0,1.25) for T in (1/365,0.25,1.0) for s in (0.1,0.3,1.0)]
        f3=lambda side,T,s,S0:mp.diff(lambda x:bsm_mp(side,x,100,T,r,q,s)[0],S0,3)
        for side,T,s in ((0,1/365,0.2),(1,1/365,0.2)):   # M1 points: zeros of V''' in S
            S0=float(mp.findroot(lambda x:f3(side,T,s,x),100.0));pts.append((side,S0,T,s))
        for side,S,T,s in pts:
            V=lambda S_=S,T_=T,r_=r,s_=s:bsm_mp(side,S_,100,T_,r_,q,s_)[0]
            ds=lambda n,a,b:sup(lambda x:mp.diff(lambda y:V(s_=y),x,n),a,b)
            dr=lambda n:sup(lambda x:mp.diff(lambda y:V(r_=y),x,n),r-1e-4,r+1e-4)
            rows.append({'side':side,'S':S,'K':100.0,'T':T,'r':r,'q':q,'sigma':s,
                         'sup':{'s3':ds(3,s-1e-3,s+1e-3),'s5':ds(5,s-1e-3,s+1e-3),'s2':ds(2,s,s+1e-3),'r3':dr(3),'r5':dr(5)}})
        return rows
    if part=='monotonicity':
        rows=[]
        for model in ('bjs','crr'):
            price=price_function(model,params)
            for side in (0,1):
                for sk in SK_BJS:
                    for T in T_BJS:
                        lo=sigma_lo(model,side,T,r,q,params);grid=[lo+1e-3*i for i in range(int((5.0-lo)/1e-3)+1)]
                        vals=[price(side,100*sk,100.0,T,r,q,s) for s in grid];regions=[];start=None
                        for i in range(1,len(vals)):
                            if vals[i]<vals[i-1] and start is None:start=grid[i-1]
                            if vals[i]>=vals[i-1] and start is not None:regions.append([start,grid[i-1]]);start=None
                        if start is not None:regions.append([start,grid[-1]])
                        rows.append({'model':model,'side':side,'S_over_K':sk,'T':T,'regions':regions})
        return rows
    if part=='edges':return edge_rows(params)
    if part=='lnphi':return normal_rows()
    if part=='baw':return baw_edge_rows(params)+baw_stencil_points(params)
    if part=='alo':return alo_edge_rows(params)
    raise ValueError('unknown oracle part')

def edge_rows(params):
    r,q=params.rate,params.dividend_yield;rows=[]
    def add(name,row,model,status,extra=None):rows.append({'name':name,'row':list(row),'model':model,'status':status,**({'params':extra} if extra else {})})
    for m in ('bsm','bjs','crr'):
        price=price_function(m,params);p=price(0,100.0,100.0,0.5,r,q,0.3)
        add(f'{m}-invalid',(0,-1.0,100.0,0.5,1.0,1.1,r,q),m,'INVALID_INPUT');add(f'{m}-expired',(0,100.0,100.0,0.0,1.0,1.1,r,q),m,'EXPIRED')
        add(f'{m}-no-bid',(0,100.0,100.0,0.5,0.0,1.1,r,q),m,'NO_BID');add(f'{m}-crossed',(0,100.0,100.0,0.5,1.2,1.1,r,q),m,'CROSSED')
        add(f'{m}-below-min',(0,150.0,100.0,0.5,25.0,25.0,r,q),m,'BELOW_MIN');add(f'{m}-above-max',(0,100.0,100.0,0.5,300.0,300.0,r,q),m,'ABOVE_MAX')
        add(f'{m}-ok',(0,100.0,100.0,0.5,p-0.01,p+0.01,r,q),m,'OK');add(f'{m}-locked-quote',(0,100.0,100.0,0.5,p,p,r,q),m,'OK')
        pt=price(0,100.0,100.0,60/31536000,r,q,0.3);add(f'{m}-t-just-above-zero',(0,100.0,100.0,60/31536000,pt,pt,r,q),m,'OK')
        fs,fK=(1,100.0) if m=='bjs' else (0,100.0*math.exp((r-q)*1.0))   # a quotable price (>= 0.01) at sigma_lo + 5e-4 (CRR: forward-ATM call, review)
        lo=sigma_lo(m,fs,1.0,r,q,params);pl=price(fs,100.0,fK,1.0,r,q,lo+5e-4);add(f'{m}-forward-vega',(fs,100.0,fK,1.0,pl,pl,r,q),m,'OK')
        ph=price(1,100.0,100.0,1.0,r,q,4.999);add(f'{m}-near-sigma-hi',(1,100.0,100.0,1.0,ph,ph,r,q),m,'OK')
    lo=sigma_lo('crr',0,1.0,r,q,params);pc=crr_price(0,100.0,100.0,1.0,r,q,lo*1.0001,params.crr_steps);add('crr-at-sigma-lo',(0,100.0,100.0,1.0,pc,pc,r,q),'crr','OK')
    wide={'kappa_cap':1e6};pw=CaseParams(**{**params.__dict__,**wide});trig=1.001*(abs(q-r)+params.h_r)*1.0/2.0
    above=bjs_price(1,100.0,100.0,1.0,r,q,trig*1.05);add('bjs-put-above-sigma-trig',(1,100.0,100.0,1.0,above,above,r,q),'bjs','OK',wide)
    below=0.99*bjs_price(1,100.0,100.0,1.0,r,q,sigma_lo('bjs',1,1.0,r,q,pw))   # below the price at sigma_lo under the wide-kappa params
    add('bjs-put-below-sigma-trig',(1,100.0,100.0,1.0,below,below,r,q),'bjs','BELOW_MIN',wide)
    carry=sigma_lo('bjs',1,1.0,r,q,params);pc2=bjs_price(1,100.0,100.0,1.0,r,q,carry*1.05)
    add('bjs-above-sigma-carry',(1,100.0,100.0,1.0,pc2,pc2,r,q),'bjs','OK');add('bjs-below-sigma-carry',(1,100.0,100.0,1.0,0.99*bjs_price(1,100.0,100.0,1.0,r,q,carry),0.99*bjs_price(1,100.0,100.0,1.0,r,q,carry),r,q),'bjs','BELOW_MIN')
    pt=bjs_price(1,100.0,100.0,1.0,r,q,trig*0.95)      # just below sigma_trig (wide kappa): QuantLib's European fallback prices it
    add('bjs-put-just-below-sigma-trig',(1,100.0,100.0,1.0,pt,pt,r,q),'bjs','BELOW_MIN',wide)
    nf=non_finite_row(params)
    if nf is not None:add('bjs-non-finite-evaluation',nf[0],'bjs','MODEL_DOMAIN',nf[1])
    band=rounding_band_row(params)
    if band is not None:add('bsm-rounding-band',band,'bsm','OK')     # oracle.check_edge_rows: a name ending -rounding-band needs the flag
    p7=crr_price(0,100.0,100.0,7.0,r,q,0.3,params.crr_steps)
    add('crr-domain-check-holds',(0,100.0,100.0,7.0,p7,p7,r,q),'crr','OK')            # T = 7 < 7.10 years: g(sigma_lo) >= 0
    add('crr-domain-check-fails',(0,100.0,100.0,7.2,10.0,10.0,r,q),'crr','MODEL_DOMAIN')  # T = 7.2 > 7.10 years: g(sigma_lo) < 0
    # PL-T11B-DIV0-01 (Task 11b review ruling): T = 1e-24 gives dx = 1e-17 and a 0/0 lattice delta inside the solve; IEEE-754
    # semantics (QuantLib C++) ignore it, the NPV decides: f(sigma_lo) < 0 and f(5.0) < 0, so ABOVE_MAX in every variant
    add('crr-ieee-division-tiny-t',(0,100.0,100.0,1e-24,0.5,0.6,r,q),'crr','ABOVE_MAX')
    rows+=local_domain_rows(params)
    return rows

LOCAL_DOMAIN=(('b-m010',0.10),('b-p009',-0.09))   # (name tag, q - r): carry b = r - q = -0.10 and +0.09

def local_domain_rows(params):
    """Amendment C item 5, label "local-domain spot check": each model, an at-the-money put (BjS: the transformed put has
    r~ = q, negative for q < 0), T = 30 days, sigma = 0.3, at b = -0.10, b = +0.09 (r = the case rate) and q = -0.02.
    Judged like every edge row; they do not qualify the local domain. The fixture name pattern allows [a-z0-9-] only, so
    b-0.10, b+0.09 and q-0.02 are written b-m010, b-p009 and q-m002."""
    r=params.rate;T=30/365;rows=[]
    for m in ('bsm','bjs','crr'):
        price=price_function(m,params)
        for tag,qq in [(tag,r+d) for tag,d in LOCAL_DOMAIN]+[('q-m002',-0.02)]:
            p=price(1,100.0,100.0,T,r,qq,0.3)
            rows.append({'name':f'local-domain-{m}-{tag}','row':[1,100.0,100.0,T,p-0.01,p+0.01,r,qq],'model':m,'status':'OK'})
    return rows

def non_finite_row(params):
    """A test-only parameter set (kappa_cap 56200, so sigma_lo = sigma_carry = 1e-3 for a call) and a call whose engine value
    at sigma_lo is NaN: inside the 1993 American branch (q_I <= 12.5) (I/S)^kappa overflows and N(...) underflows to 0.
    Spec 3.8 item 8 (replaces the tail-condition row). Returns (row, params) or None."""
    r,q=params.rate,params.dividend_yield;wide={'kappa_cap':56200.0};pw=CaseParams(**{**params.__dict__,**wide})
    lo=sigma_lo('bjs',0,1.0,r,q,pw)
    from optionlab.models import mapped_inputs, _log, _sqrt, _exp, _max
    D_r,D_q,v=mapped_inputs(1.0,r,q,lo);bT=_log(D_q/D_r);rT=_log(1.0/D_r);K=100.0
    beta=(0.5-bT/v)+_sqrt((bT/v-0.5)**2+2.0*rT/v);binf=beta/(beta-1.0)*K;b0=_max(K,rT/(rT-bT)*K)
    I=b0+(binf-b0)*(1-_exp(-(bT+2.0*_sqrt(v))*b0/(binf-b0)))
    for x in (0.01,0.008,0.005,0.011,0.012):
        S=I*math.exp(-x)*D_r/D_q
        if not math.isfinite(bjs_price(0,S,K,1.0,r,q,lo)):
            mid=round(S-K+1.0,2);return (0,S,K,1.0,mid,mid,r,q),wide
    return None

def rounding_band_row(params):
    """Spec 3.3 rounding-band edge row (round-2 item L-B): a slightly out-of-the-money BSM put, T = 1 year, ln(F/K) in
    [6e-4, 8e-4], sigma_lo = 1e-4 (sigma' = 1e-4). The first K whose py-reference value at sigma_lo is in
    -tau_V <= V < 0; the quote is the price at sigma = 0.2, so the solve continues to an OK IV."""
    r,q=params.rate,params.dividend_yield;S=100.0;T=1.0
    r1,q1,_=unit(T,r,q,1.0);F=(S*(1.0/math.exp(q1*1.0)))/(1.0/math.exp(r1*1.0))
    for j in range(2001):
        K=F*math.exp(-(6e-4+2e-4*j/2000));V=bsm_price(1,S,K,T,r,q,1e-4)
        if -tau_v(S,K,T,r,q)<=V<0.0:
            mid=bsm_price(1,S,K,T,r,q,0.2);return (1,S,K,T,mid,mid,r,q)
    return None

def normal_rows():
    """N(x) and n(x) at 50 digits: a grid for item 4, and both sides of the N series switch (N = 1e-8, x about -5.612) and of
    the density cutoff (x^2/2 = 690, x about -37.148) for item 8 (spec 3.8)."""
    sw=float(mp.findroot(lambda x:mp.ncdf(x)-mp.mpf('1e-8'),-5.6));cut=-math.sqrt(1380.0)
    edge=[(sw,'series-switch'),(math.nextafter(sw,-math.inf),'series-switch'),(math.nextafter(sw,math.inf),'series-switch'),
          (sw-1e-6,'series-switch'),(sw+1e-6,'series-switch'),(cut,'density-cutoff'),(cut+1e-9,'density-cutoff'),(cut-1e-9,'density-cutoff')]
    grid=[(x/4.0,'grid') for x in range(-160,41)]
    return [{'x':x,'kind':k,'N':float(mp.ncdf(mp.mpf(x))),'n':float(mp.npdf(mp.mpf(x)))} for x,k in edge+grid]

# ---- part `baw` (Amendment G2.5) ----
class DesignError(RuntimeError):
    """A designed property of a BAW oracle row does not hold: the generation fails (never a silent fixture)."""

def _baw_sstar(side,K,T,r,q,s,params):
    from optionlab.models import mapped_inputs
    from optionlab.baw_admit import sstar
    D_r,D_q,v=mapped_inputs(T,r,q,s);return sstar(side,K,D_r,D_q,v,params.baw_newton_max)

def baw_edge_rows(params):
    """Item 8 rows of G2.5 for `baw`. Each row stores the status, flags and admit_reason that py-reference gives; the
    designed property of each row is asserted (DesignError otherwise). Run-defect rows store status 'DEFECT' and the
    defect text. The forced cap (baw_newton_max 1) and the planted non-finite S* use test-only parameter sets."""
    from optionlab.reference import evaluate, price_function, FLAG_STENCIL_SWITCHED as SW, FLAG_ADMIT_EXCLUDED as AX
    from optionlab.models import BawRunDefect, RunDefect, AloRunDefect
    r,q=params.rate,params.dividend_yield;rows=[];P=price_function('baw',params)
    def add(name,row,expect=None,extra=None,flags_on=0,reason=None,design=None):
        """`expect`, `flags_on` and `reason` are the designed status, required flag bits and exclusion reason; `design`
        (a predicate of status, flags, reason) replaces them where only a weaker property is designed."""
        pp=CaseParams(**{**params.__dict__,**(extra or {})});info={}
        if expect=='DEFECT':
            try:evaluate(tuple(row),'baw',pp,info=info)
            except BawRunDefect as exc:rows.append({'kind':'edge','name':name,'row':list(row),'status':'DEFECT','defect':exc.args[0],**({'params':extra} if extra else {})});return
            raise DesignError(name)
        st,_,flags,_=evaluate(tuple(row),'baw',pp,info=info);why=info.get('admit_reason')
        ok=design(st,flags,why) if design else ((expect is None or st==expect) and flags&flags_on==flags_on and why==reason)
        if not ok:raise DesignError(name)
        rows.append({'kind':'edge','name':name,'row':list(row),'status':st,'flags':flags,'reason':why,**({'params':extra} if extra else {})})
    def quote(side,S,K,T,rr,qq,s):p=P(side,S,K,T,rr,qq,s);return (side,S,K,T,p,p,rr,qq)
    # the ordinary statuses
    add('baw-invalid',(1,-1.0,100.0,0.5,1.0,1.1,r,q),'INVALID_INPUT');add('baw-expired',(1,100.0,100.0,0.0,1.0,1.1,r,q),'EXPIRED')
    add('baw-no-bid',(1,100.0,100.0,0.5,0.0,1.1,r,q),'NO_BID');add('baw-crossed',(1,100.0,100.0,0.5,1.2,1.1,r,q),'CROSSED')
    add('baw-put-ok',quote(1,100.0,100.0,0.5,r,q,0.3),'OK');add('baw-call-ok',quote(0,100.0,100.0,0.5,r,q,0.3),'OK')
    add('baw-above-max',(1,100.0,100.0,0.5,300.0,300.0,r,q),'ABOVE_MAX')
    add('baw-put-t-just-above-zero',quote(1,100.0,100.0,60/31536000,r,q,0.3),'OK');add('baw-put-near-sigma-hi',quote(1,100.0,100.0,1.0,r,q,4.999),'OK')
    lo=sigma_lo('baw',1,1.0,r,q,params);add('baw-put-forward-vega',quote(1,100.0,100.0,1.0,r,q,lo+5e-4),'OK',flags_on=SW)
    pb=0.99*P(1,100.0,100.0,1.0,r,q,lo);add('baw-put-below-sigma-lo',(1,100.0,100.0,1.0,pb,pb,r,q),'BELOW_MIN')
    # rows at and near S* on both sides (T = 1, sigma 0.3); the central S stencil crosses S* (one-sided, flag 32)
    for side,tag in ((0,'call'),(1,'put')):
        qq=0.05 if side==0 else q                     # a call needs q > 0 for an American branch with S* within reach
        Sk=_baw_sstar(side,100.0,1.0,r,qq,0.3,params);inside=-1.0 if side==0 else 1.0
        add(f'baw-{tag}-near-sstar-continuation',quote(side,Sk*(1.0+inside*5e-2),100.0,1.0,r,qq,0.3),'OK')
        add(f'baw-{tag}-stencil-switched',quote(side,Sk*(1.0+inside*5e-4),100.0,1.0,r,qq,0.3),'OK',flags_on=SW)
        Sx=Sk*(1.0-inside*5e-3);ix=(Sx-100.0) if side==0 else (100.0-Sx)
        add(f'baw-{tag}-exercise-side',(side,Sx,100.0,1.0,ix,ix,r,qq),'OK')
        add(f'baw-{tag}-exercise-side-quote-above',(side,Sx,100.0,1.0,ix+0.05,ix+0.05,r,qq),design=lambda st,fl,why:why is None)
    # the baw_admit boundary on both sides: D_r = 1 (admitted) and D_r > 1 (excluded, reason row); the branch gate at q' = 2^-53
    # D_r = 1 (r = 0) passes check 2b; a put then fails check 2d (q_u = 0, S_u = -0): excluded with reason brent (record
    # R4 item 2d; QuantLib's behaviour at r = 0 for a put is not measured in R13). A call with r = 0 and q > 0 is admitted.
    p0=P(1,100.0,100.0,1.0,1e-3,q,0.3)               # the quote of a nearby admitted rate
    add('baw-put-zero-rate',(1,100.0,100.0,1.0,p0,p0,0.0,q),'MODEL_DOMAIN',flags_on=AX,reason='brent')
    add('baw-call-zero-rate-admitted',quote(0,100.0,100.0,1.0,0.0,0.05,0.3),'OK')
    add('baw-put-negative-rate',(1,100.0,100.0,1.0,p0,p0,-1e-6,q),'MODEL_DOMAIN',flags_on=AX,reason='row')
    e=2.0**-53
    add('baw-call-q-at-branch-gate',quote(0,100.0,100.0,1.0,r,e,0.3),'OK')
    add('baw-call-q-above-branch-gate',(0,100.0,100.0,1.0,12.0,12.2,r,math.nextafter(e,1.0)),'MODEL_DOMAIN',flags_on=AX,reason='brent')
    # small r: forward rho (N7); the European call branch (q = 0, q < 0, and D_r > 1 with q = 0): always admitted
    add('baw-put-small-rate-forward-rho',quote(1,100.0,100.0,1.0,5e-5,q,0.3),'OK',flags_on=SW)
    add('baw-call-european-q-zero',quote(0,100.0,100.0,1.0,r,0.0,0.3),'OK');add('baw-call-european-q-negative',quote(0,100.0,100.0,1.0,r,-0.01,0.3),'OK')
    add('baw-call-european-negative-rate',quote(0,100.0,100.0,1.0,-0.01,0.0,0.3),'OK')
    add('baw-put-rate-stencil-halved',_halved_rate_row(params),'OK',flags_on=SW)
    bump=_baw_bump_exclusion_row(params)
    if bump is not None:add('baw-put-excluded-bump',bump[1],'MODEL_DOMAIN',flags_on=AX,reason='bump')
    # the run defects (test-only parameter sets): forced cap and planted non-finite S*
    add('baw-defect-cap',(1,100.0,110.0,1.0,12.0,12.2,r,q),'DEFECT',{'baw_newton_max':1})
    add('baw-defect-nonfinite-sstar',(1,100.0,110.0,1.0,12.0,12.2,r,q),'DEFECT',{'baw_plant_nan_sstar':True})
    return rows

def _halved_rate_row(params):
    """A put row whose r stencil is halved (record R7): h_r/2 < r < h_r forces the forward point (N7), and S just above
    S*(r) puts r + h_r on the exercise side, so the step halves until the backward point r - h/2 >= 0 is allowed."""
    from optionlab.reference import evaluate, price_and_greeks, price_function
    q=params.dividend_yield;rr=0.75*params.h_r;P=price_function('baw',params);Sk=_baw_sstar(1,100.0,1.0,rr,q,0.3,params)
    for e in (1e-8,1e-7,1e-6,1e-5,1e-4):
        S=Sk*(1.0+e);p=P(1,S,100.0,1.0,rr,q,0.3);row=(1,S,100.0,1.0,p,p,rr,q)
        st,vals,fl,_=evaluate(row,'baw',params)
        if st=='OK' and price_and_greeks('baw',1,S,100.0,1.0,rr,q,vals[0],params)['stencils']['r'][1]<params.h_r:return row
    raise DesignError('no halved r stencil row')

def _baw_bump_exclusion_row(params):
    """A put row admitted at its IV with an excluded greek point (reason `bump`): first r = h_r (the lower rho point is
    r = 0, D_r = 1); else a forward theta point T + d (record R9, BAW1-05: sigma_trig grows with T, so h > 0 is possible
    there): short T (d = T/2), IV just above sigma_lo, S just above S*(T) so that T - d is on the exercise side. Returns
    (label, row) or None (none in the searched set)."""
    from optionlab.reference import evaluate, price_function
    from optionlab.models import BawRunDefect, RunDefect, AloRunDefect
    r,q=params.rate,params.dividend_yield;P=price_function('baw',params)
    hr=params.h_r;p=P(1,100.0,100.0,1.0,hr,q,0.3);row=(1,100.0,100.0,1.0,p,p,hr,q);info={}
    evaluate(row,'baw',params,info=info)             # r = h_r: the central rho stencil's lower point is r = 0 (D_r = 1)
    if info.get('admit_reason')=='bump':return 'rate-at-h-r',row
    for T in (1/365/24,3/365/24,1/365,2/365):
        lo=sigma_lo('baw',1,T,r,q,params)
        for m in (1.0001,1.001,1.01,1.05):
            s=lo*m
            try:Sk=_baw_sstar(1,100.0,T,r,q,s,params)
            except RunDefect:raise
            except ArithmeticError:continue
            for eps in (1e-9,1e-8,1e-7,1e-6):
                S=Sk*(1.0+eps)
                try:p=P(1,S,100.0,T,r,q,s)
                except RunDefect:raise
                except ArithmeticError:continue
                row=(1,S,100.0,T,p,p,r,q);info={}
                try:st,_,_,_=evaluate(row,'baw',params,info=info)
                except RunDefect:raise
                except ArithmeticError:continue
                if info.get('admit_reason')=='bump':return 'forward-theta',row
    return None

from optionlab.oracle import BAW_LEAD     # one table (oracle.BAW_LEAD): (c1, c2, p1, p2, lead order, next order, floor order, scale)

def _bs_mp(side,K,F,sd):
    d1=mp.log(F/K)/sd+sd/2;d2=d1-sd
    return F*mp.ncdf(d1)-K*mp.ncdf(d2) if side==0 else K*mp.ncdf(-d2)-F*mp.ncdf(-d1)

def baw_mp(side,S,K,D_r,D_q,v,Sk=None,guess=None):
    """The ideal BAW value (the engine's formulas of lines 50-138 and 196-234 in exact arithmetic, 50 digits): the exact
    root S* of g = LHS - RHS (or the given Sk) and the continuation-side value Black + a (S/S*)^Q. Returns (V, S*)."""
    D_r,D_q,v,S,K=map(mp.mpf,(D_r,D_q,v,S,K));sd=mp.sqrt(v)
    n=2*mp.log(D_q/D_r)/v;Kc=(-2*mp.log(D_r)/(v*(1-D_r))) if D_r!=1 else 2/v
    root=mp.sqrt((n-1)**2+4*Kc);Q=(-(n-1)+root)/2 if side==0 else (-(n-1)-root)/2
    def d1(x):return (mp.log(x*D_q/D_r/K)+v/2)/sd
    def g(x):
        if side==0:return (x-K)-(_bs_mp(0,K,x*D_q/D_r,sd)*D_r+(1-D_q*mp.ncdf(d1(x)))*x/Q)
        return (K-x)-(_bs_mp(1,K,x*D_q/D_r,sd)*D_r-(1-D_q*mp.ncdf(-d1(x)))*x/Q)
    if Sk is None:Sk=mp.findroot(g,mp.mpf(guess))
    Sk=mp.mpf(Sk)
    a=(Sk/Q)*(1-D_q*mp.ncdf(d1(Sk))) if side==0 else -(Sk/Q)*(1-D_q*mp.ncdf(-d1(Sk)))
    return _bs_mp(side,K,S*D_q/D_r,sd)*D_r+a*(S/Sk)**Q,Sk

def _exact_inputs(T,r,q,s):
    T,r,q,s=map(mp.mpf,(T,r,q,s));return mp.e**(-r*T),mp.e**(-q*T),s*s*T

def baw_stencil_points(params):
    """Item 7 points per side (record R7): the stencil forms that py-reference uses at each point, the derivative of the
    ideal model at 50 digits (V_i: exact inputs, exact S* root) in output units, the sups over each stencil interval (9
    points, calibration sup_points) of the leading and next derivative, and the S* term (the approved erratum F7 to record R7,
    spec Appendix G-BAW R12; commits f893813 and 539afc3):
    - S stencil: the engine's points share one S* (it does not depend on S); the remainder uses V_f(x) = the model at the
      float S* and float inputs, and the S* term is |D V_f - D V_i| at S;
    - sigma, r, T stencils: each point has its own S*; the S* term is sum |c_j| |V_f(x_j) - V_i(x_j)| over the stencil
      coefficients c_j (output units), V_f(x_j) at that point's float S* and float inputs."""
    from optionlab.reference import price_and_greeks
    from optionlab.models import mapped_inputs
    r,q=params.rate,params.dividend_yield;out=[];n_sup=9
    def sup(fn,a,b,k):return float(max(abs(mp.diff(fn,a+(b-a)*mp.mpf(i)/(n_sup-1),k)) for i in range(n_sup)))
    pts=[]
    for side,qq in ((0,0.05),(1,q)):
        Sk=_baw_sstar(side,100.0,1.0,r,qq,0.3,params);inside=-1.0 if side==0 else 1.0
        pts+=[(side,100.0,100.0,0.5,r,qq,0.3),(side,100.0,100.0,1.0,r,qq,0.2),(side,100.0,100.0,7/365,r,qq,0.4),(side,Sk*(1.0+inside*5e-4),100.0,1.0,r,qq,0.3)]
    # review fix round 1: the forms that the case parameters reach besides those above (record R7); vega-backward is not
    # reachable on these sides (S* is monotone in sigma, so the forward point keeps the row side whenever the backward one leaves it)
    pts.append((1,100.0,100.0,1.0,0.5*params.h_r,q,0.3))                                   # rho-forward: r - h_r < 0 (N7)
    pts.append(_find_put_point('r','backward',1.0,r,q,0.3,params))                          # S just above S*: S*(r + h_r) > S
    t=_find_put_point('T','forward',1.0,r,q,0.3,params)                                     # S just above S*: S*(T - d) > S
    if t not in pts:pts.append(t)                                                           # the same point can hold both forms
    for side,S,K,T,r,qq,s in pts:
        g=price_and_greeks('baw',side,S,K,T,r,qq,s,params)
        if g['flags']&16:raise DesignError('stencil point unresolved')
        st=g['stencils'];V0f,_=baw_mp(side,S,K,*mapped_inputs(T,r,qq,s),Sk=_baw_sstar(side,K,T,r,qq,s,params))
        def Vi(S_=S,T_=T,r_=r,s_=s):
            D_r,D_q,v=_exact_inputs(T_,r_,qq,s_);return baw_mp(side,S_,K,D_r,D_q,v,guess=_baw_sstar(side,K,T_,r_,qq,s_,params))[0]
        def Vf(S_=S,T_=T,r_=r,s_=s):
            return baw_mp(side,S_,K,*mapped_inputs(T_,r_,qq,s_),Sk=_baw_sstar(side,K,T_,r_,qq,s_,params))[0]
        Skf=_baw_sstar(side,K,T,r,qq,s,params);Df=mapped_inputs(T,r,qq,s)
        VfS=lambda x:baw_mp(side,x,K,*Df,Sk=Skf)[0]
        items={}
        form,h=st['S'];a,b=((S-h,S+h) if form=='central' else ((S-2*h,S) if side==0 else (S,S+2*h)))
        for name,order in (('delta',1),('gamma',2)):
            kind=f'{name}-{form}';c1,c2,p1,p2,k1,k2,fo,scale=BAW_LEAD[kind]
            exact=mp.diff(lambda x:Vi(S_=x),S,order);term=abs(mp.diff(VfS,S,order)-exact)
            items[name]={'kind':kind,'h':h,'exact':float(exact),'sup_lead':sup(VfS,a,b,k1),'sup_next':sup(VfS,a,b,k2),'sstar_term':float(term)}
        for name,var,x0,key in (('vega','s_',s,'sigma'),('rho','r_',r,'r'),('theta','T_',T,'T')):
            form,h=st[key];kind=f'{name}-{form}';c1,c2,p1,p2,k1,k2,fo,scale=BAW_LEAD[kind]
            fi=lambda x,var=var:Vi(**{var:x});ff=lambda x,var=var:Vf(**{var:x})
            if name=='theta':
                exact=-mp.diff(fi,x0,1)/365;a,b=(x0-h,x0) if form=='backward' else (x0,x0+h)
                pts_c=[(x0-h,1/(h*365)),(x0,-1/(h*365))] if form=='backward' else [(x0,1/(h*365)),(x0+h,-1/(h*365))]
            else:
                exact=mp.diff(fi,x0,1)*mp.mpf('0.01')
                if form=='central':a,b=x0-h,x0+h;pts_c=[(x0+h,0.01/(2*h)),(x0-h,-0.01/(2*h))]
                elif form=='forward':a,b=x0,x0+h;pts_c=[(x0+h,0.01/h),(x0,-0.01/h)]
                else:a,b=x0-h,x0;pts_c=[(x0,0.01/h),(x0-h,-0.01/h)]
            term=sum(abs(c)*abs(ff(x)-fi(x)) for x,c in pts_c)
            items[name]={'kind':kind,'h':h,'exact':float(exact),'sup_lead':sup(fi,a,b,k1),'sup_next':sup(fi,a,b,k2),'sstar_term':float(term)}
        out.append({'kind':'stencil','side':side,'S':S,'K':K,'T':T,'r':r,'q':qq,'sigma':s,'value':float(V0f),
                    'stencils':{k:list(v) for k,v in st.items()},'greeks':items})
    return out

def _find_put_point(key,form,T,r,q,s,params,eps=(1e-8,1e-7,1e-6,1e-5,1e-4,1e-3)):
    """(side, S, K, T, r, q, sigma) of a put on the continuation side just above S* whose `key` stencil has `form`."""
    from optionlab.reference import price_and_greeks
    Sk=_baw_sstar(1,100.0,T,r,q,s,params)
    for e in eps:
        S=Sk*(1.0+e);g=price_and_greeks('baw',1,S,100.0,T,r,q,s,params)
        if g['stencils'].get(key,('',))[0]==form:return (1,S,100.0,T,r,q,s)
    raise DesignError(f'no put point with the {key} {form} stencil')

# ---- part `alo` (Amendment I4.4 item 8) ----
def alo_edge_rows(params):
    """Item 8 rows of I4.4 for `alo`. Each row stores the status, flags and row equation (info['alo_equation']) that
    py-reference gives; the designed property of each row is asserted (DesignError otherwise). Run-defect rows store
    status 'DEFECT', the AloRunDefect kind and site (test-only parameter sets: alo_plant_nan, alo_force_cap)."""
    from optionlab import alo
    from optionlab.reference import evaluate, price_function, price_and_greeks, FLAG_STENCIL_SWITCHED as SW, FLAG_STENCIL_UNRESOLVED as SU
    from optionlab.models import AloRunDefect, RunDefect
    r,q=params.rate,params.dividend_yield;rows=[];P=price_function('alo',params);hr=params.h_r
    def add(name,row,expect=None,extra=None,flags_on=0,equation=None,design=None,note=None):
        pp=CaseParams(**{**params.__dict__,**(extra or {})});info={}
        if expect=='DEFECT':
            try:evaluate(tuple(row),'alo',pp,info=info)
            except AloRunDefect as exc:
                rows.append({'kind':'edge','name':name,'row':list(row),'status':'DEFECT','defect':exc.args[0],'site':exc.site,**({'params':extra} if extra else {})});return
            raise DesignError(name)
        st,_,flags,_=evaluate(tuple(row),'alo',pp,info=info);eq=info.get('alo_equation')
        ok=design(st,flags,eq) if design else ((expect is None or st==expect) and flags&flags_on==flags_on and (equation is None or eq==equation))
        if not ok:raise DesignError(f'{name}: {st} {flags} {eq}')
        rows.append({'kind':'edge','name':name,'row':list(row),'status':st,'flags':flags,'equation':eq,**({'params':extra} if extra else {}),**({'note':note} if note else {})})
    def quote(side,S,K,T,rr,qq,s):p=P(side,S,K,T,rr,qq,s);return (side,S,K,T,p,p,rr,qq)
    Y=31536000.0
    add('alo-invalid',(1,-1.0,100.0,0.5,1.0,1.1,r,q),'INVALID_INPUT');add('alo-expired',(1,100.0,100.0,0.0,1.0,1.1,r,q),'EXPIRED')
    add('alo-no-bid',(1,100.0,100.0,0.5,0.0,1.1,r,q),'NO_BID');add('alo-crossed',(1,100.0,100.0,0.5,1.2,1.1,r,q),'CROSSED')
    add('alo-put-ok',quote(1,100.0,100.0,0.5,r,q,0.3),'OK',equation='FP_B');add('alo-call-ok',quote(0,100.0,100.0,0.5,r,q,0.3),'OK',equation='FP_B')
    add('alo-above-max',(1,100.0,100.0,0.5,300.0,300.0,r,q),'ABOVE_MAX')
    # both sides of the equation switch (record R4: 1,126,285 s FP-A, 1,126,286 s FP-B), calls and puts
    for side,tag in ((0,'call'),(1,'put')):
        add(f'alo-{tag}-switch-last-fp-a',quote(side,100.0,100.0,1126285/Y,r,q,0.3),'OK',equation='FP_A')
        add(f'alo-{tag}-switch-first-fp-b',quote(side,100.0,100.0,1126286/Y,r,q,0.3),'OK',flags_on=SW,equation='FP_B')
    # a rho stencil halved once (test-only rates: r = q + 0.6 h_r at T = 10 y; r + h_r crosses the switch, r - h_r crosses r/q = 1)
    rr=q+0.6*hr;hrow=quote(1,100.0,100.0,10.0,rr,q,0.3)
    add('alo-put-rate-stencil-halved',hrow,'OK',flags_on=SW,equation='FP_A')
    st,vals,_,_=evaluate(hrow,'alo',params)
    if not price_and_greeks('alo',1,100.0,100.0,10.0,rr,q,vals[0],params)['stencils']['r'][1]<hr:raise DesignError('alo-put-rate-stencil-halved: step')
    # stencil_unresolved (test-only: r = q at T = 200 y; r - h/2^k crosses r/q = 1 and r + h/2^k crosses the switch for k <= 4)
    pu=P(1,100.0,100.0,200.0,q,q,0.3)
    add('alo-put-stencil-unresolved',(1,100.0,100.0,200.0,pu,pu,q,q),'MODEL_DOMAIN',flags_on=SU,equation='FP_A')
    # FP-A at long T (test-only |r - q| < 0.001), Amendment C-like rates (FP-A at 0.5 y, FP-B at 2.5 y)
    add('alo-put-fp-a-long-t',quote(1,100.0,100.0,2.0,0.04,0.0399,0.3),'OK',equation='FP_A')
    add('alo-put-c-like-fp-a',quote(1,100.0,100.0,0.5,0.043,0.0425,0.3),'OK',equation='FP_A')
    add('alo-put-c-like-fp-b',quote(1,100.0,100.0,2.5,0.043,0.0425,0.3),'OK',equation='FP_B')
    # the European edge branch (put with r <= 0 and r <= q) and the exchanged-put European branch (call with q <= 0, q <= r)
    add('alo-put-european-edge',quote(1,100.0,100.0,0.5,-0.001,q,0.3),'OK',equation='FP_B')
    # r = 0 exactly: r + h_r leaves the European edge (xMax case 1) and r - h_r enters xMax case 5, at every halving:
    # stencil_unresolved on a natural parameter set (order 5 with flag 16; the segment rule of I2.6)
    add('alo-put-zero-rate-unresolved',quote(1,100.0,100.0,0.5,0.0,q,0.3),'MODEL_DOMAIN',flags_on=SU,equation='FP_B',
        note=('controller ruling A4R-02: kept as the literal I2.6 result (shared alo_segment, the same status in every variant, '
              'no bias); the segment tuple holds the xMax case also inside the European edge branch, so r - h_r (case 5) '
              'and r + h_r (case 1) both leave the row segment (case 4) at every halving; no erratum'))
    add('alo-call-european-edge',quote(0,100.0,100.0,0.5,r,0.0,0.3),'OK')
    add('alo-put-r-eq-q-kink',quote(1,100.0,100.0,1.0,0.03,0.03,0.3),'OK',equation='FP_A')
    add('alo-put-t-one-hour',quote(1,100.0,100.0,3600/Y,r,q,0.3),'OK',equation='FP_A');add('alo-put-t-three-years',quote(1,100.0,100.0,3.0,r,q,0.3),'OK',equation='FP_B')
    lo=sigma_lo('alo',1,1.0,r,q,params)
    add('alo-put-forward-vega',quote(1,100.0,100.0,1.0,r,q,lo+5e-4),'OK')
    pb=0.99*P(1,100.0,100.0,1.0,r,q,lo);add('alo-put-below-sigma-lo',(1,100.0,100.0,1.0,pb,pb,r,q),'BELOW_MIN')
    add('alo-put-near-sigma-hi',quote(1,100.0,100.0,1.0,r,q,4.999),'OK')
    # the double-boundary QL_FAIL row (test-only negative rates q < r < 0): order 5
    add('alo-put-double-boundary',(1,100.0,100.0,1.0,10.0,10.0,-0.01,-0.02),'MODEL_DOMAIN')
    # the largest tanh-sinh level and a Brent-fallback row among short-T, low-sigma puts
    best=None;fb=None
    for T in (3600/Y,6*3600/Y,1/365,7/365):
        lo=sigma_lo('alo',1,T,r,q,params)
        for s in (lo*1.001,lo*1.5,lo*3,0.01,0.05):
            for K in (99.0,100.0,101.0,105.0):
                try:p=P(1,100.0,K,T,r,q,s)
                except RunDefect:raise
                except ArithmeticError:continue
                stt=alo.last_stats()
                if p>=0.01 and (best is None or stt.levels>best[0]):best=(stt.levels,(1,100.0,K,T,p,p,r,q))
                if p>=0.01 and fb is None and stt.fallback_nodes>0:fb=(1,100.0,K,T,p,p,r,q)
    if best is not None:add('alo-put-largest-tanh-sinh-level',best[1],design=lambda st,fl,eq:st in ('OK','BELOW_MIN'))
    if fb is None:                                   # a natural row: alo.TEST_ROW of the seeded 32-row chain (40 fallback node solves)
        from optionlab.contract import load_chain, rows as chain_rows
        from optionlab.synthetic import generate as synth
        fb=tuple(chain_rows(load_chain(synth(32,20261007,params)),params)[alo.TEST_ROW])
    n_fb=[0];real=alo.engine
    def counted(*a,**k):
        try:return real(*a,**k)
        finally:n_fb[0]+=alo.last_stats().fallback_nodes
    alo.engine=counted
    try:evaluate(fb,'alo',params)
    finally:alo.engine=real
    if n_fb[0]==0:raise DesignError('alo-brent-fallback: no fallback node solve')
    add('alo-brent-fallback',fb,'OK')
    # the run defects (test-only parameter sets): a planted NaN at the QD+ evaluator value and a forced Halley cap excess
    add('alo-defect-planted-nan',quote(1,100.0,100.0,0.5,r,q,0.3),'DEFECT',{'alo_plant_nan':'qdplus:66'})
    add('alo-defect-cap',quote(1,100.0,100.0,0.5,r,q,0.3),'DEFECT',{'alo_force_cap':'halley'})
    return rows

if __name__=='__main__':
    part,out=sys.argv[1],sys.argv[2]
    rows=generate(part)
    with open(out,'w') as f:json.dump(rows,f,separators=(',',':'),allow_nan=False)
    print(json.dumps({'part':part,'rows':len(rows)}))
