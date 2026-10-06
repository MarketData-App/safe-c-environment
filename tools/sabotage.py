"""Disposable mutations; the imported outer evaluator is never edited by a test."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import tempfile
from evidence import GateError, Runner, atomic_json, read_json, passed, environment_gate, file_hash
from policy import inventory_gate, upstream_gate, baseline_gate, baseline_identity, source_files, build_audit, source_identity, validate_fresh_report, lit_accounting, configuration_gate, validate_lit_options
from qualification import Qualifier, ast_banned_calls
from fuzzing import adapter_build, adapter_replay

class Scratch:
    def __init__(self,root,q,name):
        self.temp=tempfile.TemporaryDirectory(prefix='safe-c-mutation-')
        self.root=Path(self.temp.name)/'candidate';self.root.mkdir()
        for rel in source_files(root):
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/rel,p)
        for folder in ['src','include']:(self.root/folder).mkdir(exist_ok=True)
        self.runner=Runner(self.root,q.runner.run_dir/'sabotage'/name,q.runner.lock,Path(self.temp.name)/'capture')
        self.q=Qualifier(self.root,self.runner)
    def close(self):self.runner.close();self.temp.cleanup()
    def edit(self,rel,transform):
        p=self.root/rel;p.write_text(transform(p.read_text()))


def rejection(action):
    try:action()
    except (GateError,ValueError,KeyError,OSError) as exc:return True,str(exc)
    return False,'broken state was accepted'

def synthetic(scratch):
    # Test-only trusted fixture factory performs the contract transition in this
    # disposable copy. The actual normal safety_add_program helper builds both TUs.
    (scratch.root/'src/probe.c').write_text('#include <stdlib.h>\nint helper(char *p);\nint main(void){char *p=malloc(4);if(!p)return 2;p[0]=0;int r=helper(p);free(p);return r;}\n')
    (scratch.root/'src/helper.c').write_text('int helper(char *p);\nint helper(char *p){return p[0];}\n')
    scratch.edit('CMakeLists.txt',lambda s:s.replace('if(app_sources)','if(FALSE)')+'\nsafety_add_program(synthetic_app src/probe.c src/helper.c)\n')

def synthetic_build_audit(scratch):
    b=scratch.q.build('asan');
    audit=build_audit(b['commands'],['src/probe.c','src/helper.c'],'asan')
    if not scratch.q.built(b):raise GateError('synthetic build failed or link instrumentation missing')
    return audit


def run_sabotage(root,q,report):
    result=[]
    contract=read_json(root/'safety/contract.json');expected_fixtures=read_json(root/'safety/fixtures.json')
    def trusted_inventory(candidate):
        if read_json(candidate/'safety/fixtures.json')!=expected_fixtures:raise GateError('protected fixture inventory/expectation changed')
        return inventory_gate(candidate,contract)
    base_control=trusted_inventory(root);upstream_control=upstream_gate(root)
    def test(pid,name,mutate,check,control=None):
        scratch=Scratch(root,q,pid+'-'+name)
        try:
            control_ok=True
            if control:
                try:control(scratch)
                except (GateError,OSError,ValueError,KeyError):control_ok=False
            scratch.runner.close()
            mutate(scratch)
            scratch.q.builds={}
            if scratch.runner.alive:
                scratch.runner.run(['rm','-rf','/work/build'],label='mutation-clean-build')
            rejected,reason=rejection(lambda:check(scratch))
            row={'name':name,'status':'PASS' if rejected and control_ok else 'FAIL','control':'PASS' if control_ok else 'FAIL','evidence_paths':[r['evidence_path'] for r in scratch.runner.records],'reason':reason}
            atomic_json(q.runner.run_dir/'sabotage'/pid/(name+'.json'),row)
            return row
        finally:scratch.close()
    def simple(pid,name,rel,transform,checker=trusted_inventory):
        return test(pid,name,lambda s:s.edit(rel,transform),lambda s:checker(s.root),lambda s:checker(s.root))
    def from_rows(pid,rows):
        status='PASS' if rows and all(r['status']=='PASS' for r in rows) else 'FAIL'
        row={'id':pid,'status':status,'control':'PASS' if all(r['control']=='PASS' for r in rows) else 'FAIL','subcases':rows,'evidence_paths':[p for r in rows for p in r['evidence_paths']],'reason':'all named mutations rejected' if status=='PASS' else 'mutation or control failed'}
        result.append(row);print(pid+': '+status+' ('+str(len(rows))+' subcases)',flush=True)
    # Missing pinned executables cannot be replaced by a successful version string.
    def tool_check(s):
        from cli import doctor
        if doctor(s.q,probes=False)['status']!='PASS':raise GateError('doctor blocks missing required executable')
    def missing_tool(name):
        def mutate(s):
            j=read_json(s.root/'toolchain.lock.json');j['tools'][name]['path']='/missing/'+name;atomic_json(s.root/'toolchain.lock.json',j)
        return mutate
    from_rows('P01',[test('P01','analyzer-missing',missing_tool('clang-tidy'),tool_check,tool_check),test('P01','upstream-tool-missing',missing_tool('FileCheck'),tool_check,tool_check)])
    def drop_object(s):
        s.edit('CMakeLists.txt',lambda text:text+'\nset_source_files_properties(src/helper.c PROPERTIES COMPILE_OPTIONS "-fno-sanitize=all")\n')
    from_rows('P02',[test('P02','object-uninstrumented',drop_object,synthetic_build_audit,lambda s:(synthetic(s),synthetic_build_audit(s))),
       test('P02','adapter-object-uninstrumented',lambda s:s.edit('.clusterfuzzlite/build.sh',lambda text:text.replace('"${cflags[@]}" -std=c17 -I/src/fuzz -c "/src/$parser"','-O1 -g -std=c17 -I/src/fuzz -c "/src/$parser"')),lambda s:require_adapter(s),lambda s:require_adapter(s))])
    def drop_link(s):
        s.edit('cmake/Safety.cmake',lambda text:text.replace('target_link_options(${target} PRIVATE ${flags})','target_link_options(${target} PRIVATE -Wl,--no-as-needed)'))
    from_rows('P03',[test('P03','link-uninstrumented',drop_link,synthetic_build_audit,lambda s:(synthetic(s),synthetic_build_audit(s)))])
    p4=[]
    for name,content in [('no-sanitize','__attribute__((no_sanitize("address"))) int banned(void){return 0;}'),('sanitizer-dummy-success','#if __has_feature(address_sanitizer)\nint main(void){return 0;}\n#endif'),('ignorelist','/* -fsanitize-ignorelist=all */')]:
        p4.append(test('P04',name,lambda s,content=content:(s.root/'fuzz/parser_good.c').write_text(content),lambda s:configuration_gate(s.root),lambda s:configuration_gate(s.root)))
    for env in ['LIT_OPTS','FILECHECK_OPTS','ASAN_OPTIONS','LSAN_OPTIONS','UBSAN_OPTIONS','MSAN_OPTIONS','TSAN_OPTIONS']:
        rejected,reason=rejection(lambda env=env:environment_gate({env:'--no-execute'}));p4.append({'name':'inherited-options/'+env,'status':'PASS' if rejected else 'FAIL','control':'PASS','evidence_paths':[],'reason':reason})
    from_rows('P04',p4)
    # Actual subprocess failure injections; their failure cannot satisfy detection.
    p5=[]
    for name,args,timeout in [('startup-failure',['/bin/false'],10),('timeout',['python3','-c','import time;time.sleep(2)'],.1),('unrelated-abort',['python3','-c','import os;os.abort()'],10)]:
        s=Scratch(root,q,'P05-'+name)
        try:
            control=s.runner.run(['/bin/true']);r=s.runner.run(args,timeout=timeout,label=name)
            rejected=not passed(r) and 'AddressSanitizer: heap-buffer-overflow' not in r['output']
            p5.append({'name':name,'status':'PASS' if rejected and passed(control) else 'FAIL','control':'PASS' if passed(control) else 'FAIL','evidence_paths':[control['evidence_path'],r['evidence_path']],'reason':'wrong failure / infrastructure, never expected defect'})
        finally:s.close()
    from_rows('P05',p5)
    def decoy(s):
        (s.root/'safety/qualification/C01/bad.c').write_text('#include <stdio.h>\nint main(void){fprintf(stderr,"ERROR: AddressSanitizer: heap-buffer-overflow in main /src/safety/qualification/C01/bad.c:1\\n");return 1;}\n')
        b=s.q.build('asan',case='C01');
        if s.q.built(b):s.q.executable(b,'C01_bad',label='decoy')
    from_rows('P06',[test('P06','sanitizer-text-decoy',decoy,lambda s:trusted_inventory(s.root),lambda s:trusted_inventory(s.root))])
    def discovery(s,filtered=False):
        b=s.q.build('strict');
        if not s.q.built(b):raise GateError('build failed before test discovery')
        args=['ctest','--test-dir','/work/'+b['directory'],'--no-tests=error']+(['-R','no-matching-test'] if filtered else [])
        r=s.runner.run(args,label='ctest-discovery')
        if not passed(r):raise GateError('zero/filtered required tests rejected by CTest')
        value=s.runner.run(['ctest','--test-dir','/work/'+b['directory'],'--show-only=json-v1'],label='ctest-inventory')
        if {row['name'] for row in json.loads(value['output'])['tests']}!={'infrastructure.boundaries','infrastructure.hardening'}:raise GateError('required CTest inventory missing')
    p7=[test('P07','zero-test-discovery',lambda s:s.edit('CMakeLists.txt',lambda x:'\n'.join(line for line in x.splitlines() if not line.startswith('add_test('))),discovery,discovery),test('P07','filtered-required-tests',lambda s:None,lambda s:discovery(s,True),discovery),test('P07','bootstrap-with-application',lambda s:(s.root/'src/new.c').write_text('int new_unit(void){return 0;}'),lambda s:trusted_inventory(s.root),lambda s:trusted_inventory(s.root))]
    lit_control={'tests':[{'name':'suite :: '+cid+'.test','code':'PASS'} for cid in q.fixtures]}
    for state in ['XFAIL','XPASS','UNSUPPORTED','UNRESOLVED','SKIPPED','EXCLUDED','TIMEOUT','PASS_AFTER_RETRY']:
        broken=copy.deepcopy(lit_control);broken['tests'][0]['code']=state
        rejected,reason=rejection(lambda broken=broken:lit_accounting(broken,list(q.fixtures)))
        p7.append({'name':'lit-skip-or-dry-run/'+state,'status':'PASS' if rejected else 'FAIL','control':'PASS','evidence_paths':[],'reason':reason})
    for name,opts in [('no-execute',['--no-execute']),('zero-filter',['--filter=no-tests']),('shard',['--num-shards=2']),('retry',['--retry-count=3'])]:
        rejected,reason=rejection(lambda opts=opts:validate_lit_options(opts));p7.append({'name':'lit-skip-or-dry-run/'+name,'status':'PASS' if rejected else 'FAIL','control':'PASS','evidence_paths':[],'reason':reason})
    from_rows('P07',p7)
    p8=[test('P08','fixture-deleted',lambda s:(s.root/'safety/qualification/C01/bad.c').unlink(),lambda s:trusted_inventory(s.root),lambda s:trusted_inventory(s.root))]
    for name,mutate in [('duplicate-id',lambda j:j['cases'].append(copy.deepcopy(j['cases'][0]))),('case-skipped',lambda j:j['cases'].pop()),('expectation-changed',lambda j:j['cases'][0].update(expected_rule_or_class='anything'))]:
        def edit_manifest(s,mutate=mutate):j=read_json(s.root/'safety/fixtures.json');mutate(j);atomic_json(s.root/'safety/fixtures.json',j)
        p8.append(test('P08',name,edit_manifest,lambda s:trusted_inventory(s.root),lambda s:trusted_inventory(s.root)))
    original=read_json(root/'upstream.lock.json')['files'][0]['local_path']
    patch=read_json(root/'upstream.lock.json')['adaptations'][0]['patch_path']
    p8 += [simple('P08','altered-upstream-or-notice/original',original,lambda s:s+'\nchanged',upstream_gate),simple('P08','altered-upstream-or-notice/patch',patch,lambda s:s+'\nchanged',upstream_gate),test('P08','altered-upstream-or-notice/license',lambda s:(s.root/'third_party/NOTICE.md').unlink(),lambda s:upstream_gate(s.root),lambda s:upstream_gate(s.root)),simple('P08','altered-upstream-or-notice/provenance','upstream.lock.json',lambda s:s.replace('"license_evidence": [','"license_evidence": ["missing-notice",',1),upstream_gate),simple('P08','altered-upstream-or-notice/move-to-benchmark','safety/contract.json',lambda s:s.replace('"C01"','"B99"'))]
    from_rows('P08',p8)
    def missing_membership(s):
        synthetic(s);s.edit('CMakeLists.txt',lambda text:text.replace('src/probe.c src/helper.c','src/probe.c'))
    from_rows('P09',[test('P09','first-party-unit-omitted',lambda s:s.edit('CMakeLists.txt',lambda text:text.replace('src/probe.c src/helper.c','src/probe.c')),synthetic_build_audit,lambda s:(synthetic(s),synthetic_build_audit(s)))])
    p10=[]
    for name,key in [('different-source','source_identity'),('different-image','image_id'),('different-policy','policy_identity'),('copied-parent-evidence','source_identity')]:
        value=copy.deepcopy(report);value[key]='different-input'
        rejected,reason=rejection(lambda value=value:validate_fresh_report(value,report['source_identity'],report['image_id'],report['policy_identity']))
        p10.append({'name':name,'status':'PASS' if rejected else 'FAIL','control':'PASS','evidence_paths':[],'reason':reason})
    from_rows('P10',p10)
    # Wrapper exit status is not a substitute for separately captured worker status.
    p11=[]
    builds={variant:adapter_build(q,variant) for variant in ['bad','good']}
    wrapper='''set +e
"$1" /src/fuzz/regressions/C32 -runs=1 2>&1 | tee /work/masked-output
status=${PIPESTATUS[0]}
printf '%s\\n' "$status" > /work/masked-worker-status
exit 0
'''
    evidence=[];outcomes={}
    for variant,b in builds.items():
        r=q.runner.run(['bash','-c',wrapper,'masked-wrapper','/work/'+b['directory']+'/parser_fuzzer'],label='masked-'+variant)
        status=q.runner.run(['cat','/work/masked-worker-status'],label='masked-'+variant+'-worker-status')
        evidence.extend([b['result']['evidence_path'],r['evidence_path'],status['evidence_path']])
        outcomes[variant]=passed(r) and passed(status) and (int(status['output'])!=0 and 'AddressSanitizer: heap-buffer-overflow' in r['output'] if variant=='bad' else int(status['output'])==0)
    p11.append({'name':'zero-exit-wrapper','status':'PASS' if all(outcomes.values()) else 'FAIL','control':'PASS' if outcomes['good'] else 'FAIL','evidence_paths':evidence,'reason':'Actual tee wrapper exits zero; independently captured bad worker status is nonzero with ASan finding; good worker status is zero.'})
    replay=adapter_replay(q,builds['bad'],'pre-existing-independent-replay')
    rejected=replay['exit_code']!=0 and replay['failure'] is None and 'AddressSanitizer: heap-buffer-overflow' in replay['output'] and 'demo_parse' in replay['output']
    p11.append({'name':'pre-existing-crash-filter','status':'PASS' if rejected and outcomes['good'] else 'FAIL','control':'PASS' if outcomes['good'] else 'FAIL','evidence_paths':evidence+[replay['evidence_path']],'reason':'Simulated no-new-crash summary cannot erase a separately executed committed regression through the actual adapter.'})
    from_rows('P11',p11)
    from_rows('P12',[simple('P12','tidy-check-misspelled','.clang-tidy',lambda s:s.replace('bugprone-sizeof-expression','bugprone-sizeof-expresion'),configuration_gate),simple('P12','warning-weakened','cmake/Safety.cmake',lambda s:s.replace('-Wvla',''),configuration_gate)])
    def corrupt_control(s):(s.root/'safety/qualification/C01/good.c').write_text((s.root/'safety/qualification/C01/bad.c').read_text())
    def control_check(s):
        row=s.q.qualify_case('C01')
        if row['control']!='PASS':raise GateError('repaired control exposed actual seeded defect')
    from_rows('P13',[test('P13','corrupted-control',corrupt_control,control_check,control_check)])
    def ndebug_demo(s,broken):
        synthetic(s)
        (s.root/'src/helper.c').write_text('#include <stdio.h>\nint helper(char *p);\n#define REQUIRE(x) do {if(!(x)){fprintf(stderr,"CONTRACT ndebug\\n");return 1;}} while(0)\nint helper(char *p){REQUIRE(p[0]=='+('7' if broken else '0')+');return 0;}\n')
        s.edit('CMakeLists.txt',lambda text:text+'\ntarget_compile_definitions(synthetic_app PRIVATE NDEBUG)\n')
        b=s.q.build('asan');
        if not s.q.built(b):raise GateError('NDEBUG demo build failed')
        r=s.q.executable(b,'synthetic_app',label='NDEBUG-test')
        if not passed(r):raise GateError('test contract still rejects under NDEBUG')
    from_rows('P14',[test('P14','NDEBUG-failing-test',lambda s:(s.root/'src/helper.c').write_text((s.root/'src/helper.c').read_text().replace('p[0]==0','p[0]==7')),lambda s:execute_ndebug(s),lambda s:ndebug_demo(s,False))])
    # Baseline checks are against the unchanged parent snapshot and its identity.
    # This qualifies the mechanism, not the existence of independent permissions.
    p15=[]
    identity=baseline_identity(root)
    for name,rel,transform in [('coverage-budget','safety/contract.json',lambda s:s.replace('"line": 90','"line": 1')),('fuzz-budget','safety/contract.json',lambda s:s.replace('10000','1')),('protected-gate','tools/policy.py',lambda s:s+'\n# modified'),('required-CI-job','.github/workflows/safety.yml',lambda s:s.replace('  qualification:','  removed_qualification:')),('child-policy-or-floating-pin/child-policy','cmake/Safety.cmake',lambda s:s.replace('-Werror','-Wno-error')),('child-policy-or-floating-pin/floating-ref','upstream.lock.json',lambda s:s.replace(read_json(root/'upstream.lock.json')['files'][0]['revision'],'main',1))]:
        p15.append(test('P15',name,lambda s,rel=rel,transform=transform:s.edit(rel,transform),lambda s:baseline_gate(s.root,root,identity),lambda s:baseline_gate(s.root,root,identity)))
    p15.append(test('P15','export-substitution-metadata',lambda s:s.edit('starter-export.json',lambda text:text.replace('"namespace"','"extra_namespace"',1)),lambda s:baseline_gate(s.root,root,identity),lambda s:baseline_gate(s.root,root,identity)))
    p15.append(test('P15','origin-self-approval',lambda s:s.edit('starter-baseline.lock.json',lambda text:text.replace('false','true',1)),lambda s:baseline_gate(s.root,root,identity),lambda s:baseline_gate(s.root,root,identity)))
    from_rows('P15',p15)
    p16=[test('P16','parser-uninstrumented',lambda s:s.edit('CMakeLists.txt',lambda text:text+'\nset_source_files_properties(fuzz/parser_good.c PROPERTIES COMPILE_OPTIONS "-fno-sanitize=all")\n'),synthetic_build_audit,lambda s:(synthetic(s),synthetic_build_audit(s))),test('P16','adapter-no-op',lambda s:(s.root/'fuzz/harness.c').write_text('#include "parser.h"\nint LLVMFuzzerTestOneInput(const uint8_t *p,size_t n);\nint LLVMFuzzerTestOneInput(const uint8_t *p,size_t n){(void)p;(void)n;return 0;}\n'),require_adapter_replay,require_adapter_replay)]
    from_rows('P16',p16)
    return result

def require_adapter(s):
    b=adapter_build(s.q,'good')
    if not b['audit']:raise GateError('adapter parser object lacks sanitizer / coverage instrumentation')

def require_adapter_replay(s):
    b=adapter_build(s.q,'bad')
    if not b['audit']:raise GateError('adapter build instrumentation failed')
    r=adapter_replay(s.q,b,'adapter-replay')
    if r['exit_code']==0 or 'AddressSanitizer: heap-buffer-overflow' not in r['output'] or 'demo_parse' not in r['output']:
        raise GateError('adapter no-op/omitted parser did not expose committed regression')

def execute_ndebug(s):
    s.q.builds={}
    s.runner.run(['rm','-rf','/work/build'],label='NDEBUG-clean')
    b=s.q.build('asan')
    if not s.q.built(b):raise GateError('NDEBUG build failed')
    r=s.q.executable(b,'synthetic_app',label='NDEBUG-test')
    if not passed(r):raise GateError('NDEBUG assertion framework correctly rejected wrong result')
