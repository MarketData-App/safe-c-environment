import copy, math, sys, unittest
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_capacity as bc, bench_model as bm
from evidence import GateError
POL=bm.load_policy(ROOT);CASE=bm.load_case(ROOT,'bench-control-spin')
ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'};ENV2=dict(ENV4,cpus=2,cpuset=[0,1],reduced=True)

class PercentileTests(unittest.TestCase):
    def test_required_samples_are_exact(self):
        for p,n in bc.REQUIRED_SAMPLES.items():self.assertEqual(n,math.ceil(Fraction(10)/(1-Fraction(p,100))))
    def test_percentiles_need_enough_samples(self):
        r=bc.percentiles(list(range(1,20)));self.assertIsNone(r['p50']);self.assertIn('19 < 20',r['reasons']['p50'])
        r=bc.percentiles(list(range(1,21)));self.assertEqual(r['p50'],10);self.assertIsNone(r['p90'])
        r=bc.percentiles(list(range(1,101)));self.assertEqual((r['p50'],r['p90']),(50,90));self.assertIsNone(r['p99'])
    def test_empty(self):self.assertEqual(bc.percentiles([])['n'],0)

class PlanTests(unittest.TestCase):
    def test_three_configurations_and_three_client_counts(self):
        t,b,est=bc.capacity_trials(CASE,POL,ENV4,'decision',7)
        self.assertEqual(len({(x['configuration'],x['clients']) for x in t}),9);self.assertEqual(len(t),27);self.assertEqual(b,[])
        sw=[x for x in t if x['configuration']=='serial-workers'];self.assertTrue(all(x['servers']==4 and x['workers']=='direct' for x in sw))
        tw=[x for x in t if x['configuration']=='threaded-worker'];self.assertTrue(all(x['servers']==1 and x['workers']==4 for x in tw))
    def test_smoke_is_one_client_one_trial(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);self.assertEqual(sorted({x['clients'] for x in t}),[1]);self.assertEqual(len(t),3)
    def test_configuration_beyond_envelope_is_blocked(self):
        t,b,_=bc.capacity_trials(CASE,POL,ENV2,'decision',7)
        self.assertTrue(all(x['clients']<=2 for x in t));self.assertTrue(any('envelope' in r['reason'] for r in b))
        self.assertTrue(all(x['servers']<=2 for x in t if x['configuration']=='serial-workers'))
    def test_too_long_trial_is_refused_not_shrunk(self):
        c=copy.deepcopy(CASE);c['capacity']['requests_per_client']=64;p=copy.deepcopy(POL);p['capacity']['trial_seconds_max']=1
        with self.assertRaises(GateError):bc.capacity_trials(c,p,ENV4,'decision',7)
    def test_case_without_capacity_plans_nothing(self):
        c=copy.deepcopy(CASE);c.pop('capacity');self.assertEqual(bc.capacity_trials(c,POL,ENV4,'decision',7),([],[],0.0))

class CheckTests(unittest.TestCase):
    def obs(self,t,**over):
        n=t['clients']*t['requests_per_client'];row={'trial_id':t['trial_id'],'scope':'capacity','warmup':False,'eligible':True,'work_units':n*256,'wall_ns':10**9,'cpu_usage_usec':10**6,
            'capacity':{'configuration':t['configuration'],'clients':t['clients'],'servers':t['servers'],'requests_per_client':t['requests_per_client'],'completed':n,'errors':0,'latencies_ns':[10**6]*n,'route':None}}
        row.update(over);return row
    def test_complete_trials_pass(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);plan={'capacity':t,'sizes':POL['sizes']}
        self.assertEqual(bc.check_capacity(plan,[self.obs(x) for x in t]),[])
    def test_lost_requests_and_errors_fail(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);plan={'capacity':t,'sizes':POL['sizes']};o=[self.obs(x) for x in t]
        o[0]['capacity']['completed']-=1;o[1]['capacity']['errors']=1;del o[2]
        self.assertEqual(len(bc.check_capacity(plan,o)),3)
    def test_rows_are_exploratory(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7)
        rows=bc.capacity_rows([self.obs(x) for x in t],POL);self.assertTrue(all(r['label']=='exploratory; capacity rows never decide' for r in rows))

