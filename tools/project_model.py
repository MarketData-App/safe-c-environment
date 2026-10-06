"""Project model: project.json, project inventory and the framework manifest."""
import hashlib
import json
import posixpath
import re
from pathlib import Path
import policy
from evidence import GateError, read_json
from schema_check import validate

PROJECT_PATHS = ('src/', 'include/', 'tests/project/', 'fuzz/project/', 'specs/project/', 'review/')
MANIFEST = 'framework-manifest.json'
PROJECT_FILE = 'project.json'
_CI_WORKFLOW = '.github/workflows/project-ci.yml'
_SCRATCH = '.superpowers'


def _framework_root(root, framework_root):
    if framework_root is not None:
        return Path(framework_root)
    root = Path(root)
    return root if (root/'schemas').is_dir() else Path(__file__).resolve().parents[1]


def _safe_path(rel, what):
    if not isinstance(rel, str) or not rel or rel.startswith('/') or '\\' in rel or '\0' in rel or '\n' in rel:
        raise GateError(f'project path is not allowed: {what}')
    if '..' in rel.split('/') or '' in rel.split('/') or '.' in rel.split('/'):
        raise GateError(f'project path is not allowed: {rel}')
    return rel


def _declared_paths(project):
    paths = []
    for module in project['modules']:
        paths += [module['spec']] + module['sources'] + module['headers'] + module['tests']
        for fuzz in module['fuzz']:
            paths.append(fuzz['harness'])
    paths += [program['main'] for program in project['programs']]
    return paths


def _dir_paths(project):
    return [d for module in project['modules'] for fuzz in module['fuzz'] for d in (fuzz['corpus'], fuzz['regressions'])]


def _normalized_source(text):
    """Return the text after line splicing, with block comments replaced by one space."""
    spliced = re.sub(r'\\\r?\n', '', text)
    return re.sub(r'/\*.*?\*/', ' ', spliced, flags=re.S)


def forbidden_pattern(text, patterns):
    """Return the first policy pattern found in the raw or normalized text, or None."""
    variants = (text, _normalized_source(text))
    for item, regex in patterns:
        if any(regex.search(v) for v in variants):
            return item
    return None


def project_policy(root):
    value = read_json(Path(root)/'safety/project-policy.json')
    validate(Path(root), 'project-policy', value)
    return value


def load_project(root, project_dir='.', framework_root=None):
    root = Path(root)
    fw = _framework_root(root, framework_root)
    if project_dir != '.':
        _safe_path(project_dir, 'project_dir')
    base = root/project_dir
    path = base/PROJECT_FILE
    if path.is_symlink() or not path.is_file():
        raise GateError(f'{PROJECT_FILE} is missing: {project_dir}')
    value = read_json(path)
    validate(fw, 'project', value)
    for rel in _declared_paths(value) + _dir_paths(value):
        _safe_path(rel, rel)
    names = [m['name'] for m in value['modules']]
    if len(set(names)) != len(names):
        raise GateError('project: duplicate module name')
    for program in value['programs']:
        for name in program['modules']:
            if name not in names:
                raise GateError(f'project: program {program["name"]} uses unknown module {name}')
    if value['run']['program'] not in [p['name'] for p in value['programs']]:
        raise GateError('project: run.program is not a declared program')
    return value


def undeclared_application_sources(root):
    """src/include C files that no root project.json declares (all of them without project.json)."""
    root = Path(root)
    found = sorted(str(p.relative_to(root)) for folder in ('src', 'include') for p in (root/folder).rglob('*')
                   if p.suffix in {'.c', '.h'})
    if not found or not (root/PROJECT_FILE).is_file():
        return found
    declared = set(_declared_paths(load_project(root)))
    return [rel for rel in found if rel not in declared]


def project_files(root, project_dir='.'):
    base = Path(root)/project_dir
    walked = Path(root)
    for part in Path(project_dir).parts:
        walked = walked/part
        if walked.is_symlink():
            raise GateError(f'symlink input is forbidden: {project_dir}')
    result = {}
    for top in PROJECT_PATHS:
        start = base/top
        if start.is_symlink():
            raise GateError(f'symlink input is forbidden: {top}')
        if not start.exists():
            continue
        for path in sorted(start.rglob('*')):
            if path.is_symlink():
                raise GateError(f'symlink input is forbidden: {path.relative_to(base)}')
            if path.is_file():
                result[str(path.relative_to(base))] = policy.file_hash(path)
    return result


def framework_files(root):
    root = Path(root)
    result = {}
    for rel, digest in policy.source_files(root).items():
        if rel.startswith(PROJECT_PATHS) or rel in (PROJECT_FILE, MANIFEST, _CI_WORKFLOW):
            continue
        if rel.split('/')[0] == _SCRATCH:
            continue
        result[rel] = digest
    return result


