"""Host-side bench data loading and rules. Reads JSON only; never imports benchmarks/ code."""
from __future__ import annotations
from pathlib import Path
import copy, hashlib, math, os, re, sys
from evidence import GateError, file_hash, read_json, load_project_json, PROJECT_JSON_MAX_BYTES
from schema_check import validate

VARIANTS=('py-reference','py-optimized','py-library','py-threads','py-processes','c-serial','c-threads')
POOL_VARIANTS=('py-threads','py-processes','c-threads')
CASES='benchmarks/performance/cases'
# plan L7: sys.stdlib_module_names of the bench container interpreter (Debian CPython 3.13.5), '_' names included.
# The container test test_stdlib_list_matches_the_image keeps this literal equal to the image's list.
STDLIB_313=frozenset({
    '__future__', '_abc', '_aix_support', '_android_support', '_apple_support', '_ast', '_asyncio', '_bisect', '_blake2', '_bz2', '_codecs',
    '_codecs_cn', '_codecs_hk', '_codecs_iso2022', '_codecs_jp', '_codecs_kr', '_codecs_tw', '_collections', '_collections_abc', '_colorize',
    '_compat_pickle', '_compression', '_contextvars', '_csv', '_ctypes', '_curses', '_curses_panel', '_datetime', '_dbm', '_decimal', '_elementtree',
    '_frozen_importlib', '_frozen_importlib_external', '_functools', '_gdbm', '_hashlib', '_heapq', '_imp', '_interpchannels', '_interpqueues',
    '_interpreters', '_io', '_ios_support', '_json', '_locale', '_lsprof', '_lzma', '_markupbase', '_md5', '_multibytecodec', '_multiprocessing',
    '_opcode', '_opcode_metadata', '_operator', '_osx_support', '_overlapped', '_pickle', '_posixshmem', '_posixsubprocess', '_py_abc', '_pydatetime',
    '_pydecimal', '_pyio', '_pylong', '_pyrepl', '_queue', '_random', '_scproxy', '_sha1', '_sha2', '_sha3', '_signal', '_sitebuiltins', '_socket',
    '_sqlite3', '_sre', '_ssl', '_stat', '_statistics', '_string', '_strptime', '_struct', '_suggestions', '_symtable', '_sysconfig', '_thread',
    '_threading_local', '_tkinter', '_tokenize', '_tracemalloc', '_typing', '_uuid', '_warnings', '_weakref', '_weakrefset', '_winapi', '_wmi',
    '_zoneinfo', 'abc', 'antigravity', 'argparse', 'array', 'ast', 'asyncio', 'atexit', 'base64', 'bdb', 'binascii', 'bisect', 'builtins', 'bz2',
    'cProfile', 'calendar', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys', 'compileall', 'concurrent', 'configparser',
    'contextlib', 'contextvars', 'copy', 'copyreg', 'csv', 'ctypes', 'curses', 'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
    'doctest', 'email', 'encodings', 'ensurepip', 'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'fractions', 'ftplib',
    'functools', 'gc', 'genericpath', 'getopt', 'getpass', 'gettext', 'glob', 'graphlib', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http',
    'idlelib', 'imaplib', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword', 'linecache', 'locale', 'logging', 'lzma',
    'mailbox', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder', 'msvcrt', 'multiprocessing', 'netrc', 'nt', 'ntpath', 'nturl2path', 'numbers',
    'opcode', 'operator', 'optparse', 'os', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pkgutil', 'platform', 'plistlib', 'poplib', 'posix',
    'posixpath', 'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc', 'pydoc_data', 'pyexpat', 'queue', 'quopri', 'random',
    're', 'readline', 'reprlib', 'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex', 'shutil', 'signal',
    'site', 'smtplib', 'socket', 'socketserver', 'sqlite3', 'sre_compile', 'sre_constants', 'sre_parse', 'ssl', 'stat', 'statistics', 'string',
    'stringprep', 'struct', 'subprocess', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny', 'tarfile', 'tempfile', 'termios', 'textwrap', 'this',
    'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize', 'tomllib', 'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo',
    'types', 'typing', 'unicodedata', 'unittest', 'urllib', 'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser', 'winreg', 'winsound',
    'wsgiref', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib', 'zoneinfo'
})
# Top-level modules of the pinned bench wheels (/opt/bench-python; the container test checks it covers them) and the framework package.
WHEEL_MODULES=frozenset({'numpy', 'pyperf', 'psutil'})
# Interpreter startup hooks: site imports them from any path entry before any framework code (review fix).
STARTUP_HOOKS=frozenset({'sitecustomize', 'usercustomize'})
# Top-level packages of /src/benchmarks/performance/python (the container test checks it covers them).
FRAMEWORK_PACKAGES=frozenset({'benchlab', 'tests'})
RESERVED_MODULES=STDLIB_313|WHEEL_MODULES|STARTUP_HOOKS|FRAMEWORK_PACKAGES
# One path rule for --project on the host and in the coordinator (container/bench-coordinator.py PROJECT_RE).
PROJECT_RE=re.compile(r'^(\.|[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*)$')
IDENTITY_FILES=4096;IDENTITY_BYTES=67108864
PROJECT_AREA='benchmarks/project'

