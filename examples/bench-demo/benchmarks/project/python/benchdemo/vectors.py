"""The generator of the C test vectors (FR6 N1). The Python reference (benchdemo.reference) computes every expected value;
the C unit test tests/project/test_bd_digest.c holds the generated block between BEGIN and END, byte for byte. A unit
test (tests/test_demo.py) compares that block with c_block(), so a vector never changes to match the C code.

The generation check `demo-vectors` (bench.json, before_run false) writes c_block() to its output directory as
bd_vectors.inc inside the bench container; the block is then copied into the C test."""
from benchdemo import reference as r
BEGIN='/* BEGIN GENERATED VECTORS: benchdemo.vectors; regenerate, never edit by hand */\n'
END='/* END GENERATED VECTORS */\n'
U64_MAX=r.MASK
# (seed, steps): seed 0 and the zero-seed constant, k 0, 1, 2, small, exact maximum, the u64 maximum and high-bit seeds.
RECORDS=((0,0),(0,1),(0,2),(0,r.STEPS_MAX),(r.ZERO_SEED,0),(r.ZERO_SEED,1),(1,0),(1,1),(1,2),(1,3),
         (2,64),(20261007,64),(0x0123456789ABCDEF,4096),(0x8000000000000000,13),(0x7FFFFFFFFFFFFFFF,7),
         (U64_MAX,0),(U64_MAX,1),(U64_MAX,r.STEPS_MAX-1),(0xDEADBEEFCAFEF00D,r.STEPS_MAX))
MAX_STEP_CYCLE=31

def max_request():
    """The request of exactly RECORDS_MAX records: record i has seed i * ZERO_SEED (mod 2**64) and steps i % 31."""
    return r.encode_request(((i*r.ZERO_SEED)&U64_MAX,i%MAX_STEP_CYCLE) for i in range(r.RECORDS_MAX))

def c_block():
    """The generated C text, BEGIN and END lines included."""
    rows=[]
    for seed,steps in RECORDS:
        checksum,state=r.digest_record(seed,steps)
        rows.append(f'    {{0x{seed:016x}U, {steps}U, 0x{checksum:016x}U, 0x{state:016x}U}},\n')
    big=r.fnv1a(r.digest_request(max_request()))
    return (BEGIN+'struct bd_vector {\n    uint64_t seed;\n    uint32_t steps;\n    uint64_t checksum;\n    uint64_t state;\n};\n\n'
            '/* seed, steps, FNV-1a checksum, final state */\nstatic const struct bd_vector bd_vectors[] = {\n'+''.join(rows)+'};\n\n'
            f'/* The request of BD_RECORDS_MAX records: record i has seed i * 0x9e3779b97f4a7c15 (mod 2^64)\n'
            f' * and steps i % {MAX_STEP_CYCLE}. The value is FNV-1a 64 over its whole output. */\n'
            f'enum {{ BD_MAX_STEP_CYCLE = {MAX_STEP_CYCLE} }};\n'
            f'static const uint64_t bd_max_request_output_fnv = 0x{big:016x}U;\n'+END)

def extract_block(text):
    """The BEGIN..END block of a C source text (markers included); ValueError when it is missing or not unique."""
    if text.count(BEGIN)!=1 or text.count(END)!=1:raise ValueError('the generated vector block is missing or not unique')
    start=text.index(BEGIN);end=text.index(END)
    if end<start+len(BEGIN):raise ValueError('the generated vector block markers are out of order')
    return text[start:end+len(END)]
