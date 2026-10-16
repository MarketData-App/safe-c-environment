"""Task 7 (Amendment G3.3, G3.7; P3P-08) and Task A6 (Amendment I7.2, H21): the panel reference schema, the host-side
selection from the stored candidate inputs under the H21 cell rule (five models, mask 31), the reference check, the
pre-flight record input of `bench panel --rejected-from` and the `bench panel` refusals. No container runs here.

Task A6 replaced the G3.3 selection tests (a distance over two row values, rounding_band excluded, mask 15): H21
supersedes that rule (erratum to item G3.3 and item I7.2). Each replaced test has an H21 counterpart below (listed flags,
other flag bits, grid test, status, category, ties, the unevaluated grid test, the distance). FR5 (rulings FR5-R1, FR5-R3):
the cell rule and the grid settings come from the fixture project's protocol under neutral names."""
import argparse, copy, json, math, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_panel as bp
import bench_model as bm
from evidence import GateError
from schema_check import validate

MODELS=('m1','m2','m3','m4','m5')       # FR3: the panel models of the fixture project's protocol (the example models move with the example)
DF='fixture-v1';FIXTURE='tests/fixtures/bench-project'
S_NEAR=30/365          # the scale target of the fixture's near cells
# FR5 (ruling FR5-R1 item 1): the synthetic cell rule of the fixture project's protocol. Category column `group` (g0 = 0,
# g1 = 1), position column `p`, scale column `s`, report column `r`; the six cells keep the H21 bands and targets.
RULE=bp.panel_rule(ROOT,FIXTURE);COLUMNS=bp.row_columns(RULE);GRID=RULE['grid']   # FR5A-01: the grid settings of the protocol

def h21_doc():
    """12 rows, five models, mask 31: two candidates per cell, the second only at level 1 or 2; row 10 carries rounding_band."""
    side=[1,1,1,1,0,0,0,0,1,1,1,1];x=[0.09,0.12,0.10,0.08,0.01,-0.02,0.0,0.03,-0.11,-0.09,-0.10,-0.12]
    t=[45/365,14/365,1.0,3.5,45/365,100/365,1.0,0.3,30/365,8/365,1.0,2.6]
    cols={'group':side,'p':x,'s':t,'r':[1.0]*12}
    per={m:{'status':['OK']*12,'flags':[0]*12,'grid_ok':[True]*12,'engine_evals':[1]*12} for m in MODELS}
    per['m5']['flags'][10]=bp.ROUNDING_BAND
    return {'rows':12,'rows_columns':cols,'per_model':per,'mask':31,'models':list(MODELS)}

def fixture(rejected=()):
    """The sealed full panel reference of h21_doc (the closed schema); `rejected`: stored rejection entries."""
    d=h21_doc();n=d['rows']
    d['rows_columns']['r']=[1.10,1.12,1.105,1.08,1.01,0.98,1.0,1.03,0.9,0.91,0.905,0.89]
    inputs={'n':n,'models':list(MODELS),'mask':31,'digest_form':DF,'reference_sha256':'b'*64,'grid':GRID,
            **{k:d['rows_columns'][k] for k in COLUMNS},'per_model':d['per_model']}
    return bp.build(inputs,case='demo-case',seed=20261007,generator_sha256='a'*64,models=MODELS,digest_form=DF,rule=RULE,rejected=list(rejected))

def entry(row,cell,variant='py-library',workers='direct',model='m5',status='MODEL_DOMAIN',ref='OK',band=True,sha='c'*64):
    return {'row':row,'cell':cell,'reason':'preflight-status-difference','variant':variant,'workers':workers,'model':model,'status':status,
            'reference_status':ref,'band_difference':band,'preflight_sha256':sha,'preflight_path':f'cases/panel-preflight/{sha}.json'}

class PanelCellRuleTests(unittest.TestCase):            # Amendment H21
    def test_constants(self):
        self.assertEqual(bp.panel_spec(ROOT,FIXTURE),(list(MODELS),31,DF));self.assertFalse(bp.LISTED_FLAGS&bp.ROUNDING_BAND)
        with self.assertRaisesRegex(GateError,'no panel'):bp.panel_spec(ROOT,'examples/bench-demo')      # a project without a panel
        self.assertFalse(hasattr(bp,'MODELS'))                                                          # the framework names no model
    def test_classes_are_never_relaxed(self):
        d=h21_doc();sel=bp.select(d,RULE);x=d['rows_columns']['p']
        self.assertTrue(x[sel[0]]>0 and x[sel[1]]>0);self.assertTrue(all(abs(x[i])<=math.log(1.05) for i in sel[2:4]));self.assertTrue(x[sel[4]]<0 and x[sel[5]]<0)
    def test_rounding_band_is_admitted(self):
        self.assertIn(10,bp.select(h21_doc(),RULE))
    def test_fallback_levels(self):
        self.assertEqual([c['selected']['level'] for c in bp.selection_report(h21_doc(),RULE)['cells']],[0,0,0,0,0,0])
        d=h21_doc();d['per_model']['m3']['status'][0]='MODEL_DOMAIN'      # the level-0 row of g1-pos-near leaves; row 1 (scale 14/365) enters at level 1
        self.assertEqual(bp.selection_report(d,RULE)['cells'][0]['selected'],{'row':1,'level':1})
    def test_rejected_rows_are_skipped_and_cells_recomputed(self):
        d=h21_doc();first=bp.select(d,RULE);again=bp.select(d,RULE,rejected=frozenset({first[0]}))
        self.assertNotIn(first[0],again);self.assertEqual(len(set(again)),6)
    def test_empty_cell_fails(self):
        d=h21_doc()
        for i in (8,9,10,11):d['per_model']['m1']['status'][i]='MODEL_DOMAIN'
        with self.assertRaises(bp.PanelRefusal) as e:bp.select(d,RULE)
        self.assertEqual(e.exception.reason,'panel-cell-empty')
    def test_stored_order_is_a_prefix_up_to_the_selected_row(self):
        for c in bp.selection_report(h21_doc(),RULE)['cells']:self.assertEqual(c['order'][-1]['row'],c['selected']['row'])

