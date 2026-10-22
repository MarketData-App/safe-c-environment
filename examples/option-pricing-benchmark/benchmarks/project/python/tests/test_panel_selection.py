"""Task A6 (spec Amendment H21.6, I7.2; replaces the Task 7 body): the stored five-model panel reference against an
independent evaluation.

- Schema, identity and generator: the closed schema, models MODELS5 and mask 31, and the stored generator hash equal to
  the sha256 of the regenerated synthetic large chain (T7-04).
- Every stored row: side, K/S, x = ln(K/F) and T recompute bit-equal from the regenerated row (H21.6).
- Per cell: the stored candidate order is the prefix, up to the selected row, of the order recomputed from the stored
  inputs (H21.3 classes, H21.5 window levels and d order, ties by the lower index).
- Each stored rejection names an existing pre-flight record with an equal sha256 that holds the status difference.
- The one selection rule with the stored rejected set R reproduces the stored indices.
- Every row of the stored orders recomputes equal (status, flags, engine_evals per model; the grid test where the rule
  reaches it), and the slowest-row diagnostic rows (largest stored engine_evals per model) recompute equal.
The synthetic generator is prefix-stable, so synthetic.row(j, seed) is row j of the large chain."""
import hashlib, json, math, pathlib, sys, unittest
import jsonschema
from optionlab import synthetic, reference as ref_mod
from optionlab.contract import MODELS5, load_chain, rows as chain_rows, with_rates
from optionlab.panel import LISTED_FLAGS, grid_ok, row_x, scale_value
from optionlab import panel as panel_mod, protocol
from optionlab.params import CASE
SRC=pathlib.Path('/src');sys.path.insert(0,str(SRC/'tools'))
import bench_panel as bp
PROJECT_DIR='examples/option-pricing-benchmark'
RULE=protocol.protocol()['panel']['cell_rule']
PROJECT=pathlib.Path(__file__).resolve().parents[2]
PANEL=json.loads((PROJECT/'cases/option-chain-greeks.panel.json').read_text())
MANIFEST=json.loads((PROJECT/'cases/option-chain-greeks.json').read_text())
# H21.3 cells in cell order: the cells of the protocol cell rule (FR5), as (category value, position target, scale target, band test)
CELLS=tuple((RULE['category']['labels'][c['category']],c['position_target'],c['scale_target'],lambda x,b=c['band']:bp.in_band(x,b)) for c in RULE['cells'])

def regenerate(j):
    rec=synthetic.row(j,PANEL['seed'],CASE);chain=with_rates(load_chain({'s':'ok',**{k:[rec[k]] for k in synthetic.KEYS}}),CASE.rate,CASE.dividend_yield)
    return chain_rows(chain)[0]
def candidate(i):
    per=PANEL['per_model']
    return all(per[m]['status'][i]=='OK' and not per[m]['flags'][i]&LISTED_FLAGS and per[m]['grid_ok'][i] is True for m in MODELS5)
def level(t,tt):
    a=math.fabs(math.log(t/tt));return 0 if a<=math.log(2.0) else 1 if a<=math.log(4.0) else 2
def candidate_order(cell):
    side,xt,tt,cls=cell;c=PANEL['rows_columns']
    rows=[i for i in range(PANEL['rows']) if c['side'][i]==side and c['x'][i] is not None and cls(c['x'][i]) and candidate(i)]   # x is null where K/F <= 0 (an INVALID_INPUT row, K = 0)
    return sorted(rows,key=lambda i:(level(c['t'][i],tt),abs(c['x'][i]-xt)+abs(math.log(c['t'][i]/tt)),i))
def rejected():
    return {r['row'] for cell in PANEL['cells'] for r in cell['rejected']}

