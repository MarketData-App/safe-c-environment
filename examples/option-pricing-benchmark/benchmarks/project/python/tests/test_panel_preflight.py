"""Task A6 (spec Amendment H21.4, H21.5, H21.7; I4.3): the panel pre-flight check and the ALO agreement refusal before
the tolerance lock.

The pre-flight check runs every planned single-record variant (the case manifest's implemented variants and worker counts
within the policy envelope; C rows are planned for Phase 2 and listed as not implemented) on the six panel rows for each
model and compares each status with py-reference's stored status. Any difference (a rounding-band difference included)
adds the row to the rejected set R; the selection is computed again by the one rule of H21.5 and the check repeats for
every changed row until all six pass. The check writes panel-preflight.json and never a panel reference.

The variant runner is injected here: a test-only stub returns the stored py-reference statuses, except MODEL_DOMAIN for one
variant, model and panel row. No real variant runs in these tests (the real runner is exercised by `bench check --check
panel-preflight`)."""
import json, math, pathlib, tempfile, unittest
from unittest import mock
from optionlab import checks, panel
from optionlab.contract import MODELS5
from optionlab import protocol
PROJECT=pathlib.Path(__file__).resolve().parents[2]
PANEL_PATH=PROJECT/'cases/option-chain-greeks.panel.json'
PANEL=json.loads(PANEL_PATH.read_text())
BAND=8

def stub(differ=None):
    """runner(variant, workers, model, indices) -> [(status, flags)] from the stored py-reference columns; `differ` =
    (variant, workers, model, row): that one call returns MODEL_DOMAIN on that row. `calls` records every call."""
    calls=[]
    def run(variant,workers,model,indices):
        calls.append((variant,workers,model,tuple(indices)));per=PANEL['per_model'][model]
        return [('MODEL_DOMAIN',per['flags'][i]) if differ==(variant,workers,model,i) else (per['status'][i],per['flags'][i]) for i in indices]
    run.calls=calls;return run

class PanelPreflightTests(unittest.TestCase):
    def body(self,runner):
        out=pathlib.Path(tempfile.mkdtemp());before=PANEL_PATH.read_bytes()
        res=checks.panel_preflight_body(out,runner=runner)
        self.assertEqual(PANEL_PATH.read_bytes(),before)          # the check never writes a panel reference
        return res,json.loads((out/'panel-preflight.json').read_text())
    def test_planned_variants_are_the_single_record_rows(self):
        got=checks.preflight_variants()
        self.assertEqual(got['run'],[('py-reference','direct'),('py-optimized','direct'),('py-library','direct')])
        self.assertEqual((got['not_implemented'],got['native']),([],['c-serial']))     # EX-10: c-serial is implemented; native-routes runs its panel rows
    def test_preflight_without_difference_changes_nothing(self):
        run=stub();res,rec=self.body(run)
        self.assertEqual(res['status'],'PASS');self.assertEqual(rec['replacements'],[]);self.assertEqual(rec['indices_after'],PANEL['indices'])
        self.assertEqual(rec['indices_before'],PANEL['indices']);self.assertEqual(rec['panel_sha256'],PANEL['sha256'])
        self.assertEqual({(m,v,w) for v,w,m,_ in run.calls},{(m,v,w) for m in MODELS5 for v,w in checks.preflight_variants()['run']})
        self.assertEqual({i for c in run.calls for i in c[3]},set(PANEL['indices']))
    def test_preflight_replaces_a_row_with_a_status_difference(self):
        old=PANEL['indices'][0];run=stub(('py-library','direct','alo',old));res,rec=self.body(run)
        self.assertEqual(res['status'],'PASS');self.assertEqual(len(rec['replacements']),1)
        r=rec['replacements'][0];per=PANEL['per_model']['alo']
        R={x['row'] for c in PANEL['cells'] for x in c['rejected']}|{old}
        want=panel.selection(PANEL,R)
        self.assertEqual((r['cell'],r['old_index'],r['variant'],r['workers'],r['model'],r['status'],r['reference_status']),
                         (0,old,'py-library','direct','alo','MODEL_DOMAIN',per['status'][old]))
        self.assertEqual(r['band_difference'],bool(per['flags'][old]&BAND) and per['status'][old]=='OK')
        self.assertEqual(r['agreement_finding'],not r['band_difference'])
        self.assertEqual((r['new_index'],r['level']),(want['indices'][0],want['cells'][0]['selected']['level']))
        self.assertEqual(rec['indices_after'],want['indices']);self.assertNotIn(old,rec['indices_after'])
        self.assertTrue(set(rec['passed_rows'])>=set(rec['indices_after']))           # every row of the final selection passed
        new=[c for c in run.calls if r['new_index'] in c[3]]
        self.assertEqual({(v,w,m) for v,w,m,_ in new},{(v,w,m) for m in MODELS5 for v,w in checks.preflight_variants()['run']})
    def test_a_py_reference_difference_is_a_failure(self):
        run=stub(('py-reference','direct','bsm',PANEL['indices'][2]));res,rec=self.body(run)
        self.assertEqual(res['status'],'FAIL');self.assertEqual(res['reason'],'py-reference differs from the stored panel reference')

