import copy, json, math, unittest
from pathlib import Path
ROOT=Path('/src')   # the bench container mounts the repository read-only at /src
from optionlab.agreement import compare, multi_root, tau_sigma, TOLERANCES
from optionlab.reference import FLAG_BOUNDARY_AMBIGUOUS
from optionlab.params import CASE
from optionlab.models import ModelDefect
from optionlab import protocol

ROWS=[(0,100.0,100.0,0.5,6.0,6.2,0.04,0.012),(1,100.0,90.0,0.25,1.0,1.1,0.04,0.012),(0,100.0,100.0,0.0,1.0,1.1,0.04,0.012)]

class AgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from optionlab.reference import evaluate3 as evaluate
        from optionlab.contract import FIELDS
        col={'status':[],'flags':[],**{f:[] for f in FIELDS}}
        for row in ROWS:
            st,vals,fl=evaluate(row,'bsm',CASE);col['status'].append(st);col['flags'].append(fl)
            for f,x in zip(FIELDS,vals):col[f].append(x)
        cls.ref={'n':3,'models':{'bsm':col}}
    def cmp(self,got):return compare(ROWS,got,self.ref,CASE,models=('bsm',))
    def test_identical_result_is_eligible(self):
        v=self.cmp(copy.deepcopy(self.ref));self.assertTrue(v['eligible']);self.assertEqual(v['reduction'],'MATCH')
    def test_perturbed_greek_is_a_failure(self):
        got=copy.deepcopy(self.ref);got['models']['bsm']['vega'][0]*=1+1e-4
        v=self.cmp(got);self.assertFalse(v['eligible']);self.assertEqual(v['failures'],{'bsm.vega':1})
    def test_negative_zero_equals_zero_and_infinity_fails(self):
        ref=copy.deepcopy(self.ref);ref['models']['bsm']['rho'][0]=0.0
        got=copy.deepcopy(ref);got['models']['bsm']['rho'][0]=-0.0
        self.assertTrue(compare(ROWS,got,ref,CASE,models=('bsm',))['eligible'])
        got['models']['bsm']['delta'][1]=math.inf;self.assertEqual(compare(ROWS,got,ref,CASE,models=('bsm',))['failures'],{'bsm.nonfinite':1})
    def test_nan_rules(self):
        got=copy.deepcopy(self.ref);got['models']['bsm']['iv'][2]=0.2;self.assertEqual(self.cmp(got)['failures'],{'bsm.nan':1})
    def test_status_mismatch_and_missing_rows(self):
        got=copy.deepcopy(self.ref);got['models']['bsm']['status'][0]='NOT_CONVERGED'
        self.assertIn('bsm.status',self.cmp(got)['failures'])
        got=copy.deepcopy(self.ref);got['models']['bsm']['iv'].pop();self.assertEqual(self.cmp(got)['reduction'],'MISSING_ROWS')
    def test_boundary_ambiguous_row_accepts_a_neighbor_status(self):
        ref=copy.deepcopy(self.ref);ref['models']['bsm']['flags'][0]|=FLAG_BOUNDARY_AMBIGUOUS
        got=copy.deepcopy(ref);got['models']['bsm']['status'][0]='BELOW_MIN'
        for f in ('iv','price','delta','gamma','theta','vega','rho'):got['models']['bsm'][f][0]=math.nan
        v=compare(ROWS,got,ref,CASE,models=('bsm',));self.assertTrue(v['eligible']);self.assertEqual(v['boundary_ambiguous'],{'bsm':1})   # row 1 is a band row, compared since Amendment D item 3
    def test_otm_put_at_sigma_lo_is_a_rounding_band_row(self):
        # Task 7b: ROWS[1] (put, K = 90 < F) at sigma_lo = 1e-4 has N(d1) = N(d2) = 1 - 2^-53 (QuantLib erf gives 1 - eps for
        # |x| >= 6), so V = D (K - F) 2^-53 < 0 inside the band: py-reference marks it rounding_band, and since Amendment D
        # item 3 not boundary_ambiguous (the band relaxes the status only).
        from optionlab.reference import FLAG_ROUNDING_BAND
        self.assertTrue(self.ref['models']['bsm']['flags'][1]&FLAG_ROUNDING_BAND);self.assertFalse(self.ref['models']['bsm']['flags'][1]&FLAG_BOUNDARY_AMBIGUOUS)
        self.assertFalse(self.ref['models']['bsm']['flags'][0]&FLAG_BOUNDARY_AMBIGUOUS);self.assertEqual(self.ref['models']['bsm']['status'][1],'OK')
    def test_tolerances_equal_the_policy_values(self):
        policy=protocol.tolerances()
        self.assertEqual(TOLERANCES,{k:policy[k] for k in TOLERANCES})
    def test_l1_close_roots_missed_by_the_grid_are_caught_by_brackets(self):
        r1,r2=0.300000000,0.300000004   # roots 4e-9 apart: no 64-point grid cell separates them
        price=lambda side,S,K,T,r,q,s:(s-r1)*(s-r2)*-1e6+1.0
        self.assertTrue(multi_root(price,(0,100.0,100.0,0.5,1.0,1.0,0.04,0.012),'bsm',CASE,r1,r2,1.0))
        single=lambda side,S,K,T,r,q,s:(s-r1)+1.0
        self.assertFalse(multi_root(single,(0,100.0,100.0,0.5,1.0,1.0,0.04,0.012),'bsm',CASE,r1,r2,1.0))

    # Additions beyond the brief: row count, reduction mismatch, flat_vega, ambiguous-row NaN rule.
    def test_row_count_mismatch(self):
        got=copy.deepcopy(self.ref);got['n']=2
        v=self.cmp(got);self.assertFalse(v['eligible']);self.assertEqual(v['reduction'],'ROW_COUNT')
    def test_reduction_mismatch_when_the_maximum_iv_moves(self):
        got=copy.deepcopy(self.ref);col=got['models']['bsm']
        for i,s in enumerate(col['status']):
            if s=='OK':col['iv'][i]+=1e-3
        v=self.cmp(got);self.assertFalse(v['eligible']);self.assertEqual(v['reduction'],'MISMATCH')
    def test_unknown_status_text_is_a_status_failure(self):
        got=copy.deepcopy(self.ref);got['models']['bsm']['status'][2]='EXPIRED '
        v=self.cmp(got);self.assertEqual(v['failures'],{'bsm.status':1});self.assertEqual(v['reduction'],'MISMATCH');self.assertFalse(v['eligible'])
    def test_boundary_ambiguous_row_keeps_the_nan_and_finite_rules(self):
        ref=copy.deepcopy(self.ref);ref['models']['bsm']['flags'][0]|=FLAG_BOUNDARY_AMBIGUOUS
        got=copy.deepcopy(ref);got['models']['bsm']['status'][0]='BELOW_MIN'   # numeric fields stay finite: a NaN-rule failure
        self.assertEqual(compare(ROWS,got,ref,CASE,models=('bsm',))['failures'],{'bsm.nan':1})
        got=copy.deepcopy(ref);got['models']['bsm']['gamma'][0]=math.inf      # neighbor status OK with infinity
        self.assertEqual(compare(ROWS,got,ref,CASE,models=('bsm',))['failures'],{'bsm.nonfinite':1})
        got=copy.deepcopy(ref);got['models']['bsm']['status'][0]='NOT_CONVERGED'
        self.assertIn('bsm.status',compare(ROWS,got,ref,CASE,models=('bsm',))['failures'])