# ---- Beyond the brief's tests (Task 22 implementer): the integration that a capacity run needs ----
import argparse, contextlib, io, json, tempfile, uuid
from unittest import mock
import bench, bench_evidence as be, bench_guardrails as bg, bench_plan as bp
from schema_check import validate
CP=json.loads((ROOT/'safety/container-policy.json').read_text())
DOC={'cpu_max':'max 100000','thread_environment':dict(POL['envelope']['thread_environment']),'cpuset':'0-3'}
SMALL={'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256}

def observation(t,run_id='e'*32,**cap):
    """A coordinator observation of a capacity trial (container/bench_capacity.py) that completed every request."""
    n=t['clients']*t['requests_per_client'];size=POL['sizes'][t['tier']]
    row={'schema_version':1,'run_id':run_id,'trial_id':t['trial_id'],'block':t['block'],'order':t['order'],'point':'capacity','scope':'capacity','mode':'warm',
         'variant':t['variant'],'workers':t['workers'],'tier':t['tier'],'phase':'capacity','warmup':False,'runner':'safe-c-trial-runner','wall_ns':10**9,
         'cpu_usage_usec':10**6,'cpu_user_usec':9*10**5,'cpu_system_usec':10**5,'nr_throttled':0,'throttled_usec':0,'pids_start':1,'pids_end':1,'threads_start':1,'threads_end':1,
         'loops':1,'work_units':n*size,'phases':{},'result_sha256':None,'eligible':True,'verdict':{'failures':{}},'memory':None,'unavailable':{},'pool':None,
         'capacity':{'configuration':t['configuration'],'clients':t['clients'],'servers':t['servers'],'requests_per_client':t['requests_per_client'],'completed':n,'errors':0,
                     'latencies_ns':[10**6+i for i in range(n)],'route':t['route'],**cap}}
    return row

class CaseAndPolicyTests(unittest.TestCase):
    def test_the_control_case_declares_the_capacity_scope(self):
        self.assertIn('capacity',CASE['scopes']);self.assertEqual(CASE['capacity']['tier'],'tiny');self.assertEqual(CASE['capacity']['clients'],[1,2,4])
        self.assertEqual([c['name'] for c in CASE['capacity']['configurations']],['serial-workers','threaded-worker','python-pool'])
        self.assertEqual(POL['capacity'],{'trial_seconds_max':120,'latency_samples_max':4096,'trials':{'smoke':1,'decision':3},'smoke_clients':[1]})
    def test_the_case_schema_is_closed(self):
        for bad in ({'tier':'tiny','clients':[1],'requests_per_client':65,'configurations':[{'name':'serial-workers','variant':'py-reference'}]},
                    {'tier':'tiny','clients':[3],'requests_per_client':4,'configurations':[{'name':'serial-workers','variant':'py-reference'}]},
                    {'tier':'tiny','clients':[1],'requests_per_client':4,'configurations':[]},
                    {'tier':'tiny','clients':[1],'requests_per_client':4,'configurations':[{'name':'other','variant':'py-reference'}]},
                    {'tier':'tiny','clients':[1],'requests_per_client':4,'configurations':[{'name':'serial-workers','variant':'py-reference','extra':1}]},
                    {'tier':'tiny','clients':[1],'requests_per_client':4,'configurations':[{'name':'serial-workers','variant':'py-reference'}],'extra':1}):
            with self.subTest(bad=bad):
                with self.assertRaises(GateError):validate(ROOT,'bench-case',dict(CASE,capacity=bad))
    def test_configuration_names_are_unique(self):
        c=copy.deepcopy(CASE);c['capacity']['configurations'].append(dict(c['capacity']['configurations'][0]))
        with self.assertRaisesRegex(GateError,'unique'):bc.capacity_trials(c,POL,ENV4,'smoke',7)
    def test_a_variant_that_is_not_implemented_is_blocked(self):
        c=copy.deepcopy(CASE);c['capacity']['configurations'][0]['variant']='py-optimized'
        t,b,_=bc.capacity_trials(c,POL,ENV4,'smoke',7)
        self.assertNotIn('serial-workers',{x['configuration'] for x in t});self.assertIn('not implemented',b[0]['reason'])

class BuildPlanTests(unittest.TestCase):
    def test_the_plan_holds_the_capacity_trials_and_their_estimate(self):
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4)
        c=copy.deepcopy(CASE);c.pop('capacity');c['scopes']=[s for s in c['scopes'] if s!='capacity']
        plain=bp.build_plan(c,POL,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4)
        t,b,est=bc.capacity_trials(CASE,POL,ENV4,'smoke',7)
        self.assertEqual((plan['capacity'],plan['capacity_blocked']),(t,b));self.assertNotIn('capacity',plain);self.assertNotIn('capacity_blocked',plain)
        self.assertAlmostEqual(plan['estimate_seconds'],plain['estimate_seconds']+est,delta=0.11);self.assertGreater(est,0);self.assertLessEqual(plan['estimate_seconds'],600)
        self.assertEqual(bench.plan_digest(plan),plan['plan_id'])
    def test_a_too_long_capacity_trial_refuses_the_plan(self):
        c=copy.deepcopy(CASE);c['capacity']['requests_per_client']=64;p=copy.deepcopy(POL);p['capacity']['trial_seconds_max']=1
        with self.assertRaises(GateError):bp.build_plan(c,p,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4)

