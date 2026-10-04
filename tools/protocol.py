"""Scripted review responses verified against an actual isolated C demo."""
from evidence import GateError, atomic_json, file_hash, passed
from ledger import Ledger
from policy import source_identity
from schema_check import validate


def run_protocol(q):
    identity = source_identity(q.root)[0]
    unit = 'safety/qualification/C33/bad.c'
    units = {unit: ['exact-bound', 'return-status']}
    ledger = Ledger(identity, units)
    build = q.build('asan', case='C33')
    if not q.built(build):
        raise GateError('protocol demo could not build')
    before = q.executable(build, 'C33_bad', label='protocol-original')
    after = q.executable(build, 'C33_good', label='protocol-repair')
    still_bad = q.executable(build, 'C33_bad', label='protocol-claimed-fix')
    exposed = before['failure'] is None and before['exit_code'] == 1 and 'PROPERTY exact-bound: length=4 capacity=4' in before['output'] and 'Sanitizer' not in before['output']
    clean = passed(after) and after['binary_unchanged']
    repeated = still_bad['exit_code'] == 1 and still_bad['failure'] is None and still_bad['binary_sha256'] == before['binary_sha256']
    if not (exposed and clean and repeated):
        raise GateError('protocol counterexample / repair evidence invalid')
    regression = 'C33: length=4 capacity=4; identical ASan build and runtime settings'

    def add(identifier, prop='exact-bound'):
        ledger.add({'id': identifier, 'origin': 'scripted-reviewer', 'source_identity': identity,
                    'location': unit + ':15', 'property': prop, 'severity': 'major',
                    'rationale': 'Check the independently stated inclusive-capacity boundary.',
                    'reproducer': regression, 'state': 'OPEN', 'attempts': 0,
                    'history': [], 'verification': None})

    add('SIM-GENUINE')
    verified = ledger.repair('SIM-GENUINE', before_failed=exposed, after_passed=clean,
                             regression_identity=regression, source_identity=after['binary_sha256'])
    add('SIM-WRONG', 'exact-capacity should always be rejected')
    ledger.reject('SIM-WRONG', 'The contract permits exact capacity; the genuine repaired binary passes this boundary: ' + after['evidence_path'])
    add('SIM-CLAIMED-FIX')
    unresolved = ledger.repair('SIM-CLAIMED-FIX', before_failed=exposed, after_passed=passed(still_bad),
                              regression_identity=regression, source_identity=still_bad['binary_sha256'])
    add('SIM-REPEATED')
    for _ in range(3):
        blocked = ledger.repair('SIM-REPEATED', before_failed=exposed, after_passed=passed(still_bad),
                                regression_identity=regression, source_identity=still_bad['binary_sha256'])
    stopped = False
    try:
        ledger.repair('SIM-REPEATED', before_failed=exposed, after_passed=clean,
                      regression_identity=regression, source_identity=after['binary_sha256'])
    except GateError:
        stopped = True
    ledger.account([{'unit': unit, 'question': question, 'locations': [15]} for question in units[unit]], identity)
    payload = {'schema_version': 1, 'source_identity': identity, 'units': units,
               'findings': list(ledger.findings.values()), 'review': ledger.review}
    validate(q.root, 'ledger', payload)
    path = q.runner.run_dir / 'simulated-review-ledger.json'
    atomic_json(path, payload)
    ok = verified == 'VERIFIED' and unresolved == 'UNRESOLVED' and blocked == 'BLOCKED' and stopped
    return {'status': 'PASS' if ok else 'FAIL', 'mode': 'protocol tests with simulated agent responses against real C33 bad/good binaries',
            'live_review': 'NOT_RUN; no provider enabled', 'counterexample': regression,
            'outcomes': {identifier: row['state'] for identifier, row in ledger.findings.items()},
            'required_reviewer_policy': 'An unavailable reviewer required by a future application contract blocks that review step.',
            'ledger_sha256': file_hash(path), 'evidence_paths': [path.as_posix(), before['evidence_path'], after['evidence_path'], still_bad['evidence_path']]}
