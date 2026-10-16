import hashlib, shutil, sys, tempfile, unittest
from pathlib import Path
from benchlab.profiling import profile, top
SPIN='/src/benchmarks/performance/cases/bench-control-spin.json'

class ProfilingTests(unittest.TestCase):
    def out(self):
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);return d
    def test_profiles_name_coverage_and_write_pstats(self):
        for variant in ('py-optimized','py-processes'):
            out=self.out();r=profile(SPIN,variant,64,1,str(out))
            with self.subTest(variant=variant):
                self.assertTrue(r['files'] and all((out/f).is_file() for f in r['files']));self.assertTrue(r['top']);self.assertIn('profiled' if variant=='py-processes' else 'one process',r['coverage'])
    def test_process_profile_names_the_missing_parent_and_never_sums_nested_times(self):
        out=self.out();r=profile(SPIN,'py-processes',64,1,str(out))
        self.assertIn('the parent process is not profiled',r['coverage'])
        self.assertIn('ProcessPoolExecutor.map, not run_pool',r['scope'])
        self.assertIn(f"per-function totals across {len(r['files'])} worker files",r['times'])
        self.assertEqual(r['files'],sorted(r['files']));self.assertTrue(all(f.startswith('py-processes-worker-') for f in r['files']))
        self.assertEqual(r['variant'],'py-processes');self.assertLessEqual(len(r['top']),20)
        self.assertNotIn('dataset',[p.name for p in out.iterdir()])          # the synthetic dataset never stays in the output
        for row in r['top']:
            self.assertEqual(set(row),{'function','calls','tottime_s','cumtime_s'});self.assertLessEqual(row['tottime_s'],row['cumtime_s']+1e-6)
        cum=[row['cumtime_s'] for row in r['top']];self.assertEqual(cum,sorted(cum,reverse=True))
    def test_top_reads_pstats_without_summing_across_nested_calls(self):
        out=self.out();r=profile(SPIN,'py-reference',64,1,str(out))
        rows=top([out/f for f in r['files']],limit=5);self.assertLessEqual(len(rows),5)
        self.assertEqual(rows,r['top'][:5])
        self.assertIn('benchlab/controlcase.py:',' '.join(x['function'] for x in r['top']))   # module path, not the basename only
        self.assertTrue(r['coverage'].startswith('adapter run, one process'));self.assertEqual(r['scope'],'adapter run')
    def test_thread_profile_counts_chunks_and_states_the_time_caveat(self):
        out=self.out();r=profile(SPIN,'py-threads',64,1,str(out))
        self.assertIn('2 of 2 worker-thread chunks appear in the in-process profile',r['coverage'])
        self.assertIn('call counts are exact',r['times']);self.assertIn('approximate',r['times'])
        self.assertGreater(r['wall_s'],0);self.assertIsNotNone(r['run_chunk_cumtime_s'])
    def test_profile_records_input_and_runtime_identity(self):
        out=self.out();r=profile(SPIN,'py-reference',8,1,str(out))
        self.assertEqual(r['case_manifest_sha256'],hashlib.sha256(Path(SPIN).read_bytes()).hexdigest())
        self.assertEqual(len(r['dataset_sha256']),64);self.assertEqual(r['bench_ref'][0],'benchlab.controlcase:Spin')
        self.assertEqual(r['runtime']['version'],sys.version);self.assertEqual(r['runtime']['implementation'],sys.implementation.name)
        self.assertIn('sys.monitoring',r['runtime']['profiler'])
    def test_profile_refuses_an_unknown_variant(self):
        with self.assertRaises(ValueError):profile(SPIN,'py-nothing',8,1,str(self.out()))
