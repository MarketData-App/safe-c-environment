"""G-ALO-CO part 1 (spec Amendment I, item I13.1 step 7c), option-chain case: an adapter is built only through
benchlab.workload.construct_adapter. The case declares single-threaded variants only (owner 2026-10-16), so its adapter is not
pooled and keeps no request limit; a pooled construction through the helper still gives the policy limit. The market adapter
(with_market) is a copy of the adapter with the same bench_ref (FR5 item 10: no method of a manifest adapter class calls its own
class). The coordinator's SYNTH_CODE and REFERENCE_CODE (the latter also on a local dataset, which takes the market step of the
adapter load since EX-6; MARKET_CODE left the framework in FR3) run with SAFE_C_BENCH_REQUEST_LIMIT set and fail with the
helper's message when neither the variable nor the policy gives the limit. The project-scope construction guard (FIX1-A01,
EXL-CONSTRUCTION-GUARD-01) is OptionConstructionGuardTests below."""
import ast, hashlib, importlib.util, json, os, re, shutil, struct, subprocess, tempfile, unittest
from pathlib import Path
from benchlab.workload import construct_adapter, load_case_adapter
from optionlab.adapter import OptionChainGreeks
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')
POLICY=json.loads(Path('/src/safety/performance-policy.json').read_text())
LIMIT=POLICY['pools']['request_limit'];R=0.0435
ENV='SAFE_C_BENCH_REQUEST_LIMIT';HELPER='benchlab.workload.construct_adapter'
def _load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
FRAMEWORK='/src/benchmarks/performance/python';PROJECT='/src/examples/option-pricing-benchmark/benchmarks/project/python'

class OptionConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a=load_case_adapter(json.loads(CASE_FILE.read_text()))
        data=cls.a.synthesize(20000,7);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        cls.ds={'path':str(p),'sha256':hashlib.sha256(data).hexdigest()};cls.chain=cls.a.load(cls.ds)
    def test_the_helper_gives_the_policy_limit_to_a_pooled_construction_only(self):
        self.assertEqual(os.environ.get(ENV),str(LIMIT));self.assertEqual(LIMIT,14336)
        self.assertEqual((self.a.request_limit,self.a.bench_ref),(None,('optionlab.adapter:OptionChainGreeks',self.a.raw)))    # not pooled
        b=construct_adapter('optionlab.adapter:OptionChainGreeks',self.a.raw,selector='bsm',pooled=True)
        self.assertEqual((b.request_limit,b.bench_ref),(LIMIT,('optionlab.adapter:OptionChainGreeks',self.a.raw,'bsm',LIMIT)))
    def test_the_market_adapter_is_a_copy_with_the_same_ref(self):
        from optionlab import market, synthetic
        data=synthetic.as_local_sample(self.a.synthesize(256,7));p=Path(tempfile.mkdtemp())/'local.json';p.write_bytes(data)
        ds={'path':str(p),'sha256':hashlib.sha256(data).hexdigest()};local=self.a.load(ds)      # an owner-like dataset: the market step runs in load
        m=self.a.market_parameters(local);self.assertTrue(m['date_ok'])
        b=self.a.with_market(m['table']);self.assertIsNot(b,self.a);self.assertIs(type(b),type(self.a))
        self.assertEqual((b.request_limit,b.bench_ref,b.selector,b.raw),(self.a.request_limit,self.a.bench_ref,self.a.selector,self.a.raw))
        rate=market.protocol_rate()['continuous_rate']
        self.assertIsNone(self.a.market);self.assertEqual(b.market['rate'],rate)
        chain=b.load(ds);self.assertEqual(chain['n'],256);self.assertEqual(set(chain['r']),{rate});self.assertNotEqual(chain['r'],self.chain['r'][:256])

