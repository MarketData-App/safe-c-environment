"""Tolerance calibration from recorded spreads (`./tools/safety bench tolerance`). Host-side, stdlib and framework tools only.

A project check records, per tolerance field and per variant, the largest absolute spread against the reference and the
sample count, and per field the oracle error bound, in a spread file (schemas/bench-tolerance-spread.json). The current
values come from the project protocol `tolerances` (schemas/bench-protocol.json). The framework names no field and no
variant: a field is the dotted protocol path of a number in `tolerances` (`abs`, `<block>.abs`, `<block>.<group>.<name>`),
a variant is a name of the spread file.

Calibration rule, per field: `measured` is the largest spread over every variant. `proposed` is the current value when
measured < current < oracle_error. For a field of an approved locked selector block the rule is measured < current:
the oracle bound is not checked, so margin_high can be 1 or less. Otherwise proposed is None with a reason. The tool never
proposes a wider value and never writes the protocol: a project locks the values through its protected protocol with an
approval reference (`lock_record`, FR3: `state: locked-<label>` and `approval`; the bare state `locked` is refused).
margin_low = proposed / measured (None for a zero spread), margin_high = oracle_error / proposed (None when not finite).

Every input is project-controlled: the spread file passes the capped boundary (evidence.load_project_json: size cap,
strict UTF-8, depth cap, no duplicate key, no NaN or infinity) and the checks here; every malformed input raises GateError
(exit 2), never another Python exception."""
from __future__ import annotations
import copy, hashlib, math, re
from pathlib import Path
from evidence import GateError, PROJECT_JSON_MAX_BYTES, atomic_json, load_project_json, read_capped

SPREAD_MAX_BYTES=PROJECT_JSON_MAX_BYTES       # 4 MiB
MAX_FIELDS=256          # fields of one spread file and of one proposal
MAX_VARIANTS=32         # variants of one field
MAX_SAMPLES=2**53       # samples of one variant of one field: an exact double integer, so a count is never rounded
KEY=re.compile(r'^[a-z][a-z0-9_-]{0,40}$')                                  # bench-protocol.json $defs/key
FIELD=re.compile(r'^[a-z][a-z0-9_-]{0,40}(\.[a-z][a-z0-9_-]{0,40}){0,2}$')  # at most three protocol levels
LABEL=re.compile(r'^[a-z0-9][a-z0-9-]{0,38}$')                              # the <name> of locked-<name>
REFERENCE=re.compile(r'^[A-Za-z0-9._/-]{8,160}$')                           # bench-protocol.json tolerance approval
STATE=re.compile(r'^(provisional|locked)-[a-z0-9][a-z0-9-]{0,38}$')        # bench-protocol.json $defs/tolerance state
DOUBLE_MAX_INT=int(1.7976931348623157e308)

class ToleranceError(GateError, ValueError):
    """A malformed tolerance input or a refused lock: GateError (exit 2) and ValueError."""

def _number(v):
    """True for an int (not bool) within the double range or a finite float. Never raises."""
    if isinstance(v,bool):return False
    if isinstance(v,int):return -DOUBLE_MAX_INT<=v<=DOUBLE_MAX_INT
    return isinstance(v,float) and math.isfinite(v)

def _nonneg(v,what):
    if not _number(v) or v<0:raise ToleranceError(f'{what} must be a finite number >= 0')
    return v

def _field(name,what='field'):
    if not isinstance(name,str) or not FIELD.fullmatch(name):raise ToleranceError(f'{what} name breaks the field grammar')
    return name

def _mapping(value,what,limit):
    if not isinstance(value,dict):raise ToleranceError(f'{what} must be an object')
    if len(value)>limit:raise ToleranceError(f'{what} holds more than {limit} entries')
    return value