# FR3 (FS1 F5, design Task 32): the per-project protected protocol file. The framework policy holds only framework values;
# a project brings its own protected data in <project>/benchmarks/project/protocol/protocol.json (schemas/bench-protocol.json).
PROTOCOL_DIR='protocol';PROTOCOL_FILE='protocol/protocol.json';PROTOCOL_MAX_BYTES=4194304;PROTOCOL_DATA_MAX_BYTES=16777216
PROJECT_KEYS=('tolerances','budgets','before_run_required','panel_cells')      # the policy keys that load_policy takes from the project protocol
PANEL_CELLS=6           # G7.3: a pass is six one-row requests (the L rule, the deadline inputs and the byte bounds); FR5: the protocol names the six cells
PANEL_RESERVED=frozenset({'n','models','mask','digest_form','reference_sha256','grid','per_model','counts',
                          'part','start','stop','n_total','dataset_sha256'})     # keys of the panel inputs and parts; never a row column

def _framework_policy(root):
    value=read_json(Path(root)/'safety/performance-policy.json');validate(root,'bench-policy',value)
    if value['pools']['request_limit']!=value['protocol']['max_request_records']:      # Amendment E item 2 (verdict L1)
        raise GateError('policy pools.request_limit differs from protocol.max_request_records')
    return value

def load_policy(root,project_dir=None):
    """The validated framework policy (safety/performance-policy.json) plus the project values of the protocol of
    `project_dir` (PROJECT_KEYS): `tolerances` (the protocol's, else {}), budgets.estimate_share_per_selector and
    budgets.share_required (the protocol's, else {} and []), `before_run_required` (the protocol's, else {}) and
    `panel_cells` (FR5: the cell names of the protocol's panel cell rule, else []). The
    framework file names no model, tolerance, share or required check; without a project every one of them is empty."""
    value=_framework_policy(root)
    proto=load_protocol(root,project_dir) if project_dir is not None else None
    proto=proto or {}
    value['tolerances']=copy.deepcopy(proto.get('tolerances',{}))
    budgets=proto.get('budgets',{})
    value['budgets']=dict(value['budgets'],estimate_share_per_selector=dict(budgets.get('estimate_share_per_selector',{})),
                          share_required=list(budgets.get('share_required',[])))
    value['before_run_required']=copy.deepcopy(proto.get('before_run_required',{}))
    value['panel_cells']=[c['name'] for c in ((proto.get('panel') or {}).get('cell_rule') or {}).get('cells',[])]   # FR5: [] without a cell rule
    return value

def load_fixtures(root):
    value=read_json(Path(root)/'safety/performance-fixtures.json');validate(root,'bench-fixtures',value);return value

DECISION_POLICIES=('owner','demo-latency-2x','demo-cpu-40')     # the framework rule policies; unit-threshold policies are project data

def load_decision_policy(root,name,project_dir=None):
    """A framework rule policy by name, or (with `project_dir`) a unit-threshold policy of the project's protocol. The
    returned copy names where it comes from: `origin` framework or project, `sha256` of the file that holds it (the
    framework policy or the protocol file) and, for a project policy, `protocol_approved` (the protocol's approval state)
    and the protocol's `library_report`."""
    if name in DECISION_POLICIES:
        pols=_framework_policy(root).get('decision_policies') or {}
        if name not in pols:raise GateError('unknown decision policy')
        return dict(copy.deepcopy(pols[name]),name=name,origin='framework',sha256=file_hash(Path(root)/'safety/performance-policy.json'))
    proto=load_protocol(root,project_dir) if project_dir is not None else None
    pols=(proto or {}).get('decision_policies') or {}
    if name not in pols:raise GateError('unknown decision policy')
    return dict(copy.deepcopy(pols[name]),name=name,origin='project',sha256=protocol_digest(root,project_dir),
                protocol_approved=proto['approval']['state']=='APPROVED',library_report=copy.deepcopy(proto.get('library_report')))

def engine_unit_policy(root):
    """FR3: the synthetic engine test unit-threshold policy of the protected fixtures (decision_cases.unit_policy, selectors
    m1..m5), for B14, P15 verdict-from-cold-row and the unit tests. Never a policy of a real decision."""
    pol=load_fixtures(root)['decision_cases']['unit_policy']
    return dict(copy.deepcopy(pol),origin='framework',sha256=file_hash(Path(root)/'safety/performance-fixtures.json'))

def unit_policy_names(root,project_dir):
    """The unit-threshold decision policy names of the project's protocol ([] without a project or protocol)."""
    return sorted((protocol_value(root,project_dir,'decision_policies',{}) or {}).keys())

def policy_filled(policy):
    if policy.get('kind')=='unit-threshold':
        return (policy.get('state')=='approved' and isinstance(policy.get('threshold_ns_per_request'),int)
                and (policy.get('origin')!='project' or policy.get('protocol_approved') is True))
    return policy.get('state')!='owner-must-fill' and all(policy.get(k) not in (None,[],'') for k in ('metric','relative_threshold','modes','points'))

def protocol_path(root,project_dir):
    """The protocol file path of a project (it may be absent)."""
    return _project_base(root,project_dir)/PROTOCOL_FILE