class GuardrailTests(unittest.TestCase):                  # B12 (spec H1, H6): the capacity format is defined; the guardrail checks it
    def plan(self,env=ENV4,mode='smoke'):return bp.build_plan(CASE,POL,mode=mode,dataset=SMALL,seed=7,envelope=env)
    def test_a_built_capacity_plan_is_checked_and_passes(self):
        r=bg.check(self.plan(),POL,ENV4,CP,DOC)
        self.assertEqual((r['rejected'],r['blocked']),([],[]));self.assertNotIn(bg.NA_CAPACITY,r.get('not_applicable',[]))
        self.assertNotIn(bg.NA_CAPACITY,json.dumps(r))
    def test_malformed_capacity_trials_are_rejected(self):
        good=self.plan()['capacity'][0]
        sw=next(t for t in self.plan()['capacity'] if t['configuration']=='serial-workers');tw=next(t for t in self.plan()['capacity'] if t['configuration']=='threaded-worker')
        for bad in ([{}],['x'],[dict(good,configuration='other')],[dict(good,clients=0)],[dict(good,requests_per_client=65)],[dict(good,extra=1)],
                    [{k:v for k,v in good.items() if k!='servers'}],[dict(sw,workers=4)],[dict(tw,servers=2)],[dict(tw,workers='direct')],[dict(good,scope='caller')],
                    [dict(good,clients=True)],'x'):
            with self.subTest(bad=bad):
                r=bg.check(dict(self.plan(),capacity=bad),POL,ENV4,CP,DOC)
                self.assertTrue(any(x.startswith('capacity') for x in r['rejected']),r)
        r=bg.check(dict(self.plan(),capacity_blocked=[{'configuration':'x'}]),POL,ENV4,CP,DOC);self.assertTrue(any(x.startswith('capacity') for x in r['rejected']))
    def test_an_oversubscribed_capacity_trial_is_rejected(self):
        sw=next(t for t in self.plan()['capacity'] if t['configuration']=='serial-workers')
        r=bg.check(dict(self.plan(),capacity=[sw]),POL,ENV2,CP,dict(DOC,cpuset='0-1'))
        self.assertIn(f"oversubscribed {sw['trial_id']} (4 servers x 1 workers x 1 threads > 2 CPUs)",r['rejected'])
        p=dict(self.plan(),capacity=[sw],fixed_environment=dict(POL['envelope']['thread_environment'],OMP_NUM_THREADS='2'))
        self.assertIn(f"oversubscribed {sw['trial_id']} (4 servers x 1 workers x 2 threads > 4 CPUs)",bg.check(p,POL,ENV4,CP,DOC)['rejected'])
        self.assertEqual(bg.check(dict(self.plan(),capacity=[sw]),POL,ENV4,CP,DOC)['rejected'],[])          # 4 x 1 x 1 = 4 CPUs: permitted
    def test_planned_clients_beyond_the_envelope_block_the_run(self):
        tw=next(t for t in self.plan()['capacity'] if t['configuration']=='threaded-worker');p=dict(self.plan(),sessions=[],memory=[],capacity=[dict(tw,workers=2,clients=4)])
        doc=dict(DOC,cpuset='0-1');hits=bg.affected(p,POL,ENV2,CP,doc);r=bg.check(p,POL,ENV2,CP,doc)
        self.assertEqual(r['rejected'],[]);self.assertIn(f"capacity {tw['trial_id']}: 4 clients beyond the 2-CPU envelope",r['blocked']);self.assertTrue(bg.blocks_run(hits))
    def test_blocked_configurations_are_listed_and_do_not_block_the_other_rows(self):
        p=self.plan(ENV2,'decision');self.assertTrue(p['capacity_blocked'])
        doc=dict(DOC,cpuset='0-1');hits=bg.affected(p,POL,ENV2,CP,doc);r=bg.check(p,POL,ENV2,CP,doc)
        self.assertEqual(r['rejected'],[]);self.assertFalse(bg.blocks_run(hits))
        for b in p['capacity_blocked']:self.assertTrue(any(b['configuration'] in x and b['reason'] in x for x in r['blocked']),r)
        self.assertFalse([x for x in bg.blocked_rows(p,hits)])
    def test_a_hidden_cpu_limit_affects_the_capacity_trials(self):
        p=dict(self.plan(),sessions=[],memory=[]);hits=bg.affected(p,POL,ENV4,CP,dict(DOC,cpu_max='200000 100000'))
        self.assertTrue(bg.blocks_run(hits));hit=[t['trial_id'] for _,h,_ in hits for t in h]
        self.assertEqual(sorted(hit),sorted(t['trial_id'] for t in p['capacity']))    # every smoke capacity trial needs 4 CPUs
        self.assertEqual(bg.blocked_rows(p,hits),[])                                       # capacity trials are not timing rows

