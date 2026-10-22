"""EX-1: the per-project third-party lock (schemas/project-third-party.json). Host side; reads JSON and files only.

A project pins its own Python wheels and source archives in <project>/benchmarks/project/third_party/lock.json.
bench.json binds the lock by sha256 (bench_model._third_party_binding); the lock binds each part, provenance record and
notice by sha256 and carries a license record per item. Every path is relative to benchmarks/project/ and lies under
third_party/; a path that resolves outside that directory (a link on the way) is refused. The wheels enter the project
bench image (tools/project_image.py) under LAYER_PATH; the source archives never enter an image.

A first-party fixture wheel (origin kind first-party-fixture) has no tracked archive: the repository admits no first-party
archive (.githooks/personal_info_check.py). Its row names `source_dir` instead of parts, and build_source_wheel makes the
wheel bytes from that tracked directory by one deterministic rule (stored zip, sorted files, fixed time stamps and modes,
RECORD last); the lock sha256 and bytes bind the result.

FW-HOOK (fact F14), additive forms: a `retained` row binds upstream files that the project keeps without their upstream
archive (for example selected headers), with origin, provenance, notice and license; `files` of a wheel or source row binds
more upstream files of that row; a provenance or notice record may bind its `bytes`. Every such path passes the same path
rules, and verify_files checks every byte. No row binds the lock itself. The privacy hook exempts the content of a bound
file only when the lock binds its path, sha256 and size in a row with an allowlisted upstream origin (the schema's
$defs.exempt_origin_url); nothing of a retained row enters an image.

T6-R2 (ruling R27), host members: a wheel row of tracked parts may declare `host_members`, at most HOST_MEMBERS_MAX members
inside the wheel ({member, bytes, sha256}), each above PART_MAX_BYTES (the container file bound) and at most
HOST_MEMBER_MAX_BYTES. The extraction job (container/project-wheels.py) hashes such a member in bounded chunks and never
writes it; tools/project_image.py streams it from the verified wheel bytes into the layer. Any other member above the file
bound is refused.

T6-R3 (ruling R33): a wheel row may declare `notice_member`, the exact wheel member path of its license file, below its
dist-info directory or below `<dist>.data/data/` (notice_member_rules); the extraction job reads exactly that member as the
notice. A control character is refused in a host member and in a notice member path (T6R2-A03)."""
from __future__ import annotations
from pathlib import Path
import base64
import hashlib
import io
import os
import re
import stat
import zipfile
from evidence import GateError, read_json
from schema_check import validate

LOCK_DIR = 'third_party'
LOCK_FILE = 'third_party/lock.json'
LOCK_MAX_BYTES = 1048576
RECORD_MAX_BYTES = 1048576            # one provenance record or notice file
PART_MAX_BYTES = 33554432             # one tracked part (the container file bound)
ITEM_MAX_BYTES = 67108864             # one whole wheel or source archive
LAYER_PATH = '/opt/project-python'
LAYER_ROOT = 'opt/project-python/'
LAYER_MAX_BYTES = 201326592           # the extracted project layer (192 MiB), below the collector total of 256 MiB
LAYER_MAX_FILES = 3072
HOST_MEMBER_MAX_BYTES = 50331648      # T6-R2: one host member (a wheel member above PART_MAX_BYTES, the container file bound)
HOST_MEMBERS_MAX = 4                  # T6-R2: the host members of one wheel row
DATA_SCHEME = 'data'                  # T6-R3: the one admitted scheme of a wheel data directory (<dist>.data/data/)
CONTROL_CHARACTER = re.compile(r'[\x00-\x1f\x7f]')     # T6R2-A03: refused in a host member and a notice member path
SOURCE_MAX_FILES = 256               # one first-party fixture wheel source directory
SOURCE_FILE_MAX_BYTES = 1048576
FIXTURE_ROOT = 'tests/fixtures/'      # EX1-A01: only framework fixture projects may use the origin first-party-fixture
EXPORT_SET = 'starter-export.json'     # EX1-R1-01: the framework export set lists every framework-tracked file
EXPORT_MAX_BYTES = 4194304
PROJECT_AREA = 'benchmarks/project'
# EX1-A01: a first-party wheel source holds source text only: no compiled object by name or by magic, no NUL, UTF-8 only.
COMPILED_SUFFIXES = ('.so', '.pyd', '.dll', '.dylib', '.o', '.obj', '.a', '.lib', '.exe', '.pyc', '.pyo', '.whl', '.zip', '.egg')
COMPILED_MAGIC = (b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
                  b'MZ', b'!<arch>\n')


