"""The option-chain Greeks workload of the reference example (Amendment A): the full registered-workload contract.
The timed call is prepare + run + materialize (caller scope).

Per-row rates (spec 3.1; Amendment C item 3; controller ruling on Task 13b): `load` gives every row its own r and q
columns, filled from the case parameters (the labeled assumptions of CI, tests and the synthetic chain). The pricing
path of every variant reads those columns; it never reads the scalar case rate or dividend yield. A chain without the
columns fails closed (ValueError) in `prepare`, `reference` and `validate`.

Owner-chain local runs (Task 18b, Amendment C; EX-6): there is no network step. `load` takes a dataset that is not positively
labeled synthetic (contract.decode_chain_origin: the generator symbol form and underlying SYN) as an owner chain: it prices every row with the SOFR constant of the protocol
(optionlab.market.protocol_rate) and the per-expiry q estimated from the chain (`owner_chain_rates`), so the reference, every
variant and `local_summary` (the provider cross-check) use the same values. If the protocol SOFR day is not the SOFR date of the
snapshot, `load` raises (`market_date_mismatch`); an owner chain never takes the case assumptions and never runs without a rate
(T9-A04). `with_market(items)` copies the adapter with a given q table for the protocol rate.

C rows (task EX-10, ruling R43): the variant c-serial runs on the route that benchlab.trial sets (`route`: stdio, shm or
inproc; optionlab.backends.NativeRows) with the models mask of the selector (native_codec.mask_for); prepare packs the request
records or the eight columns, run uses the warm backend of native_start or a cold one, materialize decodes the 290-byte
records (native_codec.materialize). The kernel hooks of the framework: pack_native (the request records of the kernel input
file), unpack_native (the kernel output records) and native_reference_digest (FNV-1a 64 of the ocg-v1 / ocg-v1m bytes of the
selected reference models, the value that pl-kernel prints as PLK1 digest=). take and row_status serve the single-record
(panel) trials (G7.3).

The run reference (R48; T6-R6, task M2c): `reference_cover(chain, selectors)` is the optional hook of benchlab.workload. It
returns one py-reference result of the union of the listed selectors' models, from which `selected` of each listed selector
takes exactly what its own `reference` gives (T6R6-A01). The count hooks (reference_counts, reference_exclusions,
reference_alo_counts) count every model that the reference they get holds: the coordinator calls them on the adapter of
the reference selector with its own or its covered reference (T6R6-A05).

The agreement controls (EX-14, T22; case B06): the hook agreement_mutation applies the project mutations of the protocol key
`agreement_mutations` (optionlab.agreement_controls) for the framework job agreement-controls. `digest` is total (a refused
value gets refused_digest) and `validate` decodes a raw C answer with the codec's record rule and refuses a result outside
the canonical form; see the two methods."""
import copy, hashlib, json, math
from optionlab.contract import decode_chain_origin, rows, rates, slice_chain, with_rates, selector_models, FIELDS, MODELS5, STATUSES, MAX_INPUT_BYTES
from optionlab import counters
from optionlab import native_codec as nc
from optionlab import reference as ref_mod
from optionlab.backends import NativeRows
from optionlab.params import params_from_manifest
from optionlab.synthetic import SIZES
MIN_QUANTILE_ROWS=5   # local_summary: crosscheck quantiles over fewer rows are suppressed (null)
REFUSED_FORM=b'ocg-refused-v1\n'       # EX-14: the prefix of refused_digest; canonical bytes start with b'{"digest_form":'
REFUSED_ERRORS=(ValueError,TypeError,KeyError,AttributeError,OverflowError)   # a value that the record rule or the canonical form refuses

def _refused_item(v):
    if isinstance(v,(bytes,bytearray,memoryview)):return {'bytes':bytes(v).hex()}
    return repr(v)

def refused_digest(value):
    """EX-14 (B06): the SHA-256 of REFUSED_FORM and a JSON form of a value that the canonical form refuses (keys sorted, NaN
    kept, bytes as hex). It is never the digest of a canonical result: the hashed bytes start with REFUSED_FORM, the canonical
    bytes with '{"digest_form":'. A value without a JSON form hashes its type name."""
    try:body=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=True,default=_refused_item).encode('ascii')
    except (TypeError,ValueError,RecursionError):body=type(value).__name__.encode('ascii','replace')
    return hashlib.sha256(REFUSED_FORM+body).hexdigest()

