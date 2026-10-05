"""Finite negative metadata controls; executes only in the protected container."""
from pathlib import Path
import argparse
import copy
import json
import sys
import tempfile

sys.path.insert(0,'/src/tools')
from evidence import GateError,read_json,atomic_json
from developer_report import feedback,qualification,binding
from developer import configure_parser,request,namespace
from developer_state import pack,restore
from container_policy import make_plan,validate_plan,dispatch_gate,completion_gate
from runtime import runtime_members,inventory_gate
from schema_check import validate


def rejected(operation):
    try:operation()
    except (GateError,OSError,ValueError,KeyError,SystemExit,argparse.ArgumentError):return True
    return False


def main():
    inputs=read_json(Path('/work/developer-record-input.json'))
    policy=read_json(Path('/src/safety/developer-policy.json'))
    inventory=read_json(Path('/src/safety/developer-fixtures.json'))
    original=inputs['debug'];summary=inputs['qualification']
    feedback(original);binding(original,original)
    qualification(summary,inventory,summary['source_identity'],summary['image_id'])
    class TypedParser(argparse.ArgumentParser):
        def error(self,message):raise GateError('unsupported typed developer option')
    parser=TypedParser(exit_on_error=False)
    configure_parser(parser)
    def typed(argv):
        args=parser.parse_args(argv);request(args,policy)
    typed(['debug','--target','developer_demo','--recipe','breakpoint','--location','demo/candidate.c:13'])
    result=[]
    def record(parent,name,variant,operation):
        failed=rejected(operation)
        result.append({'parent':parent,'name':name,'variant':variant,
            'status':'PASS' if failed else 'FAIL','control':'PASS',
            'observation':'rejected' if failed else 'accepted invalid metadata'})
    def altered(change):
        value=copy.deepcopy(original);change(value);return value
    name='dev-tool-or-route-unavailable'
    dispatch={'execution_path':'docker','container_id':'owned','effective':{'verified':True},
              'lifecycle':None,'profile':'build','plan':{'profile':'build'}}
    dispatch_gate(dispatch)
    record('P01',name,'host-route',lambda:dispatch_gate(dict(dispatch,execution_path='host')))
    # The actual removed adapter is a bounded private copy, never /src.
    paths=['tools/developer.py','tools/developer_lsp.py','tools/developer_gdb.py',
           'tools/developer_state.py','tools/developer_workspace.py','tools/developer_report.py',
           'container/developer-job.py','container/developer-argv.py','CMakeLists.txt',
           'cmake/Developer.cmake','cmake/Foundation.cmake','cmake/Safety.cmake',
           'starter-baseline.lock.json','toolchain.lock.json','foundation.lock.json',
           'developer.lock.json','safety/developer-policy.json','safety/contract.json','safety/foundation-api-policy.json']
    with tempfile.TemporaryDirectory(dir='/work') as temporary:
        root=Path(temporary)
        for path in paths:
            dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((Path('/src')/path).read_bytes())
        namespace(root,'debug');(root/'tools/developer_lsp.py').unlink()
        record('P01',name,'adapter',lambda:namespace(root,'debug'))
    name='dev-build-context-mismatch'
    record('P02',name,'binary',lambda:binding(altered(lambda v:v['result']['debugger'].update(executable_sha256='0'*64)),original))
    name='dev-config-or-debugger-injection'
    for variant,args in [('query-driver',['--query-driver','/fixture/compiler']),
        ('config',['--config','/fixture/config']),('plugin',['--plugin','/fixture/plugin']),
        ('arbitrary-gdb-command',['--command','unsafe-operation']),('remote-target',['--target','remote:1234']),
        ('external-pid',['--pid','1']),('profile-override',['--profile','host'])]:
        base=['debug','--target','developer_demo','--recipe','breakpoint','--location','demo/candidate.c:13']
        record('P04',name,variant,lambda a=base+args:typed(a))
    name='dev-inventory-or-partial-success'
    missing=copy.deepcopy(summary);missing['cases'].pop()
    record('P07',name,'missing-case',lambda:qualification(missing,inventory,summary['source_identity'],summary['image_id']))
    malformed=copy.deepcopy(summary);del malformed['cases'][0]['subchecks'][0]['control']
    record('P07',name,'missing-control',lambda:qualification(malformed,inventory,summary['source_identity'],summary['image_id']))
    record('P07',name,'zero-tests',lambda:feedback({'scope':'partial_feedback','acceptance':False,'status':'PASS',
        'result':{'test_result':{'executed_cases':0,'complete_selection':False,'program_result_preserved':True,'ctest_exit_code':0}}}))
    record('P07',name,'partial-index-as-acceptance',lambda:feedback(altered(lambda v:v.update(acceptance=True))))
    name='dev-stale-state'
    for variant,key in [('worktree','context_namespace'),('profile-index','profile')]:
        record('P10',name,variant,lambda key=key:binding(altered(lambda v:v.update({key:'different'})),original))
    with tempfile.TemporaryDirectory(dir='/work') as temporary:
        root=Path(temporary);build=root/'build';build.mkdir();(build/'record.o').write_bytes(b'bounded object')
        pack(build,root/'state','expected',policy['limits'],{'source':'hash'})
        restore(root/'control',root/'state','expected',policy['limits'])
        archive=next((root/'state').glob('*.tar.gz'));archive.write_bytes(archive.read_bytes()+b'altered')
        record('P10',name,'cache-artifact',lambda:restore(root/'negative',root/'state','expected',policy['limits']))
    record('P10',name,'source-symbol-map',lambda:binding(altered(lambda v:v['result']['debugger'].update(breakpoint={'number':'999'})),original))
    record('P10',name,'parent-report',lambda:qualification(dict(summary,source_identity='parent'),inventory,summary['source_identity'],summary['image_id']))
    name='dev-failure-masked'
    record('P11',name,'zero-gdb-after-inferior-failure',lambda:feedback(altered(lambda v:v['result']['debugger'].update(inferior_outcome={'status':'PASSED','exit_code':7}))))
    record('P11',name,'unreached-breakpoint',lambda:feedback(altered(lambda v:v['result']['debugger'].update(stop={'reason':'exited-normally'}))))
    record('P11',name,'replay-child-status',lambda:feedback({'scope':'partial_feedback','acceptance':False,'status':'PASS',
        'result':{'fuzz_result':{'program_result_preserved':True,'exit_code':1}}}))
    record('P11',name,'truncation',lambda:feedback(altered(lambda v:v['result']['debugger'].update(complete_capture=False))))
    valid_life={'state_before':{'Running':False},'state_after':{'Pid':0},'removed':True,'children_reaped':True}
    completion_gate({'exit_code':1,'failure':None,'evidence_complete':True},valid_life)
    record('P11',name,'incomplete-timeout-cleanup',lambda:completion_gate({'exit_code':1,'failure':'TIMEOUT'},dict(valid_life,removed=False)))
    name='dev-policy-or-packaging-downgrade'
    containment=read_json(Path('/src/safety/container-policy.json'))
    image=read_json(Path('/src/developer.lock.json'))['image_id']
    plan=make_plan(containment,image,{},'build');validate_plan(plan,containment,image,{},'build')
    for variant,change in [('limits',lambda v:v['resources'].update(memory_bytes=v['resources']['memory_bytes']+1)),
        ('tracing',lambda v:v.update(capabilities=['SYS_PTRACE']))]:
        changed=copy.deepcopy(plan);change(changed)
        record('P15',name,variant,lambda changed=changed:validate_plan(changed,containment,image,{},'build'))
    validate(Path('/src'),'developer-policy',policy)
    startup=copy.deepcopy(policy);startup['debugger']['auto_load']=True
    record('P15',name,'auto-load',lambda:validate(Path('/src'),'developer-policy',startup))
    cached=copy.deepcopy(policy);cached['compiler_cache']['acceptance_cache_reuse']=True
    record('P15',name,'acceptance-cache',lambda:validate(Path('/src'),'developer-policy',cached))
    runtime={p:'verified hash' for p in runtime_members()};inventory_gate(runtime,runtime)
    record('P15',name,'runtime-payload',lambda:inventory_gate(dict(runtime,**{'usr/bin/gdb':'tool','tools/developer_gdb.py':'adapter'}),runtime))
    path=Path('/work/developer-record-result.json');atomic_json(path,{'status':'PASS' if all(r['status']=='PASS' for r in result) else 'FAIL','variants':result})
    print(json.dumps({'status':'PASS' if all(r['status']=='PASS' for r in result) else 'FAIL',
                     'variants':result,'artifact':'developer-record-result.json'}))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'FAIL','error_type':type(error).__name__}));raise SystemExit(1)
