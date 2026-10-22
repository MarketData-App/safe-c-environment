"""EX-18b (Phase 3 addendum Tasks A8 and A9, generic): the window plan, the window attempts, the control pairs, the
extension windows and the window chain of a unit-threshold policy that declares `windows` (project data).

The policy name, the units, the selector shares, the window sizing values and the two control pairs (the base A/A pair and
the candidate control pair) come from the project protocol. These tests declare their own values on a synthetic case and
on the synthetic engine test policy; the framework names no policy, model, control case or record field. bench-demo is the
framework example that runs the window logic in a real smoke (bench selftest and the window smoke of the task report)."""
import argparse, copy, hashlib, json, math, shutil, statistics, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_windows as bw, bench_model as bm, bench_plan as bp, bench_stats as bs, bench_evidence as be, bench_phase3_cli as cli
from evidence import GateError, read_json
from schema_check import validate

POLICY_DOC=bm.load_policy(ROOT)
CELLS=('c-one','c-two','c-three','c-four','c-five','c-six')
CAL=dict(POLICY_DOC['budgets']['estimate_seconds_per_record'])
ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
LARGE={'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':13230}
SMALL={'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256}
SOURCE={'run_id':'5'*32,'observations_sha256':'6'*64}
WDECL={'window_seconds':86400,'cap_headroom':1.2,'cap_step_seconds':600,
       'controls':{'base':{'point':'baseline','variant':'py-optimized'},'candidate':{'point':'baseline','variant':'c-serial','route':'stdio'}}}

def pdoc(**shares):
    d=copy.deepcopy(POLICY_DOC);d['budgets']['estimate_share_per_selector']=dict({'ma':1.0,'mb':0.1},**shares);d['panel_cells']=list(CELLS);return d

def wcase():
    """A synthetic case: a baseline point (the control rows), two full-dataset unit points, one single-record unit point
    on the panel and one slow-row diagnostic point."""
    return {'schema_version':1,'case_id':'window-fixture','version':1,'kind':'function','adapter':'x.adapter:Y','description':'synthetic window fixture',
            'work_unit':'one row','parameters':{},'scopes':['caller','kernel'],'sizes':['tiny','small','medium','large'],'selectors':['all','ma','mb'],
            'variants':[{'id':'py-reference','language':'python','workers':['direct'],'status':'implemented'},
                        {'id':'py-optimized','language':'python','workers':['direct'],'status':'implemented'},
                        {'id':'c-serial','language':'c','workers':['direct'],'status':'implemented','routes':['stdio','shm']}],
            'points':[{'name':'baseline','scope':'caller','size':'small','modes':['warm','cold'],'variants':['py-reference','py-optimized','c-serial'],'class':'primary'},
                      {'name':'unit-ma-full','scope':'caller','size':'large','modes':['warm','cold'],'variants':['py-optimized','c-serial'],'class':'primary',
                       'selector':'ma','unit':'ma/full-dataset'},
                      {'name':'unit-mb-full','scope':'caller','size':'large','modes':['warm'],'variants':['py-reference','py-optimized','c-serial'],'class':'primary',
                       'selector':'mb','unit':'mb/full-dataset'},
                      {'name':'unit-ma-one','scope':'caller','size':'tiny','modes':['warm'],'variants':['py-reference','py-optimized','c-serial'],'class':'primary',
                       'selector':'ma','unit':'ma/single-record','panel':[0,1,2,3,4,5]},
                      {'name':'unit-ma-slowest','scope':'caller','size':'small','modes':['warm'],'variants':['py-optimized'],'class':'exploratory','selector':'ma'}],
            'opportunity_record':None}

UPOL=bm.engine_unit_policy(ROOT)
WPOL=dict(copy.deepcopy(UPOL),name='window-fixture-units',case='window-fixture',units=['ma/full-dataset','mb/full-dataset','ma/single-record'],windows=WDECL)

def obs_row(point,variant,selector,per_unit_s,block=0,panel=None,units=256,**extra):
    """One eligible timed caller observation of a smoke calibration run: one trial of `units` work units whose wall is
    per_unit_s seconds per work unit (a panel trial: `panel` passes of six one-row calls, units = 6 x passes)."""
    o={'trial_id':f'{point}-{variant}-{selector}-b{block:02d}','point':point,'variant':variant,'selector':selector,'workers':'direct','mode':'warm',
       'phase':'caller','scope':'caller','tier':'small','block':block,'warmup':False,'eligible':True,'loops':1,'work_units':units,
       'wall_ns':int(round(per_unit_s*1e9))*units,'cpu_pressure_total':5}
    if panel is not None:o['panel_passes']=panel
    o.update(extra);return o

# EX-18c (EX18b-A03): the measured reference walls of the smoke calibration: the reference batch of each full-dataset unit
# (ma: the added point reference-ma, because unit-ma-full lists no py-reference row; mb: its own unit point) and the
# py-reference panel row of the single-record unit point. The values equal the planning rate x share of pdoc(), so the
# estimates of the plans below stay those of rate x share.
REF_OBS=[obs_row('reference-ma','py-reference','ma',0.14),obs_row('unit-mb-full','py-reference','mb',0.014),
         obs_row('unit-ma-one','py-reference','ma',0.14,panel=5,units=30)]

def decision_plan(case=None,policy=WPOL,doc=None,observations=REF_OBS,**kw):
    return bp.build_plan(case or wcase(),doc or pdoc(),mode='decision',dataset=LARGE,seed=3,envelope=ENV4,calibration=dict(CAL),
                         calibration_source=dict(SOURCE),unit_policy=policy,calibration_observations=observations,**kw)

L=86400-1800
def grp(gid,order,secs,ref=0.0):return {'id':gid,'order':order,'sessions':[{'id':f'{gid}-s{i}','seconds':s} for i,s in enumerate(secs)],'reference':ref}

# ---- A8: the plan part ----
class PlanInputTests(unittest.TestCase):
    def test_a_selector_without_its_approved_share_refuses(self):
        d=pdoc();d['budgets']['share_required']=['mc']
        sess={'session':'s','trials':[{'variant':'py-optimized','selector':'mc','tier':'large','loops':1,'warmup':False,'scope':'caller','mode':'warm'}]}
        with self.assertRaises(GateError) as e:bw.session_seconds(sess,d,None,LARGE)
        self.assertIn('planning share not approved',str(e.exception))
    def test_session_seconds_use_the_share(self):
        sess={'session':'s','trials':[{'variant':'py-reference','selector':'ma','tier':'large','loops':1,'warmup':False,'scope':'caller','mode':'warm'}]}
        one=bw.session_seconds(sess,pdoc(),None,LARGE);two=copy.deepcopy(sess);two['trials'][0]['selector']='mb'
        self.assertLess(bw.session_seconds(two,pdoc(),None,LARGE),one)                 # share 0.1 < share 1.0
        self.assertAlmostEqual(one,13230*CAL['py-reference']*1.0+POLICY_DOC['budgets']['trial_overhead_seconds'])
        warm=copy.deepcopy(sess);warm['trials'].append(dict(sess['trials'][0],warmup=True))
        self.assertAlmostEqual(bw.session_seconds(warm,pdoc(),None,LARGE),2*one)        # a warmup trial counts
    def test_a_panel_trial_counts_six_calls_per_pass(self):
        sess={'session':'s','trials':[{'variant':'py-optimized','selector':'ma','tier':'tiny','loops':1,'warmup':False,'scope':'caller','mode':'warm',
                                        'panel':[0,1,2,3,4,5],'panel_passes':7}]}
        self.assertAlmostEqual(bw.session_seconds(sess,pdoc(),None,LARGE),6*7*CAL['py-optimized']+POLICY_DOC['budgets']['trial_overhead_seconds'])
    def test_reference_seconds_of_a_unit(self):
        self.assertAlmostEqual(bw.reference_seconds('mb/full-dataset',13230,pdoc(),None),13230*CAL['py-reference']*0.1)
        self.assertEqual(bw.reference_seconds('ma/single-record',13230,pdoc(),None),0.0)
    def test_e_ctrl_counts_blocks_and_one_warmup_per_session(self):
        case=wcase();d=pdoc();rows=bw.control_rows(case,WPOL)
        self.assertEqual([(r['point'],r['variant'],r.get('route'),r['tier']) for r in rows],
                         [('control-base-a','py-optimized',None,'small'),('control-base-b','py-optimized',None,'small'),
                          ('control-candidate-a','c-serial','stdio','small'),('control-candidate-b','c-serial','stdio','small')])
        want=lambda s:sum((12+s)*bp.trial_estimate(d,r['variant'],d['sizes'][r['tier']],1,None) for r in rows)
        self.assertAlmostEqual(bw.e_ctrl(d,None,case,WPOL,1),want(1));self.assertAlmostEqual(bw.e_ctrl(d,None,case,WPOL,3),want(3))
        self.assertEqual(bw.control_tier(case,WPOL,'base'),'small')             # the tier of the declared control point
        big=wcase();big['points'][0]['size']='medium';self.assertEqual(bw.control_tier(big,WPOL,'candidate'),'medium')
    def test_calibration_report(self):
        f=POLICY_DOC['controls']['aa_pressure']['factor'];m=POLICY_DOC['controls']['aa_pressure']['min_usec']
        row=lambda point,vals:[{'point':point,'variant':'py-optimized','workers':'direct','mode':'warm','block':b,'warmup':False,'scope':'caller',
                                'cpu_pressure_total':v,'wall_ns':1000,'eligible':True,'work_units':1,'loops':1,'trial_id':f'{point}-{b}'} for b,v in enumerate(vals)]
        obs=row('control-base-a',[m,m,(f+1)*m])+row('unit-ma-full',[m,(f+1)*m])      # median of [m, m, (f+1)m] is m; (f+1)m > f*m and > m
        rep=bw.calibration_report(obs,POLICY_DOC)
        self.assertAlmostEqual(rep['trip_rate']['control-base-a py-optimized xdirect warm'],1/3)
        self.assertIsNone(rep['trip_rate']['unit-ma-full py-optimized xdirect warm'])                   # 2 blocks: test (b) cannot trip
        self.assertIn('fewer than 3 smoke blocks',rep['trip_reason']['unit-ma-full py-optimized xdirect warm'])
        self.assertIn('normal',rep['method']);self.assertEqual(set(rep['control_non_equal']),{'base','candidate'})
        self.assertEqual(rep['control_non_equal'],{'base':None,'candidate':None})                      # no complete pair in these rows
    def test_the_non_equal_rate_of_a_control_pair(self):
        doc=copy.deepcopy(POLICY_DOC);doc['statistics']['bootstrap_resamples']=200
        pair=lambda side,vals:[{'point':f'control-base-{side}','variant':'py-optimized','workers':'direct','mode':'warm','block':b,'warmup':False,'scope':'caller',
                                'cpu_pressure_total':0,'wall_ns':v,'eligible':True,'work_units':1,'loops':1,'trial_id':f'{side}-{b}'} for b,v in enumerate(vals)]
        quiet=pair('a',[1000]*12)+pair('b',[1000]*12)
        noisy=pair('a',[1000]*12)+pair('b',[1000*(1.3 if b%2 else 0.7) for b in range(12)])
        q=bw.calibration_report(quiet,doc,draws=20);n=bw.calibration_report(noisy,doc,draws=20)
        self.assertEqual(q['control_non_equal']['base'],0.0);self.assertGreater(n['control_non_equal']['base'],0.5)
        self.assertIsNone(q['control_non_equal']['candidate'])
        self.assertEqual(bw.calibration_report(noisy,doc,draws=20),n)            # seeded: the same rows give the same rates
    def test_selector_calibration(self):
        obs=[{'trial_id':f't{b}','block':b,'warmup':False,'eligible':True,'work_units':256,'loops':1,'phase':'caller','workers':'direct',
              'variant':'py-reference','selector':'ma','wall_ns':256*140_000_000} for b in range(2)]
        self.assertAlmostEqual(bp.selector_calibration(obs,POLICY_DOC)['ma']['py-reference'],0.140)
        rep=bw.calibration_report(obs,pdoc(),calibration=dict(CAL))
        self.assertAlmostEqual(rep['share_check']['ma']['py-reference'],0.140/(CAL['py-reference']*1.0))
    def test_the_window_smoke_points(self):
        pts=bw.window_smoke_points(wcase(),WPOL,pdoc());names=[p['name'] for p in pts]
        self.assertEqual(names[0],'smoke-caller');self.assertNotIn('smoke-kernel',names);self.assertNotIn('baseline',names)
        units=[p for p in pts if p.get('unit')]
        self.assertEqual(sorted(p['unit'] for p in units),sorted(WPOL['units']))
        self.assertTrue(all(p['blocks']=='smoke' and p['modes']==['warm'] for p in units))
        self.assertEqual({p['unit']:p['size'] for p in units},{'ma/full-dataset':'small','mb/full-dataset':'small','ma/single-record':'tiny'})
        self.assertEqual([p['name'] for p in pts if p['name'].endswith('-slowest')],['unit-ma-slowest'])
        self.assertEqual(next(p for p in pts if p['name']=='unit-ma-slowest')['blocks'],1)
    def test_the_window_smoke_plan_holds_the_control_pairs(self):
        plan=bp.build_plan(wcase(),pdoc(),mode='smoke',dataset=SMALL,seed=3,envelope=ENV4,unit_policy=WPOL)
        self.assertEqual(plan['policy'],'window-fixture-units');self.assertEqual((plan['memory'],plan.get('capacity')),([],None))
        ctl=[t for s in plan['sessions'] for t in s['trials'] if t['point'].startswith('control-')]
        self.assertEqual(sorted({t['point'] for t in ctl}),['control-base-a','control-base-b','control-candidate-a','control-candidate-b'])
        for point in {t['point'] for t in ctl}:
            with self.subTest(point=point):
                self.assertEqual(sorted(t['block'] for t in ctl if t['point']==point and not t['warmup']),list(range(12)))
        self.assertTrue(all(t['mode']=='warm' and t['tier']=='small' for t in ctl))
        self.assertEqual({t.get('route') for t in ctl if t['point'].startswith('control-candidate')},{'stdio'})
        self.assertEqual(bench.plan_digest(plan),plan['plan_id'])
    def test_a_decision_plan_needs_a_calibration_and_a_windows_declaration(self):
        with self.assertRaises(GateError) as e:bp.build_plan(wcase(),pdoc(),mode='decision',dataset=LARGE,seed=3,envelope=ENV4,unit_policy=WPOL)
        self.assertIn('needs a calibration',str(e.exception))
        with self.assertRaises(GateError) as e:decision_plan(policy={k:v for k,v in WPOL.items() if k!='windows'})
        self.assertIn('declares no windows',str(e.exception))
        with self.assertRaises(GateError) as e:decision_plan(policy=dict(WPOL,case='another-case'))
        self.assertIn('policy-case-mismatch',str(e.exception))
        with self.assertRaises(GateError) as e:decision_plan(observations=None)              # EX-18c: the measured walls come from the calibration run
        self.assertIn('observations of its calibration run',str(e.exception))
    def test_the_plan_command_refuses_a_window_plan_without_a_calibration(self):
        ns=argparse.Namespace(project=None,case='bench-control-spin',mode='decision',policy='window-fixture-units',dataset='synthetic:large',calibrate=None,
                              format='json',matrix=None,repair=None)
        out=io_quiet(bench.plan_cmd,ROOT,ns);self.assertEqual(out[0],1);self.assertIn('needs a calibration',json.dumps(out[1]))

def io_quiet(fn,root,ns):
    """(exit code, last JSON row) of one bench operation (bench._quiet), with the policy lookup of the namespace patched to the
    synthetic window policy (no project declares it)."""
    with mock.patch('bench_model.load_decision_policy',return_value=dict(WPOL,case=ns.case)):
        return bench._quiet(fn,root,ns)

class DecisionPlanTests(unittest.TestCase):
    def test_the_plan_keeps_the_unit_and_diagnostic_points_only(self):
        plan=decision_plan()
        self.assertEqual(sorted({s['point'] for s in plan['sessions']}),['unit-ma-full','unit-ma-one','unit-ma-slowest','unit-mb-full'])
        self.assertEqual((plan['memory'],plan.get('capacity')),([],None));self.assertEqual(plan['policy'],'window-fixture-units')
        self.assertTrue(all(t['unit']==s['trials'][0]['unit'] for s in plan['sessions'] if s['point']!='unit-ma-slowest' for t in s['trials']))
        self.assertEqual(bench.plan_digest(plan),plan['plan_id'])
    def test_the_window_plan_is_recorded(self):
        plan=decision_plan();w=plan['windows']
        self.assertEqual([x['id'] for x in w],['1a']);self.assertLessEqual(w[0]['estimate'],86400)
        self.assertEqual(sorted(w[0]['units']),sorted(WPOL['units']));self.assertEqual(w[0]['sessions'],[s['session'] for s in plan['sessions']])
        self.assertEqual(plan['e_ctrl'],bw.e_ctrl(pdoc(),dict(CAL),wcase(),WPOL,len(plan['sessions'])))
        self.assertEqual([x['window'] for x in plan['look2']],['1a']);self.assertLessEqual(plan['look2'][0]['estimate'],w[0]['estimate'])
        self.assertEqual(plan['caps_proposed'],{'synthetic':bw.cap(w[0]['estimate'],1.2,600)})
        kinds={p['kind'] for p in w[0]['parts']};self.assertEqual(kinds,{'unit','single-record','diagnostics'})
        ma=next(p for p in w[0]['parts'] if p['group']=='ma/full-dataset')
        self.assertAlmostEqual(ma['reference'],13230*CAL['py-reference']*1.0);self.assertEqual(w[0]['blocks']['ma/full-dataset'],list(range(12)))
        self.assertAlmostEqual(w[0]['estimate'],plan['e_ctrl']+sum(p['estimate'] for p in w[0]['parts']))
        self.assertIn('calibration_report',plan)                        # EX-18c (EX18b-A03, A06): every window plan reads its calibration run
    def test_the_estimate_sums_its_sessions_and_references(self):
        plan=decision_plan();d=pdoc();parts={p['group']:p for p in plan['windows'][0]['parts']}
        mb=[s for s in plan['sessions'] if s['point']=='unit-mb-full']
        self.assertAlmostEqual(parts['mb/full-dataset']['estimate'],sum(bw.session_seconds(s,d,dict(CAL),LARGE) for s in mb)+13230*CAL['py-reference']*0.1)
    def test_the_calibration_report_is_bound_in_the_plan_identity(self):
        # EX-18c (EX18b-A06): the report is part of the plan id, and bench run --plan re-derives it from the bound calibration run
        press=[obs_row('control-base-a','py-optimized','all',0.001,block=b,cpu_pressure_total=v) for b,v in enumerate((1,1,10**6))]
        plain=decision_plan();loud=decision_plan(observations=REF_OBS+press)
        self.assertIn('trip_rate',loud['calibration_report']);self.assertNotEqual(loud['calibration_report'],plain['calibration_report'])
        self.assertNotEqual(loud['plan_id'],plain['plan_id'])
        for p in (plain,loud):self.assertEqual(bench.plan_digest(p),p['plan_id'])
        edited=copy.deepcopy(loud);edited['calibration_report']['trip_rate']={}
        self.assertNotEqual(bench.plan_digest(edited),loud['plan_id'])                # an edit of the report alone: the plan id differs
        edited['plan_id']=bench.plan_digest(edited);loud['project_dir']=None;edited['project_dir']=None
        with mock.patch('bench_plan.calibration_inputs',return_value=(dict(CAL),dict(SOURCE),REF_OBS+press)):
            bench.verify_written_plan(wcase(),pdoc(),loud,ENV4,None,None,root=ROOT,unit_policy=WPOL)
            with self.assertRaises(GateError) as e:bench.verify_written_plan(wcase(),pdoc(),edited,ENV4,None,None,root=ROOT,unit_policy=WPOL)
        self.assertIn('differs from the plan',str(e.exception))                        # an edit with a recomputed plan id: the re-derived report differs
    def test_the_decision_cap_of_the_rule_policies_is_not_the_window_cap(self):
        doc=pdoc();doc['budgets']['decision_cap_seconds']=1000        # a cap that the plan is above (the policy file holds 28,800)
        plan=decision_plan(doc=doc);self.assertGreater(plan['estimate_seconds'],1000)
        self.assertLessEqual(max(w['estimate'] for w in plan['windows']),86400)
        plain=wcase()
        with self.assertRaises(GateError) as e:bp.build_plan(plain,doc,mode='decision',dataset=LARGE,seed=3,envelope=ENV4,calibration=dict(CAL))
        self.assertIn('decision cap',str(e.exception))                  # the rule-policy plan of the same case keeps its cap
        self.assertAlmostEqual(plan['estimate_seconds'],round(sum(w['estimate'] for w in plan['windows']),1),places=1)
    def test_plan_refusals(self):
        with self.assertRaises(bw.PlanRefusal) as e:decision_plan(policy=dict(WPOL,windows=dict(WDECL,window_seconds=3600)),doc=pdoc(ma=2.0))
        self.assertEqual(e.exception.reason,'window-cap-infeasible');self.assertTrue(e.exception.estimates)
        with self.assertRaises(bw.PlanRefusal) as e:decision_plan(doc=pdoc(ma=500.0))
        self.assertEqual(e.exception.reason,'session-cap-infeasible')
        capped=dict(WPOL,windows=dict(WDECL,caps_seconds={'synthetic':600,'local':600}))
        with self.assertRaises(bw.PlanRefusal) as e:decision_plan(policy=capped)
        self.assertEqual(e.exception.reason,'owner-cap-exceeded')
        decision_plan(policy=dict(WPOL,windows=dict(WDECL,caps_seconds={'synthetic':86400,'local':600})))      # the cap of the plan's dataset decides
    def test_a_written_window_plan_is_verified_like_any_plan(self):
        plan=decision_plan();plan['project_dir']=None
        with mock.patch('bench_plan.calibration_inputs',return_value=(dict(CAL),dict(SOURCE),REF_OBS)):    # EX-18c: one read gives the rates and the rows
            bench.verify_written_plan(wcase(),pdoc(),plan,ENV4,None,None,root=ROOT,unit_policy=WPOL)
            edited=copy.deepcopy(plan);edited['windows'][0]['estimate']=1.0;edited['plan_id']=bench.plan_digest(edited)
            with self.assertRaises(GateError):bench.verify_written_plan(wcase(),pdoc(),edited,ENV4,None,None,root=ROOT,unit_policy=WPOL)
            with self.assertRaises(GateError):bench.verify_written_plan(wcase(),pdoc(),plan,ENV4,None,None,root=ROOT)     # a window plan needs its policy

def crafted(sessions_by_unit,diag=()):
    """A built-plan-like body whose sessions hold py-reference trials at the large size (share ma 1.0: 1,854 s each)."""
    sess=[]
    for unit,counts in sessions_by_unit:
        point='unit-'+unit.split('/')[0]+('-full' if unit.endswith('full-dataset') else '-one');first=0
        for i,n in enumerate(counts):
            sess.append({'session':f'{point}-s{len(sess):02d}','point':point,'trials':[{'trial_id':f'{point}-{i}-{k}','variant':'py-reference','selector':unit.split('/')[0],
                         'tier':'large','loops':1,'warmup':False,'unit':unit,'block':first+k,'scope':'caller','mode':'warm','workers':'direct'} for k in range(n)]})
            first+=n
    for n in diag:
        sess.append({'session':f'unit-ma-slowest-s{len(sess):02d}','point':'unit-ma-slowest','trials':[{'trial_id':f'd{len(sess)}-{k}','variant':'py-optimized','selector':'ma',
                     'tier':'small','loops':1,'warmup':False,'block':k,'scope':'caller','mode':'warm','workers':'direct'} for k in range(n)]})
    return {'sessions':sess,'dataset':LARGE,'plan_id':'7'*32}

class WindowSplitOfAPlanTests(unittest.TestCase):
    def test_a_plan_above_one_window_is_split_by_its_groups_and_session_parts(self):
        plan=crafted([('ma/full-dataset',[5]*10),('mb/full-dataset',[3])],diag=[1])
        out=bw.window_plan(plan,wcase(),WPOL,pdoc(mb=1.0),dict(CAL))
        ids=[w['id'] for w in out['windows']];self.assertEqual(ids,['1a','1b'])
        self.assertTrue(all(w['estimate']<=86400 for w in out['windows']))
        split=[p for w in out['windows'] for p in w['parts'] if p['group']=='ma/full-dataset']
        self.assertGreater(len(split),1)                                 # the unit is cut into session parts
        self.assertEqual(sorted(s for p in split for s in p['sessions']),sorted(s['session'] for s in plan['sessions'] if s['point']=='unit-ma-full'))
        self.assertTrue(all(p['reference']>0 for p in split))           # every part of a full-dataset unit holds its reference batch
        for w in out['windows']:
            with self.subTest(window=w['id']):self.assertLessEqual(bw.e_ctrl(pdoc(mb=1.0),dict(CAL),wcase(),WPOL,len(w['sessions'])),out['e_ctrl'])
        self.assertEqual([len(w['sessions']) for w in out['windows']],[9,3])
        self.assertEqual(out['windows'][0]['blocks'],{'ma/full-dataset':list(range(45))})      # the crafted unit numbers its blocks 0-4 per session
        self.assertEqual([x['window'] for x in out['look2']],['1a','1b'])
        self.assertTrue(all(x['estimate']<=w['estimate'] for x,w in zip(out['look2'],out['windows'])))
    def test_the_control_blocks_of_a_window_are_spread_over_its_sessions(self):
        self.assertEqual(bw.control_assignment(1,12),[list(range(12))])
        self.assertEqual(bw.control_assignment(3,12),[[0,1,2,3],[4,5,6,7],[8,9,10,11]])
        self.assertEqual(bw.control_assignment(5,12),[[0,1],[2,3,4],[5,6],[7,8,9],[10,11]])
        self.assertEqual(sum(bw.control_assignment(16,12),[]),list(range(12)))
    def test_a_session_with_its_control_trials_above_the_cap_refuses(self):
        plan=crafted([('ma/full-dataset',[5])])
        with self.assertRaises(bw.PlanRefusal) as e:bw.window_plan(plan,wcase(),WPOL,pdoc(ma=1.16),dict(CAL))     # 10,753 s alone, 10,889 s with its controls
        self.assertEqual(e.exception.reason,'session-cap-infeasible')
        bw.window_plan(plan,wcase(),WPOL,pdoc(ma=1.1),dict(CAL))                 # 10,333 s with its controls: within the cap
    def test_more_windows_than_the_record_holds_refuse(self):
        gs=[grp(f'g{i}',i,[80000.0]) for i in range(17)]
        with self.assertRaises(bw.PlanRefusal) as e:bw.check_window_count(bw.split_windows(gs,1800.0))
        self.assertEqual(e.exception.reason,'window-cap-infeasible')
        bw.check_window_count(bw.split_windows(gs[:16],1800.0))

# ---- A9: the run part ----
POLICY={'controls':{'aa_pressure':{'factor':3.0,'min_usec':1000}}}
def att(w,a,status,reason=None,sha=None,extends=None):return {'window':w,'attempt':a,'status':status,'reason':reason,'record_sha256':sha or f'{w}{a}'.ljust(64,'0'),'extends':extends}

class AttemptTests(unittest.TestCase):
    def test_attempt_outcomes(self):
        quiet={'r':[100]*12};loud={'r':[100]*11+[10000]}
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL','echo':'EQUAL'},{'aa':quiet,'echo':quiet,'rows':quiet},POLICY),('PASS',None))
        self.assertEqual(bw.attempt_outcome({'aa':'INCONCLUSIVE','echo':'EQUAL'},{'aa':loud,'echo':quiet,'rows':quiet},POLICY),('BLOCKED','window-pressure'))
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL','echo':'EQUAL'},{'aa':quiet,'echo':quiet,'rows':loud},POLICY),('BLOCKED','window-pressure'))
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL','echo':'SLOWER'},{'aa':quiet,'echo':quiet,'rows':quiet},POLICY),('BLOCKED','window-control-noise'))
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL','echo':'EQUAL'},{'aa':quiet,'echo':{'r':[100]*11+[None]},'rows':quiet},POLICY),('BLOCKED','window-pressure'))
    def test_a_row_with_one_block_cannot_trip_the_row_test(self):
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL'},{'aa':{'r':[100]*12},'rows':{'one':[10**9]}},POLICY),('PASS',None))
    def test_a_pressured_row_of_an_equal_control_pair_passes(self):
        # H15.2 (a) needs a pair result other than EQUAL; test (b) reads the other rows of the attempt only
        loud={'r':[100]*11+[10000]}
        self.assertEqual(bw.attempt_outcome({'aa':'EQUAL'},{'aa':loud,'rows':{}},POLICY),('PASS',None))
        self.assertEqual(bw.attempt_outcome({'aa':'FASTER'},{'aa':loud,'rows':{}},POLICY),('BLOCKED','window-pressure'))
    def test_the_control_classifier_is_the_compare_classifier(self):
        base={b:1000.0 for b in range(12)}
        self.assertEqual(bw.control_result(base,dict(base),POLICY_DOC),'EQUAL')
        self.assertEqual(bw.control_result(base,{b:3000.0 for b in range(12)},POLICY_DOC),'SLOWER')
        self.assertEqual(bw.control_result(base,{b:1000.0 for b in range(11)},POLICY_DOC),'INCONCLUSIVE')
    def obs(self,point,walls,pressure=10,variant='py-optimized',route=None,unit=None):
        return [{'trial_id':f'{point}-{b}','point':point,'block':b,'warmup':False,'eligible':True,'scope':'caller','mode':'warm','variant':variant,'workers':'direct',
                 'route':route,'tier':'medium','work_units':1,'loops':1,'wall_ns':w,'cpu_pressure_total':pressure,**({'unit':unit} if unit else {})} for b,w in enumerate(walls)]
    def test_the_outcome_of_a_recorded_attempt(self):
        rows=self.obs('control-base-a',[1000]*12)+self.obs('control-base-b',[1000]*12)+self.obs('control-candidate-a',[500]*12,variant='c-serial',route='stdio')
        rows+=self.obs('control-candidate-b',[500]*12,variant='c-serial',route='stdio')+self.obs('unit-ma-full',[9000]*12,unit='ma/full-dataset')
        out=bw.run_attempt_outcome('VALID',rows,POLICY_DOC)
        self.assertEqual(out,{'status':'PASS','reason':None,'controls':{'base':'EQUAL','candidate':'EQUAL'}})
        noisy=[dict(o,wall_ns=o['wall_ns']*(3 if o['block']%2 else 1)) if o['point']=='control-candidate-b' else o for o in rows]
        self.assertEqual(bw.run_attempt_outcome('VALID',noisy,POLICY_DOC)['status'],'BLOCKED')
        self.assertEqual(bw.run_attempt_outcome('VALID',noisy,POLICY_DOC)['reason'],'window-control-noise')
        unread=[dict(o,cpu_pressure_total=None) if o['trial_id']=='unit-ma-full-3' else o for o in rows]
        self.assertEqual(bw.run_attempt_outcome('VALID',unread,POLICY_DOC)['reason'],'window-pressure')
        self.assertEqual(bw.run_attempt_outcome('INVALID_EXPERIMENT',rows,POLICY_DOC)['status'],'FAIL')
        self.assertEqual(bw.run_attempt_outcome('BLOCKED',[],POLICY_DOC),{'status':'BLOCKED','reason':'window-pressure','controls':{'base':None,'candidate':None}})
        self.assertEqual(bw.run_attempt_outcome('VALID',[o for o in rows if o['point']!='control-base-b'],POLICY_DOC)['reason'],'window-pressure')    # a missing control row: unreadable

class ChainTests(unittest.TestCase):                    # Amendment H15.2 chain tests
    def chain(self,attempts,exhausted=(),files=None,positions=None):
        for k,a in enumerate(attempts):a.setdefault('seq',k)
        sup=[a for a in attempts if a['status']=='BLOCKED']
        pos=positions if positions is not None else {a['window']:a['record_sha256'] for a in attempts if a['status'] in ('PASS','FAIL')}
        return {'attempts':attempts,'superseded':sup,'superseded_files':files if files is not None else {a['record_sha256']:True for a in sup},
                'exhausted':list(exhausted),'positions':pos}
    def test_valid_chains(self):
        for att_list in ([att('1a',1,'PASS')],[att('1a',1,'BLOCKED','window-pressure'),att('1a',2,'PASS')],
                         [att('1a',1,'BLOCKED','window-pressure'),att('1a',2,'BLOCKED','window-pressure'),att('1a',3,'PASS')]):
            self.assertEqual(bw.chain_problems(self.chain(att_list),['1a'],set()),[])
    def test_exhausted_window_then_a_pass_window(self):
        a=[att('1a',i,'BLOCKED','window-pressure') for i in (1,2,3)]+[att('1b',1,'PASS')]
        self.assertEqual(bw.chain_problems(self.chain(a,['1a']),['1a','1b'],set()),[])
    def test_three_noise_attempts_are_control_fail(self):
        a=[att('1a',i,'BLOCKED','window-control-noise') for i in (1,2,3)]
        self.assertTrue(bw.chain_state(self.chain(a,['1a']))['control_fail'])
        self.assertFalse(bw.chain_state(self.chain([att('1a',i,'BLOCKED','window-pressure') for i in (1,2,3)],['1a']))['control_fail'])
    def test_refused_chains(self):
        bad={'attempt after a PASS':[att('1a',1,'PASS'),att('1a',2,'BLOCKED','window-pressure')],
             'fourth attempt':[att('1a',i,'BLOCKED','window-pressure') for i in (1,2,3,4)],
             'exhausted with fewer than 3':[att('1a',1,'BLOCKED','window-pressure'),att('1a',2,'BLOCKED','window-pressure')],
             'gap':[att('1a',1,'BLOCKED','window-pressure'),att('1a',3,'PASS')],
             'missing window':[att('1b',1,'PASS')],
             'extension of an exhausted window':[att('1a',i,'BLOCKED','window-pressure') for i in (1,2,3)]+[att('2a',1,'PASS')],
             'an open window':[att('1a',1,'BLOCKED','window-pressure')]}
        for name,a in bad.items():
            with self.subTest(name):
                ex=['1a'] if name.startswith('exhausted') or name.startswith('extension') else []
                self.assertNotEqual(bw.chain_problems(self.chain(a,ex),['1a'],{'1a'}),[])
    def test_extends_names_the_nearest_earlier_pass(self):
        a=[att('1a',1,'PASS',sha='a'*64),att('1b',1,'PASS',extends='b'*64)]
        self.assertIn('extends',' '.join(bw.chain_problems(self.chain(a),['1a','1b'],set())))
        ok=[att('1a',1,'PASS',sha='a'*64),att('1b',1,'PASS',extends='a'*64)]
        self.assertEqual(bw.chain_problems(self.chain(ok),['1a','1b'],set()),[])
    def test_valid_exhausted_extension(self):
        a=[att('1a',1,'PASS',sha='a'*64)]+[att('2a',i,'BLOCKED','window-pressure') for i in (1,2,3)]
        self.assertEqual(bw.chain_problems(self.chain(a,['2a']),['1a'],{'1a'}),[])
    def test_valid_extension_names_its_window(self):
        a=[att('1a',1,'PASS',sha='a'*64),att('1b',1,'PASS',sha='b'*64,extends='a'*64),att('2a',1,'PASS',sha='c'*64,extends='b'*64)]
        self.assertEqual(bw.chain_problems(self.chain(a),['1a','1b'],{'1a'}),[])
        self.assertNotEqual(bw.chain_problems(self.chain(a),['1a','1b'],{'1b'}),[])           # 1a has no triggered unit: no 2a
    def test_valid_exhausted_window_alone(self):                         # PB-L4
        a=[att('1a',i,'BLOCKED','window-pressure') for i in (1,2,3)]
        self.assertEqual(bw.chain_problems(self.chain(a,['1a']),['1a'],set()),[])
    def test_exhausted_id_with_a_pass_is_refused(self):
        a=[att('1a',i,'BLOCKED','window-pressure') for i in (1,2)]+[att('1a',3,'PASS',sha='a'*64)]
        self.assertNotEqual(bw.chain_problems(self.chain(a,['1a']),['1a'],set()),[])
    def test_extends_that_skips_a_pass_window_is_refused(self):
        a=[att('1a',1,'PASS',sha='a'*64),att('1b',1,'PASS',sha='b'*64,extends='a'*64),att('1c',1,'PASS',sha='c'*64,extends='a'*64)]
        self.assertIn('extends',' '.join(bw.chain_problems(self.chain(a),['1a','1b','1c'],set())))
    def test_a_failed_run_is_a_final_position(self):
        a=[att('1a',1,'FAIL','run-invalid',sha='a'*64),att('1b',1,'PASS',sha='b'*64,extends='a'*64)]
        self.assertEqual(bw.chain_problems(self.chain(a),['1a','1b'],set()),[])
        self.assertNotEqual(bw.chain_problems(self.chain(a+[att('2a',1,'PASS',extends='b'*64)]),['1a','1b'],{'1a'}),[])   # no extension of a failed window
    def test_more_refused_chains(self):
        p1=att('1a',1,'BLOCKED','window-pressure',sha='1'*64);p2=att('1a',2,'PASS',sha='2'*64)
        cases={'missing or altered superseded file':self.chain([p1,p2],files={'1'*64:False}),
               'position is not the latest attempt':self.chain([dict(p1),dict(p2)],positions={'1a':'1'*64}),
               'reordered window ids':self.chain([att('1b',1,'PASS',sha='b'*64,extends=None),att('1a',1,'PASS',sha='a'*64)]),
               'extends names a BLOCKED attempt':self.chain([dict(p1),dict(p2),att('1b',1,'PASS',sha='b'*64,extends='1'*64)])}
        for name,ch in cases.items():
            with self.subTest(name):self.assertNotEqual(bw.chain_problems(ch,['1a','1b'] if '1b' in {x['window'] for x in ch['attempts']} else ['1a'],set()),[])

class MovedFromTask19Tests(unittest.TestCase):          # base Task 19 tests, verbatim except the module path and the unit names
    ID={'bench_profile_sha256':'a'*64,'cpuset_size':4,'smt_siblings':[],'image_id':'sha256:'+'b'*64,'policy_sha256':'c'*64,'case_version':2,
        'source_identity':'d'*64,'native':{'bd-kernel':'e'*64},'datasets':{'primary':'f'*64,'panel':'0'*64}}
    def test_identical_windows_match(self):self.assertEqual(bw.windows_match(self.ID,copy.deepcopy(self.ID)),[])
    def test_each_key_breaks_the_match(self):
        for k in self.ID:
            other=copy.deepcopy(self.ID);other[k]='changed' if not isinstance(self.ID[k],(int,list,dict)) else ({'x':1} if isinstance(self.ID[k],dict) else 99)
            self.assertEqual(bw.windows_match(self.ID,other),[k])
    def test_extension_only_for_triggered_units(self):
        rec={'units':[{'unit':'ma/full-dataset','extension':{'trigger':True}},{'unit':'mb/full-dataset','extension':{'trigger':False}}]}
        plan={'cells':{'ma/full-dataset':['py-optimized:direct:warm','py-optimized:direct:cold'],'mb/full-dataset':['py-optimized:direct:warm']}}
        ext=bw.extension_plan(rec,plan);self.assertEqual(sorted(ext['units']),['ma/full-dataset']);self.assertEqual(ext['blocks'],list(range(12,24)))
        self.assertEqual(ext['cells']['ma/full-dataset'],plan['cells']['ma/full-dataset'])
    def test_b09_extension_sub_checks(self):
        rec={'units':[{'unit':'ma/full-dataset','extension':{'trigger':False}}]}
        self.assertIn('extension without trigger',bw.check_extension(rec,{'units':['ma/full-dataset'],'blocks':list(range(12,24))},self.ID,self.ID))
        rec2={'units':[{'unit':'ma/full-dataset','extension':{'trigger':True}}]}
        self.assertIn('discarded blocks',bw.check_extension(rec2,{'units':['ma/full-dataset'],'blocks':list(range(12,23))},self.ID,self.ID))
        self.assertIn('window envelope mismatch',bw.check_extension(rec2,{'units':['ma/full-dataset'],'blocks':list(range(12,24))},self.ID,dict(self.ID,image_id='x')))
        self.assertEqual(bw.check_extension(rec2,{'units':['ma/full-dataset'],'blocks':list(range(12,24))},self.ID,self.ID),[])
    def test_no_trigger_no_extension(self):
        self.assertIsNone(bw.extension_plan({'units':[{'unit':'ma/full-dataset','extension':{'trigger':False}}]},{'cells':{}}))
    def test_b09_sub_checks_are_wired(self):
        src=(ROOT/'tools/bench.py').read_text();self.assertIn('bench_windows.check_extension(',src)

class SplitUnitExtensionTests(unittest.TestCase):       # PB-05: a unit split across 1a (blocks 0-7) and 1b (blocks 8-11)
    REC={'units':[{'unit':'ma/full-dataset','extension':{'trigger':True}}]}
    PLAN={'cells':{'ma/full-dataset':['py-optimized:direct:warm']}}
    def test_each_extension_continues_the_index_sequence(self):
        a=bw.extension_plan(self.REC,self.PLAN,{'ma/full-dataset':list(range(0,8))});b=bw.extension_plan(self.REC,self.PLAN,{'ma/full-dataset':list(range(8,12))})
        self.assertEqual((a['blocks']['ma/full-dataset'],b['blocks']['ma/full-dataset']),(list(range(12,20)),list(range(20,24))))
        self.assertEqual(sorted(a['blocks']['ma/full-dataset']+b['blocks']['ma/full-dataset']),list(range(12,24)))     # no duplicates
    def test_check_extension_uses_the_part(self):
        ID=MovedFromTask19Tests.ID
        self.assertEqual(bw.check_extension(self.REC,{'units':['ma/full-dataset'],'blocks':list(range(20,24))},ID,ID,{'ma/full-dataset':list(range(8,12))}),[])
        self.assertIn('discarded blocks',bw.check_extension(self.REC,{'units':['ma/full-dataset'],'blocks':list(range(12,24))},ID,ID,{'ma/full-dataset':list(range(8,12))}))

class WindowRunPlanTests(unittest.TestCase):
    def test_the_run_plan_of_a_window_holds_its_sessions_and_the_control_pairs(self):
        plan=decision_plan();sub=bw.window_run_plan(plan,'1a',wcase(),WPOL,pdoc())
        self.assertEqual(sub['window'],{'id':'1a','look':1,'plan_id':plan['plan_id']});self.assertEqual(sub['plan_id'],bench.plan_digest(sub))
        self.assertEqual((sub['mode'],sub['memory'],sub['policy'],sub['case']),('decision',[],'window-fixture-units','window-fixture'))
        own=[t for s in sub['sessions'] for t in s['trials'] if not t['point'].startswith('control-')]
        self.assertEqual(sorted(t['trial_id'] for t in own),sorted(t['trial_id'] for s in plan['sessions'] for t in s['trials']))
        ctl=[t for s in sub['sessions'] for t in s['trials'] if t['point'].startswith('control-')]
        for point in ('control-base-a','control-base-b','control-candidate-a','control-candidate-b'):
            with self.subTest(point=point):
                self.assertEqual(sorted(t['block'] for t in ctl if t['point']==point and not t['warmup']),list(range(12)))
                self.assertEqual(sum(1 for t in ctl if t['point']==point and t['warmup']),len(sub['sessions']))      # one warmup per session
        ids=[t['trial_id'] for s in sub['sessions'] for t in s['trials']];self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(sub,bw.window_run_plan(plan,'1a',wcase(),WPOL,pdoc()))           # deterministic
        self.assertEqual(sub['estimate_seconds'],plan['windows'][0]['estimate'])
        with self.assertRaises(GateError):bw.window_run_plan(plan,'1b',wcase(),WPOL,pdoc())
    def test_the_extension_run_plan_holds_the_triggered_units_with_their_extension_blocks(self):
        plan=decision_plan();sub=bw.extension_run_plan(plan,'1a',['ma/full-dataset'],wcase(),WPOL,pdoc())
        self.assertEqual(sub['window'],{'id':'2a','look':2,'plan_id':plan['plan_id']})
        own=[t for s in sub['sessions'] for t in s['trials'] if not t['point'].startswith('control-')]
        self.assertEqual({t['point'] for t in own},{'unit-ma-full'});self.assertTrue(all(t['trial_id'].startswith('x') for t in own))
        look1=[t for s in plan['sessions'] if s['point']=='unit-ma-full' for t in s['trials']]
        self.assertEqual(sorted(t['block'] for t in own if not t['warmup']),sorted(t['block']+12 for t in look1 if not t['warmup']))
        self.assertEqual(sum(1 for t in own if t['warmup']),sum(1 for t in look1 if t['warmup']))      # one warmup set per session
        self.assertEqual(sorted({t['point'] for s in sub['sessions'] for t in s['trials'] if t['point'].startswith('control-')}),
                         ['control-base-a','control-base-b','control-candidate-a','control-candidate-b'])
        with self.assertRaises(GateError):bw.extension_run_plan(plan,'1a',['zz/full-dataset'],wcase(),WPOL,pdoc())
        with self.assertRaises(GateError):bw.extension_run_plan(plan,'1a',[],wcase(),WPOL,pdoc())

def run_record(root,run_id,window,attempt,status,reason=None,extends=None,plan_id='7'*32,created='2026-10-15T10:00:00+00:00',identity=None,**extra):
    """One recorded window attempt (run.json with its run record digest) under root/artifacts/bench/<run_id>."""
    d=Path(root)/'artifacts/bench'/run_id;d.mkdir(parents=True)
    run={'run_id':run_id,'created_at':created,'window':window,'attempt':attempt,'window_plan_id':plan_id,'extends':extends,
         'attempt_outcome':{'status':status,'reason':reason,'controls':{'base':'EQUAL','candidate':'EQUAL'}},
         'envelope_identity':identity or dict(MovedFromTask19Tests.ID),**extra}
    run['run_record_sha256']=be.run_record_sha256(run);(d/'run.json').write_text(json.dumps(run));return run

class RecordedChainTests(unittest.TestCase):
    def test_the_chain_of_a_plan_version_from_its_run_records(self):
        with tempfile.TemporaryDirectory() as t:
            a=run_record(t,'a'*32,'1a',1,'BLOCKED','window-pressure',created='2026-10-15T10:00:00+00:00')
            b=run_record(t,'b'*32,'1a',2,'PASS',created='2026-10-15T11:00:00+00:00')
            c=run_record(t,'c'*32,'1b',1,'PASS',extends=b['run_record_sha256'],created='2026-10-15T12:00:00+00:00')
            run_record(t,'d'*32,'1a',1,'PASS',plan_id='8'*32)                       # another plan version
            ch=bw.chain(Path(t),'7'*32)
            self.assertEqual([(x['window'],x['attempt'],x['status']) for x in ch['attempts']],[('1a',1,'BLOCKED'),('1a',2,'PASS'),('1b',1,'PASS')])
            self.assertEqual(ch['positions'],{'1a':b['run_record_sha256'],'1b':c['run_record_sha256']})
            self.assertEqual([x['record_sha256'] for x in ch['superseded']],[a['run_record_sha256']]);self.assertEqual(ch['superseded_files'],{a['run_record_sha256']:True})
            self.assertEqual(bw.chain_problems(ch,['1a','1b'],set()),[])
            p=Path(t)/'artifacts/bench'/('a'*32)/'run.json';doc=json.loads(p.read_text());doc['attempt_outcome']['reason']='window-control-noise';p.write_text(json.dumps(doc))
            ch=bw.chain(Path(t),'7'*32);self.assertEqual(ch['superseded_files'],{a['run_record_sha256']:False})
            self.assertNotEqual(bw.chain_problems(ch,['1a','1b'],set()),[])
    def test_the_attempt_rules_of_bench_run(self):
        plan={'plan_id':'7'*32,'windows':[{'id':'1a'},{'id':'1b'}]}
        with tempfile.TemporaryDirectory() as t:
            ch=lambda:bw.chain(Path(t),'7'*32)
            self.assertIsNone(bw.window_refusal(ch(),plan,'1a'));self.assertEqual(bw.next_attempt(ch(),'1a'),1)
            self.assertIn('runs after',bw.window_refusal(ch(),plan,'1b'))
            self.assertIn('not a window',bw.window_refusal(ch(),plan,'1c'))
            first=run_record(t,'a'*32,'1a',1,'BLOCKED','window-pressure',created='2026-10-15T10:00:00+00:00')
            self.assertIsNone(bw.window_refusal(ch(),plan,'1a'));self.assertEqual(bw.next_attempt(ch(),'1a'),2)
            self.assertIsNone(bw.extends_of(ch(),plan,'1a'))
            ok=run_record(t,'b'*32,'1a',2,'PASS',created='2026-10-15T11:00:00+00:00')
            self.assertIn('final attempt',bw.window_refusal(ch(),plan,'1a'));self.assertIsNone(bw.window_refusal(ch(),plan,'1b'))
            self.assertEqual(bw.extends_of(ch(),plan,'1b'),ok['run_record_sha256'])
            for k in (1,2,3):run_record(t,f'{k}'*32,'1b',k,'BLOCKED','window-pressure',created=f'2026-10-15T1{2+k}:00:00+00:00')
            self.assertIn('3 attempts',bw.window_refusal(ch(),plan,'1b'))
    def test_three_noise_attempts_refuse_every_later_attempt(self):
        plan={'plan_id':'7'*32,'windows':[{'id':'1a'},{'id':'1b'}]}
        with tempfile.TemporaryDirectory() as t:
            for k in (1,2,3):run_record(t,f'{k}'*32,'1a',k,'BLOCKED','window-control-noise',created=f'2026-10-15T1{k}:00:00+00:00')
            self.assertIn('window-control-fail',bw.window_refusal(bw.chain(Path(t),'7'*32),plan,'1b'))
            self.assertEqual(bw.control_fail_versions(Path(t),{'7'*32}),['7'*32])

class ChainFixtureTests(unittest.TestCase):
    def test_the_chain_fixtures_are_consistent(self):
        s=bw.CHAIN_FIXTURE_STATE
        self.assertEqual((s['problems'],s['pooled']),([],[]));self.assertFalse(s['state']['control_fail'])
        self.assertEqual(bw.windows_record(s,'0'*32),bw.CHAIN_FIXTURE_RECORD)
        self.assertEqual(bw.chain_problems(s['history'],['1a'],set()),[])
        self.assertEqual(set(bw.CHAIN_FIXTURE_IDENTITY),set(bw.envelope_identity({'bench_profile_sha256':'a'*64,'envelope':ENV4,'image_id':'sha256:'+'b'*64,
                         'policy_sha256':'c'*64,'protocol_sha256':None,'case_version':1,'source_identity':'d'*64,'dataset':SMALL})))
    def test_the_envelope_identity_of_a_run(self):
        run={'bench_profile_sha256':'a'*64,'envelope':ENV4,'image_id':'sha256:'+'b'*64,'policy_sha256':'c'*64,'protocol_sha256':'9'*64,'case_version':4,
             'source_identity':'d'*64,'dataset':SMALL,'native':{'binaries':{'bd-kernel':'e'*64}}}
        ident=bw.envelope_identity(run)
        self.assertEqual((ident['cpuset_size'],ident['smt_siblings'],ident['native'],ident['case_version']),(4,[],{'bd-kernel':'e'*64},4))
        self.assertEqual(bw.windows_match(ident,bw.envelope_identity(dict(run,dataset=LARGE))),['datasets'])
        self.assertEqual(bw.windows_match(ident,bw.envelope_identity(dict(run,envelope=dict(ENV4,cpuset=[0,1])))),['cpuset_size'])

# ---- decide over a window chain: the merged evidence of the PASS positions ----
def write_window_run(root,run_id,sub,observations,window,attempt,status='PASS',version=None,extends=None,created='2026-10-15T10:00:00+00:00',extension_of=None,look1=None):
    d=Path(root)/'artifacts/bench'/run_id;d.mkdir(parents=True)
    (d/'plan.json').write_text(json.dumps(sub));(d/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in observations))
    (d/'window-plan.json').write_text(json.dumps(version))
    if look1 is not None:
        (d/'look1-decision.json').write_text(json.dumps(look1))
        extension_of=dict(extension_of,decision_sha256=hashlib.sha256((d/'look1-decision.json').read_bytes()).hexdigest())
    run={'run_id':run_id,'created_at':created,'status':'VALID','reasons':[],'window':window,'attempt':attempt,'window_plan_id':version['plan_id'],'extends':extends,
         'attempt_outcome':{'status':status,'reason':None if status!='BLOCKED' else 'window-pressure','controls':{'base':'EQUAL','candidate':'EQUAL'}},
         'envelope_identity':dict(MovedFromTask19Tests.ID),'extension_of':extension_of,'plan':{'plan_id':sub['plan_id'],'project_dir':None}}
    run['run_record_sha256']=be.run_record_sha256(run);(d/'run.json').write_text(json.dumps(run));return run

