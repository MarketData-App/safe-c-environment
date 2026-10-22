"""FR3-19 (ruling FR3-R9): every host parse of JSON that a project or a container can write goes through the capped
boundary of tools/evidence.py (the size cap, strict UTF-8 and the 64-level depth cap checked on the raw text before the
parse). Deep nesting at each reader gives GateError (also a ValueError, so a reader that refuses a malformed document
keeps its refusal value), never RecursionError. An inventory test keeps every other json.load/json.loads call out of
the host tools, except the listed trusted framework files that no project or container can write."""
import ast, functools, importlib.util, io, json, math, os, sys, tarfile, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError

DEEP=10**5
DEEP_ARRAYS='['*DEEP+']'*DEEP                    # one JSON line of 10**5 levels
DEEP_OBJECT='{"a":'*DEEP+'0'+'}'*DEEP            # starts with {, so last_json and the JSON-lines readers try it

# Trusted framework files that no project or container can write (reader: reason). A plain json.load stays there.
TRUSTED={('tools/bench_plan.py','artifact_bytes'):'safety/container-policy.json of the framework tree (tools/../safety)',
         ('tools/bench_units.py','load_local_evidence'):'safety/contract.json of the framework root',
         ('tools/bench_phase3.py','_edit_policy'):'a framework-written copy of safety/performance-policy.json in a B-case mini root',
         ('tools/evidence.py','_parse'):'the boundary itself, after the size and depth caps',
         # the developer image assembly recipe is pinned by sha256 in developer.lock.json (assembly_recipe_sha256); an edit
         # needs image requalification. It runs only at acquisition, on the Docker daemon output and the archive it saved.
         ('tools/assemble_developer_image.py','load'):'pinned assembly recipe: the saved image archive documents',
         ('tools/assemble_developer_image.py','main'):'pinned assembly recipe: Docker daemon image listing and inspect output',
         # FR3-22: the privacy hook is self-contained (it imports nothing from tools/); its own capped reader
         ('.githooks/personal_info_check.py','lock_json'):'capped reader of the hook: a 64 MiB size cap before the parse; '
             'ValueError, RecursionError and MemoryError give None (no pins), so a malformed lock file never crashes the hook',
         # FR4P-01 (ruling FR5-R2): the host loads these two container files (HOST_LOADED); these functions run only in the
         # foundation build container, from the file's own __main__ path, never on the host
         ('container/build-foundation.py','prepare'):'container only (__main__ path): the pinned acquisition record and the '
             'protected test adaptation file of the read-only /src tree',
         ('container/build-foundation.py','package'):'container only (__main__ path): the build records that this recipe wrote '
             'in its own build directory and the protected test adaptation file of the read-only /src tree'}

# FR4P-01 (ruling FR5-R2): container files that host tools load with exec_module (file: (host loader, the names it uses)).
# They are scanned like every host file; the host uses only the listed names, which parse no JSON.
HOST_LOADED={'container/build-foundation.py':('tools/build_foundation_sdk.py','recipe',('PROFILES','UPSTREAM_TESTS')),
             'container/foundation-policy-probe.py':('tools/foundation.py','module',('definitions',)),
             # T5R1-A01: the planned work of a trial, one file for the host rules and the rules inside a local decision job
             'container/bench_trial_work.py':('tools/bench_plan.py','trial_work',('PANEL_ROWS_PER_CALL','planned_work_units','request_rows'))}

# FR4P-02 (ruling FR5-R2): every json.load/json.loads call of the inline Python of the CI workflow files (a heredoc
# `python3 - <<'EOF'` block or a `python3 -c "..."` command), with its reason. CAPPED: the inline script reads at most
# its cap first and turns a deep document into a job failure (fail closed).
WORKFLOWS=('.github/workflows/safety.yml','.github/workflows/example.yml','ci/project-ci.yml')
WORKFLOW_PARSES={'/etc/docker/daemon.json':'CAPPED: the runner Docker configuration (not a framework file): a 1 MiB read cap, '
                     'strict UTF-8 and a RecursionError guard before the parse; any failure stops the job',
                 'ci/image-bundle.json':'framework file: the tracked, protected image bundle record of the checkout; no project '
                     'or container writes it before this step, and a malformed file stops the job'}

