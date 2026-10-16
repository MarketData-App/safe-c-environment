"""`./tools/safety bench panel`: the single-record panel reference (spec Amendment G3.3, G3.6, G3.7; Task 7, P3P-08;
Amendment I7.2 and the H21 cell rule, Task A6; FR5 ruling FR5-R1 item 1).

Container jobs (`panel`, synthetic large dataset only) write the candidate inputs that host code cannot compute: per row and
model the py-reference status, the result flags, engine_evals and the grid test `grid_ok`, plus the row columns that the
project's cell rule names, and the reference digest of the project's digest form. FR3: the panel models, the mask
(2^n - 1 over the models in order) and the digest form come from the `panel` block of the project's protected protocol
file; the framework names no model. FR5: the cell rule comes from the same block (`cell_rule`, validated by
bench_model when the protocol loads): the framework names no cell, no category and no column. The inputs of several
models can take longer than one container lives (the launcher holder, about 1,800 s), so
the rows run as PANEL_PARTS contiguous parts in separate jobs and one join job computes the digest of the joined result
(each row is evaluated alone, so the joined columns equal one sequential run). This module builds the closed
`bench-panel-reference` document from the stored values, applies the cell rule to them (`select`,
`selection_report`; it never recomputes a row), seals it with its own sha256 and writes
benchmarks/project/cases/<case>.panel.json of the project. `--rejected-from` names a tracked pre-flight record (H21.7) whose
rejected rows form the set R. Host code only: it never imports a module under benchmarks/ or examples/.

The cell rule is a generic banded rule over project-named numeric columns (FR5-R1 item 1: no project code runs on the
host, so the rule is data, not a project adapter function). Each of the PANEL_CELLS cells names a category value, a band
on the position column (gt, lt or abs_le a bound) and two targets. A row is a candidate of a cell when its category column
holds the cell's category value, its position is a number inside the band, and the row passes the status, flag and grid
rule of every panel model. The fallback level of a row is 0 when fabs(log(s / s_t)) <= log(level_ratios[0]), 1 when
<= log(level_ratios[1]), else 2 (s the scale column, s_t the cell's scale target); the distance is
d = |p - p_t| + |log(s / s_t)| in binary64, in this order. The report entries name the columns (each with an optional
factor) that the panel rows and the decision record show."""
from __future__ import annotations
from pathlib import Path
import copy, hashlib, json, math, re, subprocess
from evidence import GateError, ProjectDataError, PROJECT_JSON_MAX_BYTES, load_project_json, read_json, passed, file_hash
import bench_model as bm
from schema_check import validate

def panel_spec(root,project):
    """FR3 (was Amendment I7.2 MODELS and mask 31): (models, mask, digest form) of the `panel` block of the project's
    protocol; the models are also the selector mask of the job's call deadline (bench_deadline._selectors). GateError
    when the project declares no panel."""
    panel=bm.protocol_value(root,project,'panel')
    if not panel:raise GateError('bench panel: the project protocol declares no panel (models and digest form)')
    models=list(panel['models']);return models,(1<<len(models))-1,panel['digest_form']

def panel_rule(root,project):
    """FR5: the validated cell rule (`panel.cell_rule`) of the project's protocol. GateError when the project declares no
    panel or no cell rule."""
    panel=bm.protocol_value(root,project,'panel')
    if not panel or 'cell_rule' not in panel:raise GateError('bench panel: the project protocol declares no panel cell rule')
    return panel['cell_rule']

def cell_names(root,project):
    """FR5: the panel cell names of the project's protocol in cell order ([] without a project, a panel or a cell rule)."""
    if project is None:return []
    panel=bm.protocol_value(root,project,'panel') or {}
    return [c['name'] for c in (panel.get('cell_rule') or {}).get('cells',[])]