def unit_obs(sub,wall=lambda o:1000):
    """One eligible observation per timed trial of a run plan (the unit rows and the control rows)."""
    return [{'trial_id':t['trial_id'],'block':t['block'],'warmup':t['warmup'],'eligible':True,'scope':t['scope'],'mode':t['mode'],'variant':t['variant'],
             'workers':t['workers'],'route':t.get('route'),'point':t['point'],'tier':t['tier'],'work_units':256,'loops':1,'wall_ns':wall(t),'phase':'caller',
             'cpu_pressure_total':5,**({'unit':t['unit']} if 'unit' in t else {})} for s in sub['sessions'] for t in s['trials'] if 'panel' not in t]

class ChainForDecideTests(unittest.TestCase):
    def setUp(self):
        self.case=wcase();self.case['points']=[p for p in self.case['points'] if 'panel' not in p]
        self.pol=dict(WPOL,units=['ma/full-dataset','mb/full-dataset'])
        self.version=decision_plan(case=self.case,policy=self.pol)
    def decide_input(self,t):
        with mock.patch('bench_phase3_cli.recorded_problems',return_value=[]),mock.patch('bench_model.load_decision_policy',return_value=self.pol),\
             mock.patch('bench_model.load_case',return_value=self.case),mock.patch('bench_model.load_policy',return_value=pdoc()):
            return bw.chain_for_decide(Path(t),'a'*32)
    def test_one_window(self):
        sub=bw.window_run_plan(self.version,'1a',self.case,self.pol,pdoc())
        with tempfile.TemporaryDirectory() as t:
            run=write_window_run(t,'a'*32,sub,unit_obs(sub),'1a',1,version=self.version)
            cfd=self.decide_input(t)
            self.assertEqual((cfd['problems'],cfd['pooled']),([],[]));self.assertEqual(cfd['state']['positions'],{'1a':run['run_record_sha256']})
            ev=cfd['evidence'];self.assertEqual(ev['looks'],{});self.assertEqual((ev['window_pressure'],ev['extension_exhausted'],ev['window_invalid']),([],[],[]))
            self.assertEqual({o['unit'] for o in ev['observations'] if o.get('unit')},{'ma/full-dataset','mb/full-dataset'})
            self.assertFalse(any(o['point'].startswith('control-') for o in ev['observations']))
            self.assertIn('unit-ma-slowest',{o['point'] for o in ev['observations']})            # the diagnostic rows stay reported
            rec=bw.windows_record(cfd,self.version['plan_id'])
            self.assertEqual([(p['window'],p['attempt'],p['status']) for p in rec['positions']],[('1a',1,'PASS')])
    def test_an_extension_pools_the_triggered_unit_at_look_2(self):
        sub=bw.window_run_plan(self.version,'1a',self.case,self.pol,pdoc());ext=bw.extension_run_plan(self.version,'1a',['ma/full-dataset'],self.case,self.pol,pdoc())
        look1={'units':[{'unit':'ma/full-dataset','look':1,'extension':{'trigger':True,'note':None}},{'unit':'mb/full-dataset','look':1,'extension':{'trigger':False,'note':None}}],
               'windows':{'plan_id':self.version['plan_id']}}
        with tempfile.TemporaryDirectory() as t:
            first=write_window_run(t,'a'*32,sub,unit_obs(sub),'1a',1,version=self.version)
            write_window_run(t,'b'*32,ext,unit_obs(ext),'2a',1,version=self.version,extends=first['run_record_sha256'],created='2026-10-15T11:00:00+00:00',
                             extension_of={'run_id':'a'*32,'window':'1a','record_sha256':first['run_record_sha256'],'decision_sha256':'9'*64,'units':['ma/full-dataset']},look1=look1)
            cfd=self.decide_input(t)
            self.assertEqual(cfd['problems'],[]);self.assertEqual(cfd['evidence']['looks'],{'ma/full-dataset':2})
            blocks=sorted({o['block'] for o in cfd['evidence']['observations'] if o.get('unit')=='ma/full-dataset' and not o['warmup']})
            self.assertEqual(blocks,list(range(24)))
            self.assertEqual([p['unit'] for p in cfd['pooled']],['ma/full-dataset']);self.assertEqual(cfd['pooled'][0]['windows'],['1a','2a'])
    def test_an_exhausted_window_gives_its_units_the_window_pressure_order(self):
        sub=bw.window_run_plan(self.version,'1a',self.case,self.pol,pdoc())
        with tempfile.TemporaryDirectory() as t:
            for k in (1,2,3):write_window_run(t,f'{k}'*32,sub,[],'1a',k,status='BLOCKED',version=self.version,created=f'2026-10-15T1{k}:00:00+00:00')
            with mock.patch('bench_phase3_cli.recorded_problems',return_value=[]),mock.patch('bench_model.load_decision_policy',return_value=self.pol),\
                 mock.patch('bench_model.load_case',return_value=self.case),mock.patch('bench_model.load_policy',return_value=pdoc()):
                cfd=bw.chain_for_decide(Path(t),'1'*32)
            self.assertEqual(cfd['problems'],[]);self.assertEqual(sorted(cfd['evidence']['window_pressure']),['ma/full-dataset','mb/full-dataset'])
            self.assertEqual(cfd['state']['exhausted'],['1a'])
    def test_a_recorded_problem_of_a_chain_run_is_a_chain_problem(self):
        sub=bw.window_run_plan(self.version,'1a',self.case,self.pol,pdoc())
        with tempfile.TemporaryDirectory() as t:
            write_window_run(t,'a'*32,sub,unit_obs(sub),'1a',1,version=self.version)
            with mock.patch('bench_phase3_cli.recorded_problems',return_value=['changed after the run: observations.jsonl']),\
                 mock.patch('bench_model.load_decision_policy',return_value=self.pol),mock.patch('bench_model.load_case',return_value=self.case),\
                 mock.patch('bench_model.load_policy',return_value=pdoc()):
                cfd=bw.chain_for_decide(Path(t),'a'*32)
            self.assertTrue(any('changed after the run' in p for p in cfd['problems']))
    def test_a_run_of_another_run_plan_is_a_chain_problem(self):
        sub=bw.window_run_plan(self.version,'1a',self.case,self.pol,pdoc());edited=copy.deepcopy(sub);edited['sessions']=edited['sessions'][:1]
        edited['plan_id']=bench.plan_digest(edited)
        with tempfile.TemporaryDirectory() as t:
            write_window_run(t,'a'*32,edited,unit_obs(edited),'1a',1,version=self.version)
            self.assertTrue(any('run plan' in p for p in self.decide_input(t)['problems']))
    def test_a_run_that_is_not_a_window_run_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'artifacts/bench'/('a'*32);d.mkdir(parents=True);(d/'run.json').write_text(json.dumps({'run_id':'a'*32}))
            with self.assertRaises(bw.NotAWindowRun):bw.chain_for_decide(Path(t),'a'*32)

