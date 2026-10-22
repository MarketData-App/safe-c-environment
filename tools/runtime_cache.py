"""FR4-IMG-BOUND-01: evict the per-project runtime cache images that no container uses, before an owned-image count.

tools/project_check.py imports each project's runtime image on demand (label org.safe-c.project-runtime=1) and
re-creates it when it is gone, so such a cache is safe to remove while no container uses it. The developer image
assembler (tools/assemble_developer_image.py) counts every safe-c- image toward max_owned_images; it is a pinned
acquisition recipe (developer.lock.json assembly_recipe_sha256), so it does not call this module.

FR7b-A01: the command takes the launcher lock /tmp/safe-c-launcher.lock itself, with a bounded wait, and removes
nothing without it. Run it directly (`python3 tools/runtime_cache.py`), not under flock(1) of that lock: an outer
holder makes it wait and then refuse. Every agent command that starts containers runs under the same lock, so they
are excluded while it runs. The lock is an operator convention; Launcher.create does not take it. So, under the
lock, the command also needs zero safe-c containment containers (running or stopped) before it lists any image: a
project check of a process that does not follow the convention BLOCKS the eviction instead of losing its cache
between inspect and create (that loss would be fail-closed in any case).

FR7b-A02: an image is a cache only when it has the label value 1, the project-name label, at least one tag and only
runtime cache tags. A child image built FROM a cache inherits the label but has no cache tag, so it is kept. The
command never removes any other image, never forces a removal and never prunes.

EX-1: the project bench image (tools/project_image.py; label org.safe-c.project-bench=1, tags safe-c-project-bench:) is
a second cache kind: it is content-addressed and rebuilt offline from the project's tracked pinned wheels. The same rules
apply to it, per kind: an image is a cache only when exactly one kind label is present, its value is 1, and every tag
is a tag of that kind. cache_ids lists both kinds; max_owned_images bounds them together (the project runtime import and
the project bench build count this union before they add an image)."""
from pathlib import Path
import fcntl
import json
import os
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from evidence import GateError, loads_capped, passed, read_json  # noqa: E402

LABEL_KEY = 'org.safe-c.project-runtime'
LABEL = LABEL_KEY + '=1'
NAME_KEY = 'org.safe-c.project-name'
CONTAINMENT_LABEL = 'org.safe-c.containment=1'
TAG_PREFIX = 'safe-c-project-runtime:'
BENCH_LABEL_KEY = 'org.safe-c.project-bench'
BENCH_TAG_PREFIX = 'safe-c-project-bench:'
KINDS = {LABEL_KEY: TAG_PREFIX, BENCH_LABEL_KEY: BENCH_TAG_PREFIX}      # cache kind label -> its tag prefix
ID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')
MAX_IMAGES = 64
LAUNCHER_LOCK = '/tmp/safe-c-launcher.lock'
LOCK_WAIT_SECONDS = 60


class HeldLock:
    """The launcher lock held by this process (made only by acquire_lock)."""
    def __init__(self, fd):
        self.fd = fd
        self.held = True

    def release(self):
        if self.held:
            self.held = False
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)


