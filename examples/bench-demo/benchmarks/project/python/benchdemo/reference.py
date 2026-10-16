"""The bench-demo workload, native Python version (FR6, specs/project/bd_digest.md). Pure Python integers, standard
library only. It is the reference: the C module (src/bd_digest.c) must give byte-identical output for every request.

A request holds n records of 12 bytes: a u64 seed and a u32 step count k, both little-endian; 1 <= n <= 14,336 and
0 <= k <= 1,000,000. Seed 0 maps to ZERO_SEED before stepping (xorshift64 has a zero fixed point). Per record:
x = seed; repeat k times: x ^= x << 13; x ^= x >> 7; x ^= x << 17 (mod 2**64); after each step fold the 8 bytes of x,
little-endian, into FNV-1a 64 that starts from the offset basis for each record. The output record is the FNV-1a value
and the final x, both u64 little-endian: 16 bytes.

A refused request raises ValueError whose text is the C status name (BD_EMPTY_REQUEST and so on), checked in the same
order as bd_check_request.

Overlap (N1-A01): the request bytes and the output bytes must not overlap. digest_request copies the request into a new
bytes object and returns a new bytes object, so in Python they never share memory. The C route entry bd_digest_request
refuses an overlapping pair with BD_OVERLAP (specs/project/bd_digest.md).

Steps (N1-A02): digest_record refuses steps above STEPS_MAX; the C bd_digest_record computes any u32 value, and only the
C route entry bd_digest_request enforces the limit."""
import struct
RECORD_IN=12;RECORD_OUT=16;RECORDS_MAX=14336;STEPS_MAX=1000000
ZERO_SEED=0x9E3779B97F4A7C15;FNV_OFFSET=0xcbf29ce484222325;FNV_PRIME=0x100000001b3;MASK=0xFFFFFFFFFFFFFFFF
_IN=struct.Struct('<QI');_OUT=struct.Struct('<QQ')

def digest_record(seed,steps):
    """(checksum, state) of one record. seed is a u64 and steps a u32 step count within STEPS_MAX."""
    if type(seed) is not int or not 0<=seed<=MASK:raise ValueError('seed must be a u64')
    if type(steps) is not int or not 0<=steps<=STEPS_MAX:raise ValueError('BD_STEPS_TOO_LARGE')
    x=seed if seed else ZERO_SEED;h=FNV_OFFSET;p=FNV_PRIME;m=MASK
    for _ in range(steps):
        x^=(x<<13)&m;x^=x>>7;x^=(x<<17)&m
        h=((h^(x&255))*p)&m;h=((h^((x>>8)&255))*p)&m;h=((h^((x>>16)&255))*p)&m;h=((h^((x>>24)&255))*p)&m
        h=((h^((x>>32)&255))*p)&m;h=((h^((x>>40)&255))*p)&m;h=((h^((x>>48)&255))*p)&m;h=((h^(x>>56))*p)&m
    return h,x

def encode_request(records):
    """The request bytes of a sequence of (seed, steps) pairs. The values are packed as given; check_request decides."""
    return b''.join(_IN.pack(seed,steps) for seed,steps in records)

def check_request(request):
    """The record count of a valid request; ValueError with the C status name otherwise (bd_check_request order)."""
    if not isinstance(request,(bytes,bytearray,memoryview)):raise ValueError('BD_NULL_ARGUMENT')
    request=bytes(request)
    if len(request)==0:raise ValueError('BD_EMPTY_REQUEST')
    if len(request)>RECORDS_MAX*RECORD_IN:raise ValueError('BD_TOO_MANY_RECORDS')
    if len(request)%RECORD_IN:raise ValueError('BD_PARTIAL_RECORD')
    if any(steps>STEPS_MAX for _,steps in _IN.iter_unpack(request)):raise ValueError('BD_STEPS_TOO_LARGE')
    return len(request)//RECORD_IN

def digest_request(request):
    """The output bytes (16 per record) of a valid request; ValueError with the C status name otherwise."""
    check_request(request)
    return b''.join(_OUT.pack(*digest_record(seed,steps)) for seed,steps in _IN.iter_unpack(bytes(request)))

def fnv1a(data):
    """FNV-1a 64 over bytes: the checksum of a whole output in the generated C vectors."""
    h=FNV_OFFSET
    for b in bytes(data):h=((h^b)*FNV_PRIME)&MASK
    return h
