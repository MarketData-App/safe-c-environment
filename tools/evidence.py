"""Trusted, bounded host orchestration. Candidate processes receive no credentials."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import uuid

class GateError(RuntimeError):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_hash(path: Path) -> str:
    return digest(path.read_bytes())

def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)

def bounded(argv, timeout=30, limit=4*1024*1024, env=None, cwd=None):
    """Kill/reap process groups; never confuse timeout/truncated output with success."""
    started = time.monotonic()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, env=env, cwd=cwd)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    cause = None
    while selector.get_map():
        if time.monotonic() - started > timeout:
            cause = 'TIMEOUT'
            break
        for key, _ in selector.select(.05):
            data = os.read(key.fileobj.fileno(), 65536)
            if not data:
                selector.unregister(key.fileobj)
            else:
                output.extend(data)
                if len(output) > limit:
                    cause = 'OUTPUT_LIMIT'
                    break
        if cause:
            break
    if cause:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        code = process.wait(timeout=max(.1, timeout - (time.monotonic()-started)))
    except subprocess.TimeoutExpired:
        cause = 'TIMEOUT'
        os.killpg(process.pid, signal.SIGKILL)
        code = process.wait()
    selector.close()
    process.stdout.close()
    return {'argv': list(argv), 'exit_code': code, 'failure': cause,
            'seconds': round(time.monotonic()-started, 4),
            'output': bytes(output[:limit]).decode('utf-8', errors='replace')}

PROHIBITED_ENV = ('LIT_OPTS', 'FILECHECK_OPTS', 'ASAN_OPTIONS', 'LSAN_OPTIONS',
                  'MSAN_OPTIONS', 'TSAN_OPTIONS', 'UBSAN_OPTIONS', 'LLVM_PROFILE_FILE',
                  'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CMAKE_ARGS',
                  'CTEST_TEST_ARGS', 'CTEST_PARALLEL_LEVEL', 'LD_PRELOAD', 'LD_LIBRARY_PATH')
RUNTIME_ENV = {'ASAN_OPTIONS': 'detect_leaks=1:detect_stack_use_after_return=1:halt_on_error=1:symbolize=1',
               'LSAN_OPTIONS': 'exitcode=23',
               'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
               'MSAN_OPTIONS': 'halt_on_error=1:exit_code=24:print_stats=1',
               'TSAN_OPTIONS': 'halt_on_error=1:exitcode=25',
               'ASAN_SYMBOLIZER_PATH': '/usr/lib/llvm-19/bin/llvm-symbolizer'}

def environment_gate(environment=None):
    inherited = os.environ if environment is None else environment
    bad = [key for key in PROHIBITED_ENV if inherited.get(key)]
    if bad:
        raise GateError('prohibited inherited options: ' + ', '.join(bad))

class Runner:
    def __init__(self, root: Path, run_dir: Path, lock, scratch: Path):
        self.root, self.run_dir, self.lock, self.scratch = root.resolve(), run_dir, lock, scratch.resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.records = []
        self.name = 'safe-c-' + uuid.uuid4().hex
        self.alive = False

    def start(self):
        if self.alive:
            return
        argv = ['docker', 'run', '-d', '--pull=never', '--name', self.name,
                '--network=none', '--read-only', '--cap-drop=ALL',
                '--security-opt=no-new-privileges', '--memory=3g', '--memory-swap=3g',
                '--cpus=2', '--pids-limit=128', '--ulimit', 'core=0',
                '--ulimit', 'fsize=33554432:33554432',
                '--user', f'{os.getuid()}:{os.getgid()}',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
                '--tmpfs', f'/work:rw,exec,nosuid,nodev,size=2g,uid={os.getuid()},gid={os.getgid()}',
                '--mount', f'type=bind,src={self.root},dst=/src,readonly',
                '--workdir', '/work', self.lock['image_id'],
                'python3', '-c', 'import time; time.sleep(43200)']
        result = bounded(argv, timeout=30)
        if result['exit_code'] != 0 or result['failure']:
            raise GateError('isolated runner unavailable: ' + result['output'])
        self.alive = True

    def close(self):
        if self.alive:
            bounded(['docker', 'rm', '--force', self.name], timeout=15)
            self.alive = False

    def fetch(self, relative, destination=None):
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise GateError('unsafe scratch path')
        destination = destination or self.scratch / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        import base64
        result = bounded(['docker', 'exec', self.name, 'python3', '-c',
                          'import pathlib,base64,sys; p=pathlib.Path(sys.argv[1]); data=p.read_bytes(); assert len(data)<=33554432; print(base64.b64encode(data).decode())',
                          '/work/'+relative], timeout=30, limit=48*1024*1024)
        if result['exit_code'] != 0 or result['failure']:
            raise GateError('missing build evidence: '+relative+': '+result['output'][:500])
        destination.write_bytes(base64.b64decode(result['output'], validate=False))
        return destination

    def run(self, args, *, timeout=30, env=None, label='process'):
        self.start()
        self.counter += 1
        argv = ['docker', 'exec', '--workdir', '/work']
        settings = dict(RUNTIME_ENV)
        settings.update(env or {})
        for key, value in settings.items():
            argv.extend(['--env', f'{key}={value}'])
        argv.extend([self.name, *args])
        result = bounded(argv, timeout=timeout)
        if result['failure']:
            self.close()  # Docker reaps every descendant; no retry of this result.
        result['command'] = list(args)
        result['image_id'] = self.lock['image_id']
        filename = f'{self.counter:04d}-{label}.json'
        result['evidence_path'] = str(self.run_dir / 'evidence' / filename)
        atomic_json(Path(result['evidence_path']), result)
        self.records.append(result)
        return result

def passed(result):
    return result['exit_code'] == 0 and result['failure'] is None