class PanelSelectionRuleTests(unittest.TestCase):
    """The example's copy of the one selection rule (optionlab.panel.selection, used by the pre-flight replacement) equals
    the stored selection, and an empty cell raises PanelCellEmpty."""
    def test_selection_of_the_stored_reference(self):
        R={x['row'] for c in PANEL['cells'] for x in c['rejected']}
        got=panel.selection(PANEL,R)
        self.assertEqual(got['indices'],PANEL['indices'])
        self.assertEqual([c['order'] for c in got['cells']],[c['order'] for c in PANEL['cells']])
        self.assertEqual([c['selected'] for c in got['cells']],[c['selected'] for c in PANEL['cells']])
    def test_empty_cell(self):
        cols={'side':[1,0,1],'x':[0.1,0.0,-0.1],'t':[30/365,30/365,30/365],'k_over_s':[1.1,1.0,0.9]}
        per={m:{'status':['OK']*3,'flags':[0]*3,'grid_ok':[True]*3,'engine_evals':[1]*3} for m in MODELS5}
        with self.assertRaises(panel.PanelCellEmpty) as e:panel.selection({'rows':3,'rows_columns':cols,'per_model':per},set())
        self.assertEqual(e.exception.args[0],'itm-put-1y')    # the only ITM put is held by the 30-day cell; the 1-year cell has no row
    def test_row_x_is_the_log_moneyness_against_the_tau_v_forward(self):
        from optionlab.mapping import unit
        from optionlab.models import discount
        row=(1,100.0,110.0,0.5,1.0,1.1,0.04,0.012);r1,q1,_=unit(0.5,0.04,0.012,1.0)
        D_r=discount(r1,1.0);D_q=discount(q1,1.0);self.assertEqual(panel.row_x(row,None),math.log(110.0/((100.0*D_q)/D_r)))

class PanelPartJoinTests(unittest.TestCase):
    """A6P-04 (Task A6 lock follow-up): on a small synthetic chain (12 rows, K = 3) the example's row parts and join give the
    same columns, counts and reference_sha256 as one whole run (part=None)."""
    def test_parts_and_join_equal_one_run(self):
        from optionlab import synthetic
        from optionlab.contract import load_chain, with_rates
        from optionlab.params import CASE
        chain=with_rates(load_chain(synthetic.generate(12,PANEL['seed'],CASE)),CASE.rate,CASE.dividend_yield)
        whole=panel.inputs(chain,CASE,1);parts=[panel.inputs(chain,CASE,1,part=(k,3)) for k in range(3)]
        self.assertEqual([(p['start'],p['stop']) for p in parts],[(0,4),(4,8),(8,12)])
        joined=panel.join(parts)
        self.assertEqual(joined['grid'],panel.grid());self.assertNotIn('grid_points',joined);self.assertNotIn('sigma_hi',joined)
        self.assertEqual(joined,whole)
        with self.assertRaises(ValueError):panel.join([parts[1],parts[0],parts[2]])
        with self.assertRaises(ValueError):panel.join([parts[0],dict(parts[1],grid={'upper':4.0,'points':parts[1]['grid']['points']}),parts[2]])