def _read_bound(root,project_dir,path,sha,what,limit):
    """The bytes of a protocol file: a regular file inside the project (no link on the way), at most `limit` bytes, whose
    sha256 is `sha`. GateError otherwise ('edited' when only the digest differs)."""
    if path.is_symlink() or path.parent.is_symlink():raise GateError(f'{what} must not be a symbolic link')
    _inside(root,project_dir,path)
    if not path.is_file():raise GateError(f'{what} is missing')
    with open(path,'rb') as f:data=f.read(limit+1)          # FR3-17: never more than one byte past the limit
    if len(data)>limit:raise GateError(f'{what} exceeds {limit} bytes')
    if hashlib.sha256(data).hexdigest()!=sha:raise GateError(f'{what} was edited: its sha256 differs from the bound digest')
    return data

def load_protocol(root,project_dir):
    """The validated protocol of a project, or None for no project or a project without a protocol (bench.json has no
    `protocol` binding and no protocol file exists). project_bench checks the binding (the sha256 in bench.json); this
    function validates the file against schemas/bench-protocol.json, requires its cases to be cases of bench.json, its
    models to cover its named selectors and every referenced file (oracle, aggregate_schema) to match its sha256."""
    if project_dir is None:return None
    decl=project_bench(root,project_dir)
    bind=decl.get('protocol')
    if bind is None:return None
    path=protocol_path(root,project_dir)
    raw=_read_bound(root,project_dir,path,bind['sha256'],'protocol file',PROTOCOL_MAX_BYTES)
    # FR3-17: the one boundary (evidence.load_project_json); every check of the parsed protocol runs inside it
    return load_project_json(raw,'protocol',PROTOCOL_MAX_BYTES,label='protocol file',
                             check=lambda value:_check_protocol(root,project_dir,decl,path,raw,value))

def _check_summary_schema(schema):
    if summary_schema_problems(schema):raise GateError('protocol aggregate schema breaks the framework schema grammar (FR3-10)')

def _check_protocol(root,project_dir,decl,path,raw,value):
    """The checks of load_protocol on the parsed protocol `value` (GateError on the first failure)."""
    validate(root,'bench-protocol',value)
    if value['approval']['state']=='APPROVED':_approval_record(root,project_dir,hashlib.sha256(raw).hexdigest(),value['approval']['reference'])
    unknown=sorted(set(value['cases'])-set(decl['cases']))
    if unknown:raise GateError('protocol cases are not cases of bench.json: '+', '.join(unknown))
    named=sorted(set(value.get('before_run_required',{}))-set(value['cases']))
    if named:raise GateError('protocol before_run_required names cases outside the protocol: '+', '.join(named))
    outside=sorted(n for n,p in (value.get('decision_policies') or {}).items() if p.get('case') not in value['cases'])
    if outside:raise GateError('protocol decision policies name a case outside the protocol: '+', '.join(outside))   # FR3-08
    models=set(value.get('models',[]))
    used=set((value.get('panel') or {}).get('models',[]))|set((value.get('library_report') or {}).get('selectors',[]))
    used|=set((value.get('budgets') or {}).get('estimate_share_per_selector',{}))|set((value.get('budgets') or {}).get('share_required',[]))
    if used-models:raise GateError('protocol names selectors outside its models: '+', '.join(sorted(used-models)))
    rule=(value.get('panel') or {}).get('cell_rule')
    if rule is not None:_check_cell_rule(rule)
    checks={c['name'] for c in decl.get('checks',[])}
    bad=sorted({s['check'] for s in value.get('stubs',[])}-checks)
    if bad:raise GateError('protocol stubs name checks that bench.json does not declare: '+', '.join(bad))
    if len({s['reason'] for s in value.get('stubs',[])})!=len(value.get('stubs',[])):raise GateError('protocol stubs repeat a reason')
    for key in ('oracle','aggregate_schema'):
        ref=value.get(key)
        if ref is None:continue
        data=_read_bound(root,project_dir,path.parent/ref['file'],ref['sha256'],f'protocol {key} file',PROTOCOL_DATA_MAX_BYTES)
        if key=='aggregate_schema':
            load_project_json(data,'aggregate-schema',PROTOCOL_DATA_MAX_BYTES,label='protocol aggregate schema file',check=_check_summary_schema)
    return value

def _check_cell_rule(rule):
    """FR5 (ruling FR5-R1 item 1): the cross-field rules of a panel cell rule that the schema cannot state. The category,
    position and scale columns are three different columns; no row column is a reserved key of the panel inputs; the
    report names are unique; the cell names are unique; each cell names a category label of the rule; the level ratios
    increase; an abs_le band has a bound >= 0. GateError on the first failure."""
    roles=[rule['category']['column'],rule['position'],rule['scale']]
    if len(set(roles))!=3:raise GateError('protocol panel cell rule: the category, position and scale columns must differ')
    columns=set(roles)|{r['column'] for r in rule['report']}
    if columns&PANEL_RESERVED:raise GateError('protocol panel cell rule names a reserved panel input key: '+', '.join(sorted(columns&PANEL_RESERVED)))
    if len(columns)>8:raise GateError('protocol panel cell rule names more than 8 row columns')
    names=[r['name'] for r in rule['report']]
    if len(set(names))!=len(names):raise GateError('protocol panel cell rule repeats a report name')
    cells=[c['name'] for c in rule['cells']]
    if len(set(cells))!=len(cells) or len(cells)!=PANEL_CELLS:raise GateError(f'protocol panel cell rule needs {PANEL_CELLS} cells with different names')
    unknown=sorted({c['category'] for c in rule['cells']}-set(rule['category']['labels']))
    if unknown:raise GateError('protocol panel cells name a category outside the rule labels: '+', '.join(unknown))
    if len(set(rule['category']['labels'].values()))!=len(rule['category']['labels']):raise GateError('protocol panel category labels share a value')
    lo,hi=rule['level_ratios']
    if not lo<hi:raise GateError('protocol panel level ratios must increase')
    if any(c['band']['op']=='abs_le' and c['band']['bound']<0 for c in rule['cells']):raise GateError('protocol panel abs_le band needs a bound >= 0')

