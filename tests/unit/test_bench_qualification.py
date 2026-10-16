import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
import jsonschema
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_units as bu, bench_model as bm, bench
# Ruling T14-C2 (Amendment A): a framework test never names an example. FR1 (FS1 F3): PROJECT is a synthetic project
# directory string; the truth table only writes it into temporary project reports and reads no project tree, so the
# framework test needs no example project (bench_phase3.QUALIFICATION_PROJECT is the same string for B14).
I='a'*64;J='f'*64;CI='c'*32;PROJECT='examples/demo-project';V='artifacts/approvals/t/verdict.md'
GATES=json.loads((ROOT/'safety/contract.json').read_text())['required_gates']
POL=bm.engine_unit_policy(ROOT);T=POL['threshold_ns_per_request'];ST={'resamples':200,'seed':20261007}   # FR3: the synthetic engine test policy
QUAL_SCHEMA=json.loads((ROOT/'schemas/bench-decision.json').read_text())['properties']['qualification']
FEASIBLE={'missing':(None,),'other-project':(0,1,2,3),'malformed':(0,1,3),'blocked-early':(2,),'present':(0,1,2,3),'wrong-identity':(0,1,2,3)}
CIS=('absent','report-missing','run-id-mismatch','valid','identity-mismatch','gate-fail','not-ci','gates-chosen')
APPROVALS=('absent','valid','mismatch','rejected','missing-file')
ANY_CI=set(CIS);ANY_APPR=set(APPROVALS);NO_CI={'absent','report-missing','run-id-mismatch'};NOT_VALID={'absent','mismatch','rejected','missing-file'}
NO_LOCAL={'framework_ci_run_id':None,'ci_report_path':None,'ci_report_sha256':None,'ci_local_state':None,'ci_required_gates':'NOT_CHECKED'}
CI_SET=lambda state,gates:{'framework_ci_run_id':'CI','ci_report_path':'CR','ci_report_sha256':'sha(CR)','ci_local_state':state,'ci_required_gates':gates}
U='framework unqualified';L='framework qualified locally, not published';FU='framework-unqualified'
def project(pe,pi):return {'project_exit':pe,'project_report_path':'PR','project_report_sha256':'sha(PR)','project_identity':pi}
NO_PROJECT={'project_exit':None,'project_report_path':None,'project_report_sha256':None,'project_identity':None}
def R(rid,exits,reports,cis,apprs,kind,label,local,cond,proj,ci,lr,vd):
    q=dict(kind=kind,label=label,**proj,**ci,local_reason=lr,verdicts=vd,source_identity='I')
    return {'id':rid,'exit':set(exits),'report':set(reports),'ci':set(cis),'approvals':set(apprs),'kind':kind,'label':label,'local':local,'condition':cond,'q':q}