class PanelCellRuleDetailTests(unittest.TestCase):
    """H21 counterparts of the replaced G3.3 selection tests, and the window, order and one-rule details of H21.5."""
    def test_cells_are_the_protocol_cells_in_order(self):
        """FR5: the cells come from the fixture protocol (the H21 bands and targets with neutral names); the framework
        module names no cell."""
        self.assertEqual([(c['name'],c['category'],c['band']['op'],c['band']['bound'],c['position_target'],c['scale_target']) for c in RULE['cells']],
                         [('g1-pos-near','g1','gt',0.0,math.log(1.10),S_NEAR),('g1-pos-far','g1','gt',0.0,math.log(1.10),1.0),
                          ('g0-mid-near','g0','abs_le',math.log(1.05),0.0,S_NEAR),('g0-mid-far','g0','abs_le',math.log(1.05),0.0,1.0),
                          ('g1-neg-near','g1','lt',0.0,math.log(0.90),S_NEAR),('g1-neg-far','g1','lt',0.0,math.log(0.90),1.0)])
        self.assertEqual((RULE['category'],RULE['position'],RULE['scale'],RULE['level_ratios']),({'column':'group','labels':{'g0':0,'g1':1}},'p','s',[2.0,4.0]))
        self.assertEqual(COLUMNS,['group','p','s','r'])
        self.assertFalse(hasattr(bp,'CELLS'));self.assertFalse(hasattr(bp,'SIDES'))
        self.assertEqual(bp.cell_names(ROOT,FIXTURE),[c['name'] for c in RULE['cells']]);self.assertEqual(bp.cell_names(ROOT,None),[])
        self.assertEqual(bp.cell_names(ROOT,'examples/bench-demo'),[])
        with self.assertRaisesRegex(GateError,'cell rule'):bp.panel_rule(ROOT,'examples/bench-demo')
    def test_window_levels_use_the_normative_test(self):
        tt=S_NEAR
        for t,want in ((tt*2.0,0),(tt/2.0,0),(tt*2.0000001,1),(tt*4.0,1),(tt*4.0000001,2),(tt/4.0000001,2)):
            with self.subTest(t=t):self.assertEqual(bp.level(t,tt),want);self.assertEqual(bp.level(t,tt,RULE['level_ratios']),want)
        self.assertEqual(bp.level(tt*3.0,tt,(3.0,9.0)),0);self.assertEqual(bp.level(tt*3.1,tt,(3.0,9.0)),1)   # FR5: the declared ratios decide
    def test_each_band_op(self):
        for op,bound,yes,no in (('gt',0.0,1e-9,0.0),('lt',0.0,-1e-9,0.0),('abs_le',0.5,-0.5,0.5000001)):
            with self.subTest(op=op):
                self.assertTrue(bp.in_band(yes,{'op':op,'bound':bound}));self.assertFalse(bp.in_band(no,{'op':op,'bound':bound}))
    def test_level_and_distance_of_the_fixture(self):
        o=bp.selection_report(h21_doc(),RULE,full=True)['cells'][0]['order']
        self.assertEqual([(e['row'],e['level']) for e in o],[(0,0),(1,1),(2,2),(3,2)])
        self.assertEqual(o[0]['d'],abs(0.09-math.log(1.10))+abs(math.log((45/365)/S_NEAR)))
    def test_each_listed_flag_excludes_the_row(self):
        for bit in (1,2,4):
            d=h21_doc();d['per_model']['m2']['flags'][0]=bit
            with self.subTest(bit=bit):self.assertEqual(bp.selection_report(d,RULE)['cells'][0]['selected'],{'row':1,'level':1})
    def test_other_flag_bits_do_not_exclude(self):
        for bit in (8,16,32,64):
            d=h21_doc();d['per_model']['m4']['flags'][0]=bit
            with self.subTest(bit=bit):self.assertEqual(bp.select(d,RULE)[0],0)
    def test_a_failed_grid_test_excludes_the_row(self):
        d=h21_doc();d['per_model']['m5']['grid_ok'][0]=False;self.assertEqual(bp.select(d,RULE)[0],1)
    def test_a_status_other_than_ok_excludes_the_row(self):
        for status in ('NOT_CONVERGED','MODEL_DOMAIN','BELOW_MIN'):
            d=h21_doc();d['per_model']['m5']['status'][4]=status
            with self.subTest(status=status):self.assertEqual(bp.selection_report(d,RULE)['cells'][2]['selected'],{'row':5,'level':1})   # level 1: scale 100/365 (d 1.224) before scale 0.3 (d 1.325)
    def test_category_matters(self):
        d=h21_doc()
        for i in (4,5,6,7):d['per_model']['m1']['status'][i]='MODEL_DOMAIN'
        with self.assertRaises(bp.PanelRefusal) as e:bp.select(d,RULE)   # g1 rows with |p| <= ln(1.05) never fill a g0 cell
        self.assertEqual(e.exception.cell,'g0-mid-near')
    def test_an_unevaluated_grid_test_on_a_candidate_row_is_an_error(self):
        d=h21_doc();d['per_model']['m1']['grid_ok'][0]=None
        with self.assertRaisesRegex(ValueError,'grid'):bp.select(d,RULE)
    def test_ties_go_to_the_lower_index(self):
        d=h21_doc();d['rows_columns']['p'][3]=d['rows_columns']['p'][0];d['rows_columns']['s'][3]=d['rows_columns']['s'][0]
        self.assertEqual(bp.select(d,RULE)[0],0)
        d['per_model']['m1']['status'][0]='MODEL_DOMAIN';self.assertEqual(bp.selection_report(d,RULE)['cells'][0]['selected'],{'row':3,'level':0})
    def test_a_row_is_used_in_one_cell_only(self):
        d=h21_doc();d['rows_columns']['s'][2]=S_NEAR;d['rows_columns']['p'][2]=math.log(1.10)   # row 2 is now the best row of both g1-pos cells
        sel=bp.select(d,RULE);self.assertEqual(sel[0],2);self.assertEqual(sel[1],3)
    def test_rejected_row_in_any_cell_is_skipped_everywhere(self):
        d=h21_doc();rep=bp.selection_report(d,RULE,rejected=frozenset({0,8}))
        self.assertEqual([c['selected']['row'] for c in rep['cells']],[1,2,4,6,9,10])
        self.assertEqual([e['row'] for e in rep['cells'][0]['order']],[0,1])     # the stored order holds the rejected row before the selected one
    def test_distance_is_linear_position_plus_log_scale(self):
        d=h21_doc();d['rows_columns']['p'][11]=math.log(0.90);d['rows_columns']['s'][11]=1.0      # an exact g1-neg-far row beats row 10
        self.assertEqual(bp.select(d,RULE)[5],11)
    def test_panel_rows_list_the_category_the_report_values_and_the_level(self):
        rows=bp.panel_rows(fixture(),RULE)
        self.assertEqual([(r['cell'],r['index'],r['category'],r['level']) for r in rows][0],('g1-pos-near',0,'g1',0))
        self.assertEqual({k:v for k,v in rows[0]['values'].items() if k!='s_scaled'},{'r':1.10,'p':0.09,'s':45/365})
        self.assertAlmostEqual(rows[0]['values']['s_scaled'],45.0,places=9)          # the report factor 365
        self.assertEqual([r['index'] for r in rows],[0,2,4,6,8,10])
    def test_slowest_row_per_model(self):
        d=fixture();self.assertEqual(bp.slowest(d),{m:0 for m in MODELS})

