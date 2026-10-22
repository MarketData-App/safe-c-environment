"""Oracle checks (spec 4, with the section 3.8 replacements of Task 7b) against stored mpmath fixtures, and Phase 1
calibration. No mpmath at check time.

Items: 1 BSM (mpmath); 2 BjS 1993 (mpmath); 3 published values; 4 the QuantLib normal functions N(x) and n(x) (replaces
the removed bivariate normal item: the definition has no M(a, b, rho)); 5 properties and the BjS-versus-lattice metric;
6 IV round trip; 7 the CRR bumps (vega h_sigma, rho h_r) on BSM; 8 edge rows (statuses; the rounding_band flag where a row
declares it) and N(x) at its series switch and density cutoff.

BAW (Amendment G2.5): item 5 gains the documented model-accuracy metric against A_ref (`baw_lattice_metric`, never a gate);
item 6 gains BAW round trips; item 7 the record's stencil checks per side (fixture part `baw`, kind 'stencil'); item 8 the
BAW edge rows (kind 'edge': status, flags and exclusion reason; 'DEFECT' rows must raise the run defect). A missing `baw`
fixture part fails items 7 and 8.

ALO (Amendment I4.4, Task A4): item 6 gains ALO round trips; item 8 the ALO edge rows (fixture part `alo`, kind 'edge':
status, flags and the row's equation; 'DEFECT' rows must raise models.AloRunDefect with the stored kind and site). A
missing `alo` fixture part fails item 8. Item 7 for ALO is the measured check of erratum E-ALO-6 (Appendix I-ALO R12):
stencil identity with the oracle's own I2.6 decisions, a truncation check from the h/2 and h/4 stencils, unresolved
terms counted; labelled "measured, not proven" (ALO_ITEM7_LABEL, ALO_ITEM7_REASON): `alo_item7_point`."""
import math
from optionlab.models import bsm, bsm_price, bjs_price, crr_price, sigma_lo, BawRunDefect, RunDefect, AloRunDefect
from optionlab.normal import norm_cdf, norm_pdf, erf, M_SQRT_2
from optionlab.reference import evaluate3 as evaluate, price_function, FLAG_ROUNDING_BAND
from optionlab.params import CaseParams
EPS=2.220446049250313e-16
MIN_NORMAL=2.2250738585072014e-308
LEAD={'vega':(1/6,1/120,2,4,1,0.01),'rho':(1/6,1/120,2,4,1,0.01),'vega-forward':(1/2,1/6,1,2,1,0.01)}   # spec 3.8 item 7

FLOOR_EPS_MIN=4   # spec 4 item 7 floor multiplier; calibration may only raise it

def floor(value,h,order,cal,scale=1.0,inputs=None):
    """Rounding floor of spec 4 item 7. With `inputs` = max(S, K) the calibrated multiplier is capped so that the floor never
    exceeds 4*eps*max(1, S, K)/h^k: a BSM price is a difference of terms of size about S and K, so its rounding error scales with
    max(S, K), not with |V| (Task 9 review). The cap keeps the calibration from absorbing a truncation or formula error."""
    m=cal['floor_eps_multiplier']
    if inputs is not None:m=min(m,max(FLOOR_EPS_MIN,FLOOR_EPS_MIN*max(1.0,abs(inputs))/max(1.0,abs(value))))
    return scale*m*EPS*max(1.0,abs(value))/h**order+cal['floor_abs']

def fd_bound(kind,h,sup_lead,sup_next,value,cal,inputs=None):
    """M1: Lagrange remainder with the sup of the leading derivative over the bump interval plus the next series term."""
    c1,c2,p1,p2,order,scale=LEAD[kind]
    return scale*cal['safety_factor']*(c1*h**p1*abs(sup_lead)+c2*h**p2*abs(sup_next))+floor(value,h,order,cal,scale,inputs)

def _status(failures,checked,blocked=False):
    return {'status':'BLOCKED' if blocked else 'PASS' if checked and not failures else 'FAIL','checked':checked,'failures':len(failures),'examples':failures[:5]}

