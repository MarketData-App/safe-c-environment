"""One capacity trial in the caller child (Amendment H6): servers, closed loop, validation of every result."""
import argparse, json, sys
from benchlab.capacity import run_closed_loop
from benchlab.markers import Marker
from benchlab.trial import POOLED, warm_start, runtime_identity
from benchlab.workload import load_case_adapter
from benchlab import pools

def make_server(adapter,variant,workers,route):
    if route is not None and hasattr(adapter,'route'):adapter.route=route
    if variant.startswith('c-') and hasattr(adapter,'start_pool'):return adapter.start_pool(variant,workers)
    if variant in POOLED:return warm_start(variant,workers,adapter.bench_ref)
    return None

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--spec',required=True);a=p.parse_args(argv)
    with open(a.spec) as f:spec=json.load(f)
    with open(spec['case_manifest']) as f:case=json.load(f)
    adapter=load_case_adapter(case);data=adapter.load({'path':spec['dataset'],'sha256':spec['sha256']})
    with open(spec['reference']) as f:reference=json.load(f)
    t=spec['trial'];sub=adapter.slice(data,spec['size']);ref=adapter.slice_result(reference,spec['size'],sub)
    workers=1 if t['workers']=='direct' else int(t['workers'])
    m=Marker();m.hello(t['trial_id']);m.note('identity:'+t['trial_id'],**runtime_identity())
    if t['variant']=='py-processes':pools.ensure_tracker()     # session setup before the servers, as benchlab.trial (outside the closed loop)
    servers=[make_server(adapter,t['variant'],t['workers'],t.get('route')) for _ in range(t['servers'])];bad=[]
    def call(server,client,i):
        raw=adapter.run(adapter.prepare(sub,t['variant'],workers),t['variant'],workers,pool=server);result=adapter.materialize(raw)
        v=adapter.validate(result,ref,sub)
        if not v.get('eligible'):bad.append(1);raise ValueError('result failed validation')
        return adapter.work_units(result)
    m.begin('capacity',t['trial_id']);out=run_closed_loop(call,servers,t['clients'],t['requests_per_client']);m.end('capacity',t['trial_id'])
    for s in servers:
        if s is not None and hasattr(s,'shutdown'):s.shutdown(wait=True)
    cap={'configuration':t['configuration'],'clients':t['clients'],'servers':t['servers'],'requests_per_client':t['requests_per_client'],
         'completed':out['completed'],'errors':len(out['errors']),'latencies_ns':out['latencies_ns'][:spec['latency_samples_max']],'route':t.get('route')}
    ok=not out['errors'] and not bad and out['completed']==t['clients']*t['requests_per_client']
    m.note(t['trial_id'],work_units=out['units'],eligible=ok,failures={} if ok else {'capacity':len(out['errors'])+len(bad)},result_sha256=None,capacity=cap)
    m.close();return 0 if ok else 1

if __name__=='__main__':sys.exit(main())
