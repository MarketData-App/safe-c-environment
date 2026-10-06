# Project CI, Framework Manifest and Portable Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project created from this starter runs every framework code gate on its own code with `./tools/safety project check` in about 6–10 minutes on any capable Linux x86-64 host, while the full framework qualification stays in this repository.

**Architecture:** A capability check replaces the machine-pinned Docker preflight. A tracked `framework-manifest.json` proves that a project runs a qualified framework file set. A new host module (`tools/project_check.py`) runs 23 code gates inside one `project` container from the SDK image and starts the built program in a runtime image; `project.json` declares targets, tests, fuzz targets and modules, never flags. `instantiate` creates a project in project mode with the hello-world example as starting code.

**Tech Stack:** Python 3 host tooling (jsonschema 4.19.2), CMake/Ninja/CTest, GCC and Clang toolchains, sanitizers, clang-tidy, Clang Static Analyzer, GCC analyzer, libFuzzer, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-06-project-ci-design.md`

## Global Constraints

- Platform: Linux x86-64 only. Windows, macOS and ARM64 are out of scope.
- Every native build, test, analyzer, sanitizer, fuzz and runtime operation runs through the protected Docker launcher (`tools/container_policy.py` `Launcher`). No host fallback, no arbitrary Docker flags, no daemon-socket or home mounts, no privileged containers.
- Never weaken a warning, sanitizer, analyzer, coverage threshold (line 90, branch 85 from `safety/contract.json`) or resource limit.
- Output hygiene (AGENTS.md "Agent context amendment"): never print raw evidence `output` fields, sanitizer/leak/race reports, backtraces, Python tracebacks, seeded-defect sources or mutation code; bound every command's output.
- Commits use the noreply identity; `core.hooksPath .githooks` stays enabled; never `--no-verify`.
- `tools/cli.py`, `AGENTS.md`, `docs/agent-development-quickstart.md` and the other files in `tools/developer_acceptance.py:101-113` are in the developer tooling identity. Edit them only in the tasks that say so; Task 12 repeats the live trial.
- Framework unit tests run only inside Docker through `./tools/safety check-fast`. When several worktrees run it, serialize with `flock /tmp/safe-c-launcher.lock ./tools/safety check-fast` (the launcher admits at most 4 containers).
- Evidence collector limits per checkout: 20000 files, 2 GiB under `artifacts/`. Never change limits or delete evidence; archive with `artifacts/resume/archive_*` helpers.
- New first-party `*.c` files must be listed in `safety/source-inventory.json` with sha256, role and targets; every new tracked file must be added to `starter-export.json`.
- Protected changes (policy, schemas, contract, fixtures, CMake helpers, launcher, AGENTS.md) need one adversarial agent approver (docs/approval-protocol.md) before the final push.
- Project fuzz exploration budget: 30 seconds per target by default, never lower.

## Review Focus

1. A project whose `CMakeLists.txt`, source pragmas or `project.json` try to weaken flags (for example `#pragma GCC diagnostic ignored`, `__attribute__((no_sanitize))`, extra keys in `project.json`) — expected: a gate fails with the offending file. Test: Task 6 Step 1 case `weakening-attempts`.
2. A project with zero modules or an empty `src/` — expected: `project check` stops with "no project code declared", not a vacuous PASS. Test: Task 2 Step 1 `test_empty_project_rejected`.
3. A host without AppArmor and without SELinux, or with a remote Docker endpoint — expected: BLOCKED naming the missing capability before any container exists. Test: Task 1 Step 1.
4. A file added under `tools/` or `safety/` in a project after instantiation — expected: manifest mismatch naming the file and requiring `./tools/safety ci`. Test: Task 2 Step 1 `test_manifest_detects_added_framework_file`.
5. Project paths with spaces or non-ASCII characters (the starter export already names a child "first project with space") — expected: every gate handles them. Test: Task 6 Step 1 case `path-with-space`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `tools/host_capabilities.py` (new) | Pure decision function for host capability problems | 1 |
| `tools/container_policy.py` (modify) | Use capability check; LSM-dependent security options; `project` profile; `purpose='project'` | 1 |
| `safety/container-policy.json`, `schemas/container-policy.json` (modify) | Portable `runner` block; `project` profile | 1 |
| `tools/containment.py`, `safety/containment-fixtures.json` (modify) | Replace `wrong-daemon` sabotage with `remote-endpoint` and `missing-lsm` | 1 |
| `tools/developer.py`, `tools/image_transfer.py` (modify) | Accept the LSM-dependent security options and local context endpoints | 1 |
| `tools/project_model.py` (new) | Load/validate `project.json`; project paths; framework file set; manifest write/check; project inventory | 2 |
| `schemas/project.json`, `schemas/framework-manifest.json`, `schemas/project-policy.json`, `schemas/project-report.json` (new) | Schemas | 2 |
| `safety/project-policy.json` (new) | Project gate list, fuzz budget, coverage reference, flag audit | 2 |
| `examples/hello-world/**` (new) | Complete example project | 3 |
| `cmake/Project.cmake` (new), `CMakeLists.txt` (modify) | Targets from `project.json`; project mode switch | 4 |
| `container/foundation-policy.py` (modify) | Optional extra include directories for project scans | 4 |
| `ci/image-bundle.json`, `ci/controller-requirements.txt` (modify/new) | Published image asset; hashed controller dependencies | 5 |
| `tools/project_check.py` (new), `container/project-fuzz-build.sh` (new) | Gate runner: one `project` container, runtime start, report | 6 |
| `tools/cli.py`, `tools/starter.py`, `tools/policy.py`, `tools/developer.py`, `safety/source-inventory.json`, `starter-export.json` (modify) | `project` and `framework` subcommands; project-mode instantiate; project-mode source rules | 7 |
| `.github/workflows/example.yml`, `ci/project-ci.yml` (new); `.github/workflows/safety.yml` (modify) | CI workflows | 8 |
| `AGENTS.md`, `docs/agent-development-quickstart.md`, `README.md`, `ci/README.md`, `docs/approval-protocol.md`, `specs/github-runner-migration.md` (modify) | Documentation and agent rules | 9 |
| `safety/project-gate-fixtures/**`, `tools/project_selftest.py` (new); `safety/contract.json`, `schemas/contract.json` (modify) | Framework gate `project-gates`: one seeded defect per project gate | 10 |
| `framework-manifest.json` (new, generated) | Qualified framework file set | 11 |

**Parallel waves.** Wave 1: Tasks 1, 2, 3, 4, 5 (separate worktrees, no shared files). Wave 2: Task 6, then Tasks 7 and 8 in parallel. Wave 3: Tasks 9 and 10 in parallel. Then Task 11 and Task 12 in sequence.

