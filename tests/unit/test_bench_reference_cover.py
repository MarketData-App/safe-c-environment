"""R48 (T6-R6, rulings R48 and R51): the reference of a run, and of a local job, covers the models of every selector that
the plan (or the job) holds, through the optional adapter hook reference_cover(data, selectors); an adapter without the
hook keeps the reference of its reference selector. Synthetic inputs only: a stand-in adapter whose `all` selector
computes two of four models, so a caller row of a third selector validates only against a reference that covers it. The
host builds the job plans (bench run with fake sessions, the local decision runner with fake redacted sessions); the
coordinator computes the reference in a real child with the stand-in adapter; each caller row validates as benchlab.trial
validates it (slice, slice_result, validate, verdict_fields or malformed_verdict)."""
import copy, hashlib, importlib.util, json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
BENCHLAB=str(ROOT/'benchmarks/performance/python')
for _p in (str(ROOT/'tools'),str(ROOT/'tests/unit'),BENCHLAB):
    if _p not in sys.path:sys.path.insert(0,_p)
import bench, bench_model as bm, bench_plan as bp
import test_bench_local_decision as tld

POLICY=bm.load_policy(ROOT)
MODULE='refcover_standin'
STANDIN=r'''
import hashlib, json
MODELS={'all':('m1','m2'),'m1':('m1',),'m2':('m2',),'m3':('m3',),'m4':('m4',)}
WEIGHT={'m1':1,'m2':2,'m3':3,'m4':4}
class Plain:
    """No reference_cover hook: the reference holds the models of its own selector only."""
    def __init__(self,params,selector='all'):self.models=MODELS[selector]
    def synthesize(self,rows,seed):return json.dumps([(seed+i)%97 for i in range(rows)]).encode()
    def load(self,ref):
        with open(ref['path'],'rb') as f:return json.loads(f.read())
    def slice(self,data,n):return data[:n]
    def prepare(self,data,variant,workers=1):return data
    def compute(self,data,models):return {m:[x*WEIGHT[m] for x in data] for m in models}
    def run(self,prepared,variant,workers,pool=None):return self.compute(prepared,self.models)
    def materialize(self,raw):return raw
    def work_units(self,result):return min(len(v) for v in result.values())
    def reference(self,data):return self.compute(data,self.models)
    def slice_result(self,result,n,data):return {m:v[:n] for m,v in result.items()}
    def validate(self,result,reference,data):
        if any(m not in reference for m in self.models):raise ValueError('the reference lacks a selected model')
        bad=sum(1 for m in self.models for a,b in zip(result[m],reference[m]) if a!=b)
        return {'eligible':bad==0,'failures':{'verdict':bad} if bad else {}}
    def digest(self,result):return hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
class Cover(Plain):
    """The optional hook: one reference with the union of the models of the listed selectors."""
    def reference_cover(self,data,selectors):return self.compute(data,sorted({m for s in selectors for m in MODELS[s]}))
'''
ROWS=8

def case(adapter):
    return {'schema_version':1,'case_id':'cover-standin','version':1,'kind':'function','adapter':f'{MODULE}:{adapter}',
            'parameters':{'seed':{'value':11,'label':'protocol'}},'selectors':['all','m1','m2','m3','m4'],
            'variants':[{'id':'py-reference','language':'python','workers':['direct'],'status':'implemented'}]}

def coordinator():
    spec=importlib.util.spec_from_file_location('bench_coordinator_cover',ROOT/'container/bench-coordinator.py')
    bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);return bc

def sha(data):return hashlib.sha256(data).hexdigest()

