"""Thin lit format invoking the protected production adapters, not shell RUN text."""
import json
import lit.Test
from lit.formats.base import FileBasedTest
from evidence import GateError
Q = None
OUTPUT = None
class GateFormat(FileBasedTest):
    def __init__(self, qualifier):
        self.qualifier = qualifier
    def execute(self, test, config):
        cid=test.path_in_suite[-1].removesuffix('.test')
        if config.noExecute or test.config.unsupported or test.xfails or test.requires:
            return lit.Test.Result(lit.Test.UNRESOLVED, 'mandatory test cannot be skipped or waived')
        try:
            row=self.qualifier.qualify_case(cid)
        except (GateError,OSError,ValueError,KeyError) as exc:
            return lit.Test.Result(lit.Test.UNRESOLVED,str(exc))
        print(f"{cid}: {row['classification']} / control {row['control']}",flush=True)
        return lit.Test.Result(lit.Test.PASS if row['status']=='PASS' else lit.Test.FAIL,json.dumps(row))