---

### Task 1: Portable capability check (replaces the machine pin)

**Files:**
- Create: `tools/host_capabilities.py`
- Modify: `tools/container_policy.py:30,106-151,169-251`, `safety/container-policy.json:4-12` (runner) and profiles, `schemas/container-policy.json`, `tools/containment.py:259-277`, `safety/containment-fixtures.json` (P01 variants near L238 and L298), `tools/developer.py:268-273`, `tools/image_transfer.py:196-200`
- Test: `tests/unit/test_containment.py` (new class `HostCapabilityTests`)

**Interfaces:**
- Produces: `host_problems(info: dict, context: dict, environ: dict, core_pattern: str) -> list[str]` (empty list = host qualifies); `security_options(info: dict) -> list[str]` returning `['no-new-privileges','apparmor=docker-default']` when AppArmor is active, `['no-new-privileges','label=type:container_t']` when SELinux is active; `Launcher(root, run_dir, lock, *, purpose)` accepts `purpose='project'`; policy profile `project`.
- New `runner` block: `{"role": "portable", "endpoint_scheme": "unix", "architecture": "x86_64", "cgroup_version": "2", "lsm": ["apparmor", "selinux"]}`.
- New profile `project`: memory 3 GiB, swap 0, cpus 2, pids 256, work 4 GiB, tmp 256 MiB, run 1 MiB, shm 64 MiB, work_inodes 262144, wall_seconds 1500, network none, executable_work true. It must fit `aggregate` (12 GiB, 8 cpus, 512 pids).

- [ ] **Step 1: Write the failing tests**

```python
class HostCapabilityTests(unittest.TestCase):
    def info(self, **kw):
        base={'ID':'any-daemon','Architecture':'x86_64','CgroupVersion':'2','MemoryLimit':True,'SwapLimit':True,
              'PidsLimit':True,'CpuCfsQuota':True,'CpuCfsPeriod':True,
              'SecurityOptions':['name=seccomp,profile=builtin','name=apparmor','name=cgroupns']}
        base.update(kw); return base
    def ctx(self, endpoint='unix:///var/run/docker.sock'): return {'Name':'default','Endpoints':{'docker':{'Host':endpoint}}}
    def test_any_daemon_id_qualifies(self):
        from host_capabilities import host_problems
        self.assertEqual(host_problems(self.info(ID='other'),self.ctx(),{},'core'),[])
    def test_rootless_socket_qualifies(self):
        from host_capabilities import host_problems
        self.assertEqual(host_problems(self.info(),self.ctx('unix:///run/user/1000/docker.sock'),{},'core'),[])
    def test_selinux_qualifies_without_apparmor(self):
        from host_capabilities import host_problems
        i=self.info(SecurityOptions=['name=seccomp,profile=builtin','name=selinux'])
        self.assertEqual(host_problems(i,self.ctx(),{},'core'),[])
    def test_rejections_name_the_capability(self):
        from host_capabilities import host_problems
        cases=[(self.info(SecurityOptions=['name=seccomp,profile=builtin']),self.ctx(),{},'core','linux-security-module'),
               (self.info(SecurityOptions=['name=apparmor']),self.ctx(),{},'core','seccomp'),
               (self.info(),self.ctx('tcp://10.0.0.1:2376'),{},'core','local-unix-endpoint'),
               (self.info(),self.ctx('ssh://host'),{},'core','local-unix-endpoint'),
               (self.info(),self.ctx(),{'DOCKER_HOST':'unix:///x'},'core','inherited-docker-setting'),
               (self.info(CgroupVersion='1'),self.ctx(),{},'core','cgroup-v2'),
               (self.info(Architecture='aarch64'),self.ctx(),{},'core','architecture'),
               (self.info(PidsLimit=False),self.ctx(),{},'core','resource-controllers'),
               (self.info(),self.ctx(),{},'|/usr/lib/systemd/systemd-coredump','core-handling')]
        for info,ctx,env,core,expected in cases:
            with self.subTest(expected=expected):
                problems=host_problems(info,ctx,env,core)
                self.assertTrue(any(expected in p for p in problems),problems)
    def test_security_options_follow_the_lsm(self):
        from host_capabilities import security_options
        self.assertIn('apparmor=docker-default',security_options(self.info()))
        self.assertIn('label=type:container_t',security_options(self.info(SecurityOptions=['name=seccomp','name=selinux'])))
    def test_project_profile_is_in_policy(self):
        value=policy(ROOT); self.assertIn('project',value['profiles']); self.assertEqual(value['profiles']['project']['network'],'none')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `flock /tmp/safe-c-launcher.lock ./tools/safety check-fast; python3 tools/diagnostic_summary.py artifacts/bootstrap-report.json --case-id unit | tail -n 5`
Expected: the `unit` gate FAILS (`ModuleNotFoundError: host_capabilities` counted as an error).

- [ ] **Step 3: Implement `tools/host_capabilities.py`**

```python
"""Portable Docker host capability decision; no machine identity is pinned."""
INHERITED=('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','DOCKER_API_VERSION','DOCKER_CONFIG')
CONTROLLERS=('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod')

def active_lsm(info):
    joined=' '.join(info.get('SecurityOptions') or [])
    return 'apparmor' if 'apparmor' in joined else 'selinux' if 'selinux' in joined else None

def host_problems(info, context, environ, core_pattern):
    problems=[f'inherited-docker-setting: {k}' for k in INHERITED if environ.get(k)]
    endpoint=((context.get('Endpoints') or {}).get('docker') or {}).get('Host','')
    if not endpoint.startswith('unix:///'):problems.append('local-unix-endpoint: active context endpoint is not a local Unix socket')
    if info.get('Architecture')!='x86_64':problems.append('architecture: x86_64 required')
    if str(info.get('CgroupVersion'))!='2':problems.append('cgroup-v2: cgroup v2 required')
    missing=[k for k in CONTROLLERS if not info.get(k)]
    if missing:problems.append('resource-controllers: '+','.join(missing))
    if not any('seccomp' in s for s in info.get('SecurityOptions') or []):problems.append('seccomp: seccomp required')
    if active_lsm(info) is None:problems.append('linux-security-module: AppArmor or SELinux required')
    if core_pattern.strip().startswith('|'):problems.append('core-handling: piped core handler requires operator review')
    return problems

def security_options(info):
    return ['no-new-privileges','apparmor=docker-default'] if active_lsm(info)=='apparmor' else ['no-new-privileges','label=type:container_t']
