"""FR3 (FS1 F5, F6; FR2-03): the framework holds no option-pricer data or logic and no owner-specific values.

A project brings its models, oracle, tolerances, planning shares, decision policies, required checks, stubs, panel models
and local aggregate schema in its protected protocol file (tests/unit/test_bench_protocol_file.py). This module checks
that the framework files no longer hold them: the protected policy and fixtures keep only framework values, the option
tools and the market-rate fetch are gone, and a word scan of the framework code and data finds no option model name,
market-rate source, owner policy name or internal branch name outside the listed residue (each entry names its reason)."""
import json, re, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))

PATTERNS={'model':re.compile(r'(?<![A-Za-z0-9])(bsm|bjs|crr|baw|alo)(?![A-Za-z0-9])|(?<![A-Za-z0-9])(?<!G-)(BSM|BJS|CRR|BAW|ALO)(?![A-Za-z0-9])'),   # FR3-03: also crr_steps
          'market':re.compile(r'(?i)\bsofr\b|newyorkfed|market-rate|market_params'),
          'owner-policy':re.compile(r'owner-request-200ms'),
          'option-case':re.compile(r'option[-_]chain|optionlab|ocg-v1m'),
          'internal-branch':re.compile(r'perf-lab|fw-release|fw-license'),       # FR3-14: also the framework release branch names
          'option-fields':re.compile(r"vega|k_over_s|t_years|t_days|(?<![A-Za-z0-9_])dte(?![A-Za-z0-9])|(?<![A-Za-z0-9_])(?:itm|atm|otm)-(?:put|call)"
                                     r"|(?<!op['\"]:)['\"](?:put|call)['\"]"),   # FR3-13: verdict and panel contract fields, cell names
          'quantlib':re.compile(r'(?i)quantlib'),
          'option-words':re.compile(r'(?i)bjerksund|black-scholes|barone-adesi|\bgreeks?\b|openinterest|\bimplied[- ]vol|moneyness|\bstrike\b'
                                    r'|newton[- ]iv|(?<![A-Za-z0-9])iv(?![A-Za-z0-9])'),      # FR3-11: the IV field and label
          'example-prefix':re.compile(r'(?<![A-Za-z0-9])(?:lib)?pl[-_][a-z]'),    # N4-A09: the option example's name prefix (pl-kernel, pl_inproc)
          'example-tool':re.compile(r'(?i)pricer|pricing'),       # FINAL-06, FR5B-05: the example's own name for its library
          # FR5A-01, FR5A-02 (ruling FR5-R3): the example's panel and grid field words, the side key and option model names
          'option-panel':re.compile(r"K/S|T_target|(?i:real side)|(?i:volatility)|sigma_(?:hi|lo)(?![A-Za-z0-9])"
                                    r"|(?<!op['\"]:)['\"]side['\"]"),
          'option-models':re.compile(r'(?i)(?<![A-Za-z0-9])(?:cev|heston|sabr|bachelier|black-?76|garman|kohlhagen|merton)(?![A-Za-z0-9])'),
          'chain-control':re.compile(r'(?i)chain[-_ ]?scan'),     # FR5A-04: the old name of the record-scan control
          'old-unit-kinds':re.compile(r'(?i)full[-_ ]chain|one[-_ ]contract|panel_contracts'),    # ruling FR5-R4: the old unit kinds and field
          # FR5B-01 to FR5B-06 (ruling FR5-R6): standalone cell words, the unit of work and the dataset in the example's words,
          # the example's domain history text, a stale CLI attribute and a price-quote probe text
          'option-standalone':re.compile(r'(?i)(?<![A-Za-z0-9])(?:itm|otm|atm)(?![A-Za-z0-9])'),
          'contract-domain':re.compile(r"contract_wall|contracts_per_call|seconds_per_contract|max_input_contracts|PANEL_CONTRACT|['\"]contracts['\"]"
                                       r"|(?i:panel contracts?|per[- ]contract|worst[- _]contract|effective contract|six (?:panel |planned )?contracts|x contracts)"),
          'chain-dataset':re.compile(r'(?i)/data/chain|(?<![A-Za-z])chain\.json|synthetic (?:large )?chain|large[- ]chain|per (?:large )?chain|joined chain'
                                     r'|local[: ]chain|secret[-_ ]chain|owner[-_ ]chain|fixture[-_]chain|chain data|(?<![A-Za-z0-9_])chain(?:=|\[)|[\'"]chain[\'"]'),
          'example-history':re.compile(r'(?i)options?[\-_\s]+(?:example|case[\-_\s]+run|case|manifest|cell|column|run)s?'
                                        r'|(?-i:[Oo]ptions?(?:Example|Case|Manifest|Cell|Column|Run)s?)|quote[- ]like|quote \d|synthetic quote|market=None|\bD30\b|\d+-day row'),   # FR5C-02: also the hyphen forms; FR5D-01: the column form; FR5E-01, FR5E-02: underscore, any white space, the run forms; FR5F-03: the plural and the camel-case join
          'example-hook':re.compile(r'with_market')}      # FR5C-01: the example's former data-hook method name