def acquire_lock(path=LAUNCHER_LOCK, wait_seconds=LOCK_WAIT_SECONDS, clock=time.monotonic, sleep=time.sleep):
    """Takes the exclusive launcher lock, polling once a second for at most `wait_seconds`; GateError when another
    holder keeps it (also an outer flock(1) of this command) or the file cannot be opened."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise GateError('launcher lock unavailable') from exc
    deadline = clock() + wait_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return HeldLock(fd)
        except BlockingIOError:
            if clock() >= deadline:
                os.close(fd)
                raise GateError('launcher lock is held by another command; nothing removed') from None
            sleep(1.0)


def _require(lock):
    if not isinstance(lock, HeldLock) or not lock.held:
        raise GateError('the launcher lock is not held; nothing removed')


def cache_ids(docker):
    """The sorted image ids that carry a cache kind label (both kinds, KINDS); GateError when a listing fails or is
    malformed."""
    ids = set()
    for key in sorted(KINDS):
        listed = docker(['image', 'ls', '--no-trunc', '--filter', 'label=' + key + '=1', '--format', '{{.ID}}'])
        if not passed(listed):
            raise GateError('runtime cache inventory unavailable')
        ids |= set(listed['output'].split())
    if len(ids) > MAX_IMAGES or not all(ID_RE.fullmatch(i) for i in ids):
        raise GateError('runtime cache inventory malformed')
    return sorted(ids)


def _exact_cache(docker, identity):
    """True when `identity` is exactly a cache image of one kind: its inspect Id is the identity, exactly one kind label
    is present and its value is 1, it has a project-name label, and it has at least one tag and every tag is a tag of
    that kind."""
    info = docker(['image', 'inspect', identity])
    if not passed(info):
        return False
    try:
        rows = loads_capped(info['output'])
    except ValueError:
        return False
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return False
    obj = rows[0]
    labels = (obj.get('Config') or {}).get('Labels') or {}
    tags = obj.get('RepoTags')
    if not isinstance(labels, dict):
        return False
    kinds = [key for key in KINDS if key in labels]
    if len(kinds) != 1:
        return False
    prefix = KINDS[kinds[0]]
    return (obj.get('Id') == identity and labels.get(kinds[0]) == '1'
            and isinstance(labels.get(NAME_KEY), str) and labels[NAME_KEY] != ''
            and isinstance(tags, list) and len(tags) >= 1
            and all(isinstance(t, str) and t.startswith(prefix) for t in tags))


def evict_unused(docker, lock):
    """`docker(args)` gives a bounded command result (Launcher.docker); `lock` is the HeldLock of acquire_lock (else
    GateError before any docker call). Lists the images with a cache kind label (cache_ids); for each one, checks it again by
    inspect (_exact_cache) and lists every container, running or stopped, created from it; removes it (`image rm`, no
    force) only when it is exactly a cache and no container uses it. Returns {'evicted', 'kept' (a container uses it),
    'refused' (not exactly a cache, or a docker step failed)}; GateError when the inventory is unavailable or
    malformed."""
    _require(lock)
    ids = cache_ids(docker)
    result = {'evicted': [], 'kept': [], 'refused': []}
    for identity in ids:
        _require(lock)
        if not _exact_cache(docker, identity):
            result['refused'].append(identity)
            continue
        users = docker(['ps', '--all', '--no-trunc', '--quiet', '--filter', 'ancestor=' + identity])
        if not passed(users):
            result['refused'].append(identity)
            continue
        if users['output'].split():
            result['kept'].append(identity)
            continue
        removed = docker(['image', 'rm', identity])
        result['evicted' if passed(removed) else 'refused'].append(identity)
    return result


def run(docker, lock):
    """Under the held lock: GateError when any safe-c containment container exists (running or stopped); then
    evict_unused."""
    _require(lock)
    active = docker(['ps', '--all', '--no-trunc', '--quiet', '--filter', 'label=' + CONTAINMENT_LABEL])
    if not passed(active):
        raise GateError('containment container inventory unavailable')
    if active['output'].split():
        raise GateError('safe-c containment containers are active; nothing removed')
    return evict_unused(docker, lock)


def main():
    lock = acquire_lock()
    try:
        from container_policy import Launcher
        launcher = Launcher(ROOT, Path(tempfile.mkdtemp(prefix='safe-c-runtime-cache-')), read_json(ROOT / 'toolchain.lock.json'))
        result = run(launcher.docker, lock)
    finally:
        lock.release()
    print(json.dumps({'status': 'PASS', **{k: len(v) for k, v in result.items()}, 'evicted_ids': [i[:19] for i in result['evicted']]}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__,
                          'property': str(error) if isinstance(error, GateError) else None}))
        raise SystemExit(1)