def check_bsm(fx,params):
    bad=[];names=('price','delta','gamma','theta','vega','rho')
    for i,p in enumerate(fx['oracle']['bsm']):
        got=bsm(p['side'],p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma'])
        for name,g in zip(names,got):
            if not abs(g-p[name])<=max(1e-12*abs(p[name]),1e-14*max(1.0,p['S'])):bad.append({'field':name,'index':i})
    return _status(bad,len(fx['oracle']['bsm']))

def check_bjs(fx,params):
    bad=[]
    for i,p in enumerate(fx['oracle']['bjs']):
        g=bjs_price(p['side'],p['S'],p['K'],p['T'],params.rate,params.dividend_yield,p['sigma'])
        if not abs(g-p['value'])<=max(1e-10*abs(p['value']),1e-12*max(1.0,p['K'])):bad.append({'index':i,'side':p['side'],'T':p['T'],'sigma':p['sigma']})
    out=_status(bad,len(fx['oracle']['bjs']));out['decision']=kappa_decision(bad,params);return out

def check_known_answers(fx,params):
    bad=[];blocked=not any(r['model']=='bjs' for r in fx['oracle']['known_answers'])
    for r in fx['oracle']['known_answers']:
        f=bsm_price if r['model']=='bsm' else bjs_price
        if round(f(r['side'],r['S'],r['K'],r['T'],r['r'],r['q'],r['sigma']),r['decimals'])!=r['value']:bad.append(r['source'])
    out=_status(bad,len(fx['oracle']['known_answers']))
    out['bjs_transcription']='BLOCKED' if blocked else 'PRESENT'
    if blocked and out['status']=='PASS':out['status']='INCOMPLETE'   # approval P1-R1-02: no BjS-1993 row, so never PASS
    return out

INCOMPLETE_ALLOWED=frozenset({'3'})   # item 3 while no BjS-1993 published row is transcribed (ledger PLAN-T9-BJS2002-01)

def summary_status(items):
    """Approval P1-R1-02: the oracle summary status and the incomplete items. Item 3 INCOMPLETE keeps the gate status
    (Amendment B: QuantLib agreement is the correctness proof) and is named in the summary; any other non-PASS item fails."""
    incomplete=sorted(k for k,v in items.items() if v['status']=='INCOMPLETE')
    ok=all(v['status']=='PASS' or (v['status']=='INCOMPLETE' and k in INCOMPLETE_ALLOWED) for k,v in items.items())
    return ('PASS' if ok else 'FAIL'),incomplete

SERIES_REL=1e-6     # A-S 26.2.12 is asymptotic: the truncation is at most the smallest term, about 2.1e-7 N at the switch

def normal_error(p):
    """None when the QuantLib N(x) and n(x) ports meet the 50-digit values within the error of their own arithmetic.
    The branch is QuantLib's: the erf form 0.5*(1 + erf(x/sqrt 2)) when it is > 1e-8 (absolute rounding of a few eps; 4 eps
    allowed), else the A-S 26.2.12 series (relative truncation SERIES_REL). n(x) = c*exp(-x*x/2) has relative error
    <= 4 eps max(1, x*x) from the rounded exponent. Where -x*x/2 <= -690, n is exactly 0 and the series gives N = 0
    (the definition; the 50-digit values there are below 1e-299). Otherwise the name of the failing function."""
    x=p['x'];N=norm_cdf(x);n=norm_pdf(x)
    if -(x*x)/2.0<=-690.0:
        if not (n==0.0 and p['n']<1e-299):return 'n'
        if not (N==0.0 and p['N']<1e-299):return 'N'
        return None
    form=0.5*(1.0+erf(x*M_SQRT_2))
    tolN=SERIES_REL*p['N'] if form<=1e-8 else 4*EPS
    if not abs(N-p['N'])<=tolN:return 'N'
    if not abs(n-p['n'])<=4*EPS*max(1.0,x*x)*p['n']:return 'n'
    return None

def check_normal(fx,params):
    """Item 4 (spec 3.8: the bivariate normal item is removed): the QuantLib normal functions against mpmath."""
    rows=fx['oracle']['lnphi'];bad=[{'index':i,'function':e} for i,p in enumerate(rows) for e in (normal_error(p),) if e]
    return _status(bad,len(rows),blocked=not rows)

def check_properties(fx,params):
    """Item 5. Gates (Amendment D item 0(c)): BSM parity and vega, CRR American >= European, BjS call with b >= r equals BSM.
    The CRR q = 0 call equality, the discretization band, the convergence rule and C_crr are model-accuracy metrics
    (Amendment D item 2): `crr_accuracy`, never a failure."""
    bad=[];r,q=params.rate,params.dividend_yield;n=0
    for p in fx['oracle']['bsm']:
        n+=1;c=bsm_price(0,p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma']);pu=bsm_price(1,p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma'])
        if abs(c-pu-(p['S']*math.exp(-p['q']*p['T'])-p['K']*math.exp(-p['r']*p['T'])))>1e-12*max(1.0,p['S']):bad.append('parity')
        vega=bsm(p['side'],p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma'])[4]   # strictly positive unless the 50-digit vega is below the smallest normal double
        if vega<0.0 or (vega==0.0 and p['vega']>=MIN_NORMAL):bad.append('vega')
    for p in fx['oracle']['lattice']:
        n+=1;a=crr_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma'],100);e=crr_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma'],100,american=False)
        if a<e-1e-12*max(1.0,a):bad.append('american-below-european')
    for S in (80.0,100.0,120.0):
        n+=1
        if abs(bjs_price(0,S,100.0,1.0,0.04,0.0,0.3)-bsm_price(0,S,100.0,1.0,0.04,0.0,0.3))>1e-12*max(1.0,S):bad.append('bjs-carry-at-rate')
    out=_status(bad,n);out['bjs_vs_lattice']=bjs_lattice_metric(fx,params);out['crr_accuracy']=crr_accuracy(fx,params)
    out['baw_vs_lattice']=baw_lattice_metric(fx,params);return out

