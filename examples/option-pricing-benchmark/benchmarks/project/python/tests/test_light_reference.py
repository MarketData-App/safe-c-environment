import json, math, unittest
from pathlib import Path
ROOT=Path('/src')   # the bench container mounts the repository read-only at /src
from optionlab.contract import load_chain, decode_chain, ChainError, rows, STATUSES
from optionlab.solver import brent, N_MAX
from optionlab.reference import evaluate3 as evaluate, reduction, run, FLAG_BELOW_INTRINSIC
from optionlab.models import bsm_price
from optionlab.params import CASE

U=1791331200
def chain(**over):
    base={'s':'ok','optionSymbol':['A','B'],'side':['call','put'],'strike':[100.0,100.0],'expiration':[U+86400*30]*2,'updated':[U,U],
          'bid':[3.0,2.0],'ask':[3.2,2.2],'mid':[3.1,2.1],'underlyingPrice':[100.0,100.0],'openInterest':[10,20],
          'iv':[0.2,0.2],'delta':[0.5,-0.5],'gamma':[0.1,0.1],'theta':[-0.1,-0.1],'vega':[0.1,0.1]}
    base.update(over);return base

class ChainTests(unittest.TestCase):
    def test_null_numbers_and_unknown_side_are_row_statuses(self):
        c=load_chain(chain(side=['call','straddle'],bid=[None,2.0]))
        r=rows(c,CASE)
        self.assertEqual(evaluate(r[0],'bsm',CASE)[0],'INVALID_INPUT');self.assertEqual(evaluate(r[1],'bsm',CASE)[0],'INVALID_INPUT')
    def test_type_error_message_has_index_and_key_only(self):
        with self.assertRaises(ChainError) as ctx:load_chain(chain(strike=[100.0,'412.35']))
        self.assertEqual(str(ctx.exception),'record 1: strike')
        for bad in [chain(s='error'),{**chain(),'bid':[1.0]},{k:v for k,v in chain().items() if k!='vega'},[]]:
            with self.assertRaises(ChainError) as ctx:load_chain(bad)
            self.assertTrue(str(ctx.exception).startswith('chain: '));self.assertNotIn('412',str(ctx.exception))
    def test_size_limits(self):
        with self.assertRaises(ChainError):decode_chain(b' '*(32*1024*1024+1))
        n=20001;big={k:([v[0]]*n if isinstance(v,list) else v) for k,v in chain().items()}
        with self.assertRaises(ChainError):load_chain(big)
    def test_same_day_rows_are_priced_and_past_rows_expire(self):
        c=load_chain(chain(expiration=[U+3600,U],bid=[0.5,1.0],ask=[0.6,1.1]))
        r=rows(c,CASE)
        self.assertEqual(evaluate(r[0],'bsm',CASE)[0],'OK');self.assertEqual(evaluate(r[1],'bsm',CASE)[0],'EXPIRED')
    def test_status_order(self):
        base=(0,100.0,100.0,0.5,3.0,3.2,0.04,0.012)
        cases=[((0,-1.0)+base[2:],'INVALID_INPUT'),(base[:3]+(0.0,)+base[4:],'EXPIRED'),(base[:4]+(0.0,1.0)+base[6:],'NO_BID'),
               (base[:4]+(3.2,3.0)+base[6:],'CROSSED'),(base[:4]+(0.5,0.5)+base[6:],'BELOW_MIN'),(base[:4]+(250.0,250.0)+base[6:],'ABOVE_MAX')]
        for row,status in cases:
            with self.subTest(status=status):self.assertEqual(evaluate(row,'bsm',CASE)[0],status)
    def test_locked_quote_is_accepted(self):
        self.assertEqual(evaluate((0,100.0,100.0,0.5,6.0,6.0,0.04,0.012),'bsm',CASE)[0],'OK')
    def test_below_intrinsic_flag(self):
        st,vals,flags=evaluate((0,150.0,100.0,0.5,10.0,10.0,0.04,0.012),'bsm',CASE)
        self.assertEqual(st,'BELOW_MIN');self.assertTrue(flags&FLAG_BELOW_INTRINSIC);self.assertTrue(all(math.isnan(v) for v in vals))

