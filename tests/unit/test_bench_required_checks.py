"""T29-APP-01 (P15 removed-safety-check): `bench validate` and `bench run` refuse a case whose project declaration drops a
before_run check that the project's protected protocol file (`before_run_required`) names for that case. FAIL (exit 1)
with a named reason before any container; the unmutated declaration reaches the launch step.

FR1 (FS1 F3): the project is the synthetic unit-test project tests/fixtures/bench-project. FR3 (design Task 32): its
protected protocol file names the required checks of the fixture case (REQUIRED); bench_model.load_policy(root, project)
takes them from there. The framework policy names no required check. The assertion that the example project's protocol
names every before_run check of its case moves with the example (FR1 report, FR3 handoff list)."""
import argparse, contextlib, copy, io, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm, container_policy

FIXTURE='tests/fixtures/bench-project';REQUIRED=['fixture-oracle','fixture-agreement']

class Launch(Exception):
    """Raised by the patched launch steps: the command passed the declaration check and went on to start work."""

def launch(*a,**k):raise Launch()

def policy(root=ROOT):
    """The policy of the fixture project: the framework policy plus the protocol's before_run_required."""
    return bm.load_policy(root,FIXTURE)

def example():
    project=FIXTURE;decl=bm.project_bench(ROOT,project)
    return project,decl,decl['cases'][0]

def run(command,case,project,decl):
    """(exit code, emitted JSON row or None, launched) of `bench validate` or `bench run` with `decl` as the project's
    bench.json; every launch step raises Launch."""
    out=io.StringIO();launched=False
    if command=='validate':args=argparse.Namespace(case=case,project=project,format='json')
    else:args=argparse.Namespace(case=case,plan=None,project=project,format='json',mode='smoke',dataset='synthetic:small',calibrate=None)
    real=bm.project_bench
    with mock.patch.object(bm,'project_bench',lambda root,p:copy.deepcopy(decl) if p==project else real(root,p)),\
         mock.patch.object(bm,'project_identity',lambda *a,**k:'a'*64),mock.patch.object(container_policy,'host_topology',launch),\
         mock.patch.object(bench,'new_run_dir',launch),mock.patch.object(bench,'BenchSession',launch),mock.patch.object(bench,'doctor_probe',launch),\
         contextlib.redirect_stdout(out):
        try:code=(bench.validate_case if command=='validate' else bench.run_cmd)(ROOT,args)
        except Launch:code,launched=None,True
    lines=out.getvalue().strip().splitlines()
    return code,(json.loads(lines[-1]) if lines else None),launched

def dropped(decl,name):
    d=copy.deepcopy(decl);d['checks']=[c for c in d['checks'] if c['name']!=name];return d

def switched_off(decl,name):
    d=copy.deepcopy(decl)
    for c in d['checks']:
        if c['name']==name:c['before_run']=False
    return d

class RequiredBeforeRunTests(unittest.TestCase):
    def test_the_fixture_protocol_names_every_before_run_check_of_the_fixture_case(self):
        # FR1: the fixture premise of the tests below (the example project's form of this test moved with the example).
        project,decl,case=example()
        required=policy()['before_run_required']
        self.assertEqual(required,bm.load_protocol(ROOT,FIXTURE)['before_run_required'])
        self.assertEqual(sorted(required[case]),sorted(REQUIRED))
        self.assertEqual(sorted(required[case]),sorted(c['name'] for c in decl['checks'] if c['before_run']))
        self.assertTrue(any('agreement' in n for n in required[case]))       # the agreement check is one of them
        self.assertEqual(bm.load_policy(ROOT)['before_run_required'],{})         # the framework policy names none

    def test_validate_and_run_refuse_a_dropped_or_switched_off_check_before_any_container(self):
        project,decl,case=example();required=policy()['before_run_required'][case]
        agreement=next(n for n in required if 'agreement' in n);other=next(n for n in required if n!=agreement)
        for command in ('validate','run'):
            for name,mutated in ((agreement,dropped(decl,agreement)),(other,switched_off(decl,other))):
                with self.subTest(command=command,check=name):
                    code,row,launched=run(command,case,project,mutated)
                    self.assertFalse(launched)
                    self.assertEqual((code,row['status']),(1,'FAIL'))
                    self.assertIn('removed safety check',row['reason']);self.assertIn(name,row['reason'])

    def test_the_unmutated_declaration_and_a_framework_case_reach_the_launch_step(self):
        project,decl,case=example()
        for command in ('validate','run'):
            with self.subTest(command=command):self.assertEqual(run(command,case,project,decl),(None,None,True))
            with self.subTest(command=command,case='bench-control-spin'):self.assertEqual(run(command,'bench-control-spin',None,None),(None,None,True))

    def test_every_dropped_check_is_named(self):
        project,decl,case=example();pol=policy();required=pol['before_run_required'][case]
        self.assertEqual(bm.dropped_before_run_checks(pol,case,decl),[])
        none=dict(decl,checks=[c for c in decl['checks'] if c['name'] not in required])
        reasons=bm.dropped_before_run_checks(pol,case,none)
        self.assertEqual(len(reasons),len(required));self.assertTrue(all(n in r for n,r in zip(required,reasons)))
        self.assertEqual(len(bm.dropped_before_run_checks(pol,case,None)),len(required))     # no declaration: every check missing
        self.assertEqual(bm.dropped_before_run_checks(pol,'bench-control-spin',None),[])      # a case without an entry

    def test_the_protocol_schema_checks_the_declaration(self):
        from schema_check import validate
        from evidence import GateError
        proto=bm.load_protocol(ROOT,FIXTURE)
        self.assertTrue(validate(ROOT,'bench-protocol',proto))
        with self.assertRaises(GateError):validate(ROOT,'bench-protocol',dict(proto,before_run_required={'x':['Bad Name']}))
        with self.assertRaises(GateError):validate(ROOT,'bench-protocol',dict(proto,before_run_required={'fixture-case':[]}))