LISTED_FLAGS=1|2|4                            # the excluding flag bits of a reference row (H21.4: bit 8 no longer excludes)
ROUNDING_BAND=8                               # flag bit 8, admitted by the cell rule (H21.4); host tools never import a project
DATASET='synthetic:large'
PANEL_PARTS=8                                 # row parts of the panel inputs, one container job each (holder lifetime)
PANEL_CELLS=bm.PANEL_CELLS                    # the six one-row requests of a pass (G7.3); the protocol declares six cells
PREFLIGHT_DIR='cases/panel-preflight'         # tracked pre-flight records <sha256>.json, relative to the project's benchmarks/project/
REJECT_REASON='preflight-status-difference'
BANDS={'gt':lambda p,b:p>b,'lt':lambda p,b:p<b,'abs_le':lambda p,b:abs(p)<=b}
CELL_KEYS=('name','category','band','position_target','scale_target')
RULE_KEYS=('category','position','scale','level_ratios','grid','report')     # the stored copy of the rule (the cells are stored per cell)
INPUT_KEYS=('n','models','mask','digest_form','reference_sha256','grid','per_model')
GRID_POINTS_MAX=4096        # FR5A-01: the framework limit of the project's grid point count (schemas/bench-protocol.json grid)
ENTRY_KEYS=('row','reason','variant','workers','model','status','reference_status','band_difference','preflight_sha256','preflight_path')

def row_columns(rule):
    """The row column names of a cell rule: the category, position and scale columns, then each report column, once each."""
    out=[]
    for c in (rule['category']['column'],rule['position'],rule['scale'],*(r['column'] for r in rule['report'])):
        if c not in out:out.append(c)
    return out

def stored_rule(rule):
    """The part of the cell rule that a panel reference stores at its top level (its cells are stored per cell)."""
    return copy.deepcopy({k:rule[k] for k in RULE_KEYS})        # a copy: a stored document never aliases the rule

class PanelRefusal(Exception):
    """H21.5: a cell without a row (reason `panel-cell-empty`); `bench panel` then fails (exit 1) and writes no reference."""
    def __init__(self,reason,cell):
        super().__init__(f'{reason}: {cell}');self.reason=reason;self.cell=cell

def digest(doc):
    """sha256 of the canonical JSON (sorted keys, no spaces, ASCII, no NaN) of the document without its `sha256` field."""
    body={k:v for k,v in doc.items() if k!='sha256'}
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()

def seal(doc):
    out={k:v for k,v in doc.items() if k!='sha256'};out['sha256']=digest(out);return out

def before_grid(doc,i):
    """Status OK for every model and none of the listed flags: the part of the candidate rule before the grid test."""
    per=doc['per_model'];return all(per[m]['status'][i]=='OK' and not per[m]['flags'][i]&LISTED_FLAGS for m in doc['models'])

def candidate(doc,i):
    """H21.4: status OK for every model of the panel mask, none of the listed flags, grid_ok True for every model.
    ValueError when a row that passes the status and flag part has no evaluated grid test."""
    if not before_grid(doc,i):return False
    grid=[doc['per_model'][m]['grid_ok'][i] for m in doc['models']]
    if any(g is None for g in grid):raise ValueError(f'row {i}: grid_ok not evaluated on a row that passes the status and flag rule')
    return all(g is True for g in grid)

def level(s,st,ratios=(2.0,4.0)):
    """H21.5 normative window test (binary64, platform log): 0 when fabs(log(s/s_t)) <= log(ratios[0]), 1 when
    <= log(ratios[1]), else 2."""
    a=math.fabs(math.log(s/st))
    return 0 if a<=math.log(ratios[0]) else 1 if a<=math.log(ratios[1]) else 2

def distance(p,s,cell):
    """H21.5: d = |p - p_t| + |ln(s/s_t)| in binary64, in this order."""
    return abs(p-cell['position_target'])+abs(math.log(s/cell['scale_target']))

def in_band(p,band):
    """The cell's band test of a position value (gt, lt or abs_le the bound)."""
    return BANDS[band['op']](p,band['bound'])

def candidate_order(doc,cell,rule):
    """The cell's candidate order (H21.5): the candidate rows of the cell's category value inside its band, each once at its
    first level, level-0 rows in d order, then the rows that enter at level 1, then level 2 (ties: lower index)."""
    cols=doc['rows_columns'];cat=cols[rule['category']['column']];pos=cols[rule['position']];sc=cols[rule['scale']]
    value=rule['category']['labels'][cell['category']];out=[]
    for i in range(doc['rows']):
        if cat[i]!=value or pos[i] is None or not in_band(pos[i],cell['band']) or not candidate(doc,i):continue   # position null: no value
        d=distance(pos[i],sc[i],cell)
        if not bm.finite_number(d):raise ValueError(f'row {i}: the distance to cell {cell["name"]} is not a finite number')   # FR5A-05
        out.append((level(sc[i],cell['scale_target'],rule['level_ratios']),d,i))
    out.sort();return [{'row':i,'level':lv,'d':d} for lv,d,i in out]