class CoordinatorCodeTests(unittest.TestCase):
    """The code strings of container/bench-coordinator.py, run as the coordinator runs them (isolated child, BOOT)."""
    @classmethod
    def setUpClass(cls):
        cls.bc=_load('bench_coordinator_oc','/src/container/bench-coordinator.py')
        cls.tmp=Path(tempfile.mkdtemp());cls.copy=cls.tmp/'copy'      # a benchlab copy outside any repository: no policy file
        shutil.copytree(FRAMEWORK+'/benchlab',cls.copy/'benchmarks/performance/python/benchlab',ignore=shutil.ignore_patterns('__pycache__'))
    def run_code(self,code,args,env_limit=True,policy=True):
        path=':'.join(['/opt/bench-python',FRAMEWORK if policy else str(self.copy/'benchmarks/performance/python'),PROJECT])
        env={k:v for k,v in os.environ.items() if k!=ENV}
        if env_limit:env[ENV]=str(LIMIT)
        return subprocess.run(self.bc.python_argv(path,'-c',code,*args),env=env,capture_output=True,text=True,timeout=600)
    def test_synth_and_reference_code_use_the_helper_limit(self):
        """Property (was ..._synth_reference_and_market_code_...; MARKET_CODE left the framework, FR3): every coordinator code string that
        builds the adapter builds it through the helper, so it takes the request limit from the variable or the policy and fails with the
        helper's message without both. The E counterpart of MARKET_CODE is the market step of the adapter load, run here by REFERENCE_CODE
        on a local dataset (a relabeled synthetic one)."""
        from optionlab import synthetic
        target=self.tmp/'data.json';ref=self.tmp/'reference.json';local=self.tmp/'local.json';lref=self.tmp/'local-reference.json'
        synth=[str(target),'256','20261007',str(CASE_FILE)]
        r=self.run_code(self.bc.SYNTH_CODE,synth);self.assertEqual(r.returncode,0,'SYNTH_CODE failed')
        sha=hashlib.sha256(target.read_bytes()).hexdigest()
        r=self.run_code(self.bc.REFERENCE_CODE,[str(CASE_FILE),str(target),sha,str(ref),'256']);self.assertEqual(r.returncode,0,'REFERENCE_CODE failed')
        self.assertEqual(json.loads(ref.read_text())['n'],256)
        data=synthetic.as_local_sample(target.read_bytes());local.write_bytes(data);lsha=hashlib.sha256(data).hexdigest()
        largs=[str(CASE_FILE),str(local),lsha,str(lref),'256']
        r=self.run_code(self.bc.REFERENCE_CODE,largs);self.assertEqual(r.returncode,0,'REFERENCE_CODE failed on a local dataset')
        self.assertEqual(json.loads(lref.read_text())['n'],256);self.assertNotEqual(lref.read_bytes(),ref.read_bytes())    # the protocol rate priced it
        # the variable alone (a benchlab copy without a policy file) is enough
        self.assertEqual(self.run_code(self.bc.SYNTH_CODE,synth,policy=False).returncode,0,'SYNTH_CODE failed with the variable alone')
        # neither the variable nor a policy file: each code string fails with the helper's message
        for name,code,args in (('SYNTH_CODE',self.bc.SYNTH_CODE,synth),('REFERENCE_CODE',self.bc.REFERENCE_CODE,[str(CASE_FILE),str(target),sha,str(ref),'256']),
                               ('REFERENCE_CODE on a local dataset',self.bc.REFERENCE_CODE,largs)):
            r=self.run_code(code,args,env_limit=False,policy=False)
            with self.subTest(code=name):
                self.assertNotEqual(r.returncode,0);self.assertIn('ValueError: request_limit:',r.stderr);self.assertIn(HELPER,r.stderr)
    def test_reference_code_covers_the_planned_selectors(self):
        """R48 (T6-R6; task M2c, T6R6-A01): REFERENCE_CODE with the reference selector `all` and a cover list (argv 9: the sorted
        selectors of the case, as container reference_path sends them) calls the adapter's reference_cover. The child writes the
        .cover file with the list, one reference.json from which the adapter of each listed selector takes exactly its own
        reference (every column; the binary64 bits, both after the JSON round trip), and the count files of every covered model
        (.evals: the five models with the totals of their own references; .admit: the baw admission block). Without a list the
        child computes the reference of `all`, as before, and writes no .cover file."""
        from optionlab.contract import ALL_MODELS, MODELS5
        case=json.loads(CASE_FILE.read_text());cover=sorted(case['selectors']);self.assertEqual(len(cover),6)
        target=self.tmp/'cover-data.json';ref=self.tmp/'cover-reference.json';plain=self.tmp/'plain-reference.json'
        r=self.run_code(self.bc.SYNTH_CODE,[str(target),'32','20261007',str(CASE_FILE)]);self.assertEqual(r.returncode,0,'SYNTH_CODE failed')
        sha=hashlib.sha256(target.read_bytes()).hexdigest();head=[str(CASE_FILE),str(target),sha]
        r=self.run_code(self.bc.REFERENCE_CODE,head+[str(ref),'32','[]','0','all',json.dumps(cover)]);self.assertEqual(r.returncode,0,'REFERENCE_CODE failed with a cover list')
        self.assertEqual(json.loads(Path(f'{ref}.cover').read_text()),cover)
        got=json.loads(ref.read_text());self.assertEqual((got['n'],list(got['models'])),(32,list(MODELS5)))
        own={}
        for s in cover:
            b=load_case_adapter(case,selector=s);chain=b.slice(b.load({'path':str(target),'sha256':sha}),32);own[s]=json.loads(json.dumps(b.reference(chain)))
            with self.subTest(selector=s):self.assertEqual(_bits(b.selected(got)),_bits(own[s]))
        self.assertEqual(json.loads(Path(f'{ref}.evals').read_text()),{m:sum(own[m]['models'][m]['engine_evals']) for m in MODELS5})
        self.assertEqual(json.loads(Path(f'{ref}.admit').read_text()),load_case_adapter(case,selector='baw').reference_exclusions(own['baw']))
        r=self.run_code(self.bc.REFERENCE_CODE,head+[str(plain),'32','[]','0','all']);self.assertEqual(r.returncode,0,'REFERENCE_CODE failed without a list')
        self.assertFalse(Path(f'{plain}.cover').exists());base=json.loads(plain.read_text())
        self.assertEqual(list(base['models']),list(ALL_MODELS));self.assertEqual(_bits(base),_bits(own['all']))

