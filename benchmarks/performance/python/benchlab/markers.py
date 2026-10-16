"""Client side of the coordinator handshake channel (newline JSON over a Unix socket)."""
import json, os, socket

class Marker:
    def __init__(self,path=None):
        path=path if path is not None else os.environ.get('SAFE_C_BENCH_MARKER')
        self.sock=None;self.file=None
        if path:
            self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.connect(path);self.file=self.sock.makefile('rwb')
    def _write(self,obj):
        self.file.write((json.dumps(obj,separators=(',',':'),allow_nan=False)+'\n').encode());self.file.flush()
    def _read(self):
        line=self.file.readline()
        if not line:raise ConnectionError('coordinator closed the marker channel')
        return json.loads(line)
    def _send(self,obj):
        if self.sock is None:return {}
        self._write(obj);return self._read()
    def hello(self,client):return self._send({'m':'hello','client':client})
    def begin(self,phase,trial):return self._send({'m':'begin','phase':phase,'trial':trial})
    def end(self,phase,trial,**fields):return self._send({'m':'end','phase':phase,'trial':trial,**fields})
    def note(self,trial,**fields):return self._send({'m':'note','trial':trial,**fields})
    def close(self):
        """Close the stream and the socket. Safe to call twice and without a channel."""
        for handle in (self.file,self.sock):
            if handle is not None:handle.close()
        self.file=None
    def command(self):
        if self.sock is None:return {'op':'shutdown'}
        return self._read()
