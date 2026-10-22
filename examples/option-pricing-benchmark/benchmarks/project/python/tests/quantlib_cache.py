"""Task DD (DD2; finding P3-T15-CHILD-BUDGET-01, ruling D1-R2(c)): one shared QuantLib comparison per test process. The
heavy unit tests keep every assertion and read the parts of checks.quantlib_evidence from here instead of recomputing
them in each module. An entry is keyed exactly like the saved copy of DD1 (checks.quantlib_binding: the fixture content,
every case parameter, the optionlab source and the QuantLib version), so a test with an edited fixture or parameter gets
its own computation. A test that patches a part function or a function the parts call (a defect or fault injection) must
call the part function directly, never this cache. Not a test module: unit_groups list only tests/test_*.py."""
import copy, json
from optionlab import checks

_DOCS={}

def doc(fx,params,parts=checks.QL_EVIDENCE_PARTS):
    """The live cache entry for (fx, params) with `parts` computed. Callers must not mutate it; quantlib_agreement_item
    only reads the parts it finds and adds the missing ones."""
    key=json.dumps(checks.quantlib_binding(fx,params),sort_keys=True)
    return checks.quantlib_evidence(fx,params,parts,_DOCS.setdefault(key,{}))

def part(fx,params,name):
    """A private copy of one part (lattice, baw_alignment, baw_record_grid, baw_edge_rows or alo)."""
    return copy.deepcopy(doc(fx,params,(name,))[name])

def place(session_dir,fx,params):
    """Write the complete comparison as b06-prerequisite-oracle saves it, where the framework restores it for the later
    checks of the session (<session_dir>/shared/<producer>/<file>); quantlib-alignment then runs with output directory
    <session_dir>/out. Returns that output directory."""
    from pathlib import Path
    shared=Path(session_dir)/'shared'/checks.QL_EVIDENCE_PRODUCER;shared.mkdir(parents=True,exist_ok=True)
    checks.write_quantlib_evidence(shared,fx,params,doc(fx,params))
    out=Path(session_dir)/'out';out.mkdir(parents=True,exist_ok=True)
    return out
