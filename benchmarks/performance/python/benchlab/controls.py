"""Measurement controls (spec 9, 8.4): CPU (wait, spin, children, native) and memory (errors 2-8)."""
import mmap, os, resource, subprocess, sys, time
from benchlab.markers import Marker
MIB=1048576
CPU_CONTROLS=('control-zero','wait','spin','spin-children-2','native-spin','short-children-20')
MEMORY_CONTROLS=('child-touch-64','sequential-children-64x2','children-32-64','shared-mapping-64','short-spike-64','untouched-1024')

def spin(seconds):
    end=time.perf_counter()+seconds;n=0
    while time.perf_counter()<end:n+=1
    return n
def touch(mib):
    buf=bytearray(mib*MIB)
    for i in range(0,len(buf),4096):buf[i]=1
    return buf
def child_argv(code):
    """Task 13a residual: a control grandchild starts isolated (-I: no PYTHONPATH, no user site, no startup hook) with
    this process's explicit import path, like every coordinator child."""
    paths=[p for p in sys.path if p]
    return [sys.executable,'-I','-c',f'import sys;sys.path[0:0]={paths!r};import benchlab.controls as c;'+code]
def child(code):
    p=subprocess.Popen(child_argv(code));_,status,usage=os.wait4(p.pid,0)
    p.returncode=os.waitstatus_to_exitcode(status)   # reaped here: Popen must not wait again or warn
    if p.returncode:raise RuntimeError('control child failed')
    return usage
def cpu_usec(u):return int((u.ru_utime+u.ru_stime)*1e6)

def live_tree_cpu_usec(proc='/proc'):
    """A polling sampler: CPU of this process plus its live descendants now. Exited, waited children are absent (lower bound)."""
    tick=os.sysconf('SC_CLK_TCK');parent={};used={}
    for name in os.listdir(proc):
        if not name.isdigit():continue
        try:
            with open(f'{proc}/{name}/stat') as f:fields=f.read().rsplit(')',1)[1].split()
        except (OSError,IndexError):continue
        parent[int(name)]=int(fields[1]);used[int(name)]=(int(fields[11])+int(fields[12]))*1000000//tick
    me=os.getpid();tree={me};grew=True
    while grew:
        more={p for p,pp in parent.items() if pp in tree and p not in tree};grew=bool(more);tree|=more
    return cpu_usec(resource.getrusage(resource.RUSAGE_SELF))+sum(used[p] for p in tree if p!=me)

def shared_mapping(mib):
    """Parent writes and a forked child reads one MAP_SHARED anonymous mapping (policy touch_mib): summed RSS counts the pages twice, USS does not.
    Anonymous shared memory, not a /work file: the protected 32 MiB RLIMIT_FSIZE refuses a 64 MiB file."""
    import psutil
    size=mib*MIB;m=mmap.mmap(-1,size,flags=mmap.MAP_SHARED|mmap.MAP_ANONYMOUS)
    try:
        for i in range(0,size,4096):m[i]=1
        ready_r,ready_w=os.pipe();hold_r,hold_w=os.pipe();pid=os.fork()
        if pid==0:
            code=1
            try:
                os.close(ready_r);os.close(hold_w);s=sum(m[i] for i in range(0,size,4096))
                os.write(ready_w,b'r' if s==size//4096 else b'x');os.read(hold_r,1);code=0
            finally:os._exit(code)
        os.close(ready_w);os.close(hold_r)
        try:
            if os.read(ready_r,1)!=b'r':raise RuntimeError('shared mapping reader failed')
            info=[x.memory_full_info() for x in (psutil.Process(),psutil.Process(pid))]
        finally:
            os.close(hold_w);os.close(ready_r)
            _,status=os.waitpid(pid,0)
        if status:raise RuntimeError('shared mapping reader failed')
    finally:m.close()
    return {'rss_kib':[i.rss//1024 for i in info],'uss_kib':[i.uss//1024 for i in info],'label':'summed RSS is an upper bound; shared pages counted'}

def run(name,seconds,native_mib,marker,trial,short_children=20,touch_mib=64,untouched_mib=1024):
    extra={}
    if name=='short-spike-64':
        marker.begin('control',trial);buf=touch(touch_mib);del buf;return marker.end('control',trial,sampled=True)
    polled=live_tree_cpu_usec() if name=='short-children-20' else None
    marker.begin('control',trial)
    if name=='wait':time.sleep(seconds)
    elif name=='spin':spin(seconds)
    elif name=='spin-children-2':
        ps=[subprocess.Popen(child_argv(f'c.spin({seconds})')) for _ in range(2)]
        for p in ps:
            if p.wait():raise RuntimeError('control child failed')
    elif name=='native-spin':
        before_self=resource.getrusage(resource.RUSAGE_SELF);head=subprocess.Popen(['head','-c',str(native_mib*MIB),'/dev/zero'],stdout=subprocess.PIPE)
        subprocess.run(['sha256sum'],stdin=head.stdout,stdout=subprocess.DEVNULL,check=True);head.stdout.close()
        if head.wait():raise RuntimeError('native control child failed')
        kids=resource.getrusage(resource.RUSAGE_CHILDREN);me=resource.getrusage(resource.RUSAGE_SELF)
        extra={'children_cpu_usec':cpu_usec(kids),'parent_self_cpu_usec':cpu_usec(me)-cpu_usec(before_self)}
    elif name=='short-children-20':
        before_self=resource.getrusage(resource.RUSAGE_SELF)
        for _ in range(short_children):child(f'c.spin({seconds/short_children})')
        kids=resource.getrusage(resource.RUSAGE_CHILDREN);me=resource.getrusage(resource.RUSAGE_SELF)
        extra={'children_cpu_usec':cpu_usec(kids),'parent_self_cpu_usec':cpu_usec(me)-cpu_usec(before_self),'children':short_children,
               'polled_tree_cpu_usec':live_tree_cpu_usec()-polled,'polled_label':'lower bound: live process tree sampled at the handshakes; exited children missed'}
    elif name=='child-touch-64':child(f'b=c.touch({touch_mib})')
    elif name=='sequential-children-64x2':extra={'child_maxrss_kib':[child(f'b=c.touch({touch_mib})').ru_maxrss,child(f'b=c.touch({touch_mib})').ru_maxrss]}
    elif name=='children-32-64':
        a=child(f'b=c.touch({touch_mib//2})').ru_maxrss;b=child(f'b=c.touch({touch_mib})').ru_maxrss
        extra={'child_maxrss_kib':[a,b],'rusage_children_maxrss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
               'label':'largest waited child (RUSAGE_CHILDREN ru_maxrss), not a sum and not a group peak'}
    elif name=='shared-mapping-64':extra=shared_mapping(touch_mib)
    elif name=='untouched-1024':m=mmap.mmap(-1,untouched_mib*MIB,flags=mmap.MAP_PRIVATE|mmap.MAP_ANONYMOUS);time.sleep(0.2);m.close()
    elif name!='control-zero':raise ValueError('unknown control')
    return marker.end('control',trial,**extra)

def main(argv):
    name,seconds,native_mib=argv[1],float(argv[2]),int(argv[3]);sizes=[int(v) for v in argv[4:7]];m=Marker()
    try:
        m.hello(name)
        try:run(name,seconds,native_mib,m,name,*sizes)
        except Exception as error:   # the type only (agent context rule); the row records the failure, the exit code fails the job
            m.note(name,error=type(error).__name__);return 1
    finally:m.close()
    return 0

if __name__=='__main__':sys.exit(main(sys.argv))
