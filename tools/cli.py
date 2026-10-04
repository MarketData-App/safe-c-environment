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
from evidence import GateError, Runner, atomic_json, environment_gate, file_hash, read_json, passed
from policy import C_IDS, P_IDS, inventory_gate, upstream_gate, source_identity, baseline_identity, baseline_gate, validate_fresh_report
from qualification import Qualifier, INFRA
from schema_check import validate

ROOT = Path(__file__).resolve().parent.parent

def gate(name, status='PASS', details=None, evidence=()):
    return {'name':name,'status':status,'details':details or {},'evidence_paths':list(evidence)}

def initial_report(root, lock):
    identity, files=source_identity(root)
    return {'schema_version':1,'run_id':uuid.uuid4().hex,'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':'',
        'overall_state':'BLOCKED','local_state':'BLOCKED','enforcement_state':'UNSEALED',
        'source_identity':identity,'source_inventory':files,'policy_identity':file_hash(root/'safety/contract.json'),
        'baseline_identity':baseline_identity(root) if (root/'starter-export.json').exists() else None,
        'image_id':lock['image_id'],'runner':{'architecture':platform.machine(),'kernel':platform.release(),'platform':platform.system(),'image_libc':lock['libc'],'network':'none','source_mount':'read-only','scratch':'2 GiB tmpfs','memory':'3 GiB cgroup','pids':128,'cpus':2},
        'gates':[], 'cases':[{'id':cid,'status':'BLOCKED','classification':'NOT_RUN','detector':'pending','bad':'BLOCKED','control':'BLOCKED','baseline':'BLOCKED','matching_diagnostic':None,'evidence_paths':[],'repetitions':0} for cid in C_IDS],
        'sabotage':[{'id':pid,'status':'BLOCKED','control':'BLOCKED','subcases':[],'evidence_paths':[],'reason':'not executed'} for pid in P_IDS],
        'benchmark':{'execution_status':'BLOCKED','reason':'not executed'},'starter':{'status':'BLOCKED','reason':'not executed'},
        'reuse':{'upstream_integrity':'BLOCKED','lit':'BLOCKED','clusterfuzzlite':{'local_adapter_execution':'BLOCKED','remote_ci_execution':'NOT_RUN','remote_enforcement':'UNSEALED'},'upstream_mapping':'docs/upstream-map.md'},
        'review_protocol':{'status':'BLOCKED','mode':'simulated agent responses; no live model benchmark'},'fuzz':{'status':'BLOCKED'},
        'application_release_ready':False,'application_coverage':'NOT_APPLICABLE','blockers':[], 'commands':[],
        'limitations':['Finite fixtures do not prove arbitrary C safety.','P06 checks a defined decoy, not arbitrary forged native diagnostics.','Agent accounting checks submitted evidence, not comprehension.','No independently protected baseline or remote enforcement was verified.','First-party publication licensing awaits the owner.','Pinned built image is retained locally; APT rebuild recipe is not snapshot-complete.']}

def doctor(q, *, probes=True):
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
    result={'status':'PASS' if passed(tools) else 'BLOCKED','tool_evidence':tools['evidence_path'],'probes':[]}
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
            if name=='tidy':args=['clang-tidy','--config-file=/src/.clang-tidy','/src/'+rel,'--','-std=c17','-I/src/fuzz']
            elif name=='csa':args=['clang','--analyze','-std=c17','-I/src/fuzz','-Xanalyzer','-analyzer-output=text','/src/'+rel]
            elif name=='gcc-analyzer':args=['gcc','-std=c17','-I/src/fuzz','-O0','-fanalyzer','-Wanalyzer-too-complex','-Wanalyzer-symbol-too-complex','-Werror','-c','/src/'+rel,'-o','/work/analysis.o']
            else:args=['clang','-std=c17','-I/src/fuzz','-Xclang','-ast-dump=json','-fsyntax-only','/src/'+rel]
            r=q.runner.run(args,label='normal-'+name);output.append(r['evidence_path'])
            clean=passed(r)
            if name=='csa':clean=clean and 'warning:' not in r['output']
            if name=='ast':
                from qualification import ast_banned_calls
                clean=clean and not ast_banned_calls(json.loads(r['output']))
            ok=ok and clean
        results.append(gate(name,'PASS' if ok else 'FAIL',{'source_coverage':INFRA},output))
    if full:
        for profile in ['asan','ubsan','integer','msan','tsan','coverage','hardened']:
            b=q.build(profile)
            ok=q.built(b);evidence=[r['evidence_path'] for r in [b['configure'],b['build']] if r]
            if ok:
                for target in ['infrastructure_demo','hardening_probe']:
                    env={'LLVM_PROFILE_FILE':'/work/'+profile+'-'+target+'.profraw'} if profile=='coverage' else None
                    r=q.executable(b,target,env=env);ok=ok and passed(r);evidence.append(r['evidence_path'])
                if profile=='coverage':
                    merged=q.runner.run(['llvm-profdata','merge','-sparse','/work/coverage-infrastructure_demo.profraw','-o','/work/demo.profdata'],label='coverage-merge')
                    cov=q.runner.run(['llvm-cov','export','/work/'+b['directory']+'/infrastructure_demo','-instr-profile=/work/demo.profdata'],label='coverage-export')
                    try:
                        value=json.loads(cov['output']);summary=value['data'][0]['totals'];covered=summary['lines']['covered'];total=summary['lines']['count'];ok=ok and passed(merged) and passed(cov) and 0<covered<total
                    except (KeyError,ValueError):summary={};ok=False
                    evidence.extend([merged['evidence_path'],cov['evidence_path']])
                if profile=='hardened':
                    elf=q.runner.run(['readelf','-h','-l','-d','-s','/work/'+b['directory']+'/hardening_probe'],label='hardening-ELF')
                    text=elf['output'];ok=ok and passed(elf) and all(x in text for x in ['DYN','GNU_RELRO','BIND_NOW','__stack_chk_fail']) and bool(__import__('re').search(r'GNU_STACK[^\n]*\n[^\n]*RW\s',text))
                    evidence.append(elf['evidence_path'])
            results.append(gate(profile,'PASS' if ok else 'FAIL',{'build_audit':b['audit']},evidence))
    return results

