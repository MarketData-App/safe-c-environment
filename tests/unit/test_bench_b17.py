"""Phase 3 Task 30 (brief section 15 B17; Amendment H1), framework part (task EX-17): the real complete demo matrix and
`--matrix python|full` of bench plan and bench run.

The checks are tested on a synthetic case (the framework control case with synthetic variants; H3: no example case is
loaded), on its real smoke plan (bench_plan.build_plan) and on synthetic observations of that plan. The real B17 runs
(the framework control case and every native example project, through the public commands) run in bench selftest
--suite cases."""
import argparse, contextlib, copy, csv, io, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, bench_plan as bp, bench_phase3 as b3
from evidence import GateError

POLICY=bm.load_policy(ROOT);ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
SMALL={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256}
RUN_ID='3'*32;CURRENT='a'*64
PROPERTY=('execute the Python/C one/multiple-worker matrix, all three scope demonstrations, cold/warm caller paths and independent '
          'memory trials through public commands; publish actual numbers even if C loses; synthetic decision tests cannot substitute')
ALL_DIMENSIONS={d for d,_ in b3.B17_DIMENSIONS}

def full_case():
    """The framework control case with synthetic variants: Python direct and pool rows, C direct and pool rows on three routes,
    the kernel, caller and capacity scopes and two capacity configurations (one with a C variant)."""
    c=copy.deepcopy(bm.load_case(ROOT,'bench-control-spin'));c['case_id']='bench-matrix-fixture'      # never a control-identity case of compare
    c['variants']=[{'id':'py-reference','language':'python','workers':['direct'],'status':'implemented'},
                   {'id':'py-optimized','language':'python','workers':['direct'],'status':'same-as-reference','reason':'synthetic'},
                   {'id':'py-threads','language':'python','workers':[1,2],'status':'implemented'},
                   {'id':'c-serial','language':'c','workers':['direct'],'status':'implemented','routes':['stdio','shm','inproc']},
                   {'id':'c-threads','language':'c','workers':[1,2],'status':'implemented','routes':['stdio','shm','inproc']}]
    c['capacity']=dict(c['capacity'],configurations=[{'name':'serial-workers','variant':'c-serial','route':'stdio'},{'name':'threaded-worker','variant':'py-threads'}])
    c['points']=[dict(c['points'][0],variants=['py-reference','py-threads','c-serial','c-threads'])]
    return c

def direct_case():
    """Direct rows only (no pool variant) on the kernel and caller scopes: the matrix has no multiple-worker cell."""
    c=full_case();c['variants']=[v for v in c['variants'] if v['id'] not in ('py-threads','c-threads')];c['scopes']=['kernel','caller'];c.pop('capacity')
    c['points']=[dict(c['points'][0],variants=['py-reference','c-serial'])];return c

def smoke_plan(case,envelope=ENV4,**kw):return bp.build_plan(case,POLICY,mode='smoke',dataset=SMALL,seed=3,envelope=envelope,**kw)

def observe(plan,run_id=RUN_ID):
    """One eligible observation per planned trial, memory trial and capacity trial (synthetic values)."""
    sizes=POLICY['sizes'];rows=[]
    def base(t,scope):
        return {'run_id':run_id,'trial_id':t['trial_id'],'block':t.get('block'),'warmup':t.get('warmup',False),'eligible':True,'loops':1,
                'work_units':sizes[t['tier']],'wall_ns':1000000,'cpu_usage_usec':1000,'point':t['point'],'scope':scope,'mode':t['mode'],
                'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],'route':t.get('route'),'phase':'work' if scope=='kernel' else 'caller'}
    for s in plan['sessions']:
        for t in s['trials']:rows.append(base(t,t['scope']))
    for m in plan['memory']:rows.append(dict(base(m,'memory'),memory={'group_peak_bytes':4096,'ready_current':2048}))
    for c in plan.get('capacity') or []:
        n=c['clients']*c['requests_per_client']
        rows.append(dict(base(c,'capacity'),work_units=sizes[c['tier']]*n,
                         capacity={'configuration':c['configuration'],'clients':c['clients'],'route':c['route'],'completed':n,'errors':0,'latencies_ns':[1000]*n}))
    return rows

def cell(o):return (o['scope'],o['mode'],o['variant'],o['workers'],o.get('route'))

def write_run(root,case,plan,obs=None,status='VALID'):
    """A recorded run of `plan` in a temporary root (with the framework safety and schemas files), as bench run writes it."""
    obs=observe(plan) if obs is None else obs;d=Path(root)
    for p in ('safety','schemas'):
        if not (d/p).exists():shutil.copytree(ROOT/p,d/p)
    rd=d/'artifacts/bench'/RUN_ID;rd.mkdir(parents=True,exist_ok=True)
    (rd/'plan.json').write_text(json.dumps(plan));(rd/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in obs))
    (rd/'phases.jsonl').write_text(json.dumps({'phase':'control-zero','wall_ns':1000})+'\n')
    (rd/'run.json').write_text(json.dumps({'run_id':RUN_ID,'case':case['case_id'],'mode':'smoke','status':status,'dataset':plan['dataset'],
                                           'source_identity':CURRENT,'runtime':{'python':'3.13.0'},'envelope':{'cpus':4}}))
    return rd

