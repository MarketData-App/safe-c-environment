"""QuantLib Brent through Solver1D::solve (spec 3.5; QL_VERSION 1.43), scalar form (the NumPy and C forms mirror it).

Transcribed statement by statement from the retained QuantLib 1.43 source: ql/math/solver1d.hpp:162-211 (solve with
the xMin/xMax bracket), ql/math/solvers1d/brent.hpp:39-133 (solveImpl) and ql/math/comparison.hpp:59-76 (close).
The result is `root_`. Every f call counts (`evaluations`): at most N_MAX = 201 for maxEvaluations = 200 (spec 3.5:
2 bracket calls, the guess call, then at most 198 loop passes with one call each).

Statuses (spec 3.3 orders 6-8): the bracket error ("root not bracketed: f[...") gives BELOW_MIN when f(xMin) > 0 and
ABOVE_MAX otherwise; the maximum-evaluations error gives NOT_CONVERGED; an exception raised by f propagates.
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math
from optionlab.models import close
from optionlab.normal import QL_EPSILON

N_MAX=201
ACCURACY=1e-10
MAX_EVALUATIONS=200

def _sign(a,b):return math.fabs(a) if b>=0.0 else -math.fabs(a)

def brent(fun,lo,hi,guess,accuracy=ACCURACY,max_evaluations=MAX_EVALUATIONS):
    """Returns (status, root, f(lo), f(hi), evaluations); root is NaN unless status is OK; f(hi) is NaN when not evaluated."""
    if not accuracy>0.0:raise ValueError('accuracy must be positive')
    accuracy=max(accuracy,QL_EPSILON)
    xMin,xMax=lo,hi
    if not xMin<xMax:raise ValueError('invalid range')
    n=0
    fxMin=fun(xMin);n+=1;f_lo=fxMin
    if close(fxMin,0.0):return 'OK',xMin,f_lo,math.nan,n
    fxMax=fun(xMax);n+=1;f_hi=fxMax
    if close(fxMax,0.0):return 'OK',xMax,f_lo,f_hi,n
    evaluationNumber=2
    if not fxMin*fxMax<0.0:
        return ('BELOW_MIN' if fxMin>0.0 else 'ABOVE_MAX'),math.nan,f_lo,f_hi,n
    if not guess>xMin or not guess<xMax:raise ValueError('guess outside the bracket')
    root=guess
    # Brent::solveImpl
    froot=fun(root);n+=1
    evaluationNumber+=1
    if froot*fxMin<0:
        xMax=xMin;fxMax=fxMin
    else:
        xMin=xMax;fxMin=fxMax
    d=root-xMax
    e=d
    while evaluationNumber<=max_evaluations:
        if (froot>0.0 and fxMax>0.0) or (froot<0.0 and fxMax<0.0):
            xMax=xMin;fxMax=fxMin
            e=d=root-xMin
        if math.fabs(fxMax)<math.fabs(froot):
            xMin=root;root=xMax;xMax=xMin
            fxMin=froot;froot=fxMax;fxMax=fxMin
        xAcc1=2.0*QL_EPSILON*math.fabs(root)+0.5*accuracy
        xMid=(xMax-root)/2.0
        if math.fabs(xMid)<=xAcc1 or close(froot,0.0):
            fun(root);n+=1
            evaluationNumber+=1
            return 'OK',root,f_lo,f_hi,n
        if math.fabs(e)>=xAcc1 and math.fabs(fxMin)>math.fabs(froot):
            s=froot/fxMin
            if close(xMin,xMax):
                p=2.0*xMid*s
                q=1.0-s
            else:
                q=fxMin/fxMax
                r=froot/fxMax
                p=s*(2.0*xMid*q*(q-r)-(root-xMin)*(r-1.0))
                q=(q-1.0)*(r-1.0)*(s-1.0)
            if p>0.0:q=-q
            p=math.fabs(p)
            min1=3.0*xMid*q-math.fabs(xAcc1*q)
            min2=math.fabs(e*q)
            if 2.0*p<(min1 if min1<min2 else min2):
                e=d
                d=p/q
            else:
                d=xMid
                e=d
        else:
            d=xMid
            e=d
        xMin=root
        fxMin=froot
        if math.fabs(d)>xAcc1:root+=d
        else:root+=_sign(xAcc1,xMid)
        froot=fun(root);n+=1
        evaluationNumber+=1
    return 'NOT_CONVERGED',math.nan,f_lo,f_hi,n