PROTOCOL_APPROVAL_FILE='protocol/approval.json';PROTOCOL_APPROVAL_MAX_BYTES=4096

def _approval_record(root,project_dir,digest,reference):
    """FR3-04 (ruling FR3-R2): an APPROVED protocol needs its approval record (PROTOCOL_APPROVAL_FILE, a regular file inside
    the project, schemas/bench-protocol-approval.json) that names the sha256 of the protocol file bytes and the protocol's
    approval reference. The project's own APPROVED state is never enough: a missing, linked, malformed, other-digest or
    other-reference record raises GateError, so every plan, run, check and decide of the project is BLOCKED (exit 2).
    Tamper-evident, not tamper-proof: the record is unsigned; review of the protected protocol directory is the control."""
    path=protocol_path(root,project_dir).parent/'approval.json'
    if path.is_symlink():raise GateError('protocol approval record must not be a symbolic link')
    _inside(root,project_dir,path)
    if not path.is_file():raise GateError('protocol approval record is missing for an APPROVED protocol')
    def check(rec):
        try:validate(root,'bench-protocol-approval',rec)
        except GateError:raise GateError('protocol approval record has an invalid shape') from None
        if rec['protocol_sha256']!=digest:raise GateError('protocol approval record names another protocol digest: the protocol changed after its approval')
        if rec['reference']!=reference:raise GateError('protocol approval record names another approval reference')
    return load_project_json(path,'protocol-approval',PROTOCOL_APPROVAL_MAX_BYTES,label='protocol approval record',check=check)   # FR3-17

# FR3-01 / FR3-10 (ruling FR3-R4): the framework privacy vocabulary of a local aggregate summary (bench_privacy uses it).
SUMMARY_LABELS=frozenset({'VALID','INVALID_EXPERIMENT','BLOCKED','PASS','FAIL','warm','cold','direct','kernel','caller',
                          'tiny','small','medium','large'})      # the only strings a summary may hold: framework labels
SUMMARY_KEY=re.compile(r'^[a-z][a-z0-9_]{0,31}$')
SUMMARY_MAX_DEPTH=8;SUMMARY_MAX_ITEMS=256;SUMMARY_MAX_NODES=16384
_NUMBER_KEYS=frozenset({'minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf'})
# FR3-16: a numeric value of the grammar (and of a summary) is finite and representable as an IEEE-754 double. A float
# must be finite; an int must lie in -DOUBLE_MAX_INT..DOUBLE_MAX_INT (int(DBL_MAX), exact bound included). The int test is
# an exact int comparison with no float conversion, so a huge int (10**400) never raises OverflowError; bool is no number.
DOUBLE_MAX_INT=int(sys.float_info.max)

def finite_number(v):
    """True only for an int (not bool) within +-DOUBLE_MAX_INT or a finite float; False for every other value. Never raises."""
    if isinstance(v,bool):return False
    if isinstance(v,int):return -DOUBLE_MAX_INT<=v<=DOUBLE_MAX_INT
    if isinstance(v,float):return math.isfinite(v)
    return False