class InventoryTests(unittest.TestCase):
    def test_the_b17_row_is_appended_with_the_brief_name_and_property(self):
        rows=bm.load_fixtures(ROOT)['b_cases']
        self.assertEqual(rows[-1],{'id':'B17','name':'real-complete-demo-matrix','phase':3,'property':PROPERTY})
        self.assertLessEqual(len(PROPERTY),300);self.assertEqual([r['id'] for r in rows].count('B17'),1)
    def test_the_ledger_row_of_the_not_run_dimension_is_open(self):
        rows={r['id']:r for r in json.loads((ROOT/'safety/framework-ledger.json').read_text())['findings']}
        self.assertEqual(set(b3.B17_NOT_RUN.values()),{b3.B17_LEDGER});self.assertEqual(rows[b3.B17_LEDGER]['state'],'OPEN')
        self.assertTrue(set(b3.B17_NOT_RUN)<=ALL_DIMENSIONS)
    def test_the_dimensions_follow_the_property(self):
        self.assertEqual(ALL_DIMENSIONS,{'python-one-worker','python-multiple-workers','c-one-worker','c-multiple-workers','kernel-scope','caller-scope',
                                         'capacity-scope','caller-warm','caller-cold','memory-trials','route-stdio','route-shm','route-inproc'})

