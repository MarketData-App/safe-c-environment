import copy, json, math, sys, unittest
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench_model as bm, bench_plan as bp, bench_stats as bs, bench_windows as bw
import schema_check
# Amendment A: a framework fixture with the shape of the Task 2 example manifest (the example case moved to the example project).
CASE=json.loads((ROOT/'tests/unit/data/bench-plan-case.json').read_text());schema_check.validate(ROOT,'bench-case',CASE);POLICY=bm.load_policy(ROOT)
ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'};ENV2=dict(ENV4,cpus=2,cpuset=[0,1],reduced=True)
DS={'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256}

class StatsTests(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(bs.summarize([4,1,3,2]),{'n':4,'median':2.5,'iqr':1.5,'min':1,'max':4})
    def test_bootstrap_is_deterministic_and_resamples_blocks(self):
        base={i:10.0+i%3 for i in range(12)};other={i:5.0+i%2 for i in range(12)}
        a=bs.paired_block_bootstrap(base,other);b=bs.paired_block_bootstrap(base,other)
        self.assertEqual(a,b);self.assertEqual((a['blocks'],a['resamples']),(12,10000));self.assertLessEqual(a['low'],a['ratio']);self.assertLessEqual(a['ratio'],a['high'])
    def test_bootstrap_needs_paired_blocks(self):
        with self.assertRaises(ValueError):bs.paired_block_bootstrap({0:1.0},{1:1.0})

class UnitTests(unittest.TestCase):
    """B02: exact conversions on synthetic records; resolution is declared in the policy, not assumed from scheduling."""
    def test_exact_time_and_byte_conversions(self):
        from fractions import Fraction
        self.assertEqual(bs.convert(1500,'us','ms'),Fraction(3,2));self.assertEqual(bs.convert(1,'s','ns'),10**9);self.assertEqual(bs.convert(250,'ns','us'),Fraction(1,4))
        self.assertEqual(bs.convert(2,'GiB','KiB'),2097152);self.assertEqual(bs.convert(6144,'B','KiB'),6)
        with self.assertRaises(ValueError):bs.convert(1,'s','KiB')
        with self.assertRaises(ValueError):bs.convert(1,'min','s')
    def test_busy_cpu_from_an_exact_record(self):
        from fractions import Fraction
        record={'cpu_usage_usec':1234,'wall_ns':5000000}
        self.assertEqual(bs.convert(record['cpu_usage_usec'],'us','ns')/record['wall_ns'],Fraction(1234000,5000000))
    def test_invalid_denominators(self):
        self.assertEqual(bs.per_unit(10,4),2.5)
        for bad in (0,-1,None,2.5):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bs.per_unit(10,bad)
    def test_resolution_is_declared(self):
        self.assertEqual(POLICY['resolution'],{'perf_counter_ns':1,'cpu_stat_usec':1,'rusage_usec':1,'memory_bytes':4096})

class OutcomeTests(unittest.TestCase):
    """B09: known synthetic datasets; insufficient or noisy evidence is INCONCLUSIVE and never triggers a retry."""
    E=dict(relative=0.05,min_abs=0,min_blocks=3,resamples=2000,seed=7,interval=0.95)
    base={i:10.0+0.01*(i%3) for i in range(12)}
    def test_equal_faster_slower(self):
        self.assertEqual(bs.classify(self.base,dict(self.base),**self.E)['outcome'],'EQUAL')
        self.assertEqual(bs.classify(self.base,{i:v/2 for i,v in self.base.items()},**self.E)['outcome'],'FASTER')
        self.assertEqual(bs.classify(self.base,{i:v*2 for i,v in self.base.items()},**self.E)['outcome'],'SLOWER')
    def test_noisy_missing_and_invalid_are_inconclusive(self):
        noisy={i:(3.0 if i%2 else 30.0) for i in range(12)}
        self.assertEqual(bs.classify(self.base,noisy,**self.E)['outcome'],'INCONCLUSIVE')
        missing={i:v for i,v in self.base.items() if i!=4}
        self.assertEqual(bs.classify(self.base,missing,**self.E)['outcome'],'INCONCLUSIVE')
        self.assertEqual(bs.classify({0:1.0,1:1.0},{0:0.5,1:0.5},**self.E)['outcome'],'INCONCLUSIVE')
        for bad in (0.0,float('nan'),None):
            other=dict(self.base);other[2]=bad
            with self.subTest(bad=bad):self.assertEqual(bs.classify(self.base,other,**self.E)['outcome'],'INCONCLUSIVE')
    def test_correlated_inner_samples_are_one_trial(self):
        self.assertEqual(bs.trial_value([1.0,1.0,1.0,100.0]),1.0)
        one_trial={0:bs.trial_value([5.0]*50)}
        self.assertEqual(bs.classify({0:10.0},one_trial,**self.E)['outcome'],'INCONCLUSIVE')
        with self.assertRaises(ValueError):bs.trial_value([])
    def test_no_retry_api_exists(self):
        import bench_plan
        self.assertFalse([n for n in dir(bs)+dir(bench_plan) if 'retry' in n.lower() or 'rerun' in n.lower()])

class PlanTests(unittest.TestCase):
    def test_smoke_plan_is_complete_and_fits_the_smoke_job(self):
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        caller=[s for s in p['sessions'] if s['scope']=='caller'][0]
        blocks={}
        for t in caller['trials']:
            if not t['warmup']:blocks.setdefault(t['block'],[]).append((t['variant'],t['workers'],t['mode']))
        self.assertEqual(len(blocks),2);self.assertTrue(all(sorted(v)==sorted(blocks[0]) for v in blocks.values()))
        self.assertEqual(len(blocks[0]),2*8);self.assertTrue(all(s['estimate_seconds']<=600 for s in p['sessions']))
        self.assertEqual(len(p['memory']),8)
    def test_plan_records_the_chunk_rule(self):
        """Amendment E item 5: the plan records the chunk rule, the partition, its seed and the request limit (in the plan id)."""
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        self.assertEqual((p['chunk_rule'],p['partition'],p['partition_seed'],p['request_limit']),
                         ('one-per-worker','splitmix64-fisher-yates','0x5AFEC0DE20261007',14336))
    def test_policy_request_limit_must_equal_the_protocol_limit(self):
        """Amendment E item 2 (verdict L1): load_policy refuses pools.request_limit != protocol.max_request_records."""
        import shutil, tempfile
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);shutil.copytree(ROOT/'schemas',d/'schemas');(d/'safety').mkdir()
        v=json.loads((ROOT/'safety/performance-policy.json').read_text());v['pools']['request_limit']=8192
        (d/'safety/performance-policy.json').write_text(json.dumps(v))
        with self.assertRaises(GateError):bm.load_policy(d)
        v['pools']['request_limit']=14336;(d/'safety/performance-policy.json').write_text(json.dumps(v));bm.load_policy(d)
        with mock.patch.object(bm,'validate',lambda root,kind,value:True):       # the host rule holds without the schema constant too
            v['protocol']['max_request_records']=8192;(d/'safety/performance-policy.json').write_text(json.dumps(v))
            with self.assertRaises(GateError):bm.load_policy(d)
    def test_block_order_is_seeded_and_shuffled(self):
        a=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4);b=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        self.assertEqual(a['sessions'],b['sessions'])
    def test_plan_blocks_rows_beyond_envelope(self):
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV2)
        self.assertIn({'variant':'py-threads','workers':4,'reason':'beyond the 2-CPU envelope'},p['blocked_rows'])
        self.assertFalse(any(t['workers']==4 for s in p['sessions'] for t in s['trials']))
    def test_plan_over_cap_is_refused_not_shrunk(self):
        slow={'py-reference':0.140,'py-optimized':0.02,'c':0.0004}
        with self.assertRaises(GateError) as ctx:bp.build_plan(CASE,POLICY,mode='decision',dataset=dict(DS,size='large',rows=13230),seed=1,envelope=ENV4,calibration=slow)
        self.assertIn('8 h',str(ctx.exception))
    def test_group_over_session_cap_splits_whole_blocks(self):
        cal={'py-reference':0.140,'py-optimized':0.006,'c':0.0004}
        p=bp.build_plan(CASE,POLICY,mode='decision',dataset=dict(DS,size='large',rows=13230),seed=1,envelope=ENV4,calibration=cal)
        full=[s for s in p['sessions'] if s['point']=='full-dataset']
        self.assertEqual(p['plan_version'],'v1-split');self.assertGreater(len(full),1)
        self.assertEqual(sum(len({t['block'] for t in s['trials'] if not t['warmup']}) for s in full),12)
        self.assertTrue(all(any(t['warmup'] for t in s['trials']) and s['estimate_seconds']<=10800 for s in full))
    def test_trial_design_check_rejects_inner_values_as_trials(self):
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        obs=[{'trial_id':t['trial_id'],'warmup':t['warmup'],'runner':'safe-c-trial-runner','phase':'caller'} for s in p['sessions'] if s['scope']=='caller' for t in s['trials']]
        obs+=[{'trial_id':t['trial_id'],'warmup':False,'runner':'pyperf','phase':'work'} for s in p['sessions'] if s['scope']=='kernel' for t in s['trials']]
        self.assertEqual(bp.check_trial_design(p,obs),[])
        bad=obs+[dict(obs[-1])]*3;self.assertTrue(bp.check_trial_design(p,bad))
        self.assertTrue(bp.check_trial_design(p,obs[1:]))

