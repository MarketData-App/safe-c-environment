"""EX-3: the option example's protocol (benchmarks/project/protocol/). The framework loads protocol.json through
bench_model.load_protocol (schema, case, models, stubs, policy, windows and bound-file checks); these tests pin the values
of the example: the 10 owner units, the two-condition rule, the dated SOFR constant, the required before_run checks, the
approval references, the aggregate schema grammar and the reads of the example code. Standard library, jsonschema and the
mounted framework tools only (no SciPy, no QuantLib)."""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path('/src')                                           # the bench container mounts the repository read-only at /src
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm
from optionlab import protocol, agreement, checks
PROJECT=Path(__file__).resolve().parents[2]                 # benchmarks/project
PROJECT_DIR='examples/option-pricing-benchmark'
POLICY='unit-200ms-and-20pct'
CASE='option-chain-greeks'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(rel):return json.loads((PROJECT/rel).read_text())

class ProtocolFileTests(unittest.TestCase):
    def test_the_framework_loads_the_protocol(self):
        doc=bm.load_protocol(ROOT,PROJECT_DIR)
        self.assertEqual(doc['cases'],[CASE,'echo-control']);self.assertEqual(doc['models'],['bsm','bjs','crr','baw','alo'])
        self.assertEqual(doc,protocol.protocol())
    def test_every_binding_matches_its_file(self):
        self.assertEqual(load('bench.json')['protocol'],{'file':'protocol/protocol.json','sha256':sha(protocol.PROTOCOL_FILE)})
        doc=protocol.protocol()
        self.assertEqual(doc['oracle'],{'file':'oracle.json','sha256':sha(protocol.ORACLE_FILE)})
        self.assertEqual(doc['aggregate_schema'],{'file':'aggregate.schema.json','sha256':sha(protocol.AGGREGATE_SCHEMA_FILE)})
    def test_the_protocol_names_every_before_run_check_of_the_case(self):
        declared=[c['name'] for c in load('bench.json')['checks'] if c['before_run']]
        required=protocol.protocol()['before_run_required'][CASE]
        self.assertEqual(sorted(declared),sorted(required));self.assertEqual(len(required),len(set(required)))
        self.assertEqual(set(protocol.protocol()['before_run_required']),{CASE})
    def test_the_values_follow_the_handoff_list(self):
        """FR3 handoff list section 2 (commit 34512cd of the framework): the shared tolerances, the alo and baw blocks, the solver
        constants, the planning shares and the required share."""
        doc=protocol.protocol()
        self.assertEqual(doc['solver'],{'tolerance':1e-10,'max_iterations':200,'sigma_hi':5.0,'slow_steps':3,'multi_root_grid':64})
        self.assertEqual(doc['budgets'],{'estimate_share_per_selector':{'bsm':0.05,'bjs':0.1,'crr':1.0,'baw':0.15,'alo':3.14},'share_required':['alo']})
        t=doc['tolerances']
        self.assertEqual(t['state'],'calibrated-phase-2')        # EX-16 (ruling R74): the values are those of the calibration proposal
        self.assertEqual((t['calibration']['proposal'],t['calibration']['verdict']),('protocol/tolerance-proposal.json','artifacts/approvals/ex-option-T23/verdict.md'))
        self.assertEqual({k:t[k] for k in ('iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega','ambiguity_rel','provider_mid_diff')},
                         {'iv_abs':1e-8,'iv_ulp_rel':1e-13,'price_rel':1e-12,'fit_nu':1e-10,'fit_rel':1e-12,'greek_abs':1e-9,'greek_rel':1e-6,'flat_vega':1e-12,
                          'ambiguity_rel':1e-9,'provider_mid_diff':0.005})
        self.assertEqual((t['baw']['state'],t['baw']['approval']),('locked-g-baw2','perf-lab-t7-baw-lock'))
        self.assertEqual(t['baw']['sstar_k'],{'delta':0,'gamma':0,'theta':0,'vega':0,'rho':0})
        self.assertEqual((t['alo']['state'],t['alo']['approval']),('locked-g-alo2','perf-lab-alo-panel'))
        for model in ('alo','baw'):
            for key in ('iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega'):
                self.assertEqual(t[model][key],t[key],(model,key))
    def test_the_other_blocks(self):
        doc=protocol.protocol()
        self.assertEqual(doc['verdict_counts'],['multi_root','boundary_ambiguous','flat_vega'])
        self.assertEqual(doc['local_exceptions'],['ChainError','ModelDefect','TailCondition'])
        self.assertEqual(doc['library_report'],{'selectors':['baw'],'label':'py-library: Python S* side test included'})
        self.assertEqual((doc['panel']['models'],doc['panel']['digest_form']),(['bsm','bjs','crr','baw','alo'],'ocg-v1m'))
        rule=doc['panel']['cell_rule'];self.assertEqual(rule['grid'],{'upper':5.0,'points':64});self.assertEqual(rule['level_ratios'],[2.0,4.0])
        self.assertEqual([c['name'] for c in rule['cells']],['itm-put-30d','itm-put-1y','atm-call-30d','atm-call-1y','otm-put-30d','otm-put-1y'])
    def test_the_six_panel_cells_are_the_h21_3_literals(self):
        """T11T12-A09: the cell values of Amendment H21.3, as literals: position targets ln 1.10, 0 and ln 0.90, the bands (> 0, |x| <= ln 1.05,
        < 0) and the scales 30/365 and 1.0. The values come through protocol.protocol(), the reader of the example."""
        LN110,LN105,LNM90=0.09531017980432493,0.04879016416943205,-0.10536051565782628;T30,T1Y=0.0821917808219178,1.0
        itm,atm,otm=({'op':'gt','bound':0.0},{'op':'abs_le','bound':LN105},{'op':'lt','bound':0.0})
        want=[('itm-put-30d','put',itm,LN110,T30),('itm-put-1y','put',itm,LN110,T1Y),('atm-call-30d','call',atm,0.0,T30),('atm-call-1y','call',atm,0.0,T1Y),
              ('otm-put-30d','put',otm,LNM90,T30),('otm-put-1y','put',otm,LNM90,T1Y)]
        cells=protocol.protocol()['panel']['cell_rule']['cells']
        self.assertEqual([(c['name'],c['category'],c['band'],c['position_target'],c['scale_target']) for c in cells],want)
    def test_the_stubs_match_the_case_deadlines_and_the_checks(self):
        doc=protocol.protocol();case=load('cases/option-chain-greeks.json')
        reasons={e['reason'] for e in ([case['call_deadline']]+case['call_deadlines'])}
        self.assertEqual([(s['reason'],s['check'],s['variant']) for s in doc['stubs']],
                         [('baw-hang','baw-hang-stub','py-library'),('alo-overrun','alo-overrun-stub','py-library')])
        self.assertEqual({s['reason'] for s in doc['stubs']},reasons)
        names={c['name'] for c in load('bench.json')['checks']};self.assertTrue({s['check'] for s in doc['stubs']}<=names)
        text=(PROJECT/'python/optionlab/library.py').read_text()          # read as text: the module imports QuantLib (a missing-module id until T14)
        for line in ("STUB_ENV='SAFE_C_TEST_STUB'","BAW_STUB_REASON='baw-hang'","ALO_STUB_REASON='alo-overrun'"):self.assertIn(line,text)
        self.assertNotIn('SAFE_C_TEST_BAW_STUB',text);self.assertNotIn('SAFE_C_TEST_ALO_STUB',text)