def selection_report(doc,rule,rejected=frozenset(),full=False):
    """The one selection rule (H21.5) from the stored inputs only: cells in cell order; each cell's row is the first row of
    its candidate order that is not in `rejected` (R) and not held by an earlier cell. Per cell the evaluated order up to
    and including the selected row (the whole order with `full`) and the selected row with its level. PanelRefusal
    ('panel-cell-empty', cell name) when a cell has no such row."""
    held=set();cells=[];R=set(rejected)
    for cell in rule['cells']:
        order=candidate_order(doc,cell,rule)
        k=next((n for n,e in enumerate(order) if e['row'] not in R and e['row'] not in held),None)
        if k is None:raise PanelRefusal('panel-cell-empty',cell['name'])
        sel=order[k];held.add(sel['row'])
        cells.append({'name':cell['name'],'order':order if full else order[:k+1],'selected':{'row':sel['row'],'level':sel['level']}})
    return {'cells':cells,'indices':[c['selected']['row'] for c in cells]}

def select(doc,rule,rejected=frozenset()):
    """The panel indices in cell order (H21.5); see selection_report."""
    return selection_report(doc,rule,rejected)['indices']

def stored_rejected(doc):
    """The set R of a stored reference: every rejected row of every cell."""
    return {e['row'] for c in doc['cells'] for e in c['rejected']}

def report_value(v,factor):
    """A report value: the stored value times the entry's factor (no factor: the stored value unchanged); None stays None."""
    return None if v is None else v if factor is None else v*factor

def panel_rows(doc,rule):
    """H21.6 (and T7-01): per panel index, in cell order, the cell name, the category label, the report values (each
    report entry of the rule: its column times its factor) and the fallback level of the stored row. Values of synthetic
    rows only."""
    cols=doc['rows_columns'];names={v:k for k,v in rule['category']['labels'].items()};cat=cols[rule['category']['column']]
    return [{'cell':cell['name'],'index':i,'category':names.get(cat[i]),'level':c['selected']['level'],
             'values':{r['name']:report_value(cols[r['column']][i],r.get('factor')) for r in rule['report']}}
            for cell,c,i in zip(rule['cells'],doc['cells'],doc['indices'])]

def slowest(doc):
    """G3.6 diagnostic: per model the row with the largest stored engine_evals (ties: the lower index)."""
    out={}
    for m in doc['models']:
        ev=doc['per_model'][m]['engine_evals'];out[m]=min(range(len(ev)),key=lambda i:(-ev[i],i))
    return out

def _finite(v):return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)

def column_problems(cols,rule):
    """FR5: the row columns against the rule: exactly the rule's columns; the category column holds rule label values; the
    scale column holds finite numbers > 0; the position and report columns hold finite numbers or null. [] when sound."""
    if not isinstance(cols,dict) or sorted(cols)!=sorted(row_columns(rule)):return ['the row columns differ from the cell rule columns']
    out=[];values=set(rule['category']['labels'].values())
    if any(type(v) is not int or v not in values for v in cols[rule['category']['column']]):out.append('a category value outside the rule labels')
    if any(not _finite(v) or v<=0 for v in cols[rule['scale']]):out.append('a scale value that is not a finite number > 0')
    others=[c for c in row_columns(rule) if c not in (rule['category']['column'],rule['scale'])]
    if any(v is not None and not _finite(v) for c in others for v in cols[c]):out.append('a row value that is not a finite number or null')
    return out

