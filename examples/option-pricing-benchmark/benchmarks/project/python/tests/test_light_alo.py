"""G-ALO2 part A light tests (Amendment I2.2, Appendix I-ALO R5): the protected `alo_scheme` parameter and the frozen
25-point Gauss-Legendre table (25 + 25 binary64 bit patterns in x() order) with its digest, in the module, in the
protected fixture `alo_gauss_legendre` and equal to the wheel's GaussLegendreIntegration(25)."""
import hashlib, json, struct, unittest
from pathlib import Path
from optionlab import alo
from optionlab.params import CASE, CASE_FILE

SCHEME={"name":"accurateScheme","class":"QdFpLegendreTanhSinhScheme","l":25,"m":5,"n":13,"eps":1e-8,"fp_equation":"Auto"}
X=('3fefdb9a4a51c2f5 3fef40d4b23b417a 3fee2cd9020c6b11 3feca3c642223462 3feaab8fe033d77e 3fe84bda14fdc6bf 3fe58ddb0e88edd4 '
   '3fe27c36f82fec33 3fde45ad3f9e97d5 3fd71d72726b05d7 3fcf3707b1145cb5 3fbf740f7c9899b8 bc8fb94f498a5702 bfbf740f7c9899a9 '
   'bfcf3707b1145cc4 bfd71d72726b05e5 bfde45ad3f9e97d8 bfe27c36f82fec2e bfe58ddb0e88eddd bfe84bda14fdc6c2 bfeaab8fe033d776 '
   'bfeca3c642223466 bfee2cd9020c6afd bfef40d4b23b417c bfefdb9a4a51c2fc').split()
W=('3f8755a1bf835128 3f9afccd36646ec7 3fa4f5fa2650dc7b 3fac1c77e339dfc9 3fb16af5d29930e6 3fb48419d7047207 3fb74da0d03a821d '
   '3fb9bcb95550b81f 3fbbc7f12e17560c 3fbd6759d2b4d178 3fbe94a725b474d8 3fbf4b47ded39780 3fbf88774268159e 3fbf4b47ded3970e '
   '3fbe94a725b474da 3fbd6759d2b4d196 3fbbc7f12e17568d 3fb9bcb95550b818 3fb74da0d03a8207 3fb48419d7047218 3fb16af5d2993136 '
   '3fac1c77e339e021 3fa4f5fa2650dbd4 3f9afccd36646f05 3f8755a1bf83525b').split()
DIGEST=hashlib.sha256(json.dumps({'w':W,'x':X},sort_keys=True,separators=(',',':')).encode()).hexdigest()
from optionlab.protocol import ORACLE_FILE as FIXTURES   # EX-3: the ALO table is protocol data (protocol/oracle.json)

def bits(v):return struct.pack('>d',v).hex()

class LightAloTests(unittest.TestCase):
    def test_scheme_parameter(self):
        self.assertEqual(CASE.alo_scheme,SCHEME)
        c=json.loads(CASE_FILE.read_text())
        self.assertEqual(c['parameters']['alo_scheme'],{"value":SCHEME,"label":"protocol","note":"Amendment I2.2; a change is a new definition"})
        self.assertEqual(c['version'],5)          # Task A4: version 2 (alo_scheme); Task A6 (H21 five-model panel, ruling R-A3): version 3; EX-3: version 4 (single-threaded variants only, owner C15); EX-10: version 5 (C rows, unit points)
    def test_frozen_table_and_digest(self):
        self.assertEqual((list(alo.GL_X_BITS),list(alo.GL_W_BITS)),(X,W))
        self.assertEqual(([bits(v) for v in alo.GL_X],[bits(v) for v in alo.GL_W]),(X,W))
        self.assertEqual(alo.GL_DIGEST,DIGEST)
    def test_fixture_holds_the_table(self):
        self.assertTrue(FIXTURES.is_file())
        g=json.loads(FIXTURES.read_text())['alo_gauss_legendre']
        self.assertEqual((g['n'],g['x'],g['w'],g['sha256']),(25,X,W,DIGEST))
    def test_table_equals_the_wheel(self):
        try:import QuantLib as ql
        except ImportError:self.skipTest('QuantLib-Python not available')
        gl=ql.GaussLegendreIntegration(25)
        self.assertEqual(([bits(float(v)) for v in gl.x()],[bits(float(v)) for v in gl.weights()]),(X,W))

if __name__=='__main__':unittest.main()