# FR3-22: the inventory covers every exported host-run Python file (a .py file or a python3 script). These areas run only
# inside the protected containers or are upstream data, never on the host (area: reason).
IN_CONTAINER={'container/':'container entry points and helpers; they run inside the protected Docker launcher (the files '
                            'that a host tool loads are scanned: HOST_LOADED)',
              'benchmarks/':'bench workloads and their tests; they run inside bench containers',
              'tests/':'unit and container tests; ./tools/safety runs them inside the protected launcher',
              'fuzz/':'fuzz harness data; built and run inside containers',
              'foundation/':'foundation sources and tests; built and run inside containers',
              'safety/lit/':'lit configuration; lit runs inside the analyzer container',
              'safety/qualification/':'qualification probes and fixtures; they run inside containers',
              'third_party/':'upstream files; never executed on the host by the framework',
              'examples/':'example project data; a project check runs it inside containers'}

def is_python(path):
    if path.suffix=='.py':return True
    try:
        with open(path,'rb') as handle:first=handle.readline(128)
    except OSError:return False
    return first.startswith(b'#!') and b'python' in first

@functools.lru_cache(maxsize=1)
def host_python_files():
    """Every exported host-run Python file (starter-export.json), outside the IN_CONTAINER areas."""
    out=[]
    for rel in json.loads((ROOT/'starter-export.json').read_text())['files']:
        p=ROOT/rel
        if (rel.startswith(tuple(IN_CONTAINER)) and rel not in HOST_LOADED) or not p.is_file() or p.is_symlink():continue
        if is_python(p):out.append(rel)
    return tuple(sorted(out))

import re
CALL_TEXT=re.compile(r'\bjson\s*\.\s*loads?\b')

@functools.lru_cache(maxsize=1)
def host_json_calls():
    """(file, function, line) of each json.load/json.loads call in every host Python file (an in-container code string is
    no call; json.loads(json.dumps(x)) is a deep copy, not a parse)."""
    out=[]
    for rel in host_python_files():
        text=(ROOT/rel).read_text()
        if not CALL_TEXT.search(text):continue       # FR3-R10: no call is possible without this text; parse only the rest
        stack=[(ast.parse(text),None)]
        while stack:
            node,fn=stack.pop()
            for ch in ast.iter_child_nodes(node):
                inner=ch.name if isinstance(ch,(ast.FunctionDef,ast.AsyncFunctionDef)) else fn
                if (isinstance(ch,ast.Call) and isinstance(ch.func,ast.Attribute) and ch.func.attr in ('load','loads')
                        and isinstance(ch.func.value,ast.Name) and ch.func.value.id=='json'):
                    a=ch.args[0] if ch.args else None
                    if not (isinstance(a,ast.Call) and isinstance(a.func,ast.Attribute) and a.func.attr=='dumps'):
                        out.append((rel,fn,ch.lineno))
                stack.append((ch,inner))
    return tuple(out)

