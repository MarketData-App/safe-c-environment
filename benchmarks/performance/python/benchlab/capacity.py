"""Closed-loop capacity core (spec 14 Phase 3, Amendment H6). Framework code; no workload knowledge."""
import queue, threading, time

def run_closed_loop(call,servers,clients,requests,clock=time.perf_counter_ns):
    free=queue.Queue()
    for s in servers:free.put(s)
    lat=[];units=[];errors=[];lock=threading.Lock()
    def client(c):
        for i in range(requests):
            t0=clock();server=free.get()
            try:got=call(server,c,i)
            except Exception as exc:
                free.put(server)
                with lock:errors.append(type(exc).__name__)
                return
            t1=clock();free.put(server)
            with lock:lat.append(t1-t0);units.append(got)
    threads=[threading.Thread(target=client,args=(c,),name=f'capacity-client-{c}') for c in range(clients)]
    start=clock()
    for t in threads:t.start()
    for t in threads:t.join()
    return {'wall_ns':clock()-start,'latencies_ns':sorted(lat),'completed':len(lat),'units':sum(units),'errors':errors}
