"""Task 18: the adapter's `local_summary` (Amendment A): the option-case block of the closed local aggregate (spec 12, L4).
Synthetic chains only; a summary holds counts, quantiles over OK rows and whole-run digests, never a row value."""
import copy, hashlib, json, math, re, sys, tempfile, unittest
from pathlib import Path
from benchlab.workload import load_case_adapter
from optionlab import reference as ref_mod
from optionlab.contract import rows, MODELS, MODELS5, STATUSES
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')
KEYS={'rows','status_counts','flag_counts','crosscheck','unit_scale','result_sha256','reference_sha256'}
FLAGS={'multi_root','boundary_ambiguous','flat_vega','provider_mid_differs','below_intrinsic','erf_saturated'}

def leaves(value):
    if isinstance(value,dict):
        for v in value.values():yield from leaves(v)
    elif isinstance(value,list):
        for v in value:yield from leaves(v)
    else:yield value

class LocalSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a=load_case_adapter(json.loads(CASE_FILE.read_text()))
        data=cls.a.synthesize(64,11);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        cls.chain=cls.a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()});cls.ref=cls.a.reference(cls.chain)
        cls.summary=cls.a.local_summary(cls.chain,cls.ref)
    def test_summary_has_exactly_the_closed_keys(self):
        s=self.summary;self.assertEqual(set(s),KEYS);self.assertEqual(s['rows'],64);self.assertEqual(set(s['flag_counts']),FLAGS)
        for m in MODELS:
            with self.subTest(model=m):self.assertEqual(sum(s['status_counts'][m].values()),64);self.assertEqual(set(s['status_counts'][m]),{x.lower() for x in STATUSES})   # EX-3: the aggregate schema's keys
        for k in ('result_sha256','reference_sha256'):self.assertRegex(s[k],r'^[0-9a-f]{64}$')
        self.assertEqual(s['reference_sha256'],self.a.digest(self.ref))
    def test_summary_validates_against_the_protocol_aggregate_schema(self):
        """EX-3: the summary block (the closed keys without the framework fields) holds the schema of protocol/aggregate.schema.json."""
        import jsonschema
        from optionlab import protocol
        schema=json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text())
        block={k:self.summary[k] for k in ('status_counts','flag_counts','crosscheck','unit_scale')}
        jsonschema.Draft202012Validator(schema).validate(block)
    def test_summary_holds_no_row_value(self):
        text=json.dumps(self.summary);values={v for v in leaves(self.summary) if isinstance(v,float)}
        bids=[b for b in self.chain['bid'] if math.isfinite(b) and b!=int(b)]
        self.assertTrue(bids)
        for b in bids:
            with self.subTest(bid=b):self.assertNotIn(b,values);self.assertNotIn(repr(b),re.findall(r'-?\d+\.\d+(?:e-?\d+)?',text))
    def test_erf_saturated_is_the_reference_count_per_model(self):
        """Amendment D item 3: erf_saturated per model, as optionlab.reference defines it (a count, not a failure)."""
        got=self.summary['flag_counts']['erf_saturated']
        self.assertEqual(got,ref_mod.erf_saturated(rows(self.chain),self.ref,self.a.params));self.assertEqual(set(got),set(MODELS))
        self.assertTrue(all(isinstance(v,int) and v>=0 for v in got.values()))
    def test_erf_saturated_counts_a_saturated_ok_row_and_a_band_row(self):
        """Synthetic reproducer: an OK row whose implied volatility puts |d| past 6 sqrt 2, and a MODEL_DOMAIN row with the
        rounding_band flag, each add one row to the model's count."""
        base=self.summary['flag_counts']['erf_saturated']['bsm'];col=self.ref['models']['bsm']
        def counted(i):
            one={'n':1,'models':{'bsm':{k:v[i:i+1] for k,v in col.items()}}}
            return ref_mod.erf_saturated([rows(self.chain)[i]],one,self.a.params)['bsm']
        ok=[i for i in range(64) if col['status'][i]=='OK' and not counted(i) and abs(math.log(self.chain['S'][i]/self.chain['K'][i]))>0.05]
        self.assertGreaterEqual(len(ok),2)
        ref=copy.deepcopy(self.ref);m=ref['models']['bsm']
        m['iv'][ok[0]]=1e-6
        m['status'][ok[1]]='MODEL_DOMAIN';m['flags'][ok[1]]|=ref_mod.FLAG_ROUNDING_BAND
        for f in ('iv','price','delta','gamma','theta','vega','rho'):m[f][ok[1]]=math.nan
        self.assertEqual(self.a.local_summary(self.chain,ref)['flag_counts']['erf_saturated']['bsm'],base+2)

    def test_crosscheck_quantiles_over_fewer_than_five_rows_are_null(self):
        """Controller ruling (concern 2): counts 1 and 4 keep the count and emit null quantiles; count 5 emits numbers."""
        ok=[i for i in range(64) if all(self.ref['models'][m]['status'][i]=='OK' for m in MODELS)
            and all(math.isfinite(v[i]) for v in self.chain['provider'].values())]
        self.assertGreaterEqual(len(ok),5)
        for k in (1,4,5):
            chain=copy.deepcopy(self.chain);keep=set(ok[:k])
            for f,col in chain['provider'].items():
                for i in range(64):
                    if i not in keep:col[i]=math.nan
            cc=self.a.local_summary(chain,self.ref)['crosscheck']
            for m in MODELS:
                for f,q in cc[m].items():
                    with self.subTest(k=k,model=m,field=f):
                        self.assertEqual(q['count'],k)
                        if k<5:self.assertEqual((q['median'],q['p90']),(None,None))
                        else:self.assertTrue(isinstance(q['median'],float) and isinstance(q['p90'],float))

