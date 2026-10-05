"""Small saved-file stdio LSP client; execute clangd only inside Docker."""
from pathlib import Path
import json
import os
import selectors
import signal
import subprocess
import time
from urllib.parse import quote, unquote, urlsplit

from evidence import GateError

ENCODINGS = {'utf-8', 'utf-16', 'utf-32'}


def position(text, line, column, encoding):
    if encoding not in ENCODINGS or type(line) is not int or type(column) is not int:
        raise GateError('unsupported semantic position encoding or coordinate type')
    lines = text.split('\n')
    if not 1 <= line <= len(lines):
        raise GateError('semantic line outside saved document')
    value = lines[line - 1].removesuffix('\r')
    if not 1 <= column <= len(value) + 1:
        raise GateError('semantic column outside saved document')
    prefix = value[:column - 1]
    if any(0xD800 <= ord(c) <= 0xDFFF for c in prefix):
        raise GateError('semantic position contains a non-scalar character')
    units = (len(prefix.encode('utf-8')) if encoding == 'utf-8' else
             len(prefix.encode('utf-16-le')) // 2 if encoding == 'utf-16' else len(prefix))
    return {'line': line - 1, 'character': units}


def scalar_position(text, value, encoding):
    if (type(value.get('line')) is not int or type(value.get('character')) is not int or
            value['line'] < 0 or value['character'] < 0):
        raise GateError('invalid server position')
    lines = text.split('\n')
    if value['line'] >= len(lines):
        raise GateError('server position outside known document')
    line = lines[value['line']].removesuffix('\r')
    for column in range(1, len(line) + 2):
        if position(line, 1, column, encoding)['character'] == value['character']:
            return {'line': value['line'] + 1, 'column': column}
    raise GateError('server position is not a Unicode scalar boundary')


def uri(path):
    return 'file://' + quote(str(path), safe='/')


class Client:
    def __init__(self, policy):
        self.policy = policy
        self.started = time.monotonic()
        self.last_activity = self.started
        self.sequence = 0
        self.buffer = bytearray()
        self.total = 0
        self.events = []
        self.diagnostics = {}
        self.file_status = {}
        self.progress = {}
        self.progress_end_observed = False
        self.opened = {}
        self.completed = False
        self.error = Path('/work/developer-job/clangd.opaque.log').open('wb')
        self.transport = Path('/work/developer-job/lsp-transport.opaque.jsonl').open('wb')
        self.process = subprocess.Popen(
            ['/usr/lib/llvm-19/bin/clangd', '--compile-commands-dir=/work/developer-build',
             '--enable-config=false', '--background-index', '-j=2', '--log=verbose'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.error,
            cwd='/work/developer-build', start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        os.set_blocking(self.process.stdin.fileno(),False)
        self.encoding = 'utf-16'

    def record(self, direction, value):
        data = json.dumps({'direction': direction, 'message': value}, ensure_ascii=True).encode() + b'\n'
        self.total += len(data)
        if self.total > self.policy['limits']['protocol_total_bytes']:
            raise GateError('semantic protocol total output bound exceeded')
        self.transport.write(data)
        self.transport.flush()

    def send(self, value):
        data = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
        if len(data) > self.policy['limits']['message_bytes']:
            raise GateError('semantic protocol message bound exceeded')
        self.record('out', value)
        payload=b'Content-Length: ' + str(len(data)).encode() + b'\r\n\r\n' + data
        cursor=0
        import select
        while cursor<len(payload):
            remaining=self.policy['limits']['server_wall_seconds']-(time.monotonic()-self.started)
            idle=self.policy['limits']['server_idle_seconds']-(time.monotonic()-self.last_activity)
            if min(remaining,idle)<=0:raise GateError('semantic write deadline exhausted')
            try:
                cursor+=os.write(self.process.stdin.fileno(),payload[cursor:])
                self.last_activity=time.monotonic()
            except BlockingIOError:
                select.select([],[self.process.stdin],[],min(remaining,idle,.1))

    def notify(self, method, params):
        self.send({'jsonrpc': '2.0', 'method': method, 'params': params})

    def read(self):
        while True:
            marker = self.buffer.find(b'\r\n\r\n')
            if marker >= 0:
                if marker > 8192:
                    raise GateError('semantic protocol header bound exceeded')
                fields = self.buffer[:marker].decode('ascii').split('\r\n')
                lengths = [int(line.split(':', 1)[1].strip()) for line in fields
                           if line.lower().startswith('content-length:')]
                if len(lengths) != 1 or not 0 < lengths[0] <= self.policy['limits']['message_bytes']:
                    raise GateError('invalid semantic protocol content length')
                end = marker + 4 + lengths[0]
                if len(self.buffer) >= end:
                    value = json.loads(self.buffer[marker + 4:end].decode('utf-8'))
                    del self.buffer[:end]
                    if not isinstance(value, dict) or value.get('jsonrpc') != '2.0':
                        raise GateError('invalid semantic protocol record')
                    self.record('in', value)
                    return value
            now = time.monotonic()
            if now - self.started >= self.policy['limits']['server_wall_seconds']:
                raise GateError('semantic server overall deadline exhausted')
            if now - self.last_activity >= self.policy['limits']['server_idle_seconds']:
                raise GateError('semantic server idle deadline exhausted')
            ready = self.selector.select(.1)
            if ready:
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise GateError('semantic server transport closed before completion')
                self.last_activity = time.monotonic()
                self.buffer.extend(data)
                if len(self.buffer) > self.policy['limits']['message_bytes'] + 8192:
                    raise GateError('semantic protocol buffered message bound exceeded')

    def handle(self, value):
        method = value.get('method')
        params = value.get('params', {})
        if method and 'id' in value:
            if method == 'window/workDoneProgress/create':
                self.send({'jsonrpc': '2.0', 'id': value['id'], 'result': None})
            elif method == 'workspace/configuration':
                self.send({'jsonrpc': '2.0', 'id': value['id'],
                           'result': [None] * len(params.get('items', []))})
            else:
                self.send({'jsonrpc': '2.0', 'id': value['id'],
                           'error': {'code': -32601, 'message': 'Client method unsupported'}})
        elif method == 'textDocument/publishDiagnostics':
            if params.get('uri') in self.opened and params.get('version', 1) == 1:
                self.diagnostics[params['uri']] = params.get('diagnostics', [])
        elif method == 'textDocument/clangd.fileStatus':
            self.file_status[params['uri']] = params.get('state')
        elif method == '$/progress':
            token, progress = params.get('token'), params.get('value', {})
            if progress.get('kind') == 'begin':
                self.progress[token] = 'ACTIVE'
            elif progress.get('kind') == 'end':
                self.progress[token] = 'ENDED'
                self.progress_end_observed = True
        self.events.append({'method': method, 'id': value.get('id')})

    def request(self, method, params):
        self.sequence += 1
        identifier = self.sequence
        self.send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params})
        try:
            while True:
                value = self.read()
                if type(value.get('id')) is int and value['id'] == identifier and 'method' not in value:
                    if 'error' in value:
                        raise GateError('semantic server rejected the correlated request')
                    if 'result' not in value:
                        raise GateError('semantic response omitted its result')
                    return value['result']
                self.handle(value)
        except GateError:
            self.notify('$/cancelRequest', {'id': identifier})
            raise

    def initialize(self):
        value = self.request('initialize', {
            'processId': None, 'rootUri': 'file:///src',
            'capabilities': {'general': {'positionEncodings': ['utf-8', 'utf-16', 'utf-32']},
                             'offsetEncoding': ['utf-8', 'utf-16', 'utf-32'],
                             'window': {'workDoneProgress': True},
                             'textDocument': {'publishDiagnostics': {'versionSupport': True}}},
            'initializationOptions': {'clangdFileStatus': True}})
        self.capabilities = value['capabilities']
        self.encoding = self.capabilities.get('positionEncoding', value.get('offsetEncoding', 'utf-16'))
        if self.encoding not in ENCODINGS:
            raise GateError('semantic server selected an unsupported position encoding')
        self.notify('initialized', {})

    def open(self, path):
        if not path.is_file() or path.stat().st_size > self.policy['limits']['document_bytes']:
            raise GateError('semantic saved document unavailable or oversized')
        text = path.read_bytes().decode('utf-8')
        address = uri(path)
        if address not in self.opened:
            self.opened[address] = text
            self.notify('textDocument/didOpen', {'textDocument': {
                'uri': address, 'languageId': 'c', 'version': 1, 'text': text}})
        return address

    def await_documents(self, addresses):
        while any(address not in self.diagnostics or self.file_status.get(address) != 'idle'
                  for address in addresses):
            self.handle(self.read())

    def await_observed_index(self):
        # Finish the background work actually announced by this local server.
        # An ended local batch is still not a global completeness guarantee.
        while any(value=='ACTIVE' for value in self.progress.values()):
            self.handle(self.read())

    def close(self):
        try:
            if self.process.poll() is None:
                self.request('shutdown', None)
                self.notify('exit', {})
                self.process.stdin.close()
                self.process.wait(timeout=3)
                self.completed = self.process.returncode == 0
        finally:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
            self.selector.close()
            self.process.stdout.close()
            if not self.process.stdin.closed:
                self.process.stdin.close()
            self.error.close()
            self.transport.close()


def mapped(value, encoding, default_path=None):
    """Convert protocol locations without ever interpreting a source expression."""
    if isinstance(value, list):
        return [mapped(row, encoding, default_path) for row in value]
    if not isinstance(value, dict):
        return value
    row = {k: mapped(v, encoding, default_path) for k, v in value.items()}
    address = value.get('uri') or value.get('targetUri')
    ranges = [key for key in ['range', 'selectionRange', 'targetRange', 'targetSelectionRange'] if key in value]
    if address or (default_path is not None and ranges):
        path = default_path
    if address:
        split = urlsplit(address)
        if split.scheme != 'file' or split.netloc not in {'', 'localhost'}:
            raise GateError('semantic result has an unapproved URI scheme')
        path = Path(unquote(split.path))
        if '..' in path.parts or any(c in str(path) for c in '\0\n\r'):
            raise GateError('semantic result has an unsafe URI path')
    if address or (default_path is not None and ranges):
        if path.is_relative_to('/src'):
            location = {'scope': 'source', 'path': str(path.relative_to('/src'))}
        elif path.is_relative_to('/fixture'):
            location = {'scope': 'demo-source', 'path': 'demo/'+str(path.relative_to('/fixture'))}
        elif path.is_relative_to('/opt/foundation'):
            location = {'scope': 'dependency', 'path': str(path.relative_to('/opt/foundation'))}
        elif path.is_relative_to('/usr') or path.is_relative_to('/work/developer-build'):
            location = {'scope': 'toolchain' if path.is_relative_to('/usr') else 'generated', 'path': str(path)}
        else:
            raise GateError('semantic result points outside approved source/header domains')
        text = path.read_bytes().decode('utf-8')
        for key in ['range', 'selectionRange', 'targetRange', 'targetSelectionRange']:
            if key in value:
                location[key] = {end: scalar_position(text, value[key][end], encoding)
                                 for end in ['start', 'end']}
                row[key] = location[key]
        row['mapped_location'] = location
    return row


def navigate(request, database, targets, policy):
    current=Path('/work/developer-build/compile_commands.json')
    if not current.is_file() or json.loads(current.read_text())!=database:
        raise GateError('actual semantic compilation context is missing or changed')
    known = {row['file'] for row in database}
    kind = request['kind']
    requested=request.get('file', 'foundation/tests/recipes.c')
    path = (Path('/fixture')/requested.removeprefix('demo/') if requested.startswith('demo/') and
            request.get('demo_workspace') else Path('/src')/requested)
    context = None
    if path.suffix == '.h':
        if not request.get('tu') or '/src/' + request['tu'] not in known:
            raise GateError('public header query requires an actual registered including TU')
        context = '/src/' + request['tu']
    elif str(path) not in known:
        raise GateError('semantic source has no actual registered compilation command')
    client = Client(policy)
    try:
        client.initialize()
        if context:
            including = client.open(Path(context))
            client.await_documents([including])
        address = client.open(path)
        client.await_documents([address])
        others = [client.open(Path(source)) for source in sorted(known) if source != str(path)]
        client.await_documents(others)
        if kind in {'references','workspace-symbols'}:
            client.await_observed_index()
        params = {'textDocument': {'uri': address}}
        if kind in {'definition', 'references', 'hover'}:
            params['position'] = position(client.opened[address], request['line'], request['column'], client.encoding)
        if kind == 'references':
            params['context'] = {'includeDeclaration': True}
        if kind == 'diagnostics':
            answer = client.diagnostics[address]
        elif kind == 'workspace-symbols':
            answer = client.request('workspace/symbol', {'query': request['symbol']})
        else:
            method = {'definition': 'textDocument/definition', 'references': 'textDocument/references',
                      'hover': 'textDocument/hover', 'document-symbols': 'textDocument/documentSymbol'}[kind]
            answer = client.request(method, params)
        result = {'kind': kind, 'result': mapped(answer, client.encoding, path),
                  'position_encoding': client.encoding, 'saved_documents': len(client.opened),
                  'document_version': 1, 'including_tu': context,
                  'diagnostics_complete': address in client.diagnostics,
                  'local_index_progress_end_observed': client.progress_end_observed,
                  'active_index_progress': sum(v == 'ACTIVE' for v in client.progress.values()),
                  'global_index_complete': False,
                  'cross_file_result_may_be_incomplete': bool(kind in {'references', 'workspace-symbols'} and
                      (not client.progress_end_observed or any(v == 'ACTIVE' for v in client.progress.values()))),
                  'acceptance': False}
    finally:
        client.close()
    result['server_shutdown_complete'] = client.completed
    if not client.completed:
        raise GateError('semantic server cleanup/shutdown incomplete')
    if context:
        observed = Path('/work/developer-job/clangd.opaque.log').read_text(errors='replace')
        needle = str(path) + ' version 1 with command inferred from ' + context
        result['header_context_observed'] = needle in observed
        if not result['header_context_observed']:
            raise GateError('semantic header command did not match the explicit including TU')
    return result
