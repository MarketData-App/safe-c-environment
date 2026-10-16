"""FR3-17 (ruling FR3-R7): one fail-closed boundary for project-controlled JSON.

The framework reads project-controlled JSON at these entry points: bench.json (bench_model.project_bench, bench.new_case
and bench_readiness.demo_cases), a project case manifest (bench_model.load_case), a project opportunity record
(bench_model.load_opportunity), the protocol file, its approval record and its aggregate schema (bench_model.load_protocol),
the protocol oracle and aggregate schema data (bench_model.protocol_data), the local aggregate
(bench_privacy.accept_aggregate), a panel pre-flight record (bench_panel.load_rejected), a panel reference
(bench_units._panel_reference), project.json (project_model.load_project), review/ledger.json (project_check.review_gate)
and the owner confirmation (bench_phase3_cli._sensitivity). Malformed data gives GateError with the stable problem name
project-data-invalid:<kind>:<reason> (exit 2), or the documented refusal value of an entry point that returns one (the
aggregate gate deletes the document; the review gate gives FAIL; the confirmation is refused; the readiness scan skips the
project). Never another Python exception. Every mutation runs in a temporary root; the tree is never changed."""
import argparse, contextlib, hashlib, io, json, random, shutil, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm
from evidence import GateError

FIXTURE='tests/fixtures/bench-project';CASE_ID='fixture-case';NEW_CASE='zz-boundary-case';DEMO='examples/boundary-demo'
DEEP=10**5                                    # the brief: 10**5 nesting levels of [ and of {
DEEP_ARRAYS=('['*DEEP+']'*DEEP).encode();DEEP_OBJECTS=('{"a":'*DEEP+'0'+'}'*DEEP).encode()   # built once (FR3-R10)
DEEP_MIXED=('[{"a":'*(DEEP//2)).encode()
SEED=20261014;DOCUMENTS=2000                  # the property test: a fixed seed and at least 2,000 documents
# The documented caps (docs/performance-laboratory.md): bytes per kind and 64 nesting levels.
MIB=1048576
CAPS={'bench-json':4*MIB,'case-manifest':4*MIB,'opportunity-record':4*MIB,'protocol':4*MIB,'protocol-approval':4096,
      'aggregate-schema':16*MIB,'oracle':16*MIB,'aggregate':262144,'preflight-record':4*MIB,'panel-reference':16*MIB,
      'project-json':4*MIB,'review-ledger':16*MIB,'owner-confirmation':4*MIB}
MAX_DEPTH=64

AREA=f'{FIXTURE}/{bm.PROJECT_AREA}'
FILES={'bench':f'{AREA}/bench.json','case':f'{AREA}/cases/{CASE_ID}.json','opportunity':f'{AREA}/cases/{CASE_ID}.opportunity.json',
       'protocol':f'{AREA}/protocol/protocol.json','approval':f'{AREA}/protocol/approval.json',
       'schema':f'{AREA}/protocol/aggregate.schema.json','oracle':f'{AREA}/protocol/oracle.json'}

def sha(data):return hashlib.sha256(data).hexdigest()

def closed_aggregate():
    fields=('f1','f2','f3','f4','f5')
    return {'schema_version':2,'run_id':'0'*32,'case':CASE_ID,'dataset_sha256':'a'*64,'rows':64,
            'summary':{'crosscheck':{s:{f:{'count':0,'median':None,'p90':None} for f in fields} for s in ('s1','s2')}},
            'timings':[],'counters':{'cpu_usage_usec':0,'memory_peak_bytes':None},'exceptions':[],
            'output_digests':{'result_sha256':'b'*64,'reference_sha256':'c'*64},'status':'VALID'}

PROJECT={'schema_version':1,'name':'demo-app','modules':[{'name':'greeting','spec':'specs/project/greeting.md','sources':['src/greeting.c'],
  'headers':['include/greeting.h'],'tests':['tests/project/test_greeting.c'],'reads_external_input':True,
  'fuzz':[{'name':'greeting','harness':'fuzz/project/greeting_fuzz.c','corpus':'fuzz/project/corpus/greeting','regressions':'fuzz/project/regressions/greeting'}]}],
  'programs':[{'name':'hello','main':'src/main.c','modules':['greeting']}],'run':{'program':'hello','args':['world'],'expect_exit':0}}
LEDGER={'schema_version':1,'source_identity':'s','units':{'greeting':['src/greeting.c']},
        'findings':[{'id':'F-1','origin':'reviewer','source_identity':'s','location':'src/greeting.c:1','property':'p','severity':'high',
                     'rationale':'r','reproducer':'t','state':'REJECTED','attempts':0,'history':[],'verification':None}],
        'review':[{'unit':'greeting','question':'q','locations':[1]}]}

class Scratch:
    """A temporary framework root with the fixture project (the protocol tests' layout), an example project for the
    readiness scan, a run directory for the aggregate and a separate project-mode root for project.json and the review
    ledger. `restore()` puts back every file that the last call changed, so each call reads exactly one changed document.
    FR3-R10: one scratch root per test class; the baseline documents are parsed once."""
    def __init__(self,owner):
        t=Path(tempfile.mkdtemp(prefix='safe-c-boundary-'));owner.addClassCleanup(shutil.rmtree,t,True);self.t=t
        shutil.copytree(ROOT/'schemas',t/'schemas');(t/'safety').mkdir()
        for rel in ('safety/performance-policy.json','developer.lock.json'):shutil.copyfile(ROOT/rel,t/rel)
        (t/bm.CASES).mkdir(parents=True);shutil.copytree(ROOT/FIXTURE,t/FIXTURE)
        (t/DEMO/bm.PROJECT_AREA).mkdir(parents=True);(t/'run').mkdir()
        self.base={k:(t/rel).read_bytes() for k,rel in FILES.items()}
        self.protocol=json.loads(self.base['protocol'])
        self.case=json.loads(self.base['case'])
        self.coverage=t/'coverage.json';self.coverage.write_text('{"status":"PASS"}')
        p=t/'project-mode';self.p=p
        files={'project.json':json.dumps(PROJECT),'specs/project/greeting.md':'# spec','src/greeting.c':'int x;','src/main.c':'int main(void){return 0;}',
               'include/greeting.h':'int x;','tests/project/test_greeting.c':'int main(void){return 0;}','fuzz/project/greeting_fuzz.c':'int y;',
               'fuzz/project/corpus/greeting/seed':'a','fuzz/project/regressions/greeting/.keep':'','review/ledger.json':json.dumps(LEDGER)}
        for rel,text in files.items():
            f=p/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(text)
        self.project_base={'project.json':json.dumps(PROJECT).encode(),'review/ledger.json':json.dumps(LEDGER).encode()}
        self.by_path={self.path(k):data for k,data in self.base.items()}
        self.by_path.update({p/rel:data for rel,data in self.project_base.items()})
        self.bench_doc=json.loads(self.base['bench']);self.protocol_doc=json.loads(self.base['protocol'])
        self.schema_doc=json.loads(self.base['schema']);self.dirty=set();self.zero={}
    def path(self,key):return self.t/FILES[key]
    def write(self,path,data):
        """`data` is bytes, or an int n: a sparse file of n zero bytes (no tmpfs pages, so a one-past-the-cap file is
        cheap). The path is restored before the next call."""
        path.parent.mkdir(parents=True,exist_ok=True);self.dirty.add(path)
        if isinstance(data,int):
            with open(path,'wb') as f:f.truncate(data)
        else:path.write_bytes(data)
    def sha(self,data):
        """sha256 of the bytes, or of n zero bytes for an int n (computed once per n)."""
        if not isinstance(data,int):return sha(data)
        if data not in self.zero:self.zero[data]=sha(b'\0'*data)
        return self.zero[data]
    def restore(self):
        for p in self.dirty:
            if p in self.by_path:p.write_bytes(self.by_path[p])
            elif p.exists() or p.is_symlink():p.unlink()
        self.dirty.clear()
        new=self.t/AREA/'cases'/(NEW_CASE+'.json')
        if new.exists():          # an accepted new_case scaffold: rebuild the fixture project from the tree
            shutil.rmtree(self.t/FIXTURE);shutil.copytree(ROOT/FIXTURE,self.t/FIXTURE)
    def bind(self,doc):
        """Write the protocol document `doc` and bind its digest in bench.json and in a new approval record."""
        data=json.dumps(doc).encode();self.write(self.path('protocol'),data)
        decl=dict(self.bench_doc,protocol=dict(self.bench_doc['protocol'],sha256=sha(data)));self.write(self.path('bench'),json.dumps(decl).encode())
        self.write(self.path('approval'),json.dumps({'schema_version':1,'protocol_sha256':sha(data),'reference':doc['approval']['reference'],
                                                     'verdict':'APPROVE','approver':'fresh-context-agent'}).encode())


# ---- the entry points: each driver writes one document and calls one entry point ----
# mode 'raise': the refusal is GateError. 'aggregate': (None, reason) and the document is deleted. 'row': a FAIL row.
# 'refuse': None (the confirmation is refused). 'skip': the readiness scan holds no case of the project.
def d_bench(s,data):
    s.write(s.path('bench'),data);return bm.project_bench(s.t,FIXTURE)
def d_new_case(s,data):
    import bench
    s.write(s.path('bench'),data);return bench.new_case(s.t,NEW_CASE,FIXTURE)
def d_readiness(s,data):
    import bench_readiness
    s.write(s.t/DEMO/bm.PROJECT_AREA/'bench.json',data);return {c for c in bench_readiness.demo_cases(s.t) if c[0]==DEMO}
def d_case(s,data):
    s.write(s.path('case'),data);return bm.load_case(s.t,CASE_ID,FIXTURE)
def d_opportunity(s,data):
    s.write(s.path('opportunity'),data);return bm.load_opportunity(s.t,s.case,FIXTURE)
def d_protocol(s,data):
    s.write(s.path('protocol'),data);decl=dict(s.bench_doc,protocol=dict(s.bench_doc['protocol'],sha256=s.sha(data)))
    s.write(s.path('bench'),json.dumps(decl).encode());return bm.load_protocol(s.t,FIXTURE)
def d_approval(s,data):
    s.write(s.path('approval'),data);return bm.load_protocol(s.t,FIXTURE)
def _bound_file(s,key,ref,data):
    s.write(s.path(key),data);doc=dict(s.protocol_doc);doc[ref]=dict(doc[ref],sha256=s.sha(data));s.bind(doc)
def d_schema(s,data):
    _bound_file(s,'schema','aggregate_schema',data);return bm.protocol_data(s.t,FIXTURE,'aggregate_schema')
def d_oracle(s,data):
    _bound_file(s,'oracle','oracle',data);return bm.protocol_data(s.t,FIXTURE,'oracle')
def d_aggregate(s,data,project=False):
    import bench_privacy as bp
    p=s.t/'run'/'aggregate.json';s.write(p,data)
    if project:return bp.accept_aggregate(s.t,p,project_dir=FIXTURE),p
    return bp.accept_aggregate(s.t,p,summary_schema=s.schema_doc,exceptions=()),p
def d_aggregate_project(s,data):return d_aggregate(s,data,project=True)
def d_preflight(s,data):
    import bench_panel
    rel=f'{bench_panel.PREFLIGHT_DIR}/{s.sha(data)}.json';s.write(s.t/AREA/rel,data)
    with mock.patch.object(bench_panel,'tracked',return_value=True):return bench_panel.load_rejected(s.t,FIXTURE,rel)
def d_panel(s,data):
    import bench_units
    s.write(s.path('case').with_name(CASE_ID+'.panel.json'),data);return bench_units._panel_reference(s.t,FIXTURE,CASE_ID)
def d_project(s,data):
    import project_model as pm
    s.write(s.p/'project.json',data);return pm.load_project(s.p,'.',framework_root=ROOT)
def d_review(s,data):
    import project_check as pc
    s.write(s.p/'review/ledger.json',data);return pc.review_gate(s.p,'.',ROOT)
def d_confirmation(s,data):
    import bench_phase3_cli as cli
    p=s.t/'confirmation.json';s.write(p,data)
    with contextlib.redirect_stdout(io.StringIO()):
        return cli._sensitivity(s.t,argparse.Namespace(format='json',sensitivity_confirmation=str(p)))

def baselines(s):
    """The valid (or near-valid) document of each driver; the property test mutates it."""
    return {'bench':json.loads(s.base['bench']),'new-case':json.loads(s.base['bench']),'readiness':json.loads(s.base['bench']),
            'case':json.loads(s.base['case']),'opportunity':json.loads(s.base['opportunity']),'protocol':json.loads(s.base['protocol']),
            'approval':json.loads(s.base['approval']),'schema':json.loads(s.base['schema']),'oracle':json.loads(s.base['oracle']),
            'aggregate':closed_aggregate(),'aggregate-project':closed_aggregate(),'preflight':{'replacements':[],'carried':[]},
            'panel':{'schema_version':1,'sha256':'0'*64},'project':copy_of(PROJECT),'review':copy_of(LEDGER),
            'confirmation':{'schema_version':1,'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64,'coverage_path':'coverage.json',
                            'owner_words':'boundary','date':'2026-10-14'}}

def copy_of(v):return json.loads(json.dumps(v))

# name: (driver, kind, mode)
DRIVERS={'bench':(d_bench,'bench-json','raise'),'new-case':(d_new_case,'bench-json','raise'),'readiness':(d_readiness,'bench-json','skip'),
         'case':(d_case,'case-manifest','raise'),'opportunity':(d_opportunity,'opportunity-record','raise'),
         'protocol':(d_protocol,'protocol','raise'),'approval':(d_approval,'protocol-approval','raise'),
         'schema':(d_schema,'aggregate-schema','raise'),'oracle':(d_oracle,'oracle','raise'),
         'aggregate':(d_aggregate,'aggregate','aggregate'),'aggregate-project':(d_aggregate_project,'aggregate','aggregate'),
         'preflight':(d_preflight,'preflight-record','raise'),'panel':(d_panel,'panel-reference','raise'),
         'project':(d_project,'project-json','raise'),'review':(d_review,'review-ledger','row'),
         'confirmation':(d_confirmation,'owner-confirmation','refuse')}

def outcome(s,name,data):
    """('accept', value) or ('refuse', text) for one call; any exception other than GateError propagates."""
    fn,kind,mode=DRIVERS[name];s.restore()
    try:got=fn(s,data)
    except GateError as exc:
        if mode!='raise':raise AssertionError(f'{name}: GateError from an entry point that returns its refusal') from None
        return 'refuse',str(exc)
    if mode=='aggregate':
        (doc,reason),p=got
        if doc is None:
            if p.exists() or p.is_symlink():raise AssertionError(f'{name}: a rejected aggregate stayed on disk')
            return 'refuse',reason
        return 'accept',doc
    if mode=='row':return ('accept',got) if got['status']=='PASS' else ('refuse',got['details'].get('reason',''))
    if mode=='refuse':return ('refuse','') if got is None else ('accept',got)
    if mode=='skip':return ('refuse','') if not got else ('accept',got)
    return 'accept',got

class Shared(unittest.TestCase):
    """FR3-R10: the test classes share one scratch root per class (each call restores what the last call changed)."""
    shared=None
    def scratch(self):
        cls=type(self)
        if cls.__dict__.get('shared') is None:cls.shared=Scratch(cls)
        return cls.shared

class RefusedFormTests(Shared):
    """Each refused form at each entry point: the stable problem name (or the entry point's refusal value)."""
    def refused(self,data,reason):
        s=self.scratch()
        for name,(fn,kind,mode) in DRIVERS.items():
            with self.subTest(entry=name):
                state,text=outcome(s,name,data)
                self.assertEqual(state,'refuse')
                # the size cap comes first: a document larger than the cap of its kind (a 10**5-level document is larger
                # than the 4096-byte approval record cap and the 256 KiB aggregate cap) is refused as too-large
                want='too-large' if len(data)>CAPS[kind] else reason
                if mode in ('raise','aggregate','row'):self.assertIn(f'project-data-invalid:{kind}:{want}',text)
    def test_deep_arrays(self):
        self.refused(DEEP_ARRAYS,'too-deep')
    def test_deep_objects(self):
        self.refused(DEEP_OBJECTS,'too-deep')
    def test_deep_mixed_and_unbalanced(self):
        self.refused(DEEP_MIXED,'too-deep')
    def test_invalid_utf8(self):
        self.refused(b'{"a":"\xff\xfe"}','not-utf-8')
    def test_duplicate_keys(self):
        self.refused(b'{"schema_version":1,"schema_version":1}','duplicate-key')
    def test_nan_and_infinity_literals(self):
        for literal in (b'NaN',b'Infinity',b'-Infinity'):
            with self.subTest(literal=literal):self.refused(b'{"schema_version":'+literal+b'}','non-finite-literal')
    def test_numbers_that_overflow_to_infinity(self):
        """FR3-20: a number literal that parses to inf or -inf is refused at the boundary like the Infinity token."""
        for literal in (b'1e400',b'-1e999',b'1E+400',b'-0.1e310'):
            with self.subTest(literal=literal):self.refused(b'{"schema_version":'+literal+b'}','non-finite-literal')

class NonFiniteNumberTests(unittest.TestCase):
    """FR3-20: the finite boundary refuses every number that parses to a non-finite float; the largest finite double and
    an underflow to zero stay accepted; the readers without `finite` keep the json.loads values."""
    def load(self,data,finite=True):
        from evidence import load_project_json
        return load_project_json(data,'fr3-20',4096,finite=finite)
    def test_the_largest_finite_double_is_accepted_and_one_past_is_refused(self):
        self.assertEqual(self.load(b'[1.7976931348623157e308]'),[1.7976931348623157e308])
        self.assertEqual(self.load(b'[-1.7976931348623157e308]'),[-1.7976931348623157e308])
        for data in (b'[1.7976931348623159e308]',b'[1.8e308]',b'[-1.8e308]',b'[1e400]',b'{"a":[0,{"b":-1e999}]}'):
            with self.subTest(data=data):
                with self.assertRaisesRegex(GateError,r'^project-data-invalid:fr3-20:non-finite-literal '):self.load(data)
    def test_zero_underflow_and_integers_stay_accepted(self):
        self.assertEqual(self.load(b'[1e-400,0,-0.0,0e999]'),[0.0,0,-0.0,0.0])
        self.assertEqual(self.load(b'['+b'9'*400+b']'),[int('9'*400)])         # an integer literal never becomes a float
    def test_readers_without_finite_keep_the_json_values(self):
        import math
        from evidence import loads_capped
        self.assertEqual(self.load(b'[1e400,-1e400]',finite=False),[math.inf,-math.inf])
        self.assertEqual(loads_capped(b'[1e400]'),[math.inf])

class DepthBoundTests(Shared):
    """The depth cap is 64 levels on the raw text: 65 levels is refused; brackets inside strings and escaped quotes do not
    count; the valid baselines still load."""
    def test_one_past_the_depth_cap_is_refused_at_every_entry_point(self):
        s=self.scratch()
        for name,(fn,kind,mode) in DRIVERS.items():
            with self.subTest(entry=name):
                state,text=outcome(s,name,('['*(MAX_DEPTH+1)+']'*(MAX_DEPTH+1)).encode())
                self.assertEqual(state,'refuse')
                if mode in ('raise','aggregate','row'):self.assertIn(f'project-data-invalid:{kind}:too-deep',text)
    def test_at_the_depth_cap_the_document_is_parsed(self):
        s=self.scratch()
        for name,(fn,kind,mode) in DRIVERS.items():
            with self.subTest(entry=name):
                state,text=outcome(s,name,('['*MAX_DEPTH+']'*MAX_DEPTH).encode())    # parsed; a shape rule may refuse it
                self.assertNotIn('too-deep',text)
        self.assertEqual(outcome(s,'oracle',('['*MAX_DEPTH+']'*MAX_DEPTH).encode())[0],'accept')    # the oracle has no shape rule
    def test_brackets_and_escaped_quotes_inside_strings_do_not_count(self):
        s=self.scratch();text='"]'*100+'\\'+'[{'*200+'\\"'*50+'{'*100
        oracle=json.loads(s.base['oracle']);oracle['fixture']=text
        self.assertEqual(outcome(s,'oracle',json.dumps(oracle).encode()),('accept',oracle))
        ledger=copy_of(LEDGER);ledger['findings'][0]['rationale']=text
        self.assertEqual(outcome(s,'review',json.dumps(ledger).encode())[0],'accept')
    def test_the_valid_baselines_load(self):
        s=self.scratch();base=baselines(s)
        for name in ('bench','readiness','case','opportunity','protocol','approval','schema','oracle','aggregate','aggregate-project','preflight','project','review'):
            with self.subTest(entry=name):
                data=s.base['protocol'] if name=='protocol' else json.dumps(base[name]).encode()
                self.assertEqual(outcome(s,name,data)[0],'accept')

class SizeCapTests(Shared):
    """One byte past the cap of each kind is refused before the parse; a valid document padded to exactly the cap loads."""
    def test_one_past_the_cap_is_refused(self):
        s=self.scratch()
        for name,(fn,kind,mode) in DRIVERS.items():
            with self.subTest(entry=name):
                state,text=outcome(s,name,CAPS[kind]+1)
                self.assertEqual(state,'refuse')
                if mode in ('raise','aggregate','row'):self.assertRegex(text,rf'project-data-invalid:{kind}:too-large|exceeds|too large')
    def test_a_document_of_exactly_the_cap_loads(self):
        s=self.scratch()
        for name,data in (('bench',s.base['bench']),('approval',s.base['approval']),('aggregate',json.dumps(closed_aggregate()).encode())):
            with self.subTest(entry=name):
                kind=DRIVERS[name][1];padded=data+b' '*(CAPS[kind]-len(data))
                self.assertEqual(len(padded),CAPS[kind])
                self.assertEqual(outcome(s,name,padded)[0],'accept')

# ---- the property test ----
SENTINEL='zzsentinelzz'

def nodes(value):
    """Every (container, key) slot of `value`, by an iterative walk."""
    out=[];stack=[value]
    while stack:
        v=stack.pop()
        items=v.items() if isinstance(v,dict) else enumerate(v) if isinstance(v,list) else ()
        for k,x in items:
            out.append((v,k))
            if isinstance(x,(dict,list)):stack.append(x)
    return out

def random_value(rng,depth=0):
    r=rng.randrange(9 if depth<4 else 6)
    if r==0:return None
    if r==1:return rng.choice([True,False])
    if r==2:return rng.choice([0,1,-1,2**63,-2**63,10**20,rng.randint(-10**6,10**6)])
    if r==3:return rng.choice([0.5,-0.0,1e308,-1e308,5e-324,rng.random()])
    if r==4:return rng.choice(['','x','1','1e9999','NaN','true','null','APPROVED','VALID','m1','*'*rng.randint(1,64)])
    if r==5:return rng.choice([[],{}])
    if r==6:return [random_value(rng,depth+1) for _ in range(rng.randint(0,4))]
    if r==7:return {rng.choice(['a','type','state','cases','schema_version','sha256','summary','x'*8]):random_value(rng,depth+1) for _ in range(rng.randint(0,4))}
    return {'type':rng.choice(['object','array','number','string','boolean','null',['number','null']]),'properties':{},'items':{}}

def literal(rng):
    """A JSON text that json.dumps cannot write: a huge integer, a huge exponent, a non-finite literal or a deep value."""
    r=rng.randrange(6)
    if r==0:return '9'*rng.randint(300,5000)
    if r==1:return '-'+'1'*rng.randint(4290,4310)
    if r==2:return rng.choice(['1e9999','-1e9999','1E400','0.'+'0'*400+'1'])
    if r==3:return rng.choice(['NaN','Infinity','-Infinity'])
    d=rng.randint(MAX_DEPTH-3,MAX_DEPTH+3) if r==4 else rng.randint(1,300)
    return '['*d+']'*d

def mutate(rng,base):
    """One adversarial document (bytes) from the baseline `base` of an entry point."""
    pick=rng.randrange(14);doc=copy_of(base);slots=nodes(doc)
    if pick==0:
        d=DEEP if rng.random()<0.05 else rng.choice([rng.randint(1,200),MAX_DEPTH-1,MAX_DEPTH,MAX_DEPTH+1,rng.randint(300,3000)])
        open_,close=rng.choice([('[',']'),('{"a":','}'),('[{"k":','}]')])
        return (open_*d+('0' if open_!='[' else '')+close*d).encode()
    if pick==1:return (rng.choice(['[','{"a":','[{"a":'])*rng.randint(50,5000)).encode()
    if pick in (2,3,4) and slots:
        c,k=rng.choice(slots)
        if pick==2:c[k]=SENTINEL;return json.dumps(doc).replace(f'"{SENTINEL}"',literal(rng)).encode()
        if pick==3:c[k]=random_value(rng);return json.dumps(doc).encode()
        c[k]=str(c[k]) if isinstance(c[k],(int,float)) and not isinstance(c[k],bool) else rng.choice(['1','1e9999','-0',''])
        return json.dumps(doc).encode()
    if pick==5:return rng.choice([b'{}',b'[]',b'true',b'false',b'null',b'""',b'0',b'',b' ',b'{',b']'])
    if pick==6:
        dicts=[(c,k) for c,k in slots if isinstance(c[k],dict)] or slots
        if dicts:c,k=rng.choice(dicts);c[k]=rng.choice([{},True,False,[],None])
        return json.dumps(doc).encode()
    if pick==7 and isinstance(doc,dict) and doc:
        k=rng.choice(sorted(doc));text=json.dumps(doc)
        return (text[:-1]+','+json.dumps(k)+':'+json.dumps(random_value(rng))+'}').encode()
    if pick==8:
        text=json.dumps(doc);i=rng.randrange(len(text)+1);return (text[:i]+rng.choice(['NaN','Infinity','-Infinity'])+text[i:]).encode()
    if pick==9:
        data=json.dumps(doc).encode();i=rng.randrange(len(data)+1)
        return data[:i]+rng.choice([b'\xff',b'\xc3',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\x80'])+data[i:]
    if pick==10:text=json.dumps(doc);return text[:rng.randrange(len(text)+1)].encode()
    if pick==11 and slots:
        c,k=rng.choice(slots);c[k]=SENTINEL;d=rng.randint(MAX_DEPTH-8,MAX_DEPTH+8)
        return json.dumps(doc).replace(f'"{SENTINEL}"','['*d+']'*d).encode()
    if pick==12:return json.dumps(random_value(rng)).encode()
    return json.dumps(rng.choice([doc,[doc],{'a':doc},random_value(rng)])).encode()

WORKERS=2          # FR3-R10: the unit container has 2 CPUs; the documents run in 2 processes (same documents, same checks)

def property_run(worker):
    """Run every document i with i % WORKERS == worker in a fresh scratch root of this process. The generator runs for
    every i, so each process sees exactly the documents of the single sequence of SEED. Returns (escaped, counts)."""
    class Owner:
        cleanups=[]
        @classmethod
        def addClassCleanup(cls,fn,*args):cls.cleanups.append((fn,args))
    s=Scratch(Owner)
    try:
        base=baselines(s);rng=random.Random(SEED);names=list(DRIVERS)
        escaped={};counts={n:{'accept':0,'refuse':0} for n in names}
        for i in range(DOCUMENTS):
            name=names[i%len(names)];data=mutate(rng,base[name])
            if i%WORKERS!=worker:continue
            try:state,_=outcome(s,name,data)
            except AssertionError as exc:
                key=(name,str(exc)[:80]);escaped[key]=escaped.get(key,0)+1;continue
            except Exception as exc:     # the property under test: nothing but GateError (or the refusal value) escapes
                key=(name,type(exc).__name__);escaped[key]=escaped.get(key,0)+1;continue
            counts[name][state]+=1
        s.restore()
        return escaped,counts
    finally:
        for fn,args in Owner.cleanups:fn(*args)

class PropertyTests(unittest.TestCase):
    def test_random_malformed_documents_give_a_gate_error_or_are_accepted(self):
        """A fixed seed generates DOCUMENTS adversarial documents (deep nesting, huge integers, wrong types, strings in
        number places, empty and boolean schemas, duplicate keys, non-finite literals, invalid UTF-8, truncations). The
        documents rotate over the entry points (each one gets at least DOCUMENTS // 16). Every call accepts or refuses
        in its documented way; no other exception escapes, and a rejected aggregate never stays on disk. The documents
        split over WORKERS processes (fork; spawn when other threads run, so no lock is copied while held)."""
        import multiprocessing, threading
        ctx=multiprocessing.get_context('fork' if threading.active_count()==1 else 'spawn')
        with ctx.Pool(WORKERS) as pool:results=pool.map_async(property_run,range(WORKERS)).get(timeout=60)
        names=list(DRIVERS);escaped={};counts={n:{'accept':0,'refuse':0} for n in names}
        for got,c in results:
            for k,v in got.items():escaped[k]=escaped.get(k,0)+v
            for n in names:
                for state in ('accept','refuse'):counts[n][state]+=c[n][state]
        self.assertGreaterEqual(DOCUMENTS,2000)
        self.assertEqual(sum(sum(c.values()) for c in counts.values())+sum(escaped.values()),DOCUMENTS)   # every document ran once
        self.assertEqual(escaped,{})
        for n in names:
            with self.subTest(entry=n):self.assertGreaterEqual(sum(counts[n].values()),DOCUMENTS//len(names))

if __name__=='__main__':
    unittest.main()
