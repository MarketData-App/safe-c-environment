"""Compiler-based project source policy, part of the project `ast` gate.

Runs inside the protected project container after every gate build. For every
project translation unit and every build configuration the gates use, it runs
the configuration's real compiler with its real flags as `-E -MD` and checks:

- pragmas: no #pragma (or other directive except #define/#undef) survives the
  full `-E -dD` pass in a project-origin line (linemarkers attribute lines to
  files; _Pragma appears as #pragma; #pragma once is consumed);
- markers: no project file is marked as a system header, renamed by #line, or
  entered without being a compiler dependency;
- identity: the project-origin code of the `-E -fdirectives-only` pass (the
  project's own tokens after conditional inclusion, no macro expanded) and the
  project's #define/#undef lines are the same in every configuration;
- build-macros: project code and project macro definitions name no predefined
  or command-line macro whose definition differs between configurations (from
  `-dM -E` of each configuration);
- preprocess: every unit preprocesses in every configuration.

System macros may expand differently per compiler (NULL, INT_MAX, DBL_MAX); the
identity check therefore compares the project's own unexpanded tokens, and the
build-macros check covers values that differ by build.

Usage: project-source-policy.py PLAN_JSON
PLAN_JSON: {"project_root": "/src/...", "units": ["/src/..."],
            "configs": [{"name", "database"} | {"name", "argv", "gnu_source_probe"?}]}
"""
import json
import posixpath
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, '/src/tools')
import project_source as ps

WORK = Path('/work/project/source-policy')
LIMIT = 20
SECONDS = 120
_GNU_SOURCE = re.compile(r'^\s*#\s*define\s+_GNU_SOURCE\s*$', re.M)


def _rel(path):
    return path[len('/src/'):] if isinstance(path, str) and path.startswith('/src/') else path


def _database(path):
    entries = {}
    for row in json.loads(Path(path).read_text()):
        argv = row.get('arguments') or shlex.split(row['command'])
        directory = row.get('directory', '/')
        source = row['file'] if row['file'].startswith('/') else posixpath.join(directory, row['file'])
        entries.setdefault(posixpath.normpath(source), (argv, directory, row['file']))
    return entries


def commands(plan):
    """[(config name, {unit: (argv, cwd, source, replacement)})] with the exact flags of each configuration.

    A unit missing from a build's compilation database (a fuzz harness) uses the
    command of the first project unit that is in it, with only the file replaced:
    every project target of one build gets the same flags (cmake/Project.cmake)."""
    result = []
    for config in plan['configs']:
        table = {}
        if 'database' in config:
            entries = _database(config['database'])
            fallback = next((entries[u] for u in plan['units'] if u in entries), None)
            for unit in plan['units']:
                if unit in entries:
                    argv, cwd, source = entries[unit]
                    table[unit] = (argv, cwd, source, None)
                elif fallback is not None:
                    argv, cwd, source = fallback
                    table[unit] = (argv, cwd, source, unit)
        else:
            for unit in plan['units']:
                argv = list(config['argv'])
                if config.get('gnu_source_probe'):
                    # The AST scan adds this definition for such a unit (container/foundation-policy.py).
                    leading = Path(unit).read_text(errors='replace').split('#include', 1)[0]
                    if _GNU_SOURCE.search(leading):
                        argv.append('-D_GNU_SOURCE=')
                table[unit] = (argv + [unit], str(WORK), unit, None)
        result.append((config['name'], table))
    return result


def _run(command, cwd, log):
    with log.open('wb') as errors:
        try:
            done = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=errors, timeout=SECONDS)
        except subprocess.TimeoutExpired:
            return None, 'timeout'
    if done.returncode != 0:
        return None, 'exit '+str(done.returncode)
    return done.stdout.decode('utf-8', 'replace'), None


def predefined(job):
    """Predefined and command-line macros of one configuration."""
    index, name, argv, cwd, source = job
    text, error = _run(ps.predefined_argv(argv, source), cwd, WORK/f'macros-{index:02d}.log')
    return name, (None if error else ps.parse_macros(text)), error


def run_one(job):
    index, name, unit, argv, cwd, source, replacement, prefixes, build_macros = job
    depfile = WORK/f'{index:04d}.d'
    full, error = _run(ps.preprocess_argv(argv, ps.dependency_pass(str(depfile)), source, replacement), cwd,
                       WORK/f'{index:04d}-full.log')
    if error is None and not depfile.is_file():
        error = 'no dependency file'
    if error is None:
        bare, error = _run(ps.preprocess_argv(argv, ps.DIRECTIVES_PASS, source, replacement), cwd,
                           WORK/f'{index:04d}-directives.log')
    if error is not None:
        return {'config': name, 'unit': unit, 'error': error, 'log': str(WORK/f'{index:04d}-*.log')}
    dependencies = [posixpath.normpath(d if d.startswith('/') else posixpath.join(cwd, d))
                    for d in ps.parse_depfile(depfile.read_text(errors='replace'))]
    scan = ps.scan_preprocessed(full, unit, prefixes, dependencies)
    _code, found = ps.split_origin(scan['lines'])
    code, _bare_directives = ps.split_origin(ps.scan_preprocessed(bare, unit, prefixes)['lines'])
    return {'config': name, 'unit': unit, 'dependencies': dependencies, 'markers': scan['markers'],
            'directives': [(f, l, n) for f, l, n, _r in found if n not in ps.MACRO_DIRECTIVES],
            'defines': ps.define_stream(found), 'stream': code,
            'macro_uses': ps.build_macro_uses(code, found, build_macros)}


