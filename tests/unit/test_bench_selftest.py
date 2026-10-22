import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, bench_plan as bp, project_model
spec=importlib.util.spec_from_file_location('bench_coordinator_selftest',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
POLICY=bm.load_policy(ROOT);MIB=1048576
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
DS={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256}
EMPTY_SHA='44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'      # sha256 of the shared test file body '{}' (DD-01)

class SelftestInventoryTests(unittest.TestCase):
    def test_contract_requires_the_bench_gates(self):
        c=json.loads((ROOT/'safety/contract.json').read_text())
        self.assertIn('bench-doctor',c['required_gates']);self.assertIn('bench-selftest',c['required_gates'])
        names={(s['parent'],s['name']) for s in c['subcases']}
        for row in bm.load_fixtures(ROOT)['pipeline_subcases']:self.assertIn((row['parent'],row['name']),names)
    def test_phase_one_b_inventory(self):
        rows={b['id']:b['name'] for b in bm.load_fixtures(ROOT)['b_cases'] if b['phase']==1}
        self.assertEqual(rows,{'B01':'tool-manifest-runner-qualification','B02':'wall-versus-cpu-and-units','B03':'descendant-and-short-lived-worker-cpu',
                               'B05':'whole-workload-memory-and-peak','B09':'statistics-and-unstable-outcomes','B10':'python-concurrency-and-runtime-identity',
                               'B13':'measurement-perturbation-and-cache-policy'})
    def test_benchmarks_is_a_framework_directory(self):
        self.assertIn('benchmarks',project_model.FRAMEWORK_DIRS);self.assertIn('benchmarks/project/',project_model._NOT_FRAMEWORK)
    def test_doctor_status_needs_an_envelope(self):
        self.assertEqual(bench.doctor_status({'status':'PASS'},None),'BLOCKED')
        self.assertEqual(bench.doctor_status({'status':'PASS'},{'cpus':4}),'PASS')
        self.assertEqual(bench.doctor_status({'status':'BLOCKED'},{'cpus':4}),'BLOCKED')
        self.assertEqual(bench.doctor_status({},{'cpus':4}),'BLOCKED')
    def test_every_pipeline_variant_has_one_addition_shape(self):
        row=bench._sub('P07','bench-missing-work-or-rows','zero-work-units',True,True,[],'r')
        self.assertEqual(set(row),{'parent','name','variant','status','control','evidence_paths','reason'})
        self.assertEqual((row['status'],row['control']),('PASS','PASS'))
        self.assertEqual(bench._sub('P07','n','v',True,False,[],'r')['status'],'FAIL')   # a failed control never yields PASS
        self.assertEqual(bench._sub('P07','n','v',False,True,[],'r')['status'],'FAIL')   # an accepted mutation is a FAIL

class CoordinatorMutationTests(unittest.TestCase):
    """The doctor mutations act only in a selftest plan (Task 19a)."""
    def doctor(self,plan):
        saved=(bc.CG,bc.WORK,list(sys.path),list(sys.meta_path))
        with tempfile.TemporaryDirectory() as d:
            cg=Path(d)/'cg';cg.mkdir();work=Path(d)/'work';work.mkdir()
            for name,text in {'cpu.stat':'usage_usec 1\nuser_usec 1\nsystem_usec 0\nnr_throttled 0\nthrottled_usec 0\n','memory.stat':'anon 1\nfile 1\nshmem 0\n',
                              'memory.current':'1\n','pids.current':'1\n','cgroup.procs':'','cpuset.cpus.effective':'0-3\n'}.items():(cg/name).write_text(text)
            (Path(d)/'selftestwheel.py').write_text("__version__='1.0'\n")
            try:
                bc.CG=cg;bc.WORK=work;sys.path.insert(0,d)
                return bc.job_doctor(dict({'job':'doctor','expected':{'selftestwheel':'1.0'}},**plan),work)
            finally:
                bc.CG,bc.WORK=saved[0],saved[1];sys.path[:]=saved[2];sys.meta_path[:]=saved[3];sys.modules.pop('selftestwheel',None)
    def test_hidden_counter_is_missing_only_in_a_selftest(self):
        self.assertEqual(self.doctor({})['missing_counters'],[])
        r=self.doctor({'selftest':True,'mutation':'hide-counter:cpu.stat'})
        self.assertEqual(r['missing_counters'],['cpu.stat']);self.assertEqual(r['status'],'BLOCKED')
    def test_hidden_module_is_unavailable_only_in_a_selftest(self):
        self.assertEqual(self.doctor({})['libraries'],{'selftestwheel':'MATCH'})
        sys.modules['selftestwheel']=type(sys)('selftestwheel');sys.modules['selftestwheel'].__version__='1.0'   # already imported: still hidden
        r=self.doctor({'selftest':True,'mutation':'hide-module:selftestwheel'})
        self.assertEqual(r['libraries'],{'selftestwheel':'UNAVAILABLE'});self.assertEqual(r['status'],'BLOCKED')

class MutationPlanTests(unittest.TestCase):
    """Review Minor 3: a mutation without selftest=true, or an unknown mutation, is refused before any job runs."""
    EXPECTED={'pyperf':'2.9.0'}
    def test_mutation_rules(self):
        ok=lambda **p:bc.selftest_mutation(dict({'job':'doctor','expected':self.EXPECTED},**p))
        self.assertEqual(ok(),'');self.assertEqual(ok(selftest=True,mutation='hide-counter:cpu.stat'),'hide-counter:cpu.stat')
        self.assertEqual(ok(selftest=True,mutation='hide-module:pyperf'),'hide-module:pyperf')
        for bad in ({'mutation':'hide-counter:cpu.stat'},{'selftest':'true','mutation':'hide-counter:cpu.stat'},{'selftest':True},
                    {'selftest':True,'mutation':'hide-counter:cpu.weight'},{'selftest':True,'mutation':'hide-counter:../cpu.stat'},
                    {'selftest':True,'mutation':'hide-module:os'},{'selftest':True,'mutation':'erase:all'},{'selftest':True,'mutation':['hide-module:pyperf']},
                    {'selftest':True,'mutation':'hide-counter:cpu.stat','job':'timing'},{'selftest':False,'mutation':'hide-counter:cpu.stat'}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):ok(**bad)
    def test_doctor_job_is_registered(self):
        self.assertIs(bc.JOBS['doctor'],bc.job_doctor)       # the validator is a helper, never the registered job
    def test_main_refuses_before_running_the_job(self):
        calls=[];saved=(bc.WORK,bc.JOBS['doctor'])
        with tempfile.TemporaryDirectory() as d:
            try:
                bc.WORK=Path(d);bc.JOBS['doctor']=lambda plan,out:calls.append(plan) or {'status':'PASS'}
                for bad in ({'mutation':'hide-counter:cpu.stat'},{'selftest':True,'mutation':'hide-module:os'}):
                    (Path(d)/'plan.json').write_text(json.dumps(dict({'schema_version':1,'job':'doctor','expected':self.EXPECTED},**bad)))
                    with self.subTest(bad=bad):
                        self.assertEqual(bc.main(['x','plan.json']),1)
                        self.assertEqual(json.loads((Path(d)/'bench/out/result.json').read_text())['reason'],'selftest mutation rejected')
                self.assertEqual(calls,[])
            finally:bc.WORK,bc.JOBS['doctor']=saved

class DoctorStatusTests(unittest.TestCase):
    """Review Minor 2: the control doctor needs a passed job; a mutated doctor job is expected to exit BLOCKED."""
    def test_control_needs_a_passed_job(self):
        self.assertEqual(bench.doctor_job_status(True,{'status':'PASS'},{'cpus':4}),'PASS')
        self.assertEqual(bench.doctor_job_status(False,{'status':'PASS'},{'cpus':4}),'BLOCKED')   # failed job, PASS row
        self.assertEqual(bench.doctor_job_status(True,{'status':'PASS'},None),'BLOCKED')
    def test_mutated_job_row_decides(self):
        self.assertEqual(bench.doctor_job_status(False,{'status':'BLOCKED'},{'cpus':4},mutated=True),'BLOCKED')
        self.assertEqual(bench.doctor_job_status(False,{'status':'PASS'},{'cpus':4},mutated=True),'PASS')    # a mutation that went unseen
        self.assertEqual(bench.doctor_job_status(False,{},{'cpus':4},mutated=True),'BLOCKED')

def plan_and_obs():
    case=bm.load_case(ROOT,'bench-control-spin');plan=bp.build_plan(case,POLICY,mode='smoke',dataset=DS,seed=3,envelope=ENV);out=[]
    for s in plan['sessions']:
        for t in s['trials']:
            pooled=t['variant'] in bench.POOLED
            out.append({'schema_version':1,'run_id':'0'*32,'runner':'safe-c-trial-runner','block':t['block'],'order':t['order'],'point':t['point'],'loops':1,
                        'cpu_user_usec':1,'cpu_system_usec':0,'nr_throttled':0,'throttled_usec':0,'pids_start':1,'pids_end':1,'threads_start':1,'threads_end':1,
                        'result_sha256':'e'*64,'memory':None,
                        'trial_id':t['trial_id'],'warmup':t['warmup'],'scope':t['scope'],'mode':t['mode'],'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],
                        'work_units':256,'eligible':True,'verdict':{'failures':{},'reduction':'MATCH'},'phase':'caller' if t['scope']=='caller' else 'work',
                        'wall_ns':1000*(t['block'] or 0)+1000,'cpu_usage_usec':1,'unavailable':{},'phases':{'pool_start':5 if pooled and t['mode']=='cold' else None},
                        'pool':{'max_pending':2*t['workers'],'window':2*t['workers'],'chunks':min(t['workers'],256),'chunk_sizes':bp.expected_chunk_sizes(256,t['workers'],14336),
                                'chunk_rule':'one-per-worker','chunk_wall_ns':[1000]*min(t['workers'],256),'pids_distinct':1 if t['variant']=='py-threads' else t['workers'],
                                'caller_pid_included':t['variant']=='py-threads','threads':t['workers'],'start_method':'thread' if t['variant']=='py-threads' else 'spawn',
                                'tracker_session_setup':None if t['variant']=='py-threads' else True} if pooled else None})
    out+=[{'trial_id':m['trial_id'],'warmup':False,'scope':'memory','mode':'warm','variant':m['variant'],'workers':m['workers'],'tier':m['tier'],
           'work_units':256,'eligible':True,'verdict':{'failures':{},'reduction':'MATCH'},'phase':'caller','phases':{}} for m in plan['memory']]
    phases=[{'phase':'pool_start','variant':v,'workers':w} for v in bench.POOLED for w in (1,2,4)]+[{'phase':'control-zero','variant':'py-reference','workers':'direct'}]
    return plan,out,phases

def controls():
    r=lambda name,ratio,**extra:{'name':name,'wall_ns':10**9,'cpu_usage_usec':int(ratio*10**6),'cpu_user_usec':0,'cpu_system_usec':0,'extra':extra,'unavailable':{}}
    cpu=[r('control-zero',0.0),r('wait',0.01),r('spin',1.0),r('spin-children-2',2.0),
         r('native-spin',1.0,children_cpu_usec=950000,parent_self_cpu_usec=20000),r('short-children-20',1.2,children_cpu_usec=1150000,parent_self_cpu_usec=30000,children=20,
           polled_tree_cpu_usec=31000,polled_label='lower bound: live process tree sampled at the handshakes')]
    m=lambda name,peak,**extra:{'name':name,'ready_current':100*MIB,'post_current':100*MIB,'group_peak_bytes':(100+peak)*MIB,'extra':extra,'unavailable':{}}
    mem=[m('child-touch-64',75),m('sequential-children-64x2',76,child_maxrss_kib=[76*1024,76*1024]),
         m('children-32-64',76,child_maxrss_kib=[44*1024,76*1024],rusage_children_maxrss_kib=76*1024,label='largest waited child, not a sum'),
         m('shared-mapping-64',70,rss_kib=[70*1024,66*1024],uss_kib=[4*1024,3*1024]),
         m('short-spike-64',66,sampled_max_bytes=101*MIB,label='lower bound: handshake samples'),m('untouched-1024',2)]
    return {'cpu':bench.evaluate_cpu_controls(cpu,POLICY,ENV),'memory':bench.evaluate_memory_controls(mem,POLICY),'cpu_rows':cpu,'memory_rows':mem,'envelope':ENV}

EVIDENCE={'run':['artifacts/bench/r/plan.json','artifacts/bench/r/observations.jsonl'],'controls':['artifacts/bench/s/controls.json']}

class SubcaseTests(unittest.TestCase):
    def test_fixture_rows_are_schema_valid_and_carry_blocks(self):
        from schema_check import validate
        plan,obs,phases=plan_and_obs();first=next(o for o in obs if not o['warmup'] and o['scope']=='caller')
        validate(ROOT,'bench-observation',first);self.assertIsInstance(first['block'],int)
        group=[o for o in obs if (o.get('point'),o['scope'],o['mode'],o['variant'],o['workers'])==(first['point'],first['scope'],first['mode'],first['variant'],first['workers'])]
        self.assertIn(first['block'],bench.per_trial(group,'wall_ns'))       # so the fast-failure check really tests the per_trial exclusion
    def test_p07_and_p11_mutations_are_rejected_with_passing_controls(self):
        plan,obs,phases=plan_and_obs();rows=bench.run_subcases(ROOT,plan,obs,phases,controls(),POLICY,EVIDENCE)
        want={('P07','dropped-result-rows'),('P07','zero-work-units'),('P07','missing-planned-row'),('P07','unselected-model-units'),('P11','fast-failing-variant'),
              ('P11','parent-only-cpu-total'),('P11','tracemalloc-as-memory'),('P11','summed-rss-peak')}
        self.assertEqual({(r['parent'],r['variant']) for r in rows},want)
        status={r['variant']:(r['status'],r['control']) for r in rows}
        for variant in status:self.assertEqual(status[variant],('PASS','PASS'),variant)
        for r in rows:   # review Minor 4: each subcase names the evidence it mutated
            want=EVIDENCE['controls'] if r['variant'] in ('parent-only-cpu-total','summed-rss-peak') else EVIDENCE['run']
            self.assertEqual(r['evidence_paths'],want,r['variant'])
        self.assertEqual(obs,plan_and_obs()[1])                                # the recorded evidence is never mutated in place
    def test_fast_failure_counted_as_a_fast_time_is_caught(self):
        plan,obs,phases=plan_and_obs();saved=bench.per_trial
        try:
            bench.per_trial=lambda rows,field:{o['block']:o['wall_ns'] for o in rows if not o['warmup']}   # a defect: ineligible rows kept
            row=next(r for r in bench.run_subcases(ROOT,plan,obs,phases,controls(),POLICY,EVIDENCE) if r['variant']=='fast-failing-variant')
        finally:bench.per_trial=saved
        self.assertEqual(row['status'],'FAIL')
    def test_schema_invalid_original_fails_the_tracemalloc_control(self):
        plan,obs,phases=plan_and_obs();del next(o for o in obs if not o['warmup'] and o['scope']=='caller')['runner']
        row=next(r for r in bench.run_subcases(ROOT,plan,obs,phases,controls(),POLICY,EVIDENCE) if r['variant']=='tracemalloc-as-memory')
        self.assertEqual((row['status'],row['control']),('FAIL','FAIL'))
    def test_failed_controls_make_every_subcase_fail(self):
        plan,obs,phases=plan_and_obs();next(o for o in obs if not o['warmup'] and o['scope']=='caller')['work_units']=0;ctl=controls()
        ctl['cpu']={'status':'FAIL','checks':[]};ctl['memory']={'status':'FAIL','checks':[]}
        for r in bench.run_subcases(ROOT,plan,obs,phases,ctl,POLICY,EVIDENCE):
            if r['variant']=='tracemalloc-as-memory':continue   # its control is the schema check of the row (test_schema_invalid_original_...)
            with self.subTest(variant=r['variant']):self.assertEqual((r['status'],r['control']),('FAIL','FAIL'))
    def test_fixtures_name_every_selftest_variant(self):
        fixtures={(r['parent'],r['name'],v) for r in bm.load_fixtures(ROOT)['pipeline_subcases'] for v in r['variants']}
        plan,obs,phases=plan_and_obs()
        produced={(r['parent'],r['name'],r['variant']) for r in bench.run_subcases(ROOT,plan,obs,phases,controls(),POLICY,EVIDENCE)}
        produced|={('P01','bench-metric-or-runner-unavailable',v) for v,_ in bench.DOCTOR_MUTATIONS}|{('P01','bench-metric-or-runner-unavailable','cpuset-unrecorded')}
        import bench_phase3            # ruling T29-C1: the P10 and P15 variants come from bench_phase3.phase3_cases
        produced|={(p,bench_phase3.NAMES[p],v) for p,v in bench_phase3.ALL_VARIANTS}
        import bench_phase2            # EX-13: the P02, P04 and P16 variants come from bench_phase2.phase2_cases
        produced|={(p,bench_phase2.NAMES[p],v) for p,v in bench_phase2.ALL_VARIANTS}
        self.assertEqual(produced,fixtures)

class NoChangeControlTests(unittest.TestCase):
    """Task 16a residual and review Minor 6: the A/A control of the qualification run pairs six blocks per half and must be EQUAL."""
    def test_qualification_point_gives_six_blocks_per_half_within_the_decision_cap(self):
        case=bm.load_case(ROOT,'bench-control-spin');plan=bp.build_plan(case,POLICY,mode='decision',dataset=DS,seed=1,envelope=ENV)
        blocks={t['block'] for s in plan['sessions'] for t in s['trials'] if t['variant']=='py-reference' and not t['warmup']}
        self.assertEqual(len(blocks)//2,bench.AA_MIN_BLOCKS_PER_HALF);self.assertEqual(bench.AA_MIN_BLOCKS_PER_HALF,6)
        self.assertLessEqual(plan['estimate_seconds'],POLICY['budgets']['decision_cap_seconds'])
    def test_no_change_problems(self):
        aa=lambda outcome,blocks:{'controls':{'no_change':[{'point':'qual-caller','mode':'warm','outcome':outcome,'blocks':blocks}]}}
        self.assertEqual(bench.check_no_change(aa('EQUAL',6)),[])
        for bad in (aa('INCONCLUSIVE',6),aa('FASTER',6),aa('SLOWER',12),aa('EQUAL',5),aa('EQUAL',None),{'controls':{'no_change':[]}},{}):
            with self.subTest(bad=bad):self.assertTrue(bench.check_no_change(bad))
        self.assertIn('EQUAL required',' '.join(bench.check_no_change(aa('INCONCLUSIVE',6))))

class HostNoiseTests(unittest.TestCase):
    """PL-T20-B13-HOSTNOISE, Amendment H12, rulings T10-C3..C5. Rows carry the fields compare pairs on (scope, eligible,
    work_units, wall_ns), so the paired blocks of pressure_blocks are the blocks the A/A row paired."""
    def rows(self,pressures,scope='caller',start=0):
        return [{'trial_id':f'{scope}{b}','block':b,'variant':'py-optimized','point':'qualification','mode':'warm','scope':scope,'warmup':False,
                 'eligible':True,'work_units':1,'wall_ns':1000,'cpu_pressure_total':p} for b,p in enumerate(pressures,start)]
    def cmp(self,outcome,blocks=6):
        return {'controls':{'no_change':[{'point':'qualification','scope':'caller','mode':'warm','outcome':outcome,'blocks':blocks,'control':'no-change (A/A: even versus odd blocks of py-optimized)'}]}}
    def test_inconclusive_with_pressure_evidence_is_blocked(self):
        obs=self.rows([100,120,90,110,50000,105,95,100,115,98,60000,102])
        status,problems=bench.classify_no_change(self.cmp('INCONCLUSIVE'),obs,POLICY)
        self.assertEqual(status,'BLOCKED');self.assertIn('pressure',problems[0])
        self.assertEqual(bench.pressure_blocks(obs,'qualification','warm','py-optimized',POLICY,scope='caller'),[4,10])
    def test_inconclusive_without_pressure_evidence_fails(self):
        status,_=bench.classify_no_change(self.cmp('INCONCLUSIVE'),self.rows([100]*12),POLICY);self.assertEqual(status,'FAIL')
    def test_false_difference_fails_even_with_pressure(self):
        obs=self.rows([100]*11+[90000])
        for out in ('FASTER','SLOWER'):self.assertEqual(bench.classify_no_change(self.cmp(out),obs,POLICY)[0],'FAIL')
    def test_equal_passes(self):self.assertEqual(bench.classify_no_change(self.cmp('EQUAL'),self.rows([100]*12),POLICY),('PASS',[]))
    def test_missing_pressure_is_no_evidence(self):
        self.assertEqual(bench.classify_no_change(self.cmp('INCONCLUSIVE'),self.rows([None]*12),POLICY)[0],'FAIL')
    def test_small_absolute_pressure_is_no_evidence(self):
        self.assertEqual(bench.classify_no_change(self.cmp('INCONCLUSIVE'),self.rows([1]*11+[900]),POLICY)[0],'FAIL')
    def test_policy_holds_the_threshold(self):
        self.assertEqual(POLICY['controls']['aa_pressure'],{'factor':3.0,'min_usec':1000})
    def test_check_no_change_keeps_its_list_interface(self):
        self.assertEqual(bench.check_no_change(self.cmp('EQUAL')),[])
    def test_block_count_fail_wins_over_pressure(self):
        # T10-C4: fewer than six blocks per half is a design FAIL, never BLOCKED.
        obs=self.rows([100,120,90,110,50000,105,95,100,115,60000])
        status,problems=bench.classify_no_change(self.cmp('INCONCLUSIVE',blocks=5),obs,POLICY)
        self.assertEqual(status,'FAIL');self.assertIn('at least 6 required',' '.join(problems))
    def test_pressure_of_another_scope_is_no_evidence(self):
        # T10-C5: only the A/A row's own scope counts.
        obs=self.rows([100]*12)+self.rows([100]*11+[90000],scope='kernel')
        self.assertEqual(bench.pressure_blocks(obs,'qualification','warm','py-optimized',POLICY,scope='caller'),[])
        self.assertEqual(bench.classify_no_change(self.cmp('INCONCLUSIVE'),obs,POLICY)[0],'FAIL')
        self.assertEqual(bench.pressure_blocks(obs,'qualification','warm','py-optimized',POLICY,scope='kernel'),[11])
    def test_only_paired_blocks_count(self):
        # T10-C5: a 13th block has no partner in the even/odd pairing; an ineligible block is not paired either.
        obs=self.rows([100]*12+[90000])
        self.assertEqual(bench.pressure_blocks(obs,'qualification','warm','py-optimized',POLICY,scope='caller'),[])
        self.assertEqual(bench.classify_no_change(self.cmp('INCONCLUSIVE'),obs,POLICY)[0],'FAIL')
        obs=self.rows([100]*12);obs[3]=dict(obs[3],eligible=False,cpu_pressure_total=90000)
        self.assertEqual(bench.pressure_blocks(obs,'qualification','warm','py-optimized',POLICY,scope='caller'),[])
    def test_b13_failure_wins_over_blocked(self):
        # T10-C3: a failing B13 condition is FAIL even when the A/A control is BLOCKED.
        self.assertEqual(bench.b13_status(False,'BLOCKED'),'FAIL')
        self.assertEqual(bench.b13_status(True,'BLOCKED'),'BLOCKED')
        self.assertEqual(bench.b13_status(True,'PASS'),'PASS')
        for ok,aa in ((False,'PASS'),(True,'FAIL'),(False,'FAIL'),(True,None),(True,'pass')):
            with self.subTest(ok=ok,aa=aa):self.assertEqual(bench.b13_status(ok,aa),'FAIL')
    def test_pressure_of_another_workers_or_tier_group_is_no_evidence(self):
        # T10-APP-05: only the A/A row's own workers and tier group counts (compare groups by both).
        own=[dict(o,workers='direct',tier='small') for o in self.rows([100]*12)]
        other=[dict(o,workers=w,tier=t,trial_id=f'{o["trial_id"]}-{w}-{t}') for w,t in ((2,'small'),('direct','large')) for o in self.rows([100]*11+[90000])]
        cmp=self.cmp('INCONCLUSIVE');cmp['controls']['no_change'][0].update(workers='direct',tier='small')
        self.assertEqual(bench.pressure_blocks(own+other,'qualification','warm','py-optimized',POLICY,scope='caller',workers='direct',tier='small'),[])
        self.assertEqual(bench.classify_no_change(cmp,own+other,POLICY)[0],'FAIL')
        self.assertEqual(bench.pressure_blocks(own+other,'qualification','warm','py-optimized',POLICY,scope='caller',workers=2,tier='small'),[11])
        self.assertEqual(bench.pressure_blocks(own+other,'qualification','warm','py-optimized',POLICY,scope='caller',workers='direct',tier='large'),[11])
        hot=[dict(o,workers='direct',tier='small') for o in self.rows([100,120,90,110,50000,105,95,100,115,98,60000,102])]
        self.assertEqual(bench.classify_no_change(cmp,hot+other,POLICY)[0],'BLOCKED')
    def b13(self,rc=0,run=None,q_rc=0,outcome='INCONCLUSIVE',pressures=(100,120,90,110,50000,105,95,100,115,98,60000,102),q_cmp=True,overhead_n=3):
        # T10-APP-03: the pure B13 suite assembly of selftest_cases (smoke run, qualification run, classify_no_change, b13_status).
        cmp={'controls':{'no_change':[{'outcome':'EQUAL'}],'empty_overhead':{'n':overhead_n}}}
        return bench.b13_suite(rc,{'sessions':[]},[],[],run or {},cmp,'r'*32,q_rc,'q'*32,self.cmp(outcome) if q_cmp else None,self.rows(list(pressures)),POLICY)
    def test_b13_suite_blocked_input(self):
        s=self.b13();self.assertEqual((s['status'],s['aa_status']),('BLOCKED','BLOCKED'));self.assertIn('pressure',s['no_change_problems'][0])
        self.assertEqual((s['run_id'],s['qualification_run_id']),('r'*32,'q'*32));self.assertEqual(s['no_change'][0]['outcome'],'INCONCLUSIVE')
    def test_b13_suite_fail_input(self):
        for kw in ({'rc':1},{'run':{'mode':'profile'}},{'overhead_n':0}):      # a failing B13 condition wins over the BLOCKED A/A control
            with self.subTest(**kw):s=self.b13(**kw);self.assertEqual((s['status'],s['aa_status']),('FAIL','BLOCKED'))
        for kw in ({'pressures':[100]*12},{'q_rc':1},{'q_cmp':False},{'outcome':'FASTER'}):   # the A/A control itself fails
            with self.subTest(**kw):s=self.b13(**kw);self.assertEqual((s['status'],s['aa_status']),('FAIL','FAIL'))
        s=self.b13(outcome='EQUAL');self.assertEqual((s['status'],s['aa_status'],s['no_change_problems']),('PASS','PASS',[]))
    def test_b13_property_names_the_h12_blocked_case(self):
        # T10-APP-06
        p=self.b13()['property'];self.assertIn('H12',p);self.assertIn('BLOCKED',p);self.assertIn('EQUAL',p)

class SelftestAggregateTests(unittest.TestCase):
    """T10-APP-01: `bench selftest` is FAIL when any suite FAILs; BLOCKED only when no suite FAILs and some suite is BLOCKED.
    The unit-group and controls aggregates inside selftest follow the same rule."""
    def test_status_rule(self):
        for st,want in (([],'FAIL'),(['PASS'],'PASS'),(['PASS','PASS'],'PASS'),(['PASS','BLOCKED'],'BLOCKED'),(['BLOCKED','FAIL'],'FAIL'),
                        (['FAIL','BLOCKED'],'FAIL'),(['PASS',None],'FAIL'),(['PASS','pass'],'FAIL'),(['BLOCKED',None],'FAIL')):
            with self.subTest(st=st):self.assertEqual(bench.selftest_status(st),want)
    def drive(self,suite,cases=None,groups=None,controls=None):
        from unittest import mock
        import argparse
        run_dir=Path(tempfile.mkdtemp());unit=iter(groups or [])
        with mock.patch.object(bench,'new_run_dir',lambda root,kind:run_dir),mock.patch.object(bench,'emit',lambda args,result,text:None),\
             mock.patch.object(bench,'project_arg',lambda root,args:'examples/demo' if groups else None),\
             mock.patch.object(bench.bm,'unit_groups',lambda root,project:[[f'm{k}'] for k in range(len(groups or []))]),\
             mock.patch.object(bench,'_unit_job',lambda root,rd,policy,project,g:{'status':next(unit)}),\
             mock.patch.object(bench,'run_controls',lambda root,rd:{'cpu':{'status':controls[0]},'memory':{'status':controls[1]}}),\
             mock.patch.object(bench,'selftest_cases',lambda root,rd,scope=None:(cases,[{'status':'PASS'}])):
            rc=bench.selftest(ROOT,argparse.Namespace(suite=suite,project=None,format='json'))
        result=json.loads((run_dir/'selftest.json').read_text());return result['status'],rc,result['suites']
    def test_a_failing_case_suite_wins_over_a_blocked_b13(self):
        self.assertEqual(self.drive('cases',cases={'B09':{'status':'FAIL'},'B13':{'status':'BLOCKED'}})[:2],('FAIL',1))
        self.assertEqual(self.drive('cases',cases={'B09':{'status':'PASS'},'B13':{'status':'BLOCKED'}})[:2],('BLOCKED',2))
        self.assertEqual(self.drive('cases',cases={'B09':{'status':'PASS'},'B13':{'status':'PASS'}})[:2],('PASS',0))
    def test_a_failing_unit_group_wins_over_a_blocked_one(self):
        status,rc,suites=self.drive('unit',groups=['FAIL','BLOCKED']);self.assertEqual((status,rc,suites['unit']['status']),('FAIL',1,'FAIL'))
        status,rc,suites=self.drive('unit',groups=['PASS','BLOCKED']);self.assertEqual((status,rc,suites['unit']['status']),('BLOCKED',2,'BLOCKED'))
        status,rc,suites=self.drive('unit',groups=['PASS','PASS']);self.assertEqual((status,rc,suites['unit']['status']),('PASS',0,'PASS'))
    def test_a_failing_control_wins_over_a_blocked_one(self):
        for ctl,want in ((('FAIL','BLOCKED'),('FAIL',1)),(('BLOCKED','FAIL'),('FAIL',1)),(('PASS','BLOCKED'),('BLOCKED',2)),(('PASS','PASS'),('PASS',0))):
            with self.subTest(ctl=ctl):self.assertEqual(self.drive('controls',controls=ctl)[:2],want)

if __name__=='__main__':unittest.main()

class ExampleProjectGateTests(unittest.TestCase):
    """Controller ruling (Task 11a review Important 2): an example project under examples/ is framework content, so the
    `ci` bench-selftest gate runs its bench unit suite and every `before_run` check it declares."""
    DECL={'schema_version':1,'name':'demo','cases':['demo-case'],
          'checks':[{'name':'prereq-check','module':'demo.checks','before_run':True},{'name':'manual-check','module':'demo.checks','before_run':False}]}
    def run_gates(self,unit_rc=0,check_status='PASS',privacy='PASS'):
        from unittest import mock
        d=Path(tempfile.mkdtemp());(d/'examples/demo/benchmarks/project').mkdir(parents=True);(d/'examples/plain').mkdir(parents=True)
        (d/'examples/demo/benchmarks/project/bench.json').write_text(json.dumps(self.DECL));(d/'artifacts').mkdir()
        calls=[]
        def quiet(fn,root,args):
            calls.append(('unit',args.project));return (unit_rc if args.project else 0),{'status':'PASS'}
        def check(root,run_dir,project,name,args=(),deadline_key='smoke',shared=()):
            calls.append(('check',project,name));return check_status,'evidence.json',{'status':check_status}
        with mock.patch.object(bench,'doctor_probe',lambda root,run_dir:{'status':'PASS','evidence_paths':[]}),\
             mock.patch.object(bench,'selftest_cases',lambda root,run_dir:({'B01':{'status':'PASS','evidence_paths':[]}},[])),\
             mock.patch.object(bench,'_quiet',quiet),mock.patch.object(bench,'run_check',check),\
             mock.patch.object(bench,'_privacy_suite',lambda root,run_dir:{'status':privacy,'evidence_paths':['privacy.json']}),\
             mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL if project=='examples/demo' else None):
            gates,_=bench.ci_gates(d)
        return next(g for g in gates if g['name']=='bench-selftest'),calls
    def test_example_unit_suite_and_before_run_checks_run_in_ci(self):
        gate,calls=self.run_gates()
        self.assertEqual(calls,[('unit',None),('unit','examples/demo'),('check','examples/demo','prereq-check')])
        self.assertEqual(gate['status'],'PASS')
        self.assertEqual(gate['details']['examples'],{'examples/demo':{'unit':'PASS','checks':{'prereq-check':'PASS'}}})
        self.assertEqual(bench.example_projects(Path(tempfile.mkdtemp())),[])
    def test_a_failed_example_unit_suite_or_check_fails_the_gate(self):
        self.assertEqual(self.run_gates(unit_rc=1)[0]['status'],'FAIL')
        self.assertEqual(self.run_gates(check_status='FAIL')[0]['status'],'FAIL')
        self.assertEqual(self.run_gates(unit_rc=2)[0]['status'],'BLOCKED')

class ProjectSuiteTests(unittest.TestCase):
    """Task 19b: the privacy suite and one suite per declared check of every registered project, in selftest and ci."""
    DECL={'schema_version':1,'name':'demo','cases':['demo-case'],
          'checks':[{'name':'gen','module':'demo.checks','before_run':False}]+[{'name':f'acc-{i}','module':'demo.checks','before_run':True} for i in range(4)]}
    def test_projects_are_discovered_generically(self):
        # The framework names no example (test_bench_framework_imports): the expected list comes from the layout itself, minus
        # the standalone examples (amendment E rule S; FIX1 T3-A02: rule S changes the expectation, a standalone example is
        # no framework project).
        standalone=set(project_model.standalone_examples(ROOT))
        layout=sorted(rel for rel in (p.parents[2].relative_to(ROOT).as_posix() for p in ROOT.glob('examples/*/benchmarks/project/bench.json'))
                      if rel not in standalone)
        self.assertTrue(layout);self.assertEqual(bench.registered_projects(ROOT),layout)
        d=Path(tempfile.mkdtemp());self.assertEqual(bench.registered_projects(d),[])
        (d/'benchmarks/project').mkdir(parents=True);(d/'benchmarks/project/bench.json').write_text('{}');self.assertEqual(bench.registered_projects(d),['.'])
        (d/'examples/demo/benchmarks/project').mkdir(parents=True);(d/'examples/demo/benchmarks/project/bench.json').write_text('{}')
        (d/'examples/plain').mkdir();self.assertEqual(bench.registered_projects(d),['.','examples/demo'])
    def test_a_standalone_example_is_not_registered_in_a_copy_of_the_tree(self):
        """FIX1 T3-A02: the real-tree expectation with a standalone example present. A copy of the export list and of the
        project.json and bench.json files of every example, plus one synthetic standalone example with bench.json."""
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'starter-export.json').write_bytes((ROOT/'starter-export.json').read_bytes())
            for p in [*ROOT.glob('examples/*/project.json'),*ROOT.glob('examples/*/benchmarks/project/bench.json')]:
                q=d/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
            solo=d/'examples/solo-demo';(solo/'benchmarks/project').mkdir(parents=True)
            (solo/'project.json').write_text('{}\n');(solo/'benchmarks/project/bench.json').write_text('{}\n')
            everything=sorted(p.parents[2].relative_to(d).as_posix() for p in d.glob('examples/*/benchmarks/project/bench.json'))
            standalone=set(project_model.standalone_examples(d));self.assertIn('examples/solo-demo',standalone)
            expected=[rel for rel in everything if rel not in standalone]
            self.assertEqual(bench.registered_projects(d),expected)
            self.assertNotIn('examples/solo-demo',expected);self.assertNotEqual(everything,expected)   # the expectation before rule S fails here
            real=set(project_model.standalone_examples(ROOT))
            self.assertEqual(expected,sorted(rel for rel in (p.parents[2].relative_to(ROOT).as_posix() for p in ROOT.glob('examples/*/benchmarks/project/bench.json'))
                                              if rel not in real))      # the framework examples of the real tree
            self.assertEqual(bench.registered_projects(d,'examples/solo-demo'),['examples/solo-demo'])
    def test_selftest_has_privacy_and_project_suites(self):
        import argparse
        p=argparse.ArgumentParser();bench.configure_parser(p)
        for suite in ('privacy','project'):self.assertEqual(p.parse_args(['selftest','--suite',suite]).suite,suite)
    def suites(self,check_status=lambda name:'PASS',unit_rc=0):
        from unittest import mock
        calls=[]
        def quiet(fn,root,args):
            calls.append(('unit',args.project,args.suite));return unit_rc,{'suites':{'unit':{'status':'PASS','evidence_paths':['unit.json']}}}
        def check(root,run_dir,project,name,args=(),deadline_key='smoke',shared=()):
            calls.append(('check',project,name,deadline_key));st=check_status(name)
            if st=='RAISE':raise bench.GateError('launcher refused')
            return st,f'{name}.json',{'status':st}
        with mock.patch.object(bench,'registered_projects',lambda root,scope=None:['examples/demo']),mock.patch.object(bench,'_quiet',quiet),\
             mock.patch.object(bench,'run_check',check),mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL),\
             mock.patch.object(bench,'project_image_suites',lambda root,run_dir:{}):      # EX-1: the image control has its own test (test_project_image)
            return bench.project_suites(ROOT,Path(tempfile.mkdtemp())),calls
    def test_every_before_run_check_is_one_suite(self):
        suites,calls=self.suites()
        self.assertEqual(list(suites),['project:examples/demo:unit']+[f'project:examples/demo:acc-{i}' for i in range(4)])
        self.assertTrue(all(v['status']=='PASS' for v in suites.values()))
        self.assertEqual(calls,[('unit','examples/demo','unit')]+[('check','examples/demo',f'acc-{i}','selftest') for i in range(4)])
        self.assertEqual(suites['project:examples/demo:acc-2']['evidence_paths'],['acc-2.json'])
        self.assertEqual(suites['project:examples/demo:unit']['evidence_paths'],['unit.json'])
    def test_a_failed_or_blocked_check_keeps_the_later_checks(self):
        suites,calls=self.suites(check_status=lambda name:{'acc-1':'FAIL','acc-2':'RAISE'}.get(name,'PASS'))
        self.assertEqual({k.split(':')[-1]:v['status'] for k,v in suites.items()},{'unit':'PASS','acc-0':'PASS','acc-1':'FAIL','acc-2':'BLOCKED','acc-3':'PASS'})
        self.assertEqual(suites['project:examples/demo:acc-2']['reason'],'launcher refused')
        for rc,status in ((1,'FAIL'),(2,'BLOCKED')):
            with self.subTest(rc=rc):self.assertEqual(self.suites(unit_rc=rc)[0]['project:examples/demo:unit']['status'],status)
    def run_selftest(self,suite):
        from unittest import mock
        import argparse
        run_dir=Path(tempfile.mkdtemp());seen=[]
        class NoSession:
            def __init__(self,*a,**k):raise bench.GateError('no launcher in the unit test')
        with mock.patch.object(bench,'new_run_dir',lambda root,kind:run_dir),mock.patch.object(bench,'BenchSession',NoSession),\
             mock.patch.object(bench,'_privacy_suite',lambda root,rd:seen.append('privacy') or {'status':'PASS','evidence_paths':[]}),\
             mock.patch.object(bench,'project_suites',lambda root,rd,scope=None:seen.append('project') or {'project:examples/demo:unit':{'status':'PASS'}}),\
             mock.patch.object(bench,'selftest_cases',lambda root,rd,scope=None:seen.append('cases') or ({'B01':{'status':'PASS'}},[])),\
             mock.patch.object(bench,'emit',lambda args,result,text:None):
            bench.selftest(ROOT,argparse.Namespace(suite=suite,project=None,format='json'))
        return json.loads((run_dir/'selftest.json').read_text())['suites'],seen
    def test_selftest_privacy_project_and_all(self):
        suites,seen=self.run_selftest('privacy');self.assertEqual((list(suites),seen),(['privacy'],['privacy']))
        suites,seen=self.run_selftest('project');self.assertEqual((list(suites),seen),(['project:examples/demo:unit'],['project']))
        suites,seen=self.run_selftest('all');self.assertEqual(sorted(seen),['cases','privacy','project'])
        for key in ('unit','privacy','B01','subcases','project:examples/demo:unit'):self.assertIn(key,suites)
    def test_ci_holds_the_privacy_and_project_suites(self):
        gate,calls=ExampleProjectGateTests.run_gates(ExampleProjectGateTests())
        self.assertEqual(gate['details']['privacy'],'PASS');self.assertEqual(gate['details']['project:examples/demo:prereq-check'],'PASS')
        self.assertEqual(gate['details']['project:examples/demo:unit'],'PASS');self.assertNotIn('project:examples/demo:manual-check',gate['details'])
        self.assertIn('privacy.json',gate['evidence_paths']);self.assertIn('evidence.json',gate['evidence_paths'])
        self.assertIn(('check','examples/demo','prereq-check'),calls)
        for privacy in ('FAIL','BLOCKED'):
            with self.subTest(privacy=privacy):self.assertEqual(ExampleProjectGateTests.run_gates(ExampleProjectGateTests(),privacy=privacy)[0]['status'],privacy)

