"""Task 27 (S-06): the fixture file name pattern. A local run (and `bench privacy-pattern`) appends the escaped base name of the
local: dataset to the private path patterns of the hooks; the hooks match each staged, committed or tagged path's base name
against them (never content) and mask the path. Synthetic names only."""
import argparse, contextlib, importlib.util, io, json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_privacy as bp
from evidence import GateError

def load_hook():
    spec=importlib.util.spec_from_file_location('personal_info_check_t27',ROOT/'.githooks/personal_info_check.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

PLAN={'mode':'smoke','project_dir':None,'dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None,'path':'/private/sample-name.json'},
      'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}

class PatternTests(unittest.TestCase):
    def test_install_appends_once_and_never_prints(self):
        with tempfile.TemporaryDirectory() as t:
            info=Path(t)/'info';info.mkdir();f=Path(t)/'dataset file.json';f.write_text('{}')
            with mock.patch('bench_privacy._git_common_dir',return_value=Path(t)),mock.patch('bench_privacy.resolve_local_dataset',return_value={'path':str(f)}):
                self.assertTrue(bp.install_fixture_pattern(ROOT,'local:x'));self.assertFalse(bp.install_fixture_pattern(ROOT,'local:x'))
            lines=(info/'personal-path-patterns').read_text().splitlines();self.assertEqual(lines,['^'+re.escape('dataset file.json')+'$'])
            self.assertEqual(oct((info/'personal-path-patterns').stat().st_mode&0o777),'0o600')

    def test_install_in_a_real_repository_keeps_other_lines(self):
        # a temporary git repository; the synthetic dataset lies outside its work tree (spec 12 rules apply unmocked)
        with tempfile.TemporaryDirectory() as t:
            repo=Path(t)/'repo';repo.mkdir();env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':t,'GIT_CONFIG_NOSYSTEM':'1'}
            subprocess.run(['git','-C',str(repo),'init','-q'],env=env,check=True,capture_output=True)
            data=Path(t)/'outside'/'sample dataset.json';data.parent.mkdir();data.write_text('{}')
            target=repo/'.git/info/personal-path-patterns';target.write_text('^kept\\.csv$');target.chmod(0o644)
            out=io.StringIO()
            with mock.patch.dict(os.environ,{},clear=False),contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
                os.environ.pop('CI',None)
                self.assertTrue(bp.install_fixture_pattern(repo,'local:'+str(data)))
                self.assertFalse(bp.install_fixture_pattern(repo,'local:'+str(data)))
            self.assertEqual(target.read_text().splitlines(),['^kept\\.csv$','^'+re.escape('sample dataset.json')+'$'])
            self.assertEqual(target.stat().st_mode&0o777,0o600);self.assertEqual(out.getvalue(),'')
            with mock.patch.dict(os.environ,{'CI':'true'}),self.assertRaises(GateError) as ctx:bp.install_fixture_pattern(repo,'local:'+str(data))
            self.assertNotIn('sample',str(ctx.exception))
            for spec in ('synthetic:tiny','local:'):
                with self.subTest(spec=spec),self.assertRaises(GateError):bp.install_fixture_pattern(repo,spec)

    def test_git_common_dir_takes_the_last_line_and_needs_a_directory(self):
        # T27-06: evidence.bounded merges stderr into stdout; a warning line before the path must not become the path
        with tempfile.TemporaryDirectory() as t:
            common=Path(t)/'common';common.mkdir();missing=Path(t)/'missing'
            def result(text,code=0):return {'exit_code':code,'failure':None,'output':text}
            with mock.patch.object(bp,'bounded',return_value=result('warning: synthetic notice\n'+str(common)+'\n\n')):
                self.assertEqual(bp._git_common_dir(ROOT),common)
            for text in (str(missing)+'\n','warning: synthetic notice\n'+str(missing)+'\n',str(common)+'\nwarning: synthetic notice\n',
                         'relative/dir\n','\n \n',''):
                with self.subTest(text=text),mock.patch.object(bp,'bounded',return_value=result(text)),self.assertRaises(GateError) as ctx:
                    bp._git_common_dir(ROOT)
                self.assertEqual(str(ctx.exception),'the git common directory was not found')
            with mock.patch.object(bp,'bounded',return_value=result(str(common)+'\n',code=1)),self.assertRaises(GateError):bp._git_common_dir(ROOT)
            afile=Path(t)/'afile';afile.write_text('x')
            with mock.patch.object(bp,'bounded',return_value=result(str(afile)+'\n')),self.assertRaises(GateError):bp._git_common_dir(ROOT)

    def test_hook_reads_path_patterns(self):
        hook=load_hook()
        with tempfile.TemporaryDirectory() as t:
            common=Path(t)/'common';(common/'info').mkdir(parents=True);home=Path(t)/'home';(home/'.config/safe-c-environment').mkdir(parents=True)
            (common/'info/personal-path-patterns').write_text('# comment\n^secret-dataset\\.json$\n\n')
            (home/'.config/safe-c-environment/personal-path-patterns').write_text('(unclosed\n^other-name\\.csv$\n')
            errors=[]
            with mock.patch.object(hook,'git',return_value=str(common)+'\n'),mock.patch.object(hook.Path,'home',return_value=home):
                got=hook.path_rules(errors)
            self.assertEqual(sorted(r.pattern for r in got),['^other-name\\.csv$','^secret-dataset\\.json$'])
            self.assertEqual(errors,['personal-path-patterns:1: invalid-private-path-pattern'])
            (common/'info/personal-path-patterns').unlink();(common/'info/personal-path-patterns').mkdir()    # unreadable: an error line
            errors=[]
            with mock.patch.object(hook,'git',return_value=str(common)+'\n'),mock.patch.object(hook.Path,'home',return_value=Path(t)/'nohome'):
                self.assertEqual(hook.path_rules(errors),[])
            self.assertEqual(errors,['personal-path-patterns: unreadable-private-path-patterns'])

    def test_hook_matches_the_base_name_only_and_masks_the_path(self):
        hook=load_hook()
        scanner=object.__new__(hook.Scanner)
        scanner.rules,scanner.findings,scanner.raw,scanner.pins=[],[],[],{}
        scanner.path_rules=[re.compile(r'^secret-dataset\.json$',re.I)]
        with mock.patch.object(hook,'git',return_value=b'secret-dataset.json\n'):
            scanner.blob('secret-dataset.json','secret-dataset.json',':')
            scanner.blob('0123456789ab:docs/Secret-Dataset.json','docs/Secret-Dataset.json','0123456789ab')
            scanner.blob('notes.txt','notes.txt',':')                       # content that names the file is not blocked
            scanner.blob('secret-dataset.json.bak','secret-dataset.json.bak',':')
            scanner.blob('secret-dataset.json/readme.txt','secret-dataset.json/readme.txt',':')   # a directory name is not the base name
        self.assertEqual(scanner.findings,['s'+'*'*18+': private-path-pattern','0123456789ab:d'+'*'*23+': private-path-pattern'])   # the masks keep the name length

    def test_run_local_installs_the_pattern_before_the_first_container(self):
        import bench
        class Stop(Exception):pass
        for fail in (False,True):
            order=[]
            def install(root,spec):
                order.append(('install',spec))
                if fail:raise GateError('the git common directory was not found')
                return True
            def probe(root,run_dir):order.append('doctor');raise Stop()
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as t,mock.patch.object(bp,'install_fixture_pattern',side_effect=install),\
                 mock.patch.object(bench,'doctor_probe',probe),mock.patch.object(bench,'BenchSession',side_effect=AssertionError('container')):
                with self.assertRaises(GateError if fail else Stop):
                    bp.run_local(Path(t),argparse.Namespace(format='json'),json.loads(json.dumps(PLAN)),{'case_id':'record-scan','version':1},{})
                self.assertEqual(order,[('install','local:/private/sample-name.json')]+([] if fail else ['doctor']))

    def test_privacy_pattern_operation_prints_only_the_fixed_line(self):
        import bench
        parser=argparse.ArgumentParser();bench.configure_parser(parser)
        for added,text in ((True,'privacy path pattern installed'),(False,'privacy path pattern already present')):
            for fmt in ('text','json'):
                args=parser.parse_args(['privacy-pattern','--dataset','local:/private/sample-name.json','--format',fmt]);out=io.StringIO()
                with self.subTest(added=added,fmt=fmt),mock.patch.object(bp,'install_fixture_pattern',return_value=added) as inst,contextlib.redirect_stdout(out):
                    rc=bench.execute(ROOT,args)
                self.assertEqual(rc,0);inst.assert_called_once_with(ROOT,'local:/private/sample-name.json')
                printed=out.getvalue().strip()
                self.assertEqual(printed if fmt=='text' else json.loads(printed)['result'],text);self.assertNotIn('sample-name',printed)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parser.parse_args(['privacy-pattern'])

if __name__=='__main__':
    unittest.main()