class ApprovalTests(unittest.TestCase):
    def test_the_protocol_approval_reference_resolves(self):
        """PENDING needs no reference and no record; APPROVED needs protocol/approval.json with the protocol digest and the same reference
        (bench_model.load_protocol enforces it; this test states the example rule)."""
        a=protocol.protocol()['approval']
        if a['state']=='PENDING':
            self.assertIsNone(a['reference']);self.assertFalse(protocol.APPROVAL_FILE.exists())
        else:
            rec=json.loads(protocol.APPROVAL_FILE.read_text())
            self.assertEqual((rec['protocol_sha256'],rec['reference']),(sha(protocol.PROTOCOL_FILE),a['reference']))
    def test_each_tolerance_approval_reference_resolves(self):
        """The lock references of the alo and baw blocks name the approvals of the history; checks.py names both and the
        lock states, so a changed reference or state fails here."""
        text=(PROJECT/'python/optionlab/checks.py').read_text();t=protocol.tolerances()
        for model,ref in (('baw','perf-lab-t7-baw-lock'),('alo','perf-lab-alo-panel')):
            with self.subTest(model=model):
                self.assertEqual(t[model]['approval'],ref);self.assertIn(ref,text);self.assertIn(t[model]['state'],text)
        self.assertEqual(checks.BAW_LOCK_STATE,t['baw']['state'])
    def test_the_opportunity_record_names_an_approval_and_the_policy(self):
        rec=load('cases/option-chain-greeks.opportunity.json')
        self.assertEqual(rec['approval']['state'],'APPROVED');self.assertTrue(rec['approval']['reference'].startswith('perf-lab-t14-decide'))
        self.assertIn('ex-option-T10',rec['approval']['reference']);self.assertIn(POLICY,rec['target']['unit'])
        self.assertEqual(load('cases/option-chain-greeks.json')['version'],5)        # EX-10: the C rows and the unit points (the record binds the case by id)
    def test_the_echo_control_record_is_approved_by_the_t19_verdict(self):
        """R43 item f, R23: the echo-control record was PENDING until its approver reviewed it; the R23 bookkeeping (M-L)
        recorded the T19 approval, so the state is APPROVED and the reference names ex-option-T19."""
        rec=load('cases/echo-control.opportunity.json')
        self.assertEqual((rec['case_id'],rec['approval']['state']),('echo-control','APPROVED'))
        self.assertTrue(rec['approval']['reference'].startswith('ex-option-T19 ('))
        self.assertEqual(rec['approval']['baseline_variant'],'py-reference')

