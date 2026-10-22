"""The example's bench declaration, case manifest and opportunity record against the framework schemas (Amendment A)."""
import json, unittest
from pathlib import Path
import jsonschema
from optionlab import protocol
SRC=Path('/src')                                            # the bench container mounts the repository read-only at /src
PROJECT=Path(__file__).resolve().parents[2]                 # benchmarks/project

def schema(kind):return json.loads((SRC/'schemas'/f'{kind}.json').read_text())
def load(rel):return json.loads((PROJECT/rel).read_text())

class ManifestTests(unittest.TestCase):
    def test_files_validate_against_the_framework_schemas(self):
        for kind,rel in [('bench-project','bench.json'),('bench-case','cases/option-chain-greeks.json'),
                         ('bench-opportunity','cases/option-chain-greeks.opportunity.json'),('bench-case','cases/echo-control.json'),
                         ('bench-opportunity','cases/echo-control.opportunity.json')]:
            with self.subTest(rel=rel):jsonschema.Draft202012Validator(schema(kind)).validate(load(rel))
    def test_declaration_names_the_case_and_the_oracle_checks(self):
        decl=load('bench.json')
        self.assertEqual(decl['cases'],['option-chain-greeks','echo-control'])          # EX-10: the echo control case (R43 item h)
        self.assertEqual([(c['name'],c['module'],c['before_run']) for c in decl['checks']],
                         [('oracle-generate','optionlab.checks',False),('oracle-calibrate','optionlab.checks',False),
                          ('b06-prerequisite-oracle','optionlab.checks',True),('quantlib-alignment','optionlab.checks',True),
                          ('optimized-agreement','optionlab.checks',True),('b06-prerequisite-agreement','optionlab.checks',True),('call-cost-exploratory','optionlab.checks',False),
                          ('baw-hang-stub','optionlab.checks',False),       # Task 6 (G2.3): test-only, never before a run
                          ('baw-spread','optionlab.checks',False),          # Task 7 (G2.4): calibration evidence, never a gate before the lock
                          ('baw-agreement','optionlab.checks',True),        # Task A1 (G2.4): BAW value agreement at the locked tolerances
                          ('alo-overrun-stub','optionlab.checks',False),    # Task A5 (I9.4): test-only, never before a run
                          ('alo-spread','optionlab.checks',False),          # Task A5 (I4.2): measurement evidence, never a gate before the A6 lock
                          ('panel-preflight','optionlab.checks',False),     # Task A6 (H21.7): before the smoke calibration, never before every run
                          ('alo-accuracy','optionlab.checks',False)]        # Task A6 (I4.5): documented metric, never a gate
                         +([('alo-agreement','optionlab.checks',True),        # the lock follow-up (I4.3: after the lock only): the chain inputs
                            ('alo-agreement-edges','optionlab.checks',True)]  # and the edge-row inputs (two jobs: the 600 s check limit)
                           if protocol.tolerances()['alo']['state']=='locked-g-alo2' else [])
                         +[('c-vectors','optionlab.checks',True),('c-census','optionlab.checks',True),   # Phase 2: the C vectors and the census
                           ('c-census-generate','optionlab.checks',False),
                           ('worker-routes','optionlab.worker_check',False),    # EX-8 (T16-A03): the framework NativeWorker drives pl-worker; native, never before a run
                           ('native-routes','optionlab.native_check',False),    # EX-10 (R43 items b, c): the real-worker route tests
                           ('c-call-deadline','optionlab.native_check',False),  # EX-10 (R43 item i): the call-deadline kill of a C caller child
                           ('native-agreement','optionlab.native_check',False),  # EX-12 (R50 item c): the C agreement check, the native agreement check of bench.json
                           ('api-native','optionlab.api_check',False),           # EX-11 (R49 item c): the native tests of optionlab.api.price_chain
                           ('native-spread','optionlab.native_check',False)])    # EX-16 (R68): the section 3.7 spread of every variant (no gate)
    def test_the_case_no_longer_declares_local_requires(self):
        """FR3: the framework case schema has no `local_requires` key (the market-rate step left the framework). The market
        requirement of a local: run is held by the example adapter (task EX-6, T9-A04): `load` prices a dataset that is not
        labeled synthetic with the protocol SOFR rate or fails (test_market OwnerChainFailClosedTests). The case declares
        nothing, and the framework schema test above refuses the key."""
        self.assertNotIn('local_requires',load('cases/option-chain-greeks.json'))
    def test_the_case_manifests_declare_single_threaded_variants_only(self):
        """Owner 2026-10-16 (amendment E C15; ruling R3): the example has no pool row. Every variant runs on `direct`, every
        point uses only declared variants, and the case names no pool variant, so the framework builds a non-pooled adapter."""
        want={'option-chain-greeks.json':['py-reference','py-optimized','py-library','c-serial'],'echo-control.json':['py-reference','c-serial']}
        seen=[]
        for path in sorted((PROJECT/'cases').glob('*.json')):
            doc=json.loads(path.read_text())
            if 'variants' not in doc:continue
            with self.subTest(case=path.name):
                ids=[v['id'] for v in doc['variants']];seen.append(path.name)
                self.assertEqual(ids,want[path.name])
                c=next(v for v in doc['variants'] if v['id']=='c-serial')
                self.assertEqual((c['status'],c['workers']),('implemented',['direct']))        # EX-10: c-serial only (R43 item a)
                self.assertTrue(all(v['workers']==['direct'] for v in doc['variants']))
                self.assertTrue(all(set(p['variants'])<=set(ids) for p in doc['points']))
                from benchlab.workload import pooled_variants
                self.assertEqual(pooled_variants(doc),[])
        self.assertEqual(sorted(seen),sorted(want))
    def test_the_unit_points_use_the_neutral_unit_kind_names(self):
        """FR5 item 8: the full-dataset point replaces the former point name; the single-record units come with the protocol."""
        doc=load('cases/option-chain-greeks.json')
        self.assertEqual([p['name'] for p in doc['points']],['baseline','full-dataset','language-only','crossover-tiny','crossover-small']
                         +[f'unit-{m}-{k}' for k in ('full','one') for m in ('bsm','bjs','crr','baw','alo')])     # EX-10 (T10-A02): the 10 unit points
        self.assertEqual(load('cases/option-chain-greeks.opportunity.json')['sizes'],{'records_per_call':13230})
    def test_every_declared_check_is_registered(self):
        import importlib
        declared=load('bench.json')['checks']
        by_module={}
        for c in declared:by_module.setdefault(c['module'],set()).add(c['name'])
        for module,names in by_module.items():   # each declared check is registered by the module that declares it (T16-A03)
            with self.subTest(module=module):self.assertEqual(names,set(importlib.import_module(module).CHECKS))
    def test_case_and_record_paths_are_project_relative(self):
        case=load('cases/option-chain-greeks.json');record=load('cases/option-chain-greeks.opportunity.json')
        self.assertEqual(case['opportunity_record'],'benchmarks/project/cases/option-chain-greeks.opportunity.json')
        self.assertEqual((case['case_id'],record['case_id']),('option-chain-greeks','option-chain-greeks'))
        self.assertEqual(case['adapter'],'optionlab.adapter:OptionChainGreeks')
    def test_every_test_module_is_in_exactly_one_unit_group(self):
        """Ruling A6-C3 (Task A6 lock follow-up): the example suite runs as two container commands by a fixed module list;
        every tests/test_*.py module is in exactly one group, so no test is removed."""
        groups=load('bench.json')['unit_groups'];self.assertEqual(len(groups),2)
        modules=sorted(p.stem for p in (PROJECT/'python/tests').glob('test_*.py'))
        flat=[m for g in groups for m in g];self.assertEqual(sorted(flat),modules);self.assertEqual(len(flat),len(set(flat)))
    def test_opportunity_record_holds_the_i11_text(self):
        """Amendment I11 (Task A6), through the Amendment F item 6 procedure: the approver of perf-lab-t14-decide approved the
        record bytes at f91ce5b; the follow-up commit sets APPROVED with that approval reference (controller ruling, Task 15)."""
        record=load('cases/option-chain-greeks.opportunity.json')
        self.assertEqual(record['operation'],'IV and five greeks for one selected model (each of five), per request')
        self.assertIn({'name':'`fastScheme` for ALO (a definition change under `alo_scheme`, not an alternative under it)','state':'proposed','run_id':None},
                      record['python_options'])
        self.assertEqual(record['approval']['state'],'APPROVED');self.assertTrue(record['approval']['reference'].startswith('perf-lab-t14-decide'))
        self.assertEqual(record['approval']['baseline_variant'],'py-reference')
    def test_an_unknown_check_name_fails(self):
        import contextlib, io
        from optionlab import checks
        out=io.StringIO()
        with contextlib.redirect_stdout(out):rc=checks.main(['checks','no-such-check','/tmp'])
        self.assertEqual(rc,2);self.assertEqual(json.loads(out.getvalue().splitlines()[-1])['status'],'FAIL')
    def test_oracle_generate_refuses_an_unknown_part(self):
        import tempfile
        from optionlab import checks
        row=checks.CHECKS['oracle-generate'](Path(tempfile.mkdtemp()),['no-such-part'])
        self.assertEqual((row['status'],row['files']),('FAIL',[]))
    def test_checks_without_arguments_refuse_extra_arguments(self):
        """Review Minor 6."""
        import tempfile
        from optionlab import checks
        for name in ('oracle-calibrate','b06-prerequisite-oracle'):
            with self.subTest(name=name):
                row=checks.CHECKS[name](Path(tempfile.mkdtemp()),['extra'])
                self.assertEqual((row['status'],row['files']),('FAIL',[]))
        self.assertEqual(checks.CHECKS['oracle-generate'](Path(tempfile.mkdtemp()),['lnphi','extra'])['status'],'FAIL')
    def test_a_failed_oracle_item_is_counted_in_the_allowlisted_counts(self):
        """Review Minor 4: the framework filter passes `counts` only, so the per-item results travel there."""
        import tempfile
        from unittest import mock
        from optionlab import checks, oracle
        items={str(i):{'status':'PASS','checked':3,'failures':[]} for i in range(1,9)}
        items['5']=dict(items['5'],status='FAIL',failures=['a','b'],bjs_vs_lattice=None)
        item9={'status':'PASS','checked':4,'failures':[],'parts':{}}     # Task 9b: item 9 (QuantLib agreement) is part of the check
        with mock.patch.object(oracle,'run_all',lambda fx,params:items),mock.patch.object(checks,'quantlib_agreement_item',lambda fx,params,evidence=None:item9):
            row=checks.CHECKS['b06-prerequisite-oracle'](Path(tempfile.mkdtemp()),[])
        self.assertEqual(row['status'],'FAIL');self.assertEqual(len(row['counts']),19)   # ruling T28-C1: plus incomplete_items
        self.assertEqual((row['counts']['item5_checked'],row['counts']['item5_failures'],row['counts']['item1_failures']),(3,2,0))
        self.assertTrue(all(isinstance(v,int) for v in row['counts'].values()))