def _bits(x):
    """`x` with every float replaced by the hex of its binary64 bits: exact equality of two references."""
    if isinstance(x,float):return 'f'+struct.pack('<d',x).hex()
    if isinstance(x,dict):return {k:_bits(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [_bits(v) for v in x]
    return x

def _call_name(func):return func.id if isinstance(func,ast.Name) else func.attr if isinstance(func,ast.Attribute) else None

def construction_violations(source,path,classes):
    """(path, line, rule) of every construction of a manifest adapter class outside benchlab.workload.construct_adapter: a
    direct constructor call (inside a method of the class too: FR5C-01, no method name is exempt), an aliased call, type(...)(...),
    <expr>.__class__(...), a factory call and an adapter factory resolved by getattr on an imported module. The same rules as
    tests/unit/test_bench_construction.py (the framework guard), applied to this standalone example (FIX1-A01)."""
    tree=ast.parse(source);found=[];aliases={}
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):aliases.update({a.asname:a.name for a in node.names if a.name in classes and a.asname and a.asname!=a.name})
        if isinstance(node,ast.Assign) and isinstance(node.value,(ast.Name,ast.Attribute)) and _call_name(node.value) in classes:
            aliases.update({t.id:_call_name(node.value) for t in node.targets if isinstance(t,ast.Name)})
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call):continue
        name=_call_name(node.func)
        if name in classes:found.append((path,node.lineno,'direct constructor call '+name))
        if isinstance(node.func,ast.Name) and node.func.id in aliases:found.append((path,node.lineno,'aliased constructor call '+node.func.id))
        if name=='factory':found.append((path,node.lineno,'factory call'))
        if isinstance(node.func,ast.Call) and _call_name(node.func.func)=='getattr':found.append((path,node.lineno,'getattr(...)(...) call'))
        if isinstance(node.func,ast.Call) and isinstance(node.func.func,ast.Name) and node.func.func.id=='type':found.append((path,node.lineno,'type(...)(...) call'))
        if isinstance(node.func,ast.Attribute) and node.func.attr=='__class__':found.append((path,node.lineno,'__class__(...) call'))
        if name=='getattr' and node.args and isinstance(node.args[0],ast.Call) and _call_name(node.args[0].func)=='import_module':
            lit=node.args[1:2];dunder=len(lit)==1 and isinstance(lit[0],ast.Constant) and isinstance(lit[0].value,str) and re.fullmatch(r'__[a-z]+__',lit[0].value) is not None   # the framework pattern
            if not dunder:found.append((path,node.lineno,'adapter factory resolved outside the helper'))
    return found