class AloAgreementLockTests(unittest.TestCase):
    def test_alo_agreement_refused_before_the_lock(self):
        prov={'state':'provisional-g-alo2','iv_abs':1e-8,'iv_ulp_rel':1e-13,'price_rel':1e-12,'fit_nu':1e-10,'fit_rel':1e-12,'greek_abs':1e-9,
              'greek_rel':1e-6,'flat_vega':1e-12}
        with mock.patch.object(checks,'_tolerance_block',return_value=prov):
            res=checks.alo_agreement_body(pathlib.Path(tempfile.mkdtemp()))
        self.assertEqual((res['status'],res['reason'],res['tolerance_state']),('FAIL','tolerances.alo not locked','provisional-g-alo2'))
        with mock.patch.object(checks,'_tolerance_block',return_value=None):
            self.assertEqual(checks.alo_agreement_body(pathlib.Path(tempfile.mkdtemp()))['reason'],'tolerances.alo not locked')
    def test_alo_agreement_after_a_lock_compares_every_variant(self):
        locked={'state':'locked-g-alo2','approval':'perf-lab-test-only-lock','iv_abs':1e-8,'iv_ulp_rel':1e-13,'price_rel':1e-12,'fit_nu':1e-10,
                'fit_rel':1e-12,'greek_abs':1e-9,'greek_rel':1e-6,'flat_vega':1e-12}
        with mock.patch.object(checks,'_tolerance_block',return_value=locked):
            out=pathlib.Path(tempfile.mkdtemp());res=checks.alo_agreement_body(out,chains=((1,3),),edge_names=['alo-put-ok'])
        self.assertEqual(res['status'],'PASS',res.get('counts'))
        self.assertEqual(res['counts']['rows'],2*len(checks.ALO_AGREEMENT_VARIANTS));self.assertEqual(res['counts']['alo_edge_rows'],1)
        doc=json.loads((out/'alo-agreement.json').read_text())
        self.assertTrue(all(r['bits_16_32_equal'] and r['status_equal'] for r in doc['rows']))
    def test_check_is_declared_only_after_the_lock(self):
        decl={x['name']:x for x in json.loads((PROJECT/'bench.json').read_text())['checks']}
        state=protocol.tolerances()['alo']['state']
        for name in ('alo-agreement','alo-agreement-edges'):
            if state=='locked-g-alo2':self.assertEqual(decl[name],{'name':name,'module':'optionlab.checks','before_run':True,'selectors':['alo']})
            else:self.assertNotIn(name,decl)
        self.assertEqual(decl['panel-preflight']['before_run'],False);self.assertEqual(decl['alo-accuracy']['before_run'],False)
    def test_the_two_agreement_jobs_cover_every_input(self):
        """The ALO value agreement runs as two before-run checks (each within the 600 s check limit): alo-agreement on the
        AGREEMENT_CHAINS (no edge row) and alo-agreement-edges on every general and ALO edge row (no chain). Together they
        are the inputs of one alo_agreement_body run; no input is removed."""
        calls=[]
        with mock.patch.object(checks,'alo_agreement_body',side_effect=lambda out,**kw:calls.append(kw) or {'status':'PASS','rows':[]}):
            checks.CHECKS['alo-agreement'](pathlib.Path(tempfile.mkdtemp()),[]);checks.CHECKS['alo-agreement-edges'](pathlib.Path(tempfile.mkdtemp()),[])
        self.assertEqual(calls,[{'chains':checks.AGREEMENT_CHAINS,'edge_names':()},{'chains':(),'edge_names':None}])

if __name__=='__main__':unittest.main()