class SolverTests(unittest.TestCase):
    """Task 7b: QuantLib Brent (spec 3.5) replaces the Illinois regula falsi."""
    def test_iv_round_trip_bsm(self):
        target=bsm_price(1,100,90,0.25,0.04,0.012,0.37)
        st,s,fa,fb,n=brent(lambda x:bsm_price(1,100,90,0.25,0.04,0.012,x)-target,1e-4,5.0,2.50005)
        self.assertEqual(st,'OK');self.assertLess(abs(s-0.37),1e-8);self.assertLessEqual(n,N_MAX)
    def test_bracket_statuses(self):
        self.assertEqual(brent(lambda x:x+1.0,1e-4,5.0,2.50005)[0],'BELOW_MIN');self.assertEqual(brent(lambda x:x-9.0,1e-4,5.0,2.50005)[0],'ABOVE_MAX')
        self.assertEqual(brent(lambda x:x+1.0,1e-4,5.0,2.50005)[4],2)      # the bracket error after the two end calls
    def test_evaluation_cap_gives_not_converged(self):
        self.assertEqual(brent(lambda x:math.copysign(1.0,x-1.234567),1e-4,5.0,2.50005,accuracy=1e-300,max_evaluations=5)[0],'NOT_CONVERGED')

class ReductionTests(unittest.TestCase):
    def test_reduction_counts_every_status_and_excludes_flagged_rows(self):
        col={'status':['OK','EXPIRED','OK'],'iv':[0.2,math.nan,0.5]}
        red=reduction({'models':{'bsm':col}})['bsm']
        self.assertEqual((red['counts']['OK'],red['counts']['EXPIRED'],red['max_iv_index']),(2,1,2))
        red=reduction({'models':{'bsm':col}},{'bsm':[2]})['bsm'];self.assertEqual((red['counts']['OK'],red['max_iv_index']),(1,0))

# Review fix round 1 (Task 7): codec strictness, canonical digest, flags, MODEL_DOMAIN, safeguard, numeric range.
import dataclasses, hashlib, itertools
from unittest import mock
from optionlab.contract import FIELDS
from optionlab.reference import (FLAG_BOUNDARY_AMBIGUOUS, FLAG_FLAT_VEGA, canonical_result, result_digest)
from optionlab.numeric import median, quantile

class StrictCodecTests(unittest.TestCase):
    def test_valid_input_decodes(self):
        self.assertEqual(decode_chain(json.dumps(chain()).encode())['n'],2)
    def test_integer_beyond_binary64_is_a_row_status(self):
        for big in (10**400,-10**400):
            with self.subTest(sign=big>0):
                c=decode_chain(json.dumps(chain(strike=[big,100.0])).encode())
                r=rows(c,CASE)
                self.assertEqual(evaluate(r[0],'bsm',CASE)[0],'INVALID_INPUT');self.assertEqual(evaluate(r[1],'bsm',CASE)[0],'OK')
    def test_non_json_constants_reject_the_input(self):
        for bad in (math.nan,math.inf,-math.inf):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(ChainError) as ctx:decode_chain(json.dumps(chain(bid=[bad,2.0])).encode())
                self.assertEqual(str(ctx.exception),'chain: input is not JSON')
    def test_duplicate_key_rejects_the_input(self):
        text=json.dumps(chain());data=('{"strike":[1.0,2.0],'+text[1:]).encode()
        with self.assertRaises(ChainError) as ctx:decode_chain(data)
        self.assertEqual(str(ctx.exception),'chain: duplicate key')
    def test_deep_nesting_rejects_the_input(self):
        with self.assertRaises(ChainError) as ctx:decode_chain(b'['*200000+b']'*200000)
        self.assertEqual(str(ctx.exception),'chain: input is not JSON')

def one_row(**over):
    col={'status':['OK'],'flags':[0],**{f:[1.0] for f in FIELDS}};col.update(over);return {'n':1,'models':{'bsm':col}}

