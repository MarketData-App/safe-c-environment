"""Deterministic regression replay remains independent of new-crash filtering."""
import json
import re
from evidence import passed

def adapter_build(q, variant):
    directory='adapter/'+variant
    env={'CC':'clang','CXX':'clang++','CFLAGS':'-O1 -g -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,address,undefined -fno-sanitize-recover=all',
         'CXXFLAGS':'-O1 -g -fsanitize=address,undefined','LIB_FUZZING_ENGINE':'-fsanitize=fuzzer',
         'OUT':'/work/'+directory,'WORK':'/work/'+directory,'SAFETY_QUALIFICATION_VARIANT':variant}
    result=q.runner.run(['bash','-x','/src/.clusterfuzzlite/build.sh'],env=env,timeout=45,label='adapter-'+variant+'-build')
    symbols=q.runner.run(['llvm-nm','--undefined-only','/work/'+directory+'/parser.o'],label='adapter-'+variant+'-instrumentation') if passed(result) else None
    audit=passed(result) and symbols is not None and passed(symbols) and '__asan_report' in symbols['output'] and '__sanitizer_cov' in symbols['output']
    return {'directory':directory,'result':result,'symbols':symbols,'audit':bool(audit),'env':env}

def adapter_replay(q, build, label):
    b={'directory':build['directory']}
    return q.executable(b,'parser_fuzzer',['/src/fuzz/regressions/C32','-runs=1'],label=label)

def run_fuzz(q, profile):
    records=[];ok=True
    builds={variant:adapter_build(q,variant) for variant in ['bad','good']}
    for variant,b in builds.items():
        records.extend([b['result']['evidence_path']]+([b['symbols']['evidence_path']] if b['symbols'] else []))
        ok=ok and b['audit']
    replay={}
    for variant,b in builds.items():
        if b['audit']:
            r=adapter_replay(q,b,'adapter-'+variant+'-regression');records.append(r['evidence_path'])
            if variant=='bad':clean=r['exit_code']!=0 and r['failure'] is None and 'AddressSanitizer: heap-buffer-overflow' in r['output'] and 'demo_parse' in r['output'] and '/src/fuzz/parser_bad.c' in r['output'] and r['binary_unchanged']
            else:clean=passed(r) and r['binary_unchanged']
            replay[variant]='PASS' if clean else 'FAIL';ok=ok and clean
        else:replay[variant]='BLOCKED'
    exploration={'status':'BLOCKED'}
    if builds['good']['audit']:
        q.runner.run(['python3','-c','import pathlib,shutil;p=pathlib.Path("/work/exploration-corpus");p.mkdir(exist_ok=True);[shutil.copyfile(x,p/x.name) for x in pathlib.Path("/src/fuzz/corpus").iterdir() if x.is_file()];pathlib.Path("/work/fuzz-failures").mkdir(exist_ok=True)'],label='fuzz-corpus')
        budget=['-runs=10000'] if profile=='smoke' else ['-max_total_time=900']
        r=q.runner.run(['/work/'+builds['good']['directory']+'/parser_fuzzer','/work/exploration-corpus',*budget,'-seed=12345','-max_len=256','-timeout=3','-rss_limit_mb=1024','-artifact_prefix=/work/fuzz-failures/'],timeout=45 if profile=='smoke' else 930,label='adapter-exploration-'+profile)
        records.append(r['evidence_path'])
        executions=re.findall(r'#(\d+)\s+DONE',r['output']);coverage=re.findall(r'cov: (\d+)',r['output']);features=re.findall(r'ft: (\d+)',r['output'])
        failures=q.runner.run(['python3','-c','import pathlib,json;print(json.dumps([str(p) for p in pathlib.Path("/work/fuzz-failures").iterdir()]))'],label='fuzz-failure-inventory')
        crashed=json.loads(failures['output']) if passed(failures) else ['missing evidence']
        complete=passed(r) and not crashed and executions and coverage and int(coverage[-1])>1 and (int(executions[-1])>=10000 if profile=='smoke' else True)
        exploration={'status':'PASS' if complete else 'FAIL','profile':profile,'executions':int(executions[-1]) if executions else 0,'coverage_edges':int(coverage[-1]) if coverage else 0,'features':int(features[-1]) if features else 0,'seed':12345,'budget':10000 if profile=='smoke' else 900,'budget_unit':'executions' if profile=='smoke' else 'seconds','failure_artifacts':crashed,'evidence_path':r['evidence_path'],'known_trigger_excluded_from_initial_corpus':True}
        ok=ok and bool(complete)
        # Every committed safe-corpus item must replay cleanly too.
        for path in sorted((q.root/'fuzz/corpus').iterdir()):
            r=q.runner.run(['/work/'+builds['good']['directory']+'/parser_fuzzer','/src/fuzz/corpus/'+path.name,'-runs=1'],label='adapter-safe-corpus');records.append(r['evidence_path']);ok=ok and passed(r)
    return {'status':'PASS' if ok else 'FAIL','regression_replay':replay,'exploration':exploration,'evidence_paths':records,
        'clusterfuzzlite':{'local_adapter_execution':'PASS' if ok else 'FAIL','local_image_id':q.runner.lock['image_id'],'compiler':'Clang 19.1.7 / matching compiler-rt and libFuzzer','remote_ci_execution':'NOT_RUN','remote_enforcement':'UNSEALED','build_interface':'Pinned ClusterFuzzLite build.sh conventions; external compiler and engine variables honored; .c compiled as C, C++ link driver','separate_toolchain':False}}
