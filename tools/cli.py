from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import uuid
from evidence import GateError, Runner, atomic_json, environment_gate, file_hash, read_json, passed, bounded
from policy import C_IDS, P_IDS, inventory_gate, upstream_gate, source_identity, baseline_identity, baseline_gate, validate_fresh_report, gate_accounting
from qualification import Qualifier, INFRA
from schema_check import validate

ROOT = Path(__file__).resolve().parent.parent

def gate(name, status='PASS', details=None, evidence=()):
    return {'name':name,'status':status,'details':details or {},'evidence_paths':list(evidence)}

def initial_report(root, lock):
    identity, files=source_identity(root)
    status=bounded(['git','-C',str(root),'status','--porcelain=v1','--untracked-files=all']) if (root/'.git').exists() else {'exit_code':1,'failure':None,'output':''}
    source_control={'status':'RECORDED' if passed(status) else 'NO_GIT_CHECKOUT','porcelain':status['output'] if passed(status) else '', 'dirty_and_untracked_file_bytes_included':True}
    return {'schema_version':1,'run_id':uuid.uuid4().hex,'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':'',
        'overall_state':'BLOCKED','local_state':'BLOCKED','enforcement_state':'UNSEALED',
        'source_identity':identity,'source_inventory':files,'source_control':source_control,'policy_identity':file_hash(root/'safety/contract.json'),
        'mandatory_gates':{'expected':read_json(root/'safety/contract.json')['required_gates'],'executed':[]},
        'baseline_identity':baseline_identity(root) if (root/'starter-export.json').exists() else None,
        'image_id':lock['image_id'],'runner':{'architecture':platform.machine(),'kernel':platform.release(),'platform':platform.system(),'image_libc':lock['libc'],'network':'none','source_mount':'read-only','scratch':'2 GiB tmpfs','memory':'3 GiB cgroup','pids':128,'cpus':2},
        'qualification_axes':{'native_code':'BLOCKED','local_docker':'BLOCKED','containment':'BLOCKED','runtime_demo':'BLOCKED','remote_ci':'NOT_RUN','independent_enforcement':'UNSEALED','production_approval':'NOT_REQUESTED'},'containment':{'status':'BLOCKED','reason':'not executed'},'gates':[], 'cases':[{'id':cid,'status':'BLOCKED','classification':'NOT_RUN','detector':'pending','bad':'BLOCKED','control':'BLOCKED','baseline':'BLOCKED','matching_diagnostic':None,'evidence_paths':[],'repetitions':0} for cid in C_IDS],
        'sabotage':[{'id':pid,'status':'BLOCKED','control':'BLOCKED','subcases':[],'evidence_paths':[],'reason':'not executed'} for pid in P_IDS],
        'benchmark':{'execution_status':'BLOCKED','reason':'not executed'},'starter':{'status':'BLOCKED','reason':'not executed'},
        'reuse':{'upstream_integrity':'BLOCKED','lit':'BLOCKED','clusterfuzzlite':{'local_adapter_execution':'BLOCKED','remote_ci_execution':'NOT_RUN','remote_enforcement':'UNSEALED'},'upstream_mapping':'docs/upstream-map.md'},
        'review_protocol':{'status':'BLOCKED','mode':'simulated agent responses; no live model benchmark'},'fuzz':{'status':'BLOCKED'},
        'foundation':{'status':'BLOCKED','reason':'not executed'},
        'application_release_ready':False,'application_coverage':'NOT_APPLICABLE','blockers':[], 'commands':[],
        'limitations':['Finite fixtures do not prove arbitrary C safety.','P06 checks a defined decoy, not arbitrary forged native diagnostics.','Agent accounting checks submitted evidence, not comprehension.','No independently protected baseline or remote enforcement was verified.','First-party publication licensing awaits the owner.','Pinned built image is retained locally; APT rebuild recipe is not snapshot-complete.']}