NON_CANONICAL='NON_CANONICAL'      # EX-16 (T22-A01): the row_status of a one-row result outside the canonical form; never a status
_REQUIRED=frozenset(('status','flags')+FIELDS)

def _canonical_shape(result):
    """EX-16 (T22-A01): True when the form of `result` is one that reference.canonical_result accepts apart from the values and
    the column lengths: exactly the keys n and models, n an int, a non-empty set of known model parts, each with every required
    column and only optional columns (reference.OPTIONAL_COLUMNS) besides, every column a list or tuple. Never raises."""
    if not isinstance(result,dict) or set(result)!={'n','models'} or type(result['n']) is not int:return False
    models=result['models']
    if not isinstance(models,dict) or not models or not set(models)<=set(MODELS5):return False
    for col in models.values():
        if not isinstance(col,dict) or not _REQUIRED<=set(col)<=_REQUIRED|set(ref_mod.OPTIONAL_COLUMNS):return False
        if any(not isinstance(v,(list,tuple)) for v in col.values()):return False
    return True

def _refused_rows(cols,n):
    """EX-16 (T22-A01): the indices below n of the rows that the canonical form refuses in a model part (the value rules of
    reference.canonical_result): a flag that is not an int, a field value that is not a number or is infinite, an engine_evals
    value that is not an int >= 0. A column of floats only (int flags only) is checked at C speed; only a column with another
    type, an infinity or a negative count is read row by row (reference._digest_float decides a field value)."""
    bad=set()
    for c in cols:
        flags=c['flags'][:n]
        if set(map(type,flags))-{int}:bad.update(i for i,v in enumerate(flags) if type(v) is not int)
        ev=c.get('engine_evals')
        if ev is not None:
            ev=ev[:n]
            if set(map(type,ev))-{int} or (ev and min(ev)<0):bad.update(i for i,v in enumerate(ev) if type(v) is not int or v<0)
        for f in FIELDS:
            col=c[f][:n]
            if set(map(type,col))<={float}:
                if math.inf in col or -math.inf in col:bad.update(i for i,v in enumerate(col) if v in (math.inf,-math.inf))
                continue
            for i,v in enumerate(col):
                try:ref_mod._digest_float(v)
                except REFUSED_ERRORS:bad.add(i)
    return bad

