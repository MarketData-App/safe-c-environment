"""E-suite orchestration using public commands and the protected native launcher."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid
import os
import subprocess

from evidence import Runner, GateError, bounded, atomic_json, file_hash, read_json, passed
from policy import source_identity, source_files
from schema_check import validate
from developer_report import qualification,feedback


class Suite:
    def __init__(self,root,policy,lock,out):
        self.root,self.policy,self.lock,self.out=root,policy,lock,out
        self.inventory=read_json(root/'safety/developer-fixtures.json')
        validate(root,'developer-fixtures',self.inventory)
        self.identity=source_identity(root)[0]
        self.workspace=root/'artifacts/developer/workspaces'/('qualification-'+out.name)
        self.workspace.mkdir(parents=True)
        self.template=(root/'safety/qualification/developer/template.c').read_bytes()
        (self.workspace/'candidate.c').write_bytes(self.template)
        self.expected=read_json(root/'safety/qualification/developer/expectations.json')
        self.calls=[]
        self.native_calls={}
        self.report={'schema_version':1,'status':'BLOCKED','run_id':out.name,
            'source_identity':self.identity,'image_id':lock['image_id'],
            'binding':{'worktree':hashlib.sha256(str(root.resolve()).encode()).hexdigest(),
                       'inputs':{p:file_hash(root/p) for p in ['developer.lock.json','toolchain.lock.json',
                            'foundation.lock.json','safety/developer-policy.json','safety/developer-fixtures.json',
                            'safety/container-policy.json']}},'receipt_hashes':{},
            'cases':[{'id':r['id'],'status':'BLOCKED','control':'BLOCKED',
                     'subchecks':[{'name':name,'status':'BLOCKED','control':'BLOCKED',
                         'evidence_paths':[],'reason':'not executed'} for name in r['subchecks']]} for r in self.inventory['cases']],
            'pipeline_variants':[{'parent':r['parent'],'name':r['name'],'variant':v,
                'status':'BLOCKED','control':'BLOCKED','evidence_paths':[],'reason':'not executed'}
                for r in self.inventory['pipeline_subcases'] for v in r['variants']],
            'commands':[],'measurements':[], 'scripted_workflow_trial':'NOT_EXECUTED',
            'live_agent_trial':'NOT_EXECUTED','independent_enforcement':'PENDING',
            'handoff_ready':False,'application_started':False,'production_authorized':False,
            'limitations':['Finite developer experiments are not application acceptance.',
                'Live trial and independent authority are separate from deterministic CI.']}

    def call(self,operation,*arguments,demo=False,root=None):
        candidate=root or self.root
        argv=[str(Path(__file__).parent/'safety'),'--candidate',str(candidate),'dev',operation,*map(str,arguments),'--format','json']
        if demo:argv+=['--demo-workspace',str(self.workspace.relative_to(self.root))]
        started=time.monotonic()
        record=bounded(argv,timeout=120,limit=4194304)
        path=self.out/('public-%03d-%s.opaque.json'%(len(self.calls),operation))
        atomic_json(path,record)
        try:
            value=json.loads(record['output'])
            feedback(value)
        except (ValueError,TypeError,GateError):
            value={'status':'BLOCKED','reason':'Public entrypoint did not produce valid structured feedback.'}
        observation={'value':value,'exit_code':record['exit_code'],'failure':record['failure'],
                     'path':str(path),'seconds':time.monotonic()-started,'argv':argv}
        self.calls.append(observation)
        self.report['commands'].append({'argv':argv,'exit_code':record['exit_code'],
             'run_id':value.get('run_id'),'evidence_path':str(path)})
        atomic_json(self.out/'progress.json',{'calls':len(self.calls),'operation':operation,
                                            'status':value.get('status')})
        return observation

    @staticmethod
    def good(record):
        return record['exit_code']==0 and record['failure'] is None and record['value'].get('status')=='PASS'

    def observe(self,case,name,condition,records,control,details=None):
        row=next(r for r in self.report['cases'] if r['id']==case)
        item=next(r for r in row['subchecks'] if r['name']==name)
        if item['status']!='BLOCKED' or item['evidence_paths']:
            raise GateError('developer observation was submitted twice')
        item.update(status='PASS' if condition and self.good(control) else 'FAIL',
            control='PASS' if self.good(control) else 'FAIL',
            evidence_paths=sorted({r['path'] for r in [*records,control]}),reason=None,
            details=details or {})
        self.save()

    def native(self,case):
        scratch=Path(tempfile.mkdtemp(prefix='safe-c-e-probe-'))
        directory=self.out/('native-'+case)
        runner=Runner(self.root,directory,dict(read_json(self.root/'toolchain.lock.json'),image_id=self.lock['image_id']),
                      scratch,purpose='development',fixture_root=self.workspace)
        try:
            record=runner.run(['python3','/src/container/developer-qualification.py',case],
                             timeout=90,label='developer-fixed-experiment')
            value=json.loads(record['output'])
            for name in value.get('artifacts',[]):
                if not name.startswith('developer-job/') or '..' in Path(name).parts:
                    raise GateError('developer experiment collection path rejected')
                runner.fetch(name,directory/name)
            observation={'value':value,'exit_code':record['exit_code'],'failure':record['failure'],
                         'path':record['evidence_path'],'seconds':record['seconds']}
            self.native_calls[case]=observation
            return observation
        finally:
            runner.close();shutil.rmtree(scratch,ignore_errors=True)

    def save(self):
        for case in self.report['cases']:
            states=[s['status'] for s in case['subchecks']]
            case['status']='FAIL' if 'FAIL' in states else 'BLOCKED' if 'BLOCKED' in states else 'PASS'
            controls=[s['control'] for s in case['subchecks']]
            case['control']='FAIL' if 'FAIL' in controls else 'BLOCKED' if 'BLOCKED' in controls else 'PASS'
        statuses=[r['status'] for r in self.report['cases']+self.report['pipeline_variants']]
        self.report['status']='FAIL' if 'FAIL' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASS'
        paths={p for case in self.report['cases'] for row in case['subchecks'] for p in row['evidence_paths']}
        paths.update(p for row in self.report['pipeline_variants'] for p in row['evidence_paths'])
        paths.update(row['evidence_path'] for row in self.report['commands'])
        self.report['receipt_hashes']={p:file_hash(Path(p)) for p in sorted(paths)}
        validate(self.root,'developer-report',self.report)
        qualification(self.report,self.inventory,self.identity,self.lock['image_id'])
        atomic_json(self.out/'qualification.json',self.report)

    @staticmethod
    def rebuilt(record):
        return [name for step in record['value'].get('result',{}).get('steps',[])
                for name in step.get('rebuilt_objects',[])]

    def nav(self,kind,symbol=None,file='demo/candidate.c',occurrence=0,**options):
        if kind in {'document-symbols','diagnostics'}:
            return self.call('nav','--kind',kind,'--file',file,demo=True)
        if kind=='workspace-symbols':
            return self.call('nav','--kind',kind,'--symbol',symbol,demo=True)
        native=self.workspace/file.removeprefix('demo/') if file.startswith('demo/') else self.root/file
        matches=[(i+1,line.index(symbol)+1) for i,line in enumerate(native.read_text().splitlines()) if symbol in line]
        line,column=matches[occurrence]
        return self.call('nav','--kind',kind,'--file',file,'--line',line,'--column',column,demo=True)

    @staticmethod
    def locations(record):
        rows=record['value'].get('result',{}).get('navigation',{}).get('result') or []
        return [r.get('mapped_location',{}) for r in rows] if isinstance(rows,list) else []

    def semantic_and_workflow(self,control,definition,header,debug):
        api_type=self.nav('hover','GBytes')
        self.observe('E02','generated-glib-header',self.good(api_type) and
            'GBytes' in json.dumps(api_type['value']['result']['navigation']['result']),[api_type,header],control)
        declaration=self.nav('definition','developer_read_pair',file='safety/qualification/developer/control.c',occurrence=1)
        self.observe('E03','definition-declaration',self.good(declaration) and bool(self.locations(declaration)) and
            self.good(definition),[declaration,definition],control)
        references=self.nav('references','developer_read_pair',occurrence=1)
        locations=self.locations(references)
        self.observe('E03','cross-file-references',self.good(references) and
            {'demo/candidate.c','safety/qualification/developer/control.c','safety/qualification/developer/developer-demo.h'}.issubset(
                {r.get('path') for r in locations}),[references],control)
        decoys=[]
        for name,path in [('demo/candidate.c',self.workspace/'candidate.c'),
                          ('safety/qualification/developer/control.c',self.root/'safety/qualification/developer/control.c')]:
            decoys += [(name,i+1) for i,line in enumerate(path.read_text().splitlines())
                       if 'developer_read_pair' in line and ('/*' in line or '"' in line)]
        self.observe('E03','comment-string-decoys',self.good(references) and bool(locations) and
            all(not any(r.get('path')==name and r.get('range',{}).get('start',{}).get('line')==line for r in locations)
                for name,line in decoys),[references],control,{'excluded_decoy_locations':decoys})
        statics=[self.nav('references','local_marker',file=file) for file in
                 ['demo/candidate.c','safety/qualification/developer/control.c']]
        self.observe('E03','distinct-static-symbols',all(self.good(r) and self.locations(r) and
            all(p.get('path')==file for p in self.locations(r)) for r,file in zip(statics,
                ['demo/candidate.c','safety/qualification/developer/control.c'])),statics,control)
        candidate=self.workspace/'candidate.c'
        candidate.write_bytes(self.template.replace(b'sc_bytes_read_u16be',b'developer_missing_api'))
        invalid=self.nav('diagnostics')
        candidate.write_bytes(self.template)
        repaired=self.nav('diagnostics')
        self.observe('E03','diagnostic-edit-repair',self.good(invalid) and self.good(repaired) and
            any(r.get('severity')==1 for r in invalid['value']['result']['navigation']['result']) and
            not any(r.get('severity')==1 for r in repaired['value']['result']['navigation']['result']),[invalid,repaired],control)
        candidate.write_bytes(self.template.replace(b'return 0;',b'return 1;',1))
        failed=self.call('test','--id','developer.pair',demo=True)
        self.observe('E05','failing-control',failed['exit_code']!=0 and
            failed['value'].get('result',{}).get('test_result',{}).get('executed_cases')==1,[failed],control)
        self.observe('E07','real-test-failure',failed['exit_code']!=0 and
            failed['value'].get('bundle',{}).get('original_replay_available'),[failed],control)
        failed_id=failed['value'].get('run_id')
        diagnosed=self.call('diagnose','--run-id',failed_id)
        replay=self.call('replay','--run-id',failed_id,'--snapshot','original')
        point=self.expected['candidate_breakpoint']
        investigation=self.call('debug','--run-id',failed_id,'--recipe','breakpoint',
            '--location',point['file']+':'+str(point['line']),'--value',point['value'])
        state=investigation['value'].get('result',{}).get('debugger',{})
        candidate.write_bytes(self.template)
        comparison=diagnosed['value']['result']['current_candidate_comparison']
        passing=self.call('test',*comparison['argv'][3:])
        replay_after=self.call('replay','--run-id',failed_id,'--snapshot','original')
        self.observe('E07','original-input-replay',all(r['exit_code']!=0 and
            r['value'].get('result',{}).get('test_result',{}).get('binary_sha256')==
            failed['value']['result']['test_result']['binary_sha256'] for r in [replay,replay_after]),
            [failed,replay,replay_after],control)
        self.observe('E07','current-repair-comparison',comparison['available'] and
            comparison['original_run_id']==failed['value']['run_id'] and self.good(passing) and
            passing['value'].get('demo_source_identity')!=failed['value'].get('demo_source_identity'),[failed,passing],control)
        self.observe('E07','nonzero-preserved',all(r['exit_code']!=0 and r['value'].get('status')=='FAIL'
            for r in [failed,replay,replay_after]),[failed,replay,replay_after],control)
        bundle=self.root/'artifacts/developer/runs'/failed_id/'bundle/binary'
        saved=bundle.with_name('binary.qualification-missing')
        bundle.rename(saved)
        try:missing=self.call('replay','--run-id',failed_id,'--snapshot','original')
        finally:saved.rename(bundle)
        self.observe('E07','tampered-missing-input',missing['exit_code']!=0,[missing,replay],control)
        coverage=self.call('test','--id','developer.pair','--profile','coverage',demo=True)
        view=self.call('coverage','--run-id',coverage['value'].get('run_id'))
        self.observe('E05','matching-coverage',self.good(coverage) and self.good(view) and
            any(r['path']=='demo/candidate.c' for r in view['value']['result'].get('files',[])),[coverage,view],control)
        candidate.write_bytes(self.template+b'\n/* source revision for freshness */\n')
        stale=self.call('coverage','--run-id',coverage['value'].get('run_id'))
        candidate.write_bytes(self.template)
        self.observe('E05','stale-coverage-rejected',stale['exit_code']!=0,[view,stale],control)
        workflow=(all(self.good(r) for r in [control,definition,diagnosed,passing]) and failed['exit_code']!=0 and
            replay['exit_code']!=0 and self.good(investigation) and state.get('values',{}).get(point['value'])==point['mutant_value'])
        self.report['scripted_workflow_trial']='PASSED' if workflow else 'FAILED'
        self.observe('E12','public-command-rehearsal',workflow,[control,definition,failed,diagnosed,replay,investigation,passing],control)

    def incremental_contexts(self,control,warm):
        candidate=self.workspace/'candidate.c'
        self.observe('E06','cold-build',self.good(control) and not
            control['value']['result']['incremental']['restored'] and bool(self.rebuilt(control)),[control],control)
        settled=self.call('build','--target','developer_demo',demo=True)
        unchanged=self.call('build','--target','developer_demo',demo=True)
        self.observe('E06','warm-no-change',self.good(unchanged) and not self.rebuilt(unchanged),[settled,unchanged],control)
        stamp=candidate.stat().st_mtime_ns
        candidate.write_bytes(self.template+b'\n/* qualification revision */\n')
        os.utime(candidate,ns=(stamp,stamp))
        changed=self.call('build','--target','developer_demo',demo=True)
        current=self.nav('document-symbols')
        expected_object='candidate.c.o'
        source_rebuilt=self.good(changed) and any(expected_object in p for p in self.rebuilt(changed))
        self.observe('E06','source-edit',source_rebuilt,[unchanged,changed],control)
        self.observe('E04','source-edit',source_rebuilt and self.good(current),[changed,current],control)
        self.observe('E06','rebuilt-object-identities',source_rebuilt and all(
            len(digest)==64 for step in changed['value']['result']['steps'] for digest in step.get('object_sha256',{}).values()),[changed],control)
        candidate.write_bytes(self.template)
        descriptor=self.workspace/'context.json'
        settings={'schema_version':1,'primary':'candidate.c','extra':False,'generated_value':0,'define_value':0}
        for key,name in [('generated_value','generated-header-edit'),('define_value','define-change')]:
            settings[key]=1;atomic_json(descriptor,settings)
            record=self.call('build','--target','developer_demo',demo=True)
            self.observe('E06',name,self.good(record) and any('candidate.c.o' in p for p in self.rebuilt(record)),[record],control)
            if key=='generated_value':
                nav=self.nav('diagnostics')
                self.observe('E04',name,self.good(record) and self.good(nav),[record,nav],control)
        candidate.rename(self.workspace/'renamed.c');settings['primary']='renamed.c';atomic_json(descriptor,settings)
        renamed=self.nav('document-symbols',file='demo/renamed.c')
        deleted=self.call('nav','--kind','document-symbols','--file','demo/candidate.c',demo=True)
        self.observe('E04','rename-delete',self.good(renamed) and deleted['exit_code']!=0,[renamed,deleted],control)
        (self.workspace/'extra.c').write_text('int developer_extra_marker(void);\nint developer_extra_marker(void) { return 17; }\n')
        settings['extra']=True;atomic_json(descriptor,settings)
        added=self.nav('document-symbols',file='demo/extra.c')
        self.observe('E04','new-registered-file',self.good(added) and bool(
            added['value']['result']['navigation']['result']),[added],control)
        spaced=self.workspace/'path with space/µ.c';spaced.parent.mkdir()
        (self.workspace/'renamed.c').rename(spaced);settings['primary']='path with space/µ.c';atomic_json(descriptor,settings)
        spaced_query=self.nav('definition','sc_bytes_read_u16be',file='demo/path with space/µ.c')
        self.observe('E04','spaces-path',self.good(spaced_query) and bool(self.locations(spaced_query)),[spaced_query],control)
        profile=self.call('prepare','--profile','asan',demo=True)
        self.observe('E04','profile-switch',self.good(profile) and profile['value']['context_namespace']!=control['value']['context_namespace'],[profile,control],control)
        self.observe('E06','profile-switch',self.good(profile) and not profile['value']['result']['incremental']['restored'] and
            bool(self.rebuilt(profile)),[profile,control],control)
        self.observe('E06','optional-cache-absent',self.policy['compiler_cache']['status']=='ABSENT' and
            profile['value']['result']['incremental']['compiler_cache']=='ABSENT',[profile],control)
        self.report['measurements']=[{'run_id':r['value'].get('run_id'),'seconds':r['seconds'],
            'rebuilt_objects':self.rebuilt(r)} for r in [control,warm,unchanged,changed,profile]]
        spaced.rename(candidate);spaced.parent.rmdir();(self.workspace/'extra.c').unlink();descriptor.unlink()
        clone=self.out/'alternate worktree'
        clone.mkdir()
        for name in source_files(self.root):
            target=clone/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.root/name,target)
        for name in ['src','include']:(clone/name).mkdir(exist_ok=True)
        cloned_workspace=clone/self.workspace.relative_to(self.root);cloned_workspace.mkdir(parents=True)
        (cloned_workspace/'candidate.c').write_bytes(self.template)
        different=self.call('prepare',demo=True,root=clone)
        self.observe('E04','different-worktree',self.good(different) and
            different['value']['context_namespace']!=control['value']['context_namespace'] and not
            different['value']['result']['incremental']['restored'],[different,control],control)
        public=clone/'foundation/include/sc-foundation.h'
        public.write_bytes(public.read_bytes()+b'\n/* public-header qualification revision */\n')
        header=self.call('prepare',demo=True,root=clone)
        self.observe('E06','public-header-edit',self.good(header) and len(self.rebuilt(header))>=2,[different,header],control)
        # Retain copied-scope receipts before deleting the disposable worktree.
        # They cannot stand in for a child's independently executed CI.
        retained=self.out/'alternate-worktree-evidence'
        shutil.copytree(clone/'artifacts',retained)
        atomic_json(self.out/'alternate-worktree-path-map.json',
            {'original':str(clone/'artifacts'),'retained':str(retained),
             'source_identity':source_identity(clone)[0],'acceptance':False})
        shutil.rmtree(clone)

    def fuzz_regressions(self,control):
        from qualification import Qualifier
        from fuzzing import adapter_build
        from developer_bundle import capture_fuzz
        records=[];values={}
        for variant in ['bad','good']:
            identifier=uuid.uuid4().hex
            directory=self.root/'artifacts/developer/runs'/identifier
            scratch=Path(tempfile.mkdtemp(prefix='safe-c-e-fuzz-'))
            runner=Runner(self.root,directory,dict(read_json(self.root/'toolchain.lock.json'),image_id=self.lock['image_id']),scratch,purpose='development')
            try:
                q=Qualifier(self.root,runner);build=adapter_build(q,variant)
                if not build['audit']:raise GateError('existing fuzz regression build/instrumentation failed')
                executed=q.executable(build,'parser_fuzzer',['/src/fuzz/regressions/C32','-runs=1'],label='developer-fuzz-regression-'+variant)
                value={'schema_version':1,'operation':'test','status':'PASS' if passed(executed) else 'FAIL',
                    'run_id':identifier,'source_identity':source_identity(self.root)[0],'profile':'fuzz',
                    'context_namespace':None,'scope':'partial_feedback','acceptance':False,
                    'evidence_paths':[build['result']['evidence_path'],executed['evidence_path']],
                    'result':{'fuzz_result':{'program_result_preserved':True,'exit_code':executed['exit_code'],
                        'binary_sha256':executed['binary_sha256'],'input_sha256':file_hash(self.root/'fuzz/regressions/C32'),
                        'budget_runs':1,'runtime_profile':'fuzz'}},'limitations':['Existing isolated fuzz regression; no new campaign.']}
                value['bundle']=capture_fuzz(self.root,runner,value,executed,variant)
                feedback(value);atomic_json(directory/'result.json',value);values[variant]=value
                records.append({'path':str(directory/'result.json')})
            finally:runner.close();shutil.rmtree(scratch,ignore_errors=True)
        replays=[self.call('replay','--run-id',values[v]['run_id'],'--snapshot','original') for v in ['bad','good']]
        self.observe('E07','fuzz-regression',values['bad']['status']=='FAIL' and values['good']['status']=='PASS' and
            replays[0]['exit_code']!=0 and self.good(replays[1]) and all(
                r['value']['result']['fuzz_result']['input_sha256']==values[v]['result']['fuzz_result']['input_sha256'] and
                r['value']['result']['fuzz_result']['binary_sha256']==values[v]['result']['fuzz_result']['binary_sha256']
                for v,r in zip(['bad','good'],replays)),records+replays,control)

    def lifecycle(self,control):
        from developer import admission,stop
        from container_policy import Launcher, LABEL
        main='safety/qualification/developer/control.c:'+str(self.expected['main_line'])
        timeout=self.call('debug','--target','developer_demo','--recipe','breakpoint',
            '--location',main,'--argument','timeout',demo=True)
        state=timeout['value'].get('result',{}).get('debugger',{})
        expired=(timeout['exit_code']!=0 and state.get('timed_out') is True and
            state.get('inferior_outcome',{}).get('status')=='TIMEOUT' and not state.get('complete_capture'))
        self.observe('E09','timeout',expired,[timeout],control)
        self.observe('E11','timeout',expired,[timeout],control)
        with admission(self.root,'debug'):
            refused=self.call('prepare',demo=True)
        self.observe('E11','single-profile-admission',refused['exit_code']!=0,[refused],control)
        argv=[str(Path(__file__).parent/'safety'),'--candidate',str(self.root),'dev','debug',
            '--target','developer_demo','--recipe','breakpoint','--location',main,'--argument','timeout',
            '--demo-workspace',str(self.workspace.relative_to(self.root)),'--format','json']
        command_path=self.out/'public-cancellation.opaque.log'
        with command_path.open('wb') as output:
            process=subprocess.Popen(argv,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            launcher=Launcher(self.root,self.out/'cancellation-observer',dict(read_json(self.root/'toolchain.lock.json'),image_id=self.lock['image_id']),purpose='development')
            observed=False;deadline=time.monotonic()+20
            try:
                while process.poll() is None and time.monotonic()<deadline:
                    active=list((self.root/'artifacts/developer/active').glob('*.json'))
                    for path in active:
                        row=read_json(path)
                        if row['worktree']!=launcher.worktree_scope:continue
                        listed=launcher.docker(['ps','-q','--filter','label='+LABEL+'=1',
                            '--filter','label=org.safe-c.run='+row['run_id'],
                            '--filter','label=org.safe-c.purpose=development'])
                        for identifier in listed['output'].split():
                            # Fixed, read-only observation of this registered
                            # job's own namespace; no external PID attachment.
                            check=launcher.docker(['exec',identifier,'python3','-I','-S','-c',
                                'import pathlib,json;print(json.dumps({"gdb":any(p.name.isdecimal() and (p/"comm").is_file() and (p/"comm").read_text().strip()=="gdb" for p in pathlib.Path("/proc").iterdir())}))'],timeout=2)
                            atomic_json(self.out/'cancellation-observation.opaque.json',check)
                            if passed(check) and json.loads(check['output']).get('gdb'):observed=True;break
                    if observed:break
                    time.sleep(.05)
                cancelled=self.call('stop')
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,9);process.wait(timeout=5)
                launcher.close()
        cancellation={'path':str(command_path)}
        clean=cancelled['value'].get('result',{})
        self.observe('E11','cancellation',observed and self.good(cancelled) and process.returncode!=0 and
            clean.get('stopped_containers',0)>=1 and all(r['removed'] and r['children_reaped'] for r in clean.get('cleanup',[])),
            [cancelled,cancellation],control)
        restarted=self.call('prepare',demo=True)
        self.observe('E11','restart',self.good(restarted),[timeout,cancelled,restarted],control)
        foreign=uuid.uuid4().hex
        active=self.root/'artifacts/developer/active'/(foreign+'.json')
        atomic_json(active,{'run_id':foreign,'worktree':'foreign-worktree','image_id':self.lock['image_id']})
        try:refused_foreign=self.call('stop')
        finally:active.unlink()
        self.observe('E11','foreign-scope-rejection',refused_foreign['exit_code']!=0,[refused_foreign,cancelled],control)
        launcher=Launcher(self.root,self.out/'lifecycle-observer',dict(read_json(self.root/'toolchain.lock.json'),image_id=self.lock['image_id']),purpose='development')
        try:
            listed=launcher.docker(['ps','-aq','--filter','label=org.safe-c.worktree='+launcher.worktree_scope,
                '--filter','label=org.safe-c.purpose=development'])
            path=self.out/'lifecycle-summary.json'
            atomic_json(path,{'status':'PASS' if passed(listed) and not listed['output'].strip() else 'FAIL',
                'remaining_container_count':len(listed['output'].split()),'restarted_run_id':restarted['value'].get('run_id')})
            self.observe('E11','repeat-cleanup',passed(listed) and not listed['output'].strip(),[{'path':str(path)},cancelled,restarted],control)
            records=list((self.root/'artifacts/developer/runs'/control['value']['run_id']).glob('container-*.json'))
            actual=[read_json(p) for p in records]
            self.observe('E10','confined-control',bool(actual) and all(r.get('execution_path')=='docker' and
                r.get('effective') and r.get('lifecycle',{}).get('removed') for r in actual),[control,{'path':str(path)}],control)
        finally:launcher.close()
        prohibited=[]
        for arguments in [('--value','offset=1'),('--value','function()'),('--target','remote:1234'),('--profile','host')]:
            base=['--target','developer_demo','--recipe','breakpoint','--location',main]
            if arguments[0]=='--target':base=base[2:]
            prohibited.append(self.call('debug',*base,*arguments,demo=True))
        self.observe('E10','prohibited-command-target',all(r['exit_code']!=0 for r in prohibited),prohibited,control)

    def pipeline(self,control,debug,literal):
        scratch=Path(tempfile.mkdtemp(prefix='safe-c-e-records-'))
        runner=Runner(self.root,self.out/'record-probes',dict(read_json(self.root/'toolchain.lock.json'),image_id=self.lock['image_id']),scratch,purpose='development')
        try:
            input_file=scratch/'records.json'
            atomic_json(input_file,{'debug':debug['value'],'qualification':self.report})
            runner.start();runner.restore('developer-record-input.json',input_file)
            record=runner.run(['python3','/src/container/developer-record-probes.py'],timeout=45,label='developer-negative-record-controls')
            data=json.loads(record['output'])
            runner.fetch(data['artifact'],self.out/'record-probes/result.json')
            if data.get('status')!='PASS':
                self.report['limitations'].append('One or more negative record controls failed.')
            observed={(r['parent'],r['name'],r['variant']):r for r in data['variants']}
            def submit(parent,name,variant,condition,records):
                row=next(r for r in self.report['pipeline_variants'] if
                    (r['parent'],r['name'],r['variant'])==(parent,name,variant))
                row.update(status='PASS' if condition and self.good(debug) else 'FAIL',
                    control='PASS' if self.good(debug) else 'FAIL',
                    evidence_paths=sorted({r['path'] for r in [*records,debug]}),reason=None)
            for key,row in observed.items():
                submit(*key,row['status']=='PASS' and row['control']=='PASS',[{'path':record['evidence_path']}])
            for parent,name,variant,native in [
                ('P01','dev-tool-or-route-unavailable','clangd','missing-clangd'),
                ('P01','dev-tool-or-route-unavailable','gdb','missing-gdb'),
                ('P01','dev-tool-or-route-unavailable','tracing','denied-tracing'),
                ('P02','dev-build-context-mismatch','compilation-database','wrong-db-profile'),
                ('P02','dev-build-context-mismatch','generated-header','wrong-generated-context'),
                ('P02','dev-build-context-mismatch','symbols','stripped-symbols'),
                ('P04','dev-config-or-debugger-injection','startup-script','startup-canaries')]:
                actual=self.native_calls[native]
                submit(parent,name,variant,self.good(actual) and actual['value'].get('control')=='PASS',[actual])
            loaded=self.native('wrong-loaded-profile')
            submit('P02','dev-build-context-mismatch','loaded-dependency',self.good(loaded) and loaded['value'].get('control')=='PASS',[loaded])
            state=literal['value'].get('result',{}).get('debugger',{})
            submit('P04','dev-config-or-debugger-injection','shell-argv',self.good(literal) and
                state.get('observed_inferior_argv')==state.get('inferior_argv') and
                state.get('effective_startup',{}).get('startup-with-shell')=='off',[literal])
            failure=next(r for r in self.calls if r['value'].get('operation')=='replay' and r['value'].get('status')=='FAIL')
            missing=next(r for r in self.calls if r['value'].get('operation')=='replay' and r['exit_code']!=0 and
                r['value'].get('status')!='FAIL')
            submit('P10','dev-stale-state','failure-bundle',missing['exit_code']!=0,[missing,failure])
            spoof=next(r for r in self.calls if r['value'].get('result',{}).get('debugger',{}).get('inferior_argv',[0])[-1]=='spoof')
            state=spoof['value']['result']['debugger']
            submit('P11','dev-failure-masked','inferior-mi-spoof',self.good(spoof) and
                state['inferior_outcome']=={'status':'FAILED','exit_code':7} and state['inferior_output_bytes']>0,[spoof])
            self.save()
        finally:runner.close();shutil.rmtree(scratch,ignore_errors=True)

    def run(self):
        control=self.call('prepare',demo=True)
        doctor=self.call('doctor')
        targets=self.call('targets',demo=True)
        tests=self.call('tests',demo=True)
        status=self.call('status')
        help_record=bounded([str(Path(__file__).parent/'safety'),'dev','--help'])
        help_path=self.out/'public-help.opaque.json';atomic_json(help_path,help_record)
        self.observe('E01','entrypoint',all(self.good(r) for r in [control,doctor,targets,tests]) and
            passed(help_record) and 'prepare' in help_record['output'] and
            'developer_tooling' in status['value'].get('result',{}),[control,doctor,targets,tests,status,
              {'path':str(help_path)}],control)
        warm=self.call('prepare',demo=True)
        self.observe('E01','idempotent-offline-prepare',self.good(warm) and
            warm['value']['result'].get('incremental',{}).get('restored'),[control,warm],control)
        unknown=self.call('test','--id','nonexistent-test',demo=True)
        empty=self.call('test','--id','',demo=True)
        self.observe('E01','unknown-selection',not self.good(unknown) and unknown['exit_code']!=0,[unknown],control)
        self.observe('E05','unknown-empty-test',all(r['exit_code']!=0 for r in [unknown,empty]),[unknown,empty],control)
        selected=self.call('test','--id','developer.pair',demo=True)
        self.observe('E05','actual-discovered-test',self.good(selected) and
            selected['value']['result']['test_result']['executed_cases']==1,[selected,tests],control)
        self.observe('E05','partial-scope',selected['value'].get('acceptance') is False and
            selected['value'].get('scope')=='partial_feedback',[selected],control)
        point=self.expected['candidate_breakpoint'];line=point['line']
        text=self.template.decode();column=text.splitlines()[line-1].index('sc_bytes_read_u16be')+1
        definition=self.call('nav','--kind','definition','--file','demo/candidate.c','--line',line,'--column',column,demo=True)
        definitions=definition['value'].get('result',{}).get('navigation',{}).get('result',[])
        self.observe('E02','registered-tu',self.good(definition) and bool(definitions),[definition],control)
        self.observe('E04','unicode-scalar-position',self.good(definition) and any(
            r.get('mapped_location',{}).get('path')=='foundation/src/sc-foundation.c' for r in definitions),[definition],control,
            {'cli_line':line,'unicode_scalar_column':column})
        header=self.call('nav','--kind','hover','--file','foundation/include/sc-foundation.h',
            '--line','34','--column','38','--tu','foundation/tests/recipes.c')
        self.observe('E02','public-header-including-tu',self.good(header) and
            header['value']['result']['navigation'].get('header_context_observed'),[header],control)
        hover=self.call('nav','--kind','hover','--file','demo/candidate.c','--line',line,'--column',column,demo=True)
        glib_type=self.nav('hover','GBytes')
        self.observe('E03','api-glib-hover',self.good(hover) and self.good(glib_type) and
            'GBytes' in json.dumps(glib_type['value']['result']['navigation']['result']),[hover,glib_type,header],control)
        documents=self.call('nav','--kind','document-symbols','--file','demo/candidate.c',demo=True)
        symbols=self.call('nav','--kind','workspace-symbols','--symbol','developer_read_pair',demo=True)
        self.observe('E03','symbols',self.good(documents) and self.good(symbols) and
            bool(symbols['value']['result']['navigation']['result']),[documents,symbols],control)
        debug=self.call('debug','--target','developer_demo','--recipe','breakpoint',
            '--location',point['file']+':'+str(line),'--value','offset','--steps','1',demo=True)
        observation=debug['value'].get('result',{}).get('debugger',{})
        for name,condition in [('matching-debug-symbols',bool(observation.get('frames'))),
            ('resolved-reached-source-stop',observation.get('inspection_requirements_met')),
            ('predetermined-values',observation.get('values',{}).get('offset')==point['control_value']),
            ('source-step',(observation.get('step') or {}).get('reason')=='end-stepping-range')]:
            self.observe('E08',name,self.good(debug) and condition,[debug],control)
        self.observe('E09','normal-exit',observation.get('inferior_outcome')=={'status':'PASSED','exit_code':0},[debug],control)
        guards=observation.get('effective_startup',{})
        for name,setting in [('aslr-preserved','disable-randomization'),('auto-load-disabled','auto-load python-scripts')]:
            self.observe('E10',name,guards.get(setting)=='off',[debug],control)
        self.observe('E10','local-thread-library',guards.get('libthread-db-search-path')==self.policy['debugger']['libthread_db_directory'],[debug],control)
        thread=self.expected['threads_breakpoint']
        threaded=self.call('debug','--target','developer_demo','--recipe','breakpoint',
            '--location',thread['file']+':'+str(thread['line']),'--argument','threads','--value',thread['value'],demo=True)
        state=threaded['value'].get('result',{}).get('debugger',{})
        self.observe('E09','multiple-thread-stacks',self.good(threaded) and len(state.get('threads',[]))==thread['thread_count'] and
            state.get('values',{}).get(thread['value'])==thread['expected_value'],[threaded],control)
        crash=self.call('debug','--target','developer_demo','--recipe','crash','--argument','signal',demo=True)
        state=crash['value'].get('result',{}).get('debugger',{})
        self.observe('E09','signal-stop',self.good(crash) and (state.get('stop') or {}).get('signal-name')==self.expected['signal'],[crash],control)
        self.observe('E09','signal-termination',state.get('inferior_outcome')=={'status':'FAILED','signal':self.expected['signal']},[crash],control)
        main='safety/qualification/developer/control.c:'+str(self.expected['main_line'])
        for mode,name in [('exit','nonzero-exit'),('spoof','inferior-protocol-spoof')]:
            tested=self.call('debug','--target','developer_demo','--recipe','breakpoint','--location',main,'--argument',mode,demo=True)
            state=tested['value'].get('result',{}).get('debugger',{})
            self.observe('E09',name,self.good(tested) and state.get('inferior_outcome')=={'status':'FAILED','exit_code':7} and
                (mode!='spoof' or state.get('inferior_output_bytes',0)>0),[tested],control)
        literal=self.call('debug','--target','developer_demo','--recipe','breakpoint','--location',main,
            '--argument','literal','--argument','a space;$(unused)',demo=True)
        self.observe('E10','literal-argv',self.good(literal) and literal['value']['result']['debugger']['inferior_outcome']==
            {'status':'PASSED','exit_code':0},[literal],control)
        unreached=self.call('debug','--target','developer_demo','--recipe','breakpoint',
            '--location',thread['file']+':'+str(thread['line']),'--argument','pair',demo=True)
        self.observe('E08','unreached-stop',not self.good(unreached) and not
            unreached['value'].get('result',{}).get('debugger',{}).get('inspection_requirements_met'),[unreached],control)
        for case,eid,name in [('stripped-symbols','E08','wrong-symbols'),('startup-canaries','E10','startup-canaries'),
             ('denied-tracing','E09','debugger-failure'),('output-overflow','E11','output-overflow')]:
            result=self.native(case)
            self.observe(eid,name,self.good(result),[result],control)
        missing=[self.native(case) for case in ['missing-clangd','missing-gdb']]
        self.observe('E01','missing-tool-input',all(self.good(r) for r in missing),missing,control)
        mismatched=[self.native(case) for case in ['missing-db','stale-db','wrong-db-profile','wrong-generated-context']]
        self.observe('E02','wrong-missing-stale-context',all(self.good(r) for r in mismatched),mismatched,control)
        self.semantic_and_workflow(control,definition,header,debug)
        self.incremental_contexts(control,warm)
        self.fuzz_regressions(control)
        self.lifecycle(control)
        self.pipeline(control,debug,literal)
        self.save()
        return self.report


def run(root,policy,lock,out):
    return Suite(root,policy,lock,out).run()