```

- [ ] **Step 4: Rewire `Launcher.preflight()` and `create()`**

In `tools/container_policy.py`: in `preflight()` replace L129–139 with: run `docker context inspect` (fixed argv `['/usr/bin/docker','context','inspect']`, bounded 15 s), parse JSON list `[0]`, read `/proc/sys/kernel/core_pattern`, call `host_problems(info, context, os.environ, core)`, raise `GateError('host capability check failed: '+'; '.join(problems))` when non-empty. Build `self.prefix` with `--host <endpoint>` taken from the inspected context instead of `value['runner']['endpoint']`. Keep image, size, core and identity recording (L140–150); add `'lsm': active_lsm(info)` to `runner_identity`. In `create()` replace the fixed `--security-opt=no-new-privileges` and `--security-opt=apparmor=docker-default` with `--security-opt=<o>` for each `security_options(info)` (store `info` from preflight on `self`). In `effective()` accept either `docker-default (enforce)` or an SELinux `container_t` context in the probe (L242). Add `'project'` to the profile name set at L30 and `'project'` to the allowed `purpose` values. Update `schemas/container-policy.json` (`runner` properties: `role` const `portable`, `endpoint_scheme` const `unix`, `architecture` const `x86_64`, `cgroup_version` const `"2"`, `lsm` array const `["apparmor","selinux"]`; add `project` to `profiles.required` and properties with the same sub-schema as `build`) and `safety/container-policy.json` (new runner block; `project` profile values from Interfaces).

- [ ] **Step 5: Replace the daemon sabotage**

In `tools/containment.py:271-274` replace the `wrong-daemon` variant with `remote-endpoint` (context endpoint `tcp://127.0.0.1:1`, expected BLOCKED with `local-unix-endpoint`) and `missing-lsm` (fake `SecurityOptions` without AppArmor/SELinux injected through `host_problems`, expected `linux-security-module`). Update the P01 inventory in `safety/containment-fixtures.json` (`docker-or-controller-unavailable/wrong-daemon` → `remote-endpoint`, add `missing-lsm`), recompute `helper_sha256` only if `probe.py` changes (it does not). In `tools/developer.py:268-273` compare `SecurityOpt` with `security_options(launcher.info)`. In `tools/image_transfer.py:196-200` replace the context-name check with `host_problems` on the inspected context.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `flock /tmp/safe-c-launcher.lock ./tools/safety check-fast; python3 -c "import json;r=json.load(open('artifacts/bootstrap-report.json'));print({g['name']:g['status'] for g in r['gates']})" | tr ',' '\n' | grep -v PASS | head`
Expected: no gate other than the expected scoped BLOCKED overall state; `unit` PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/host_capabilities.py tools/container_policy.py safety/container-policy.json schemas/container-policy.json tools/containment.py safety/containment-fixtures.json tools/developer.py tools/image_transfer.py tests/unit/test_containment.py starter-export.json
git commit -m "feat: replace the machine-pinned Docker preflight with a portable capability check"
```

---

### Task 2: Project model, schemas and framework manifest

**Files:**
- Create: `tools/project_model.py`, `schemas/project.json`, `schemas/framework-manifest.json`, `schemas/project-policy.json`, `schemas/project-report.json`, `safety/project-policy.json`
- Test: `tests/unit/test_project_model.py`

**Interfaces:**
- Produces:
  - `PROJECT_PATHS = ('src/','include/','tests/project/','fuzz/project/','specs/project/','review/')`, `MANIFEST='framework-manifest.json'`, `PROJECT_FILE='project.json'`
  - `load_project(root: Path, project_dir: str='.') -> dict` (schema-validated, every path relative to `project_dir`, raises `GateError`)
  - `project_files(root: Path, project_dir: str) -> dict[str,str]` (relative path → sha256 under project paths of that directory)
  - `framework_files(root: Path) -> dict[str,str]` (`policy.source_files(root)` minus root project paths, `project.json`, the manifest and `.github/workflows/project-ci.yml`)
  - `write_manifest(root: Path, report: dict, images: dict) -> dict` and `check_manifest(root: Path) -> list[str]` (list of `added|removed|changed: <path>`)
  - `project_inventory(root: Path, project_dir: str, project: dict) -> None` (raises on an unlisted file, a module without spec or tests, a missing fuzz target for a module that declares `reads_external_input`, zero modules)
  - `project_policy(root) -> dict` (validated `safety/project-policy.json`)
- `project.json` schema (exact):

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":false,
 "required":["schema_version","name","modules","programs","run"],
 "properties":{
  "schema_version":{"const":1},
  "name":{"type":"string","pattern":"^[a-z][a-z0-9-]{1,62}$"},
  "modules":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":false,
    "required":["name","spec","sources","headers","tests","reads_external_input","fuzz"],
    "properties":{"name":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,62}$"},
      "spec":{"type":"string","pattern":"^specs/project/[A-Za-z0-9._ -]+\\.md$"},
      "sources":{"type":"array","items":{"type":"string","pattern":"^src/[^\\0]+\\.c$"}},
      "headers":{"type":"array","items":{"type":"string","pattern":"^include/[^\\0]+\\.h$"}},
      "tests":{"type":"array","minItems":1,"items":{"type":"string","pattern":"^tests/project/[^\\0]+\\.c$"}},
      "reads_external_input":{"type":"boolean"},
      "fuzz":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["name","harness","corpus","regressions"],
        "properties":{"name":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,62}$"},"harness":{"type":"string","pattern":"^fuzz/project/[^\\0]+\\.c$"},
          "corpus":{"type":"string","pattern":"^fuzz/project/"},"regressions":{"type":"string","pattern":"^fuzz/project/"}}}}}}},
  "programs":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":false,"required":["name","main","modules"],
    "properties":{"name":{"type":"string","pattern":"^[a-z][a-z0-9_-]{0,62}$"},"main":{"type":"string","pattern":"^src/[^\\0]+\\.c$"},
      "modules":{"type":"array","minItems":1,"items":{"type":"string"}}}}},
  "run":{"type":"object","additionalProperties":false,"required":["program","args","expect_exit"],
    "properties":{"program":{"type":"string"},"args":{"type":"array","maxItems":16,"items":{"type":"string","maxLength":256}},"expect_exit":{"const":0}}}}}
```

