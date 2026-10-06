"""Framework self-test of the 23 project gates.

Each gate has one seeded-defect fixture under safety/project-gate-fixtures/<gate>/.
The self-test applies a fixture to a scratch copy of the framework tree (the
example project inside it), runs the ordinary project check in development mode
and requires that the run fails exactly at the fixture's gate: that gate is the
only FAIL, it is where the run stopped, and every other gate is PASS (run before
it) or BLOCKED (not run after it). The unmodified example must pass every gate.

Fixture sources are seeded defects: this module never prints them or any tool
output. The console gets one line per fixture; reports stay on disk.
"""
from __future__ import annotations
import argparse
import contextlib
import copy
import json
import shutil
import tempfile
import uuid
from pathlib import Path
import policy
import project_check as pc
import project_model as pm
from evidence import GateError, atomic_json, file_hash, read_json
from schema_check import validate

FIXTURES = 'safety/project-gate-fixtures'
MANIFEST = FIXTURES+'/manifest.json'
FIXTURE_FILE = 'fixture.json'
SCHEMA = 'project-gate-fixtures'
CLEAN_VERDICTS = {'PASS', 'PASS_UNQUALIFIED_FRAMEWORK'}
SELFTEST_ARTIFACTS = 'artifacts/project-selftest'


# ---------------------------------------------------------------- manifest

def _plain(rel, what):
    """A plain relative path: no absolute, empty, '.', '..' or backslash parts."""
    try:
        return pm._safe_path(rel, what)
    except GateError as exc:
        raise GateError('project gate fixture path is not plain: '+str(rel)[:200]) from exc


def fixture_files(root):
    """Every file below the fixture directory except the manifest, as {relative path: sha256}."""
    base = Path(root)/FIXTURES
    if base.is_symlink() or not base.is_dir():
        raise GateError('project gate fixture directory is missing: '+FIXTURES)
    result = {}
    for path in sorted(base.rglob('*')):
        rel = str(path.relative_to(base))
        if path.is_symlink():
            raise GateError('symlink input is forbidden: '+FIXTURES+'/'+rel)
        if path.is_file() and rel != 'manifest.json':
            result[rel] = file_hash(path)
    return result


def load_manifest(root):
    """Validate the hash-pinned fixture set; return (manifest, {gate: fixture}).

    The manifest lists exactly the 23 project gates in policy order and the
    sha256 of every fixture file; each gate directory holds one fixture.json
    whose operations reference only files of that directory."""
    root = Path(root)
    path = root/MANIFEST
    if path.is_symlink() or not path.is_file():
        raise GateError('project gate fixture manifest is missing: '+MANIFEST)
    manifest = read_json(path)
    validate(root, SCHEMA, manifest)
    if manifest['kind'] != 'manifest':
        raise GateError('project gate fixture manifest has the wrong kind')
    if list(manifest['gates']) != list(pc.GATES):
        raise GateError('project gate fixtures do not cover exactly the 23 project gates in policy order')
    _plain(manifest['base'], 'base')
    actual = fixture_files(root)
    expected = manifest['files']
    for rel in sorted(set(actual) | set(expected)):
        if rel not in expected:
            raise GateError('unlisted project gate fixture file: '+rel)
        if rel not in actual:
            raise GateError('project gate fixture file is missing: '+rel)
        if actual[rel] != expected[rel]:
            raise GateError('project gate fixture hash mismatch: '+rel)
    gate_dirs = {rel.split('/', 1)[0] for rel in actual}
    if gate_dirs != set(pc.GATES):
        raise GateError('project gate fixture directories differ from the gate list: '
                        + ', '.join(sorted(gate_dirs ^ set(pc.GATES))))
    fixtures = {}
    for gate in pc.GATES:
        rel = gate+'/'+FIXTURE_FILE
        if rel not in actual:
            raise GateError('project gate fixture is missing: '+rel)
        fixture = read_json(root/FIXTURES/rel)
        validate(root, SCHEMA, fixture)
        if fixture['kind'] != 'fixture' or fixture['gate'] != gate:
            raise GateError('project gate fixture names another gate: '+rel)
        used = {rel}
        for operation in fixture['operations']:
            _plain(operation['path'], 'path')
            if 'source' in operation:
                source = gate+'/'+_plain(operation['source'], 'source')
                if source not in actual:
                    raise GateError('project gate fixture source is not a pinned file: '+source)
                used.add(source)
        stray = sorted(r for r in actual if r.startswith(gate+'/') and r not in used)
        if stray:
            raise GateError('project gate fixture file is not used by its fixture: '+stray[0])
        fixtures[gate] = fixture
    return manifest, fixtures


