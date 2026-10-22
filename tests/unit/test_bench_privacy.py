"""Task 18: owner-fixture privacy (spec 12): local dataset rules, the closed aggregate gate, the pre-run gate of a local
run and the coordinator's artifact-directory check. Synthetic files only; the owner dataset is never read."""
import argparse, contextlib, importlib.util, io, json, math, os, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench_privacy as bp

# T12-C4: run_local now runs the doctor probe and the B12 guardrails before any job. These tests of later steps use a
# permitting probe and gate; tests/unit/test_bench_guardrails.py (LocalRunHook) tests the real gate on this path.
PERMITTED_PROBE=lambda root,run_dir:{'status':'PASS','envelope':None,'evidence_paths':[],'lock_held_ns':0}
PERMITTED_GATE=lambda root,run_dir,plan,policy,envelope,probe:([],'PASS')

def repo():
    d=Path(tempfile.mkdtemp());subprocess.run(['git','init','-q',str(d)],check=True)
    (d/'.gitignore').write_text('ignored/\n');(d/'ignored').mkdir();(d/'tracked').mkdir()
    (d/'ignored/dataset.json').write_text('{}');(d/'tracked/dataset.json').write_text('{}');return d

# FR3: the case block `summary` is project data, validated with the project's protocol aggregate schema. These tests use a
# synthetic summary of two selectors (s1, s2) and five fields (f1..f5), and its schema (closed, counts and quantiles).
SELECTORS=('s1','s2');FIELDS=('f1','f2','f3','f4','f5')
Q={'type':'object','additionalProperties':False,'required':['count','median','p90'],
   'properties':{'count':{'type':'integer','minimum':0},'median':{'type':['number','null']},'p90':{'type':['number','null']}}}
SUMMARY_SCHEMA={'type':'object','additionalProperties':False,'required':['crosscheck'],
                'properties':{'crosscheck':{'type':'object','additionalProperties':False,'required':list(SELECTORS),
                 'properties':{s:{'type':'object','additionalProperties':False,'required':list(FIELDS),'properties':{f:Q for f in FIELDS}} for s in SELECTORS}}}}

def closed_aggregate():
    return {'schema_version':2,'run_id':'0'*32,'case':'record-scan','dataset_sha256':'a'*64,'rows':64,
            'summary':{'crosscheck':{s:{f:{'count':0,'median':None,'p90':None} for f in FIELDS} for s in SELECTORS}},
            'timings':[],'counters':{'cpu_usage_usec':0,'memory_peak_bytes':None},'exceptions':[],
            'output_digests':{'result_sha256':'b'*64,'reference_sha256':'c'*64},'status':'VALID'}

def accept(p,**kw):
    """bp.accept_aggregate with the synthetic summary schema (the role of a project's protocol aggregate schema)."""
    return bp.accept_aggregate(ROOT,p,summary_schema=kw.pop('schema',SUMMARY_SCHEMA),**kw)

def coordinator():
    spec=importlib.util.spec_from_file_location('bench_coordinator_privacy',ROOT/'container/bench-coordinator.py')
    bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);return bc