class SchemaTests(unittest.TestCase):
    def test_fixture_is_valid(self):
        self.assertTrue(validate(ROOT,'bench-panel-reference',fixture()))
        self.assertTrue(validate(ROOT,'bench-panel-reference',fixture([entry(0,0)])))
    def test_refuses_a_free_string(self):
        for path,value in ((('per_model','m1','status',1),'fine'),(('dataset',),'local:dataset'),(('cells',0,'name'),'Deep Cell'),
                           (('reference_digest_form',),'Free Form'),(('models',4),'Bad Model'),(('cells',0,'band','op'),'ge'),
                           (('cells',0,'category'),'G1'),(('cell_rule','position'),'Bad Column'),(('rows_columns','group',0),'g1'),
                           (('cell_rule','level_ratios',0),1.0),(('cells',0,'scale_target'),0.0)):
            d=fixture();o=d
            for k in path[:-1]:o=o[k]
            o[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_the_four_model_mask(self):
        # FR3: the models are project data, so the mask and model consistency is checked by bench_panel.check
        d=fixture();d['mask']=15;d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'mask'):bp.check(ROOT,d,RULE)
        d=fixture();d['models']=list(MODELS[:4]);d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'mask'):bp.check(ROOT,d,RULE)
        d=fixture();d['mask']=256
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_a_seventh_index_and_five_indices(self):
        d=fixture();d['indices'].append(0)
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
        d=fixture();d['indices'].pop()
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_a_model_without_grid_ok_or_flags(self):
        for key in ('grid_ok','flags','status','engine_evals'):
            d=fixture();del d['per_model']['m5'][key]
            with self.subTest(key=key),self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_a_missing_model_a_missing_x_and_an_extra_key(self):
        d=fixture();del d['per_model']['m5'];d=bp.seal(d)
        with self.assertRaises(GateError):bp.check(ROOT,d,RULE)              # FR3: check compares per_model with the models
        d=fixture();d['per_model']={}
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
        d=fixture();del d['rows_columns']['p'];d=bp.seal(d)          # FR5: the columns are project names, so check compares them with the rule
        with self.assertRaisesRegex(GateError,'columns'):bp.check(ROOT,d,RULE)
        d=fixture();d['rows_columns']['extra']=[0.0]*12;d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'columns'):bp.check(ROOT,d,RULE)
        d=fixture();d['schema_version']=3
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)   # FR5 migration: a version 3 reference is refused
        d=fixture();d['note']='x'
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
        d=fixture();d['per_model']['m1']['f1']=[0.2]*12          # FR3-11: an extra per-model key (neutral name)
        with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_a_bad_cell_record(self):
        for mutate in (lambda c:c.pop('order'),lambda c:c.pop('selected'),lambda c:c.pop('rejected'),lambda c:c['selected'].update(level=3),
                       lambda c:c['order'][0].update(level=-1),lambda c:c.update(note=1)):
            d=fixture();mutate(d['cells'][0])
            with self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
    def test_refuses_a_bad_rejection(self):
        for key,value in (('preflight_sha256','x'),('band_difference','yes'),('preflight_path','/etc/x.json'),('reason','other'),('model','Bad Model')):
            d=fixture([entry(0,0)]);d['cells'][0]['rejected'][0][key]=value
            with self.subTest(key=key),self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)
        d=fixture([entry(0,0)]);d['cells'][0]['rejected'][0]['model']='m9';d=bp.seal(d)       # a model outside the panel models
        with self.assertRaisesRegex(GateError,'outside'):bp.check(ROOT,d,RULE)
    def test_refuses_a_bad_value_type(self):
        for key,value in (('grid_ok',[1]*12),('flags',[-1]*12),('engine_evals',[1.5]*12)):
            d=fixture();d['per_model']['m2'][key]=value
            with self.subTest(key=key),self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',d)

