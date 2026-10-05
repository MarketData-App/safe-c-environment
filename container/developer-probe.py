"""Early fixed own-child debugger experiment, executed only inside Docker.

This prerequisite observation is not the complete E08/E10 qualification suite.
All native debugger output stays in bounded opaque artifacts.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    work = Path('/work/developer-probe')
    work.mkdir()
    binary = Path('/work/developer-build/foundation_recipes')
    source = Path('/src/foundation/src/sc-foundation.c')
    if not binary.is_file() or not source.is_file():
        raise ValueError('matching debug recipe inputs unavailable')
    configured = [
        'set auto-load off', 'set auto-load safe-path /nonexistent',
        'set debuginfod enabled off', 'set startup-with-shell off',
        'set may-call-functions off', 'set disable-randomization off',
        'set libthread-db-search-path /usr/lib/x86_64-linux-gnu',
        'set pagination off', 'set confirm off',
    ]
    argv = ['/usr/bin/gdb', '-nx', '-q', '--batch']
    for command in configured:
        argv += ['-iex', command]
    commands = [
        'show auto-load python-scripts', 'show auto-load gdb-scripts',
        'show debuginfod enabled', 'show startup-with-shell',
        'show may-call-functions', 'show disable-randomization',
        'break sc_text_new', 'run', 'print maximum', 'next',
        'info line', 'continue',
    ]
    for command in commands:
        argv += ['-ex', command]
    argv += ['--args', str(binary)]
    log = work / 'gdb.opaque.log'
    with log.open('wb') as output:
        process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT,
                                   cwd=work, start_new_session=True)
        timed_out = False
        try:
            code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=5)
    if log.stat().st_size > 4194304:
        raise ValueError('debugger prerequisite output bound exceeded')
    text = log.read_text(errors='replace')
    stop = re.search(r'Breakpoint 1, sc_text_new \(maximum=(\d+),[^\n]*\) at ([^\n]+):(\d+)', text)
    observed = re.search(r'\$1 = (\d+)\b', text)
    line = re.search(r'Line (\d+) of "([^"]+)" starts at address', text)
    resolved = bool(re.search(r'Breakpoint 1 at 0x[0-9a-f]+: file /src/foundation/src/sc-foundation.c, line \d+', text))
    normal_exit = '[Inferior ' in text and 'exited normally]' in text
    denied = any(marker in text for marker in ['Operation not permitted', 'ptrace: Permission denied'])
    step_ok = bool(stop and line and line[2] == str(source) and int(line[1]) > int(stop[3]))
    inspected = bool(resolved and stop and observed and int(stop[1]) == 16 and
                     int(observed[1]) == 16 and step_ok and not timed_out and code == 0)
    tools = {}
    for name, path in [('gdb', Path('/usr/bin/gdb')),
                       ('clangd', Path('/usr/lib/llvm-19/bin/clangd'))]:
        result = subprocess.run([str(path), '--version'], capture_output=True,
                                timeout=5, text=True)
        tools[name] = {'path': str(path), 'sha256': digest(path),
                       'version': result.stdout.splitlines()[0][:160] if result.stdout else None,
                       'version_exit_code': result.returncode}
    database = Path('/work/developer-build/compile_commands.json')
    rows = json.loads(database.read_text())
    recipe_rows = [r for r in rows if r['file'] == '/src/foundation/tests/recipes.c']
    if len(recipe_rows) != 1 or '/opt/foundation/clang-O0/' not in recipe_rows[0].get('command', ''):
        raise ValueError('real CMake recipe compilation context unavailable')
    clangd_log = work / 'clangd-check.opaque.log'
    with clangd_log.open('wb') as output:
        checked = subprocess.run(['/usr/lib/llvm-19/bin/clangd',
                                  '--check=/src/foundation/tests/recipes.c',
                                  '--compile-commands-dir=/work/developer-build',
                                  '--enable-config=false', '--log=error'],
                                 stdout=output, stderr=subprocess.STDOUT, timeout=15)
    clangd_context = checked.returncode == 0 and clangd_log.stat().st_size <= 4194304
    lock = json.loads(Path('/src/toolchain.lock.json').read_text())
    unchanged = all(digest(Path(row['path'])) == row['sha256'] for row in lock['tools'].values())
    foundation = json.loads(Path('/src/foundation.lock.json').read_text())
    sdk_checks = 0
    sdk_unchanged = True
    for profile, record in foundation['profiles'].items():
        for relative, expected in record['files'].items():
            sdk_checks += 1
            sdk_unchanged &= digest(Path('/opt/foundation') / profile / relative) == expected
    row = {'status': 'PREREQUISITE_VALIDATED' if inspected and normal_exit and unchanged and sdk_unchanged and clangd_context else 'BLOCKED',
           'evidence_scope': 'early fixed own-child probe; E suite not yet qualified',
           'debug_session_status': 'COMPLETED' if code == 0 and not timed_out else 'FAILED',
           'inspection_requirements_met': inspected,
           'inferior_outcome': 'EXITED_ZERO' if normal_exit else 'NOT_ESTABLISHED',
           'tracing_denied': denied, 'timed_out': timed_out, 'gdb_exit_code': code,
           'breakpoint_resolved': resolved,
           'observed_maximum': int(observed[1]) if observed else None,
           'breakpoint_location': {'file': stop[2], 'line': int(stop[3])} if stop else None,
           'step_location': {'file': line[2], 'line': int(line[1])} if line else None,
           'startup_commands': configured, 'commands': commands, 'tools': tools,
           'base_tool_files_unchanged': unchanged, 'sdk_files_checked': sdk_checks,
           'sdk_files_unchanged': sdk_unchanged,
           'clangd_real_context_check': clangd_context,
           'clangd_check_exit_code': checked.returncode,
           'compile_commands_sha256': digest(database),
           'compilation_context': recipe_rows[0],
           'source_sha256': digest(source), 'binary_sha256': digest(binary),
           'log_path': str(log), 'complete_capture': not timed_out}
    (work / 'summary.json').write_text(json.dumps(row, indent=2) + '\n')
    print(json.dumps({k: row[k] for k in ['status', 'inspection_requirements_met',
                      'inferior_outcome', 'tracing_denied', 'observed_maximum',
                      'base_tool_files_unchanged', 'sdk_files_checked', 'sdk_files_unchanged',
                      'clangd_real_context_check']}))
    return 0 if row['status'] == 'PREREQUISITE_VALIDATED' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(error).__name__}))
        raise SystemExit(1)
