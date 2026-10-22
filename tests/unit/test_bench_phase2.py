"""EX-13 (Phase 2 Task 23, framework part): the Phase 2 B cases and P subcases (tools/bench_phase2.py) and the coordinator
jobs native-overlap, agreement-controls and failure-controls (container/bench_phase2_job.py).

The checks are tested on synthetic rows shaped like the rows of a real bench run (H3: framework tests never name the
example). The real controls run in bench selftest --suite cases on the example projects found by layout."""
import copy, hashlib, importlib.util, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, bench_phase2 as b2
from evidence import GateError
FIX=json.loads((ROOT/'safety/performance-fixtures.json').read_text());POLICY=bm.load_policy(ROOT)
ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
LABEL=POLICY['routes'];G='f'*64;N=POLICY['sizes']['small']

def trace(workers,spans,result='ab'*8,threads=None):
    head='# workers=%d threads=%d max_inflight=%d submitted=%d executed=%d result=%s'%(
        workers,len({s[0] for s in spans}) if threads is None else threads,min(len(spans),2*workers),len(spans),len(spans),result)
    return [head]+['%d %d %d %d %d'%s for s in spans]
def overlap_doc(workers,spans,affinity=4,cpu_usec=10**6):return {'exit':0,'trace':trace(workers,spans),'affinity':affinity,'cgroup_cpu_usec':cpu_usec,'wall_ns':10**6}
GOOD=[(0,0,100,0,90),(1,10,110,1,95),(0,100,200,2,90),(1,110,210,3,92)]

def trial(tid,scope,mode,variant,route=None,warmup=False,tier='small'):
    return {'trial_id':tid,'scope':scope,'mode':mode,'variant':variant,'workers':'direct','route':route,'warmup':warmup,'tier':tier,'point':scope+'-point','selector':'all'}

def obs(t,**k):
    c=t['variant'].startswith('c-') and t['scope']=='caller'
    row={'trial_id':t['trial_id'],'scope':t['scope'],'mode':t['mode'],'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],'point':t['point'],
         'warmup':t['warmup'],'runner':'safe-c-trial-runner','eligible':True,'work_units':N,'result_sha256':'b'*64,'verdict':{'failures':{}},
         'route':t['route'] if c else None,'route_label':LABEL[t['route']] if c else None,'copied_bytes':(0 if t['route']=='inproc' else 7224) if c else None,
         'phases':{'prepare':10,'pool_start':None,'transport':5 if c else None,'work':100,'materialize':10},'pids_start':13,'pids_end':13,
         'load_process':{'pid':41,'role':'caller'} if c and t['route']=='inproc' else None}
    if c and t['mode']=='cold':row['pids_end']=15
    row.update(k);return row

def fake_ev():
    """A run record shaped like a real smoke run: Python and C caller rows on three routes (warm and cold; in-process warm
    only), kernel rows, warm startup and teardown phases, the build record and the plan."""
    ts=[trial('w-s','caller','warm','c-serial','stdio',True),trial('w-m','caller','warm','c-serial','shm',True),trial('w-i','caller','warm','c-serial','inproc',True),
        trial('p-w','caller','warm','py-reference'),trial('p-c','caller','cold','py-reference'),
        trial('c-ws','caller','warm','c-serial','stdio'),trial('c-cs','caller','cold','c-serial','stdio'),trial('c-wm','caller','warm','c-serial','shm'),
        trial('c-cm','caller','cold','c-serial','shm'),trial('c-wi','caller','warm','c-serial','inproc'),
        trial('k-c','kernel','direct','c-serial'),trial('k-p','kernel','direct','py-reference')]
    rows=[obs(t) for t in ts]
    for r in rows:
        if r['scope']=='kernel':r.update(route=None,route_label=None,copied_bytes=None,runner='pyperf' if r['variant'].startswith('py-') else 'safe-c-trial-runner')
    ph=lambda phase,mode,route,a,b,tid,variant='c-serial':{'phase':phase,'variant':variant,'workers':'direct','mode':mode,'route':route,'pids_start':a,'pids_end':b,'scope':'caller','trial_id':tid}
    phases=[ph('pool_start','warm','stdio',5,7,'w-s'),ph('pool_start','warm','shm',9,11,'w-m'),ph('pool_start','warm','inproc',13,13,'w-i'),
            ph('teardown','cold','stdio',15,13,'c-cs'),ph('teardown','cold','shm',15,13,'c-cm'),ph('teardown','warm','stdio',11,9,'w-s'),
            ph('teardown','warm','shm',7,5,'w-m'),ph('teardown','warm','inproc',3,3,'w-i'),ph('teardown','warm',None,13,13,'p-w','py-reference')]
    plan={'sessions':[{'session':'s0','trials':ts}],'memory':[],'envelope':dict(ENV4),'project_dir':'proj','seed':5}
    native={'binaries':{'demo-kernel':{'path':'k','sha256':'1'*64},'demo-worker':{'path':'w','sha256':'2'*64},'libdemo.so':{'path':'l','sha256':'3'*64}},
            'glib':{'name':b2.GLIB_NAME,'sha256':G},'flags':{'problems':[]}}
    run={'envelope':dict(ENV4),'dataset':{'kind':'synthetic','size':'small','seed':7,'sha256':None,'rows':N},'case_version':3,'plan':{'project_identity':'a'*64},
         'native':{'glib_sha256':G,'agreement':{'check':'x-native','status':'PASS'}}}
    return {'plan':plan,'run':run,'native':native,'observations':rows,'phases':phases,'dir':'r'}

