import copy, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, bench_plan as bp
CASE=bm.load_case(ROOT,'bench-control-spin');POLICY=bm.load_policy(ROOT)
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
PLAN=bp.build_plan(CASE,POLICY,mode='smoke',dataset={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256},seed=3,envelope=ENV)

def obs():
    out=[]
    for s in PLAN['sessions']:
        for t in s['trials']:
            pooled=t['variant'] in ('py-threads','py-processes')
            out.append({'trial_id':t['trial_id'],'warmup':t['warmup'],'scope':t['scope'],'mode':t['mode'],'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],
                        'work_units':256,'eligible':True,'verdict':{'failures':{},'reduction':'MATCH'},'phase':'caller' if t['scope']=='caller' else 'work',
                        'phases':{'pool_start':5 if pooled and t['mode']=='cold' else None},
                        'pool':{'max_pending':2*t['workers'],'window':2*t['workers'],'chunks':min(t['workers'],256),'chunk_sizes':bp.expected_chunk_sizes(256,t['workers'],14336),
                                'chunk_rule':'one-per-worker','chunk_wall_ns':[1000]*min(t['workers'],256),'pids_distinct':1 if t['variant']=='py-threads' else t['workers'],
                                'caller_pid_included':t['variant']=='py-threads','threads':t['workers'],'start_method':'thread' if t['variant']=='py-threads' else 'spawn',
                                'tracker_session_setup':None if t['variant']=='py-threads' else True} if pooled else None})
    out+=[{'trial_id':m['trial_id'],'warmup':False,'scope':'memory','mode':'warm','variant':m['variant'],'workers':m['workers'],'tier':m['tier'],
           'work_units':256,'eligible':True,'verdict':{'failures':{},'reduction':'MATCH'},'phase':'caller','phases':{}} for m in PLAN['memory']]
    return out
PHASES=[{'phase':'pool_start','variant':v,'workers':w} for v in ('py-threads','py-processes') for w in (1,2,4)]

