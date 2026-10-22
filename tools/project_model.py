"""Project model: project.json, project inventory and the framework manifest."""
import hashlib
import json
import posixpath
import re
from pathlib import Path
import policy
import project_source
from evidence import GateError, PROJECT_JSON_MAX_BYTES, load_project_json, read_json
from schema_check import validate

PROJECT_PATHS = project_source.PROJECT_PATHS
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
    """The text after translation phases 1-3 (project_source.lex): trigraphs replaced,
    lines spliced, each comment replaced by one space and every string or character
    literal emptied (its prefix and quotes stay). Forbidden text and patterns are
    checked on this code view and on the raw text."""
    return project_source.lex(text).code


def forbidden_pattern(text, patterns, code=None):
    """Return the first policy pattern found in the raw or normalized text, or None."""
    variants = (text, _normalized_source(text) if code is None else code)
    for item, regex in patterns:
        if any(regex.search(v) for v in variants):
            return item
    return None


# Framework include directories a project target may have searched (cmake/Safety.cmake,
# tools/foundation.py analysis_flags), relative to a child's root. An angle include must
# not reach a project path through them.
_FRAMEWORK_INCLUDE_DIRS = ('fuzz/', 'safety/qualification/')


def include_problem(rel, text, headers, present, tokens=None):
    """Return why an include directive in `text` (the source of `rel`) is forbidden, or None.

    The directives come from the lexer, so comments, literals, line splices and form
    feeds cannot hide or fake one. A quoted include must resolve, as the compiler
    searches (the including file's directory, then include/), to a header declared in
    project.json. An angle include may not leave its search directory, a file it would
    find under include/ must be a declared header, and it may not reach a project path
    through a framework include directory. Computed includes, #include_next and #import
    are forbidden. The compiler dependency check in the ast gate is authoritative."""
    tokens = project_source.lex(text).tokens if tokens is None else tokens
    for _line, name, form, target in project_source.include_targets(tokens):
        if name != 'include':
            return '#'+name
        if target is None:
            return 'computed include'
        angled = form == 'angle'
        if not target or target.startswith('/') or '\\' in target or (angled and '..' in target.split('/')):
            return 'include path leaves its directory: '+target
        if not angled:
            candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(rel), target)),
                          posixpath.normpath('include/'+target)]
            found = next((c for c in candidates if c in present), None)
            if found not in headers:
                return 'quoted include does not name a declared project header: '+target
            continue
        local = posixpath.normpath('include/'+target)
        if local in present and local not in headers:
            return 'angle include finds an undeclared file: '+target
        if any(posixpath.normpath(d+target).startswith(PROJECT_PATHS) for d in _FRAMEWORK_INCLUDE_DIRS):
            return 'angle include reaches a project path through a framework include directory: '+target
    return None


def source_problem(rel, text, forbidden, patterns, headers, present):
    """The first inventory pre-check finding for one project file, or None.

    Fast feedback only: the compiler-based checks of the ast gate are authoritative."""
    lexed = project_source.lex(text)
    for line, problem in lexed.problems:
        return f'forbidden source form in {rel}:{line}: {problem}'
    variants = (text, lexed.code)
    for item in forbidden:
        if any(item in v for v in variants):
            if item in project_source.RUNTIME_INTERFACE_PREFIXES:
                return f'forbidden runtime interface name in {rel}: {item}'
            return f'forbidden text in {rel}: {item}'
    item = forbidden_pattern(text, patterns, lexed.code)
    if item is not None:
        return f'forbidden pattern in {rel}: {item}'
    found = project_source.directive_problem(lexed.tokens)
    if found is not None:
        return f'forbidden directive in {rel}:{found[0]}: {found[1]}'
    problem = include_problem(rel, text, headers, present, lexed.tokens)
    if problem is not None:
        return f'forbidden include in {rel}: {problem}'
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
    # FR3-17: project data through the one boundary; every check of the parsed value runs inside it
    return load_project_json(path, 'project-json', PROJECT_JSON_MAX_BYTES, label=PROJECT_FILE,
                             check=lambda value: _check_project(fw, value))


def _check_project(fw, value):
    """The checks of load_project on the parsed project.json `value` (GateError on the first failure)."""
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
    # FR3-21: an argv cannot carry NUL, and a lone surrogate has no UTF-8 encoding; refuse both here, before any container
    for index, arg in enumerate(value['run']['args']):
        if any(c == '\x00' or '\ud800' <= c <= '\udfff' for c in arg):
            raise GateError(f'project: run.args[{index}] holds NUL or a lone surrogate')
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


EXPORT_LIST = 'starter-export.json'
# Substituted by instantiate; baseline_gate validates them against the origin.
INSTANCE_FILES = ('starter.json', 'starter-baseline.lock.json')
FRAMEWORK_DIRS = ('tools', 'safety', 'schemas', 'cmake', 'container', 'ci', 'foundation', 'third_party', '.githooks',
                  '.github', 'fuzz', 'tests', 'benchmarks')