class SecondStubSuiteTests(unittest.TestCase):
    """Task A5 (Amendment I9.4), FR3: the second declared stub (stub-overrun of the fixture protocol, the pattern of the first)
    gets its own run and check suite, its stub plan is the selftest plan of its entry (py-library, selector m5, the test
    floor, SAFE_C_TEST_STUB=stub-overrun) and the coordinator passes the variable only in selftest mode."""
    def test_every_declared_stub_is_wired(self):
        import bench_deadline as bd
        from unittest import mock
        seen=[]
        with mock.patch.object(bench,'example_projects',lambda root,project=None:['tests/fixtures/bench-project']),\
             mock.patch.object(bd,'_stub_run_selftest',lambda r,d,s,p,c:seen.append(('run',s['reason'])) or {'status':'PASS'}),\
             mock.patch.object(bd,'_stub_check_selftest',lambda r,d,s,p,c:seen.append(('check',s['reason'])) or {'status':'PASS'}):
            suites,_=bd.stub_suites(ROOT,Path('/nonexistent'))
        self.assertEqual(seen,[('run','stub-hang'),('check','stub-hang'),('run','stub-overrun'),('check','stub-overrun')])
        self.assertIn('stub-run-stub-overrun',suites);self.assertIn('stub-check-stub-overrun',suites)
    def test_second_stub_plan_is_checked_and_an_edit_is_refused(self):
        import copy, bench_deadline as bd
        from evidence import GateError
        from unittest import mock
        # FR1 (FS1 F3): found by declaration over the synthetic unit-test project only; the framework tree holds no
        # project that declares a test stub
        with mock.patch.object(bench,'example_projects',lambda root,project=None:['tests/fixtures/bench-project']):
            project,case,spec=bd.stub_project(ROOT,'stub-overrun');_,_,first=bd.stub_project(ROOT,'stub-hang')
        policy=bm.load_policy(ROOT,project);identity=bm.project_identity(ROOT,project,case)
        plan=bd.stub_plan(ROOT,case,policy,ENV,7,spec,project,identity)
        self.assertEqual((plan['mode'],plan['test_floor_seconds'],plan['memory'],plan['test_env']),('selftest',2,[],{'SAFE_C_TEST_STUB':'stub-overrun'}))
        (t,)=[t for s in plan['sessions'] for t in s['trials']]
        self.assertEqual((t['variant'],t['workers'],t['scope'],t['tier'],t['selector'],t['call_deadline_reason'],t['call_deadline_seconds']),
                         ('py-library','direct','caller','tiny','m5','stub-overrun',2.0))
        self.assertIs(bd.check_selftest_plan(plan,case,policy,ENV,bench.plan_digest(plan),project=project,identity=identity,root=ROOT),plan)
        other=bd.stub_plan(ROOT,case,policy,ENV,7,first,project,identity)
        self.assertIs(bd.check_selftest_plan(other,case,policy,ENV,bench.plan_digest(other),project=project,identity=identity,root=ROOT),other)
        for edit in (lambda p:p.update(test_floor_seconds=1),lambda p:p['sessions'][0]['trials'][0].update(selector='m4'),
                     lambda p:p.update(test_env={'SAFE_C_TEST_STUB':'stub-hang'}),lambda p:p.update(test_env={'SAFE_C_TEST_STUB':'Bad'}),
                     lambda p:p['sessions'][0]['trials'].append(dict(t,trial_id='x'))):
            bad=copy.deepcopy(plan);edit(bad)
            with self.subTest(edit=edit),self.assertRaises(GateError):bd.check_selftest_plan(bad,case,policy,ENV,bench.plan_digest(bad),project=project,identity=identity,root=ROOT)
    def test_child_env_passes_the_stub_only_in_selftest(self):
        import os
        old=os.environ.get('SAFE_C_TEST_STUB');os.environ['SAFE_C_TEST_STUB']='stub-overrun'
        try:
            bc.set_test_env({'mode':'smoke','test_env':{'SAFE_C_TEST_STUB':'stub-overrun'}});self.assertNotIn('SAFE_C_TEST_STUB',bc.child_env())
            bc.set_test_env({'mode':'selftest','test_env':{'SAFE_C_TEST_STUB':'stub-overrun'}});self.assertEqual(bc.child_env()['SAFE_C_TEST_STUB'],'stub-overrun')
            with self.assertRaises(ValueError):bc.set_test_env({'mode':'selftest','test_env':{'SAFE_C_TEST_STUB':'Run Now'}})
            self.assertNotIn('SAFE_C_TEST_STUB',bc.child_env())
        finally:
            bc.set_test_env({})
            if old is None:os.environ.pop('SAFE_C_TEST_STUB',None)
            else:os.environ['SAFE_C_TEST_STUB']=old

