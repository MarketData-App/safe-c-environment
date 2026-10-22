"""The option codec of the C rows (task EX-10; Phase 2 Task 20 adapted by ruling R43): the SCPL v2 record layout of
specs/project/protocol.md for pl-worker, pl-kernel and libpl_inproc.so.

Request record, 64 bytes `<8d`: side value (0.0 a call, 1.0 a put, 2.0 an unknown side, so the C side decodes it to -1 and
the row is INVALID_INPUT as in py-reference), S, K, T, bid, ask, r, q. Response record, 290 bytes `<5B5B35d`: five status
bytes and five flag bytes in MODELS5 order, then the seven fields (FIELDS order) of each model. Response payload: n records,
then the trailer u32 k and k x (u32 chunk size, u32 0, u64 chunk wall ns); k = 0 for threads 0, else min(threads, n).

materialize applies the response record rule of protocol.md (G4.5, N7, I5.3): a selected part holds a status 0-8 (255 ECHO
only for an echo request) and only its legal flag bits; an unselected part is exactly NOT_REQUESTED, flags 0 and seven fields
with the bits NAN_BITS. Anything else raises ValueError('RESERVED_NONZERO'). The result has the `reference.run` shape with
exactly the selected models. encode_records is its inverse (EX-14: the record-level agreement controls only).

The kernel digest (R43 item d): canonical_digest is FNV-1a 64 over the ocg-v1 / ocg-v1m bytes of
optionlab.reference.canonical_result, as 16 lowercase hex digits; pl-kernel prints the same value as `PLK1 ... digest=`
(specs/project/batch.md "Kernel digest"). No literal request limit: requests() takes the limit of
benchlab.workload.request_limit() from its caller (R43 item e)."""
import math, re, struct
from optionlab.contract import FIELDS, MODELS5, STATUSES

REQUEST_RECORD=struct.Struct('<8d');RESPONSE_RECORD=struct.Struct('<5B5B35d')
RECORD_IN=REQUEST_RECORD.size;RECORD_OUT=RESPONSE_RECORD.size
ECHO=255;NOT_REQUESTED=254;NAN_BITS=0x7FF8000000000000
MODEL_BITS={m:1<<k for k,m in enumerate(MODELS5)}
ALL_MASK=(1<<len(MODELS5))-1
TRAILER_HEAD=struct.Struct('<I');TRAILER_ENTRY=struct.Struct('<IIQ')
FLAGS_ANY=1|2|4|8;FLAGS_BAW_ALO=16|32;FLAGS_BAW=64
FNV_START=0xcbf29ce484222325;FNV_PRIME=0x100000001b3;FNV_MOD=1<<64
ECHO_STATUS='ECHO'
COLUMNS=('side','S','K','T','bid','ask','r','q')
_HEX=re.compile(r'^[0-9a-f]{16}$');_INT=re.compile(r'^(0|-1|[1-9][0-9]{0,19})$')

def _int(v):return not isinstance(v,bool) and isinstance(v,int)

def mask_for(selector):
    """The models mask of a case selector: 'all' is bsm|bjs|crr (7, contract.ALL_MODELS); a MODELS5 name is its bit."""
    from optionlab.contract import ALL_MODELS
    if selector=='all':return mask_of(ALL_MODELS)
    if isinstance(selector,str) and selector in MODEL_BITS:return MODEL_BITS[selector]
    raise ValueError('unknown selector')

def mask_of(models):
    """The OR of the bits of a non-empty tuple or list of distinct MODELS5 names."""
    if not isinstance(models,(tuple,list)) or not models or len(set(models))!=len(models) or any(m not in MODEL_BITS for m in models):
        raise ValueError('models: a non-empty list of distinct model names required')
    out=0
    for m in models:out|=MODEL_BITS[m]
    return out

def check_mask(mask):
    if not _int(mask) or not 1<=mask<=ALL_MASK:raise ValueError('models mask must be an integer from 1 to 31')
    return mask

def models_of(mask):
    """The model names of a mask 1-31 in MODELS5 order."""
    check_mask(mask)
    return tuple(m for k,m in enumerate(MODELS5) if mask>>k&1)

def side_value(code):
    """The request side value of a chain side code: 0 (call) -> 0.0, 1 (put) -> 1.0, anything else -> 2.0."""
    return 0.0 if code==0 and not isinstance(code,bool) else 1.0 if code==1 and not isinstance(code,bool) else 2.0

def _columns_of(chain):
    if 'r' not in chain or 'q' not in chain:raise ValueError('chain has no per-row r and q columns')
    n=chain.get('n')
    if not _int(n) or n<0:raise ValueError('chain row count rejected')
    cols=[chain[k] for k in COLUMNS]
    if any(len(c)!=n for c in cols):raise ValueError('chain columns differ in length')
    return n,cols

