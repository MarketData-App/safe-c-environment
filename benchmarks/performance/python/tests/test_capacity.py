import threading, time, unittest
from benchlab.capacity import run_closed_loop

class ClosedLoopTests(unittest.TestCase):
    def test_every_request_completes_once(self):
        seen=[];lock=threading.Lock()
        def call(server,client,i):
            with lock:seen.append((client,i))
            return 256
        out=run_closed_loop(call,[object(),object()],4,5)
        self.assertEqual(out['completed'],20);self.assertEqual(sorted(seen),[(c,i) for c in range(4) for i in range(5)]);self.assertEqual(out['units'],20*256)
        self.assertEqual(len(out['latencies_ns']),20);self.assertEqual(out['errors'],[])
    def test_a_server_serves_one_request_at_a_time(self):
        busy=set();overlap=[];lock=threading.Lock()
        def call(server,client,i):
            with lock:
                if id(server) in busy:overlap.append(1)
                busy.add(id(server))
            time.sleep(0.002)
            with lock:busy.discard(id(server))
            return 1
        run_closed_loop(call,[object()],4,3);self.assertEqual(overlap,[])
    def test_latency_includes_the_queue_wait(self):
        out=run_closed_loop(lambda s,c,i:(time.sleep(0.01),1)[1],[object()],2,1)
        self.assertGreaterEqual(max(out['latencies_ns']),15_000_000)
    def test_an_exception_ends_its_client_and_is_counted(self):
        def call(s,c,i):
            if c==1:raise ValueError('x')
            return 1
        out=run_closed_loop(call,[object()],2,3);self.assertEqual(out['completed'],3);self.assertEqual(out['errors'],['ValueError'])
