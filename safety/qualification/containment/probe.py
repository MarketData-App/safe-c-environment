"""Finite infrastructure probes. No unbounded recursion/allocation/output."""
import ctypes
import errno
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

CEILINGS={'memory_bytes':192*1024*1024,'child_attempts':64,'child_seconds':6,'busy_seconds':3,'write_bytes':24*1024*1024,'inode_attempts':96,'log_bytes':4*1024*1024,'deadline_seconds':8}

def emit(value):print(json.dumps(value),flush=True)
def home_exposed(mountinfo,home=Path('/home')):
    """True when any mount point is /home or below it, or when /home is a non-empty directory."""
    for line in mountinfo.splitlines():
        fields=line.split()
        if len(fields)>4 and (fields[4]=='/home' or fields[4].startswith('/home/')):return True
    return home.is_dir() and any(home.iterdir())
def main(mode,control=False):
    if mode=='identity':
        emit({'compute':sum(range(10)),'uid':os.getuid(),'gid':os.getgid(),'ceilings':CEILINGS})
    elif mode=='immutability':
        failures={}
        for p in ['/src/containment-canary','/fixture/input-canary','/usr/containment-canary']:
            try:
                fd=os.open(p,os.O_WRONLY|os.O_CREAT,0o666);os.write(fd,b'changed');os.close(fd);failures[p]=0
            except OSError as e:failures[p]=e.errno
        Path('/work/allowed').write_text('safe')
        emit({'denials':failures,'source_read':Path('/src/containment-canary').read_text(),'input_read':Path('/fixture/input-canary').read_text(),'scratch':Path('/work/allowed').read_text()})
    elif mode=='resources':
        visible=any('safe-c-sibling-marker' in p.read_text(errors='ignore') for p in Path('/proc').glob('[0-9]*/cmdline') if p.exists())
        emit({'outside_visible':Path(sys.argv[3]).exists(),'sibling_marker_visible':visible,'supplied':Path('/fixture/input-canary').read_text(),'namespaces':{k:os.readlink('/proc/self/ns/'+k) for k in ['pid','net','ipc','mnt']}})
    elif mode=='secrets':
        entries={k:v for k,v in os.environ.items() if k not in ['PATH','PYTHONPATH','PYTHONDONTWRITEBYTECODE','SAFETY_PUBLIC_MARKER','HOME','HOSTNAME','LANG','LC_ALL','LC_CTYPE']}
        fds={}
        for p in Path('/proc/self/fd').iterdir():
            try:fds[p.name]=os.readlink(p)
            except OSError:pass
        emit({'unexpected_environment_names':sorted(entries),'synthetic_secret_inherited':'SAFETY_SYNTHETIC_SECRET' in os.environ,'allowed':os.environ.get('SAFETY_PUBLIC_MARKER'),'management_socket_present':any(Path(p).exists() for p in ['/var/run/docker.sock','/run/containerd/containerd.sock','/alternate/management.sock']),'home_mount_present':home_exposed(Path('/proc/self/mountinfo').read_text()),'fds':fds,'home_default':os.environ.get('HOME')})
    elif mode=='network':
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen();port=server.getsockname()[1]
            with socket.create_connection(('127.0.0.1',port),timeout=1) as c:
                peer,_=server.accept();peer.sendall(b'loopback');loopback=c.recv(8).decode();peer.close()
        reached=False
        try:
            with socket.create_connection((sys.argv[3],int(sys.argv[4])),timeout=1) as c:reached=c.recv(32)==b'synthetic-fixture'
        except OSError:pass
        emit({'loopback':loopback,'fixture_reached':reached,'interfaces':sorted(p.name for p in Path('/sys/class/net').iterdir()),'routes':Path('/proc/net/route').read_text()})
    elif mode=='privilege':
        elevation=0
        try:os.setuid(0)
        except OSError as e:elevation=e.errno
        # Disposable mount point only. No host paths, devices, kernel settings
        # or real process tracing are involved. A mistakenly permitted tmpfs
        # would itself have a finite one-MiB size in this private namespace.
        target=Path('/work/forbidden-mount');target.mkdir()
        libc=ctypes.CDLL(None,use_errno=True)
        libc.mount.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_ulong,ctypes.c_char_p]
        ret=libc.mount(b'tmpfs',str(target).encode(),b'tmpfs',14,b'size=1048576')
        emit({'setuid_errno':elevation,'mount_return':ret,'mount_errno':ctypes.get_errno(),'mount_target':str(target),'getpid_ok':os.getpid()>0})
    elif mode=='memory':
        amount=8*1024*1024 if control else CEILINGS['memory_bytes']
        pid=os.fork()
        if pid==0:
            chunks=[]
            try:
                for _ in range(amount//(1024*1024)):
                    chunk=bytearray(1024*1024)
                    for i in range(0,len(chunk),4096):chunk[i]=1
                    chunks.append(chunk)
                os._exit(0)
            except MemoryError:os._exit(42)
        _,status=os.waitpid(pid,0)
        emit({'finite_max_bytes':amount,'child_exit':os.waitstatus_to_exitcode(status),'parent_healthy':True})
    elif mode=='pids':
        kids=[];refused=0;attempts=4 if control else CEILINGS['child_attempts']
        for _ in range(attempts):
            try:pid=os.fork()
            except OSError as e:refused=e.errno;break
            if pid==0:time.sleep(CEILINGS['child_seconds']);os._exit(0)
            kids.append(pid)
        for pid in kids:os.kill(pid,signal.SIGTERM)
        for pid in kids:os.waitpid(pid,0)
        emit({'finite_attempts':attempts,'created':len(kids),'refusal_errno':refused,'reaped':len(kids)})
    elif mode=='cpu':
        before=time.process_time();start=time.monotonic();value=0
        duration=.05 if control else CEILINGS['busy_seconds']
        while time.monotonic()-start<duration:value=(value+1)%1000000
        emit({'busy_wall_seconds':time.monotonic()-start,'cpu_seconds':time.process_time()-before,'finite_seconds':duration,'computation_completed':True})
    elif mode=='space':
        amount=1024 if control else CEILINGS['write_bytes'];written=0;failure=0
        try:
            with open('/work/bytes-probe','wb',buffering=0) as f:
                while written<amount:written+=f.write(b'x'*min(1024*1024,amount-written))
        except OSError as e:failure=e.errno
        usage=os.statvfs('/work');Path('/work/bytes-probe').unlink(missing_ok=True)
        count=0;inode_errno=0
        if not control:
            for i in range(CEILINGS['inode_attempts']):
                try:Path('/work/inode-'+str(i)).write_bytes(b'x');count+=1
                except OSError as e:inode_errno=e.errno;break
        inode_usage=os.statvfs('/work')
        for p in Path('/work').glob('inode-*'):p.unlink()
        emit({'finite_bytes':amount,'written':written,'space_errno':failure,'filesystem_bytes':usage.f_blocks*usage.f_frsize,'used_bytes':(usage.f_blocks-usage.f_bfree)*usage.f_frsize,'inode_errno':inode_errno,'created_files':count,'filesystem_inodes':inode_usage.f_files,'used_inodes':inode_usage.f_files-inode_usage.f_ffree})
    elif mode=='logs':
        amount=1024 if control else CEILINGS['log_bytes']
        for i in range(amount//1024):os.write(1,(f'{i:08d} '+('x'*1014)+'\n').encode())
    elif mode=='deadline':
        if control:emit({'normal_exit':True});return
        for _ in range(3):
            if os.fork()==0:time.sleep(CEILINGS['child_seconds']);os._exit(0)
        emit({'finite_child_attempts':3,'finite_parent_seconds':CEILINGS['deadline_seconds']})
        time.sleep(CEILINGS['deadline_seconds'])
        while True:
            try:os.waitpid(-1,0)
            except ChildProcessError:break
    else:raise ValueError('unknown finite probe')

if __name__=='__main__':
    try:main(sys.argv[1],sys.argv[2]=='control')
    except Exception as e:emit({'probe_error_type':type(e).__name__});raise SystemExit(1)
