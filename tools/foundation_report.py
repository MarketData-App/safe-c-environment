"""Compose named foundation observations; missing work is never a pass."""
from evidence import atomic_json, read_json
from foundation import (new_report, expected_binding, validate_report, doctor,
                        normal_checks, coverage, policy_checks,
                        runtime_fixture_checks, functional_mutant_checks,
                        policy_probe_checks, fuzz_checks)


def check(q, *, full=True, fuzz_profile='smoke'):
    value = new_report(q)
    value['doctor'] = doctor(q)
    value['profiles'] = normal_checks(q, full=full)
    value['policy'] = policy_checks(q)
    if full:
        value['coverage'] = coverage(q, value['profiles'])
        value['fuzz'] = fuzz_checks(q, fuzz_profile)
    return value


def experiments(q, value):
    value['runtime_pairs'] = runtime_fixture_checks(q)
    value['functional'] = functional_mutant_checks(q)
    value['policy_probes'] = policy_probe_checks(q)


def project(q, value, starter=None):
    """Each projection names the actual component and tested contract property."""
    normal = value['profiles']
    pairs = {r['id']: r for r in value.get('runtime_pairs', [])}
    mutants = {r['id']: r for r in value.get('functional', {}).get('mutants', [])}
    probes = {r['id']: r for r in value.get('policy_probes', {}).get('probes', [])}
    guards = {r['id']: r for r in value.get('functional', {}).get('guard_controls', [])}
    pipeline = {r['name']: r for r in value['sabotage']}
    spec = read_json(q.root / 'safety/foundation-fixtures.json')
    families = {r['parent']: r['name'] for r in spec['pipeline_subcases']}
    runtime = value['runtime']
    fuzz = value['fuzz']

    def observed(row, label, control=None):
        paths = row.get('evidence_paths', []) or ([row['evidence_path']] if row.get('evidence_path') else [])
        status = row.get('status', 'BLOCKED')
        ctrl = row.get('control', status) if control is None else control
        if status == 'PASS' and (not paths or ctrl != 'PASS'):
            status = 'BLOCKED'
        return {'status': status, 'control': ctrl, 'evidence_paths': paths,
                'observation': {'component': label}}

    def contract(name):
        rows = [r for r in normal if name in r.get('contract_checks', [])]
        ok = len(rows) == len(normal) and bool(rows) and all(r['status'] == 'PASS' for r in rows)
        return observed({'status': 'PASS' if ok else 'BLOCKED',
                         'evidence_paths': [r['contract_evidence_path'] for r in rows]}, name)

    def mutant(name):
        return observed(mutants.get(name, {}), 'mutant/' + name)

    def probe(name):
        return observed(probes.get(name, {}), 'policy/' + name)

    def pair(case):
        return observed(pairs.get(case, {}), 'runtime-pair/' + case)

    def sabotage(parent, variant):
        name = families[parent] + '/' + variant
        return observed(pipeline.get(name, {}), name)

    special = {}
    for case in ['F01', 'F02', 'F03', 'F17', 'F18', 'F19']:
        for sub in next(r for r in spec['cases'] if r['id'] == case)['subchecks']:
            special[(case, sub)] = lambda c=case: pair(c)
    for sub in ['early-return-zero', 'early-return-first', 'early-return-multiple', 'partial-initialization']:
        special[('F01', sub)] = lambda s=sub: contract('F01/' + s)
    for case, sub, name in [
            ('F04', 'direct-backing-field', 'direct-backing'), ('F04', 'macro-backing-field', 'macro-backing'),
            ('F08', 'direct-static-constructor', 'direct-static'), ('F08', 'macro-static-constructor', 'macro-static'),
            ('F08', 'direct-take-constructor', 'direct-take'), ('F08', 'macro-take-constructor', 'macro-take'),
            ('F15', 'ignored-annotated-result', 'ignored-result'), ('F15', 'direct-forbidden-call', 'direct-static'),
            ('F15', 'macro-forbidden-call', 'macro-static'), ('F15', 'alias-forbidden-call', 'alias-static'),
            ('F15', 'approved-call-control', 'approved'), ('F15', 'comment-only-control', 'comment-only')]:
        special[(case, sub)] = lambda n=name: probe(n)
    for case, sub, name in [
            ('F05', 'debug-guard-mutant', 'index-guard-O0'), ('F05', 'optimized-guard-mutant', 'index-guard-O2'),
            ('F06', 'missing-destroy-mutant', 'list-destroy-O2'), ('F06', 'missing-retain-mutant', 'list-retain-O2'),
            ('F07', 'contract-mutant', 'map-key-O2'), ('F09', 'region-mutant', 'empty-region-O2'),
            ('F10', 'arithmetic-mutant', 'arithmetic-publication-O2'), ('F11', 'conversion-mutant', 'signed-conversion-O2'),
            ('F12', 'validation-mutant', 'text-validation-O2'), ('F13', 'allocation-order-mutant', 'growth-order-O2'),
            ('F14', 'contradictory-result-mutant', 'pending-error-O2'), ('F16', 'assertion-only-mutant', 'assertion-only-O2')]:
        special[(case, sub)] = lambda n=name: mutant(n)
    for sub, name in [('NDEBUG', 'NDEBUG'), ('G_DISABLE_ASSERT', 'G_DISABLE_ASSERT'),
                      ('G_DISABLE_CHECKS', 'G_DISABLE_CHECKS'),
                      ('all-disabled', 'NDEBUG+G_DISABLE_ASSERT+G_DISABLE_CHECKS')]:
        special[('F16', sub)] = lambda n=name: observed(guards.get(n, {}), 'guards/' + n)
    special[('F14', 'unexpected-critical-rejection')] = lambda: sabotage('P11', 'unexpected-critical')
    for sub, variant in [('unrelated-abort-rejected', 'unrelated-fatal'), ('cgroup-oom-rejected', 'cgroup-oom'),
                         ('timeout-rejected', 'timeout'), ('ordinary-job-termination-rejected', 'ordinary-oom-as-success')]:
        special[('F19', sub)] = lambda v=variant: sabotage('P11', v)

    def runtime_observation(label, input_name=None):
        item = next((r for r in runtime.get('input_controls', []) if r['name'] == input_name), runtime)
        return observed({'status': item.get('status', 'BLOCKED'),
                         'evidence_paths': [runtime['evidence_path']] if runtime.get('evidence_path') else []}, label)

    special[('F19', 'production-hook-absent')] = lambda: runtime_observation('minimal-runtime-file-inventory')
    special[('F20', 'normal-profile-library-binding')] = lambda: observed({
        'status': 'PASS' if len(normal) == 12 and all(r['status'] == 'PASS' for r in normal) else 'BLOCKED',
        'evidence_paths': [p for r in normal for p in r['evidence_paths']]}, 'all-linked-and-loaded-profiles')
    for sub in ['stateful-fuzz-oracle', 'bad-mutant-counterexample', 'repaired-counterexample', 'clusterfuzzlite-real-adapter']:
        special[('F20', sub)] = lambda s=sub: observed(fuzz, s)
    for sub, inp in [('runtime-valid-input', 'valid'), ('runtime-invalid-input', 'invalid'), ('final-library-bytes', None)]:
        special[('F20', sub)] = lambda s=sub, i=inp: runtime_observation(s, i)
    special[('F20', 'noop-harness-rejected')] = lambda: observed(fuzz.get('noop', {}), 'actual-noop-object-audit')
    special[('F20', 'dependency-substitution-rejected')] = lambda: sabotage('P10', 'same-version-library')
    for sub in ['two-exports', 'complete-fresh-child']:
        def child_observation(s=sub):
            child = starter or {}
            ok = child.get('status') == 'PASS' and (child.get('first_child_full_qualification') == 'PASS' or
                 child.get('scope', '').startswith('project-instance;'))
            paths = child.get('evidence_paths', [])
            if not paths and child.get('scope', '').startswith('project-instance;'):
                paths = [str(q.root / 'starter-baseline.lock.json'), str(q.root / 'starter-export.json')]
            result = observed({'status': 'PASS' if ok else 'BLOCKED', 'evidence_paths': paths}, s)
            result['observation']['scope'] = ('inherited payload verified on this fresh instance; parent evaluates two exports; final instance CI decides combined acceptance'
                                             if child.get('scope', '').startswith('project-instance;') else 'two exported projects and actual complete first-child CI')
            return result
        special[('F20', sub)] = child_observation

    for row in value['cases']:
        classification = ('MISUSE_DETECTED_EXPECTED' if row['id'] in pairs else
                          'POLICY_REJECTED_EXPECTED' if row['id'] in {'F04', 'F08', 'F15'} else 'CONTRACT_ENFORCED')
        subs = []
        for sub in row['subchecks']:
            key = (row['id'], sub['name'])
            result = special[key]() if key in special else contract(row['id'] + '/' + sub['name'])
            result.update(name=sub['name'], classification=classification if result['status'] == 'PASS' else
                          'CONTROL_FAILED' if result['control'] == 'FAIL' else 'BLOCKED' if result['status'] == 'BLOCKED' else 'WRONG_DIAGNOSTIC')
            subs.append(result)
        row['subchecks'] = subs
        row['status'] = 'FAIL' if any(r['status'] == 'FAIL' for r in subs) else 'BLOCKED' if any(r['status'] == 'BLOCKED' for r in subs) else 'PASS'
        row['control'] = 'FAIL' if any(r['control'] == 'FAIL' for r in subs) else 'PASS' if all(r['control'] == 'PASS' for r in subs) else 'BLOCKED'
        row['bad'] = row['status']
        row['classification'] = classification if row['status'] == 'PASS' else 'CONTROL_FAILED' if row['control'] == 'FAIL' else 'WRONG_DIAGNOSTIC' if row['status'] == 'FAIL' else 'BLOCKED'
        row['evidence_paths'] = list(dict.fromkeys(p for r in subs for p in r['evidence_paths']))
        row['observations'] = {'named_components': {r['name']: r['observation'] for r in subs}}
    value['starter'] = starter or {'status': 'BLOCKED'}
    lock = read_json(q.root / 'foundation.lock.json')
    value['dependency'] = {key: lock[key] for key in [
        'glib_version', 'minimum_api', 'allocation_profile', 'inputs', 'notices',
        'local_patches', 'recipe', 'recipe_sha256', 'sdk_image_id',
        'transitive_runtime_dependency', 'profile_equivalence', 'licensing']}
    value['dependency']['qualified_build_profiles'] = lock['profiles']
    required = [r['status'] for r in value['cases'] + value['sabotage'] + normal]
    required += [value[k]['status'] for k in ['doctor', 'policy', 'coverage', 'fuzz', 'runtime', 'starter']]
    value['status'] = 'FAIL' if 'FAIL' in required else 'BLOCKED' if 'BLOCKED' in required else 'PASS'
    value['limitations'] = [
        'Finite execution does not prove arbitrary C pointer validity or ownership.',
        'API policy is mechanically enforced; live spans, cleanup pairing and synchronization remain caller obligations.',
        'F19 uses a same-source ordinary static test-link variant; shared-runtime injection is not claimed.',
        'MSan instruments GLib and PCRE2 with documented libc interceptor boundaries.',
        'Independent approval, distribution/license review and remote execution remain pending.',
        'Application, production OOM strategy and deployment are not authorized.']
    validate_report(q.root, value, expected_binding(q))
    return value