class RecordSchemaTests(unittest.TestCase):
    def test_a_window_policy_record_holds_the_windows_object(self):
        import bench_units as bu
        units=bu.decide_units(bw.UEV_FIXTURE,dict(UPOL,windows=WDECL),{'resamples':100,'seed':1})
        run={'run_id':'0'*32,'case':'fixture-case','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'dataset':{'kind':'synthetic'}}
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            rec=bu.unit_decision_record(ROOT,run,{},{'case_id':'fixture-case','variants':[]},dict(UPOL,windows=WDECL,name='window-fixture-units',sha256='0'*64),
                                        units,bw.UEV_FIXTURE,{},windows=bw.CHAIN_FIXTURE_RECORD)
        validate(ROOT,'bench-decision',rec);self.assertTrue(rec['policy']['windows'])
        with self.assertRaises(GateError):validate(ROOT,'bench-decision',dict(rec,windows=None))
        plain=dict(rec,policy={k:v for k,v in rec['policy'].items() if k!='windows'},windows=None);validate(ROOT,'bench-decision',plain)

class RunRecordSchemaTests(unittest.TestCase):
    def test_the_run_record_takes_the_window_fields(self):
        base=json.loads((ROOT/'tests/unit/fixtures/decide/run/run.json').read_text());validate(ROOT,'bench-run',base)      # the schema change is additive
        run=dict(base,window='1a',attempt=1,window_plan_id='7'*32,extends=None,attempt_outcome={'status':'PASS','reason':None,'controls':{'base':'EQUAL','candidate':'EQUAL'}},
                 envelope_identity=dict(MovedFromTask19Tests.ID,protocol_sha256=None),extension_of=None)
        validate(ROOT,'bench-run',run)
        validate(ROOT,'bench-run',dict(run,window='2a',extends='a'*64,extension_of={'run_id':'a'*32,'window':'1a','record_sha256':'b'*64,'decision_sha256':'c'*64,
                                                                                     'units':['ma/full-dataset']}))
        for key,bad in (('window','3a'),('attempt',4),('attempt',0),('attempt_outcome',{'status':'MAYBE','reason':None,'controls':{}}),('extends','x'),
                        ('window_plan_id','x'),('attempt_outcome',{'status':'BLOCKED','reason':'tired','controls':{'base':None,'candidate':None}}),
                        ('extension_of',{'run_id':'a'*32}),('envelope_identity',[1])):
            with self.subTest(key=key,bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-run',dict(run,**{key:bad}))
    def test_the_window_link_descriptions_name_the_chain_digest(self):
        """EX18c-A03 (FIX1): `extends` and extension_of.record_sha256 hold the chain digest (bench_windows.record_digest: the
        record without its decision digests), which differs from the current run_record_sha256 of a decided run."""
        props=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']
        for key in ('extends','extension_of'):
            with self.subTest(key=key):
                text=props[key]['description']
                self.assertIn('bench_windows.record_digest',text);self.assertIn('decision digests',text)
        self.assertTrue(props['extends']['description'].startswith('EX-18b (H10, H15.2): the run record sha256 of the nearest earlier'))   # additive text
        self.assertTrue(props['extension_of']['description'].startswith('EX-18b (G10.3): null for a look-1 window attempt;'))

# ---- the protocol declaration and the B09 extension sub-checks ----
class DeclarationTests(unittest.TestCase):
    def test_the_controls_must_be_rows_of_the_case(self):
        self.assertEqual(bw.declaration_problems(wcase(),WPOL),[])
        bad={'unknown point':{'base':{'point':'nowhere','variant':'py-optimized'}},
             'kernel point':None,
             'base is a C row':{'base':{'point':'baseline','variant':'c-serial','route':'stdio'}},
             'candidate is a Python row':{'candidate':{'point':'baseline','variant':'py-reference','route':'stdio'}},
             'candidate without a route':{'candidate':{'point':'baseline','variant':'c-serial'}},
             'base with a route':{'base':{'point':'baseline','variant':'py-optimized','route':'stdio'}},
             'route of no variant':{'candidate':{'point':'baseline','variant':'c-serial','route':'inproc'}},
             'variant not in the point':{'base':{'point':'unit-ma-full','variant':'py-reference'}},
             'variant never planned at the large size':{'base':{'point':'unit-mb-full','variant':'py-reference'}},
             'point without the warm mode':{'base':{'point':'cold-point','variant':'py-optimized'}}}
        case=wcase();case['points'].append({'name':'kernel-point','scope':'kernel','size':'small','modes':['direct'],'variants':['py-optimized'],'class':'exploratory'})
        case['points'].append({'name':'cold-point','scope':'caller','size':'small','modes':['cold'],'variants':['py-optimized'],'class':'exploratory'})
        bad['kernel point']={'base':{'point':'kernel-point','variant':'py-optimized'}}
        for name,controls in bad.items():
            with self.subTest(name):
                pol=dict(WPOL,windows=dict(WDECL,controls=dict(WDECL['controls'],**controls)))
                self.assertNotEqual(bw.declaration_problems(case,pol),[])
    def test_the_schema_holds_the_window_declaration(self):
        import jsonschema
        schema=json.loads((ROOT/'schemas/bench-protocol.json').read_text());v=jsonschema.Draft202012Validator(schema)
        doc=json.loads((ROOT/'tests/fixtures/bench-project/benchmarks/project/protocol/protocol.json').read_text())
        name=next(iter(doc['decision_policies']));good=copy.deepcopy(doc);good['decision_policies'][name]['windows']=WDECL
        self.assertTrue(v.is_valid(good))
        for value in (dict(WDECL,window_seconds=3600),dict(WDECL,window_seconds=86400)):       # EX-18c (EX18b-A09): both exact bounds
            with self.subTest(window_seconds=value['window_seconds']):
                doc2=copy.deepcopy(doc);doc2['decision_policies'][name]['windows']=value;self.assertTrue(v.is_valid(doc2))
        bad={'window above a day':dict(WDECL,window_seconds=86401),'window below an hour':dict(WDECL,window_seconds=3599),'headroom below one':dict(WDECL,cap_headroom=0.9),
             'step zero':dict(WDECL,cap_step_seconds=0),'one cap only':dict(WDECL,caps_seconds={'synthetic':1}),'cap text':dict(WDECL,caps_seconds={'synthetic':'1','local':1}),
             'unknown key':dict(WDECL,blocks=12),'no controls':{k:x for k,x in WDECL.items() if k!='controls'},
             'one control':dict(WDECL,controls={'base':WDECL['controls']['base']}),'control key':dict(WDECL,controls=dict(WDECL['controls'],base=dict(WDECL['controls']['base'],workers=2)))}
        for case,value in bad.items():
            with self.subTest(case=case):
                doc2=copy.deepcopy(doc);doc2['decision_policies'][name]['windows']=value;self.assertFalse(v.is_valid(doc2))
    def test_the_example_project_declares_a_window_policy(self):
        names=bm.unit_policy_names(ROOT,'examples/bench-demo');self.assertTrue(names)
        pol=bm.load_decision_policy(ROOT,names[0],'examples/bench-demo');case=bm.load_case(ROOT,pol['case'],'examples/bench-demo')
        self.assertIn('windows',pol);self.assertEqual(bw.declaration_problems(case,pol),[])
        self.assertTrue(any(p.get('unit') in pol['units'] for p in case['points']))

class ExtensionSuiteTests(unittest.TestCase):
    def test_the_b09_extension_sub_checks_reject_each_recorded_refusal(self):
        out=bench.b09_extension_checks(ROOT)
        self.assertEqual(out['status'],'PASS',out);self.assertEqual([c['name'] for c in out['checks']],['extension-without-trigger','discarded-blocks','window-envelope-mismatch'])
        self.assertTrue(all(c['rejected'] for c in out['checks']));self.assertEqual(out['control'],'PASS')
    def test_the_sub_checks_fail_when_a_refusal_is_accepted(self):
        with mock.patch('bench_windows.check_extension',return_value=[]):self.assertEqual(bench.b09_extension_checks(ROOT)['status'],'FAIL')
    def test_the_fixtures_are_recorded_files(self):
        names=sorted(p.name for p in (ROOT/'tests/unit/fixtures/windows').glob('*.json'))
        self.assertEqual(names,['extension-11-blocks.json','extension.json','identity-other-image.json','identity.json','look1-no-trigger.json','look1-trigger.json'])

# ---- G10.4: the unit smoke jobs ----
class UnitSmokeTests(unittest.TestCase):
    def test_the_unit_smoke_jobs_plan_the_unit_points_only(self):
        import bench_phase3 as b3
        plans=b3.unit_smoke_plan(wcase(),WPOL,ENV4,pdoc())
        units=sorted(t['unit'] for p in plans for s in p['sessions'] for t in s['trials'] if not t['warmup'] and t['block']==0)
        self.assertEqual(sorted(set(units)),sorted(WPOL['units']))
        for p in plans:
            with self.subTest(job=p['smoke_job']):
                self.assertEqual((p['mode'],p['policy'],p['memory']),('smoke','window-fixture-units',[]))
                self.assertLessEqual(p['estimate_seconds'],POLICY_DOC['job_deadlines']['smoke'])
                trials=[t for s in p['sessions'] for t in s['trials']]
                self.assertTrue(all(t.get('unit') and t['mode']=='warm' for t in trials))
                self.assertEqual({t['block'] for t in trials if not t['warmup']},{0,1})
                self.assertEqual({t['tier'] for t in trials if 'panel' not in t},{'small'});self.assertTrue(all(t['tier']=='tiny' for t in trials if 'panel' in t))
        self.assertEqual([p['smoke_job'] for p in plans],list(range(len(plans))))
    def test_a_job_above_the_smoke_deadline_is_split(self):
        import bench_phase3 as b3
        doc=pdoc(ma=20.0,mb=4.0)           # each unit point alone fits 600 s; together they do not
        plans=b3.unit_smoke_plan(wcase(),WPOL,ENV4,doc);self.assertGreater(len(plans),1)
        self.assertTrue(all(p['estimate_seconds']<=600 for p in plans))
        with self.assertRaises(GateError):b3.unit_smoke_plan(wcase(),WPOL,ENV4,pdoc(ma=400.0))
    def test_the_unit_smoke_suite_is_wired(self):
        import inspect, bench_phase3 as b3
        self.assertIn("suites['unit-smoke']",inspect.getsource(b3.phase3_cases))
        rows={r['id']:r for r in json.loads((ROOT/'safety/framework-ledger.json').read_text())['findings']}
        self.assertEqual(rows['EX17-A04']['state'],'VERIFIED');self.assertTrue(rows['EX17-A04']['verification'])

# ---- EX-18c (EX18b-A01): the sessions of a window plan are packed by the share-weighted estimate that the checks read ----
# Exact binary values: the reference row of the unit point at the tiny tier (1 row) costs 2,656.75 x share 2.0 + 2 =
# 5,315.5 s; a control row set costs 4 + 4 + 2.5 + 2.5 = 13 s (py-optimized and c at the small tier), so the control
# trials of one session cost at most (12 + 1) x 13 = 169 s; one block, its warmup set and those controls: exactly 10,800 s.
CALP={'py-reference':2656.75,'py-optimized':0.0078125,'c':0.001953125}
PPOL=dict(WPOL,units=['ma/full-dataset'])

def pack_case():
    c=wcase()
    c['points']=[dict(c['points'][0],modes=['warm']),{'name':'unit-ma-full','scope':'caller','size':'tiny','modes':['warm'],'variants':['py-reference'],
                                                     'class':'primary','selector':'ma','unit':'ma/full-dataset'}]
    return c

def pack_plan(cal,share=2.0):
    return bp.build_plan(pack_case(),pdoc(ma=share),mode='decision',dataset=LARGE,seed=3,envelope=ENV4,calibration=cal,calibration_source=dict(SOURCE),
                         unit_policy=PPOL,calibration_observations=[obs_row('unit-ma-full','py-reference','ma',0.125)])

class PackingTests(unittest.TestCase):
    def test_one_block_with_its_warmup_and_the_session_controls_exactly_at_the_cap(self):
        doc=pdoc(ma=2.0);plan=pack_plan(dict(CALP))
        unit=[s for s in plan['sessions'] if s['point']=='unit-ma-full']
        self.assertEqual(len(unit),12)                                              # one block per session; the 12 blocks stay
        self.assertEqual(sorted(t['block'] for s in unit for t in s['trials'] if not t['warmup']),list(range(12)))
        reserve=bw.e_ctrl(doc,CALP,pack_case(),PPOL,1);self.assertEqual(reserve,169.0)
        for s in unit:
            with self.subTest(session=s['session']):
                self.assertEqual(s['estimate_seconds'],bw.session_seconds(s,doc,CALP,LARGE,plan['measured_reference']))   # one measure
                self.assertEqual(s['estimate_seconds']+reserve,10800.0)
        self.assertEqual(int((10800-2658.75)//2658.75),3)                           # the unweighted packing: 3 blocks per session,
        self.assertGreater(4*5315.5,10800)                                          # 21,262 s weighted (session-cap-infeasible before)
        self.assertTrue(plan['windows'])
    def test_one_past_the_cap_refuses(self):
        with self.assertRaises(bw.PlanRefusal) as e:pack_plan(dict(CALP,**{'py-reference':2656.875}))      # 2 x 5,315.75 + 169 = 10,800.5 s
        self.assertEqual(e.exception.reason,'session-cap-infeasible');self.assertEqual(e.exception.estimates[0]['estimate'],10800.5)
    def test_a_share_above_one_is_packed_by_its_weighted_estimate(self):
        doc=pdoc(ma=6.0);plan=decision_plan(doc=doc)          # unweighted the 12 blocks of unit-ma-full fit one session; weighted they need two
        unit=[s for s in plan['sessions'] if s['point']=='unit-ma-full']
        self.assertEqual([sum(1 for t in s['trials'] if not t['warmup'])//6 for s in unit],[11,1])
        reserve=bw.e_ctrl(doc,dict(CAL),wcase(),WPOL,1)
        for s in plan['sessions']:
            with self.subTest(session=s['session']):
                self.assertEqual(s['estimate_seconds'],bw.session_seconds(s,doc,dict(CAL),LARGE,plan['measured_reference']))
                self.assertLessEqual(s['estimate_seconds']+reserve,10800)

# ---- EX-18c (EX18b-A03): the reference batch and the py-reference panel row use the walls the calibration measured ----
class MeasuredReferenceTests(unittest.TestCase):
    def test_the_smoke_calibration_plan_measures_each_reference_batch(self):
        self.assertEqual(bw.reference_points(wcase(),WPOL),{'ma':['reference-ma'],'mb':['unit-mb-full']})
        pts={p['name']:p for p in bw.window_smoke_points(wcase(),WPOL,pdoc())}
        self.assertEqual({k:pts['reference-ma'].get(k) for k in ('scope','size','modes','variants','blocks','selector','unit')},
                         {'scope':'caller','size':'small','modes':['warm'],'variants':['py-reference'],'blocks':1,'selector':'ma','unit':None})
        self.assertNotIn('reference-mb',pts)
        plan=bp.build_plan(wcase(),pdoc(),mode='smoke',dataset=SMALL,seed=3,envelope=ENV4,unit_policy=WPOL)
        ref=[t for s in plan['sessions'] for t in s['trials'] if t['point']=='reference-ma']
        self.assertEqual(sorted((t['variant'],t['selector'],t['tier'],t['warmup']) for t in ref),[('py-reference','ma','small',False),('py-reference','ma','small',True)])
        clash=wcase();clash['points'].append(dict(clash['points'][0],name='reference-ma'))
        with self.assertRaises(GateError):bw.window_smoke_points(clash,WPOL,pdoc())
    def test_the_measured_walls_come_from_the_reference_rows_only(self):
        obs=REF_OBS+[obs_row('reference-ma','py-reference','ma',0.5,block=1),obs_row('reference-ma','py-reference','ma',0.9,block=2),
                     obs_row('reference-ma','py-reference','ma',9.0,block=3,warmup=True),obs_row('reference-ma','py-reference','ma',9.0,block=4,eligible=False),
                     obs_row('reference-ma','py-optimized','ma',9.0),obs_row('unit-ma-full','py-reference','ma',9.0),obs_row('reference-ma','py-reference','mb',9.0,block=5),
                     obs_row('reference-ma','py-reference','ma',9.0,block=6,workers=2),obs_row('unit-ma-one','py-reference','ma',9.0,panel=5,units=30,block=7,phase='startup')]
        got=bw.measured_reference(obs,wcase(),WPOL)
        self.assertEqual(got,{'batch':{'ma':0.5,'mb':0.014},'panel':{'unit-ma-one':0.14}})      # ma: the median of 0.14, 0.5 and 0.9
        self.assertEqual(bw.measured_reference([],wcase(),WPOL),{'batch':{},'panel':{}})
        with self.assertRaises(GateError):bw.measured_reference([{'point':'reference-ma','variant':'py-reference'}],wcase(),WPOL)
    def test_the_window_plan_uses_the_measured_walls(self):
        obs=[obs_row('reference-ma','py-reference','ma',0.28),obs_row('unit-mb-full','py-reference','mb',0.05),obs_row('unit-ma-one','py-reference','ma',0.3,panel=5,units=30)]
        d=pdoc(ma=3.0);plan=decision_plan(doc=d,observations=obs);m=plan['measured_reference']
        self.assertEqual(m,{'batch':{'ma':0.28,'mb':0.05},'panel':{'unit-ma-one':0.3}})
        parts={p['group']:p for w in plan['windows'] for p in w['parts']}
        self.assertAlmostEqual(parts['ma/full-dataset']['reference'],13230*0.28)     # the measured wall, not 13,230 x rate x share 3.0
        self.assertAlmostEqual(parts['mb/full-dataset']['reference'],13230*0.05)
        one=[t for s in plan['sessions'] for t in s['trials'] if t['point']=='unit-ma-one']
        ref=[t for t in one if t['variant']=='py-reference'];other=[t for t in one if t['variant']!='py-reference']
        self.assertTrue(ref and other)
        for t in ref:self.assertAlmostEqual(bw.trial_seconds(t,d,dict(CAL),LARGE,m),6*t['panel_passes']*0.3+2.0)
        for t in other:self.assertEqual(bw.trial_seconds(t,d,dict(CAL),LARGE,m),bw.trial_seconds(t,d,dict(CAL),LARGE,None))   # the other rows: rate x share
        ext=bw.extension_run_plan(plan,'1a',['ma/full-dataset'],wcase(),WPOL,d)
        sess=[s for s in plan['sessions'] if s['point']=='unit-ma-full'];e=bw.e_ctrl(d,dict(CAL),wcase(),WPOL,len(sess))
        self.assertAlmostEqual(ext['estimate_seconds'],e+sum(bw.session_seconds(s,d,dict(CAL),LARGE,m) for s in sess)+13230*0.28)
    def test_a_window_plan_without_a_measured_wall_refuses(self):
        for missing,name in (('reference-ma','ma'),('unit-ma-one','unit-ma-one')):
            with self.subTest(missing=missing),self.assertRaises(bw.PlanRefusal) as e:decision_plan(observations=[o for o in REF_OBS if o['point']!=missing])
            self.assertEqual(e.exception.reason,'reference-not-measured');self.assertIn(name,e.exception.detail)

# ---- EX-18c (EX18b-A04): a window smoke calibration above the smoke job deadline needs its stated deadline ----
class CalibrationDeadlineTests(unittest.TestCase):
    def smoke(self,doc,case=None,**decl):
        return bp.build_plan(case or wcase(),doc,mode='smoke',dataset=SMALL,seed=3,envelope=ENV4,unit_policy=dict(WPOL,windows=dict(WDECL,**decl)))
    def test_a_calibration_above_the_smoke_job_deadline_needs_a_stated_deadline(self):
        doc=pdoc(ma=3.0)
        with self.assertRaises(GateError) as e:self.smoke(doc)
        self.assertIn('600 s smoke job deadline',str(e.exception))
        plan=self.smoke(doc,calibration_deadline_seconds=1200)
        self.assertGreater(plan['estimate_seconds'],600);self.assertLessEqual(plan['estimate_seconds'],1200);self.assertEqual(plan['cap_seconds'],1200)
        for s in plan['sessions']:
            with self.subTest(session=s['session']):self.assertLessEqual(bw.session_seconds(s,doc,None,SMALL),600)    # each session job: 600 s
        with self.assertRaises(GateError) as e:self.smoke(doc,calibration_deadline_seconds=700)
        self.assertIn('calibration_deadline_seconds',str(e.exception))
    def test_the_control_session_keeps_the_smoke_job_deadline(self):
        case=wcase();case['points'][0]=dict(case['points'][0],size='large')           # the control rows at the large tier: about 1,790 s
        with self.assertRaises(GateError) as e:self.smoke(pdoc(),case=case,calibration_deadline_seconds=10800)
        self.assertIn('control session',str(e.exception))
    def test_the_schema_holds_the_stated_calibration_deadline(self):
        import jsonschema
        v=jsonschema.Draft202012Validator(json.loads((ROOT/'schemas/bench-protocol.json').read_text()))
        doc=json.loads((ROOT/'tests/fixtures/bench-project/benchmarks/project/protocol/protocol.json').read_text());name=next(iter(doc['decision_policies']))
        for value,ok in ((600,True),(10800,True),(599,False),(10801,False),(1200.5,False),('1200',False)):
            with self.subTest(value=value):
                d=copy.deepcopy(doc);d['decision_policies'][name]['windows']=dict(WDECL,calibration_deadline_seconds=value);self.assertEqual(v.is_valid(d),ok)

# ---- EX-18c (EX18b-A06): the calibration report shows the spread of each control pair ----
class CalibrationReportTests(unittest.TestCase):
    def test_the_report_holds_the_spread_and_the_blocks_of_each_control_pair(self):
        doc=copy.deepcopy(POLICY_DOC);doc['statistics']['bootstrap_resamples']=200
        pair=lambda side,vals:[{'point':f'control-base-{side}','variant':'py-optimized','workers':'direct','mode':'warm','block':b,'warmup':False,'scope':'caller',
                                'cpu_pressure_total':0,'wall_ns':v,'eligible':True,'work_units':1,'loops':1,'trial_id':f'{side}-{b}'} for b,v in enumerate(vals)]
        walls=[1000*(1.3 if b%2 else 0.7) for b in range(12)]
        rep=bw.calibration_report(pair('a',[1000]*12)+pair('b',walls),doc,draws=20)
        logs=[math.log(w/1000) for w in walls]
        self.assertEqual(rep['control_blocks'],{'base':12,'candidate':0})
        self.assertAlmostEqual(rep['control_sd']['base'],statistics.stdev(logs));self.assertIsNone(rep['control_sd']['candidate'])
        self.assertEqual(len(rep['control_log_ratios']['base']),12);self.assertAlmostEqual(rep['control_log_ratios']['base'][1],math.log(1.3))
        self.assertEqual(rep['control_log_ratios']['candidate'],[])

# ---- EX-18c (EX18b-A02): the recorded checks of a window chain run, unmocked, on the recorded decide fixture ----
DECIDE_FIXTURE=ROOT/'tests/unit/fixtures/decide/run'

def recorded_window_copy(tmp,status,observations=None,run=None,drop=None,tamper=None,after=None):
    """A bound copy of the recorded decide fixture as one window attempt with the attempt outcome `status`: the evidence and
    run record digests are recomputed (a consistent bound run). `tamper` edits run.json and `after` an evidence file after
    the binding, without any digest recomputation."""
    d=Path(tmp)/('0'*32);shutil.copytree(DECIDE_FIXTURE,d)
    if observations is not None:
        rows=[json.loads(x) for x in (d/'observations.jsonl').read_text().splitlines() if x.strip()]
        (d/'observations.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in observations(rows)))
    if drop is not None:(d/drop).unlink()
    r=json.loads((d/'run.json').read_text());r['evidence_digests']=be.digest_files(d)
    r.update(window='1a',attempt=1,window_plan_id='7'*32,extends=None,extension_of=None,envelope_identity=dict(MovedFromTask19Tests.ID,protocol_sha256=None),
             attempt_outcome={'status':status,'reason':{'BLOCKED':'window-pressure','FAIL':'run-invalid'}.get(status),'controls':{'base':'EQUAL','candidate':'EQUAL'}})
    if run is not None:r=run(r)
    r[be.RECORD_KEY]=be.run_record_sha256(r)
    if tamper is not None:r=tamper(r)
    (d/'run.json').write_text(json.dumps(r,sort_keys=True))
    if after is not None:after(d)
    return d

def recorded(d,identity='a'*64):
    """bench_phase3_cli.recorded_problems on the copy: the current source identity is `identity`; the policy and runner
    digests of the fixture are taken as current (the fixture predates the current policy, as in test_bench_decide_cli)."""
    with mock.patch('bench._run_dir',return_value=d),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
         mock.patch('policy.source_identity',return_value=(identity,{})):
        return cli.recorded_problems(ROOT,'0'*32)

INELIGIBLE=lambda rows:[dict(rows[0],eligible=False)]+rows[1:]            # the recorded files give INVALID_EXPERIMENT

class RecordedProblemsTests(unittest.TestCase):
    def test_a_final_position_needs_the_status_of_its_outcome(self):
        cases={('PASS',None):[],('PASS',INELIGIBLE):['the recorded files give the run status INVALID_EXPERIMENT, the attempt outcome needs VALID'],
               ('FAIL',None):['the recorded files give the run status VALID, the attempt outcome needs INVALID_EXPERIMENT'],('FAIL',INELIGIBLE):[],
               ('BLOCKED',None):[],('BLOCKED',INELIGIBLE):[]}
        for (status,obs),want in cases.items():
            with self.subTest(status=status,ineligible=obs is not None),tempfile.TemporaryDirectory() as t:
                self.assertEqual(recorded(recorded_window_copy(t,status,observations=obs)),want)
    def test_each_shared_check_of_decide_applies(self):
        cases={'run.json edited':(dict(tamper=lambda r:dict(r,attempt=2)),{},['changed after the run: run.json']),
               'evidence edited':(dict(after=lambda d:(d/'plan.json').write_text((d/'plan.json').read_text()+' ')),{},['changed after the run: plan.json']),
               'another source':({},{'identity':'b'*64},['reused-source-report: the run belongs to another source identity']),
               'a profiled run':(dict(run=lambda r:dict(r,mode='profile')),{},['profiled runs never decide']),
               'no plan':(dict(drop='plan.json'),{},['missing: plan.json'])}
        for name,(edit,kw,want) in cases.items():
            with self.subTest(name),tempfile.TemporaryDirectory() as t:
                self.assertEqual(recorded(recorded_window_copy(t,'PASS',**edit),**kw),want)
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.recorded_problems(Path(t),'0'*32),['the run record is unreadable (GateError)'])

# ---- EX-18c (EX18b-A02, A07): bench run --extend on recorded window chains (a temporary root, nothing mocked but the
# protocol lookup of the synthetic window policy) ----
BASE_RUN=json.loads((DECIDE_FIXTURE/'run.json').read_text())          # a schema-valid run record; the window fields come on top
# T6-R7: the calibration run measures a wall of every variant, selector and call class that the plan version holds (the
# control rows at `all`, the unit points of ma and mb, the panel rows); each value equals the planning rate x share of
# pdoc(), so the version's estimates stay those of rate x share.
CAL_ROWS=[obs_row('smoke-caller','py-reference','all',0.14),obs_row('smoke-caller','py-optimized','all',0.0045),obs_row('smoke-caller','c-serial','all',0.0004),
          obs_row('unit-ma-full','py-optimized','ma',0.0045),obs_row('unit-ma-full','c-serial','ma',0.0004),obs_row('unit-mb-full','py-optimized','mb',0.00045),
          obs_row('unit-mb-full','c-serial','mb',0.00004),obs_row('unit-ma-one','py-optimized','ma',0.0045,panel=5,units=30),
          obs_row('unit-ma-one','c-serial','ma',0.0004,panel=5,units=30)]+REF_OBS
CAL_RUN='c0'*16                                                        # the calibration run of WindowRoot

def look1(plan_id,trigger=('ma/full-dataset',),look=1):
    """A look-1 decision record of the plan version: the units of WPOL, `trigger` with an extension trigger."""
    return {'units':[{'unit':u,'look':look,'extension':{'trigger':u in trigger,'note':None}} for u in WPOL['units']],'windows':{'plan_id':plan_id}}

class WindowRoot:
    """A temporary root with the calibration run of a window plan version and its recorded window attempts."""
    def __init__(self,t,case=None):
        self.root=Path(t);self.case=case or wcase();self.doc=pdoc();cal=CAL_RUN;d=self.root/'artifacts/bench'/cal;d.mkdir(parents=True)
        (d/'observations.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in CAL_ROWS))
        source={'run_id':cal,'observations_sha256':hashlib.sha256((d/'observations.jsonl').read_bytes()).hexdigest()}
        rates=bp.calibration_inputs(self.root,cal,self.doc,bp.calibration_families(self.case))[0]      # T6-R7: what bench run --plan re-derives
        self.version=bp.build_plan(self.case,self.doc,mode='decision',dataset=LARGE,seed=3,envelope=ENV4,calibration=rates,calibration_source=source,
                                   unit_policy=WPOL,calibration_observations=CAL_ROWS)
        self.pid=self.version['plan_id']
    def run(self,run_id,window,attempt,status,sub,extends=None,extension_of=None,look1_bytes=None,created='2026-10-15T10:00:00+00:00'):
        """One recorded window attempt as bench run writes it (plan.json, window-plan.json, observations, the bound run.json)."""
        d=self.root/'artifacts/bench'/run_id;d.mkdir(parents=True)
        (d/'plan.json').write_text(json.dumps(sub));(d/'window-plan.json').write_text(json.dumps(self.version))
        (d/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in unit_obs(sub)))
        if look1_bytes is not None:(d/'look1-decision.json').write_bytes(look1_bytes)
        run=dict(copy.deepcopy(BASE_RUN),run_id=run_id,created_at=created,window=window,attempt=attempt,window_plan_id=self.pid,extends=extends,extension_of=extension_of,
                 envelope_identity=dict(MovedFromTask19Tests.ID,protocol_sha256=None),
                 attempt_outcome={'status':status,'reason':{'BLOCKED':'window-pressure','FAIL':'run-invalid'}.get(status),'controls':{'base':'EQUAL','candidate':'EQUAL'}})
        run['evidence_digests']=be.digest_files(d);run[be.RECORD_KEY]=be.run_record_sha256(run)
        (d/'run.json').write_text(json.dumps(run));return run
    def decide(self,run_id,record):
        """What bench decide writes into a run: decision-<policy>.json, bound in run.json by bench_evidence.bind_decisions."""
        d=self.root/'artifacts/bench'/run_id;(d/f"decision-{WPOL['name']}.json").write_text(json.dumps(record,sort_keys=True))
        return be.bind_decisions(d,read_json(d/'run.json'),[WPOL['name']])
    def extend(self,run_id,case=None):
        with mock.patch('bench_model.load_decision_policy',return_value=WPOL):
            return bench.extension_attempt(self.root,argparse.Namespace(extend=run_id),case or self.case,self.doc,None,None,ENV4)
    def look1_run(self,run_id='a'*32,status='PASS',window='1a',attempt=1,created='2026-10-15T10:00:00+00:00'):
        return self.run(run_id,window,attempt,status,bw.window_run_plan(self.version,'1a',self.case,WPOL,self.doc),created=created)

class ExtensionAttemptTests(unittest.TestCase):
    def test_a_final_pass_with_a_bound_triggered_look1_record_extends(self):
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);base=w.look1_run();w.decide('a'*32,look1(w.pid))
            out,why=w.extend('a'*32);self.assertIsNone(why,why);plan,win=out
            self.assertEqual((win['window'],win['attempt'],win['extends'],win['extension_of']['units']),('2a',1,base[be.RECORD_KEY],['ma/full-dataset']))
            self.assertEqual(win['extension_of']['record_sha256'],base[be.RECORD_KEY])     # the record as bench run wrote it
            self.assertEqual(plan,bw.extension_run_plan(w.version,'1a',['ma/full-dataset'],w.case,WPOL,w.doc))
    def test_every_extend_refusal(self):
        def unbound(w):
            p=w.root/'artifacts/bench'/('a'*32)/'run.json';r=json.loads(p.read_text());r.pop(be.RECORD_KEY);p.write_text(json.dumps(r))
        def edited(w,name):
            p=w.root/'artifacts/bench'/('a'*32)/name;p.write_text(p.read_text()+' ')
        cases={'the base run record is not bound':lambda w:(w.look1_run(),unbound(w)),
               'the base run evidence changed':lambda w:(w.look1_run(),edited(w,'plan.json')),
               'no look-1 window attempt':lambda w:w.look1_run(window='2a'),
               'no PASS window attempt':lambda w:w.look1_run(status='BLOCKED'),
               'not the final position of window 1a':lambda w:(w.look1_run(),w.look1_run('b'*32,attempt=2,created='2026-10-15T11:00:00+00:00')),
               'has no look-1 decision record':lambda w:w.look1_run(),
               'differs from its bound digest':lambda w:(w.look1_run(),w.decide('a'*32,look1(w.pid)),edited(w,f"decision-{WPOL['name']}.json")),
               'no look-1 record of this plan version':lambda w:(w.look1_run(),w.decide('a'*32,look1('9'*32))),
               'no look-1 record of this plan version ':lambda w:(w.look1_run(),w.decide('a'*32,look1(w.pid,look=2))),
               'no unit of window 1a triggered an extension':lambda w:(w.look1_run(),w.decide('a'*32,look1(w.pid,trigger=())))}
        for text,setup in cases.items():
            with self.subTest(text),tempfile.TemporaryDirectory() as t:
                w=WindowRoot(t);setup(w);out,why=w.extend('a'*32)
                self.assertIsNone(out);self.assertIn(text.strip(),why)
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);w.look1_run();w.decide('a'*32,look1(w.pid))
            out,why=w.extend('a'*32,case=dict(w.case,case_id='another-case'))
            self.assertIsNone(out);self.assertIn('the base run is of case window-fixture, not another-case',why)
    def test_a_decide_never_changes_a_chain_digest(self):
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);a=w.look1_run()
            b=w.run('b'*32,'1b',1,'PASS',bw.window_run_plan(w.version,'1a',w.case,WPOL,w.doc),extends=a[be.RECORD_KEY],created='2026-10-15T11:00:00+00:00')
            before=bw.chain(w.root,w.pid);self.assertEqual(before['positions'],{'1a':a[be.RECORD_KEY],'1b':b[be.RECORD_KEY]})
            bound=w.decide('a'*32,look1(w.pid))
            self.assertNotEqual(bound[be.RECORD_KEY],a[be.RECORD_KEY])               # run.json itself binds its decision record
            self.assertEqual(bw.record_digest(bound),a[be.RECORD_KEY])
            after=bw.chain(w.root,w.pid);self.assertEqual(after['positions'],before['positions'])
            self.assertEqual(bw.chain_problems(after,['1a','1b'],set()),[])          # 1b still extends the position of 1a
    def test_an_altered_decided_run_makes_the_chain_refuse(self):
        """EX18c-A05 (coverage, FIX1): a decided run whose other fields changed has another chain digest, so the extends
        link of the later window no longer names its position and the chain refuses."""
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);a=w.look1_run()
            w.run('b'*32,'1b',1,'PASS',bw.window_run_plan(w.version,'1a',w.case,WPOL,w.doc),extends=a[be.RECORD_KEY],created='2026-10-15T11:00:00+00:00')
            bound=w.decide('a'*32,look1(w.pid));self.assertIn(be.DECISIONS_KEY,bound)
            self.assertEqual(bw.chain_problems(bw.chain(w.root,w.pid),['1a','1b'],set()),[])
            p=w.root/'artifacts/bench'/('a'*32)/'run.json';doc=json.loads(p.read_text());doc['reasons']=['an edit after the decide']
            p.write_text(json.dumps(doc))
            self.assertNotEqual(bw.record_digest(doc),a[be.RECORD_KEY])
            self.assertNotEqual(bw.chain_problems(bw.chain(w.root,w.pid),['1a','1b'],set()),[])
    def test_an_open_extension_window_survives_a_decide_on_its_base_run(self):
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);w.look1_run();w.decide('a'*32,look1(w.pid))
            (plan1,win1),why=w.extend('a'*32);self.assertIsNone(why)
            w.run('b'*32,'2a',1,'BLOCKED',plan1,extends=win1['extends'],extension_of=win1['extension_of'],look1_bytes=win1['look1'],created='2026-10-15T11:00:00+00:00')
            w.decide('a'*32,look1(w.pid,trigger=()))           # decide on the base run while 2a is open: a record without a trigger
            out,why=w.extend('a'*32);self.assertIsNone(why,why);plan2,win2=out
            self.assertEqual(win2['attempt'],2)
            self.assertEqual((win2['extension_of'],win2['look1'],win2['extends']),(win1['extension_of'],win1['look1'],win1['extends']))   # the pinned record
            w.run('c'*32,'2a',2,'PASS',plan2,extends=win2['extends'],extension_of=win2['extension_of'],look1_bytes=win2['look1'],created='2026-10-15T12:00:00+00:00')
            w.decide('a'*32,look1(w.pid))
            with mock.patch('bench_phase3_cli.recorded_problems',return_value=[]),mock.patch('bench_model.load_decision_policy',return_value=WPOL),\
                 mock.patch('bench_model.load_case',return_value=w.case),mock.patch('bench_model.load_policy',return_value=w.doc):
                cfd=bw.chain_for_decide(w.root,'c'*32)
            self.assertEqual(cfd['problems'],[]);self.assertEqual(cfd['evidence']['looks'],{'ma/full-dataset':2})
    def test_an_altered_pinned_record_refuses(self):
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);w.look1_run();w.decide('a'*32,look1(w.pid))
            (plan1,win1),why=w.extend('a'*32)
            w.run('b'*32,'2a',1,'BLOCKED',plan1,extends=win1['extends'],extension_of=win1['extension_of'],look1_bytes=win1['look1'],created='2026-10-15T11:00:00+00:00')
            p=w.root/'artifacts/bench'/('b'*32)/'look1-decision.json';p.write_bytes(p.read_bytes()+b' ')
            out,why=w.extend('a'*32);self.assertIsNone(out);self.assertIn('first extension attempt',why)
    def test_the_bound_look1_record_of_a_run(self):
        with tempfile.TemporaryDirectory() as t:
            w=WindowRoot(t);w.look1_run();w.decide('a'*32,look1(w.pid))
            rec,sha,data=bw.look1_record_of(w.root,'a'*32,WPOL['name'])
            self.assertEqual(rec,look1(w.pid));self.assertEqual(sha,hashlib.sha256(data).hexdigest())
            with self.assertRaises(GateError):bw.look1_record_of(w.root,'a'*32,'another-policy')
            p=w.root/'artifacts/bench'/('a'*32)/'run.json';r=json.loads(p.read_text());r['attempt']=2;p.write_text(json.dumps(r))
            with self.assertRaises(GateError) as e:bw.look1_record_of(w.root,'a'*32,WPOL['name'])
            self.assertIn('not bound',str(e.exception))

