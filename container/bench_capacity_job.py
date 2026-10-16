"""Coordinator job `capacity` (Amendment H6). Registered by one line in bench-coordinator.py; `g` is its globals()."""
import json, subprocess, time

def register(job,g):
    @job('capacity')
    def job_capacity(plan,out):
        WORK=g['WORK'];channel=g['Channel'](WORK/'bench/marker.sock');deadline=time.monotonic()+plan['deadline_seconds']-30;rows=[];codes=[]
        (WORK/'bench/private').mkdir(parents=True,exist_ok=True)
        try:
            dataset=g['materialize_dataset'](plan);reference=g['reference_path'](plan,dataset)
            for t in plan['trials']:
                spec_path=WORK/f"bench/private/{t['trial_id']}.json"
                spec_path.write_text(json.dumps({'trial':t,'case_manifest':g['_manifest'](plan),'dataset':dataset['path'],'sha256':dataset['sha256'],'reference':reference,
                                                 'size':plan['sizes'][t['tier']],'latency_samples_max':plan['latency_samples_max']}))
                start=len(channel.events)
                with (WORK/f"bench/private/{t['trial_id']}.log").open('wb') as log:
                    p=subprocess.Popen(g['python_argv'](g['PYTHONPATH'],'-m','benchlab.capacity_trial','--spec',spec_path),env=g['child_env'](channel.path),stdout=subprocess.DEVNULL,stderr=log)
                try:channel.pump(lambda:g['_events'](channel,start,t['trial_id'],'note') or p.poll() is not None,deadline)
                finally:
                    try:p.wait(timeout=max(1.0,deadline-time.monotonic()))
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                codes.append(p.returncode);b=g['_events'](channel,start,t['trial_id'],'begin','capacity');e=g['_events'](channel,start,t['trial_id'],'end','capacity');n=g['_events'](channel,start,t['trial_id'],'note')
                if b and e and n:
                    row=g['observation'](plan,t,'capacity',b[0],e[0],n[0]['msg'],'safe-c-trial-runner',False);row['capacity']=n[0]['msg'].get('capacity');rows.append(row)
        finally:channel.close()
        (out/'capacity.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
        return {'status':'PASS' if len(rows)==len(plan['trials']) and all(c==0 for c in codes) else 'FAIL','files':['capacity.jsonl'],'child_exit_codes':codes}
    return job_capacity