# ---------------------------------------------------------------- application

def _pointer(document, pointer):
    """Parent container and final key of a JSON pointer such as /modules/0/tests."""
    if not pointer.startswith('/'):
        raise GateError('project gate fixture JSON pointer must start with /')
    parts = [p.replace('~1', '/').replace('~0', '~') for p in pointer[1:].split('/')]
    node = document
    for part in parts[:-1]:
        node = _step(node, part, pointer)
    return node, parts[-1]


def _step(node, part, pointer):
    if isinstance(node, list):
        if not part.isdigit() or int(part) >= len(node):
            raise GateError('project gate fixture JSON pointer does not resolve: '+pointer)
        return node[int(part)]
    if isinstance(node, dict) and part in node:
        return node[part]
    raise GateError('project gate fixture JSON pointer does not resolve: '+pointer)


def apply_fixture(fixture_dir, fixture, project):
    """Apply a fixture's operations to the scratch project directory `project`."""
    fixture_dir, project = Path(fixture_dir), Path(project)
    for operation in fixture['operations']:
        op = operation['op']
        target = project/_plain(operation['path'], 'path')
        if any(p.is_symlink() for p in [target, *target.parents] if p == project or project in p.parents):
            raise GateError('symlink input is forbidden: '+operation['path'])
        if op == 'add':
            if target.exists():
                raise GateError('project gate fixture adds an existing file: '+operation['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_dir/_plain(operation['source'], 'source'), target)
            continue
        if not target.is_file():
            raise GateError('project gate fixture changes a missing file: '+operation['path'])
        if op == 'replace':
            shutil.copyfile(fixture_dir/_plain(operation['source'], 'source'), target)
        elif op == 'delete':
            target.unlink()
        elif op in ('json_set', 'json_append'):
            document = json.loads(target.read_text())
            parent, key = _pointer(document, operation['pointer'])
            if op == 'json_append':
                values = _step(parent, key, operation['pointer'])
                if not isinstance(values, list):
                    raise GateError('project gate fixture json_append target is not an array: '+operation['pointer'])
                values.append(copy.deepcopy(operation['value']))
            elif isinstance(parent, dict) and key in parent:
                parent[key] = copy.deepcopy(operation['value'])
            elif isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
                parent[int(key)] = copy.deepcopy(operation['value'])
            else:
                raise GateError('project gate fixture JSON pointer does not resolve: '+operation['pointer'])
            target.write_text(json.dumps(document, indent=2)+'\n')
        else:
            raise GateError('unknown project gate fixture operation: '+str(op))


def scratch_framework(root, destination, base):
    """Copy the framework source tree (policy.source_files) to `destination`.

    Returns the scratch project directory (destination/base). Earlier
    self-test and project-run artifacts are never copied."""
    root, destination = Path(root), Path(destination)
    for rel in policy.source_files(root):
        target = destination/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/rel, target)
    for directory in ('src', 'include'):
        (destination/directory).mkdir(exist_ok=True)
    # Empty example directories (none today) are not source files; the base must exist.
    project = destination/base
    if not (project/pm.PROJECT_FILE).is_file():
        raise GateError('scratch framework copy has no example project: '+base)
    return project


# ---------------------------------------------------------------- evaluation

def evaluate_clean(report):
    """The unmodified example passes every one of the 23 gates."""
    rows = {row['name']: row['status'] for row in report.get('gates', [])}
    bad = [name for name in pc.GATES if rows.get(name) != 'PASS']
    ok = report.get('verdict') in CLEAN_VERDICTS and not bad and not report.get('blockers')
    failed = [name for name in bad if rows.get(name) == 'FAIL']
    # A gate or runtime failure is FAIL; anything else that is not a pass (infrastructure,
    # container cleanup blockers) is BLOCKED.
    status = 'PASS' if ok else 'FAIL' if failed or report.get('verdict') == 'FAIL' else 'BLOCKED'
    result = {'status': status, 'verdict': report.get('verdict'), 'stopped_after': report.get('stopped_after')}
    if not ok:
        result['not_passed'] = bad
        result['blockers'] = list(report.get('blockers', []))[:5]
    return result


def evaluate_fixture(gate, report):
    """PASS when `gate` is the first and only FAIL of the run.

    Gates decided before it (pc.EXECUTION_ORDER) PASS; gates after it are BLOCKED as not run
    because it failed. A run blocked by infrastructure is BLOCKED; any other
    outcome (no failure, another gate failed, two gates failed) is FAIL."""
    rows = {row['name']: row for row in report.get('gates', [])}
    failed = [name for name in pc.GATES if rows.get(name, {}).get('status') == 'FAIL']
    first = report.get('stopped_after')
    result = {'gate': gate, 'status': 'FAIL', 'first_fail': first, 'verdict': report.get('verdict'), 'failed': failed}
    if report.get('blockers') or (report.get('verdict') == 'BLOCKED' and not failed):
        result.update(status='BLOCKED', reason='the run was blocked before a gate decision',
                      blockers=list(report.get('blockers', []))[:5])
        return result
    not_run = 'not run: gate '+str(gate)+' failed'
    # Gates decided before the target in execution order must PASS. A test failure
    # decides `unit` or `integration` right after its test build: the remaining test
    # builds (and the other test label) then do not run.
    exempt = set(pc.TEST_BUILDS) | {'unit'} if gate in ('unit', 'integration') else set()
    earlier = pc.EXECUTION_ORDER[:pc.EXECUTION_ORDER.index(gate)] if gate in pc.EXECUTION_ORDER else ()
    not_passed_earlier = [name for name in earlier if name not in exempt and rows.get(name, {}).get('status') != 'PASS']
    unexpected = [name for name in pc.GATES if name != gate and not (
        rows.get(name, {}).get('status') == 'PASS' or
        (rows.get(name, {}).get('status') == 'BLOCKED' and rows[name].get('details', {}).get('reason') == not_run))]
    if report.get('verdict') != 'FAIL' or failed != [gate] or first != gate:
        result['reason'] = 'the seeded defect did not fail exactly its target gate'
    elif not_passed_earlier and all(rows.get(name, {}).get('status') == 'BLOCKED' and
                                    rows[name].get('details', {}).get('reason') == not_run for name in not_passed_earlier):
        result['reason'] = 'gates that run before the target did not run'
        result['not_passed_earlier'] = not_passed_earlier
    elif unexpected and all(rows.get(name, {}).get('status') == 'BLOCKED' for name in unexpected):
        result.update(status='BLOCKED', reason='gates other than the target were blocked by infrastructure',
                      unexpected=unexpected)
    elif unexpected:
        result['reason'] = 'gates other than the target are neither PASS nor BLOCKED as not run'
        result['unexpected'] = unexpected
    else:
        result['status'] = 'PASS'
    return result


def aggregate(clean, fixtures, *, complete=True):
    """The `project-gates` gate row. Only a complete run over all 23 fixtures can PASS."""
    statuses = [clean['status']] + [f['status'] for f in fixtures]
    status = 'FAIL' if 'FAIL' in statuses else 'BLOCKED' if any(s != 'PASS' for s in statuses) else 'PASS'
    details = {'clean': clean, 'fixtures': fixtures}
    if status == 'PASS' and (not complete or [f['gate'] for f in fixtures] != list(pc.GATES)):
        status = 'BLOCKED' if not complete else 'FAIL'
        details['reason'] = 'partial self-test: only selected fixtures ran' if not complete else 'fixture results do not cover the 23 gates'
    return pc.gate_row('project-gates', status, details)


# ---------------------------------------------------------------- runner

def _save(root, run, name, report, evidence_from=None):
    """Keep the report and the evidence of the decisive gate; the scratch tree is deleted."""
    directory = Path(root)/SELFTEST_ARTIFACTS/run/name
    kept = []
    for index, source in enumerate(evidence_from or []):
        path = Path(source)
        if path.is_file() and not path.is_symlink():
            target = directory/'evidence'/f'{index:03d}-{path.name}'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            kept.append(str(target))
    atomic_json(directory/'project-report.json', dict(report, selftest_kept_evidence=kept))
    return directory


def _one_run(root, base, run, name, fixture, runner):
    scratch = Path(tempfile.mkdtemp(prefix='safe-c-project-selftest-'))
    try:
        project = scratch_framework(root, scratch/'framework', base)
        if fixture is not None:
            apply_fixture(Path(root)/FIXTURES/fixture['gate'], fixture, project)
        log = Path(root)/SELFTEST_ARTIFACTS/run/name/'console.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('w') as stream, contextlib.redirect_stdout(stream):
            report = runner(scratch/'framework', base, development=True)
        decisive = report.get('stopped_after') or ''
        evidence = next((r['evidence_paths'] for r in report.get('gates', []) if r['name'] == decisive), [])
        directory = _save(root, run, name, report, evidence)
        return report, str(directory)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def project_selftest(framework_root, *, gates=None, runner=None):
    """Run the clean example and every gate fixture; return the `project-gates` gate row."""
    root = Path(framework_root).resolve()
    runner = runner or pc.run_project_check
    run = uuid.uuid4().hex
    try:
        manifest, fixtures = load_manifest(root)
    except (GateError, ValueError, OSError) as exc:
        reason = str(exc)[:300] if isinstance(exc, GateError) else type(exc).__name__
        return pc.gate_row('project-gates', 'FAIL', {'reason': 'fixture manifest: '+reason, 'clean': {'status': 'BLOCKED'},
                                                      'fixtures': []})
    selected = list(pc.GATES) if gates is None else [g for g in pc.GATES if g in set(gates)]
    base = manifest['base']
    try:
        report, directory = _one_run(root, base, run, 'clean', None, runner)
        clean = dict(evaluate_clean(report), report=directory)
    except (GateError, OSError, ValueError) as exc:
        clean = {'status': 'BLOCKED', 'verdict': None, 'reason': str(exc)[:300] if isinstance(exc, GateError) else type(exc).__name__}
    print(f'project selftest clean example: {clean["status"]} ({clean["verdict"]})', flush=True)
    results = []
    for gate in selected:
        if clean['status'] != 'PASS':
            results.append({'gate': gate, 'status': 'BLOCKED', 'first_fail': None, 'verdict': None,
                            'reason': 'not run: the clean example did not pass every gate'})
            continue
        try:
            report, directory = _one_run(root, base, run, gate, fixtures[gate], runner)
            row = dict(evaluate_fixture(gate, report), report=directory)
        except (GateError, OSError, ValueError) as exc:
            row = {'gate': gate, 'status': 'BLOCKED', 'first_fail': None, 'verdict': None,
                   'reason': str(exc)[:300] if isinstance(exc, GateError) else type(exc).__name__}
        print(f'project selftest fixture {gate}: {row["status"]} (first fail: {row["first_fail"]})', flush=True)
        results.append(row)
    row = aggregate(clean, results, complete=gates is None)
    row['details']['run'] = run
    summary = root/SELFTEST_ARTIFACTS/run/'project-gates.json'
    row['evidence_paths'] = [str(summary)]
    atomic_json(summary, row)
    print(f'project selftest: {row["status"]}', flush=True)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(prog='project_selftest')
    parser.add_argument('--gate', action='append', choices=pc.GATES,
                        help='run only these fixtures (diagnostic; the row is never PASS)')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    row = project_selftest(root, gates=args.gate)
    return 0 if row['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