class RunChecks(unittest.TestCase):
    def test_complete_valid_evidence_passes(self):
        self.assertEqual(bench.check_completeness(PLAN,obs(),POLICY),[]);self.assertEqual(bench.check_caller_semantics(PLAN,obs(),PHASES),[])
    def test_p07_dropped_rows_zero_work_and_missing_rows_are_rejected(self):
        first=lambda o:next(x for x in o if not x['warmup'] and x['scope']=='caller')
        for mutate in [lambda o:first(o).update(work_units=255),lambda o:first(o).update(work_units=0),lambda o:first(o)['verdict'].update(reduction='MISSING_ROWS'),
                       lambda o:o.remove(first(o))]:
            o=obs();mutate(o)
            with self.subTest():self.assertTrue(bench.check_completeness(PLAN,o,POLICY))
    def test_p07_per_selector_row_counting_every_model_is_rejected(self):
        # Task 2 (Amendment G4.3): a per-selector observation whose work units count the rows of three model parts.
        o=obs();row=next(x for x in o if not x['warmup'] and x['scope']=='caller');row.update(selector='unit-one',work_units=3*256)
        self.assertTrue(any('768 of 256 units' in p for p in bench.check_completeness(PLAN,o,POLICY)))
    def test_b13_host_tuning_requests_are_rejected(self):
        from evidence import GateError
        for key in ('host_tuning','drop_caches','cpu_governor','disable_aslr','isolcpus','turbo'):
            with self.subTest(key=key),self.assertRaises(GateError):bench.reject_host_tuning(dict(PLAN,**{key:True}))
        bench.reject_host_tuning(PLAN)
    def test_b13_perturbation_checks(self):
        run={'mode':'smoke'};zero=[{'phase':'control-zero'}]
        self.assertEqual(bench.check_perturbation(run,PLAN,obs(),zero),[])
        self.assertTrue(bench.check_perturbation({'mode':'profile'},PLAN,obs(),zero))
        self.assertTrue(bench.check_perturbation(run,PLAN,obs(),[]))
        o=obs();o[0]['phase']='pool_start';self.assertTrue(bench.check_perturbation(run,PLAN,o,zero))
    def test_b13_cold_pool_must_start_inside_and_warm_outside(self):
        o=obs();cold=next(x for x in o if x['mode']=='cold' and x['variant']=='py-threads' and not x['warmup']);cold['phases']['pool_start']=None
        self.assertTrue(bench.check_caller_semantics(PLAN,o,PHASES))
        self.assertTrue(bench.check_caller_semantics(PLAN,obs(),PHASES[1:]))
    def test_b10_pool_identity(self):
        self.assertEqual(bench.check_concurrency_identity(obs(),PLAN,POLICY),[])
        for mutate in [lambda p:p.update(caller_pid_included=False),lambda p:p.update(pids_distinct=2),lambda p:p.update(max_pending=99)]:
            o=obs();row=next(x for x in o if x['variant']=='py-threads' and not x['warmup'] and x['scope']=='caller');mutate(row['pool'])
            with self.subTest():self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
        o=obs();row=next(x for x in o if x['variant']=='py-processes' and not x['warmup'] and x['workers']==2);row['pool'].update(caller_pid_included=True)
        self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
        o=obs();row=next(x for x in o if x['variant']=='py-processes' and not x['warmup'] and x['scope']=='caller');row['pool']=None
        self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
    def test_b10_chunk_rule_is_enforced(self):
        """Amendment E item 6: every pooled observation records the one-per-worker rule and exactly its chunk sizes."""
        pick=lambda o:next(x for x in o if x['variant']=='py-processes' and not x['warmup'] and x['scope']=='caller' and x['workers']==4)
        for mutate in [lambda p:p.update(chunk_sizes=[128,128]),lambda p:p.update(chunk_rule='max(32, ceil(n / (4 x workers)))'),
                       lambda p:p.update(chunk_sizes=[64,64,64,64,0]),lambda p:p.pop('chunk_sizes')]:
            o=obs();mutate(pick(o)['pool'])
            with self.subTest():self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
        o=obs();self.assertEqual(pick(o)['pool']['chunk_sizes'],[64,64,64,64]);self.assertEqual(bench.check_concurrency_identity(o,PLAN,POLICY),[])
    def test_b10_row_count_per_dataset_kind(self):
        """Amendment E item 6: synthetic -> policy sizes[tier]; local -> the planned prefix length plan['dataset']['rows']."""
        trial=next(t for s in PLAN['sessions'] for t in s['trials'] if t['variant']=='py-threads')
        self.assertEqual(bp.b10_row_count(PLAN,trial,POLICY),POLICY['sizes'][trial['tier']])
        local=dict(PLAN,dataset=dict(PLAN['dataset'],kind='local',size=None,seed=None,sha256='a'*64,rows=1000))
        self.assertEqual(bp.b10_row_count(local,trial,POLICY),1000)
        o=obs();self.assertTrue(bench.check_concurrency_identity(o,local,POLICY))      # sizes for 256 rows do not fit a 1,000-row local plan
    def test_b10_unknown_dataset_kind_is_a_reason_not_an_exception(self):
        """Review Minor 5: an unknown dataset kind gives a B10 problem and an INVALID run_status, never an uncaught GateError."""
        other=dict(PLAN,dataset=dict(PLAN['dataset'],kind='other'))
        problems=bench.check_concurrency_identity(obs(),other,POLICY)
        self.assertTrue(problems);self.assertTrue(all('dataset kind' in p for p in problems))
        status,reasons=bench.run_status(other,obs(),[{'phase':'control-zero'}]+PHASES,POLICY)
        self.assertEqual(status,'INVALID_EXPERIMENT');self.assertTrue(any('dataset kind' in r for r in reasons))
    def test_b10_chunk_times_count_equals_the_chunk_count(self):
        """Review Minor 6: an eligible pooled row records one chunk_wall_ns value per chunk."""
        pick=lambda o:next(x for x in o if x['variant']=='py-threads' and not x['warmup'] and x['scope']=='caller' and x['workers']==2)
        for times in ([],[1000],[1000,1000,1000]):
            o=obs();pick(o)['pool']['chunk_wall_ns']=times
            with self.subTest(times=times):self.assertTrue(any('chunk time' in p for p in bench.check_concurrency_identity(o,PLAN,POLICY)))
        o=obs();pick(o)['pool'].pop('chunk_wall_ns');self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
    def test_b10_every_reason_is_reported_after_a_chunk_problem(self):
        """Task 19b parked item: a chunk-rule mismatch or a row-count error no longer skips the thread/process identity checks."""
        thread=lambda o:next(x for x in o if x['variant']=='py-threads' and not x['warmup'] and x['scope']=='caller' and x['workers']==2)
        proc=lambda o:next(x for x in o if x['variant']=='py-processes' and not x['warmup'] and x['scope']=='caller' and x['workers']==2)
        o=obs();thread(o)['pool'].update(chunk_rule='other',caller_pid_included=False)
        proc(o)['pool'].update(chunk_rule='other',start_method='fork',tracker_session_setup=False)
        problems=bench.check_concurrency_identity(o,PLAN,POLICY);tid,pid=thread(o)['trial_id'],proc(o)['trial_id']
        for want in (f'{tid}: chunk rule',f'{tid}: thread row left',f'{pid}: chunk rule',f'{pid}: process row identity',f'{pid}: resource tracker'):
            with self.subTest(want=want):self.assertTrue(any(p.startswith(want) for p in problems))
        other=dict(PLAN,dataset=dict(PLAN['dataset'],kind='other'));o=obs();thread(o)['pool'].update(caller_pid_included=False)
        problems=bench.check_concurrency_identity(o,other,POLICY)
        self.assertTrue(any(p.startswith(f'{tid}: no B10 row count') for p in problems));self.assertIn(f'{tid}: thread row left the caller process',problems)
    def test_chunk_imbalance_is_the_largest_over_the_median_chunk_time(self):
        """Amendment E item 4: per trial max/median of chunk_wall_ns, summarized over trials; warmups and missing times skipped."""
        o=[{'trial_id':'a','warmup':False,'eligible':True,'pool':{'chunk_wall_ns':[100,100,300]}},
           {'trial_id':'b','warmup':False,'eligible':True,'pool':{'chunk_wall_ns':[200,400]}},
           {'trial_id':'w','warmup':True,'eligible':True,'pool':{'chunk_wall_ns':[1,99]}},{'trial_id':'n','warmup':False,'eligible':True,'pool':None}]
        r=bench.chunk_imbalance(o);self.assertEqual((r['n'],r['min'],r['max']),(2,4/3,3.0))
        self.assertEqual(bench.chunk_imbalance([])['n'],0)
    def test_b10_control_identity_is_relational(self):
        row=lambda v,w,busy,wall:{'scope':'caller','mode':'warm','variant':v,'workers':w,'busy_cpus':{'median':busy},'wall_ns_per_unit':{'median':wall}}
        good=[row('py-threads',1,1.0,2e6),row('py-threads',2,1.0,1e6),row('py-processes',2,1.8,1e6)]
        self.assertEqual(bench.check_control_identity('bench-control-spin',good),[]);self.assertEqual(bench.check_control_identity('bench-control-wait',good),[])
        bad=[row('py-threads',1,1.0,1e6),row('py-threads',2,1.0,1e6),row('py-processes',2,0.9,1e6)]
        self.assertTrue(bench.check_control_identity('bench-control-spin',bad));self.assertTrue(bench.check_control_identity('bench-control-wait',bad))
        self.assertTrue(bench.check_control_identity('bench-control-spin',[]))
    def test_before_run_checks_without_a_project(self):
        self.assertEqual(bench.before_run_checks(ROOT,None,None),([],[]))