def synthetic(iv,price=1.0,vega=0.2):
    """One OK row (mid 1.0) with hand-set reference columns, for injected price functions."""
    col={'status':['OK'],'flags':[0],'iv':[iv],'price':[price],'delta':[0.5],'gamma':[0.01],'theta':[-0.01],'vega':[vega],'rho':[0.1]}
    return {'n':1,'models':{'bsm':col}}
ROW1=[(0,100.0,100.0,0.5,0.9,1.1,0.04,0.012)]
THREE=lambda side,S,K,T,r,q,s:(s-0.2)*(s-1.0)*(s-3.0)+1.0     # three well separated roots of f = price - mid: the grid sees them
SINGLE=lambda side,S,K,T,r,q,s:(s-0.2)+1.0

class MultiRootPrecedenceTests(unittest.TestCase):
    """Spec 3.3 precedence: grid test first; then the L1 bracket test; only when both fail is the difference an `iv` failure."""
    def test_grid_rule_applies_first_without_a_bracket_sign_change(self):
        # iv_var = 0.5 is no root: its bracket shows no sign change, but the grid shows three, so the row is multi_root.
        self.assertTrue(multi_root(THREE,ROW1[0],'bsm',CASE,0.2,0.5,1.0))
    def test_bracket_rule_applies_when_the_grid_shows_at_most_one_sign_change(self):
        r1,r2=0.3,0.300001
        price=lambda side,S,K,T,r,q,s:(s-r1)*(s-r2)*-1e6+1.0
        lo=1e-4;grid=[lo*(5.0/lo)**(j/63) for j in range(64)]
        self.assertFalse(any(r1<=g<=r2 for g in grid))            # the grid alone sees no sign change
        self.assertTrue(multi_root(price,ROW1[0],'bsm',CASE,r1,r2,1.0))
    def test_neither_rule_leaves_an_iv_failure(self):
        self.assertFalse(multi_root(SINGLE,ROW1[0],'bsm',CASE,0.2,0.2+1e-3,1.0))
        v=compare(ROW1,synthetic(0.2+1e-3),synthetic(0.2),CASE,price_function=SINGLE,models=('bsm',))
        self.assertEqual(v['failures'],{'bsm.iv':1});self.assertEqual(v['multi_root'],{'bsm':0})
    def test_equal_ivs_never_get_the_bracket_rule(self):
        self.assertFalse(multi_root(SINGLE,ROW1[0],'bsm',CASE,0.2,0.2,1.0))
    def test_multi_root_row_passes_when_the_variant_iv_fits_mid(self):
        v=compare(ROW1,synthetic(1.0),synthetic(0.2),CASE,price_function=THREE,models=('bsm',))
        self.assertTrue(v['eligible']);self.assertEqual(v['multi_root'],{'bsm':1});self.assertEqual(v['reduction'],'MATCH')
    def test_multi_root_row_fails_the_fit_rule_off_a_root(self):
        v=compare(ROW1,synthetic(0.5),synthetic(0.2),CASE,price_function=THREE,models=('bsm',))
        self.assertFalse(v['eligible']);self.assertEqual(v['failures'],{'bsm.fit':1});self.assertEqual(v['multi_root'],{'bsm':1})
    def test_close_bracket_roots_pass_through_compare(self):
        r1,r2=0.3,0.300001
        price=lambda side,S,K,T,r,q,s:(s-r1)*(s-r2)*-1e6+1.0
        self.assertGreater(abs(r2-r1),tau_sigma(1.0,20.0))
        v=compare(ROW1,synthetic(r2),synthetic(r1),CASE,price_function=price,models=('bsm',))
        self.assertTrue(v['eligible']);self.assertEqual(v['multi_root'],{'bsm':1})