class IntegrityTests(unittest.TestCase):                  # B15: capacity trials are planned rows with their own work count
    def test_capacity_rows_are_planned(self):
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4);run={'run_id':'e'*32,'dataset':plan['dataset']}
        rows=[observation(t) for t in plan['capacity']];got=be.check_integrity(plan,run,rows,POL)
        self.assertFalse([x for x in got if 'capacity' in x]);self.assertFalse([x for x in got if any(t['trial_id'] in x for t in plan['capacity'])],got)
        rows[0]['work_units']-=1;self.assertIn('wrong work count: '+rows[0]['trial_id'],be.check_integrity(plan,run,rows,POL))
        self.assertIn('missing failed attempt: '+rows[1]['trial_id'],be.check_integrity(plan,run,rows[:1]+rows[2:],POL))
        self.assertIn('unplanned row: capacity-b09-00',be.check_integrity(plan,run,rows+[dict(rows[0],trial_id='capacity-b09-00')],POL))
        self.assertIn('scope mismatch: '+rows[2]['trial_id'],be.check_integrity(plan,run,rows[:2]+[dict(rows[2],scope='caller')],POL))

class SchemaTests(unittest.TestCase):
    def test_a_capacity_observation_validates(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);validate(ROOT,'bench-observation',observation(t[0]))
        for bad in ({'latencies_ns':[1]*4097},{'latencies_ns':[-1]},{'errors':-1},{'configuration':'other'},{'extra':1}):
            with self.subTest(bad=list(bad)):
                with self.assertRaises(GateError):validate(ROOT,'bench-observation',observation(t[0],**bad))
        row=observation(t[0]);row['capacity'].pop('route')
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',row)
        row=observation(t[0]);row.pop('capacity')                                          # a capacity row needs its capacity object
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',row)
    def test_the_policy_validates(self):
        import json
        doc=json.loads((ROOT/'safety/performance-policy.json').read_text())     # FR3: load_policy adds the project keys; the file holds none
        validate(ROOT,'bench-policy',doc);self.assertEqual(doc['capacity'],POL['capacity'])
        for bad in ({'trial_seconds_max':0},{'latency_samples_max':4097},{'extra':1}):
            with self.subTest(bad=bad):
                with self.assertRaises(GateError):validate(ROOT,'bench-policy',dict(doc,capacity=dict(doc['capacity'],**bad)))