def _identity(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def write_manifest(root, report, images, framework_root=None):
    root = Path(root)
    if report.get('overall_state') != 'VALIDATED_UNSEALED':
        raise GateError('manifest requires overall_state VALIDATED_UNSEALED')
    identity = policy.source_identity(root)[0]
    if report.get('source_identity') != identity:
        raise GateError('manifest report does not match the current source identity')
    run_id = report.get('run_id')
    if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
        raise GateError('manifest report needs run_id as 32 lowercase hex')
    files = framework_files(root)
    value = {'schema_version': 1, 'framework_identity': _identity(files), 'files': files, 'images': images,
             'qualification': {'run_id': run_id, 'source_identity': identity,
                               'overall_state': report['overall_state']}}
    validate(_framework_root(root, framework_root), 'framework-manifest', value)
    (root/MANIFEST).write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
    return value


def _fresh_report(root, report):
    """The same freshness checks as `safety report` and instantiate."""
    fw = _framework_root(root, None)
    validate(fw, 'report', report)
    policy.validate_fresh_report(report, policy.source_identity(root)[0], read_json(root/'toolchain.lock.json')['image_id'],
                                 policy.file_hash(root/'safety/contract.json'))
    from containment import fresh_container_evidence
    fresh_container_evidence(root, report, read_json(root/'toolchain.lock.json'))


def framework_manifest(root):
    """`safety framework manifest`: bind the current qualified report and pinned images."""
    root = Path(root)
    try:
        bundle = read_json(root/'ci/image-bundle.json')
        images = {'sdk': read_json(root/'toolchain.lock.json')['image_id'],
                  'developer': read_json(root/'developer.lock.json')['image_id'],
                  'archive_sha256': bundle['archive_sha256']}
        bundled = bundle['image_ids']
        if not isinstance(bundled, list) or any(images[k] not in bundled for k in ('sdk', 'developer')):
            raise GateError('framework manifest: sdk/developer image is not in ci/image-bundle.json image_ids')
        report = read_json(root/'artifacts/bootstrap-report.json')
        _fresh_report(root, report)
    except (KeyError, TypeError) as error:
        raise GateError(f'framework manifest input is incomplete: {error}') from error
    return write_manifest(root, report, images)


def _project_dir(root, value):
    # --project is relative to the --candidate root, never to the current directory.
    path = Path(value)
    if not path.is_absolute():
        normal = posixpath.normpath(value)
        if normal == '..' or normal.startswith('../') or normal.startswith('/'):
            raise GateError('--project must be inside the framework root')
        return normal
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError as error:
        raise GateError('--project must be inside the framework root') from error


def execute(root, args):
    if args.command == 'project':
        import project_check
        try:
            project_dir = _project_dir(root, args.project)
        except GateError as error:
            print('BLOCKED: ' + str(error))
            return 2
        return project_check.run_project_check(Path(root), project_dir, development=args.development)['exit_code']
    value = framework_manifest(root)
    print(json.dumps({'status': 'WRITTEN', 'path': str(Path(root)/MANIFEST), 'framework_identity': value['framework_identity'],
                      'files': len(value['files']), 'images': value['images']}, indent=2))
    return 0


def check_manifest(root, framework_root=None):
    root = Path(root)
    value = read_json(root/MANIFEST)
    validate(_framework_root(root, framework_root), 'framework-manifest', value)
    stored, current = value['files'], framework_files(root)
    lines = []
    for rel in sorted(set(stored) | set(current)):
        if rel not in stored:
            lines.append(f'added: {rel}')
        elif rel not in current:
            lines.append(f'removed: {rel}')
        elif stored[rel] != current[rel]:
            lines.append(f'changed: {rel}')
    if value['framework_identity'] != _identity(stored):
        lines.append('identity: framework_identity mismatch')
    return lines


def project_inventory(root, project_dir, project, framework_root=None):
    root = Path(root)
    base = root/project_dir
    if not project['modules']:
        raise GateError('project has zero modules')
    declared = set(_declared_paths(project))
    for module in project['modules']:
        if not module['tests']:
            raise GateError(f'module {module["name"]} has no tests')
        if not (base/module['spec']).is_file():
            raise GateError(f'module {module["name"]} has no spec: {module["spec"]}')
        if module['reads_external_input'] and not module['fuzz']:
            raise GateError(f'module {module["name"]} reads external input and needs a fuzz target')
    for module in project['modules']:
        for fuzz in module['fuzz']:
            if not (base/fuzz['regressions']).is_dir():
                raise GateError(f'fuzz regression directory is missing: {fuzz["regressions"]}')
            corpus = base/fuzz['corpus']
            if not corpus.is_dir() or not any(p.is_file() for p in corpus.rglob('*')):
                raise GateError(f'fuzz corpus is missing or empty: {fuzz["corpus"]}')
    actual = project_files(root, project_dir)
    data_dirs = tuple(d.rstrip('/')+'/' for d in _dir_paths(project))
    code = {p for p in actual if not p.startswith(data_dirs) and not p.startswith(('specs/project/', 'review/'))
            and p.startswith(('src/', 'include/', 'tests/project/', 'fuzz/project/'))
            and (p.startswith('fuzz/project/') is False or p.endswith('.c'))}
    listed = declared - {m['spec'] for m in project['modules']}
    for rel in sorted(code - listed):
        raise GateError(f'unlisted project file: {rel}')
    for rel in sorted(listed - set(actual)):
        raise GateError(f'declared project file is missing: {rel}')
    policy = project_policy(_framework_root(root, framework_root))
    forbidden = policy['forbidden_text']
    patterns = [(item, re.compile(item)) for item in policy['forbidden_patterns']]
    for rel in sorted(actual):
        if rel.endswith(('.c', '.h')):
            text = (base/rel).read_text(errors='replace')
            for item in forbidden:
                if item in text:
                    raise GateError(f'forbidden text in {rel}: {item}')
            item = forbidden_pattern(text, patterns)
            if item is not None:
                raise GateError(f'forbidden pattern in {rel}: {item}')
