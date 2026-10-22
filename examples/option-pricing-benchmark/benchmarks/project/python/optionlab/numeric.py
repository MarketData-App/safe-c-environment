"""Small order statistics shared by candidate code (host tools keep their own copy)."""
def median(xs):
    s=sorted(xs);n=len(s)
    if not n:raise ValueError('median of empty data')
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0
def quantile(xs,p):
    s=sorted(xs)
    if not s:raise ValueError('quantile of empty data')
    if not 0.0<=p<=1.0:raise ValueError('quantile level outside [0, 1]')
    h=(len(s)-1)*p;lo=int(h);hi=min(lo+1,len(s)-1);return s[lo]+(h-lo)*(s[hi]-s[lo])
