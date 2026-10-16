"""record-scan (spec 9, Amendment A; FR5 ruling FR5-R1 item 3): filter packed records by a whole-day window and a ratio band;
sum the record weights exactly. A framework control workload with its own seeded record generator; it needs no project
code and no domain library.

The day window compares whole days: days = floor(span*365.0 + 0.5) in IEEE double (round half up), computed only for a
finite span, so a C variant reproduces the filter exactly with floor(span*365.0+0.5) (no FMA contraction). The ratio band
compares level/base in IEEE double."""
import hashlib, json, math, random, struct
RECORD=struct.Struct('<Bdddddq')   # kind, base, level, span (in units of 365 days), low, high, weight (-1 when missing)
MAX_BYTES=33554432

def pack(records):
    out=bytearray()
    for i in range(records['n']):
        w=records['weight'][i]
        if math.isfinite(w) and w>=0:
            if w!=math.floor(w):raise ValueError(f'record {i}: weight {w!r} is not a whole number')
            w=int(w)
        else:w=-1
        out+=RECORD.pack(records['kind'][i]&0xff,records['base'][i],records['level'][i],records['span'][i],records['low'][i],records['high'][i],w)
    return bytes(out)

def whole_days(span):
    """Whole days of a span: floor(span*365.0 + 0.5); None (out of every window) when span or span*365.0+0.5 is not finite."""
    if not math.isfinite(span):return None
    days=span*365.0+0.5
    return math.floor(days) if math.isfinite(days) else None

def _keep(base,level,span,w,day_min,day_max,lo,hi):
    if w<0 or not base>0.0:return False
    days=whole_days(span)
    return days is not None and day_min<=days<=day_max and lo<=level/base<=hi

def scan_reference(packed,day_min,day_max,lo,hi):
    count=0;total=0;records=0
    for off in range(0,len(packed),RECORD.size):
        kind,base,level,span,low,high,w=RECORD.unpack_from(packed,off);records+=1
        if _keep(base,level,span,w,day_min,day_max,lo,hi):count+=1;total+=w
    return {'count':count,'weight':total,'records':records}

def scan_optimized(packed,day_min,day_max,lo,hi):
    kept=[w for kind,base,level,span,low,high,w in RECORD.iter_unpack(packed) if _keep(base,level,span,w,day_min,day_max,lo,hi)]
    return {'count':len(kept),'weight':sum(kept),'records':len(packed)//RECORD.size}

class RecordScan:
    def __init__(self,params):
        self.params=dict(params);self.bench_ref=('benchlab.recordscan:RecordScan',self.params)
        self.window=(params['day_min'],params['day_max'],params['ratio_lo'],params['ratio_hi'])
    def synthesize(self,rows,seed):
        if isinstance(rows,bool) or not isinstance(rows,int) or rows<0:raise ValueError('rows must be a non-negative integer')
        rng=random.Random(seed);out=bytearray()
        for i in range(rows):
            level=round(rng.uniform(50.0,150.0),2);span=rng.randint(0,400)/365.0;low=round(rng.uniform(0.0,20.0),2);high=round(low+rng.uniform(0.0,1.0),2)
            out+=RECORD.pack(i%2,100.0,level,span,low,high,-1 if rng.random()<0.05 else rng.randint(0,50000))
        return bytes(out)
    def load(self,dataset_ref):
        with open(dataset_ref['path'],'rb') as f:data=f.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES or len(data)%RECORD.size:raise ValueError('not a packed record-scan dataset within 32 MiB')
        if hashlib.sha256(data).hexdigest()!=dataset_ref['sha256']:raise ValueError('dataset digest mismatch')
        return data
    def slice(self,data,n):
        if n<0 or n*RECORD.size>len(data):raise ValueError('slice outside the dataset')
        return data[:n*RECORD.size]
    def prepare(self,data,variant,workers=1):
        if variant not in ('py-reference','py-optimized'):raise ValueError('spec 9: pool variants are not applicable to record-scan')
        return data
    def run(self,prepared,variant,workers,pool=None):
        return (scan_reference if variant=='py-reference' else scan_optimized)(prepared,*self.window)
    def materialize(self,raw):return dict(raw)
    def work_units(self,result):return result['records']
    def reference(self,data):return scan_reference(data,*self.window)
    def slice_result(self,result,n,data):return self.reference(data)          # `data` is the n-record prefix
    def validate(self,result,reference,data):
        ok=result==reference
        return {'eligible':ok,'failures':{} if ok else {'scan':1},'reduction':'MATCH' if ok else 'ROW_COUNT' if result.get('records')!=reference['records'] else 'MISMATCH'}
    def digest(self,result):return hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