class RowsAndReportTests(unittest.TestCase):
    def test_rows_pool_the_samples_per_configuration_and_clients(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'decision',7);rows=bc.capacity_rows([observation(x) for x in t],POL)
        self.assertEqual(len(rows),9);self.assertTrue(all(r['trials']==3 for r in rows))
        four=next(r for r in rows if r['configuration']=='serial-workers' and r['clients']==4)
        self.assertEqual(four['latency_ns']['n'],48);self.assertEqual(four['latency_ns']['p50'],10**6+7)     # 3 trials x 16 samples, nearest rank 24
        self.assertEqual(four['throughput_units_per_s']['median'],16.0);self.assertEqual(four['cpu_ns_per_unit']['median'],10**9/16)
    def test_report_lines(self):
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);lines=bc.report_lines(bc.capacity_rows([observation(x) for x in t],POL))
        self.assertEqual(lines[0],'## Capacity (exploratory; capacity rows never decide)');self.assertEqual(len(lines),4)
        self.assertTrue(all('p50 n/a (too few samples (4 < 20))' in x for x in lines[1:]),lines)
        self.assertEqual(bc.report_lines([]),['## Capacity (exploratory; capacity rows never decide)','none'])

class RunTests(unittest.TestCase):
    def session(self,rows,status='PASS',exit_code=0):
        test=self
        class Session:
            jobs=[]
            def __init__(self,root,run_dir):pass
            def job(self,plan,label,timeout,restore=()):
                Session.jobs.append((plan,label,timeout,list(restore)))
                return {'exit_code':exit_code,'failure':None,'evidence_path':'ev/capacity.json','output':json.dumps({'status':status,'files':['capacity.jsonl']})}
            def fetch(self,rel,dst):
                test.assertEqual(rel,'bench/out/capacity.jsonl');Path(dst).parent.mkdir(parents=True,exist_ok=True)
                Path(dst).write_text(''.join(json.dumps(r)+'\n' for r in rows));return dst
        return Session
    def test_one_capacity_job_in_one_session(self):
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4);rows=[observation(t) for t in plan['capacity']];done=[]
        S=self.session(rows)
        with tempfile.TemporaryDirectory() as d:
            got,reasons,ev=bc.run_capacity(ROOT,Path(d),plan,{'run_id':'e'*32},[('bench/private/reference.json','x')],POL,S,done.append)
        self.assertEqual((got,reasons,ev),(rows,[],['ev/capacity.json']));self.assertEqual(len(done),1);self.assertEqual(len(S.jobs),1)
        job,label,timeout,restore=S.jobs[0]
        self.assertEqual((job['job'],job['trials'],job['latency_samples_max'],label,timeout),('capacity',plan['capacity'],4096,'capacity',POL['job_deadlines']['session']))
        self.assertEqual(restore,[('bench/private/reference.json','x')])
    def test_a_failed_session_or_lost_requests_are_reasons(self):
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset=SMALL,seed=7,envelope=ENV4);rows=[observation(t) for t in plan['capacity']]
        with tempfile.TemporaryDirectory() as d:
            got,reasons,_=bc.run_capacity(ROOT,Path(d),plan,{},[],POL,self.session(rows,status='FAIL'),lambda s:None)
            self.assertEqual(got,[]);self.assertIn('capacity session did not complete',reasons);self.assertEqual(len(reasons),1+len(plan['capacity']))
            lost=copy.deepcopy(rows);lost[0]['capacity']['completed']-=1
            got,reasons,_=bc.run_capacity(ROOT,Path(d),plan,{},[],POL,self.session(lost),lambda s:None)
            self.assertEqual(len(got),3);self.assertEqual(len(reasons),1);self.assertIn('requests completed',reasons[0])

class RunCmdTests(unittest.TestCase):                     # bench run with the fakes of test_bench_accounting and test_bench_guardrails
    def test_a_capacity_run_is_valid_and_records_the_capacity_rows(self):
        sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_accounting as tba
        code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))
        self.assertEqual((code,run['status']),(0,'VALID'));self.assertEqual(be.verify_record(run),[])
    def test_the_run_records_the_capacity_guardrail_result(self):
        sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_guardrails as tg
        code,run,plan,guard=tg.run_cmd_with({'status':'BLOCKED'})        # a BLOCKED doctor probe: the guardrails run, no container starts
        self.assertTrue(plan['capacity']);self.assertEqual((guard['rejected'],guard['blocked']),([],[]));self.assertNotIn(bg.NA_CAPACITY,guard.get('not_applicable',[]))