def columns(chain):
    """The eight request columns (side value, S, K, T, bid, ask, r, q) as C-contiguous little-endian float64 NumPy arrays."""
    import numpy as np
    n,cols=_columns_of(chain)
    out=[np.ascontiguousarray(np.array([side_value(c) for c in cols[0]],dtype='<f8'))]
    out+=[np.ascontiguousarray(np.array(c,dtype='<f8')) for c in cols[1:]]
    return out

def pack_requests(chain):
    """The n 64-byte request records of a chain (per-row r and q; ValueError without them)."""
    import numpy as np
    n,_=_columns_of(chain)
    if n==0:return b''
    return np.stack(columns(chain),axis=1).astype('<f8',copy=False).tobytes()

def trailer_count(n,threads):
    return 0 if threads==0 else min(threads,n)

def response_length(n,threads):
    """pl_response_payload(n, threads) = n x 290 + 4 + 16 k."""
    if not _int(n) or n<0 or not _int(threads) or threads<0:raise ValueError('record count or threads rejected')
    return n*RECORD_OUT+TRAILER_HEAD.size+TRAILER_ENTRY.size*trailer_count(n,threads)

def trailer(payload,n,threads):
    """The trailer of a response payload of n records: {chunk_rule, chunks, chunk_sizes, chunk_wall_ns}. ValueError when the
    length, the chunk count, a reserved u32 or the size sum disagrees with the request."""
    if len(payload)!=response_length(n,threads):raise ValueError('LENGTH_MISMATCH')
    base=n*RECORD_OUT;k=TRAILER_HEAD.unpack_from(payload,base)[0]
    if k!=trailer_count(n,threads):raise ValueError('TRAILER_MISMATCH')
    sizes=[];walls=[]
    for i in range(k):
        size,zero,wall=TRAILER_ENTRY.unpack_from(payload,base+TRAILER_HEAD.size+TRAILER_ENTRY.size*i)
        if zero:raise ValueError('RESERVED_NONZERO')
        sizes.append(size);walls.append(wall)
    if k and sum(sizes)!=n:raise ValueError('TRAILER_MISMATCH')
    return {'chunk_rule':'one-per-worker' if k else 'direct','chunks':k,'chunk_sizes':sizes,'chunk_wall_ns':walls}

def _legal_flags(model):
    return FLAGS_ANY|(FLAGS_BAW_ALO if model in ('baw','alo') else 0)|(FLAGS_BAW if model=='baw' else 0)

_DTYPE=None
def _dtype():
    global _DTYPE
    if _DTYPE is None:
        import numpy as np
        _DTYPE=np.dtype([('status','u1',(5,)),('flags','u1',(5,)),('bits','<u8',(35,))])
    return _DTYPE

def materialize(records,n,models,*,echo=False):
    """The `reference.run` shape {'n', 'models': {model: {status, flags, iv, ..., rho}}} of n response records for the mask
    `models`, with the record rule of the module text; status 255 becomes 'ECHO' only with echo=True, and then every selected
    part must be 255 with flags 0 and seven NaN fields."""
    import numpy as np
    mask=check_mask(models)
    if not _int(n) or n<0:raise ValueError('record count rejected')
    if len(records)!=n*RECORD_OUT:raise ValueError('LENGTH_MISMATCH')
    rec=np.frombuffer(records,dtype=_dtype(),count=n)
    status=np.ascontiguousarray(rec['status']);flags=np.ascontiguousarray(rec['flags']);bits=np.ascontiguousarray(rec['bits'])
    values=bits.view('<f8');names=np.array(list(STATUSES)+[ECHO_STATUS],dtype=object);out={}
    for k,m in enumerate(MODELS5):
        st=status[:,k];fl=flags[:,k];b=bits[:,7*k:7*k+7]
        if not mask>>k&1:
            if n and not ((st==NOT_REQUESTED).all() and (fl==0).all() and (b==NAN_BITS).all()):raise ValueError('RESERVED_NONZERO')
            continue
        v=values[:,7*k:7*k+7]
        if echo:
            if n and not ((st==ECHO).all() and (fl==0).all() and np.isnan(v).all()):raise ValueError('RESERVED_NONZERO')
            idx=np.full(n,len(STATUSES),dtype=np.intp)
        else:
            if n and (int(st.max())>=len(STATUSES) or (fl&~np.uint8(_legal_flags(m))).any()):raise ValueError('RESERVED_NONZERO')
            idx=st.astype(np.intp)
        out[m]={'status':names[idx].tolist(),'flags':fl.astype(int).tolist(),**{f:v[:,j].tolist() for j,f in enumerate(FIELDS)}}
    return {'n':n,'models':out}

