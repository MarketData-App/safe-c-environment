"""Unit-maturity time mapping and chain-rule greeks (spec Amendment B item 3, section 3.6; QL_VERSION 1.43).

Every variant evaluates a price as the unit-maturity problem U(S, K, r', q', sigma') with T' = 1: in QuantLib the
evaluation date d0, the maturity d0 + 365 days, Actual365Fixed, flat continuous r' and q' curves and a constant sigma'.
The IV solve stays in sigma; only the price evaluation maps.
"""
import math

def unit(T,r,q,sigma):
    """(r', q', sigma') = (r*T, q*T, sigma*sqrt(T)), computed in this binary64 order (Amendment B item 3)."""
    r1=r*T
    q1=q*T
    s1=sigma*math.sqrt(T)
    return r1,q1,s1

def greeks_from_unit(T,r,q,sigma,dU,theta_bump=None):
    """Greeks of the original problem in output units from the mapped engine greeks `dU`.

    Keys of dU: delta_U, gamma_U (always); theta_U, vega_U, rho_U, div_rho_U when the engine supplies them; vega and rho
    may instead come as original-variable bumps `vega_bump` and `rho_bump` (per unit sigma and per unit r).
    delta = U_S; gamma = U_SS; vega = sqrt(T)*U_sigma'; rho = T*U_r'. Theta per year, precedence of Amendment B item 3:
    (a) theta_U / T when dU holds the engine theta_U; (b) -(r*U_r' + q*U_q' + sigma/(2 sqrt T)*U_sigma') when dU holds
    vega_U, rho_U and div_rho_U; (c) `theta_bump` (the declared delta bump in the original T), required in that case.
    Output units (section 3.6): theta / 365 per calendar day, vega and rho / 100 per point.
    A vega or rho that dU supplies in neither form is left out of the result (the caller adds its declared bump).
    """
    sq=math.sqrt(T)
    if 'theta_U' in dU:theta=dU['theta_U']/T
    elif all(k in dU for k in ('vega_U','rho_U','div_rho_U')):
        theta=-(r*dU['rho_U']+q*dU['div_rho_U']+sigma/(2*sq)*dU['vega_U'])
    elif theta_bump is not None:theta=theta_bump
    else:raise ValueError('theta: no engine theta, no engine vega/rho/dividendRho and no declared bump')
    out={'delta':dU['delta_U'],'gamma':dU['gamma_U'],'theta':theta/365.0}
    if 'vega_U' in dU:out['vega']=(sq*dU['vega_U'])*0.01
    elif 'vega_bump' in dU:out['vega']=dU['vega_bump']*0.01
    if 'rho_U' in dU:out['rho']=(T*dU['rho_U'])*0.01
    elif 'rho_bump' in dU:out['rho']=dU['rho_bump']*0.01
    return out
