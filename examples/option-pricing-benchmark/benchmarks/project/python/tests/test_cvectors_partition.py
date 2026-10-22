"""Amendment E partition vectors (Phase 2 Task 12; container suite). Pins the generated values to the Amendment E
known-answer vectors and to fingerprints computed independently when the plan was written."""
import json
import unittest
from optionlab import cvectors
from benchlab import pools

EXPECTED={(1,1):0x89cd31291d2aefa4,(2,2):0xb82224f202a3d9b4,(3,4):0x13d547dcb273db77,(256,4):0x297ac42e2e97a475,(1024,2):0x8143364aca12bef9,
          (13230,4):0x9868591ba204ec34,(14336,1):0x464c1153c0bd8d4d,(14336,4):0x2f992a4f4aeb6e45,(14337,1):0x3df4fdaa5dfb3974,
          (14337,4):0xa7ce786013f4a97c,(16384,4):0x9a1b3e7c30345de5,(16385,4):0x34a1ede0a902c328,(20000,1):0xa6f01a1f77ed5c4b,
          (20000,2):0x64738148773b99e9,(20000,4):0xa4b6c4c8ede63201}   # Amendment I: limit 14,336 (Task 12b)

class PartitionVectorTests(unittest.TestCase):
    def test_known_answers(self):
        g=pools.SplitMix64(pools.PARTITION_SEED);self.assertEqual([g.next() for _ in range(3)],[0xae58eab7f35199e4,0xa16951b663213f43,0xcc4ea8b7bd8207bd])
        self.assertEqual(pools.permutation(10,0),[0,3,1,4,8,2,7,9,5,6]);self.assertEqual(pools.permutation(10,1),[9,6,2,7,8,5,1,3,4,0])
        self.assertEqual(pools.chunk_bounds(10,4,0),[[0,3],[1,4,8],[2,7],[5,6,9]])
    def test_fingerprints_equal_benchlab_pools(self):
        for (n,w),value in EXPECTED.items():
            with self.subTest(n=n,w=w):self.assertEqual(cvectors.partition_fingerprint(n,w),value)
    def test_chunk_sizes_follow_the_rule(self):
        self.assertEqual(pools.chunk_sizes(20000,4,14336),[3584,3584,3584,3584,1416,1416,1416,1416])
        self.assertEqual(pools.chunk_sizes(20000,2,14336),[7168,7168,2832,2832])
        self.assertEqual(pools.chunk_sizes(14337,2,14336),[7168,7168,1])
        self.assertEqual(pools.chunk_sizes(13230,4,14336),[3307,3308,3307,3308])
    def test_limit_is_the_policy_limit(self):
        """I13.1 guard test (d): the generator limit is the policy limit, and the generated fingerprint equals the one of
        benchlab.pools.request_chunks at that limit."""
        limit=json.load(open('/src/safety/performance-policy.json'))['pools']['request_limit']
        self.assertEqual(limit,14336)
        seq=[]
        for req in pools.request_chunks(20000,4,limit):
            for c in req:seq+=[len(c)]+list(c)
        self.assertEqual(cvectors.partition_fingerprint(20000,4),cvectors.fnv(seq))
    def test_request_chunks_needs_the_limit(self):
        with self.assertRaises(TypeError):pools.request_chunks(20000,4)
    def test_every_tier_and_worker_count_has_a_fingerprint_row(self):
        """The C binding check (Amendment E item 3): every size tier and the request-limit sizes, workers 1, 2 and 4."""
        text,_=cvectors.PARTS['partition']()
        for n in (1,256,1024,13230,14336,14337,16384,20000):
            for w in (1,2,4):
                with self.subTest(n=n,w=w):self.assertIn('{%d, %d, UINT64_C(0x%016x)},'%(n,w,cvectors.partition_fingerprint(n,w)),text)
    def test_explicit_lists_cover_every_index_once(self):
        """The index lists of n = 1, 10, 256, 1024 fit index[1024] and each (n, workers) covers 0 .. n-1 once."""
        for n in cvectors.PARTITION_LIST_NS:
            self.assertLessEqual(n,1024)
            for w in (1,2,4):
                with self.subTest(n=n,w=w):self.assertEqual(sorted(i for c in pools.chunk_bounds(n,w,0) for i in c),list(range(n)))
    def test_mul_rows_are_exact(self):
        pairs=cvectors.mul_pairs();self.assertEqual(len(pairs),len(cvectors.MUL_EDGES)**2+cvectors.MUL_RANDOM)
        self.assertIn(((1<<64)-1,(1<<64)-1),pairs)
        a=(1<<64)-1;self.assertEqual(((a*a)>>64,(a*a)&((1<<64)-1)),((1<<64)-2,1))

if __name__=='__main__':unittest.main()