class DigestTests(unittest.TestCase):
    # Amendment G5 (Task 2): the ocg-v1 form belongs to the key set {bsm, bjs, crr} exactly; a bsm-only result is ocg-v1m
    # with mask 1. The model object bytes below are the Phase 1 pin, unchanged; only the envelope follows G5.
    MODEL_BYTES=(b'{"delta":["3ff0000000000000"],"flags":[0],"gamma":["0000000000000000"],'
                 b'"iv":["3ff0000000000000"],"price":["3ff0000000000000"],"rho":["4000000000000000"],"status":["OK"],"theta":[null],'
                 b'"vega":["3ff0000000000000"]}')
    def test_canonical_bytes_and_digest(self):
        one=one_row(gamma=[-0.0],theta=[math.nan],rho=[2]);res={'n':1,'models':{m:dict(one['models']['bsm']) for m in ('bsm','bjs','crr')}}
        expected=(b'{"digest_form":"ocg-v1","models":{"bjs":'+self.MODEL_BYTES+b',"bsm":'+self.MODEL_BYTES+b',"crr":'+self.MODEL_BYTES+b'},"n":1}')
        self.assertEqual(canonical_result(res),expected);self.assertEqual(result_digest(res),hashlib.sha256(expected).hexdigest())
    def test_canonical_bytes_of_a_one_model_result(self):
        res=one_row(gamma=[-0.0],theta=[math.nan],rho=[2])
        expected=b'{"digest_form":"ocg-v1m","mask":1,"models":{"bsm":'+self.MODEL_BYTES+b'},"n":1}'
        self.assertEqual(canonical_result(res),expected);self.assertEqual(result_digest(res),hashlib.sha256(expected).hexdigest())
    def test_signed_zero_and_int_values_hash_equal(self):
        self.assertEqual(result_digest(one_row(delta=[-0.0])),result_digest(one_row(delta=[0.0])))
        self.assertEqual(result_digest(one_row(iv=[1])),result_digest(one_row(iv=[1.0])))
        self.assertNotEqual(result_digest(one_row(iv=[1.0])),result_digest(one_row(iv=[math.nextafter(1.0,2.0)])))
    def test_rejections(self):
        bad=[one_row(price=[math.inf]),one_row(vega=[-math.inf]),one_row(flags=[True]),one_row(flags=[0.0]),one_row(iv=[True]),
             one_row(iv=['1']),one_row(status=['MAYBE']),one_row(iv=[1.0,2.0]),{**one_row(),'n':1.0},{**one_row(),'extra':1}]
        extra=one_row();extra['models']['bsm']['note']=[0];bad.append(extra)
        for i,res in enumerate(bad):
            with self.subTest(case=i):
                with self.assertRaises(ValueError):result_digest(res)
    def test_run_output_digests_with_nan_as_null(self):
        res=run([(-1,100.0,100.0,0.5,3.0,3.2,0.04,0.012)],CASE)
        self.assertIn(b'"iv":[null]',canonical_result(res));self.assertEqual(len(result_digest(res)),64)

class FlagAndDomainTests(unittest.TestCase):
    def test_boundary_ambiguous_and_flat_vega(self):
        p=bsm_price(0,100.0,100.0,0.5,0.04,0.012,1e-4)
        st,vals,flags=evaluate((0,100.0,100.0,0.5,p,p,0.04,0.012),'bsm',CASE)
        self.assertEqual(st,'OK');self.assertEqual(vals[0],1e-4)
        self.assertTrue(flags&FLAG_BOUNDARY_AMBIGUOUS);self.assertTrue(flags&FLAG_FLAT_VEGA)
        self.assertEqual(evaluate((0,100.0,100.0,0.5,6.0,6.0,0.04,0.012),'bsm',CASE)[2],0)
    def test_model_domain_when_sigma_lo_reaches_the_upper_bound(self):
        params=dataclasses.replace(CASE,kappa_cap=1e-4)
        st,vals,flags=evaluate((0,100.0,100.0,0.5,3.0,3.2,0.04,0.012),'bjs',params)
        self.assertEqual((st,flags),('MODEL_DOMAIN',0));self.assertTrue(all(math.isnan(v) for v in vals))
    def test_model_domain_on_a_non_finite_or_below_band_engine_value(self):
        # Task 7b (spec 3.3 order 5): the order-5 evaluation check replaces the BjS tail condition.
        row=(0,100.0,100.0,0.5,3.0,3.2,0.04,0.012)
        for bad in (math.nan,math.inf,-1e-3):
            with self.subTest(value=bad),mock.patch('optionlab.reference.model_price',lambda *a,bad=bad:bad):
                st,vals,_=evaluate(row,'bjs',CASE)
                self.assertEqual(st,'MODEL_DOMAIN');self.assertTrue(all(math.isnan(v) for v in vals))
    def test_a_value_in_the_rounding_band_is_used_and_flagged(self):
        from optionlab.reference import tau_v, FLAG_ROUNDING_BAND
        from optionlab import models
        S,K,T=100.0,100.0,0.5;tau=tau_v(S,K,T,0.04,0.012);real=models.price
        def banded(model,side,S_,K_,T_,r,q,s,params):return -0.5*tau if s==1e-4 else real(model,side,S_,K_,T_,r,q,s,params)
        with mock.patch('optionlab.reference.model_price',banded):st,vals,flags=evaluate((0,S,K,T,6.0,6.0,0.04,0.012),'bsm',CASE)
        self.assertEqual(st,'OK');self.assertTrue(flags&FLAG_ROUNDING_BAND)
        self.assertFalse(flags&FLAG_BOUNDARY_AMBIGUOUS)     # Amendment D item 3: a band row is compared, not boundary_ambiguous

