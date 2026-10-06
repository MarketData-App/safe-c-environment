"""Portable Docker host capability decision; no machine identity is pinned."""
from evidence import GateError

INHERITED=('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','DOCKER_API_VERSION','DOCKER_CONFIG')
CONTROLLERS=('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod')

def active_lsm(info):
    joined=' '.join(info.get('SecurityOptions') or [])
    return 'apparmor' if 'apparmor' in joined else 'selinux' if 'selinux' in joined else None

def context_endpoint(context):
    return ((context.get('Endpoints') or {}).get('docker') or {}).get('Host','')

def inherited_problems(environ):
    return [f'inherited-docker-setting: {k}' for k in INHERITED if environ.get(k)]

def endpoint_problems(context, environ):
    """Checks that must pass before any daemon is contacted."""
    problems=inherited_problems(environ)
    if not context_endpoint(context).startswith('unix:///'):problems.append('local-unix-endpoint: active context endpoint is not a local Unix socket')
    return problems

def host_problems(info, context, environ, core_pattern, selinux_enforcing=None):
    """selinux_enforcing is the host /sys/fs/selinux/enforce state; None means unknown and fails closed."""
    problems=endpoint_problems(context,environ)
    if info.get('Architecture')!='x86_64':problems.append('architecture: x86_64 required')
    if str(info.get('CgroupVersion'))!='2':problems.append('cgroup-v2: cgroup v2 required')
    missing=[k for k in CONTROLLERS if not info.get(k)]
    if missing:problems.append('resource-controllers: '+','.join(missing))
    if not any('seccomp' in s for s in info.get('SecurityOptions') or []):problems.append('seccomp: seccomp required')
    lsm=active_lsm(info)
    if lsm is None:problems.append('linux-security-module: AppArmor or SELinux required')
    elif lsm=='selinux' and selinux_enforcing is not True:problems.append('linux-security-module: SELinux not enforcing')
    if core_pattern.strip().startswith('|'):problems.append('core-handling: piped core handler requires operator review')
    return problems

def security_options(info):
    lsm=active_lsm(info)
    if lsm=='apparmor':return ['no-new-privileges','apparmor=docker-default']
    if lsm=='selinux':return ['no-new-privileges','label=type:container_t']
    raise GateError('host capability check failed: linux-security-module: AppArmor or SELinux required')
