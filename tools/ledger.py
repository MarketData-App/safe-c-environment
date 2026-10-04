"""Provider-neutral deterministic review/repair accounting; no model calls."""
from evidence import GateError

class Ledger:
    def __init__(self, source_identity, units, budget=5):
        self.source_identity = source_identity
        self.units = units
        self.budget = budget
        self.findings = {}
        self.review = []

    def add(self, finding):
        required={'id','origin','source_identity','location','property','severity','rationale','reproducer','state','attempts','history','verification'}
        if set(finding) != required or finding['id'] in self.findings:
            raise GateError('missing/duplicate/unknown finding fields')
        if finding['source_identity'] != self.source_identity:
            raise GateError('finding source identity mismatch')
        if finding['state'] != 'OPEN' or finding['attempts'] != 0:
            raise GateError('new finding must start OPEN')
        self.findings[finding['id']] = finding

    def repair(self, identifier, *, before_failed, after_passed, regression_identity, source_identity):
        row = self.findings[identifier]
        if row['state'] in {'VERIFIED','REJECTED','DUPLICATE'}:
            raise GateError('terminal finding cannot be silently reopened')
        row['attempts'] += 1
        row['history'].append({'attempt':row['attempts'],'before_failed':before_failed,'after_passed':after_passed,'regression_identity':regression_identity,'source_identity':source_identity})
        if type(before_failed) is not bool or type(after_passed) is not bool or not regression_identity:
            raise GateError('invalid behavioral verification evidence')
        if before_failed and after_passed:
            row['state']='VERIFIED'; row['verification']=row['history'][-1]
        elif row['attempts']>=self.budget or (len(row['history'])>=3 and len({x['source_identity'] for x in row['history'][-3:]})==1):
            row['state']='BLOCKED'
        else:
            row['state']='UNRESOLVED'
        return row['state']

    def reject(self, identifier, reason, *, duplicate_of=None):
        if not reason or (duplicate_of is not None and duplicate_of not in self.findings):
            raise GateError('rejection/duplicate needs evidence/reason')
        row=self.findings[identifier]; row['state']='DUPLICATE' if duplicate_of else 'REJECTED'
        row['history'].append({'reason':reason,'duplicate_of':duplicate_of})

    def account(self, rows, source_identity):
        if source_identity != self.source_identity:
            raise GateError('whole-source review fingerprint changed')
        owed={(unit,question) for unit,questions in self.units.items() for question in questions}
        observed=set()
        for row in rows:
            key=(row['unit'],row['question'])
            if key in observed or key not in owed or not row['locations'] or type(row['locations'][0]) is not int:
                raise GateError('invalid/duplicate/uncited review accounting')
            observed.add(key)
        if observed != owed:
            raise GateError('missing required review units/questions')
        self.review=rows