- `safety/project-policy.json` (exact): `{"schema_version":1,"gates":["format","gcc-O0","gcc-O2","clang-O0","clang-O2","hardened","tidy","csa","gcc-analyzer","ast","asan","ubsan","integer","msan","tsan","unit","integration","coverage","fuzz-replay","fuzz-exploration","clusterfuzzlite","inventory","review-protocol"],"fuzz_seconds":30,"coverage_source":"safety/contract.json","forbidden_text":["#pragma GCC diagnostic","#pragma clang diagnostic","no_sanitize","__attribute__((optimize","NOLINT"]}`
- `framework-manifest.json` schema: `{"schema_version":1,"framework_identity":"<64hex>","files":{"<path>":"<64hex>"},"images":{"sdk":"sha256:<64hex>","developer":"sha256:<64hex>","archive_sha256":"<64hex>"},"qualification":{"run_id":"<32hex>","source_identity":"<64hex>","overall_state":"VALIDATED_UNSEALED"}}` with `additionalProperties:false` everywhere.

- [ ] **Step 1: Write the failing tests**

```python
import json, sys, tempfile, unittest, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
import project_model as pm
ROOT=Path(__file__).resolve().parents[2]

def tree(base, files):
    for rel,text in files.items():
        p=base/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)

PROJECT={'schema_version':1,'name':'demo-app','modules':[{'name':'greeting','spec':'specs/project/greeting.md','sources':['src/greeting.c'],
  'headers':['include/greeting.h'],'tests':['tests/project/test_greeting.c'],'reads_external_input':True,
  'fuzz':[{'name':'greeting','harness':'fuzz/project/greeting_fuzz.c','corpus':'fuzz/project/corpus/greeting','regressions':'fuzz/project/regressions/greeting'}]}],
  'programs':[{'name':'hello','main':'src/main.c','modules':['greeting']}],'run':{'program':'hello','args':['world'],'expect_exit':0}}

class ProjectModelTests(unittest.TestCase):
    def make(self, d, project=PROJECT, extra=None):
        files={'project.json':json.dumps(project),'specs/project/greeting.md':'# spec','src/greeting.c':'int x;','src/main.c':'int main(void){return 0;}',
               'include/greeting.h':'int x;','tests/project/test_greeting.c':'int main(void){return 0;}','fuzz/project/greeting_fuzz.c':'int y;',
               'fuzz/project/corpus/greeting/seed':'a','fuzz/project/regressions/greeting/.keep':''}
        files.update(extra or {}); tree(d,files)
    def test_valid_project_loads_and_inventories(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); p=pm.load_project(d); pm.project_inventory(d,'.',p)
    def test_empty_project_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,modules=[]))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_flags_or_unknown_keys_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,cflags=['-w']))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_unlisted_project_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'src/extra.c':'int z;'})
            with self.assertRaises(GateError): pm.project_inventory(d,'.',pm.load_project(d))
    def test_external_input_module_needs_fuzz(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],fuzz=[]); d=Path(t); self.make(d,dict(PROJECT,modules=[m]))
            with self.assertRaises(GateError): pm.project_inventory(d,'.',pm.load_project(d))
    def test_paths_with_space_and_unicode(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],spec='specs/project/grüße plan.md'); d=Path(t)
            self.make(d,dict(PROJECT,modules=[m]),{'specs/project/grüße plan.md':'# spec'})
            pm.project_inventory(d,'.',pm.load_project(d))
    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],sources=['src/../tools/x.c']); d=Path(t); self.make(d,dict(PROJECT,modules=[m]))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_manifest_detects_added_removed_changed_framework_file(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'tools/a.py':'a','safety/b.json':'{}'})
            files=pm.framework_files(d); ident=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
            (d/pm.MANIFEST).write_text(json.dumps({'schema_version':1,'framework_identity':ident,'files':files,
              'images':{'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64},
              'qualification':{'run_id':'d'*32,'source_identity':'e'*64,'overall_state':'VALIDATED_UNSEALED'}}))
            self.assertEqual(pm.check_manifest(d),[])
            (d/'tools/new.py').write_text('n'); (d/'safety/b.json').write_text('{"x":1}'); (d/'tools/a.py').unlink()
            self.assertEqual(sorted(pm.check_manifest(d)),['added: tools/new.py','changed: safety/b.json','removed: tools/a.py'])
    def test_project_paths_are_not_framework_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); self.assertFalse(any(p.startswith(pm.PROJECT_PATHS) or p=='project.json' for p in pm.framework_files(d)))
    def test_project_policy_lists_23_gates(self):
        self.assertEqual(len(pm.project_policy(ROOT)['gates']),23)
```

- [ ] **Step 2: Run to verify failure** — `flock /tmp/safe-c-launcher.lock ./tools/safety check-fast`; expected `unit` FAIL (`ModuleNotFoundError: project_model`).

- [ ] **Step 3: Implement `tools/project_model.py`**

Implement exactly the Interfaces: `load_project` reads `<root>/<project_dir>/project.json`, validates with `schema_check.validate(ROOT_OF_FRAMEWORK,'project',value)` (pass the framework root separately: signature `load_project(root, project_dir='.', framework_root=None)`; default `framework_root=root`), rejects any path containing `..`, absolute paths, backslashes, NUL or newline, and any path not under `project_dir`. `project_files` walks the project paths below `project_dir` (no symlinks; reuse `policy.file_hash`). `project_inventory` requires the set of files under `src/`, `include/`, `tests/project/`, `fuzz/project/*.c` to equal the union declared in `modules` and `programs`, every `spec` to exist, every module with `reads_external_input` to declare at least one fuzz target, corpus directories to exist and be non-empty, and none of the `forbidden_text` strings from `safety/project-policy.json` to occur in project `.c`/`.h` files (`GateError` names file and string). `write_manifest` requires `report['overall_state']=='VALIDATED_UNSEALED'` and `report['source_identity']==policy.source_identity(root)[0]`, writes the manifest (sorted keys, indent 2, trailing newline) and validates it against `schemas/framework-manifest.json`. `check_manifest` validates the manifest, recomputes `framework_files` and reports `added|removed|changed: <path>` lines sorted by path, plus `identity: framework_identity mismatch` when the stored identity does not match the stored files. Add all new files to `starter-export.json`.

- [ ] **Step 4: Run to verify pass** — same command; expected `unit` PASS.

- [ ] **Step 5: Commit** — `git add tools/project_model.py schemas/project*.json schemas/framework-manifest.json safety/project-policy.json tests/unit/test_project_model.py starter-export.json && git commit -m "feat: add the project model, project policy and framework manifest"`

---

### Task 3: Hello-world example project