class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.case=full_case();self.plan=smoke_plan(self.case);self.obs=observe(self.plan)
    def missing(self,obs,plan=None,case=None):return b3.matrix_complete(plan or self.plan,obs,case or self.case)
    def one(self,obs):
        r=self.missing(obs);self.assertEqual(len(r),1,r);return r[0]
    def test_the_smoke_plan_of_a_full_case_is_a_complete_matrix(self):
        self.assertEqual(self.missing(self.obs),[])
        cells,na=b3.matrix_cells(self.case)
        # caller 2 + 4 + 5 + 10, memory 1 + 2 + 3 + 6, kernel py-reference and c-serial, capacity 2
        self.assertEqual(len(cells),21+12+2+2)
        self.assertEqual([c['cell'] for c in na],['caller cold c-serial direct [inproc]','caller cold c-threads x1 [inproc]','caller cold c-threads x2 [inproc]'])
        self.assertTrue(all(c['reason']==bp.INPROC_COLD for c in na))
    def test_a_missing_c_route_cell_is_named(self):
        r=self.one([o for o in self.obs if cell(o)!=('caller','warm','c-threads',2,'shm')])
        self.assertIn('caller warm c-threads x2 [shm]',r);self.assertIn('not observed',r)
    def test_a_missing_capacity_row_is_named(self):
        r=self.one([o for o in self.obs if not (o['scope']=='capacity' and o['capacity']['configuration']=='serial-workers')])
        self.assertIn('capacity serial-workers c-serial [stdio]',r)
    def test_a_missing_cold_cell_is_named(self):
        r=self.one([o for o in self.obs if cell(o)!=('caller','cold','py-threads',1,None)]);self.assertIn('caller cold py-threads x1',r)
    def test_a_missing_memory_trial_is_named(self):
        r=self.one([o for o in self.obs if cell(o)!=('memory','warm','c-serial','direct','inproc')]);self.assertIn('memory c-serial direct [inproc]',r)
    def test_a_memory_trial_without_its_group_peak_is_missing(self):
        obs=copy.deepcopy(self.obs);next(o for o in obs if cell(o)==('memory','warm','py-reference','direct',None))['memory']['group_peak_bytes']=None
        self.assertIn('memory py-reference direct',self.one(obs))
    def test_a_missing_kernel_cell_is_named(self):
        self.assertIn('kernel c-serial',self.one([o for o in self.obs if cell(o)!=('kernel','direct','c-serial','direct',None)]))
    def test_an_ineligible_cell_is_named(self):
        obs=copy.deepcopy(self.obs);next(o for o in obs if cell(o)==('caller','warm','c-serial','direct','stdio') and not o['warmup'])['eligible']=False
        self.assertIn('ineligible',self.one(obs))
    def test_warmup_rows_alone_never_fill_a_cell(self):
        r=self.one([o for o in self.obs if not (cell(o)==('caller','cold','c-serial','direct','shm') and not o['warmup'])])
        self.assertIn('caller cold c-serial direct [shm]',r)
    def test_cells_beyond_the_envelope_are_missing_with_the_plan_reason(self):
        env1=dict(ENV4,cpus=1,cpuset=[0]);plan=smoke_plan(self.case,env1)
        r=self.missing(observe(plan),plan=plan)
        self.assertEqual(len(r),3+8,r)        # py-threads x2: warm, cold, memory; c-threads x2: 3 warm, 2 cold, 3 memory
        self.assertTrue(all('beyond the 1-CPU envelope' in x for x in r),r)
    def test_the_python_matrix_misses_every_c_cell(self):
        plan=smoke_plan(self.case,matrix='python');r=self.missing(observe(plan),plan=plan)
        self.assertEqual(len(r),15+9+1+1,r)   # C caller, C memory, the C kernel and the C capacity configuration
        self.assertTrue(all('--matrix python' in x for x in r),r)
    def test_a_capacity_scope_without_a_configuration_is_missing(self):
        case=full_case();case.pop('capacity');plan=smoke_plan(case)
        r=b3.matrix_complete(plan,observe(plan),case);self.assertEqual(len(r),1,r);self.assertIn('capacity',r[0])
    def test_a_plan_of_another_case_is_refused(self):
        r=self.missing(self.obs,plan=dict(self.plan,case='other-case'));self.assertTrue(any('other-case' in x for x in r))
    def test_dimensions_of_the_complete_matrix(self):
        state=b3.matrix_state(self.plan,self.obs,self.case)
        self.assertEqual(b3.matrix_dimensions(state['cells']),ALL_DIMENSIONS)
        lost=[o for o in self.obs if not (o['scope']=='caller' and o['variant']=='c-threads' and o['workers']==2)]
        self.assertNotIn('c-multiple-workers',b3.matrix_dimensions(b3.matrix_state(self.plan,lost,self.case)['cells']))
    def test_direct_rows_give_no_multiple_worker_dimension(self):
        case=direct_case();plan=smoke_plan(case);state=b3.matrix_state(plan,observe(plan),case)
        self.assertEqual(b3.matrix_complete(plan,observe(plan),case),[])
        self.assertEqual(ALL_DIMENSIONS-b3.matrix_dimensions(state['cells']),{'python-multiple-workers','c-multiple-workers','capacity-scope'})