VD=[{'path':'V','sha256':'sha(V)'}]
ALL_EXITS=(None,0,1,2,3)
ROWS=[
  R('Q01',ALL_EXITS,{'missing','other-project','malformed'},ANY_CI,ANY_APPR,'none',U,None,FU,NO_PROJECT,NO_LOCAL,None,[]),
  R('Q02',(0,),{'wrong-identity'},ANY_CI,ANY_APPR,'stale',U,None,FU,project(0,'J'),NO_LOCAL,None,[]),
  R('Q03',(1,),{'wrong-identity'},ANY_CI,ANY_APPR,'stale',U,None,FU,project(1,'J'),NO_LOCAL,None,[]),
  R('Q04',(2,),{'wrong-identity'},ANY_CI,ANY_APPR,'stale',U,None,FU,project(2,'J'),NO_LOCAL,None,[]),
  R('Q05',(3,),{'wrong-identity'},ANY_CI,ANY_APPR,'stale',U,None,FU,project(3,'J'),NO_LOCAL,None,[]),
  R('Q06',(0,),{'present'},ANY_CI,ANY_APPR,'manifest','manifest recorded',None,None,project(0,'I'),NO_LOCAL,None,[]),
  R('Q07',(1,),{'present'},ANY_CI,ANY_APPR,'failed',U,None,'project-gates-failed',project(1,'I'),NO_LOCAL,None,[]),
  R('Q08',(2,),{'present'},ANY_CI,ANY_APPR,'failed',U,None,'project-check-blocked',project(2,'I'),NO_LOCAL,None,[]),
  R('Q09',(2,),{'blocked-early'},ANY_CI,ANY_APPR,'failed',U,None,'project-check-blocked',project(2,None),NO_LOCAL,None,[]),
  R('Q10',(3,),{'present'},NO_CI,NOT_VALID,'local',U,(False,'ci-evidence-missing'),FU,project(3,'I'),NO_LOCAL,'ci-evidence-missing',[]),
  R('Q11',(3,),{'present'},NO_CI,{'valid'},'local',U,(False,'ci-evidence-missing'),FU,project(3,'I'),NO_LOCAL,'ci-evidence-missing',VD),
  R('Q12',(3,),{'present'},{'gate-fail'},NOT_VALID,'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('FAIL','FAIL'),'ci-report-not-passing',[]),
  R('Q13',(3,),{'present'},{'gate-fail'},{'valid'},'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('FAIL','FAIL'),'ci-report-not-passing',VD),
  R('Q14',(3,),{'present'},{'not-ci'},NOT_VALID,'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('PASS','PASS'),'ci-report-not-passing',[]),
  R('Q15',(3,),{'present'},{'not-ci'},{'valid'},'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('PASS','PASS'),'ci-report-not-passing',VD),
  R('Q16',(3,),{'present'},{'identity-mismatch'},NOT_VALID,'local',U,(False,'ci-identity-mismatch'),FU,project(3,'I'),CI_SET('PASS','PASS'),'ci-identity-mismatch',[]),
  R('Q17',(3,),{'present'},{'identity-mismatch'},{'valid'},'local',U,(False,'ci-identity-mismatch'),FU,project(3,'I'),CI_SET('PASS','PASS'),'ci-identity-mismatch',VD),
  R('Q18',(3,),{'present'},{'valid'},{'absent'},'local',U,(False,'approval-missing'),FU,project(3,'I'),CI_SET('PASS','PASS'),'approval-missing',[]),
  R('Q19',(3,),{'present'},{'valid'},{'mismatch','rejected','missing-file'},'local',U,(False,'approval-not-valid'),FU,project(3,'I'),CI_SET('PASS','PASS'),'approval-not-valid',[]),
  R('Q20',(3,),{'present'},{'valid'},{'valid'},'local',L,(True,None),None,project(3,'I'),CI_SET('PASS','PASS'),None,VD),
  R('Q21',(3,),{'present'},{'gates-chosen'},NOT_VALID,'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('PASS','FAIL'),'ci-report-not-passing',[]),
  R('Q22',(3,),{'present'},{'gates-chosen'},{'valid'},'local',U,(False,'ci-report-not-passing'),FU,project(3,'I'),CI_SET('PASS','FAIL'),'ci-report-not-passing',VD)]

def combos():
    for report,exits in FEASIBLE.items():
        for exit in exits:
            for ci in CIS:
                for appr in APPROVALS:yield exit,report,ci,appr
def rows_for(c):return [r for r in ROWS if all(v in r[k] for k,v in zip(('exit','report','ci','approvals'),c))]

def materialize(root,exit,report,ci,appr):
    root=Path(root);(root/'safety').mkdir(parents=True);(root/'safety/contract.json').write_text(json.dumps({'required_gates':GATES}))
    if report!='missing':
        identity={'present':I,'wrong-identity':J,'other-project':I,'malformed':None,'blocked-early':None}[report]
        p=root/bu.PROJECT_REPORT;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({'exit_code':exit,'source_identity':identity,'project_dir':'examples/other' if report=='other-project' else PROJECT}))
    rid=None if ci=='absent' else CI
    if ci not in ('absent','report-missing'):
        rep={'run_id':'d'*32 if ci=='run-id-mismatch' else CI,'local_state':'FAIL' if ci=='gate-fail' else 'PASS','source_identity':J if ci=='identity-mismatch' else I,
             'commands':['./tools/safety check-fast' if ci=='not-ci' else './tools/safety ci'],
             'gates':[{'name':g,'status':'FAIL' if ci=='gate-fail' and g==GATES[0] else 'PASS'} for g in GATES]}
        if ci=='gates-chosen':rep.update(gates=[{'name':GATES[0],'status':'PASS'}],required_gates=[GATES[0]])   # the report names its own set
        p=root/bu.CI_REPORT.format(run_id=CI);p.parent.mkdir(parents=True);p.write_text(json.dumps(rep))
    paths=[] if appr=='absent' else [V]
    if appr in ('valid','mismatch','rejected'):
        p=root/V;p.parent.mkdir(parents=True)
        p.write_text('# Verdict\n'+('Verdict: REJECT' if appr=='rejected' else 'Verdict: APPROVE')+'\n- Reviewed identity: '+(J if appr=='mismatch' else I)+'\n\n## Findings\n')
    return rid,paths

def producer_chain(root,exit,report,ci,appr):
    """The real producer chain of every caller: report reader, evidence loader, qualify."""
    rid,paths=materialize(root,exit,report,ci,appr)
    pc=bu.project_check_from_report(root,bu.PROJECT_REPORT,PROJECT);before=copy.deepcopy(pc)
    q,kind,label=bu.qualify(pc,*bu.load_local_evidence(root,rid,paths),I)
    return q,kind,label,pc,before

def tokens(root):
    root=Path(root);sha=lambda rel:hashlib.sha256((root/rel).read_bytes()).hexdigest() if (root/rel).is_file() else None
    cr=bu.CI_REPORT.format(run_id=CI)
    return {'I':I,'J':J,'PR':bu.PROJECT_REPORT,'sha(PR)':sha(bu.PROJECT_REPORT),'CI':CI,'CR':cr,'sha(CR)':sha(cr),'V':V,'sha(V)':sha(V)}
def resolve(v,tok):
    if isinstance(v,str):return tok.get(v,v)
    if isinstance(v,list):return [resolve(x,tok) for x in v]
    if isinstance(v,dict):return {k:resolve(x,tok) for k,x in v.items()}
    return v

def qualified(row_id):
    """A qualified project_check for row_id, produced by the real chain; the fixture for every other test."""
    c=next(c for c in combos() if rows_for(c)[0]['id']==row_id)
    with tempfile.TemporaryDirectory() as t:return producer_chain(t,*c)[0]

CELLS=('g1-pos-near','g0-mid-near','g1-neg-near','g1-pos-far','g0-mid-far','g1-neg-far')     # FR5: the fixture protocol's cell names
def _row(variant,lang,v,unit='m3/full-dataset',route=None,records=None):
    blocks={b:float(v) for b in range(12)}
    return {'unit':unit,'mode':'warm','variant':variant,'workers':'direct','route':route,
            'route_label':'separate process; copied, bounded, validated frames over pipes (safest)' if route else None,
            'language':lang,'eligible':True,'planned':True,'wall':blocks,'cpu':dict(blocks),'peak':None,'records':records}
def uev_for(q):
    """m3/full-dataset: Python above T and C reliably faster, so order 6 or order 7 decides by the qualification alone."""
    rows=[_row('py-optimized','python',T*2),_row('py-library','python-library',T*2.02),
          _row('py-reference','python',T*10,unit='m3/single-record',records={c:{b:1e9 for b in range(12)} for c in CELLS}),
          _row('c-serial','c',T*0.5,route='stdio')]
    return {'status':'VALID','reasons':[],'rows':rows,'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
            'reference_evals':{'m3':10**6},'panel_evals':{'m3':{c:100 for c in CELLS}},'project_check':q,'current_identity':I,'opportunity_state':'APPROVED',
            'coverage_ok':True,'reference_admit_excluded':None,'library_overhead_ns_per_row':None}

def record(uev):
    """The producer of the decision record (Task 18): bench_units.unit_decision_record, validated against the closed schema.
    Ruling T16-C5: the Task 18 Step 1 body of TruthTableTests.record, here at module level (it moved in Task 16).
    Ruling T15-C4: test_truth_table (all 680 combinations) runs in the container suite,
    benchmarks/performance/python/tests/test_qualification_truth_table.py, which imports the table, combos, producer_chain and this
    producer from here (T15-APP-10)."""
    from unittest import mock
    from schema_check import validate
    run={'run_id':'0'*32,'case':'record-scan','mode':'decision','source_identity':I,'image_id':'sha256:'+'1'*64,'policy_sha256':'2'*64,'dataset':{'kind':'synthetic'}}
    with mock.patch('bench_decide._current_identity',return_value=I):      # the case name: input data (test_bench_framework_imports)
        rec=bu.unit_decision_record(ROOT,run,{'project_dir':PROJECT},{'case_id':'record-scan','variants':[]},POL,bu.decide_units(uev,POL,ST),uev,{})
    validate(ROOT,'bench-decision',rec);return rec

NAMED_ROWS=('Q01','Q06','Q07','Q08','Q10','Q16','Q19','Q20')   # the rows that test_bench_units uses through qualified()

class NamedRowTests(unittest.TestCase):                                        # T15-APP-10: the named rows stay in check-fast
    def test_named_rows_through_the_real_chain(self):
        for rid in NAMED_ROWS:
            c=next(c for c in combos() if rows_for(c)[0]['id']==rid)
            with self.subTest(row=rid,combination=c):
                hits=rows_for(c);self.assertEqual(len(hits),1);row=hits[0]
                with tempfile.TemporaryDirectory() as t:
                    q,kind,label,pc,before=producer_chain(t,*c);tok=tokens(t)
                rec=record(uev_for(q))
                self.assertEqual(pc,before);self.assertEqual((kind,label),(row['kind'],row['label']))
                self.assertEqual(None if q['local'] is None else (q['local']['ok'],q['local']['reason']),row['local'])
                self.assertEqual(rec['qualification'],resolve(row['q'],tok))
                u=next(x for x in rec['units'] if x['unit']=='m3/full-dataset')
                if row['condition'] is None:self.assertEqual((u['verdict'],u['reason'],u['failed_conditions']),('PREFER_C','c-reliably-faster',[]))
                else:self.assertEqual((u['verdict'],u['reason'],u['failed_conditions']),('INCONCLUSIVE','c-not-eligible',[row['condition']]))
                self.assertEqual(u['framework_basis'],row['kind'])
                self.assertEqual(qualified(rid),q)                             # the fixture of test_bench_units is this chain output

class LoaderTests(unittest.TestCase):                                          # P3R11-02, P3R11-04, P3R12-01, P3R12-02, P3R12-04, P3R12-05
    def test_report_cannot_choose_its_required_gates(self):                   # restored (removed in revision 12): G9.4 rule 2
        self.assertGreater(len(GATES),1)
        with tempfile.TemporaryDirectory() as t:
            materialize(t,3,'present','gates-chosen','valid')
            ci,appr=bu.load_local_evidence(t,CI,[V]);self.assertEqual(ci['required_gates'],GATES)    # from safety/contract.json, never from the report
            r=bu.check_local_evidence(ci,appr,I)
            self.assertEqual((r['ok'],r['reason'],r['local_state'],r['required_gates']),(False,'ci-report-not-passing','PASS','FAIL'))
    def test_malformed_ci_fields_give_a_valid_unqualified_record(self):      # P3R12-02
        with tempfile.TemporaryDirectory() as t:
            materialize(t,3,'present','valid','valid')
            ci,appr=bu.load_local_evidence(t,CI,[V])
            for change in ({'local_state':''},{'local_state':7},{'gates':5},{'gates':[{'name':['x'],'status':'PASS'}]}):
                with self.subTest(change=change):
                    q,kind,label=bu.qualify(bu.project_check_from_report(t,bu.PROJECT_REPORT,PROJECT),dict(ci,report=dict(ci['report'],**change)),appr,I)
                    blk=bu.qualification_block(q,I);jsonschema.Draft202012Validator(QUAL_SCHEMA).validate(blk)
                    self.assertEqual((kind,label,blk['local_reason']),('local',U,'ci-report-not-passing'))
                    self.assertTrue(blk['ci_local_state'])
    def test_long_approval_path_is_never_accepted(self):                     # P3R12-02 (the CLI refuses it first)
        with tempfile.TemporaryDirectory() as t:
            _,appr=bu.load_local_evidence(t,None,['a'*301]);self.assertEqual((len(appr[0]['path']),appr[0]['text']),(300,None))
    def test_project_dir_spelling_is_normalized(self):                       # P3R12-04
        with tempfile.TemporaryDirectory() as t:
            materialize(t,0,'present','absent','absent')
            self.assertEqual(bu.project_check_from_report(t,bu.PROJECT_REPORT,'./'+PROJECT+'/')['exit'],0)
            self.assertEqual(bu.project_check_from_report(t,bu.PROJECT_REPORT,'../'+PROJECT),qualified('Q01'))   # outside the root: never the same project
    def test_constructor_refuses_inconsistent_shapes(self):                  # P3R12-05 (restored from test_project_check_shape)
        for args in ((None,'p',None,None),(1,'p','b'*64,None),(0,'p','b'*64,I,{'ok':True}),(4,'p','b'*64,I)):
            with self.subTest(args=args),self.assertRaises(ValueError):bu._project_check(*args)
    def test_loader_without_ci_report_returns_none(self):
        with tempfile.TemporaryDirectory() as t:
            materialize(t,3,'present','absent','valid')
            for rid in (None,CI,'not-a-run-id'):
                ci,appr=bu.load_local_evidence(t,rid,[V])
                with self.subTest(rid=rid):self.assertIsNone(ci);self.assertEqual([a['path'] for a in appr],[V])
    def test_report_reader_digest_and_project(self):
        with tempfile.TemporaryDirectory() as t:
            materialize(t,3,'present','absent','absent');data=(Path(t)/bu.PROJECT_REPORT).read_bytes()
            self.assertEqual(bu.project_check_from_report(t,bu.PROJECT_REPORT,PROJECT)['report_sha256'],hashlib.sha256(data).hexdigest())
            self.assertEqual(bu.project_check_from_report(t,bu.PROJECT_REPORT,'examples/other'),qualified('Q01'))   # another project's report: the no-report shape