def summary_schema_problems(schema):
    """FR3-10 (ruling FR3-R4): the allowlist grammar of a project aggregate schema. [] when every node follows it:
    - every node is a non-empty object with an explicit `type` (a description is allowed; the root may name $schema);
    - a leaf is number or integer (with numeric minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf; each a
      finite_number, so finite and representable as an IEEE-754 double, and multipleOf above 0),
      boolean, either of these with null (type [t, "null"]), or a string with a non-empty `enum` of SUMMARY_LABELS;
    - an object has `additionalProperties: false`, explicit `properties` whose names match SUMMARY_KEY, and an optional
      `required` list of those names;
    - an array has an `items` node and a `maxItems` of 1..SUMMARY_MAX_ITEMS (and an optional `minItems` up to it);
    - the root is an object; the depth is at most SUMMARY_MAX_DEPTH.
    Every other keyword ($ref, $defs, oneOf, anyOf, allOf, not, if/then/else, const, patternProperties, propertyNames,
    dependent*, unevaluated*, contains, prefixItems, ...) and the empty schema {} or a boolean schema anywhere are refused."""
    problems=set()
    num=finite_number          # FR3-15 / FR3-16: a finite number that a double represents; never raises for any value
    def node(s,depth,root=False):
        if depth>SUMMARY_MAX_DEPTH:problems.add('too-deep');return
        if not isinstance(s,dict) or not s:problems.add('empty-or-boolean-schema');return
        if 'type' not in s:problems.add('untyped');return
        t=s['type'];types=[t] if isinstance(t,str) else t if isinstance(t,list) else None
        if not types or not all(isinstance(x,str) for x in types) or len(set(types))!=len(types):problems.add('type');return
        base=[x for x in types if x!='null']
        if len(base)!=1 or len(types)>2:problems.add('type');return
        b=base[0];nullable='null' in types
        if nullable and b not in ('number','integer','boolean'):problems.add('nullable-type');return
        allowed={'type','description'}|({'$schema'} if root else set())
        if b in ('number','integer'):
            allowed|=_NUMBER_KEYS
            if any(not num(s[k]) for k in _NUMBER_KEYS if k in s):problems.add('number-bound')
            if 'multipleOf' in s and not (num(s['multipleOf']) and s['multipleOf']>0):problems.add('multiple-of')   # FR3-15
        elif b=='boolean':pass
        elif b=='string':
            allowed|={'enum'};e=s.get('enum')
            if not isinstance(e,list) or not e or any(not isinstance(x,str) or x not in SUMMARY_LABELS for x in e):problems.add('string-not-a-framework-enum')
        elif b=='object':
            allowed|={'properties','additionalProperties','required'}
            if s.get('additionalProperties') is not False:problems.add('open-object')
            props=s.get('properties')
            if not isinstance(props,dict):problems.add('object-without-properties');props={}
            for k,sub in props.items():
                if not isinstance(k,str) or not SUMMARY_KEY.fullmatch(k):problems.add('property-name')
                node(sub,depth+1)
            req=s.get('required',[])
            if not isinstance(req,list) or any(not isinstance(r,str) or r not in props for r in req):problems.add('required')   # FR3-15
        elif b=='array':
            allowed|={'items','maxItems','minItems'}
            m=s.get('maxItems')
            if not isinstance(m,int) or isinstance(m,bool) or not 1<=m<=SUMMARY_MAX_ITEMS:problems.add('array-max-items')
            lo=s.get('minItems',0)
            if not isinstance(lo,int) or isinstance(lo,bool) or lo<0 or (isinstance(m,int) and lo>m):problems.add('array-min-items')
            if 'items' not in s:problems.add('array-without-items')
            else:node(s['items'],depth+1)
        else:problems.add('type');return
        for k in sorted(set(s)-allowed):problems.add('keyword:'+str(k)[:32])
        if root and b!='object':problems.add('root-not-object')
    node(schema,0,root=True)
    return sorted(problems)

def protocol_digest(root,project_dir):
    """sha256 of the project's bound protocol file, or None (no project, or a project without a protocol)."""
    if project_dir is None or load_protocol(root,project_dir) is None:return None
    return file_hash(protocol_path(root,project_dir))

def protocol_data(root,project_dir,key,proto=None):
    """The parsed JSON of the protocol file reference `key` (oracle or aggregate_schema), or None when the protocol or the
    reference is absent; the sha256 is checked again on this read. `proto`: the protocol that the caller has just loaded
    with load_protocol (FR3-R10: it is not loaded twice)."""
    proto=load_protocol(root,project_dir) if proto is None else proto
    ref=(proto or {}).get(key)
    if ref is None:return None
    data=_read_bound(root,project_dir,protocol_path(root,project_dir).parent/ref['file'],ref['sha256'],f'protocol {key} file',PROTOCOL_DATA_MAX_BYTES)
    return load_project_json(data,str(key).replace('_','-'),PROTOCOL_DATA_MAX_BYTES,label=f'protocol {key} file')   # FR3-17

def protocol_value(root,project_dir,key,default=None):
    """One top-level value of the project's protocol (a copy), or `default` when there is no protocol or no such key."""
    proto=load_protocol(root,project_dir) if project_dir is not None else None
    return copy.deepcopy(proto[key]) if proto is not None and key in proto else default

SIDECARS=('.opportunity.json','.panel.json')   # case sidecar files, never case manifests (Task 7: the G3.3 panel reference)

def _framework_case_ids(root):
    return sorted(p.stem for p in (Path(root)/CASES).glob('*.json') if not p.name.endswith(SIDECARS))

def _project_base(root,project_dir):
    """The project's benchmarks/project directory; the path is relative, inside the root, and never a link out of it."""
    if not isinstance(project_dir,str) or len(project_dir)>200 or not PROJECT_RE.fullmatch(project_dir) or '..' in project_dir.split('/'):
        raise GateError('project path is not allowed: project_dir must be a relative path of [A-Za-z0-9._-] segments, at most 200 characters')
    if project_dir!='.':
        from project_model import _safe_path
        _safe_path(project_dir,'project_dir')
    if not _within(os.path.realpath(Path(root)/project_dir),os.path.realpath(root)):raise GateError('project path is not allowed: outside the root')
    base=Path(root)/project_dir/PROJECT_AREA;_inside(root,project_dir,base);return base

def _within(real,top):
    """FR3-R10: real equals top or lies below it (both os.path.realpath strings; the same rule as Path.resolve() and
    Path.parents, without the per-parent Path objects)."""
    return real==top or real.startswith(top.rstrip('/')+'/')

def _inside(root,project_dir,path):
    """Review fix: every read path resolves fully (each link on the way) inside the project directory."""
    if not _within(os.path.realpath(path),os.path.realpath(Path(root)/project_dir)):raise GateError('benchmarks/project path resolves outside the project directory')
    return path