# Task 16a additions (parked review items and B09/B10 details beyond the brief's tests).
import contextlib, importlib.util, io, json, os, shutil, tempfile, argparse
spec=importlib.util.spec_from_file_location('bc16',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
PY=str(ROOT/'benchmarks/performance/python')

@contextlib.contextmanager
def framework_python():
    """Import a framework workload module for one test; sys.path and the `tests` package name are restored after."""
    saved=list(sys.path);mods=set(sys.modules)
    sys.path.insert(0,PY)
    try:yield
    finally:
        sys.path[:]=saved
        for name in [m for m in sys.modules if m not in mods and m.split('.')[0] in ('benchlab',)]:del sys.modules[name]

def sample(t,cpu):return {'perf_counter_ns':t,'cpu':{'usage_usec':cpu,'user_usec':cpu,'system_usec':0,'nr_throttled':0,'throttled_usec':0},
                          'memory_stat':None,'memory_current':None,'memory_peak':None,'pids_current':3,'pids_peak':3,'cpu_pressure':None,'memory_pressure':None,
                          'threads':4,'processes':2,'unavailable':{}}

def full_obs():
    out=obs()
    for o in out:o.update(wall_ns=1000,cpu_usage_usec=1,unavailable={})
    return out

def rehash(plan):
    import hashlib
    body={k:v for k,v in plan.items() if k not in ('plan_id','project_dir')}
    return dict(plan,plan_id=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:32])