class DecisionPolicyTests(unittest.TestCase):
    def policy(self):return protocol.protocol()['decision_policies'][POLICY]
    def test_one_policy_with_a_new_name(self):
        pols=protocol.protocol()['decision_policies'];self.assertEqual(list(pols),[POLICY])
        self.assertNotIn(POLICY,('owner','demo-latency-2x','demo-cpu-40'));self.assertFalse(POLICY.startswith('demo-'))
    def test_the_units_are_the_owners_ten(self):
        p=self.policy()
        want=sorted(f'{m}/{k}' for m in ('bsm','bjs','crr','baw','alo') for k in ('full-dataset','single-record'))
        self.assertEqual(sorted(p['units']),want);self.assertEqual(len(p['units']),10)
        self.assertEqual((p['case'],p['kind'],p['metric'],p['verdict_mode']),(CASE,'unit-threshold','wall_ns_per_request','warm'))
    def test_the_threshold_is_200_ms(self):self.assertEqual(self.policy()['threshold_ns_per_request'],200_000_000)
    def test_the_margin_rule_declares_both_conditions_and_the_families(self):
        """Owner 2026-10-15/16: C wins only when Python adds 200 ms or more (threshold) AND C is consistently more than 20 percent
        faster end to end (margin 0.2) on that route; each route is judged on its own. Base = the faster of py-reference and
        py-optimized; candidate = c-serial on stdio, shm and inproc; py-library and the pool rows never decide."""
        p=self.policy();r=p['margin_rule']
        self.assertEqual(p['threshold_ns_per_request'],200_000_000);self.assertEqual(r['margin'],0.2)
        self.assertEqual(r['base_variants'],['py-reference','py-optimized']);self.assertEqual(r['candidate_variants'],['c-serial'])
        self.assertEqual(r['routes'],['stdio','shm','inproc'])
        self.assertNotIn('py-library',r['base_variants'])
        self.assertFalse({'py-threads','py-processes','c-threads'}&(set(r['base_variants'])|set(r['candidate_variants'])))
    def test_the_base_families_are_implemented_in_the_case(self):
        """EX18a-A04: the framework checks the declared base variants against the case at load."""
        case=bm.load_case(ROOT,CASE,PROJECT_DIR);p=dict(self.policy())
        self.assertEqual(bm.margin_base_problems(case,p,POLICY),[])
        ids={v['id']:v['status'] for v in case['variants']}
        self.assertTrue(all(ids[v]=='implemented' for v in p['margin_rule']['base_variants']))
    def test_each_policy_unit_has_its_case_points(self):
        """T10-A02 (EX-10): each of the 10 policy units has its case point, so margin_base_problems and decision_points are no
        longer vacuous: unit-<m>-full (unit <m>/full-dataset; a caller selector point at the large size, no panel) and unit-<m>-one
        (unit <m>/single-record; size tiny with the six panel indices of option-chain-greeks.panel.json), each with py-optimized,
        py-library and c-serial on stdio, shm and inproc, warm and cold (py-reference at the single-record points; the plan never
        measures it at the large size). margin_base_problems gives [] with those points, and a unit point without py-optimized
        gives a problem (the check reads the points)."""
        import bench_windows
        case=bm.load_case(ROOT,CASE,PROJECT_DIR);p=dict(self.policy())
        panel=load('cases/option-chain-greeks.panel.json')['indices'];self.assertEqual(len(panel),6)
        units={}
        for pt in case['points']:
            if 'unit' in pt:units.setdefault(pt['unit'],[]).append(pt)
        self.assertEqual(sorted(units),sorted(p['units']));self.assertEqual(len(units),10)
        for m in ('bsm','bjs','crr','baw','alo'):
            with self.subTest(model=m):
                (full,),(one,)=units[f'{m}/full-dataset'],units[f'{m}/single-record']
                self.assertEqual((full['name'],full['scope'],full['selector'],full['size']),(f'unit-{m}-full','caller',m,'large'));self.assertNotIn('panel',full)
                self.assertEqual((one['name'],one['scope'],one['selector'],one['size'],one['panel']),(f'unit-{m}-one','caller',m,'tiny',panel))
                self.assertEqual(full['variants'],['py-optimized','py-library','c-serial'])
                self.assertEqual(one['variants'],['py-reference','py-optimized','py-library','c-serial'])
                for pt in (full,one):self.assertEqual((pt['routes'],pt['modes'],pt['class']),(['stdio','shm','inproc'],['warm','cold'],'primary'))
        self.assertEqual(bm.margin_base_problems(case,p,POLICY),[])
        self.assertEqual(sorted(x['unit'] for x in bench_windows.decision_points(case,p)),sorted(p['units']))
        broken=json.loads(json.dumps(case));pt=next(x for x in broken['points'] if x.get('unit')=='crr/single-record');pt['variants'].remove('py-optimized')
        self.assertEqual(len(bm.margin_base_problems(broken,p,POLICY)),1)
    def test_the_single_record_points_name_the_synthetic_panel_dataset(self):
        """R48 (task M2c; restores the key that 1dcb3ba removed): each unit-<m>-one point declares dataset_ref
        synthetic:large#panel. A panel trial of a local run needs it (container trial_dataset: the synthetic dataset that it
        names, never rows of the local dataset); the framework derives its identity from the planned points
        (bench_plan.plan_datasets; tools/bench.py dataset_identity_reasons since T6-R6): kind synthetic, size large, the case
        seed and the six panel indices. The seed and the size are those of option-chain-greeks.panel.json and of the generator
        rows that take() gives a synthetic run shorter than a panel index (R44), so a local and a synthetic panel trial take the
        same rows. No other point declares a dataset_ref (a unit-<m>-full point reads the run dataset)."""
        import bench_plan
        case=load('cases/option-chain-greeks.json');panel=load('cases/option-chain-greeks.panel.json')
        policy=json.loads((ROOT/'safety/performance-policy.json').read_text());seed=case['parameters']['seed']['value']
        self.assertEqual((seed,panel['seed'],panel['dataset'],len(panel['indices'])),(20261007,20261007,'synthetic:large',6))
        want={'synthetic:large#panel':{'kind':'synthetic','size':'large','seed':seed,'sha256':None,'rows':6,'indices':panel['indices']}}
        points={x['name']:x for x in case['points']};models=('bsm','bjs','crr','baw','alo')
        for m in models:
            with self.subTest(model=m):
                one,full=points[f'unit-{m}-one'],points[f'unit-{m}-full']
                self.assertEqual((one['dataset_ref'],one['panel']),('synthetic:large#panel',panel['indices']));self.assertNotIn('dataset_ref',full)
                self.assertEqual(bench_plan.plan_datasets([one],policy),want)
        self.assertEqual(sorted(n for n,x in points.items() if 'dataset_ref' in x),sorted(f'unit-{m}-one' for m in models))
    def test_the_windows_controls_are_rows_of_the_case(self):
        """R43 item g, T10-I5: the windows block names its control pairs as caller, warm, non-panel rows of option-chain-greeks:
        the base pair a py-optimized row, the candidate pair a c-serial row on stdio. The framework accepts the declaration
        (bench_windows.declaration_problems). T28 (A10 step 6, adaptation b): the synthetic cap is caps_proposed.synthetic of
        the synthetic window plan b66cea66ef601a4fd59b9150f10f98a5 (owner smoke calibration 9582b6735b6441d694047c489e883dbf:
        one window 1a, estimate 25,270.7 s, 600 x ceil(1.2 x 25,270.7 / 600) = 30,600 s). T28b (ruling R103, which revises R78 a):
        the local window plan is made and its cap recorded before the freeze. With the same calibration, the local plan at the
        provisional 79,200 s refused (owner-cap-exceeded; windows 1a 85,333.1 s and 1b 86,063.1 s), so the local cap is
        600 x ceil(1.2 x 86,063.1 / 600) = 103,800 s, and the plan passes at it. At the owner's go, the decision task makes both
        window plans again from the same smoke calibration."""
        import bench_windows
        w=self.policy()['windows'];case=bm.load_case(ROOT,CASE,PROJECT_DIR)
        self.assertEqual(w['controls'],{'base':{'point':'baseline','variant':'py-optimized'},'candidate':{'point':'baseline','variant':'c-serial','route':'stdio'}})
        self.assertEqual((w['window_seconds'],w['cap_headroom'],w['cap_step_seconds'],w['calibration_deadline_seconds']),(86400,1.2,600,3600))
        self.assertEqual(w['caps_seconds'],{'synthetic':30600,'local':103800})       # synthetic: T28 plan b66cea66; local: T28b local plan refusal at 79,200 s (R103)
        self.assertEqual(bench_windows.declaration_problems(case,self.policy()),[])
    def test_the_echo_case_and_the_native_declaration(self):
        """R43 items c, g, h: the protocol names echo-control as its echo case; bench.json declares the native kernel template of
        pl-kernel. EX-12 (R50 item c): the agreement check is native-agreement (the framework runs it after the native build and
        before any timing of a run with C rows); native-routes stays a declared check. The protocol never requires either before
        a run (T6R4-A02)."""
        doc=protocol.protocol();decl=load('bench.json')
        self.assertEqual((doc['echo_case'],doc['cases']),('echo-control',[CASE,'echo-control']))
        self.assertEqual(decl['native'],{'kernel':{'program':'pl-kernel','args':['--case','option-chain-greeks','--input','{input}','--records','{records}',
                                                                                  '--loops','{loops}','--threads','{threads}','--output','{output}','--handshake']},
                                         'agreement':'native-agreement'})
        self.assertIsNone(bm.native_declaration_problem(decl))
        for name in ('native-agreement','native-routes'):
            self.assertNotIn(name,[n for names in doc['before_run_required'].values() for n in names])
            self.assertFalse(next(c for c in decl['checks'] if c['name']==name)['before_run'])
    def test_the_windows_declaration_waits_for_the_c_row(self):
        """The framework refuses a windows block whose candidate control is not an implemented variant (declaration_problems), and the
        candidate control is a c-serial row. While c-serial is planned, the policy declares no windows; the window plan (T19 echo
        control case, T28 caps) adds them with windows.calibration_deadline_seconds >= 1,040 s (ruling R13, EX18c-A06: a 52-trial
        control session of a py-reference base pair at the small tier). This test fails when c-serial becomes implemented without
        the declaration."""
        status={v['id']:v['status'] for v in load('cases/option-chain-greeks.json')['variants']}['c-serial']
        w=self.policy().get('windows')
        if status=='implemented':
            self.assertIsNotNone(w,'c-serial is implemented: declare the windows part');self.assertGreaterEqual(w['calibration_deadline_seconds'],1040)
        else:self.assertIsNone(w)