def _locked_block(name,block):
    """True when the selector block `block` holds a lock: `state` locked-<name> with a valid approval reference. A state
    outside provisional-<name> or locked-<name>, or a locked state without a valid approval reference, is refused
    (EX15-TOPLOCK-01, ruling EX15-R2: no unapproved state can skip the oracle bound check)."""
    if 'state' not in block:return False
    state=block['state']
    if not isinstance(state,str) or not STATE.fullmatch(state):
        raise ToleranceError(f'tolerances.{name}.state breaks the provisional-<name> or locked-<name> grammar')
    if not state.startswith('locked-'):return False
    ref=block.get('approval')
    if not isinstance(ref,str) or not REFERENCE.fullmatch(ref):
        raise ToleranceError(f'tolerances.{name} is locked without a valid approval reference')
    return True

def current_fields(tolerances):
    """(current, locked) of a protocol `tolerances` object: {dotted path: number} of every number at most three levels
    deep, and the set of paths inside a selector block whose lock is approved (_locked_block). A lock exists only inside
    a selector block: a top-level state that starts with `locked` is refused, and so is a lock below a selector block.
    Strings (state, approval) are no fields; a block approval that is not a string is refused, as the schema does.
    ToleranceError on the first failure."""
    _mapping(tolerances,'tolerances',MAX_FIELDS)
    top=tolerances.get('state')
    if isinstance(top,str) and top.startswith('locked'):
        raise ToleranceError('a top-level locked state is refused: a lock exists only inside a selector block with an approval reference')
    current={};locked=set()
    def key_of(key):
        if not isinstance(key,str) or not KEY.fullmatch(key):raise ToleranceError('tolerances key breaks the key grammar')
        return key
    def add(path,value,is_locked):
        current[path]=value
        if is_locked:locked.add(path)
        if len(current)>MAX_FIELDS:raise ToleranceError(f'tolerances hold more than {MAX_FIELDS} fields')
    for key,value in tolerances.items():
        key_of(key)
        if _number(value):add(key,value,False)
        elif isinstance(value,dict):
            is_locked=_locked_block(key,value)
            if 'approval' in value and not isinstance(value['approval'],str):     # EX15-LOCKREC-01, as the schema
                raise ToleranceError(f'tolerances.{key}.approval is not a string: an approval is a reference, never a field')
            for k,v in value.items():
                key_of(k)
                if _number(v):add(f'{key}.{k}',v,is_locked)
                elif isinstance(v,dict):
                    for g,x in v.items():
                        key_of(g)
                        if not _number(x):raise ToleranceError(f'tolerances.{key}.{k} holds a value that is not a number')
                        add(f'{key}.{k}.{g}',x,is_locked)
                elif not isinstance(v,str):raise ToleranceError('tolerances value is not a number, string or object')
        elif not isinstance(value,str):raise ToleranceError('tolerances value is not a number, string or object')
    return current,locked

def check_spread(doc):
    """The checks of a spread file that the schema states, repeated here so that a direct caller gets the same refusal
    (ToleranceError on the first failure). Returns the document."""
    _mapping(doc,'spread file',3)
    if set(doc)-{'schema_version','fields','source'} or doc.get('schema_version')!=1 or type(doc.get('schema_version')) is not int:
        raise ToleranceError('spread file needs schema_version 1 and fields only')
    fields=_mapping(doc.get('fields'),'spread fields',MAX_FIELDS)
    if not fields:raise ToleranceError('spread file holds no field')
    if 'source' in doc and (not isinstance(doc['source'],str) or not REFERENCE.fullmatch(doc['source'])):
        raise ToleranceError('spread source breaks the reference grammar')
    for name,entry in fields.items():
        _field(name)
        _mapping(entry,'spread field',2)
        if set(entry)!={'oracle_error','variants'}:raise ToleranceError('spread field needs oracle_error and variants only')
        _nonneg(entry['oracle_error'],'oracle_error')
        variants=_mapping(entry['variants'],'spread variants',MAX_VARIANTS)
        if not variants:raise ToleranceError('spread field holds no variant')
        for variant,row in variants.items():
            if not isinstance(variant,str) or not KEY.fullmatch(variant):raise ToleranceError('variant name breaks the key grammar')
            _mapping(row,'spread variant',2)
            if set(row)!={'max_abs','samples'}:raise ToleranceError('spread variant needs max_abs and samples only')
            _nonneg(row['max_abs'],'max_abs')
            n=row['samples']
            if type(n) is not int or not 1<=n<=MAX_SAMPLES:raise ToleranceError(f'samples must be an integer in 1..{MAX_SAMPLES}')
    return doc