class CheckTests(unittest.TestCase):
    def test_check_accepts_the_fixture(self):
        self.assertIsNone(bp.check(ROOT,fixture(),RULE))
        self.assertIsNone(bp.check(ROOT,fixture([entry(0,0)]),RULE))
    def test_check_refuses_other_indices(self):
        d=fixture();d['indices']=[1,2,4,6,8,10];d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'indices'):bp.check(ROOT,d,RULE)
    def test_check_refuses_a_stored_order_that_is_not_the_recomputed_prefix(self):
        d=fixture();d['cells'][0]['order'][0]['d']+=1e-9;d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'order'):bp.check(ROOT,d,RULE)
        d=fixture();d['cells'][1]['selected']['level']=1;d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'order'):bp.check(ROOT,d,RULE)
    def test_check_refuses_changed_cell_definitions(self):
        d=fixture();d['cells'][4]['position_target']=-0.1;d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'cell'):bp.check(ROOT,d,RULE)
    def test_check_refuses_a_reference_of_another_cell_rule(self):
        """FR5: the stored rule and cells must equal the project's rule; a changed protocol rule refuses an old reference."""
        d=fixture()
        for mutate in (lambda r:r.__setitem__('level_ratios',[2.0,8.0]),lambda r:r['cells'][0]['band'].__setitem__('bound',0.01),
                       lambda r:r['report'].pop(),lambda r:r['category']['labels'].__setitem__('g2',2),lambda r:r['grid'].__setitem__('upper',3.0),lambda r:r['cells'][0].__setitem__('name','g1-pos-x')):
            rule=copy.deepcopy(RULE);mutate(rule)
            with self.subTest(mutate=mutate),self.assertRaises(GateError):bp.check(ROOT,d,rule)
    def test_check_refuses_bad_row_values(self):
        for col,i,value in (('group',0,2),('group',0,1.0),('s',0,0.0),('s',0,-1.0),('s',0,None),('r',0,True),('p',0,'0.1')):
            d=fixture();d['rows_columns'][col][i]=value;d=bp.seal(d)
            with self.subTest(col=col,value=value),self.assertRaises(GateError):bp.check(ROOT,d,RULE)
        d=fixture();d['rows_columns']['r'][0]=None;d=bp.seal(d)
        self.assertIsNone(bp.check(ROOT,d,RULE))          # a report column may hold null (no value); the selection is unchanged
        self.assertIsNone(bp.panel_rows(d,RULE)[0]['values']['r'])

    def test_check_refuses_indices_that_ignore_a_stored_rejection(self):
        d=fixture();d['cells'][0]['rejected']=[entry(0,0)];d=bp.seal(d)       # row 0 rejected but still selected
        with self.assertRaises(GateError):bp.check(ROOT,d,RULE)
    def test_check_refuses_a_wrong_digest(self):
        d=fixture();d['seed']=1
        with self.assertRaisesRegex(GateError,'sha256'):bp.check(ROOT,d,RULE)
    def test_check_refuses_a_short_column(self):
        d=fixture();d['per_model']['m4']['grid_ok'].pop();d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'length'):bp.check(ROOT,d,RULE)
        d=fixture();d['rows_columns']['p'].pop();d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'length'):bp.check(ROOT,d,RULE)
    def test_check_refuses_grid_ok_on_a_row_without_the_status_and_flag_rule(self):
        d=fixture();d['per_model']['m3']['status'][3]='MODEL_DOMAIN';d=bp.seal(d)     # grid_ok True stays on a non-candidate
        with self.assertRaisesRegex(GateError,'grid_ok'):bp.check(ROOT,d,RULE)
    def test_check_requires_grid_ok_on_a_rounding_band_row(self):
        d=fixture();d['per_model']['m5']['grid_ok'][10]=None;d=bp.seal(d)
        with self.assertRaises(GateError):bp.check(ROOT,d,RULE)
    def test_seal_is_the_sha256_of_the_document_without_its_own_field(self):
        d=fixture();self.assertRegex(d['sha256'],'^[0-9a-f]{64}$');self.assertEqual(bp.seal(copy.deepcopy(d))['sha256'],d['sha256'])