class MatrixOptionTests(unittest.TestCase):
    def test_python_matrix_keeps_only_python_rows(self):
        case=full_case();plan=smoke_plan(case,matrix='python');full=smoke_plan(case)
        self.assertEqual(plan['matrix'],'python')
        c=lambda v:v.startswith('c-')
        self.assertFalse([r for r in plan['rows'] if c(r['variant'])]);self.assertFalse([b for b in plan['blocked_rows'] if c(b['variant'])])
        self.assertFalse([t for s in plan['sessions'] for t in s['trials'] if c(t['variant'])])
        self.assertFalse([m for m in plan['memory'] if c(m['variant'])]);self.assertFalse([t for t in plan.get('capacity') or [] if c(t['variant'])])
        self.assertEqual(plan['rows'],[r for r in full['rows'] if not c(r['variant'])])
        self.assertTrue([t for s in plan['sessions'] for t in s['trials']]);self.assertTrue(plan['memory']);self.assertTrue(plan['capacity'])
        self.assertIsNone(bench.native_run_declaration(ROOT,None,plan))       # no C trial, so no native build
        self.assertNotIn('route_budget',plan)
    def test_the_full_matrix_keeps_the_plan_identity(self):
        case=full_case();a=smoke_plan(case);b=smoke_plan(case,matrix='full')
        self.assertEqual(a,b);self.assertNotIn('matrix',a)
        self.assertNotEqual(smoke_plan(case,matrix='python')['plan_id'],a['plan_id'])
        spin=bm.load_case(ROOT,'bench-control-spin')        # a Python-only case: the python matrix plans the same trials
        p,f=smoke_plan(spin,matrix='python'),smoke_plan(spin)
        self.assertEqual(p['sessions'],f['sessions']);self.assertEqual(p['memory'],f['memory']);self.assertEqual(p['capacity'],f['capacity'])
    def test_an_unknown_matrix_is_refused(self):
        for bad in ('c','FULL','',None,1):
            with self.subTest(matrix=bad),self.assertRaises(GateError):smoke_plan(full_case(),matrix=bad)
    def test_run_and_plan_take_the_matrix_option(self):
        for name in ('run','plan'):
            with self.subTest(name=name):
                opts=dict(bench.ARGUMENTS[name]);self.assertEqual(opts['--matrix']['choices'],['python','full']);self.assertIsNone(opts['--matrix']['default'])
        parser=argparse.ArgumentParser();bench.configure_parser(parser)
        self.assertEqual(parser.parse_args(['run','--case','x','--matrix','python']).matrix,'python')
        self.assertIsNone(parser.parse_args(['plan','--case','x']).matrix)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parser.parse_args(['run','--case','x','--matrix','c'])
    def test_the_matrix_argument(self):
        ns=argparse.Namespace
        self.assertEqual(bench.matrix_arg(ns()),'full');self.assertEqual(bench.matrix_arg(ns(matrix=None)),'full')
        self.assertEqual(bench.matrix_arg(ns(matrix='python')),'python')
        self.assertEqual(bench.matrix_arg(ns(matrix=None),{'matrix':'python'}),'python')       # a written plan keeps its matrix
        self.assertEqual(bench.matrix_arg(ns(matrix='full'),{}),'full')
        for args,plan in ((ns(matrix='full'),{'matrix':'python'}),(ns(matrix='python'),{})):
            with self.subTest(plan=plan),self.assertRaises(GateError):bench.matrix_arg(args,plan)
    def test_a_written_plan_keeps_its_matrix(self):
        case=full_case();plan=smoke_plan(case,matrix='python')
        bench.verify_written_plan(case,POLICY,plan,ENV4,None,None)
        edited=dict(plan);edited.pop('matrix');edited['plan_id']=bench.plan_digest(edited)
        with self.assertRaises(GateError):bench.verify_written_plan(case,POLICY,edited,ENV4,None,None)