def _measured(name,value):
    """(largest spread, its variant or None) of one spread entry: a number, or {variant: number}."""
    if isinstance(value,dict):
        _mapping(value,'spread variants',MAX_VARIANTS)
        if not value:raise ToleranceError('spread field holds no variant')
        best=None
        for variant,v in value.items():
            if not isinstance(variant,str) or not KEY.fullmatch(variant):raise ToleranceError('variant name breaks the key grammar')
            _nonneg(v,f'spread of {name}')
            if best is None or v>best[0]:best=(v,variant)
        return best
    return _nonneg(value,f'spread of {name}'),None

def _ratio(a,b):
    if b==0:return None
    try:r=a/b
    except (OverflowError,ZeroDivisionError):return None
    return r if math.isfinite(r) else None

def propose(spread,oracle,current=None,locked=()):
    """The proposal per field (see the module text). `spread`: {field: largest spread, or {variant: largest spread}};
    `oracle`: {field: oracle error bound}; `current`: {field: present value} (the protocol's); `locked`: fields an earlier
    approver lock fixed. Fields: the union of the three maps, at most MAX_FIELDS. ToleranceError on malformed input."""
    if current is None:current={}           # EX15-PROPOSE-DEFAULT-01: propose(spread, oracle) has no current value
    for value,what in ((spread,'spread'),(oracle,'oracle'),(current,'current values')):_mapping(value,what,MAX_FIELDS)
    if isinstance(locked,(str,bytes)) or not isinstance(locked,(set,frozenset,list,tuple)):raise ToleranceError('locked must be a set of field names')
    locked={_field(f,'locked field') for f in locked}
    names=set(spread)|set(oracle)|set(current)
    if len(names)>MAX_FIELDS:raise ToleranceError(f'more than {MAX_FIELDS} fields')
    for name in names:_field(name)
    for name,v in oracle.items():_nonneg(v,f'oracle error bound of {name}')
    for name,v in current.items():
        if not _number(v):raise ToleranceError(f'current value of {name} must be a finite number')
    out={}
    for name in sorted(names):
        measured,worst=_measured(name,spread[name]) if name in spread else (None,None)
        bound=oracle.get(name);value=current.get(name);is_locked=name in locked
        row={'measured':measured,'worst_variant':worst,'oracle_error':bound,'current':value,'locked':is_locked,
             'proposed':None,'reason':None,'margin_low':None,'margin_high':None}
        if value is None:row['reason']='no current value in the protocol tolerances'
        elif measured is None:row['reason']='no recorded spread'
        elif bound is None:row['reason']='no oracle error bound'
        elif not measured<value:
            row['reason']=('spread reaches the locked value: the lock stays and a new value needs an approval' if is_locked
                           else 'spread reaches the current value: a wider value is never proposed automatically')
        elif not is_locked and not value<bound:row['reason']='current value reaches the oracle error bound'
        else:
            row['proposed']=value;row['margin_low']=_ratio(value,measured);row['margin_high']=_ratio(bound,value)
        out[name]=row
    return out

def calibrate(doc,tolerances):
    """The proposal record of a checked spread file `doc` against a protocol `tolerances` object: every field of either,
    `status` PASS only when every field has a proposed value, `unproposed` the sorted fields without one. The approved
    locked selector blocks of `tolerances` (current_fields) are the only source of a lock: a caller cannot add one, so no
    field skips the oracle bound check without an approval reference (EX15-CALLOCK-01)."""
    check_spread(doc)
    current,proto_locked=current_fields(tolerances)
    fields=doc['fields']
    spread={n:{v:r['max_abs'] for v,r in e['variants'].items()} for n,e in fields.items()}
    oracle={n:e['oracle_error'] for n,e in fields.items()}
    out=propose(spread,oracle,current=current,locked=set(proto_locked))
    for name,row in out.items():
        row['samples']=sum(r['samples'] for r in fields[name]['variants'].values()) if name in fields else 0
    unproposed=sorted(n for n,r in out.items() if r['proposed'] is None)
    return {'schema_version':1,'status':'PASS' if out and not unproposed else 'FAIL','unproposed':unproposed,'fields':out}