NS=(100,200,400,800)
def crr_accuracy(fx,params,agreement=None):
    """Amendment D item 2: QuantLib CRR model-accuracy metrics per SIGMA_BANDS x T_BANDS band, never a gate. Per band: point
    count; count and largest absolute and relative deviation of the q = 0 American call from the q = 0 European call
    (N = 100); largest European error against BSM per N; convergence ratios (largest error at 2N / largest error at N);
    observed C_crr ratio (largest error * N / (S sigma sqrt T)). `q0_deviations` lists every deviating point.
    `agreement` (band -> bool, from the quantlib-alignment check) adds `equal_to_quantlib_within_align_tol` per band."""
    r,q=params.rate,params.dividend_yield;bands={};devs=[]
    for p in fx['oracle']['lattice']:
        key=_band(p['sigma'],SIGMA_BANDS)+'|'+_band(p['T'],T_BANDS)
        b=bands.setdefault(key,{'points':0,'q0_deviation_count':0,'q0_max_abs':0.0,'q0_max_rel':0.0,'euro_max_error':{str(N):0.0 for N in NS},'c_crr_observed':0.0})
        b['points']+=1
        if p['side']==0:
            a=crr_price(0,p['S'],p['K'],p['T'],r,0.0,p['sigma'],100);e=crr_price(0,p['S'],p['K'],p['T'],r,0.0,p['sigma'],100,american=False)
            d=abs(a-e);rel=d/max(1.0,abs(a))
            if d>1e-12*max(1.0,a):
                b['q0_deviation_count']+=1;devs.append({'S':p['S'],'K':p['K'],'T':p['T'],'sigma':p['sigma'],'abs':d,'rel':rel})
            b['q0_max_abs']=max(b['q0_max_abs'],d);b['q0_max_rel']=max(b['q0_max_rel'],rel)
        scale=p['S']*p['sigma']*math.sqrt(p['T'])
        for N in NS:
            err=abs(p['euro'][str(N)]-p['bsm']);b['euro_max_error'][str(N)]=max(b['euro_max_error'][str(N)],err)
            b['c_crr_observed']=max(b['c_crr_observed'],err*N/scale)
    for key,b in bands.items():
        em=b['euro_max_error'];b['convergence_ratios']={f'{N}->{2*N}':(em[str(2*N)]/em[str(N)] if em[str(N)]>0 else None) for N in (100,200,400)}
        if agreement is not None:b['equal_to_quantlib_within_align_tol']=bool(agreement.get(key,False))
    return {'bands':dict(sorted(bands.items())),'q0_deviations':devs}

def check_iv_roundtrip(fx,params):
    """Item 6. A price below 0.01 is not a tradable quote and is skipped; for an American model a quote at the sigma_lo price
    (exercise region) has no identifiable IV and must give BELOW_MIN or OK without an IV comparison (spec 21 carry-over)."""
    bad=[];n=0;skipped=0;r,q=params.rate,params.dividend_yield
    for model in ('bsm','bjs','crr','baw','alo'):
        price=price_function(model,params)
        for side,S,K,T in ((0,100.0,100.0,7/365),(1,100.0,100.0,3.0),(0,160.0,100.0,1.0),(1,60.0,100.0,1.0),(0,60.0,100.0,0.5),(1,160.0,100.0,0.5)):
            lo=sigma_lo(model,side,T,r,q,params)
            for sig in (max(lo*1.5,0.05),0.4,2.0):
                try:p=price(side,S,K,T,r,q,sig)
                except RunDefect:raise
                except ArithmeticError:bad.append((model,side,S,T,sig,'engine'));continue      # BAW: an excluded or raising point fails the item
                if p<0.01:skipped+=1;continue
                n+=1;st,vals,_=evaluate((side,S,K,T,p,p,r,q),model,params)
                try:p_lo=price(side,S,K,T,r,q,lo)
                except RunDefect:raise
                except ArithmeticError:bad.append((model,side,S,T,sig,'engine at sigma_lo'));continue
                if model!='bsm' and abs(p-p_lo)<=1e-9*max(1.0,p):
                    if st not in ('BELOW_MIN','OK'):bad.append((model,side,S,T,sig,st))
                    continue
                if st!='OK':bad.append((model,side,S,T,sig,st));continue
                nu=vals[5]*100.0;tau=1e-8+1e-13*max(1.0,p)/nu if nu>0 else math.inf
                if abs(vals[0]-sig)>tau:bad.append((model,side,S,T,sig))
    out=_status(bad,n);out['skipped_untradable']=skipped;return out

def item7_point(p,cal):
    """Spec 3.8 item 7: the CRR bumps (vega h_sigma = 1e-3 central and forward, rho h_r = 1e-4 central) on the BSM model
    against the analytic BSM vega and rho, with the Lagrange-remainder bound over the bump interval (the h_S and theta-delta
    terms left the definition)."""
    S,K,T,r,q,s,side=p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma'],p['side']
    V=lambda **k:bsm_price(side,S,K,T,k.get('r',r),q,k.get('s',s))
    an=bsm(side,S,K,T,r,q,s);hsig=1e-3;hr=1e-4;v0=V()
    fd={'vega':(V(s=s+hsig)-V(s=s-hsig))/(2*hsig)*0.01,'vega-forward':(V(s=s+hsig)-v0)/hsig*0.01,'rho':(V(r=r+hr)-V(r=r-hr))/(2*hr)*0.01}
    ref={'vega':an[4],'vega-forward':an[4],'rho':an[5]}
    h={'vega':hsig,'vega-forward':hsig,'rho':hr}
    sup={'vega':('s3','s5'),'vega-forward':('s2','s3'),'rho':('r3','r5')}
    return {k:{'kind':k,'h':h[k],'value':v0,'inputs':max(S,K),'error':abs(fd[k]-ref[k]),'bound':fd_bound(k,h[k],p['sup'][sup[k][0]],p['sup'][sup[k][1]],v0,cal,max(S,K))} for k in fd}