class OptionConstructionGuardTests(unittest.TestCase):
    """Project-scope construction guard (FIX1-A01; ledger EXL-CONSTRUCTION-GUARD-01 closure): after FIX1 no framework gate
    scans the Python of a standalone example, so this test applies the framework construction rule to every manifest adapter
    class of this example: no non-test module of the package constructs one except through the helper."""
    PKG=Path(PROJECT);CASES=PKG.parent/'cases'
    def classes(self):
        out={}
        for p in sorted(self.CASES.glob('*.json')):
            doc=json.loads(p.read_text())
            if isinstance(doc,dict) and isinstance(doc.get('adapter'),str) and ':' in doc['adapter']:out[p.name]=doc['adapter']
        return out
    def files(self):
        return [p for p in sorted(self.PKG.rglob('*.py')) if 'tests' not in p.relative_to(self.PKG).parts and '__pycache__' not in p.parts]
    def test_every_manifest_adapter_class_is_covered_by_the_scan(self):
        specs=self.classes();self.assertTrue(specs)
        for case,spec in specs.items():
            module,_,name=spec.partition(':');path=self.PKG/(module.replace('.','/')+'.py')
            with self.subTest(case=case):
                self.assertTrue(path.is_file() and path in self.files(),spec)
                self.assertTrue(any(isinstance(n,ast.ClassDef) and n.name==name for n in ast.parse(path.read_text()).body),spec)
    def test_no_module_constructs_a_manifest_adapter_class_outside_the_helper(self):
        classes={spec.rpartition(':')[2] for spec in self.classes().values()};bad=[]
        self.assertEqual(classes,{'OptionChainGreeks','EchoControl'})      # EX-10: the echo-control case adds EchoControl (optionlab.echo_adapter)
        self.assertTrue(any(p.name=='adapter.py' for p in self.files()) and any(p.name=='checks.py' for p in self.files()) and any(p.name=='echo_adapter.py' for p in self.files()))
        for p in self.files():bad+=construction_violations(p.read_text(),p.relative_to(self.PKG).as_posix(),classes)
        self.assertEqual(bad,[],'construct adapters through '+HELPER+': '+'; '.join(f'{f}:{n} {r}' for f,n,r in bad[:10]))
    def test_the_data_hook_copies_the_adapter_without_calling_its_class(self):
        tree=ast.parse((self.PKG/'optionlab/adapter.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='OptionChainGreeks')
        hook=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='with_market')
        calls=[(_call_name(c.func),getattr(c.func,'value',None)) for c in ast.walk(hook) if isinstance(c,ast.Call)]
        self.assertTrue(any(n=='copy' and isinstance(v,ast.Name) and v.id=='copy' for n,v in calls),'with_market builds its copy with copy.copy(self)')
        self.assertFalse(any(n=='OptionChainGreeks' for n,_ in calls))
        self.assertIn('out.bench_ref=self.bench_ref',ast.unparse(hook).replace(' = ','='))
    def test_the_scanner_is_live(self):
        """Each rule fires on a seeded source, and the allowed forms pass."""
        classes={'Widget'}
        seeded={'direct constructor call Widget':'class Widget:\n    def with_x(self):return Widget()\n',
                'aliased constructor call W':'from m import Widget as W\nx=W()\n',
                'factory call':'def f(spec):\n    factory=load(spec)\n    return factory({})\n',
                'type(...)(...) call':'class Widget:\n    def f(self):return type(self)()\n',
                '__class__(...) call':'class Widget:\n    def f(self):return self.__class__()\n',
                'adapter factory resolved outside the helper':'import importlib\nc=getattr(importlib.import_module("m"),"Widget")\n',
                'getattr(...)(...) call':'import importlib\ndef f():return getattr(importlib.import_module("m"),"Widget")({})\n'}
        for rule,src in seeded.items():
            with self.subTest(rule=rule):self.assertIn(rule,[r for _,_,r in construction_violations(src,'x.py',classes)])
        for src in ('import copy\nclass Widget:\n    def f(self):\n        out=copy.copy(self);out.bench_ref=self.bench_ref;return out\n',
                    'import importlib\nv=getattr(importlib.import_module("numpy"),"__version__",None)\n'):
            self.assertEqual(construction_violations(src,'x.py',classes),[])
    def test_the_scanner_finds_the_framework_bypass_forms(self):
        """T9-A08: the bypass forms of tests/unit/test_bench_construction.py (the framework review of G-ALO-CO part 1): a module alias
        call, an alias of a module attribute, getattr of a module and a call of the result, a getattr with a default or a variable
        name, a **kwargs call of a factory and of a class, and a dunder-like name outside the framework pattern __[a-z]+__. Each seed
        makes the scanner report a violation."""
        classes={'Widget'}
        forms={'alias import':'from pkg.adapter import Widget as G\nw=G({})\n',
               'alias assignment':'from pkg.adapter import Widget\nG=Widget\nw=G({})\n',
               'alias of a module attribute':'import pkg.adapter as ad\nG=ad.Widget\nw=G({})\n',
               'module alias call':'import pkg.adapter as ad\nw=ad.Widget({})\n',
               'getattr of a module then call':'import pkg.adapter as ad\nw=getattr(ad,"Widget")({})\n',
               'getattr of a module with a default':'import importlib\nf=getattr(importlib.import_module("m"),"C",None)\n',
               'getattr of a variable name':'import importlib\ndef g(m,n,p):\n    f=getattr(importlib.import_module(m),n,None);return f(p)\n',
               'kwargs call of a factory':'def f(factory,kw):return factory(**kw)\n',
               'kwargs call of a class':'from pkg.adapter import Widget\nw=Widget(**{"raw":{}})\n',
               'type of an adapter':'def f(a):return type(a)({})\n',
               'class attribute':'def f(a):return a.__class__({})\n',
               'dunder-like name outside the pattern':'import importlib\nv=getattr(importlib.import_module("numpy"),"__ver_sion__",None)\n'}
        for form,src in forms.items():
            with self.subTest(form=form):self.assertTrue(construction_violations(src,'x.py',classes),'no finding')
        self.assertEqual(construction_violations('import importlib\nv=getattr(importlib.import_module("numpy"),"__version__",None)\n','x.py',classes),[])


if __name__=='__main__':unittest.main()
