# Project CI, framework manifest and portable containment — design

Status: APPROVED by the owner on 2026-10-06. Date: 2026-10-06. Approach A of the owner's A/B
decision; approach B (framework as a versioned package) is GitHub issue #1.

## 1. Purpose

This repository exists to force agents to write safe C. A developer or agent who
starts a new project must get the complete safety layer pre-configured, with no
setup and no way to switch it off: "it just works". The framework applies every
code gate to the project's own code only. The framework code itself is treated as
proven, because this repository qualifies it.

Today a cloned project runs the full framework self-qualification (41 gates,
about 238 containers, then the same again in an exported child), which takes
about 60 minutes even for hello world. That is not practical. This design keeps
the same code gates for project code, removes the repeated framework
self-qualification from projects, and makes the container layer work on any
capable Docker host instead of one pinned machine.

Success criteria:

1. `./tools/safety project check` applies all project code gates (section 3) to
   the project's own code, and the same command runs locally and in CI.
2. Hello world passes all project gates in about 6–10 minutes on a GitHub-hosted
   runner, including image download.
3. No project setting can weaken a flag, skip a gate or change a limit.
4. The container layer runs on any Linux x86-64 host that passes the capability
   check (section 6); no machine identity is pinned. Windows and macOS are out of
   scope for now.
5. The full framework qualification (`./tools/safety ci`) stays unchanged in
   strength and runs in this repository when framework files change.

## 2. Two tiers

| Tier | Command | Where | When | Scope |
|---|---|---|---|---|
| Framework qualification | `./tools/safety ci` | this repository | framework files change | all 41 required gates, exports and fresh child |
| Project CI | `./tools/safety project check` | every project, and this repository for the example | every push and pull request | the 23 code gates on project code |

Framework files are all tracked files except the project paths (section 4) and
`framework-manifest.json`. The examples directory is framework content: it is
qualified with the framework and verified by the manifest in projects.

## 3. Gates

### 3.1 Project code gates (23, mandatory, pre-configured)

Each gate uses exactly the configuration the framework uses for its own code.

| Group | Gates |
|---|---|
| Format | `format` (repository `.clang-format`) |
| Compilers | `gcc-O0`, `gcc-O2`, `clang-O0`, `clang-O2`, all with the `cmake/Safety.cmake` warning set as errors; `hardened` (`_FORTIFY_SOURCE=3`, strong stack protector, stack-clash protection) |
| Analyzers | `tidy` (repository `.clang-tidy`), `csa` (Clang Static Analyzer), `gcc-analyzer` (`-fanalyzer`), `ast` (API policy gate from `safety/foundation-api-policy.json`) |
| Sanitizers | `asan`, `ubsan`, `integer`, `msan`, `tsan`, all with no recovery, each running all project tests |
| Tests | `unit`, `integration` (REQUIRE-style checks active with `NDEBUG`) |
| Coverage | `coverage`: at least 90% lines and 85% branches of project code (`safety/contract.json`) |
| Fuzzing | `fuzz-replay` (all saved inputs), `fuzz-exploration` (bounded run per declared target), `clusterfuzzlite` (configuration check) |
| Agent process | `inventory` (every project source has a spec in `specs/` and tests), `review-protocol` (findings ledger and adversarial review records, per the project AGENTS.md) |

Budgets come from `safety/contract.json` (timeouts, memory, processes, output);
the fuzz exploration budget per target is a fixed project value (30 seconds by
default, not lower).

### 3.2 Framework self-tests (18, this repository only)

`upstream`, `doctor`, `lit`, `selftest`, `benchmark`, `starter`,
`qualification` (34 seeded-defect cases), `containment`, `container-sabotage`,
`runtime-demo`, `foundation-doctor`, `foundation-check`, `foundation-selftest`,
`foundation-sabotage`, `developer-doctor`, `developer-selftest`,
`developer-sabotage`, `developer-workflow`. In projects, the manifest check
(section 5) replaces them by proving that the project runs the qualified layer.

## 4. Project mode and layout

A project keeps the starter layout and puts its own code in:

- `src/` and `include/` — project sources and headers;
- `tests/project/` — project unit and integration tests;
- `fuzz/project/` — project fuzz targets and corpora;
- `specs/project/` — project specifications.

Project mode is a tracked file, `project.json`, that names the project and
declares its targets, tests and fuzz targets. It contains no flags or gate
settings. `./tools/safety instantiate` creates it; without it, the bootstrap rule
of this repository (no sources in `src/`) stays in force. The root
`CMakeLists.txt` includes a new framework helper, `cmake/Project.cmake`, which
reads `project.json` and creates every gate variant; projects never edit flags.

## 5. Framework manifest

`framework-manifest.json` (tracked) records:

- the sha256 of every framework file, sorted by path;
- the SDK, developer and runtime image IDs and the image archive digest;
- the framework qualification run ID and its source identity;
- the manifest schema version.

`./tools/safety framework manifest` writes it, and only when the current
framework qualification report passed all gates for exactly the same framework
file set. In a project, the first step of `project check` recomputes every
digest. Any added, removed or changed framework file stops the run, lists the
files and states that `./tools/safety ci` is required.