class LocalDatasetTests(unittest.TestCase):
    def test_ignored_and_outside_files_are_accepted(self):
        d=repo();out=Path(tempfile.mkdtemp())/'c.json';out.write_text('{}')
        for path in (d/'ignored/dataset.json',out):
            r=bp.resolve_local_dataset(d,str(path));self.assertEqual((r['kind'],len(r['sha256'])),('local',64))
            self.assertEqual((r['size'],r['seed'],r['rows']),(None,None,None))
    def test_local_dataset_refusals(self):
        # The container's file-size limit forbids a 32 MiB file, so the size rule is checked against a smaller limit.
        self.assertEqual(bp.MAX_LOCAL_BYTES,32*1024*1024)
        d=repo();fifo=d/'ignored/p';os.mkfifo(fifo);big=d/'ignored/big.json';big.write_bytes(b' '*1025)
        dangling=d/'ignored/link.json';dangling.symlink_to(d/'ignored/missing.json')
        saved=bp.MAX_LOCAL_BYTES;bp.MAX_LOCAL_BYTES=1024
        try:
            for path in (d/'tracked/dataset.json',fifo,big,dangling,d/'ignored'):
                with self.subTest(path=path.name),self.assertRaises(GateError) as ctx:bp.resolve_local_dataset(d,str(path))
                self.assertNotIn(str(d),str(ctx.exception))
        finally:bp.MAX_LOCAL_BYTES=saved
        with mock.patch.dict(os.environ,{'CI':'true'}),self.assertRaises(GateError):bp.resolve_local_dataset(d,str(d/'ignored/dataset.json'))
    def test_a_file_of_exactly_the_limit_is_accepted(self):
        d=repo();exact=d/'ignored/exact.json';exact.write_bytes(b' '*1024)
        with mock.patch.object(bp,'MAX_LOCAL_BYTES',1024):
            self.assertEqual(bp.resolve_local_dataset(d,str(exact))['kind'],'local')
            exact.write_bytes(b' '*1025)
            with self.assertRaises(GateError):bp.resolve_local_dataset(d,str(exact))
    def assert_withheld(self,text,path):
        self.assertNotIn(str(path),text);self.assertNotIn(Path(path).name,text)
    def test_unreadable_dataset_error_names_no_path(self):
        """Review Important 1: an OSError after resolution (here EACCES from the digest or the stat) becomes one fixed GateError."""
        d=repo();path=d/'ignored/owner_secret_dataset.json';path.write_text('{}')
        for target in ('file_hash','lstat'):
            obj=bp if target=='file_hash' else bp.os
            with self.subTest(target=target),mock.patch.object(obj,target,side_effect=PermissionError(13,'Permission denied',str(path))):
                with self.assertRaises(GateError) as ctx:bp.resolve_local_dataset(d,str(path))
                self.assert_withheld(str(ctx.exception),path)
    def test_unreadable_dataset_cli_line_names_no_path(self):
        """The `bench run` CLI line for the same failure (bench.execute prints 'BLOCKED: ' + the GateError text)."""
        import bench, container_policy
        path=Path(tempfile.mkdtemp())/'owner_secret_dataset.json';path.write_text('{}')
        parser=argparse.ArgumentParser();bench.configure_parser(parser)
        args=parser.parse_args(['run','--case','record-scan','--mode','smoke','--dataset','local:'+str(path)]);out=io.StringIO()
        # ROOT holds project.json in a fresh child instance, where local datasets are refused before the read under test
        # (ci 327823a5 child unit gate); the framework-root answer keeps the same path through bench.execute.
        with mock.patch.object(bp,'file_hash',side_effect=PermissionError(13,'Permission denied',str(path))),\
             mock.patch.object(bp,'is_project_instance',return_value=False),\
             mock.patch.object(container_policy,'host_topology',return_value=((0,1,2,3),[])),mock.patch.object(container_policy,'choose_envelope',return_value=None),\
             contextlib.redirect_stdout(out):
            rc=bench.execute(ROOT,args)
        self.assertEqual(rc,2);self.assertIn('not readable',out.getvalue());self.assert_withheld(out.getvalue(),path)
    def test_project_instance_refuses_local_datasets(self):
        d=repo();(d/'project.json').write_text('{}')
        with self.assertRaises(GateError):bp.resolve_local_dataset(d,str(d/'ignored/dataset.json'))
    def test_aggregate_gate_keeps_only_a_valid_bounded_document(self):
        d=Path(tempfile.mkdtemp());p=d/'aggregate.json'
        p.write_text(json.dumps({'schema_version':1,'note':'value 412.35'}))
        doc,reason=accept(p);self.assertIsNone(doc);self.assertFalse(p.exists());self.assertIn('bytes',reason)
        self.assertNotIn('412.35',reason)
        p.write_bytes(b' '*(262144+1));doc,reason=accept(p);self.assertIsNone(doc);self.assertFalse(p.exists())
        doc,reason=accept(d/'missing.json');self.assertIsNone(doc)
    def test_aggregate_gate_accepts_the_closed_document(self):
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(closed_aggregate()))
        doc,reason=accept(p);self.assertEqual(reason,'valid');self.assertEqual(doc['status'],'VALID');self.assertTrue(p.exists())
    def test_the_summary_must_follow_the_project_schema(self):
        """FR3: a summary is refused without a project schema, when it fails the schema, and with an undeclared exception."""
        def gate(doc,**kw):
            p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(doc));return accept(p,**kw)[0]
        self.assertIsNone(gate(closed_aggregate(),schema=None))
        bad=closed_aggregate();bad['summary']['crosscheck']['s1']['f1']['note']='value 412.35';self.assertIsNone(gate(bad))
        exc=dict(closed_aggregate(),exceptions=[{'type':'ProjectError','row_index':None}])
        self.assertIsNone(gate(exc));self.assertIsNotNone(gate(exc,exceptions=('ProjectError',)))
        self.assertIsNotNone(gate(dict(closed_aggregate(),exceptions=[{'type':'ValueError','row_index':3}])))
        self.assertIsNotNone(gate(dict(closed_aggregate(),summary=None,status='INVALID_EXPERIMENT'),schema=None))   # no summary, no schema needed
        self.assertIsNone(gate(dict(closed_aggregate(),summary=None)))                                           # a null summary is never VALID
    def test_the_project_schema_comes_from_the_protocol(self):
        """FR3: with project_dir the gate reads the aggregate schema and local_exceptions of the project's protocol."""
        import bench_model as bm
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(dict(closed_aggregate(),summary=None,status='INVALID_EXPERIMENT',
                                                                                    exceptions=[{'type':'FixtureError','row_index':None}])))
        self.assertIsNotNone(bp.accept_aggregate(ROOT,p,project_dir='tests/fixtures/bench-project')[0])
        self.assertEqual(bm.load_protocol(ROOT,'tests/fixtures/bench-project')['local_exceptions'],['FixtureError'])

class QuantileSuppressionTests(unittest.TestCase):
    """Controller ruling (Task 18 concern 2): a quantile over fewer than 5 rows is near-individual; the host rejects an
    aggregate that carries one as a number (FR3: anywhere in the project summary)."""
    def gate(self,count,median):
        doc=closed_aggregate();doc['summary']['crosscheck']['s1']['f1']={'count':count,'median':median,'p90':median}
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(doc));return accept(p),p
    def test_small_count_with_a_number_is_rejected(self):
        for count in (1,4):
            with self.subTest(count=count):
                (doc,reason),p=self.gate(count,0.0123);self.assertIsNone(doc);self.assertFalse(p.exists());self.assertNotIn('0.0123',reason)
    def test_small_count_with_null_and_count_five_with_a_number_are_accepted(self):
        for count,median in ((1,None),(4,None),(5,0.0123),(0,None)):
            with self.subTest(count=count):(doc,reason),_=self.gate(count,median);self.assertEqual(reason,'valid')
    def test_the_threshold_is_five(self):self.assertEqual(bp.MIN_QUANTILE_ROWS,5)

class FixedPathErrorTests(unittest.TestCase):
    """Task 19b parked item: the lstat, work-tree and check-ignore error paths each give one fixed text, without the path,
    and the GateError drops its chained OSError (raise from None), so a traceback cannot print the path either."""
    def check(self,d,what,patch,expected):
        path=d/'ignored/owner_secret_dataset.json';path.write_text('{}');err=PermissionError(13,'Permission denied',str(path))
        obj,name,kw=patch(err)
        with mock.patch.object(obj,name,**kw),self.assertRaises(GateError) as ctx:bp._resolve_untracked(d,str(path),what,1024)
        text=str(ctx.exception);self.assertEqual(text,expected)
        self.assertNotIn(str(path),text);self.assertNotIn(path.name,text)
        self.assertIsNone(ctx.exception.__cause__);self.assertTrue(ctx.exception.__context__ is None or ctx.exception.__suppress_context__)
    @staticmethod
    def lstat_of_the_rule(err):
        """Fail only the rule's own lstat: Path.resolve (os.path.realpath) also calls os.lstat and must succeed."""
        real=os.lstat
        def lstat(*a,**k):
            if sys._getframe(1).f_code.co_name=='_resolve_untracked':raise err
            return real(*a,**k)
        return lstat
    def test_each_error_path_has_a_fixed_text(self):
        d=repo()
        for what in ('local dataset','local replay'):
            for label,patch,expected in (
                    ('lstat',lambda e:(bp.os,'lstat',{'new':self.lstat_of_the_rule(e)}),f'{what} is not readable'),
                    ('work tree',lambda e:(bp.Path,'is_relative_to',{'side_effect':e}),'work tree does not resolve'),
                    ('check-ignore error',lambda e:(bp,'bounded',{'side_effect':e}),f'git check-ignore could not run for the {what}'),
                    ('check-ignore refusal',lambda e:(bp,'bounded',{'return_value':{'exit_code':1}}),f'a {what} inside the work tree must be git-ignored')):
                with self.subTest(what=what,path=label):self.check(d,what,patch,expected)

