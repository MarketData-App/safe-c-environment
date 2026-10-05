"""Outcome and inventory invariants; advisory tools cannot grant acceptance."""
from evidence import GateError
from policy import exact_ids


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
        if case['id']!=required['id']:
            raise GateError('developer case ordering mismatch')
        names=[r['name'] for r in case['subchecks']]
        if len(names)!=len(set(names)) or set(names)!=set(required['subchecks']):
            raise GateError('missing, duplicate or unknown developer subcheck')
        complete=case['control']=='PASS' and all(r['status']=='PASS' and r['control']=='PASS' and
                     r['evidence_paths'] for r in case['subchecks'])
        if case['status']=='PASS' and not complete:
            raise GateError('developer case omitted a required control or observation')
    expected={(r['parent'],r['name'],v) for r in inventory['pipeline_subcases'] for v in r['variants']}
    rows=value['pipeline_variants']
    actual=[(r['parent'],r['name'],r['variant']) for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise GateError('developer pipeline variant inventory mismatch')
    complete=all(c['status']=='PASS' for c in value['cases']) and all(r['status']=='PASS' and
        r['control']=='PASS' and r['evidence_paths'] for r in rows)
    if value['status']=='PASS' and not complete:
        raise GateError('unexecuted mandatory developer experiment cannot pass')
    return True