class BrentCountTests(unittest.TestCase):
    """Task 7b (spec 3.5): the evaluation count of Solver1D::solve and Brent::solveImpl; N_MAX = 201."""
    def test_minimum_counts_at_the_bracket_ends(self):
        self.assertEqual(brent(lambda x:x-1e-4,1e-4,5.0,2.50005)[::4],('OK',1));self.assertEqual(brent(lambda x:x-5.0,1e-4,5.0,2.50005)[::4],('OK',2))
    def test_a_non_converged_solve_makes_exactly_n_max_calls(self):
        # A step at 1e-200 inside [-1e300, 1e300]: bisection needs about 1000 halvings, so 200 evaluations cannot converge.
        calls=[];f=lambda x:(calls.append(x),-1.0 if x<1e-200 else 1.0)[1]
        st,_,_,_,n=brent(f,-1e300,1e300,1.0)
        self.assertEqual((st,n,len(calls),N_MAX),('NOT_CONVERGED',201,201,201))
        calls.clear();self.assertEqual(brent(f,-1e300,1e300,1.0,max_evaluations=5)[::4],('NOT_CONVERGED',6));self.assertEqual(len(calls),6)
    def test_the_root_is_an_evaluated_point_with_the_smaller_residual(self):
        calls={};f=lambda x:calls.setdefault(x,math.atan(x-1.0)*(1.0 if x<1.0 else 1000.0))
        st,root,_,_,_=brent(f,1e-4,5.0,2.50005)
        self.assertEqual(st,'OK');self.assertIn(root,calls);self.assertLess(abs(root-1.0),2e-10)

class NumericTests(unittest.TestCase):
    def test_order_statistics_and_range(self):
        self.assertEqual(median([3.0,1.0,2.0]),2.0);self.assertEqual(median([4.0,1.0]),2.5)
        self.assertEqual((quantile([1.0,2.0,3.0],0.0),quantile([1.0,2.0,3.0],0.5),quantile([1.0,2.0,3.0],1.0)),(1.0,2.0,3.0))
        for p in (-0.1,1.5,math.nan):
            with self.subTest(p=p):
                with self.assertRaises(ValueError):quantile([1.0,2.0],p)
        with self.assertRaises(ValueError):median([])

# Task 7 parked items, added in Task 10.
class ParkedSolverTests(unittest.TestCase):
    """Task 7 parked items: the reduction tie rule (the Illinois safeguard test left with the Illinois solver, Task 7b)."""
    def test_reduction_tie_takes_the_lowest_index(self):
        from optionlab.reference import reduction
        col={'status':['OK','OK','OK','OK','OK'],'iv':[0.3,0.5,0.2,0.5,0.5]}
        red=reduction({'models':{'bsm':col}})['bsm'];self.assertEqual((red['max_iv'],red['max_iv_index']),(0.5,1))
        red=reduction({'models':{'bsm':col}},{'bsm':[1]})['bsm'];self.assertEqual(red['max_iv_index'],3)
