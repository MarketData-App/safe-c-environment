"""The option example's protocol data (task EX-3): the values that FR3 moved out of the framework policy
and fixture files into the protected protocol directory
benchmarks/project/protocol/. The framework reads protocol.json (bound by sha256 in bench.json); the example code reads
the same files here. oracle.json holds the option oracle, the calibration, the generator record, the ALO
Gauss-Legendre table and the dated market constants; protocol.json binds it by sha256, and `oracle()` refuses a file
whose digest differs from the binding."""
import hashlib, json
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[2]       # <project dir>/benchmarks/project (the case files live here too)
PROTOCOL_DIR=PROJECT/'protocol'
PROTOCOL_FILE=PROTOCOL_DIR/'protocol.json'
ORACLE_FILE=PROTOCOL_DIR/'oracle.json'
AGGREGATE_SCHEMA_FILE=PROTOCOL_DIR/'aggregate.schema.json'
APPROVAL_FILE=PROTOCOL_DIR/'approval.json'

def protocol():
    """The parsed protocol.json."""
    return json.loads(PROTOCOL_FILE.read_text())

def unit_selectors():
    """EX-20 item 4 (plan Task 31): the single-model selectors that the protocol units declare, the model part of each unit name
    ('bsm/full-dataset' -> 'bsm') of every decision policy, as a frozenset."""
    return frozenset(u.split('/',1)[0] for p in (protocol().get('decision_policies') or {}).values() for u in p.get('units') or [])

def tolerances():
    """The protocol `tolerances` (the shared fields and the `alo` and `baw` blocks)."""
    return protocol()['tolerances']

def solver():
    """The protocol `solver` constants."""
    return protocol()['solver']

def oracle():
    """The parsed oracle.json (keys oracle, calibration, generator, alo_gauss_legendre, market_constants). ValueError when
    its sha256 differs from the digest that protocol.json binds."""
    raw=ORACLE_FILE.read_bytes();bound=protocol()['oracle']['sha256']
    if hashlib.sha256(raw).hexdigest()!=bound:raise ValueError('oracle.json differs from the digest that protocol.json binds')
    return json.loads(raw)

def sofr():
    """The dated SOFR constant of the protocol (market_constants.sofr in oracle.json): day, percent, rate, source, url, note."""
    return oracle()['market_constants']['sofr']