class WithheldChainTests(unittest.TestCase):
    """Task 19b parked item: `_withheld` reads the whole printed chain (__cause__, and __context__ unless suppressed)."""
    PATH='/private/owner_secret_dataset.json'
    def chained(self,inner,suppress=False):
        try:
            try:raise OSError(5,'Input/output error',inner)
            except OSError:
                if suppress:raise RuntimeError('session failed') from None
                raise RuntimeError('session failed')
        except RuntimeError as exc:return exc
    def test_a_path_in_the_chain_is_withheld(self):
        self.assertTrue(bp._withheld(self.chained(self.PATH),self.PATH))
        self.assertTrue(bp._withheld(self.chained('owner_secret_dataset.json'),self.PATH))
        cause=RuntimeError('session failed');cause.__cause__=OSError(5,'x',self.PATH);self.assertTrue(bp._withheld(cause,self.PATH))
        self.assertFalse(bp._withheld(self.chained('/other/file'),self.PATH))
        self.assertFalse(bp._withheld(self.chained(self.PATH,suppress=True),self.PATH))      # never printed: raise ... from None
        loop=RuntimeError('a');loop.__context__=RuntimeError('b');loop.__context__.__context__=loop;self.assertFalse(bp._withheld(loop,self.PATH))
    def test_run_local_withholds_a_chained_path(self):
        import bench
        root=Path(tempfile.mkdtemp());path=self.PATH;chained=self.chained
        class FailingSession:
            def __init__(self,*a,**k):raise chained(path)
        plan={'mode':'smoke','project_dir':None,'dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None,'path':path},
              'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}
        with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',FailingSession),\
             mock.patch.object(bench,'doctor_probe',PERMITTED_PROBE),mock.patch.object(bench,'guardrail_gate',PERMITTED_GATE),\
             mock.patch.object(bp,'install_fixture_pattern',return_value=True):   # T12-C4: the B12 step passes here; Task 27 pattern step
            with self.assertRaises(GateError) as ctx:
                bp.run_local(root,argparse.Namespace(format='json'),plan,{'case_id':'record-scan','version':1},{'sizes':{'small':256},'job_deadlines':{'session':10800}})
        self.assertIn('withheld',str(ctx.exception));self.assertIsNone(ctx.exception.__cause__);self.assertTrue(ctx.exception.__suppress_context__)

class QuantileEveryFieldTests(unittest.TestCase):
    """Task 19b parked item: the small-count rule holds for every selector and field, and for the median and p90 separately
    (FR3: at any depth of the project summary, also inside lists)."""
    def test_every_model_and_field_median_and_p90_independently(self):
        self.assertEqual(set(closed_aggregate()['summary']['crosscheck']['s1']),set(FIELDS))
        for m in SELECTORS:
            for f in FIELDS:
                for which in ('median','p90'):
                    for count in (1,4):
                        doc=closed_aggregate();doc['summary']['crosscheck'][m][f]={'count':count,'median':None,'p90':None,which:0.0123}
                        with self.subTest(model=m,field=f,which=which,count=count),self.assertRaises(GateError):bp.small_quantiles(doc)
                    doc=closed_aggregate();doc['summary']['crosscheck'][m][f]={'count':5,'median':None,'p90':None,which:0.0123}
                    with self.subTest(model=m,field=f,which=which,count=5):self.assertIsNone(bp.small_quantiles(doc))
    def test_any_depth_and_lists_and_a_bad_count(self):
        for summary in ({'a':[{'b':{'count':2,'median':1.0}}]},{'x':{'y':{'z':{'count':0,'p90':0.5}}}}):
            with self.subTest(summary=summary),self.assertRaises(GateError):bp.small_quantiles({'summary':summary})
        with self.assertRaises(GateError):bp.small_quantiles({'summary':{'q':{'count':-1,'median':None}}})
        self.assertIsNone(bp.small_quantiles({'summary':None}));self.assertIsNone(bp.small_quantiles({'summary':{'a':[{'count':5,'median':2.0}]}}))

class SummaryValueRuleTests(unittest.TestCase):
    """FR3-01 (ruling): the framework privacy rule on the project summary that no project aggregate schema can relax. The
    summary holds numbers, booleans, null, objects and arrays only; a string is accepted only when it is a framework label
    (bp.SUMMARY_LABELS); keys are short identifiers; depth, list length and node count are capped; a number is finite.
    A project aggregate schema must be closed (every object schema has additionalProperties false)."""
    PERMISSIVE={}
    def gate(self,summary,schema=None):
        doc=closed_aggregate();doc['summary']=summary
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(doc))
        return accept(p,schema=self.PERMISSIVE if schema is None else schema),p
    STRING_FIELD={'type':'object','additionalProperties':False,'properties':{'note':{'type':'string'},'rows':{'type':'array','items':{'type':'string'}}}}
    def test_a_project_schema_cannot_pass_a_string(self):
        for summary in ({'rows':['AAPL 2026-10-16 C 100']},{'note':'raw row value'}):
            with self.subTest(summary=summary):          # the closed project schema accepts the string; the framework rule refuses it
                (doc,reason),p=self.gate(summary,schema=self.STRING_FIELD);self.assertIsNone(doc);self.assertFalse(p.exists())
                self.assertNotIn('raw',reason);self.assertNotIn('AAPL',reason)
        for summary in ({'rows':['AAPL 2026-10-16 C 100']},{'a':{'b':'raw row value'}},{'note':'x'},{'a':[1,2,'3']}):
            with self.subTest(summary=summary):
                self.assertTrue(bp.summary_value_problems(summary))
                (doc,_),_p=self.gate(summary);self.assertIsNone(doc)           # a permissive project schema is refused as well
    def test_free_keys_depth_lists_and_non_finite_numbers_are_refused(self):
        deep={'a':1}
        for _ in range(bp.SUMMARY_MAX_DEPTH):deep={'a':deep}
        for summary in ({'AAPL 2026':1},{'k'*40:1},{'a b':1},deep,{'a':list(range(bp.SUMMARY_MAX_ITEMS+1))},{'a':math.nan},{'a':[math.inf]}):
            with self.subTest(summary=str(summary)[:40]):self.assertTrue(bp.summary_value_problems(summary))
    def test_framework_labels_numbers_and_nesting_pass(self):
        for summary in ({'a':{'b':[1,2.5,None,True]},'status':'VALID'},{'mode':'warm','n':0},closed_aggregate()['summary']):
            with self.subTest(summary=str(summary)[:40]):self.assertEqual(bp.summary_value_problems(summary),[])
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(closed_aggregate()))
        self.assertEqual(accept(p)[1],'valid')                              # control: the closed fixture schema and a numeric summary
    def test_an_open_project_schema_is_refused(self):
        self.assertEqual(bp.summary_schema_problems(SUMMARY_SCHEMA),[])
        opened=json.loads(json.dumps(SUMMARY_SCHEMA));opened['properties']['crosscheck']['additionalProperties']=True
        for schema in ({},{'type':'object'},opened,{'type':'object','additionalProperties':False,'patternProperties':{'.*':{}}},
                       {'type':'object','additionalProperties':{'type':'number'}}):
            with self.subTest(schema=str(schema)[:60]):
                self.assertTrue(bp.summary_schema_problems(schema))
                (doc,_),_p=self.gate(closed_aggregate()['summary'],schema=schema);self.assertIsNone(doc)