def doctor(q, *, probes=True):
    q.runner.start()
    container={'status':'PASS','runner':q.runner.launcher.runner_identity,'effective':q.runner.session['effective'],'policy_hash':q.runner.session['policy_hash']}
    script='''import shutil,hashlib,json,sys,subprocess,platform
lock=json.load(open('/src/toolchain.lock.json'))
errors=[]
for name,row in lock['tools'].items():
 p=row['path']
 try:
  if hashlib.sha256(open(p,'rb').read()).hexdigest()!=row['sha256']:errors.append(name+': executable hash changed')
 except OSError:errors.append(name+': unavailable')
if platform.machine()!=lock['architecture']:errors.append('architecture mismatch')
if subprocess.check_output(['getconf','GNU_LIBC_VERSION'],text=True).strip()!=lock['libc']:errors.append('libc mismatch')
print(json.dumps({'errors':errors,'tools':lock['tools']}));sys.exit(bool(errors))'''
    tools=q.runner.run(['python3','-c',script],label='doctor-tool-identities')
    result={'status':'PASS' if passed(tools) else 'BLOCKED','tool_evidence':tools['evidence_path'],'probes':[],'container':container}
    tidy=q.runner.run(['clang-tidy','--verify-config','--config-file=/src/.clang-tidy'],label='doctor-tidy-config')
    checks=q.runner.run(['clang-tidy','--list-checks','--config-file=/src/.clang-tidy'],label='doctor-tidy-checks')
    if not passed(tidy) or not passed(checks) or 'bugprone-sizeof-expression' not in checks['output']:
        result['status']='BLOCKED'
    result['tidy_evidence']=[tidy['evidence_path'],checks['evidence_path']]
    if probes:
        for cid in ['C01','C11','C13','C18','C21','C22','C24','C25','C26','C28']:
            row=q.qualify_case(cid);result['probes'].append(row)
            print(f"doctor {cid}: {row['classification']} / control {row['control']}",flush=True)
            if row['status']!='PASS':result['status']='BLOCKED'
    return result

