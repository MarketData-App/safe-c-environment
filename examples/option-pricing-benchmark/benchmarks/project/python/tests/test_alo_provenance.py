"""FR4 moved test (ruling R15; FR4-REPORT section 4): tests/unit/test_alo_provenance.py of the framework before FR4 (d1101c6^).
G-ALO1 provenance (spec Amendment I item I3, R1 and R1a; controller ruling R-A4): the retained Boost tanh-sinh files match their
recorded digests, quantlib-source.json lists the ALO files read, and both provenance files are protected. FR4 moved the records,
the Boost files and the QuantLib source out of the framework; they now live in this project's third-party directory
(benchmarks/project/third_party/: provenance/, sources/), every retained_path is relative to benchmarks/project, and the
protection is project_protected of safety/protected-paths.json (benchmarks/project/third_party/), with each record bound by
sha256 in the lock and the lock bound by sha256 in bench.json. The assertions of the three old tests are kept; the lock and
bench.json bindings are added. Reads files only."""
import hashlib, json, unittest
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[2]                 # benchmarks/project
SRC=Path('/src')                                             # the bench container mounts the repository read-only at /src
PROVENANCE=PROJECT/'third_party/provenance'
LOCK_FILE=PROJECT/'third_party/lock.json'

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class AloProvenanceTests(unittest.TestCase):
    def test_boost_files_match_their_digests(self):
        d=json.loads((PROVENANCE/'boost-source.json').read_text())
        self.assertEqual(d['schema_version'],1)
        self.assertRegex(d['archive_sha256'],'^[0-9a-f]{64}$')
        self.assertIn('never built',d['role'])
        self.assertIn('agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; no separate legal-team statement for the Boost 1.90.0 material (BSL-1.0) (the legal-team confirmation of 2026-10-19 names QuantLib only); review_status PENDING',d['license_review'])   # ruling R62
        self.assertTrue(any(f['retained_path'].endswith('LICENSE_1_0.txt') for f in d['files']))
        for f in d['files']:
            self.assertEqual(sha256(PROJECT/f['retained_path']),f['sha256'],f['retained_path'])
        # the lock binds the same eight files (path, sha256, bytes) in its retained row Boost, with the same archive origin
        boost=next(r for r in json.loads(LOCK_FILE.read_text())['retained'] if r['name']=='Boost')
        self.assertEqual(sorted((f['path'],f['sha256'],f['bytes']) for f in boost['files']),
                         sorted((f['retained_path'],f['sha256'],f['bytes']) for f in d['files']))
        self.assertEqual(len(d['files']),8)
        self.assertEqual(boost['origin'],{'kind':'upstream-archive','url':d['archive_url']})

    def test_quantlib_files_used_holds_the_alo_files(self):
        used={u['path'] for u in json.loads((PROVENANCE/'quantlib-source.json').read_text())['files_used']}
        for p in ('ql/pricingengines/vanilla/qdfpamericanengine.cpp','ql/pricingengines/vanilla/qdplusamericanengine.cpp',
                  'ql/math/integrals/tanhsinhintegral.hpp','ql/math/interpolations/chebyshevinterpolation.cpp'):
            self.assertTrue(any(u.endswith(p) for u in used),p)

    def test_both_provenance_files_are_protected(self):                    # controller ruling R-A4
        protected=json.loads((SRC/'safety/protected-paths.json').read_text())['project_protected']
        self.assertIn('benchmarks/project/third_party/',protected)
        lock=json.loads(LOCK_FILE.read_text())
        bound={r['provenance']['path']:r['provenance']['sha256'] for k in ('wheels','sources','retained') for r in lock[k]}
        for rel in ('third_party/provenance/boost-source.json','third_party/provenance/quantlib-source.json'):
            self.assertTrue(any(('benchmarks/project/'+rel).startswith(p) for p in protected),rel)
            self.assertEqual(bound[rel],sha256(PROJECT/rel),rel)
        bench=json.loads((PROJECT/'bench.json').read_text())
        self.assertEqual(bench['third_party'],{'file':'third_party/lock.json','sha256':sha256(LOCK_FILE)})

if __name__=='__main__':
    unittest.main()