def check(root,doc,rule):
    """The closed schema, the own sha256, equal column lengths, grid_ok present exactly on the rows that pass the status
    and flag rule (rounding-band rows included), the stored cell rule and cell definitions equal to the project's `rule`,
    the row columns of that rule, and per cell the stored order, rejected set and selected row equal to the one selection
    rule applied to the stored inputs with the stored R. GateError on any failure."""
    validate(root,'bench-panel-reference',doc)
    if doc['sha256']!=digest(doc):raise GateError('panel reference sha256 differs from its content')
    if doc['mask']!=(1<<len(doc['models']))-1 or sorted(doc['per_model'])!=sorted(doc['models']):raise GateError('panel reference mask or per-model columns differ from its models')
    if any(e['model'] not in doc['models'] for c in doc['cells'] for e in c['rejected']):raise GateError('panel reference rejection names a model outside its models')
    if doc['cell_rule']!=stored_rule(rule):raise GateError('panel reference cell rule differs from the project protocol cell rule')
    if [{k:c[k] for k in CELL_KEYS} for c in doc['cells']]!=[{k:c[k] for k in CELL_KEYS} for c in rule['cells']]:
        raise GateError('panel reference cell definitions differ from the project protocol cells')
    problems=column_problems(doc['rows_columns'],rule)
    if problems:raise GateError('panel reference row columns: '+problems[0])
    n=doc['rows']
    if any(len(v)!=n for v in doc['rows_columns'].values()) or any(len(v)!=n for col in doc['per_model'].values() for v in col.values()):
        raise GateError('panel reference column length differs from rows')
    for i in range(n):
        pre=before_grid(doc,i);grid=[doc['per_model'][m]['grid_ok'][i] for m in doc['models']]
        if pre and any(g is None for g in grid):raise GateError(f'panel reference row {i}: grid_ok missing on a row that passes the status and flag rule')
        if not pre and any(g is not None for g in grid):raise GateError(f'panel reference row {i}: grid_ok on a row that fails the status and flag rule')
    try:rep=selection_report(doc,rule,stored_rejected(doc))
    except (ValueError,PanelRefusal) as exc:raise GateError('panel reference selection: '+str(exc)) from None
    if doc['indices']!=rep['indices']:raise GateError('panel reference indices differ from the H21 selection of its stored inputs')
    for k,(c,want) in enumerate(zip(doc['cells'],rep['cells'])):
        if c['order']!=want['order'] or c['selected']!=want['selected']:
            raise GateError(f'panel reference cell {k}: stored order or selection differs from the recomputed candidate order')
    return None

def build(inputs,*,case,seed,generator_sha256,models,digest_form,rule,rejected=()):
    """The sealed panel reference of the joined inputs: the indices of the one selection rule with R = the rows of
    `rejected` (entries of load_rejected, each with its cell index), each cell with its definition, its evaluated order,
    its rejected entries and its selected row. The inputs must name the project's panel `models` (mask 2^n - 1) and
    `digest_form` (panel_spec) and carry the row columns of the project's cell `rule` (panel_rule). PanelRefusal
    propagates (a cell without a row)."""
    columns=row_columns(rule)
    if not isinstance(inputs,dict) or set(inputs)-{'counts'}!=set(INPUT_KEYS)|set(columns):raise GateError('panel inputs have unexpected keys')
    mask=(1<<len(models))-1
    if inputs['models']!=list(models) or inputs['mask']!=mask or inputs['digest_form']!=digest_form:raise GateError('panel inputs are not the project panel reference (models, mask, digest form)')
    if inputs['grid']!=rule['grid']:raise GateError('panel inputs name other grid settings than the project protocol cell rule')   # FR5A-01
    cols={k:inputs[k] for k in columns}
    problems=column_problems(cols,rule)
    if problems:raise GateError('panel inputs: '+problems[0])
    doc={'schema_version':4,'case':case,'dataset':DATASET,'seed':seed,'rows':inputs['n'],'generator_sha256':generator_sha256,
         'models':list(models),'mask':mask,'reference_digest_form':digest_form,'reference_sha256':inputs['reference_sha256'],
         'cell_rule':stored_rule(rule),'cells':[],'indices':[],
         'rows_columns':cols,'per_model':inputs['per_model']}
    R={e['row'] for e in rejected}
    try:rep=selection_report(doc,rule,R)
    except PanelRefusal:raise
    except (ValueError,KeyError,IndexError,TypeError) as exc:raise GateError('panel selection: '+str(exc)[:200]) from None
    for k,(cell,c) in enumerate(zip(rule['cells'],rep['cells'])):
        doc['cells'].append({**copy.deepcopy({key:cell[key] for key in CELL_KEYS}),'order':c['order'],'rejected':[{key:e[key] for key in ENTRY_KEYS} for e in rejected if e['cell']==k],
                             'selected':c['selected']})
    doc['indices']=rep['indices']
    return seal(doc)