class SummarySchemaGrammarTests(unittest.TestCase):
    """FR3-10 (ruling FR3-R4): the project aggregate schema follows an allowlist grammar. Every node has an explicit
    `type`. Leaves are number, integer, boolean (each may add null) or a string enum of framework labels. Objects have
    `additionalProperties: false` and explicit `properties`. Arrays have `items` and a bounded `maxItems`. Every other
    keyword and the empty schema {} anywhere are refused."""
    GOOD={'type':'object','additionalProperties':False,'required':['a'],'description':'ok',
          'properties':{'a':{'type':'array','items':{'type':'number','minimum':0},'maxItems':8,'minItems':0},
                        's':{'type':'string','enum':['VALID','BLOCKED']},'n':{'type':['integer','null'],'minimum':0,'maximum':9},
                        'b':{'type':'boolean'},'o':{'type':'object','additionalProperties':False,'properties':{}}}}
    def inner(self,node):
        return {'type':'object','additionalProperties':False,'properties':{'x':node}}
    def test_the_grammar_accepts_typed_closed_nodes(self):
        for schema in (SUMMARY_SCHEMA,self.GOOD):
            with self.subTest(schema=str(schema)[:50]):self.assertEqual(bp.summary_schema_problems(schema),[])
    def test_each_other_keyword_is_refused(self):
        num={'type':'number'}
        for name,node in (('$ref',{'$ref':'#/properties/y'}),('oneOf',{'oneOf':[num]}),('anyOf',{'anyOf':[num]}),('allOf',{'allOf':[num]}),
                          ('not',{'not':num}),('typed-not',dict(num,**{'not':{'type':'integer'}})),('if',dict(num,**{'if':num})),
                          ('then',dict(num,then=num)),('else',dict(num,**{'else':num})),('const',dict(num,const=1)),('enum-number',dict(num,enum=[1])),
                          ('$defs',{'type':'object','additionalProperties':False,'properties':{},'$defs':{'q':num}}),
                          ('patternProperties',{'type':'object','additionalProperties':False,'properties':{},'patternProperties':{'^a':num}}),
                          ('propertyNames',{'type':'object','additionalProperties':False,'properties':{},'propertyNames':{'pattern':'^a'}}),
                          ('dependentRequired',{'type':'object','additionalProperties':False,'properties':{'a':num},'dependentRequired':{'a':['a']}}),
                          ('dependentSchemas',{'type':'object','additionalProperties':False,'properties':{'a':num},'dependentSchemas':{'a':{}}}),
                          ('unevaluatedProperties',{'type':'object','additionalProperties':False,'properties':{},'unevaluatedProperties':False}),
                          ('unevaluatedItems',{'type':'array','items':num,'maxItems':4,'unevaluatedItems':False}),
                          ('contains',{'type':'array','items':num,'maxItems':4,'contains':num}),
                          ('prefixItems',{'type':'array','items':num,'maxItems':4,'prefixItems':[num]})):
            with self.subTest(keyword=name):self.assertTrue(bp.summary_schema_problems(self.inner(node)))
    def test_each_open_or_untyped_shape_is_refused(self):
        num={'type':'number'}
        for name,node in (('nested-empty',{}),('true',True),('false',False),('untyped-branch',{'minimum':0}),('untyped-object',{'properties':{'a':num},'additionalProperties':False}),
                          ('array-without-items',{'type':'array','maxItems':4}),('array-without-maxItems',{'type':'array','items':num}),
                          ('array-maxItems-too-large',{'type':'array','items':num,'maxItems':bp.SUMMARY_MAX_ITEMS+1}),('array-items-empty',{'type':'array','items':{},'maxItems':4}),
                          ('object-without-additionalProperties',{'type':'object','properties':{'a':num}}),('object-without-properties',{'type':'object','additionalProperties':False}),
                          ('additionalProperties-true',{'type':'object','properties':{},'additionalProperties':True}),
                          ('additionalProperties-schema',{'type':'object','properties':{},'additionalProperties':num}),
                          ('bad-property-name',{'type':'object','additionalProperties':False,'properties':{'Bad Key':num}}),
                          ('free-string',{'type':'string'}),('string-enum-of-data',{'type':'string','enum':['AAPL']}),('null-only',{'type':'null'}),
                          ('object-or-null',{'type':['object','null'],'additionalProperties':False,'properties':{}}),('two-types',{'type':['number','boolean']}),
                          ('unknown-type',{'type':'any'})):
            with self.subTest(shape=name):self.assertTrue(bp.summary_schema_problems(self.inner(node)))
        for root in ({},True,{'type':'array','items':num,'maxItems':4},{'type':'number'}):
            with self.subTest(root=str(root)):self.assertTrue(bp.summary_schema_problems(root))
    def test_malformed_values_are_problems_not_exceptions(self):
        """FR3-15: a required element that is not a string, a multipleOf that is not above 0 and a non-finite or
        non-numeric bound give a problem (GateError at the gate), never a Python exception."""
        num={'type':'number'}
        cases={'required-list':{'type':'object','additionalProperties':False,'properties':{'a':num},'required':[['a']]},
               'required-object':{'type':'object','additionalProperties':False,'properties':{'a':num},'required':[{'a':1}]},
               'required-number':{'type':'object','additionalProperties':False,'properties':{'a':num},'required':[1]},
               'required-not-list':{'type':'object','additionalProperties':False,'properties':{'a':num},'required':'a'},
               'multipleOf-zero':dict(num,multipleOf=0),'multipleOf-negative':dict(num,multipleOf=-1),'multipleOf-nan':dict(num,multipleOf=math.nan),
               'minimum-inf':dict(num,minimum=math.inf),'maximum-nan':dict(num,maximum=math.nan),'minimum-bool':dict(num,minimum=True),
               'exclusiveMaximum-string':dict(num,exclusiveMaximum='1'),'maxItems-float':{'type':'array','items':num,'maxItems':4.0},
               'properties-not-object':{'type':'object','additionalProperties':False,'properties':[]},'items-list':{'type':'array','items':[num],'maxItems':4},
               'enum-unhashable':{'type':'string','enum':[['VALID']]},'type-unhashable':{'type':[['number']]}}
        for name,node in cases.items():
            with self.subTest(case=name):
                schema=self.inner(node)
                self.assertTrue(bp.summary_schema_problems(schema))           # a problem list, no exception
                doc=closed_aggregate();doc['summary']={'x':{'a':1} if node.get('type')=='object' else 1}
                p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(doc))
                got,reason=accept(p,schema=schema);self.assertIsNone(got);self.assertNotEqual(reason,'valid')
    def test_huge_and_odd_numbers_are_problems_not_exceptions(self):
        """FR3-16: a numeric keyword holds a finite number that an IEEE-754 double represents. A huge integer (10**400,
        -10**400), a bool, NaN, an infinity or a numeric string gives the stable problem of its keyword at the top level
        and in a nested node (GateError at the gate), never OverflowError or another exception."""
        big=10**400;num={'type':'number'};arr={'type':'array','items':num,'maxItems':4}
        values={'big':big,'minus-big':-big,'bool':True,'nan':math.nan,'inf':math.inf,'minus-inf':-math.inf,'string':'1e9999'}
        nodes={}
        for key in ('minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf'):
            for t in ('number','integer'):
                for vname,v in values.items():nodes[f'{t}-{key}-{vname}']=({'type':t,key:v},'number-bound')
        for key,problem in (('maxItems','array-max-items'),('minItems','array-min-items')):
            for vname,v in values.items():nodes[f'array-{key}-{vname}']=(dict(arr,**{key:v}),problem)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        for name,(node,problem) in nodes.items():
            for where,schema in (('top',node),('nested',self.inner(node)),('deep',self.inner(self.inner(node)))):
                with self.subTest(case=name,where=where):
                    got=bp.summary_schema_problems(schema)          # a problem list, no exception
                    self.assertIn(problem,got)
                    if where=='top':continue
                    doc=closed_aggregate();doc['summary']={'x':1} if where=='nested' else {'x':{'x':1}}
                    p=Path(tmp.name)/'aggregate.json';p.write_text(json.dumps(doc))
                    out,reason=accept(p,schema=schema);self.assertIsNone(out);self.assertIn('GateError',reason)
    def test_numeric_bounds_at_the_double_limit(self):
        """FR3-16: the documented range of an integer bound is -int(DBL_MAX)..int(DBL_MAX) (exact bound passes, one past
        is a problem); a float bound passes up to DBL_MAX; zero passes as a bound and is refused as a multipleOf."""
        top=int(sys.float_info.max)
        for v in (0,1,-1,top,-top,sys.float_info.max,-sys.float_info.max,5e-324):
            with self.subTest(ok=str(v)[:20]):self.assertEqual(bp.summary_schema_problems(self.inner({'type':'number','minimum':v})),[])
        for v in (top+1,-top-1):
            with self.subTest(bad=str(v)[:20]):self.assertIn('number-bound',bp.summary_schema_problems(self.inner({'type':'number','maximum':v})))
        self.assertEqual(bp.summary_schema_problems(self.inner({'type':'integer','multipleOf':top})),[])
        self.assertIn('multiple-of',bp.summary_schema_problems(self.inner({'type':'number','multipleOf':0})))
        self.assertIn('number-bound',bp.summary_schema_problems(self.inner({'type':'number','multipleOf':top+1})))
    def test_a_huge_summary_integer_is_refused_not_an_exception(self):
        """FR3-16: a summary number must be representable as a double (|int| at most int(DBL_MAX)); a huge integer is a
        privacy problem, so a float multipleOf in the project schema never meets it (no OverflowError at the gate)."""
        top=int(sys.float_info.max)
        for v in (10**400,-10**400,top+1,-top-1):
            with self.subTest(bad=str(v)[:20]):self.assertIn('number-range',bp.summary_value_problems({'a':v,'b':[v]}))
        for v in (top,-top,0):
            with self.subTest(ok=str(v)[:20]):self.assertEqual(bp.summary_value_problems({'a':v}),[])
        schema=self.inner({'type':'number','multipleOf':0.5})
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        for v in (10**400,-10**400):
            with self.subTest(gate=str(v)[:20]):
                doc=closed_aggregate();doc['summary']={'x':v}
                p=Path(tmp.name)/'aggregate.json';p.write_text(json.dumps(doc))
                out,reason=accept(p,schema=schema);self.assertIsNone(out);self.assertIn('GateError',reason)
        doc=closed_aggregate();doc['summary']={'x':2.5}
        p=Path(tmp.name)/'aggregate.json';p.write_text(json.dumps(doc));self.assertEqual(accept(p,schema=schema)[1],'valid')   # control
    def test_a_nested_empty_schema_lets_no_summary_pass(self):
        schema=self.inner({})                   # the verdict example: {"x":{}} would accept {"x":{"<any key>":1}}
        doc=closed_aggregate();doc['summary']={'x':{'anykey':1}}
        p=Path(tempfile.mkdtemp())/'aggregate.json';p.write_text(json.dumps(doc))
        (got,reason)=accept(p,schema=schema);self.assertIsNone(got);self.assertNotEqual(reason,'valid')

