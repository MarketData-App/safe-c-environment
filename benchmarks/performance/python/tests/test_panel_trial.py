"""Base Task 18 (Amendment G7.3, H21.4): the single-record L-pass panel trial of the framework control, through the
coordinator's timing job and the trial child (`benchlab.trial --panel`). Container suite (framework control)."""
import importlib.util, json, shutil, tempfile, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bc_panel','/src/container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
CELLS=['g1-pos-near','g1-pos-far','g0-mid-near','g0-mid-far','g1-neg-near','g1-neg-far']     # FR5: project cell names (synthetic)

class PanelTrialTests(unittest.TestCase):
    def work(self):
        out=Path(tempfile.mkdtemp());saved=bc.WORK;bc.WORK=out;(out/'bench/out').mkdir(parents=True)
        self.addCleanup(shutil.rmtree,out,True);self.addCleanup(setattr,bc,'WORK',saved);return out
    def panel_run(self,reference_status,passes=5,mode='warm',variant='py-reference',workers='direct',tier='tiny'):
        """(observation, trial, job plan, phases) of one real panel trial of the timing job."""
        out=self.work()
        trial={'trial_id':'unit-one-s00-b00-00','block':0,'order':0,'point':'unit-one','scope':'caller','mode':mode,'variant':variant,'workers':workers,
               'tier':tier,'loops':1,'warmup':False,'panel':[0,1,2,3,4,5],'panel_passes':passes,'panel_cells':CELLS,'panel_reference_status':reference_status}
        plan={'schema_version':1,'job':'timing','run_id':'0'*32,'case':'bench-control-spin','case_manifest':'/src/benchmarks/performance/cases/bench-control-spin.json','project_dir':None,
              'dataset':{'kind':'synthetic','size':'tiny','seed':20261007,'sha256':None,'rows':6},'rows':6,'sizes':{'tiny':1,'small':256},'pyperf':{'values':1,'warmups':0},
              'trials':[trial],'deadline_seconds':300,'local':False,'output':'bench/out'}
        ref=bc.JOBS['reference'](dict(plan,job='reference'),out/'bench/out')
        res=bc.JOBS['timing'](dict(plan,reference_sha256=ref['reference_sha256']),out/'bench/out')
        rows=[json.loads(x) for x in (out/'bench/out/observations.jsonl').read_text().splitlines()]
        phases=[json.loads(x) for x in (out/'bench/out/phases.jsonl').read_text().splitlines()]
        self.assertEqual(res['status'],'PASS');self.assertEqual(len(rows),1);return rows[0],trial,plan,phases
    def panel_row(self,reference_status,passes=5,mode='warm'):
        return self.panel_run(reference_status,passes,mode)[0]
    def test_panel_trial_reports_six_cells_of_l_walls(self):
        row=self.panel_row(['OK']*6)
        self.assertEqual(set(row['panel_walls']),set(CELLS))       # observations.jsonl is written with sorted keys
        self.assertTrue(all(len(w)==5 and all(type(x) is int and x>0 for x in w) for w in row['panel_walls'].values()))
        self.assertEqual(row['work_units'],30);self.assertIs(row['eligible'],True);self.assertEqual((row['panel_status_diff'],row['detail']),([],None))
        self.assertGreaterEqual(row['wall_ns'],sum(sum(w) for w in row['panel_walls'].values()))     # every call is timed inside the caller interval
        import statistics                                                   # fix round 1 (T18-C1b): L <= 64 keeps every wall in the audit sample
        self.assertEqual(row['panel_passes'],5)
        self.assertEqual(row['panel_stats'],{c:{'median_ns':statistics.median(w),'min_ns':min(w),'max_ns':max(w)} for c,w in row['panel_walls'].items()})
    def test_a_status_difference_makes_the_observation_ineligible(self):     # H21.4: identical status required, no band acceptance
        row=self.panel_row(['OK']*5+['MODEL_DOMAIN'])
        self.assertIs(row['eligible'],False);self.assertEqual(row['detail'],'panel-status')
        self.assertEqual([(d['cell'],d['status'],d['reference_status']) for d in row['panel_status_diff']],[('g1-neg-far','OK','MODEL_DOMAIN')])
    def test_a_cold_panel_trial_makes_one_pass(self):
        row=self.panel_row(['OK']*6,passes=1,mode='cold')
        self.assertTrue(all(len(w)==1 for w in row['panel_walls'].values()));self.assertEqual(row['work_units'],6)
        self.assertEqual(row['panel_passes'],1);self.assertTrue(all(s['median_ns']==s['min_ns']==s['max_ns'] for s in row['panel_stats'].values()))
    def test_the_work_rules_accept_a_real_single_record_trial(self):
        """T5R1-A01 (live): a real single-record trial reports the planned work of container/bench_trial_work.py
        (len(panel) x L one-row calls), never the rows of its tier, and the in-job rules of a local decision job accept it:
        work-count, and pool-identity with the chunks of one row for a warm pooled trial on a non-tiny point (small)."""
        for passes,mode,variant,workers,tier in ((5,'warm','py-reference','direct','tiny'),(1,'cold','py-reference','direct','tiny'),
                                                 (5,'warm','py-threads',2,'small'),(5,'warm','py-processes',2,'small')):
            with self.subTest(mode=mode,variant=variant,tier=tier):
                row,trial,plan,phases=self.panel_run(['OK']*6,passes,mode,variant,workers,tier)
                counts=bc.local_rule_counts(plan,[row],phases,{},set(),'/src/safety/performance-policy.json')
                self.assertEqual({k:counts[k] for k in ('work-count','pool-identity','caller-semantics','trial-design','unplanned-row')},
                                 {'work-count':0,'pool-identity':0,'caller-semantics':0,'trial-design':0,'unplanned-row':0})
                self.assertEqual(row['work_units'],6*passes)
                if workers!='direct':self.assertEqual((row['pool']['chunk_sizes'],row['pool']['chunks']),([1],1))
                self.assertEqual(row['work_units'],bc._trial_work.planned_work_units(trial,plan['sizes']))

if __name__=='__main__':unittest.main()