def lock_record(proposal,verdict_reference,tolerances=None,label='calibrated'):
    """The protocol `tolerances` object that locks the proposed values: a copy of `tolerances` (or {}) with each proposed
    value set, and `state: locked-<label>` plus `approval: <verdict_reference>` on every selector block that holds a
    proposed field. `proposal`: {field: {'proposed': value}} or a calibrate record. ValueError (ToleranceError) when
    the reference or label breaks its grammar, a field is a top-level field (EX15-TOPLOCK-01: a lock exists only inside
    a selector block), a field has no proposed value, a value is wider than the current one, a field is not a field of
    `tolerances`, or a locked block keeps a field without a proposed value. EX15-LOCKREC-01: the record never drops a
    proposed value, so a field `<block>.state` or `<block>.approval` (or below a group of that name), a field that is a
    path prefix of another field, and a non-string block approval in `tolerances` (current_fields) are refused too."""
    if not isinstance(verdict_reference,str) or not REFERENCE.fullmatch(verdict_reference):
        raise ToleranceError('lock record needs an approval reference (8 to 160 characters of A-Z a-z 0-9 . _ / -)')
    if not isinstance(label,str) or not LABEL.fullmatch(label):raise ToleranceError('lock label breaks the locked-<name> grammar')
    if isinstance(proposal,dict) and isinstance(proposal.get('fields'),dict) and proposal.get('schema_version')==1:proposal=proposal['fields']
    _mapping(proposal,'proposal',MAX_FIELDS)
    if not proposal:raise ToleranceError('proposal holds no field')
    values={}
    for name,row in proposal.items():
        _field(name)
        v=row.get('proposed') if isinstance(row,dict) else None
        if not _number(v):raise ToleranceError(f'field {name} has no proposed value: it cannot be locked')
        values[name]=v
    top=sorted(n for n in values if '.' not in n)
    if top:raise ToleranceError(f'field {top[0]} is a top-level field: a lock exists only inside a selector block; '
                                'move the value into a selector block of the protocol tolerances')
    reserved=sorted(n for n in values if n.split('.')[1] in ('state','approval'))     # EX15-LOCKREC-01: never overwritten
    if reserved:raise ToleranceError(f'field {reserved[0]} names the block state or approval, which the lock record writes')
    prefix=sorted(n for n in values if any(m.startswith(n+'.') for m in values))
    if prefix:raise ToleranceError(f'field {prefix[0]} is a path prefix of another proposed field')
    base=copy.deepcopy(tolerances) if tolerances is not None else {}
    current,_=current_fields(base) if tolerances is not None else ({},set())
    if tolerances is not None:
        for name,v in values.items():
            if name not in current:raise ToleranceError(f'field {name} is not a field of the protocol tolerances')
            if v>current[name]:raise ToleranceError(f'field {name}: the proposed value is wider than the current value')
    blocks={name.split('.')[0] for name in values}
    for block in blocks:
        kept=[n for n in current if n.split('.')[0]==block and '.' in n and n not in values]
        if kept:raise ToleranceError(f'a locked block keeps a field without a proposed value: {kept[0]}')
    for name,v in values.items():
        parts=name.split('.');node=base
        for p in parts[:-1]:
            nxt=node.get(p)
            if nxt is None:nxt=node[p]={}
            if not isinstance(nxt,dict):raise ToleranceError(f'field {name} crosses a value that is not an object')
            node=nxt
        node[parts[-1]]=v
    for block in blocks:
        node=base[block]
        node['state']='locked-'+label;node['approval']=verdict_reference
    return base

