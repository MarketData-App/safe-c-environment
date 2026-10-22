"""The planned work of one bench trial: one definition for the host rules and the rules inside a local decision job.

T5R1-A01 (the T5-R1 approver finding): a single-record (panel) trial (benchlab/trial.py run_panel, Amendment G7.3) makes
panel_passes passes over its panel rows, one one-row request per row and pass, and adds the work units of each one-row
result, so its observation reports len(panel) x panel_passes x PANEL_ROWS_PER_CALL work units, never the rows of its
tier. Each pooled call of such a trial holds one row, so its pool identity (the last call's) has the chunks of one row
(spec B10: a one-row request has one chunk).

Users: on the host, tools/bench.py check_completeness (P07), tools/bench_evidence.py check_integrity (B15 `wrong work
count`) and tools/bench_plan.py b10_row_count (B10, for tools/bench.py check_concurrency_identity); inside a local
decision job, the rules work-count and pool-identity of container/bench-coordinator.py local_rule_counts. The host loads
this file by its path (tools/bench_plan.py); the coordinator imports it from its own directory. No import, no I/O."""

PANEL_ROWS_PER_CALL=1      # spec L4 items 2 and 3, G7.3: a single-record request holds exactly one row (the adapter's `take`)

def _count(v):return type(v) is int and v>=0

def planned_work_units(trial,sizes):
    """The work units that the observation of the planned trial `trial` reports when the trial completes (P07, B15). A
    single-record (panel) trial: len(panel) x panel_passes x PANEL_ROWS_PER_CALL. A capacity trial: the rows of its tier
    for every request of every client (Task 22). Any other trial: the rows of its tier, sizes[tier]. None when the plan
    row or `sizes` is malformed: no observed count equals None, so a rule that compares with it fails closed."""
    if not isinstance(trial,dict) or not isinstance(sizes,dict):return None
    if 'panel' in trial:
        panel,passes=trial.get('panel'),trial.get('panel_passes')
        if not isinstance(panel,list) or not panel or not _count(passes) or passes<1:return None
        return len(panel)*passes*PANEL_ROWS_PER_CALL
    tier=trial.get('tier');rows=sizes.get(tier) if isinstance(tier,str) else None
    if not _count(rows):return None
    if trial.get('scope')=='capacity':
        clients,requests=trial.get('clients'),trial.get('requests_per_client')
        return rows*clients*requests if _count(clients) and _count(requests) else None
    return rows

def request_rows(trial,rows):
    """B10 (Amendment E item 6): the rows of one pooled request of the planned trial `trial`, the row count of its chunk
    rule. A single-record (panel) trial calls one-row requests: PANEL_ROWS_PER_CALL. Any other trial: `rows`, the row
    count of the caller (the rows of its tier; on the host, the planned prefix of a local dataset)."""
    return PANEL_ROWS_PER_CALL if isinstance(trial,dict) and 'panel' in trial else rows
