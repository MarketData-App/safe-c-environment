"""Small bounded GDB/MI adapter, invoked only within the protected container."""
import ast
import errno
import json
import os
from pathlib import Path
import pty
import re
import selectors
import signal
import subprocess
import termios
import time

from evidence import GateError, file_hash


class MIParser:
    def __init__(self, text):
        self.text, self.cursor = text, 0

    def value(self, depth=0):
        if depth > 24 or self.cursor >= len(self.text):
            raise GateError('MI nesting or missing value rejected')
        char = self.text[self.cursor]
        if char == '"':
            start = self.cursor
            self.cursor += 1
            escaped = False
            while self.cursor < len(self.text):
                char = self.text[self.cursor]
                self.cursor += 1
                if char == '"' and not escaped:
                    value = ast.literal_eval(self.text[start:self.cursor])
                    if not isinstance(value, str):
                        raise GateError('MI string type rejected')
                    return value
                escaped = char == '\\' and not escaped
            raise GateError('unterminated MI string')
        if char not in '{[':
            raise GateError('MI value grammar rejected')
        closer = '}' if char == '{' else ']'
        self.cursor += 1
        values = []
        fields = {}
        while self.cursor < len(self.text) and self.text[self.cursor] != closer:
            match = re.match(r'([A-Za-z_][A-Za-z0-9_-]*)=', self.text[self.cursor:])
            if match:
                self.cursor += len(match[0])
                key, value = match[1], self.value(depth + 1)
                if char == '{':
                    if key in fields:
                        raise GateError('duplicate MI tuple field')
                    fields[key] = value
                else:
                    values.append({key: value})
            else:
                if char == '{':
                    raise GateError('MI tuple requires named fields')
                values.append(self.value(depth + 1))
            if self.cursor < len(self.text) and self.text[self.cursor] == ',':
                self.cursor += 1
            elif self.cursor >= len(self.text) or self.text[self.cursor] != closer:
                raise GateError('MI collection delimiter missing')
        if self.cursor >= len(self.text):
            raise GateError('MI collection incomplete')
        self.cursor += 1
        return fields if char == '{' else values


def parse(line, maximum=1048576):
    if len(line.encode()) > maximum:
        raise GateError('MI record exceeds message bound')
    if line.strip() == '(gdb)':
        return {'kind': 'prompt'}
    match = re.fullmatch(r'(\d*)([\^*=+~@&])(.*)', line)
    if not match:
        raise GateError('unframed GDB protocol record')
    token, kind, rest = match.groups()
    if kind in '~@&':
        parser = MIParser(rest)
        value = parser.value()
        if parser.cursor != len(rest) or not isinstance(value, str):
            raise GateError('MI stream grammar rejected')
        return {'kind': kind, 'value': value}
    name, separator, tail = rest.partition(',')
    if not re.fullmatch(r'[a-z][a-z0-9-]*', name):
        raise GateError('MI result class rejected')
    parser = MIParser('{' + tail + '}')
    fields = parser.value()
    if parser.cursor != len(parser.text):
        raise GateError('MI trailing data rejected')
    return {'kind': kind, 'class': name, 'token': int(token) if token else None,
            'fields': fields}


def quoted(value):
    return json.dumps(value, ensure_ascii=True)