# Parked items carried into Task 15 (controller dispatch).

class PerUnitTests(unittest.TestCase):
    """Pre-flight ruling F-07 (ruling 4 of the dispatch): per-unit figures divide by loops x size and use per-trial medians."""
    def test_trial_per_unit_divides_by_loops_times_size(self):
        self.assertEqual(bs.trial_per_unit([1000,1200,90000],loops=4,size=50),1200/200)
        for loops,size in ((0,50),(4,0),(-1,50),(4,None),(2.0,50),(True,50)):
            with self.subTest(loops=loops,size=size),self.assertRaises(ValueError):bs.trial_per_unit([1000],loops=loops,size=size)
    def test_per_trial_values_collapse_inner_samples_by_trial(self):
        obs=[{'trial_id':'k-b00-00','block':0,'warmup':True,'loops':2,'work_units':10,'wall_ns':999999},
             {'trial_id':'k-b00-00','block':0,'warmup':False,'loops':2,'work_units':10,'wall_ns':200},
             {'trial_id':'k-b00-00','block':0,'warmup':False,'loops':2,'work_units':10,'wall_ns':400},
             {'trial_id':'k-b00-00','block':0,'warmup':False,'loops':2,'work_units':10,'wall_ns':9000},
             {'trial_id':'k-b01-00','block':1,'warmup':False,'loops':2,'work_units':10,'wall_ns':100}]
        self.assertEqual(bs.per_trial_values(obs,'wall_ns'),{'k-b00-00':20.0,'k-b01-00':5.0})
        broken=obs+[{'trial_id':'k-b01-00','block':1,'warmup':False,'loops':3,'work_units':10,'wall_ns':100}]
        with self.assertRaises(ValueError):bs.per_trial_values(broken,'wall_ns')
    def test_calibration_uses_per_trial_medians_per_record(self):
        obs=[{'trial_id':'c-b00-00','variant':'py-optimized','phase':'caller','workers':'direct','warmup':False,'eligible':True,'loops':1,'work_units':1000,'wall_ns':5_000_000_000},
             {'trial_id':'k-b00-00','variant':'py-reference','phase':'work','workers':'direct','warmup':False,'eligible':True,'loops':2,'work_units':100,'wall_ns':20_000_000_000},
             {'trial_id':'k-b00-00','variant':'py-reference','phase':'work','workers':'direct','warmup':False,'eligible':True,'loops':2,'work_units':100,'wall_ns':30_000_000_000},
             {'trial_id':'k-b00-00','variant':'py-reference','phase':'work','workers':'direct','warmup':False,'eligible':True,'loops':2,'work_units':100,'wall_ns':900_000_000_000},
             {'trial_id':'k-b00-01','variant':'py-reference','phase':'work','workers':'direct','warmup':True,'eligible':True,'loops':2,'work_units':100,'wall_ns':1}]
        cal=bp.calibration_from_observations(obs,POLICY)
        self.assertEqual(cal,{'py-optimized':0.005,'py-reference':0.15,'c':POLICY['budgets']['estimate_seconds_per_record']['c']})
        with self.assertRaises(GateError):bp.calibration_from_observations(obs[:1],POLICY)

