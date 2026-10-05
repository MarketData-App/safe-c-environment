"""Explicit offline dependency acquisition/build step, never run by normal checks.

The trusted host orchestrates finite Docker jobs and collects opaque evidence.
It executes no native compiler/library/test on the host and prints only summaries.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import shutil
import tempfile
from evidence import Runner, read_json, passed, file_hash, GateError

ROOT = Path(__file__).resolve().parents[1]

def retain_failure(runner, outcome, directory):
    for line in outcome['output'].splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if row.get('phase', '').startswith('upstream-') and not row['phase'].startswith('upstream-build-') and row.get('exit_code'):
            relative = 'dependency/' + row['phase'] + '-testlog.json'
            native = runner.fetch(relative, directory / Path(relative).name)
            for data in [json.loads(x) for x in native.read_text().splitlines() if x.strip()]:
                text = data.get('stdout', '') + data.get('stderr', '')
                print(json.dumps({'case_id': data.get('name'), 'exit_code': data.get('returncode'),
                    'ASAN_FINDING': 'ERROR: AddressSanitizer' in text,
                    'LSAN_FINDING': 'LeakSanitizer' in text,
                    'UBSAN_FINDING': 'runtime error:' in text,
                    'MSAN_FINDING': 'WARNING: MemorySanitizer' in text,
                    'diagnostic_paths': sorted(set(re.findall(r'/(?:work|src)/[A-Za-z0-9_./-]+\.(?:c|h)(?::\d+)?', text)))[:5],
                    'native_log_path': str(native)}), flush=True)
        elif row.get('log') and row.get('exit_code'):
            log = runner.fetch(row['log'].removeprefix('/work/'), directory / Path(row['log']).name)
            print(json.dumps({'failed_phase': row['phase'], 'exit_code': row['exit_code'],
                              'log_path': str(log)}), flush=True)
        if row.get('error_type'):
            print(json.dumps({'error_type': row['error_type'], 'file_path': row.get('file_path')}), flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('recipe', ROOT / 'container/build-foundation.py')
    recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recipe)
    profiles = list(recipe.PROFILES)
    if args.profile:
        if args.profile not in profiles:
            raise GateError('unknown dependency profile')
        profiles = [args.profile]
    else:
        profiles = ['asan', 'msan', *[p for p in profiles if p not in ['asan', 'msan']]]
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'artifacts') or output.exists():
        raise GateError('new owned evidence destination required')
    output.mkdir(parents=True)
    lock = read_json(ROOT / 'toolchain.lock.json')
    rows = []
    for profile in profiles:
        directory = output / profile
        runner = Runner(ROOT, directory, lock, Path(tempfile.mkdtemp(prefix='foundation-sdk-')),
                        build_profile='dependency-build')
        try:
            for phase in ['prepare', 'pcre-configure', 'pcre-build', 'glib-configure',
                          'glib-build', 'upstream-build', 'upstream-test', 'package']:
                result = runner.run(['python3', '/src/container/build-foundation.py', phase, profile],
                                    timeout=580, label=profile + '-' + phase)
                print(json.dumps({'profile': profile, 'phase': phase, 'exit_code': result['exit_code'],
                                  'failure': result['failure'], 'evidence_path': result['evidence_path']}), flush=True)
                if not passed(result):
                    retain_failure(runner, result, directory)
                    raise GateError('dependency phase failed: ' + profile + '/' + phase)
            archive = runner.fetch('dependency/profile-' + profile + '.tar.gz',
                                   directory / ('profile-' + profile + '.tar.gz'))
            for name in recipe.UPSTREAM_TESTS:
                runner.fetch('dependency/upstream-' + profile + '-' + name + '-testlog.json',
                             directory / ('upstream-' + name + '.json'))
            rows.append({'profile': profile, 'archive': str(archive),
                         'sha256': file_hash(archive), 'status': 'PASS'})
            print(json.dumps({'profile': profile, 'status': 'PASS', 'archive_path': str(archive)}), flush=True)
            (output / 'summary.json').write_text(json.dumps({'profiles': rows,
                'all_complete': len(rows) == len(profiles), 'required': profiles}, indent=2) + '\n')
        finally:
            runner.close()
            shutil.rmtree(runner.scratch)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(1)