class OptionChainGreeks(NativeRows):
    """Amendment G4.2: `selector` ('all' or one model name, contract.selector_models) chooses the computed models; every
    variant, the reference and the validation use `self.models` only. 'baw': py-reference since G-BAW2 part A (Task 5);
    py-optimized and py-library since G-BAW2 part B (Task 6). EX-10: c-serial on the trial's route (NativeRows)."""
    def __init__(self,params,selector='all',request_limit=None):
        self.selector=selector;self.models=selector_models(selector)
        self.raw=dict(params);self.params=params_from_manifest({'parameters':{k:{'value':v} for k,v in self.raw.items()}})
        self.request_limit=request_limit                                  # G-ALO-CO: from benchlab.workload.construct_adapter
        self.bench_ref=('optionlab.adapter:OptionChainGreeks',self.raw,selector,request_limit)   # direct use; load_adapter overwrites it
        self.market=None                                                  # Amendment C: {'rate': r, 'q': {expiration: q_e}} after with_market
        self._native_init();self._takes={}                                # EX-10: no route until the trial sets one; the take() row cache
    def with_market(self,items):
        """A copy of this adapter that prices every row with the protocol market rate (optionlab.market.protocol_rate) and the q of
        its expiry (`items`: optionlab.market.table_json). The rate is not an argument (EX-6: no override). The copy has no C
        backend and no cached take() row of its own original."""
        from optionlab.market import table_from_json, protocol_rate
        out=copy.copy(self);out.bench_ref=self.bench_ref;out.market={'rate':protocol_rate()['continuous_rate'],'q':table_from_json(items)}
        out._native_init();out.route=self.route;out._takes={};return out
    def market_parameters(self,chain):
        """Amendment C inside the container, with the rate of the protocol constant (EX-6): the snapshot New York date and its
        expected SOFR effective date; when the protocol record matches, the per-expiry q table and the exercise bias. Returns
        {'public': market block, 'table': [[e, q], ...], 'rate': r, 'date_ok': bool}; on a date mismatch the table is empty and
        the block holds only the rate record. The aggregate schema of the protocol has no market block, so nothing writes 'public'."""
        from optionlab import market as mk
        day,other=mk.snapshot(chain);expected=mk.expected_effective(day);rec=mk.protocol_rate()
        info={**rec,'updated_other_date':other,'snapshot_date':day.isoformat()}
        r=rec['continuous_rate']
        if rec['effective_date']!=expected.isoformat():return {'public':mk.public({},{},info),'table':[],'rate':r,'date_ok':False}
        table=mk.estimate(chain,r);bias=mk.exercise_bias(chain,r,table,self.params)
        return {'public':mk.public(table,bias,info),'table':mk.table_json(table),'rate':r,'date_ok':True}
    def owner_chain_rates(self,chain):
        """The chain with the protocol market rate and the per-expiry q of an owner (not synthetic) dataset. ValueError
        `market_date_mismatch` when the protocol SOFR day is not the SOFR date of the chain snapshot; there is no fallback to the
        case assumptions and no run without a rate. The messages hold no record value."""
        from optionlab import market as mk
        day,_=mk.snapshot(chain);rec=mk.protocol_rate()
        if rec['effective_date']!=mk.expected_effective(day).isoformat():raise ValueError('market_date_mismatch: the protocol SOFR day is not the SOFR date of the dataset snapshot')
        r=rec['continuous_rate'];table={e:row['q'] for e,row in mk.estimate(chain,r).items()}
        return with_rates(chain,*rates(chain,market={'rate':r,'q':table}))
    def synthesize(self,n,seed):
        from optionlab.synthetic import generate
        return json.dumps(generate(n,seed,self.params)).encode()
    def load(self,dataset_ref):
        with open(dataset_ref['path'],'rb') as f:data=f.read(MAX_INPUT_BYTES+1)
        if hashlib.sha256(data).hexdigest()!=dataset_ref['sha256']:raise ValueError('dataset digest mismatch')
        chain,synthetic=decode_chain_origin(data);chain['synthetic']=synthetic        # the origin mark (panel_inputs takes a synthetic chain only)
        if self.market is not None:return with_rates(chain,*rates(chain,market=self.market))
        if synthetic:return with_rates(chain,self.params.rate,self.params.dividend_yield)     # labeled assumptions, synthetic data only
        return self.owner_chain_rates(chain)          # EX-6, T9-A04: any other dataset takes the protocol market rate or fails
    def slice(self,chain,n):return slice_chain(chain,n)
    def slice_result(self,result,n,chain):return {'n':n,'models':{m:{k:v[:n] for k,v in col.items()} for m,col in result['models'].items()}}
    def prepare(self,chain,variant,workers=1):
        if isinstance(variant,str) and variant.startswith('c-'):return self.native_prepare(chain,variant,workers)   # EX-10: c-serial only, on self.route
        if variant in ('py-reference','py-library'):return rows(chain)       # Task 9b: py-library takes the row tuples (per-row r, q)
        from optionlab import optimized
        return optimized.prepare(chain)
    def run(self,prepared,variant,workers,pool=None):      # the framework passes pool=; a single-threaded variant ignores it
        if isinstance(variant,str) and variant.startswith('c-'):return self.native_run(prepared,variant,workers)   # EX-10: warm or cold backend
        if variant=='py-reference':return ref_mod.run(prepared,self.params,models=self.models)
        if variant=='py-library':                                           # Task 9b: QuantLib-Python 1.43, C++ library through SWIG
            from optionlab import library
            return library.run(prepared,self.params,models=self.models)
        if variant!='py-optimized':raise ValueError('unknown variant')
        from optionlab import optimized
        return optimized.run(prepared,self.params,models=self.models)
    def materialize(self,raw):
        if isinstance(raw,dict) and 'records' in raw:return self.native_materialize(raw)     # EX-10: the raw C result of a backend
        if isinstance(next(iter(raw['models'].values()))['status'],list):return raw
        from optionlab import optimized
        return optimized.materialize(raw)
    def unpack_native(self,data):
        """Kernel hook: the reference.run shape of the kernel output file (290-byte records for the mask of this selector);
        ValueError for a length that is not whole records, or for a reserved content."""
        data=bytes(data)
        return nc.materialize(data,len(data)//nc.RECORD_OUT,self.native_mask())
    def native_reference_digest(self,reference):
        """Kernel hook: FNV-1a 64 of the ocg-v1 / ocg-v1m bytes of the selected reference models, as 16 lowercase hex digits.
        pl-kernel prints the same value of its own result as PLK1 digest= (specs/project/batch.md "Kernel digest"), so a kernel
        row is eligible only when its result has the reference bytes."""
        return nc.canonical_digest(self.selected(reference))
    def take(self,data,i):
        """Base Task 18 (G7.3): the one-row request of row i of the synthetic panel dataset (synthetic:large with the case seed).
        A row of the loaded chain when it is long enough; for a synthetic chain shorter than the row index, the same row from
        the prefix-stable generator (optionlab.synthetic.row), cached per index (ruling R44 item 3: the synthetic run dataset
        holds the largest planned tier only; T7 backlog). A chain that `load` did not mark synthetic, and a market-priced
        adapter, never get a generated row (ValueError). The cold C backend of the previous one-row call stops here, outside
        the call wall (optionlab.backends module text)."""
        self.native_retire_cold()
        if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<SIZES['large']:raise ValueError('take: a row index of the synthetic panel dataset is required')
        if i<data['n']:
            out={k:(v[i:i+1] if isinstance(v,list) else v) for k,v in data.items() if k!='provider'}
            out['provider']={k:v[i:i+1] for k,v in data['provider'].items()};out['n']=1;return out
        if self.market is not None or data.get('synthetic') is not True:raise ValueError('take: a generated row needs a synthetic chain (never a local or market-priced one)')
        got=self._takes.get(i)
        if got is None:
            from optionlab.synthetic import row
            seed=self.raw.get('seed')
            if isinstance(seed,bool) or not isinstance(seed,int):raise ValueError('take: a generated row needs the integer case seed')
            record=row(i,seed,self.params)
            chain,synthetic=decode_chain_origin(json.dumps({'s':'ok',**{k:[v] for k,v in record.items()}}).encode())
            if not synthetic:raise ValueError('take: the generated row is not labeled synthetic')
            chain['synthetic']=True
            got=self._takes[i]=with_rates(chain,self.params.rate,self.params.dividend_yield)
        return got
    def row_status(self,result):
        """Base Task 18 (H21.4): the status of a one-row result for the panel comparison: the first status other than OK of the
        selected models (MODELS5 order), else OK; ROW_COUNT for a result of another row count, MODEL_MISSING without a
        selected model. EX-16 (T23; T22-A01, ruling R72): NON_CANONICAL, a text outside STATUSES, for a result that
        reference.canonical_result refuses (an infinity, a flag that is not an int, a value that is not a number, a column
        outside the form), so such a panel row never has the reference status (before EX-14 the digest raised there). An
        unknown status text stays the status, as before."""
        if result.get('n')!=1:return 'ROW_COUNT'
        status='OK'
        for m in self.models:
            col=result['models'].get(m)
            if col is None:return 'MODEL_MISSING'
            if col['status'][0]!='OK':status=col['status'][0];break
        if status not in STATUSES:return status
        try:ref_mod.canonical_result(result)
        except REFUSED_ERRORS:return NON_CANONICAL
        return status
    def work_units(self,result):
        """The completed rows: a row counts when its status is one of STATUSES in every model part. EX-16 (T23; T22-A01, ruling
        R72): and when the canonical form (reference.canonical_result) accepts the row in every part (every flag an int, every
        field value a number that is not infinite); a result whose form the canonical form refuses (another top-level key, a
        model part with another key set, an unknown model) has no unit. Since EX-14 the digest is total, so this keeps a
        memory trial (benchlab.trial: work_units and the digest only) of such a result below its planned work (the host rule
        P07). Rows of a result whose columns end early are counted up to the shortest column, as before."""
        if not _canonical_shape(result):return 0
        cols=list(result['models'].values());n=min(len(c[k]) for c in cols for k in ('status','flags')+FIELDS)
        bad=_refused_rows(cols,n)
        return sum(1 for i in range(n) if i not in bad and all(c['status'][i] in STATUSES for c in cols))
    def reference(self,chain):return ref_mod.run(rows(chain),self.params,models=self.models)
    def reference_cover(self,chain,selectors):
        """R48 (T6-R6, rulings R48 and R51; task M2c): the optional framework hook (benchlab.workload). `selectors` is the sorted
        list of the selectors that a run, or a local job of more than one selector, plans; the coordinator calls the hook on the
        adapter of the reference selector. Returns one py-reference result of the union of the listed selectors' models
        (contract.selector_models; `all` gives bsm, bjs and crr) in MODELS5 order, computed as `reference` computes its own
        models. reference.run evaluates each (row, model) pair on its own, so `selected` of the adapter of each listed selector
        gives exactly what its `reference` gives: statuses, flags, the binary64 bits of every field and the columns outside the
        digest (T6R6-A01; tests test_per_model.ReferenceCoverTests and test_construction). The union need not hold this
        adapter's own models. ValueError for a value that is not a non-empty list of distinct, declared selector names."""
        if not isinstance(selectors,list) or not selectors or not all(isinstance(s,str) for s in selectors) or len(set(selectors))!=len(selectors):
            raise ValueError('reference_cover: a non-empty list of distinct selector names is required')
        covered=[selector_models(s) for s in selectors]             # ValueError for an unknown or pending selector
        return ref_mod.run(rows(chain),self.params,models=tuple(m for m in MODELS5 if any(m in c for c in covered)))
    def selected(self,reference):
        """The selector part of a reference (G4.2): the run reference may hold more models than this selector."""
        missing=[m for m in self.models if m not in reference['models']]
        if missing:raise ValueError('the reference lacks a selected model')
        return {'n':reference['n'],'models':{m:reference['models'][m] for m in self.models}}
    def _reference_models(self,reference):
        """R48 (task M2c, T6R6-A05): the models that a py-reference result holds, in MODELS5 order: the selected models of this
        adapter's own `reference`, or every covered model of a `reference_cover` result. ValueError for a result without a
        model or with a model name outside MODELS5."""
        held=reference['models']
        if not held or any(m not in MODELS5 for m in held):raise ValueError('the reference holds no model or an unknown model')
        return tuple(m for m in MODELS5 if m in held)
    def reference_counts(self,reference):
        """Amendment G3.7: total engine evaluations per model of a py-reference result ({model: int}). R48 (task M2c,
        T6R6-A05): the coordinator calls every count hook on the adapter of the reference selector with the reference that its
        job computed: its own `reference` (the selected models) or a `reference_cover` result. Each hook counts every model
        that the reference holds (_reference_models). A model's count depends only on the rows and the model, so the run's
        reference_evals gives each planned model its total (the py-reference guard of each unit reads it), and the blocks of
        local window jobs with different covers agree per key (reference_evals) and per selector (reference_admit_excluded)."""
        return {m:sum(reference['models'][m]['engine_evals']) for m in self._reference_models(reference)}
    def reference_exclusions(self,reference):
        """Amendment G2.3 (P3R2-04): {'row', 'brent', 'bump'} counts of the per-row `admit_reason` column of the models of a
        py-reference result (outside the digest; R48: every model that the reference holds, see reference_counts); None when no
        model has the column (no baw)."""
        cols=[reference['models'][m]['admit_reason'] for m in self._reference_models(reference) if 'admit_reason' in reference['models'][m]]
        if not cols:return None
        out={k:0 for k in ref_mod.ADMIT_REASONS}
        for col in cols:
            for v in col:
                if v is None:continue
                if v not in out:raise ValueError('admit_reason: unknown reason')
                out[v]+=1
        return out
    def reference_alo_counts(self,reference):
        """Amendment I8.3, H10: the ALO unit-report counts of a py-reference result (reference.alo_aggregate: equation rows
        {FP_A, FP_B}, stencil_switched, stencil_unresolved, alo_nan_guarded; outside the digest); None when the reference
        holds no `alo` (R48: every model that the reference holds, see reference_counts)."""
        if 'alo' not in self._reference_models(reference):return None
        return ref_mod.alo_aggregate({'n':reference['n'],'models':{'alo':reference['models']['alo']}})
    def reference_overhead(self,data):
        """Amendment G2.3 (P3R2-04): {'library_overhead_ns_per_row': median ns per row} of the shared S* transcription calls
        that py-library's BAW stencil side tests add (optionlab.library.sstar_overhead), on the first 256 rows of `data`.
        The framework passes the synthetic chain of the case seed (the generator is prefix-stable, so these are the first
        256 rows of the synthetic large chain), never the owner chain; it runs in the coordinator `reference` job, outside
        every timed interval. None when the selected models hold no `baw`."""
        if 'baw' not in self.models:return None
        from optionlab import library
        r=rows(data)
        if len(r)<library.OVERHEAD_ROWS:raise ValueError(f'reference_overhead needs the first {library.OVERHEAD_ROWS} rows of the synthetic chain; got {len(r)}')
        value=library.sstar_overhead(r,self.params)
        return None if value is None else {'library_overhead_ns_per_row':value}
    def panel_inputs(self,chain,workers,part=None):
        """Amendment G3.3, G3.7 (Task 7), I7.2 and H21 (Task A6): the panel candidate inputs of a synthetic chain for the five
        models, whatever the selector (optionlab.panel.inputs: py-reference status, flags and engine_evals, the 64-point
        grid test, side, K/S, T and x = ln(K/F) per row, the ocg-v1m reference digest with mask 31). The coordinator job
        `panel` calls it on the synthetic large chain only, outside every timed interval; `workers` spawned processes share
        the rows; `part` = (k, K) computes row part k of K (joined by panel_join). A chain that `load` did not mark synthetic (an owner
        chain, or a chain without the mark) is refused (T11T12-A04)."""
        if self.market is not None or chain.get('synthetic') is not True:raise ValueError('panel inputs are synthetic only (G3.3)')
        from optionlab import panel
        return panel.inputs(chain,self.params,workers,part=part)
    def panel_join(self,parts):
        """Task A6: the panel inputs of the K row parts of panel_inputs, joined in row order with the digest of the joined
        result (optionlab.panel.join)."""
        if self.market is not None:raise ValueError('panel inputs are synthetic only (G3.3)')
        from optionlab import panel
        return panel.join(parts)
    def validate(self,result,reference,chain):
        """The agreement verdict (optionlab.agreement.compare) with the project verdict counts under `counts` (FR5 item 2): the
        protocol `verdict_counts` names (multi_root, boundary_ambiguous, flat_vega), each {model: count}, are moved out of the top
        level of the verdict; the framework keys (eligible, failures, reduction, model_errors) and the other internal keys stay.
        EX-14 (B06; T22): a raw C answer (a dict with `records`, the form that run returns) is decoded first by the record rule of
        native_codec (native_materialize); an answer that the rule refuses is not eligible (failure `record`). A result that
        compare accepts but the canonical form (reference.canonical_result) refuses is not eligible (failure `canonical`): since
        EX-14 the digest is total, so the canonical form no longer ends the trial child, and this rule keeps every such result
        refused. Every other verdict is the verdict of compare, unchanged (an unknown status text is a status failure there)."""
        from optionlab.agreement import compare
        from optionlab import protocol
        names=protocol.protocol()['verdict_counts']
        try:result=self._decoded(result)
        except REFUSED_ERRORS:return {'eligible':False,'failures':{'record':1},'reduction':'NOT_RUN','model_errors':{},'counts':{k:{} for k in names}}
        v=compare(rows(chain),result,self.selected(reference),self.params)
        if v['eligible']:
            try:ref_mod.canonical_result(result)
            except REFUSED_ERRORS:v=dict(v,eligible=False,failures=dict(v['failures'],canonical=1))
        return {**{k:x for k,x in v.items() if k not in names},'counts':{k:v[k] for k in names}}
    def digest(self,result):
        """The canonical digest (reference.result_digest: SHA-256 of the ocg-v1 / ocg-v1m bytes) of a result, or of a raw C answer
        after the record rule (native_materialize). EX-14 (B06; T22): total. A value that the record rule or the canonical form
        refuses (an unknown status text, a model part with another column, a refused answer) gets refused_digest, which is never
        the digest of a canonical result; validate refuses every such value. Before EX-14 the canonical form raised ValueError
        here, and the generic mutation precision-change ('OK' becomes 'OJ') ended the agreement-controls job child (B06)."""
        try:return ref_mod.result_digest(self._decoded(result))
        except REFUSED_ERRORS:return refused_digest(result)
    def _decoded(self,result):
        """EX-14: a raw C answer (a dict with `records`) decoded by this adapter's record rule (native_materialize; ValueError or
        KeyError when the rule refuses it); any other value unchanged."""
        if isinstance(result,dict) and 'records' in result:return self.native_materialize(result)
        return result
    def agreement_mutation(self,name,result,data):
        """EX-14 (B06): the framework hook of the agreement-controls job for each protocol `agreement_mutations` entry: the mutated
        result of `result` (a C result of this adapter) on `data` (optionlab.agreement_controls), or None when the mutation does
        not apply. ValueError for a name that the module does not define."""
        from optionlab import agreement_controls
        return agreement_controls.mutate(self,name,result,data)
    def local_summary(self,chain,reference):
        """spec 12 aggregate block of a local run (Task 18; Amendment A): counts, quantiles over OK rows and whole-run digests
        only (L4), never a row value. `erf_saturated` is the per-model count of Amendment D item 3 (optionlab.reference).
        EX-20 item 4 (plan Task 31): a per-unit local run uses the selector of its unit; a single-model selector that the protocol
        units declare (protocol.unit_selectors) gives the same keys with that model only in every model block (the provider
        cross-check and the unit-scale check read the models of the reference). Any other single-model selector is refused
        before any work. T28 (ruling R84; ledger row EX20-LOCALSUMMARY-SCHEMA-01): the protected protocol aggregate schema
        lists the five models as optional properties, so the host accepts a single-model summary; the schema alone would also
        accept an `all` summary without one of bsm, bjs and crr, and `selected` refuses such a reference here (ValueError)."""
        from optionlab import protocol
        if self.selector!='all' and self.selector not in protocol.unit_selectors():
            raise ValueError('local_summary supports selector all and the single-model selectors of the protocol units only (Task 31)')
        from optionlab.contract import mid_differences
        from optionlab.crosscheck import provider_crosscheck, unit_scale
        from optionlab.agreement import compare
        from optionlab import optimized
        reference=self.selected(reference)
        r=rows(chain);res=optimized.materialize(optimized.run(optimized.prepare(chain),self.params,models=self.models));v=compare(r,res,reference,self.params)
        scale=unit_scale(chain,reference);cc=provider_crosscheck(chain,reference,{f:x['scale'] for f,x in scale.items() if x['scale']})
        # Controller ruling (Task 18 concern 2): a quantile over fewer than MIN_QUANTILE_ROWS rows is near-individual; keep
        # the count and emit null quantiles. The framework's accept_aggregate refuses a number there.
        cc={m:{f:(q if q['count']>=MIN_QUANTILE_ROWS else dict(q,median=None,p90=None)) for f,q in fields.items()} for m,fields in cc.items()}
        return {'rows':chain['n'],'status_counts':{m:{s.lower():reference['models'][m]['status'].count(s) for s in STATUSES} for m in reference['models']},   # EX-3: lower-case keys (summary grammar)
                'flag_counts':{'multi_root':sum(v['multi_root'].values()),'boundary_ambiguous':sum(v['boundary_ambiguous'].values()),'flat_vega':sum(v['flat_vega'].values()),
                               'provider_mid_differs':mid_differences(chain),
                               'below_intrinsic':sum(1 for m in reference['models'].values() for f in m['flags'] if f&ref_mod.FLAG_BELOW_INTRINSIC),
                               'erf_saturated':ref_mod.erf_saturated(r,reference,self.params)},
                'crosscheck':cc,'unit_scale':{f:{'scale':x['scale'],'rescaled':x['rescaled']} for f,x in scale.items()},
                'result_sha256':self.digest(res),'reference_sha256':self.digest(reference)}