class InventoryTests(unittest.TestCase):
    def test_every_host_json_parse_goes_through_the_boundary(self):
        stray=sorted((f,fn,line) for f,fn,line in host_json_calls() if (f,fn) not in TRUSTED)
        self.assertEqual(stray,[],f'{len(stray)} host json.load/json.loads calls outside the boundary')
    def test_no_host_tool_imports_a_json_parser_under_another_name(self):
        import re
        pattern=re.compile(r'^\s*(from\s+json\s+import|import\s+json\s+as)\b',re.M)
        self.assertEqual(sorted(rel for rel in host_python_files() if pattern.search((ROOT/rel).read_text())),[])
    def test_the_inventory_covers_every_host_python_file(self):
        """FR3-22: the hooks, the ci scripts, tools/safety and every tools module are scanned; each excluded area names its
        reason and holds exported files."""
        files=set(host_python_files())
        for rel in ('.githooks/personal_info_check.py','ci/runner-request','ci/images','tools/safety','tools/evidence.py',
                    'tools/acquire_bench_wheels.py','ci/changed-examples'):      # amendment E: the example.yml job selection
            with self.subTest(path=rel):self.assertIn(rel,files)
        self.assertEqual(sorted(rel for rel in files if rel.startswith('tools/') and rel.count('/')==1 and rel.endswith('.py')),
                         sorted('tools/'+p.name for p in (ROOT/'tools').glob('*.py')))
        exported=json.loads((ROOT/'starter-export.json').read_text())['files']
        for area,reason in IN_CONTAINER.items():
            with self.subTest(area=area):
                self.assertTrue(reason);self.assertTrue(any(rel.startswith(area) for rel in exported))
    def test_the_hook_lock_reader_is_capped(self):
        """FR3-22: a deep, oversized or malformed lock file gives no pins instead of an exception in the privacy hook."""
        spec=importlib.util.spec_from_file_location('personal_info_check_fr322',ROOT/'.githooks/personal_info_check.py')
        hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
        self.assertIsNone(hook.lock_json(DEEP_ARRAYS.encode()))
        self.assertIsNone(hook.lock_json(DEEP_OBJECT.encode()))
        self.assertIsNone(hook.lock_json(b'{'))
        self.assertIsNone(hook.lock_json(b' '*(hook.LOCK_MAX_BYTES+1)))
        self.assertEqual(hook.lock_json(b'{"a":"'+b'0'*64+b'"}'),{'a':'0'*64})
        self.assertEqual(hook.LOCK_MAX_BYTES,67108864)
        scanner=object.__new__(hook.Scanner);scanner.pins={}
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d);Path(d,'developer.lock.json').write_text(DEEP_ARRAYS)
                Path(d,'toolchain.lock.json').write_text(json.dumps({'image_id':'sha256:'+'1'*64}))
                self.assertEqual(scanner.pinned(None),{('image_id','1'*64),('sha256:'+'1'*64,'1'*64)})    # the deep lock adds no pin
            finally:os.chdir(old)
    def test_the_runner_request_parses_docker_output_through_the_boundary(self):
        """FR3-22: ci/runner-request reads the policy and the locks with read_json and the Docker output with loads_capped."""
        text=(ROOT/'ci/runner-request').read_text()
        self.assertNotRegex(text,CALL_TEXT)
        self.assertEqual(text.count('loads_capped('),2)
    def test_each_trusted_reader_exists(self):
        found={(f,fn) for f,fn,_ in host_json_calls()}
        self.assertEqual(sorted(set(TRUSTED)-found),[])
    def test_the_host_loaded_container_files_are_scanned(self):
        """FR4P-01: the container files that a host tool loads are in the inventory; the host uses only the listed names,
        and the module body runs no function except under its __main__ guard."""
        files=set(host_python_files())
        for rel,(loader,var,names) in HOST_LOADED.items():
            with self.subTest(path=rel):
                self.assertIn(rel,files)
                src=(ROOT/loader).read_text();self.assertIn(rel,src)
                self.assertEqual(sorted(set(re.findall(r'\b'+var+r'\.([A-Za-z_]+)\b',src))-{'loader'}),sorted(names))
                tree=ast.parse((ROOT/rel).read_text())
                for node in tree.body:
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue        # a definition runs no code
                    if isinstance(node,ast.If) and ast.unparse(node.test)=="__name__ == '__main__'":continue
                    calls=[c for c in ast.walk(node) if isinstance(c,ast.Call) and isinstance(c.func,ast.Name)
                           and c.func.id in {f.name for f in tree.body if isinstance(f,ast.FunctionDef)}]
                    self.assertEqual(calls,[],f'{rel}: module code calls a function outside the __main__ guard')
    def test_every_workflow_inline_json_parse_is_listed(self):
        """FR4P-02 with FR5A-06: the inline Python of each CI workflow file is parsed; each json.load/json.loads call is
        bound to exactly one listed target (through the names that feed its argument), and the CAPPED reader holds its cap
        and its depth guard."""
        seen=set()
        for rel in WORKFLOWS:
            scripts=workflow_scripts((ROOT/rel).read_text())
            with self.subTest(path=rel):
                self.assertGreaterEqual(len(scripts),3)
                for code in scripts:
                    for call,targets in parse_targets(code):
                        self.assertEqual(len(targets),1,f'{rel}: a json parse at line {call.lineno} has no single listed target: {sorted(targets)}')
                        target=next(iter(targets));seen.add(target)
                        if WORKFLOW_PARSES[target].startswith('CAPPED'):
                            self.assertRegex(code,r'\.read\(1048577\)');self.assertIn('1048576',code)
                            self.assertIn("decode('utf-8')",code);self.assertIn('except RecursionError',code)
        self.assertEqual(seen,set(WORKFLOW_PARSES))
    def test_the_binding_is_per_parse_call(self):
        """FR5A-06: a script that parses a listed file and also another file fails, although the listed name is in it."""
        code=("import json\npath = '/etc/docker/daemon.json'\nwith open(path, 'rb') as f:\n    data = f.read(1048577)\n"
              "config = json.loads(data)\nother = json.load(open('/tmp/other.json'))\nx = json.loads(json.dumps(config))\n")
        got=[sorted(t) for _,t in parse_targets(code)]
        self.assertEqual(got,[['/etc/docker/daemon.json'],[]])         # the deep copy is no parse; the second parse has no listed target
        self.assertEqual(workflow_scripts('run: x=$(python3 -c "import json;print(json.load(open(\\"ci/image-bundle.json\\"))[\'url\'])")\n'),
                         ['import json;print(json.load(open(\\"ci/image-bundle.json\\"))[\'url\'])'])   # an escaped quote ends no -c string