def escape(name):
    """The wheel filename and dist-info form of a distribution name (runs of other characters become '_')."""
    return re.sub(r'[^A-Za-z0-9.]+', '_', name)


def dist_info_name(name, version):
    return escape(name) + '-' + version + '.dist-info'


def compatible(filename):
    """The wheel tag rule of the bench interpreter (the rule of tools/acquire_bench_wheels.py compatible, kept here so that
    this module needs no acquisition tool): py3-none-any, or a manylinux x86_64 wheel for cp313 or abi3 of cp3x <= 13."""
    if not filename.endswith('.whl'):
        return False
    py, abi, plat = filename[:-4].split('-')[-3:]
    if (py, abi, plat) == ('py3', 'none', 'any'):
        return True
    linux = any(p.endswith('_x86_64') and p.startswith(('manylinux_2_', 'manylinux2014_', 'manylinux2010_', 'manylinux1_'))
                for p in plat.split('.'))
    return linux and ((py, abi) == ('cp313', 'cp313') or (abi == 'abi3' and py.startswith('cp3') and py[3:].isdigit() and int(py[3:]) <= 13))


def _resolve(base, rel):
    """base/rel: no link on the way below base, and the real path lies inside base/third_party."""
    top = Path(base) / LOCK_DIR
    path = Path(base) / rel
    for p in [path, *path.parents]:
        if p == Path(base):
            break
        if p.is_symlink():
            raise GateError('third-party path is not allowed: a symbolic link on the way: ' + rel)
    real, limit = os.path.realpath(path), os.path.realpath(top)
    if not real.startswith(limit.rstrip('/') + '/'):
        raise GateError('third-party path is not allowed: outside the project third_party directory: ' + rel)
    return path


def _items(value):
    return [('wheel', w) for w in value['wheels']] + [('source', s) for s in value['sources']]


def _retained(value):
    """FW-HOOK: the retained rows (upstream files kept without their archive); an older lock has none."""
    return value.get('retained', [])


def _export_set(root):
    """The file list of the framework export set (root/EXPORT_SET), or an empty set when it is missing or malformed."""
    path = Path(root) / EXPORT_SET
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > EXPORT_MAX_BYTES:
            return set()
        files = read_json(path).get('files')
    except (OSError, ValueError, AttributeError, GateError):
        return set()
    return {f for f in files if isinstance(f, str)} if isinstance(files, list) else set()


def fixture_project(project_dir, root=None):
    """EX1-A01, EX1-R1-01: True only for a framework-tracked fixture project: a literal relative path under tests/fixtures/
    (no '.', '..' or empty segment, no trailing '/'), whose real path under `root` is that literal path (no link on the
    way), and whose lock file the framework export set (starter-export.json of `root`) lists. A project can create its own
    tests/fixtures/<x>, but it is not in the export set; an edit of the export set changes a framework file, which the
    framework manifest check of `project check` reports. False without a root."""
    if root is None or not isinstance(project_dir, str) or not project_dir.startswith(FIXTURE_ROOT) or len(project_dir) <= len(FIXTURE_ROOT):
        return False
    parts = project_dir.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return False
    real_root = os.path.realpath(root)
    if os.path.realpath(os.path.join(real_root, project_dir)) != os.path.join(real_root, project_dir):
        return False
    return project_dir + '/' + PROJECT_AREA + '/' + LOCK_FILE in _export_set(root)


