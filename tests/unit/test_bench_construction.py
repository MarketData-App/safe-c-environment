"""G-ALO-CO part 1 (spec Amendment I, item I13.1): one construction path for every adapter.

(a) Guard: every non-test Python file of benchlab, container/, tools/ and each example's benchmarks/project/python
    package is scanned. A factory call outside benchlab.workload.construct_adapter, a direct constructor call of a class
    that a case manifest names as `adapter` (FR5C-01: no project method name is exempt) and a bench_ref
    of a pooled adapter class (one with chunks or run_chunk) that is not one four-item tuple fail.
    G-ALO-CO part 2 (Task A2, part 1 review Minors 1-2): aliased imports and assignments of a manifest class, type(a)(...),
    a.__class__(...), a factory resolved with any arity, a list, variable or starred bench_ref, the exact helper path and a
    whitespace-tolerant pre-filter; the example adapter classes are read from the case manifests, never named here.
(b) Argument checks: a pooled adapter without a limit refuses its first pooled prepare; construct_adapter refuses a
    mismatching explicit limit; benchlab.workload.request_limit refuses a missing or conflicting limit.
The value tests (chunk sizes at 14,336, 14,337 and 20,000 through the helper and in pool workers) run in the container
suites (benchmarks/performance/python/tests/test_construction.py and the example test_construction.py)."""
import ast, json, os, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/performance/python'))
sys.path.insert(0,str(ROOT/'tools'))
from benchlab import workload, pools
from benchlab.controlcase import Spin
from benchlab.recordscan import RecordScan
HELPER='benchlab.workload.construct_adapter'
LIMIT=json.loads((ROOT/'safety/performance-policy.json').read_text())['pools']['request_limit']
P={'rounds':1,'seed':20261007}
SCAN={'day_min':7,'day_max':60,'ratio_lo':0.9,'ratio_hi':1.1,'seed':1}
ENV='SAFE_C_BENCH_REQUEST_LIMIT'

def scanned_files(root=ROOT):
    tops=[root/'benchmarks/performance/python/benchlab',root/'container',root/'tools']+sorted(root.glob('examples/*/benchmarks/project/python'))
    out=[]
    for top in tops:
        for p in sorted(top.rglob('*.py')):
            rel=p.relative_to(top).parts
            if 'tests' in rel or '__pycache__' in rel:continue
            out.append(p)
    return out

def manifest_adapters(root=ROOT):
    """Class names that a case manifest names as `adapter` (framework cases and every example's cases)."""
    names=set()
    for p in sorted(root.glob('benchmarks/performance/cases/*.json'))+sorted(root.glob('examples/*/benchmarks/project/cases/*.json')):
        doc=json.loads(p.read_text())
        if isinstance(doc,dict) and isinstance(doc.get('adapter'),str) and ':' in doc['adapter']:names.add(doc['adapter'].rpartition(':')[2])
    return names

HELPER_PATH='benchmarks/performance/python/benchlab/workload.py'    # review Minor 1: the exemption holds for this exact path only

def _call_name(func):
    return func.id if isinstance(func,ast.Name) else func.attr if isinstance(func,ast.Attribute) else None

def _is_import_module(node):
    return isinstance(node,ast.Call) and _call_name(node.func)=='import_module'

def _dunder(args):
    """A literal dunder attribute name (`__version__`): module metadata, never an adapter factory."""
    return len(args)==1 and isinstance(args[0],ast.Constant) and isinstance(args[0].value,str) and re.fullmatch(r'__[a-z]+__',args[0].value) is not None

def _aliases(tree,classes):
    """Names that stand for a manifest class in this file: `from m import C as G` and `G = C` / `G = m.C` (review Minor 1)."""
    out={}
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            out.update({a.asname:a.name for a in node.names if a.name in classes and a.asname and a.asname!=a.name})
        if isinstance(node,ast.Assign) and _call_name(node.value) in classes and isinstance(node.value,(ast.Name,ast.Attribute)):
            out.update({t.id:_call_name(node.value) for t in node.targets if isinstance(t,ast.Name) and t.id!=_call_name(node.value)})
    return out