class Standin(unittest.TestCase):
    """A temporary directory with the stand-in module and the coordinator, whose work directory and child import path
    point there (the child gets benchlab and the stand-in module only)."""
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.tmp,True)
        mod=self.tmp/'mod';mod.mkdir();(mod/f'{MODULE}.py').write_text(STANDIN)
        self.work=self.tmp/'work';self.work.mkdir()
        self.bc=coordinator();self.bc.WORK=self.work;self.bc.PYTHONPATH=BENCHLAB+':'+str(mod)
        sys.path.insert(0,str(mod));sys.modules.pop(MODULE,None)
        self.addCleanup(lambda:(sys.path.remove(str(mod)),sys.modules.pop(MODULE,None)))
    def manifest(self,adapter):
        p=self.tmp/f'{adapter}.json';p.write_text(json.dumps(case(adapter)));return str(p)
    def reference_job(self,adapter,**extra):
        """The coordinator's reference job of a synthetic run (job_reference: the dataset and the reference child run for
        real); returns (job row, the reference file of the job's output)."""
        out=self.tmp/'out';out.mkdir(exist_ok=True)
        plan={'job':'reference','dataset':{'kind':'synthetic','seed':11},'rows':ROWS,'sizes':POLICY['sizes'],'deadline_seconds':120,**extra}
        with mock.patch.object(self.bc,'_manifest',return_value=self.manifest(adapter)):row=self.bc.job_reference(plan,out)
        return row,out/'reference.json'
    def local_dataset(self,rows):
        """A synthetic local dataset file of the stand-in adapter (the dataset of a local job in these tests)."""
        p=self.tmp/'local.bin';p.write_bytes(json.dumps([(11+i)%97 for i in range(rows)]).encode());return {'path':str(p),'sha256':sha(p.read_bytes())}
    def caller_verdict(self,adapter,selector,reference,dataset,rows=ROWS):
        """The verdict fields of one caller row of `selector`, validated as benchlab.trial validates a caller result."""
        from benchlab.workload import load_case_adapter
        from benchlab.trial import malformed_verdict, verdict_fields
        a=load_case_adapter(case(adapter),selector=selector);sub=a.slice(a.load(dataset),rows)
        ref=a.slice_result(json.loads(Path(reference).read_text()),rows,sub)
        result=a.materialize(a.run(a.prepare(sub,'py-reference',1),'py-reference',1))
        try:return verdict_fields(a.validate(result,ref,sub))
        except ValueError as error:return malformed_verdict(error)
    def run_dataset(self):return {'path':str(self.work/'bench/data/dataset'),'sha256':None}

class SyntheticRunReferenceTests(Standin):
    """Defect 1: the reference job of a synthetic run computes one reference for the plan's selectors (one digest)."""
    def test_a_row_of_a_selector_outside_all_validates_against_the_run_reference(self):
        row,ref=self.reference_job('Cover',reference_selectors=['all','m3'])
        self.assertEqual(row['status'],'PASS')
        self.assertTrue(self.caller_verdict('Cover','m3',ref,self.run_dataset())['eligible'])
        self.assertTrue(self.caller_verdict('Cover','all',ref,self.run_dataset())['eligible'])
        self.assertEqual(row.get('reference_selectors'),['all','m3'])
        self.assertEqual(row['reference_sha256'],sha(ref.read_bytes()))
        # the cost grows only by the planned models: m4 is declared by the case, but no trial plans it
        self.assertEqual(sorted(json.loads(ref.read_text())),['m1','m2','m3'])
    def test_the_cover_holds_the_listed_selectors_only(self):
        row,ref=self.reference_job('Cover',reference_selectors=['m3','m4'])
        self.assertEqual(sorted(json.loads(ref.read_text())),['m3','m4']);self.assertEqual(row.get('reference_selectors'),['m3','m4'])
        self.assertTrue(self.caller_verdict('Cover','m4',ref,self.run_dataset())['eligible'])
        self.assertFalse(self.caller_verdict('Cover','all',ref,self.run_dataset())['eligible'])     # `all` is not planned: not covered
    def test_an_adapter_without_the_hook_keeps_the_reference_of_all(self):
        row,ref=self.reference_job('Plain',reference_selectors=['all','m3']);data=ref.read_bytes()
        self.assertEqual(row['status'],'PASS');self.assertNotIn('reference_selectors',row)
        base_row,base_ref=self.reference_job('Plain')
        self.assertEqual((data,row['reference_sha256']),(base_ref.read_bytes(),base_row['reference_sha256']))
        self.assertEqual(sorted(json.loads(data)),['m1','m2'])
        v=self.caller_verdict('Plain','m3',ref,self.run_dataset())
        self.assertEqual((v['eligible'],v['failures'],v.get('verdict_error')),(False,{'verdict':1},'ValueError'))
        self.assertTrue(self.caller_verdict('Plain','all',ref,self.run_dataset())['eligible'])
    def test_a_plan_without_the_list_keeps_the_reference_child_argv(self):
        seen=[]
        plan={'job':'reference','dataset':{'kind':'synthetic','seed':11},'rows':ROWS,'sizes':POLICY['sizes'],'deadline_seconds':120}
        with mock.patch.object(self.bc,'run_deadline',side_effect=lambda argv,*a,**k:seen.append(argv)),mock.patch.object(self.bc,'_manifest',return_value='/m.json'):
            self.bc.reference_path(plan,{'path':'/d','sha256':'a'*64})
            self.bc.reference_path(dict(plan,reference_selectors=['all','m3']),{'path':'/d','sha256':'a'*64})
        self.assertEqual(seen[0][-1],'all')
        self.assertEqual(seen[1][:-1],seen[0]);self.assertEqual(json.loads(seen[1][-1]),['all','m3'])
    def test_a_malformed_selector_list_is_refused_before_the_child(self):
        plan={'job':'reference','dataset':{'kind':'synthetic','seed':11},'rows':ROWS,'sizes':POLICY['sizes'],'deadline_seconds':120}
        for bad in ('all',[],['m3','all'],['all','all'],['all','Bad Selector'],['all',3],[f's{i:02d}' for i in range(17)],None):
            with self.subTest(bad=bad),mock.patch.object(self.bc,'run_deadline',side_effect=AssertionError('a child started')),\
                 mock.patch.object(self.bc,'_manifest',return_value='/m.json'),self.assertRaises(ValueError):
                self.bc.reference_path(dict(plan,reference_selectors=bad),{'path':'/d','sha256':'a'*64})
    def test_a_selector_that_the_case_does_not_declare_stops_the_reference_child(self):
        with self.assertRaises(subprocess.CalledProcessError):self.reference_job('Cover',reference_selectors=['all','m9'])
        self.assertFalse((self.tmp/'out/reference.json').exists())

