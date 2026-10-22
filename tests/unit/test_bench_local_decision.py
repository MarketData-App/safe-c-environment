"""EX-19 (Phase 3 Task 31, framework part; spec 12, Amendment H10, H15.2): local decision runs on a private dataset and
their window attempts (ledger EX18b-A08). Synthetic inputs only: the tests build their own synthetic local files, plans,
observations and closed aggregates; no owner dataset is read. The coordinator parts run on synthetic observations; the
runner runs with fake redacted sessions that return closed aggregates of the job plan they get."""
import argparse, contextlib, copy, hashlib, importlib.util, io, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'tests/unit'))
import bench, bench_model as bm, bench_privacy as bp
from evidence import GateError
from schema_check import validate

POLICY=bm.load_policy(ROOT)
FIXTURE='tests/fixtures/bench-project'          # the project whose protocol holds the aggregate schema of the summary
CASE={'case_id':'fixture-case','version':1}
INODE=4242
CONTROLS=('control-base-a','control-base-b','control-candidate-a','control-candidate-b')

def bl():
    import bench_local_decision
    return bench_local_decision

def coordinator():
    spec=importlib.util.spec_from_file_location('bench_coordinator_local',ROOT/'container/bench-coordinator.py')
    bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);return bc

def summary():
    import test_bench_privacy as tp
    return tp.closed_aggregate()['summary']

# ---- synthetic plans, observations and aggregates ----
def trial(point,variant,block,warmup=False,mode='warm',tier='small',selector='all',unit=None,scope='caller',**extra):
    tid=f"{point}-{variant}-{mode}-"+('w' if warmup else f'b{block:02d}')
    t={'trial_id':tid,'block':None if warmup else block,'order':0,'point':point,'scope':scope,'mode':mode,'variant':variant,'workers':'direct',
       'tier':tier,'loops':1,'warmup':warmup,'selector':selector,**({'unit':unit} if unit else {}),**extra}
    return t

def session(name,rows,blocks=range(12),point='baseline',tier='small'):
    """A timing session: per row (point, variant, selector, unit) one warmup trial and one trial per block."""
    trials=[trial(p,v,None,warmup=True,selector=s,unit=u,tier=tier) for p,v,s,u in rows]
    trials+=[trial(p,v,b,selector=s,unit=u,tier=tier) for b in blocks for p,v,s,u in rows]
    return {'session':name,'point':point,'tier':tier,'class':'primary','trials':trials}

def plan(sessions,sha='a'*64,path='/private/synthetic-local.bin',memory=()):
    return {'schema_version':1,'plan_id':'0'*32,'plan_version':'v1','seed':3,'mode':'decision','case':CASE['case_id'],'case_version':1,
            'dataset':{'kind':'local','size':None,'seed':None,'sha256':sha,'rows':None,'path':path},'project_dir':FIXTURE,'envelope':None,
            'sessions':list(sessions),'memory':list(memory),'pyperf':{'values':3,'warmups':1},'request_limit':POLICY['pools']['request_limit'],'estimate_seconds':1.0,
            'blocked_rows':[]}

def dist(v,n):return {'n':n,'median':v,'iqr':0.0,'min':v,'max':v}

def rows_of(trials,value=100.0,pressure=5,records=4):
    """Closed timing rows of the planned non-warmup trials of a job: per row and block `value` ns per unit, cpu_pressure_total
    `pressure` (a callable of (point, block) gives per-block values) and `records` per request."""
    groups={}
    for t in trials:
        if t.get('warmup') or t.get('scope') not in ('caller','kernel'):continue
        k=(t['point'],t['scope'],t['mode'],t['variant'],t['workers'],t['tier'],t.get('route'),t.get('selector','all'),t.get('unit'))
        groups.setdefault(k,[]).append(t['block'])
    out=[]
    for k,blocks in groups.items():
        b=sorted(blocks);n=len(b);v=value(k[0]) if callable(value) else value
        out.append({'point':k[0],'scope':k[1],'mode':k[2],'variant':k[3],'workers':k[4],'tier':k[5],'route':k[6],'selector':k[7],'unit':k[8],'trials':n,'eligible':True,
                    'wall_ns_per_unit':dist(v,n),'cpu_ns_per_unit':dist(v,n),'block_ids':b,'block_eligible':[True]*n,'blocks':[v]*n,'cpu_blocks':[v]*n,
                    'pressure_blocks':[pressure(k[0],x) if callable(pressure) else pressure for x in b],'request_records':[records]*n})
    return out

ZERO='0'*64

def rule_names():
    """The closed rule names of the aggregate's `rules` block (T5-A02)."""
    return json.loads((ROOT/'schemas/bench-local-aggregate.json').read_text())['properties']['rules']['required']

def aggregate_for(job,**over):
    """The closed aggregate that a decision job of the job plan `job` writes (synthetic values). T5-R1: a job plan with
    `partial` gets the job keys of the coordinator: the flag, the rule counts (all zero) and, for a partial job, rows 0, no
    summary and the zero digests (spec 12 L4)."""
    d={'schema_version':2,'run_id':job['run_id'],'case':job['case'],'dataset_sha256':job['dataset']['sha256'],'rows':job['rows'],'summary':summary(),
       'timings':rows_of(job['trials'],**over.pop('rows_kw',{})),'counters':{'cpu_usage_usec':900,'memory_peak_bytes':None},'exceptions':[],
       'output_digests':{'result_sha256':'b'*64,'reference_sha256':'c'*64},'status':'VALID','cgroup_inode':INODE,'isolated':True,'selector':job.get('reference_selector','all')}
    if 'partial' in job:
        d.update(partial=job['partial'],rules={r:0 for r in rule_names()})
        if job['partial']:d.update(rows=0,summary=None,output_digests={'result_sha256':ZERO,'reference_sha256':ZERO})
    d.update(over);return d

def job_observations(bc,job,per_row_ns=1000):
    """T5R1-A02: the observations that the trials of a local job note inside its container (synthetic values, every trial
    once and eligible). A single-record (panel) trial notes what benchlab/trial.py run_panel notes: L passes of one one-row
    call per panel cell, one work unit per call, the walls of each cell (cell k, from 0, takes (k + 1) x 100 us per call)
    and the coordinator's panel summary; every other trial the rows of its tier at `per_row_ns` ns per row."""
    out=[]
    for t in job['trials']:
        o={'schema_version':1,'run_id':job['run_id'],'trial_id':t['trial_id'],'block':t.get('block'),'order':t.get('order',0),'point':t['point'],
           'scope':t['scope'],'mode':t['mode'],'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],'phase':'caller' if t['scope']=='caller' else 'work',
           'warmup':t['warmup'],'eligible':True,'loops':1,'unavailable':{},'memory':None,'verdict':{'failures':{},'reduction':'MATCH'},'phases':{},
           'cpu_pressure_total':5,'selector':t.get('selector','all')}
        o.update({k:t[k] for k in ('route','route_label','unit') if t.get(k) is not None})
        if 'panel' in t:
            walls={c:[(k+1)*100000]*t['panel_passes'] for k,c in enumerate(t['panel_cells'])}
            o.update(bc._panel_fields(walls),work_units=sum(len(w) for w in walls.values()),wall_ns=sum(sum(w) for w in walls.values())+1000)
        else:o.update(work_units=job['sizes'][t['tier']],wall_ns=per_row_ns*job['sizes'][t['tier']])
        o['cpu_usage_usec']=o['wall_ns']//1000;out.append(o)
    return out

ROOTS=[]      # the temporary roots of the running test; Case.tearDown removes them (the unit gate's /tmp is a small tmpfs)

class Case(unittest.TestCase):
    def tearDown(self):
        while ROOTS:shutil.rmtree(ROOTS.pop(),ignore_errors=True)

def temp_root():
    root=Path(tempfile.mkdtemp());ROOTS.append(root);shutil.copytree(ROOT/'schemas',root/'schemas');(root/'safety').mkdir()
    shutil.copytree(ROOT/FIXTURE,root/FIXTURE)
    for name in ('safety/performance-policy.json','safety/performance-fixtures.json','developer.lock.json','safety/container-policy.json'):shutil.copy(ROOT/name,root/name)
    return root

PROBE=lambda root,run_dir:{'status':'PASS','envelope':None,'evidence_paths':[],'lock_held_ns':0}
GATE=lambda root,run_dir,plan,policy,envelope,probe:([],'PASS')

def run_local(sessions,window=None,make=None,inode=INODE,root=None,memory=(),p=None,case=None):
    """run_local_decision with fake redacted sessions (each returns `make(job plan, label)`, default aggregate_for; None
    gives an empty file) and permitting doctor, guardrail and pre-run steps. `p`: an explicit run plan (default plan of
    `sessions`). Each launcher record path names its label, as the launcher's evidence file name does. Returns (exit code,
    run record, run directory, job plans)."""
    root=root or temp_root();jobs=[];make=make or (lambda j,label:aggregate_for(j))
    class Runner:
        def __init__(self):self.session={'effective':{'cgroup_inode':inode,'events_before':{'cpu.stat':'usage_usec 100\n'}},
                                          'lifecycle':{'counters_after':{'cpu.stat':'usage_usec 900\n'}},'bench':{'envelope':None,'active_before':0}}
        def run(self,argv,timeout=30,label='process',**k):return {'exit_code':0,'failure':None,'evidence_path':f'evidence/0003-{label}.json'}
    class Session:
        image=staticmethod(lambda root:'sha256:'+'e'*64)
        def __init__(self,root,run_dir,fixture=None,redacted=False):
            assert fixture and redacted;self.runner=Runner();self.plan=None;self.label=None
        def job(self,plan,label,timeout,restore=()):
            self.plan=plan;self.label=label;jobs.append(plan);return {'exit_code':0,'failure':None,'evidence_path':f'evidence/0002-{label}.json'}
        def fetch(self,rel,dst):
            assert rel=='bench/out/aggregate.json';doc=make(self.plan,self.label)
            Path(dst).write_text(json.dumps(doc) if doc is not None else '{}');return dst
        def close(self):pass
    p=p if p is not None else plan(sessions,memory=memory);args=argparse.Namespace(format='json')
    with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',Session),\
         mock.patch.object(bench,'doctor_probe',PROBE),mock.patch.object(bench,'guardrail_gate',GATE),mock.patch('policy.source_identity',return_value=('f'*64,None)),\
         mock.patch.object(bench,'native_run_declaration',return_value=None),\
         mock.patch.object(bp,'install_fixture_pattern',return_value=True),contextlib.redirect_stdout(io.StringIO()):
        rc=bp.run_local(root,args,p,dict(case or CASE),POLICY,window=window)
    d=root/'artifacts/bench'/args.created_run_id      # the run that this call created (a root may hold several runs)
    return rc,json.loads((d/'run.json').read_text()),d,jobs

UNIT=[('baseline','py-reference','all',None),('baseline','py-library','all',None)]
CTRL=[(c,'py-reference','all',None) for c in CONTROLS]

# ---- the coordinator part (inside the container) ----
def obs(point,variant,block,wall,units=4,eligible=True,pressure=7,trial_id=None,**extra):
    o={'trial_id':trial_id or f'{point}-{variant}-b{block}','block':block,'point':point,'scope':'caller','mode':'warm','variant':variant,'workers':'direct',
       'tier':'small','warmup':False,'eligible':eligible,'loops':1,'work_units':units,'wall_ns':int(wall*units),'cpu_usage_usec':int(wall*units),'cpu_pressure_total':pressure}
    o.update(extra);return o