def job_module():
    spec=importlib.util.spec_from_file_location('bench_phase2_job_test',ROOT/'container/bench_phase2_job.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class InventoryTests(unittest.TestCase):
    def test_b_cases_are_appended_with_exact_names(self):
        names={c['id']:c['name'] for c in FIX['b_cases']}
        self.assertEqual([names[k] for k in ('B04','B06','B07','B08','B11','B16','B13-echo')],['actual-c-concurrency','equal-work-and-correctness-oracle',
            'fair-build-and-resource-context','caller-boundary-and-cold-warm-separation','c-pool-ownership-and-lifecycle','failure-cancellation-and-cleanup',
            'measurement-perturbation-and-cache-policy-echo-control'])
        self.assertEqual([c['id'] for c in FIX['b_cases']][:11],['B01','B02','B03','B05','B09','B10','B13','B12','B14','B15','B18'])   # earlier entries kept (append-only)
        self.assertEqual([c['id'] for c in FIX['b_cases']][11:18],['B04','B06','B07','B08','B11','B16','B13-echo'])     # EX-17 appends B17 (phase 3) after them
        self.assertTrue(all(c['phase']==2 for c in FIX['b_cases'][11:18]))
    def test_pipeline_subcases_are_appended(self):
        subs={s['parent']:s for s in FIX['pipeline_subcases']}
        self.assertEqual([s['parent'] for s in FIX['pipeline_subcases']],['P01','P07','P11','P10','P15','P02','P04','P16'])
        self.assertEqual(subs['P02']['variants'],['sanitized-or-debug-artifact','wrong-dependency','hidden-algorithm-or-precision-change','incomplete-workload-inventory','different-cpu-envelope','different-selector-panel-or-dataset'])
        self.assertEqual(subs['P04']['variants'],['unlimited-pool-or-queue','unauthorized-thread-api','unsafe-native-loading','host-execution','changed-affinity','unmanaged-subprocess','profiler-privilege'])
        self.assertEqual(subs['P16']['variants'],['skip-useful-work','reuse-answer','no-op-native-kernel','removed-result-consumption','selector-overcompute','selector-no-op'])
        self.assertEqual({(p,b2.NAMES[p]) for p in ('P02','P04','P16')},{(s['parent'],s['name']) for s in FIX['pipeline_subcases'] if s['parent'] in ('P02','P04','P16')})
        self.assertEqual(set(b2.ALL_VARIANTS),{(s['parent'],v) for s in FIX['pipeline_subcases'] if s['parent'] in ('P02','P04','P16') for v in s['variants']})
    def test_contract_rows(self):
        c=json.loads((ROOT/'safety/contract.json').read_text());names={(s['parent'],s['name']) for s in c['subcases']}
        for p,v in b2.ALL_VARIANTS:
            self.assertIn((p,b2.NAMES[p]),names);self.assertIn((p,b2.NAMES[p]+'/'+v),names)
        self.assertEqual(len(c['subcases']),23+3+19)
    def test_hooks(self):
        self.assertIn('bench_phase2.phase2_cases(root,run_dir,project)',(ROOT/'tools/bench.py').read_text())
        self.assertIn('import bench_phase2_job as _bench_phase2;_bench_phase2.register(job,globals())',(ROOT/'container/bench-coordinator.py').read_text())
        for name in ('native-overlap','agreement-controls','failure-controls'):self.assertIn(f"@job('{name}')",(ROOT/'container/bench_phase2_job.py').read_text())
    def test_privilege_keys_are_refused_before_any_container(self):
        for key in b2.PRIVILEGE_KEYS:
            self.assertIn(key,bench.HOST_TUNING_KEYS)
            with self.assertRaises(GateError):bench.reject_host_tuning({key:True})
        bench.reject_host_tuning({'mode':'smoke'})
    def test_generic_mutations_only(self):
        self.assertEqual(b2.AGREEMENT_MUTATIONS,('skipped-chunk','wrong-order','missing-output','hardcoded-answer','precision-change','range-change'))
        self.assertEqual(len(b2.AGREEMENT_MUTATIONS),6)
        self.assertEqual(b2.required_mutations(ROOT,None),list(b2.AGREEMENT_MUTATIONS))

class ConcurrencyTests(unittest.TestCase):
    def test_concurrency_needs_working_overlapping_workers(self):
        self.assertEqual(b2.check_concurrency(overlap_doc(2,GOOD),2,ENV4)['status'],'PASS')
        for doc in (overlap_doc(2,[(0,0,100,0,90),(0,100,200,1,90),(0,200,300,2,90),(0,300,400,3,90)]),     # serial dispatch
                    overlap_doc(2,[(0,0,100,0,90),(1,10,110,1,0),(0,100,200,2,90),(1,110,210,3,0)]),       # an idle worker
                    overlap_doc(2,[(0,0,100,0,90),(1,200,300,1,90)]),                                      # no overlap
                    overlap_doc(2,GOOD,affinity=1),                                                        # one-CPU affinity
                    overlap_doc(2,[(0,0,100,0,9*10**6),(1,10,110,1,9*10**6)],cpu_usec=1000),                # task CPU above the cgroup CPU
                    overlap_doc(2,[(0,0,100,0,90),(1,10,110,1,95),(2,10,110,2,95),(1,110,210,3,92)]),     # more threads than workers
                    overlap_doc(2,[(0,0,100,0,90),(1,10,110,0,95),(0,100,200,2,90),(1,110,210,3,92)]),    # a repeated task ID
                    dict(overlap_doc(2,GOOD),exit=1)):
            self.assertEqual(b2.check_concurrency(doc,2,ENV4)['status'],'FAIL',doc['trace'][1:])
        self.assertEqual(b2.check_concurrency(overlap_doc(2,GOOD),2,dict(ENV4,multicore='BLOCKED'))['status'],'FAIL')
        self.assertEqual(b2.check_concurrency(overlap_doc(1,[(0,0,10,0,9),(0,10,20,1,9)]),1,ENV4)['status'],'PASS')
        self.assertEqual(b2.check_concurrency(overlap_doc(1,[(0,0,10,0,9),(1,10,20,1,9)]),1,ENV4)['status'],'FAIL')   # one worker, two identities
    def test_parse_trace(self):
        p=b2.parse_trace(['# workers=0 result='+'cd'*8]+trace(2,GOOD));self.assertEqual((p['serial'],sorted(p['sections']),p['problems']),('cd'*8,[2],[]))
        for bad in (['# workers=0'],['# workers=2 threads=2 max_inflight=4 submitted=4 executed=4']+['x y'],['0 1 2 3 4'],trace(2,GOOD)+trace(2,GOOD),['# workers=0 result='+'0'*16]*2):
            self.assertTrue(b2.parse_trace(bad)['problems'],bad)
        self.assertTrue(b2.parse_trace(['0 1 2 3 4']*(b2.MAX_TRACE_LINES+1))['problems'])
    def overlap_record(self,lines,affinity=4):return {'exit':0,'lines':lines,'affinity':affinity,'cgroup_cpu_usec':10**6,'wall_ns':10**6}
    def test_project_overlap_record(self):
        r='ab'*8;spans4=GOOD+[(2,20,120,4,90),(3,30,130,5,90),(2,120,220,6,90),(3,130,230,7,90)]
        lines=['# workers=0 result='+r]+trace(1,[(0,0,10,0,9),(0,10,20,1,9),(0,20,30,2,9),(0,30,40,3,9)],r)+trace(2,GOOD,r)+trace(4,spans4,r)
        st,detail=b2.b04_project(self.overlap_record(lines),ENV4)
        self.assertEqual((st,detail['problems']),('PASS',[]),detail);self.assertEqual(detail['masquerades'],{'serial-dispatch':'FAIL','one-cpu-affinity':'FAIL'})
        self.assertEqual(b2.b04_project(self.overlap_record([lines[0].replace(r,'cd'*8)]+lines[1:]),ENV4)[0],'FAIL')    # a result differs from the serial run
        self.assertEqual(b2.b04_project(self.overlap_record(lines[:1]+lines[6:]),ENV4)[0],'FAIL')                        # the one-worker section is missing
        self.assertEqual(b2.b04_project(self.overlap_record(lines,affinity=1),ENV4)[0],'FAIL')
        self.assertEqual(b2.b04_project(self.overlap_record(lines),dict(ENV4,multicore='BLOCKED'))[0],'BLOCKED')
        self.assertEqual(b2.b04_project(self.overlap_record(lines),dict(ENV4,cpus=1))[0],'BLOCKED')
    def test_one_row_one_chunk(self):
        self.assertEqual(b2.check_one_row_one_chunk([{'trial_id':'a','work_units':1,'pool':{'chunks':1,'chunk_sizes':[1]}},{'work_units':256,'pool':{'chunks':2,'chunk_sizes':[128,128]}}]),[])
        self.assertTrue(b2.check_one_row_one_chunk([{'trial_id':'a','work_units':1,'pool':{'chunks':2,'chunk_sizes':[1,0]}}]))

class AgreementTests(unittest.TestCase):
    def test_agreement_controls(self):
        doc={'control':{'eligible':True},'mutations':{m:{'eligible':False,'changed':True} for m in b2.AGREEMENT_MUTATIONS}}
        self.assertEqual(b2.check_agreement_controls(doc),[])
        for edit in (lambda d:d['mutations']['wrong-order'].update(eligible=True),lambda d:d['mutations']['skipped-chunk'].update(changed=False),
                     lambda d:d['mutations'].pop('range-change'),lambda d:d['control'].update(eligible=False),lambda d:d['mutations']['missing-output'].update(eligible=None)):
            bad=copy.deepcopy(doc);edit(bad);self.assertTrue(b2.check_agreement_controls(bad))
        self.assertTrue(b2.check_agreement_controls(doc,list(b2.AGREEMENT_MUTATIONS)+['project-extra']))     # a protocol mutation that was not applied
        doc['mutations']['project-extra']={'changed':True,'eligible':False};self.assertEqual(b2.check_agreement_controls(doc,list(b2.AGREEMENT_MUTATIONS)+['project-extra']),[])

class ContextTests(unittest.TestCase):
    def test_selector_context_and_mask_echo(self):
        self.assertTrue(b2.check_comparison_context([{'selector':'sel-a','dataset':'d1','panel':None},{'selector':'all','dataset':'d1','panel':None}]))
        ev=fake_ev();rows=[r for r in ev['observations'] if r['scope']=='caller']
        mask=copy.deepcopy(rows);next(r for r in mask if r['trial_id']=='c-ws').update(request_mask=1,response_mask=7)
        self.assertTrue(b2.check_caller_scope(mask,ev['phases'],LABEL))           # the response mask differs
    def test_real_shaped_contexts_and_p02(self):
        ev=fake_ev();ctx=b2.comparison_contexts(ev['run'],ev['plan'],ev['observations'],ev['native'],POLICY)
        self.assertEqual(len(ctx),4);self.assertEqual(b2.check_comparison_context(ctx),[])
        _,control,rows=b2.p02_additions(ROOT,ev,POLICY,['e'])
        self.assertTrue(control);self.assertEqual({r['variant']:(r['status'],r['control']) for r in rows},{v:('PASS','PASS') for v in b2.P02_VARIANTS})
        broken=fake_ev();broken['native']['flags']['problems']=['src/a.c: forbidden -O0']
        _,control,rows=b2.p02_additions(ROOT,broken,POLICY,['e'])
        self.assertFalse(control);self.assertTrue(all(r['status']=='FAIL' for r in rows))       # a broken control never gives PASS

class CallerScopeTests(unittest.TestCase):
    def test_real_shaped_rows_pass_and_scope_mutants_fail(self):
        ev=fake_ev();routes=('stdio','shm','inproc')
        self.assertEqual(b2.check_caller_scope(ev['observations'],ev['phases'],LABEL,routes,ev['plan']),[])
        m=b2.b08_mutants(ev,LABEL,routes);self.assertEqual(len(m),7);self.assertTrue(all(m.values()),m)
    def test_each_rule(self):
        ev=fake_ev();rows=ev['observations'];ph=ev['phases']
        def bad(edit,phases=None,**kw):
            x=copy.deepcopy(rows);edit(x);return bool(b2.check_caller_scope(x,ph if phases is None else phases,LABEL,**kw))
        row=lambda x,tid:next(r for r in x if r['trial_id']==tid)
        self.assertTrue(bad(lambda x:row(x,'c-cs').update(pids_end=13)))                          # a cold row without startup inside its interval
        self.assertFalse(bad(lambda x:row(x,'c-cs').update(pids_end=13,phases=dict(row(x,'c-cs')['phases'],pool_start=50))))   # or with a pool_start
        self.assertTrue(bad(lambda x:None,phases=[p for p in ph if p['trial_id']!='c-cs']))        # no teardown phase of a cold row
        self.assertTrue(bad(lambda x:None,phases=[p for p in ph if p['phase']!='pool_start']))     # warm startup not reported apart
        self.assertTrue(bad(lambda x:row(x,'c-ws').update(phases=dict(row(x,'c-ws')['phases'],pool_start=9))))
        self.assertTrue(bad(lambda x:row(x,'p-w').update(route='stdio')))                          # a Python control with a route
        self.assertTrue(bad(lambda x:row(x,'c-ws').update(workers=2)))                             # a pooled C row needs the Python process control
        self.assertTrue(bad(lambda x:None,routes=('stdio','shm','inproc','other')))                # a declared route without a row
        self.assertTrue(bad(lambda x:row(x,'c-wi').update(copied_bytes=-1)))

class EchoTests(unittest.TestCase):
    def test_fixture_and_cells(self):
        f=b2.b13_fixture(LABEL);self.assertEqual(f['status'],'PASS');self.assertEqual(f['cells'],2*(5+5))     # 4 worker counts x 3 routes x 2 modes, in-process cold left out
        self.assertTrue(b2.check_echo_coverage([],{'variants':[],'points':[]},LABEL))

class LifecycleTests(unittest.TestCase):
    def report(self=None):
        return {'parallel':{'status':'PASS','faults':{'label':'simulated','status':'PASS'},
                            'mutants':[{'id':m,'bad':'PASS','control':'PASS'} for m in ('m-a','m-b','m-c')]},
                'profiles':[{'profile':p,'status':'PASS'} for p in ('gcc-O0','asan','ubsan','msan','tsan')]}
    def test_pool_lifecycle(self):
        good=self.report();self.assertEqual(b2.check_pool_lifecycle(good,[{'project_dir':'p','gates':[{'name':s,'status':'PASS'} for s in b2.SANITIZERS]}]),[])
        for edit in (lambda r:r['parallel'].update(status='FAIL'),lambda r:r['parallel']['faults'].update(label='real'),lambda r:r['parallel']['mutants'].pop(),
                     lambda r:r['parallel']['mutants'][0].update(bad='FAIL'),lambda r:r['parallel']['mutants'][1].update(control='FAIL'),lambda r:r['profiles'][3].update(status='FAIL')):
            bad=copy.deepcopy(good);edit(bad);self.assertTrue(b2.check_pool_lifecycle(bad))
        self.assertTrue(b2.check_pool_lifecycle(good,[{'project_dir':'p','gates':[{'name':'tsan','status':'FAIL'}]}]))
        self.assertTrue(b2.check_pool_lifecycle(None))

class FailureTests(unittest.TestCase):
    def doc(self):
        cases=[{'case':n,'class':w[0],'returncode':-9,'reaped':True,'eligible':False,'work_units':0} for n,w in b2.FAILURE_CLASSES.items()]
        next(c for c in cases if c['case']=='crash')['returncode']=-11
        cases.append({'case':'caller-crash','framework_row':{'status':'FAILED','error_type':'ChildExited','child_exit_code':-11,'child_error_class':'no exception line'},
                      'reaped':True,'observations':0})
        return {'cases':cases,'normal':{'result_kept':True,'returncode':0},'leftover_processes':[],'leftover_shm':[]}
    def test_failure_rows_never_count(self):
        self.assertEqual(b2.check_incomplete_never_counts([{'eligible':True,'work_units':256},{'eligible':False,'work_units':0}]),[])
        self.assertTrue(b2.check_incomplete_never_counts([{'trial_id':'x','eligible':False,'work_units':256}]))
    def test_failure_classes(self):
        self.assertEqual(b2.check_failure_classes(self.doc()),[])
        edits=(lambda d:d['cases'][0].update(**{'class':'COMPLETED'}),lambda d:d['cases'][1].update(reaped=False),lambda d:d['cases'][2].update(work_units=1),
               lambda d:next(c for c in d['cases'] if c['case']=='crash').update(returncode=-9),lambda d:d['cases'].pop(3),
               lambda d:d['cases'][-1]['framework_row'].update(child_exit_code=0),lambda d:d['cases'][-1]['framework_row'].update(error_type='TimeoutError'),
               lambda d:d['cases'][-1].update(observations=1),lambda d:d['cases'][-1].update(reaped=False),lambda d:d['cases'].pop(),
               lambda d:d['normal'].update(result_kept=False),lambda d:d.update(leftover_processes=[12]),
               lambda d:d.update(leftover_shm=['/dev/shm/x']))
        for edit in edits:
            bad=self.doc();edit(bad);self.assertTrue(b2.check_failure_classes(bad))
    def test_the_failure_job_on_the_framework_stub_worker(self):
        """The real failure-controls job body with the framework stub worker (the unit gate runs in the bench image)."""
        spec=importlib.util.spec_from_file_location('bench_native_job_phase2',ROOT/'container/bench_native_job.py')
        nb=importlib.util.module_from_spec(spec);spec.loader.exec_module(nb)
        m=job_module();m.STUB=ROOT/'benchmarks/performance/python/tests/stub_worker.py';nb.FRAMEWORK_PY=str(ROOT/'benchmarks/performance/python')
        with tempfile.TemporaryDirectory() as d:
            row=m.failure_controls({'deadline_seconds':120},Path(d),{'_bench_native':nb})
            doc=json.loads((Path(d)/'failure-controls.json').read_text())
        # EX13-A04: without the coordinator caller-child path (a unit test) the caller crash is recorded as not run, so the
        # whole check fails; the stub-worker classes are real here
        self.assertEqual(row['status'],'PASS');self.assertEqual(b2.check_failure_classes(doc),['caller-crash: not run (the framework caller-child path is absent)'],doc)
        self.assertEqual(b2.check_stub_classes(doc),[])

class LaunchTests(unittest.TestCase):
    def test_launch_pool_identity_and_privilege(self):
        ev=fake_ev();rows=ev['observations']
        self.assertEqual(b2.check_launch(rows),[]);self.assertTrue(b2.check_launch([dict(rows[0],runner='host')]))
        for w in (0,-1,8,64,True,'2'):self.assertTrue(b2.check_pool_request({'rows':[{'variant':'c-threads','workers':w}],'envelope':ENV4},POLICY),w)
        self.assertTrue(b2.check_pool_request({'rows':[{'variant':'c-threads','workers':4}],'envelope':dict(ENV4,cpus=2)},POLICY))
        self.assertTrue(b2.check_pool_request({'rows':[{'variant':'c-threads','workers':2,'window':5}],'envelope':ENV4},POLICY))
        self.assertEqual(b2.check_pool_request({'rows':[{'variant':'c-threads','workers':w,'window':2*w} for w in (1,2,4)],'envelope':ENV4},POLICY),[])
        native={'binaries':{'demo-kernel':{'sha256':'a'*64}},'glib':{'sha256':G}}
        self.assertEqual(b2.check_native_identity({'demo-kernel':'a'*64,b2.GLIB_NAME:G},native),[])
        self.assertTrue(b2.check_native_identity({'demo-kernel':'0'*64,b2.GLIB_NAME:G},native))
        self.assertTrue(b2.check_native_identity({'demo-kernel':'a'*64},native))
        self.assertEqual(b2.check_inproc_isolation([dict(rows[0],route='inproc',load_process={'pid':41,'role':'caller'})]),[])
        self.assertTrue(b2.check_inproc_isolation([dict(rows[0],route='inproc',load_process={'pid':7,'role':'coordinator'})]))
        self.assertTrue(b2.check_inproc_isolation([dict(rows[0],route='inproc',load_process=None)]))
    def test_cleanup_and_affinity(self):
        ev=fake_ev();self.assertEqual(b2.check_process_cleanup(ev['phases']),[])
        left=copy.deepcopy(ev['phases']);left[5]['pids_end']=11;self.assertTrue(b2.check_process_cleanup(left))
        none=[p for p in ev['phases'] if not (p['phase']=='teardown' and p['route']=='stdio' and p['mode']=='warm')];self.assertTrue(b2.check_process_cleanup(none))
        self.assertEqual(b2.check_affinity(ENV4,dict(ENV4),4),[])
        self.assertTrue(b2.check_affinity(ENV4,dict(ENV4,cpuset=[0],cpus=1)));self.assertTrue(b2.check_affinity(ENV4,ENV4,1))
    def test_thread_api_findings(self):
        self.assertTrue(any(f['rule']=='threading-outside-grant' for f in b2.thread_api_findings(ROOT,'g_thread_pool_new')))
        self.assertEqual(b2.thread_api_findings(ROOT,'sc_parallel_run'),[])
    def test_p04_additions_on_real_shaped_evidence(self):
        ev=fake_ev();rows=b2.p04_additions(ROOT,ev,POLICY,{'native-overlap':('PASS',{'affinity':4},None)},['e'])
        self.assertEqual({r['variant']:(r['status'],r['control']) for r in rows},{v:('PASS','PASS') for v in b2.P04_VARIANTS})
        rows=b2.p04_additions(ROOT,ev,POLICY,{},['e'])          # no overlap record: the affinity control fails, never PASS
        self.assertEqual(next(r for r in rows if r['variant']=='changed-affinity')['status'],'FAIL')

class NoOpTests(unittest.TestCase):
    def test_p16_checks(self):
        self.assertTrue(b2.check_replay([{'seed':1,'result_sha256':'a'*64},{'seed':2,'result_sha256':'a'*64}]))
        self.assertEqual(b2.check_replay([{'seed':1,'result_sha256':'a'*64},{'seed':2,'result_sha256':'b'*64}]),[])
        self.assertTrue(b2.check_no_op([{'echo':True,'case':'case-x','digest_match':False,'eligible':True}]))
        self.assertEqual(b2.check_no_op([{'echo':True,'case':'case-x','digest_match':False,'eligible':False}]),[])
        self.assertTrue(b2.check_skipped_work([{'records':128,'planned_rows':256,'eligible':True}]))
        self.assertTrue(b2.check_result_consumption([{'self_reduction_match':False,'eligible':True}]))
        self.assertTrue(b2.check_selector_counters([{'selector':'sel-a','unselected_evals':5,'selected_evals':10,'agreement':True,'eligible':True}]))   # overcompute
        self.assertTrue(b2.check_selector_counters([{'selector':'sel-a','unselected_evals':0,'selected_evals':0,'agreement':False,'eligible':True}]))   # no-op
        self.assertEqual(b2.check_selector_counters([{'selector':'sel-a','unselected_evals':0,'selected_evals':10,'agreement':True,'eligible':True}]),[])
    def kernel_doc(self):
        return {'seeds':[{'seed':5,'result_sha256':'a'*64},{'seed':6,'result_sha256':'b'*64}],
                'kernel':{'records':64,'planned_rows':64,'notes':{'control':{'eligible':True,'validated':True,'canonical_ok':True,'records':64},
                                                                   'no-op':{'eligible':False,'validated':False,'canonical_ok':True,'records':64},
                                                                   'removed-consumption':{'eligible':False,'validated':True,'canonical_ok':False,'records':64}}}}
    def test_p16_additions_read_real_observations_or_are_not_run(self):
        """EX13-A01, EX13-A02: the kernel variants read the real kernel verification of the agreement-controls job; the
        selector variants have no project with selector counters and are NOT_RUN with a reason (never a PASS)."""
        ev=fake_ev();jobs={'agreement-controls':('PASS',self.kernel_doc(),None)}
        rows,not_run=b2.p16_additions(ev,POLICY,jobs,['e'])
        self.assertEqual({r['variant']:(r['status'],r['control']) for r in rows},{v:('PASS','PASS') for v in b2.P16_VARIANTS if not v.startswith('selector-')})
        self.assertEqual({n['suite'] for n in not_run},{'P16 bench-no-op-or-gamed-optimizer/selector-overcompute','P16 bench-no-op-or-gamed-optimizer/selector-no-op'})
        self.assertTrue(all(n['reason'] and 'EX13-P16-SELECTOR-01' in n['reason'] for n in not_run))
        for name,edit in (('no-op-native-kernel',lambda k:k['notes']['no-op'].update(eligible=True)),
                          ('removed-result-consumption',lambda k:k['notes']['removed-consumption'].update(eligible=True)),
                          ('no-op-native-kernel',lambda k:k['notes']['control'].update(eligible=False)),
                          ('removed-result-consumption',lambda k:k.pop('notes'))):
            doc=self.kernel_doc();edit(doc['kernel'])
            r=next(x for x in b2.p16_additions(ev,POLICY,{'agreement-controls':('PASS',doc,None)},['e'])[0] if x['variant']==name)
            self.assertEqual(r['status'],'FAIL',name)          # an accepted defect or a broken control is never PASS
        r=b2.p16_additions(ev,POLICY,{},['e'])[0]
        self.assertTrue(all(x['status']=='FAIL' for x in r if x['variant'] in ('reuse-answer','no-op-native-kernel','removed-result-consumption')))

class RoundOneTests(unittest.TestCase):
    """EX-13 fix round 1 (ruling EX13-R4): no control reports PASS by construction."""
    def test_b04_without_a_trace_program_is_not_run(self):
        row=b2.b04_row(None,ENV4,'proj')
        self.assertEqual(row['status'],'NOT_RUN');self.assertIn('native.trace',row['reason'])
        self.assertEqual(b2.b04_row(('FAIL',None,'ev'),ENV4,'proj')['status'],'FAIL')
    def test_suite_rows_that_did_not_run_go_to_not_run(self):
        suite,not_run=b2.join_project_rows('B04',{'p-a':{'status':'NOT_RUN','reason':'r'},'p-b':{'status':'PASS'}})
        self.assertEqual(suite['status'],'PASS');self.assertEqual(not_run,[{'suite':'B04 p-a','reason':'r'}])
        suite,not_run=b2.join_project_rows('B04',{'p-a':{'status':'NOT_RUN','reason':'r'}})
        self.assertIsNone(suite);self.assertEqual(len(not_run),1)
        suite,_=b2.join_project_rows('B04',{'p-a':{'status':'FAIL'},'p-b':{'status':'PASS'}});self.assertEqual(suite['status'],'FAIL')
    def sreport(self,project='p',source='s'*64,status='PASS'):
        return {'schema_version':1,'kind':'sanitizer-evidence','project_dir':project,'source_identity':source,'verdict':status,
                'gates':[{'name':g,'status':status} for g in b2.SANITIZERS],'blockers':[]}     # FWN1-B11-SHAPE-01: the writer always writes the list
    def full_sreport(self,project,source):
        """A report with every field of schemas/project-sanitizer-report.json."""
        return dict(self.sreport(project,source),run_id='0'*32,project='demo',project_identity='a'*64,image_id='sha256:'+'1'*64,started_at='x',
                    finished_at='y',elapsed_seconds=1.0,stopped_after=None,blockers=[],evidence_directory='d')
    def test_b11_refuses_a_sanitizer_report_without_its_blockers_list(self):
        """FWN1-B11-SHAPE-01: a report without the `blockers` field, or with a `blockers` value that is not an empty list, is
        BLOCKED; it is never read as "no blocker"."""
        good=LifecycleTests.report(None);good['binding']={'source':'s'*64};cur='s'*64
        no_key=self.sreport();del no_key['blockers']
        for rep in (no_key,dict(self.sreport(),blockers=''),dict(self.sreport(),blockers=0),dict(self.sreport(),blockers={}),
                    dict(self.sreport(),blockers=None),dict(self.sreport(),blockers=False),dict(self.sreport(),blockers=[''])):
            with self.subTest(blockers=rep.get('blockers','<missing>')):
                st,why,ok=b2.b11_status(good,{'p':rep},cur,['p']);self.assertEqual((st,ok),('BLOCKED',[]));self.assertIn('blockers',why)
        self.assertEqual(b2.b11_status(good,{'p':self.sreport()},cur,['p'])[0],'PASS')      # the control: an empty list
    def test_b11_checks_each_sanitizer_report_against_its_schema_when_it_reads_it(self):
        """FWN1-B11-SHAPE-01: b11_suite validates every per-project report that it reads; a report that fails the schema
        (no blockers field, a wrong type, an extra field) or is no JSON is BLOCKED with the project named."""
        cur='b'*64;project='examples/demo-q'
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);shutil.copytree(ROOT/'schemas',root/'schemas');(root/'artifacts').mkdir()
            fr=LifecycleTests.report(None);fr['binding']={'source':cur}
            (root/'artifacts/foundation-qualification-report.json').write_text(json.dumps(fr))
            path=b2.sanitizer_report_path(root,project);path.parent.mkdir(parents=True)
            def b11(doc):
                path.write_text(doc if isinstance(doc,str) else json.dumps(doc))
                with mock.patch.object(b2,'native_projects',return_value=[(project,None,None,None)]),mock.patch('policy.source_identity',return_value=(cur,[])):
                    return b2.b11_suite(root)
            row=b11(self.full_sreport(project,cur));self.assertEqual(row['status'],'PASS',row.get('reason'));self.assertEqual(row['project_reports'],[project])
            no_key=self.full_sreport(project,cur);del no_key['blockers']
            for doc in (no_key,dict(self.full_sreport(project,cur),blockers='x'),dict(self.full_sreport(project,cur),extra=1),'{not json'):
                with self.subTest(doc=str(doc)[:40]):
                    row=b11(doc);self.assertEqual(row['status'],'BLOCKED');self.assertIn(project,row['reason']);self.assertEqual(row['project_reports'],[])
    def test_b11_needs_current_project_sanitizer_evidence(self):
        """EX13-A03, EX13-A08: B11 reads one sanitizer-evidence report per native example (never one shared file) and is
        BLOCKED when one is missing, of another project or of another source."""
        good=LifecycleTests.report(None);good['binding']={'source':'s'*64};cur='s'*64
        self.assertEqual(b2.b11_status(good,{'p':self.sreport()},cur,['p'])[0],'PASS')
        self.assertEqual(b2.b11_status(good,{'p':self.sreport(),'q':self.sreport('q')},cur,['p','q'])[0],'PASS')
        st,why,_=b2.b11_status(good,{'p':self.sreport()},cur,['p','q']);self.assertEqual(st,'BLOCKED');self.assertIn('q',why)
        st,why,_=b2.b11_status(good,{},cur,['p']);self.assertEqual(st,'BLOCKED');self.assertIn('sanitizer',why)
        self.assertEqual(b2.b11_status(good,{'p':self.sreport(source='0'*64)},cur,['p'])[0],'BLOCKED')
        self.assertEqual(b2.b11_status(good,{'p':self.sreport('q')},cur,['p'])[0],'BLOCKED')
        self.assertEqual(b2.b11_status(good,{'p':dict(self.sreport(),kind='project-check')},cur,['p'])[0],'BLOCKED')
        self.assertEqual(b2.b11_status(dict(good,binding={'source':'0'*64}),{'p':self.sreport()},cur,['p'])[0],'BLOCKED')
        bad=self.sreport();bad['gates'][3]['status']='FAIL';self.assertEqual(b2.b11_status(good,{'p':bad},cur,['p'])[0],'FAIL')
        self.assertEqual(b2.b11_status(good,{},cur,[])[0],'BLOCKED')      # no native example project: nothing proves the project part
    def test_b11_needs_the_sanitizer_report_verdict_pass_and_no_blocker(self):
        """EX13-A11: four PASS gate rows are not enough. A report with verdict BLOCKED (a container cleanup or report schema
        failure after the gates) or with a blocker never gives B11 PASS; a report with verdict FAIL gives FAIL."""
        good=LifecycleTests.report(None);good['binding']={'source':'s'*64};cur='s'*64
        blocked=dict(self.sreport(),verdict='BLOCKED')
        self.assertEqual([g['status'] for g in blocked['gates']],['PASS']*4)
        st,why,ok=b2.b11_status(good,{'p':blocked},cur,['p']);self.assertEqual(st,'BLOCKED');self.assertEqual(ok,[]);self.assertIn('verdict',why)
        st,_,ok=b2.b11_status(good,{'p':dict(self.sreport(),blockers=['container cleanup: x'])},cur,['p'])
        self.assertEqual(st,'BLOCKED');self.assertEqual(ok,[])
        no_verdict=self.sreport();del no_verdict['verdict']
        for rep in (no_verdict,dict(self.sreport(),verdict=None),dict(self.sreport(),verdict='pass'),dict(self.sreport(),blockers='x')):
            with self.subTest(rep={k:rep.get(k) for k in ('verdict','blockers')}):self.assertEqual(b2.b11_status(good,{'p':rep},cur,['p'])[0],'BLOCKED')
        st,why,_=b2.b11_status(good,{'p':dict(self.sreport(),verdict='FAIL')},cur,['p']);self.assertEqual(st,'FAIL');self.assertIn('verdict',why)
        q='examples/demo-q'
        st,why,_=b2.b11_status(good,{'p':self.sreport(),q:dict(self.sreport(q),verdict='BLOCKED')},cur,['p',q])
        self.assertEqual(st,'BLOCKED');self.assertIn(q,why)
        self.assertEqual(b2.b11_status(good,{'p':dict(self.sreport(),blockers=[])},cur,['p'])[0],'PASS')     # the control
    def test_one_sanitizer_report_file_per_project(self):
        a=b2.sanitizer_report_path(ROOT,'examples/demo-a');b=b2.sanitizer_report_path(ROOT,'examples/demo-b')
        self.assertNotEqual(a,b);self.assertEqual(a.parent,ROOT/'artifacts/project-sanitizers');self.assertNotEqual(a.name,'project-report.json')
        from schema_check import validate
        validate(ROOT,'project-sanitizer-report',dict(self.sreport(source='b'*64),run_id='0'*32,project='demo',project_identity='a'*64,image_id='sha256:'+'1'*64,
                                                     started_at='x',finished_at='y',elapsed_seconds=1.0,stopped_after=None,blockers=[],evidence_directory='d'))
    def test_the_sanitizer_step_runs_exactly_the_sanitizer_builds(self):
        import project_check as pc
        self.assertEqual(pc.SANITIZER_GATES,('ubsan','asan','msan','tsan'))
        self.assertEqual([b['gate'] for b in pc.sanitizer_builds('examples/x')],['ubsan','asan','msan','tsan'])
        self.assertEqual(set(pc.SANITIZER_GATES),set(b2.SANITIZERS))
        rows={g:{'name':g,'status':'PASS'} for g in pc.SANITIZER_GATES}
        self.assertEqual(pc.sanitizer_verdict(rows,None,[]),'PASS')
        self.assertEqual(pc.sanitizer_verdict(dict(rows,tsan={'name':'tsan','status':'FAIL'}),'tsan',[]),'FAIL')
        self.assertEqual(pc.sanitizer_verdict({k:v for k,v in rows.items() if k!='msan'},None,[]),'BLOCKED')
        self.assertEqual(pc.sanitizer_verdict(rows,None,['infrastructure']),'BLOCKED')
        src=(ROOT/'tools/project_check.py').read_text();body=src[src.index('def run_sanitizer_evidence'):]
        body=body[:body.index('\ndef ',1)]
        self.assertNotIn("artifacts/project-report.json",body)        # never the shared project report
    def test_ci_writes_the_sanitizer_evidence_before_the_bench_gates(self):
        src=(ROOT/'tools/cli.py').read_text()
        self.assertIn('sanitizer_evidence_all(root)',src)
        self.assertLess(src.index('sanitizer_evidence_all(root)'),src.index('bench_gates,bench_additions=ci_gates(root)'))
        self.assertIn('sanitizer-evidence',bench.HANDLERS)
    def test_b13_echo_real_part_is_listed_as_not_run(self):
        entries=b2.echo_not_run([])
        self.assertEqual(entries,[{'suite':'B13-echo real rows','reason':'no example project declares echo_case in its protocol (ledger EX13-B13ECHO-01)'}])
        self.assertEqual(b2.echo_not_run([('p','c')]),[])
    def test_phase2_cases_returns_not_run(self):
        import inspect
        self.assertIn('not_run',inspect.getsource(b2.phase2_cases))
        self.assertIn('s2,a2,n2=bench_phase2.phase2_cases(root,run_dir,project)',(ROOT/'tools/bench.py').read_text())
    def test_the_job_kernel_controls_use_the_framework_verifier(self):
        src=(ROOT/'container/bench_phase2_job.py').read_text()
        self.assertIn("nb.KERNEL_VERIFY_CODE",src);self.assertIn("nb.KERNEL_PACK_CODE",src);self.assertIn("nb.kernel_argv(",src)
        self.assertIn("g['CallerChild'](",src);self.assertIn("g['failure_row'](",src)