RESPONSE_BITS=struct.Struct('<5B5B35Q')         # the response record with the binary64 fields as their bit patterns

def _bits(v):return struct.unpack('<Q',struct.pack('<d',float(v)))[0]

def encode_records(result,mask):
    """The n response records of a (non-echo) result for the mask: the inverse of materialize. A selected part writes its
    status code (its index in STATUSES), its flag byte and the binary64 bits of its seven fields; an unselected part writes
    NOT_REQUESTED, flags 0 and NAN_BITS. ValueError when the result's models are not exactly the mask's models, or a column
    length, a status or a flag is outside the record layout (the flag rule of materialize is not applied here). No backend path
    uses it: the agreement controls (optionlab.agreement_controls) build the record-level mutations of a C result with it."""
    want=models_of(mask);models=result.get('models') if isinstance(result,dict) else None
    if not isinstance(models,dict) or set(models)!=set(want):raise ValueError('encode: the result models are not the mask models')
    n=result.get('n')
    if not _int(n) or n<0:raise ValueError('record count rejected')
    keys=('status','flags')+FIELDS
    for m in want:
        col=models[m]
        if not isinstance(col,dict) or any(not isinstance(col.get(k),(list,tuple)) or len(col[k])!=n for k in keys):raise ValueError('encode: a column is missing or of another length')
    out=bytearray()
    for i in range(n):
        st=[];fl=[];words=[]
        for k,m in enumerate(MODELS5):
            if not mask>>k&1:st.append(NOT_REQUESTED);fl.append(0);words+=[NAN_BITS]*len(FIELDS);continue
            col=models[m];s=col['status'][i];f=col['flags'][i]
            if s not in STATUSES:raise ValueError('encode: a status outside STATUSES')
            if not _int(f) or not 0<=f<=255:raise ValueError('encode: a flag outside one byte')
            st.append(STATUSES.index(s));fl.append(f);words+=[_bits(col[x][i]) for x in FIELDS]
        out+=RESPONSE_BITS.pack(*st,*fl,*words)
    return bytes(out)

def parse_reduction(text,models):
    """The PLK1 `red=` value: one part per selected model of the mask, MODELS5 order, each
    `<model>:<c0>,...,<c8>:<16 hex|null>:<index>` (null exactly when the index is -1). {model: {counts, max_iv_bits,
    max_iv_index}}; ValueError for a part of an unselected model, a missing selected part, more than five parts or a
    malformed part (G4.4)."""
    want=models_of(models)
    if not isinstance(text,str) or not text:raise ValueError('red: empty')
    parts=text.split(';')
    if len(parts)>len(MODELS5):raise ValueError('red: more than five parts')
    out={}
    for part in parts:
        fields=part.split(':')
        if len(fields)!=4:raise ValueError('red: malformed part')
        m,counts,bits,index=fields
        if m not in want or m in out or (out and MODELS5.index(m)<MODELS5.index(list(out)[-1])):raise ValueError('red: a part of an unselected model, a repeat or another order')
        c=counts.split(',')
        if len(c)!=len(STATUSES) or not all(re.fullmatch(r'0|[1-9][0-9]{0,19}',x) for x in c):raise ValueError('red: counts')
        if not _INT.fullmatch(index):raise ValueError('red: index')
        i=int(index)
        if not ((bits=='null' and i==-1) or (_HEX.fullmatch(bits) and i>=0)):raise ValueError('red: max iv')
        out[m]={'counts':[int(x) for x in c],'max_iv_bits':None if bits=='null' else bits,'max_iv_index':i}
    if tuple(out)!=want:raise ValueError('red: a selected part is missing')
    return out

def requests(n,limit):
    """The L2 requests [(start, end), ...] of n records (benchlab.pools.request_splits); `limit` is required."""
    from benchlab.pools import request_splits
    return request_splits(n,limit)

def fnv1a64(data):
    """FNV-1a 64 of a bytes-like value (start 0xcbf29ce484222325, prime 0x100000001b3)."""
    h=FNV_START
    for b in bytes(data):h=((h^b)*FNV_PRIME)%FNV_MOD
    return h

def canonical_digest(result):
    """The kernel digest of a result: FNV-1a 64 of its ocg-v1 / ocg-v1m canonical bytes, 16 lowercase hex digits."""
    from optionlab.reference import canonical_result
    return '%016x'%fnv1a64(canonical_result(result))