class ProbeDeclarationTests(unittest.TestCase):
    """T14-A01 (ruling R37): the P15 control removed-safety-check copies each project's bench.json into a probe project
    (bench_phase3._declared) and reads only its case list and checks (bm.dropped_before_run_checks). The probe holds no file
    of the project, so it carries no binding to one: neither `protocol` (FR3) nor `third_party` (the lock). Before the fix,
    a project that binds a lock made the probe refuse itself ('third-party lock is missing')."""
    def locked(self):
        """The fixture declaration (with its protocol binding) plus a third-party lock binding, as a project with wheels has."""
        decl=copy.deepcopy(bm.project_bench(ROOT,FIXTURE));decl['third_party']={'file':'third_party/lock.json','sha256':'0'*64};return decl

    def test_the_probe_of_a_declaration_with_a_lock_binding_holds_the_checks_and_no_binding(self):
        import bench_phase3 as b3
        decl=self.locked();self.assertIn('protocol',decl)
        with tempfile.TemporaryDirectory() as t:got=b3._declared(ROOT,Path(t),decl)
        self.assertEqual(got,{k:v for k,v in decl.items() if k not in ('protocol','third_party')})
        self.assertEqual(bm.dropped_before_run_checks(policy(),decl['cases'][0],got),[])

    def test_the_removed_safety_check_passes_on_a_project_that_binds_a_lock(self):
        import bench_phase3 as b3
        real=bm.project_bench;decl=self.locked()
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bm,'project_bench',lambda root,p:copy.deepcopy(decl) if p==FIXTURE else real(root,p)):
            self.assertEqual(b3._removed_safety_check(ROOT,Path(t),FIXTURE),(True,True))     # (mutations refused, control passes)
        with tempfile.TemporaryDirectory() as t:                                             # control: the fixture as it is
            self.assertEqual(b3._removed_safety_check(ROOT,Path(t),FIXTURE),(True,True))

class ProbeNativeTests(unittest.TestCase):
    """T6R4-A02 (T6-R5): a project whose bench.json holds a `native` block and whose protocol requires the native agreement
    check in before_run_required. The P15 mutation _without drops that check; the probe must not keep `native`, which the
    control does not read (it keeps schema_version, name, cases, checks), else the mutation raises 'bench.json native:
    agreement names no declared check' and P15 fails on a false reason."""
    def native(self):
        decl=copy.deepcopy(bm.project_bench(ROOT,FIXTURE))
        decl['native']={'kernel':{'program':'kernel','args':['{input}','{records}','{loops}','{output}']},'agreement':'fixture-agreement'}
        return decl

    def test_the_probe_of_a_declaration_without_its_agreement_check_holds_no_native_block(self):
        import bench_phase3 as b3
        decl=self.native();mutated=b3._without(decl,'fixture-agreement')
        with tempfile.TemporaryDirectory() as t:got=b3._declared(ROOT,Path(t),mutated)
        self.assertEqual(sorted(got),['cases','checks','name','schema_version'])
        self.assertTrue(bm.dropped_before_run_checks(policy(),decl['cases'][0],got))

    def test_the_removed_safety_check_passes_on_a_project_with_a_native_agreement_check(self):
        import bench_phase3 as b3
        real=bm.project_bench;decl=self.native()
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bm,'project_bench',lambda root,p:copy.deepcopy(decl) if p==FIXTURE else real(root,p)):
            self.assertEqual(b3._removed_safety_check(ROOT,Path(t),FIXTURE),(True,True))

if __name__=='__main__':unittest.main()