class CrashProbeTests(unittest.TestCase):
    """EX13-A09: the observation count and the reap state of the caller crash come from real probes."""
    def test_process_gone_reads_the_process_table(self):
        import subprocess, time
        m=job_module();p=subprocess.Popen([sys.executable,'-c','pass'])
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and m.process_state(p.pid)!='Z':time.sleep(0.01)
        self.assertEqual(m.process_state(p.pid),'Z');self.assertFalse(m.process_gone(p.pid))     # exited, not reaped
        p.wait();self.assertTrue(m.process_gone(p.pid))
        q=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);self.addCleanup(q.wait);self.addCleanup(q.kill)
        self.assertFalse(m.process_gone(q.pid))
    def test_call_notes_count_the_coordinator_events_of_the_trial(self):
        m=job_module()
        events=lambda channel,start,tid,kind=None,phase=None:[e for e in channel if e['trial']==tid and e['m']==kind][start:]
        self.assertEqual(m.call_notes(events,[{'trial':'t','m':'note'},{'trial':'u','m':'note'},{'trial':'t','m':'begin'}],0,'t'),1)
        self.assertEqual(m.call_notes(events,[],0,'t'),0)
    def test_each_caller_crash_check_can_fail(self):
        ok={'case':'caller-crash','framework_row':{'error_type':'ChildExited','child_exit_code':-11},'reaped':True,'observations':0}
        self.assertEqual(b2.caller_crash_problems(ok),[])
        for edit in ({'framework_row':{'error_type':'ChildExited','child_exit_code':0}},{'reaped':False},{'observations':1},{'observations':None},{'reaped':None}):
            self.assertTrue(b2.caller_crash_problems(dict(ok,**edit)),edit)
        src=(ROOT/'container/bench_phase2_job.py').read_text()
        self.assertIn("'observations':call_notes(",src);self.assertIn("'reaped':process_gone(",src)