class BuildTests(unittest.TestCase):
    def test_build_selects_stores_the_order_and_seals(self):
        d=fixture()
        self.assertEqual(d['indices'],[0,2,4,6,8,10]);self.assertEqual(d['mask'],31);self.assertEqual(d['models'],list(MODELS))
        self.assertEqual([c['selected'] for c in d['cells']],[{'row':i,'level':0} for i in (0,2,4,6,8,10)])
        self.assertTrue(all(c['rejected']==[] for c in d['cells']))
    def test_build_with_a_rejection_moves_the_cell_and_stores_the_entry_by_cell(self):
        e=entry(0,0);d=fixture([e])
        self.assertEqual(d['indices'][0],1);self.assertEqual(d['cells'][0]['selected'],{'row':1,'level':1})
        stored=d['cells'][0]['rejected'];self.assertEqual(len(stored),1)
        self.assertEqual(stored[0],{k:v for k,v in e.items() if k!='cell'})
        self.assertEqual([x['row'] for x in d['cells'][0]['order']],[0,1])
    def test_build_refuses_other_models(self):
        f=fixture();inputs={'n':12,'models':['m1','m2','m3','m4'],'mask':15,'digest_form':DF,'reference_sha256':'b'*64,'grid':GRID,
                             **{k:f['rows_columns'][k] for k in COLUMNS},'per_model':f['per_model']}
        with self.assertRaises(GateError):bp.build(inputs,case='demo-case',seed=20261007,generator_sha256='a'*64,models=MODELS,digest_form=DF,rule=RULE)
    def test_build_refuses_inputs_without_the_rule_columns(self):
        f=fixture();base={'n':12,'models':list(MODELS),'mask':31,'digest_form':DF,'reference_sha256':'b'*64,'grid':GRID,
                          **{k:f['rows_columns'][k] for k in COLUMNS},'per_model':f['per_model']}
        build=lambda inputs:bp.build(inputs,case='demo-case',seed=20261007,generator_sha256='a'*64,models=MODELS,digest_form=DF,rule=RULE)
        self.assertEqual(build(base)['indices'],[0,2,4,6,8,10])
        for change in (lambda i:i.pop('p'),lambda i:i.__setitem__('extra',[0]*12),lambda i:i['group'].__setitem__(0,7),
                       lambda i:i.__setitem__('grid',dict(GRID,points=GRID['points']*2)),lambda i:i.pop('grid')):     # FR5A-01: the protocol grid
            inputs=copy.deepcopy(base);change(inputs)
            with self.subTest(change=change),self.assertRaises(GateError):build(inputs)
    def test_the_grid_settings_are_project_data(self):
        """FR5A-01 (ruling FR5-R3): the reference stores the protocol's grid settings in its cell rule; the framework schema
        names no grid constant and bounds the settings (finite upper above 0, an integer point count of 2 to GRID_POINTS_MAX)."""
        d=fixture();self.assertEqual(d['cell_rule']['grid'],GRID);self.assertEqual(GRID,{'upper':2.5,'points':32})
        schema=json.loads((ROOT/'schemas/bench-panel-reference.json').read_text())
        self.assertEqual(sorted(k for k,v in schema['properties'].items() if 'const' in v),['dataset','schema_version'])   # no project value is a constant
        self.assertEqual(sorted(d),sorted(schema['required']))
        for grid in ({'upper':0,'points':32},{'upper':1e7,'points':32},{'upper':2.5,'points':1},{'upper':2.5,'points':bp.GRID_POINTS_MAX+1},
                     {'upper':2.5,'points':2.5},{'upper':'x','points':32},{'upper':2.5},{'upper':2.5,'points':32,'extra':1}):
            p=copy.deepcopy(bm.load_protocol(ROOT,FIXTURE));p['panel']['cell_rule']['grid']=grid
            with self.subTest(grid=grid),self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)
            r=copy.deepcopy(d);r['cell_rule']['grid']=grid
            with self.subTest(reference=grid),self.assertRaises(GateError):validate(ROOT,'bench-panel-reference',r)
        p=copy.deepcopy(bm.load_protocol(ROOT,FIXTURE));p['panel']['cell_rule']['grid']={'upper':2.5,'points':bp.GRID_POINTS_MAX}
        self.assertTrue(validate(ROOT,'bench-protocol',p))
        rule=copy.deepcopy(RULE);rule['grid']=dict(GRID,points=64)
        with self.assertRaisesRegex(GateError,'cell rule'):bp.check(ROOT,d,rule)          # a reference of other grid settings
    def test_an_extreme_scale_target_gives_a_gate_error(self):
        """FR5A-05: a scale target near the schema minimum makes s / s_t overflow; the distance is not finite, so build and
        check refuse with GateError (never an uncaught ValueError from the seal)."""
        rule=copy.deepcopy(RULE)
        for c in rule['cells']:c['scale_target']=1e-308
        f=fixture();inputs={'n':12,'models':list(MODELS),'mask':31,'digest_form':DF,'reference_sha256':'b'*64,'grid':GRID,
                            **copy.deepcopy({k:f['rows_columns'][k] for k in COLUMNS}),'per_model':f['per_model']}
        inputs['s']=[1e300]*12
        with self.assertRaisesRegex(GateError,'finite'):
            bp.build(inputs,case='demo-case',seed=20261007,generator_sha256='a'*64,models=MODELS,digest_form=DF,rule=rule)
        d=fixture();d['rows_columns']['s']=[1e300]*12;d['cell_rule']=bp.stored_rule(rule)
        for c,rc in zip(d['cells'],rule['cells']):c['scale_target']=rc['scale_target']
        d=bp.seal(d)
        with self.assertRaisesRegex(GateError,'finite'):bp.check(ROOT,d,rule)
    def test_build_raises_the_refusal_for_an_empty_cell(self):
        f=fixture();per=copy.deepcopy(f['per_model'])
        for i in (8,9,10,11):per['m1']['status'][i]='MODEL_DOMAIN';per['m1']['grid_ok'][i]=None
        inputs={'n':12,'models':list(MODELS),'mask':31,'digest_form':DF,'reference_sha256':'b'*64,'grid':GRID,
                **{k:f['rows_columns'][k] for k in COLUMNS},'per_model':per}
        for m in MODELS:
            for i in (8,9,10,11):per[m]['grid_ok'][i]=None
        with self.assertRaises(bp.PanelRefusal):bp.build(inputs,case='demo-case',seed=20261007,generator_sha256='a'*64,models=MODELS,digest_form=DF,rule=RULE)
    def test_join_parts_concatenates_in_row_order(self):
        f=fixture();cols=f['rows_columns'];per=f['per_model']
        def part(k,a,b):
            return {'part':[k,2],'start':a,'stop':b,'n_total':12,'grid':GRID,**{c:cols[c][a:b] for c in COLUMNS},   # FR5A-01: each part names its grid
                    'per_model':{m:{key:v[a:b] for key,v in per[m].items()} for m in MODELS}}
        joined=bp.join_part_columns([part(0,0,5),part(1,5,12)],COLUMNS)
        self.assertEqual(joined['group'],cols['group']);self.assertEqual(joined['per_model'],per)
        with self.assertRaises(GateError):bp.join_part_columns([part(1,5,12),part(0,0,5)],COLUMNS)
        with self.assertRaises(GateError):bp.join_part_columns([part(0,0,5),part(1,6,12)],COLUMNS)
        with self.assertRaises(GateError):bp.join_part_columns([part(0,0,5),part(1,5,12)],COLUMNS+['q'])   # a rule column that the parts lack
    def test_part_ranges_cover_the_rows_once(self):
        self.assertEqual(bp.part_ranges(13230,8)[0],(0,1653));self.assertEqual(bp.part_ranges(13230,8)[-1][1],13230)
        r=bp.part_ranges(13230,bp.PANEL_PARTS);self.assertEqual(sum(b-a for a,b in r),13230)
        self.assertTrue(all(r[k][1]==r[k+1][0] for k in range(len(r)-1)))

