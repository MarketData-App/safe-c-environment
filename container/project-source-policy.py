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
- build-macros: project code and project macro bodies name no macro whose
  definition differs between configurations (`-dM -E` of the unit with its
  headers; object-like macros expanded, numbers compared by value, and a macro
  that names a differing macro differs too);
- preprocess: every unit preprocesses in every configuration.

System macros may expand differently per compiler (NULL, INT_MAX, DBL_MAX); the
identity check therefore compares the project's own unexpanded tokens, and the
build-macros check covers values that differ by build.

Memory: the runs of one unit (every configuration) are folded into small result
rows as soon as they finish, and at most UNITS_IN_FLIGHT units have runs alive,
so peak memory depends on the largest units, not on the number of units.

Usage: project-source-policy.py PLAN_JSON
PLAN_JSON: {"project_root": "/src/...", "units": ["/src/..."],
            "configs": [{"name", "database"} | {"name", "argv", "gnu_source_probe"?}]}
"""
import collections
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
UNITS_IN_FLIGHT = 2
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


def run_one(job):
    index, name, unit, argv, cwd, source, replacement, prefixes = job
    depfile = WORK/f'{index:04d}.d'
    full, error = _run(ps.preprocess_argv(argv, ps.dependency_pass(str(depfile)), source, replacement), cwd,
                       WORK/f'{index:04d}-full.log')
    if error is None and not depfile.is_file():
        error = 'no dependency file'
    if error is None:
        bare, error = _run(ps.preprocess_argv(argv, ps.DIRECTIVES_PASS, source, replacement), cwd,
                           WORK/f'{index:04d}-directives.log')
    if error is None:
        defined, error = _run(ps.preprocess_argv(argv, ps.MACROS_PASS, source, replacement), cwd,
                              WORK/f'{index:04d}-macros.log')
    if error is not None:
        return {'config': name, 'unit': unit, 'error': error, 'log': str(WORK/f'{index:04d}-*.log')}
    dependencies = [posixpath.normpath(d if d.startswith('/') else posixpath.join(cwd, d))
                    for d in ps.parse_depfile(depfile.read_text(errors='replace'))]
    scan = ps.scan_preprocessed(full, unit, prefixes, dependencies)
    _code, found = ps.split_origin(scan['lines'])
    code, _bare_directives = ps.split_origin(ps.scan_preprocessed(bare, unit, prefixes)['lines'])
    return {'config': name, 'unit': unit, 'dependencies': dependencies, 'markers': scan['markers'],
            'directives': [(f, l, n) for f, l, n, _r in found if n not in ps.MACRO_DIRECTIVES],
            'defines': ps.define_stream(found), 'stream': code, 'found': found, 'macros': ps.parse_macros(defined)}


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


class Accumulator:
    """The policy result, folded one unit at a time (bounded memory).

    fold() takes the runs of one unit, computes that unit's facts (pragmas,
    markers, errors, dependencies, differing macros, build-macro uses, first
    code and defines differences) and keeps only those small rows; the unit's
    token streams, directives and macro tables are not kept. Units are folded
    in plan order. Each run carries its position in configuration-major run
    order (for each configuration, for each unit), so the result rows keep the
    order of an evaluation over all runs at once (P2-B2-SRCPOL-MEM-01)."""

    def __init__(self, plan):
        self.names = [c['name'] for c in plan['configs']]
        self.units = list(plan['units'])
        self.runs = 0
        self.covered = set()
        self.errors = []
        self.pragmas, self.markers, self.uses, self.dependencies = {}, {}, {}, {}
        self.differences = []
        self.differing_count = 0

    @staticmethod
    def _seen(rows, key, order, config, row):
        entry = rows.get(key)
        if entry is None:
            rows[key] = [order, row, {config: order}]
            return
        entry[0] = min(entry[0], order)
        entry[2][config] = min(entry[2].get(config, order), order)

    def fold(self, unit, runs):
        """Fold one unit's runs: [(position, run)] in ascending position (configuration order)."""
        tables, scanned, code, defines = [], [], [], []
        for position, run in runs:
            if run['unit'] != unit:
                raise ValueError('run_of_another_unit')
            self.runs += 1
            self.covered.add((run['config'], run['unit']))
            if 'error' in run:
                self.errors.append((position, {'unit': _rel(unit), 'config': run['config'], 'error': run['error'],
                                               'log': run['log']}))
                continue
            for k, (file, line, name) in enumerate(run['directives']):
                self._seen(self.pragmas, (file, line, name), (position, k), run['config'],
                           {'file': _rel(file), 'line': line, 'directive': name or '#'})
            for k, (file, line, problem) in enumerate(run['markers']):
                self._seen(self.markers, (file, line, problem), (position, k), run['config'],
                           {'file': _rel(file), 'line': line, 'problem': problem})
            tables.append(run['macros'])
            scanned.append((run['config'], run['stream'], run['found']))
            self.dependencies.setdefault(_rel(unit), set()).update(run['dependencies'])
            code.append((run['config'], run['stream']))
            defines.append((run['config'], run.get('defines', [])))
        differing = ps.differing_macros(tables) if tables else set()
        self.differing_count = max(self.differing_count, len(differing))
        for config, stream, directives_found in scanned:
            for file, line, name in ps.build_macro_uses(stream, directives_found, differing):
                _add(self.uses, (file, line, name), {'file': _rel(file), 'line': line, 'macro': name, 'configs': [config]})
        for kind, streams in (('code', code), ('defines', defines)):
            found = ps.first_difference(streams)
            if found is not None:
                self.differences.append(_difference(unit, kind, found))

    @staticmethod
    def _rows(rows):
        return [dict(row, configs=[c for c, _o in sorted(configs.items(), key=lambda item: item[1])])
                for _order, row, configs in sorted(rows.values(), key=lambda entry: entry[0])]

    def result(self):
        errors = [row for _position, row in sorted(self.errors, key=lambda entry: entry[0])]
        for name in self.names:
            for unit in self.units:
                if (name, unit) not in self.covered:
                    errors.append({'unit': _rel(unit), 'config': name, 'error': 'no compile command'})
        pragmas, markers = self._rows(self.pragmas), self._rows(self.markers)
        uses, differences = list(self.uses.values()), self.differences
        failed = [check for check, rows in (('preprocess', errors), ('pragmas', pragmas), ('markers', markers),
                                             ('identity', differences), ('build-macros', uses)) if rows]
        return {'status': 'FAIL' if failed else 'PASS', 'failed_checks': failed, 'configurations': list(self.names),
                'units': [_rel(u) for u in self.units], 'runs': self.runs,
                'preprocess_errors': errors[:LIMIT], 'pragmas': pragmas[:LIMIT],
                'markers': markers[:LIMIT], 'differences': differences[:LIMIT],
                'build_macros': uses[:LIMIT], 'differing_macros': self.differing_count,
                'dependencies': {unit: sorted(paths) for unit, paths in sorted(self.dependencies.items())}}