## 6. Portable containment (replaces the machine pin)

The current policy accepts only one Docker daemon ID, the endpoint
`unix:///var/run/docker.sock`, the context `default`, and requires AppArmor; some
checks read host paths such as `/proc`. That pins the framework to one machine.

New rule: any Linux x86-64 host qualifies when a capability check at the start
of each run passes. The check requires:

- a local Docker Unix socket of the active context (system or rootless Docker);
  remote TCP/SSH endpoints and inherited `DOCKER_*` overrides stay rejected;
- cgroup v2 with working memory, CPU and process limits, proven by the existing
  harmless preflight probes;
- a Linux security module applied to every container: AppArmor or SELinux;
- seccomp, dropped capabilities, no-new-privileges, read-only root filesystem,
  non-root user, offline network, no privileged mode, no daemon socket or home
  directory mount, no inherited credentials;
- the exact image digests from the manifest, and non-piped core handling.

All limits, mounts, confinement and cleanup obligations stay exactly as strict as
today. The daemon ID and host details are recorded in run evidence as a record,
never as a gate. Host-side tooling (Python 3 and the JSON Schema controller) runs
on the Linux host.

## 7. Project check sequence

1. Manifest check and project mode check (host, seconds).
2. Container 1, SDK image, one new `project` profile: format, the four compiler
   builds and hardened build with tests, the five sanitizer builds with tests,
   the coverage build and threshold, the analyzers and the API gate, fuzz replay
   and bounded exploration — each in its own build directory, in sequence.
3. Container 2, runtime image: start the project program once; exit code 0.
4. Report `artifacts/project-report.json` and a short console summary.

Failure behaviour: every failure stops the run with a non-zero exit and names the
gate. Compiler and analyzer findings name file, line and check. Test failures name
the test. Sanitizer findings name the sanitizer and test; full reports go to an
evidence file, not the console. A host that fails the capability check stops with
BLOCKED and the missing capability. There is never a host fallback.

## 8. Example

`examples/hello-world/` is a complete project in the section 4 layout:

- `project.json`, `CMakeLists.txt` (includes the framework helper only);
- `specs/project/greeting.md` — name input: 1 to 64 bytes, valid UTF-8,
  printable; results for empty, NULL, exact limit, one past the limit and invalid
  bytes;
- `include/greeting.h`, `src/greeting.c` — bounded
  `format_greeting(name, out, capacity)` with explicit result codes; `src/main.c`;
- `tests/project/test_greeting.c` — boundary tests derived from the spec;
- `fuzz/project/greeting_fuzz.c` and a small seed corpus;
- `AGENTS.md` — the project rules for agents;
- `README.md` — what each gate does, how to run it, expected output and time.

It passes all project gates. `.github/workflows/example.yml` in this repository
runs `./tools/safety project check --project examples/hello-world` on every push
and pull request.

## 9. CI workflows

- Project template workflow (`ci/project-ci.yml`, copied into new projects by
  `instantiate` as `.github/workflows/project-ci.yml`): checkout at a pinned SHA
  without credentials; obtain the image archive, verify its digest against the
  manifest and load it; run `./tools/safety project check`; upload the report as
  a bounded artifact. Read-only permissions.
- `.github/workflows/safety.yml` (framework qualification) runs on framework
  changes, on manual start and on pull requests that touch framework files.

## 10. Prerequisites and open decisions

1. Image distribution: GitHub runners need the SDK and runtime images. Decided
   2026-10-06: this is an open source project that complies with the licenses of
   its components (notices in `third_party/`); publishing the image archive as a
   GitHub release asset is approved.
2. Platform: decided 2026-10-06 — Linux x86-64 only (Linux hosts and
   GitHub-hosted Ubuntu runners). Windows, macOS and native ARM64 images are out
   of scope for now.
3. Protected changes (container policy, contract, AGENTS.md, CMake helpers,
   CLI) go through one adversarial agent approver per docs/approval-protocol.md
   (owner decision 2026-10-06: one reviewer is enough).
4. AGENTS.md currently requires fresh-child requalification of everything; it is
   amended so that projects run the project gates plus the manifest check, and
   the framework runs full qualification. AGENTS.md is part of the developer
   tooling identity, so the developer live trial is repeated after this change.

## 11. Verification of this change

- Unit tests for the manifest writer and checker, project mode parsing and the
  capability check, with boundary and failure cases.
- The example passes `project check`; a seeded copy of the example with one
  defect per gate fails at exactly that gate (warning, analyzer finding,
  sanitizer error, coverage shortfall, fuzz crash, API violation, missing spec).
- The capability check passes on this host and on a GitHub-hosted runner, and
  rejects a host without cgroup limits or seccomp, a remote endpoint and a
  privileged setting.
- Full framework qualification `./tools/safety ci` passes after the change.
- Measured `project check` time for the example on a GitHub runner is recorded.

## 12. Out of scope

- Approach B (GitHub issue #1).
- Windows, macOS and native ARM64 (item 10.2).
- Any reduction of warnings, sanitizers, analyzers, coverage or limits.
