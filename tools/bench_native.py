"""Phase 2 Task 17 (plan amendment FR6 N2): the native build job, the sha256 restore and `bench check --native`.

Host side, record-agnostic. One `native-build` job (container/bench_native_job.py) builds the project's declared programs and
libraries with the hardened clang -O2 profile in a bench container, runs the project's `run` entry once as a smoke and hands
the targets out. The host fetches each target to run_dir/native/<name>, checks the fetched sha256 against the job row, the
compile flags of every project translation unit and the locked GLib runtime digest, and writes run_dir/native.json. A later
job gets the binaries back by `native_restore` (restored as bench/private/native/<name>) and their digests by `native_plan`;
the coordinator verifies every restored file before a child sees SAFE_C_BENCH_NATIVE (container native_env)."""
from __future__ import annotations
from pathlib import Path
import posixpath, re
from evidence import GateError, atomic_json, file_hash

REQUIRED_FLAGS=('-O2','-ffp-contract=off')
FORBIDDEN_FLAGS=('-fsanitize','-fprofile-instr-generate','-fcoverage-mapping','-ffast-math','-march=','-O0','-O1','-Ofast')
# N2-A01: clang applies the last flag of a family. The effective optimization level must be -O2, the effective
# -ffp-contract value must be off, and no fast-math family flag may be in effect at the end of the argv.
FAST_MATH_OFF={'-ffast-math':'-fno-fast-math','-funsafe-math-optimizations':'-fno-unsafe-math-optimizations',
               '-fassociative-math':'-fno-associative-math','-freciprocal-math':'-fno-reciprocal-math','-fno-signed-zeros':'-fsigned-zeros',
               '-fno-trapping-math':'-ftrapping-math','-ffinite-math-only':'-fno-finite-math-only','-fno-honor-nans':'-fhonor-nans',
               '-fno-honor-infinities':'-fhonor-infinities','-Ofast':None}
FAST_MATH_FLAGS=tuple(FAST_MATH_OFF)
OPT_LEVEL=re.compile(r'^-O(?:[0-9]+|s|z|g|fast)?$')
GLIB_NAME='libglib-2.0.so.0'
NATIVE_PREFIX='bench/private/native/'
PROGRAM_RE=re.compile(r'^[a-z][a-z0-9_-]{0,62}$');LIBRARY_RE=re.compile(r'^lib([a-z][a-z0-9_]{0,62})\.so$')
SHA256_RE=re.compile(r'^[0-9a-f]{64}$')
MAX_TARGETS=32;MAX_COMMANDS=512

class NativeBuildError(GateError):
    """A native build problem (FAIL): failed job, digest, flags, GLib or smoke. Infrastructure errors stay GateError (BLOCKED)."""

def native_targets(root,project_dir):
    """The program names, then lib<name>.so for each declared library, from the project's project.json."""
    import project_model as pm
    project=pm.load_project(root,project_dir)
    return [p['name'] for p in project['programs']]+['lib'+l['name']+'.so' for l in project.get('libraries',[])]

def cmake_target(name):
    """The CMake target of a native target: a program's own name; project-library-<name> for lib<name>.so (cmake/Project.cmake)."""
    m=LIBRARY_RE.fullmatch(name) if isinstance(name,str) else None
    if m:return 'project-library-'+m.group(1)
    if isinstance(name,str) and PROGRAM_RE.fullmatch(name):return name
    raise GateError('native target name rejected')

def _source(argv):
    """The translation unit of one compile argv: the argument after -c, else None."""
    for k,arg in enumerate(argv[:-1]):
        if arg=='-c':return argv[k+1]
    return None