class RejectedFromTests(unittest.TestCase):
    """--rejected-from (H21.6, H21.7): a tracked pre-flight record under cases/panel-preflight/ whose sha256 is its file
    name; its rejected rows form R. Anything else refuses the command before any container."""
    def setUp(self):
        self.d=Path(tempfile.mkdtemp());self.base=self.d/'p'/bm.PROJECT_AREA;(self.base/'cases/panel-preflight').mkdir(parents=True)
        self.addCleanup(shutil.rmtree,self.d)
    def record(self,replacements,carried=(),name=None):
        import hashlib
        body=json.dumps({'schema_version':1,'label':'panel-preflight','replacements':list(replacements),'carried':list(carried)}).encode()
        sha=hashlib.sha256(body).hexdigest();rel=f'cases/panel-preflight/{name or sha}.json';(self.base/rel).write_bytes(body);return rel,sha
    def rep(self,row=0,cell=0):
        return {'cell':cell,'cell_name':'g1-pos-near','old_index':row,'variant':'py-library','workers':'direct','model':'m5',
                'status':'MODEL_DOMAIN','reference_status':'OK','band_difference':True,'new_index':1,'level':1}
    def test_a_tracked_record_gives_the_rejected_entries(self):
        rel,sha=self.record([self.rep()])
        with mock.patch.object(bp,'tracked',return_value=True):got=bp.load_rejected(self.d,'p',rel)
        self.assertEqual(got,[{'row':0,'cell':0,'reason':'preflight-status-difference','variant':'py-library','workers':'direct','model':'m5',
                                'status':'MODEL_DOMAIN','reference_status':'OK','band_difference':True,'preflight_sha256':sha,'preflight_path':rel}])
    def test_carried_entries_keep_their_own_record(self):
        old_rel,old_sha=self.record([self.rep(3,4)])
        carried=[dict(entry(3,4,sha=old_sha))]
        rel,sha=self.record([self.rep()],carried)
        with mock.patch.object(bp,'tracked',return_value=True):got=bp.load_rejected(self.d,'p',rel)
        self.assertEqual(sorted((e['row'],e['preflight_sha256']) for e in got),[(0,sha),(3,old_sha)])
    def test_an_untracked_record_is_refused(self):
        rel,_=self.record([self.rep()])
        with mock.patch.object(bp,'tracked',return_value=False),self.assertRaisesRegex(GateError,'tracked'):bp.load_rejected(self.d,'p',rel)
    def test_a_name_that_is_not_the_sha256_is_refused(self):
        rel,_=self.record([self.rep()],name='0'*64)
        with mock.patch.object(bp,'tracked',return_value=True),self.assertRaisesRegex(GateError,'sha256'):bp.load_rejected(self.d,'p',rel)
    def test_a_record_outside_the_preflight_folder_is_refused(self):
        rel,_=self.record([self.rep()])
        other=self.base/'cases'/Path(rel).name;other.write_bytes((self.base/rel).read_bytes())
        for path in (f'cases/{Path(rel).name}','../x.json','/tmp/x.json'):
            with self.subTest(path=path),mock.patch.object(bp,'tracked',return_value=True),self.assertRaises(GateError):bp.load_rejected(self.d,'p',path)
    def test_a_carried_entry_without_its_record_is_refused(self):
        carried=[entry(3,4,sha='d'*64)]
        rel,_=self.record([self.rep()],carried)
        with mock.patch.object(bp,'tracked',return_value=True),self.assertRaises(GateError):bp.load_rejected(self.d,'p',rel)

class CommandTests(unittest.TestCase):
    def args(self,dataset,rejected_from=None):
        project='tests/fixtures/bench-project'      # FR1 (FS1 F3): the synthetic unit-test project; the framework names no example
        return argparse.Namespace(project=project,case=bm.project_bench(ROOT,project)['cases'][0],dataset=dataset,format='json',rejected_from=rejected_from)
    def test_panel_refuses_a_local_dataset_before_any_container(self):
        with self.assertRaisesRegex(GateError,'synthetic'):bp.panel_cmd(ROOT,self.args('local:/tmp/dataset.json'))
    def test_panel_refuses_another_synthetic_tier(self):
        for d in ('synthetic:small','synthetic:medium','synthetic:large#panel','x'):
            with self.subTest(d=d),self.assertRaises(GateError):bp.panel_cmd(ROOT,self.args(d))
    def test_panel_needs_a_project(self):
        a=self.args('synthetic:large');a.project=None
        with self.assertRaises(GateError):bp.panel_cmd(ROOT,a)
    def test_panel_refuses_a_missing_record_before_any_container(self):
        with mock.patch.object(bp,'tracked',return_value=False),self.assertRaises(GateError):
            bp.panel_cmd(ROOT,self.args('synthetic:large','cases/panel-preflight/'+'e'*64+'.json'))
    def test_panel_is_registered_in_bench(self):
        import bench
        self.assertIn('panel',bench.HANDLERS)
        parser=argparse.ArgumentParser();bench.configure_parser(parser)
        a=parser.parse_args(['panel','--project','examples/demo','--case','demo-case','--format','json'])
        self.assertEqual((a.project,a.case,a.dataset,a.format,a.rejected_from),('examples/demo','demo-case','synthetic:large','json',None))
        a=parser.parse_args(['panel','--project','examples/demo','--case','demo-case','--rejected-from','cases/panel-preflight/x.json'])
        self.assertEqual(a.rejected_from,'cases/panel-preflight/x.json')
    def test_registration_line_precedes_configure_parser(self):
        src=(ROOT/'tools/bench.py').read_text()
        self.assertEqual(src.count('import bench_phase3_cli;bench_phase3_cli.register(HANDLERS,ARGUMENTS)'),1)
        self.assertLess(src.index('bench_phase3_cli.register(HANDLERS,ARGUMENTS)'),src.index('def configure_parser'))
    def test_panel_job_inputs_are_the_large_tier_with_the_five_model_mask(self):
        import bench_deadline as bd
        pol=bm.load_policy(ROOT)
        self.assertEqual(bd.job_inputs('panel',{'sizes':pol['sizes']},{}),(pol['sizes']['large'],1))
        self.assertEqual(bp.panel_spec(ROOT,FIXTURE)[0],['m1','m2','m3','m4','m5'])     # FR3: the job's selector mask is the protocol's panel models