# Residue that stays, with its reason (FR3 report, section "Residue"; fix round 1, FR3-05). FR5 removed every FR5 row: the
# framework mechanisms take their domain names from the project protocol (bench_panel, the verdict counts) or use neutral
# names (the record-scan control, the library export tests, the fixtures and the ledger).
LICENSE_TEXT='permanent: license text, roman numeral (iv), not option data'     # FINAL-09: upstream license text never changes
NEG='negative input of a test that proves the framework refuses the example name; it must name the example'
RESIDUE={
    'tests/unit/test_bench_acquisition.py':{'quantlib':NEG},       # proves the removed wheels are gone
    'benchmarks/performance/python/tests/test_wheel_set.py':{'quantlib':NEG},
    'third_party/developer/notices/libglib2.0-0t64/copyright':{'option-words':LICENSE_TEXT},
    'third_party/foundation-notices/glib-CC-BY-SA-3.0.txt':{'option-words':LICENSE_TEXT},
    'third_party/foundation-notices/glib-CC0-1.0.txt':{'option-words':LICENSE_TEXT},
    'third_party/originals/trailofbits/skills/LICENSE':{'option-words':LICENSE_TEXT},
    'tools/bench_b18.py':{'option-case':'runtime-image exclusion pattern for dataset file names; removing it would weaken B18 (AGENTS.md)'},
    'tests/unit/test_bench_cli.py':{'option-case':NEG},
    'tests/unit/test_bench_project.py':{'option-case':NEG},
    'tests/unit/test_bench_framework_imports.py':{'option-case':NEG,'option-words':NEG,'example-tool':NEG},   # FR5B-05: the example directory name
    'tests/unit/test_bench_construction.py':{'example-hook':NEG},        # FR5C-01: the guard refuses the former exempt method name
    'benchmarks/performance/python/tests/test_workload.py':{'example-hook':NEG},   # FR5C-01: the loader never calls the former hook
    'tests/unit/test_framework_ledger.py':{'internal-branch':NEG,'model':NEG},
}
EXPORT='starter-export.json'      # FR3-03: the scan covers every exported (pushed) file, this module excepted

def scanned_files():
    out=[]
    for rel in json.loads((ROOT/EXPORT).read_text())['files']:
        p=ROOT/rel
        if rel==Path(__file__).relative_to(ROOT).as_posix() or not p.is_file() or p.is_symlink():continue
        if b'\0' in p.read_bytes()[:8192]:continue          # a binary archive (container/foundation-inputs): no text to scan
        out.append(p)
    return sorted(out)

def scan_hits(rel,text):
    """The whole-tree scan of one file: each hit as 'rel:line: pattern', outside the residue rows of rel. FR5F-01: the
    pattern runs over the whole file text, so a match that crosses a line break is a hit at its start line; the line
    hits of each line stay in the result too."""
    found=[];allowed=RESIDUE.get(rel,{})
    for name,rx in PATTERNS.items():
        if name in allowed:continue
        lines={text.count('\n',0,m.start())+1 for m in rx.finditer(text)}
        if not lines:continue           # no whole-text match: no line can match either
        lines|={n for n,line in enumerate(text.split('\n'),1) if rx.search(line)}
        found+=[f'{rel}:{n}: {name}' for n in sorted(lines)]
    return found