class CoordinatorTimingTests(Case):
    def test_the_per_block_fields_of_a_row(self):
        bc=coordinator()
        o=[obs('unit-p','py-reference',2,30.0),obs('unit-p','py-reference',0,10.0),obs('unit-p','py-reference',1,20.0,eligible=False,pressure=None),
           obs('unit-p','c-serial',0,5.0,route='stdio',route_label='x',selector='s1',unit='s1/full-dataset')]
        rows={(r['variant']):r for r in bc._local_timings(o)}
        r=rows['py-reference']
        self.assertEqual((r['block_ids'],r['blocks'],r['block_eligible'],r['pressure_blocks'],r['request_records']),
                         ([0,1,2],[10.0,20.0,30.0],[True,False,True],[7,None,7],[4,4,4]))
        self.assertEqual(r['cpu_blocks'],[10000.0,20000.0,30000.0])       # cpu_usage_usec per unit x 1000 (ns);self.assertFalse(r['eligible']);self.assertEqual((r['route'],r['selector'],r['unit']),(None,'all',None))
        c=rows['c-serial'];self.assertEqual((c['route'],c['selector'],c['unit'],c['blocks']),('stdio','s1','s1/full-dataset',[5.0]))
        agg=bc.local_aggregate({'run_id':'0'*32,'case':'fixture-case','dataset':{'sha256':'a'*64}},dict(summary(),rows=4,result_sha256='b'*64,reference_sha256='c'*64),
                               list(rows.values()),o,[],True)
        validate(ROOT,'bench-local-aggregate',agg)
    def test_inner_samples_collapse_to_their_median(self):
        bc=coordinator()
        o=[obs('k','py-reference',0,w,trial_id='k-0',scope='kernel') for w in (10.0,30.0,20.0)]
        r=bc._local_timings(o)[0];self.assertEqual((r['blocks'],r['trials'],r['pressure_blocks']),([20.0],1,[7]))
    def test_no_per_block_fields_for_an_unblocked_or_repeated_block(self):
        bc=coordinator()
        for name,o in {'no block':[obs('p','py-reference',None,1.0)],'repeated':[obs('p','py-reference',0,1.0,trial_id='a'),obs('p','py-reference',0,1.0,trial_id='b')],
                       'too many':[obs('p','py-reference',b,1.0) for b in range(25)]}.items():
            with self.subTest(name):r=bc._local_timings(o)[0];self.assertNotIn('block_ids',r);self.assertNotIn('blocks',r)
    def test_a_panel_row_holds_the_cell_medians(self):
        bc=coordinator()
        def p(block,m):return obs('unit-one','py-reference',block,1.0,panel_passes=3,panel_call_ns=900,
                                 panel_stats={c:{'median_ns':m+i,'min_ns':0,'max_ns':0} for i,c in enumerate(('c-one','c-two'))})
        r=bc._local_timings([p(1,50.0),p(0,40.0)])[0]
        self.assertEqual(r['cells'],[{'cell':'c-one','blocks':[40.0,50.0]},{'cell':'c-two','blocks':[41.0,51.0]}])
        self.assertEqual((r['panel_passes'],r['call_blocks'],r['panel_status']),(3,[900,900],False))
        diff=dict(p(0,1.0),panel_status_diff=[{'cell':'c-one'}]);self.assertTrue(bc._local_timings([diff])[0]['panel_status'])
    def test_the_aggregate_refuses_a_free_string_and_a_per_row_column(self):
        bc=coordinator();row=bc._local_timings([obs('unit-p','py-reference',0,1.0)])[0]
        base={'schema_version':2,'run_id':'0'*32,'case':'fixture-case','dataset_sha256':'a'*64,'rows':4,'summary':None,'timings':[row],
              'counters':{'cpu_usage_usec':1,'memory_peak_bytes':None},'exceptions':[],'output_digests':{'result_sha256':'b'*64,'reference_sha256':'c'*64},
              'status':'INVALID_EXPERIMENT'}
        validate(ROOT,'bench-local-aggregate',base)
        for name,bad in {'point text':dict(row,point='Owner Row 7'),'per-row column':dict(row,engine_evals=[1,2,3]),'row digest':dict(row,result_sha256='d'*64),
                         'cell text':dict(row,cells=[{'cell':'A B','blocks':[1.0]}]),'25 blocks':dict(row,blocks=[1.0]*25)}.items():
            with self.subTest(name),self.assertRaises(GateError):validate(ROOT,'bench-local-aggregate',dict(base,timings=[bad]))
        with self.assertRaises(GateError):validate(ROOT,'bench-local-aggregate',dict(base,reference_evals={'a':1},owner_rows=[1]))
    def test_the_native_timing_check_runs_in_the_job(self):
        bc=coordinator();plan={'native':{'bd-kernel':'9'*64},'native_kernel':{'program':'bd-kernel'}}
        good={'trial_id':'k1','scope':'kernel','variant':'c-serial','warmup':False,'self_timing':{'mono_ns':1000,'cpu_ns':900},'wall_ns':1000,'cpu_usage_usec':1,'native_sha256':'9'*64}
        bad=dict(good,trial_id='k2',native_sha256='8'*64);slow=dict(good,trial_id='k3',self_timing={'mono_ns':10**9,'cpu_ns':1})
        self.assertEqual(bc.native_timing_failures([good,bad,slow,dict(good,trial_id='k4',warmup=True)],plan,ROOT/'safety/performance-policy.json'),{'k2','k3'})
        self.assertEqual(bc.native_timing_failures([good],plan,ROOT/'no-such-policy.json'),{'k1'})      # an unreadable policy fails every row
        r=bc._local_timings([dict(obs('kern','c-serial',0,1.0,trial_id='k2',scope='kernel'))],failed={'k2'})[0]
        self.assertEqual((r['eligible'],r['block_eligible']),(False,[False]))
    def test_the_job_fields(self):
        bc=coordinator()
        with tempfile.TemporaryDirectory() as t:
            ref=Path(t)/'reference.json';ref.write_text('{}');Path(str(ref)+'.evals').write_text(json.dumps({'s1':5}))
            Path(str(ref)+'.admit').write_text(json.dumps({'row':1,'brent':0,'bump':2}))
            bc.CG=Path(t)
            out=bc.local_job_fields({'reference_selector':'s1'},{'children':[{'isolated':True},{'isolated':True}]},ref)
            self.assertEqual({k:out[k] for k in ('isolated','selector','reference_evals','reference_admit_excluded')},
                             {'isolated':True,'selector':'s1','reference_evals':{'s1':5},'reference_admit_excluded':{'row':1,'brent':0,'bump':2}})
            self.assertIsInstance(out['cgroup_inode'],int);self.assertNotIn('reference_overhead',out)
            self.assertFalse(bc.local_job_fields({},{'children':[{'isolated':None}]},ref)['isolated'])
            Path(str(ref)+'.evals').write_text('{"S1":-1}')
            with self.assertRaises(ValueError):bc.local_job_fields({},{},ref)
    def test_a_panel_trial_of_a_local_job_reads_synthetic_rows(self):
        bc=coordinator();runs=[]
        with tempfile.TemporaryDirectory() as t:
            bc.WORK=Path(t);(Path(t)/'bench/data').mkdir(parents=True)
            def fake(argv,**k):
                runs.append(argv);Path(argv[-4]).write_bytes(b'synthetic');return mock.Mock(returncode=0)
            plan={'dataset':{'kind':'local'},'sizes':POLICY['sizes'],'deadline_seconds':60,'case_manifest':'/src/x.json',
                  'datasets':{'synthetic:large#panel':{'kind':'synthetic','size':'large','seed':20261007}}}
            run={'path':'/work/bench/data/dataset','sha256':'a'*64};panel={'panel':[0,1],'dataset_ref':'synthetic:large#panel'}
            with mock.patch.object(bc.subprocess,'run',side_effect=fake),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                self.assertIs(bc.trial_dataset(plan,{'point':'p'},run,{}),run)                                   # not a panel trial
                self.assertIs(bc.trial_dataset(dict(plan,dataset={'kind':'synthetic'}),panel,run,{}),run)        # a synthetic run keeps its dataset
                cache={};got=bc.trial_dataset(plan,panel,run,cache);again=bc.trial_dataset(plan,panel,run,cache)
            self.assertEqual(got['sha256'],hashlib.sha256(b'synthetic').hexdigest());self.assertIs(got,again);self.assertEqual(len(runs),1)
            self.assertEqual(runs[0][-3:],[str(POLICY['sizes']['large']),'20261007','/m.json'])
            for bad in ({},{'synthetic:large#panel':{'kind':'local','size':'large','seed':1}},{'synthetic:large#panel':{'kind':'synthetic','size':'large','seed':True}}):
                with self.subTest(bad=bad),self.assertRaises(ValueError):bc.trial_dataset(dict(plan,datasets=bad),panel,run,{})
    def test_the_reference_and_the_summary_use_the_reference_selector(self):
        bc=coordinator();seen=[]
        with tempfile.TemporaryDirectory() as t:
            bc.WORK=Path(t)
            plan={'dataset':{'kind':'local'},'sizes':POLICY['sizes'],'rows':4,'deadline_seconds':60,'reference_selector':'s1'}
            with mock.patch.object(bc,'run_deadline',side_effect=lambda argv,*a,**k:seen.append(argv)),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                bc.reference_path(plan,{'path':'/d','sha256':'a'*64})
                with self.assertRaises(ValueError):bc.reference_path(dict(plan,reference_selector='Bad Selector'),{'path':'/d','sha256':'a'*64})
            self.assertEqual(seen[0][-1],'s1')
        self.assertIn("selector=sys.argv[8]",bc.REFERENCE_CODE);self.assertIn("selector=sys.argv[6]",bc.LOCAL_SUMMARY);self.assertIn("selector=sys.argv[2]",bc.LOCAL_HAS_SUMMARY)

class CoordinatorJobTests(Case):
    def test_a_decision_job_writes_the_job_fields(self):
        bc=coordinator()
        with tempfile.TemporaryDirectory() as t:
            work=Path(t);bc.WORK=work;bc.CG=work;private=work/'bench/private/out';private.mkdir(parents=True);out=work/'bench/out';out.mkdir(parents=True)
            (work/'bench/private/reference.json').write_text('{}');(work/'bench/private/reference.json.evals').write_text(json.dumps({'s1':3}))
            # T5-R1 (T5-A02): a decision job checks its observations against its planned trials, so the job plan holds them and
            # each observation is complete (run id, phase, the work units of the tier, the mandatory metrics)
            trials=[trial('unit-p','py-reference',b) for b in range(3)]
            rows=[obs('unit-p','py-reference',b,10.0,units=POLICY['sizes']['small'],trial_id=trials[b]['trial_id'],run_id='0'*32,phase='caller',unavailable={},memory=None)
                  for b in range(3)]
            def timing(plan,o):
                (o/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));return {'status':'PASS','children':[{'isolated':True}]}
            calls=[]
            def run(argv,**k):
                calls.append(argv);return mock.Mock(returncode=0,stdout=json.dumps(dict(summary(),rows=4,result_sha256='b'*64,reference_sha256='c'*64))+'\n')
            plan={'run_id':'0'*32,'case':'fixture-case','dataset':{'kind':'local','sha256':'a'*64},'rows':4,'decision':True,'reference_selector':'s1',
                  'partial':False,'trials':trials,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1}}
            with mock.patch.object(bc,'job_timing',side_effect=timing),mock.patch.object(bc.subprocess,'run',side_effect=run),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                result=bc._local_trials(plan,out,private,[],None)
            doc=json.loads((out/'aggregate.json').read_text());validate(ROOT,'bench-local-aggregate',doc)
            self.assertEqual(result['status'],'PASS');self.assertEqual((doc['status'],doc['selector'],doc['reference_evals'],doc['isolated']),('VALID','s1',{'s1':3},True))
            self.assertIsInstance(doc['cgroup_inode'],int);self.assertEqual(calls[0][-1],'s1')
            self.assertEqual(doc['timings'][0]['block_ids'],[0,1,2])
            with mock.patch.object(bc,'job_timing',side_effect=timing),mock.patch.object(bc.subprocess,'run',side_effect=run),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                bc._local_trials({k:v for k,v in plan.items() if k!='decision'},out,private,[],None)      # a Phase 1 smoke job: no job fields
            self.assertNotIn('cgroup_inode',json.loads((out/'aggregate.json').read_text()))

# ---- the host part ----
class JobTests(Case):
    def test_jobs_selectors_and_rows(self):
        a=session('s-a',[('unit-p','py-reference','s1','s1/full-dataset')],tier='large');b=session('s-b',UNIT+CTRL,tier='small')
        jobs=bl().local_jobs(plan([a,b]),POLICY)
        self.assertEqual([(j['name'],j['selector'],j['rows'],len(j['trials'])) for j in jobs],
                         [('s-a','s1',POLICY['sizes']['large'],13),('s-b','all',POLICY['sizes']['small'],6*13)])
        panel=session('s-c',[('unit-one','py-reference','s1','s1/single-record')],tier='large')
        for t in panel['trials']:t['panel']=[0];t['tier']='large'
        panel['trials']+=[trial('control-base-a','py-reference',0,tier='tiny')]
        self.assertEqual(bl().job_rows(panel['trials'],POLICY['sizes']),POLICY['sizes']['tiny'])       # a panel trial reads synthetic rows
        self.assertEqual(bl().overhead_selectors(plan([a,b])),['s1'])
        self.assertEqual(bl().not_run(plan([a],memory=[{'trial_id':'m'}])),[{'kind':'memory','trials':1}])

class RowCheckTests(Case):
    def test_every_row_is_a_planned_row(self):
        s=session('s',UNIT);job={'run_id':'0'*32,'case':'fixture-case','dataset':{'sha256':'a'*64},'rows':256,'trials':s['trials']}
        doc=aggregate_for(job);self.assertEqual(bl().row_problems(doc,s['trials']),[])
        cases={'an unplanned point':lambda r:r[0].update(point='other-point'),'a trial count':lambda r:r[0].update(trials=11),
               'the blocks':lambda r:r[0].update(block_ids=list(range(1,13))),'a repeated row':lambda r:r.append(copy.deepcopy(r[0])),
               'a missing row':lambda r:r.pop()}
        for name,edit in cases.items():
            with self.subTest(name):
                d=copy.deepcopy(doc);edit(d['timings']);codes={c for c,_ in bl().row_problems(d,s['trials'])}
                self.assertTrue(codes&{'rows-unplanned','rows-missing'},codes)
    def test_a_panel_row_names_its_planned_cells(self):
        t=[trial('unit-one','py-reference',b,panel=[0,1],panel_cells=['c-two','c-one'],panel_passes=3) for b in range(2)]
        row={'point':'unit-one','scope':'caller','mode':'warm','variant':'py-reference','workers':'direct','tier':'small','route':None,'selector':'all','unit':None,'trials':2,
             'block_ids':[0,1],'panel_passes':3,'cells':[{'cell':'c-one','blocks':[1.0,1.0]},{'cell':'c-two','blocks':[1.0,1.0]}]}
        self.assertEqual(bl().row_problems({'timings':[row]},t),[])
        self.assertEqual(bl().row_problems({'timings':[dict(row,panel_passes=4)]},t)[0][0],'rows-unplanned')
        self.assertEqual(bl().row_problems({'timings':[dict(row,cells=row['cells'][:1])]},t)[0][0],'rows-unplanned')

def merged_of(docs,jobs,**host):
    h={'run_id':'0'*32,'case':'fixture-case','dataset_sha256':'a'*64,'problems':[],'accounting':[],'not_run':[]};h.update(host)
    return bl().merge_aggregates(docs,jobs,h)