def check_native_flags(commands,project_root):
    """One problem string per project translation unit (its source lies under project_root) that misses a required flag or
    carries a forbidden one. Framework units (foundation, cmake/empty.c) are not judged for flags here. EX1-A02 (b): every
    unit whose argv names the project wheel layer or the project's third-party tree gives a project-wheel-path problem."""
    import project_source
    top=posixpath.normpath(str(project_root)).rstrip('/')+'/'
    problems=[]
    for argv in commands:
        source=_source(argv) if isinstance(argv,list) and all(isinstance(a,str) for a in argv) else None
        # EX1-A02 (b): no compile command (a framework unit too) names the project wheel layer or the project's
        # third-party tree
        if source is not None and project_source.wheel_path_hits(argv,project_root=top.rstrip('/')):
            problems.append(f'{source}: {project_source.WHEEL_PATH_REASON} (names the project wheel layer or the project third-party tree)')
        if source is None or not posixpath.normpath(source).startswith(top):continue
        missing=[f for f in REQUIRED_FLAGS if f not in argv]
        forbidden=[a for a in argv if a.startswith(FORBIDDEN_FLAGS)]
        effective=_effective_problems(argv)
        if missing or forbidden or effective:
            problems.append(f'{source}: '+', '.join(['missing '+f for f in missing]+['forbidden '+f for f in forbidden]+effective))
    return problems

def _effective_problems(argv):
    """N2-A01: the last-wins value of each flag family (optimization level, -ffp-contract, each fast-math flag)."""
    out=[];levels=[a for a in argv if OPT_LEVEL.fullmatch(a)];contract=[a for a in argv if a.startswith('-ffp-contract=')]
    if levels and levels[-1]!='-O2':out.append('effective '+levels[-1]+' overrides -O2')
    if contract and contract[-1]!='-ffp-contract=off':out.append('effective '+contract[-1]+' overrides -ffp-contract=off')
    for flag,off in FAST_MATH_OFF.items():
        on=[k for k,a in enumerate(argv) if a==flag];undo=[k for k,a in enumerate(argv) if off and a==off]
        if flag=='-Ofast':on=[k for k in on if levels and levels[-1]=='-Ofast']
        if on and (not undo or undo[-1]<on[-1]):out.append('effective '+flag)
    return out

def verify_fetched(expected,directory):
    """{name: sha256} of the fetched files in directory; GateError when a file is missing or its sha256 differs from expected."""
    got={}
    for name,digest in expected.items():
        path=Path(directory)/name
        if path.is_symlink() or not path.is_file():raise NativeBuildError(f'fetched native target is missing: {name}')
        got[name]=file_hash(path)
        if got[name]!=digest:raise NativeBuildError(f'fetched native target digest differs from the job row: {name}')
    return got

def native_restore(native):
    """(container path, host path, sha256) per binary of a native.json value: restored as bench/private/native/<name>;
    Runner.restore refuses a copy whose bytes differ from the sha256 (DD-01)."""
    return [(NATIVE_PREFIX+name,Path(b['path']),b['sha256']) for name,b in native['binaries'].items()]   # N2-A04: the transfer checks the digest

def native_plan(native):
    """name -> sha256 of every binary, plus libglib-2.0.so.0 -> the GLib sha256: the plan key `native` of a later job."""
    return {**{name:b['sha256'] for name,b in native['binaries'].items()},native['glib']['name']:native['glib']['sha256']}

def _row_problems(row,targets,glib):
    if row.get('status')!='PASS':return [f"native build job status {row.get('status')!r} ({row.get('reason','no reason')})"]
    sha=row.get('sha256')
    if not isinstance(sha,dict) or sorted(sha)!=sorted(targets) or not all(type(v) is str and SHA256_RE.fullmatch(v) for v in sha.values()):
        return ['native build job row does not name a sha256 for exactly the declared targets']
    if row.get('glib_sha256')!=glib:return ['the GLib runtime of the build container differs from foundation.lock.json']
    return []