# ---- EX-18c (EX18b-A02): the plan versions after window-control-fail: unmocked lookups and the repair record ----
class ControlFailTests(unittest.TestCase):
    def failed(self,t):
        """WindowRoot with three window-control-noise attempts of its plan version (window-plan.json in the first)."""
        w=WindowRoot(t)
        for k in (1,2,3):run_record(t,f'{k}'*32,'1a',k,'BLOCKED','window-control-noise',plan_id=w.pid,created=f'2026-10-15T1{k}:00:00+00:00')
        (w.root/'artifacts/bench'/('1'*32)/'window-plan.json').write_text(json.dumps(w.version));return w
    def test_the_previous_versions_of_a_case_policy_and_dataset(self):
        with tempfile.TemporaryDirectory() as t:
            w=self.failed(t);base=w.root/'artifacts/bench'
            for name,edit in (('d'*32,{'case':'another-case'}),('e'*32,{'policy':'another-policy'}),('f'*32,{'dataset':SMALL}),('9'*32,{'dataset':dict(LARGE,sha256='0'*64)})):
                (base/name).mkdir();(base/name/'window-plan.json').write_text(json.dumps(dict(w.version,plan_id=name,**edit)))
            (base/('8'*32)).mkdir();(base/('8'*32)/'window-plan.json').write_text('{')
            (base/('7'*32)).symlink_to(base/('d'*32))
            self.assertEqual(bw.previous_versions(w.root,'window-fixture',WPOL['name'],LARGE),{w.pid})
            self.assertEqual(bw.control_fail_versions(w.root,{w.pid,'d'*32}),[w.pid])
    def test_the_repair_names_a_closed_finding_and_a_commit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'safety').mkdir();(root/'proj/review').mkdir(parents=True)
            (root/'safety/framework-ledger.json').write_text(json.dumps({'findings':[{'id':'FW-NOISE-01','state':'VERIFIED'},{'id':'FW-OPEN-01','state':'OPEN'}]}))
            (root/'proj/review/ledger.json').write_text(json.dumps({'findings':[{'id':'PRJ-NOISE-01','state':'VERIFIED'}]}))
            self.assertEqual(bw.repair_record(root,None,'FW-NOISE-01:abc1234',{'7'*32}),{'ledger_id':'FW-NOISE-01','commit':'abc1234','plan_ids':['7'*32]})
            self.assertEqual(bw.repair_record(root,'proj','PRJ-NOISE-01:'+'d'*40,{'7'*32})['ledger_id'],'PRJ-NOISE-01')
            for text in (None,'FW-NOISE-01','FW-NOISE-01:xyz','FW-OPEN-01:abc1234','NONE-01:abc1234','PRJ-NOISE-01:abc1234'):
                with self.subTest(text=text),self.assertRaises(bw.PlanRefusal) as e:bw.repair_record(root,None,text,{'7'*32})
                self.assertEqual(e.exception.reason,'control-fail-unrepaired')
    def test_bench_plan_refuses_a_plan_version_after_window_control_fail_with_exit_1(self):
        with tempfile.TemporaryDirectory() as t:
            w=self.failed(t);(w.root/'safety').mkdir()
            (w.root/'safety/framework-ledger.json').write_text(json.dumps({'findings':[{'id':'FW-OPEN-01','state':'OPEN'}]}))
            before=sorted(p.name for p in (w.root/'artifacts/bench').iterdir())
            for repair in (None,'not-a-repair','FW-OPEN-01:abc1234'):
                ns=argparse.Namespace(project=None,case='window-fixture',mode='decision',policy=WPOL['name'],dataset='synthetic:large',calibrate=CAL_RUN,format='json',
                                      matrix=None,repair=repair)
                with self.subTest(repair=repair),mock.patch('container_policy.host_topology',return_value=([0,1,2,3],{c:frozenset({c}) for c in range(4)})),\
                     mock.patch('bench_model.load_policy',return_value=w.doc),mock.patch('bench_model.load_case',return_value=w.case),\
                     mock.patch('bench_model.case_rules',return_value=None),mock.patch('bench_model.load_decision_policy',return_value=WPOL):
                    rc,out=bench._quiet(bench.plan_cmd,w.root,ns)
                    self.assertEqual((rc,out['status'],out['reason']),(1,'FAIL','control-fail-unrepaired'))
            self.assertEqual(sorted(p.name for p in (w.root/'artifacts/bench').iterdir()),before)        # no plan and no run directory