class MergeTests(Case):
    def setUp(self):
        self.jobs=bl().local_jobs(plan([session('s-a',UNIT),session('s-b',CTRL)]),POLICY)
        self.docs={j['name']:aggregate_for(dict(j,run_id='0'*32,case='fixture-case',dataset={'sha256':'a'*64},reference_selector=j['selector'])) for j in self.jobs}
    def test_a_complete_merge_is_closed_and_valid(self):
        m=merged_of(self.docs,self.jobs);validate(ROOT,'bench-local-merged',m)
        self.assertEqual((m['status'],m['problems'],len(m['timings']),[j['name'] for j in m['jobs']]),('VALID',[],6,['s-a','s-b']))
        self.assertEqual({r['job'] for r in m['timings']},{'s-a','s-b'})
    def test_each_problem(self):
        def doc(name,**over):return {**self.docs,name:dict(self.docs[name],**over)}
        cases={'job-missing':({**self.docs,'s-b':None},{}),'job-invalid':(doc('s-a',status='INVALID_EXPERIMENT'),{}),
               'dataset-differs':(doc('s-a',dataset_sha256='d'*64),{}),'case-differs':(doc('s-a',case='other-case'),{}),
               'cgroup-identity':({**self.docs,'s-a':{k:v for k,v in self.docs['s-a'].items() if k!='cgroup_inode'}},{}),
               'children-not-isolated':(doc('s-a',isolated=False),{}),
               'counts-differ':({'s-a':dict(self.docs['s-a'],reference_evals={'s1':1}),'s-b':dict(self.docs['s-b'],reference_evals={'s1':2})},{}),
               'overhead-repeated':({n:dict(d,reference_overhead={'library_overhead_ns_per_row':1.0}) for n,d in self.docs.items()},{}),
               'rows-unplanned':(doc('s-a',selector='s1'),{})}
        for code,(docs,host) in cases.items():
            with self.subTest(code):
                m=merged_of(docs,self.jobs,**host);validate(ROOT,'bench-local-merged',m)
                self.assertIn(code,m['problems']);self.assertEqual(m['status'],'INVALID_EXPERIMENT')
        acc=[{'session':'s-a','host_total_usec':1,'window_usec':None,'trial_sum_usec':0,'trials':1,'launcher_cgroup_inode':1,'job_cgroup_inode':2,'status':'FAIL'}]
        self.assertIn('cgroup-identity',merged_of(self.docs,self.jobs,accounting=acc)['problems'])
        m=merged_of({},self.jobs,problems=['doctor-blocked']);self.assertEqual(m['status'],'BLOCKED');validate(ROOT,'bench-local-merged',m)
    def test_the_counts_of_the_largest_jobs(self):
        """T5-R1: the largest jobs are the whole-run jobs of the plan (s-b is a tiny session, a partial job without counts);
        the overhead comes from the one whole-run job that measured it."""
        jobs=bl().local_jobs(plan([session('s-a',UNIT),session('s-b',CTRL,tier='tiny')]),POLICY)
        base={j['name']:aggregate_for(dict(j,run_id='0'*32,case='fixture-case',dataset={'sha256':'a'*64},reference_selector=j['selector'])) for j in jobs}
        docs={'s-a':dict(base['s-a'],rows=256,reference_evals={'s1':4},reference_admit_excluded={'row':1,'brent':0,'bump':0},
                         reference_overhead={'library_overhead_ns_per_row':2.5}),'s-b':base['s-b']}
        m=merged_of(docs,jobs)
        self.assertEqual((m['rows'],m['reference_evals'],m['reference_admit_excluded'],m['reference_overhead']),
                         (256,{'s1':4},{'row':1,'brent':0,'bump':0},{'library_overhead_ns_per_row':2.5}))
    def test_the_merged_document_has_no_free_string(self):
        """Every string of the merged document is an enum, a const or a patterned value, and every object is closed: no
        additional property, or keys bounded by a pattern with integer or number values only."""
        schema=json.loads((ROOT/'schemas/bench-local-merged.json').read_text());free=[]
        def types(node):t=node.get('type');return set(t if isinstance(t,list) else [t])
        def walk(node,path):
            if isinstance(node,dict):
                ts=types(node)
                if 'string' in ts and 'pattern' not in node and 'enum' not in node and 'const' not in node:free.append(path)
                if 'object' in ts:
                    extra=node.get('additionalProperties',True)
                    if extra is not False and not (isinstance(extra,dict) and types(extra)<={'integer','number'} and 'pattern' in (node.get('propertyNames') or {})):
                        free.append(path+' (open object)')
                for k,v in node.items():walk(v,path+'/'+k)
            elif isinstance(node,list):
                for i,v in enumerate(node):walk(v,f'{path}/{i}')
        walk(schema,'');self.assertEqual(free,[])

class ObservationTests(Case):
    def merged(self,rows):
        return {'timings':[dict({'job':'s','cells':None,'panel_passes':None,'panel_status':False,'call_blocks':None},**r) for r in rows]}
    def test_the_decision_code_gets_back_the_block_values(self):
        import bench_units as bu
        s=session('s',[('unit-p','py-optimized','s1','s1/full-dataset')])
        m=self.merged(rows_of(s['trials'],value=lambda p:250.0,records=8));o=bl().observations_from_merged(m,plan([s]),POLICY['routes'])
        self.assertEqual(len(o),12);self.assertEqual({x['trial_id'] for x in o},{t['trial_id'] for t in s['trials'] if not t['warmup']})
        self.assertEqual(bench.per_trial(o,'wall_ns'),{b:250.0 for b in range(12)})
        rows=bu.rows_from_observations(o,planned=bu.planned_passes(plan([s])))
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['eligible']);self.assertEqual(rows[0]['wall'],{b:2000.0 for b in range(12)})   # per request: 250 x 8 records
        self.assertEqual(rows[0]['unit'],'s1/full-dataset')
        self.assertTrue(all('result_sha256' not in x and 'dataset_ref' not in x for x in o))
    def test_a_panel_row_gives_its_worst_cell(self):
        import bench_units as bu
        cells=['c1','c2','c3','c4','c5','c6']
        tr=[trial('unit-one','py-reference',b,unit='s1/single-record',selector='s1',panel=list(range(6)),panel_cells=cells,panel_passes=2) for b in range(12)]
        row=rows_of(tr)[0];row.update(panel_passes=2,cells=[{'cell':c,'blocks':[10.0*(i+1)]*12} for i,c in enumerate(cells)],call_blocks=[5]*12)
        p=plan([{'session':'s','trials':tr}]);o=bl().observations_from_merged(self.merged([row]),p)
        rows=bu.rows_from_observations(o,planned=bu.planned_passes(p),cells=cells)
        self.assertEqual(rows[0]['wall'],{b:60.0 for b in range(12)});self.assertTrue(rows[0]['eligible'])
        bad=dict(row,panel_status=True);self.assertFalse(bu.rows_from_observations(bl().observations_from_merged(self.merged([bad]),p),planned=bu.planned_passes(p),cells=cells)[0]['eligible'])
    def test_an_ineligible_block_stays_ineligible(self):
        s=session('s',[('unit-p','py-optimized','all',None)]);row=rows_of(s['trials'])[0];row['block_eligible'][3]=False
        o=bl().observations_from_merged(self.merged([row]),plan([s]))
        self.assertNotIn(3,bench.per_trial(o,'wall_ns'));self.assertEqual(len(bench.per_trial(o,'wall_ns')),11)

class AccountingTests(Case):
    SESSION={'effective':{'cgroup_inode':77,'events_before':{'cpu.stat':'usage_usec 100\n'}},'lifecycle':{'counters_after':{'cpu.stat':'usage_usec 900\n'}}}
    def test_the_cgroup_identity_of_a_job(self):
        import bench_accounting as ba
        reasons,row=bl().local_accounting('s-a',self.SESSION,{'cgroup_inode':77,'counters':{'cpu_usage_usec':500}},3)
        self.assertEqual((reasons,row['status'],row['host_total_usec'],row['trial_sum_usec'],row['window_usec']),([],'PASS',800,500,None))
        self.assertEqual(ba.recheck({'dataset':{'kind':'local'},'accounting':[row]}),[])
        reasons,row=bl().local_accounting('s-a',self.SESSION,{'cgroup_inode':78,'counters':{}});self.assertIn('incorrect cgroup identity',reasons[0]);self.assertEqual(row['status'],'FAIL')
        reasons,row=bl().local_accounting('s-a',self.SESSION,None);self.assertEqual(row['status'],'FAIL')
        self.assertEqual(bl().require_local_fields({'cgroup_inode':5}),[]);self.assertEqual(bl().require_local_fields({}),['aggregate lacks cgroup_inode'])

# ---- the runner ----
class RunnerTests(Case):
    def test_a_local_decision_run_merges_one_aggregate_per_session(self):
        rc,run,d,jobs=run_local([session('s-a',UNIT),session('s-b',UNIT,point='baseline')])
        self.assertEqual((rc,run['status'],run['mode']),(0,'VALID','decision'))
        self.assertEqual([j['trials'] for j in jobs],[session('s-a',UNIT)['trials'],session('s-b',UNIT)['trials']])
        self.assertTrue(all(j['decision'] is True and j['local'] is True and j['reference_selector']=='all' for j in jobs))
        self.assertEqual(sorted(p.name for p in d.iterdir() if p.name.startswith('aggregate-')),['aggregate-s-a.json','aggregate-s-b.json'])
        m=json.loads((d/'local-merged.json').read_text());validate(ROOT,'bench-local-merged',m);self.assertEqual(m['status'],'VALID')
        for name in ('local-merged.json','aggregate-s-a.json','plan.json'):self.assertIn(name,run['evidence_digests'])
        self.assertEqual([a['status'] for a in run['accounting']],['PASS','PASS']);self.assertNotIn('path',json.loads((d/'plan.json').read_text())['dataset'])
        self.assertNotIn('synthetic-local',json.dumps(run)+(d/'local-merged.json').read_text())          # the fixture path is in no record
        self.assertNotIn('window',run)
    def test_the_first_job_measures_the_overhead_only(self):
        s1=session('s-a',[('unit-p','py-reference','s1','s1/full-dataset')]);s2=session('s-b',[('unit-p2','py-reference','s1','s1/full-dataset')])
        _,run,_,jobs=run_local([s1,s2])
        self.assertEqual([j.get('overhead_selectors') for j in jobs],[['s1'],None]);self.assertEqual([j['reference_selector'] for j in jobs],['s1','s1'])
    def test_a_missing_or_failed_job_makes_the_run_invalid(self):
        rc,run,d,_=run_local([session('s-a',UNIT),session('s-b',UNIT)],make=lambda j,label:None if label=='local-s-b' else aggregate_for(j))
        self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'))
        m=json.loads((d/'local-merged.json').read_text());self.assertIn('job-missing',m['problems']);self.assertIn('job-failed',m['problems'])
        self.assertEqual([j['status'] for j in m['jobs']],['VALID','MISSING']);self.assertFalse((d/'aggregate-s-b.json').exists())    # a rejected aggregate is deleted
        rc,run,d,_=run_local([session('s-a',UNIT)],make=lambda j,label:aggregate_for(j,status='INVALID_EXPERIMENT'))
        self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('job-invalid',json.loads((d/'local-merged.json').read_text())['problems'])
        rc,run,d,_=run_local([session('s-a',UNIT)],make=lambda j,label:aggregate_for(j,timings=[]))
        self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('rows-missing',json.loads((d/'local-merged.json').read_text())['problems'])
        rc,run,d,_=run_local([session('s-a',UNIT)],inode=INODE+1)
        self.assertEqual(run['status'],'INVALID_EXPERIMENT');self.assertEqual(run['accounting'][0]['status'],'FAIL')
    def test_memory_trials_are_not_run_and_decide_nothing(self):
        rc,run,d,jobs=run_local([session('s-a',UNIT)],memory=[{'trial_id':'memory-x'}])
        self.assertEqual((rc,len(jobs)),(0,1));self.assertEqual(json.loads((d/'local-merged.json').read_text())['not_run'],[{'kind':'memory','trials':1}])

def window(attempt=1,extends=None):
    return {'window':'1a','attempt':attempt,'window_plan_id':'1'*32,'extends':extends,'version':{'plan_id':'1'*32,'windows':[{'id':'1a'}]},'extension_of':None,'look1':None}