**Files:**
- Create: `examples/hello-world/project.json`, `examples/hello-world/CMakeLists.txt`, `examples/hello-world/README.md`, `examples/hello-world/AGENTS.md`, `examples/hello-world/specs/project/greeting.md`, `examples/hello-world/include/greeting.h`, `examples/hello-world/src/greeting.c`, `examples/hello-world/src/main.c`, `examples/hello-world/tests/project/test_greeting.c`, `examples/hello-world/fuzz/project/greeting_fuzz.c`, `examples/hello-world/fuzz/project/corpus/greeting/{seed-world,seed-empty,seed-max}`, `examples/hello-world/fuzz/project/regressions/greeting/.keep`, `examples/hello-world/review/ledger.json`
- Modify: `safety/source-inventory.json` (four example `.c` files, role `example`), `starter-export.json`

**Interfaces:**
- Produces: `project.json` matching Task 2's schema with module `greeting` and program `hello` run with args `["world"]`.
- C API (exact):

```c
/* include/greeting.h */
#ifndef GREETING_H
#define GREETING_H
#include <stddef.h>
enum greeting_status { GREETING_OK = 0, GREETING_NULL_ARGUMENT = 1, GREETING_EMPTY_NAME = 2,
                       GREETING_NAME_TOO_LONG = 3, GREETING_INVALID_UTF8 = 4, GREETING_NOT_PRINTABLE = 5,
                       GREETING_BUFFER_TOO_SMALL = 6 };
enum { GREETING_NAME_MAX = 64 };
/* Writes "Hello, <name>!" plus NUL into out[0..capacity). name has name_len bytes (not NUL terminated).
 * On any status other than GREETING_OK, out[0] is NUL when capacity > 0 and *written is 0. */
enum greeting_status greeting_format(const char *name, size_t name_len, char *out, size_t capacity, size_t *written);
#endif
```

- [ ] **Step 1: Write the spec** `specs/project/greeting.md`: inputs (`name` pointer, nullable → `GREETING_NULL_ARGUMENT`; `name_len` 0 → `GREETING_EMPTY_NAME`; 1..64 valid; 65 → `GREETING_NAME_TOO_LONG`; `SIZE_MAX` → `GREETING_NAME_TOO_LONG`), validation order (NULL, empty, length, UTF-8, printable = no C0/C1 controls and no DEL), borrowed lifetime (name and out are borrowed for the call only; no allocation), output (`written` = bytes before NUL; capacity must be ≥ `8 + name_len + 1`; one byte short → `GREETING_BUFFER_TOO_SMALL`), failure (out cleared), concurrency (reentrant, no globals).

- [ ] **Step 2: Write the failing tests** `tests/project/test_greeting.c` with a REQUIRE macro active under `NDEBUG`:

```c
#include "greeting.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define REQUIRE(c) do { if (!(c)) { (void)fprintf(stderr, "REQUIRE failed: %s:%d: %s\n", __FILE__, __LINE__, #c); exit(1); } } while (0)
static void expect(const char *name, size_t len, size_t cap, enum greeting_status want, const char *text) {
    char out[128]; size_t written = 99U;
    REQUIRE(cap <= sizeof out);
    enum greeting_status got = greeting_format(name, len, out, cap, &written);
    REQUIRE(got == want);
    if (want == GREETING_OK) { REQUIRE(strcmp(out, text) == 0); REQUIRE(written == strlen(text)); }
    else { REQUIRE(written == 0U); if (cap > 0U) { REQUIRE(out[0] == '\0'); } }
}
int main(void) {
    char max[GREETING_NAME_MAX + 1]; memset(max, 'a', sizeof max);
    expect(NULL, 1U, 64U, GREETING_NULL_ARGUMENT, "");
    expect("", 0U, 64U, GREETING_EMPTY_NAME, "");
    expect("w", 1U, 64U, GREETING_OK, "Hello, w!");
    expect(max, GREETING_NAME_MAX, 128U, GREETING_OK, "Hello, aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!");
    expect(max, GREETING_NAME_MAX + 1U, 128U, GREETING_NAME_TOO_LONG, "");
    expect(max, SIZE_MAX, 128U, GREETING_NAME_TOO_LONG, "");
    expect("\xff", 1U, 64U, GREETING_INVALID_UTF8, "");
    expect("\xc3", 1U, 64U, GREETING_INVALID_UTF8, "");
    expect("a\tb", 3U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("\xc2\x85", 2U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("Gr\xc3\xbc\xc3\x9f" "e", 7U, 64U, GREETING_OK, "Hello, Gr\xc3\xbc\xc3\x9f" "e!");
    expect("world", 5U, 14U, GREETING_OK, "Hello, world!");
    expect("world", 5U, 13U, GREETING_BUFFER_TOO_SMALL, "");
    expect("world", 5U, 0U, GREETING_BUFFER_TOO_SMALL, "");
    { size_t w = 0U; REQUIRE(greeting_format("w", 1U, NULL, 8U, &w) == GREETING_NULL_ARGUMENT); }
    { char o[16]; REQUIRE(greeting_format("w", 1U, o, sizeof o, NULL) == GREETING_NULL_ARGUMENT); }
    return 0;
}
```

- [ ] **Step 3: Implement** `src/greeting.c` (bounded UTF-8 validation rejecting overlongs, surrogates and code points above U+10FFFF; printable check; `memcpy`-free byte copy loop with explicit bounds; status order from the spec), `src/main.c` (`int main(int argc, char **argv)`: exactly one argument required, else usage on stderr and exit 2; prints the greeting with `fputs` and exits 0; on a status error prints the status name on stderr and exits 1), `fuzz/project/greeting_fuzz.c` (`LLVMFuzzerTestOneInput` calling `greeting_format` with capacities 0, 1, exact and large, asserting the documented postconditions with `__builtin_trap()`), the seed corpus files, `review/ledger.json` (a valid empty ledger per `schemas/ledger.json` with one unit `greeting` and its review questions cited), `project.json`, `CMakeLists.txt` (`cmake_minimum_required(VERSION 3.25)`, `project(hello_world LANGUAGES C)`, `include("${SAFE_C_ROOT}/cmake/Project.cmake")`, `safety_project("${CMAKE_CURRENT_SOURCE_DIR}")`), `AGENTS.md` (project rules: specs first, boundary tests, ledger, review, never weaken gates, run `./tools/safety project check`), `README.md` (what each of the 23 gates does, how to run, expected output and time).

- [ ] **Step 4: Verify with the project gates** after Task 6 exists: `./tools/safety project check --project examples/hello-world --development`; expected: all 23 gates PASS, verdict `PASS_UNQUALIFIED_FRAMEWORK` (exit 3) until Task 11 writes the manifest.