def build_native(root,run_dir,project_dir):
    """One native-build job for project_dir; fetches every target to run_dir/native/<name>, verifies it and writes
    run_dir/native.json. Returns the native.json value; raises GateError on any problem (NativeBuildError for build problems)."""
    import bench, bench_model as bm, project_check, project_model as pm
    run_dir=Path(run_dir);project=pm.load_project(root,project_dir);targets=native_targets(root,project_dir)
    if not targets or len(targets)>MAX_TARGETS:raise NativeBuildError('a native build needs 1 to 32 declared targets')
    for name in targets:cmake_target(name)
    glib=project_check.closure_allowlist(root)[GLIB_NAME]
    deadline=bm.load_policy(root,project_dir)['job_deadlines']['smoke']
    plan={'schema_version':1,'job':'native-build','run_id':run_dir.name,'project_dir':project_dir,'targets':targets,'deadline_seconds':deadline}
    session=bench.BenchSession(root,run_dir)
    try:
        r=session.job(plan,'native-build',deadline)
        evidence=[str(p) for p in (getattr(session,'evidence_paths',None) or [r['evidence_path']])]
        row=bench.last_json(r['output'])
        if not bench.passed(r) and row.get('status')=='PASS':row['status']='FAIL'
        problems=_row_problems(row,targets,glib)
        if problems:raise NativeBuildError(problems[0])
        fetched={}
        for name in targets:
            destination=run_dir/'native'/name;session.fetch('bench/out/'+name,destination)
            fetched[name]=session.fetched_sha256(destination)
            if fetched[name]!=row['sha256'][name]:raise NativeBuildError(f'fetched native target digest differs from the job row: {name}')
    finally:session.close()
    verify_fetched(row['sha256'],run_dir/'native')
    commands=row.get('commands') if isinstance(row.get('commands'),list) else []
    project_root=project_check.container_dir(project_dir)
    problems=check_native_flags(commands[:MAX_COMMANDS],project_root)
    if row.get('commands_cut') is not False or len(commands)>MAX_COMMANDS:     # N2-A02: every project unit must be judged
        problems.append('the compile database was cut at the job limits: not every project translation unit was judged')
    if not any(isinstance(a,list) and isinstance(_source(a),str) and posixpath.normpath(_source(a)).startswith(project_root.rstrip('/')+'/') for a in commands):
        problems.append('the compile database names no project translation unit')
    smoke_exit=row.get('smoke_exit') if type(row.get('smoke_exit')) is int else None
    compiler=row.get('compiler') if isinstance(row.get('compiler'),str) else None
    native={'project_dir':project_dir,'project_identity':project_check.project_identity(root,project_dir),
            'binaries':{name:{'path':str(run_dir/'native'/name),'sha256':fetched[name]} for name in targets},
            'glib':{'name':GLIB_NAME,'sha256':glib},'compiler':compiler[:200] if compiler else None,
            'flags':{'required':list(REQUIRED_FLAGS),'forbidden':list(FORBIDDEN_FLAGS),'problems':problems},
            'smoke':{'program':project['run']['program'],'exit':smoke_exit},'evidence_paths':evidence}
    atomic_json(run_dir/'native.json',native)
    if problems:raise NativeBuildError('native compile flags: '+problems[0])
    if smoke_exit!=0:raise NativeBuildError(f'native smoke run of {project["run"]["program"]} exited {smoke_exit}')
    return native

def native_build_cmd(root,args):
    """./tools/safety bench native-build --project DIR [--format json]: PASS (0) with native.json, FAIL (1) with the problem."""
    import bench
    project=bench.project_arg(root,args)
    if project is None:raise GateError('bench native-build needs --project')
    run_dir=bench.new_run_dir(root,'native-build')
    try:result={'status':'PASS','run_dir':str(run_dir),**build_native(root,run_dir,project)}
    except NativeBuildError as exc:result={'status':'FAIL','run_dir':str(run_dir),'reason':str(exc)[:300]}
    atomic_json(run_dir/'native-build.json',result)
    text=f"bench native-build: {result['status']}"+(f" ({result['reason']})" if 'reason' in result else f" {len(result['binaries'])} binaries")
    bench.emit(args,result,text);return bench.EXIT[result['status']]

def register_cli(handlers,arguments):
    """Adds the operation native-build and the --native flag of check (each once)."""
    handlers['native-build']=native_build_cmd
    arguments['native-build']=[('--project',{})]
    if '--native' not in dict(arguments.get('check',[])):arguments['check']=list(arguments.get('check',[]))+[('--native',{'action':'store_true'})]