_NOT_FRAMEWORK = ('fuzz/project/', 'tests/project/', 'benchmarks/project/', _CI_WORKFLOW)
_SKIPPED_PARTS = {'__pycache__', _SCRATCH, 'artifacts', 'build', '.git', '.cache', '.direnv'}


def _exported_framework_list(root):
    try:
        files = read_json(root/EXPORT_LIST)['files']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise GateError(f'framework file list is unreadable: {EXPORT_LIST}') from error
    if not isinstance(files, list) or len(files) != len(set(map(str, files))):
        raise GateError(f'framework file list is invalid: {EXPORT_LIST}')
    for rel in files:
        _safe_path(rel, 'starter-export.json entry')
    return [rel for rel in files if rel not in INSTANCE_FILES]


EXAMPLES_DIR = 'examples'


def standalone_examples(root):
    """Rule S (amendment E, section 1.2): the sorted directories examples/<name> that hold project.json while
    starter-export.json does not list examples/<name>/project.json. A standalone example is no framework file: the
    framework inventory, the framework manifest and the framework bench scope leave it out, and its own project check
    (project_inventory) checks its C files. An examples/<name> without project.json stays framework content (fail
    closed). A symbolic link at examples/, examples/<name> or examples/<name>/project.json is refused (FIX1-A06: a deeper
    link is a path of its tree); the export list is read only when a candidate exists.
    FIX1 T3-A06: a standalone tree that holds a path of the export list is a mixed state (the path would stay in the
    manifest and the export but leave the framework source inventory and the B18 payload); it raises GateError."""
    root = Path(root)
    base = root/EXAMPLES_DIR
    if base.is_symlink():
        raise GateError(f'symlink input is forbidden: {EXAMPLES_DIR}')
    if not base.is_dir():
        return []
    candidates = []
    for path in sorted(base.iterdir()):
        rel = f'{EXAMPLES_DIR}/{path.name}'
        if path.is_symlink() or (path/PROJECT_FILE).is_symlink():
            raise GateError(f'symlink input is forbidden: {rel}')
        if path.is_dir() and (path/PROJECT_FILE).is_file():
            candidates.append(rel)
    if not candidates:
        return []
    listed = set(_exported_framework_list(root))
    standalone = [rel for rel in candidates if f'{rel}/{PROJECT_FILE}' not in listed]
    for rel in standalone:
        mixed = sorted(path for path in listed if path.startswith(rel + '/'))
        if mixed:
            raise GateError(f'{EXPORT_LIST} lists a file of the standalone example {rel}: {mixed[0]}')
    return standalone


def example_scopes(paths, listed):
    """Rule S over the tracked paths of one commit (FIX1 T3-A01; ci/changed-examples reads a base and a head this way):
    {examples/<name>: 'framework' | 'standalone' | 'project-less'} for every examples/<name> that holds a path of `paths`.
    framework: examples/<name>/project.json is a path and `listed` (the export list of the same commit) holds it;
    standalone: the path exists and is not listed; project-less: no project.json (framework content, fail closed). A path
    directly under examples/ belongs to no example directory."""
    paths, listed, scopes = set(paths), set(listed), {}
    for path in paths:
        parts = path.split('/')
        if len(parts) < 3 or parts[0] != EXAMPLES_DIR:
            continue
        rel = f'{EXAMPLES_DIR}/{parts[1]}'
        project = f'{rel}/{PROJECT_FILE}'
        scopes[rel] = 'project-less' if project not in paths else 'framework' if project in listed else 'standalone'
    return scopes


def _framework_sets(root):
    """(listed, unlisted): exported framework files, and other files under framework directories."""
    root = Path(root)
    listed = {}
    for rel in _exported_framework_list(root):
        path = root/rel
        if path.is_symlink():
            raise GateError(f'symlink input is forbidden: {rel}')
        if path.is_file():
            listed[rel] = policy.file_hash(path)
    unlisted = {}
    for top in FRAMEWORK_DIRS:
        start = root/top
        if start.is_symlink():
            raise GateError(f'symlink input is forbidden: {top}')
        if not start.is_dir():
            continue
        for path in sorted(start.rglob('*')):
            rel = path.relative_to(root)
            if any(part in _SKIPPED_PARTS for part in rel.parts):
                continue
            name = rel.as_posix()
            if name.startswith(_NOT_FRAMEWORK) or name in listed:
                continue
            if path.is_symlink():
                raise GateError(f'symlink input is forbidden: {name}')
            if path.is_file():
                unlisted[name] = policy.file_hash(path)
    return listed, unlisted


def framework_files(root):
    """starter-export.json files minus the instance files, plus unlisted files under framework directories."""
    listed, unlisted = _framework_sets(root)
    return {**listed, **unlisted}


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
    listed, unlisted = _framework_sets(root)
    if unlisted:
        raise GateError('framework files are not in starter-export.json: '+', '.join(sorted(unlisted)[:20]))
    files = listed
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


