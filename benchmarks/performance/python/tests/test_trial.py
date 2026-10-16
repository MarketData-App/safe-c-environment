import importlib.util, json, os, shutil, tempfile, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bc','/src/container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)

class TrialTests(unittest.TestCase):
    def work(self):
        """A fresh coordinator work directory, removed after the test; the module WORK is restored."""
        out=Path(tempfile.mkdtemp());saved=bc.WORK;bc.WORK=out;(out/'bench/out').mkdir(parents=True)
        self.addCleanup(shutil.rmtree,out,True);self.addCleanup(setattr,bc,'WORK',saved);return out
    def test_tiny_timing_session_produces_complete_observations(self):
        out=self.work()
        trials=[{'trial_id':'t-w00','block':None,'order':None,'point':'smoke-caller','scope':'caller','mode':'cold','variant':'py-threads','workers':1,'tier':'tiny','loops':1,'warmup':True},
                {'trial_id':'t-b00-00','block':0,'order':0,'point':'smoke-caller','scope':'caller','mode':'warm','variant':'py-processes','workers':1,'tier':'tiny','loops':1,'warmup':False},
                {'trial_id':'k-b00-00','block':0,'order':0,'point':'smoke-kernel','scope':'kernel','mode':'direct','variant':'py-optimized','workers':'direct','tier':'tiny','loops':1,'warmup':False}]
        plan={'schema_version':1,'job':'timing','run_id':'0'*32,'case':'bench-control-spin','case_manifest':'/src/benchmarks/performance/cases/bench-control-spin.json','project_dir':None,
              'dataset':{'kind':'synthetic','size':'tiny','seed':20261007,'sha256':None,'rows':1},'rows':1,'sizes':{'tiny':1},'pyperf':{'values':1,'warmups':0},
              'trials':trials,'deadline_seconds':300,'local':False,'output':'bench/out'}
        ref=bc.JOBS['reference'](dict(plan,job='reference'),out/'bench/out')     # once per run; later jobs verify it by digest
        res=bc.JOBS['timing'](dict(plan,reference_sha256=ref['reference_sha256']),out/'bench/out')
        rows=[json.loads(x) for x in (out/'bench/out/observations.jsonl').read_text().splitlines()]
        self.assertEqual(res['status'],'PASS');self.assertEqual(sorted(r['trial_id'] for r in rows),['k-b00-00','t-b00-00','t-w00'])
        self.assertTrue(all(r['eligible'] and r['work_units']==1 and r['cpu_usage_usec'] is not None for r in rows))
        phases=[json.loads(x) for x in (out/'bench/out/phases.jsonl').read_text().splitlines()]
        self.assertIn('pool_start',[p['phase'] for p in phases]);self.assertIn('control-zero',[p['phase'] for p in phases])
        # Task 16a: B10 pool identity recorded by the child; the tracker started at session setup; the cold pool started inside the interval.
        proc=next(r for r in rows if r['variant']=='py-processes');thr=next(r for r in rows if r['variant']=='py-threads')
        self.assertEqual((proc['pool']['start_method'],proc['pool']['caller_pid_included'],proc['pool']['tracker_session_setup']),('spawn',False,True))
        self.assertEqual((thr['pool']['start_method'],thr['pool']['caller_pid_included'],thr['pool']['pids_distinct']),('thread',True,1))
        self.assertIsNotNone(thr['phases']['pool_start']);self.assertIsNone(proc['phases']['pool_start'])
        kernel=next(r for r in rows if r['scope']=='kernel');self.assertEqual(kernel['runner'],'pyperf');self.assertIsNotNone(kernel.get('pyperf_wall_ns'))
        self.assertTrue((out/'bench/out/pyperf/k-b00-00.json').is_file());self.assertIn('pyperf/k-b00-00.json',res['files'])
        # B10: every trial child (caller and pyperf worker) reports process identity and GIL state after imports, and started isolated.
        self.assertEqual(sorted(c['client'] for c in res['children']),['k-b00-00','py-processes:1:warm','py-threads:1:cold'])
        self.assertTrue(all(c['isolated'] is True and 'gil_label' in c for c in res['children']))
    def test_synthetic_job_without_the_run_reference_digest_fails(self):
        out=self.work()
        plan={'schema_version':1,'job':'timing','run_id':'0'*32,'case':'bench-control-spin','case_manifest':'/src/benchmarks/performance/cases/bench-control-spin.json','project_dir':None,
              'dataset':{'kind':'synthetic','size':'tiny','seed':20261007,'sha256':None,'rows':1},'rows':1,'sizes':{'tiny':1},'pyperf':{'values':1,'warmups':0},
              'trials':[],'deadline_seconds':120,'local':False,'output':'bench/out'}
        with self.assertRaises(ValueError):bc.JOBS['timing'](plan,out/'bench/out')
        with self.assertRaises(ValueError):bc.JOBS['timing'](dict(plan,reference_sha256='0'*64),out/'bench/out')
    def test_memory_trial_records_ready_and_retained_state(self):
        out=self.work()
        plan={'schema_version':1,'job':'memory','run_id':'0'*32,'case':'bench-control-touch','case_manifest':'/src/benchmarks/performance/cases/bench-control-touch.json','project_dir':None,
              'dataset':{'kind':'synthetic','size':'tiny','seed':20261007,'sha256':None,'rows':1},'rows':1,'sizes':{'tiny':1},'pyperf':{'values':1,'warmups':0},
              'trial':{'trial_id':'memory-py-threads-1-0','point':'memory','tier':'tiny','variant':'py-threads','workers':1,'mode':'warm'},'deadline_seconds':120,'local':False,'output':'bench/out'}
        res=bc.JOBS['memory'](plan,out/'bench/out');self.assertEqual(res['status'],'PASS')
        row=json.loads((out/'bench/out/memory.jsonl').read_text())
        self.assertEqual((row['scope'],row['phase'],row['work_units'],row['eligible']),('memory','caller',1,None))
        self.assertIsNotNone(row['memory']['ready_current']);self.assertIsNotNone(row['memory']['retained_current'])