class DeclarationTests(unittest.TestCase):
    def test_trace_program_and_echo_case_rules(self):
        decl={'cases':['case-one','case-two'],'checks':[{'name':'x-native','module':'m','before_run':False}],
              'native':{'kernel':{'program':'k','args':['{input}','{records}','{loops}','{output}']},'agreement':'x-native','trace':{'program':'t'}}}
        self.assertIsNone(bm.native_declaration_problem(decl))
        same=copy.deepcopy(decl);same['native']['trace']['program']='k';self.assertTrue(bm.native_declaration_problem(same))
        value={'schema_version':1,'cases':['case-one','case-two'],'approval':{'state':'PENDING','reference':None},'echo_case':'case-two','agreement_mutations':['project-extra']}
        bm._check_protocol(ROOT,'p',decl,Path('p'),b'{}',value)
        with self.assertRaisesRegex(GateError,'echo_case'):bm._check_protocol(ROOT,'p',decl,Path('p'),b'{}',dict(value,echo_case='case-two',cases=['case-one']))

class JobPlanTests(unittest.TestCase):
    def test_job_plans_are_checked_before_any_child(self):
        m=job_module();g={'_bench_native':None}
        with tempfile.TemporaryDirectory() as d:
            for plan in ({'trace':{'program':'Bad'},'native':{'Bad':'a'*64}},{'trace':{'program':'t','x':1},'native':{'t':'a'*64}},{'trace':{'program':'t'},'native':{}}):
                self.assertEqual(m.overlap(dict(plan,deadline_seconds=60),Path(d),{'_bench_native':type('N',(),{'_benchlab':staticmethod(lambda n:None)})})['reason'],'trace program rejected')
            good={'variant':'c-serial','workers':'direct','route':'stdio','rows':64,'seed':5,'mutations':[]}
            for edit in ({'variant':'py-reference'},{'workers':'0'},{'route':'tcp'},{'rows':1},{'rows':True},{'seed':-1},{'mutations':['Bad name']},{'mutations':['m-x']*17}):
                self.assertEqual(m.agreement_controls(dict(good,**edit,deadline_seconds=60),Path(d),g)['reason'],'agreement-controls plan rejected',edit)