class PointValidationTests(unittest.TestCase):
    """Task 2 review minor: points must reference declared variants, scopes and sizes of the case."""
    def test_declared_points_pass(self):
        self.assertEqual(bp.point_problems(CASE,POLICY),[])
        self.assertEqual(bp.point_problems(bm.load_case(ROOT,'record-scan'),POLICY),[])
    def test_undeclared_references_are_refused(self):
        for key,value in (('variants',['py-reference','c-vector']),('scope','throughput'),('size','huge')):
            case=copy.deepcopy(CASE);case['points'][0][key]=value
            with self.subTest(key=key):
                self.assertTrue(bp.point_problems(case,POLICY))
                with self.assertRaises(GateError):bp.build_plan(case,POLICY,mode='decision',dataset=DS,seed=1,envelope=ENV4)
    def test_size_declared_by_case_but_not_policy_is_refused(self):
        case=copy.deepcopy(CASE);case['sizes']=case['sizes']+['huge'];case['points'][0]['size']='huge'
        self.assertTrue(bp.point_problems(case,POLICY))

class PlanCapAndPrivacyTests(unittest.TestCase):
    def test_split_plan_keeps_every_block_and_row(self):
        cal={'py-reference':0.140,'py-optimized':0.006,'c':0.0004}
        p=bp.build_plan(CASE,POLICY,mode='decision',dataset=dict(DS,size='large',rows=13230),seed=1,envelope=ENV4,calibration=cal)
        for s in p['sessions']:
            per_block={}
            for t in s['trials']:
                if not t['warmup']:per_block.setdefault(t['block'],0);per_block[t['block']]+=1
            self.assertEqual(len(set(per_block.values())),1)
        primary=[s for s in p['sessions'] if s['class']=='primary']
        for name in {s['point'] for s in primary}:
            self.assertEqual(len({t['block'] for s in primary if s['point']==name for t in s['trials'] if not t['warmup']}),12)
        self.assertLessEqual(p['estimate_seconds'],28800)
    def test_one_block_over_the_session_cap_is_refused(self):
        cal={'py-reference':0.140,'py-optimized':0.2,'c':0.0004}
        with self.assertRaises(GateError) as ctx:bp.build_plan(CASE,POLICY,mode='decision',dataset=dict(DS,size='large',rows=13230),seed=1,envelope=ENV4,calibration=cal)
        self.assertIn('session cap',str(ctx.exception))
    def test_plan_never_holds_the_fixture_path(self):
        secret='/srv/fixtures/private/fixture-dataset.json'
        local={'kind':'local','size':'small','seed':None,'sha256':'0'*64,'rows':256,'path':secret}
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=local,seed=1,envelope=ENV4)
        import json
        self.assertNotIn(secret,json.dumps(p));self.assertNotIn('path',p['dataset']);self.assertIn('path',local)
        q=bp.build_plan(CASE,POLICY,mode='smoke',dataset=dict(local,path='/elsewhere'),seed=1,envelope=ENV4)
        self.assertEqual(p['plan_id'],q['plan_id'])
    def test_parse_dataset(self):
        self.assertEqual(bp.parse_dataset(ROOT,'synthetic:small',POLICY),DS)
        for bad in ('synthetic:huge','remote:x','small'):
            with self.subTest(bad=bad),self.assertRaises(GateError):bp.parse_dataset(ROOT,bad,POLICY)
    def test_calibration_run_id_is_checked(self):
        for bad in ('../x','',None,'A'*32):
            with self.subTest(bad=bad),self.assertRaises(GateError):bp.calibration_run_dir(ROOT,bad)