def finish(root, report, runner, command):
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    report['commands'].append('./tools/safety '+command)
    report['local_state']='PASS' if report['gates'] and all(r['status']=='PASS' for r in report['gates']) else 'FAIL'
    # Only complete CI can receive the unsealed local qualification state.
    complete = command=='ci' and report['local_state']=='PASS' and all(r['status']=='PASS' for r in report['cases']+report['sabotage'])
    report['overall_state']='VALIDATED_UNSEALED' if complete else 'BLOCKED' if report['blockers'] else 'FAILED'
    if command!='ci':report['blockers'].append('This command is scoped; final aggregate qualification has not passed.')
    validate(root,'report',report)
    current,_=source_identity(root)
    validate_fresh_report(report,current,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
    out=root/'artifacts';atomic_json(out/'bootstrap-report.json',report)
    counted=sum(r['classification']=='DETECTED_EXPECTED' for r in report['cases']);controls=sum(r['control']=='PASS' for r in report['cases']);pcount=sum(r['status']=='PASS' for r in report['sabotage'])
    lines=[f"# Bootstrap report: {report['overall_state']}",f"Run `{report['run_id']}`; local `{report['local_state']}`; enforcement `{report['enforcement_state']}`.",f"Source `{report['source_identity']}`; starter `{report['baseline_identity']}`; image `{report['image_id']}`.",f"C defects: {counted}/34; controls: {controls}/34; pipeline cases: {pcount}/16.","Application release readiness: false. Application coverage: not applicable.","",'| Case | Detector | Classification | Control |','|---|---|---|---|']
    lines += [f"| {r['id']} | {r['detector']} | {r['classification']} | {r['control']} |" for r in report['cases']]
    lines += ['', '| Pipeline | Status | Required subcases |','|---|---|---|']
    lines += [f"| {r['id']} | {r['status']} | "+'; '.join(x['name']+': '+x['status'] for x in r['subcases'])+' |' for r in report['sabotage']]
    lines+=['','Blockers:']+[f'- {x}' for x in report['blockers']]
    lines+=['','Limits:']+[f'- {x}' for x in report['limitations']]
    lines+=['','Reproduce: `'+report['commands'][-1]+'`. Complete bounded logs and commands are listed in the JSON evidence paths.','', 'Detailed integration results:', '```json',json.dumps({k:report[k] for k in ['benchmark','starter','reuse','review_protocol','fuzz']},indent=2),'```']
    (out/'bootstrap-report.md').write_text('\n\n'.join(lines)+'\n')
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
    args=parser.parse_args(argv);root=args.candidate.resolve()
    try:
        environment_gate()
        if args.command=='report':
            report=read_json(root/'artifacts/bootstrap-report.json');validate(root,'report',report)
            current,_=source_identity(root);validate_fresh_report(report,current,read_json(root/'toolchain.lock.json')['image_id'],file_hash(root/'safety/contract.json'))
            print(json.dumps(report,indent=2));return 0
        if args.command=='instantiate':
            from starter import instantiate
            result=instantiate(root,args.destination,args.name,baseline=args.baseline,expected=args.expected_baseline)
            print(json.dumps(result,indent=2));return 0
        if args.command=='upstream':
            print(json.dumps(upstream_gate(root),indent=2));return 0
        lock=read_json(root/'toolchain.lock.json');report=initial_report(root,lock)
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
                d=doctor(q,probes=args.command in ['bootstrap','doctor']);report['gates'].append(gate('doctor',d['status'],d,[d['tool_evidence']]))
            if args.command in ['check-fast','check-full','ci']:
                report['gates']+=production_checks(q,args.command!='check-fast')
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
                report['fuzz']=run_fuzz(q,args.profile if args.command=='fuzz' else 'smoke')
                report['reuse']['clusterfuzzlite']=report['fuzz']['clusterfuzzlite']
                report['gates'].append(gate('fuzz',report['fuzz']['status']))
            if args.command in ['ci','benchmark']:
                from benchmark import run_benchmark
                report['benchmark']=run_benchmark(q);report['gates'].append(gate('benchmark',report['benchmark']['execution_status']))
            if args.command in ['ci','starter']:
                from starter import verify_starter
                report['starter']=verify_starter(root,lock,run_dir,instance=args.instance,expected=args.expected_baseline,baseline=args.baseline);report['gates'].append(gate('starter',report['starter']['status']))
            if args.command in ['check-fast','check-full','ci','selftest']:
                tests=runner.run(['python3','-m','unittest','discover','-s','/src/tests/unit','-v'],label='python-unit-tests')
                ok=passed(tests) and __import__('re').search(r'Ran [1-9][0-9]* tests',tests['output']) is not None
                report['gates'].append(gate('unit','PASS' if ok else 'FAIL',evidence=[tests['evidence_path']]))
                report['review_protocol']={'status':'PASS' if ok else 'FAIL','mode':'protocol tests with simulated agent responses','evidence':tests['evidence_path'],'live_review':'NOT_RUN; no provider enabled'}
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