class LocalWindowTests(Case):           # EX18b-A08: a local window attempt is recorded with its chain fields
    def test_a_pass_attempt_records_its_chain_fields(self):
        rc,run,d,_=run_local([session('w-s00',UNIT+CTRL)],window=window())
        self.assertEqual(rc,0)
        self.assertEqual((run['window'],run['attempt'],run['window_plan_id'],run['extends'],run['extension_of']),('1a',1,'1'*32,None,None))
        self.assertEqual(run['attempt_outcome'],{'status':'PASS','reason':None,'controls':{'base':'EQUAL','candidate':'EQUAL'}})
        self.assertEqual(run['envelope_identity']['datasets']['primary'],hashlib.sha256(json.dumps({'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':run['dataset']['rows']},
                                                                                                     sort_keys=True,separators=(',',':')).encode()).hexdigest())
        m=json.loads((d/'local-merged.json').read_text())
        self.assertEqual(m['window'],{'id':'1a','attempt':1,'plan_id':'1'*32,'extends':None,'outcome':run['attempt_outcome']})
        self.assertEqual(json.loads((d/'window-plan.json').read_text()),window()['version'])
    def test_an_unreadable_pressure_blocks_the_attempt(self):
        make=lambda j,label:aggregate_for(j,rows_kw={'pressure':lambda point,b:None if point=='control-base-a' and b==4 else 5})
        rc,run,_,_=run_local([session('w-s00',UNIT+CTRL)],window=window(),make=make)
        self.assertEqual((rc,run['attempt_outcome']['status'],run['attempt_outcome']['reason']),(2,'BLOCKED','window-pressure'))
        self.assertEqual(run['status'],'VALID')                       # the run is valid; the attempt is environmental (run the window again)
    def test_noisy_controls_block_the_attempt(self):
        make=lambda j,label:aggregate_for(j,rows_kw={'value':lambda point:200.0 if point=='control-candidate-b' else 100.0})
        _,run,_,_=run_local([session('w-s00',UNIT+CTRL)],window=window(),make=make)
        self.assertEqual((run['attempt_outcome']['status'],run['attempt_outcome']['reason'],run['attempt_outcome']['controls']['candidate']),
                         ('BLOCKED','window-control-noise','SLOWER'))
    def test_an_invalid_attempt_is_a_final_fail(self):
        _,run,_,_=run_local([session('w-s00',UNIT+CTRL)],window=window(),make=lambda j,label:aggregate_for(j,isolated=False))
        self.assertEqual((run['status'],run['attempt_outcome']['status'],run['attempt_outcome']['reason']),('INVALID_EXPERIMENT','FAIL','run-invalid'))
    def test_the_chain_and_the_recorded_checks_read_a_local_attempt(self):
        import bench_windows as bw, bench_phase3_cli as cli
        root=temp_root();_,run,d,_=run_local([session('w-s00',UNIT+CTRL)],window=window(),root=root)
        ch=bw.chain(root,'1'*32)
        self.assertEqual([(a['window'],a['attempt'],a['status'],a['record_sha256']) for a in ch['attempts']],[('1a',1,'PASS',run['run_record_sha256'])])
        self.assertEqual(ch['positions'],{'1a':run['run_record_sha256']})
        self.assertEqual(bw.run_observations(d),bl().observations_from_merged(json.loads((d/'local-merged.json').read_text()),json.loads((d/'plan.json').read_text()),POLICY['routes']))
        with mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),mock.patch('policy.source_identity',return_value=('f'*64,None)):
            self.assertEqual(cli.recorded_problems(root,d.name),[])
            self.assertEqual(bl().outcome_problems(root,d,dict(run,attempt_outcome=dict(run['attempt_outcome'],status='BLOCKED')),json.loads((d/'plan.json').read_text()),POLICY),
                             ['the recorded attempt outcome differs from the outcome of the merged document'])
    def test_a_local_window_attempt_reaches_the_local_runner(self):
        """EX18b-A08 regression: bench run --plan PATH --window ID on a local dataset is no longer refused; the attempt, its
        window, attempt number and plan version go to the local runner (the fixture path is in no plan version). The run
        root is an empty directory: a project instance (a child of the starter export) refuses every local dataset (spec
        12), and the loads of the run are mocked."""
        import test_bench_windows as tw
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'root';root.mkdir()
            data=Path(t)/'synthetic-local.bin';data.write_bytes(b'synthetic rows');sha=hashlib.sha256(data.read_bytes()).hexdigest()
            version=dict(tw.decision_plan(),dataset={'kind':'local','size':None,'seed':None,'sha256':sha,'rows':None})
            path=Path(t)/'plan.json';path.write_text(json.dumps(version));seen={}
            def fake(root,args,plan,case,policy,envelope=None,window=None):seen.update(plan=plan,window=window);return 0
            args=argparse.Namespace(case='window-fixture',plan=str(path),window='1a',extend=None,policy=None,project=None,dataset='local:'+str(data),mode='smoke',
                                    calibrate=None,format='json',matrix=None)
            with mock.patch('bench.project_arg',return_value=None),mock.patch('bench_model.load_policy',return_value=tw.pdoc()),\
                 mock.patch('bench_model.load_case',return_value=tw.wcase()),mock.patch('bench_model.case_rules'),mock.patch('bench.refuse_dropped_checks',return_value=None),\
                 mock.patch('bench_model.load_decision_policy',return_value=tw.WPOL),mock.patch('bench.verify_written_plan'),mock.patch('bench.native_run_declaration',return_value=None),\
                 mock.patch('bench_model.require_locked_selectors'),mock.patch('bench.dataset_identity_reasons',return_value=[]),mock.patch('bench_privacy.run_local',side_effect=fake),\
                 mock.patch('container_policy.choose_envelope',return_value=tw.ENV4),mock.patch('container_policy.host_topology',return_value=(None,None)),\
                 mock.patch('bench_windows.chain',return_value={'attempts':[],'superseded':[],'exhausted':[],'positions':{}}),contextlib.redirect_stdout(io.StringIO()):
                rc=bench.run_cmd(root,args)
            self.assertEqual(rc,0);self.assertEqual((seen['window']['window'],seen['window']['attempt'],seen['window']['extends']),('1a',1,None))
            self.assertNotIn('path',seen['window']['version']['dataset']);self.assertEqual(seen['plan']['dataset']['path'],str(data.resolve()))
            self.assertEqual(seen['plan']['window'],{'id':'1a','look':1,'plan_id':version['plan_id']})
    def test_a_window_smoke_calibration_on_a_local_dataset_is_refused(self):
        import test_bench_windows as tw
        args=argparse.Namespace(case='window-fixture',plan=None,window=None,extend=None,policy='window-fixture-units',project=None,dataset='local:/x',mode='smoke',
                                calibrate=None,format='json',matrix=None)
        out=io.StringIO()
        with mock.patch('bench.project_arg',return_value=None),mock.patch('bench_model.load_case',return_value=tw.wcase()),mock.patch('bench_model.case_rules'),\
             mock.patch('bench.refuse_dropped_checks',return_value=None),mock.patch('bench_model.load_decision_policy',return_value=tw.WPOL),\
             mock.patch('container_policy.choose_envelope',return_value=tw.ENV4),mock.patch('container_policy.host_topology',return_value=(None,None)),contextlib.redirect_stdout(out):
            self.assertEqual(bench.run_cmd(ROOT,args),1)
        self.assertIn('a local run records no observations',out.getvalue())
    def test_a_window_plan_on_a_local_dataset_is_estimated(self):
        """A local plan records no row count (F-11): the window estimate and the call deadline use the tier rows that a
        local job slices (bench_windows.trial_seconds, bench_deadline.job_inputs), never a missing row count."""
        import test_bench_windows as tw, bench_deadline as bd
        local={'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None}
        p=tw.bp.build_plan(tw.wcase(),tw.pdoc(),mode='decision',dataset=local,seed=3,envelope=tw.ENV4,calibration=dict(tw.CAL),calibration_source=dict(tw.SOURCE),
                           unit_policy=tw.WPOL,calibration_observations=tw.REF_OBS)
        self.assertEqual(p['dataset'],local);self.assertTrue(p['windows'])
        t={'variant':'py-optimized','selector':'ma','tier':'large','loops':1}
        self.assertEqual(tw.bw.trial_seconds(t,tw.pdoc(),None,local),tw.bw.trial_seconds(t,tw.pdoc(),None,tw.LARGE))
        self.assertEqual(bd.job_inputs('timing',{'sizes':POLICY['sizes'],'dataset':local},{'tier':'small','loops':2}),(POLICY['sizes']['small'],2))

class PrivacyRunTests(Case):
    def test_a_decision_plan_goes_to_the_local_decision_runner_without_its_path(self):
        seen={}
        def fake(root,args,plan,case,policy,path,envelope=None,window=None):seen.update(plan=plan,path=path,window=window);return 0
        p=plan([session('s',UNIT)])
        with mock.patch('bench_local_decision.run_local_decision',side_effect=fake):
            self.assertEqual(bp.run_local(ROOT,argparse.Namespace(format='json'),p,dict(CASE),POLICY,window={'window':'1a'}),0)
        self.assertEqual(seen['path'],'/private/synthetic-local.bin');self.assertNotIn('path',seen['plan']['dataset']);self.assertEqual(seen['window'],{'window':'1a'})
        with self.assertRaises(GateError):bp.run_local(ROOT,argparse.Namespace(format='json'),dict(plan([]),mode='smoke'),dict(CASE),POLICY,window={'window':'1a'})
    def test_an_error_that_names_the_fixture_is_withheld(self):
        path='/private/synthetic-local.bin'
        class Failing:
            def __init__(self,*a,**k):raise OSError(5,'Input/output error',path)
        with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',Failing),\
             mock.patch.object(bench,'doctor_probe',PROBE),mock.patch.object(bench,'guardrail_gate',GATE),mock.patch.object(bp,'install_fixture_pattern',return_value=True):
            with self.assertRaises(GateError) as ctx:bp.run_local(temp_root(),argparse.Namespace(format='json'),plan([session('s',UNIT)]),dict(CASE),POLICY)
        self.assertIn('withheld',str(ctx.exception));self.assertNotIn(path,str(ctx.exception))

class DecideTests(Case):
    def decide(self,d,policy):
        import bench_phase3_cli as cli
        out=io.StringIO()
        with mock.patch('bench._run_dir',return_value=d),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
             mock.patch('policy.source_identity',return_value=('f'*64,{})),mock.patch('bench_decide._current_identity',return_value='f'*64),contextlib.redirect_stdout(out):
            rc=cli.decide_cmd(ROOT,argparse.Namespace(run_id=d.name,policy=policy,format='json',ci_run_id=None,approval=[]))
        return rc,out.getvalue()
    def test_a_rule_policy_decides_a_local_run_from_its_merged_document(self):
        _,run,d,_=run_local([session('s-a',UNIT)])
        rc,_=self.decide(d,'demo-cpu-40');self.assertIn(rc,(0,1))
        rec=json.loads((d/'decision-demo-cpu-40.json').read_text())
        self.assertEqual((rec['local'],rec['evidence_quality']),(True,'owner fixture, local run, aggregate'))
    def test_a_local_run_whose_merged_document_differs_from_its_aggregates_is_invalid(self):
        import bench_evidence as be, bench_local_decision as b
        _,run,d,_=run_local([session('s-a',UNIT)])
        p=d/'aggregate-s-a.json';doc=json.loads(p.read_text());doc['timings'][0]['blocks'][0]=1.0;p.write_text(json.dumps(doc))
        status,reasons=b.recorded_status(ROOT,d,run,json.loads((d/'plan.json').read_text()),POLICY)
        self.assertEqual(status,'INVALID_EXPERIMENT');self.assertIn('local-merged.json differs from the merge of its recorded aggregates',reasons)
        self.assertIn('changed after the run: aggregate-s-a.json',be.verify(d,run))       # decide refuses it earlier: the evidence digests
        rc,text=self.decide(d,'demo-cpu-40');self.assertEqual(rc,1)

# ---- T5-R1 (the EX-19 approver findings) ----
def files_with(d,text):
    """The files of the run directory `d` whose bytes hold `text` (a planted value must be in none)."""
    return sorted(str(p.relative_to(d)) for p in Path(d).rglob('*') if p.is_file() and text.encode() in p.read_bytes())

class PartialJobTests(Case):           # T5-A01 (spec 12 Round-4 L4): whole-run digests, summaries and counts only
    def test_a_partial_job_leaves_no_digest_summary_or_count_of_its_slice(self):
        rc,run,d,jobs=run_local([session('s-a',UNIT),session('s-b',CTRL,tier='tiny')])
        self.assertEqual((rc,run['status']),(0,'VALID'))
        self.assertEqual([(j['rows'],j['partial']) for j in jobs],[(POLICY['sizes']['small'],False),(POLICY['sizes']['tiny'],True)])
        part=json.loads((d/'aggregate-s-b.json').read_text());whole=json.loads((d/'aggregate-s-a.json').read_text())
        self.assertEqual((part['partial'],part['rows'],part['summary'],part['output_digests']),(True,0,None,{'result_sha256':ZERO,'reference_sha256':ZERO}))
        self.assertFalse(any(k in part for k in ('reference_evals','reference_admit_excluded','reference_overhead')))
        self.assertEqual((whole['partial'],whole['output_digests']['reference_sha256']),(False,'c'*64))
        m=json.loads((d/'local-merged.json').read_text());validate(ROOT,'bench-local-merged',m)
        by={j['name']:j for j in m['jobs']}
        self.assertEqual({k:by['s-b'][k] for k in ('partial','rows','reference_sha256','result_sha256')},{'partial':True,'rows':None,'reference_sha256':None,'result_sha256':None})
        self.assertEqual((by['s-a']['partial'],by['s-a']['rows'],m['rows'],run['dataset']['rows']),(False,POLICY['sizes']['small'],POLICY['sizes']['small'],POLICY['sizes']['small']))
    def test_the_host_refuses_and_deletes_a_partial_slice_digest_summary_rows_or_count(self):
        planted='d'*64
        def bad(edit):
            def make(j,label):
                doc=aggregate_for(j)
                if j['partial']:edit(doc)
                return doc
            return make
        cases={'a digest':lambda d:d.update(output_digests={'result_sha256':planted,'reference_sha256':planted}),
               'a summary':lambda d:d.update(summary=summary()),'a row count':lambda d:d.update(rows=1),
               'a count block':lambda d:d.update(reference_evals={'s1':7}),
               'the whole-run flag with a digest':lambda d:d.update(partial=False,rows=1,summary=summary(),output_digests={'result_sha256':planted,'reference_sha256':planted}),
               'no flag with a digest':lambda d:(d.pop('partial'),d.update(rows=1,summary=summary(),output_digests={'result_sha256':planted,'reference_sha256':planted}))}
        for name,edit in cases.items():
            with self.subTest(name):
                rc,run,d,_=run_local([session('s-a',UNIT),session('s-b',CTRL,tier='tiny')],make=bad(edit))
                self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'))
                self.assertFalse((d/'aggregate-s-b.json').exists())          # the rejected aggregate is deleted
                m=json.loads((d/'local-merged.json').read_text());self.assertIn('job-missing',m['problems'])
                self.assertEqual(files_with(d,planted),[])
                if name in ('the whole-run flag with a digest','no flag with a digest'):self.assertIn('partial-slice',m['problems'])
    def test_the_aggregate_schema_refuses_a_partial_slice(self):
        job={'run_id':'0'*32,'case':'fixture-case','dataset':{'sha256':'a'*64},'rows':1,'trials':session('s',CTRL,tier='tiny')['trials'],'partial':True}
        doc=aggregate_for(job);validate(ROOT,'bench-local-aggregate',doc)
        for name,over in {'digest':{'output_digests':{'result_sha256':'b'*64,'reference_sha256':ZERO}},'summary':{'summary':summary()},'rows':{'rows':1},
                          'counts':{'reference_evals':{'s1':1}},'admission':{'reference_admit_excluded':{'row':0,'brent':0,'bump':0}},
                          'overhead':{'reference_overhead':{'library_overhead_ns_per_row':1.0}}}.items():
            with self.subTest(name),self.assertRaises(GateError):validate(ROOT,'bench-local-aggregate',dict(doc,**over))
        whole=aggregate_for(dict(job,partial=False,rows=256));validate(ROOT,'bench-local-aggregate',whole)
        with self.assertRaises(GateError):validate(ROOT,'bench-local-aggregate',dict(whole,summary=None))     # a whole-run job without a summary is never VALID
    def test_the_merge_never_copies_a_partial_slice(self):
        jobs=bl().local_jobs(plan([session('s-a',UNIT),session('s-b',CTRL,tier='tiny')]),POLICY)
        docs={j['name']:aggregate_for(dict(j,run_id='0'*32,case='fixture-case',dataset={'sha256':'a'*64},reference_selector=j['selector'])) for j in jobs}
        self.assertEqual([bl().slice_problems(docs[j['name']],j) for j in jobs],[[],[]])
        m=merged_of(docs,jobs);self.assertEqual((m['status'],m['problems']),('VALID',[]))
        leak=dict(docs['s-b'],partial=False,rows=1,output_digests={'result_sha256':'d'*64,'reference_sha256':'d'*64},reference_evals={'s1':3})
        self.assertEqual(bl().slice_problems(leak,jobs[1]),['partial-flag','rows','digest','counts'])
        m=merged_of(dict(docs,**{'s-b':leak}),jobs);validate(ROOT,'bench-local-merged',m)
        self.assertIn('partial-slice',m['problems']);self.assertNotIn('d'*64,json.dumps(m));self.assertNotIn('reference_evals',m)
        self.assertEqual(bl().slice_problems(dict(docs['s-a'],partial=True),jobs[0]),['partial-flag'])     # a whole-run job: its flag
    def test_a_run_of_one_row_has_no_whole_run_job(self):
        jobs=bl().local_jobs(plan([session('s-a',UNIT,tier='tiny'),session('s-b',CTRL,tier='tiny')]),POLICY)
        self.assertEqual([j['partial'] for j in jobs],[True,True])
        rc,run,d,_=run_local([session('s-a',UNIT,tier='tiny')])
        m=json.loads((d/'local-merged.json').read_text())
        self.assertEqual((rc,m['rows'],m['jobs'][0]['reference_sha256'],run['dataset']['rows']),(0,0,None,None))
    def test_the_first_whole_run_job_measures_the_overhead(self):
        s1=session('s-a',[('unit-p','py-reference','s1','s1/full-dataset')],tier='tiny');s2=session('s-b',[('unit-p2','py-reference','s1','s1/full-dataset')])
        _,run,_,jobs=run_local([s1,s2])
        self.assertEqual([(j['partial'],j.get('overhead_selectors')) for j in jobs],[(True,None),(False,['s1'])])
    def test_a_partial_coordinator_job_computes_no_summary_and_exports_no_slice(self):
        bc=coordinator()
        with tempfile.TemporaryDirectory() as t:
            work=Path(t);bc.WORK=work;bc.CG=work;private=work/'bench/private/out';private.mkdir(parents=True);out=work/'bench/out';out.mkdir(parents=True)
            (work/'bench/private/reference.json').write_text('{}');(work/'bench/private/reference.json.evals').write_text(json.dumps({'s1':3}))
            (work/'bench/private/reference.json.admit').write_text(json.dumps({'row':1,'brent':0,'bump':0}))
            trials=[trial('unit-p','py-reference',b,tier='tiny') for b in range(3)]
            rows=[obs('unit-p','py-reference',b,10.0,trial_id=trials[b]['trial_id'],units=1,tier='tiny',run_id='0'*32,phase='caller',unavailable={},memory=None) for b in range(3)]
            def timing(plan,o):
                (o/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));return {'status':'PASS','children':[{'isolated':True}]}
            calls=[]
            def run(argv,**k):
                calls.append(argv);return mock.Mock(returncode=0,stdout=json.dumps(dict(summary(),rows=1,result_sha256='b'*64,reference_sha256='c'*64))+'\n')
            plan={'run_id':'0'*32,'case':'fixture-case','dataset':{'kind':'local','sha256':'a'*64},'rows':1,'decision':True,'reference_selector':'s1','partial':True,
                  'trials':trials,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1}}
            with mock.patch.object(bc,'job_timing',side_effect=timing),mock.patch.object(bc.subprocess,'run',side_effect=run),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                result=bc._local_trials(plan,out,private,[],None)
            doc=json.loads((out/'aggregate.json').read_text());validate(ROOT,'bench-local-aggregate',doc)
            self.assertEqual(calls,[])                                      # no summary child: its rows are a slice of the run's rows
            self.assertEqual((result['status'],doc['status'],doc['partial'],doc['rows'],doc['summary'],doc['output_digests']),
                             ('PASS','VALID',True,0,None,{'result_sha256':ZERO,'reference_sha256':ZERO}))
            self.assertFalse(any(k in doc for k in ('reference_evals','reference_admit_excluded')))
            self.assertEqual(set(doc['rules']),set(bc.LOCAL_RULES));self.assertFalse(any(doc['rules'].values()))
    def test_a_failure_of_the_job_fields_keeps_the_partial_flag_of_the_plan(self):
        """T5R1-A04: when local_job_fields raises (an OSError of the cgroup stat, a malformed count file), the aggregate
        still holds the plan's partial flag, so the host records an invalid job and never the privacy code partial-slice
        for an I/O failure; whole-run and partial jobs."""
        for partial,error in ((False,OSError('cgroup stat')),(True,OSError('cgroup stat')),(False,ValueError('count file'))):
            bc=coordinator()
            with self.subTest(partial=partial,error=type(error).__name__),tempfile.TemporaryDirectory() as t:
                work=Path(t);bc.WORK=work;bc.CG=work;private=work/'bench/private/out';private.mkdir(parents=True);out=work/'bench/out';out.mkdir(parents=True)
                (work/'bench/private/reference.json').write_text('{}')
                trials=[trial('unit-p','py-reference',b,tier='tiny') for b in range(3)]
                rows=[obs('unit-p','py-reference',b,10.0,trial_id=trials[b]['trial_id'],units=1,tier='tiny',run_id='0'*32,phase='caller',unavailable={},memory=None)
                      for b in range(3)]
                def timing(plan,o):
                    (o/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));return {'status':'PASS','children':[{'isolated':True}]}
                def run(argv,**k):return mock.Mock(returncode=0,stdout=json.dumps(dict(summary(),rows=2,result_sha256='b'*64,reference_sha256='c'*64))+'\n')
                plan={'run_id':'0'*32,'case':'fixture-case','dataset':{'kind':'local','sha256':'a'*64},'rows':2,'decision':True,'reference_selector':'s1',
                      'partial':partial,'trials':trials,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1}}
                with mock.patch.object(bc,'job_timing',side_effect=timing),mock.patch.object(bc.subprocess,'run',side_effect=run),\
                     mock.patch.object(bc,'_manifest',return_value='/m.json'),mock.patch.object(bc,'local_job_fields',side_effect=error):
                    result=bc._local_trials(plan,out,private,[],None)
                doc=json.loads((out/'aggregate.json').read_text());validate(ROOT,'bench-local-aggregate',doc)
                self.assertEqual((result['status'],doc['status'],doc.get('partial')),('FAIL','INVALID_EXPERIMENT',partial))
                self.assertEqual(bl().slice_problems(doc,{'partial':partial}),[])        # no partial-slice: the job is invalid, not a slice
                self.assertNotIn('cgroup_inode',doc);self.assertEqual(set(doc['rules']),set(bc.LOCAL_RULES))