class CallDeadlineTests(unittest.TestCase):
    def test_c_caller_trials_of_a_covered_selector_carry_the_declared_deadline(self):
        """R43 item i, ruling R44 item 5 (part 1): the plan arms every c-serial caller trial of a covered selector (baw: baw-hang,
        alo: alo-overrun) on each route with call_deadline_seconds and the declared reason, as it arms the Python rows of the same
        point (bench_deadline.deadline_fields is variant-blind); a selector without an entry gets none. Part 2 (the coordinator
        kill_group removes the C caller child and its pl-worker) is the check c-call-deadline."""
        import bench_deadline
        case=bm.load_case(ROOT,CASE,PROJECT_DIR);policy=bm.load_policy(ROOT,PROJECT_DIR)
        plan={'sizes':policy['sizes'],'dataset':{'kind':'synthetic','rows':None}};cap=float(policy['budgets']['session_cap_seconds']);seen=0
        for pt in case['points']:
            sel=pt.get('selector','all')
            if pt['scope']!='caller' or 'panel' in pt:continue
            for route in pt.get('routes',['stdio','shm','inproc']):
                base={'variant':'c-serial','workers':'direct','mode':'warm','tier':pt['size'],'loops':1,'selector':sel,'route':route,'scope':'caller'}
                got=bench_deadline.deadline_fields(case,policy,'timing',plan,base,None,cap)
                py=bench_deadline.deadline_fields(case,policy,'timing',plan,dict(base,variant='py-optimized',route=None),None,cap)
                want={'baw':'baw-hang','alo':'alo-overrun'}.get(sel)
                with self.subTest(point=pt['name'],route=route):
                    if want is None:self.assertEqual((got,py),({},{}))
                    else:
                        self.assertEqual(got['call_deadline_reason'],want);self.assertEqual(py['call_deadline_reason'],want);seen+=1
                        self.assertGreaterEqual(got['call_deadline_seconds'],60.0);self.assertLessEqual(got['call_deadline_seconds'],cap)
        self.assertEqual(seen,6)               # unit-baw-full and unit-alo-full, three routes each