def violations(source,path,classes):
    """(path, line, rule) of every construction outside the helper. `path` is the repository-relative label of the file (posix)."""
    tree=ast.parse(source);found=[];aliases=_aliases(tree,classes)
    helper_file=path==HELPER_PATH
    def visit(node,func_stack,class_stack):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):func_stack=func_stack+[node.name]
        if isinstance(node,ast.ClassDef):class_stack=class_stack+[node]
        in_helper=helper_file and 'construct_adapter' in func_stack
        if isinstance(node,ast.Call) and not in_helper:
            name=_call_name(node.func)
            if name=='factory':found.append((path,node.lineno,'factory call'))
            if isinstance(node.func,ast.Call) and _call_name(node.func.func)=='getattr':found.append((path,node.lineno,'getattr(...)(...) factory call'))
            if isinstance(node.func,ast.Call) and isinstance(node.func.func,ast.Name) and node.func.func.id=='type':
                found.append((path,node.lineno,f'type(...)(...) constructor call outside {HELPER}'))
            if isinstance(node.func,ast.Attribute) and node.func.attr=='__class__':
                found.append((path,node.lineno,f'__class__(...) constructor call outside {HELPER}'))
            if name=='getattr' and node.args and _is_import_module(node.args[0]) and not _dunder(node.args[1:2]):   # any arity (review Minor 1)
                found.append((path,node.lineno,'adapter factory resolved outside the helper'))
            if name in classes:found.append((path,node.lineno,f'direct constructor call {name}'))
            if isinstance(node.func,ast.Name) and node.func.id in aliases:
                found.append((path,node.lineno,f'aliased constructor call {node.func.id} of {aliases[node.func.id]} outside {HELPER}'))
        if isinstance(node,(ast.Assign,ast.AugAssign,ast.AnnAssign)) and class_stack:
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            pooled=any(isinstance(b,(ast.FunctionDef,ast.AsyncFunctionDef)) and b.name in ('chunks','run_chunk') for b in class_stack[-1].body)
            if pooled and any(isinstance(t,ast.Attribute) and t.attr=='bench_ref' for t in targets) and node.value is not None:
                v=node.value
                four=isinstance(v,ast.Tuple) and len(v.elts)==4 and not any(isinstance(x,(ast.BinOp,ast.Starred)) for x in ast.walk(v))
                copy=isinstance(v,ast.Attribute) and v.attr=='bench_ref' and not isinstance(node,ast.AugAssign)     # a copy of the instance keeps its ref
                if not (four or copy):found.append((path,node.lineno,'pooled adapter bench_ref is not one four-item tuple'))
        for child in ast.iter_child_nodes(node):visit(child,func_stack,class_stack)
    visit(tree,[],[]);return found

def _trigger(classes):
    """Text pre-filter: a file without any trigger skips the AST pass. A manifest class name anywhere (aliases), getattr,
    type(...) and __class__ with any spacing (review Minor 1)."""
    return re.compile(r'\bfactory\b|bench_ref|\bgetattr\s*\(|\btype\s*\(|__class__|'+'|'.join(r'\b'+re.escape(c)+r'\b' for c in sorted(classes)))

def example_adapter_classes(root=ROOT):
    """{case file: adapter class} of every example case manifest (review Minor 2: read from the manifests, never named here)."""
    out={}
    for p in sorted(root.glob('examples/*/benchmarks/project/cases/*.json')):
        doc=json.loads(p.read_text())
        if isinstance(doc,dict) and isinstance(doc.get('adapter'),str) and ':' in doc['adapter']:out[p.relative_to(root).as_posix()]=doc['adapter'].rpartition(':')[2]
    return out