class NoCrossUseTests(Standin):
    """A restored run reference with a bound selector list refuses a job that holds a trial of another selector; the
    digest check of a restored reference is unchanged."""
    def restored(self,body=b'{"m1":[1],"m2":[2],"m3":[3]}'):
        p=self.work/'bench/private/reference.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body);return sha(body)
    def plan(self,digest,selectors,covered=('all','m3')):
        return {'job':'timing','dataset':{'kind':'synthetic','seed':11},'rows':ROWS,'sizes':POLICY['sizes'],'deadline_seconds':120,'reference_sha256':digest,
                'reference_selectors':list(covered),'trials':[{'trial_id':f't{n}',**({} if s is None else {'selector':s})} for n,s in enumerate(selectors)]}
    def test_a_trial_outside_the_bound_selectors_is_refused(self):
        digest=self.restored()
        with self.assertRaisesRegex(ValueError,'a trial selector outside the run reference'):self.bc.reference_path(self.plan(digest,['all','m4']),{})
        with self.assertRaisesRegex(ValueError,'a trial selector outside the run reference'):self.bc.reference_path(self.plan(digest,[None],covered=('m3',)),{})
        target=str(self.work/'bench/private/reference.json')
        self.assertEqual(self.bc.reference_path(self.plan(digest,['all','m3',None]),{}),target)       # a trial without a selector is `all`
        unbound=self.plan(digest,['m4']);unbound.pop('reference_selectors')        # no bound list (no hook): today's restore
        self.assertEqual(self.bc.reference_path(unbound,{}),target)
    def test_a_trial_of_another_selector_never_validates_against_the_cover_of_the_plan(self):
        row,ref=self.reference_job('Cover',reference_selectors=['all','m3'])
        v=self.caller_verdict('Cover','m4',ref,self.run_dataset())
        self.assertEqual((v['eligible'],v.get('verdict_error')),(False,'ValueError'))
        dst=self.work/'bench/private/reference.json';dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(ref.read_bytes())
        with self.assertRaisesRegex(ValueError,'a trial selector outside the run reference'):
            self.bc.reference_path(self.plan(row['reference_sha256'],['all','m3','m4']),{})
    def test_a_tampered_restored_reference_still_refuses(self):
        digest=self.restored();p=self.work/'bench/private/reference.json'
        p.write_bytes(b'{"m1":[1],"m2":[2],"m3":[4]}')
        with self.assertRaisesRegex(ValueError,'restored reference digest mismatch'):self.bc.reference_path(self.plan(digest,['all','m3']),{})
        p.unlink()
        with self.assertRaisesRegex(ValueError,'restored reference digest mismatch'):self.bc.reference_path(self.plan(digest,['all']),{})
    def test_a_malformed_bound_list_is_refused(self):
        digest=self.restored()
        for bad in ('all',[],['m3','all'],['all','Bad Selector']):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.bc.reference_path(dict(self.plan(digest,['all']),reference_selectors=bad),{})