class MarketConstantTests(unittest.TestCase):
    def test_sofr_has_its_date_and_url(self):
        s=protocol.sofr()
        self.assertEqual(s['day'],'2026-10-05');self.assertEqual(s['rate'],0.0389);self.assertEqual(s['percent'],3.89)
        self.assertEqual(s['source'],'New York Fed');self.assertEqual(s['url'],'https://www.newyorkfed.org/markets/reference-rates/sofr')
        self.assertEqual(s['note'],'value given by the owner 2026-10-15 (plan EX Amendment D item 3)')
        self.assertAlmostEqual(s['percent']/100.0,s['rate'],places=15)

class OracleFileTests(unittest.TestCase):
    def test_the_oracle_file_holds_the_handoff_keys(self):
        o=protocol.oracle()
        self.assertEqual(sorted(o),['alo_gauss_legendre','calibration','generator','market_constants','oracle'])
        self.assertEqual(o['alo_gauss_legendre']['n'],25);self.assertTrue(o['calibration']['locked'])
        for key in ('bsm','bjs','lattice','greeks','edge_rows','known_answers','lnphi','baw','alo'):self.assertTrue(o['oracle'][key],key)
    def test_an_edited_oracle_file_is_refused(self):
        d=Path(tempfile.mkdtemp());edited=d/'oracle.json';edited.write_text(protocol.ORACLE_FILE.read_text().replace('"calibration"','"calibrations"',1))
        old=protocol.ORACLE_FILE
        try:
            protocol.ORACLE_FILE=edited
            with self.assertRaises(ValueError):protocol.oracle()
        finally:protocol.ORACLE_FILE=old