RID='0'*32;SHA='9'*64
PANEL_CELLS=('g1-pos-near','g1-pos-far','g0-mid-near','g0-mid-far','g1-neg-near','g1-neg-far')     # the cell rule of the FIXTURE protocol

def panel_keys(passes,cells=PANEL_CELLS):
    """The G7.3 plan keys of a single-record (panel) trial (bench_plan.panel_fields): six panel rows in cell order, L passes,
    the cell labels and the reference status of each row."""
    return {'panel':[0,1,2,3,4,5],'panel_passes':passes,'panel_cells':list(cells),'panel_reference_status':['OK']*6}

def rule_evidence():
    """A clean synthetic job (T5-A02): a warm caller row (a warmup and one block), a Python kernel row (pyperf values +
    warmups observations, with its control-zero phase) and a warm py-threads caller row (its pool start phase and the
    Amendment E chunk rule), each on the small tier. T5R1-A01: and a warm single-record (panel) trial on the tiny tier: six
    panel rows, L = 5 passes of one-row calls, so its observation reports 6 x 5 = 30 work units (benchlab/trial.py
    run_panel). (trials, observations, phases, timing)."""
    import bench_plan as bpl
    def t(tid,scope,variant,warmup=False,workers='direct'):
        return {'trial_id':tid,'block':None if warmup else 0,'order':0,'point':'p','scope':scope,'mode':'warm','variant':variant,'workers':workers,'tier':'small',
                'loops':1,'warmup':warmup}
    trials=[t('c-w','caller','py-reference',True),t('c-b0','caller','py-reference'),t('k-b0','kernel','py-reference'),t('t-b0','caller','py-threads',workers=2),
            dict(t('pn-b0','caller','py-reference'),tier='tiny',**panel_keys(5))]
    def o(tr,phase='caller',**extra):
        r={'schema_version':1,'run_id':RID,'trial_id':tr['trial_id'],'block':tr['block'],'order':0,'point':'p','scope':tr['scope'],'mode':'warm','variant':tr['variant'],
           'workers':tr['workers'],'tier':'small','phase':phase,'warmup':tr['warmup'],'eligible':True,'loops':1,'work_units':POLICY['sizes']['small'],'wall_ns':10000,
           'cpu_usage_usec':9,'unavailable':{},'memory':None,'verdict':{'failures':{}},'phases':{}}
        r.update(extra);return r
    sizes=bpl.expected_chunk_sizes(POLICY['sizes']['small'],2,POLICY['pools']['request_limit'])
    pool={'max_pending':4,'window':4,'pids_distinct':1,'caller_pid_included':True,'start_method':'thread','chunk_rule':bpl.CHUNK_RULE,'chunk_sizes':sizes,
          'chunks':len(sizes),'chunk_wall_ns':[5]*len(sizes)}
    obs=[o(trials[0]),o(trials[1])]+[o(trials[2],phase='work') for _ in range(4)]+[o(trials[3],pool=pool)]
    obs+=[o(trials[4],tier='tiny',work_units=6*5,panel_passes=5)]
    phases=[{'run_id':RID,'trial_id':'k-b0','phase':'control-zero','scope':'kernel','variant':'py-reference','workers':'direct'},
            {'run_id':RID,'trial_id':'t-b0','phase':'pool_start','scope':'caller','variant':'py-threads','workers':2}]
    return trials,obs,phases,{}

def host_reasons(trials,obs,phases,timing,kernel=None):
    """The reasons that the synthetic run checks give for the same evidence: bench.run_status, bench_evidence.check_integrity,
    bench.check_native_timing and bench_guardrails.orphan_reasons."""
    import bench_evidence as be, bench_guardrails as bg
    ds={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':POLICY['sizes']['small']}
    p={'mode':'decision','sessions':[{'session':'s','trials':trials}],'memory':[],'pyperf':{'values':3,'warmups':1},'dataset':ds,'run_id':RID}
    out=bench.run_status(p,obs,phases,POLICY)[1]+be.check_integrity(p,{'run_id':RID,'dataset':ds},obs+phases,POLICY)
    out+=bench.check_native_timing(obs,POLICY,kernel)+bg.orphan_reasons((timing or {}).get('deadline_kills') or [])
    return out

def local_counts(bc,trials,obs,phases,timing,native=None):
    plan={'run_id':RID,'trials':trials,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1},**(native or {})}
    failed=bc.native_timing_failures(obs,plan,ROOT/'safety/performance-policy.json')
    return bc.local_rule_counts(plan,obs,phases,timing,failed,ROOT/'safety/performance-policy.json')

def _first(obs,tid):return next(o for o in obs if o['trial_id']==tid)