def _add(rows, key, row):
    if key in rows:
        if row['configs'][0] not in rows[key]['configs']:
            rows[key]['configs'].append(row['configs'][0])
    else:
        rows[key] = row


def _difference(unit, kind, found):
    return {'unit': _rel(unit), 'stream': kind, 'file': _rel(found['file']), 'line': found['line'],
            'token': found['token'], 'baseline': found['baseline'], 'config': found['config'],
            'other_file': _rel(found['other_file']), 'other_line': found['other_line'],
            'other_token': found['other_token']}


def evaluate(plan, runs, macro_errors=()):
    """The policy result from the per-run scans (pure; runs in configuration order)."""
    names = [c['name'] for c in plan['configs']]
    pragmas, markers, uses, dependencies, differences = {}, {}, {}, {}, []
    errors = [dict(e) for e in macro_errors]
    code = {unit: [] for unit in plan['units']}
    defines = {unit: [] for unit in plan['units']}
    for run in runs:
        unit = run['unit']
        if 'error' in run:
            errors.append({'unit': _rel(unit), 'config': run['config'], 'error': run['error'], 'log': run['log']})
            continue
        for file, line, name in run['directives']:
            _add(pragmas, (file, line, name), {'file': _rel(file), 'line': line, 'directive': name or '#',
                                              'configs': [run['config']]})
        for file, line, problem in run['markers']:
            _add(markers, (file, line, problem), {'file': _rel(file), 'line': line, 'problem': problem,
                                                 'configs': [run['config']]})
        for file, line, name in run.get('macro_uses', []):
            _add(uses, (file, line, name), {'file': _rel(file), 'line': line, 'macro': name, 'configs': [run['config']]})
        dependencies.setdefault(_rel(unit), set()).update(run['dependencies'])
        code[unit].append((run['config'], run['stream']))
        defines[unit].append((run['config'], run.get('defines', [])))
    covered = {(r['config'], r['unit']) for r in runs}
    for name in names:
        for unit in plan['units']:
            if (name, unit) not in covered:
                errors.append({'unit': _rel(unit), 'config': name, 'error': 'no compile command'})
    for unit in plan['units']:
        for kind, streams in (('code', code[unit]), ('defines', defines[unit])):
            found = ps.first_difference(streams)
            if found is not None:
                differences.append(_difference(unit, kind, found))
    failed = [check for check, rows in (('preprocess', errors), ('pragmas', pragmas), ('markers', markers),
                                         ('identity', differences), ('build-macros', uses)) if rows]
    return {'status': 'FAIL' if failed else 'PASS', 'failed_checks': failed, 'configurations': names,
            'units': [_rel(u) for u in plan['units']], 'runs': len(runs),
            'preprocess_errors': errors[:LIMIT], 'pragmas': list(pragmas.values())[:LIMIT],
            'markers': list(markers.values())[:LIMIT], 'differences': differences[:LIMIT],
            'build_macros': list(uses.values())[:LIMIT],
            'dependencies': {unit: sorted(paths) for unit, paths in sorted(dependencies.items())}}


def main(argv):
    if len(argv) != 1:
        raise ValueError('plan_argument_required')
    plan = json.loads(argv[0])
    root = plan['project_root']
    if not root.startswith('/src') or '..' in root.split('/'):
        raise ValueError('project_root_under_src_required')
    for unit in plan['units']:
        if not unit.startswith('/src/') or '..' in unit.split('/'):
            raise ValueError('unit_under_src_required')
    WORK.mkdir(parents=True, exist_ok=True)
    prefixes = ps.origin_prefixes(root)
    tables = commands(plan)
    probes = []
    for index, (name, table) in enumerate(tables):
        first = next((table[u] for u in plan['units'] if u in table), None)
        if first is not None:
            argv, cwd, source, replacement = first
            probes.append((index, name, argv, cwd, source))
    with ThreadPoolExecutor(max_workers=2) as pool:
        macros = list(pool.map(predefined, probes))
    macro_errors = [{'unit': None, 'config': name, 'error': 'predefined macros: '+error} for name, _t, error in macros if error]
    build_macros = ps.differing_macros([t for _n, t, _e in macros if t is not None])
    jobs, index = [], 0
    for name, table in tables:
        for unit in plan['units']:
            if unit in table:
                jobs.append((index, name, unit, *table[unit], prefixes, build_macros))
                index += 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(run_one, jobs))
    result = evaluate(plan, runs, macro_errors)
    result['differing_macros'] = len(build_macros)
    (WORK/'result.json').write_text(json.dumps(result, sort_keys=True))
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(error).__name__}))
        raise SystemExit(2)