def wire(result):
    """The printed form of a result: the per-unit dependencies as indexes into one
    sorted table of distinct paths (`dependency_paths`), so that the line stays under
    the protected capture record limit (safety/container-policy.json
    common.capture_record_bytes) when many units share headers. Lossless: the host
    (project_check.source_policy_dependencies) decodes the same {unit: [paths]}."""
    paths = sorted({path for unit_paths in result['dependencies'].values() for path in unit_paths})
    index = {path: k for k, path in enumerate(paths)}
    return dict(result, dependency_paths=paths,
                dependencies={unit: [index[path] for path in unit_paths]
                              for unit, unit_paths in result['dependencies'].items()})


def evaluate(plan, runs):
    """The policy result from the per-run scans (pure; runs in configuration order).

    Build macros: per unit, the macros whose definitions differ between the
    configurations (`-dM -E` of that unit) may not be named by project code or a
    project macro body. The runs are folded one unit at a time (Accumulator)."""
    accumulator = Accumulator(plan)
    known = set(plan['units'])
    if any(run['unit'] not in known for run in runs):
        raise ValueError('run_of_unknown_unit')
    for unit in plan['units']:
        accumulator.fold(unit, [(position, run) for position, run in enumerate(runs) if run['unit'] == unit])
    return accumulator.result()


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
    if len(set(plan['units'])) != len(plan['units']):
        raise ValueError('unique_units_required')
    WORK.mkdir(parents=True, exist_ok=True)
    prefixes = ps.origin_prefixes(root)
    jobs, index = {unit: [] for unit in plan['units']}, 0
    for name, table in commands(plan):
        for unit in plan['units']:
            if unit in table:
                jobs[unit].append((index, name, unit, *table[unit], prefixes))
                index += 1
    # Memory bound: at most UNITS_IN_FLIGHT units have runs alive (submitted,
    # finished or being folded); a unit's runs are dropped once it is folded.
    accumulator = Accumulator(plan)
    order = iter(plan['units'])
    pending = collections.deque()
    with ThreadPoolExecutor(max_workers=2) as pool:
        def submit():
            unit = next(order, None)
            if unit is not None:
                pending.append((unit, [(job[0], pool.submit(run_one, job)) for job in jobs.pop(unit)]))
        for _ in range(UNITS_IN_FLIGHT):
            submit()
        while pending:
            unit, futures = pending.popleft()
            accumulator.fold(unit, [(position, future.result()) for position, future in futures])
            del futures
            submit()
    result = accumulator.result()
    line = json.dumps(wire(result), sort_keys=True)
    (WORK/'result.json').write_text(line)
    print(line)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(error).__name__}))
        raise SystemExit(2)
