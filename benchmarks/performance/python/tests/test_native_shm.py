import fcntl, os, unittest
from benchlab import native_shm as ns
from benchlab import native_worker as nw
IN_BYTES=4096;OUT_BYTES=8192            # region sizes are per codec values (FR6-R3 item 1); the framework takes them as given

class RegionTests(unittest.TestCase):
    def test_regions_are_exact_sealed_and_cleaned(self):
        before=ns.snapshot()
        with ns.Regions(IN_BYTES,OUT_BYTES) as r:
            self.assertEqual(os.fstat(r.input_fd).st_size,IN_BYTES);self.assertEqual(os.fstat(r.output_fd).st_size,OUT_BYTES)
            self.assertEqual(fcntl.fcntl(r.input_fd,fcntl.F_GET_SEALS)&ns.SEALS,ns.SEALS)
            self.assertEqual(fcntl.fcntl(r.output_fd,fcntl.F_GET_SEALS)&ns.SEALS,ns.SEALS)
            with self.assertRaises(OSError):os.ftruncate(r.input_fd,10)                    # size change refused by the seal
            with self.assertRaises(OSError):os.ftruncate(r.output_fd,OUT_BYTES+1)
            self.assertEqual((len(r.input),len(r.output)),(IN_BYTES,OUT_BYTES));self.assertEqual(r.pass_fds(),(r.input_fd,r.output_fd))
            r.input[:4]=b'abcd';self.assertEqual(os.pread(r.input_fd,4,0),b'abcd')        # the map and the descriptor share bytes
            os.pwrite(r.output_fd,b'wxyz',OUT_BYTES-4);self.assertEqual(bytes(r.output[-4:]),b'wxyz')
            self.assertTrue(ns.leftover(before))                                          # the regions exist while open
        self.assertEqual(ns.leftover(before),[])
    def test_cleanup_on_every_path(self):
        before=ns.snapshot()
        try:
            with ns.Regions(IN_BYTES,OUT_BYTES):raise RuntimeError('boom')
        except RuntimeError:pass
        r=ns.Regions(IN_BYTES,OUT_BYTES);r.close();r.close()                                 # idempotent
        self.assertIsNone(r.input);self.assertIsNone(r.output)
        self.assertEqual(ns.leftover(before),[])
    def test_region_sizes_are_bounded_by_the_frame_limit(self):
        before=ns.snapshot()
        with ns.Regions(1,nw.MAX_FRAME) as r:self.assertEqual(os.fstat(r.output_fd).st_size,nw.MAX_FRAME)
        for sizes in ((0,1),(1,0),(nw.MAX_FRAME+1,1),(1,nw.MAX_FRAME+1),(True,1),(1.0,1),(-1,1)):
            with self.subTest(sizes=sizes),self.assertRaises(ValueError):ns.Regions(*sizes)
        self.assertEqual(ns.leftover(before),[])
    def test_descriptor_codec(self):
        self.assertEqual(len(ns.encode_descriptor(0,64,0,294)),32)
        self.assertEqual(ns.encode_descriptor(1,2,3,4),bytes([1]+[0]*7+[2]+[0]*7+[3]+[0]*7+[4]+[0]*7))
        for bad in ((-1,0,0,0),(0,0,0,2**64),(0.0,0,0,0)):
            with self.subTest(bad=bad),self.assertRaises(ValueError):ns.encode_descriptor(*bad)
    def test_descriptor_fits_the_regions(self):
        with ns.Regions(IN_BYTES,OUT_BYTES) as r:
            ns.check_descriptor(r,0,IN_BYTES,0,OUT_BYTES);ns.check_descriptor(r,IN_BYTES,0,OUT_BYTES,0)
            for bad in ((1,IN_BYTES,0,0),(0,0,1,OUT_BYTES),(2**64-1,2,0,0)):
                with self.subTest(bad=bad),self.assertRaises(ValueError):ns.check_descriptor(r,*bad)
    def test_leftover_names_new_memfds_and_shm_entries(self):
        before=ns.snapshot();fd=os.memfd_create('safe-c-leftover-probe',os.MFD_CLOEXEC)
        try:self.assertTrue(any('safe-c-leftover-probe' in x for x in ns.leftover(before)))
        finally:os.close(fd)
        self.assertEqual(ns.leftover(before),[])
        self.assertEqual(sorted(ns.snapshot()),['memfd','shm'])

if __name__=='__main__':unittest.main()