class OverlapIdentityTests(unittest.TestCase):
    """The native-overlap job confirms its verified trace program through the real benchlab.native_worker client, with
    the path argument of confirm_verified (FR7b-IDENTITY-RULE-01, owner rule: a replaced file is always refused). The
    process start and the stdout read are replaced; open_verified and confirm_verified run unchanged on a real file."""
    def run_overlap(self,replace):
        spec=importlib.util.spec_from_file_location('bench_native_job_overlap',ROOT/'container/bench_native_job.py')
        nb=importlib.util.module_from_spec(spec);spec.loader.exec_module(nb);nb.FRAMEWORK_PY=str(ROOT/'benchmarks/performance/python')
        native=type('N',(),{'_benchlab':staticmethod(nb._benchlab),'native_env':staticmethod(lambda plan:{}),'MISMATCH':nb.MISMATCH})
        m=job_module()
        with tempfile.TemporaryDirectory() as d:
            m.NATIVE_DIR=Path(d)/'native';m.NATIVE_DIR.mkdir();program=m.NATIVE_DIR/'trace';program.write_bytes(b'trace program bytes\n')
            digest=hashlib.sha256(program.read_bytes()).hexdigest();out=Path(d)/'out';out.mkdir();started=[]
            class Proc:
                returncode=0
                def kill(self):started.append('killed')
                def wait(self):started.append('reaped');return -9
            def popen(argv,**kw):
                started.append(argv)
                if replace:     # the same bytes under a new inode at the verified path while the program starts
                    other=m.NATIVE_DIR/'other';other.write_bytes(program.read_bytes());os.replace(other,program)
                return Proc()
            with mock.patch.object(m.subprocess,'Popen',popen),mock.patch.object(m,'_capped_run',lambda proc,deadline:(b'',False,False)):
                row=m.overlap({'trace':{'program':'trace'},'native':{'trace':digest},'deadline_seconds':60},out,
                              {'_bench_native':native,'read_counters':lambda:{}})
            return row,started,(out/'overlap.json').exists()
    def test_the_verified_trace_program_runs(self):
        row,started,written=self.run_overlap(False)
        self.assertEqual(row['status'],'PASS',row);self.assertEqual(started,[['trace']]);self.assertTrue(written)
    def test_a_replaced_trace_program_is_refused(self):
        row,started,written=self.run_overlap(True)
        self.assertEqual((row['status'],row['reason']),('FAIL','trace program refused'),row)
        self.assertEqual(started,[['trace'],'killed','reaped']);self.assertFalse(written)

if __name__=='__main__':unittest.main()