def check_greeks(fx,params):
    bad=[]
    for i,p in enumerate(fx['oracle']['greeks']):
        for k,v in item7_point(p,fx['calibration']['item7']).items():
            if not v['error']<=v['bound']:bad.append({'index':i,'greek':k})
    pts=[p for p in fx['oracle'].get('baw',[]) if p.get('kind')=='stencil']
    if not pts:bad.append({'baw':'no stencil points in the fixture'})
    for i,p in enumerate(pts):
        for k,v in baw_item7_point(p,fx['calibration']['item7'],params).items():
            if not v['ok']:bad.append({'baw_index':i,'greek':k})
    alo=alo_item7(params)
    bad+=[{'alo_point':i,'greek':k} for i,k in alo['failed']]
    out=_status(bad,len(fx['oracle']['greeks'])+len(pts)+alo['terms']);out['baw_points']=len(pts)
    out['alo_item7']={k:alo[k] for k in ('label','reason','points','terms','failures','per_greek','per_form','not_resolved','max_error_over_tol')};return out

# ---- ALO item 7 (Amendment I4.4 with erratum E-ALO-6, Appendix I-ALO R12): a measured check, not a proven bound ----
ALO_ITEM7_LABEL='measured, not proven'
ALO_ITEM7_REASON=('no closed form and no high-precision ALO model exists, so item 7 for alo is a measured check: the oracle '
                  'derives each stencil from the I2.6 rules on its own (stencil identity, bit for bit) and checks the '
                  'truncation against a Richardson reference from the h/2 and h/4 stencils of the ALO price; implementation '
                  'correctness is gated by bit equality with QuantLib (section 4 item 9)')
EPS_SCH=1e-8            # the accurateScheme tolerance (Amendment I2.2)
C_CENTRAL=32/3          # E-ALO-6: twice (16/3), the p = 2 Richardson factor
C_ONE_SIDED=8.0         # E-ALO-6: twice 4, the p = 1 Richardson factor
ALO_GREEKS=('delta','gamma','vega','rho','theta')
_ALO_KEY={'delta':'S','gamma':'S','vega':'sigma','rho':'r','theta':'T'}

def alo_item7_points(params):
    """The item 7 points for `alo`: central S, sigma, r and the backward T stencils on a put/call grid (T 7 d, 0.5 y, 1 y;
    S/K 0.9, 1.0, 1.1; sigma 0.25), and the one-sided forms of I2.6: forward rho and forward theta (the first FP-B second
    of the equation switch), backward rho (the last FP-A second), forward vega (sigma just above sigma_lo), a halved rho
    (r = q + 0.6 h_r, T = 10 y)."""
    from optionlab.models import sigma_lo
    r,q=params.rate,params.dividend_yield;pts=[]
    for side in (0,1):
        for T in (7/365,0.5,1.0):
            for sk in (0.9,1.0,1.1):pts.append((side,100.0*sk,100.0,T,r,q,0.25))
    for side in (0,1):pts.append((side,100.0,100.0,1126286/31536000.0,r,q,0.3))
    pts.append((1,100.0,100.0,1126285/31536000.0,r,q,0.3))
    lo=sigma_lo('alo',1,1.0,r,q,params);pts.append((1,100.0,100.0,1.0,r,q,lo+5e-4))
    pts.append((1,100.0,100.0,10.0,q+0.6*params.h_r,q,0.3))
    return pts

def alo_item7_stencils(side,S,K,T,r,q,sigma,params):
    """E-ALO-6 test (1): the stencil form and step of each greek, derived by the oracle from the I2.6 rules on its own
    (never read from a variant): h_S = min(1e-3, 0.1 sigma sqrt T) S central for delta and gamma; vega h_sigma, forward iff
    sigma - h_sigma < sigma_lo(ALO, row), else central; rho h_r with q fixed: central when r + h and r - h have the row's
    segment (alo_segment), else forward or backward on the side that has it, else h halved (at most 4 halvings); theta
    d = min(1/365, T/2): backward when T - d has the row's segment, else forward when T + d has it, else d halved (at most
    4 halvings). An unresolved rho or theta is None."""
    from optionlab.alo_equation import alo_segment
    from optionlab.models import sigma_lo
    from optionlab.mapping import unit
    seg=lambda T_,r_:alo_segment(side,*unit(T_,r_,q,1.0)[:2])
    hS=min(1e-3,0.1*sigma*math.sqrt(T))*S
    hs=params.h_sigma;vega=('forward',hs) if sigma-hs<sigma_lo('alo',side,T,r,q,params) else ('central',hs)
    row=seg(T,r);rho=None;h=params.h_r
    for _ in range(5):
        up=seg(T,r+h)==row;dn=seg(T,r-h)==row
        if up and dn:rho=('central',h);break
        if up:rho=('forward',h);break
        if dn:rho=('backward',h);break
        h=h/2
    theta=None;d=min(1.0/365.0,T/2.0)
    for _ in range(5):
        if seg(T-d,r)==row:theta=('backward',d);break
        if seg(T+d,r)==row:theta=('forward',d);break
        d=d/2
    return {'delta':('central',hS),'gamma':('central',hS),'vega':vega,'rho':rho,'theta':theta}