def host_plan(trials):
    """(plan, run record) of the synthetic run that host_reasons checks for `trials`."""
    ds={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':POLICY['sizes']['small']}
    return ({'mode':'decision','sessions':[{'session':'s','trials':trials}],'memory':[],'pyperf':{'values':3,'warmups':1},'dataset':ds,'run_id':RID},
            {'run_id':RID,'dataset':ds})

def with_panel(units,tier='tiny',passes=5,mode='warm',variant='py-reference',workers='direct',pool=None,start=False):
    """T5R1-A01: rule_evidence with one more single-record (panel) trial px-b0 of `tier`, L = `passes`, `mode`, `variant` and
    `workers` whose observation reports `units` work units (with `pool`, its pool identity; `start`, its pool start phase)."""
    tr,ob,ph,ti=rule_evidence()
    base=next(t for t in tr if t['trial_id']=='pn-b0')
    tr.append(dict(base,trial_id='px-b0',tier=tier,mode=mode,variant=variant,workers=workers,**panel_keys(passes)))
    ob.append(dict(_first(ob,'pn-b0'),trial_id='px-b0',tier=tier,mode=mode,variant=variant,workers=workers,work_units=units,panel_passes=passes,
                   **({'pool':pool} if pool is not None else {})))
    if start:ph.append({'run_id':RID,'trial_id':'px-b0','phase':'pool_start','scope':'caller','variant':variant,'workers':workers})
    return tr,ob,ph,ti

def _native(trials,obs,phases,timing):
    t={'trial_id':'n-b0','block':0,'order':0,'point':'p','scope':'kernel','mode':'direct','variant':'c-serial','workers':'direct','tier':'small','loops':1,'warmup':False}
    trials.append(t);obs.append(dict(_first(obs,'c-b0'),trial_id='n-b0',scope='kernel',mode='direct',variant='c-serial',phase='work',
                                      self_timing={'mono_ns':10**9,'cpu_ns':1},native_sha256=SHA))

RULE_CASES={       # rule: the edit of the clean evidence that breaks it
    'call-deadline':lambda tr,ob,ph,ti:_first(ob,'c-w').update(failure_reason='call-deadline',eligible=False,work_units=0),
    'trial-design':lambda tr,ob,ph,ti:ob.append(dict(_first(ob,'c-w'))),
    'missing-trial':lambda tr,ob,ph,ti:ob.remove(_first(ob,'c-b0')),
    'duplicate-rows':lambda tr,ob,ph,ti:ob.append(dict(_first(ob,'c-b0'))),
    'unplanned-row':lambda tr,ob,ph,ti:ob.append(dict(_first(ob,'c-b0'),trial_id='x-b0')),
    'cross-run':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(run_id='1'*32),
    'work-count':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(work_units=POLICY['sizes']['small']-1),
    'rows-dropped':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(verdict={'failures':{},'reduction':'ROW_COUNT'}),
    'pyperf-agreement':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(pyperf_wall_ns=10000+2000000),
    'control-zero':lambda tr,ob,ph,ti:ph.pop(0),
    'timed-launch':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(phase='pool_start'),
    'memory-in-timing':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(memory={'peak':1}),
    'metrics':lambda tr,ob,ph,ti:_first(ob,'c-b0').update(cpu_usage_usec=None),
    'caller-semantics':lambda tr,ob,ph,ti:ph.pop(1),
    'pool-identity':lambda tr,ob,ph,ti:_first(ob,'t-b0').update(pool=dict(_first(ob,'t-b0')['pool'],window=3)),
    'native-timing':_native,
    'orphans':lambda tr,ob,ph,ti:ti.update(deadline_kills=[{'trial_id':'c-b0','left':0,'foreign_orphans':1}])}

class RuleTests(Case):                  # T5-A02: the synthetic run rule set inside a local decision job
    NATIVE={'native':{'bd-kernel':SHA},'native_kernel':{'program':'bd-kernel'}}
    def test_the_rule_names_are_the_closed_schema_names(self):
        self.assertEqual(rule_names(),list(coordinator().LOCAL_RULES));self.assertEqual(sorted(RULE_CASES),sorted(rule_names()))
    def test_clean_evidence_breaks_no_rule_here_and_on_the_host(self):
        bc=coordinator();tr,ob,ph,ti=rule_evidence()
        self.assertEqual(host_reasons(tr,ob,ph,ti,SHA),[])
        self.assertEqual(local_counts(bc,tr,ob,ph,ti,self.NATIVE),{r:0 for r in bc.LOCAL_RULES})
    def test_each_rule_gives_the_validity_of_the_synthetic_run(self):
        """Parity: for every rule, the same evidence breaks the rule inside the job and makes the synthetic checks give a
        reason (an INVALID_EXPERIMENT run), so a local job is never VALID where a synthetic run is not."""
        bc=coordinator()
        for rule,edit in RULE_CASES.items():
            with self.subTest(rule):
                tr,ob,ph,ti=rule_evidence();edit(tr,ob,ph,ti)
                got=local_counts(bc,tr,ob,ph,ti,self.NATIVE)
                self.assertGreater(got[rule],0,got);self.assertTrue(host_reasons(tr,ob,ph,ti,SHA))
    def test_the_pyperf_rule_is_one_sided_here_and_on_the_host(self):
        """T6 item 5 (T5-A05): the in-job rule pyperf-agreement and the host check give the same answer for the recorded
        honest overheads (1,069,719 ns on a 31.65 ms wall; the largest of the 212 distinct honest trials, 1,661,031 ns,
        recorded on a 274.8 ms wall and applied here to the shortest recorded wall, 29,392,881 ns; T6-A01), the exact bounds
        and a forged self-timing above or far below the bracket, with the real policy file."""
        bc=coordinator()
        for wall,pyperf,broken in ((31650646,30580927,False),(29392881,29392881-1661031,False),(30000000,25000000,False),
                                   (30000000,24999999,True),(30000000,30001000,False),(30000000,30001001,True),(30000000,-1,True)):
            with self.subTest(wall=wall,pyperf=pyperf):
                tr,ob,ph,ti=rule_evidence();_first(ob,'k-b0').update(wall_ns=wall,pyperf_wall_ns=pyperf)
                got=local_counts(bc,tr,ob,ph,ti,self.NATIVE)
                self.assertEqual(got['pyperf-agreement'],int(broken),got)
                self.assertEqual(any(r.startswith('forged self-timing') for r in host_reasons(tr,ob,ph,ti,SHA)),broken)
    def test_a_single_record_trial_breaks_no_work_rule_here_and_on_the_host(self):
        """T5R1-A01: a single-record (panel) trial reports len(panel) x L x 1 work units (L passes of one one-row call per
        panel row), never the rows of its tier. Each of the three work rules accepts it: P07 bench.check_completeness, B15
        bench_evidence.check_integrity (`wrong work count`) and the in-job rule work-count; warm (L = 5) and cold (L = 1),
        on the tiny tier and on a non-tiny point (small)."""
        import bench_evidence as be
        bc=coordinator()
        for tier,passes,mode in (('tiny',5,'warm'),('tiny',1,'cold'),('small',5,'warm'),('small',8192,'warm')):
            tr,ob,ph,ti=with_panel(6*passes,tier=tier,passes=passes,mode=mode)
            p,run=host_plan(tr)
            with self.subTest(tier=tier,passes=passes,rule='P07 check_completeness'):
                self.assertEqual(bench.check_completeness(p,ob,POLICY),[])
            with self.subTest(tier=tier,passes=passes,rule='B15 check_integrity'):
                self.assertEqual([r for r in be.check_integrity(p,run,ob+ph,POLICY) if 'work count' in r],[])
            with self.subTest(tier=tier,passes=passes,rule='in-job work-count'):
                self.assertEqual(local_counts(bc,tr,ob,ph,ti,self.NATIVE)['work-count'],0)
            with self.subTest(tier=tier,passes=passes,rule='all rules'):
                self.assertEqual(host_reasons(tr,ob,ph,ti,SHA),[]);self.assertEqual(local_counts(bc,tr,ob,ph,ti,self.NATIVE),{r:0 for r in bc.LOCAL_RULES})
    def test_a_single_record_trial_with_other_work_breaks_the_work_rules_here_and_on_the_host(self):
        """T5R1-A01 (parity, broken): a dropped panel cell (25 of 30), a dropped pass (24), an extra call (31), zero work,
        one call only (1, the rows of the tiny tier) and the rows of a non-tiny tier (256) each break work-count inside the
        job and give the host reasons (P07 and B15 `wrong work count`): the rule is never weakened."""
        import bench_evidence as be
        bc=coordinator()
        for tier,units in (('tiny',25),('tiny',24),('tiny',31),('tiny',0),('tiny',POLICY['sizes']['tiny']),('small',POLICY['sizes']['small'])):
            with self.subTest(tier=tier,units=units):
                tr,ob,ph,ti=with_panel(units,tier=tier);p,run=host_plan(tr)
                self.assertEqual(local_counts(bc,tr,ob,ph,ti,self.NATIVE)['work-count'],1)          # px-b0 only: pn-b0 keeps its 30 units
                self.assertTrue([r for r in bench.check_completeness(p,ob,POLICY) if r.startswith('px-b0: ')])
                self.assertIn('wrong work count: px-b0',be.check_integrity(p,run,ob+ph,POLICY))
    def test_a_pooled_single_record_row_has_the_chunks_of_one_row_here_and_on_the_host(self):
        """T5R1-A01 with B10 (spec B10: a one-row request has one chunk): each pooled call of a single-record trial holds one
        row, so its pool identity (the last call's, benchlab.pools LAST_STATS) has one chunk of one row on a non-tiny point
        too; the chunks of the tier rows break pool-identity inside the job and B10 on the host."""
        import bench_plan as bpl
        bc=coordinator();limit=POLICY['pools']['request_limit']
        def pool(variant,sizes):
            if variant=='c-threads':return {'chunk_rule':bpl.CHUNK_RULE,'chunk_sizes':sizes,'chunks':len(sizes),'chunk_wall_ns':[5]*len(sizes)}
            return {'max_pending':len(sizes),'window':4,'pids_distinct':1,'caller_pid_included':variant=='py-threads','start_method':'thread' if variant=='py-threads' else 'spawn',
                    'chunk_rule':bpl.CHUNK_RULE,'chunk_sizes':sizes,'chunks':len(sizes),'chunk_wall_ns':[5]*len(sizes),
                    **({'tracker_session_setup':True} if variant=='py-processes' else {})}
        for variant in ('py-threads','py-processes','c-threads'):
            for sizes,broken in (([1],False),(bpl.expected_chunk_sizes(POLICY['sizes']['small'],2,limit),True)):
                with self.subTest(variant=variant,chunk_sizes=sizes):
                    tr,ob,ph,ti=with_panel(30,tier='small',variant=variant,workers=2,pool=pool(variant,sizes),start=variant in ('py-threads','py-processes'))
                    p,_=host_plan(tr)
                    self.assertEqual(local_counts(bc,tr,ob,ph,ti,self.NATIVE)['pool-identity'],int(broken))
                    self.assertEqual(bool([r for r in bench.check_concurrency_identity(ob,p,POLICY) if 'px-b0' in r]),broken)
                    self.assertEqual(bool(host_reasons(tr,ob,ph,ti,SHA)),broken)
    def test_an_unreadable_policy_fails_the_policy_rules(self):
        bc=coordinator();tr,ob,ph,ti=rule_evidence();_first(ob,'c-b0')['pyperf_wall_ns']=10000
        plan={'run_id':RID,'trials':tr,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1}}
        got=bc.local_rule_counts(plan,ob,ph,ti,set(),ROOT/'no-such-policy.json')
        self.assertEqual((got['pyperf-agreement'],got['pool-identity']),(1,1))
    def test_a_warmup_killed_at_its_call_deadline_makes_the_job_invalid(self):
        """G2.6 (the approver's example): a warmup trial killed at its call deadline left the job VALID before T5-R1."""
        bc=coordinator()
        with tempfile.TemporaryDirectory() as t:
            work=Path(t);bc.WORK=work;bc.CG=work;private=work/'bench/private/out';private.mkdir(parents=True);out=work/'bench/out';out.mkdir(parents=True)
            (work/'bench/private/reference.json').write_text('{}')
            trials=[trial('unit-p','py-reference',None,warmup=True,tier='tiny')]+[trial('unit-p','py-reference',b,tier='tiny') for b in range(3)]
            rows=[obs('unit-p','py-reference',t['block'],10.0,trial_id=t['trial_id'],units=1,tier='tiny',run_id='0'*32,phase='caller',unavailable={},memory=None,
                      warmup=t['warmup']) for t in trials]
            rows[0].update(failure_reason='call-deadline',eligible=False,work_units=0)
            def timing(plan,o):
                (o/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));return {'status':'PASS','children':[{'isolated':True}]}
            plan={'run_id':'0'*32,'case':'fixture-case','dataset':{'kind':'local','sha256':'a'*64},'rows':1,'decision':True,'reference_selector':'all','partial':True,
                  'trials':trials,'sizes':POLICY['sizes'],'pyperf':{'values':3,'warmups':1}}
            with mock.patch.object(bc,'job_timing',side_effect=timing),mock.patch.object(bc,'_manifest',return_value='/m.json'):
                result=bc._local_trials(plan,out,private,[],None)
            doc=json.loads((out/'aggregate.json').read_text());validate(ROOT,'bench-local-aggregate',doc)
            self.assertEqual((result['status'],doc['status'],doc['rules']['call-deadline']),('FAIL','INVALID_EXPERIMENT',1))
            self.assertTrue(all(r['eligible'] for r in doc['timings']))     # the timing rows alone looked valid
    def test_a_broken_rule_makes_the_local_run_invalid(self):
        zero={r:0 for r in rule_names()}
        make=lambda j,label:aggregate_for(j,rules=dict(zero,**{'pyperf-agreement':2}),status='INVALID_EXPERIMENT') if label=='local-s-a' else aggregate_for(j)
        rc,run,d,_=run_local([session('s-a',UNIT),session('s-b',UNIT)],make=make)
        m=json.loads((d/'local-merged.json').read_text())
        self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('rules-failed',m['problems'])
        self.assertIn('job s-a: rule pyperf-agreement broken by 2 trials',run['reasons'])
        def without(j,label):
            d=aggregate_for(j);d.pop('rules');return d
        rc,run,d,_=run_local([session('s-a',UNIT)],make=without)
        self.assertEqual(run['status'],'INVALID_EXPERIMENT');self.assertIn('rules-failed',json.loads((d/'local-merged.json').read_text())['problems'])
        self.assertIn('job s-a: aggregate lacks the rule counts',run['reasons'])