def project_bench(root,project_dir):
    """Amendment A: a project registers workloads in <project>/benchmarks/project/bench.json (case ids and checks only).
    A project sets no flag, limit, deadline or budget; its module names never shadow the container's modules (plan L7)."""
    if project_dir is None:return None
    base=_project_base(root,project_dir);path=base/'bench.json'
    for p in (base,path,base/'cases'):
        if p.is_symlink():raise GateError('benchmarks/project paths must not be symbolic links')
        _inside(root,project_dir,p)
    if not path.is_file():raise GateError('benchmarks/project/bench.json is missing')
    # FR3-17: the one boundary; every check of the parsed declaration runs inside it
    return load_project_json(path,'bench-json',PROJECT_JSON_MAX_BYTES,label='benchmarks/project/bench.json',
                             check=lambda decl:_check_bench(root,project_dir,base,decl))

def _check_bench(root,project_dir,base,decl):
    """The checks of project_bench on the parsed bench.json `decl` (GateError on the first failure)."""
    validate(root,'bench-project',decl)
    clash=sorted(set(decl['cases'])&set(_framework_case_ids(root)))
    if clash:raise GateError('project case ids collide with framework cases: '+', '.join(clash))
    files=[p for p in (base/'cases').glob('*.json') if not p.name.endswith(SIDECARS)] if (base/'cases').is_dir() else []
    if any(p.is_symlink() for p in files):raise GateError('project case manifests must not be symbolic links')
    for p in files:_inside(root,project_dir,p)
    if {p.stem for p in files}!=set(decl['cases']):raise GateError('project case manifests differ from bench.json cases')
    checks=decl.get('checks',[]);names=[c['name'] for c in checks]
    if len(names)!=len(set(names)):raise GateError('duplicate project check name')
    if any(not all(part.isidentifier() for part in c['module'].split('.')) for c in checks):raise GateError('project check module is not a dotted module name')
    py=base/'python'
    if py.is_symlink():raise GateError('benchmarks/project paths must not be symbolic links')
    _inside(root,project_dir,py)
    tops={p.name.split('.')[0] for p in py.iterdir() if p.name not in ('tests','__pycache__') and not p.name.startswith('.')} if py.is_dir() else set()
    tops|={c['module'].split('.')[0] for c in checks}
    clash=sorted(t for t in tops if t in RESERVED_MODULES)
    if clash:raise GateError('project module names collide with stdlib, startup hooks, bench wheels or framework packages: '+', '.join(clash))
    _protocol_binding(root,project_dir,base,decl)
    native_problem=native_declaration_problem(decl)
    if native_problem:raise GateError('bench.json native: '+native_problem)
    return decl

KERNEL_PLACEHOLDERS=('{input}','{records}','{loops}','{output}')      # each exactly once; {threads} is optional

def native_declaration_problem(decl):
    """Phase 2 Task 19 (FR6 N4): None, or the problem of the optional `native` declaration of a parsed bench.json (after the
    schema): `agreement` names a declared check, and the kernel argument template holds each of KERNEL_PLACEHOLDERS once and
    {threads} at most once. The kernel program must also be a native target of project.json (bench_native.native_targets,
    checked where the binaries are built)."""
    native=decl.get('native')
    if native is None:return None
    if native['agreement'] not in [c['name'] for c in decl.get('checks',[])]:return 'agreement names no declared check'
    args=native['kernel']['args']
    if any(args.count(p)!=1 for p in KERNEL_PLACEHOLDERS) or args.count('{threads}')>1:return 'kernel arguments need {input}, {records}, {loops} and {output} once each'
    return None


def _protocol_binding(root,project_dir,base,decl):
    """FR3: a protocol directory needs the bench.json binding {file: protocol/protocol.json, sha256}; a binding needs the
    file, and the file's sha256 must equal the bound digest (an unbound or edited protocol is refused). The schema of the
    file is checked by load_protocol."""
    proto=base/PROTOCOL_DIR;bind=decl.get('protocol')
    if proto.is_symlink():raise GateError('benchmarks/project paths must not be symbolic links')
    if bind is None:
        if proto.exists():raise GateError('protocol file is not bound: bench.json has no protocol binding (file and sha256)')
        return None
    _read_bound(root,project_dir,base/PROTOCOL_FILE,bind['sha256'],'protocol file',PROTOCOL_MAX_BYTES)
    return None

def unit_groups(root,project_dir):
    """Ruling A6-C3 (Task A6 lock follow-up): the project's optional `unit_groups`, a fixed partition of its
    python/tests/test_*.py modules into 2 to 8 groups (bench selftest runs one container command per group). None when not
    declared. GateError when a module is missing, listed twice or unknown (no test is ever left out)."""
    decl=project_bench(root,project_dir)
    groups=(decl or {}).get('unit_groups')
    if groups is None:return None
    tests=_project_base(root,project_dir)/'python'/'tests'
    if tests.is_symlink() or not tests.is_dir():raise GateError('unit_groups: the project has no python/tests directory')
    modules=sorted(x.stem for x in tests.glob('test_*.py'))
    flat=[m for g in groups for m in g]
    if len(flat)!=len(set(flat)):raise GateError('unit_groups: a module is listed twice')
    if sorted(flat)!=modules:
        raise GateError('unit_groups: the groups differ from the test modules (missing: '+', '.join(sorted(set(modules)-set(flat)))[:200]+
                        '; unknown: '+', '.join(sorted(set(flat)-set(modules)))[:200]+')')
    return [list(g) for g in groups]