- [ ] **Step 5: Commit** — `git add examples/hello-world safety/source-inventory.json starter-export.json && git commit -m "feat: add the hello-world example project"`

---

### Task 4: CMake project helper and project mode

**Files:**
- Create: `cmake/Project.cmake`
- Modify: `CMakeLists.txt:11-16`, `container/foundation-policy.py` (argument parsing and include flags)
- Test: covered by Task 6 gates; add `tests/unit/test_project_model.py::test_cmake_helper_has_no_flag_inputs` (reads `cmake/Project.cmake` and asserts it never references `CMAKE_C_FLAGS`, `add_compile_options`, `target_compile_options` with a project-provided value).

**Interfaces:**
- Produces: CMake function `safety_project(<project_dir>)` that reads `<project_dir>/project.json` with `file(READ)` and `string(JSON ...)`, creates a static library `project_<module>` per module (sources, `include/` as include dir) via `safety_target`, one executable per program via `safety_add_program` linking its modules, one test executable per module test (`safety_add_program`, `add_test(NAME project.<module>.<basename>)` with label `unit`), and one integration test per program that runs it with the `run.args` and requires exit 0 (`add_test(NAME project.run.<program>)`, label `integration`). Fuzz harnesses are not built by CMake (Task 6 builds them).
- Root `CMakeLists.txt`: when `SAFE_C_PROJECT_DIR` is set, or `project.json` exists in the source root, `include(cmake/Project.cmake)`, call `safety_project(...)` and `return()` before the bootstrap rule and the infrastructure targets; otherwise keep the bootstrap `FATAL_ERROR`.
- `container/foundation-policy.py`: new optional fourth argument `--include <dir>` (repeatable, each must be under `/src`, no `..`), appended as `-I<dir>` after the fixed include flags.

- [ ] **Step 1: Write the failing unit test** `test_cmake_helper_has_no_flag_inputs` (above) and run check-fast; expected FAIL (file missing).
- [ ] **Step 2: Implement `cmake/Project.cmake`** with only the commands listed in Interfaces; every target goes through `safety_target`/`safety_add_program`, so flags come from `cmake/Safety.cmake` and `SAFETY_PROFILE`.
- [ ] **Step 3: Implement the root switch and the scanner include option**; keep the bootstrap error text unchanged for the non-project path.
- [ ] **Step 4: Run check-fast**; expected `unit` PASS and all existing gates unchanged.
- [ ] **Step 5: Commit** — `git add cmake/Project.cmake CMakeLists.txt container/foundation-policy.py tests/unit/test_project_model.py starter-export.json && git commit -m "feat: add the CMake project helper and the project mode switch"`

---

### Task 5: Image publication and hashed controller dependencies

**Files:**
- Modify: `ci/image-bundle.json`
- Create: `ci/controller-requirements.txt`

**Interfaces:**
- Produces: GitHub release `images-sdk-developer-v2` with asset `images.tar.gz` (bytes 496826156, sha256 `ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624`); `ci/image-bundle.json` fields `status:"PUBLISHED"`, `publication_authorized:true`, `license_review:"OWNER_CONFIRMED_COMPLIANT_2026-10-06"`, `url:"https://github.com/MarketData-App/safe-c-environment/releases/download/images-sdk-developer-v2/images.tar.gz"`; `ci/controller-requirements.txt` with `jsonschema==4.19.2` and its exact transitive dependencies, each with `--hash=sha256:` values from PyPI.

- [ ] **Step 1: Verify the local archive** — `sha256sum ~/.local/state/safe-c-environment/image-transfer/20261005-sdk-developer-v2/images.tar.gz`; expected the digest above.
- [ ] **Step 2: Create the release** — `gh release create images-sdk-developer-v2 <archive> --repo MarketData-App/safe-c-environment --title "SDK and developer images v2" --notes-file <notes>` where notes state the two image IDs, the digest and that third_party notices apply; verify the downloaded asset digest with `curl -L -o <tmp> <url> && sha256sum <tmp>`.
- [ ] **Step 3: Write `ci/controller-requirements.txt`** from `pip download jsonschema==4.19.2 --no-binary :none: -d <tmp>` metadata, or from the PyPI JSON API; include `attrs`, `jsonschema-specifications`, `referencing`, `rpds-py` pins with hashes for CPython 3 manylinux x86_64 wheels.
- [ ] **Step 4: Update `ci/image-bundle.json`** and validate it with its schema if one exists (otherwise ensure valid JSON).
- [ ] **Step 5: Commit** — `git add ci/image-bundle.json ci/controller-requirements.txt starter-export.json && git commit -m "ci: publish the image archive and pin hashed controller dependencies"`

---

### Task 6: Project gate runner

**Files:**
- Create: `tools/project_check.py`, `container/project-fuzz-build.sh`
- Test: `tests/unit/test_project_check.py` (pure functions), live verification with the example

**Interfaces:**
- Consumes: `host_capabilities`, `Launcher(..., purpose='project')` and profile `project` (Task 1); `project_model` (Task 2); `safety_project` CMake helper and scanner `--include` (Task 4); `policy.build_audit`, `cli.analysis_flags` (move `analysis_flags` into `tools/project_check.py` as a copy if importing `cli` would create a cycle; do not edit `cli.py` here).
- Produces:
  - `run_project_check(framework_root: Path, project_dir: str, *, development: bool=False) -> dict` returning the report (validated against `schemas/project-report.json`) and writing `artifacts/project-report.json` plus evidence under `artifacts/project-runs/<run_id>/`.
  - Verdicts: `PASS` (exit 0), `FAIL` (exit 1), `BLOCKED` (exit 2), `PASS_UNQUALIFIED_FRAMEWORK` (exit 3, only with `development=True` when the manifest check reports differences).
  - `coverage_ok(summary: dict, files: set[str], line: int, branch: int) -> tuple[bool,dict]` and `parse_ctest_names(json_text: str) -> list[str]` (pure, unit tested).
