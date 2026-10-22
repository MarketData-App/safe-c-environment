"""Phase 3 Task 25 (spec 13), framework part (task EX-17): a failed row of a bench report links the native agreement check
that the project's bench.json `native.agreement` names, `dev diagnose`, its input replay and a separately labeled debugger
or sanitizer investigation; nothing timed under GDB or a sanitizer is a release measurement.

Framework tests use synthetic rows and a synthetic project directory string (H3: no example is named)."""
import argparse, contextlib, io, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_decide as bd, bench_model as bm
from evidence import GateError

ROW={'case':'demo-case','point':'p-caller','scope':'caller','mode':'warm','variant':'c-threads','workers':4,'route':'shm','failures':2,
     'correctness':'10/12 eligible','language':'c'}
PY_ROW=dict(ROW,variant='py-threads',route=None,language='python')
PROJECT='examples/demo-x'
DS={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256}
LABEL='investigation only; nothing timed under GDB or a sanitizer is a release measurement'

def text(rows,project=PROJECT,local=False,agreement='demo-agree'):return '\n'.join(bd.investigation_lines(rows,project,local,agreement))

class InvestigationLineTests(unittest.TestCase):
    def test_c_row_links_native_agreement_and_dev(self):
        t=text([ROW])
        self.assertIn(f'./tools/safety bench check --project {PROJECT} --native --check demo-agree',t)
        self.assertIn('./tools/safety dev test --id',t)
        self.assertIn('./tools/safety dev diagnose --run-id <failed dev run id>',t)
        self.assertIn('./tools/safety dev replay --run-id <failed dev run id> --snapshot original',t)
        self.assertLess(t.index('dev test'),t.index('dev diagnose'));self.assertLess(t.index('dev test'),t.index('dev replay'))
        self.assertIn(LABEL,t)
    def test_the_agreement_check_name_comes_from_the_argument(self):
        self.assertIn('--native --check other-name',text([ROW],agreement='other-name'))
        t=text([ROW],agreement=None)          # a project without a native declaration: no invented check name
        self.assertNotIn('--native --check',t);self.assertIn('native.agreement',t)
    def test_local_run_needs_a_synthetic_reproducer(self):
        t=text([ROW],local=True)
        self.assertIn('synthetic reproducer',t);self.assertIn('no input-replay artifact exists for a local: run',t)
        self.assertNotIn('dev replay',t);self.assertIn('dev diagnose --run-id',t);self.assertIn(LABEL,t)
    def test_passing_rows_have_no_lines(self):
        self.assertEqual(bd.investigation_lines([dict(ROW,failures=0)],None,False),[])
        self.assertEqual(bd.investigation_lines([],PROJECT,False,'demo-agree'),[])
    def test_each_failed_row_has_a_heading_and_three_labeled_steps(self):
        lines=bd.investigation_lines([ROW,dict(ROW,failures=0,route='stdio'),PY_ROW],PROJECT,False,'demo-agree')
        heads=[l for l in lines if l.startswith('### ')];self.assertEqual(len(heads),2)
        for n in (1,2,3):self.assertEqual(len([l for l in lines if l.startswith(f'{n}. ')]),2)
        self.assertIn('c-threads x4 [shm]',heads[0]);self.assertIn('2 failed',heads[0]);self.assertIn('10/12 eligible',heads[0])
        self.assertTrue(lines[0].startswith('## '))
    def test_python_row_validates_the_case_and_never_names_the_native_check(self):
        t=text([PY_ROW])
        self.assertNotIn('--native',t);self.assertIn(f'./tools/safety bench validate --case demo-case --project {PROJECT}',t)
        self.assertIn('dev diagnose --run-id',t);self.assertIn('dev replay --run-id',t);self.assertIn(LABEL,t)
    def test_a_framework_row_without_a_project_has_no_project_option(self):
        t=text([PY_ROW],project=None,agreement=None)
        self.assertNotIn('--project',t);self.assertIn('./tools/safety bench validate --case demo-case',t)
    def test_malformed_failure_counts_are_never_skipped_silently(self):
        for bad in (None,'2',True,-1):
            with self.subTest(failures=bad):
                t=text([dict(ROW,failures=bad)])
                self.assertIn('### ',t)          # an unreadable failure count is investigated, never treated as zero