def save(q, value):
    validate_report(q.root, value, expected_binding(q))
    atomic_json(q.runner.run_dir / 'foundation-qualification-report.json', value)
    atomic_json(q.root / 'artifacts/foundation-qualification-report.json', value)
    lines = ['# Foundation qualification: ' + value['status'], '',
             'Allocation profile: `glib-fail-stop`. Application readiness: false.', '',
             '| Case | Status | Classification | Control | Named subchecks |', '|---|---|---|---|---|']
    lines += ['| ' + r['id'] + ' | ' + r['status'] + ' | ' + r.get('classification', 'BLOCKED') + ' | ' + r['control'] + ' | ' +
              '; '.join(s['name'] + ': ' + s['status'] for s in r['subchecks']) + ' |' for r in value['cases']]
    lines += ['', 'Profiles: ' + ', '.join(r['name'] + ': ' + r['status'] for r in value['profiles']), '',
              'Coverage, fuzz, runtime and exact linked/loaded identities are recorded separately in the JSON report.', '']
    totals = value['coverage'].get('totals', {})
    lines += ['Foundation-only coverage: ' + '; '.join(f"{key} {row['covered']}/{row['count']} ({row['percent']:.2f}%)" for key, row in totals.items()),
              'Fuzz: ' + value['fuzz']['status'] + '; budget/executions, counterexample hashes, object audits and replay pairs are in the JSON.',
              'Runtime: ' + value['runtime']['status'] + '; actual image and binary hashes, final filesystem and valid/invalid input controls are in the JSON.', '',
              '| Profile | Selected dependency | Loaded library identity | Generated header identity |', '|---|---|---|---|']
    for row in value['profiles']:
        binding = row.get('library_binding', {})
        lines.append('| ' + row['name'] + ' | ' + row['dependency_profile'] + ' | ' +
                     '; '.join(path + ': `' + sha + '`' for path, sha in binding.get('library_hashes', {}).items()) + ' | `' +
                     binding.get('generated_header_sha256', 'unexecuted') + '` |')
    allocation = next((r for r in value.get('runtime_pairs', []) if r['id'] == 'F19'), {})
    lines += ['', 'Allocation experiment: ' + allocation.get('status', 'BLOCKED') +
              '. Same-source ordinary static test-link injection; no shared-runtime injection claim.', '',
              '| Pipeline variant | Status | Control |', '|---|---|---|']
    lines += ['| ' + r['name'] + ' | ' + r['status'] + ' | ' + r['control'] + ' |' for r in value['sabotage']]
    lines += ['', 'Exact source/dependency/runner/instance bindings and commands are in the JSON and cited evidence paths.', '']
    lines += ['- ' + text for text in value.get('limitations', [])]
    (q.root / 'artifacts/foundation-qualification-report.md').write_text('\n'.join(lines) + '\n')
