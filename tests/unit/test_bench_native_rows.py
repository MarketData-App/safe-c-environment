"""Phase 2 Task 19 (plan amendment FR6 N4): the route dimension, C rows in plan, run and report, and native kernel trials.

Framework tests use framework cases and synthetic variants only (H3): the control case gets synthetic C variants and
caller points; no example case is loaded. Adaptations of the source test text to the real framework (FR6 N4 report):
the control case implements no separate py-optimized variant, so the Python key is py-reference; points are named by
`name`; the container module is container/bench_native_job.py."""
import argparse, contextlib, copy, io, json, sys, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, bench_plan as bp
POLICY=bm.load_policy(ROOT);ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
EX=None   # H3: framework tests use framework cases and synthetic variants only
SMALL={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256}
LARGE={'kind':'synthetic','size':'large','seed':1,'sha256':None,'rows':13230}

def case_with_c():
    """The framework control case with synthetic C variants and caller points (never the example case)."""
    c=copy.deepcopy(bm.load_case(ROOT,'bench-control-spin'))
    c['variants']=[v for v in c['variants'] if not v['id'].startswith('c-')]
    c['variants']+=[{'id':'c-serial','language':'c','workers':['direct'],'status':'implemented','routes':['stdio','shm','inproc']},
                    {'id':'c-threads','language':'c','workers':[1,2,4],'status':'implemented','routes':['stdio','shm','inproc']}]
    for pt in c['points']:pt['variants']=list(dict.fromkeys(pt['variants']+['c-serial','c-threads']))
    return c

def case_with_kernel():
    """case_with_c with warm and cold caller modes and a kernel point (a decision plan: the smoke plan of every route
    exceeds the smoke job deadline on four CPUs)."""
    c=case_with_c();c['points'][0]['modes']=['warm','cold']
    c['points'].append({'name':'qual-kernel','scope':'kernel','size':'small','modes':['direct'],'variants':['py-reference','c-serial'],'class':'exploratory'})
    return c

def trials(plan):return [t for s in plan['sessions'] for t in s['trials']]