def unlisted_source_files(root, project_dir, base, source_dir):
    """EX1-R1-01: the files of a first-party fixture wheel source_dir (relative to `root`) that the framework export set
    does not list; [] when every file is listed."""
    listed = _export_set(root)
    top = Path(base) / source_dir
    prefix = project_dir + '/' + PROJECT_AREA + '/' + source_dir + '/'
    rels = sorted(prefix + p.relative_to(top).as_posix() for p in top.rglob('*') if not p.is_dir()) if top.is_dir() else [prefix]
    return [rel for rel in rels if rel not in listed]


def check_lock(root, base, value, reserved, project_dir=None):
    """The checks of a parsed lock `value` (schemas of `root`) of the project `project_dir` whose benchmarks/project
    directory is `base` (GateError on the first failure): the origin first-party-fixture only in a framework-tracked fixture
    project (EX1-A01, EX1-R1-01: fixture_project, and every source_dir file listed in the export set), the schema, unique
    names and paths, part sizes that add up, wheel filenames that match name, version
    and tag, a tag of the bench interpreter, a PyPI URL that names the file, modules outside `reserved` and not shared by
    two wheels, and every path inside the project third_party directory. FW-HOOK: the files of every row and the retained
    rows pass the same name and path rules, and no row binds the lock itself. T6-R2: the host members of a wheel row (none
    for a first-party fixture wheel, whose source files are at most SOURCE_FILE_MAX_BYTES) have distinct member paths, at
    most HOST_MEMBERS_MAX, each above PART_MAX_BYTES and at most HOST_MEMBER_MAX_BYTES. File contents are checked by
    verify_files."""
    validate(root, 'project-third-party', value)
    names, paths, leaves, modules = set(), set(), set(), set()

    def row_name(item):
        key = escape(item['name']).lower()
        if key in names:
            raise GateError('third-party lock repeats a name: ' + item['name'])
        names.add(key)
        if item['origin']['kind'] == 'first-party-fixture' and not fixture_project(project_dir, root):
            raise GateError('the origin first-party-fixture is allowed only in a framework-tracked fixture project under tests/fixtures/'
                            ' (listed in starter-export.json): ' + item['name'])

    def row_path(rel):
        if rel == LOCK_FILE:
            raise GateError('a third-party row cannot bind the lock itself: ' + rel)
        if rel in paths:
            raise GateError('third-party lock repeats a path: ' + rel)
        paths.add(rel)
        _resolve(base, rel)

    for kind, item in _items(value):
        row_name(item)
        built = item['origin']['kind'] == 'first-party-fixture' and kind == 'wheel'
        if built and 'source_dir' in item and unlisted_source_files(root, project_dir, base, item['source_dir']):
            raise GateError('a first-party fixture wheel source holds a file that is not framework-tracked (not in starter-export.json),'
                            ' so it is no framework-tracked fixture: ' + unlisted_source_files(root, project_dir, base, item['source_dir'])[0])
        if built != ('source_dir' in item) or (built and item['parts']) or (not built and not item['parts']):
            raise GateError('a first-party fixture wheel names source_dir and no parts; every other item names parts: ' + item['name'])
        if item['parts'] and sum(p['bytes'] for p in item['parts']) != item['bytes']:
            raise GateError('third-party parts do not add up to the item bytes: ' + item['name'])
        if item['origin']['kind'] == 'pypi' and not item['origin']['url'].endswith('/' + item['filename']):
            raise GateError('third-party URL does not name the file: ' + item['name'])
        if kind == 'wheel':
            if item['filename'] != escape(item['name']) + '-' + item['version'] + '-' + item['tag'] + '.whl':
                raise GateError('wheel filename does not match name, version and tag: ' + item['name'])
            if not compatible(item['filename']):
                raise GateError('wheel tag is not a tag of the bench interpreter: ' + item['name'])
            clash = sorted(set(item['modules']) & (set(reserved) | modules))
            if clash:
                raise GateError('wheel modules collide with container modules or another wheel: ' + ', '.join(clash))
            modules |= set(item['modules'])
            hosts = item.get('host_members', [])
            if hosts and built:
                raise GateError('a first-party fixture wheel declares no host member (its source files are at most '
                                f'{SOURCE_FILE_MAX_BYTES} bytes): ' + item['name'])
            if len({h['member'] for h in hosts}) != len(hosts):
                raise GateError('third-party lock repeats a host member: ' + item['name'])
            if len(hosts) > HOST_MEMBERS_MAX or any(not PART_MAX_BYTES < h['bytes'] <= HOST_MEMBER_MAX_BYTES for h in hosts):
                raise GateError(f'a host member lies outside its bounds (above {PART_MAX_BYTES} and at most {HOST_MEMBER_MAX_BYTES} '
                                f'bytes, at most {HOST_MEMBERS_MAX} per wheel): ' + item['name'])
            if any(CONTROL_CHARACTER.search(h['member']) for h in hosts):            # T6R2-A03: `$` of the schema admits a newline
                raise GateError('a host member path holds a control character: ' + item['name'])
            if 'notice_member' in item:
                notice_member_rules(item)
        for rel in ([p['path'] for p in item['parts']] + [item['provenance']['path'], item['notice']['path']] + ([item['source_dir']] if built else [])
                    + [f['path'] for f in item.get('files', [])]):
            row_path(rel)
        for leaf in [Path(p['path']).name for p in item['parts']] + ([item['filename']] if built else []):
            if leaf in leaves or leaf == 'lock.json':
                raise GateError('third-party part file names must be unique: ' + leaf)
            leaves.add(leaf)
    for item in _retained(value):
        row_name(item)
        for rel in [f['path'] for f in item['files']] + [item['provenance']['path'], item['notice']['path']]:
            row_path(rel)
    return value