class PanelWorkTests(Case):             # T5R1-A01: one definition of the planned work of a trial
    def test_the_host_rules_and_the_job_rules_use_one_definition(self):
        """container/bench_trial_work.py defines the planned work of a trial once (standard library only, no import):
        tools/bench_plan.py loads that file by its path for the host rules (P07 bench.check_completeness, B15
        bench_evidence.check_integrity, B10 bench_plan.b10_row_count), and the coordinator imports the same file for the
        rules work-count and pool-identity of a local decision job."""
        import ast, inspect, bench_plan as bpl, bench_evidence as be
        bc=coordinator();path=(ROOT/'container/bench_trial_work.py').resolve()
        self.assertEqual(Path(bpl.trial_work.__file__).resolve(),path);self.assertEqual(Path(bc._trial_work.__file__).resolve(),path)
        self.assertEqual([n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,(ast.Import,ast.ImportFrom))],[])
        for fn in (bench.check_completeness,be.check_integrity,bc.local_rule_counts):
            with self.subTest(rule=fn.__name__):self.assertIn('planned_work_units(',inspect.getsource(fn))
        self.assertIn('request_rows(',inspect.getsource(bpl.b10_row_count));self.assertIn('request_rows(',inspect.getsource(bc.local_rule_counts))
    def test_the_planned_work_of_a_trial(self):
        """A single-record (panel) trial: len(panel) x panel_passes x 1 (one row per call), whatever its tier; a capacity
        trial: the tier rows of every request of every client; any other trial: its tier rows; a malformed plan row: None
        (no count equals it). B10: a pooled call of a single-record trial holds one row."""
        import bench_plan as bpl
        bc=coordinator();sizes=POLICY['sizes']
        tier=lambda name:{'trial_id':'t','scope':'caller','tier':name}
        panel=lambda passes,rows=6:dict(tier('tiny'),**dict(panel_keys(passes),panel=list(range(rows))))
        cases=[(tier('tiny'),sizes['tiny']),(tier('small'),sizes['small']),(tier('large'),sizes['large']),
               (panel(5),30),(panel(1),6),(panel(8192),6*8192),(panel(3,rows=1),3),(dict(panel(5),tier='small'),30),
               ({'trial_id':'c','scope':'capacity','tier':'small','clients':4,'requests_per_client':8},sizes['small']*32),
               (dict(panel(5),panel_passes=0),None),(dict(panel(5),panel_passes=True),None),(dict(panel(5),panel_passes='5'),None),
               (dict(panel(5),panel=[]),None),(dict(panel(5),panel=None),None),(tier('no-such-tier'),None),(tier(None),None)]
        for t,want in cases:
            with self.subTest(trial=t):
                self.assertEqual(bpl.planned_work_units(t,sizes),want);self.assertEqual(bc._trial_work.planned_work_units(t,sizes),want)
        synthetic={'dataset':{'kind':'synthetic'}};local={'dataset':{'kind':'local','rows':1000}}
        self.assertEqual([bpl.b10_row_count(p,t,POLICY) for p in (synthetic,local) for t in (tier('small'),panel(5),dict(panel(5),tier='small'))],
                         [sizes['small'],1,1,1000,1,1])
        self.assertEqual((bpl.PANEL_ROWS_PER_CALL,bc._trial_work.PANEL_ROWS_PER_CALL),(1,1))

class CheckRecordTests(Case):           # T5-A06
    def test_each_job_keeps_its_artifact_directory_check_record(self):
        _,run,_,_=run_local([session('s-a',UNIT),session('s-b',UNIT),session('s-c',CTRL)])
        jobs=run['evidence']['jobs'];self.assertEqual(len(jobs),len(set(jobs)))
        for name in ('s-a','s-b','s-c'):self.assertIn(f'evidence/0003-local-check-{name}.json',jobs)

class AdmissionTests(Case):             # T5-A07: reference_admit_excluded is compared within one selector
    def merged(self,sessions,blocks):
        jobs=bl().local_jobs(plan(sessions),POLICY)
        docs={j['name']:aggregate_for(dict(j,run_id='0'*32,case='fixture-case',dataset={'sha256':'a'*64},reference_selector=j['selector']),
                                      reference_admit_excluded=blocks[j['name']]) for j in jobs}
        return merged_of(docs,jobs)
    def test_a_selector_dependent_count_gives_no_false_counts_differ(self):
        one=lambda name,sel:session(name,[('unit-'+sel,'py-reference',sel,sel+'/full-dataset')])
        a={'row':1,'brent':0,'bump':0};b={'row':5,'brent':2,'bump':0}
        m=self.merged([session('s-all',UNIT),one('s-1','s1')],{'s-all':a,'s-1':b})
        self.assertEqual((m['status'],m['problems'],m['reference_admit_excluded']),('VALID',[],a))       # the `all` block is the run's block
        m=self.merged([one('s-2','s2'),one('s-1','s1')],{'s-2':b,'s-1':a})
        self.assertEqual((m['status'],m['reference_admit_excluded']),('VALID',a))                         # else the first selector in sorted order
        m=self.merged([one('s-1','s1'),one('s-3','s1')],{'s-1':a,'s-3':b})
        self.assertIn('counts-differ',m['problems'])                                                      # one selector: the blocks must be equal

