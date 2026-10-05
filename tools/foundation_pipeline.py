"""Individual foundation pipeline rejection experiments and unchanged controls."""
import copy
import json
import shutil
import tempfile
from pathlib import Path
from evidence import GateError, atomic_json, environment_gate, read_json, file_hash
from foundation import (fixture_inventory, sdk_gate, input_gate, validate_report,
                        expected_binding, finding_gate, fail_stop_gate,
                        ordinary_gate, functional_gate, NORMAL_PROFILES)
from policy import baseline_gate, baseline_identity, inventory_gate, export_inventory


def run(q, value):
    rows = []
    spec = fixture_inventory(q.root)
    probes = {r['id']: r for r in value['policy_probes']['probes']}
    mutants = {r['id']: r for r in value['functional']['mutants']}
    pairs = {r['id']: r for r in value['runtime_pairs']}
    sdk = value['doctor']['observed_files']
    binding = expected_binding(q)

    def evidence(row, marker):
        for path in row['evidence_paths']:
            record = read_json(Path(path))
            if marker(record):
                return record
        raise GateError('foundation pipeline executed component evidence unavailable')

    def classify_pair(identifier):
        row = pairs[identifier]
        finding = row['observations']['finding']
        negative = read_json(Path(finding['evidence_path']))
        control = evidence(row, lambda r: r.get('binary_sha256') == row['observations']['control_binary_sha256'] and r.get('exit_code') == 0)
        return row, negative, control

    def report_gate(report):
        validate_report(q.root, report, binding, complete=False)

    def profiles_gate(report):
        names = [r['name'] for r in report['profiles']]
        if len(names) != len(set(names)) or set(names) != NORMAL_PROFILES:
            raise GateError('mandatory foundation profile missing')
        report_gate(report)

    def coverage_gate(report):
        denominator = ['foundation/src/sc-foundation.c', 'foundation/include/sc-foundation.h']
        cov = report['coverage']
        if cov.get('status') != 'PASS' or cov.get('denominator') != denominator:
            raise GateError('foundation coverage denominator missing')
        for category, minimum in [('lines', 90), ('branches', 85)]:
            totals = cov['totals'][category]
            if totals['count'] <= 0 or 100 * totals['covered'] / totals['count'] < minimum:
                raise GateError('foundation coverage insufficient')

    def record(parent, name, variant, control, rejection, paths, reason):
        control_ok = rejected = False
        try:
            control()
            control_ok = True
        except (GateError, OSError, KeyError, ValueError):
            pass
        if control_ok:
            try:
                rejected = rejection() is True
            except GateError:
                rejected = True
        item = {'parent': parent, 'name': name + '/' + variant,
                'status': 'PASS' if control_ok and rejected else 'FAIL',
                'control': 'PASS' if control_ok else 'FAIL',
                'evidence_paths': list(dict.fromkeys(paths)), 'reason': reason}
        output = q.runner.run_dir / ('foundation-pipeline-' + parent + '-' + variant + '.json')
        atomic_json(output, {'input_binding': binding, 'variant': item['name'],
                             'control': item['control'], 'mutation_rejected': rejected,
                             'status': item['status'], 'component_evidence': item['evidence_paths']})
        item['evidence_paths'].append(str(output))
        rows.append(item)
        print(json.dumps({'case_id': item['name'], 'verdict': item['status']}), flush=True)

    def require_pass(row):
        if row.get('status') != 'PASS' or row.get('control', 'PASS') != 'PASS':
            raise GateError('executed component/control did not pass')

    root_files = __import__('policy').source_files(q.root)
    identity = baseline_identity(q.root)
    with tempfile.TemporaryDirectory(prefix='foundation-pipeline-', dir=q.runner.run_dir) as temporary:
        candidate = Path(temporary)
        for relative in root_files:
            dst = candidate / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(q.root / relative, dst)

        def candidate_experiment(relative, mutation, gate):
            path = candidate / relative
            original = path.read_bytes()
            try:
                mutation(path)
                gate()
            finally:
                path.write_bytes(original)

        def candidate_gate():
            baseline_gate(candidate, q.root, identity)

        def json_edit(path, change):
            data = read_json(path)
            change(data)
            atomic_json(path, data)

        for family in spec['pipeline_subcases']:
            parent, name = family['parent'], family['name']
            for variant in family['variants']:
                control = lambda: report_gate(value)
                paths = [value['doctor']['sdk_evidence_path']]
                reason = 'The unchanged executed component passes; the designated altered input is rejected.'
                if parent == 'P01' and variant in {'missing-library', 'missing-header', 'missing-generated-config'}:
                    changed = copy.deepcopy(sdk)
                    target = {'missing-library': 'lib/libglib-2.0.so.0', 'missing-header': 'include/glib-2.0/glib.h',
                              'missing-generated-config': 'lib/glib-2.0/include/glibconfig.h'}[variant]
                    changed['clang-O0'].pop(target)
                    control = lambda: sdk_gate(q.root, sdk)
                    rejection = lambda c=changed: sdk_gate(q.root, c)
                elif parent == 'P01' and variant == 'ambient-pkg-config':
                    control = lambda: environment_gate({})
                    rejection = lambda: environment_gate({'PKG_CONFIG_PATH': '/unapproved'})
                elif parent == 'P01':
                    relative = 'foundation.lock.json'
                    if variant == 'missing-notice':
                        relative = next(iter(read_json(q.root / relative)['notices']))
                        mutation = lambda p: p.unlink()
                    elif variant == 'missing-provenance':
                        mutation = lambda p: json_edit(p, lambda d: d['inputs'].pop())
                    else:
                        mutation = lambda p: json_edit(p, lambda d: d.update(minimum_api='2.60'))
                    control = lambda: input_gate(candidate)
                    rejection = lambda r=relative, m=mutation: candidate_experiment(r, m, lambda: input_gate(candidate))
                elif parent == 'P02' and variant == 'missing-first-party-tu':
                    control = lambda: inventory_gate(candidate)
                    rejection = lambda: candidate_experiment('safety/source-inventory.json',
                        lambda p: json_edit(p, lambda d: d['files'].pop('foundation/src/sc-foundation.c')), lambda: inventory_gate(candidate))
                elif parent == 'P02' and variant == 'uninstrumented-dependency-object':
                    control = candidate_gate
                    rejection = lambda: candidate_experiment('foundation.lock.json',
                        lambda p: json_edit(p, lambda d: d['profiles']['msan'].update(flags=[])), candidate_gate)
                elif (parent == 'P02' and variant == 'wrong-loaded-profile') or (parent == 'P10' and variant == 'same-version-library'):
                    changed = copy.deepcopy(value)
                    profile = changed['profiles'][0]
                    path = next(iter(profile['library_binding']['library_hashes']))
                    profile['library_binding']['library_hashes'][path] = '0' * 64
                    rejection = lambda c=changed: report_gate(c)
                    paths = value['profiles'][0]['evidence_paths']
                elif parent == 'P04' and variant in {'direct-forbidden-api', 'macro-forbidden-api', 'backing-field', 'allocator-hook', 'sanitizer-suppression', 'renamed-application-source'}:
                    key = {'direct-forbidden-api': 'direct-static', 'macro-forbidden-api': 'macro-static', 'backing-field': 'direct-backing',
                           'allocator-hook': 'allocator-hook', 'sanitizer-suppression': 'suppression', 'renamed-application-source': 'renamed-application'}[variant]
                    row = probes[key]
                    control = lambda r=row: require_pass(r)
                    rejection = lambda r=row: r['status'] == 'PASS'
                    paths = row['evidence_paths']
                elif parent == 'P04':
                    control = candidate_gate
                    rejection = lambda: candidate_experiment('safety/foundation-api-policy.json',
                        lambda p: json_edit(p, lambda d: d['approved_glib_functions'].append('g_malloc')), candidate_gate)
                elif parent == 'P07':
                    changed = copy.deepcopy(value)
                    if variant == 'missing-F-case':
                        changed['cases'].pop(); rejection = lambda c=changed: report_gate(c)
                    elif variant == 'missing-control':
                        changed['cases'][0]['control'] = 'BLOCKED'; changed['cases'][0]['status'] = 'PASS'
                        rejection = lambda c=changed: report_gate(c)
                    elif variant == 'missing-profile':
                        changed['profiles'].pop(); control = lambda: profiles_gate(value); rejection = lambda c=changed: profiles_gate(c)
                    elif variant == 'missing-coverage-denominator':
                        changed['coverage']['denominator'].pop(); control = lambda: coverage_gate(value); rejection = lambda c=changed: coverage_gate(c)
                        paths = value['coverage']['evidence_paths']
                    else:
                        control = lambda: export_inventory(candidate)
                        rejection = lambda: candidate_experiment('starter-export.json',
                            lambda p: json_edit(p, lambda d: d['files'].remove('foundation/src/sc-foundation.c')), lambda: export_inventory(candidate))
                elif parent == 'P10':
                    changed = copy.deepcopy(value)
                    if variant == 'generated-header-substitution':
                        changed['profiles'][0]['library_binding']['generated_header_sha256'] = '0' * 64
                    elif variant == 'runtime-image-substitution':
                        changed['runtime']['input_binding']['image'] = 'sha256:' + '0' * 64
                    elif variant == 'copied-parent-report':
                        changed['binding']['instance'] = '0' * 64
                    else:
                        changed['profiles'][0]['library_binding']['input_binding']['source'] = '0' * 64
                    rejection = lambda c=changed: report_gate(c)
                elif parent == 'P11':
                    if variant == 'unexpected-critical':
                        build = q.build('ordinary', foundation_case='F14')
                        if not q.built(build):
                            raise GateError('foundation diagnostic classifier fixture build failed')
                        negative = q.executable(build, 'F14_bad', label='foundation-unexpected-critical')
                        positive = q.executable(build, 'F14_good', label='foundation-no-critical-control')
                        control = lambda r=positive: ordinary_gate(r)
                        rejection = lambda r=negative: ordinary_gate(r)
                        paths = [negative['evidence_path'], positive['evidence_path']]
                    elif variant == 'wrong-functional-failure':
                        row = mutants['index-guard-O0']
                        negative = evidence(row, lambda r: r.get('binary_sha256') == row['negative_binary_sha256'])
                        control = lambda r=negative: functional_gate(r, 'F05/empty-index')
                        rejection = lambda r=negative: functional_gate(r, 'F05/one-past-logical')
                        paths = row['evidence_paths']
                    elif variant == 'missing-msan-finding':
                        row, negative, positive = classify_pair('F17')
                        control = lambda r=negative: finding_gate(r, 'F17', 'uninitialized-value', 'safety/qualification/foundation/F17.c', origin=True)
                        changed = copy.deepcopy(negative); changed['output'] = ''
                        rejection = lambda r=changed: finding_gate(r, 'F17', 'uninitialized-value', 'safety/qualification/foundation/F17.c', origin=True)
                        paths = row['evidence_paths']
                    else:
                        row, negative, positive = classify_pair('F19')
                        static_hash = row['observations']['finding']['static_library_sha256']
                        changed = copy.deepcopy(negative)
                        if variant == 'ordinary-oom-as-success':
                            control = lambda r=positive: ordinary_gate(r)
                            rejection = lambda r=negative: ordinary_gate(r)
                        else:
                            control = lambda r=negative, h=static_hash: fail_stop_gate(r, h)
                            if variant == 'cgroup-oom': changed.update(exit_code=137, failure='CONTAINER_OOM')
                            elif variant == 'timeout': changed.update(failure='TIMEOUT')
                            else: changed['output'] = ''
                            rejection = lambda r=changed, h=static_hash: fail_stop_gate(r, h)
                        paths = row['evidence_paths']
                elif parent == 'P15':
                    control = candidate_gate
                    if variant == 'unchecked-collection-index':
                        row = mutants['index-guard-O2']; control = lambda r=row: require_pass(r)
                        rejection = lambda r=row: r['bad'] == 'PASS'
                        paths = row['evidence_paths']
                    else:
                        relative = 'safety/foundation-api-policy.json' if variant in {'recoverable-oom-relabel', 'child-policy-downgrade'} else 'safety/source-inventory.json' if variant == 'runtime-as-qualification-fixture' else 'specs/foundation-contract.md'
                        if variant == 'recoverable-oom-relabel':mutation = lambda p: json_edit(p, lambda d: d.update(oom_policy='recoverable'))
                        elif variant == 'runtime-as-qualification-fixture':mutation = lambda p: json_edit(p, lambda d: d['files']['foundation/src/sc-foundation.c'].update(role='qualification'))
                        elif variant == 'child-policy-downgrade':mutation = lambda p: json_edit(p, lambda d: d['approved_glib_functions'].append('g_malloc'))
                        else:mutation = lambda p: p.write_text(p.read_text().replace('text 4096 bytes', 'text 1 byte'))
                        rejection = lambda r=relative, m=mutation: candidate_experiment(r, m, candidate_gate)
                elif parent == 'P16':
                    fuzz = value['fuzz']
                    if variant in {'noop-harness', 'omitted-adapter-object'}:
                        row = fuzz['noop' if variant == 'noop-harness' else 'omitted_adapter']
                        control = lambda r=row: require_pass(r)
                        rejection = lambda r=row: r['status'] == 'PASS'
                        paths = row['evidence_paths']
                    else:
                        row = next(r for r in fuzz['pairs'] if r['interface'] == 'clusterfuzzlite')
                        control = lambda r=row: require_pass(r)
                        negative = read_json(Path(row['evidence_paths'][0]))
                        rejection = lambda r=negative: ordinary_gate(r)
                        paths = row['evidence_paths']
                else:
                    raise GateError('foundation pipeline variant has no executor')
                record(parent, name, variant, control, rejection, paths, reason)
    return rows