def framework_tools():
    """The framework planner modules (bench_capacity, bench_phase3, bench_model) from the read-only /src/tools."""
    import sys
    if str(SRC/'tools') not in sys.path:sys.path.insert(0,str(SRC/'tools'))
    import bench_capacity, bench_model, bench_phase3
    return bench_capacity,bench_phase3,bench_model

class CapacityAndMatrixTests(unittest.TestCase):
    """EX-20 (T26). Capacity (ruling R71 revised, then R84; owner answer 2026-10-20 'single thread only'): the case capacity
    block has one configuration, serial-workers with the Python variant py-optimized (direct, in the capacity child), and one
    client, so no two capacity requests run at the same time. R84: the framework capacity job starts its child without the
    native environment, so a C capacity configuration cannot run (open row EX20-CAPACITY-CNATIVE-01). B17 (Task 30; amendment E C5, C15): the case declares every single-threaded
    cell of the complete demo matrix (each implemented variant on direct workers; the kernel and caller scopes; warm and cold
    on every route, the inproc cold cell not-applicable; one memory trial per row; the capacity cell) and no multiple-worker
    cell, so B17 keeps the c-multiple-workers dimension NOT_RUN with the framework row EX17-B17-CMULTI-01."""
    CAPACITY={'tier':'small','clients':[1],'requests_per_client':8,
              'configurations':[{'name':'serial-workers','variant':'py-optimized'}]}
    ENVELOPE={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
    CELLS=['caller warm py-reference direct','caller cold py-reference direct','memory py-reference direct','kernel py-reference direct',
           'caller warm py-optimized direct','caller cold py-optimized direct','memory py-optimized direct','kernel py-optimized direct',
           'caller warm py-library direct','caller cold py-library direct','memory py-library direct',
           'caller warm c-serial direct [stdio]','caller cold c-serial direct [stdio]','memory c-serial direct [stdio]',
           'caller warm c-serial direct [shm]','caller cold c-serial direct [shm]','memory c-serial direct [shm]',
           'caller warm c-serial direct [inproc]','memory c-serial direct [inproc]','kernel c-serial direct',
           'capacity serial-workers py-optimized']
    DIMENSIONS={'python-one-worker','c-one-worker','kernel-scope','caller-scope','capacity-scope','caller-warm','caller-cold',
                'memory-trials','route-stdio','route-shm','route-inproc'}
    def test_the_capacity_block_has_one_single_threaded_configuration_and_one_client(self):
        case=load('cases/option-chain-greeks.json')
        self.assertEqual(case['capacity'],self.CAPACITY)
        self.assertIn('capacity',case['scopes'])
    def test_every_planned_capacity_trial_has_one_client(self):
        bc,_,bm=framework_tools();case=load('cases/option-chain-greeks.json');policy=bm.load_policy(SRC)
        for mode in ('decision','smoke'):
            with self.subTest(mode=mode):
                trials,blocked,estimate=bc.capacity_trials(case,policy,self.ENVELOPE,mode,20261007)
                self.assertEqual(blocked,[])
                self.assertEqual(len(trials),policy['capacity']['trials'][mode])        # one trial per block: 1 configuration x 1 client
                self.assertEqual({(t['configuration'],t['variant'],t['route'],t['workers'],t['clients'],t['requests_per_client'],t['tier'])
                                  for t in trials},{('serial-workers','py-optimized',None,'direct',1,8,'small')})
                self.assertTrue(all(bc.trial_format(t) is None for t in trials))
                self.assertGreater(estimate,0.0)
    def test_the_b17_matrix_of_the_case_holds_the_single_threaded_cells_only(self):
        _,b3,_=framework_tools();case=load('cases/option-chain-greeks.json')
        cells,na=b3.matrix_cells(case)
        self.assertEqual(sorted(c['cell'] for c in cells),sorted(self.CELLS))
        self.assertEqual([c['cell'] for c in na],['caller cold c-serial direct [inproc]'])
        self.assertTrue(all(c['workers'] in ('direct',None) for c in cells))
        dims=set().union(*[b3.cell_dimensions(c) for c in cells])
        self.assertEqual(dims,self.DIMENSIONS)
        self.assertEqual({d for d,_ in b3.B17_DIMENSIONS}-dims,{'python-multiple-workers','c-multiple-workers'})
        self.assertEqual(b3.B17_NOT_RUN,{'c-multiple-workers':'EX17-B17-CMULTI-01'})   # C5: the framework row keeps the C cell open
    def test_matrix_complete_needs_every_cell_and_names_each_missing_one(self):
        _,b3,_=framework_tools();case=load('cases/option-chain-greeks.json');cells,_=b3.matrix_cells(case)
        def observed(c):
            row={'scope':c['scope'],'mode':c['mode'],'variant':c['variant'],'workers':c['workers'],'route':c['route'],'warmup':False,
                 'eligible':True,'work_units':256}
            if c['scope']=='memory':row['memory']={'group_peak_bytes':1}
            if c['scope']=='capacity':row.update(workers='direct',capacity={'configuration':c['configuration'],'clients':1,'route':c['route']})
            return row
        rows=[observed(c) for c in cells];plan={'case':'option-chain-greeks'}
        self.assertEqual(b3.matrix_complete(plan,rows,case),[])
        for k,c in enumerate(cells):
            with self.subTest(cell=c['cell']):
                self.assertEqual(b3.matrix_complete(plan,rows[:k]+rows[k+1:],case),[f"{c['cell']}: not observed"])