class NativeRowTests(unittest.TestCase):
    def test_policy_route_labels(self):
        self.assertEqual(set(POLICY['routes']),{'stdio','shm','inproc'})
        self.assertIn('corrupt the interpreter',POLICY['routes']['inproc'])
        self.assertEqual(POLICY['native_timing'],{'abs_ns':2000000,'rel':0.05})
    def test_case_rows_expand_routes_and_block_inproc_cold(self):
        rows,blocked=bp.case_rows(case_with_c(),ENV4)
        keys={(r['variant'],r['workers'],r['route']) for r in rows}
        self.assertIn(('c-serial','direct','shm'),keys);self.assertIn(('c-threads',4,'inproc'),keys);self.assertIn(('py-reference','direct',None),keys)
        self.assertEqual(len([k for k in keys if k[0]=='c-threads']),9)
        plan=bp.build_plan(case_with_kernel(),POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        reasons={(b['variant'],b.get('route'),b.get('mode')):b['reason'] for b in plan['blocked_rows']}
        self.assertEqual(reasons[('c-serial','inproc','cold')],'inproc cold: not-applicable (library load is the startup phase)')
        self.assertFalse([t for t in trials(plan) if t.get('route')=='inproc' and t['mode']=='cold'])
        self.assertTrue([t for t in trials(plan) if t.get('route')=='shm' and t['mode']=='cold'])
    def test_a_variant_without_routes_has_the_stdio_route_and_a_point_narrows_the_routes(self):
        c=case_with_c();del c['variants'][-1]['routes']
        rows,_=bp.case_rows(c,ENV4)
        self.assertEqual({r['route'] for r in rows if r['variant']=='c-threads'},{'stdio'})
        c=case_with_c();c['points'][0]['routes']=['shm']
        plan=bp.build_plan(c,POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        self.assertEqual({t['route'] for t in trials(plan) if t['variant'].startswith('c-')},{'shm'})
    def test_python_rows_carry_no_route_and_keep_the_phase_1_plan(self):
        c=copy.deepcopy(bm.load_case(ROOT,'bench-control-spin'))
        plan=bp.build_plan(c,POLICY,mode='smoke',dataset=SMALL,seed=3,envelope=ENV4)
        self.assertFalse([t for t in trials(plan) if 'route' in t]);self.assertNotIn('route_budget',plan)
        self.assertFalse([r for r in plan['rows'] if 'route' in r])
    def test_c_trials_carry_the_route_label_of_the_policy(self):
        plan=bp.build_plan(case_with_kernel(),POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        got={(t['route'],t['route_label']) for t in trials(plan) if t.get('route')}
        self.assertEqual(got,{(r,POLICY['routes'][r]) for r in ('stdio','shm','inproc')})
        kernel=[t for t in trials(plan) if t['scope']=='kernel' and t['variant'].startswith('c-')]
        self.assertTrue(kernel);self.assertFalse([t for t in kernel if 'route' in t])     # a kernel row has no transfer route
    def test_plan_blocks_c_threads_beyond_envelope(self):
        env={'cpus':2,'cpuset':[0,1],'smt_siblings':[],'reduced':True,'multicore':'PASS'}
        plan=bp.build_plan(case_with_c(),POLICY,mode='smoke',dataset=SMALL,seed=3,envelope=env)
        self.assertIn(('c-threads',4),[(r['variant'],r['workers']) for r in plan['blocked_rows']])
        self.assertFalse([t for t in trials(plan) if t['variant']=='c-threads' and t['workers']==4])
        self.assertFalse([t for t in trials(plan) if t.get('route')=='inproc' and t['mode']=='cold'])
    def test_native_timing_check(self):
        row={'variant':'c-serial','scope':'kernel','wall_ns':10**8,'cpu_usage_usec':10**5,'self_timing':{'mono_ns':10**8,'cpu_ns':9*10**7},'native_sha256':'a'*64,'warmup':False}
        self.assertEqual(bench.check_native_timing([row],POLICY,'a'*64),[])
        self.assertTrue(bench.check_native_timing([dict(row,self_timing={'mono_ns':2*10**8,'cpu_ns':1})],POLICY,'a'*64))
        self.assertTrue(bench.check_native_timing([dict(row,self_timing={'mono_ns':10**8,'cpu_ns':10**9})],POLICY,'a'*64))
        self.assertTrue(bench.check_native_timing([row],POLICY,'b'*64))
        self.assertTrue(bench.check_native_timing([dict(row,self_timing=None)],POLICY,'a'*64))      # a C kernel row needs its self-timing
        self.assertEqual(bench.check_native_timing([dict(row,variant='py-reference',self_timing=None)],POLICY,'b'*64),[])
        small={'mono_ns':10**8+2*10**6,'cpu_ns':1};self.assertEqual(bench.check_native_timing([dict(row,wall_ns=10**8,self_timing=small)],POLICY,'a'*64),[])   # max(abs, rel x wall)
    def test_observation_schema_knows_routes_and_stays_backward_compatible(self):
        s=json.loads((ROOT/'schemas/bench-observation.json').read_text())
        self.assertIn('route',json.dumps(s));self.assertIn('copied_bytes',json.dumps(s))
        self.assertNotIn('route',s.get('required',[]))
        from schema_check import validate
        old=json.loads((ROOT/'tests/unit/fixtures/bench-observation-phase1.json').read_text())
        from evidence import GateError
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',old)   # FR5A-03 migration: its two solver counts are project counts now
        old['verdict']={k:v for k,v in old['verdict'].items() if k in ('failures','model_errors','reduction')}
        validate(ROOT,'bench-observation',old)     # a Phase 1 observation without route stays valid (C1) once its verdict is migrated
        new=dict(old,variant='c-serial',route='shm',route_label=POLICY['routes']['shm'],copied_bytes=4096,load_process=None,self_timing=None,
                 native_sha256=None,phases=dict(old['phases'],transport=12345))
        validate(ROOT,'bench-observation',new)
        kernel=dict(old,variant='c-serial',scope='kernel',route=None,self_timing={'mono_ns':5,'cpu_ns':4},native_sha256='a'*64)
        validate(ROOT,'bench-observation',kernel)
        from evidence import GateError
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',dict(old,route='tcp'))
    def test_case_schema_takes_routes_and_stays_backward_compatible(self):
        from schema_check import validate
        from evidence import GateError
        c=case_with_c();validate(ROOT,'bench-case',c)
        validate(ROOT,'bench-case',bm.load_case(ROOT,'bench-control-spin'))
        c['points'][0]['routes']=['stdio'];validate(ROOT,'bench-case',c)
        bad=case_with_c();bad['variants'][-1]['routes']=['tcp']
        with self.assertRaises(GateError):validate(ROOT,'bench-case',bad)
    def test_compare_rows_carry_route_labels(self):
        rows=[{'variant':'c-serial','route':r,'route_label':POLICY['routes'][r]} for r in ('stdio','shm','inproc')]
        lines=bench.route_summary(rows,POLICY)
        self.assertEqual(len(lines),3);self.assertTrue(any('corrupt the interpreter' in l for l in lines))
        self.assertEqual(bench.route_summary([{'variant':'py-reference','route':None}],POLICY),[])
    def test_the_strongest_python_row_is_the_smallest_median_wall(self):
        def obs(block,wall):return {'trial_id':f't{block}-{wall}','block':block,'warmup':False,'eligible':True,'work_units':1,'loops':1,'wall_ns':wall}
        groups={('p','caller','warm','py-reference','direct','small',None):[obs(0,900),obs(1,910)],
                ('p','caller','warm','py-threads',2,'small',None):[obs(0,400),obs(1,410)],
                ('p','caller','warm','c-serial','direct','small','stdio'):[obs(0,10),obs(1,11)],
                ('p','caller','cold','py-processes',2,'small',None):[obs(0,1),obs(1,1)]}
        self.assertEqual(bench.best_python_key(groups,'p','caller','warm','small'),('p','caller','warm','py-threads',2,'small',None))
        self.assertIsNone(bench.best_python_key(groups,'p','kernel','direct','small'))
    def test_compare_uses_the_decide_rule_for_the_best_python_row(self):
        """N4-A02: compare and decide call one rule (bench_decide.best_python_of); a pool row that fails the pool CPU guard
        is never the best Python row, in compare as in decide."""
        import bench_decide
        def obs(block,wall,cpu):return {'trial_id':f't{block}-{wall}','block':block,'warmup':False,'eligible':True,'work_units':1,'loops':1,'wall_ns':wall,'cpu_usage_usec':cpu}
        ref=('p','caller','warm','py-reference','direct','small',None);thr=('p','caller','warm','py-threads',2,'small',None)
        groups={ref:[obs(0,900,1),obs(1,910,1)],thr:[obs(0,400,3),obs(1,410,3)],          # the pool row uses 3x the CPU of the serial row
                ('p','caller','warm','c-serial','direct','small','stdio'):[obs(0,10,1),obs(1,11,1)]}
        self.assertEqual(bench.best_python_key(groups,'p','caller','warm','small',guard=0.25),ref)     # fails a 25 % guard
        self.assertEqual(bench.best_python_key(groups,'p','caller','warm','small',guard=2.5),thr)      # within a 250 % guard
        self.assertEqual(bench.best_python_key(groups,'p','caller','warm','small',guard=None),thr)     # no guard
        rows=[{'point':k[0],'scope':'caller','mode':k[2],'variant':k[3],'workers':k[4],'route':None,'language':'python','eligible':True,
               'wall':bench.per_trial(v,'wall_ns'),'cpu':{b:x*1000.0 for b,x in bench.per_trial(v,'cpu_usage_usec').items()}} for k,v in groups.items() if not k[3].startswith('c-')]
        for guard,want in ((0.25,'py-reference'),(2.5,'py-threads'),(None,'py-threads')):
            pol={'metric':'wall_ns_per_unit','modes':['warm'],'points':['p'],'pool_cpu_guard':guard}
            real=bench_decide.best_python_of
            with self.subTest(guard=guard),mock.patch.object(bench_decide,'best_python_of',side_effect=real) as shared:
                self.assertEqual(bench_decide.Decider({'rows':rows},pol,None,{}).best_python('p','warm')['variant'],want)
                self.assertEqual(bench.best_python_key(groups,'p','caller','warm','small',guard=guard)[3],want)
                self.assertEqual(shared.call_count,2)             # decide once, compare once: one shared rule
    def test_compare_takes_the_strictest_framework_pool_cpu_guard(self):
        """N4-A02: compare has no decision policy; it applies the smallest pool_cpu_guard of the framework decision policies
        (a pool row that passes it passes the guard of every framework policy). No guard when every policy has null."""
        self.assertEqual(bench.compare_pool_cpu_guard(POLICY),0.25)
        pol=copy.deepcopy(POLICY)
        for p in pol['decision_policies'].values():p['pool_cpu_guard']=None
        self.assertIsNone(bench.compare_pool_cpu_guard(pol))
        pol['decision_policies']['demo-cpu-40']['pool_cpu_guard']=0.1;pol['decision_policies']['demo-latency-2x']['pool_cpu_guard']=0.5
        self.assertEqual(bench.compare_pool_cpu_guard(pol),0.1)
    def test_the_report_names_the_language_and_route_of_each_row(self):
        rows=[{'variant':'c-serial','workers':'direct','route':'inproc','route_label':POLICY['routes']['inproc'],'scope':'caller','mode':'warm','point':'p',
               'best_python':'py-reference','relative_wall_vs_best_python':{'outcome':'FASTER','ratio':0.5,'low':0.4,'high':0.6}},
              {'variant':'py-reference','workers':'direct','route':None}]
        lines=bench.route_report_lines({'rows':rows,'routes':bench.route_summary(rows,POLICY)})
        self.assertTrue(lines[0].startswith('Routes (Task 19): route inproc: in-process shared library'))
        self.assertIn('C row c-serial route inproc (caller/warm at p): against best Python py-reference: FASTER ratio 0.5 [0.4, 0.6]',lines[1])
        self.assertEqual([bench.row_language(r) for r in rows],['c','python'])
        self.assertEqual(bench.route_report_lines({'rows':[rows[1]]}),[])            # a Python-only run keeps its report
    def test_job_end_check(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('bench_native_c',str(ROOT/'container/bench_native_job.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        self.assertEqual(m.job_end_problems({'memfd':[],'dev_shm':[]},{'memfd':[],'dev_shm':[]}),[])
        self.assertTrue(m.job_end_problems({'memfd':[],'dev_shm':[]},{'memfd':['/memfd:bd-in (deleted)'],'dev_shm':[]}))
        self.assertTrue(m.job_end_problems({'memfd':[],'dev_shm':[]},{'memfd':[],'dev_shm':['seg']}))
        self.assertEqual(m.job_end_problems({'memfd':['a'],'dev_shm':['b']},{'memfd':['a'],'dev_shm':['b']}),[])
        self.assertEqual(m.caller_env({}),{'SAFE_C_BENCH_ROLE':'caller'})
    def test_c_rows_carry_selector_unit_and_dataset_ref(self):
        c=case_with_c();c['selectors']=list(dict.fromkeys(c.get('selectors',['all'])+['sel-a']))
        c['points'].append(dict(c['points'][0],name='unit-sel-a',selector='sel-a',unit='sel-a/full'))   # opaque selector (H3: no model name)
        plan=bp.build_plan(c,POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        got=[t for t in trials(plan) if t.get('point')=='unit-sel-a' and t['variant'].startswith('c-')]
        self.assertTrue(got);self.assertTrue(all(t.get('selector')=='sel-a' and t.get('unit')=='sel-a/full' for t in got))
    def test_route_budget_per_selector(self):
        pol=copy.deepcopy(POLICY);pol['budgets']['estimate_share_per_selector']={'sel-a':0.1}
        c=case_with_c();c['selectors']=list(dict.fromkeys(c.get('selectors',['all'])+['sel-a']))
        c['points']=[dict(c['points'][0],name='p-all'),dict(c['points'][0],name='p-sel',selector='sel-a')]
        plan=bp.build_plan(c,pol,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        b=plan['route_budget'];self.assertLess(b['stdio']['sel-a'],b['stdio']['all'])
        self.assertAlmostEqual(b['stdio']['sel-a'],0.1*b['stdio']['all'],places=6)
    def test_route_budget_is_recorded_and_below_the_cap(self):
        plan=bp.build_plan(case_with_c(),POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        self.assertEqual(set(plan['route_budget']),{'stdio','shm','inproc'})                       # per route, then per selector
        self.assertLessEqual(plan['estimate_seconds'],POLICY['budgets']['decision_cap_seconds'])
    def test_c_kernel_trials_are_observed_once(self):
        plan=bp.build_plan(case_with_kernel(),POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4);plan['pyperf']={'values':3,'warmups':1}
        self.assertTrue([t for t in trials(plan) if t['scope']=='kernel' and t['variant']=='c-serial'])
        obs=[{'trial_id':t['trial_id'],'warmup':t['warmup']} for t in trials(plan) for _ in range(1 if t['scope']!='kernel' or t['variant'].startswith('c-') else 4)]
        self.assertEqual(bp.check_trial_design(plan,obs),[])
    def test_second_dataset_identity_is_checked(self):
        """A plan whose plan.datasets identity differs from the case derivation is INVALID_EXPERIMENT before any container."""
        c=case_with_c();c['points'].append(dict(c['points'][0],name='second-set',dataset_ref='synthetic:medium'))
        plan=bp.build_plan(c,POLICY,mode='decision',dataset=LARGE,seed=3,envelope=ENV4)
        self.assertEqual(bench.dataset_identity_reasons(c,POLICY,plan),[])
        bad=copy.deepcopy(plan);bad['datasets']['synthetic:medium']['rows']=7
        self.assertTrue(bench.dataset_identity_reasons(c,POLICY,bad))
        args=argparse.Namespace(case='bench-control-spin',plan=None,project=None,format='json',mode='decision',dataset='synthetic:large',calibrate=None)
        import container_policy
        out=io.StringIO()
        with mock.patch.object(bm,'load_case',lambda *a,**k:copy.deepcopy(c)),mock.patch.object(bm,'case_rules',lambda *a,**k:None),\
             mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:ENV4),\
             mock.patch.object(bp,'build_plan',lambda *a,**k:copy.deepcopy(bad)),\
             mock.patch.object(bench,'doctor_probe',side_effect=AssertionError('a container started')),\
             mock.patch.object(bench,'new_run_dir',side_effect=AssertionError('a run started')),contextlib.redirect_stdout(out):
            code=bench.run_cmd(ROOT,args)
        self.assertEqual(code,1);self.assertIn('INVALID_EXPERIMENT',out.getvalue())

def native_job():
    import importlib.util
    spec=importlib.util.spec_from_file_location('bench_native_c',str(ROOT/'container/bench_native_job.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

GOOD_KERNEL={'program':'bd-kernel','args':['--input','{input}','--records','{records}','--loops','{loops}','--threads','{threads}','--output','{output}']}
VALUES={'input':'/p/in','records':'4','loops':'2','threads':'0','output':'/p/out'}

class KernelArgvTests(unittest.TestCase):
    """N4-A04: the container kernel argv (container/bench_native_job.py kernel_argv) is the one argv builder; it refuses a
    literal with '/' or ';', a missing or duplicate placeholder, a program outside PROGRAM_RE and (run_native_kernel) a
    program that is not a built target of plan.native. The host copy bench_model.native_kernel_argv had no caller and no
    literal check; it is removed."""
    def test_a_good_declaration_gives_the_argv(self):
        m=native_job()
        self.assertEqual(m.kernel_argv(GOOD_KERNEL,VALUES),[str(m.NATIVE_DIR/'bd-kernel'),'--input','/p/in','--records','4','--loops','2','--threads','0','--output','/p/out'])
    def test_the_refusals(self):
        m=native_job()
        def edit(f):k=copy.deepcopy(GOOD_KERNEL);f(k);return k
        cases={'literal with a slash':edit(lambda k:k['args'].append('../x')),
               'literal with a semicolon':edit(lambda k:k['args'].append('a;b')),
               'literal with a space':edit(lambda k:k['args'].append('a b')),
               'missing placeholder':edit(lambda k:k['args'].remove('{loops}')),
               'duplicate placeholder':edit(lambda k:k['args'].append('{input}')),
               'duplicate threads':edit(lambda k:k['args'].append('{threads}')),
               'unknown placeholder':edit(lambda k:k['args'].append('{home}')),
               'program with a slash':edit(lambda k:k.update(program='../bd-kernel')),
               'program with upper case':edit(lambda k:k.update(program='Bd-kernel')),
               'program too long':edit(lambda k:k.update(program='b'*64)),
               'extra key':edit(lambda k:k.update(env={})),
               'too few arguments':{'program':'bd-kernel','args':['{input}','{records}','{loops}']},
               'too many arguments':edit(lambda k:k['args'].extend(['x']*15))}
        for name,kernel in cases.items():
            with self.subTest(name),self.assertRaises(ValueError):m.kernel_argv(kernel,VALUES)
    def test_a_program_outside_the_built_targets_is_an_ineligible_row(self):
        import tempfile
        m=native_job()
        with tempfile.TemporaryDirectory() as tmp:
            real=m.Path
            g={'read_counters':lambda:{},'observation':lambda plan,trial,phase,b,e,note,runner,warmup:dict(note,trial_id=trial['trial_id'])}
            plan={'sizes':{'small':4},'native_kernel':GOOD_KERNEL,'native':{'other-kernel':'a'*64}}
            trial={'trial_id':'k0','tier':'small','loops':2,'workers':'direct','warmup':False}
            with mock.patch.dict(m._COORD,{'g':g}),mock.patch.object(m,'_benchlab',lambda name:object()),mock.patch.object(m,'Path',lambda p:real(tmp)/'private' if p=='/work/bench/private' else real(p)):
                obs,phases,files=m.run_native_kernel(None,plan,trial,{'path':'d','sha256':'b'*64},'ref',1e18,None)
                bad=dict(plan,native_kernel=dict(GOOD_KERNEL,args=GOOD_KERNEL['args']+['a;b']),native={'bd-kernel':'a'*64})
                obs2,_,_=m.run_native_kernel(None,bad,trial,{'path':'d','sha256':'b'*64},'ref',1e18,None)
        self.assertEqual((obs[0]['eligible'],obs[0]['failures']),(False,{'native-declaration':1}))
        self.assertEqual((obs2[0]['eligible'],obs2[0]['failures']),(False,{'native-declaration':1}))
    def test_the_host_has_no_second_argv_builder(self):
        self.assertFalse(hasattr(bm,'native_kernel_argv'))

class RouteRuleTests(unittest.TestCase):
    """N4-A05: `routes` belongs to a C variant or a caller point only, and a point route list is a subset of the routes of
    the case's C variants; case validation refuses each wrong use with a GateError (before the opportunity record check)."""
    def refused(self,c,text):
        from evidence import GateError
        with self.assertRaisesRegex(GateError,text):bm.case_rules(ROOT,c)
    def test_routes_on_a_python_variant_are_refused(self):
        c=case_with_c();next(v for v in c['variants'] if v['id']=='py-reference')['routes']=['stdio']
        self.refused(c,'py-reference: routes belong to a C variant')
    def test_routes_on_a_kernel_point_are_refused(self):
        c=case_with_kernel();c['points'][-1]['routes']=['stdio']
        self.refused(c,'qual-kernel: a kernel point has no routes')
    def test_a_point_route_outside_the_variant_routes_is_refused(self):
        c=case_with_c();c['variants'][-1]['routes']=['stdio'];c['variants'][-2]['routes']=['stdio','shm'];c['points'][0]['routes']=['shm','inproc']
        self.refused(c,'routes inproc are not routes of a C variant')
        c=case_with_c();del c['variants'][-1]['routes'];del c['variants'][-2]['routes'];c['points'][0]['routes']=['shm']    # default stdio
        self.refused(c,'routes shm are not routes of a C variant')
    def test_a_point_route_subset_passes_the_route_rules(self):
        from evidence import GateError
        c=case_with_c();c['points'][0]['routes']=['shm']
        self.assertTrue(bm.route_rules(c))
        with self.assertRaisesRegex(GateError,'opportunity record'):bm.case_rules(ROOT,c)     # the next check: no record for the synthetic C rows
        self.assertTrue(bm.route_rules(case_with_kernel()))

class BlockedStartTests(unittest.TestCase):
    """N4-A10: the host turns each BLOCKED row of a timing job into a run reason, so the run is not VALID."""
    def test_each_blocked_row_is_a_reason(self):
        row={'status':'PASS','blocked_rows':[{'variant':'c-serial','workers':'direct','route':'shm','mode':'warm','selector':'all','trials':['t1'],
                                               'reason':'warm C start failed (child exit 3, BinaryRefused)'}]}
        self.assertEqual(bench.blocked_start_reasons(row),['planned row BLOCKED: c-serial route shm warm: warm C start failed (child exit 3, BinaryRefused)'])
        self.assertEqual(bench.blocked_start_reasons({'status':'PASS'}),[])
    def test_a_malformed_blocked_row_is_still_a_reason(self):
        for bad in ('x',['x'],[{'variant':7}],[{}],{'a':1}):
            with self.subTest(bad=bad):
                got=bench.blocked_start_reasons({'blocked_rows':bad})
                self.assertTrue(got);self.assertTrue(all(r.startswith('planned row BLOCKED') and len(r)<=300 for r in got))

if __name__=='__main__':unittest.main()