class Session:
    def __init__(self, policy, output, executable, arguments):
        self.limits, self.output = policy['limits'], output
        self.deadline = time.monotonic() + self.limits['server_wall_seconds']
        self.total = 0
        self.token = 0
        self.buffer = b''
        self.events = []
        self.errors = []
        self.protocol = (output / 'gdb-mi.opaque.log').open('wb')
        self.inferior_log = (output / 'inferior.opaque.log').open('wb')
        self.master, self.slave = pty.openpty()
        attributes = termios.tcgetattr(self.slave)
        attributes[3] &= ~termios.ECHO
        termios.tcsetattr(self.slave, termios.TCSANOW, attributes)
        self.tty = os.ttyname(self.slave)
        startup = ['auto-load off', 'auto-load safe-path /nonexistent-safe-c-auto-load',
                   'debuginfod enabled off', 'startup-with-shell off',
                   'may-call-functions off', 'disable-randomization off',
                   'libthread-db-search-path ' + policy['debugger']['libthread_db_directory'],
                   'pagination off', 'confirm off']
        argv = ['/usr/bin/gdb', '-nx', '-q', '--interpreter=mi2']
        for setting in startup:
            argv.extend(['-iex', 'set ' + setting])
        # --args consumes an argv vector. Unlike most MI commands,
        # -exec-arguments retains its raw argument text and cannot use the
        # generic MI C-string parameter encoder without changing literal argv.
        argv.extend(['--args',str(executable),*arguments])
        self.argv = argv
        environment = {'PATH': '/usr/bin:/bin', 'HOME': '/work/debug-home',
                       'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                       'DEBUGINFOD_URLS': '', 'TERM': 'dumb'}
        Path(environment['HOME']).mkdir(exist_ok=True)
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, env=environment,
                                        cwd='/work', start_new_session=True)
        self.selector = selectors.DefaultSelector()
        for descriptor in [self.process.stdout.fileno(), self.master]:
            os.set_blocking(descriptor, False)
            self.selector.register(descriptor, selectors.EVENT_READ)
        os.set_blocking(self.process.stdin.fileno(), False)

    def remaining(self):
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise GateError('debugger deadline exhausted')
        return value

    def read(self):
        idle = time.monotonic() + self.limits['server_idle_seconds']
        while True:
            if b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                record = parse(line.rstrip(b'\r').decode('utf-8', errors='strict'))
                if record['kind'] == '*' and record['class'] == 'stopped':
                    self.events.append(record['fields'])
                return record
            timeout = min(self.remaining(), idle - time.monotonic())
            if timeout <= 0:
                raise GateError('debugger protocol idle deadline exhausted')
            for key, _ in self.selector.select(timeout):
                try:
                    data = os.read(key.fd, 65536)
                except OSError as error:
                    if key.fd == self.master and error.errno == errno.EIO:
                        continue
                    raise
                if not data:
                    if key.fd == self.process.stdout.fileno():
                        raise GateError('GDB protocol ended before required response')
                    continue
                self.total += len(data)
                if self.total > self.limits['protocol_total_bytes']:
                    raise GateError('debugger capture bound exhausted; evidence incomplete')
                if key.fd == self.master:
                    self.inferior_log.write(data)
                else:
                    self.protocol.write(data)
                    self.buffer += data
            if len(self.buffer) > self.limits['message_bytes']:
                raise GateError('debugger record bound exhausted')

    def command(self, operation, *arguments):
        self.token += 1
        payload = (str(self.token) + '-' + operation +
                   ''.join(' ' + quoted(str(p)) for p in arguments) + '\n').encode()
        cursor = 0
        while cursor < len(payload):
            self.remaining()
            try:
                cursor += os.write(self.process.stdin.fileno(), payload[cursor:])
            except BlockingIOError:
                import select
                if not select.select([], [self.process.stdin], [], min(self.remaining(), 1))[1]:
                    continue
        while True:
            record = self.read()
            if record['kind'] == '^':
                if record['token'] != self.token:
                    raise GateError('uncorrelated GDB result token')
                if record['class'] == 'error':
                    self.errors.append(record['fields'])
                    raise GateError('GDB rejected a required typed operation')
                return record

    def stopped(self, previous):
        while len(self.events) <= previous:
            self.read()
        return self.events[-1]

    def close(self):
        if self.process.poll() is None and self.deadline>time.monotonic():
            try:
                self.command('gdb-exit')
            except (GateError,BrokenPipeError,OSError):
                pass
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=3)
        while True:
            try:
                data=os.read(self.master,65536)
            except (BlockingIOError,OSError):
                break
            if not data:break
            self.total+=len(data)
            if self.total>self.limits['protocol_total_bytes']:
                raise GateError('inferior capture bound exhausted during teardown')
            self.inferior_log.write(data)
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()
        os.close(self.master)
        os.close(self.slave)
        self.protocol.close()
        self.inferior_log.close()


