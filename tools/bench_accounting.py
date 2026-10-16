"""B15 (spec 8.2, Amendment H7): whole-workload CPU reconciliation between trial deltas, the coordinator window and the
host cgroup totals at create and dispose. Host-only; reads recorded values."""
import json
from evidence import read_json
from pathlib import Path

def usage_usec(cpu_stat_text):
    if not isinstance(cpu_stat_text,str):return None
    for line in cpu_stat_text.splitlines():
        parts=line.split()
        if len(parts)==2 and parts[0]=='usage_usec' and parts[1].isdigit():return int(parts[1])
    return None

def host_total_usec(session_record):
    rec=session_record or {}
    before=usage_usec(((rec.get('effective') or {}).get('events_before') or {}).get('cpu.stat'))
    after=usage_usec(((rec.get('lifecycle') or {}).get('counters_after') or {}).get('cpu.stat'))
    return None if before is None or after is None or after<before else after-before

def _valid_delta(d):return isinstance(d,int) and not isinstance(d,bool) and d>=0

def checked_total(rows):
    """T11-APP-05: the trial total that check_session compares (non-negative integer deltas only); reconcile records it."""
    return sum(d for d in (o.get('cpu_usage_usec') for o in rows) if _valid_delta(d))

def check_session(name,host_total,window,rows,resolution_usec):
    r=resolution_usec;reasons=[]
    if host_total is None:return [f'B15 {name}: host CPU total unavailable (a mandatory metric)']
    if window is None:return [f'B15 {name}: coordinator window unavailable (a mandatory metric)']
    deltas=[o.get('cpu_usage_usec') for o in rows]
    if not all(_valid_delta(d) for d in deltas):reasons.append(f'B15 {name}: a trial CPU delta is missing or negative')
    total=checked_total(rows)
    if total>window+len(deltas)*r:reasons.append(f'B15 {name}: trial deltas {total} us exceed the coordinator window {window} us')
    if window>host_total+2*r:reasons.append(f'B15 {name}: coordinator window {window} us exceeds the host total {host_total} us')
    return reasons

def check_cgroup_identity(name,launcher_inode,job_inode):
    """Brief B15 "incorrect cgroup identity": the cgroup the launcher created (inode at create) must be the cgroup the
    coordinator read (inode of /sys/fs/cgroup inside the container). A missing inode is a missing mandatory metric."""
    ok=lambda v:isinstance(v,int) and not isinstance(v,bool) and v>0
    if not ok(launcher_inode) or not ok(job_inode) or launcher_inode!=job_inode:
        return [f'B15 {name}: incorrect cgroup identity (launcher {launcher_inode}, coordinator {job_inode})']
    return []

def reconcile(sessions,policy):
    r=policy['accounting']['resolution_usec'];reasons=[];rows=[]
    for s in sessions:
        got=check_session(s['session'],s['host_total_usec'],s['window_usec'],s['rows'],r)
        got+=check_cgroup_identity(s['session'],s.get('launcher_cgroup_inode'),s.get('job_cgroup_inode'));reasons+=got
        rows.append({'session':s['session'],'host_total_usec':s['host_total_usec'],'window_usec':s['window_usec'],
                     'trial_sum_usec':checked_total(s['rows']),'trials':len(s['rows']),
                     'launcher_cgroup_inode':s.get('launcher_cgroup_inode'),'job_cgroup_inode':s.get('job_cgroup_inode'),'status':'FAIL' if got else 'PASS'})
    return reasons,rows

UNRECORDED='cgroup-identity-unrecorded'

def recheck(run,run_dir=None):
    """compare and decide (P3R4-01, P3R5-01): re-run the identity check on the recorded accounting rows of a run.
    A local run (dataset kind local) whose run.json holds no rows takes them from its recorded local-merged.json (bound by
    the run's evidence digests). A run without any rows gives exactly [UNRECORDED]; never a KeyError."""
    rows=run.get('accounting') or []
    if not rows and run_dir is not None and (run.get('dataset') or {}).get('kind')=='local':
        merged=Path(run_dir)/'local-merged.json'
        if merged.is_file():rows=read_json(merged).get('accounting') or []     # FR3-19: a container-merged record, capped
    if not rows:return [UNRECORDED]
    return [x for a in rows for x in check_cgroup_identity(a.get('session','?'),a.get('launcher_cgroup_inode'),a.get('job_cgroup_inode'))]