def require_locked_selectors(policy,selectors):
    """A6P-05 (Task A6 lock follow-up): a selector whose tolerance block (policy tolerances.<selector>, an object with a
    state; load_policy takes `tolerances` from the project's protocol) is not in a locked state is refused for a plan or a
    run (N6: no agreement gate and no timing before the approver lock). A selector without such a block passes.
    Model-neutral: the block name is the selector."""
    tol=policy['tolerances']
    for s in selectors:
        block=tol.get(s) if isinstance(s,str) else None
        if isinstance(block,dict) and 'state' in block and not str(block['state']).startswith('locked-'):
            raise GateError(f'tolerances.{s} not locked (state {block["state"]}): selector {s} is refused until the approver lock')
        if isinstance(block,dict) and 'state' in block and not isinstance(block.get('approval'),str):   # FR3-02: the lock names its approval
            raise GateError(f'tolerances.{s} is locked without an approval reference: selector {s} is refused')
    return None

def case_ids(root,project_dir=None):
    decl=project_bench(root,project_dir);return sorted(_framework_case_ids(root)+(decl['cases'] if decl else []))

def _case_file(root,case_id,project_dir):
    decl=project_bench(root,project_dir)
    if decl and case_id in decl['cases']:return _inside(root,project_dir,_project_base(root,project_dir)/'cases'/(case_id+'.json'))
    if case_id in _framework_case_ids(root):return Path(root)/CASES/(case_id+'.json')
    raise GateError('unknown bench case')

def load_case(root,case_id,project_dir=None):
    path=_case_file(root,case_id,project_dir)
    def check(value):
        validate(root,'bench-case',value)
        if value['case_id']!=case_id:raise GateError('case manifest id differs from its file name')
    return load_project_json(path,'case-manifest',PROJECT_JSON_MAX_BYTES,label='case manifest',check=check)   # FR3-17

def load_opportunity(root,case,project_dir=None):
    """A framework record path is relative to the root; a project record (benchmarks/project/...) to the project directory."""
    rel=case['opportunity_record']
    if rel is None:return None
    if not isinstance(rel,str) or '..' in rel.split('/') or rel.startswith('/'):raise GateError('opportunity record path is not allowed')
    if rel.startswith(PROJECT_AREA+'/'):
        if project_dir is None:raise GateError('a project opportunity record needs the project directory')
        path=_inside(root,project_dir,_project_base(root,project_dir).parent.parent/rel)
    else:   # Task 13a residual: a framework record resolves inside the framework cases directory
        path=Path(root)/rel;top=(Path(root)/CASES).resolve();real=path.resolve()
        if top not in real.parents:raise GateError('opportunity record path resolves outside benchmarks/performance/cases')
    if path.is_symlink():raise GateError('opportunity record must not be a symbolic link')
    def check(value):
        validate(root,'bench-opportunity',value)
        if value['case_id']!=case['case_id']:raise GateError('opportunity record names another case')
    return load_project_json(path,'opportunity-record',PROJECT_JSON_MAX_BYTES,label='opportunity record',check=check)   # FR3-17

