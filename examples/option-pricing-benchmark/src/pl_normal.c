/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/normal.py lines
 * 1-96: ql/math/errorfunction.cpp 196-246, ql/math/distributions/normaldistribution.hpp 262-281,
 * 296-299, ql/math/distributions/normaldistribution.cpp 33-53, ql/mathconstants.hpp 85-87, 97-99,
 * ql/qldefines.hpp 179. QuantLib license (BSD-3-Clause): the copyright notices, conditions and
 * disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_normal.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <float.h>
#include <math.h>
#include <stddef.h>

/* QuantLib normal functions (specs/project/models.md "Normal distribution"). Each function copies
 * the cited optionlab.normal function statement by statement; every constant is the hex-float
 * literal of the Python value (spec 3.4; Amendment F item 8). */

/* PL_M_SQRT_2 (mathconstants.hpp:85-87, 0.7071067811865475244008443621048490392848359376887)
 * and PL_M_1_SQRTPI are in pl_types.h. */
/* normaldistribution.hpp:270 normalizationFactor_ = M_SQRT_2 * M_1_SQRTPI / sigma_, with
 * M_1_SQRTPI = 0.564189583547756286948 = 0x1.20dd750429b6dp-1 (mathconstants.hpp:97-99) and
 * sigma_ = 1.0: the binary64 value of normal.NORMALIZATION. */
static const double PL_NORMALIZATION = 0x1.9884533d43651p-2;
/* normaldistribution.hpp:271-272 denominator_ = 2.0 * sigma_ * sigma_ (normal.DENOMINATOR). */
static const double PL_DENOMINATOR = 2.0;
/* normal.py: the series switch of norm_cdf, 1e-8. */
static const double PL_CDF_SERIES_BELOW = 0x1.5798ee2308c3ap-27;
/* errorfunction.cpp bounds as written in normal.py: 3.7252902984e-09 (just below 2**-28) and
 * the RA/RB switch 2.85714285714285 (about 1/0.35). */
static const double PL_ERF_SMALL = 0x1.ffffffffdb73dp-29;
static const double PL_ERF_RA_BELOW = 0x1.6db6db6db6da7p+1;

/* ErrorFunction constants (errorfunction.cpp, normal.py:21-37). */
static const double ONE = 1.0;
static const double ERX = 0x1.b0ac160000000p-1;
static const double EFX = 0x1.06eba8214db69p-3;
static const double EFX8 = 0x1.06eba8214db69p+0;
static const double PP[5] = {
    0x1.06eba8214db68p-3,   /* 1.28379167095512558561e-01 */
    -0x1.4cd7d691cb913p-2,  /* -3.25042107247001499370e-01 */
    -0x1.d2a51dbd7194fp-6,  /* -2.84817495755985104766e-02 */
    -0x1.7a291236668e4p-8,  /* -5.77027029648944159157e-03 */
    -0x1.8ead6120016acp-16, /* -2.37630166566501626084e-05 */
};

static const double QQ[5] = {
    0x1.97779cddadc09p-2,   /* 3.97917223959155352819e-01 */
    0x1.0a54c5536cebap-4,   /* 6.50222499887672944485e-02 */
    0x1.4d022c4d36b0fp-8,   /* 5.08130628187576562776e-03 */
    0x1.15dc9221c1a10p-13,  /* 1.32494738004321644526e-04 */
    -0x1.09c4342a26120p-18, /* -3.96022827877536812320e-06 */
};

static const double PA[7] = {
    -0x1.359b8bef77538p-9, /* -2.36211856075265944077e-03 */
    0x1.a8d00ad92b34dp-2,  /* 4.14856118683748331666e-01 */
    -0x1.7d240fbb8c3f1p-2, /* -3.72207876035701323847e-01 */
    0x1.45fca805120e4p-2,  /* 3.18346619901161753674e-01 */
    -0x1.c63983d3e28ecp-4, /* -1.10894694282396677476e-01 */
    0x1.22a36599795ebp-5,  /* 3.54783043256182359371e-02 */
    -0x1.1bf380a96073fp-9, /* -2.16637559486879084300e-03 */
};

static const double QA[6] = {
    0x1.b3e6618eee323p-4, /* 1.06420880400844228286e-01 */
    0x1.14af092eb6f33p-1, /* 5.40397917702171048937e-01 */
    0x1.2635cd99fe9a7p-4, /* 7.18286544141962662868e-02 */
    0x1.02660e763351fp-3, /* 1.26171219808761642112e-01 */
    0x1.bedc26b51dd1cp-7, /* 1.36370839120290507362e-02 */
    0x1.88b545735151dp-7, /* 1.19844998467991074170e-02 */
};

static const double RA[8] = {
    -0x1.43412600d6435p-7, /* -9.86494403484714822705e-03 */
    -0x1.63416e4ba7360p-1, /* -6.93858572707181764372e-01 */
    -0x1.51e0441b0e726p+3, /* -1.05586262253232909814e+01 */
    -0x1.f300ae4cba38dp+5, /* -6.23753324503260060396e+01 */
    -0x1.44cb184282266p+7, /* -1.62396669462573470355e+02 */
    -0x1.7135cebccabb2p+7, /* -1.84605092906711035994e+02 */
    -0x1.4526557e4d2f2p+6, /* -8.12874355063065934246e+01 */
    -0x1.3a0efc69ac25cp+3, /* -9.81432934416914548592e+00 */
};

