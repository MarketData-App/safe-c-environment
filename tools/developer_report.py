"""Outcome and inventory invariants; advisory tools cannot grant acceptance."""
from evidence import GateError
from policy import exact_ids


def binding(value,expected):
    """Bind collected feedback to independently retained outer job identities."""
    for key in ['source_identity','profile','context_namespace','demo_source_identity']:
        if value.get(key)!=expected.get(key):
            raise GateError('developer feedback source/worktree/profile binding rejected')
    actual=value.get('result',{}).get('debugger')
    original=expected.get('result',{}).get('debugger')
    if original and (not actual or any(actual.get(key)!=original.get(key) for key in
        ['executable_sha256','loaded_dependency','inferior_argv','observed_inferior_argv','breakpoint'])):
        raise GateError('developer executable/dependency/source-symbol binding rejected')
    return feedback(value)


def feedback(value):
    if value.get('scope')!='partial_feedback' or value.get('acceptance') is not False:
        raise GateError('developer feedback cannot claim complete acceptance')
    native=value.get('result',{})
    test=native.get('test_result')
    if test:
        if test.get('executed_cases')!=1 or test.get('complete_selection') is not True:
            raise GateError('selected developer test is empty, ambiguous or incomplete')
        if test.get('program_result_preserved') is not True:
            raise GateError('selected developer child outcome was not preserved')
        if value['status']=='PASS' and test.get('ctest_exit_code')!=0:
            raise GateError('failed selected test cannot pass feedback')
    debug=native.get('debugger')
    if debug:
        if value['status']=='PASS' and debug.get('debug_session_status')!='PASS':
            raise GateError('failed debugger session cannot pass feedback')
        if debug.get('debug_session_status')=='PASS':
            if (debug.get('inspection_requirements_met') is not True or
                    debug.get('complete_capture') is not True or not debug.get('frames') or
                    not debug.get('stop') or debug.get('errors') or debug.get('timed_out')):
                raise GateError('incomplete debugger inspection cannot pass')
        outcome=debug.get('inferior_outcome',{})
        if outcome.get('status')=='PASSED' and outcome.get('exit_code')!=0:
            raise GateError('nonzero inferior cannot be a passed program')
        if outcome.get('status')=='FAILED' and outcome.get('exit_code')==0:
            raise GateError('contradictory inferior failure/zero exit')
        if debug.get('recipe')=='breakpoint' and debug.get('inspection_requirements_met'):
            if debug['stop'].get('reason')!='breakpoint-hit' or not debug.get('breakpoint'):
                raise GateError('unreached breakpoint cannot satisfy inspection')
            if debug['stop'].get('bkptno')!=debug['breakpoint'].get('number'):
                raise GateError('debugger stop did not reach the selected breakpoint')
    fuzz=native.get('fuzz_result')
    if fuzz and (fuzz.get('program_result_preserved') is not True or
                 (value['status']=='PASS' and fuzz.get('exit_code')!=0)):
        raise GateError('original fuzz failure cannot be masked')
    return True


def qualification(value,inventory,expected_source,expected_image):
    if value['source_identity']!=expected_source or value['image_id']!=expected_image:
        raise GateError('developer qualification source/image binding mismatch')
    exact_ids(value['cases'],[r['id'] for r in inventory['cases']])
    for case,required in zip(sorted(value['cases'],key=lambda r:r['id']),inventory['cases']):
        if set(case)!={'id','status','control','subchecks'}:
            raise GateError('malformed developer case record')
        if case['id']!=required['id']:
            raise GateError('developer case ordering mismatch')
        names=[r['name'] for r in case['subchecks']]
        if len(names)!=len(set(names)) or set(names)!=set(required['subchecks']):
            raise GateError('missing, duplicate or unknown developer subcheck')
        for row in case['subchecks']:
            if (not {'name','status','control','evidence_paths','reason'}.issubset(row) or
                    row['status'] not in {'PASS','FAIL','BLOCKED'} or row['control'] not in {'PASS','FAIL','BLOCKED'} or
                    (row['status']=='PASS' and (row['control']!='PASS' or not row['evidence_paths']))):
                raise GateError('developer subcheck control/evidence missing or contradictory')
        complete=case['control']=='PASS' and all(r['status']=='PASS' and r['control']=='PASS' and
                     r['evidence_paths'] for r in case['subchecks'])
        if case['status']=='PASS' and not complete:
            raise GateError('developer case omitted a required control or observation')
        states=[r['status'] for r in case['subchecks']]
        controls=[r['control'] for r in case['subchecks']]
        expected_status='FAIL' if 'FAIL' in states else 'BLOCKED' if 'BLOCKED' in states else 'PASS'
        expected_control='FAIL' if 'FAIL' in controls else 'BLOCKED' if 'BLOCKED' in controls else 'PASS'
        if case['status']!=expected_status or case['control']!=expected_control:
            raise GateError('developer aggregate masks a subcheck outcome')
    expected={(r['parent'],r['name'],v) for r in inventory['pipeline_subcases'] for v in r['variants']}
    rows=value['pipeline_variants']
    actual=[(r['parent'],r['name'],r['variant']) for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise GateError('developer pipeline variant inventory mismatch')
    for row in rows:
        if (not {'parent','name','variant','status','control','evidence_paths','reason'}.issubset(row) or
                row['status'] not in {'PASS','FAIL','BLOCKED'} or row['control'] not in {'PASS','FAIL','BLOCKED'} or
                (row['status']=='PASS' and (row['control']!='PASS' or not row['evidence_paths']))):
            raise GateError('developer pipeline control/evidence incomplete')
    complete=all(c['status']=='PASS' for c in value['cases']) and all(r['status']=='PASS' and
        r['control']=='PASS' and r['evidence_paths'] for r in rows)
    if value['status']=='PASS' and not complete:
        raise GateError('unexecuted mandatory developer experiment cannot pass')
    statuses=[r['status'] for r in value['cases']+rows]
    expected_status='FAIL' if 'FAIL' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASS'
    if value['status']!=expected_status:
        raise GateError('developer qualification masks a required outcome')
    return True