# FR3: MarketGateTests (the example project's market block on the host gate) and the market step tests of LocalJobTests
# moved to the example handoff list with the market feature; the generic gate tests above replace their framework part.
FIXTURE='tests/fixtures/bench-project'

class RunStatusTests(unittest.TestCase):
    def test_run_status_names_the_reason(self):
        doc=closed_aggregate();self.assertEqual(bp.local_run_status(doc,'valid'),('VALID',[]))
        bad=dict(doc,status='INVALID_EXPERIMENT');self.assertEqual(bp.local_run_status(bad,'some gate reason'),('INVALID_EXPERIMENT',['some gate reason']))
        self.assertEqual(bp.local_run_status(bad,'valid'),('INVALID_EXPERIMENT',['aggregate status INVALID_EXPERIMENT']))
        self.assertEqual(bp.local_run_status(None,'aggregate rejected (GateError); 9 bytes kept as a count only')[0],'INVALID_EXPERIMENT')

class LocalCollectionTests(unittest.TestCase):
    """Task 18b: the aggregate is collected whenever the artifact-directory check passes, also after a failed job, so its
    reason reaches the run reasons. A failed job with a VALID aggregate is inconsistent and gives no aggregate. FR3: the run
    is a run of the fixture project, whose protocol holds the summary schema; run.json records the protocol digest."""
    def run_local(self,job_exit,doc,check_exit=0,session=None):
        import bench, shutil
        root=Path(tempfile.mkdtemp());shutil.copytree(ROOT/'schemas',root/'schemas');(root/'safety').mkdir()
        shutil.copytree(ROOT/FIXTURE,root/FIXTURE)
        for name in ('safety/performance-policy.json','safety/performance-fixtures.json','developer.lock.json','safety/container-policy.json'):shutil.copy(ROOT/name,root/name)   # T16: bench_profile_sha256 reads the bench profile
        class Runner:
            def run(self,*a,**k):return {'exit_code':check_exit,'failure':None}
        Runner.session=session
        class Session:
            image=staticmethod(lambda root:'sha256:'+'e'*64)
            def __init__(self,*a,**k):self.runner=Runner()
            def job(self,plan,*a,**k):return {'exit_code':job_exit,'failure':None,'evidence_path':'x'}
            def fetch(self,rel,dst):Path(dst).write_text(json.dumps(doc));return dst
            def close(self):pass
        plan={'mode':'smoke','project_dir':FIXTURE,'dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None,'path':'/private/dataset.json'},
              'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}
        with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',Session),\
             mock.patch.object(bench,'doctor_probe',PERMITTED_PROBE),mock.patch.object(bench,'guardrail_gate',PERMITTED_GATE),\
             mock.patch('policy.source_identity',return_value=('f'*64,None)),contextlib.redirect_stdout(io.StringIO()),\
             mock.patch.object(bp,'install_fixture_pattern',return_value=True):      # Task 27 pattern step
            rc=bp.run_local(root,argparse.Namespace(format='json'),plan,{'case_id':'record-scan','version':1},{'sizes':{'small':256},'job_deadlines':{'session':10800}})
        run=json.loads(next(root.glob('artifacts/bench/*/run.json')).read_text());return rc,run
    def test_an_invalid_aggregate_status_is_the_run_reason(self):
        doc=dict(closed_aggregate(),status='INVALID_EXPERIMENT')
        rc,run=self.run_local(1,doc);self.assertEqual(rc,1);self.assertEqual((run['status'],run['reasons']),('INVALID_EXPERIMENT',['local job failed (exit 1)']))
        self.assertEqual(run['evidence']['aggregate'],'aggregate.json')
        rc,run=self.run_local(0,doc);self.assertEqual((run['status'],run['reasons']),('INVALID_EXPERIMENT',['aggregate status INVALID_EXPERIMENT']))
    def test_a_refused_or_failed_job_keeps_its_reason(self):
        """Review Important 1: a refusal (exit 3, no local_summary) or a failed job writes an empty summary."""
        for code,text in ((3,'local job refused (exit 3)'),(1,'local job failed (exit 1)')):
            doc=dict(closed_aggregate(),status='INVALID_EXPERIMENT',rows=0,summary=None)
            rc,run=self.run_local(code,doc)
            with self.subTest(code=code):
                self.assertEqual(rc,1);self.assertEqual((run['status'],run['reasons']),('INVALID_EXPERIMENT',[text]));self.assertEqual(run['evidence']['aggregate'],'aggregate.json')
    def test_a_failed_job_with_a_valid_aggregate_gives_none(self):
        rc,run=self.run_local(1,closed_aggregate())
        self.assertEqual((rc,run['status'],run['evidence']['aggregate']),(1,'INVALID_EXPERIMENT',None))
    def test_the_local_run_binds_its_evidence(self):                 # Task 16 (H8): the main local path records digests and the profile digest
        import bench_evidence as be, bench_model as bm
        rc,run=self.run_local(0,closed_aggregate())
        self.assertEqual((rc,run['status']),(0,'VALID'));self.assertIn('aggregate.json',run['evidence_digests'])
        self.assertEqual(run['bench_profile_sha256'],be.bench_profile_sha256(ROOT))
        self.assertEqual(run['protocol_sha256'],bm.protocol_digest(ROOT,FIXTURE))       # FR3: the protocol digest is bound
    def test_a_summary_outside_the_protocol_schema_is_rejected(self):
        bad=closed_aggregate();bad['summary']={'other':1}
        rc,run=self.run_local(0,bad);self.assertEqual((rc,run['status'],run['evidence']['aggregate']),(1,'INVALID_EXPERIMENT',None))
    def test_a_smoke_row_outside_the_plan_is_invalid(self):
        """T5-A11: the host row check of the decision jobs also applies to a Phase 1 smoke aggregate: a timing row that is
        no planned row makes the run INVALID_EXPERIMENT; the record names the problem code, never the row's values."""
        dist={'n':1,'median':1.0,'iqr':0.0,'min':1.0,'max':1.0}
        row={'point':'unplanned-point','scope':'caller','mode':'warm','variant':'py-reference','workers':'direct','tier':'small','trials':1,'eligible':True,
             'wall_ns_per_unit':dist,'cpu_ns_per_unit':dist}
        rc,run=self.run_local(0,dict(closed_aggregate(),timings=[row]))
        self.assertEqual((rc,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('local rows: rows-unplanned',run['reasons'])
        self.assertNotIn('unplanned-point',json.dumps(run))
    def test_a_passing_job_and_a_failed_directory_check(self):
        rc,run=self.run_local(0,closed_aggregate());self.assertEqual((rc,run['status'],run['reasons']),(0,'VALID',[]))
        rc,run=self.run_local(0,closed_aggregate(),check_exit=3)
        self.assertEqual((run['status'],run['reasons']),('INVALID_EXPERIMENT',['local job or artifact-directory check failed']))

    def test_the_local_run_records_the_observed_active_before(self):
        """Approval P1-R1-08: the admission record holds the session's observed bench.active_before, and null (never 0)
        when the launcher reported none."""
        doc=closed_aggregate()
        _,run=self.run_local(0,doc,session={'bench':{'envelope':None,'active_before':0}});self.assertEqual(run['admission']['active_at_handshake'],[0])
        _,run=self.run_local(0,doc,session={'bench':{'envelope':None,'active_before':2}});self.assertEqual(run['admission']['active_at_handshake'],[2])
        _,run=self.run_local(0,doc,session=None);self.assertEqual(run['admission']['active_at_handshake'],[None])
    def test_the_active_before_helper_never_substitutes_zero(self):
        import bench
        class S:
            def __init__(self,session):self.runner=type('R',(),{'session':session})()
        self.assertEqual(bench.active_before(S({'bench':{'active_before':0}})),0)
        self.assertEqual(bench.active_before(S({'bench':{'active_before':3}})),3)
        for session in (None,{},{'bench':None},{'bench':{}},{'bench':{'active_before':-1}},{'bench':{'active_before':True}}):
            with self.subTest(session=session):self.assertIsNone(bench.active_before(S(session)))

class LocalGateTests(unittest.TestCase):
    def test_failing_before_run_check_stops_the_local_run(self):
        """Amendment A item 4 (M5): a failing pre-run check ends a local: run before the owner-fixture container exists."""
        import argparse, contextlib, io, bench
        root=Path(tempfile.mkdtemp());jobs=[]
        class NoSession:
            def __init__(self,*a,**k):jobs.append(('session',k.get('fixture') is not None))
            def job(self,plan,*a,**k):jobs.append(plan['job'])
        plan={'mode':'smoke','project_dir':None,'dataset':{'kind':'local','sha256':'a'*64,'path':'/nonexistent/dataset.json'},'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}
        saved=(bench.before_run_checks,bench.BenchSession)
        bench.before_run_checks=lambda r,d,proj:(['pre-run check b06-prerequisite-oracle: FAIL'],[]);bench.BenchSession=NoSession
        try:
            out=io.StringIO()
            with contextlib.redirect_stdout(out),mock.patch.object(bench,'doctor_probe',PERMITTED_PROBE),mock.patch.object(bench,'guardrail_gate',PERMITTED_GATE),\
                 mock.patch.object(bp,'install_fixture_pattern',return_value=True):rc=bp.run_local(root,argparse.Namespace(format='json'),plan,{'case_id':'record-scan','version':1},{'sizes':{'small':256},'job_deadlines':{'session':10800}})
        finally:bench.before_run_checks,bench.BenchSession=saved
        self.assertEqual(rc,1);self.assertIn('INVALID_EXPERIMENT',out.getvalue());self.assertEqual(jobs,[])
        self.assertNotIn('/nonexistent',out.getvalue())
        written=next(root.glob('artifacts/bench/*/plan.json')).read_text();self.assertNotIn('/nonexistent',written)
    def test_a_session_error_that_names_the_fixture_is_withheld(self):
        """Review Important 1 audit: an error raised after the pre-run gate whose text holds the fixture path or name is replaced."""
        import bench
        root=Path(tempfile.mkdtemp());path='/private/owner_secret_dataset.json'
        class FailingSession:
            def __init__(self,*a,**k):raise OSError(5,'Input/output error',path)
        plan={'mode':'smoke','project_dir':None,'dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None,'path':path},
              'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}
        with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',FailingSession),\
             mock.patch.object(bench,'doctor_probe',PERMITTED_PROBE),mock.patch.object(bench,'guardrail_gate',PERMITTED_GATE),\
             mock.patch.object(bp,'install_fixture_pattern',return_value=True):   # T12-C4: the B12 step passes here; Task 27 pattern step
            with self.assertRaises(GateError) as ctx:
                bp.run_local(root,argparse.Namespace(format='json'),plan,{'case_id':'record-scan','version':1},{'sizes':{'small':256},'job_deadlines':{'session':10800}})
        self.assertNotIn(path,str(ctx.exception));self.assertNotIn('owner_secret_dataset',str(ctx.exception))
    def test_privacy_probe_fails_when_the_value_is_kept_under_any_key(self):
        """Review Minor 2: the probe value must be absent from the whole evidence record."""
        import bench
        for record,want in (({'output':'','output_bytes':23},'PASS'),({'output':'','output_bytes':23,'stderr_text':'synthetic value '+bp.PROBE_VALUE},'FAIL')):
            ev=Path(tempfile.mkdtemp())/'e.json';ev.write_text(json.dumps(record))
            class ProbeSession:
                def __init__(self,*a,**k):pass
                def job(self,*a,**k):return {'exit_code':0,'failure':None,'evidence_path':str(ev)}
                def close(self):pass
            with self.subTest(want=want),mock.patch.object(bench,'BenchSession',ProbeSession):
                self.assertEqual(bp.privacy_probe(ROOT,Path(tempfile.mkdtemp()))['status'],want)
    def test_decision_mode_runs_the_local_decision_runner(self):
        """EX-19 (Task 31): the decision branch replaces the Phase 1 refusal ('decision runs on the owner fixture belong to
        Phase 3'); the fixture path leaves the plan first. Any other mode is still refused."""
        import argparse
        plan={'mode':'decision','dataset':{'kind':'local','sha256':'a'*64,'path':'/nonexistent/dataset.json'}}
        with mock.patch('bench_local_decision.run_local_decision',return_value=0) as run:
            self.assertEqual(bp.run_local(Path(tempfile.mkdtemp()),argparse.Namespace(format='json'),plan,{'case_id':'record-scan','version':1},{}),0)
        self.assertEqual(run.call_args[0][5],'/nonexistent/dataset.json');self.assertNotIn('path',run.call_args[0][2]['dataset'])
        self.assertNotIn('belong to Phase 3',(ROOT/'tools/bench_privacy.py').read_text())
        for mode in ('profile','selftest'):
            with self.subTest(mode=mode),self.assertRaises(GateError):
                bp.run_local(Path(tempfile.mkdtemp()),argparse.Namespace(format='json'),dict(plan,mode=mode,dataset=dict(plan['dataset'])),{'case_id':'record-scan','version':1},{})

class LocalCheckTests(unittest.TestCase):
    """The coordinator's --local-check: exactly one regular aggregate.json of at most 256 KiB in the artifact directory."""
    def check(self,setup):
        bc=coordinator();work=Path(tempfile.mkdtemp());out=work/'bench/out';out.mkdir(parents=True);setup(out);bc.WORK=work
        return bc.main(['bench-coordinator.py','--local-check','bench/out'])
    def test_one_bounded_aggregate_passes(self):
        self.assertEqual(self.check(lambda o:(o/'aggregate.json').write_text('{}')),0)
    def test_other_contents_fail(self):
        cases={'empty':lambda o:None,'extra file':lambda o:((o/'aggregate.json').write_text('{}'),(o/'result.json').write_text('{}')),
               'oversized':lambda o:(o/'aggregate.json').write_bytes(b' '*(262144+1)),'directory':lambda o:(o/'aggregate.json').mkdir(),
               'link':lambda o:((o/'x').write_text('{}'),(o/'aggregate.json').symlink_to(o/'x'))}
        for name,setup in cases.items():
            with self.subTest(name=name):self.assertEqual(self.check(setup),3)
    def test_link_alone_fails(self):
        def setup(o):
            target=Path(tempfile.mkdtemp())/'a.json';target.write_text('{}');(o/'aggregate.json').symlink_to(target)
        self.assertEqual(self.check(setup),3)

class PrivacySuiteTests(unittest.TestCase):
    def test_privacy_suite_runs_no_local_project_case_run(self):
        """Task 18a: `bench selftest --suite privacy` runs only the stderr probe, never a local: run."""
        import bench
        self.assertEqual(bench.privacy_suite_jobs(),['stderr-probe']);self.assertNotIn('local',bench.privacy_suite_jobs())

class LocalJobTests(unittest.TestCase):
    """Review Minor 1 and 5: the coordinator's local aggregate, its NaN fallback and the Amendment A refusal."""
    def setUp(self):
        from schema_check import validate
        self.validate=lambda doc:validate(ROOT,'bench-local-aggregate',doc)
        self.bc=coordinator();self.bc.AGGREGATE_SCHEMA=ROOT/'schemas/bench-local-aggregate.json'
        self.plan={'schema_version':1,'job':'local','run_id':'0'*32,'case':'record-scan','case_manifest':'/src/benchmarks/performance/cases/record-scan.json',
                   'dataset':{'kind':'local','sha256':'a'*64},'rows':4,'local':True,'output':'bench/out','deadline_seconds':60}
    def test_empty_aggregate_validates_with_a_null_summary(self):
        doc=self.bc.local_aggregate(self.plan,None,[],[],[],False);self.validate(doc);self.assertEqual(doc['status'],'INVALID_EXPERIMENT')
        self.assertIsNone(doc['summary']);self.assertEqual(doc['schema_version'],2)
        schema=json.loads((ROOT/'schemas/bench-local-aggregate.json').read_text());self.assertEqual(set(doc),set(schema['required']))
    def test_the_summary_is_every_project_key_of_local_summary(self):
        stats=dict(closed_aggregate()['summary'],rows=4,result_sha256='b'*64,reference_sha256='c'*64)
        doc=self.bc.local_aggregate(self.plan,stats,[],[],[],True);self.validate(doc)
        self.assertEqual((doc['summary'],doc['rows'],doc['status']),(closed_aggregate()['summary'],4,'VALID'))
        self.assertEqual(self.bc.local_aggregate(self.plan,stats,[],[],[],False)['status'],'INVALID_EXPERIMENT')
    def test_local_exceptions_come_from_the_plan_only(self):
        class ProjectError(Exception):pass
        self.bc.set_local_names({'local_exceptions':['ProjectError']});self.assertEqual(self.bc._exception_row(ProjectError())['type'],'ProjectError')
        self.bc.set_local_names({});self.assertEqual(self.bc._exception_row(ProjectError())['type'],'Other')
        self.assertEqual(self.bc._exception_row(ValueError())['type'],'ValueError')
        for bad in ({'local_exceptions':'ProjectError'},{'local_exceptions':['bad name']},{'local_exceptions':['A'+'b'*50]}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.bc.set_local_names(bad)
    def test_nan_summary_falls_back_to_the_empty_invalid_block(self):
        stats=dict(closed_aggregate()['summary'],rows=4,result_sha256='b'*64,reference_sha256='c'*64)
        stats['crosscheck']['s1']['f1']={'count':1,'median':math.nan,'p90':math.nan}
        out=Path(tempfile.mkdtemp());self.bc._write_aggregate(out,self.bc.local_aggregate(self.plan,stats,[],[],[],True),self.plan)
        doc=json.loads((out/'aggregate.json').read_text());self.validate(doc)
        self.assertEqual(doc['status'],'INVALID_EXPERIMENT');self.assertEqual(doc['exceptions'][-1]['type'],'ValueError');self.assertEqual(doc['rows'],0)
    def test_case_without_local_summary_is_refused_with_exit_3(self):
        """Amendment A: the has-summary child exits 3; the job writes only the empty INVALID_EXPERIMENT aggregate and exits 3."""
        work=Path(tempfile.mkdtemp());(work/'bench').mkdir();(work/'bench/plan.json').write_text(json.dumps(self.plan));self.bc.WORK=work
        calls=[]
        def fake_run(argv,**k):
            calls.append(argv);return subprocess.CompletedProcess(argv,3)
        with mock.patch.object(self.bc.subprocess,'run',side_effect=fake_run),mock.patch.object(self.bc,'_manifest',return_value='/m.json'),\
             mock.patch.object(self.bc,'job_timing',side_effect=AssertionError('no trial may run')):
            rc=self.bc.main(['bench-coordinator.py','bench/plan.json'])
        self.assertEqual(rc,3);self.assertEqual(len(calls),1)
        self.assertEqual(sorted(p.name for p in (work/'bench/out').iterdir()),['aggregate.json'])
        doc=json.loads((work/'bench/out/aggregate.json').read_text());self.validate(doc);self.assertEqual(doc['status'],'INVALID_EXPERIMENT')

    def test_the_coordinator_has_no_market_step_and_no_market_variable(self):
        """FR3: the market step left the framework (FR3 handoff list); no child gets a market variable."""
        self.assertFalse(hasattr(self.bc,'MARKET_CODE'));self.assertFalse(hasattr(self.bc,'local_market'))
        with mock.patch.dict(os.environ,{'SAFE_C_BENCH_MARKET':'/x'}):self.assertEqual(self.bc.child_env().get('SAFE_C_BENCH_MARKET'),'/x')   # inherited only as any other variable
        self.assertNotIn('SAFE_C_BENCH_MARKET',self.bc.child_env())

if __name__=='__main__':unittest.main()