import test_bench_accounting as ta

class CaptureSession(ta.FakeSession):
    """The fake BenchSession of test_bench_accounting; it keeps every job plan, and a reference job row reports `cover`
    as the selectors that its reference covers (None: the row reports none, as for an adapter without the hook)."""
    plans=[];cover=None
    def job(self,plan,label,timeout,restore=()):
        CaptureSession.plans.append(copy.deepcopy(plan));r=super().job(plan,label,timeout,restore)
        if plan['job']=='reference' and CaptureSession.cover is not None:
            row=json.loads(r['output']);row['reference_selectors']=CaptureSession.cover;r['output']=json.dumps(row)
        return r

class HostRunTests(unittest.TestCase):
    """bench run: the reference job plan holds the planned selectors (only when a selector other than `all` is planned),
    and every timing and capacity job plan holds the list that the reference job reports, when it equals the request."""
    def run_capture(self,selector=None,cover=None):
        real=bp.build_plan;made={}
        def build(*a,**k):
            plan=real(*a,**k)
            if selector is not None:
                for t in plan['sessions'][0]['trials']:t['selector']=selector
            made['plan']=copy.deepcopy(plan);return plan
        CaptureSession.plans=[];CaptureSession.cover=cover
        with mock.patch.object(ta,'FakeSession',CaptureSession),mock.patch.object(bp,'build_plan',build):
            code,run=ta.run_with(lambda name,trials:ta.session_config(len(name),trials))
        return code,run,made['plan'],list(CaptureSession.plans)
    @staticmethod
    def planned(plan):
        return sorted({t.get('selector','all') for s in plan['sessions'] for t in s['trials']}|({'all'} if plan.get('capacity') else set()))
    def test_the_reference_job_gets_the_planned_selectors_and_each_job_the_bound_list(self):
        _,run,plan,plans=self.run_capture(selector='hang',cover=None)
        want=self.planned(plan);self.assertIn('hang',want)
        ref=[p for p in plans if p['job']=='reference']
        self.assertEqual(len(ref),1);self.assertEqual(ref[0].get('reference_selectors'),want)
        self.assertEqual(bench.reference_selectors(plan),want)
        # the reference job reports no covered list (no hook): the jobs restore the reference without a bound list
        self.assertTrue([p for p in plans if p['job']=='timing'])
        self.assertTrue(all('reference_selectors' not in p for p in plans if p['job']!='reference'))
        _,run,plan,plans=self.run_capture(selector='hang',cover=want)
        jobs=[p for p in plans if p['job'] in ('timing','capacity')]
        self.assertTrue(jobs);self.assertTrue(all(p.get('reference_selectors')==want and p.get('reference_sha256') for p in jobs))
        self.assertNotIn('reference job failed',run['reasons'])
    def test_a_plan_of_selector_all_only_keeps_its_reference_job(self):
        _,run,plan,plans=self.run_capture()
        self.assertEqual(self.planned(plan),['all']);self.assertEqual(bench.reference_selectors(plan),[])
        self.assertTrue(plans);self.assertTrue(all('reference_selectors' not in p for p in plans))
    def test_a_reference_job_that_covers_other_selectors_fails_the_run(self):
        for cover in (['all'],['all','hang','m9'],'all'):
            with self.subTest(cover=cover):
                _,run,plan,plans=self.run_capture(selector='hang',cover=cover)
                self.assertEqual([p['job'] for p in plans],['reference'])          # no timing, memory or capacity job ran
                self.assertIn('reference job failed',run['reasons']);self.assertEqual(run['status'],'INVALID_EXPERIMENT')
        _,run,plan,plans=self.run_capture(cover=['all'])        # a list for a plan that requested none
        self.assertEqual([p['job'] for p in plans],['reference']);self.assertIn('reference job failed',run['reasons'])
    def test_the_list_holds_all_for_capacity_trials(self):
        plan={'sessions':[{'trials':[{'selector':'m3'},{'selector':'m3'}]}],'capacity':[{'trial_id':'c0'}]}
        self.assertEqual(bench.reference_selectors(plan),['all','m3'])
        self.assertEqual(bench.reference_selectors(dict(plan,capacity=[])),['m3'])
        self.assertEqual(bench.reference_selectors({'sessions':[{'trials':[{},{'selector':'all'}]}],'capacity':[{'trial_id':'c0'}]}),[])