class Task16aChecks(unittest.TestCase):
    def tmp(self):
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);return d
    def test_reference_evals_schema_and_copy(self):
        # Task 2 (Amendment G3.7): run.json `reference_evals` is optional, {string: integer >= 0}, at most 8 keys; the
        # reference job row carries it and run_cmd copies a well-formed value only.
        good={'m1':10,'m2':0,'m3':123456789012}
        self.assertEqual(bench.reference_evals_of({'status':'PASS','reference_evals':good}),(good,None))
        self.assertEqual(bench.reference_evals_of({'status':'PASS'}),(None,None))
        for bad in ({},{'m1':-1},{'m1':1.5},{'m1':True},{'M1':1},{'k%d'%i:1 for i in range(9)},['m1'],'x',{'a'*17:1}):
            with self.subTest(bad=bad):
                value,reason=bench.reference_evals_of({'status':'PASS','reference_evals':bad})
                self.assertIsNone(value);self.assertEqual(reason,'reference job evaluation counts are malformed')
        schema=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']['reference_evals']
        import jsonschema
        jsonschema.Draft202012Validator(schema).validate(good)
        for bad in ({'m1':-1},{'m1':1.5},{'k%d'%i:1 for i in range(9)},{'M1':1}):
            with self.subTest(schema_bad=bad):self.assertFalse(jsonschema.Draft202012Validator(schema).is_valid(bad))
    def test_coordinator_reads_the_reference_evaluation_counts(self):
        d=self.tmp();p=d/'reference.json.evals'
        self.assertIsNone(bc.reference_evals(p))                                        # an adapter without reference_counts writes none
        p.write_text('{"m1": 3, "m3": 0}');self.assertEqual(bc.reference_evals(p),{'m1':3,'m3':0})
        for bad in ('[]','{}','{"m1": -1}','{"m1": 1.0}','{"m1": true}','{"Bad": 1}','not json',json.dumps({'k%d'%i:1 for i in range(9)})):
            with self.subTest(bad=bad):
                p.write_text(bad)
                with self.assertRaises(ValueError):bc.reference_evals(p)
        self.assertIn("reference_counts",bc.REFERENCE_CODE);self.assertIn("'.evals'",bc.REFERENCE_CODE)
    def test_b10_tracker_session_setup_must_be_true_for_process_rows(self):
        for value in (False,None):
            o=obs();row=next(x for x in o if x['variant']=='py-processes' and not x['warmup'] and x['scope']=='caller');row['pool']['tracker_session_setup']=value
            with self.subTest(value=value):self.assertTrue(bench.check_concurrency_identity(o,PLAN,POLICY))
        self.assertEqual(bench.check_concurrency_identity(obs(),PLAN,POLICY),[])
    def test_task10_model_errors_map_to_an_explicit_verdict_count(self):
        with framework_python():
            from benchlab.trial import verdict_fields
            v={'eligible':False,'failures':{'m1.f1':2},'counts':{'c1':{'m3':3},'c2':{'m1':1,'m2':0}},'x1':{'m1':5},
               'model_errors':{'m1':{'TailCondition':2,'ModelDefect':1},'m3':{'TailCondition':4}},'reduction':'MISMATCH'}
            got=verdict_fields(v)        # FR5, FR5A-03: every project count goes through `counts`; another top-level key is dropped
            self.assertEqual(got,{'eligible':False,'failures':{'m1.f1':2},'reduction':'MISMATCH',
                                  'verdict_counts':{'c1':3,'c2':1},'model_errors':7})
            self.assertEqual(verdict_fields({'eligible':True,'failures':{}})['model_errors'],0)
            self.assertNotIn('verdict_counts',verdict_fields({'eligible':True,'failures':{}}))      # additive: no counts, no key
            for bad in ({'failures':{'x':-1}},{'failures':{'x':True}},{'failures':{},'model_errors':{'m1':{'E':1.5}}},{'failures':{},'counts':{'c1':'3'}},
                        {'failures':{},'counts':{'Bad Name':1}},{'failures':{},'counts':{'c1':-1}},{'failures':{},'counts':[1]},
                        {'failures':{},'counts':{f'c{i}':1 for i in range(17)}},{'failures':{},'counts':{'c'*33:1}}):
                with self.subTest(bad=bad),self.assertRaises(ValueError):verdict_fields(dict(bad,eligible=True))   # Minor 2: never silently 0
            self.assertEqual(len(verdict_fields({'eligible':True,'failures':{},'counts':{f'c{i}':1 for i in range(16)}})['verdict_counts']),16)
        t={'trial_id':'t-b00-00','block':0,'order':0,'point':'smoke-caller','scope':'caller','mode':'warm','variant':'py-reference','workers':'direct','tier':'small','loops':1}
        row=bc.observation({'run_id':'0'*32},t,'caller',{'sample':sample(0,0)},{'msg':{},'sample':sample(10**6,900)},dict(got,work_units=256,result_sha256='a'*64),'safe-c-trial-runner',False)
        self.assertEqual(row['verdict']['model_errors'],7);self.assertEqual(row['verdict']['verdict_counts'],{'c1':3,'c2':1})
        self.assertEqual(sorted(row['verdict']),['failures','model_errors','reduction','verdict_counts'])   # FR5A-03: the framework names no solver count
        from schema_check import validate
        from evidence import GateError
        validate(ROOT,'bench-observation',row)
        for bad in ({'Bad':1},{'c1':-1},{f'c{i}':1 for i in range(17)}):       # FR5: bounded count names and values
            o=dict(row,verdict=dict(row['verdict'],verdict_counts=bad))
            with self.subTest(bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-observation',o)
        o=dict(row,verdict=dict(row['verdict'],c1=0))          # FR5: a project count outside verdict_counts is refused (closed verdict)
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',o)
        obs=[dict(row,verdict=dict(row['verdict'],verdict_counts={'c1':1,'c9':2}))]
        self.assertEqual(bench.undeclared_counts(ROOT,None,obs),['c1','c9'])          # no project: every name is undeclared
        self.assertEqual(bench.undeclared_counts(ROOT,'tests/fixtures/bench-project',obs),['c9'])   # the fixture protocol declares c1, c2
        self.assertEqual(bench.undeclared_counts(ROOT,'tests/fixtures/bench-project',[row]),[])
        row['pool']={'max_pending':1,'chunks':1,'window':2,'pids_distinct':1,'caller_pid_included':True,'threads':1,'start_method':'thread','tracker_session_setup':None,
                     'chunk_rule':'one-per-worker','chunk_sizes':[256],'chunk_wall_ns':[1000]}     # Amendment E fields (closed pool object)
        validate(ROOT,'bench-observation',row)
        from evidence import GateError
        for bad in ({'start_method':'fork'},{'outcome':'ok'},{'max_pending':-1}):
            with self.subTest(bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-observation',dict(row,pool=dict(row['pool'],**bad)))
    def test_phase_split_records_none_for_phases_that_did_not_run(self):
        with framework_python():
            from benchlab.trial import phase_split
            self.assertEqual(phase_split(0,10,30,70,80,True),{'prepare':10,'pool_start':20,'work':40,'materialize':10})
            self.assertEqual(phase_split(0,10,30,70,80,False),{'prepare':10,'pool_start':None,'work':40,'materialize':10})
            self.assertEqual(phase_split(0,10,30,None,None,True),{'prepare':10,'pool_start':20,'work':None,'materialize':None})   # run raised
            self.assertEqual(phase_split(0,None,None,None,None,False),{'prepare':None,'pool_start':None,'work':None,'materialize':None})
    def test_per_trial_values_are_keyed_by_block(self):
        rows=[{'trial_id':f's-b{b:02d}-0{o}','block':b,'warmup':False,'eligible':True,'work_units':4,'loops':1,'wall_ns':400*(b+1)} for b,o in ((0,1),(1,0),(2,3))]
        self.assertEqual(bench.per_trial(rows,'wall_ns'),{0:100.0,1:200.0,2:300.0})
        rows.append(dict(rows[0],trial_id='s-w00',warmup=True,block=None));rows.append(dict(rows[1],trial_id='x',eligible=False))
        self.assertEqual(bench.per_trial(rows,'wall_ns'),{0:100.0,1:200.0,2:300.0})
    def test_busy_cpus_is_one_value_per_trial(self):
        rows=[{'trial_id':'k','block':0,'warmup':False,'eligible':True,'work_units':4,'loops':1,'wall_ns':1000,'cpu_usage_usec':c} for c in (1,2,3)]   # pyperf inner values
        rows.append(dict(rows[0],trial_id='k2',block=1,cpu_usage_usec=4))
        self.assertEqual(bench.per_trial_busy(rows),{0:2.0,1:4.0})
    def test_missing_mandatory_metrics_invalidate_the_run(self):
        zero=PHASES+[{'phase':'control-zero','variant':'py-reference','workers':'direct'}]
        self.assertEqual(bench.run_status(PLAN,full_obs(),zero,POLICY),('VALID',[]))
        for field,value in (('cpu_usage_usec',None),('wall_ns',None),('unavailable',{'cpu.stat':'OSError'})):
            o=full_obs();row=next(x for x in o if not x['warmup'] and x['scope']=='caller');row[field]=value
            with self.subTest(field=field):
                status,reasons=bench.run_status(PLAN,o,zero,POLICY)
                self.assertEqual(status,'INVALID_EXPERIMENT');self.assertTrue(any(row['trial_id'] in r and 'metric' in r for r in reasons),reasons)
        o=full_obs();o[0]['cpu_usage_usec']=None;self.assertEqual(bench.run_status(PLAN,o,zero,POLICY)[0],'VALID')   # a warmup row is not a measurement
    def test_written_plan_must_equal_the_rebuilt_plan(self):
        from evidence import GateError
        bench.verify_written_plan(CASE,POLICY,copy.deepcopy(PLAN),ENV,None,None)
        edits=[lambda p:p.update(plan_id='f'*32),
               lambda p:p['sessions'][0]['trials'].pop(),
               lambda p:p['sessions'][0]['trials'][-1].update(variant='py-optimized'),
               lambda p:p.update(pyperf={'values':1,'warmups':0}),
               lambda p:p.update(seed=4)]
        for i,edit in enumerate(edits):
            p=copy.deepcopy(PLAN);edit(p)
            for q in ([p,rehash(p)] if i else [p]):
                with self.subTest(i=i,rehashed=q is not p),self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,q,ENV,None,None)
        with self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,copy.deepcopy(PLAN),dict(ENV,cpus=2,cpuset=[0,1]),None,None)   # planned for another envelope
        with self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,copy.deepcopy(PLAN),ENV,None,'a'*64)
    def test_written_plan_calibration_is_bound_to_its_recorded_run(self):
        """Task 16a re-review residual: an edited calibration never passes, even with a recomputed plan id."""
        from evidence import GateError
        d=self.tmp();run='a'*32;(d/'artifacts/bench'/run).mkdir(parents=True);path=d/'artifacts/bench'/run/'observations.jsonl'
        row=dict(phase='caller',warmup=False,eligible=True,loops=1,work_units=1000)
        path.write_text(''.join(json.dumps(r)+'\n' for r in [dict(row,trial_id='a',variant='py-optimized',workers='direct',wall_ns=4_000_000_000),
                                                             dict(row,trial_id='e',variant='py-reference',workers='direct',wall_ns=140_000_000_000)]))
        cal,source=bp.calibration_record(d,run,POLICY)
        self.assertEqual(source,{'run_id':run,'observations_sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()})
        ds={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256}
        plan=bp.build_plan(CASE,POLICY,mode='decision',dataset=ds,seed=3,envelope=ENV,calibration=cal,calibration_source=source)
        bench.verify_written_plan(CASE,POLICY,copy.deepcopy(plan),ENV,None,None,root=d)
        edits=[lambda p:p['calibration'].update({'py-reference':p['calibration']['py-reference']*2}),
               lambda p:p.pop('calibration_source'),
               lambda p:p['calibration_source'].update(observations_sha256='0'*64),
               lambda p:p['calibration_source'].update(run_id='b'*32)]
        for i,edit in enumerate(edits):
            p=copy.deepcopy(plan);edit(p)
            with self.subTest(i=i),self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,rehash(p),ENV,None,None,root=d)
        with self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,copy.deepcopy(plan),ENV,None,None)   # no root: the run cannot be read
        unbound=bp.build_plan(CASE,POLICY,mode='decision',dataset=ds,seed=3,envelope=ENV,calibration=cal)
        with self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,unbound,ENV,None,None,root=d)
        with self.assertRaises(GateError):bp.build_plan(CASE,POLICY,mode='decision',dataset=ds,seed=3,envelope=ENV,calibration_source=source)
        path.write_text(path.read_text().replace('4000000000','5000000000'))   # the calibration run changed after the plan was written
        with self.assertRaises(GateError):bench.verify_written_plan(CASE,POLICY,copy.deepcopy(plan),ENV,None,None,root=d)
    def test_case_manifests_are_confined_to_case_directories(self):
        d=self.tmp();(d/'benchmarks/performance/cases').mkdir(parents=True);(d/'p/benchmarks/project/python').mkdir(parents=True)
        (d/'p/benchmarks/project/cases').mkdir();(d/'other').mkdir()
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT,list(sys.path))
        try:
            bc.SRC=d
            self.assertTrue(bc.case_manifest_allowed(str(d/'benchmarks/performance/cases/x.json')))
            self.assertFalse(bc.case_manifest_allowed(str(d/'other/x.json')))
            self.assertFalse(bc.case_manifest_allowed(str(d/'p/benchmarks/project/cases/x.json')))   # no project configured
            out=d/'out';out.mkdir()
            self.assertEqual(bc.job_validate({'deadline_seconds':100,'case_manifest':str(d/'other/x.json')},out)['status'],'FAIL')
            bc.configure_project({'project_dir':'p'})
            self.assertTrue(bc.case_manifest_allowed(str(d/'p/benchmarks/project/cases/x.json')))
            self.assertFalse(bc.case_manifest_allowed(str(d/'other/x.json')))
            self.assertFalse(bc.case_manifest_allowed(str(d/'p/x.json')))
            (d/'p/benchmarks/project/bench.json').write_text(json.dumps({'schema_version':1,'name':'demo','cases':[],'checks':[]}))
            self.assertEqual(bc.project_checks(),[])
            bc.PROJECT_ROOT=(d/'other').resolve()          # bench.json must resolve inside the project directory itself
            self.assertIsNone(bc.project_checks())
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT=saved[:4];sys.path[:]=saved[4]
    def test_child_deadline_is_a_timeout_not_an_exit(self):
        class Chan:
            def pump(self,until,deadline):return None
        class Proc:
            returncode=None
            def poll(self):return None
        c=bc.CallerChild.__new__(bc.CallerChild);c.channel=Chan();c.proc=Proc();c.key='py-threads:1:warm';c.log=self.tmp()/'x.log'
        with self.assertRaises(TimeoutError):c._pump(lambda:False,0)
        Proc.returncode=1;Proc.poll=lambda self:1
        with self.assertRaises(bc.ChildExited):c._pump(lambda:False,0)
    def test_child_exit_detail_is_kept_in_the_failure_row(self):
        """PL-FLAKY-B13-01 diagnostic: a ChildExited failure keeps the child exit code and exception class (bounded, no message text)."""
        class Chan:
            def pump(self,until,deadline):return None
        class Proc:
            returncode=1
            def poll(self):return 1
        log=self.tmp()/'x.log';log.write_text('Traceback (most recent call last):\n  File "x", line 1\nRuntimeError: expected one resource tracker child, found 0\n')
        c=bc.CallerChild.__new__(bc.CallerChild);c.channel=Chan();c.proc=Proc();c.key='py-processes:4:warm';c.log=log
        with self.assertRaises(bc.ChildExited) as caught:c._pump(lambda:False,0)
        self.assertEqual(bc.failure_row(caught.exception),{'status':'FAILED','error_type':'ChildExited','child_exit_code':1,'child_error_class':'RuntimeError'})
        self.assertEqual(bc.failure_row(ValueError('secret text')),{'status':'FAILED','error_type':'ValueError'})
        odd=bc.ChildExited('x');odd.returncode='9'*500;odd.error_class='A'*500    # malformed fields are dropped, never echoed
        self.assertEqual(bc.failure_row(odd),{'status':'FAILED','error_type':'ChildExited','child_exit_code':None,'child_error_class':None})
    def test_framework_opportunity_records_are_confined(self):
        from evidence import GateError
        for rel in ('../outside.json','benchmarks/performance/../../x.json','safety/performance-policy.json'):
            with self.subTest(rel=rel),self.assertRaises(GateError):bm.load_opportunity(ROOT,dict(CASE,opportunity_record=rel))
        # positive control (Amendment A: no tracked framework case holds a record now): a framework record inside the cases directory loads
        d=self.tmp();shutil.copytree(ROOT/'schemas',d/'schemas');(d/bm.CASES).mkdir(parents=True)
        shutil.copy(ROOT/'tests/unit/data/bench-plan-case.opportunity.json',d/bm.CASES/'plan-fixture.opportunity.json')
        fixture=json.loads((ROOT/'tests/unit/data/bench-plan-case.json').read_text())
        self.assertIsNotNone(bm.load_opportunity(d,dict(fixture,opportunity_record=f'{bm.CASES}/plan-fixture.opportunity.json')))
    def test_control_grandchildren_start_isolated(self):
        with framework_python():
            import benchlab.controls as c
            argv=c.child_argv('c.spin(0)')
        self.assertEqual(argv[:3],[sys.executable,'-I','-c'])
        self.assertIn('import benchlab.controls as c',argv[3]);self.assertIn('sys.path[0:0]=',argv[3])
    def recorded(self,status='VALID'):
        d=self.tmp()
        for p in ('safety','schemas'):shutil.copytree(ROOT/p,d/p)
        run_id='1'*32;rd=d/'artifacts/bench'/run_id;rd.mkdir(parents=True)
        def row(tid,block,variant,workers,wall,mode='warm',scope='caller',point='qual-caller'):
            return {'run_id':run_id,'trial_id':tid,'block':block,'warmup':False,'eligible':True,'work_units':256,'loops':1,'wall_ns':wall,'cpu_usage_usec':wall//1000,'point':point,'scope':scope,
                    'mode':mode,'variant':variant,'workers':workers,'tier':'small','phase':'caller'}
        rows=[]                     # 6 blocks; within-row spread 0.2 % (the A/A control is EQUAL), x4 at 0.3 of x1 (FASTER)
        for b in range(6):
            rows+=[row(f'a-b{b:02d}-00',b,'py-reference','direct',2560000+1000*b),row(f'a-b{b:02d}-01',b,'py-threads',2,1280000+1000*b),
                   row(f'a-b{b:02d}-02',b,'py-processes',1,2560000+1000*b),row(f'a-b{b:02d}-03',b,'py-processes',4,768000+1000*b)]
        rows+=[{'run_id':run_id,'trial_id':'memory-py-threads-2-0','warmup':False,'scope':'memory','point':'memory','work_units':256,'mode':'warm','variant':'py-threads','workers':2,'eligible':True,
                'memory':{'group_peak_bytes':10,'ready_current':5}}]
        (rd/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        trial=lambda r:{k:r[k] for k in ('trial_id','block','point','scope','mode','variant','workers','tier','warmup')}   # T16-C1: the plan that recorded these rows
        (rd/'plan.json').write_text(json.dumps({'mode':'decision','sessions':[{'session':'s00','trials':[trial(r) for r in rows if r['scope']!='memory']}],
                                                'memory':[{'trial_id':'memory-py-threads-2-0','point':'memory','mode':'warm','variant':'py-threads','workers':2,'tier':'small'}]}))
        (rd/'phases.jsonl').write_text(json.dumps({'phase':'control-zero','wall_ns':1000})+'\n')
        (rd/'run.json').write_text(json.dumps({'run_id':run_id,'case':'bench-control-spin','mode':'decision','status':status,'runtime':{'python':'3.13.0'},'envelope':{'cpus':4}}))
        return d,run_id,rd
    def quiet(self,fn,d,run_id):
        with contextlib.redirect_stdout(io.StringIO()):return fn(d,argparse.Namespace(run_id=run_id,format='json'))
    def test_compare_and_report_on_recorded_evidence(self):
        d,run_id,rd=self.recorded()
        self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),0);self.assertEqual(self.quiet(bench.report_cmd,d,run_id),0)
        data=json.loads((rd/'compare.json').read_text())
        threads=next(r for r in data['rows'] if r['variant']=='py-threads')
        self.assertEqual(threads['relative_wall_vs_py_reference']['blocks'],6);self.assertEqual(threads['relative_wall_vs_py_reference']['outcome'],'FASTER')
        self.assertEqual(threads['group_peak_bytes']['median'],10)
        self.assertIsNone(next(r for r in data['rows'] if r['variant']=='py-reference')['group_peak_bytes']['median'])
        self.assertEqual(data['controls']['empty_overhead']['median'],1000)
        aa=data['controls']['no_change'];self.assertEqual([c['outcome'] for c in aa],['EQUAL']);self.assertIn('py-reference',aa[0]['control'])
        self.assertEqual([(s['point'],s['mode'],s['outcome']) for s in data['controls']['scaling']],[('qual-caller','warm','FASTER')])   # py-processes x4 versus x1
        self.assertEqual(data['controls']['identity']['status'],'FAIL')        # no py-processes x2 row in this recorded set
        md=(rd/'summary.md').read_text();head=next(l for l in md.splitlines() if l.startswith('| point'))
        for col in ('point','completed units','repetitions','blocks'):self.assertIn(col,head)
        self.assertIn('point',(rd/'summary.csv').read_text().splitlines()[0].split(','))
        with self.assertRaises(bench.GateError):
            (rd/'run.json').write_text(json.dumps({'run_id':run_id,'case':'bench-control-spin','mode':'profile','status':'VALID'}))
            bench.compare_cmd(d,argparse.Namespace(run_id=run_id,format='json'))
    def test_no_change_row_names_its_workers_and_tier(self):
        # T10-APP-05: pressure_blocks filters by the A/A row's workers and tier, so the compare row records both.
        d,run_id,rd=self.recorded()
        self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),0)
        aa=json.loads((rd/'compare.json').read_text())['controls']['no_change']
        self.assertEqual([(c['workers'],c['tier']) for c in aa],[('direct','small')])
    def test_compare_of_an_invalid_run_decides_nothing(self):
        for status in ('INVALID_EXPERIMENT','BLOCKED'):
            d,run_id,rd=self.recorded(status)
            with self.subTest(status=status):
                self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),1);self.assertEqual(self.quiet(bench.report_cmd,d,run_id),1)
                data=json.loads((rd/'compare.json').read_text())
                self.assertTrue(all(r['evidence_quality']==f'invalid run ({status})' for r in data['rows']))
                self.assertTrue(all((r['relative_wall_vs_py_reference'] or {'outcome':'INCONCLUSIVE'})['outcome']=='INCONCLUSIVE' for r in data['rows']))
                self.assertTrue(all(c['outcome']=='INCONCLUSIVE' for c in data['controls']['no_change']+data['controls']['scaling']))
                self.assertIn(f'invalid run ({status})',(rd/'summary.md').read_text())
    def test_invalid_label_wins_over_the_unbound_label(self):           # T16-C1: a run that is both invalid and unbound
        import bench_evidence as be
        for status,label in (('INVALID_EXPERIMENT','invalid run (INVALID_EXPERIMENT)'),('VALID','unbound (recorded before evidence digests; cgroup identity unrecorded)')):
            d,run_id,rd=self.recorded(status)
            with self.subTest(status=status):
                run=json.loads((rd/'run.json').read_text());self.assertTrue(be.is_unbound(be.verify(rd,run)));self.assertNotIn('accounting',run)
                self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),0 if status=='VALID' else 1)
                self.assertEqual({r['evidence_quality'] for r in json.loads((rd/'compare.json').read_text())['rows']},{label})
    def test_report_refuses_when_compare_refused(self):               # T16-C1: no compare.json after a refusal; report exits 1 and writes nothing
        d,run_id,rd=self.recorded()
        obs=(rd/'observations.jsonl').read_text().splitlines();(rd/'observations.jsonl').write_text('\n'.join(obs[1:])+'\n')   # a planned trial has no row
        self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),1);self.assertFalse((rd/'compare.json').exists())
        self.assertEqual(self.quiet(bench.report_cmd,d,run_id),1)
        self.assertFalse((rd/'compare.json').exists());self.assertFalse((rd/'summary.md').exists());self.assertFalse((rd/'summary.json').exists())
    def test_report_refuses_rewritten_evidence(self):                 # H8: report verifies the digests before use
        import bench_evidence as be
        d,run_id,rd=self.recorded();run=json.loads((rd/'run.json').read_text());run['evidence_digests']=be.digest_files(rd);(rd/'run.json').write_text(json.dumps(run))
        self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),0)
        (rd/'observations.jsonl').write_text((rd/'observations.jsonl').read_text()+'\n')
        self.assertEqual(self.quiet(bench.report_cmd,d,run_id),1);self.assertFalse((rd/'summary.md').exists())
    def test_report_labels_the_py_library_row(self):
        """Task 9b review Minor: the compare row, summary.md and summary.csv carry the py-library label (spec Amendment B item 5)."""
        d,run_id,rd=self.recorded();label='C++ library through SWIG; per-evaluation Python callback cost included'
        obs=(rd/'observations.jsonl').read_text().splitlines()
        extra=[json.dumps(dict(json.loads(obs[0]),trial_id=f'a-b{b:02d}-09',block=b,variant='py-library',workers='direct')) for b in range(6)]
        (rd/'observations.jsonl').write_text('\n'.join(obs+extra)+'\n')
        plan=json.loads((rd/'plan.json').read_text())         # T16-APP-02 (ruling T16-C1): the plan that recorded the added rows
        plan['sessions'][0]['trials']+=[{k:json.loads(x)[k] for k in ('trial_id','block','point','scope','mode','variant','workers','tier','warmup')} for x in extra]
        (rd/'plan.json').write_text(json.dumps(plan))
        self.assertEqual(self.quiet(bench.compare_cmd,d,run_id),0);self.assertEqual(self.quiet(bench.report_cmd,d,run_id),0)
        rows=json.loads((rd/'compare.json').read_text())['rows']
        self.assertEqual({r['variant_label'] for r in rows if r['variant']=='py-library'},{label})
        self.assertTrue(all(r['variant_label'] is None for r in rows if r['variant']!='py-library'))
        self.assertIn(label,(rd/'summary.md').read_text())
        import csv
        table=list(csv.DictReader((rd/'summary.csv').read_text().splitlines()))
        self.assertEqual({r['variant_label'] for r in table if r['variant']=='py-library'},{label})
    def test_run_and_compare_commands_are_registered(self):
        for name in ('run','compare','report'):self.assertIn(name,bench.HANDLERS)
        flags=[f for f,_ in bench.ARGUMENTS['run']];self.assertIn('--plan',flags);self.assertIn('--case',flags);self.assertIn('--project',flags)