# ---- EX-18c (EX18b-A09): the exact bounds of the window plan ----
CALX={'py-reference':0.125,'py-optimized':0.0078125,'c':0.001953125}       # exact binary rates: every estimate below is exact

class ExactBoundTests(unittest.TestCase):
    def test_a_window_estimate_equal_to_the_declared_cap_is_accepted(self):
        plan=crafted([('ma/full-dataset',[3])])                 # 169 + 1,653.75 (reference) + 3 x 1,655.75 = 6,790 s
        out=bw.window_plan(plan,wcase(),WPOL,pdoc(),dict(CALX));self.assertEqual(out['windows'][0]['estimate'],6790.0)
        bw.window_plan(plan,wcase(),dict(WPOL,windows=dict(WDECL,caps_seconds={'synthetic':6790,'local':1})),pdoc(),dict(CALX))
        with self.assertRaises(bw.PlanRefusal) as e:bw.window_plan(plan,wcase(),dict(WPOL,windows=dict(WDECL,caps_seconds={'synthetic':6789,'local':86400})),pdoc(),dict(CALX))
        self.assertEqual(e.exception.reason,'owner-cap-exceeded')
    def test_a_plan_without_a_unit_session_refuses(self):
        for sessions in ([],[{'session':'baseline-s00','point':'baseline','trials':[{'variant':'py-optimized','selector':'all','tier':'small','loops':1,'warmup':False,
                                                                                        'block':0,'scope':'caller','mode':'warm','workers':'direct'}]}]):
            with self.subTest(sessions=len(sessions)),self.assertRaises(bw.PlanRefusal) as e:
                bw.window_plan({'sessions':sessions,'dataset':LARGE,'plan_id':'7'*32},wcase(),WPOL,pdoc(),dict(CAL))
            self.assertEqual((e.exception.reason,e.exception.detail),('window-cap-infeasible','the plan holds no unit session'))

