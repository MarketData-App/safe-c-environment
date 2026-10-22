"""Generic agreement-control mutations (Phase 2 Task 23 B06, framework part; task EX-13). Record-agnostic.

A mutation acts on the JSON form of a result (dicts, lists, strings, numbers): it never names a field. The target list is
the first list of scalar leaves with at least two distinct items, in depth-first order over sorted dict keys. Two
mutations use the adapter's own methods instead: `missing-output` (slice_result to one work unit less) and
`hardcoded-answer` (the C result of another input). `apply` returns the mutated result, or None when the mutation does
not apply to this result (the caller then records the mutation as unchanged, which fails the control).

- skipped-chunk: the last quarter (at least one item) of the target list keeps the zero value of its type.
- wrong-order: the first two adjacent items of the target list with different values change places.
- missing-output: the adapter's slice_result of the result to one work unit less.
- hardcoded-answer: the result computed on another input, presented for this input.
- precision-change: every scalar leaf of every list changes in its last place (an integer flips its lowest bit, a float
  is rounded to single precision or moves to the next float, a text changes its last character).
- range-change: the target list is clamped into the range of its 25th to 75th percentile (a narrower value range)."""
import copy, math, struct

GENERIC=('skipped-chunk','wrong-order','missing-output','hardcoded-answer','precision-change','range-change')
HEX='0123456789abcdef'

def _scalar(v):return isinstance(v,(str,int,float)) and not isinstance(v,bool)

def leaf_lists(value,path=()):
    """(path, list) of every list of scalar leaves, depth first over sorted dict keys and list order."""
    if isinstance(value,dict):
        for k in sorted(value,key=str):yield from leaf_lists(value[k],path+(k,))
    elif isinstance(value,list):
        if value and all(_scalar(v) for v in value):yield path,value
        else:
            for i,v in enumerate(value):yield from leaf_lists(v,path+(i,))

def target(result):
    """(path, list) of the first scalar-leaf list with at least two distinct items, or None."""
    for path,lst in leaf_lists(result):
        if len({repr(v) for v in lst})>=2:return path,lst
    return None

def _with(result,path,new):
    out=copy.deepcopy(result);node=out
    for k in path[:-1]:node=node[k]
    if path:node[path[-1]]=new
    else:out=new
    return out

def zero(v):
    if isinstance(v,str):return '0'*len(v)
    if isinstance(v,float):return 0.0
    return 0

def last_place(v):
    """The value changed in its last place."""
    if isinstance(v,str):
        if not v:return '0'
        c=v[-1]
        if c.lower() in HEX:d=HEX[(HEX.index(c.lower())^1)];return v[:-1]+(d.upper() if c.isupper() else d)
        return v[:-1]+chr(ord(c)^1)
    if isinstance(v,float):
        if not math.isfinite(v):return v
        single=struct.unpack('<f',struct.pack('<f',v))[0] if abs(v)<3.4e38 else v
        return single if single!=v else math.nextafter(v,math.inf)
    return v^1

def _skipped_chunk(result):
    t=target(result)
    if t is None:return None
    path,lst=t;k=max(1,len(lst)//4)
    return _with(result,path,lst[:-k]+[zero(v) for v in lst[-k:]])

def _wrong_order(result):
    t=target(result)
    if t is None:return None
    path,lst=t;new=list(lst)
    for i in range(len(new)-1):
        if repr(new[i])!=repr(new[i+1]):
            new[i],new[i+1]=new[i+1],new[i];return _with(result,path,new)
    return None

def _precision(result):
    out=copy.deepcopy(result);seen=False
    for path,lst in list(leaf_lists(out)):
        out=_with(out,path,[last_place(v) for v in lst]);seen=True
    return out if seen else None

def _range(result):
    t=target(result)
    if t is None:return None
    path,lst=t
    try:ordered=sorted(lst)
    except TypeError:return None
    lo,hi=ordered[len(ordered)//4],ordered[(3*len(ordered))//4]
    return _with(result,path,[min(max(v,lo),hi) for v in lst])

def apply(name,result,*,units=None,slice_result=None,data=None,other=None):
    """The mutated result of the generic mutation `name`, or None when it does not apply. `units` (the adapter's
    work_units of the result), `slice_result` and `data` serve missing-output; `other` (the C result of another input)
    serves hardcoded-answer."""
    if name=='skipped-chunk':return _skipped_chunk(result)
    if name=='wrong-order':return _wrong_order(result)
    if name=='missing-output':
        if slice_result is None or not isinstance(units,int) or units<1:return None
        return slice_result(result,units-1,data)
    if name=='hardcoded-answer':return copy.deepcopy(other) if other is not None else None
    if name=='precision-change':return _precision(result)
    if name=='range-change':return _range(result)
    raise ValueError('unknown generic mutation')
