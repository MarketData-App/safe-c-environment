"""The demo-digest workload (FR6): xorshift64 steps folded into an FNV-1a checksum per record (benchdemo.reference, the
native Python version; specs/project/bd_digest.md). The C module src/bd_digest.c gives the same bytes.

Dataset: the 8-byte magic DATASET_MAGIC, then packed request records (12 bytes each: u64 seed, u32 steps, little-endian).
A dataset of 0 records is allowed and gives no request. `prepare` splits the records into requests of at most
RECORDS_MAX records; `run` digests each request; the result holds one 32-digit hex value (the 16 output bytes) per record.

FR6 N4, the three versions: py-reference is the native Python version; c-serial is the C code, over the route that the
framework trial child sets (`route`: stdio, shm or inproc, through benchdemo.native.Session) or, in a kernel trial, the
bd-kernel program with no Python in its timed loops (pack_native writes its input, unpack_native reads its output and
native_reference_digest gives the canonical digest of the reference output, the FNV-1a 64 that bd-kernel prints).
native_start and native_stop are the framework hooks of a warm and a cold C row."""
import hashlib, json
from benchlab import native_worker as nw
from benchdemo import reference as r
MAX_BYTES=33554432;DATASET_MAGIC=b'bd-demo\x01';DIRECT=('py-reference','py-optimized');NATIVE=('c-serial',)

class DemoDigest:
    def __init__(self,params):
        self.params=dict(params);self.bench_ref=('benchdemo.adapter:DemoDigest',self.params);self.route=None;self.session=None
        steps=self.params.get('steps')
        if type(steps) is not int or not 0<=steps<=r.STEPS_MAX:raise ValueError('invalid parameter: steps must be an integer in 0..1000000')
        self.steps=steps
    def synthesize(self,rows,seed):
        """`rows` records; record i has seed (seed * 1000003 + i) * ZERO_SEED (mod 2**64) and the case's step count."""
        if isinstance(rows,bool) or not isinstance(rows,int) or rows<0:raise ValueError('rows must be a non-negative integer')
        if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError('seed must be a non-negative integer')
        return DATASET_MAGIC+r.encode_request((((seed*1000003+i)*r.ZERO_SEED)&r.MASK,self.steps) for i in range(rows))
    def load(self,dataset_ref):
        with open(dataset_ref['path'],'rb') as f:data=f.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('dataset exceeds 32 MiB')
        if hashlib.sha256(data).hexdigest()!=dataset_ref['sha256']:raise ValueError('dataset digest mismatch')
        if not data.startswith(DATASET_MAGIC) or (len(data)-len(DATASET_MAGIC))%r.RECORD_IN:raise ValueError('not a bench-demo dataset')
        records=data[len(DATASET_MAGIC):]
        for start in range(0,len(records),r.RECORDS_MAX*r.RECORD_IN):r.check_request(records[start:start+r.RECORDS_MAX*r.RECORD_IN])
        return records
    def slice(self,data,n):
        if type(n) is not int or n<0 or n*r.RECORD_IN>len(data):raise ValueError('slice outside the dataset')
        return data[:n*r.RECORD_IN]
    def prepare(self,data,variant,workers=1):
        if variant not in DIRECT+NATIVE:raise ValueError('demo-digest has the direct Python variants and c-serial')
        step=r.RECORDS_MAX*r.RECORD_IN
        return [data[start:start+step] for start in range(0,len(data),step)]
    def run(self,prepared,variant,workers,pool=None):
        if variant in NATIVE:return self._native_run(prepared)
        return [r.digest_request(request) for request in prepared]
    def _native_run(self,prepared):
        """c-serial over self.route; a cold row starts its session inside the call (native_stop ends it after the call)."""
        session=self._session();before=dict(session.stats);out=[session.digest(request) for request in prepared]
        nw.LAST_STATS.update(transport_ns=session.stats['transport_ns']-before['transport_ns'],copied_bytes=session.stats['copied_bytes']-before['copied_bytes'],
                             load_process=session.stats['load_process'])
        return out
    def _session(self):
        from benchdemo import native
        if self.route not in ('stdio','shm','inproc'):raise ValueError('a c-serial caller row needs the route stdio, shm or inproc')
        if self.session is None or self.session.route!=self.route:self.session=native.Session(self.route)
        return self.session
    def native_start(self,variant,workers):
        """Framework hook (warm C row): start the worker or load the library before the first interval."""
        if variant in NATIVE:self._session().start()
    def native_stop(self,variant,workers):
        """Framework hook (after a cold C call, and at shutdown): stop the worker."""
        if self.session is not None:self.session.stop()
    def pack_native(self,data):
        """The bd-kernel input file: the packed request records of the sliced dataset (12 bytes each)."""
        return bytes(data)
    def unpack_native(self,output):
        """The result of a bd-kernel output file (16 bytes per record), in the form of materialize."""
        if len(output)%r.RECORD_OUT:raise ValueError('kernel output is not whole records')
        return self.materialize([bytes(output)])
    def native_reference_digest(self,reference):
        """The canonical digest of the reference output: FNV-1a 64 of its output bytes, 16 hex digits (bd-kernel digest=)."""
        return format(r.fnv1a(bytes.fromhex(''.join(reference['values']))),'016x')
    def materialize(self,raw):
        out=b''.join(raw)
        return {'values':[out[i:i+r.RECORD_OUT].hex() for i in range(0,len(out),r.RECORD_OUT)]}
    def work_units(self,result):return len(result['values'])
    def reference(self,data):return self.materialize(self.run(self.prepare(data,'py-reference'),'py-reference',1))
    def slice_result(self,result,n,data):return {'values':result['values'][:n]}
    def validate(self,result,reference,data):
        ok=result==reference;count=len(result.get('values',[]))!=len(reference['values'])
        return {'eligible':ok,'failures':{} if ok else {'values':1},'reduction':'MATCH' if ok else 'ROW_COUNT' if count else 'MISMATCH'}
    def digest(self,result):return hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