class PanelSelectionTests(unittest.TestCase):
    def test_schema_identity_and_generator(self):
        jsonschema.Draft202012Validator(json.loads((SRC/'schemas/bench-panel-reference.json').read_text())).validate(PANEL)
        self.assertEqual((PANEL['models'],PANEL['mask']),(list(MODELS5),31))
        from optionlab.adapter import OptionChainGreeks
        a=OptionChainGreeks({k:v['value'] for k,v in MANIFEST['parameters'].items()})
        self.assertEqual(hashlib.sha256(a.synthesize(PANEL['rows'],PANEL['seed'])).hexdigest(),PANEL['generator_sha256'])
    def test_the_framework_checks_the_reference_against_the_protocol_rule(self):
        """T11 (EX-4): schema version 4, the sealed digest, the stored cell rule and cells equal to the protocol cell rule, and the
        order, rejected set and indices recomputed by the framework rule (bench_panel.check) from the stored inputs."""
        self.assertEqual(PANEL['schema_version'],4);self.assertEqual(PANEL['sha256'],bp.digest(PANEL))
        self.assertNotIn('grid_points',PANEL);self.assertNotIn('sigma_hi',PANEL)
        self.assertEqual(PANEL['cell_rule'],bp.stored_rule(RULE));self.assertEqual(PANEL['cell_rule']['grid'],panel_mod.grid())
        self.assertEqual([c['name'] for c in PANEL['cells']],panel_mod.cell_names())
        bp.check(SRC,PANEL,RULE)
        self.assertEqual(bp.select(PANEL,RULE,bp.stored_rejected(PANEL)),PANEL['indices'])
        self.assertEqual(panel_mod.selection(PANEL,bp.stored_rejected(PANEL))['indices'],PANEL['indices'])
    def test_the_scale_column_is_positive_on_every_row(self):
        """The framework refuses a scale value <= 0; a row with T <= 0 stores NO_SCALE and is never a candidate."""
        t=PANEL['rows_columns']['t'];self.assertTrue(all(v>0.0 for v in t))
        for i,v in enumerate(t):
            if v==panel_mod.NO_SCALE:self.assertFalse(candidate(i))
        self.assertEqual((scale_value(0.0),scale_value(-1.0),scale_value(0.5)),(panel_mod.NO_SCALE,panel_mod.NO_SCALE,0.5))
    def test_side_ks_x_and_t_recompute_bit_equal_for_every_row(self):
        c=PANEL['rows_columns'];bad=[]
        for i in range(PANEL['rows']):                              # every stored row (H21.6), not only the rows of the candidate orders
            row=regenerate(i);side,S,K,T=row[:4]
            if (side,K/S,row_x(row,CASE),scale_value(T))!=(c['side'][i],c['k_over_s'][i],c['x'][i],c['t'][i]):bad.append(i)
        self.assertEqual(bad,[])
    def test_stored_order_is_the_recomputed_prefix(self):
        for cell,stored in zip(CELLS,PANEL['cells']):
            got=candidate_order(cell);want=[r['row'] for r in stored['order']]
            self.assertEqual(got[:len(want)],want);self.assertEqual(want[-1],stored['selected']['row'])
    def test_each_rejection_names_an_existing_preflight_record(self):
        for cell in PANEL['cells']:
            for r in cell['rejected']:
                p=PROJECT/r['preflight_path'];data=p.read_bytes()          # stored relative to benchmarks/project/ (PB-L6)
                self.assertEqual(hashlib.sha256(data).hexdigest(),r['preflight_sha256'])
                rec=json.loads(data)
                self.assertTrue(any(x['old_index']==r['row'] and x['variant']==r['variant'] and x['model']==r['model'] and x['status']!=x['reference_status'] for x in rec['replacements']))
    def test_one_selection_rule_with_the_stored_rejected_set(self):
        held=set();R=rejected();out=[]
        for cell in CELLS:
            i=next(j for j in candidate_order(cell) if j not in R and j not in held);held.add(i);out.append(i)
        self.assertEqual(out,PANEL['indices'])
    def test_rows_in_the_stored_orders_recompute_equal(self):
        per=PANEL['per_model']
        for i in sorted({r['row'] for cell in PANEL['cells'] for r in cell['order']}):
            row=regenerate(i)
            for m in MODELS5:
                status,_,flags,evals=ref_mod.evaluate(row,m,CASE,{})
                with self.subTest(row=i,model=m):
                    self.assertEqual((status,flags,evals),(per[m]['status'][i],per[m]['flags'][i],per[m]['engine_evals'][i]))
                    if status=='OK' and not flags&LISTED_FLAGS:self.assertEqual(grid_ok(row,m,CASE),per[m]['grid_ok'][i])
    def test_slowest_rows_recompute_equal(self):
        """The slowest-row check of the Task 7 test, for five models (G3.6 diagnostic: the largest stored engine_evals per
        model, ties by the lower index)."""
        per=PANEL['per_model']
        for m in MODELS5:
            ev=per[m]['engine_evals'];i=ev.index(max(ev))
            with self.subTest(model=m):
                status,_,flags,evals=ref_mod.evaluate(regenerate(i),m,CASE,{})
                self.assertEqual((status,flags,evals),(per[m]['status'][i],per[m]['flags'][i],ev[i]))

if __name__=='__main__':unittest.main()