class SharedCheckFileTests(unittest.TestCase):
    """Task DD (ruling D1-R2(b)): the checks of one session (before_run_checks; one project's checks in project_suites) hand
    the shared-* output files of each PASS check to the later checks, through Runner.restore into bench/shared/<check>/. A
    FAIL check hands nothing on, a single `bench check` has no shared files, and run_check refuses a shared file outside the
    run's own evidence or with another container path."""
    DECL={'schema_version':1,'name':'demo','cases':['demo-case'],
          'checks':[{'name':'acc-0','module':'demo.checks','before_run':True},{'name':'gen','module':'demo.checks','before_run':False},
                    {'name':'acc-1','module':'demo.checks','before_run':True},{'name':'acc-2','module':'demo.checks','before_run':True}]}
    def tmp(self):
        """A temporary directory removed after the test (the unit gate's /tmp is a bounded tmpfs)."""
        import shutil
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);return d
    def fake_check(self,run_dir,calls,status=lambda name:{'acc-1':'FAIL'}.get(name,'PASS')):
        def check(root,rd,project,name,args=(),deadline_key='smoke',shared=()):
            calls.append((name,tuple(shared)));files=[f'shared-{name}.json','plain.json']
            for f in files:(Path(rd)/name).mkdir(parents=True,exist_ok=True);(Path(rd)/name/f).write_text('{}')
            return status(name),f'{name}.json',{'status':status(name),'files':files,'file_sha256':{f:EMPTY_SHA for f in files}}
        return check
    def expected(self,run_dir):
        a=('bench/shared/acc-0/shared-acc-0.json',Path(run_dir)/'acc-0'/'shared-acc-0.json',EMPTY_SHA)
        return [('acc-0',()),('acc-1',(a,)),('acc-2',(a,))]      # acc-1 FAILs: its shared file is not handed on
    def test_shared_outputs_rule(self):
        d=self.tmp();(d/'c1').mkdir();(d/'c1/shared-q.json').write_text('{}');(d/'c1/plain.json').write_text('{}')
        (d/'c1/shared-link.json').symlink_to(d/'c1/shared-q.json')
        files=['shared-q.json','plain.json','shared-missing.json','shared-link.json','../shared-x.json']
        row={'status':'PASS','files':files,'file_sha256':{f:EMPTY_SHA for f in files}}
        self.assertEqual(bench.shared_outputs(d,'c1','PASS',row),[('bench/shared/c1/shared-q.json',d/'c1'/'shared-q.json',EMPTY_SHA)])
        for status in ('FAIL','BLOCKED'):
            with self.subTest(status=status):self.assertEqual(bench.shared_outputs(d,'c1',status,row),[])
        self.assertEqual(bench.shared_outputs(d,'c1','PASS',{'status':'PASS'}),[])
        # DD-01: a file without a well-formed recorded fetch digest is not handed on.
        for digests in (None,{},{'shared-q.json':None},{'shared-q.json':'0'*63},{'shared-q.json':EMPTY_SHA.upper()},[EMPTY_SHA]):
            with self.subTest(digests=digests):self.assertEqual(bench.shared_outputs(d,'c1','PASS',dict(row,file_sha256=digests)),[])
    def test_before_run_checks_hand_shared_files_forward(self):
        from unittest import mock
        run_dir=self.tmp();calls=[]
        with mock.patch.object(bench,'run_check',self.fake_check(run_dir,calls)),mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL):
            reasons,evidence=bench.before_run_checks(ROOT,run_dir,'examples/demo')
        self.assertEqual(calls,self.expected(run_dir))
        self.assertEqual((reasons,evidence),(['pre-run check acc-1: FAIL'],['acc-0.json','acc-1.json','acc-2.json']))
    def test_project_suites_hand_shared_files_forward_within_one_project(self):
        from unittest import mock
        run_dir=self.tmp();calls=[]
        with mock.patch.object(bench,'registered_projects',lambda root,scope=None:['examples/demo']),\
             mock.patch.object(bench,'_quiet',lambda fn,root,args:(0,{'suites':{'unit':{'status':'PASS','evidence_paths':[]}}})),\
             mock.patch.object(bench,'run_check',self.fake_check(run_dir,calls)),mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL),\
             mock.patch.object(bench,'project_image_suites',lambda root,run_dir:{}):      # EX-1: the image control has its own test (test_project_image)
            suites=bench.project_suites(ROOT,run_dir)
        self.assertEqual(calls,self.expected(run_dir))
        self.assertEqual({k.split(':')[-1]:v['status'] for k,v in suites.items()},{'unit':'PASS','acc-0':'PASS','acc-1':'FAIL','acc-2':'PASS'})
    def test_run_check_restores_the_shared_files_and_refuses_others(self):
        from unittest import mock
        from evidence import GateError
        run_dir=self.tmp();(run_dir/'acc-0').mkdir();src=run_dir/'acc-0'/'shared-acc-0.json';src.write_text('{}');seen=[]
        class Session:
            def __init__(self,root,rd):pass
            def job(self,plan,label,timeout,restore=()):
                seen.append((plan['check'],restore));return {'output':json.dumps({'status':'PASS','files':[]}),'exit_code':0,'failure':None,'evidence_path':'e.json'}
            def fetch(self,relative,destination):raise AssertionError('no file listed')
            def close(self):pass
        good=(('bench/shared/acc-0/shared-acc-0.json',src,EMPTY_SHA),)
        with mock.patch.object(bench,'BenchSession',Session),mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL):
            self.assertEqual(bench.run_check(ROOT,run_dir,'examples/demo','acc-2',shared=good)[0],'PASS')
            self.assertEqual(bench.run_check(ROOT,run_dir,'examples/demo','acc-2')[0],'PASS')
            outside=self.tmp()/'shared-acc-0.json';outside.write_text('{}')
            for bad in ((('bench/shared/acc-0/shared-acc-0.json',outside,EMPTY_SHA),),(('bench/out/shared-acc-0.json',src,EMPTY_SHA),),
                        (('bench/shared/acc-0/plain.json',src,EMPTY_SHA),),(('bench/shared/../x/shared-a.json',src,EMPTY_SHA),),(('bench/shared/../shared-a.json',src,EMPTY_SHA),),
                        (('bench/shared/acc-0/shared-acc-0.json',run_dir/'acc-0'/'..'/'..'/'shared-acc-0.json',EMPTY_SHA),),good*33,
                        (('bench/shared/acc-0/shared-acc-0.json',src),),(('bench/shared/acc-0/shared-acc-0.json',src,None),),       # DD-01: no fetch digest
                        (('bench/shared/acc-0/shared-acc-0.json',src,'0'*63),),(('bench/shared/acc-0/shared-acc-0.json',src,EMPTY_SHA.upper()),)):
                with self.subTest(bad=bad[0]),self.assertRaises(GateError):bench.run_check(ROOT,run_dir,'examples/demo','acc-2',shared=bad)
            # DD-03: the <check> segment of the container path is the check directory of the copy, and that directory is
            # a check directory of this run (the producer belongs to this session).
            deep=run_dir/'acc-0'/'deep';deep.mkdir();(deep/'shared-acc-0.json').write_text('{}');(run_dir/'shared-top.json').write_text('{}')
            for bad in (('bench/shared/acc-1/shared-acc-0.json',src,EMPTY_SHA),('bench/shared/gen/shared-acc-0.json',src,EMPTY_SHA),
                        ('bench/shared/deep/shared-acc-0.json',deep/'shared-acc-0.json',EMPTY_SHA),
                        ('bench/shared/acc-0/shared-acc-0.json',deep/'shared-acc-0.json',EMPTY_SHA),
                        (f'bench/shared/{run_dir.name}/shared-top.json',run_dir/'shared-top.json',EMPTY_SHA)):
                with self.subTest(producer=bad[:2]),self.assertRaises(GateError):bench.run_check(ROOT,run_dir,'examples/demo','acc-2',shared=(bad,))
        self.assertEqual(seen,[('acc-2',(('bench/shared/acc-0/shared-acc-0.json',src,EMPTY_SHA),)),('acc-2',())])
    def test_run_check_records_the_fetched_digests(self):
        # DD-01: a passed check records, for every file it fetched, the sha256 from the session's collection record (the
        # bytes collect fetched), and shared_outputs hands that digest on with the file.
        from unittest import mock
        run_dir=self.tmp();fetched=[]
        class Session:
            def __init__(self,root,rd):pass
            def job(self,plan,label,timeout,restore=()):
                return {'output':json.dumps({'status':'PASS','files':['shared-q.json','plain.json']}),'exit_code':0,'failure':None,'evidence_path':'e.json'}
            def fetch(self,relative,destination):
                Path(destination).parent.mkdir(parents=True,exist_ok=True);Path(destination).write_text('{}');fetched.append(relative)
            def fetched_sha256(self,destination):return {'shared-q.json':'1'*64,'plain.json':'2'*64}[Path(destination).name]
            def close(self):pass
        with mock.patch.object(bench,'BenchSession',Session),mock.patch.object(bench.bm,'project_bench',lambda root,project:self.DECL):
            status,_,row=bench.run_check(ROOT,run_dir,'examples/demo','acc-0')
        self.assertEqual((status,fetched,row['file_sha256']),('PASS',['bench/out/shared-q.json','bench/out/plain.json'],{'shared-q.json':'1'*64,'plain.json':'2'*64}))
        self.assertEqual(bench.shared_outputs(run_dir,'acc-0',status,row),[('bench/shared/acc-0/shared-q.json',run_dir/'acc-0'/'shared-q.json','1'*64)])