class AggregateSchemaTests(unittest.TestCase):
    def test_the_aggregate_schema_passes_the_summary_grammar(self):
        schema=json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text())
        self.assertEqual(bm.summary_schema_problems(schema),[])
        self.assertEqual(sorted(schema['properties']),['crosscheck','flag_counts','status_counts','unit_scale'])
        self.assertEqual(sorted(schema['properties']['status_counts']['properties']['bsm']['properties']),
                         sorted(['invalid_input','expired','no_bid','crossed','model_domain','below_min','above_max','not_converged','ok']))
    def test_the_model_blocks_list_the_five_models_as_optional_properties(self):
        """T28 (ruling R84, adaptation f; row EX20-LOCALSUMMARY-SCHEMA-01): status_counts, flag_counts.erf_saturated and
        crosscheck list the five protocol models as optional properties (no `required` list), so a per-unit local summary of
        one model passes; each model block keeps its closed keys; every other node is unchanged."""
        schema=json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text());p=schema['properties']
        models=['bsm','bjs','crr','baw','alo']
        blocks={'status_counts':p['status_counts'],'erf_saturated':p['flag_counts']['properties']['erf_saturated'],'crosscheck':p['crosscheck']}
        for name,node in blocks.items():
            with self.subTest(block=name):
                self.assertEqual(list(node['properties']),models);self.assertNotIn('required',node);self.assertIs(node['additionalProperties'],False)
                self.assertEqual(len({json.dumps(node['properties'][m],sort_keys=True) for m in models}),1)
        self.assertEqual(p['status_counts']['properties']['alo']['required'],['invalid_input','expired','no_bid','crossed','model_domain','below_min','above_max','not_converged','ok'])
        self.assertEqual(p['crosscheck']['properties']['alo']['required'],['iv','delta','gamma','theta','vega'])
        self.assertEqual(p['flag_counts']['required'],['multi_root','boundary_ambiguous','flat_vega','provider_mid_differs','below_intrinsic','erf_saturated'])
        self.assertEqual((schema['required'],p['unit_scale']['required']),(['status_counts','flag_counts','crosscheck','unit_scale'],['delta','gamma','theta','vega']))