_SCALE={'delta':lambda x:x,'gamma':lambda x:x,'vega':lambda x:x*0.01,'rho':lambda x:x*0.01,'theta':lambda x:x/365.0}

def alo_stencil(p,params,name,form,h,p0=None):
    """One I2.6 stencil of greek `name` at step h on the ALO engine price, in the operation order of the reference
    stencils, in output units: (D, max|V over the stencil points|, h_eff in output units)."""
    from optionlab import alo
    side,S,K,T,r,q,s=p
    V=lambda S_,T_,r_,s_:alo.price(side,S_,K,T_,r_,q,s_,params)
    if p0 is None:p0=V(S,T,r,s)
    if name=='delta':a=V(S+h,T,r,s);b=V(S-h,T,r,s);d,vs,he=(a-b)/(2*h),(a,b),2*h
    elif name=='gamma':a=V(S+h,T,r,s);b=V(S-h,T,r,s);d,vs,he=(a-2*p0+b)/(h*h),(a,p0,b),h*h
    elif name=='vega':
        if form=='central':a=V(S,T,r,s+h);b=V(S,T,r,s-h);d,vs,he=(a-b)/(2.0*h),(a,b),2.0*h
        else:a=V(S,T,r,s+h);d,vs,he=(a-p0)/h,(a,p0),h
    elif name=='rho':
        if form=='central':a=V(S,T,r+h,s);b=V(S,T,r-h,s);d,vs,he=(a-b)/(2.0*h),(a,b),2.0*h
        elif form=='forward':a=V(S,T,r+h,s);d,vs,he=(a-p0)/h,(a,p0),h
        else:b=V(S,T,r-h,s);d,vs,he=(p0-b)/h,(p0,b),h
    elif form=='backward':a=V(S,T-h,r,s);d,vs,he=(a-p0)/h,(a,p0),h
    else:b=V(S,T+h,r,s);d,vs,he=(p0-b)/h,(p0,b),h
    return _SCALE[name](d),max(abs(v) for v in vs),he

def alo_truncation(p,params,name,form,h):
    """E-ALO-6 test (2) reference: D_{h/2}, D_{h/4}, D_R = (4 D_{h/4} - D_{h/2})/3 (central) or 2 D_{h/4} - D_{h/2}
    (one-sided), tol = 2 eps_sch max|V over the h/4 stencil points| / h_eff(h/4) + c |D_{h/2} - D_{h/4}| in output units
    (c = 32/3 central, 8 one-sided). Neither D_R nor tol uses the greek or D_h."""
    central=form=='central'
    d2,_,_=alo_stencil(p,params,name,form,h/2);d4,vmax,he4=alo_stencil(p,params,name,form,h/4)
    dr=(4*d4-d2)/3 if central else 2*d4-d2
    scheme=abs(_SCALE[name](2*EPS_SCH*vmax/he4));tol=scheme+(C_CENTRAL if central else C_ONE_SIDED)*abs(d2-d4)
    return {'d_h2':d2,'d_h4':d4,'d_r':dr,'tol':tol,'tol_scheme':scheme}

def alo_item7_point(p,params,variant=None):
    """E-ALO-6 tests (1)-(3) of one point. `variant`: the variant's result in the form of reference.price_and_greeks (the
    greeks and `stencils`); default py-reference. Per greek: the oracle's form and step, stencil_ok (the variant reports
    that form and step, and its greek equals the oracle's stencil at h bit for bit), the truncation check (error =
    |greek - D_R| <= tol), resolved (tol < |greek|/2, controller amendment A4-C6: then a doubled greek must fail test (2)),
    error/tol, tol/|greek|, ok = stencil_ok and truncation_ok."""
    from optionlab.reference import price_and_greeks
    side,S,K,T,r,q,s=p
    g=variant if variant is not None else price_and_greeks('alo',side,S,K,T,r,q,s,params)
    own=alo_item7_stencils(side,S,K,T,r,q,s,params);out={}
    for name in ALO_GREEKS:
        st=own[name];greek=g[name]
        if st is None:
            out[name]={'kind':name+'-unresolved','h':None,'greek':greek,'stencil_ok':False,'truncation_ok':False,'ok':False,'resolved':False,
                       'error':math.inf,'tol':math.inf,'err_over_tol':None,'tol_over_greek':None,'label':ALO_ITEM7_LABEL};continue
        form,h=st
        reported=tuple(g.get('stencils',{}).get(_ALO_KEY[name],()))
        dh,_,_=alo_stencil(p,params,name,form,h)
        stencil_ok=reported==(form,h) and dh==greek
        t=alo_truncation(p,params,name,form,h);err=abs(greek-t['d_r'])
        out[name]={'kind':f'{name}-{form}','h':h,'greek':greek,'d_h':dh,**t,'error':err,'stencil_ok':stencil_ok,'truncation_ok':err<=t['tol'],
                   'ok':stencil_ok and err<=t['tol'],'resolved':t['tol']<abs(greek)/2,     # E-ALO-6 test (3) with controller amendment A4-C6
                   'err_over_tol':err/t['tol'] if t['tol']>0 else (0.0 if err==0 else math.inf),
                   'tol_over_greek':t['tol']/abs(greek) if greek!=0 else math.inf,'label':ALO_ITEM7_LABEL}
    return out

