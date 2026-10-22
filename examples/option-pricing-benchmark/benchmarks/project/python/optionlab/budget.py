"""Amendment I10.2: the planning-budget formula (pure; seconds unless stated).

This module left the framework (FR5B-04; PB-L3, FR3 residue) and lives in the option example; the content is
tools/bench_budget.py of commit a722ed7. The constants below are the planning constants of the I10.2 illustration, measured
on this example. They give only a pre-calibration illustration; no framework code calls this module. The planning shares
come from the project's protocol (load_policy(root, project))."""
import math

SYNTHETIC_BLOCK_SECONDS=797.0      # one full-dataset block per unit share, synthetic large chain (I10.2)
LOCAL_BLOCK_SECONDS=1203.5         # the same block on the local chain (I10.2)
BLOCK_OVERHEAD_SECONDS=36.0        # per-block fixed overhead (I10.2)
REFERENCE_SECONDS_PER_ROW=0.140    # py-reference seconds per row per unit share (I10.2)
SINGLE_RECORD_BASE_SECONDS=86.0     # single-record block base (I10.2)
SINGLE_RECORD_SHARE_SECONDS=4.2     # single-record block seconds per unit share (I10.2)
SINGLE_RECORD_BLOCKS=13             # 12 timed blocks + 1 warm-up (I10.2)
DIAGNOSTIC_SECONDS_PER_MODEL=180.0
BLOCKS=12;SESSION_CAP_SECONDS=10800

class PlanRefusal(Exception):
    """A plan that cannot be built: `reason` is a stable reason name, `detail` a short text (used by Task A8)."""
    def __init__(self,reason,detail):
        super().__init__(f'{reason}: {detail}');self.reason=reason;self.detail=detail

def full_dataset_block(share,local=False):
    """B = 797 s x share + 36 s (synthetic) or 1203.5 s x share + 36 s (local)."""
    return (LOCAL_BLOCK_SECONDS if local else SYNTHETIC_BLOCK_SECONDS)*share+BLOCK_OVERHEAD_SECONDS

def sessions_for(block,blocks=BLOCKS,cap=SESSION_CAP_SECONDS):
    """Sessions for `blocks` timed blocks of `block` seconds: b_max = floor(cap / block) - 1 (one warm-up block per
    session); refused (PlanRefusal session-cap-infeasible) when b_max < 1; else ceil(blocks / b_max)."""
    b_max=math.floor(cap/block)-1
    if b_max<1:raise PlanRefusal('session-cap-infeasible',f'a block of {block:.1f} s leaves no timed block in a {cap} s session')
    return math.ceil(blocks/b_max)

def reference_batch(share,rows):
    """R = 0.140 s x rows x share."""
    return REFERENCE_SECONDS_PER_ROW*rows*share

def full_dataset_group(share,rows,local):
    """{'block','sessions','timing','warmups','reference','total'}: timing = 12 B, warmups = n B, reference = R."""
    block=full_dataset_block(share,local);n=sessions_for(block);timing=BLOCKS*block;warmups=n*block;ref=reference_batch(share,rows)
    return {'block':block,'sessions':n,'timing':timing,'warmups':warmups,'reference':ref,'total':timing+warmups+ref}

def single_record_group(shares):
    """Sum over models of 13 x (86 s + 4.2 s x share)."""
    return sum(SINGLE_RECORD_BLOCKS*(SINGLE_RECORD_BASE_SECONDS+SINGLE_RECORD_SHARE_SECONDS*s) for s in shares)

def diagnostics(models):
    """180 s per model."""
    return DIAGNOSTIC_SECONDS_PER_MODEL*models

def share(policy,selector):
    """The planning share of a selector: 1.0 for `all` (the calibration rates come from selector `all` rows); the
    approved budgets.estimate_share_per_selector value; any other selector raises ValueError (no 1.0 default here)."""
    if selector=='all':return 1.0
    shares=policy['budgets'].get('estimate_share_per_selector',{})
    if selector not in shares:raise ValueError(f'{selector} share not approved (G-ALO1 R14)')
    return float(shares[selector])