class GuardTests(unittest.TestCase):
    def test_every_construction_goes_through_the_helper(self):
        classes=manifest_adapters();self.assertTrue({'Spin','Wait','Touch','RecordScan'}<=classes)
        examples=example_adapter_classes();self.assertTrue(examples);self.assertTrue(set(examples.values())<=classes)
        trig=_trigger(classes);bad=[];files=scanned_files()
        self.assertTrue(any(p.name=='bench-coordinator.py' for p in files) and any(p.name=='checks.py' for p in files))
        for p in files:
            text=p.read_text()
            if trig.search(text):bad+=violations(text,p.relative_to(ROOT).as_posix(),classes)
        self.assertEqual(bad,[],f'construct adapters through {HELPER}: '+'; '.join(f'{f}:{n} {r}' for f,n,r in bad[:10]))
    def test_the_guard_finds_each_kind_of_violation(self):
        """The scanner is live: each rule fires on a seeded source, and the allowed forms pass."""
        classes={'Spin','Widget'}
        seeded={'factory call':'def f(spec):\n    factory=load(spec)\n    return factory({})\n',
                'getattr(...)(...) factory call':'import importlib\ndef f():return getattr(importlib.import_module("m"),"C")({})\n',
                'adapter factory resolved outside the helper':'import importlib\ndef f():\n    c=getattr(importlib.import_module("m"),"C")\n    return c\n',
                'direct constructor call Spin':'from benchlab.controlcase import Spin\nw=Spin({})\n',
                'pooled adapter bench_ref is not one four-item tuple':'class A:\n    def __init__(self,p,s):self.bench_ref=("m:A",p,s)\n    def chunks(self,p,w):return []\n'}
        self.assertIn('pooled adapter bench_ref is not one four-item tuple',[r for _,_,r in violations('class A:\n    def __init__(self,p,s):self.bench_ref=("m:A",p)+(() if s=="all" else (s,))\n    def run_chunk(self,c):return c\n','x/mod.py',classes)])
        for rule,src in seeded.items():
            with self.subTest(rule=rule):self.assertIn(rule,[r for _,_,r in violations(src,'x/mod.py',classes)])
        allowed=['import importlib\ndef construct_adapter(spec):\n    factory=getattr(importlib.import_module("m"),"C")\n    return factory({})\n',
                 'class Widget:\n    def __init__(self,p):self.p=p\n',
                 'class A:\n    def __init__(self,p,s,l):self.bench_ref=("m:A",p,s,l)\n    def chunks(self,p,w):return []\n',
                 'class B:\n    def __init__(self,p,s):self.bench_ref=("m:B",p,s)\n',
                 'import importlib\nv=getattr(importlib.import_module("numpy"),"__version__",None)\n',
                 'import copy\nclass Widget:\n    def variant(self):\n        out=copy.copy(self);out.bench_ref=self.bench_ref;return out\n    def chunks(self,p,w):return []\n',
                 'from benchlab.controlcase import Spin\nkind=Spin.__name__\n']
        paths=[HELPER_PATH,'x/pkg/adapter.py','x/a.py','x/b.py','x/c.py','x/pkg/adapter.py','x/d.py']
        for src,path in zip(allowed,paths):
            with self.subTest(path=path,src=src[:30]):self.assertEqual(violations(src,path,classes),[])
        self.assertTrue(violations(allowed[0],'x/other.py',classes))     # the helper exemption holds only in benchlab/workload.py
        self.assertTrue(violations(allowed[0],'examples/x/benchmarks/project/python/benchlab/workload.py',classes))   # exact path, not a suffix
        self.assertTrue(violations('class Widget:\n    def other(self):return Widget({})\n','x/pkg/adapter.py',classes))
    def test_no_project_method_name_exempts_a_construction(self):
        """FR5C-01 (ruling FR5-R9): the guard names no project method. A manifest class that constructs itself in any method,
        including the former exempt name of the example's data hook, is a direct constructor call; a copy of the instance
        that keeps its bench_ref is the allowed form."""
        classes={'Widget'}
        for method in ('with_market','copy_with','other','__copy__'):      # NEG: the example's former exempt method name
            for src in (f'class Widget:\n    def {method}(self):return Widget({{}})\n',
                        f'class Widget:\n    def {method}(self):\n        out=Widget({{}});out.bench_ref=self.bench_ref;return out\n    def chunks(self,p,w):return []\n'):
                with self.subTest(method=method,src=src[:40]):
                    self.assertIn('direct constructor call Widget',[r for _,_,r in violations(src,'x/pkg/adapter.py',classes)])
    def test_the_guard_finds_the_bypass_forms_of_the_review(self):
        """G-ALO-CO part 1 review Minor 1: aliased imports, getattr(module, 'Class')(...), type(a)(...), a.__class__(...),
        a factory resolved with a default or a keyword, a **kwargs call of a factory and a list or variable bench_ref of a
        pooled adapter. Each finding names the helper (the scan message adds it to every finding)."""
        classes={'Spin','Widget'}
        forms={'alias import':'from pkg.adapter import Widget as G\nw=G({})\n',
               'alias assignment':'from pkg.adapter import Widget\nG=Widget\nw=G({})\n',
               'alias of a module attribute':'import pkg.adapter as ad\nG=ad.Widget\nw=G({})\n',
               'aliased module':'import pkg.adapter as ad\nw=ad.Widget({})\n',
               'getattr of a module':'import pkg.adapter as ad\nw=getattr(ad,"Widget")({})\n',
               'type of an adapter':'def f(a):return type(a)({})\n',
               'class attribute':'def f(a):return a.__class__({})\n',
               'getattr with a default':'import importlib\nf=getattr(importlib.import_module("m"),"C",None)\n',
               'getattr of a variable name':'import importlib\ndef g(m,n,p):\n    f=getattr(importlib.import_module(m),n,None);return f(p)\n',
               'kwargs call of a factory':'def f(factory,kw):return factory(**kw)\n',
               'kwargs call of a class':'from pkg.adapter import Widget\nw=Widget(**{"raw":{}})\n',
               'list bench_ref':'class A:\n    def __init__(self,p,s,l):self.bench_ref=["m:A",p,s,l]\n    def chunks(self,p,w):return []\n',
               'variable bench_ref':'class A:\n    def __init__(self,r):self.bench_ref=r\n    def run_chunk(self,c):return c\n',
               'starred bench_ref':'class A:\n    def __init__(self,r):self.bench_ref=(*r,1,2,3)\n    def run_chunk(self,c):return c\n'}
        for form,src in forms.items():
            with self.subTest(form=form):
                self.assertTrue(_trigger(classes).search(src),'the text pre-filter skips the file')
                self.assertTrue(violations(src,'x/mod.py',classes),'no finding')
        for form in ('alias import','alias assignment','type of an adapter','class attribute'):
            with self.subTest(named=form):self.assertTrue(all(HELPER in r for _,_,r in violations(forms[form],'x/mod.py',classes)))
        self.assertTrue(_trigger(classes).search('x=getattr (m, "n")\n'))      # spacing before the parenthesis