def alo_item7(params):
    """Item 7 for ALO over alo_item7_points (E-ALO-6): counts, the failing (point, greek) pairs (a failed test (1) or (2)),
    per greek the resolved and not-resolved counts and the largest error/tol, the label, and (A4R2-03, Task A5) every
    not-resolved term by (point index, greek, stencil kind, tol/|greek|) and the resolved and not-resolved counts per
    stencil form (`per_form`: a form with no resolved term has no resolved truncation evidence)."""
    pts=alo_item7_points(params);failed=[];terms=0;worst=0.0;unresolved=[];forms={}
    per={g:{'resolved':0,'not_resolved':0,'max_error_over_tol':0.0} for g in ALO_GREEKS}
    for i,p in enumerate(pts):
        for k,v in alo_item7_point(p,params).items():
            terms+=1;e=v['err_over_tol'] if v['err_over_tol'] is not None else math.inf;res='resolved' if v['resolved'] else 'not_resolved'
            per[k][res]+=1;per[k]['max_error_over_tol']=max(per[k]['max_error_over_tol'],e);worst=max(worst,e)
            forms.setdefault(v['kind'],{'resolved':0,'not_resolved':0})[res]+=1
            if not v['resolved']:unresolved.append({'point':i,'greek':k,'kind':v['kind'],'tol_over_greek':v['tol_over_greek']})
            if not v['ok']:failed.append((i,k))
    return {'label':ALO_ITEM7_LABEL,'reason':ALO_ITEM7_REASON,'points':len(pts),'terms':terms,'failures':len(failed),'failed':failed,
            'per_greek':per,'per_form':forms,'not_resolved':unresolved,'max_error_over_tol':worst}

BAW_GREEKS=('delta','gamma','theta','vega','rho')

def baw_item7_point(p,cal,params):
    """Item 7 for BAW (Amendment G2.5; record R7): py-reference's greek at the point must use the stored stencil form and
    step, and lie within scale * safety * (c1 h^p1 sup_lead + c2 h^p2 sup_next) + floor + S* term of the ideal derivative
    (oracle_gen.baw_stencil_points; the lead table is oracle_gen.BAW_LEAD, repeated here as BAW_LEAD so that no mpmath
    import happens at check time)."""
    from optionlab.reference import price_and_greeks
    g=price_and_greeks('baw',p['side'],p['S'],p['K'],p['T'],p['r'],p['q'],p['sigma'],params)
    same={k:list(v) for k,v in g['stencils'].items()}==p['stencils'];out={}
    for name in BAW_GREEKS:
        it=p['greeks'][name];c1,c2,p1,p2,_,_,order,scale=BAW_LEAD[it['kind']];h=it['h']
        # The S* term (the effect of the engine's S* stop tolerance on the differenced values) is the approved erratum F7 to
        # record R7 (spec Appendix G-BAW R12 F7; commits f893813 and 539afc3).
        bound=scale*cal['safety_factor']*(c1*h**p1*abs(it['sup_lead'])+c2*h**p2*abs(it['sup_next']))+floor(p['value'],h,order,cal,scale,max(p['S'],p['K']))+it['sstar_term']
        err=abs(g[name]-it['exact']);out[name]={'kind':it['kind'],'error':err,'bound':bound,'ok':same and err<=bound}
    return out

BAW_LEAD={'delta-central':(1/6,1/120,2,4,3,5,1,1.0),'gamma-central':(1/12,1/360,2,4,4,6,2,1.0),
          'delta-one-sided':(1/3,1/4,2,3,3,4,1,1.0),'gamma-one-sided':(1.0,7/12,1,2,3,4,2,1.0),
          'vega-central':(1/6,1/120,2,4,3,5,1,0.01),'vega-forward':(1/2,1/6,1,2,2,3,1,0.01),'vega-backward':(1/2,1/6,1,2,2,3,1,0.01),
          'rho-central':(1/6,1/120,2,4,3,5,1,0.01),'rho-forward':(1/2,1/6,1,2,2,3,1,0.01),'rho-backward':(1/2,1/6,1,2,2,3,1,0.01),
          'theta-backward':(1/2,1/6,1,2,2,3,1,1/365),'theta-forward':(1/2,1/6,1,2,2,3,1,1/365)}