def production_checks(q, full):
    results=[]
    # Four strict C17 compiler / optimization combinations; fixture-only
    # exceptions never reach these actual normal infrastructure targets.
    for cc in ['gcc','clang']:
        for opt in [0,2]:
            b=q.build('strict',compiler=cc,opt=opt)
            ok=q.built(b)
            evidence=[x['evidence_path'] for x in [b['configure'],b['build'],b['links']] if x]
            if ok:
                ctest=q.runner.run(['ctest','--test-dir','/work/'+b['directory'],'--no-tests=error','--output-on-failure'],label=f'{cc}-O{opt}-ctest')
                discovered=q.runner.run(['ctest','--test-dir','/work/'+b['directory'],'--show-only=json-v1'],label=f'{cc}-O{opt}-discovery')
                try:ids={x['name'] for x in json.loads(discovered['output'])['tests']}
                except (KeyError,ValueError):ids=set()
                ok=passed(ctest) and passed(discovered) and ids=={'infrastructure.boundaries','infrastructure.hardening'}
                evidence += [ctest['evidence_path'],discovered['evidence_path']]
            results.append(gate(f'{cc}-O{opt}','PASS' if ok else 'FAIL',{'build_audit':b['audit']},evidence))
    formatting=q.runner.run(['clang-format','--dry-run','--Werror',*['/src/'+p for p in read_json(q.root/'safety/source-inventory.json')['format_files']]],label='format')
    results.append(gate('format','PASS' if passed(formatting) else 'FAIL',evidence=[formatting['evidence_path']]))
    for name in ['tidy','csa','gcc-analyzer','ast']:
        output=[];ok=True
        for rel in INFRA:
            from foundation import analysis_flags
            flags=analysis_flags('gcc-O0' if name=='gcc-analyzer' else 'clang-O0')
            if name=='tidy':args=['clang-tidy','--config-file=/src/.clang-tidy','/src/'+rel,'--',*flags]
            elif name=='csa':args=['clang','--analyze',*flags,'-Xanalyzer','-analyzer-output=text','/src/'+rel]
            elif name=='gcc-analyzer':args=['gcc',*flags,'-O0','-fanalyzer','-Wanalyzer-too-complex','-Wanalyzer-symbol-too-complex','-Werror','-c','/src/'+rel,'-o','/work/analysis.o']
            else:args=['python3','/src/container/foundation-policy.py',rel,'clang-O0','normal-'+str(INFRA.index(rel))]
            r=q.runner.run(args,label='normal-'+name);output.append(r['evidence_path'])
            clean=passed(r)
            if name=='csa':clean=clean and 'warning:' not in r['output']
            if name=='ast':
                clean=clean and json.loads(r['output']).get('status')=='PASS'
            ok=ok and clean
        results.append(gate(name,'PASS' if ok else 'FAIL',{'source_coverage':INFRA},output))
    if full:
        for profile in ['asan','ubsan','integer','msan','tsan','coverage','hardened']:
            b=q.build(profile)
            ok=q.built(b);evidence=[r['evidence_path'] for r in [b['configure'],b['build']] if r]
            if ok:
                for target in ['infrastructure_demo','hardening_probe','runtime_demo']:
                    env={'LLVM_PROFILE_FILE':'/work/'+profile+'-'+target+'.profraw'} if profile=='coverage' else None
                    r=q.executable(b,target,env=env);ok=ok and passed(r);evidence.append(r['evidence_path'])
                if profile=='coverage':
                    merged=q.runner.run(['llvm-profdata','merge','-sparse','/work/coverage-infrastructure_demo.profraw','-o','/work/demo.profdata'],label='coverage-merge')
                    cov=q.runner.run(['llvm-cov','export','/work/'+b['directory']+'/infrastructure_demo','-instr-profile=/work/demo.profdata'],label='coverage-export')
                    try:
                        value=json.loads(cov['output']);summary=value['data'][0]['totals'];covered=summary['lines']['covered'];total=summary['lines']['count'];branches=summary['branches'];ok=ok and passed(merged) and passed(cov) and 0<covered<total and 0<branches['covered']<branches['count']
                    except (KeyError,ValueError):summary={};ok=False
                    evidence.extend([merged['evidence_path'],cov['evidence_path']])
                if profile=='hardened':
                    elf=q.runner.run(['readelf','--wide','-h','-l','-d','-s','/work/'+b['directory']+'/hardening_probe'],label='hardening-ELF')
                    text=elf['output'];ok=ok and passed(elf) and all(x in text for x in ['DYN','GNU_RELRO','BIND_NOW','__stack_chk_fail']) and bool(__import__('re').search(r'__(?:v)?snprintf_chk',text)) and bool(__import__('re').search(r'GNU_STACK[^\n]*\bRW\b',text))
                    evidence.append(elf['evidence_path'])
            details={'build_audit':b['audit']}
            if profile=='coverage':details['demonstration_totals']=summary if ok else {}
            results.append(gate(profile,'PASS' if ok else 'FAIL',details,evidence))
    results.append(gate('integration','PASS' if all(r['status']=='PASS' for r in results[:4]) else 'FAIL',{'ctest_required':['infrastructure.boundaries','infrastructure.hardening'],'compiler_variants':4,'executed_tests':8}))
    return results