class FlatVegaTests(unittest.TestCase):
    def test_flat_vega_row_compares_the_fit_rule_only(self):
        ref=synthetic(0.2,vega=1e-16);got=synthetic(0.9,vega=1e-16)    # IV far off: flat_vega rows skip the IV comparison
        v=compare(ROW1,got,ref,CASE,price_function=SINGLE,models=('bsm',))
        self.assertTrue(v['eligible']);self.assertEqual(v['flat_vega'],{'bsm':1})
        got['models']['bsm']['price'][0]=1.0+1e-6
        self.assertEqual(compare(ROW1,got,ref,CASE,price_function=SINGLE,models=('bsm',))['failures'],{'bsm.fit':1})

class ReviewFixTests(unittest.TestCase):
    """Task 10 review fix round 1."""
    def test_fit_slope_stays_inside_the_domain(self):
        ra=1e-4+2e-7      # a variant root 2e-7 above sigma_lo (bsm 1e-4); the old step evaluated sigma_lo - 8e-7
        def price(side,S,K,T,r,q,s):
            if s<1e-4:raise ModelDefect('below sigma_lo')
            return (s-ra)*(s-0.2)*(s-1.0)*10.0+1.0
        v=compare(ROW1,synthetic(ra),synthetic(0.2),CASE,price_function=price,models=('bsm',))
        self.assertTrue(v['eligible']);self.assertEqual(v['multi_root'],{'bsm':1})
    def test_short_dated_crr_slope_at_sigma_lo(self):
        from optionlab.agreement import fit_slope
        from optionlab.models import sigma_lo
        from optionlab.reference import price_function
        row=(0,100.0,100.0,1.0/365.0,1.0,1.1,0.04,0.012);price=price_function('crr',CASE);lo=sigma_lo('crr',0,row[3],0.04,0.012,CASE)
        with self.assertRaises(ModelDefect):price(0,100.0,100.0,row[3],0.04,0.012,lo-1e-6)   # the unclipped step is a model defect
        self.assertTrue(math.isfinite(fit_slope(price,row,'crr',CASE,lo)))
    def test_variant_iv_outside_the_domain_is_an_iv_failure(self):
        for root in (5.5,5e-5):
            price=lambda side,S,K,T,r,q,s,root=root:(s-0.2)*(s-1.0)*(s-root)+1.0   # grid sees two sign changes; root fits mid
            v=compare(ROW1,synthetic(root),synthetic(0.2),CASE,price_function=price,models=('bsm',))
            self.assertEqual(v['failures'],{'bsm.iv':1},root);self.assertEqual(v['multi_root'],{'bsm':0})
    def test_model_error_in_extra_points_is_a_recorded_failure(self):
        for exc in (ModelDefect,):          # Task 7b: TailCondition left the definition (no bivariate term in BjS 1993)
            def price(side,S,K,T,r,q,s,exc=exc):
                if s>2.0:raise exc()
                return (s-0.2)+1.0
            v=compare(ROW1,synthetic(0.201),synthetic(0.2),CASE,price_function=price,models=('bsm',))
            self.assertFalse(v['eligible']);self.assertEqual(v['failures'],{'bsm.model_error':1})
            self.assertEqual(v['model_errors'],{'bsm':{exc.__name__:1}})
    def test_multi_root_grid_equals_the_policy_value(self):
        from optionlab.agreement import MULTI_ROOT_GRID
        policy=protocol.solver()
        self.assertEqual(MULTI_ROOT_GRID,policy['multi_root_grid'])