- Sequence inside ONE container (`launcher.create('project', {'/src': snapshot})`, default sleep command, then `launcher.execute(record, argv, timeout=...)` per step; never `Runner.native()` or `Runner.ctest()`):
  1. `format`: `clang-format --dry-run --Werror` on every project `.c`/`.h`.
  2. Builds with `cmake -S /src/<project_dir> -B /work/project/<p>-<cc>-O<n> -G Ninja -DSAFE_C_ROOT=/src -DCMAKE_C_COMPILER=<cc> -DSAFETY_PROFILE=<p> -DSAFETY_CASE=NONE -DSAFETY_VARIANT=both -DCMAKE_C_FLAGS=-O<n> -DFOUNDATION_CASE=NONE -DFOUNDATION_MUTANT=NONE -DFOUNDATION_DISABLED_GUARDS=` then `cmake --build ... --parallel 2`, then `policy.build_audit` on the compile database, then `ctest --test-dir ... --no-tests=error --output-on-failure` (unit and integration labels). Matrix: `strict` × {gcc, clang} × {O0, O2} (gates `gcc-O0`..`clang-O2`), `hardened` (clang O2, plus the readelf checks from `cli.py:119-122` on every program), `asan`, `ubsan`, `integer`, `msan`, `tsan` (clang O0; Safety.cmake adds O1), `coverage`.
  3. `unit` = every `unit`-labelled CTest passes in every build; `integration` = every `integration`-labelled CTest passes in every build.
  4. `coverage`: `llvm-profdata merge` of all test profiles, `llvm-cov export -summary-only` over the test binaries, restricted to the project's `src/` files; thresholds from `safety/contract.json` `coverage`.
  5. `tidy`, `csa`, `gcc-analyzer`, `ast` on every project `.c` with the commands from `cli.py:88-103`, `-I/src/<project_dir>/include`, and the scanner `--include /src/<project_dir>/include`.
  6. Fuzz: `container/project-fuzz-build.sh <project_dir> <name> <harness> <module sources...>` builds each target with `CC=clang`, `CFLAGS=-O1 -g -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,address,undefined -fno-sanitize-recover=all`, `LIB_FUZZING_ENGINE=-fsanitize=fuzzer` (gate `clusterfuzzlite` = this build contract succeeds and the object shows `__asan_report` and `__sanitizer_cov` symbols); `fuzz-replay` = every regression and corpus file runs with `-runs=1` and exit 0; `fuzz-exploration` = `-seed=12345 -max_len=4096 -timeout=3 -rss_limit_mb=1024 -max_total_time=<fuzz_seconds>` on a copy of the corpus, exit 0, no crash files, coverage counter greater than 1.
  7. `inventory` = `project_model.project_inventory` (host side, before the container starts); `review-protocol` = `review/ledger.json` validates against `schemas/ledger.json` and has no finding in state OPEN, UNRESOLVED or BLOCKED with severity `high`.
  8. Runtime: fetch the program and its shared-library closure, build a rootfs tar as in `tools/runtime.py:19-62`, import it as `safe-c-project-runtime:<digest[:24]>`, add it to `launcher.approved_runtime_images`, `launcher.create('runtime-demo', {}, image=..., command=run.args)`, `docker wait` exit must equal `run.expect_exit`.
- Report gate rows: `{"name": <gate>, "status": "PASS|FAIL|BLOCKED", "details": {...}, "evidence_paths": [...]}`; console prints one line per gate and the verdict; sanitizer and analyzer text stays in evidence files.

- [ ] **Step 1: Write the failing unit tests** for `coverage_ok`, `parse_ctest_names` and the gate ordering (`gate_plan(project_policy) -> list[str]` must equal the 23 gates in policy order), and the Review Focus cases: `weakening-attempts` (forbidden text in a project file → `inventory` FAIL via `project_inventory`) and `path-with-space` (a project directory named `my app` loads and plans).
- [ ] **Step 2: Run check-fast**; expected `unit` FAIL.
- [ ] **Step 3: Implement `tools/project_check.py` and `container/project-fuzz-build.sh`** per Interfaces; every subprocess goes through `launcher.execute` or the existing `bounded` helper for Docker management commands only.
- [ ] **Step 4: Run check-fast**; expected `unit` PASS.
- [ ] **Step 5: Live run** (after Task 3 is merged into the branch): `./tools/safety project check --project examples/hello-world --development` — temporary entry: until Task 7 wires the CLI, run `python3 -c "import sys;sys.path.insert(0,'tools');import project_check as p;print(p.run_project_check(__import__('pathlib').Path('.'),'examples/hello-world',development=True)['verdict'])"`; expected `PASS_UNQUALIFIED_FRAMEWORK`; record the elapsed time.
- [ ] **Step 6: Commit** — `git add tools/project_check.py container/project-fuzz-build.sh tests/unit/test_project_check.py starter-export.json && git commit -m "feat: run every code gate on project code in one container"`

---

### Task 7: CLI, instantiate in project mode, project-mode source rules

**Files:**
- Modify: `tools/cli.py:188-209` (register `project` and `framework` subcommands, dispatch before the bootstrap `try` like `dev`), `tools/starter.py:26-63,79-80`, `tools/policy.py:51-54,68-74`, `tools/developer.py:110-112`, `safety/source-inventory.json`, `starter-export.json`
- Test: `tests/unit/test_project_model.py` (instantiate tests use a temp copy without running containers)

**Interfaces:**
- CLI: `./tools/safety project check [--project DIR] [--development]` → `project_check.run_project_check`; `./tools/safety framework manifest` → `project_model.write_manifest(root, read_json(artifacts/bootstrap-report.json), images)` where images come from `toolchain.lock.json`, `developer.lock.json` and `ci/image-bundle.json`.
- `instantiate`: after copying the export set, copy `examples/hello-world/{project.json,src,include,tests/project,fuzz/project,specs/project,review}` into the child root (rename `name` in `project.json` to the child name), copy `ci/project-ci.yml` to `.github/workflows/project-ci.yml`. `verify_starter` child file-set check (`starter.py:79-80`) compares against export set ∪ these declared project files.
- `policy.inventory_gate`: when `project.json` exists, skip the bootstrap `src/`/`include/` rule and exclude root project paths from the framework `source-inventory` requirement (project files are covered by `project_inventory`); `examples/**` stays framework content (registered, role `example`).
- `developer.py:110-112`: allow project files declared in `project.json`.

