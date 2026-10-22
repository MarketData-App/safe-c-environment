"""QuantLib 1.43 normal functions in exact binary64 operation order (spec 3.4; one definition for every variant).

Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz):
- ql/math/errorfunction.cpp:196-246 (ErrorFunction, a port of the fdlibm erf) -> `erf`;
- ql/math/distributions/normaldistribution.cpp:33-53 (CumulativeNormalDistribution::operator()) -> `norm_cdf`;
- ql/math/distributions/normaldistribution.hpp:262-281, 296-299 (NormalDistribution with average 0 and sigma 1;
  CumulativeNormalDistribution::derivative) -> `norm_pdf`;
- ql/mathconstants.hpp:85-87, 97-99 (M_SQRT_2, M_1_SQRTPI literals) and ql/qldefines.hpp:179 (QL_EPSILON).
The forms 0.5*erfc(-x/sqrt 2) and exp(-x*x/2)/sqrt(2 pi) are not the definition (they round differently). There is no
bivariate normal: the pinned Bjerksund-Stensland engine is the 1993 one-step method (spec 3.4).
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math, sys

QL_VERSION='1.43'
QL_EPSILON=sys.float_info.epsilon            # 2**-52 (qldefines.hpp:179)
DBL_MIN=sys.float_info.min
QL_MAX_REAL=sys.float_info.max
M_SQRT_2=0.7071067811865475244008443621048490392848359376887     # 0x1.6a09e667f3bcdp-1
M_1_SQRTPI=0.564189583547756286948                                # 0x1.20dd750429b6dp-1
NORMALIZATION=M_SQRT_2*M_1_SQRTPI/1.0                             # 0x1.9884533d43651p-2 (normaldistribution.hpp:270)
DENOMINATOR=2.0*(1.0*1.0)                                         # normaldistribution.hpp:271-272

TINY=QL_EPSILON;ONE=1.0;ERX=8.45062911510467529297e-01
EFX=1.28379167095512586316e-01;EFX8=1.02703333676410069053e+00
PP=(1.28379167095512558561e-01,-3.25042107247001499370e-01,-2.84817495755985104766e-02,-5.77027029648944159157e-03,-2.37630166566501626084e-05)
QQ=(3.97917223959155352819e-01,6.50222499887672944485e-02,5.08130628187576562776e-03,1.32494738004321644526e-04,-3.96022827877536812320e-06)
PA=(-2.36211856075265944077e-03,4.14856118683748331666e-01,-3.72207876035701323847e-01,3.18346619901161753674e-01,-1.10894694282396677476e-01,
    3.54783043256182359371e-02,-2.16637559486879084300e-03)
QA=(1.06420880400844228286e-01,5.40397917702171048937e-01,7.18286544141962662868e-02,1.26171219808761642112e-01,1.36370839120290507362e-02,
    1.19844998467991074170e-02)
RA=(-9.86494403484714822705e-03,-6.93858572707181764372e-01,-1.05586262253232909814e+01,-6.23753324503260060396e+01,-1.62396669462573470355e+02,
    -1.84605092906711035994e+02,-8.12874355063065934246e+01,-9.81432934416914548592e+00)
SA=(1.96512716674392571292e+01,1.37657754143519042600e+02,4.34565877475229228821e+02,6.45387271733267880336e+02,4.29008140027567833386e+02,
    1.08635005541779435134e+02,6.57024977031928170135e+00,-6.04244152148580987438e-02)
RB=(-9.86494292470009928597e-03,-7.99283237680523006574e-01,-1.77579549177547519889e+01,-1.60636384855821916062e+02,-6.37566443368389627722e+02,
    -1.02509513161107724954e+03,-4.83519191608651397019e+02)
SB=(3.03380607434824582924e+01,3.25792512996573918826e+02,1.53672958608443695994e+03,3.19985821950859553908e+03,2.55305040643316442583e+03,
    4.74528541206955367215e+02,-2.24409524465858183362e+01)

def erf(x):
    """QuantLib ErrorFunction::operator() (errorfunction.cpp:196-246), statement by statement (QL_VERSION 1.43)."""
    if not math.isfinite(x):
        if math.isnan(x):return x
        return 1.0 if x>0 else -1.0
    ax=math.fabs(x)
    if ax<0.84375:
        if ax<3.7252902984e-09:
            if ax<DBL_MIN*16:return 0.125*(8.0*x+EFX8*x)
            return x+EFX*x
        z=x*x
        r=PP[0]+z*(PP[1]+z*(PP[2]+z*(PP[3]+z*PP[4])))
        s=ONE+z*(QQ[0]+z*(QQ[1]+z*(QQ[2]+z*(QQ[3]+z*QQ[4]))))
        y=r/s
        return x+x*y
    if ax<1.25:
        s=ax-ONE
        P=PA[0]+s*(PA[1]+s*(PA[2]+s*(PA[3]+s*(PA[4]+s*(PA[5]+s*PA[6])))))
        Q=ONE+s*(QA[0]+s*(QA[1]+s*(QA[2]+s*(QA[3]+s*(QA[4]+s*QA[5])))))
        return ERX+P/Q if x>=0 else -ERX-P/Q
    if ax>=6:
        return ONE-TINY if x>=0 else TINY-ONE
    s=ONE/(ax*ax)
    if ax<2.85714285714285:
        R=RA[0]+s*(RA[1]+s*(RA[2]+s*(RA[3]+s*(RA[4]+s*(RA[5]+s*(RA[6]+s*RA[7]))))))
        S=ONE+s*(SA[0]+s*(SA[1]+s*(SA[2]+s*(SA[3]+s*(SA[4]+s*(SA[5]+s*(SA[6]+s*SA[7])))))))
    else:
        R=RB[0]+s*(RB[1]+s*(RB[2]+s*(RB[3]+s*(RB[4]+s*(RB[5]+s*RB[6])))))
        S=ONE+s*(SB[0]+s*(SB[1]+s*(SB[2]+s*(SB[3]+s*(SB[4]+s*(SB[5]+s*SB[6]))))))
    r=math.exp(-ax*ax-0.5625+R/S)
    return ONE-r/ax if x>=0 else r/ax-ONE

def norm_pdf(x):
    """NormalDistribution(0, 1)::operator() (normaldistribution.hpp:275-281); also the CDF derivative (lines 296-299)."""
    deltax=x-0.0
    exponent=-(deltax*deltax)/DENOMINATOR
    return 0.0 if exponent<=-690.0 else NORMALIZATION*math.exp(exponent)

def norm_cdf(z):
    """CumulativeNormalDistribution(0, 1)::operator() (normaldistribution.cpp:33-53): erf form, then the
    Abramowitz-Stegun 26.2.12 series when the result is <= 1e-8."""
    z=(z-0.0)/1.0
    result=0.5*(1.0+erf(z*M_SQRT_2))
    if result<=1e-8:
        sum_=1.0;zsqr=z*z;i=1.0;g=1.0;a=QL_MAX_REAL
        while True:
            lasta=a
            x=(4.0*i-3.0)/zsqr
            y=x*((4.0*i-1)/zsqr)
            a=g*(x-y)
            sum_-=a
            g*=y
            i+=1.0
            a=math.fabs(a)
            if not (lasta>a and a>=math.fabs(sum_*QL_EPSILON)):break
        result=-norm_pdf(z)/z*sum_
    return result