class RestoreDigestTests(unittest.TestCase):
    """Task DD approver finding DD-01: Runner.restore hands on only the bytes that collect fetched. It compares the bytes
    with the sha256 recorded when collect fetched the file (in the same Runner, or passed on with the shared file to the
    Runner of a later check), never with a digest re-read from the host copy at restore time. A host-side edit of the
    copy between the fetch and a restore is refused before any byte goes across. The Runner is the real one; only the
    launcher is a stand-in that keeps the container /work in a dict."""
    def tmp(self):
        import shutil
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);return d
    def runner(self,work,run_dir):
        import base64, hashlib
        from unittest import mock
        import evidence
        class Launcher:
            value={'common':{'artifact_bytes':1<<20,'artifact_total_bytes':1<<22,'artifact_files':64}}
            def __init__(self,*a,**k):pass
            def verify_session(self,session):pass
            def docker(self,args,timeout,limit):        # collect: ['exec', id, 'python3', '-c', script, relative, cap]
                return {'exit_code':0,'failure':None,'evidence_complete':True,'output':base64.b64encode(work[args[-2]]).decode()}
            def execute(self,session,args,timeout):     # restore: prepare, chunk and verify-and-publish steps
                code=0
                if 'os.replace' in args[2]:
                    code=0 if hashlib.sha256(work.get(args[3],b'')).hexdigest()==args[5] else 32
                    if not code:work[args[4]]=work.pop(args[3])
                elif 'open("ab")' in args[2]:work[args[3]]=work[args[3]]+base64.b64decode(args[5])
                else:work[args[4]]=b''
                return {'exit_code':code,'failure':None,'evidence_complete':True,'output':''}
        with mock.patch('container_policy.Launcher',Launcher):
            r=evidence.Runner(ROOT,run_dir,{'image_id':'sha256:'+'0'*64},self.tmp(),build_profile='bench',purpose='bench')
        r.session={'container_id':'c'};r.input_binding={}
        return r
    def test_a_host_edit_after_the_fetch_is_refused(self):
        import hashlib
        from evidence import GateError
        run_dir=self.tmp();work={'bench/out/shared-q.json':b'{"q": 1}'}
        fetched=hashlib.sha256(b'{"q": 1}').hexdigest()
        # The same Runner: the digest that collect recorded decides.
        r=self.runner(work,run_dir);dest=r.collect(r.session,'bench/out/shared-q.json',run_dir/'acc-0'/'shared-q.json')
        dest.write_bytes(b'{"q": 2}')                     # a host-side edit between the fetch and the restore
        with self.assertRaises(GateError):r.restore('bench/shared/acc-0/shared-q.json',dest)
        self.assertEqual([k for k in work if k.startswith('bench/shared/')],[])
        dest.write_bytes(b'{"q": 1}');r.restore('bench/shared/acc-0/shared-q.json',dest)
        self.assertEqual(work['bench/shared/acc-0/shared-q.json'],b'{"q": 1}')
        # The Runner of a later check: the fetched digest goes with the shared file.
        later=self.runner(work,run_dir)
        later.restore('bench/shared/acc-0/shared-r.json',dest,fetched)
        self.assertEqual(work['bench/shared/acc-0/shared-r.json'],b'{"q": 1}')
        dest.write_bytes(b'{"q": 3}')
        with self.assertRaises(GateError):later.restore('bench/shared/acc-0/shared-s.json',dest,fetched)
        self.assertNotIn('bench/shared/acc-0/shared-s.json',work)
        self.assertEqual([k for k in work if '.restore-' in k],[])     # refused before any transfer step
        dest.write_bytes(b'{"q": 1}')
        for bad in ('0'*63,'g'*64,fetched.upper(),fetched+'\n',7):          # a malformed fetched digest is refused
            with self.subTest(bad=bad),self.assertRaises(GateError):later.restore('bench/shared/acc-0/shared-t.json',dest,bad)
    def test_every_restore_writes_its_own_receipt(self):
        # DD-02: the same shared file restored for several destination jobs leaves one PASS receipt per restore, named
        # by the sha256 and the job label (with a count for a repeated name); none overwrites another.
        import hashlib
        run_dir=self.tmp();work={'bench/out/shared-q.json':b'{"q": 1}'};sha=hashlib.sha256(b'{"q": 1}').hexdigest()
        r=self.runner(work,run_dir);dest=r.collect(r.session,'bench/out/shared-q.json',run_dir/'acc-0'/'shared-q.json')
        for label in ('check-acc-1','check-acc-2','check-acc-2',None,'check:odd/label'):
            self.runner(work,run_dir).restore('bench/shared/acc-0/shared-q.json',dest,sha,label=label)
        names=sorted(p.name for p in (run_dir/'transfers').iterdir())
        self.assertEqual(names,sorted([f'{sha}-check-acc-1.json',f'{sha}-check-acc-2.json',f'{sha}-check-acc-2-2.json',f'{sha}.json',f'{sha}-check-odd-label.json']))
        receipts=[json.loads((run_dir/'transfers'/n).read_text()) for n in names]
        self.assertEqual({(x['status'],x['source_sha256'],x['destination']) for x in receipts},{('PASS',sha,'bench/shared/acc-0/shared-q.json')})
        self.assertEqual(sorted(str(x['label']) for x in receipts),['None','check-acc-1','check-acc-2','check-acc-2','check:odd/label'])