static const double SA[8] = {
    0x1.3a6b9bd707687p+4,  /* 1.96512716674392571292e+01 */
    0x1.1350c526ae721p+7,  /* 1.37657754143519042600e+02 */
    0x1.b290dd58a1a71p+8,  /* 4.34565877475229228821e+02 */
    0x1.42b1921ec2868p+9,  /* 6.45387271733267880336e+02 */
    0x1.ad02157700314p+8,  /* 4.29008140027567833386e+02 */
    0x1.b28a3ee48ae2cp+6,  /* 1.08635005541779435134e+02 */
    0x1.a47ef8e484a93p+2,  /* 6.57024977031928170135e+00 */
    -0x1.eeff2ee749a62p-5, /* -6.04244152148580987438e-02 */
};

static const double RB[7] = {
    -0x1.4341239e86f4ap-7,  /* -9.86494292470009928597e-03 */
    -0x1.993ba70c285dep-1,  /* -7.99283237680523006574e-01 */
    -0x1.1c209555f995ap+4,  /* -1.77579549177547519889e+01 */
    -0x1.4145d43c5ed98p+7,  /* -1.60636384855821916062e+02 */
    -0x1.3ec881375f228p+9,  /* -6.37566443368389627722e+02 */
    -0x1.004616a2e5992p+10, /* -1.02509513161107724954e+03 */
    -0x1.e384e9bdc383fp+8,  /* -4.83519191608651397019e+02 */
};

static const double SB[7] = {
    0x1.e568b261d5190p+4,  /* 3.03380607434824582924e+01 */
    0x1.45cae221b9f0ap+8,  /* 3.25792512996573918826e+02 */
    0x1.802eb189d5118p+10, /* 1.53672958608443695994e+03 */
    0x1.8ffb7688c246ap+11, /* 3.19985821950859553908e+03 */
    0x1.3f219cedf3be6p+11, /* 2.55305040643316442583e+03 */
    0x1.da874e79fe763p+8,  /* 4.74528541206955367215e+02 */
    -0x1.670e242712d62p+4, /* -2.24409524465858183362e+01 */
};
/* The nested Python form c[0]+s*(c[1]+s*(...+s*c[n-1])) of normal.py, evaluated innermost first:
 * t = c[n-1], then t = c[k-1] + s * t for k = n-1 down to 1. Python evaluates the nested
 * expression in this order and rounds each operation to binary64, so the operations, their order
 * and their association are the same. n >= 2 for every table. */
static double nested(const double *c, size_t n, double s) {
    double t = *(c + (n - 1u));
    for (size_t k = n - 1u; k > 0u; k--) {
        t = *(c + (k - 1u)) + s * t;
    }
    return t;
}

/* normal.erf (normal.py:40-69), QuantLib ErrorFunction::operator() (errorfunction.cpp:196-246). */
double pl_erf(double x) {
    if (!pl_is_finite(x)) {
        if (pl_is_nan(x)) {
            return x;
        }
        return x > 0.0 ? 1.0 : -1.0;
    }
    const double ax = pl_fabs(x);
    if (ax < 0.84375) {
        if (ax < PL_ERF_SMALL) {
            if (ax < DBL_MIN * 16.0) {
                return 0.125 * (8.0 * x + EFX8 * x);
            }
            return x + EFX * x;
        }
        const double z = x * x;
        const double r = nested(PP, 5u, z);
        const double s = ONE + z * nested(QQ, 5u, z);
        const double y = r / s;
        return x + x * y;
    }
    if (ax < 1.25) {
        const double s = ax - ONE;
        const double P = nested(PA, 7u, s);
        const double Q = ONE + s * nested(QA, 6u, s);
        return x >= 0.0 ? ERX + P / Q : -ERX - P / Q;
    }
    if (ax >= 6.0) {
        return x >= 0.0 ? ONE - PL_QL_EPSILON : PL_QL_EPSILON - ONE;
    }
    const double s = ONE / (ax * ax);
    double R;
    double S;
    if (ax < PL_ERF_RA_BELOW) {
        R = nested(RA, 8u, s);
        S = ONE + s * nested(SA, 8u, s);
    } else {
        R = nested(RB, 7u, s);
        S = ONE + s * nested(SB, 7u, s);
    }
    const double r = exp(-ax * ax - 0.5625 + R / S);
    return x >= 0.0 ? ONE - r / ax : r / ax - ONE;
}

/* normal.norm_pdf (normal.py:72-76), NormalDistribution(0, 1)::operator()
 * (normaldistribution.hpp:275-281). */
double pl_norm_pdf(double x) {
    const double deltax = x - 0.0;
    const double exponent = -(deltax * deltax) / PL_DENOMINATOR;
    return exponent <= -690.0 ? 0.0 : PL_NORMALIZATION * exp(exponent);
}

/* normal.norm_cdf (normal.py:78-96), CumulativeNormalDistribution(0, 1)::operator()
 * (normaldistribution.cpp:33-53). */
double pl_norm_cdf(double z) {
    z = (z - 0.0) / 1.0;
    double result = 0.5 * (1.0 + pl_erf(z * PL_M_SQRT_2));
    if (result <= PL_CDF_SERIES_BELOW) {
        double sum = 1.0;
        const double zsqr = z * z;
        double i = 1.0;
        double g = 1.0;
        double a = DBL_MAX;
        for (;;) {
            const double lasta = a;
            const double x = (4.0 * i - 3.0) / zsqr;
            const double y = x * ((4.0 * i - 1.0) / zsqr);
            a = g * (x - y);
            sum = sum - a;
            g = g * y;
            i = i + 1.0;
            a = pl_fabs(a);
            if (!(lasta > a && a >= pl_fabs(sum * PL_QL_EPSILON))) {
                break;
            }
        }
        result = (-pl_norm_pdf(z)) / z * sum;
    }
    return result;
}