def parse_targets(code):
    """(call, {listed targets}) for each json.load/json.loads call of one script (json.loads(json.dumps(x)) is a copy). The
    targets are the WORKFLOW_PARSES keys among the string constants that reach the call argument, directly or through the
    assignments and `with ... as` names of the script that feed it."""
    tree=ast.parse(code);feeds={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for t in node.targets:
                if isinstance(t,ast.Name):feeds.setdefault(t.id,[]).append(node.value)
        elif isinstance(node,ast.withitem) and isinstance(node.optional_vars,ast.Name):
            feeds.setdefault(node.optional_vars.id,[]).append(node.context_expr)
    def reach(expr,seen):
        out=set()
        for n in ast.walk(expr):
            if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in WORKFLOW_PARSES:out.add(n.value)
            elif isinstance(n,ast.Name) and n.id not in seen:
                seen.add(n.id)
                for v in feeds.get(n.id,[]):out|=reach(v,seen)
        return out
    out=[]
    for c in ast.walk(tree):
        if (isinstance(c,ast.Call) and isinstance(c.func,ast.Attribute) and c.func.attr in ('load','loads')
                and isinstance(c.func.value,ast.Name) and c.func.value.id=='json' and c.args):
            a=c.args[0]
            if isinstance(a,ast.Call) and isinstance(a.func,ast.Attribute) and a.func.attr=='dumps':continue
            out.append((c,reach(a,set())))
    return sorted(out,key=lambda x:(x[0].lineno,x[0].col_offset))

def workflow_scripts(text):
    """The inline Python of a workflow file: each `python3 - <<'EOF'` heredoc body (dedented) and each `python3 -c "..."`
    code string (a backslash-escaped quote stays inside the string)."""
    import textwrap
    out=[textwrap.dedent(m.group(1)) for m in re.finditer(r"python3 - <<'EOF'\n(.*?)\n[ ]*EOF\n",text,re.S)]
    out+=[m.group(1) for m in re.finditer(r'python3 -c "((?:[^"\\]|\\.)*)"',text)]
    return out

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.d=Path(tempfile.mkdtemp(prefix='safe-c-capped-'));self.addCleanup(__import__('shutil').rmtree,self.d,True)
    def file(self,rel,text):
        p=self.d/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    def assertDeep(self,ctx):
        self.assertIsInstance(ctx.exception,ValueError)
        self.assertIn('too-deep',str(ctx.exception))

    def test_read_json(self):
        from evidence import read_json
        with self.assertRaises(GateError) as ctx:read_json(self.file('deep.json',DEEP_ARRAYS))
        self.assertDeep(ctx)
        self.assertEqual(read_json(self.file('cap.json','['*64+']'*64)),json.loads('['*64+']'*64))   # 64 levels load
        with self.assertRaises(GateError):read_json(self.file('past.json','['*65+']'*65))
        self.assertTrue(math.isnan(read_json(self.file('nan.json','[NaN]'))[0]))        # NaN stays allowed (atomic_json may write it)
        with self.assertRaises(FileNotFoundError):read_json(self.d/'missing.json')                    # OSError unchanged
    def test_schema_validate_reads_a_capped_schema(self):
        from schema_check import validate
        self.file('schemas/deep.json',DEEP_OBJECT)
        with self.assertRaises(GateError):validate(self.d,'deep',{})
    def test_bench_jsonl_rows_and_last_json(self):
        import bench
        with self.assertRaises(GateError) as ctx:bench.read_jsonl(self.file('observations.jsonl','{"a":1}\n'+DEEP_OBJECT+'\n'))
        self.assertDeep(ctx)
        with self.assertRaises(GateError):bench._rows('{"a":1}\n'+DEEP_ARRAYS)
        self.assertEqual(bench.last_json('x\n'+DEEP_OBJECT),{})
    def test_readiness_jsonl(self):
        import bench_readiness
        self.assertIsNone(bench_readiness._jsonl(self.file('rows.jsonl',DEEP_OBJECT)))
    def test_unit_records(self):
        import bench_units
        self.assertEqual(bench_units._read_object(self.file('coverage.json',DEEP_OBJECT)),(None,None))
    def test_calibration_observations(self):
        import bench_plan
        rid='0'*32;self.file(f'artifacts/bench/{rid}/observations.jsonl',DEEP_OBJECT+'\n')
        with self.assertRaises(GateError):bench_plan.calibration_record(self.d,rid,None)
    def test_local_merged_accounting(self):
        import bench_accounting
        self.file('run/local-merged.json',DEEP_OBJECT)
        with self.assertRaises(GateError):bench_accounting.recheck({'dataset':{'kind':'local'}},self.d/'run')
    def test_b18_records(self):
        import bench_b18
        from policy import TRACKED_MANIFEST
        self.file(TRACKED_MANIFEST,DEEP_OBJECT)
        with self.assertRaises(GateError):bench_b18.tracked_files(self.d,['tools'])
        self.file('artifacts/bench/'+'1'*32+'/run.json',DEEP_OBJECT)
        self.assertEqual(bench_b18.bench_runs(self.d),[{'unreadable':True,'run_id':'1'*32}])
        child=self.d/'child';(child/'artifacts').mkdir(parents=True)
        (child/'artifacts/bootstrap-report.json').write_text(DEEP_OBJECT)
        self.assertIsNone(bench_b18._report(child))
        (child/'artifacts/bootstrap-report.json').write_text(json.dumps({'source_identity':'c','local_state':'PASS','gates':[]}))
        run=child/'artifacts/bench'/('2'*32);run.mkdir(parents=True);(run/'run.json').write_text(DEEP_OBJECT)
        self.assertTrue(any('no VALID' in p for p in bench_b18._measured(child,'p','c')))
    def test_phase3_rewrite_of_a_container_row(self):
        import bench_phase3
        p=self.file('obs.jsonl',DEEP_OBJECT+'\n');bench_phase3._rewrite(p)
        self.assertTrue(p.read_text().endswith(' '))
    def test_ctest_inventory(self):
        import project_check
        with self.assertRaises(GateError):project_check.parse_ctest_names(DEEP_OBJECT)
    def test_diagnostic_summary(self):
        import diagnostic_summary
        diagnostic_summary.reduce_file(self.file('evidence.json',DEEP_OBJECT),'case')       # no exception escapes
    def test_image_metadata(self):
        import image_transfer
        buf=io.BytesIO();data=('['*2000).encode()          # 2000 levels: inside the 1 MiB metadata bound
        with tarfile.open(fileobj=buf,mode='w') as t:
            info=tarfile.TarInfo('manifest.json');info.size=len(data);t.addfile(info,io.BytesIO(data))
        buf.seek(0)
        with tarfile.open(fileobj=buf) as t, self.assertRaises(GateError):image_transfer.metadata(t,t.getmember('manifest.json'))

if __name__=='__main__':
    unittest.main()