def check_edge_rows(fx,params):
    """Item 8: each edge row's status (and the rounding_band flag for a row whose name ends -rounding-band), and N(x) on both sides of the
    series switch and the density cutoff (spec 3.8)."""
    switch=[p for p in fx['oracle']['lnphi'] if p.get('kind') in ('series-switch','density-cutoff')]
    bad=[f"normal({p['x']})" for p in switch if normal_error(p)]
    for e in fx['oracle']['edge_rows']:
        pp=CaseParams(**{**params.__dict__,**e.get('params',{})})
        st,_,flags=evaluate(tuple(e['row']),e['model'],pp)
        if st!=e['status'] or (e['name'].endswith('-rounding-band') and not flags&FLAG_ROUNDING_BAND):bad.append(e['name'])
    baw=[e for e in fx['oracle'].get('baw',[]) if e.get('kind')=='edge']
    if not baw:bad.append('baw: no edge rows in the fixture')
    bad+=[e['name'] for e in baw if not baw_edge_ok(e,params)]
    alo=[e for e in fx['oracle'].get('alo',[]) if e.get('kind')=='edge']
    if not alo:bad.append('alo: no edge rows in the fixture')
    bad+=[e['name'] for e in alo if not alo_edge_ok(e,params)]
    out=_status(bad,len(fx['oracle']['edge_rows'])+len(switch)+len(baw)+len(alo),blocked=not switch);out['baw_edge_rows']=len(baw);out['alo_edge_rows']=len(alo);return out

def alo_edge_ok(e,params):
    """An ALO edge row (I4.4 item 8): py-reference gives the stored status, flags and row equation; a 'DEFECT' row raises
    models.AloRunDefect with the stored kind and site (never a status)."""
    from optionlab.models import AloRunDefect
    from optionlab.reference import evaluate as evaluate4
    pp=CaseParams(**{**params.__dict__,**e.get('params',{})});info={}
    if e['status']=='DEFECT':
        try:evaluate4(tuple(e['row']),'alo',pp,info=info)
        except AloRunDefect as exc:return (exc.args[0],exc.site)==(e['defect'],e['site'])
        return False
    st,_,flags,_=evaluate4(tuple(e['row']),'alo',pp,info=info)
    return (st,flags,info.get('alo_equation'))==(e['status'],e['flags'],e['equation'])

def baw_edge_ok(e,params):
    """A BAW edge row (G2.5 item 8): py-reference gives the stored status, flags and admit_reason; a 'DEFECT' row raises
    models.BawRunDefect with the stored text (never a status)."""
    from optionlab.models import BawRunDefect, RunDefect, AloRunDefect
    from optionlab.reference import evaluate as evaluate4
    pp=CaseParams(**{**params.__dict__,**e.get('params',{})});info={}
    if e['status']=='DEFECT':
        try:evaluate4(tuple(e['row']),'baw',pp,info=info)
        except BawRunDefect as exc:return exc.args==(e['defect'],)
        return False
    st,_,flags,_=evaluate4(tuple(e['row']),'baw',pp,info=info)
    return (st,flags,info.get('admit_reason'))==(e['status'],e['flags'],e['reason'])

def floor_multiplier(terms,cal):
    """Smallest floor_eps_multiplier that covers every item 7 term (spec 4 item 7: the floor constants are calibrated in Phase 1).
    A term holds kind, h, value, error and its bound under `cal`; only the error above the truncation part of the bound counts."""
    need=0.0
    for t in terms:
        order,scale=LEAD[t['kind']][4],LEAD[t['kind']][5]
        truncation=t['bound']-floor(t['value'],t['h'],order,cal,scale,t.get('inputs'))
        unit=scale*EPS*max(1.0,abs(t['value']))/t['h']**order
        excess=t['error']-truncation-cal['floor_abs']
        if excess>0.0:need=max(need,excess/unit)
    return need

def calibrated_floor(need):
    """Calibrated multiplier: 2 x the largest requirement on the grid (the C_crr and rho_bjs rule), an integer, at least the spec value."""
    return max(FLOOR_EPS_MIN,math.ceil(2.0*need))

def item7_terms(fx,cal):
    return [v for p in fx['oracle']['greeks'] for v in item7_point(p,cal).values()]

def kappa_decision(failures,params):
    """L5: a failure is fixable by a lower kappa_cap only below sigma_carry at kappa_cap = 10 (the lowest cap this plan proposes)."""
    if not failures:return 'PASS'
    for f in failures:
        b=(params.rate-params.dividend_yield) if f['side']==0 else (params.dividend_yield-params.rate)
        if f['sigma']>=math.sqrt(2.0*(abs(b)+params.h_r)/10.0):return 'OWNER_ESCALATION'
    return 'LOWER_KAPPA'

SIGMA_BANDS=((0.1,'sigma<=0.1'),(0.3,'0.1<sigma<=0.3'),(1.0,'0.3<sigma<=1'),(math.inf,'sigma>1'))
T_BANDS=((7/365,'T<=7d'),(0.25,'7d<T<=0.25y'),(1.0,'0.25y<T<=1y'),(math.inf,'T>1y'))

def _band(x,bands):return next(label for edge,label in bands if x<=edge)