class FrameworkNeutralTests(unittest.TestCase):
    def test_the_policy_keeps_only_framework_values(self):
        pol=json.loads((ROOT/'safety/performance-policy.json').read_text())
        for key in ('tolerances','solver','before_run_required'):self.assertNotIn(key,pol)
        for key in ('estimate_share_per_selector','share_required'):self.assertNotIn(key,pol['budgets'])
        self.assertEqual(sorted(pol['decision_policies']),['demo-cpu-40','demo-latency-2x','owner'])
        self.assertNotIn('oracle_part',pol['job_deadlines'])

    def test_the_fixtures_keep_only_framework_values(self):
        fx=json.loads((ROOT/'safety/performance-fixtures.json').read_text())
        for key in ('oracle','generator','calibration','alo_gauss_legendre'):self.assertNotIn(key,fx)
        self.assertEqual(sorted(fx),['b_cases','decision_cases','pipeline_subcases','schema_version'])

    def test_the_option_tools_and_the_market_fetch_are_gone(self):
        for rel in ('tools/bench_oracle.py','tools/bench_market.py','schemas/bench-market-params.json','tests/unit/test_bench_market.py'):
            with self.subTest(path=rel):self.assertFalse((ROOT/rel).exists())
        import bench
        self.assertNotIn('market-rate',bench.HANDLERS)

    def test_the_protected_schemas_take_project_values(self):
        agg=json.loads((ROOT/'schemas/bench-local-aggregate.json').read_text())
        self.assertNotIn('enum',agg['properties']['case']);self.assertIn('summary',agg['properties'])
        panel=json.loads((ROOT/'schemas/bench-panel-reference.json').read_text())
        self.assertNotIn('const',panel['properties']['models'])
        dec=json.loads((ROOT/'schemas/bench-decision.json').read_text())
        self.assertNotIn('enum',dec['properties']['policy']['properties']['name'])

    def test_no_framework_file_holds_option_or_owner_words_outside_the_residue(self):
        found=[]
        for p in scanned_files():
            rel=p.relative_to(ROOT).as_posix();found+=scan_hits(rel,p.read_text(errors='replace'))
        self.assertEqual(found[:40],[])
    def test_the_whole_tree_routine_reports_a_hit_across_a_line_break(self):
        """FR5F-01: the whole-tree routine reports a match that crosses a line break, at its start line; a residue row
        still exempts its file; text without a match gives no hit."""
        rel='docs/scan-fixture.md'
        self.assertEqual(scan_hits(rel,'one option\ncolumns here\n'),[f'{rel}:1: example-history'])
        self.assertEqual(scan_hits(rel,'first line\nthe option\n   cells follow\n'),[f'{rel}:2: example-history'])
        self.assertEqual(scan_hits(rel,'a\nb\nthe options\r\ncolumn list\n'),[f'{rel}:3: example-history'])
        self.assertEqual(scan_hits(rel,'one option\ncolumns\nand one option_run\n'),
                         [f'{rel}:1: example-history',f'{rel}:3: example-history'])
        self.assertEqual(scan_hits(rel,'a line hit: option_case\n'),[f'{rel}:1: example-history'])
        self.assertEqual(scan_hits('tests/unit/test_bench_cli.py','an option_chain\n'),[])
        for text in ('a CLI option\nthe column count\n','an option.\nColumns follow\n','an option flag\n\ncolumn\n','',
                     'column\noptions\n','optional\ncolumn\n'):
            with self.subTest(text=text):self.assertEqual(scan_hits(rel,text),[])

    def test_the_scan_covers_every_exported_text_file(self):
        """FR3-03: tests/unit (data and test files), docs, third_party and every other exported path are scanned."""
        rels={p.relative_to(ROOT).as_posix() for p in scanned_files()}
        for rel in ('tests/unit/data/bench-plan-case.json','tests/unit/data/bench-plan-case.opportunity.json','tests/unit/test_bench_units.py',
                    'docs/agent-development-quickstart.md','third_party/NOTICE.md','safety/framework-ledger.json'):
            with self.subTest(path=rel):self.assertIn(rel,rels)
        self.assertGreater(len(rels),600)
    def test_every_residue_entry_names_its_reason_phase_and_owner(self):
        """FR3-05: each residue item is a negative input, the B18 exclusion or permanent upstream license text. FR5 (ruling
        FR5-R1 item 6): no row waits for a later phase; FINAL-09: no stale phase label stays."""
        for rel,names in RESIDUE.items():
            for name,reason in names.items():
                with self.subTest(path=rel,pattern=name):
                    self.assertTrue(reason==NEG or 'B18' in reason or reason==LICENSE_TEXT,reason)
                    self.assertNotIn('phase FR',reason)
        self.assertEqual(sorted(rel for rel,names in RESIDUE.items() if LICENSE_TEXT in names.values()),
                         sorted(rel for rel in RESIDUE if rel.startswith('third_party/')))
    def test_the_scan_finds_the_panel_words_model_names_and_the_old_control_name(self):
        """FR5A-01, FR5A-02, FR5A-04: the scan fails on each of these words; generic words with the same letters pass."""
        for name,texts in (('option-panel',('K/S 1.1','T_target','the real side','implied volatility',"'sigma_hi':5.0",'sigma_lo',
                                            "{'side':'put'}",'"side": 1')),
                           ('option-models',('cev','CEV model','Heston','sabr','Bachelier','black76','Black-76','Garman','Merton')),
                           ('chain-control',('chain-scan','benchlab.chainscan','ChainScan','chain_scan'))):
            for text in texts:
                with self.subTest(pattern=name,text=text):self.assertTrue(PATTERNS[name].search(text))
        for text in ('sigma_log','sigma','the host side','library side test','k/s','t_target','T_t','record-scan','RecordScan','chain',
                     'cevian','merton2','sides',"{'op':'side'}",'scan'):
            with self.subTest(text=text):
                self.assertFalse(any(PATTERNS[n].search(text) for n in ('option-panel','option-models','chain-control')))
    def test_the_scan_finds_the_old_unit_kinds(self):
        """Ruling FR5-R4: the old unit kind names and their field fail the scan; the neutral names pass."""
        for text in ('m3/full-chain','m3/one-contract','full_chain_group','ONE_CONTRACT_BASE_SECONDS','panel_contracts','a full chain','one contract'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['old-unit-kinds'].search(text))
        for text in ('m3/full-dataset','m3/single-record','panel_records','contract','chain','full dataset','single record'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['old-unit-kinds'].search(text))
    def test_the_schemas_take_only_the_neutral_unit_kinds(self):
        """Ruling FR5-R4: every framework schema that names a unit kind or a point refuses the old names."""
        from schema_check import validate
        from evidence import GateError
        import copy
        sys.path.insert(0,str(ROOT/'tools'));import bench_model as bm
        proto=bm.load_protocol(ROOT,'tests/fixtures/bench-project');pol=next(iter(proto['decision_policies']))
        self.assertTrue(all(u.endswith(('/full-dataset','/single-record')) for u in proto['decision_policies'][pol]['units']))
        for old,new in (('m1/full-chain','m1/full-dataset'),('m1/one-contract','m1/single-record')):
            p=copy.deepcopy(proto);p['decision_policies'][pol]['units']=[new];self.assertTrue(validate(ROOT,'bench-protocol',p))
            p['decision_policies'][pol]['units']=[old]
            with self.subTest(old=old),self.assertRaises(GateError):validate(ROOT,'bench-protocol',p)
        for rel in ('schemas/bench-decision.json','schemas/bench-fixtures.json','schemas/bench-policy.json','schemas/bench-local-aggregate.json',
                    'schemas/bench-protocol.json'):
            with self.subTest(schema=rel):self.assertNotRegex((ROOT/rel).read_text(),PATTERNS['old-unit-kinds'])
        fx=json.loads((ROOT/'safety/performance-fixtures.json').read_text())
        self.assertTrue(validate(ROOT,'bench-fixtures',fx))
        bad=json.loads(json.dumps(fx).replace('/full-dataset"','/full-chain"',1))
        self.assertNotEqual(bad,fx)
        with self.assertRaises(GateError):validate(ROOT,'bench-fixtures',bad)
    def test_the_scan_finds_the_example_tool_name(self):
        """FINAL-06: the example's name for its library is outside the framework; generic words with other letters pass."""
        for text in ('the option pricer','pricer-free','Pricer'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-tool'].search(text))
        for text in ('example pricing library','Pricing'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-tool'].search(text))
        for text in ('price','priced','precise','prime'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['example-tool'].search(text))
    def test_the_scan_finds_the_round_2_words(self):
        """FR5B-01 to FR5B-06 (ruling FR5-R6): each pattern finds its domain forms; the generic words pass."""
        for name,texts in (('option-standalone',('ITM put','otm','both ATM cells','atm-x')),
                           ('contract-domain',('contract_wall','contracts_per_call','estimate_seconds_per_contract','max_input_contracts',
                                               "'contracts':{}",'panel contract','per contract','per-contract','worst contract','worst_contract',
                                               'effective contract count','the six panel contracts','loops x contracts','PANEL_CONTRACT_BYTES')),
                           ('chain-dataset',('/data/chain.json','synthetic large chain','the synthetic chain','one large-chain call','per chain',
                                             'saving >= 100 ms per chain','joined chain','local:chain','secret-chain.json','owner chain',
                                             'fixture-chain.json','chain data.json','chain=adapter.load(x)',"st['chain']",'x(chain[0])')),
                           ('example-history',('option example','the option case','option manifests','quote 412.35','quote-like value',
                                               'market=None','D30','the 30-day row','the option-example form','fixed option cells',
                                               "'synthetic quote '+v")),('example-hook',('def with_market(self):','a.with_market(r,i)'))):
            for text in texts:
                with self.subTest(pattern=name,text=text):self.assertTrue(PATTERNS[name].search(text),text)
        for text in ('item','atmosphere','bottom','API contract','safety/contract.json','-ffp-contract=off','foundation API contracts',
                     'specs/foundation-contract.md','window chain','exception chain','image layer chains','the gate chain','records',
                     'record_wall','a command-line option','the quote character','MarketData-App','market=1','30 days','whole-day window',
                     'toolchain.json','blockchain','quoted string','the quote character','shell quote rules','a CLI option',
                     'cell rule','with_rate'):
            with self.subTest(text=text):
                self.assertFalse(any(PATTERNS[n].search(text) for n in ('option-standalone','contract-domain','chain-dataset','example-history','example-hook')),text)
    def test_the_scan_finds_the_column_form(self):
        """FR5D-01: example-history finds "option column(s)" in each form; the generic uses of the two words pass."""
        for text in ('the eight option columns','one option column','an option-column list','Option Columns','the options column'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-history'].search(text),text)
        for text in ('a CLI option','the column count','an option flag','one column per option','optional column',
                     'column options','the input columns','option: column','check_column'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['example-history'].search(text),text)
    def test_the_scan_finds_the_underscore_line_break_and_run_forms(self):
        """FR5E-01, FR5E-02: example-history joins its two words by a hyphen, an underscore or any white space (a line wrap
        too), and finds the run forms; the generic uses of the words pass."""
        for text in ('option_columns','option\ncolumns','local_option_run','option case run','the option_case','option\n  cells',
                     'the options column'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-history'].search(text),text)
        for text in ('a CLI option','the column count','an option flag','one column per option','optional column',
                     'column options','the input columns','option: column','check_column','a run option','the --x option, run',
                     'option flag'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['example-history'].search(text),text)
    def test_the_scan_finds_the_plural_and_camel_case_forms(self):
        """FR5F-03: example-history finds the plural first word and the ASCII camel-case join with a capital letter; the
        generic plural and the other words with the same letters pass."""
        for text in ('options column','the options columns','options_run','local_options_case','options-manifest','options\ncells',
                     'optionRun','optionColumns','OptionCase','optionsCell','optionManifest','optionExample','optionCaseRun'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-history'].search(text),text)
        for text in ('CLI options','options flag','optional','column options','the options, run','optionally run','optionFlag',
                     'optionsParser','Options: case-sensitive','options.cells'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['example-history'].search(text),text)
    def test_the_unit_gate_has_the_build_profile_deadline(self):
        """The unit gate runs every unit test in one build-profile command; its deadline is the build profile wall, not
        the 30 s default of the runner (the suite needs about 28 s, so the default left no margin)."""
        import cli
        build=json.loads((ROOT/'safety/container-policy.json').read_text())['profiles']['build']['wall_seconds']
        self.assertEqual(cli.UNIT_GATE_SECONDS,build)
        self.assertIn("timeout=UNIT_GATE_SECONDS,label='python-unit-tests'",(ROOT/'tools/cli.py').read_text())
    def test_the_record_and_dataset_names_are_the_framework_names(self):
        """Ruling FR5-R6, FR5B-04: the schemas refuse the old unit-of-work fields; the bench file mount is /data/dataset.json;
        the example planning constants are no framework module."""
        from schema_check import validate
        from evidence import GateError
        import copy, container_policy, bench_model as bm
        self.assertEqual(container_policy.BENCH_FILE_TARGET,'/data/dataset.json')
        self.assertFalse((ROOT/'tools/bench_budget.py').exists());self.assertFalse((ROOT/'tests/unit/test_bench_budget.py').exists())
        pol=json.loads((ROOT/'safety/performance-policy.json').read_text());self.assertTrue(validate(ROOT,'bench-policy',pol))
        text=json.dumps(pol)
        for new,old in (('estimate_seconds_per_record','estimate_seconds_per_contract'),('max_input_records','max_input_contracts')):
            with self.subTest(field=new):
                self.assertIn(new,text);bad=json.loads(text.replace(new,old))
                with self.assertRaises(GateError):validate(ROOT,'bench-policy',bad)
        fx=json.loads((ROOT/'safety/performance-fixtures.json').read_text());t=json.dumps(fx);self.assertIn('"record_wall"',t)
        with self.assertRaises(GateError):validate(ROOT,'bench-fixtures',json.loads(t.replace('"record_wall"','"contract_wall"')))
        opp=bm.read_json(ROOT/'tests/fixtures/bench-project/benchmarks/project/cases/fixture-case.opportunity.json')
        self.assertTrue(validate(ROOT,'bench-opportunity',opp));t=json.dumps(opp);self.assertIn('records_per_call',t)
        with self.assertRaises(GateError):validate(ROOT,'bench-opportunity',json.loads(t.replace('records_per_call','contracts_per_call')))
    def test_the_scan_finds_each_option_word_of_the_verdicts(self):
        """FR3-11: the scan fails on each option word that the FR3 verdicts found (the IV field and the Newton IV label)."""
        for text in ('{"name": "Newton IV", "state": "proposed"}',"'failures':{'m1.iv':2}","d['per_model']['m1']['iv']=[0.2]",
                     'IV from mid, then price','newton-iv','implied vol','five greeks','Bjerksund-Stensland 2002','CRR(100)','crr_steps'):
            with self.subTest(text=text):self.assertTrue(any(rx.search(text) for rx in PATTERNS.values()))
        for text in ('ivory','divide','give','interval','NIV','m1.f1'):
            with self.subTest(text=text):self.assertFalse(any(rx.search(text) for rx in PATTERNS.values()))
    def test_the_scan_finds_each_field_and_branch_name_of_verdict_r2(self):
        """FR3-13, FR3-14: the scan fails on the verdict and panel contract fields, the cell names and the internal branch
        names; generic words with the same letters pass."""
        for text in ("'flat_vega':{'m3':3}","\"side\":{\"enum\":[\"put\",\"call\"]}","{'side':'put'}","'k_over_s':1.1","'t_years':0.08",
                     "'t_days':30.0","'dte_min':7","dte window","'itm-put-30d'","atm-call","otm-put","branch fw-release at",
                     "fw-license","perf-lab-t3fix2"):
            with self.subTest(text=text):self.assertTrue(any(rx.search(text) for rx in PATTERNS.values()))
        for text in ("{'op':'call','trial':1}","update","mkdtemp","puts the row","callable(f)","framework release"):
            with self.subTest(text=text):self.assertFalse(any(rx.search(text) for rx in PATTERNS.values()))
    def test_the_scan_finds_the_example_prefix(self):
        """N4-A09: the option example's name prefix is option-specific, so the scan finds it; generic words with the same
        letters pass."""
        for text in ('/memfd:pl-in (deleted)','pl-kernel','pl-worker binary','libpl_inproc.so','pl_inproc_price','src/pl_batch.c'):
            with self.subTest(text=text):self.assertTrue(PATTERNS['example-prefix'].search(text))
        for text in ('/memfd:bd-in (deleted)','apply-x','sample_rate','tmpl-a','pl','PL-x','opl_x','pl-1','impl_ok','replace'):
            with self.subTest(text=text):self.assertFalse(PATTERNS['example-prefix'].search(text))
    def test_every_residue_entry_is_still_needed(self):
        for rel,names in RESIDUE.items():
            text=(ROOT/rel).read_text(errors='replace')
            for name in names:
                with self.subTest(path=rel,pattern=name):self.assertRegex(text,PATTERNS[name])

if __name__=='__main__':unittest.main()