def part_ranges(n,parts):
    """Contiguous row ranges [a, b) of `parts` parts of n rows (part k: k n // parts to (k + 1) n // parts)."""
    return [(k*n//parts,(k+1)*n//parts) for k in range(parts)]

def join_part_columns(parts,columns):
    """The per-row columns (`columns`, the row columns of the cell rule) and the per-model columns of the part documents
    joined in row order. GateError when the parts are not the contiguous parts 0..K-1 of one dataset, or (A6P-01) when
    their grid settings differ."""
    K=len(parts);n=parts[0]['n_total'] if parts else 0;at=0;out={c:[] for c in columns};per={}
    for k,p in enumerate(parts):
        if p.get('part')!=[k,K] or p.get('start')!=at or p.get('n_total')!=n or not isinstance(p.get('stop'),int) or p['stop']<=at:
            raise GateError('panel parts are not contiguous in row order')
        if not isinstance(p.get('grid'),dict) or p.get('grid')!=parts[0].get('grid'):
            raise GateError('panel parts differ in their grid settings')
        size=p['stop']-p['start']
        for c in columns:
            if not isinstance(p.get(c),list) or len(p[c])!=size:raise GateError('panel part column length differs from its range')
            out[c]+=p[c]
        for m,col in p['per_model'].items():
            dst=per.setdefault(m,{key:[] for key in col})
            for key,v in col.items():
                if len(v)!=size:raise GateError('panel part column length differs from its range')
                dst[key]+=v
        at=p['stop']
    if at!=n:raise GateError('panel parts do not cover the dataset')
    return {**out,'per_model':per}

def same_source(sources):
    """A6P-01: the one source identity (evidence input binding `source`) of every part and join job; GateError when one
    differs from the first job's or is missing (parts from different code are never joined into a sealed reference)."""
    if not sources or any(not isinstance(x,str) or x!=sources[0] for x in sources):
        raise GateError('a panel job ran on another source identity than the first job (or reported none): the tree changed during the run')
    return sources[0]

# ---- --rejected-from (H21.6, H21.7): a tracked pre-flight record whose sha256 is its file name ----
def tracked(root,rel):
    """True when `rel` (relative to the root) is a file tracked by git in the root checkout (host only)."""
    r=subprocess.run(['git','-C',str(root),'ls-files','--error-unmatch','--',rel],capture_output=True,text=True)
    return r.returncode==0

def _record(root,project,rel):
    """(bytes, sha256) of one pre-flight record: under PREFLIGHT_DIR, named <sha256>.json with that sha256 of its bytes,
    a regular file inside the project and tracked by git."""
    if not isinstance(rel,str) or not re.fullmatch(re.escape(PREFLIGHT_DIR)+r'/[0-9a-f]{64}\.json',rel):
        raise GateError(f'pre-flight record path must be {PREFLIGHT_DIR}/<sha256>.json relative to benchmarks/project/')
    base=bm._project_base(root,project);path=base/rel
    if path.is_symlink() or not path.is_file():raise GateError('pre-flight record not found: '+rel)
    with open(path,'rb') as f:data=f.read(PROJECT_JSON_MAX_BYTES+1)
    if len(data)>PROJECT_JSON_MAX_BYTES:raise ProjectDataError('preflight-record','too-large','pre-flight record')   # FR3-17: the cap first
    sha=hashlib.sha256(data).hexdigest()
    if sha!=Path(rel).stem:raise GateError('pre-flight record sha256 differs from its file name: '+rel)
    if not tracked(root,str(path.relative_to(Path(root)))):raise GateError('pre-flight record is not tracked by git: '+rel)
    return data,sha

def load_rejected(root,project,rel):
    """The rejected entries of the record at `rel` (relative to the project's benchmarks/project/): its replacements (each
    with this record's sha256 and path) and its carried entries (the rejections that the panel already held, each with
    its own record, checked by the same rules). Each entry keeps its cell index."""
    data,sha=_record(root,project,rel)
    out=[]
    def check(rec):           # FR3-17: every check of the parsed record runs inside the one boundary
        if not isinstance(rec,dict) or not isinstance(rec.get('replacements'),list) or not isinstance(rec.get('carried'),list):
            raise GateError('pre-flight record lacks replacements and carried lists')
        try:
            for r in rec['replacements']:
                out.append({'row':r['old_index'],'cell':r['cell'],'reason':REJECT_REASON,'variant':r['variant'],'workers':r['workers'],'model':r['model'],
                            'status':r['status'],'reference_status':r['reference_status'],'band_difference':r['band_difference'],
                            'preflight_sha256':sha,'preflight_path':rel})
            for c in rec['carried']:
                _,csha=_record(root,project,c['preflight_path'])
                if csha!=c['preflight_sha256']:raise GateError('carried rejection names another record digest')
                out.append({'cell':c['cell'],**{k:c[k] for k in ENTRY_KEYS}})
        except (KeyError,TypeError) as exc:raise GateError('pre-flight record entry is incomplete: '+str(exc)[:80]) from None
        if any(type(e['row']) is not int or type(e['cell']) is not int or not 0<=e['cell']<PANEL_CELLS for e in out):raise GateError('pre-flight record entry has a bad row or cell')
    load_project_json(data,'preflight-record',PROJECT_JSON_MAX_BYTES,label='pre-flight record',check=check)
    return out

def _fmt(v):return 'null' if v is None else f'{v:.6g}'

def panel_path(root,project,case_id):return bm._project_base(root,project)/'cases'/f'{case_id}.panel.json'

def _job(root,run_dir,plan,label,session,restore=()):
    """One coordinator job in its own container (each part gets a fresh holder lifetime)."""
    import bench
    run_dir.mkdir(parents=True,exist_ok=True);s=bench.BenchSession(root,run_dir)
    try:
        r=s.job(plan,label,session,restore=restore);row=bench.last_json(r['output']);evidence=list(s.evidence_paths)
        ok=passed(r) and row.get('status')=='PASS';source=(r.get('input_binding') or {}).get('source')
        if ok:s.fetch('bench/out/'+plan['panel_file'],run_dir/plan['panel_file'])
    finally:s.close()
    return ok,row,evidence,source

def panel_cmd(root,args):
    """bench panel --project DIR --case ID [--dataset synthetic:large] [--rejected-from PATH]: PANEL_PARTS container jobs on
    contiguous row parts and one join job, then the host builds, checks and writes the panel reference. Any dataset other
    than synthetic:large (a local: dataset above all) and any rejected-from record that is not a tracked
    cases/panel-preflight/<sha256>.json of the project are refused before any container starts. A cell without a row is
    FAIL (exit 1, reason panel-cell-empty) and writes no reference."""
    import bench, bench_deadline, bench_plan
    from evidence import atomic_json
    if getattr(args,'dataset',DATASET)!=DATASET:raise GateError(f'bench panel: the panel is computed on {DATASET} only (G3.3: synthetic only; a local: dataset is refused)')
    if getattr(args,'project',None) is None:raise GateError('bench panel needs --project')
    project=bench.project_arg(root,args);case=bm.load_case(root,args.case,project)
    if case['case_id'] not in bm.project_bench(root,project)['cases']:raise GateError('bench panel: the case is not a case of the project')
    rel=getattr(args,'rejected_from',None);rejected=load_rejected(root,project,rel) if rel is not None else []
    bm.case_rules(root,case,project_dir=project);policy=bm.load_policy(root,project);dataset=bench_plan.parse_dataset(root,DATASET,policy)
    seed=(case.get('parameters') or {}).get('seed',{}).get('value')
    if seed!=dataset['seed']:raise GateError('bench panel: the case parameter seed differs from the synthetic dataset seed')
    models,_,digest_form=panel_spec(root,project)        # FR3: the project's panel models and digest form (refused before any container)
    rule=panel_rule(root,project);columns=row_columns(rule)   # FR5: the project's cell rule (refused before any container)
    session=policy['job_deadlines']['session'];rows=policy['sizes']['large']
    fields=bench_deadline.deadline_fields(case,policy,'panel',{'sizes':policy['sizes']},{'variant':'py-reference','selectors':models},None,session)
    run_dir=bench.new_run_dir(root,'panel')
    base={'schema_version':1,'job':'panel','case':case['case_id'],'case_manifest':bm.container_case_path(case['case_id'],project,root),
          'project_dir':project,'dataset':dataset,'rows':rows,'sizes':policy['sizes'],'local':False,'output':'bench/out','deadline_seconds':session,
          'panel_workers':policy['envelope']['cpus'],'request_limit':policy['pools']['request_limit'],**fields}
    evidence=[];row={};ok=True;parts=[];shas=[];sources=[]
    for k in range(PANEL_PARTS):
        sub=run_dir/f'part-{k}'
        ok,row,ev,src=_job(root,sub,{**base,'run_id':run_dir.name,'panel_part':[k,PANEL_PARTS],'panel_file':f'panel-part-{k}.json'},f'panel-part-{k}',session);evidence+=ev;sources.append(src)
        if not ok or bench_deadline.job_reason(row) is not None:break
        if file_hash(sub/f'panel-part-{k}.json')!=row.get('inputs_sha256'):raise GateError('fetched panel part digest differs')
        parts.append(sub/f'panel-part-{k}.json');shas.append(row.get('dataset_sha256'))
    if ok and bench_deadline.job_reason(row) is None:
        import shutil
        staged=run_dir/'join'/'parts';staged.mkdir(parents=True)        # the launcher restores only files under the job's own run directory
        restore=[(f'bench/data/panel-part-{k}.json',shutil.copy2(p,staged/p.name)) for k,p in enumerate(parts)]
        ok,row,ev,src=_job(root,run_dir/'join',{**base,'run_id':run_dir.name,'panel_join':PANEL_PARTS,'panel_file':'panel-inputs.json'},'panel-join',session,restore);evidence+=ev;sources.append(src)
    reason=bench_deadline.job_reason(row)
    if not ok or reason is not None:
        result={'status':'FAIL','case':case['case_id'],'reason':row.get('reason','panel job failed'),'evidence_paths':evidence,**({'failure_reason':reason} if reason else {})}
        atomic_json(run_dir/'panel.json',result);bench.emit(args,result,f"bench panel {case['case_id']}: FAIL"+(f' {reason}' if reason else ''));return 1
    if any(x!=row.get('dataset_sha256') for x in shas):raise GateError('panel parts and join saw different generated datasets')
    source=same_source(sources)                                    # A6P-01: one source identity for all 9 jobs
    inputs_path=run_dir/'join'/'panel-inputs.json'
    if file_hash(inputs_path)!=row.get('inputs_sha256'):raise GateError('fetched panel inputs digest differs')
    inputs=read_json(inputs_path)
    if inputs.get('n')!=rows:raise GateError('panel inputs row count differs from the large tier')
    joined=join_part_columns([read_json(x) for x in parts],columns)   # the host cross-check of the container join
    if any(joined[c]!=inputs.get(c) for c in columns) or joined['per_model']!=inputs.get('per_model'):raise GateError('joined panel inputs differ from the parts')
    try:doc=build(inputs,case=case['case_id'],seed=seed,generator_sha256=row['dataset_sha256'],models=models,digest_form=digest_form,rule=rule,rejected=rejected)
    except PanelRefusal as exc:
        result={'status':'FAIL','case':case['case_id'],'reason':exc.reason,'cell':exc.cell,'evidence_paths':evidence}
        atomic_json(run_dir/'panel.json',result);bench.emit(args,result,f"bench panel {case['case_id']}: FAIL {exc.reason} {exc.cell}");return 1
    check(root,doc,rule)
    target=panel_path(root,project,case['case_id'])
    target.write_text(json.dumps(doc,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n')
    if digest(read_json(target))!=doc['sha256']:raise GateError('written panel reference differs')
    result={'status':'PASS','case':case['case_id'],'path':str(target.relative_to(root)),'sha256':doc['sha256'],'indices':doc['indices'],
            'cells':[c['name'] for c in rule['cells']],'panel_rows':panel_rows(doc,rule),'slowest':slowest(doc),'reference_sha256':doc['reference_sha256'],
            'generator_sha256':doc['generator_sha256'],'source_identity':source,'counts':inputs.get('counts'),'rejected':[{k:e[k] for k in ('row','cell','variant','model')} for e in rejected],
            'status_counts':{m:{st:doc['per_model'][m]['status'].count(st) for st in sorted(set(doc['per_model'][m]['status']))} for m in models},
            'evidence_paths':evidence}
    atomic_json(run_dir/'panel.json',result)
    lines=''.join(f"\n  {r['cell']}: row {r['index']} {r['category']} "+' '.join(f"{k} {_fmt(v)}" for k,v in r['values'].items())+f" level {r['level']}"
                  for r in result['panel_rows'])
    bench.emit(args,result,f"bench panel {case['case_id']}: PASS indices {doc['indices']} -> {result['path']}"+lines);return 0
