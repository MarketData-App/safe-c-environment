"""EX-14 (T22; Phase 2 Task 23 example part, case B06; plan G12 B06 and Amendment I item I5.3): the project mutations of the
framework job agreement-controls. The protocol key `agreement_mutations` names them; the job (container/bench_phase2_job.py
AGREEMENT_CODE) calls the adapter hook agreement_mutation(name, result, data) with the real C result of the case adapter and
the job's synthetic rows, then the adapter's digest and validate: each mutated result must have another digest, and validate
must refuse it. Each function returns the mutated result, or None when the mutation does not apply to the result (the job then
records it as unchanged, which fails B06, never passes it).

- wrong-model: a call returns another model's values. In a result of several models the first part (MODELS5 order) holds the
  values of the second part; in a per-model result the part holds the values of another model (bsm, or bjs for a bsm call),
  computed by py-reference on the same rows (C = py-reference byte for byte). agreement.compare refuses it.
- not-requested-garbage: the response records of the result (native_codec.encode_records), with the status byte of the first
  unselected part of record 0 set to OK instead of NOT_REQUESTED (254). The mutated result is the raw C answer (records, n,
  mask, echo) as a backend run returns it; the adapter's validate decodes it with the record rule of native_codec, which
  refuses it (RESERVED_NONZERO). A result of all five models has no unselected part: None.
- misplaced-flag: the same raw answer with a flag bit in a byte where the I5.3 rule forbids it, in the flag byte of the first
  selected part of record 0: bit 16 for bsm, bjs or crr, bit 64 for alo, bit 128 for baw (bits 16 and 32 in the baw and alo
  bytes and bit 64 in the baw byte are valid and never a mutation)."""
import copy
from optionlab import native_codec as nc
from optionlab.contract import FIELDS, MODELS5, STATUSES, rows

NAMES=('wrong-model','not-requested-garbage','misplaced-flag')
FORBIDDEN_FLAG={'bsm':16,'bjs':16,'crr':16,'baw':128,'alo':64}
COLUMNS=('status','flags')+FIELDS

def wrong_model(result,data,params):
    """The result with its first part holding another model's values (see the module text)."""
    models=[m for m in MODELS5 if m in result['models']]
    if not models:return None
    first=models[0]
    if len(models)>1:other=result['models'][models[1]]
    else:
        from optionlab import reference as ref_mod
        name='bsm' if first!='bsm' else 'bjs'
        other=ref_mod.run(rows(data),params,models=(name,))['models'][name]
    out=copy.deepcopy(result);out['models'][first]=dict(out['models'][first],**{k:copy.deepcopy(other[k]) for k in COLUMNS})
    return out

def _answer(records,result,mask):return {'records':bytes(records),'n':result['n'],'mask':mask,'echo':False}

def not_requested_garbage(result,mask):
    """The raw C answer of the result with the status OK in the first unselected part of record 0."""
    unselected=[k for k in range(len(MODELS5)) if not mask>>k&1]
    if not unselected or result['n']<1:return None
    records=bytearray(nc.encode_records(result,mask));records[unselected[0]]=STATUSES.index('OK')
    return _answer(records,result,mask)

def misplaced_flag(result,mask):
    """The raw C answer of the result with a forbidden flag bit in the first selected part of record 0."""
    selected=[k for k in range(len(MODELS5)) if mask>>k&1]
    if not selected or result['n']<1:return None
    k=selected[0];records=bytearray(nc.encode_records(result,mask));records[len(MODELS5)+k]|=FORBIDDEN_FLAG[MODELS5[k]]
    return _answer(records,result,mask)

def mutate(adapter,name,result,data):
    """The mutation `name` of a result of `adapter` (its models mask and parameters); ValueError for an unknown name."""
    if name=='wrong-model':return wrong_model(result,data,adapter.params)
    if name=='not-requested-garbage':return not_requested_garbage(result,adapter.native_mask())
    if name=='misplaced-flag':return misplaced_flag(result,adapter.native_mask())
    raise ValueError('unknown agreement mutation')
