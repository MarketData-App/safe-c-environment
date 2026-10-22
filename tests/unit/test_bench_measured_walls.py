"""T6-R7 (design I9.3; brief items 1(a) to 1(d)): every caller-scope timing trial of a calibrated plan is sized from the
measured wall of its variant, selector and call class, and the smoke plan measures every such class.

The defect (framework hit of demo run 34dc1922 of the example project): a plan sized a single-record panel trial (its
passes L and its call-deadline input) and every non-reference session, group and window term from a per-family rate of
256-row `all` calls times the selector share. A variant with a fixed per-call cost pays it on every one-row call, so a
warm trial of such a variant planned L = 36 passes at 2.37 ms per call while one call took about 0.94 s, and the 60 s call
deadline killed it. These tests use the synthetic window fixture of test_bench_windows (selectors ma and mb, six panel
cells) with one call deadline on ma; the slow one-row wall SLOW plays that variant."""
import copy, json, math, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'tests/unit'))
import bench, bench_deadline as bd, bench_plan as bp, bench_windows as bw
import test_bench_windows as tw
from evidence import GateError

SLOW=0.94          # seconds of one one-row call of py-optimized at selector ma: about 209 times rate x share (0.0045 x 1.0)
# The measured walls of the calibration run, per (variant, selector, call class): one-row in seconds per call, multi-row in
# seconds per record of a small-tier call. Every value differs from the rate x share of tw.pdoc() for that row.
WALLS={('py-reference','all','multi-row'):0.14,('py-optimized','all','multi-row'):0.0045,('c-serial','all','multi-row'):0.0012,
       ('py-reference','ma','multi-row'):0.3,('py-optimized','ma','multi-row'):0.0073,('c-serial','ma','multi-row'):0.0052,
       ('py-reference','mb','multi-row'):0.014,('py-optimized','mb','multi-row'):0.0011,('c-serial','mb','multi-row'):0.0006,
       ('py-reference','ma','one-row'):0.3,('py-optimized','ma','one-row'):SLOW,('c-serial','ma','one-row'):0.006}
SIZES=tw.POLICY_DOC['sizes'];OVER=tw.POLICY_DOC['budgets']['trial_overhead_seconds'];CAP=float(tw.POLICY_DOC['budgets']['session_cap_seconds'])
ROWS_LARGE=tw.LARGE['rows'];RUN_ID='a1'*16

def case():
    """The window fixture case with a call deadline on selector ma (factor 10, floor 60 s)."""
    c=tw.wcase();c['call_deadline']={'selectors':['ma'],'reason':'ma-overrun','factor':10,'floor_seconds':60};return c

def klass(t):
    """The call class of a planned trial (the rule of the brief, written out here): one-row for a panel trial or a tier of
    one row, else multi-row."""
    return 'one-row' if 'panel' in t else 'one-row' if SIZES[t['tier']]==1 else 'multi-row'

def cal_rows(skip=()):
    """The eligible timed caller rows of a calibration run with the walls of WALLS: the smoke-caller rows of `all`, the
    multi-row rows of each selector (py-reference at reference-ma and unit-mb-full, the reference points of the window
    fixture) and the one-row panel rows (one pass of six one-row calls)."""
    point={('all','multi-row'):'smoke-caller',('ma','multi-row'):'unit-ma-full',('mb','multi-row'):'unit-mb-full',('ma','one-row'):'unit-ma-one'}
    rows=[]
    for (v,s,c),w in WALLS.items():
        if (v,s,c) in skip:continue
        name='reference-ma' if (v,s,c)==('py-reference','ma','multi-row') else point[(s,c)]
        rows.append(tw.obs_row(name,v,s,w,panel=1,units=6) if c=='one-row' else tw.obs_row(name,v,s,w))
    return rows

