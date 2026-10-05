"""Fixed native negative/control experiments, available only to E qualification."""
import ctypes
import importlib.util
import json
import shutil
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,'/src/tools')
from evidence import GateError, bounded, passed, atomic_json, file_hash
from developer_gdb import inspect
from developer_lsp import navigate

CASES={'stripped-symbols','missing-db','stale-db','wrong-db-profile',
       'wrong-generated-context','wrong-loaded-profile','missing-clangd','missing-gdb',
       'denied-tracing','startup-canaries','output-overflow'}


def deny_tracing():
    # An additional filter in this disposable process denies tracing; it never
    # modifies or relaxes the launcher's default filter or any host setting.
    class Instruction(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('length',ctypes.c_ushort),('filter',ctypes.POINTER(Instruction))]
    entries=(Instruction*4)(Instruction(0x20,0,0,0),Instruction(0x15,0,1,101),
                             Instruction(0x06,0,0,0x50001),Instruction(0x06,0,0,0x7fff0000))
    program=Program(4,entries)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(22,2,ctypes.byref(program),0,0)!=0:
        os._exit(97)
    Path("/work/tracing-denial-installed").write_text("installed")


def main(case):
    if case not in CASES:raise GateError('unknown protected developer experiment')
    spec=importlib.util.spec_from_file_location('developer_native_job','/src/container/developer-job.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    request={'operation':'build','target':'developer_demo','profile':'debug',
             'demo_workspace':'protected-e-experiment','context_namespace':'0'*64,'state_restored':False}
    job=module.Job(request)
    context=job.complete()
    output=Path('/work/developer-job')
    expected=json.loads(Path('/src/safety/qualification/developer/expectations.json').read_text())
    point=expected['candidate_breakpoint']
    debug=dict(request,recipe='breakpoint',location=point['file']+':'+str(point['line']),
               values=['offset'],arguments=['pair'],steps=1)
    from developer_lsp import navigate
    control_directory=output/'passing-control'
    control_directory.mkdir()
    control_debug=inspect(debug,'developer_demo',job.policy,control_directory)
    text=Path('/fixture/candidate.c').read_text().splitlines()
    control_nav=navigate(dict(request,operation='nav',kind='definition',file='demo/candidate.c',
        line=point['line'],column=text[point['line']-1].index('sc_bytes_read_u16be')+1),job.database,job.targets,job.policy)
    control_ok=(control_debug['debug_session_status']=='PASS' and control_debug['values'].get('offset')=='0' and
                bool(control_nav['result']) and control_nav['server_shutdown_complete'])
    atomic_json(control_directory/'observation.opaque.json',{'status':'PASS' if control_ok else 'FAIL',
                'debugger':control_debug,'navigation':control_nav})
    for name in ['clangd.opaque.log','lsp-transport.opaque.jsonl']:
        shutil.copy2(output/name,control_directory/name)
    result={'case':case,'status':'FAIL','control_build':context['status'],
            'source_executable_sha256':file_hash(Path('/work/developer-build/developer_demo')),
            'artifacts':list(job.artifacts),'observations':{}}
    result['control']='PASS' if control_ok else 'FAIL'
    result['artifacts'] += [str(p.relative_to('/work')) for p in control_directory.iterdir() if p.is_file()]
    if not control_ok:return result
    if case=='output-overflow':
        record=bounded(['python3','-c','import os;os.write(1,b"x"*4194305)'],timeout=5,limit=4194304)
        atomic_json(output/'overflow.opaque.json',record)
        result['artifacts'].append('developer-job/overflow.opaque.json')
        result['observations']={k:record[k] for k in ['exit_code','failure','evidence_complete']}
        result['status']='PASS' if record['failure'] and not record['evidence_complete'] else 'FAIL'
        return result
    if case in {'missing-db','stale-db','wrong-db-profile','wrong-generated-context','missing-clangd'}:
        database=Path('/work/developer-build/compile_commands.json')
        if case=='missing-db':database.unlink()
        elif case=='stale-db':database.write_text('[]')
        elif case=='wrong-db-profile':
            rows=json.loads(database.read_text());rows[0]['command']=rows[0]['command'].replace('/opt/foundation/clang-O0','/opt/foundation/clang-O2');database.write_text(json.dumps(rows))
        elif case=='wrong-generated-context':
            rows=json.loads(database.read_text());rows[0]['command']=rows[0]['command'].replace('/opt/foundation/clang-O0/include','/nonexistent-approved-generated-header');database.write_text(json.dumps(rows))
        else:
            import developer_lsp
            original=developer_lsp.subprocess.Popen
            def launch(argv,**kwargs):
                argv=list(argv);argv[0]='/work/nonexistent-required-clangd'
                return original(argv,**kwargs)
            developer_lsp.subprocess.Popen=launch
        native=dict(request,operation='nav',kind='definition',file='demo/candidate.c',
                    line=point['line'],column=1)
        rejected=False
        try:navigate(native,job.database,job.targets,job.policy)
        except (GateError,OSError,ValueError):rejected=True
        result['observations']={'actual_operation_rejected':rejected,'generic_fallback_qualified':False}
        result['status']='PASS' if rejected else 'FAIL'
        for name in ['clangd.opaque.log','lsp-transport.opaque.jsonl']:
            if (output/name).is_file():result['artifacts'].append('developer-job/'+name)
        return result
    binary=Path('/work/developer-build/developer_demo')
    if case=='stripped-symbols':
        stripped=job.run(['objcopy','--strip-debug',str(binary)],'strip-debug-symbols')
        if not passed(stripped):raise GateError('actual stripped-symbol experiment unavailable')
    elif case=='wrong-loaded-profile':
        strings=Path('/work/dependency-profile.dynstr')
        dumped=job.run(['objcopy','--dump-section','.dynstr='+str(strings),str(binary)],'read-profile-rpath')
        if not passed(dumped) or strings.stat().st_size>65536:raise GateError('bounded dynamic string inventory unavailable')
        data=strings.read_bytes()
        old=b'/opt/foundation/clang-O0/lib'
        if data.count(old)!=1:raise GateError('dynamic string experiment requires one exact RPATH')
        strings.write_bytes(data.replace(old,b'/opt/foundation/clang-O2/lib'))
        updated=job.run(['objcopy','--update-section','.dynstr='+str(strings),str(binary)],'wrong-profile-rpath')
        if not passed(updated):raise GateError('bounded profile experiment could not update dynamic string section')

    elif case in {'missing-gdb','denied-tracing'}:
        import developer_gdb
        original=developer_gdb.subprocess.Popen
        def launch(argv,**kwargs):
            argv=list(argv)
            if case=='missing-gdb':argv[0]='/work/nonexistent-required-gdb'
            else:kwargs['preexec_fn']=deny_tracing
            return original(argv,**kwargs)
        developer_gdb.subprocess.Popen=launch
    elif case=='startup-canaries':
        home=Path('/work/debug-home');home.mkdir(exist_ok=True)
        marker='/work/unexpected-gdb-startup'
        (home/'.gdbinit').write_text('shell touch '+marker+'\n')
        Path('/work/.gdbinit').write_text('shell touch '+marker+'\n')
        binary.with_name('developer_demo-gdb.py').write_text('open("/work/unexpected-gdb-startup","w").write("loaded")\n')
        binary.with_name('developer_demo-gdb.gdb').write_text('shell touch '+marker+'\n')
    observation=inspect(debug,'developer_demo',job.policy,output)
    atomic_json(output/'gdb-observation.opaque.json',observation)
    result['artifacts']+=['developer-job/gdb-observation.opaque.json']
    for name in ['gdb-mi.opaque.log','inferior.opaque.log']:
        if (output/name).is_file():result['artifacts'].append('developer-job/'+name)
    complete=observation['debug_session_status']=='PASS' and observation['inspection_requirements_met']
    result['observations']={'debug_session_status':observation['debug_session_status'],
        'inspection_requirements_met':observation['inspection_requirements_met'],
        'inferior_outcome':observation['inferior_outcome'],'error_type':observation.get('error_type'),
        'error_property':observation.get('error_property'),'startup_marker_present':Path('/work/unexpected-gdb-startup').exists(),
        'values':observation['values'],'guards':observation.get('effective_startup')}
    result['status']='PASS' if (complete and not result['observations']['startup_marker_present'] if case=='startup-canaries' else not complete) else 'FAIL'
    if case=='denied-tracing':
        result['observations']['denial_filter_installed']=Path('/work/tracing-denial-installed').is_file()
        result['status']='PASS' if result['status']=='PASS' and result['observations']['denial_filter_installed'] and observation.get('errors') else 'FAIL'
    result['artifacts']=sorted(set(result['artifacts']+job.artifacts))
    return result


if __name__=='__main__':
    try:
        result=main(sys.argv[1]);print(json.dumps(result,ensure_ascii=True))
        raise SystemExit(0 if result['status']=='PASS' else 1)
    except Exception as error:
        print(json.dumps({'status':'FAIL','error_type':type(error).__name__,
                          'property':str(error) if isinstance(error,GateError) else None}))
        raise SystemExit(1)