class DecideTests(unittest.TestCase):
    def test_capacity_rows_never_enter_the_decision_evidence(self):     # B14, spec H6: capacity is reported by compare only
        import bench_decide as bd
        plan=bp.build_plan(CASE,POL,mode='decision',dataset=SMALL,seed=7,envelope=ENV4)
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'observations.jsonl').write_text(''.join(json.dumps(observation(t))+'\n' for t in plan['capacity']))
            ev=bd.evidence_from_run(ROOT,Path(d),{'status':'VALID'},plan,CASE)
        self.assertEqual([r for r in ev['rows'] if r['scope']=='capacity'],[])

class ApprovalFindingTests(unittest.TestCase):           # Task 22 approval: T22-APP-01, T22-APP-02, T22-APP-03
    def test_the_capacity_cpu_figure_is_labelled_not_reconciled(self):          # T22-APP-01 (choice b): compare rows and report lines
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'smoke',7);rows=bc.capacity_rows([observation(x) for x in t],POL)
        self.assertTrue(rows);self.assertTrue(all(r['cpu_ns_per_unit_note']=='not reconciled (B15)' for r in rows),rows)
        lines=bc.report_lines(rows)
        self.assertTrue(all('ns/unit (not reconciled (B15))' in x for x in lines[1:]),lines)
    def test_rows_pool_only_eligible_trials_and_count_the_others(self):        # T22-APP-02
        t,_,_=bc.capacity_trials(CASE,POL,ENV4,'decision',7);obs=[observation(x) for x in t]
        sw4=[o for o in obs if o['capacity']['configuration']=='serial-workers' and o['capacity']['clients']==4]
        sw4[0].update(eligible=False,wall_ns=10**12,cpu_usage_usec=10**9);sw4[0]['capacity']['latencies_ns']=[10**12]*16
        tw1=[o for o in obs if o['capacity']['configuration']=='threaded-worker' and o['capacity']['clients']==1]
        for o in tw1:o['eligible']=False
        rows=bc.capacity_rows(obs,POL)
        four=next(r for r in rows if r['configuration']=='serial-workers' and r['clients']==4)
        self.assertEqual((four['trials'],four['ineligible_trials']),(2,1));self.assertEqual(four['latency_ns']['n'],32)
        self.assertEqual(four['throughput_units_per_s']['n'],2);self.assertEqual(four['throughput_units_per_s']['median'],16.0)
        self.assertEqual(four['cpu_ns_per_unit']['max'],10**9/16);self.assertEqual(four['latency_ns']['p50'],10**6+7)   # 2 trials x 16 samples, nearest rank 16
        one=next(r for r in rows if r['configuration']=='threaded-worker' and r['clients']==1)
        self.assertEqual((one['trials'],one['ineligible_trials'],one['latency_ns']['n'],one['throughput_units_per_s']['n']),(0,3,0,0))
        other=next(r for r in rows if r['configuration']=='python-pool' and r['clients']==2);self.assertEqual((other['trials'],other['ineligible_trials']),(3,0))
        lines=bc.report_lines(rows)
        self.assertTrue(any(x.startswith('- serial-workers, 4 clients,') and '2 trials (1 ineligible excluded)' in x for x in lines),lines)
        self.assertTrue(any(x.startswith('- threaded-worker, 1 clients,') and '0 trials (3 ineligible excluded)' in x for x in lines),lines)
    def test_the_case_schema_refuses_an_invalid_configuration_variant_pair(self):   # T22-APP-03
        def case(name,variant):
            c=copy.deepcopy(CASE);c['capacity']['configurations']=[{'name':name,'variant':variant}];return c
        for name,variant in (('serial-workers','py-threads'),('serial-workers','py-processes'),('serial-workers','c-threads'),
                             ('threaded-worker','py-reference'),('threaded-worker','c-serial'),('python-pool','py-optimized'),('python-pool','py-library')):
            with self.subTest(name=name,variant=variant):
                with self.assertRaises(GateError):validate(ROOT,'bench-case',case(name,variant))
                with self.assertRaisesRegex(GateError,'capacity configuration'):bc.capacity_trials(case(name,variant),POL,ENV4,'smoke',7)
        for name,variant in (('serial-workers','py-reference'),('serial-workers','c-serial'),('serial-workers','py-library'),('threaded-worker','py-threads'),
                             ('threaded-worker','c-threads'),('python-pool','py-processes')):
            with self.subTest(valid=(name,variant)):
                self.assertTrue(validate(ROOT,'bench-case',case(name,variant)))

if __name__=='__main__':unittest.main()