def inspect(request, target, policy, output):
    executable = Path('/work/developer-build') / target
    if not executable.is_file() or executable.is_symlink():
        raise GateError('matching debug executable missing')
    result = {'debug_session_status': 'FAIL', 'inspection_requirements_met': False,
              'inferior_outcome': {'status': 'NOT_COMPLETED'}, 'complete_capture': False,
              'executable_sha256': file_hash(executable), 'profile': request['profile'],
              'recipe': request['recipe'], 'stop': None, 'step': None,
              'frames': [], 'locals': [], 'values': {}, 'threads': [], 'errors': [],'timed_out':False}
    session = None
    try:
        session = Session(policy, output, executable, request.get('arguments',[]))
        result['debugger_argv'] = session.argv
        result['inferior_argv'] = [str(executable), *request.get('arguments', [])]
        session.command('inferior-tty-set', session.tty)
        session.command('file-exec-and-symbols', str(executable))
        symbols = session.command('file-list-exec-source-files')['fields'].get('files', [])
        if not any(p.get('fullname', '').startswith('/src/') for p in symbols):
            raise GateError('first-party matching debug symbols unavailable')
        if request['recipe'] == 'breakpoint':
            location=request['location']
            native_location=('/fixture/'+location.removeprefix('demo/') if location.startswith('demo/') else '/src/'+location)
            resolved = session.command('break-insert', native_location)['fields']['bkpt']
            if resolved.get('addr') in {None, '<PENDING>'} or not resolved.get('line'):
                raise GateError('source breakpoint did not resolve')
            result['breakpoint'] = resolved
        before = len(session.events)
        session.command('exec-run')
        stop = session.stopped(before)
        result['stop'] = stop
        wanted = ('breakpoint-hit' if request['recipe'] == 'breakpoint' else 'signal-received')
        reached = stop.get('reason') == wanted
        if request['recipe'] == 'breakpoint':
            reached = reached and stop.get('bkptno') == result['breakpoint']['number']
        if reached:
            result['frames'] = session.command('stack-list-frames', '0', str(policy['limits']['max_frames'] - 1))['fields'].get('stack', [])
            result['locals'] = session.command('stack-list-variables', '--simple-values')['fields'].get('variables', [])[:policy['limits']['max_values']]
            for name in request.get('values', []):
                result['values'][name] = session.command('data-evaluate-expression', name)['fields']['value']
            threads = session.command('thread-info')['fields'].get('threads', [])
            if len(threads) > policy['limits']['max_threads']:
                raise GateError('debugger thread inventory exceeds bound')
            for thread in threads:
                identifier = thread.get('id', '')
                if not re.fullmatch(r'[0-9]+', identifier):
                    raise GateError('debugger thread identifier malformed')
                session.command('thread-select', identifier)
                stack = session.command('stack-list-frames', '0', str(policy['limits']['max_frames'] - 1))['fields'].get('stack', [])
                result['threads'].append({'id': identifier, 'frames': stack})
            if stop.get('thread-id'):
                session.command('thread-select', stop['thread-id'])
            for _ in range(request.get('steps', 0)):
                before = len(session.events)
                session.command('exec-next')
                result['step'] = session.stopped(before)
                if result['step'].get('reason') != 'end-stepping-range':
                    raise GateError('requested source step did not complete')
            before = len(session.events)
            session.command('exec-continue')
            endpoint = session.stopped(before)
        else:
            endpoint = stop
        reason = endpoint.get('reason')
        if reason == 'exited-normally':
            result['inferior_outcome'] = {'status': 'PASSED', 'exit_code': 0}
        elif reason == 'exited':
            code = endpoint.get('exit-code', '')
            result['inferior_outcome'] = {'status': 'FAILED', 'exit_code': int(code, 8) if code else None}
        elif reason == 'exited-signalled':
            result['inferior_outcome'] = {'status': 'FAILED', 'signal': endpoint.get('signal-name')}
        else:
            result['inferior_outcome'] = {'status': 'STOPPED', 'reason': reason}
        result['inspection_requirements_met'] = reached
        result['debug_session_status'] = 'PASS' if reached and reason in {'exited-normally', 'exited', 'exited-signalled'} else 'FAIL'
        result['complete_capture'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
        result['error_property'] = str(error) if isinstance(error, GateError) else None
        if isinstance(error,GateError) and 'deadline' in str(error):
            result['timed_out']=True
            result['inferior_outcome']={'status':'TIMEOUT'}
    finally:
        if session is not None:
            result['errors'] = session.errors
            result['stop_events'] = session.events
            session.close()
            result['inferior_output_sha256']=file_hash(output/'inferior.opaque.log')
            result['inferior_output_bytes']=(output/'inferior.opaque.log').stat().st_size
    return result