def write_run(root,rows,run_id=RUN_ID):
    d=Path(root)/'artifacts/bench'/run_id;d.mkdir(parents=True,exist_ok=True)
    (d/'observations.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in rows));return run_id

def calibrate(root,rows,c=None):
    """(calibration, source, rows) of one read of the written calibration run (bench_plan.calibration_inputs)."""
    return bp.calibration_inputs(root,write_run(root,rows),tw.pdoc(),bp.calibration_families(c or case()))

def rule_plan(cal,source,c=None,**kw):
    return bp.build_plan(c or case(),tw.pdoc(),mode='decision',dataset=tw.LARGE,seed=3,envelope=tw.ENV4,calibration=cal,calibration_source=source,**kw)

def window_plan(cal,source,rows,c=None):
    return bp.build_plan(c or case(),tw.pdoc(),mode='decision',dataset=tw.LARGE,seed=3,envelope=tw.ENV4,calibration=cal,calibration_source=source,
                         unit_policy=tw.WPOL,calibration_observations=rows)

def trials(plan,point=None):
    return [t for s in plan['sessions'] for t in s['trials'] if point is None or t['point']==point]

def classes(plan,memory=True):
    """{(variant, selector, call class)} of the caller timing trials (and the memory trials) of a plan."""
    out={(t['variant'],t.get('selector','all'),klass(t)) for t in trials(plan) if t['scope']=='caller'}
    return out|({(m['variant'],m['selector'],klass(m)) for m in plan.get('memory') or []} if memory else set())

def want_seconds(t,cal_walls=WALLS,measured=None):
    """The measured estimate of one planned trial, written out: calls x rows x the wall of its class + the overhead."""
    if 'panel' in t:rows,calls=1,(6 if t['mode']=='cold' else 6*t['panel_passes'])
    else:rows,calls=SIZES[t['tier']],t.get('loops',1)
    if measured is not None and 'panel' in t and t['variant']=='py-reference':return measured['panel'][t['point']]*rows*calls+OVER
    return cal_walls[(t['variant'],t.get('selector','all'),klass(t))]*rows*calls+OVER

class SingleRecordTrialTests(unittest.TestCase):
    """Item 1(a): a one-row wall far above rate x share sets L, the expected trial wall and the call-deadline input."""
    def test_a_slow_one_row_call_gives_the_minimum_passes_and_a_covering_deadline(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
        warm=[x for x in trials(p,'unit-ma-one') if x['variant']=='py-optimized' and x['mode']=='warm']
        self.assertTrue(warm)
        for x in warm:
            e=6*x['panel_passes']*SLOW                                   # the expected trial wall: 6 x L one-row calls
            self.assertEqual(x['panel_passes'],5)                         # L back at the minimum: one call alone is 0.94 s
            self.assertAlmostEqual(x['call_deadline_seconds'],min(max(60.0,10*e),CAP),places=6)
            self.assertGreaterEqual(x['call_deadline_seconds']/e,2.0)     # the deadline covers the expected wall with its factor
            self.assertEqual(x['call_deadline_reason'],'ma-overrun')
    def test_the_passes_of_every_row_come_from_its_measured_one_row_wall(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
        for x in trials(p,'unit-ma-one'):
            with self.subTest(trial=x['trial_id']):
                self.assertEqual(x['panel_passes'],bp.panel_passes(per_call_seconds=WALLS[(x['variant'],'ma','one-row')],mode=x['mode']))
    def test_the_session_estimate_holds_the_measured_trial_walls(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
        sessions=[s for s in p['sessions'] if s['point']=='unit-ma-one'];self.assertTrue(sessions)
        for s in sessions:self.assertAlmostEqual(s['estimate_seconds'],math.fsum(want_seconds(x) for x in s['trials']),places=6)

class MultiRowUnitTests(unittest.TestCase):
    """Item 1(b): a full-dataset unit point of one selector uses the measured per-variant wall of that selector."""
    def test_the_deadline_and_the_session_estimate_use_the_selector_wall(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
        timed=[x for x in trials(p,'unit-ma-full') if not x['warmup']];self.assertTrue(timed)
        for x in timed:
            with self.subTest(trial=x['trial_id']):
                w=WALLS[(x['variant'],'ma','multi-row')]
                self.assertAlmostEqual(x['call_deadline_seconds'],min(max(60.0,10*ROWS_LARGE*w),CAP),places=6)
        for s in [s for s in p['sessions'] if s['point'] in ('unit-ma-full','unit-mb-full','baseline')]:
            with self.subTest(session=s['session']):self.assertAlmostEqual(s['estimate_seconds'],math.fsum(want_seconds(x) for x in s['trials']),places=6)
    def test_memory_trials_use_the_wall_of_selector_all(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
        mem=math.fsum(want_seconds(m) for m in p['memory'])
        self.assertAlmostEqual(p['estimate_seconds'],round(math.fsum(s['estimate_seconds'] for s in p['sessions'])+mem+ROWS_LARGE*cal['py-reference'],1),places=0)
    def test_a_kernel_trial_keeps_the_family_rate(self):
        c=case();c['points'].append({'name':'qual-kernel','scope':'kernel','size':'small','modes':['direct'],'variants':['py-reference','c-serial'],'class':'exploratory'})
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows(),c);p=rule_plan(cal,source,c)
        s=[s for s in p['sessions'] if s['point']=='qual-kernel'][0]
        self.assertAlmostEqual(s['estimate_seconds'],math.fsum(bp.trial_estimate(tw.pdoc(),x['variant'],SIZES[x['tier']],1,cal) for x in s['trials']),places=6)

class WindowEstimateTests(unittest.TestCase):
    """Item 1(c): the window, session and group estimates use the measured walls of every variant."""
    def test_every_session_trial_uses_its_measured_wall(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,rows=calibrate(t,cal_rows());p=window_plan(cal,source,rows)
        m=p['measured_reference'];doc=tw.pdoc()
        for s in p['sessions']:
            for x in s['trials']:
                with self.subTest(trial=x['trial_id']):self.assertAlmostEqual(bw.trial_seconds(x,doc,cal,tw.LARGE,m),want_seconds(x,measured=m),places=6)
            self.assertAlmostEqual(s['estimate_seconds'],math.fsum(want_seconds(x,measured=m) for x in s['trials']),places=6)
        warm=[x for x in trials(p,'unit-ma-one') if x['variant']=='py-optimized' and x['mode']=='warm']
        self.assertTrue(warm and all(x['panel_passes']==5 for x in warm))
        groups={g['id']:g for g in bw.groups(p,tw.WPOL,doc,cal,case())}
        self.assertAlmostEqual(groups['single-record']['sessions'][0]['seconds'],
                               math.fsum(want_seconds(x,measured=m) for x in [s for s in p['sessions'] if s['session']==groups['single-record']['sessions'][0]['id']][0]['trials']),places=6)
    def test_the_control_cost_uses_the_measured_walls_of_the_control_rows(self):
        with tempfile.TemporaryDirectory() as t:
            cal,_,_=calibrate(t,cal_rows())
        rows=bw.control_rows(case(),tw.WPOL)
        for n in (1,3):
            want=math.fsum((12+n)*(SIZES[r['tier']]*WALLS[(r['variant'],'all','multi-row')]+OVER) for r in rows)
            with self.subTest(sessions=n):self.assertAlmostEqual(bw.e_ctrl(tw.pdoc(),cal,case(),tw.WPOL,n),want,places=6)

class NoExtrapolationTests(unittest.TestCase):
    """Item 1(d): a planned class without a measured wall refuses the plan; the smoke plan measures every class."""
    def test_a_missing_wall_refuses_the_rule_plan_and_the_window_plan(self):
        for skip in (('c-serial','ma','one-row'),('py-optimized','mb','multi-row')):
            with self.subTest(skip=skip),tempfile.TemporaryDirectory() as t:
                cal,source,rows=calibrate(t,cal_rows(skip=(skip,)))
                for build in (lambda:rule_plan(cal,source),lambda:window_plan(cal,source,rows)):
                    with self.assertRaises(bw.PlanRefusal) as e:build()
                    self.assertEqual(e.exception.reason,'wall-not-measured')
                    self.assertEqual(e.exception.estimates,[{'variant':skip[0],'selector':skip[1],'class':skip[2]}])
    def test_the_smoke_plan_probes_every_class_of_the_decision_plan(self):
        doc=tw.pdoc();smoke=bp.build_plan(case(),doc,mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4)
        probes=[s for s in smoke['sessions'] if s['point'].startswith('probe-')]
        self.assertEqual([s['point'] for s in probes],['probe-ma-multi-row','probe-mb-multi-row','probe-ma-one-row'])
        self.assertEqual([s['point'] for s in smoke['sessions'][:2]],['smoke-caller','smoke-kernel'])      # the first session ids stay
        shape=lambda x:(x['variant'],x['workers'],x['mode'],str(x.get('route')),x['selector'],x['tier'],str(x.get('panel')),x.get('panel_passes',0))
        for s in probes:
            warm=[x for x in s['trials'] if x['warmup']];timed=[x for x in s['trials'] if not x['warmup']]
            self.assertEqual(len(timed),len({x['variant'] for x in timed}))                     # one short timed trial per variant
            self.assertEqual(sorted(map(shape,warm)),sorted(map(shape,timed)))                  # R87: one untimed warmup of the same shape (the same child)
            self.assertLess(max(s['trials'].index(x) for x in warm),min(s['trials'].index(x) for x in timed))   # before the timed trials
            for x in timed:self.assertEqual((x['block'],x['mode']),(0,'warm'))
            for x in s['trials']:
                if 'panel' in x:self.assertEqual(x['panel_passes'],1)
                if x['variant']=='c-serial':self.assertEqual(x['route'],'stdio')
        decision=bp.build_plan(case(),doc,mode='decision',dataset=tw.LARGE,seed=3,envelope=tw.ENV4)
        self.assertLessEqual(classes(decision),classes(smoke,memory=False))
        self.assertLessEqual(smoke['estimate_seconds'],doc['job_deadlines']['smoke'])
    def test_the_window_smoke_measures_every_class_of_the_window_plan(self):
        doc=tw.pdoc();smoke=bp.build_plan(case(),doc,mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4,unit_policy=tw.WPOL)
        self.assertFalse([s for s in smoke['sessions'] if s['point'].startswith('probe-')])          # the unit points measure them
        plan=tw.decision_plan(case=case())
        ctl={(r['variant'],r['selector'],'multi-row') for r in bw.control_rows(case(),tw.WPOL)}
        self.assertLessEqual(classes(plan,memory=False)|ctl,classes(smoke,memory=False))
    def test_a_one_row_tier_point_gets_a_probe_at_its_tier(self):
        c=case();c['points'].append({'name':'tiny-all','scope':'caller','size':'tiny','modes':['warm','cold'],'variants':['py-reference','py-optimized'],'class':'secondary'})
        smoke=bp.build_plan(c,tw.pdoc(),mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4)
        probe=[s for s in smoke['sessions'] if s['point']=='probe-all-one-row']
        self.assertEqual(len(probe),1);self.assertEqual({(x['tier'],'panel' in x) for x in probe[0]['trials']},{('tiny',False)})
        self.assertEqual(sorted(x['variant'] for x in probe[0]['trials'] if not x['warmup']),['py-optimized','py-reference'])
        self.assertEqual(sorted(x['variant'] for x in probe[0]['trials'] if x['warmup']),['py-optimized','py-reference'])   # R87
    def test_a_calibration_from_the_smoke_plan_sizes_the_decision_plan(self):
        doc=tw.pdoc();smoke=bp.build_plan(case(),doc,mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4);rows=[]
        for x in trials(smoke):
            if x['scope']!='caller':continue
            units=6*x['panel_passes'] if 'panel' in x else SIZES[x['tier']]
            o=tw.obs_row(x['point'],x['variant'],x['selector'],WALLS[(x['variant'],x['selector'],klass(x))],panel=x.get('panel_passes') if 'panel' in x else None,
                         units=units,trial_id=x['trial_id'],warmup=x['warmup'],mode=x['mode'],tier=x['tier'],workers=x['workers'])
            o['block']=x['block'];rows.append(o)
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,rows);p=rule_plan(cal,source)
            self.assertEqual(bench.verify_written_plan(case(),doc,copy.deepcopy(p),tw.ENV4,None,None,root=t),None)
        warm=[x for x in trials(p,'unit-ma-one') if x['variant']=='py-optimized' and x['mode']=='warm']
        self.assertTrue(warm and all(x['panel_passes']==5 for x in warm))
    def test_a_probe_dataset_is_named_and_a_stub_plan_holds_none(self):
        c=case()
        for q in c['points']:
            if q['name']=='unit-ma-one':q['dataset_ref']=tw.PANEL_REF
        doc=tw.pdoc();smoke=bp.build_plan(c,doc,mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4)
        self.assertEqual(smoke['datasets'][tw.PANEL_REF]['indices'],[0,1,2,3,4,5])
        self.assertEqual(bench.dataset_identity_reasons(c,doc,smoke),[])          # the probe point is a planned point of the run
        stub=bd.stub_plan(None,c,doc,tw.ENV4,3,bd.stub_spec({'reason':'ma-overrun','check':'x-check','variant':'py-optimized'}))
        self.assertNotIn('datasets',stub)

def nested(walls):
    out={}
    for (v,s,c),w in walls.items():out.setdefault(v,{}).setdefault(s,{})[c]=w
    return out

class ProbeBoundTests(unittest.TestCase):
    """Ruling R87: a smoke plan that holds probe points keeps every session within the 600 s smoke job deadline (a session
    above it is split or refused as before) and may take up to bench_plan.PROBE_SMOKE_CAP_SECONDS (1,200 s) in all; a smoke
    plan without probe points keeps the 600 s rule."""
    RATES={'py-reference':0.14,'py-optimized':0.12,'c':0.0004}
    def smoke(self,c,rates):
        return bp.build_plan(c,tw.pdoc(),mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4,calibration=dict(rates))
    def test_the_probe_bound(self):
        self.assertEqual(bp.PROBE_SMOKE_CAP_SECONDS,1200);self.assertEqual(tw.POLICY_DOC['job_deadlines']['smoke'],600)
    def test_a_probe_plan_above_600_s_and_within_the_bound_is_accepted(self):
        p=self.smoke(case(),self.RATES)
        self.assertTrue([s for s in p['sessions'] if s['point'].startswith('probe-')])
        self.assertGreater(p['estimate_seconds'],600);self.assertLessEqual(p['estimate_seconds'],1200);self.assertEqual(p['cap_seconds'],1200)
        self.assertTrue(all(s['estimate_seconds']<=600 and s['deadline_seconds']==600 for s in p['sessions']))
    def test_a_probe_plan_above_the_bound_is_refused(self):
        with self.assertRaises(GateError) as e:self.smoke(case(),dict(self.RATES,**{'py-optimized':0.3}))
        self.assertIn('1200 s',str(e.exception));self.assertIn('probe',str(e.exception))
    def test_a_plan_without_probe_points_keeps_the_600_s_rule(self):
        c=case();c['points']=[q for q in c['points'] if q['name']=='baseline']
        with self.assertRaises(GateError) as e:self.smoke(c,self.RATES)
        self.assertIn('600 s smoke job deadline',str(e.exception))
        self.assertEqual(self.smoke(c,{'py-reference':0.14,'py-optimized':0.0045,'c':0.0004})['cap_seconds'],600)
    def test_a_probe_session_above_the_session_deadline_is_refused(self):
        walls=dict(WALLS);walls[('py-optimized','ma','multi-row')]=2.5          # one probe block above the 600 s session deadline
        cal={'py-reference':0.14,'py-optimized':0.0045,'c':0.0004,'walls':nested(walls)}
        with self.assertRaises(GateError) as e:
            bp.build_plan(case(),tw.pdoc(),mode='smoke',dataset=tw.SMALL,seed=3,envelope=tw.ENV4,calibration=cal)
        self.assertIn('probe-ma-multi-row',str(e.exception));self.assertIn('session cap',str(e.exception))

class WallTests(unittest.TestCase):
    """measured_walls and the evidence binding of the walls."""
    def test_measured_walls_of_a_calibration_run(self):
        row=lambda **k:tw.obs_row(**dict({'point':'p','variant':'py-optimized','selector':'ma','per_unit_s':0.007},**k))
        obs=[row(trial_id='a'),row(trial_id='b',per_unit_s=0.009),row(trial_id='c',per_unit_s=0.001,tier='medium',units=1024),
             row(trial_id='d',per_unit_s=0.5,panel=2,units=12),row(trial_id='e',selector='all',per_unit_s=0.2,tier='tiny',units=1),
             row(trial_id='f',per_unit_s=9.0,scope='kernel'),row(trial_id='g',per_unit_s=9.0,scope='memory'),row(trial_id='h',per_unit_s=9.0,scope='capacity'),
             row(trial_id='i',per_unit_s=9.0,workers=2),row(trial_id='j',per_unit_s=9.0,warmup=True),row(trial_id='k',per_unit_s=9.0,eligible=False)]
        got=bp.measured_walls(obs,tw.POLICY_DOC)
        self.assertEqual(set(got),{'py-optimized'});self.assertEqual(set(got['py-optimized']),{'ma','all'})
        self.assertAlmostEqual(got['py-optimized']['ma']['multi-row'],0.008)      # the median of the small-tier trials (the smallest multi-row tier)
        self.assertAlmostEqual(got['py-optimized']['ma']['one-row'],0.5)          # a panel trial: its wall / (6 x L)
        self.assertAlmostEqual(got['py-optimized']['all']['one-row'],0.2)         # a call of a one-row tier
        with self.assertRaises(GateError):bp.measured_walls([{'scope':'caller','trial_id':'x'}],tw.POLICY_DOC)
    def test_the_calibration_of_a_run_holds_its_walls_and_a_plan_binds_them(self):
        with tempfile.TemporaryDirectory() as t:
            cal,source,_=calibrate(t,cal_rows());p=rule_plan(cal,source)
            self.assertEqual(cal['walls']['py-optimized']['ma']['one-row'],SLOW)
            self.assertEqual(p['calibration'],cal)
            bench.verify_written_plan(case(),tw.pdoc(),copy.deepcopy(p),tw.ENV4,None,None,root=t)
            q=copy.deepcopy(p);q['calibration']['walls']['py-optimized']['ma']['one-row']=0.0045;q['plan_id']=bench.plan_digest(q)
            with self.assertRaises(GateError):bench.verify_written_plan(case(),tw.pdoc(),q,tw.ENV4,None,None,root=t)

if __name__=='__main__':unittest.main()