class AgreementNameTests(unittest.TestCase):
    def test_the_name_is_the_bench_json_native_agreement(self):
        with mock.patch.object(bm,'project_bench',return_value={'native':{'agreement':'demo-agree'}}):
            self.assertEqual(bd.native_agreement_name(ROOT,PROJECT),'demo-agree')
        with mock.patch.object(bm,'project_bench',return_value={'checks':[]}):self.assertIsNone(bd.native_agreement_name(ROOT,PROJECT))
        with mock.patch.object(bm,'project_bench',side_effect=GateError('malformed')):self.assertIsNone(bd.native_agreement_name(ROOT,PROJECT))
        self.assertIsNone(bd.native_agreement_name(ROOT,None))
    def test_each_native_example_project_gives_its_declared_name(self):
        import bench_phase2
        for project,decl,_,_ in bench_phase2.native_projects(ROOT):          # found by layout; the framework names no example
            with self.subTest(project=project):self.assertEqual(bd.native_agreement_name(ROOT,project),decl['native']['agreement'])

class ReportLinkTests(unittest.TestCase):
    """report_cmd adds the investigation lines of the failed rows to summary.md, with the agreement name of the run's project."""
    def recorded(self,tmp,failed):
        d=Path(tmp)
        for p in ('safety','schemas'):shutil.copytree(ROOT/p,d/p)
        run_id='2'*32;rd=d/'artifacts/bench'/run_id;rd.mkdir(parents=True)
        def row(tid,block,variant,eligible=True):
            return {'run_id':run_id,'trial_id':tid,'block':block,'warmup':False,'eligible':eligible,'work_units':256,'loops':1,'wall_ns':2560000+block,
                    'cpu_usage_usec':2560,'point':'qual-caller','scope':'caller','mode':'warm','variant':variant,'workers':'direct','tier':'small','phase':'caller'}
        rows=[row(f'a-b{b:02d}-00',b,'py-reference') for b in range(2)]+[row(f'a-b{b:02d}-01',b,'py-optimized',eligible=not (failed and b==1)) for b in range(2)]
        (rd/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        trial=lambda r:{k:r[k] for k in ('trial_id','block','point','scope','mode','variant','workers','tier','warmup')}
        (rd/'plan.json').write_text(json.dumps({'mode':'smoke','dataset':DS,'sessions':[{'session':'s00','trials':[trial(r) for r in rows]}],'memory':[]}))
        (rd/'phases.jsonl').write_text(json.dumps({'phase':'control-zero','wall_ns':1000})+'\n')
        (rd/'run.json').write_text(json.dumps({'run_id':run_id,'case':'bench-control-spin','mode':'smoke','status':'VALID','runtime':{'python':'3.13.0'},
                                               'envelope':{'cpus':4},'plan':{'project_dir':PROJECT},'dataset':DS}))
        return d,run_id,rd
    def report(self,d,run_id):
        with contextlib.redirect_stdout(io.StringIO()):return bench.report_cmd(d,argparse.Namespace(run_id=run_id,format='json'))
    def test_a_failed_row_is_linked_in_the_report(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bd,'native_agreement_name',return_value='demo-agree') as name:
            d,run_id,rd=self.recorded(t,failed=True);self.report(d,run_id)
            md=(rd/'summary.md').read_text()
            self.assertIn('py-optimized',md.split('## Investigation')[1]);self.assertIn('dev diagnose --run-id',md);self.assertIn(LABEL,md)
            self.assertEqual(name.call_args[0][1],PROJECT)          # the project of the run (run.json plan.project_dir)
    def test_a_report_without_failed_rows_has_no_investigation(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bd,'native_agreement_name',return_value='demo-agree'):
            d,run_id,rd=self.recorded(t,failed=False);self.assertEqual(self.report(d,run_id),0)
            self.assertNotIn('## Investigation',(rd/'summary.md').read_text())

if __name__=='__main__':unittest.main()