class B17CheckTests(unittest.TestCase):
    """b17_check on a recorded run in a temporary root, compared and reported by the real bench compare and bench report."""
    def recorded(self,tmp,case=None,plan=None,obs=None,status='VALID'):
        case=case or full_case();plan=plan or smoke_plan(case)
        return Path(tmp),write_run(tmp,case,plan,obs,status),case
    def commands(self,d):
        out=[]
        for fn in (bench.compare_cmd,bench.report_cmd):
            with contextlib.redirect_stdout(io.StringIO()):out.append(fn(d,argparse.Namespace(run_id=RUN_ID,format='json')))
        return out
    def check(self,tmp,**kw):
        d,rd,case=self.recorded(tmp,**kw);rc_c,rc_r=self.commands(d)
        return b3.b17_check(rd,case,CURRENT,(0,rc_c,rc_r)),rd,case
    def test_a_complete_reported_matrix_passes(self):
        with tempfile.TemporaryDirectory() as t:
            (problems,state),rd,_=self.check(t)
            self.assertEqual(problems,[]);self.assertEqual(b3.matrix_dimensions(state['cells']),ALL_DIMENSIONS)
    def test_the_run_must_be_valid_and_current(self):
        with tempfile.TemporaryDirectory() as t:
            (problems,_),rd,case=self.check(t,status='INVALID_EXPERIMENT')
            self.assertTrue(any('INVALID_EXPERIMENT' in p for p in problems),problems)
        with tempfile.TemporaryDirectory() as t:
            d,rd,case=self.recorded(t);rc=self.commands(d)
            self.assertTrue(any('current source' in p for p in b3.b17_check(rd,case,'b'*64,(0,*rc))[0]))
            self.assertTrue(any('bench run' in p for p in b3.b17_check(rd,case,CURRENT,(1,*rc))[0]))
            self.assertTrue(any('bench report' in p for p in b3.b17_check(rd,case,CURRENT,(0,rc[0],1))[0]))
            run=json.loads((rd/'run.json').read_text());(rd/'run.json').write_text(json.dumps(dict(run,dataset=dict(run['dataset'],kind='local'))))
            self.assertTrue(any('synthetic' in p for p in b3.b17_check(rd,case,CURRENT,(0,*rc))[0]))
    def test_a_report_without_every_row_fails(self):
        with tempfile.TemporaryDirectory() as t:
            d,rd,case=self.recorded(t);rc=self.commands(d);csv_text=(rd/'summary.csv').read_text().splitlines()
            (rd/'summary.csv').write_text('\n'.join(csv_text[:-1])+'\n')
            self.assertTrue(any('summary.csv' in p for p in b3.b17_check(rd,case,CURRENT,(0,*rc))[0]))
            (rd/'summary.csv').write_text('\n'.join(csv_text)+'\n')
            md=(rd/'summary.md').read_text().splitlines();row=next(i for i,l in enumerate(md) if l.startswith('| ') and not l.startswith('| point'))
            (rd/'summary.md').write_text('\n'.join(md[:row]+md[row+1:])+'\n')
            self.assertTrue(any('summary.md' in p for p in b3.b17_check(rd,case,CURRENT,(0,*rc))[0]))
            (rd/'summary.md').write_text('\n'.join(l for l in md if not l.startswith('- serial-workers'))+'\n')
            self.assertTrue(any('capacity' in p for p in b3.b17_check(rd,case,CURRENT,(0,*rc))[0]))
    def test_every_c_row_publishes_its_comparison_and_numbers(self):
        with tempfile.TemporaryDirectory() as t:
            d,rd,case=self.recorded(t);rc=self.commands(d)
            table=list(csv.DictReader((rd/'summary.csv').read_text().splitlines()));cols=list(table[0])
            def write(rows):
                buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=cols);w.writeheader();w.writerows(rows);(rd/'summary.csv').write_text(buf.getvalue())
            for field,word in (('outcome_vs_best_python','best Python'),('wall_ns_per_unit_median','wall'),('cpu_ns_per_unit_median','CPU'),('group_peak_bytes_median','memory')):
                with self.subTest(field=field):
                    rows=copy.deepcopy(table);i=next(k for k,r in enumerate(rows) if r['variant']=='c-threads' and r['mode']=='warm');rows[i][field]=''
                    write(rows);self.assertTrue(any(word in p for p in b3.b17_check(rd,case,CURRENT,(0,*rc))[0]),field)
            write(table);self.assertEqual(b3.b17_check(rd,case,CURRENT,(0,*rc))[0],[])
    def test_an_incomplete_matrix_fails(self):
        with tempfile.TemporaryDirectory() as t:
            case=direct_case();plan=smoke_plan(case)
            obs=[o for o in observe(plan) if cell(o)!=('memory','warm','c-serial','direct','shm')]
            plan=dict(plan,memory=[m for m in plan['memory'] if m['trial_id'] in {o['trial_id'] for o in obs}])    # the plan agrees, so compare runs
            (problems,_),_,_=self.check(t,case=case,plan=plan,obs=obs)
            self.assertTrue(any('memory c-serial direct [shm]' in p for p in problems),problems)
    def test_a_python_matrix_run_is_not_the_b17_matrix(self):
        with tempfile.TemporaryDirectory() as t:
            case=full_case();(problems,_),_,_=self.check(t,case=case,plan=smoke_plan(case,matrix='python'))
            self.assertTrue(any('full matrix' in p for p in problems));self.assertTrue(any('--matrix python' in p for p in problems))

