"""The shared Andersen-Lake-Offengenden equation choice and segment of a point (spec Amendment I items I2.4 and I2.6; the
approved source-verification record Appendix I-ALO, item R4). QL_VERSION 1.43.

QuantLib attribution (Amendment B item 9): transcribed operation by operation from the retained QuantLib 1.43 release
benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz (sha256 b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701,
tag v1.43), paths below ql/:
- termstructures/yield/flatforward.hpp:102-104 and interestrate.cpp:53-54 (the discount 1.0/exp(r' * 1.0) of a flat
  continuous curve at the process time 1.0 of the mapped problem) and pricingengines/vanilla/qdplusamericanengine.cpp:182-183
  (the read-back rates r = -log(D_r)/T, q = -log(D_q)/T with T = 1.0) -> `read_back`;
- pricingengines/vanilla/qdfpamericanengine.cpp:455-463 (Auto: FP-A iff std::abs(r - q) < 0.001) -> `alo_equation`;
- pricingengines/vanilla/qdplusamericanengine.cpp:190-193 (a call is the put with exchanged spot, strike and rates), :207
  (the European edge test r <= 0 and r <= q), :231-251 (the xMax case table and, in case 1, the test r/q < 1.0 of
  std::min(1.0, r/q)) and qdfpamericanengine.cpp:432 (the double-boundary test r < 0 and q < r) -> `alo_segment`.

One scalar implementation on `math`: py-reference calls these functions immediately before every ALO engine evaluation
and uses the result; py-optimized and py-library call the same functions (Amendment I2.4: py-library passes Auto to
QuantLib and uses `alo_segment` only for the segment rule); the C port is an operation-by-operation copy (Amendment F
item 8). IEEE-754 semantics: an exp overflow, a log of zero or of a negative number give the C++ result (models._exp,
_log), never a Python exception.
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math
from optionlab.models import _exp, _log

FP_A='FP_A';FP_B='FP_B'
SWITCH=0.001                    # qdfpamericanengine.cpp:457: std::abs(r-q) < 0.001

def side_index(side):
    """0 for a call, 1 for a put; accepts 0, 1, 'call' or 'put' (anything else raises ValueError)."""
    if side in (0,'call') and not isinstance(side,bool):return 0
    if side in (1,'put') and not isinstance(side,bool):return 1
    raise ValueError("side: 0, 1, 'call' or 'put' required")

def read_back(r1,q1):
    """(r_e, q_e) of the mapped problem in the engine's operation order: D = 1.0/exp(x*1.0) (FlatForward::discountImpl
    through InterestRate::discountFactor), then -log(D)/1.0 (the engine's read-back at T = 1.0)."""
    D_r=1.0/_exp(r1*1.0)
    D_q=1.0/_exp(q1*1.0)
    r_e=-_log(D_r)/1.0
    q_e=-_log(D_q)/1.0
    return r_e,q_e

def alo_equation(r1,q1):
    """'FP_A' iff fabs(r_e - q_e) < 0.001 on the read-back rates of the mapped problem (r1 = r*T, q1 = q*T), else 'FP_B'.
    For a call the engine passes (q_e, r_e); |q_e - r_e| = |r_e - q_e| exactly in binary64, so the side does not matter."""
    r_e,q_e=read_back(r1,q1)
    return FP_A if math.fabs(r_e-q_e)<SWITCH else FP_B

def _xmax_case(r,q):
    """The case number (1-7) of QdPlusAmericanEngine::xMax (qdplusamericanengine.cpp:235-249) for the calculatePut rates;
    0 for its QL_FAIL("internal error") (only a NaN rate reaches it)."""
    if r>0.0 and q>0.0:return 1
    elif r>0.0 and q<=0.0:return 2
    elif r==0.0 and q<0.0:return 3
    elif r==0.0 and q>=0.0:return 4
    elif r<0.0 and q>=0.0:return 5
    elif r<0.0 and q<r:return 6
    elif r<0.0 and r<=q and q<0.0:return 7
    return 0

def alo_segment(side,r1,q1):
    """The tuple of every discrete branch choice that the engine makes from the rates alone (Amendment I2.6, record R4),
    with the engine's own binary64 tests on the calculatePut rates (put: (r_e, q_e); call: (q_e, r_e)):
    (equation, European edge r <= 0 and r <= q, double boundary r < 0 and q < r, xMax case, case 1: r/q < 1.0 else None).
    Two points with equal tuples are in the same segment; S and sigma never change it."""
    s=side_index(side)
    r_e,q_e=read_back(r1,q1)
    rr,qq=(r_e,q_e) if s==1 else (q_e,r_e)
    case=_xmax_case(rr,qq)
    return (FP_A if math.fabs(r_e-q_e)<SWITCH else FP_B,rr<=0.0 and rr<=qq,rr<0.0 and qq<rr,case,(rr/qq<1.0) if case==1 else None)