class ProjectLayoutTests(unittest.TestCase):
    def test_a_panel_sidecar_and_the_preflight_folder_are_not_case_manifests(self):
        d=Path(tempfile.mkdtemp())
        try:
            base=d/'p'/bm.PROJECT_AREA;(base/'cases/panel-preflight').mkdir(parents=True);(base/'python').mkdir()
            (base/'bench.json').write_text(json.dumps({'schema_version':1,'name':'demo-project','cases':['demo-case'],'checks':[]}))
            (base/'cases/demo-case.json').write_text('{}');(base/'cases/demo-case.panel.json').write_text('{}')
            (base/'cases/panel-preflight'/('f'*64+'.json')).write_text('{}')
            shutil.copytree(ROOT/'schemas',d/'schemas')
            self.assertEqual(bm.project_bench(d,'p')['cases'],['demo-case'])
        finally:shutil.rmtree(d)

class PolicyTests(unittest.TestCase):
    """G2.4 and I4.3 (FR3: project data): per-selector tolerance blocks live in the project's protected protocol file; the
    framework policy holds none. The example project's block values and lock references move with the example (FR3
    handoff list); here the fixture protocol carries the same shapes."""
    FIXTURE='tests/fixtures/bench-project'
    def test_the_framework_policy_holds_no_tolerance(self):
        self.assertNotIn('tolerances',json.loads((ROOT/'safety/performance-policy.json').read_text()))
        self.assertEqual(bm.load_policy(ROOT)['tolerances'],{})
    def test_selector_blocks_are_separate_and_locked_with_a_reference(self):
        t=bm.load_policy(ROOT,self.FIXTURE)['tolerances']
        self.assertEqual({k:v for k,v in t.items() if not isinstance(v,dict)},{'state':'provisional-fixture','abs':1e-9})
        for s in ('m4','m5'):
            with self.subTest(selector=s):self.assertTrue(t[s]['state'].startswith('locked'));self.assertIn('approval',t[s])
        self.assertEqual(t['m4']['terms'],{'a':0,'b':0})
    def test_the_protocol_schema_refuses_a_bad_block(self):
        proto=bm.load_protocol(ROOT,self.FIXTURE)
        for mutate in (lambda b:b.__setitem__('state','Locked State'),lambda b:b.__setitem__('approval','x'),lambda b:b['terms'].__setitem__('a','zero'),
                       lambda b:b.__setitem__('Bad Key',1)):
            p=copy.deepcopy(proto);mutate(p['tolerances']['m4'])
            with self.subTest(mutate=mutate),self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)
        self.assertTrue(validate(ROOT,'bench-protocol',proto))
    def test_locked_state_needs_the_approval_reference(self):
        """FR3-02 (restores the A6P-05/N6 rule of the policy schema at 34512cd for every project block): a block in a
        locked state needs its approval reference."""
        proto=bm.load_protocol(ROOT,self.FIXTURE)
        for s in ('m4','m5'):
            p=copy.deepcopy(proto);b=p['tolerances'][s];b.pop('approval')
            with self.subTest(selector=s):
                with self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)
                b['approval']='fixture-tolerance-lock';self.assertTrue(validate(ROOT,'bench-protocol',p))
        p=copy.deepcopy(proto);p['tolerances']['m4']['state']='provisional-fixture';p['tolerances']['m4'].pop('approval')
        self.assertTrue(validate(ROOT,'bench-protocol',p))                    # a provisional block needs no reference
    def test_schema_refuses_a_free_state(self):
        """FR3-02: the bare state `locked` (and any state that is not provisional-<name> or locked-<name>) is refused."""
        proto=bm.load_protocol(ROOT,self.FIXTURE)
        for state in ('locked','provisional','locked-','unlocked-fixture','fixed'):
            p=copy.deepcopy(proto);p['tolerances']['m4']['state']=state
            with self.subTest(state=state),self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)

class LockGuardTests(unittest.TestCase):
    """A6P-05 (Task A6 lock follow-up): a plan or run refuses a selector whose tolerance block (from the project's protocol,
    FR3) is not locked; a locked block and a selector without a block pass."""
    def policy(self,state):
        p=copy.deepcopy(bm.load_policy(ROOT,'tests/fixtures/bench-project'));p['tolerances']['m5']['state']=state;return p
    def test_unlocked_selector_is_refused(self):
        with self.assertRaisesRegex(GateError,'tolerances.m5 not locked'):bm.require_locked_selectors(self.policy('provisional-fixture'),['all','m5'])
    def test_a_bare_locked_state_or_a_lock_without_a_reference_is_refused(self):
        """FR3-02: the run guard repeats the schema rule (a hand-built policy never bypasses it)."""
        with self.assertRaisesRegex(GateError,'not locked'):bm.require_locked_selectors(self.policy('locked'),['m5'])
        p=self.policy('locked-fixture');p['tolerances']['m5'].pop('approval')
        with self.assertRaisesRegex(GateError,'approval'):bm.require_locked_selectors(p,['m5'])
    def test_locked_and_blockless_selectors_pass(self):
        self.assertIsNone(bm.require_locked_selectors(self.policy('locked-fixture'),['all','m1','m4','m5']))
        self.assertIsNone(bm.require_locked_selectors(bm.load_policy(ROOT),['all','m5']))     # no project: no block
    def test_the_plan_applies_the_guard_to_every_trial(self):
        import bench_plan
        point={'name':'unit-m5-one','selector':'m5'};trial={}
        with self.assertRaisesRegex(GateError,'not locked'):
            bench_plan.trial_selector(trial,point,{},self.policy('provisional-fixture'),{},{},10800,None)