LOCAL={'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None}

class LocalEstimateTests(Case):          # T5-A08 (EX19-LOCAL-ESTIMATE-01): the reference work of every local job
    def test_a_local_plan_counts_the_reference_work_of_every_session(self):
        import test_bench_windows as tw, bench_windows as bw
        doc=tw.pdoc();case=tw.wcase()
        p=tw.bp.build_plan(case,doc,mode='decision',dataset=dict(LOCAL),seed=3,envelope=tw.ENV4,calibration=dict(tw.CAL),calibration_source=dict(tw.SOURCE),
                           unit_policy=tw.WPOL,calibration_observations=tw.REF_OBS)
        m=p['measured_reference'];gs=bw.groups(p,tw.WPOL,doc,dict(tw.CAL),case);by={s['session']:s for s in p['sessions']}
        self.assertTrue(gs)
        for g in gs:
            self.assertEqual(g['reference'],0.0)                     # no shared reference batch in a local window
            for s in g['sessions']:
                with self.subTest(session=s['id']):
                    own=bw.local_reference_seconds(by[s['id']]['trials'],case,tw.WPOL,doc,dict(tw.CAL),m);self.assertGreater(own,0.0)
                    self.assertEqual(s['seconds'],bw.session_seconds(by[s['id']],doc,dict(tw.CAL),p['dataset'],m)+own)
        for w in p['windows']:
            self.assertTrue(all(part['reference']==0.0 for part in w['parts']))
            self.assertAlmostEqual(w['estimate'],w['e_ctrl']+sum(x['seconds'] for g in gs for x in g['sessions'] if x['id'] in w['sessions']),places=6)
        win=p['windows'][0];unit=next(u for u in win['units'] if u.endswith('/full-dataset'))
        x=bw.extension_run_plan(p,win['id'],[unit],case,tw.WPOL,doc)
        shifted=[bw._shifted(by[sid],bw.EXTENSION_OFFSET,p['seed']) for sid in win['sessions'] if unit in {t.get('unit') for t in by[sid]['trials']}]
        want=(bw.e_ctrl(doc,dict(tw.CAL),case,tw.WPOL,len(shifted))+sum(bw.session_seconds(s,doc,dict(tw.CAL),p['dataset'],m) for s in shifted)
              +sum(bw.local_reference_seconds(s['trials'],case,tw.WPOL,doc,dict(tw.CAL),m) for s in shifted))     # the sessions before their control trials
        self.assertAlmostEqual(x['estimate_seconds'],want,places=6)
    def test_the_job_rows_selector_and_batches_of_a_session(self):
        import test_bench_windows as tw, bench_windows as bw
        case=tw.wcase();doc=tw.pdoc();m={'batch':{'ma':0.5,'mb':0.25},'panel':{}}
        unit=[{'tier':'large','selector':'ma'}]                     # with the control rows (selector all, small): the `all` reference over the large rows
        self.assertEqual(bw.local_reference_seconds(unit,case,tw.WPOL,doc,None,m),2*doc['sizes']['large']*0.75)
        panel=[{'tier':'large','selector':'ma','panel':[0]}]         # a panel trial reads synthetic rows: the control rows give the job rows
        self.assertEqual(bw.local_reference_seconds(panel,case,tw.WPOL,doc,None,m),2*doc['sizes']['small']*0.75)
        own=dict(case,points=[dict(p,selector='ma') if p['name']=='baseline' else p for p in case['points']])    # controls of the unit's selector
        self.assertEqual(bw.local_reference_seconds(unit,own,tw.WPOL,doc,None,m),2*doc['sizes']['large']*0.5)
        with self.assertRaises(bw.PlanRefusal) as e:bw.local_reference_seconds(unit,case,tw.WPOL,doc,None,{'batch':{'ma':0.5},'panel':{}})
        self.assertEqual(e.exception.reason,'reference-not-measured')
    def test_the_packing_of_a_local_plan_reserves_the_reference_work(self):
        """The synthetic packing fixture fits one block, its warmup set and the session controls exactly in the cap; a local
        plan also needs the reference work of the session's job, so the same point refuses (one block cannot move)."""
        import test_bench_windows as tw, bench_windows as bw
        with self.assertRaises(bw.PlanRefusal) as e:
            tw.bp.build_plan(tw.pack_case(),tw.pdoc(ma=2.0),mode='decision',dataset=dict(LOCAL),seed=3,envelope=tw.ENV4,calibration=dict(tw.CALP),
                             calibration_source=dict(tw.SOURCE),unit_policy=tw.PPOL,calibration_observations=[tw.obs_row('unit-ma-full','py-reference','ma',0.125)])
        own=bw.local_reference_seconds([{'tier':'tiny','selector':'ma'}],tw.pack_case(),tw.PPOL,tw.pdoc(ma=2.0),dict(tw.CALP),{'batch':{'ma':0.125},'panel':{}})
        self.assertEqual((e.exception.reason,e.exception.estimates[0]['estimate']),('session-cap-infeasible',10800.0+own))
        self.assertTrue(tw.pack_plan(dict(tw.CALP))['windows'])        # the synthetic plan is unchanged

def local_version(case,pol,doc,sha):
    """A digest-bound window plan version of `case` and the window policy `pol` on a local dataset (the build of bench plan)."""
    import test_bench_windows as tw
    return tw.bp.build_plan(case,doc,mode='decision',dataset=dict(LOCAL,sha256=sha),seed=3,envelope=tw.ENV4,calibration=dict(tw.CAL),
                            calibration_source=dict(tw.SOURCE),unit_policy=pol,calibration_observations=tw.REF_OBS,project_dir=FIXTURE)

def fake_version(windows):
    """A digest-bound plan version with the look-1 windows `windows` (the fields that the window chain reads)."""
    v={'schema_version':1,'plan_version':'v1','case':CASE['case_id'],'mode':'decision','policy':'local-window-units','dataset':dict(LOCAL),
       'windows':[{'id':w,'sessions':[],'units':[]} for w in windows],'sessions':[]}
    v['plan_id']=bench.plan_digest(v);return v

def next_window(root,v,wid):
    """(refusal, window) of the next attempt of window `wid`, as bench run --plan PATH --window ID computes them."""
    import bench_windows as bw
    ch=bw.chain(root,v['plan_id'])
    return bw.window_refusal(ch,v,wid),{'window':wid,'attempt':bw.next_attempt(ch,wid),'window_plan_id':v['plan_id'],'extends':bw.extends_of(ch,v,wid),
                                        'version':v,'extension_of':None,'look1':None}

BLOCK=lambda j,label:aggregate_for(j,rows_kw={'pressure':lambda point,b:None if point=='control-base-a' and b==4 else 5})
CONFIRMED={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}

class LocalWindowChainTests(Case):      # T5-A03: the window chain of local attempts beyond attempt 1 of window 1a
    def test_a_second_local_window_extends_the_first(self):
        import bench_windows as bw
        root=temp_root();v=fake_version(('1a','1b'))
        why,w=next_window(root,v,'1a');self.assertIsNone(why)
        _,a,_,_=run_local([session('w-s00',UNIT+CTRL)],window=w,root=root)
        why,w=next_window(root,v,'1b');self.assertIsNone(why);self.assertEqual((w['attempt'],w['extends']),(1,bw.record_digest(a)))
        rc,b,d,_=run_local([session('w-s01',UNIT+CTRL)],window=w,root=root)
        self.assertEqual((rc,b['extends'],json.loads((d/'local-merged.json').read_text())['window']['extends']),(0,a['run_record_sha256'],a['run_record_sha256']))
        ch=bw.chain(root,v['plan_id'])
        self.assertEqual(ch['positions'],{'1a':a['run_record_sha256'],'1b':b['run_record_sha256']});self.assertEqual(bw.chain_problems(ch,['1a','1b'],set()),[])
    def test_a_blocked_local_attempt_runs_again(self):
        import bench_windows as bw
        root=temp_root();v=fake_version(('1a',))
        _,w=next_window(root,v,'1a');rc,first,_,_=run_local([session('w-s00',UNIT+CTRL)],window=w,root=root,make=BLOCK)
        self.assertEqual((rc,first['attempt_outcome']['status']),(2,'BLOCKED'))
        why,w=next_window(root,v,'1a');self.assertIsNone(why);self.assertEqual((w['attempt'],w['extends']),(2,None))
        rc,second,_,_=run_local([session('w-s00',UNIT+CTRL)],window=w,root=root)
        ch=bw.chain(root,v['plan_id'])
        self.assertEqual((rc,[a['attempt'] for a in ch['superseded']],ch['superseded_files']),(0,[1],{first['run_record_sha256']:True}))
        self.assertEqual(ch['positions'],{'1a':second['run_record_sha256']});self.assertEqual(bw.chain_problems(ch,['1a'],set()),[])
        self.assertIn('final attempt',next_window(root,v,'1a')[0])    # a final attempt is never run again
    def test_an_exhausted_local_window(self):
        import bench_windows as bw
        root=temp_root();v=fake_version(('1a','1b'))
        for k in (1,2,3):
            why,w=next_window(root,v,'1a');self.assertIsNone(why);self.assertEqual(w['attempt'],k)
            self.assertEqual(run_local([session('w-s00',UNIT+CTRL)],window=w,root=root,make=BLOCK)[0],2)
        why,_=next_window(root,v,'1a');self.assertEqual(why,'1a has 3 attempts (exhausted)')
        ch=bw.chain(root,v['plan_id']);self.assertEqual((ch['exhausted'],ch['positions']),(['1a'],{}))
        why,w=next_window(root,v,'1b');self.assertIsNone(why);self.assertEqual(w['extends'],None)     # the next window runs; nothing to extend
        _,b,_,_=run_local([session('w-s01',UNIT+CTRL)],window=w,root=root)
        self.assertEqual(bw.chain_problems(bw.chain(root,v['plan_id']),['1a','1b'],set()),[])
    def test_bench_run_extend_on_a_local_dataset_and_decide_over_the_local_chain(self):
        """bench run --extend RUN_ID --dataset local:PATH: the extension attempt of a PASS local look-1 attempt reaches the
        local runner with its window, extends, extension_of and the dataset path (never in the plan version); its local
        run joins the chain; decide (sensitivity confirmed) decides over the window chain of the local runs and writes local unit
        records."""
        import test_bench_windows as tw, bench_windows as bw, bench_evidence as be, bench_phase3_cli as cli
        root=temp_root();t=Path(tempfile.mkdtemp());ROOTS.append(t);data=t/'synthetic-local.bin';data.write_bytes(b'synthetic rows of the extend test')
        sha=hashlib.sha256(data.read_bytes()).hexdigest()
        case=tw.wcase();case['points']=[x for x in case['points'] if 'panel' not in x];pol=dict(tw.WPOL,units=['ma/full-dataset','mb/full-dataset']);doc=tw.pdoc()
        v=local_version(case,pol,doc,sha);self.assertEqual([w['id'] for w in v['windows']],['1a']);self.assertNotIn('path',v['dataset'])
        sub=bw.window_run_plan(v,'1a',case,pol,doc);sub['dataset']['path']=str(data);sub['pyperf']={'values':3,'warmups':1}
        win={'window':'1a','attempt':1,'window_plan_id':v['plan_id'],'extends':None,'version':v,'extension_of':None,'look1':None}
        rc,base,d,_=run_local(None,window=win,root=root,p=sub,case=case);self.assertEqual((rc,base['attempt_outcome']['status']),(0,'PASS'))
        (d/f"decision-{pol['name']}.json").write_text(json.dumps(tw.look1(v['plan_id']),sort_keys=True))
        be.bind_decisions(d,json.loads((d/'run.json').read_text()),[pol['name']])
        seen={}
        def fake(root,args,plan,case,policy,envelope=None,window=None):seen.update(plan=plan,window=window);return 0
        args=argparse.Namespace(case=case['case_id'],plan=None,window=None,extend=d.name,policy=None,project=None,dataset='local:'+str(data),mode='smoke',
                                calibrate=None,format='json',matrix=None)
        with mock.patch('bench.project_arg',return_value=None),mock.patch('bench_model.load_policy',return_value=doc),mock.patch('bench_model.load_case',return_value=case),\
             mock.patch('bench_model.case_rules'),mock.patch('bench.refuse_dropped_checks',return_value=None),mock.patch('bench_model.load_decision_policy',return_value=pol),\
             mock.patch('bench.verify_written_plan'),mock.patch('bench.native_run_declaration',return_value=None),mock.patch('bench_model.require_locked_selectors'),\
             mock.patch('bench.dataset_identity_reasons',return_value=[]),mock.patch('bench_privacy.run_local',side_effect=fake),\
             mock.patch('container_policy.choose_envelope',return_value=tw.ENV4),mock.patch('container_policy.host_topology',return_value=(None,None)),\
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bench.run_cmd(root,args),0)
        w=seen['window'];x=seen['plan']
        self.assertEqual((w['window'],w['attempt'],w['extends'],w['extension_of']['run_id'],w['extension_of']['units']),('2a',1,base['run_record_sha256'],d.name,['ma/full-dataset']))
        self.assertEqual((x['dataset']['path'],x['window']['id'],x['window']['look']),(str(data.resolve()),'2a',2));self.assertNotIn('path',w['version']['dataset'])
        x['project_dir']=FIXTURE
        rc,ext,d2,_=run_local(None,window=w,root=root,p=x,case=case)
        self.assertEqual((rc,ext['window'],ext['extension_of']['run_id']),(0,'2a',d.name));self.assertTrue((d2/'look1-decision.json').is_file())
        ch=bw.chain(root,v['plan_id']);self.assertEqual(sorted(ch['positions']),['1a','2a']);self.assertEqual(bw.chain_problems(ch,['1a'],{'1a'}),[])
        got={}
        def uev(*a,**k):
            got['observations']=k.get('observations');return copy.deepcopy(bw.UEV_FIXTURE)
        with mock.patch('bench_model.load_decision_policy',return_value=pol),mock.patch('bench_model.load_case',return_value=case),\
             mock.patch('bench_model.load_policy',return_value=doc),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
             mock.patch('policy.source_identity',return_value=('f'*64,None)),mock.patch('bench_decide._current_identity',return_value='f'*64),\
             mock.patch('bench_phase3_cli._sensitivity',return_value=CONFIRMED),mock.patch('bench_units.unit_evidence_from_run',side_effect=uev),\
             mock.patch('bench_phase3_cli._write_records') as write,contextlib.redirect_stdout(io.StringIO()):
            cli.decide_cmd(root,argparse.Namespace(run_id=d2.name,policy=pol['name'],format='json',ci_run_id=None,approval=[],sensitivity_confirmation='c.json',final=False))
        rec=write.call_args[0][1][0]
        self.assertEqual((rec['local'],sorted(u['unit'] for u in rec['units'])),(True,sorted(pol['units'])))
        self.assertEqual([(p['window'],p['status']) for p in rec['windows']['positions']],[('1a','PASS'),('2a','PASS')])
        blocks=sorted({o['block'] for o in got['observations'] if o.get('unit')=='ma/full-dataset'})
        self.assertEqual(blocks,list(range(24)))                     # the pooled look-1 and extension blocks of the local runs
    def test_a_local_window_with_a_single_record_unit_decides_from_the_in_job_rules(self):
        """T5R1-A02: a local window chain that keeps the single-record point of the case. Each fake redacted session applies
        the in-job rules of the coordinator (local_rule_counts, _local_timings) to the observations of its job's trials, the
        panel evidence included (job_observations: a single-record trial reports 6 x L work units, as benchlab/trial.py
        run_panel notes them). decide (sensitivity confirmed) then runs the real bench_units.unit_evidence_from_run and
        decide_units over the local window chain. Before the T5R1-A01 repair the rule work-count broke every single-record
        trial: the attempt was a FAIL position and no unit was decided."""
        import test_bench_windows as tw, bench_windows as bw, bench_phase3_cli as cli
        bc=coordinator();root=temp_root();t=Path(tempfile.mkdtemp());ROOTS.append(t)
        data=t/'synthetic-local.bin';data.write_bytes(b'synthetic rows of the single-record chain test');sha=hashlib.sha256(data.read_bytes()).hexdigest()
        case=tw.wcase();pol=copy.deepcopy(tw.WPOL);doc=dict(tw.pdoc(),panel_cells=list(PANEL_CELLS))      # the cells of the FIXTURE protocol
        self.assertIn('ma/single-record',pol['units']);self.assertTrue(any('panel' in x for x in case['points']))     # the single-record point stays
        v=local_version(case,pol,doc,sha);sub=bw.window_run_plan(v,'1a',case,pol,doc);sub['dataset']['path']=str(data);sub['pyperf']={'values':3,'warmups':1}
        self.assertTrue([x for s in sub['sessions'] for x in s['trials'] if 'panel' in x and x.get('unit')=='ma/single-record'])
        win={'window':'1a','attempt':1,'window_plan_id':v['plan_id'],'extends':None,'version':v,'extension_of':None,'look1':None}
        counts=[]
        def in_job(job,label):
            obs=job_observations(bc,job)
            rules=bc.local_rule_counts(job,obs,[],{'deadline_kills':[]},set(),ROOT/'safety/performance-policy.json');counts.append(rules)
            return aggregate_for(job,timings=bc._local_timings(obs),rules=rules,status='INVALID_EXPERIMENT' if any(rules.values()) else 'VALID')
        rc,run,d,_=run_local(None,window=win,root=root,p=sub,case=case,make=in_job)
        self.assertEqual((rc,run['status'],run['attempt_outcome']['status']),(0,'VALID','PASS'),run.get('reasons'))
        self.assertTrue(counts);self.assertEqual([{k:v for k,v in c.items() if v} for c in counts],[{}]*len(counts))
        with mock.patch('bench_model.load_decision_policy',return_value=pol),mock.patch('bench_model.load_case',return_value=case),\
             mock.patch('bench_model.load_policy',return_value=doc),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
             mock.patch('policy.source_identity',return_value=('f'*64,None)),mock.patch('bench_decide._current_identity',return_value='f'*64),\
             mock.patch('bench_phase3_cli._sensitivity',return_value=CONFIRMED),mock.patch('bench_units.coverage_record_ok',return_value=True),\
             mock.patch('bench_phase3_cli._write_records') as write,contextlib.redirect_stdout(io.StringIO()):
            cli.decide_cmd(root,argparse.Namespace(run_id=d.name,policy=pol['name'],format='json',ci_run_id=None,approval=[],sensitivity_confirmation='c.json',final=False))
        rec=write.call_args[0][1][0];one=next(u for u in rec['units'] if u['unit']=='ma/single-record')
        why=(one.get('verdict'),one.get('reason'),one.get('detail'),rec.get('reasons'))
        self.assertEqual((rec['local'],[(p['window'],p['status']) for p in rec['windows']['positions']]),(True,[('1a','PASS')]),why)
        self.assertEqual((one['verdict'],one['reason'],one['rows_per_request'],one['k_pi']),('KEEP_PYTHON','python-under-threshold',1,2),why)
        self.assertAlmostEqual(one['H_pi']['value_ms'],0.6)          # the worst panel cell: 600 us per one-row call, every block

class LocalDecideTests(Case):           # T5-A03: decide_owner with the sensitivity confirmed over a local run
    def test_a_unit_threshold_policy_decides_a_local_run(self):
        import bench_phase3_cli as cli, bench_windows as bw
        pol=dict(bm.engine_unit_policy(ROOT),name='local-units')
        rc,run,d,_=run_local([session('s-a',[('unit-m1','py-reference','m1','m1/full-dataset'),('unit-m1','py-optimized','m1','m1/full-dataset')])])
        self.assertEqual(rc,0);got={}
        def uev(*a,**k):
            got['observations']=k.get('observations');return copy.deepcopy(bw.UEV_FIXTURE)
        with mock.patch('bench_model.load_decision_policy',return_value=pol),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
             mock.patch('policy.source_identity',return_value=('f'*64,None)),mock.patch('bench_decide._current_identity',return_value='f'*64),\
             mock.patch('bench_phase3_cli._sensitivity',return_value=CONFIRMED),mock.patch('bench_units.unit_evidence_from_run',side_effect=uev),\
             mock.patch('bench_phase3_cli._write_records') as write,contextlib.redirect_stdout(io.StringIO()):
            cli.decide_cmd(d.parent.parent.parent,argparse.Namespace(run_id=d.name,policy='local-units',format='json',ci_run_id=None,approval=[],
                                                                     sensitivity_confirmation='c.json',final=False))
        rec=write.call_args[0][1][0]
        self.assertEqual((rec['local'],len(rec['units'])),(True,len(pol['units'])))
        self.assertEqual(got['observations'],bl().run_observations(d,json.loads((d/'plan.json').read_text()),d.parent.parent.parent))
        self.assertEqual({o['unit'] for o in got['observations']},{'m1/full-dataset'})

if __name__=='__main__':unittest.main()
