"""Read opaque build/test evidence and emit only bounded diagnostic classifications.

Native reports, assertion text, source snippets and traces never reach stdout.
This is a viewing utility, not an acceptance classifier.
"""
from pathlib import Path
import argparse
import json
import re

RULES = {
    'ASAN_FINDING': r'ERROR: AddressSanitizer',
    'LSAN_FINDING': r'LeakSanitizer',
    'UBSAN_FINDING': r'runtime error:',
    'MSAN_FINDING': r'WARNING: MemorySanitizer',
    'TSAN_FINDING': r'WARNING: ThreadSanitizer',
    'RUNTIME_INTERNAL_FAILURE': r'CHECK failed|(?:FATAL|ERROR): ThreadSanitizer',
    'COMPILER_ERROR': r'(?:^|\n)[^\n]*:\d+(?::\d+)?: (?:fatal )?error:',
    'COMPILER_WARNING': r'(?:^|\n)[^\n]*:\d+(?::\d+)?: warning:',
    'CONTRACT_FAILURE': r'CONTRACT_FAILED|FOUNDATION_ORACLE_FAILED',
}


def reduce_file(path, case_id):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('finite_summary_input_required')
    content = path.read_text(errors='replace')
    try:
        value = json.loads(content)
        rows = value if isinstance(value, list) else [value]
    except ValueError:
        rows = []
        for line in content.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except ValueError:
                pass
        if not rows:
            rows = [{'output': content}]
    result = []
    if len(rows) > 256:
        raise ValueError('finite_summary_rows_required')
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        text = '\n'.join(str(row.get(key, '')) for key in ['output', 'stdout', 'stderr'])
        code = row.get('exit_code', row.get('returncode'))
        if type(code) is not int:
            code = None
        base = {'case_id': case_id + '-' + str(index), 'exit_code': code,
                'file_path': str(path)}
        result.append({**base, 'verdict': 'PASS' if code == 0 and not row.get('failure') else 'FAIL' if code is not None else 'RECORDED'})
        for rule, pattern in RULES.items():
            if re.search(pattern, text):
                result.append({**base, 'case_id': base['case_id'] + '/' + rule,
                               'verdict': 'PRESENT'})
        for source in sorted(set(re.findall(r'/(?:src|work)/[A-Za-z0-9_./-]+\.(?:c|h)(?::\d+)?', text)))[:8]:
            result.append({**base, 'case_id': base['case_id'] + '/SOURCE_LOCATION',
                           'verdict': 'RECORDED', 'file_path': source})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path)
    parser.add_argument('--case-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.case_id):
        raise ValueError('typed_case_id_required')
    for row in reduce_file(args.path, args.case_id):
        print(json.dumps(row))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'case_id': 'SUMMARY_REDUCER', 'verdict': type(error).__name__}))
        raise SystemExit(1)