class CellRuleProtocolTests(unittest.TestCase):
    """FR5 (ruling FR5-R1 item 1): the cell rule is project data in the protected protocol. The schema holds its shape; the
    protocol load (bench_model._check_cell_rule) holds the cross-field rules; both fail closed."""
    def proto(self):return copy.deepcopy(bm.load_protocol(ROOT,FIXTURE))
    def test_the_fixture_rule_is_valid(self):
        p=self.proto();self.assertTrue(validate(ROOT,'bench-protocol',p));self.assertIsNone(bm._check_cell_rule(p['panel']['cell_rule']))
    def test_the_schema_refuses_a_bad_rule_shape(self):
        for mutate in (lambda r:r['cells'].pop(),lambda r:r['cells'].append(copy.deepcopy(r['cells'][0])),lambda r:r['cells'][0]['band'].__setitem__('op','ge'),
                       lambda r:r.__setitem__('position','Bad Column'),lambda r:r['category']['labels'].__setitem__('g0',256),
                       lambda r:r.__setitem__('level_ratios',[2.0]),lambda r:r['report'][0].__setitem__('factor',0),lambda r:r.__setitem__('extra',1),
                       lambda r:r['cells'][0].__setitem__('scale_target',-1.0),lambda r:r.pop('report'),lambda r:r.pop('grid')):
            p=self.proto();mutate(p['panel']['cell_rule'])
            with self.subTest(mutate=mutate),self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)
    def test_the_protocol_load_refuses_a_bad_cross_field_rule(self):
        for mutate,word in ((lambda r:r.__setitem__('scale','p'),'differ'),(lambda r:r['report'].append({'name':'n2','column':'n'}),'reserved'),
                            (lambda r:r['report'].append({'name':'r','column':'r'}),'report name'),
                            (lambda r:r['cells'][1].__setitem__('name','g1-pos-near'),'different names'),
                            (lambda r:r['cells'][0].__setitem__('category','g9'),'category'),(lambda r:r.__setitem__('level_ratios',[4.0,2.0]),'increase'),
                            (lambda r:r['cells'][2]['band'].__setitem__('bound',-0.1),'abs_le'),
                            (lambda r:r['category']['labels'].__setitem__('g1',0),'share'),
                            (lambda r:r['report'].extend({'name':f'e{i}','column':f'e{i}'} for i in range(5)),'more than 8')):
            rule=copy.deepcopy(self.proto()['panel']['cell_rule']);mutate(rule)
            with self.subTest(word=word),self.assertRaisesRegex(GateError,word):bm._check_cell_rule(rule)
    def test_the_rule_is_optional_and_the_panel_command_needs_it(self):
        """Additive (C1): a protocol panel block without a cell rule stays valid; bench panel then refuses before any container."""
        p=self.proto();p['panel'].pop('cell_rule');self.assertTrue(validate(ROOT,'bench-protocol',p))
        p.pop('verdict_counts');self.assertTrue(validate(ROOT,'bench-protocol',p))
        with mock.patch.object(bm,'protocol_value',return_value={'models':list(MODELS),'digest_form':DF}):
            with self.assertRaisesRegex(GateError,'cell rule'):bp.panel_rule(ROOT,FIXTURE)
            self.assertEqual(bp.cell_names(ROOT,FIXTURE),[])
    def test_the_policy_carries_the_cell_names(self):
        self.assertEqual(bm.load_policy(ROOT,FIXTURE)['panel_cells'],[c['name'] for c in RULE['cells']])
        self.assertEqual(bm.load_policy(ROOT)['panel_cells'],[])

class PanelSourceTests(unittest.TestCase):
    """A6P-01 (Task A6 lock follow-up): every part and join job of `bench panel` must run on the source identity of the
    first job; the join refuses parts with different grid settings."""
    def test_one_source_identity_passes_and_is_returned(self):
        self.assertEqual(bp.same_source(['a'*64]*9),'a'*64)
    def test_a_changed_source_identity_is_refused(self):
        for srcs in (['a'*64]*4+['b'*64]+['a'*64]*4,['a'*64,None],[None]):
            with self.subTest(srcs=srcs),self.assertRaisesRegex(GateError,'source identity'):bp.same_source(srcs)
    def part(self,k,a,b,**extra):
        f=fixture();cols=f['rows_columns'];per=f['per_model']
        return {'part':[k,2],'start':a,'stop':b,'n_total':12,'grid':GRID,**{c:cols[c][a:b] for c in COLUMNS},
                'per_model':{m:{key:v[a:b] for key,v in per[m].items()} for m in MODELS},**extra}
    def test_join_refuses_other_grid_settings(self):
        for extra in ({'grid':dict(GRID,points=16)},{'grid':dict(GRID,upper=4.0)},{'grid':None}):
            with self.subTest(extra=extra),self.assertRaisesRegex(GateError,'grid'):bp.join_part_columns([self.part(0,0,5),self.part(1,5,12,**extra)],COLUMNS)
        self.assertEqual(len(bp.join_part_columns([self.part(0,0,5),self.part(1,5,12)],COLUMNS)['group']),12)

if __name__=='__main__':unittest.main()
