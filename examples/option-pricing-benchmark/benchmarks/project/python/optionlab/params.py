"""Case parameters (spec 3.1; protected values live in the case manifest)."""
import json, math
from dataclasses import dataclass, field
from pathlib import Path

CASE_FILE=Path(__file__).resolve().parents[2]/'cases'/'option-chain-greeks.json'
NEWTON_MAX_RANGE=(1,40)     # Appendix G-BAW R3: the record proves N(inputs) <= 40; tests may lower the cap (P3P-15)

def check_newton_max(v):
    """The one validator of baw_newton_max: an integer (a JSON number with no fraction) in NEWTON_MAX_RANGE. Returns int."""
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v!=int(v) or not NEWTON_MAX_RANGE[0]<=v<=NEWTON_MAX_RANGE[1]:
        raise ValueError('baw_newton_max: an integer in [%d, %d] required (Appendix G-BAW R3)'%NEWTON_MAX_RANGE)
    return int(v)

ALO_SCHEME={"name":"accurateScheme","class":"QdFpLegendreTanhSinhScheme","l":25,"m":5,"n":13,"eps":1e-8,"fp_equation":"Auto"}   # Amendment I2.2

def check_alo_scheme(v):
    """The one validator of alo_scheme (Amendment I2.2, protected): exactly the owner-ruled accurateScheme value; a change is
    a new definition (owner decision, new case version, new G-ALO1 record), so any other value raises ValueError."""
    if not isinstance(v,dict) or v!=ALO_SCHEME or any(type(v[k]) is not type(ALO_SCHEME[k]) for k in ALO_SCHEME):
        raise ValueError('alo_scheme: the Amendment I2.2 value is required (a change is a new definition)')
    return dict(v)

@dataclass(frozen=True)
class CaseParams:
    rate:float
    dividend_yield:float
    crr_steps:int
    sigma_hi:float=5.0
    kappa_cap:float=50.0
    h_r:float=1e-4
    h_sigma:float=1e-3
    baw_newton_max:int=field(kw_only=True)   # Appendix G-BAW R3: protected case parameter (label protocol); no code default
    baw_plant_nan_sstar:bool=False      # test-only (G2.3 planted non-finite S*); never in a manifest or a timed run
    alo_scheme:dict=field(default_factory=lambda:dict(ALO_SCHEME),kw_only=True,hash=False)   # Amendment I2.2 (protected; label protocol)
    alo_plant_nan:str=''                # test-only (I4.1 planted NaN at an alo.VALUE_MASK_SITES site); never in a manifest or a timed run
    alo_force_cap:str=''                # test-only (I4.1 forced cap excess of an alo.CAP_NAMES loop); never in a manifest or a timed run

_MANIFEST=json.loads(CASE_FILE.read_text())['parameters']
MANIFEST_NEWTON_MAX=check_newton_max(_MANIFEST['baw_newton_max']['value'])
MANIFEST_ALO_SCHEME=check_alo_scheme(_MANIFEST['alo_scheme']['value'])
CASE=CaseParams(0.04,0.012,100,baw_newton_max=MANIFEST_NEWTON_MAX,alo_scheme=MANIFEST_ALO_SCHEME)

REQUIRED=('rate','dividend_yield','crr_steps','sigma_hi','kappa_cap','h_r','h_sigma','seed','baw_newton_max')

def params_from_manifest(case):
    """Pricing parameters of an option case manifest. Every parameter in REQUIRED must be present (the completeness rule
    that tools/bench_model.params_from_case held for option-chain-greeks before Amendment A); a missing one raises ValueError."""
    p={k:v['value'] for k,v in case['parameters'].items()}
    missing=[k for k in REQUIRED if k not in p]
    if missing:raise ValueError('option case parameters incomplete: '+', '.join(missing))
    return CaseParams(float(p['rate']),float(p['dividend_yield']),int(p['crr_steps']),float(p['sigma_hi']),float(p['kappa_cap']),float(p['h_r']),float(p['h_sigma']),
                      baw_newton_max=check_newton_max(p['baw_newton_max']),alo_scheme=check_alo_scheme(p.get('alo_scheme',ALO_SCHEME)))