def finish(root, report, runner, command):
    runner.close()
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    report['commands'].append('./tools/safety '+command)
    report['mandatory_gates']['executed']=[row['name'] for row in report['gates']]
    if command=='ci':
        try:
            accounting=gate_accounting(report['gates'],report['mandatory_gates']['expected'])
            report['gates'].append(gate('gate-inventory',details=accounting))
        except GateError as exc:
            report['gates'].append(gate('gate-inventory','FAIL',{'reason':str(exc)}))
    report['local_state']='PASS' if report['gates'] and all(r['status']=='PASS' for r in report['gates']) else 'FAIL'
    # Only complete CI can receive the unsealed local qualification state.
    complete = command=='ci' and report['foundation'].get('status')=='PASS' and report['containment'].get('status')=='PASS' and report['local_state']=='PASS' and all(r['status']=='PASS' for r in report['cases']+report['sabotage'])
    report['qualification_axes']={'native_code':'PASS' if all(r['status']=='PASS' for r in report['cases']+report['sabotage']) else 'BLOCKED' if all(r['status']=='BLOCKED' for r in report['cases']) else 'FAIL','local_docker':'PASS' if runner.launcher.records and all(r['effective'] and r['lifecycle'] and r['lifecycle']['removed'] for r in runner.launcher.records) else 'BLOCKED','containment':report['containment']['status'],'runtime_demo':report['containment'].get('runtime_demo',{}).get('status',next((g['status'] for g in report['gates'] if g['name']=='runtime-demo'),'BLOCKED')),'remote_ci':'NOT_RUN','independent_enforcement':'UNSEALED','production_approval':'NOT_REQUESTED'}
    report['overall_state']='VALIDATED_UNSEALED' if complete else 'FAILED' if any(r['status']=='FAIL' for r in report['gates']) else 'BLOCKED'
    if command!='ci':report['blockers'].append('This command is scoped; final aggregate qualification has not passed.')
    if report['containment'].get('status')=='PASS':
        from containment import container_binding_gate,expected_binding
        container_binding_gate(report['containment'],expected_binding(root,runner.launcher.runner_identity,runner.lock['image_id'],runner.launcher.value))
    validate(root,'report',report)
    current,_=source_identity(root)
    validate_fresh_report(report,current,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
    out=root/'artifacts';atomic_json(out/'bootstrap-report.json',report)
    counted=sum(r['classification']=='DETECTED_EXPECTED' for r in report['cases']);controls=sum(r['control']=='PASS' for r in report['cases']);pcount=sum(r['status']=='PASS' for r in report['sabotage'])
    lines=[f"# Bootstrap report: {report['overall_state']}",f"Run `{report['run_id']}`; local `{report['local_state']}`; enforcement `{report['enforcement_state']}`.",f"Source `{report['source_identity']}`; starter `{report['baseline_identity']}`; image `{report['image_id']}`.",f"C defects: {counted}/34; controls: {controls}/34; pipeline cases: {pcount}/16.","Application release readiness: false. Application coverage: not applicable.","",'| Case | Detector | Classification | Control |','|---|---|---|---|']
    lines += [f"| {r['id']} | {r['detector']} | {r['classification']} | {r['control']} |" for r in report['cases']]
    lines += ['', '| Pipeline | Status | Required subcases |','|---|---|---|']
    lines += [f"| {r['id']} | {r['status']} | "+'; '.join(x['name']+': '+x['status'] for x in r['subcases'])+' |' for r in report['sabotage']]
    foundation=report['foundation']
    lines += ['', 'Foundation: '+foundation['status']+'; allocation profile `glib-fail-stop`.', '', '| Foundation | Classification | Control | Subchecks |', '|---|---|---|---|']
    lines += [f"| {r['id']} | {r.get('classification','BLOCKED')} | {r['control']} | "+'; '.join(s['name']+': '+s['status'] for s in r['subchecks'])+' |' for r in foundation.get('cases',[])]
    if 'coverage' in foundation:
        lines += ['', 'Foundation-only coverage: '+json.dumps(foundation['coverage'].get('totals',{})),
                  'Foundation fuzz: '+foundation['fuzz']['status']+'; runtime: '+foundation['runtime']['status']+'.',
                  'Detailed foundation profiles, identities, allocation experiment and scope: `artifacts/foundation-qualification-report.json` and `.md`.']
    lines+=['','Blockers:']+[f'- {x}' for x in report['blockers']]
    lines+=['','Limits:']+[f'- {x}' for x in report['limitations']]
    lines+=['','Reproduce: `'+report['commands'][-1]+'`. Complete bounded logs and commands are listed in the JSON evidence paths.','', 'Detailed integration results:', '```json',json.dumps({k:report[k] for k in ['benchmark','starter','reuse','review_protocol','fuzz','containment']},indent=2),'```']
    (out/'bootstrap-report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(runner.run_dir/'bootstrap-report.json',report)
    print(f"{report['overall_state']}: C {counted}/34, controls {controls}/34, P {pcount}/16; artifacts/bootstrap-report.json",flush=True)
    return 0 if complete or (command!='ci' and report['local_state']=='PASS') else 1


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',type=Path,default=ROOT)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--expected-baseline')
    parser.add_argument('--instance',action='store_true',help='Externally selected instance contract; requires trusted baseline and identity')
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ['bootstrap','doctor','check-fast','check-full','selftest','ci']:subs.add_parser(name)
    f=subs.add_parser('fuzz');f.add_argument('--profile',choices=['smoke','extended'],required=True)
    r=subs.add_parser('report');r.add_argument('--format',choices=['json'],required=True)
    u=subs.add_parser('upstream');u.add_argument('operation',choices=['verify'])
    b=subs.add_parser('benchmark');b.add_argument('--suite',choices=['curated'],required=True)
    s=subs.add_parser('starter');s.add_argument('operation',choices=['verify'])
    i=subs.add_parser('instantiate');i.add_argument('--destination',type=Path,required=True);i.add_argument('--name',required=True)
    sb=subs.add_parser('sandbox');sb.add_argument('operation',choices=['doctor','plan','selftest']);sb.add_argument('--profile',default='build')
    rt=subs.add_parser('runtime');rt.add_argument('operation',choices=['smoke'])
    fd=subs.add_parser('foundation');fd.add_argument('operation',choices=['doctor','check','selftest'])
    args=parser.parse_args(argv);root=args.candidate.resolve()
    sandbox_doctor=args.command=='sandbox' and args.operation=='doctor'
    if args.command=='sandbox' and args.operation=='selftest':args.command='ci'
    elif sandbox_doctor:args.command='doctor'
    try:
        environment_gate()
        if args.instance and (not args.baseline or not args.expected_baseline):raise GateError('instance selection requires an external baseline and identity')
        if args.command=='report':
            report=read_json(root/'artifacts/bootstrap-report.json');validate(root,'report',report)
            current,_=source_identity(root);validate_fresh_report(report,current,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
            from containment import fresh_container_evidence
            fresh_container_evidence(root,report,read_json(root/'toolchain.lock.json'))
            print(json.dumps(report,indent=2));return 0
        if args.command=='instantiate':
            from starter import instantiate
            result=instantiate(root,args.destination,args.name,baseline=args.baseline,expected=args.expected_baseline)
            print(json.dumps(result,indent=2));return 0
        if args.command=='upstream':
            print(json.dumps(upstream_gate(root),indent=2));return 0
        lock=read_json(root/'toolchain.lock.json')
        if args.command=='sandbox':
            from container_policy import policy,make_plan
            value=policy(root)
            plan=make_plan(value,lock['image_id'],{},args.profile)
            plan['source_snapshot']='trusted collector supplies a filtered immutable job snapshot'
            print(json.dumps(plan,indent=2));return 0
        report=initial_report(root,lock)
        run_dir=root/'artifacts/runs'/report['run_id'];run_dir.mkdir(parents=True)
        scratch=Path(tempfile.mkdtemp(prefix='safe-c-evidence-'))
        runner=Runner(root,run_dir,lock,scratch);q=Qualifier(root,runner)
        try:
            if args.baseline or args.expected_baseline:
                if not args.baseline or not args.expected_baseline:raise GateError('baseline directory and external identity are both required')
                report['gates'].append(gate('baseline',details=baseline_gate(root,args.baseline.resolve(),args.expected_baseline)))
            else:
                report['blockers'].append('Independent approval / protected CI authority is unavailable; no sealed acceptance claimed.')
            report['gates'].append(gate('inventory',details=inventory_gate(root)))
            validate(root,'fixtures',read_json(root/'safety/fixtures.json'))
            if args.command in ['bootstrap','doctor','check-fast','check-full','selftest','ci']:
                d=doctor(q,probes=args.command in ['bootstrap','doctor'] and not sandbox_doctor);report['gates'].append(gate('doctor',d['status'],d,[d['tool_evidence']]))
            if args.command in ['check-fast','check-full','ci']:
                report['gates']+=production_checks(q,args.command!='check-fast')
            if args.command in ['bootstrap','doctor','check-fast','check-full','selftest','ci','foundation']:
                from foundation import doctor as foundation_doctor, new_report as foundation_new_report
                from foundation_report import check as foundation_check, experiments as foundation_experiments
                if args.command in ['bootstrap','doctor'] or (args.command=='foundation' and args.operation=='doctor'):
                    report['foundation']=foundation_new_report(q)
                    report['foundation']['doctor']=foundation_doctor(q)
                else:
                    report['foundation']=foundation_check(q,full=args.command!='check-fast',fuzz_profile='merge' if args.command=='ci' else 'smoke')
                    components=report['foundation']
                    ok=all(r['status']=='PASS' for r in components['profiles']) and components['policy']['status']=='PASS'
                    if args.command!='check-fast':ok=ok and components['coverage']['status']==components['fuzz']['status']=='PASS'
                    report['gates'].append(gate('foundation-check','PASS' if ok else 'FAIL'))
                report['gates'].append(gate('foundation-doctor',report['foundation']['doctor']['status']))
                if args.command in ['selftest','ci'] or (args.command=='foundation' and args.operation=='selftest'):
                    foundation_experiments(q,report['foundation'])
            if args.command in ['selftest','ci']:
                lit=q.lit()
                completed={row['id']:row for row in lit.pop('case_rows')}
                report['cases']=[completed.get(row['id'],row) for row in report['cases']]
                report['reuse']['lit']=lit
                report['gates'].append(gate('qualification','PASS' if all(x['status']=='PASS' for x in report['cases']) else 'FAIL'))
                report['gates'].append(gate('lit',lit['status'],{},lit['evidence_paths']))
                from sabotage import run_sabotage
                report['sabotage']=run_sabotage(root,q,report)
                report['gates'].append(gate('selftest','PASS' if all(x['status']=='PASS' for x in report['sabotage']) else 'FAIL'))
            if args.command in ['ci','fuzz']:
                from fuzzing import run_fuzz
                report['fuzz']=run_fuzz(q,args.profile if args.command=='fuzz' else 'merge')
                report['reuse']['clusterfuzzlite']=report['fuzz']['clusterfuzzlite']
                report['gates'].append(gate('fuzz',report['fuzz']['status']))
                report['gates'].append(gate('fuzz-replay','PASS' if all(v=='PASS' for v in report['fuzz']['regression_replay'].values()) else 'FAIL'))
                report['gates'].append(gate('fuzz-exploration',report['fuzz']['exploration']['status']))
                report['gates'].append(gate('clusterfuzzlite',report['fuzz']['clusterfuzzlite']['local_adapter_execution']))
            if args.command in ['ci','benchmark']:
                from benchmark import run_benchmark
                report['benchmark']=run_benchmark(q);report['gates'].append(gate('benchmark',report['benchmark']['execution_status']))
            if args.command in ['selftest','ci']:
                from containment import new_report,Suite
                report['containment']=new_report(q)
                Suite(q,report['containment']).run()
            if args.command=='runtime':
                from runtime import runtime_smoke
                value=runtime_smoke(q);report['gates'].append(gate('runtime-demo',value['status'],value))
            if 'cases' in report['foundation'] and 'functional' in report['foundation']:
                from runtime import runtime_smoke
                from foundation_report import project
                from foundation_pipeline import run as foundation_pipeline
                report['foundation']['runtime']=report['containment'].get('runtime_demo',{}) or runtime_smoke(q)
                project(q,report['foundation'])
                report['foundation']['sabotage']=foundation_pipeline(q,report['foundation'])
            if args.command in ['ci','starter','selftest'] or (args.command=='foundation' and args.operation=='selftest'):
                from starter import verify_starter
                report['starter']=verify_starter(root,lock,run_dir,instance=args.instance,expected=args.expected_baseline,baseline=args.baseline);report['gates'].append(gate('starter',report['starter']['status']))
            if 'cases' in report['foundation']:
                from foundation_report import project,save as foundation_save
                project(q,report['foundation'],report['starter'])
                foundation_save(q,report['foundation'])
                if 'functional' in report['foundation']:
                    report['gates'].append(gate('foundation-selftest',report['foundation']['status']))
                    added=report['foundation']['sabotage']
                    report['gates'].append(gate('foundation-sabotage','PASS' if all(r['status']=='PASS' and r['control']=='PASS' for r in added) else 'FAIL'))
                    if args.command in ['selftest','ci']:
                        for parent in report['sabotage']:
                            parent['subcases'] += [{k:v for k,v in row.items() if k!='parent'} for row in added if row['parent']==parent['id']]
            if args.command in ['check-fast','check-full','ci','selftest']:
                tests=runner.run(['python3','-m','unittest','discover','-s','/src/tests/unit','-v'],label='python-unit-tests')
                ok=passed(tests) and __import__('re').search(r'Ran [1-9][0-9]* tests',tests['output']) is not None
                report['gates'].append(gate('unit','PASS' if ok else 'FAIL',evidence=[tests['evidence_path']]))
                report['gates'][-1]['details']={'executed_tests':int(__import__('re').search(r'Ran ([1-9][0-9]*) tests',tests['output']).group(1)) if ok else 0}
                if args.command in ['selftest','ci']:
                    from protocol import run_protocol
                    report['review_protocol']=run_protocol(q)
                    report['gates'].append(gate('review-protocol',report['review_protocol']['status'],evidence=report['review_protocol']['evidence_paths']))
            if args.command in ['selftest','ci']:
                from containment import routing,container_sabotage,save
                routing(q,report['containment'],report,instance=args.instance)
                added=container_sabotage(q,report['containment']);report['containment']['sabotage']=added
                for parent in report['sabotage']:
                    parent['subcases'] += [{k:v for k,v in row.items() if k!='parent'} for row in added if row['parent']==parent['id']]
                    parent['control']='PASS' if all(s['control']=='PASS' for s in parent['subcases']) else 'FAIL'
                    parent['status']='PASS' if all(s['status']=='PASS' and s['control']=='PASS' for s in parent['subcases']) else 'FAIL'
                report['containment']['status']='PASS' if all(r['status']=='PASS' for r in report['containment']['cases']+added) else 'FAIL'
                save(q,report['containment'])
                report['gates'].append(gate('containment',report['containment']['status']))
                report['gates'].append(gate('container-sabotage','PASS' if all(r['status']=='PASS' for r in added) else 'FAIL'))
                report['gates'].append(gate('runtime-demo',report['containment']['runtime_demo'].get('status','BLOCKED')))
            upstream=upstream_gate(root);report['reuse']['upstream_integrity']=upstream
            report['gates'].append(gate('upstream',details=upstream))
            return finish(root,report,runner,args.command)
        except (GateError, OSError, ValueError, KeyError) as exc:
            report['blockers'].append(str(exc));report['gates'].append(gate('infrastructure','BLOCKED',{'reason':str(exc)}))
            return finish(root,report,runner,args.command)
        finally:
            runner.close();shutil.rmtree(scratch,ignore_errors=True)
    except (GateError,OSError,ValueError) as exc:
        print('BLOCKED: '+str(exc));return 1

if __name__=='__main__':
    raise SystemExit(main())