# Task 15 review fixes.

class ReviewFixTests(unittest.TestCase):
    E=dict(relative=0.05,min_abs=0,min_blocks=3,resamples=200,seed=7,interval=0.95)
    def test_seed_is_recorded_and_bound_to_the_plan_id(self):
        a=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4);b=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=2,envelope=ENV4)
        self.assertEqual((a['seed'],b['seed']),(1,2));self.assertNotEqual(a['plan_id'],b['plan_id'])
        order=lambda p:[(t['variant'],t['workers'],t['mode']) for s in p['sessions'] for t in s['trials'] if not t['warmup']]
        self.assertNotEqual(order(a),order(b));self.assertEqual(sorted(order(a)),sorted(order(b)))
    def test_dataset_keys_are_an_allowlist(self):
        local={'kind':'local','size':'small','seed':None,'sha256':'0'*64,'rows':256,'path':'/srv/x.json','source_label':'owner dataset'}
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=local,seed=1,envelope=ENV4)
        self.assertEqual(sorted(p['dataset']),['kind','rows','seed','sha256','size'])
    def test_classify_parameters_are_checked(self):
        base={i:10.0 for i in range(4)}
        for bad in (dict(min_blocks=1),dict(min_blocks=0),dict(resamples=0),dict(interval=0.0),dict(interval=1.0),dict(interval=1.5)):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bs.classify(base,dict(base),**dict(self.E,**bad))
    def test_classify_accepts_exact_real_values(self):
        from fractions import Fraction
        base={i:Fraction(10)+Fraction(i%3,100) for i in range(12)}
        self.assertEqual(bs.classify(base,dict(base),**self.E)['outcome'],'EQUAL')
        self.assertEqual(bs.classify(base,{i:v/2 for i,v in base.items()},**self.E)['outcome'],'FASTER')
        other=dict(base);other[1]=True
        self.assertEqual(bs.classify(base,other,**self.E)['outcome'],'INCONCLUSIVE')
    def test_estimate_counts_overhead_once_and_uses_calibrated_reference(self):
        p=bp.build_plan(CASE,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        mem=sum(bp.trial_estimate(POLICY,m['variant'],POLICY['sizes'][m['tier']],1) for m in p['memory'])
        self.assertEqual(p['estimate_seconds'],round(sum(s['estimate_seconds'] for s in p['sessions'])+mem,1))
        cal={'py-reference':0.2,'py-optimized':0.0045,'c':0.0004};large=dict(DS,size='large',rows=13230)
        q=bp.build_plan(CASE,POLICY,mode='decision',dataset=large,seed=1,envelope=ENV4,calibration=cal)
        mem=sum(bp.trial_estimate(POLICY,m['variant'],POLICY['sizes'][m['tier']],1,cal) for m in q['memory'])
        self.assertAlmostEqual(q['estimate_seconds'],sum(s['estimate_seconds'] for s in q['sessions'])+mem+13230*0.2,delta=0.1)
    def test_smoke_total_over_the_job_deadline_is_refused(self):
        cal={'py-reference':0.14,'py-optimized':0.035,'c':0.0004}
        case=copy.deepcopy(CASE);case['points']=[p for p in case['points'] if p['name']!='crossover-tiny']   # T6-R7 (R87): no probe point, so the 600 s rule
        with self.assertRaises(GateError) as ctx:bp.build_plan(case,POLICY,mode='smoke',dataset=DS,seed=1,envelope=ENV4,calibration=cal)
        self.assertIn('smoke',str(ctx.exception))
    def test_memory_trial_over_its_limit_is_refused(self):
        policy=copy.deepcopy(POLICY);policy['job_deadlines']['memory']=60
        with self.assertRaises(GateError) as ctx:bp.build_plan(CASE,policy,mode='decision',dataset=dict(DS,size='large',rows=13230),seed=1,envelope=ENV4)
        self.assertIn('memory',str(ctx.exception))
    def test_invalid_loops_are_refused(self):
        self.assertEqual(bp.trial_estimate(POLICY,'c-serial',100,2),100*0.0004*2+2.0)
        for bad in (0,-1,1.5,True,None):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bp.trial_estimate(POLICY,'py-optimized',256,bad)
    def test_unknown_point_class_or_mode_is_a_plan_problem(self):
        for key,value in (('class','tertiary'),('modes',[]),('modes',['warm','hot']),('modes',['direct'])):
            case=copy.deepcopy(CASE);case['points'][0][key]=value
            with self.subTest(key=key,value=value):self.assertTrue(bp.point_problems(case,POLICY))
    def test_calibration_uses_only_single_worker_rows(self):
        row=dict(phase='caller',warmup=False,eligible=True,loops=1,work_units=1000)
        obs=[dict(row,trial_id='a',variant='py-optimized',workers='direct',wall_ns=4_000_000_000),
             dict(row,trial_id='b',variant='py-processes',workers=1,wall_ns=6_000_000_000),
             dict(row,trial_id='c',variant='py-processes',workers=4,wall_ns=1_000_000_000),
             dict(row,trial_id='d',variant='py-threads',workers=2,wall_ns=1_000_000_000),
             dict(row,trial_id='e',variant='py-reference',workers='direct',wall_ns=140_000_000_000)]
        self.assertEqual(bp.calibration_from_observations(obs,POLICY)['py-optimized'],0.005)
    def test_malformed_calibration_is_blocked(self):
        import tempfile
        run='0'*32
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/'artifacts/bench'/run;d.mkdir(parents=True)
            for text in ('{not json\n','{"trial_id":"a"}\n','[1,2]\n'):
                (d/'observations.jsonl').write_text(text)
                with self.subTest(text=text),self.assertRaises(GateError):bp.load_calibration(tmp,run,POLICY)

class PyLibraryPlanTests(unittest.TestCase):
    """Task 9b (spec Amendment B items 5 and 6): the py-library row is a direct Python row with its own family."""
    def case(self):
        case=copy.deepcopy(CASE)
        case['variants'].insert(2,{'id':'py-library','language':'python-library','workers':['direct'],'status':'implemented',
                                   'reason':'a compiled library through a Python binding; per-evaluation Python callback cost included'})
        for p in case['points']:
            if p['name']!='language-only':p['variants']=p['variants']+['py-library']
        schema_check.validate(ROOT,'bench-case',case);bm.case_rules(ROOT,case);return case
    def test_py_library_row_is_planned_and_estimated(self):
        case=self.case();rows,_=bp.python_rows(case,ENV4)
        self.assertIn({'variant':'py-library','workers':'direct'},rows)
        self.assertEqual(bp.family('py-library'),'py-library')
        self.assertEqual(POLICY['budgets']['estimate_seconds_per_record']['py-library'],0.005)
        self.assertAlmostEqual(bp.trial_estimate(POLICY,'py-library',1024),1024*0.005+POLICY['budgets']['trial_overhead_seconds'])
        p=bp.build_plan(case,POLICY,mode='decision',dataset=dict(DS,size='medium',rows=1024),seed=1,envelope=ENV4)
        by_point={}
        for s in p['sessions']:by_point.setdefault(s['point'],set()).update(t['variant'] for t in s['trials'])
        self.assertNotIn('py-library',by_point['language-only'])
        for name in ('baseline','full-dataset','crossover-tiny','crossover-small'):self.assertIn('py-library',by_point[name],name)
        rows_at={s['point']:{(t['variant'],t['workers']) for t in s['trials']} for s in p['sessions']}
        self.assertEqual(len(rows_at['baseline']),9)        # 9 Python rows here; with the 4 planned C rows the spec counts 13
    def test_calibration_gains_the_py_library_family(self):
        row=dict(phase='caller',warmup=False,eligible=True,loops=1,work_units=1000,workers='direct')
        obs=[dict(row,trial_id='a',variant='py-optimized',wall_ns=4_000_000_000),dict(row,trial_id='b',variant='py-reference',wall_ns=140_000_000_000),
             dict(row,trial_id='c',variant='py-library',wall_ns=6_000_000_000)]
        cal=bp.calibration_from_observations(obs,POLICY)
        self.assertEqual((cal['py-library'],cal['py-optimized'],cal['py-reference']),(0.006,0.004,0.14))
        self.assertEqual(bp.trial_estimate(POLICY,'py-library',1000,calibration=cal),1000*0.006+POLICY['budgets']['trial_overhead_seconds'])
        self.assertNotIn('py-library',bp.calibration_from_observations(obs[:2],POLICY))
        with self.assertRaises(GateError):bp.trial_estimate(POLICY,'py-library',1000,calibration=bp.calibration_from_observations(obs[:2],POLICY))
        with self.assertRaises(GateError) as ctx:bp.calibration_from_observations(obs[1:],POLICY)
        self.assertIn('py-optimized',str(ctx.exception));self.assertIn('lacks eligible rows',str(ctx.exception))
        with mock.patch.object(bp,'family',lambda v:'py-other' if v=='py-library' else 'py-optimized' if v=='py-optimized' else 'py-reference'):
            with self.assertRaises(GateError) as ctx:bp.calibration_from_observations(obs,POLICY)
        self.assertIn('unknown family py-other',str(ctx.exception))
    def test_the_required_families_follow_the_case(self):       # EX-18b: a case without a py-optimized row needs no py-optimized rate
        obs=[{'warmup':False,'eligible':True,'work_units':256,'phase':'caller','workers':'direct','variant':'py-reference','trial_id':f't{b}','block':b,
              'loops':1,'wall_ns':256*1000} for b in range(2)]
        with self.assertRaises(GateError):bp.calibration_from_observations(obs,POLICY)
        self.assertEqual(sorted(bp.calibration_from_observations(obs,POLICY,required=('py-reference',))),['c','py-reference'])
        case={'variants':[{'id':'py-reference','language':'python','status':'implemented'},{'id':'py-optimized','language':'python','status':'same-as-reference'},
                          {'id':'c-serial','language':'c','status':'implemented'}]}
        self.assertEqual(bp.calibration_families(case),('py-reference',))
        self.assertEqual(bp.calibration_families({'variants':[dict(v,status='implemented') for v in case['variants']]}),('py-reference','py-optimized'))
        self.assertEqual(bp.calibration_families(None),('py-reference','py-optimized'))

# EX-18b (Phase 3 addendum Task A8, Amendment H15.1): the deterministic 24-hour split of a window plan (bench_windows)
L=86400-1800
def grp(gid,order,secs,ref=0.0):return {'id':gid,'order':order,'sessions':[{'id':f'{gid}-s{i}','seconds':s} for i,s in enumerate(secs)],'reference':ref}

class SplitTests(unittest.TestCase):                    # Amendment H15.1 split tests
    def test_group_just_under_L_stays_one_group(self):
        self.assertEqual(len(bw.cut(grp('mc/full-dataset',2,[L-1000.0],ref=999.0),L)),1)
    def test_greedy_cut_points(self):
        g=grp('me/full-dataset',4,[(2*L+1)/9]*9);parts=bw.cut(g,L)
        self.assertEqual([len(p['sessions']) for p in parts],[4,4,1])
    def test_indivisible_part_refuses(self):
        with self.assertRaises(bw.PlanRefusal) as e:bw.cut(grp('me/full-dataset',4,[1000.0],ref=L),L)
        self.assertEqual(e.exception.reason,'window-cap-infeasible')
    def test_every_window_with_controls_is_within_a_day(self):
        gs=[grp('mc/full-dataset',2,[10000.0]*5,ref=1852.0),grp('me/full-dataset',4,[10000.0]*8,ref=5000.0),grp('one',5,[5000.0]),grp('diag',6,[900.0])]
        wins=bw.split_windows(gs,1800.0)
        self.assertTrue(all(w['estimate']<=86400 for w in wins));self.assertEqual([w['id'] for w in wins][:2],['1a','1b'])
    def test_loop_ends_only_at_one_group_per_window(self):
        gs=[grp(f'g{i}',i,[50000.0]) for i in range(3)]               # W = 151,800 s: n starts at 2, two groups do not fit one window
        self.assertEqual(math.ceil((1800.0+3*50000.0)/86400),2)
        wins=bw.split_windows(gs,1800.0)
        self.assertEqual((len(wins),[len(w['parts']) for w in wins]),(3,[1,1,1]))
    def test_session_above_the_cap_refuses(self):
        with self.assertRaises(bw.PlanRefusal) as e:bw.check_sessions([grp('mc/full-dataset',2,[10800.5])])
        self.assertEqual(e.exception.reason,'session-cap-infeasible')
        bw.check_sessions([grp('mc/full-dataset',2,[10800.0])])                 # exactly at the cap
    def test_look2_is_bounded_by_its_window(self):
        w=bw.split_windows([grp('mc/full-dataset',2,[10000.0]*3,ref=1852.0),grp('diag',6,[900.0])],1800.0)[0]
        self.assertLessEqual(bw.look2_worst_case(w,1800.0),w['estimate'])
    def test_cap_formula(self):
        self.assertEqual(bw.cap(754*60),600*math.ceil(1.2*754*60/600))
        self.assertEqual(bw.cap(754*60,1.5,300),300*math.ceil(1.5*754*60/300))       # the protocol's headroom and step
    def test_equal_count_partitions_resolve_to_the_greedy_one(self):
        g=grp('me/full-dataset',4,[30000.0,30000.0,30000.0,30000.0])     # [2,2] and [3,1] both give 2 parts; greedy is [2,2] at L = 84,600
        self.assertEqual([len(p['sessions']) for p in bw.cut(g,L)],[2,2])
    def test_a_shorter_protocol_window_splits_earlier(self):
        gs=[grp(f'g{i}',i,[20000.0]) for i in range(3)]
        self.assertEqual(len(bw.split_windows(gs,1800.0)),1);self.assertEqual(len(bw.split_windows(gs,1800.0,day=43200)),2)
    # EX-18c (EX18b-A09): the exact bounds of the cut and of the window
    def test_a_part_exactly_at_L_is_one_part_and_one_past_refuses(self):
        parts=bw.cut(grp('mc/full-dataset',2,[L-999.0],ref=999.0),L)
        self.assertEqual((len(parts),parts[0]['estimate']),(1,float(L)))
        with self.assertRaises(bw.PlanRefusal) as e:bw.cut(grp('mc/full-dataset',2,[L-998.0],ref=999.0),L)       # L + 1: indivisible
        self.assertEqual(e.exception.reason,'window-cap-infeasible');self.assertEqual(e.exception.estimates[0]['estimate'],L+1.0)
        self.assertEqual([len(p['sessions']) for p in bw.cut(grp('mc/full-dataset',2,[L/2,L/2]),L)],[2])          # two sessions summing to L
        self.assertEqual([len(p['sessions']) for p in bw.cut(grp('mc/full-dataset',2,[L/2,L/2+1.0]),L)],[1,1])    # to L + 1
    def test_a_window_exactly_at_the_window_length_and_one_past(self):
        wins=bw.split_windows([grp('g0',0,[L/2]),grp('g1',1,[L/2])],1800.0)                # 1,800 + 2 x 42,300 = 86,400 s
        self.assertEqual([(w['id'],w['estimate']) for w in wins],[('1a',86400.0)])
        wins=bw.split_windows([grp('g0',0,[L/2]),grp('g1',1,[L/2+1.0])],1800.0)            # 86,401 s: two windows
        self.assertEqual([w['estimate'] for w in wins],[1800.0+L/2+1.0,1800.0+L/2])
        wins=bw.split_windows([grp('g0',0,[20000.0]),grp('g1',1,[21400.0])],1800.0,day=43200)   # a protocol window length: exactly 43,200 s
        self.assertEqual([w['estimate'] for w in wins],[43200.0])