- [ ] **Step 1: Failing tests**: `test_instantiate_creates_project_mode` (child has `project.json` named after the child, the example sources, `.github/workflows/project-ci.yml`, and `framework_files(child)` equals the parent's minus nothing); `test_bootstrap_rule_still_blocks_without_project_json`.
- [ ] **Step 2: Run check-fast**; expected FAIL.
- [ ] **Step 3: Implement**; keep `instantiate`'s fresh-report precondition unchanged.
- [ ] **Step 4: Run check-fast**; expected PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: add project and framework commands and project-mode instantiate"`

---

### Task 8: Workflows

**Files:**
- Create: `.github/workflows/example.yml`, `ci/project-ci.yml`
- Modify: `.github/workflows/safety.yml`, `starter-export.json`

**Interfaces:**
- `ci/project-ci.yml` and `example.yml` (example adds `--project examples/hello-world`):

```yaml
name: project-ci
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  project:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a
        with:
          persist-credentials: false
      - name: Install hashed controller dependencies
        run: python3 -m pip install --user --require-hashes -r ci/controller-requirements.txt
      - name: Load the qualified images
        run: |
          url=$(python3 -c "import json;print(json.load(open('ci/image-bundle.json'))['url'])")
          sha=$(python3 -c "import json;print(json.load(open('ci/image-bundle.json'))['archive_sha256'])")
          curl --fail --location --proto '=https' --max-filesize 3221225472 -o "$RUNNER_TEMP/images.tar.gz" "$url"
          ci/images load --archive "$RUNNER_TEMP/images.tar.gz" --sha256 "$sha"
      - name: Project gates
        run: ./tools/safety project check
      - name: Upload the project report
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: project-report
          path: artifacts/project-report.json
          retention-days: 14
```

- `safety.yml`: remove the external baseline-variable requirement step and the `runner-request` step; keep the pinned checkout, image load as above, `sandbox doctor`, `ci`, bounded artifact upload; triggers `workflow_dispatch` and `pull_request` with `paths-ignore: ['src/**','include/**','tests/project/**','fuzz/project/**','specs/project/**','review/**','examples/**/README.md']`; timeout 240 minutes.

- [ ] **Step 1**: write the files. **Step 2**: validate YAML with `python3 -c "import yaml,sys;[yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml ci/project-ci.yml` (inside the SDK container if PyYAML is not on the host; otherwise skip and rely on GitHub's parser in Task 11). **Step 3**: commit — `git commit -m "ci: add project CI template and example workflow; make framework CI portable"`

---

### Task 9: Documentation and agent rules

**Files:** `AGENTS.md`, `docs/agent-development-quickstart.md`, `README.md`, `ci/README.md`, `docs/approval-protocol.md`, `specs/github-runner-migration.md`, `starter-export.json`

- [ ] **Step 1**: AGENTS.md — replace L7–9 and L63–64 with: this repository is the framework; a project created by `instantiate` is in project mode and may contain code in `src/`, `include/`, `tests/project/`, `fuzz/project/`, `specs/project/` and `review/`; projects run `./tools/safety project check` (all 23 code gates plus the manifest check); the framework runs full `./tools/safety ci` when framework files change, and `./tools/safety framework manifest` after a passing run; the container layer accepts any Linux x86-64 host that passes the capability check. Fold in docs/approval-protocol.md (one adversarial agent approver) as a short paragraph and keep the protocol file as the detailed reference.
- [ ] **Step 2**: quickstart — add "Project workflow": write the spec in `specs/project/`, declare the module in `project.json`, write boundary tests in `tests/project/`, a fuzz target for external input, then `./tools/safety project check`; list the 23 gates in one table with the command each runs.
- [ ] **Step 3**: README and ci/README — two tiers, timings, image release, capability check; mark `specs/github-runner-migration.md` as SUPERSEDED by the spec.
- [ ] **Step 4**: commit — `git commit -m "docs: document project mode, project check and portable containment"`

---

### Task 10: Framework self-test of the project gates

**Files:**
- Create: `safety/project-gate-fixtures/<gate>/` (one seeded defect per project gate as a patch applied to a scratch copy of the example: an unused variable warning for compilers, an analyzer-visible null dereference for csa/gcc-analyzer, a `strcpy` for ast, an out-of-bounds read for asan, signed overflow for ubsan/integer, uninitialized read for msan, a data race for tsan, an untested branch for coverage, a crashing regression input for fuzz-replay, a fuzz-reachable trap for fuzz-exploration, a broken harness build for clusterfuzzlite, an unlisted file for inventory, an OPEN high finding for review-protocol, a misformatted line for format, a missing `_FORTIFY_SOURCE` effect for hardened via a forbidden pragma, a failing unit and integration test), `tools/project_selftest.py`
- Modify: `safety/contract.json` (add `project-gates` to `required_gates`), `schemas/contract.json` if the gate list is enumerated, `tools/cli.py` (call `project_selftest` in `ci` only — this edit is part of the Task 7 tooling-identity change window; coordinate by doing it in Task 7's branch if Task 10 runs later), `starter-export.json`

**Interfaces:**
- `project_selftest(root, runner) -> dict` applies each fixture to a scratch copy, runs `run_project_check(..., development=True)` and requires: the clean example passes every gate, and each fixture fails exactly its target gate (others may pass). Output: gate row `project-gates` with per-fixture results.
- Seeded-defect sources are fixtures: never print them; hygiene rules apply.

- [ ] Steps: failing unit test for fixture inventory completeness (23 fixtures, one per gate) → implement → `check-fast` PASS → commit `feat: self-test that every project gate rejects its seeded defect`.

---

### Task 11: Qualification, manifest, push and GitHub runs

- [ ] **Step 1**: Archive superseded evidence (collector headroom ≥ 8000 files and 0.7 GB) with the `artifacts/resume/archive_*` helpers.
- [ ] **Step 2**: `./tools/safety ci` (background, about 60–70 minutes); require all required gates PASS including `project-gates`.
- [ ] **Step 3**: `./tools/safety framework manifest`; commit `framework-manifest.json` (`chore: record the qualified framework manifest`).
- [ ] **Step 4**: `./tools/safety project check --project examples/hello-world` (without `--development`); expected verdict PASS and elapsed time recorded.
- [ ] **Step 5**: privacy `--history` scan, push `main`; wait for `example` and `privacy` workflows with `agentwatch wait run <id>`; dispatch `safety` with `gh workflow run safety.yml` and wait (up to 240 minutes). Fix any failure, re-run locally, re-qualify, re-push.
- [ ] **Step 6**: record the measured GitHub times in README and the spec's success criteria.

### Task 12: Live trial and adversarial approval

- [ ] **Step 1**: Repeat the developer live trial per `prompts/developer-usability-trial.md` with a fresh-context subagent, record the receipt so `tools/developer_acceptance.py` binds the new tooling identity.
- [ ] **Step 2**: One adversarial agent approver reviews the complete change set (spec, plan, all commits since `8d60a4b`, evidence, GitHub runs) per docs/approval-protocol.md; record the verdict verbatim in `artifacts/approvals/`.
- [ ] **Step 3**: Repair findings (re-run affected gates; full `ci` before the final push only), push, confirm GitHub workflows green.
- [ ] **Step 4**: Mark ordered step 5 complete in `artifacts/resume/opus-backup-status.md`; start the benchmark.