def project_identity(root,project_dir,case):
    """Content identity of a project case: sha256 over bench.json, the case manifest, its opportunity record and the
    adapter's top-level package (or module) under benchmarks/project/python. Paths are relative to the project, so the
    same content gives the same identity at any location."""
    decl=project_bench(root,project_dir);base=_project_base(root,project_dir);top=Path(root)/project_dir
    if case['case_id'] not in decl['cases']:raise GateError('not a project case')
    files=[base/'bench.json',base/'cases'/(case['case_id']+'.json')]
    if case.get('opportunity_record') and case['opportunity_record'].startswith(PROJECT_AREA+'/'):files.append(top/case['opportunity_record'])
    module=case['adapter'].split(':')[0].split('.')[0];py=base/'python'
    if (py/module).is_dir():files+=sorted(p for p in (py/module).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    elif (py/(module+'.py')).is_file():files.append(py/(module+'.py'))
    if len(files)>IDENTITY_FILES:raise GateError('project identity: too many adapter files')
    digest=hashlib.sha256();total=0
    for f in files:
        if f.is_symlink():raise GateError('project identity: a symbolic link in the adapter tree')
        _inside(root,project_dir,f);data=f.read_bytes();total+=len(data)
        if total>IDENTITY_BYTES:raise GateError('project identity: adapter tree larger than 64 MiB')
        digest.update(f.relative_to(top).as_posix().encode()+b'\0'+hashlib.sha256(data).hexdigest().encode()+b'\n')
    return digest.hexdigest()

def dropped_before_run_checks(policy,case_id,decl):
    """T29-APP-01 (P15 removed-safety-check): the key `before_run_required` of the project's protected protocol file
    (load_policy(root, project) puts it in the policy) names, per case id, the project checks that must stay declared in
    bench.json with `before_run: true`. One reason per required check that `decl` (the validated project declaration, or
    None) does not declare or declares with before_run false; [] for a case without an entry. A policy without the key
    raises KeyError (load_policy always sets it)."""
    declared={c['name']:c['before_run'] for c in (decl or {}).get('checks',[])};reasons=[]
    for name in policy['before_run_required'].get(case_id,[]):
        if name not in declared:reasons.append(f'removed safety check: case {case_id} requires the before_run check {name}; bench.json does not declare it')
        elif declared[name] is not True:reasons.append(f'removed safety check: case {case_id} requires the before_run check {name}; bench.json declares it with before_run false')
    return reasons

def container_case_path(case_id,project_dir=None,root=None):
    """The manifest path inside the bench container (/src is the root). With `root`, a framework case keeps its framework path."""
    project=f'/src/{"" if project_dir=="." else str(project_dir).rstrip("/")+"/"}{PROJECT_AREA}/cases/{case_id}.json'
    if project_dir is not None and (root is None or case_id in project_bench(root,project_dir)['cases']):return project
    return f'/src/{CASES}/{case_id}.json'

def case_rules(root,case,project_dir=None):
    """spec 11.1: a C row needs an approved opportunity record; bench new never generates C."""
    route_rules(case)          # N4-A05: before the record check
    live_c=[v['id'] for v in case['variants'] if v['language']=='c' and v['status'] not in ('planned-phase-2','not-applicable')]
    if live_c:
        record=load_opportunity(root,case,project_dir)
        if record is None or record['approval']['state']!='APPROVED':raise GateError('C variant without an approved opportunity record')
        check_baseline_variant(case,record)
    ids=[v['id'] for v in case['variants']]
    if len(ids)!=len(set(ids)) or 'py-reference' not in ids:raise GateError('case variants must be unique and include py-reference')
    for v in case['variants']:
        if (v['id'] in ('c-serial','py-reference','py-optimized','py-library'))!=(v['workers']==['direct']):raise GateError('direct variants use workers ["direct"] only')
        if v['language']!=('c' if v['id'].startswith('c-') else 'python-library' if v['id']=='py-library' else 'python'):raise GateError('variant language mismatch')
    selector_rules(case)
    check_call_deadlines(case)
    return True

def route_rules(case):
    """N4-A05: `routes` belongs to a C variant or a caller point only, and a point route list is a subset of the routes of
    the case's C variants (a variant without `routes` has the default route list). GateError otherwise; True."""
    import bench_plan
    c_routes=set()
    for v in case['variants']:
        if 'routes' in v and v['language']!='c':raise GateError(f"{v['id']}: routes belong to a C variant")
        if v['language']=='c':c_routes|=set(v.get('routes',bench_plan.DEFAULT_ROUTES))
    for p in case['points']:
        if 'routes' not in p:continue
        name=p.get('name','?')
        if p['scope']=='kernel':raise GateError(f'{name}: a kernel point has no routes')
        extra=sorted(set(p['routes'])-c_routes)
        if extra:raise GateError(f"{name}: routes {', '.join(extra)} are not routes of a C variant")
    return True

def check_baseline_variant(case,opportunity):
    """Amendment H4 item 8 (Task 14): the opportunity record's approval.baseline_variant, when present, is a variant id that
    the case declares. GateError otherwise. A record without the field passes here; the decision engine's item 8 needs it."""
    if opportunity is None:return True
    baseline=(opportunity.get('approval') or {}).get('baseline_variant')
    if baseline is not None and baseline not in [v['id'] for v in case['variants']]:
        raise GateError(f'opportunity approval.baseline_variant {baseline} is not a variant of case {case["case_id"]}')
    return True

def selector_rules(case):
    """Amendment G4.1, G2.6: selectors and units are opaque strings; only their declaration and consistency are checked."""
    declared=case.get('selectors',['all'])
    for p in case['points']:
        name=p.get('name','?');selector=p.get('selector','all')
        if selector not in declared:raise GateError(f'{name}: selector {selector} is not declared by the case')
        if selector!='all' and p['scope']=='kernel':raise GateError(f'{name}: a selector point is a caller or capacity point (kernel rows never enter a unit, G6.5)')
        if 'panel' in p and p['size']!='tiny':raise GateError(f'{name}: a panel needs the size tiny')
        if 'unit' in p and p['unit'].partition('/')[0]!=selector:raise GateError(f'{name}: the unit names another selector than the point')
    import bench_deadline
    undeclared=[s for e in bench_deadline.entries(case) for s in e['selectors'] if s not in declared]
    if undeclared:raise GateError('call_deadline names undeclared selectors: '+', '.join(undeclared))

def check_call_deadlines(case):
    """Amendment I9.1 (Task A2): the call-deadline entries (call_deadline + call_deadlines, bench_deadline.entries) never
    share a selector, so each covered call has one declared reason. GateError('call deadline selectors overlap: <s>')."""
    import bench_deadline
    seen=set()
    for e in bench_deadline.entries(case):
        for s in e['selectors']:
            if s in seen:raise GateError(f'call deadline selectors overlap: {s}')
            seen.add(s)
    return True

def params_from_case(case):
    """The parameter values of a case manifest. A workload checks its own parameter set (Amendment A)."""
    return {k:v['value'] for k,v in case['parameters'].items()}