PANEL_REF='synthetic:large#panel'

def ref_case():
    """wcase with a dataset_ref on its single-record unit point (the panel dataset that a panel trial of a local run needs)."""
    c=wcase()
    for p in c['points']:
        if p['name']=='unit-ma-one':p['dataset_ref']=PANEL_REF
    return c

class PlannedPointDatasetTests(unittest.TestCase):
    """R48 (T6-R6) defect 2: bench run derives the expected dataset identities from the points that the plan holds, so the
    dataset_ref of a planned unit point passes in every plan mode; a dataset identity that differs from its case
    derivation stays run-invalid."""
    def smoke_plan(self,**kw):return bp.build_plan(ref_case(),pdoc(),mode='smoke',dataset=SMALL,seed=3,envelope=ENV4,unit_policy=WPOL,**kw)
    def test_a_window_smoke_plan_with_a_unit_dataset_ref_is_valid(self):
        plan=self.smoke_plan()
        self.assertEqual(plan['datasets'][PANEL_REF],{'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':6,'indices':[0,1,2,3,4,5]})
        self.assertTrue(any(t.get('dataset_ref')==PANEL_REF for s in plan['sessions'] for t in s['trials'] if t['point']=='unit-ma-one'))
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),plan),[])
    def test_a_unit_smoke_job_plan_with_a_unit_dataset_ref_is_valid(self):
        jobs=bw.unit_smoke_jobs(ref_case(),WPOL,pdoc(),ENV4)
        k=next(n for n,j in enumerate(jobs) if any(p['name']=='unit-ma-one' for p in j))
        plan=self.smoke_plan(smoke_job=k);self.assertIn(PANEL_REF,plan['datasets'])
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),plan),[])
    def test_a_window_decision_plan_with_a_unit_dataset_ref_stays_valid(self):
        plan=decision_plan(case=ref_case());self.assertIn(PANEL_REF,plan['datasets'])
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),plan),[])
    def test_a_forged_identity_stays_run_invalid(self):
        plan=self.smoke_plan();why=f'run-invalid: dataset identity differs from its case derivation: {PANEL_REF}'
        for key,value in (('seed',20261008),('rows',7),('indices',[0,1,2,3,4,6]),('size','medium'),('kind','local')):
            with self.subTest(key=key):
                bad=copy.deepcopy(plan);bad['datasets'][PANEL_REF][key]=value
                self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),bad),[why])
        bad=copy.deepcopy(plan);del bad['datasets'][PANEL_REF]
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),bad),[why])
        bad=copy.deepcopy(plan);bad.pop('datasets')
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),bad),[why])
    def test_a_dataset_ref_that_no_planned_point_declares_is_run_invalid(self):
        other='synthetic:large#row:7';bad=copy.deepcopy(self.smoke_plan())
        bad['datasets'][other]={'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':1,'indices':[7]}
        t=next(t for s in bad['sessions'] for t in s['trials'] if t['point']=='unit-mb-full');t['dataset_ref']=other
        self.assertEqual(bench.dataset_identity_reasons(ref_case(),pdoc(),bad),[f'run-invalid: dataset identity differs from its case derivation: {other}'])
        # a case point that declares the dataset but is not in the plan does not make it planned
        c=ref_case();c['points'].append(dict(c['points'][1],name='unit-ma-extra',dataset_ref=other))
        self.assertEqual(bench.dataset_identity_reasons(c,pdoc(),bad),[f'run-invalid: dataset identity differs from its case derivation: {other}'])

if __name__=='__main__':unittest.main()