class RoundingBandTests(unittest.TestCase):
    """Task 7a round-2 item M-A: every variant sets the rounding_band flag; a band row accepts py-reference's status or
    MODEL_DOMAIN, leaves the numeric comparison and is counted (L-A: a band hit in the variant only is counted too)."""
    @classmethod
    def setUpClass(cls):
        from optionlab.reference import FLAG_ROUNDING_BAND
        AgreementTests.setUpClass();cls.band=FLAG_ROUNDING_BAND;cls.ref=AgreementTests.ref
    def test_band_row_accepts_the_reference_status_or_model_domain(self):
        for side in ('ref','got'):
            ref=copy.deepcopy(self.ref);got=copy.deepcopy(ref)
            (ref if side=='ref' else got)['models']['bsm']['flags'][0]|=self.band
            got['models']['bsm']['status'][0]='MODEL_DOMAIN'
            for f in ('iv','price','delta','gamma','theta','vega','rho'):got['models']['bsm'][f][0]=math.nan
            v=compare(ROWS,got,ref,CASE,models=('bsm',))
            with self.subTest(side=side):
                self.assertTrue(v['eligible']);self.assertEqual(v['rounding_band'],{'bsm':2})      # row 0 here and the reference band row 1
                self.assertEqual(v['rounding_band_variant_only'],{'bsm':1 if side=='got' else 0})
                self.assertEqual(v['band_status_mismatch'],{'bsm':1})          # Amendment D item 3
    def test_band_row_rejects_another_status(self):
        ref=copy.deepcopy(self.ref);ref['models']['bsm']['flags'][0]|=self.band
        got=copy.deepcopy(ref);got['models']['bsm']['status'][0]='NOT_CONVERGED'
        for f in ('iv','price','delta','gamma','theta','vega','rho'):got['models']['bsm'][f][0]=math.nan
        self.assertEqual(compare(ROWS,got,ref,CASE,models=('bsm',))['failures'],{'bsm.status':1})
    def test_band_row_with_equal_ok_status_is_compared_numerically(self):
        # Amendment D item 3: both OK -> the normal section 3.7 comparison (this replaces "the band row leaves the comparison").
        ref=copy.deepcopy(self.ref);ref['models']['bsm']['flags'][0]|=self.band
        got=copy.deepcopy(ref);v=compare(ROWS,got,ref,CASE,models=('bsm',));self.assertTrue(v['eligible'])
        got['models']['bsm']['vega'][0]*=1+1e-3
        v=compare(ROWS,got,ref,CASE,models=('bsm',));self.assertEqual(v['failures'],{'bsm.vega':1});self.assertEqual(v['boundary_ambiguous'],{'bsm':0})
    def test_band_row_with_differing_status_is_skipped_and_counted(self):
        ref=copy.deepcopy(self.ref);got=copy.deepcopy(ref);got['models']['bsm']['flags'][0]|=self.band
        got['models']['bsm']['status'][0]='MODEL_DOMAIN'
        for f in ('iv','price','delta','gamma','theta','vega','rho'):got['models']['bsm'][f][0]=math.nan
        v=compare(ROWS,got,ref,CASE,models=('bsm',))
        self.assertEqual(v['failures'],{});self.assertEqual(v['band_status_mismatch'],{'bsm':1});self.assertTrue(v['eligible'])
        got['models']['bsm']['iv'][0]=0.2                                  # the NaN rule of the variant side still applies
        self.assertEqual(compare(ROWS,got,ref,CASE,models=('bsm',))['failures'],{'bsm.nan':1})
    def test_reverse_band_case_is_accepted_and_counted(self):
        # Review Minor 2 (Amendment D item 3, "or the reverse"): py-reference MODEL_DOMAIN, variant OK.
        got=copy.deepcopy(self.ref);ref=copy.deepcopy(got);ref['models']['bsm']['flags'][0]|=self.band
        ref['models']['bsm']['status'][0]='MODEL_DOMAIN'
        for f in ('iv','price','delta','gamma','theta','vega','rho'):ref['models']['bsm'][f][0]=math.nan
        v=compare(ROWS,got,ref,CASE,models=('bsm',))
        self.assertEqual(v['failures'],{});self.assertEqual(v['band_status_mismatch'],{'bsm':1});self.assertEqual(v['reduction'],'MATCH')
    def test_band_rule_accepts_only_ok_and_model_domain(self):
        # Review Minor 2: a MODEL_DOMAIN side with a status other than OK on the other side is a status failure.
        for rs,gs in (('MODEL_DOMAIN','ABOVE_MAX'),('MODEL_DOMAIN','NOT_CONVERGED'),('ABOVE_MAX','MODEL_DOMAIN'),('BELOW_MIN','MODEL_DOMAIN')):
            ref=copy.deepcopy(self.ref);ref['models']['bsm']['flags'][0]|=self.band;got=copy.deepcopy(ref)
            ref['models']['bsm']['status'][0]=rs;got['models']['bsm']['status'][0]=gs
            for col in (ref,got):
                for f in ('iv','price','delta','gamma','theta','vega','rho'):col['models']['bsm'][f][0]=math.nan
            with self.subTest(ref=rs,got=gs):
                v=compare(ROWS,got,ref,CASE,models=('bsm',));self.assertEqual(v['failures'],{'bsm.status':1});self.assertEqual(v['band_status_mismatch'],{'bsm':0})
    def test_band_rows_count_under_reference_status(self):
        from optionlab.reference import reduction
        ref=copy.deepcopy(self.ref);got=copy.deepcopy(ref);got['models']['bsm']['flags'][1]|=self.band
        got['models']['bsm']['status'][1]='MODEL_DOMAIN'
        for f in ('iv','price','delta','gamma','theta','vega','rho'):got['models']['bsm'][f][1]=math.nan
        self.assertNotEqual(reduction(got)['bsm']['counts'],reduction(ref)['bsm']['counts'])   # raw counts differ
        v=compare(ROWS,got,ref,CASE,models=('bsm',));self.assertEqual(v['reduction'],'MATCH');self.assertTrue(v['eligible'])
    def test_flags_of_the_wrong_length_are_missing_rows(self):
        got=copy.deepcopy(self.ref);got['models']['bsm']['flags'].pop()
        self.assertEqual(compare(ROWS,got,self.ref,CASE,models=('bsm',))['reduction'],'MISSING_ROWS')

if __name__=='__main__':unittest.main()