class RequestLimitIdentity(unittest.TestCase):
    """G-ALO-CO (item I13.1, step 1): bench run compares plan.request_limit with the policy at start; a mismatch is
    INVALID_EXPERIMENT (run-invalid) before any container. The job plans carry the plan's limit to the coordinator."""
    def test_the_plan_limit_must_equal_the_policy_limit(self):
        self.assertEqual(PLAN['request_limit'],POLICY['pools']['request_limit']);self.assertIsNone(bench.plan_request_limit_reason(PLAN,POLICY))
        for bad in (8192,POLICY['pools']['request_limit']+1,None,True,float(POLICY['pools']['request_limit']),str(POLICY['pools']['request_limit'])):
            with self.subTest(limit=bad):
                why=bench.plan_request_limit_reason(dict(PLAN,request_limit=bad),POLICY)
                self.assertTrue(why.startswith('run-invalid: plan request_limit'),why)
        self.assertTrue(bench.plan_request_limit_reason({k:v for k,v in PLAN.items() if k!='request_limit'},POLICY).startswith('run-invalid'))
    def test_a_written_plan_with_another_limit_is_invalid_before_any_container(self):
        import argparse, contextlib, io, json, tempfile
        from unittest import mock
        import container_policy
        d=Path(tempfile.mkdtemp());p=d/'plan.json';plan=dict(PLAN,request_limit=16384)
        import hashlib
        body={k:v for k,v in plan.items() if k not in ('plan_id','project_dir')};plan['plan_id']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:32]
        p.write_text(json.dumps(plan));out=io.StringIO()
        args=argparse.Namespace(case='bench-control-spin',plan=str(p),project=None,format='json',mode='smoke',dataset=None,calibrate=None)
        def no_container(*a,**k):raise AssertionError('no container may start')
        with mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:ENV),\
             mock.patch.object(bench,'doctor_probe',no_container),mock.patch.object(bench,'BenchSession',no_container),contextlib.redirect_stdout(out):
            code=bench.run_cmd(ROOT,args)
        row=json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual((code,row['status']),(1,'INVALID_EXPERIMENT'));self.assertTrue(row['reason'].startswith('run-invalid: plan request_limit'))

if __name__=='__main__':unittest.main()