class LocalJobReferenceTests(tld.Case,Standin):
    """Ruling R51: a local decision job computes its own reference; a job whose trials hold more than one selector (a
    window session: the unit trials of its selector and the control trials of selector `all`) gets the list of its
    selectors, so its reference covers the rows of the session."""
    UNIT=[('unit-m3','py-reference','m3','m3/full-dataset')]
    CONTROL=[('control-base-a','py-reference','all',None),('control-base-b','py-reference','all',None)]
    def jobs(self):
        single=[('unit-m3b','py-reference','m3','m3/full-dataset')]          # another point: trial ids stay unique in the plan
        sessions=[tld.session('s-mixed',self.UNIT+self.CONTROL,point='unit-m3'),tld.session('s-all',tld.UNIT),tld.session('s-m3',single,point='unit-m3b')]
        return tld.run_local(sessions)[3]
    def test_a_window_session_job_gets_the_selectors_of_its_trials(self):
        mixed,plain,single=self.jobs()
        self.assertEqual((mixed['reference_selector'],mixed.get('reference_selectors')),('all',['all','m3']))
        self.assertEqual((plain['reference_selector'],'reference_selectors' in plain),('all',False))
        self.assertEqual((single['reference_selector'],'reference_selectors' in single),('m3',False))
    def test_the_reference_of_a_window_session_job_validates_every_row_of_the_session(self):
        mixed=self.jobs()[0];rows=mixed['rows'];dataset=self.local_dataset(rows)
        with mock.patch.object(self.bc,'_manifest',return_value=self.manifest('Cover')):ref=self.bc.reference_path(mixed,dataset)
        for selector in ('m3','all'):
            with self.subTest(selector=selector):self.assertTrue(self.caller_verdict('Cover',selector,ref,dataset,rows)['eligible'])
        self.assertEqual(sorted(json.loads(Path(ref).read_text())),['m1','m2','m3'])
    def test_a_local_job_without_the_hook_keeps_the_reference_of_its_selector(self):
        mixed=self.jobs()[0];rows=mixed['rows'];dataset=self.local_dataset(rows)
        with mock.patch.object(self.bc,'_manifest',return_value=self.manifest('Plain')):ref=self.bc.reference_path(mixed,dataset)
        self.assertEqual(sorted(json.loads(Path(ref).read_text())),['m1','m2'])
        self.assertFalse(self.caller_verdict('Plain','m3',ref,dataset,rows)['eligible'])
    def test_a_local_job_with_a_trial_outside_its_list_is_refused(self):
        mixed=self.jobs()[0];bad=dict(mixed,reference_selectors=['all'])
        with mock.patch.object(self.bc,'run_deadline',side_effect=AssertionError('a child started')),mock.patch.object(self.bc,'_manifest',return_value='/m.json'),\
             self.assertRaisesRegex(ValueError,'a trial selector outside the run reference'):
            self.bc.reference_path(bad,{'path':'/d','sha256':'a'*64})

if __name__=='__main__':unittest.main()