class LimitTests(unittest.TestCase):
    def setUp(self):
        saved=os.environ.pop(ENV,None)
        self.addCleanup(lambda:os.environ.update({ENV:saved}) if saved is not None else os.environ.pop(ENV,None))
    def test_the_policy_limit_is_14336(self):
        policy=json.loads((ROOT/'safety/performance-policy.json').read_text())
        self.assertEqual((policy['pools']['request_limit'],policy['protocol']['max_request_records']),(14336,14336))
        self.assertEqual(workload.request_limit(),14336)
    def test_the_variable_and_the_policy_must_agree(self):
        os.environ[ENV]=str(LIMIT);self.assertEqual(workload.request_limit(),LIMIT)
        for bad in (str(LIMIT+1),'0','-5','abc','','14336.0',' 14336'):
            os.environ[ENV]=bad
            with self.subTest(value=bad),self.assertRaises(ValueError) as ctx:workload.request_limit()
            self.assertIn(HELPER,str(ctx.exception))
    def test_neither_source_is_refused_and_the_variable_alone_is_used(self):
        missing=Path(tempfile.mkdtemp())/'none.json'
        with mock.patch.object(workload,'POLICY_FILE',missing):
            with self.assertRaises(ValueError) as ctx:workload.request_limit()
            self.assertIn(HELPER,str(ctx.exception));self.assertTrue(str(ctx.exception).startswith('request_limit:'))
            os.environ[ENV]='4096';self.assertEqual(workload.request_limit(),4096)
    def test_the_helper_passes_the_limit_to_pooled_adapters_only(self):
        a=workload.construct_adapter('benchlab.controlcase:Spin',P,pooled=True)
        self.assertEqual((a.request_limit,a.bench_ref),(LIMIT,('benchlab.controlcase:Spin',P,'all',LIMIT)))
        h=workload.construct_adapter('benchlab.controlcase:Spin',P,selector='hang',pooled=True)
        self.assertEqual((h.selector,h.bench_ref),('hang',('benchlab.controlcase:Spin',P,'hang',LIMIT)))
        self.assertIsInstance(workload.construct_adapter('benchlab.recordscan:RecordScan',SCAN,pooled=False),RecordScan)   # no keyword
        with self.assertRaises(TypeError):workload.construct_adapter('benchlab.controlcase:Spin',P)                         # `pooled` is required
        self.assertEqual(workload.construct_adapter('benchlab.controlcase:Spin',P,pooled=True,request_limit=LIMIT).request_limit,LIMIT)
        for bad in (LIMIT-1,LIMIT+1,0,True,float(LIMIT),str(LIMIT)):
            with self.subTest(explicit=bad),self.assertRaises(ValueError) as ctx:workload.construct_adapter('benchlab.controlcase:Spin',P,pooled=True,request_limit=bad)
            self.assertIn(HELPER,str(ctx.exception))
        for bad in ('Spin','benchlab.controlcase:',':Spin'):
            with self.subTest(spec=bad),self.assertRaises(ValueError):workload.construct_adapter(bad,P,pooled=True)
        with self.assertRaises(ValueError):workload.construct_adapter('benchlab.controlcase:Spin',P,selector='Bad Selector',pooled=True)
    def test_the_helper_verifies_the_stored_limit_of_a_pooled_adapter(self):
        """Part 1 review Minor 3: a pooled factory that ignores or changes the keyword is refused; the ref uses the stored value."""
        d=Path(tempfile.mkdtemp());name='a2_limit_probe_'+str(os.getpid())
        (d/(name+'.py')).write_text('class Ignore:\n    def __init__(self,params,**kw):self.request_limit=None\n'
                                    'class Shift:\n    def __init__(self,params,request_limit=None):self.request_limit=request_limit+1\n'
                                    'class Text:\n    def __init__(self,params,request_limit=None):self.request_limit=str(request_limit)\n'
                                    'class Missing:\n    def __init__(self,params,**kw):pass\n')
        sys.path.insert(0,str(d));self.addCleanup(lambda:(sys.path.remove(str(d)),sys.modules.pop(name,None)))
        for cls in ('Ignore','Shift','Text','Missing'):
            with self.subTest(cls=cls),self.assertRaises(ValueError) as ctx:workload.construct_adapter(f'{name}:{cls}',P,pooled=True)
            self.assertIn(HELPER,str(ctx.exception))
        self.assertIsNone(workload.construct_adapter(f'{name}:Ignore',P,pooled=False).request_limit)     # a direct adapter keeps its constructor
        with mock.patch.object(workload,'_request_limit',side_effect=[LIMIT,LIMIT+1]):          # a second policy read never reaches the ref
            self.assertEqual(workload.load_adapter('benchlab.controlcase:Spin',P,pooled=True).bench_ref[3],LIMIT)
    def test_load_adapter_records_the_four_item_ref_of_a_pooled_adapter(self):
        a=workload.load_adapter('benchlab.controlcase:Spin',P,pooled=True)
        self.assertEqual((a.request_limit,a.bench_ref),(LIMIT,('benchlab.controlcase:Spin',P,'all',LIMIT)))
        self.assertEqual(workload.load_adapter('benchlab.controlcase:Spin',P,pooled=True,selector='hang').bench_ref,('benchlab.controlcase:Spin',P,'hang',LIMIT))
        self.assertEqual(workload.load_adapter('benchlab.recordscan:RecordScan',SCAN).bench_ref,('benchlab.recordscan:RecordScan',SCAN))
    def test_a_pooled_adapter_without_a_limit_refuses_its_pooled_prepare(self):
        w=Spin(P);self.assertIsNone(w.request_limit);self.assertEqual(w.bench_ref,('benchlab.controlcase:Spin',P,'all',None))
        self.assertEqual(w.prepare([1,2,3],'py-reference'),{'seeds':[1,2,3]})              # a direct variant needs no limit
        for variant in pools.POOLED:
            with self.subTest(variant=variant),self.assertRaises(ValueError) as ctx:w.prepare([1,2,3],variant,2)
            self.assertEqual(str(ctx.exception),'request_limit not set: construct the adapter through benchlab.workload.construct_adapter')
    def test_pool_workers_build_the_adapter_through_the_helper(self):
        w=pools._resolve(('benchlab.controlcase:Spin',P,'all',LIMIT));self.assertEqual((w.request_limit,w.selector),(LIMIT,'all'))
        self.assertEqual(pools._resolve(('benchlab.controlcase:Spin',P,'hang',LIMIT)).selector,'hang')
        for bad in (LIMIT+1,None,0):
            with self.subTest(ref_limit=bad),self.assertRaises(ValueError):pools._resolve(('benchlab.controlcase:Spin',P,'all',bad))
        self.assertIsInstance(pools._resolve(('benchlab.recordscan:RecordScan',SCAN)),RecordScan)         # two items: no keyword
        self.assertIsNone(pools._resolve(('benchlab.controlcase:Spin',P,'hang')).request_limit)              # three items: no keyword
        for bad in (('benchlab.controlcase:Spin',),('benchlab.controlcase:Spin',P,'all',LIMIT,1)):
            with self.subTest(ref=len(bad)),self.assertRaises(ValueError):pools._resolve(bad)

if __name__=='__main__':unittest.main()