class ExampleReadsProtocolTests(unittest.TestCase):
    def test_the_agreement_constants_are_the_protocol_values(self):
        t=protocol.tolerances()
        self.assertEqual(agreement.TOLERANCES,{k:t[k] for k in ('iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega')})
        self.assertEqual(agreement.MULTI_ROOT_GRID,protocol.solver()['multi_root_grid'])
    def test_the_checks_read_the_protocol(self):
        self.assertEqual(checks.FIXTURES,protocol.ORACLE_FILE)
        self.assertEqual(checks._baw_tolerances(),protocol.tolerances()['baw'])
        self.assertEqual(checks._tolerance_block('alo'),protocol.tolerances()['alo']);self.assertIsNone(checks._tolerance_block('bsm'))
    def test_no_module_reads_the_framework_option_data(self):
        """FR3 moved the oracle, tolerances and solver out of safety/performance-*.json: no module of the example reads them (the
        framework policy keeps pools.request_limit and the envelope, which the example still reads)."""
        here=Path(__file__).name;bad=[]
        for p in sorted(PROJECT.glob('python/**/*.py')):
            if p.name==here:continue
            text=p.read_text()
            if 'performance-fixtures' in text:bad.append(p.name)
            if 'performance-policy' in text and any(k in text for k in ("['tolerances']","['solver']")) and 'protocol.' not in text:bad.append(p.name)
        self.assertEqual(bad,[])

if __name__=='__main__':unittest.main()