def bjs_lattice_metric(fx,params):
    """Owner decision (Task 9): BjS (1993 since Task 7b) against the converged CRR lattice is a documented model-accuracy metric, not a gate.
    Relative gap (A_ref - BjS)/A_ref over points with A_ref >= 0.01 (a quotable price), per sigma band and maturity band."""
    from optionlab.numeric import median, quantile
    r,q=params.rate,params.dividend_yield;groups={};gaps=[];above=0;skipped=0
    for p in fx['oracle']['lattice']:
        bj=bjs_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma']);above+=bj>p['a_ref']+p['eps_ref']
        if p['a_ref']<0.01:skipped+=1;continue
        g=(p['a_ref']-bj)/p['a_ref'];gaps.append(g)
        groups.setdefault(_band(p['sigma'],SIGMA_BANDS)+'|'+_band(p['T'],T_BANDS),[]).append(g)
    stats=lambda xs:{'count':len(xs),'median':median(xs),'p90':quantile(xs,0.9),'max':max(xs)}
    return {'count':len(gaps),'skipped_below_0.01':skipped,'above_lattice':above,'all':stats(gaps) if gaps else None,
            'bands':{k:stats(v) for k,v in sorted(groups.items())}}

def baw_lattice_metric(fx,params):
    """Amendment G2.5: BAW against the converged CRR lattice reference A_ref (section 4 item 5) is a documented
    model-accuracy metric, never a gate. Per SIGMA_BANDS x T_BANDS: count, median, p90 and maximum of (A_ref - BAW)/A_ref
    for A_ref >= 0.01, and the counts of points above A_ref + eps_ref and below A_ref - eps_ref (BAW is not a bound).
    A lattice point that BAW does not price (baw_admit false or a QuantLib exception) is counted in `not_priced`."""
    from optionlab.numeric import median, quantile
    price=price_function('baw',params);r,q=params.rate,params.dividend_yield;groups={};gaps=[];above=0;below=0;skipped=0;not_priced=0
    for p in fx['oracle']['lattice']:
        try:v=price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma'])
        except RunDefect:raise                                        # record R8: a run defect fails the run (review I-1)
        except ArithmeticError:not_priced+=1;continue
        above+=v>p['a_ref']+p['eps_ref'];below+=v<p['a_ref']-p['eps_ref']
        if p['a_ref']<0.01:skipped+=1;continue
        g=(p['a_ref']-v)/p['a_ref'];gaps.append(g);groups.setdefault(_band(p['sigma'],SIGMA_BANDS)+'|'+_band(p['T'],T_BANDS),[]).append(g)
    stats=lambda xs:{'count':len(xs),'median':median(xs),'p90':quantile(xs,0.9),'max':max(xs)}
    return {'count':len(gaps),'skipped_below_0.01':skipped,'not_priced':not_priced,'above_lattice':above,'below_lattice':below,
            'all':stats(gaps) if gaps else None,'bands':{k:stats(v) for k,v in sorted(groups.items())}}

def calibrate(fx,params):
    lat=fx['oracle']['lattice'];r,q=params.rate,params.dividend_yield
    ratios=[];conv=True;gaps=[];above=0
    for p in lat:
        scale=p['S']*p['sigma']*math.sqrt(p['T']);errs={int(N):abs(v-p['bsm']) for N,v in p['euro'].items()}
        ratios+=[e*N/scale for N,e in errs.items()]
        bj=bjs_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma']);gaps.append(max(0.0,(p['a_ref']-bj-p['eps_ref'])/p['a_ref']) if p['a_ref']>0 else 0.0)   # the rho the distance band needs (net of eps_ref)
        above+=bj>p['a_ref']+p['eps_ref']
    for N in (100,200,400) if lat else ():
        if max(abs(p['euro'][str(2*N)]-p['bsm']) for p in lat)>0.75*max(abs(p['euro'][str(N)]-p['bsm']) for p in lat):conv=False
    item2=check_bjs(fx,params)
    rho=2.0*max(gaps) if gaps else None
    spec_cal=dict(fx['calibration']['item7'],floor_eps_multiplier=FLOOR_EPS_MIN);terms=item7_terms(fx,spec_cal)
    default_violations=sum(not t['error']<=t['bound'] for t in terms);need=floor_multiplier(terms,spec_cal);mult=calibrated_floor(need)
    new_cal=dict(spec_cal,floor_eps_multiplier=mult);violations=sum(not t['error']<=t['bound'] for t in item7_terms(fx,new_cal))
    decision=item2['decision']   # rho_bjs and the lattice lower bound are reported, never escalated (owner decision, Task 9)
    locked=fx['calibration'].get('locked') and fx['calibration']['item7'].get('floor_eps_multiplier')==mult
    if decision=='PASS' and mult>FLOOR_EPS_MIN and not locked:decision='PENDING_APPROVAL'   # a raised floor needs the approver lock
    return {'c_crr':2.0*max(ratios) if ratios else None,'rho_bjs':rho,'convergence':conv,'bjs_lower_bound_violations':above,
            'item2_failures':item2['failures'],'item7_violations':violations,'item7_violations_at_spec_floor':default_violations,
            'floor_requirement':need,'floor_eps_multiplier':mult,'bjs_vs_lattice':bjs_lattice_metric(fx,params),
            'decision':decision if not violations else 'OWNER_ESCALATION'}   # Amendment D item 2: C_crr and convergence never escalate

def run_all(fx,params):
    checks=(check_bsm,check_bjs,check_known_answers,check_normal,check_properties,check_iv_roundtrip,check_greeks,check_edge_rows)
    return {str(i+1):fn(fx,params) for i,fn in enumerate(checks)}