def notice_member_rules(item):
    """T6-R3: the declared notice member of a wheel row has no control character and lies below the row's dist-info
    directory or below `<dist>.data/data/` (the first segment compared without case, as the extraction job does)."""
    member = item['notice_member']
    if CONTROL_CHARACTER.search(member):
        raise GateError('a notice member path holds a control character: ' + item['name'])
    head, _, rest = member.partition('/')
    stem = (escape(item['name']) + '-' + item['version']).lower()
    if not rest or not (head.lower() == stem + '.dist-info' or (head.lower() == stem + '.data' and rest.startswith(DATA_SCHEME + '/'))):
        raise GateError('a notice member lies outside the dist-info directory and the data scheme directory of its wheel: '
                        + item['name'])


def wheel_modules(value):
    return {m for w in (value or {}).get('wheels', []) for m in w['modules']}


def _read_file(path, limit, what):
    if not path.is_file() or path.is_symlink():
        raise GateError(what + ' is missing')
    with open(path, 'rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise GateError(what + f' exceeds {limit} bytes')
    return data


def verify_files(base, value):
    """Every part, retained file, provenance record and notice of a checked lock: a regular file with the bound size (where
    bound) and sha256; the joined parts of an item have its sha256. GateError on the first difference. Returns {item name:
    joined bytes size} of the wheel and source rows."""
    sizes = {}
    for _, item in _items(value):
        whole = hashlib.sha256()
        if 'source_dir' in item:
            whole.update(build_source_wheel(base, item))
        for p in item['parts']:
            data = _read_file(_resolve(base, p['path']), PART_MAX_BYTES, 'third-party part ' + p['path'])
            if len(data) != p['bytes'] or hashlib.sha256(data).hexdigest() != p['sha256']:
                raise GateError('third-party part differs from the lock: ' + p['path'])
            whole.update(data)
        if whole.hexdigest() != item['sha256']:
            raise GateError('third-party item differs from the lock: ' + item['name'])
        _verify_records(base, item)
        sizes[item['name']] = item['bytes']
    for item in _retained(value):
        _verify_records(base, item)
    return sizes


def _verify_records(base, item):
    """FW-HOOK: the retained files of a row (`files`: size and sha256) and its provenance record and notice (sha256, and
    the size when the record binds one). GateError on the first difference."""
    for ref in item.get('files', []):
        data = _read_file(_resolve(base, ref['path']), PART_MAX_BYTES, 'third-party file ' + ref['path'])
        if len(data) != ref['bytes'] or hashlib.sha256(data).hexdigest() != ref['sha256']:
            raise GateError('third-party file differs from the lock: ' + ref['path'])
    for key in ('provenance', 'notice'):
        ref = item[key]
        data = _read_file(_resolve(base, ref['path']), RECORD_MAX_BYTES, f'third-party {key} ' + ref['path'])
        if hashlib.sha256(data).hexdigest() != ref['sha256'] or ('bytes' in ref and len(data) != ref['bytes']):
            raise GateError(f'third-party {key} differs from the lock: ' + ref['path'])


def build_source_wheel(base, item):
    """The bytes of a first-party fixture wheel, made from its tracked source_dir by the deterministic rule: every regular
    file (no link, at most SOURCE_MAX_FILES files of at most SOURCE_FILE_MAX_BYTES each, no RECORD), sorted by path, then a
    RECORD with urlsafe sha256 digests; stored entries, time stamp 1980-01-01, mode 0644. GateError for any other tree."""
    top = _resolve(base, item['source_dir'])
    if not top.is_dir():
        raise GateError('first-party wheel source_dir is missing: ' + item['source_dir'])
    files = []
    for path in sorted(top.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise GateError('first-party wheel source holds a link or a special file: ' + item['source_dir'])
        files.append(path.relative_to(top).as_posix())
    infos = sorted({f.rsplit('/', 1)[0] for f in files if f.endswith('.dist-info/WHEEL')})
    if (len(files) > SOURCE_MAX_FILES or len(infos) != 1 or '/' in infos[0] or
            any(f.endswith('.dist-info/RECORD') for f in files)):
        raise GateError('first-party wheel source is not one wheel tree: ' + item['source_dir'])
    bodies = {}
    for rel in sorted(files):
        with open(top / rel, 'rb') as f:
            bodies[rel] = f.read(SOURCE_FILE_MAX_BYTES + 1)
        if len(bodies[rel]) > SOURCE_FILE_MAX_BYTES:
            raise GateError('first-party wheel source file exceeds its bound: ' + rel)
        problem = source_text_problem(rel, bodies[rel])
        if problem:
            raise GateError('first-party wheel source holds ' + problem + ': ' + rel)
    record = ''.join(rel + ',sha256=' + base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip('=') + ','
                     + str(len(body)) + '\n' for rel, body in bodies.items()) + infos[0] + '/RECORD,,\n'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as archive:
        for rel, body in list(bodies.items()) + [(infos[0] + '/RECORD', record.encode())]:
            entry = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system, entry.external_attr = 3, 0o644 << 16
            archive.writestr(entry, body)
    return out.getvalue()


def source_text_problem(rel, body):
    """EX1-A01: None for source text; else why the file is no source text (a compiled-object name, a compiled-object magic,
    a NUL byte or bytes that are not UTF-8)."""
    name = rel.rsplit('/', 1)[-1].lower()
    if name.endswith(COMPILED_SUFFIXES) or '.so.' in name:
        return 'a compiled object name'
    if body.startswith(COMPILED_MAGIC):
        return 'a compiled object (ELF, Mach-O, PE or archive magic)'
    if b'\0' in body:
        return 'binary data'
    try:
        body.decode('utf-8')
    except UnicodeDecodeError:
        return 'bytes that are not UTF-8 text'
    return None


def wheel_bytes(base, item):
    """The whole bytes of a wheel row: built from source_dir, or the joined parts (each read as verify_files reads it)."""
    if 'source_dir' in item:
        return build_source_wheel(base, item)
    return b''.join(_read_file(_resolve(base, p['path']), PART_MAX_BYTES, 'third-party part ' + p['path']) for p in item['parts'])


def plan_entry(value):
    """The coordinator plan key `project_wheels` of a lock with wheels: the layer path, the exact dist-info names and the
    wheel modules."""
    return {'path': LAYER_PATH, 'dist_info': sorted(dist_info_name(w['name'], w['version']) for w in value['wheels']),
            'modules': sorted(wheel_modules(value))}