class B17SuiteTests(unittest.TestCase):
    def test_the_targets_are_the_framework_control_and_each_native_example(self):
        import bench_phase2
        targets=b3.b17_targets(ROOT)
        self.assertEqual(targets[0],(None,b3.CONTROL_CASE));self.assertEqual(targets[1:],[(p,c) for p,_,c,_ in bench_phase2.native_projects(ROOT)])
    def test_one_target_runs_the_public_commands_with_the_full_smoke_matrix(self):
        case=full_case();plan=smoke_plan(case);seen=[]
        def fake_run(root,args):
            seen.append(args);write_run(root,case,plan);print(json.dumps({'status':'VALID','run_id':RUN_ID}));return 0
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'run_cmd',fake_run),mock.patch.object(bm,'load_case',return_value=case),\
             mock.patch.object(b3,'_current_identity',return_value=CURRENT):
            row=b3.b17_target(Path(t),None,case['case_id'])
        self.assertEqual(row['status'],'PASS',row.get('problems'))
        a=seen[0];self.assertEqual((a.case,a.project,a.mode,a.dataset,a.matrix,a.plan,a.calibrate),(case['case_id'],None,'smoke','synthetic:small','full',None,None))
        self.assertEqual(row['run_id'],RUN_ID);self.assertEqual(set(row['dimensions']),ALL_DIMENSIONS);self.assertIn('seconds',row)
    def test_a_refused_or_blocked_run(self):
        def refused(root,args):raise GateError('docker unavailable')
        def blocked(root,args):print(json.dumps({'status':'BLOCKED'}));return 2
        def failed(root,args):print(json.dumps({'status':'INVALID_EXPERIMENT'}));return 1
        for fn,want in ((refused,'BLOCKED'),(blocked,'BLOCKED'),(failed,'FAIL')):
            with self.subTest(want=want),tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'run_cmd',fn),mock.patch.object(bm,'load_case',return_value=full_case()):
                self.assertEqual(b3.b17_target(Path(t),None,'x')['status'],want)
    def suite(self,rows):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(b3,'b17_targets',return_value=[(None,f'case-{i}') for i in range(len(rows))]),\
             mock.patch.object(b3,'b17_target',side_effect=list(rows)):
            return b3.b17_suite(ROOT,Path(t))
    def test_a_dimension_that_no_control_declares_is_not_run_with_its_ledger_row(self):
        suite,not_run=self.suite([{'status':'PASS','dimensions':sorted(ALL_DIMENSIONS-{'c-multiple-workers'})}])
        self.assertEqual(suite['status'],'PASS');self.assertEqual([n['suite'] for n in not_run],['B17 c-multiple-workers'])
        self.assertIn(b3.B17_LEDGER,not_run[0]['reason'])
    def test_a_covered_dimension_is_never_not_run(self):
        suite,not_run=self.suite([{'status':'PASS','dimensions':sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope'})},
                                  {'status':'PASS','dimensions':['c-multiple-workers','capacity-scope']}])
        self.assertEqual((suite['status'],not_run),('PASS',[]))
    def test_a_lost_dimension_fails(self):
        suite,not_run=self.suite([{'status':'PASS','dimensions':sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope'})}])
        self.assertEqual(suite['status'],'FAIL');self.assertIn('capacity-scope',suite['reason']);self.assertEqual([n['suite'] for n in not_run],['B17 c-multiple-workers'])
    def test_failed_blocked_or_no_targets(self):
        good={'status':'PASS','dimensions':sorted(ALL_DIMENSIONS)}
        self.assertEqual(self.suite([good,{'status':'FAIL','dimensions':[]}])[0]['status'],'FAIL')
        self.assertEqual(self.suite([good,{'status':'BLOCKED','dimensions':[]}])[0]['status'],'BLOCKED')
        self.assertEqual(self.suite([])[0]['status'],'FAIL')
        # the dimensions of a target that did not pass never count
        self.assertEqual(self.suite([{'status':'FAIL','dimensions':sorted(ALL_DIMENSIONS)},{'status':'PASS','dimensions':['caller-scope']}])[0]['status'],'FAIL')
    def test_an_exception_is_fail(self):
        with mock.patch.object(b3,'b17_targets',side_effect=KeyError('x')):
            suite,not_run=b3.b17_suite(ROOT,Path('.'));self.assertEqual((suite['status'],not_run),('FAIL',[]))
    def test_the_selftest_hooks(self):
        import ast, inspect
        self.assertIn('b17_suite(root,run_dir,project)',inspect.getsource(b3.phase3_cases))
        src=(ROOT/'tools/bench.py').read_text();tree=ast.parse(src)
        body=ast.get_source_segment(src,next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='selftest_cases'))
        self.assertIn('s3,a3,n3=bench_phase3.phase3_cases(root,run_dir,latest,project)',body);self.assertIn('not_run+=n3',body)

# EX17-A03: a host that the policy allows (the reduced 2-CPU envelope of container_policy.choose_envelope) but that cannot
# run every cell of the matrix gives B17 BLOCKED with the reason, never FAIL. A real failure still wins.
ENV2={'cpus':2,'cpuset':[0,1],'smt_siblings':[],'reduced':True,'multicore':'PASS'}

def wide_case():
    """full_case with a 4-worker C pool row: on the reduced 2-CPU envelope its cells are planned blocked."""
    c=full_case();c['variants']=[dict(v,workers=[1,2,4]) if v['id']=='c-threads' else v for v in c['variants']];return c

class ReducedEnvelopeTests(unittest.TestCase):
    def target(self,case,plan,obs=None):
        def fake_run(root,args):write_run(root,case,plan,obs);print(json.dumps({'status':'VALID','run_id':RUN_ID}));return 0
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'run_cmd',fake_run),mock.patch.object(bm,'load_case',return_value=case),\
             mock.patch.object(b3,'_current_identity',return_value=CURRENT):
            return b3.b17_target(Path(t),None,case['case_id'])
    def test_a_reduced_envelope_that_cannot_run_every_cell_is_blocked(self):
        case=wide_case();row=self.target(case,smoke_plan(case,envelope=ENV2))
        self.assertEqual(row['status'],'BLOCKED',row.get('problems'));self.assertIn('reduced envelope',row['reason'])
        self.assertIn('beyond the 2-CPU envelope',row['reason'])
        self.assertTrue(row['missing']);self.assertTrue(all('beyond the 2-CPU envelope' in m for m in row['missing']),row['missing'])
    def test_the_policy_envelope_runs_every_cell(self):
        case=wide_case();self.assertEqual(self.target(case,smoke_plan(case))['status'],'PASS')
    def test_a_real_failure_on_a_reduced_envelope_fails(self):
        case=wide_case();plan=smoke_plan(case,envelope=ENV2)
        obs=[o for o in observe(plan) if cell(o)!=('memory','warm','c-serial','direct','shm')]
        plan=dict(plan,memory=[m for m in plan['memory'] if m['trial_id'] in {o['trial_id'] for o in obs}])
        row=self.target(case,plan,obs);self.assertEqual(row['status'],'FAIL')
        self.assertTrue(any('memory c-serial direct [shm]' in p for p in row['problems']),row['problems'])
    def test_an_envelope_block_on_an_envelope_that_is_not_reduced_fails(self):
        case=wide_case();row=self.target(case,smoke_plan(case,envelope=dict(ENV2,reduced=False)))
        self.assertEqual(row['status'],'FAIL')
    def test_a_blocked_target_never_turns_a_lost_dimension_into_a_fail(self):
        run=lambda rows:B17SuiteTests.suite(self,rows)
        # EX18a-A05: the BLOCKED target declares every dimension of its case matrix (b17_target `declared`)
        suite,_=run([{'status':'BLOCKED','dimensions':[],'declared':sorted(ALL_DIMENSIONS),'reason':'the reduced envelope cannot run every cell'}])
        self.assertEqual(suite['status'],'BLOCKED');self.assertIn('python-multiple-workers',suite['reason'])
        suite,_=run([{'status':'BLOCKED','dimensions':[]},{'status':'FAIL','dimensions':[]}])
        self.assertEqual(suite['status'],'FAIL')
        suite,_=run([{'status':'PASS','dimensions':sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope'})}])
        self.assertEqual(suite['status'],'FAIL')         # every target passed: a lost dimension is a real failure

class LostDimensionTests(unittest.TestCase):                   # EX18a-A05
    def run_suite(self,rows):return B17SuiteTests.suite(self,rows)
    def test_a_blocked_target_blocks_only_the_dimensions_that_it_declares(self):
        some=sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope'})
        suite,_=self.run_suite([{'status':'PASS','dimensions':some},{'status':'BLOCKED','dimensions':[],'declared':['capacity-scope']}])
        self.assertEqual(suite['status'],'BLOCKED')
        for declared in (['caller-scope'],[],None):
            row={'status':'BLOCKED','dimensions':[]}
            if declared is not None:row['declared']=declared
            with self.subTest(declared=declared):
                suite,_=self.run_suite([{'status':'PASS','dimensions':some},row])
                self.assertEqual(suite['status'],'FAIL');self.assertIn('capacity-scope',suite['reason'])
    def test_one_undeclared_lost_dimension_fails_the_suite(self):
        some=sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope','route-shm'})
        suite,_=self.run_suite([{'status':'PASS','dimensions':some},{'status':'BLOCKED','dimensions':[],'declared':['capacity-scope']}])
        self.assertEqual(suite['status'],'FAIL');self.assertIn('route-shm',suite['reason'])
    def test_the_declaration_of_a_passing_target_never_blocks(self):
        some=sorted(ALL_DIMENSIONS-{'c-multiple-workers','capacity-scope'})
        suite,_=self.run_suite([{'status':'PASS','dimensions':some,'declared':sorted(ALL_DIMENSIONS)}])
        self.assertEqual(suite['status'],'FAIL')
    def test_a_target_row_declares_the_dimensions_of_its_case_matrix(self):
        case=wide_case();row=ReducedEnvelopeTests.target(self,case,smoke_plan(case,envelope=ENV2))
        cells,_=b3.matrix_cells(case)
        self.assertEqual(row['declared'],sorted(set().union(*[b3.cell_dimensions(c) for c in cells])))
        self.assertEqual(row['status'],'BLOCKED');self.assertLessEqual(set(row['dimensions']),set(row['declared']))
        def refused(root,args):raise GateError('docker unavailable')
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'run_cmd',refused),mock.patch.object(bm,'load_case',return_value=case):
            row=b3.b17_target(Path(t),None,'x')
        self.assertEqual(row['status'],'BLOCKED');self.assertEqual(row['declared'],sorted(set().union(*[b3.cell_dimensions(c) for c in cells])))
    def test_the_comment_states_the_rule(self):
        import inspect
        src=' '.join(inspect.getsource(b3.b17_suite).split())
        self.assertIn('only for a lost dimension that a BLOCKED target declares',src)

class UnitSmokeDeferralTests(unittest.TestCase):               # EX17-A04, closed by EX-18b
    def test_the_deferral_of_the_unit_smoke_job_is_in_the_framework_ledger(self):
        rows={r['id']:r for r in json.loads((ROOT/'safety/framework-ledger.json').read_text())['findings']}
        row=rows['EX17-A04']
        for word in ('unit_smoke_plan','unit_smoke_suite','unit-smoke'):self.assertIn(word,row['location']+row['property'])
        self.assertIn('Owner: owner',row['rationale']);self.assertIn('EX-18b',row['rationale']);self.assertIn('EX-20',row['rationale'])
        # EX-18b implemented the job (the deferral ends): the row is VERIFIED, its verification names the suite and the test
        self.assertEqual(row['state'],'VERIFIED');self.assertTrue(hasattr(b3,'unit_smoke_suite'));self.assertTrue(hasattr(b3,'unit_smoke_plan'))
        self.assertIn('unit-smoke',json.dumps(row['verification']));self.assertIn('test_bench_windows',json.dumps(row['verification']))

if __name__=='__main__':unittest.main()