def check_module_dependencies(project):
    """Amendment F item 3: `uses` names declared other modules without a cycle; `foundation` is closed."""
    names = [m['name'] for m in project['modules']]
    for m in project['modules']:
        for u in m.get('uses', []):
            if u == m['name']:
                raise GateError(f"module uses itself: {m['name']}")
            if u not in names:
                raise GateError(f"module uses an unknown module: {m['name']} -> {u}")
        if 'foundation' in m and m['foundation'] != 'glib-parallel':
            raise GateError('foundation must be "glib-parallel"')
    for m in project['modules']:
        uses_closure(project, m['name'])


def uses_closure(project, name):
    """Modules that `name` links, dependencies first, each once; a cycle raises GateError."""
    by_name = {m['name']: m for m in project['modules']}
    order, state = [], {}
    def visit(n, stack):
        if state.get(n) == 'done':
            return
        if n in stack:
            raise GateError('module dependency cycle: ' + ' -> '.join(stack + [n]))
        for u in by_name[n].get('uses', []):
            visit(u, stack + [n])
        state[n] = 'done'
        if n != name:
            order.append(n)
    visit(name, [])
    return order


# C17 and C23 keywords: an export with one of these names cannot be declared in C.
C_KEYWORDS = frozenset((
    'alignas', 'alignof', 'auto', 'bool', 'break', 'case', 'char', 'const', 'constexpr', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'false', 'float', 'for', 'goto', 'if', 'inline', 'int', 'long', 'nullptr',
    'register', 'restrict', 'return', 'short', 'signed', 'sizeof', 'static', 'static_assert', 'struct', 'switch',
    'thread_local', 'true', 'typedef', 'typeof', 'typeof_unqual', 'union', 'unsigned', 'void', 'volatile', 'while'))
_C_NAME = re.compile(r'[a-z][a-z0-9_]{0,62}')


def library_closure(project, library):
    """The modules whose whole archives form the library: each listed module's uses closure, then the module."""
    names = []
    for name in library['modules']:
        names += uses_closure(project, name) + [name]
    return list(dict.fromkeys(names))


def check_libraries(project):
    """Amendment F item 3: the closed `libraries` field.

    Each listed module is declared and listed once; each export is a C name that is not a
    keyword; library names are unique and differ from program names; at least one listed
    module reads external input and has a fuzz target (the entry point is fuzzed)."""
    libraries = project.get('libraries', [])
    by_name = {m['name']: m for m in project['modules']}
    programs = {p['name'] for p in project.get('programs', [])}
    seen = set()
    for library in libraries:
        name = library['name']
        if name in seen or name in programs:
            raise GateError(f'library name is not unique or equals a program name: {name}')
        seen.add(name)
        if len(set(library['modules'])) != len(library['modules']):
            raise GateError(f'library lists a module twice: {name}')
        for module in library['modules']:
            if module not in by_name:
                raise GateError(f'library uses an unknown module: {name} -> {module}')
        for export in library['exports']:
            if not isinstance(export, str) or not _C_NAME.fullmatch(export) or export in C_KEYWORDS:
                raise GateError(f'library export is not a valid C name: {name} -> {str(export)[:64]}')
        if not any(by_name[m]['reads_external_input'] and by_name[m]['fuzz'] for m in library['modules']):
            raise GateError(f'library module must declare reads_external_input and a fuzz target: {name}')


def project_inventory(root, project_dir, project, framework_root=None):
    root = Path(root)
    base = root/project_dir
    if not project['modules']:
        raise GateError('project has zero modules')
    check_module_dependencies(project)
    check_libraries(project)
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
    # Every file under the code paths must be declared; under fuzz/project/ only the
    # declared corpus and regression directories may hold other files.
    code = {p for p in actual if not p.startswith(data_dirs) and not p.startswith(('specs/project/', 'review/'))
            and p.startswith(('src/', 'include/', 'tests/project/', 'fuzz/project/'))}
    listed = declared - {m['spec'] for m in project['modules']}
    for rel in sorted(code - listed):
        raise GateError(f'unlisted project file: {rel}')
    for rel in sorted(listed - set(actual)):
        raise GateError(f'declared project file is missing: {rel}')
    policy = project_policy(_framework_root(root, framework_root))
    forbidden = policy['forbidden_text']
    patterns = [(item, re.compile(item)) for item in policy['forbidden_patterns']]
    headers = {h for module in project['modules'] for h in module['headers']}
    present = set(actual)
    # Every C file and every declared code path (a declared header can be included).
    for rel in sorted(p for p in actual if p.endswith(('.c', '.h')) or p in listed):
        problem = source_problem(rel, (base/rel).read_text(errors='replace'), forbidden, patterns, headers, present)
        if problem is not None:
            raise GateError(problem)