def unit_selectors():
    """The single-model selectors that the protocol units declare, read on the test side: the model part of every unit name
    of every decision policy of protocol/protocol.json, in MODELS5 order."""
    from optionlab import protocol
    names={u.split('/',1)[0] for p in protocol.protocol()['decision_policies'].values() for u in p['units']}
    return sorted(names,key=MODELS5.index)

class PerUnitLocalSummaryTests(unittest.TestCase):
    """EX-20 item 4 (plan Task 31, line 4449; addendum E-T31-5): the local_summary of a per-unit local run, for every
    single-model selector that the protocol units declare. Each summary has the closed keys of the `all` summary; each model
    block holds the selector's model only; the counts of a base model equal those of the `all` summary on the same chain; the
    provider cross-check and the unit-scale check read the models of the result (the bsm part when the result has one, else
    its own model). T28 relaxed the protected protocol aggregate schema (ruling R84; ledger row EX20-LOCALSUMMARY-SCHEMA-01):
    it accepts each single-model summary, and the example code refuses an `all` summary with a missing model. Synthetic
    chains only."""
    _cache={}
    @classmethod
    def setUpClass(cls):
        cls.case=json.loads(CASE_FILE.read_text());cls.a=load_case_adapter(cls.case)
        data=cls.a.synthesize(64,11);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        cls.chain=cls.a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
        cls.all_summary=cls.a.local_summary(cls.chain,cls.a.reference(cls.chain))
    def unit(self,s):
        """(adapter, reference) of selector s; computed once per class."""
        key=('unit',s)
        if key not in self._cache:
            a=load_case_adapter(self.case,selector=s);self._cache[key]=(a,a.reference(self.chain))
        return self._cache[key]
    def summary(self,s):
        key=('summary',s)
        if key not in self._cache:
            a,ref=self.unit(s);self._cache[key]=a.local_summary(self.chain,ref)
        return self._cache[key]
    def test_the_protocol_units_declare_the_five_models(self):
        self.assertEqual(unit_selectors(),list(MODELS5))
    def test_each_summary_has_the_closed_keys_and_its_model_only(self):
        for s in unit_selectors():
            with self.subTest(selector=s):
                a,ref=self.unit(s);summ=self.summary(s)
                self.assertEqual(set(summ),KEYS);self.assertEqual(summ['rows'],64);self.assertEqual(set(summ['flag_counts']),FLAGS)
                self.assertEqual(set(summ['status_counts']),{s});self.assertEqual(sum(summ['status_counts'][s].values()),64)
                self.assertEqual(set(summ['status_counts'][s]),{x.lower() for x in STATUSES})
                self.assertEqual(summ['flag_counts']['erf_saturated'],ref_mod.erf_saturated(rows(self.chain),ref,a.params))
                self.assertEqual(set(summ['flag_counts']['erf_saturated']),{s})
                self.assertEqual(set(summ['crosscheck']),{s});self.assertEqual(set(summ['crosscheck'][s]),{'iv','delta','gamma','theta','vega'})
                self.assertEqual(set(summ['unit_scale']),{'delta','gamma','theta','vega'})
                for k in ('result_sha256','reference_sha256'):self.assertRegex(summ[k],r'^[0-9a-f]{64}$')
                self.assertEqual(summ['reference_sha256'],a.digest(ref))
    def test_a_base_model_summary_counts_equal_the_all_summary(self):
        """The same chain and the same py-reference rows: the status counts, the erf_saturated count and the cross-check counts of
        bsm, bjs and crr equal those of the `all` summary; the bsm summary takes the unit scale from the bsm part, as `all` does."""
        allsum=self.all_summary
        for s in MODELS:
            with self.subTest(selector=s):
                summ=self.summary(s)
                self.assertEqual(summ['status_counts'][s],allsum['status_counts'][s])
                self.assertEqual(summ['flag_counts']['erf_saturated'][s],allsum['flag_counts']['erf_saturated'][s])
                self.assertEqual({f:q['count'] for f,q in summ['crosscheck'][s].items()},{f:q['count'] for f,q in allsum['crosscheck'][s].items()})
        self.assertEqual(self.summary('bsm')['unit_scale'],allsum['unit_scale'])
    def test_a_summary_holds_no_row_value(self):
        bids=[b for b in self.chain['bid'] if math.isfinite(b) and b!=int(b)]
        self.assertTrue(bids)
        for s in unit_selectors():
            summ=self.summary(s);text=json.dumps(summ);values={v for v in leaves(summ) if isinstance(v,float)}
            found=re.findall(r'-?\d+\.\d+(?:e-?\d+)?',text)
            for b in bids:
                with self.subTest(selector=s,bid=b):self.assertNotIn(b,values);self.assertNotIn(repr(b),found)
    def test_the_crosscheck_and_the_unit_scale_read_the_models_of_the_result(self):
        from optionlab.crosscheck import provider_crosscheck, unit_scale
        for s in unit_selectors():
            with self.subTest(selector=s):
                _,ref=self.unit(s)
                self.assertEqual(set(provider_crosscheck(self.chain,ref)),{s})
                self.assertEqual(unit_scale(self.chain,ref),unit_scale(self.chain,ref,model=s))
    def test_the_protocol_aggregate_schema_accepts_each_single_model_summary(self):
        """T28 (ruling R84, adaptation f; row EX20-LOCALSUMMARY-SCHEMA-01): protocol/aggregate.schema.json lists the five models
        as optional properties of status_counts, flag_counts.erf_saturated and crosscheck, so the summary block of every
        single-model selector of the protocol units passes the parts of the host gate (bench_privacy.accept_aggregate) that read
        the summary: the framework schema grammar, the framework value rule and the project schema."""
        import jsonschema
        if '/src/tools' not in sys.path:sys.path.insert(0,'/src/tools')
        import bench_privacy
        from optionlab import protocol
        schema=json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text());v=jsonschema.Draft202012Validator(schema)
        self.assertEqual(bench_privacy.summary_schema_problems(schema),[])
        for s in unit_selectors():
            with self.subTest(selector=s):
                summ=self.summary(s);block={k:summ[k] for k in ('status_counts','flag_counts','crosscheck','unit_scale')}
                self.assertEqual(bench_privacy.summary_value_problems(block),[])
                self.assertEqual(sorted(e.message for e in v.iter_errors(block)),[])
    def test_the_relaxed_schema_still_refuses_another_model_and_a_partial_model_block(self):
        """The relaxation adds optional model names only: a model name outside the five, or a model block without one of its
        keys, still fails the project schema."""
        import jsonschema
        from optionlab import protocol
        v=jsonschema.Draft202012Validator(json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text()))
        summ=self.summary('baw');block={k:copy.deepcopy(summ[k]) for k in ('status_counts','flag_counts','crosscheck','unit_scale')}
        self.assertTrue(v.is_valid(block))
        other=copy.deepcopy(block);other['status_counts']['xyz']=other['status_counts']['baw']
        partial=copy.deepcopy(block);del partial['status_counts']['baw']['ok']
        nocheck=copy.deepcopy(block);del nocheck['crosscheck']['baw']['iv']
        for name,doc in (('another model',other),('partial status block',partial),('partial crosscheck block',nocheck)):
            with self.subTest(case=name):self.assertFalse(v.is_valid(doc))
    def test_an_all_summary_with_a_missing_model_is_refused_by_the_example_code(self):
        """The trade-off of the relaxation (adaptation f): the schema grammar has no conditional, so the project schema alone
        also accepts an `all` summary block without one of bsm, bjs and crr. The example code never writes one: local_summary
        of selector `all` takes the selected part of the reference (OptionChainGreeks.selected), which refuses a reference
        that lacks a model of the selector (ValueError) before any work."""
        import jsonschema
        from optionlab import protocol
        v=jsonschema.Draft202012Validator(json.loads(protocol.AGGREGATE_SCHEMA_FILE.read_text()))
        allsum=self.all_summary;block={k:copy.deepcopy(allsum[k]) for k in ('status_counts','flag_counts','crosscheck','unit_scale')}
        self.assertEqual(set(block['status_counts']),set(MODELS));self.assertTrue(v.is_valid(block))
        ref=self.a.reference(self.chain)
        for m in MODELS:
            with self.subTest(missing=m):
                cut=copy.deepcopy(block)
                for key in ('status_counts','crosscheck'):del cut[key][m]
                del cut['flag_counts']['erf_saturated'][m]
                self.assertTrue(v.is_valid(cut))                      # the schema alone accepts it (no conditional in the grammar)
                partial=dict(ref,models={k:x for k,x in ref['models'].items() if k!=m})
                with self.assertRaises(ValueError):self.a.local_summary(self.chain,partial)

if __name__=='__main__':unittest.main()