# ---- the CLI: ./tools/safety bench tolerance --spread PATH [--project DIR] [--approval REF] [--label NAME] ----

def _reference(value):
    import argparse
    if len(value)>200:raise argparse.ArgumentTypeError('--approval: at most 200 characters')
    return value

def read_spread(root,path):
    """(document, sha256) of a spread file: a regular file (no symbolic link), relative paths from the root, at most
    SPREAD_MAX_BYTES, through the capped boundary, the schema and check_spread. GateError otherwise."""
    from schema_check import validate
    p=Path(path)
    if not p.is_absolute():p=Path(root)/p
    if p.is_symlink():raise ToleranceError('spread file must not be a symbolic link')
    if not p.is_file():raise ToleranceError('spread file is missing or not a regular file')
    try:data=read_capped(p,SPREAD_MAX_BYTES,'tolerance-spread','spread file')
    except OSError as exc:raise ToleranceError(f'spread file is unreadable ({type(exc).__name__})') from None
    def check(value):
        validate(root,'bench-tolerance-spread',value);check_spread(value)
    doc=load_project_json(data,'tolerance-spread',SPREAD_MAX_BYTES,label='spread file',check=check)
    return doc,hashlib.sha256(data).hexdigest()

def tolerance_cmd(root,args):
    """Writes artifacts/bench/<run>/tolerance-proposal.json (and, with --approval and a PASS proposal, tolerance-lock.json:
    the lock record, checked against the protocol grammar). Never edits the protocol. Exit 0 PASS, 1 FAIL (a field has no
    proposed value), 2 BLOCKED (malformed input)."""
    import bench, bench_model as bm
    from schema_check import validate
    if args.approval is not None and not REFERENCE.fullmatch(args.approval):raise ToleranceError('--approval breaks the approval reference grammar')
    if not LABEL.fullmatch(args.label or ''):raise ToleranceError('--label breaks the locked-<name> grammar')
    project=bench.project_arg(root,args)
    if project is None:raise ToleranceError('bench tolerance needs --project (the protocol holds the current tolerances)')
    proto=bm.load_protocol(root,project)
    if proto is None:raise ToleranceError('the project has no protocol: no tolerances to calibrate')
    tolerances=proto.get('tolerances') or {}
    doc,digest=read_spread(root,args.spread)
    record=calibrate(doc,tolerances)
    record.update(project=project,protocol_sha256=bm.protocol_digest(root,project),spread_sha256=digest,
                  source=doc.get('source'))
    validate(root,'bench-tolerance-proposal',record)
    run_dir=bench.new_run_dir(root,'tolerance');path=run_dir/'tolerance-proposal.json';atomic_json(path,record)
    result={'status':record['status'],'run_id':run_dir.name,'proposal':str(path),'fields':len(record['fields']),
            'unproposed':record['unproposed'][:20]}
    if args.approval is not None and record['status']=='PASS':
        lock=lock_record(record,args.approval,tolerances=tolerances,label=args.label)
        validate(root,'bench-protocol',dict(proto,tolerances=lock))
        lock_path=run_dir/'tolerance-lock.json';atomic_json(lock_path,lock);result['lock']=str(lock_path)
    text=(f"bench tolerance: {record['status']} {len(record['fields'])-len(record['unproposed'])}/{len(record['fields'])} fields proposed; "
          f'proposal {path}')
    bench.emit(args,result,text)
    return bench.EXIT[record['status']]

def register(handlers,arguments):
    """Adds `tolerance` to the bench HANDLERS and ARGUMENTS tables (once)."""
    if 'tolerance' in handlers:raise ValueError('bench operation tolerance is already registered')
    handlers['tolerance']=tolerance_cmd
    arguments['tolerance']=[('--spread',{'required':True}),('--project',{}),('--approval',{'type':_reference,'default':None}),
                            ('--label',{'default':'calibrated'})]
