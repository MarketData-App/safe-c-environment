# Agent development quickstart

Read `AGENTS.md`, `specs/foundation-contract.md`, and
`safety/foundation-api-policy.json` first. This repository currently authorizes
foundation and infrastructure work. Application development requires a later
approved contract; `src/` and `include/` stay empty.

Use the retained development image and approved SDK. Missing images, retained
inputs, tracing permission, symbols, or a required tool are blockers. Report the
structured reason; do not install packages, change Docker settings, or execute a
native build, analyzer, language server, test, or debugger on the host.

## Prepare and discover

```sh
./tools/safety dev doctor --format json
./tools/safety dev prepare --profile debug --format json
./tools/safety dev status --format json
./tools/safety dev targets --format json
./tools/safety dev tests --format json
```

Preparation uses the actual CMake/Ninja graph and compilation database. Normal
source edits reuse compatible private state. Profile, dependency, toolchain,
adapter, baseline, and worktree identities separate incompatible state.
Developer state accelerates feedback and is excluded from clean acceptance.
The compiler cache is absent; no ccache installation is needed.

`foundation_recipes` is a registered target and `foundation.recipes` is its
registered test. The compiled recipes explain checked reads, ownership, error
handling, retained byte objects, containers, and cleanup. The full public API and
its failure behavior are in the foundation contract and header.

```sh
./tools/safety dev build --target foundation_recipes --profile debug --format json
./tools/safety dev test --id foundation.recipes --profile debug --format json
./tools/safety dev nav --kind document-symbols --file foundation/tests/recipes.c --format json
./tools/safety dev nav --kind workspace-symbols --symbol sc_bytes_read_u16be --format json
./tools/safety dev nav --kind hover --file foundation/include/sc-foundation.h --line 34 --column 38 --tu foundation/tests/recipes.c --format json
```

## Saved-file semantic queries

`definition`, `references`, and `hover` take a file, one-based line, and one-based
Unicode-scalar column. `diagnostics` and `document-symbols` take a file.
`workspace-symbols` takes an explicit symbol query. All queries use saved UTF-8
files. Header queries require an actual registered including TU with `--tu`.
Returned locations identify repository, demo, dependency, generated, or toolchain
scope. Text search does not substitute for semantic references.

The adapter waits for saved-file diagnostics and announced local indexing work.
Inspect `cross_file_result_may_be_incomplete`; an ended local indexing batch is
not a proof of global completeness. A missing or stale compilation command is
rejected. The adapter disables ambient clangd configuration and query drivers.

## Isolated developer demonstration

A trial supplies its own directory under `artifacts/developer/workspaces/`.
Only files explicitly named by the task may be edited. The demo controller and
test expectations are frozen outside that directory. A task supplies the actual
workspace path; use it with `--demo-workspace` on prepare, discovery, navigation,
build, test, and target-debug commands. `developer_demo` and `developer.pair`
appear only when that workspace is explicitly selected.

For the standard saved `candidate.c`, a semantic definition query at line 13,
column 38 resolves the checked byte-read API. The source breakpoint
`demo/candidate.c:13` observes the local scalar `offset`. These locations are
frozen in `safety/qualification/developer/expectations.json`.

Debugger requests select `breakpoint` or `crash`, a registered target or retained
run, bounded named scalar/field values, up to four source steps, and literal
arguments. They provide no arbitrary GDB commands, expression calls, assignment,
external PID attachment, remote target, shell startup, or network symbol fetch.
GDB launches its own child with ASLR preserved and no capabilities. A fixed
container-local exec bridge preserves literal argv in the pinned GDB version.

Read `debug_session_status`, `inspection_requirements_met`, `complete_capture`,
and `inferior_outcome` separately. Collecting a signal or nonzero exit can be a
successful investigation of a failed program. It does not clear the failure.

Always redirect debugger JSON to an opaque artifact. An exclusion filter is
insufficient: structured `frames`, `threads` and their nested stacks are also
backtraces and must stay out of agent context. Use an explicit allowlist for
the requested scalar state, verdicts, counts and paths. For example, this real
registered recipe target permits a source stop:

```sh
./tools/safety dev debug --target foundation_recipes --recipe breakpoint --location foundation/tests/recipes.c:24 --format json > artifacts/recipe-debug.opaque.json
python3 - <<'PY'
import json
from pathlib import Path
try:
    result = json.loads(Path('artifacts/recipe-debug.opaque.json').read_text())
    debug = result.get('result', {}).get('debugger', {})
    print(json.dumps({
        'status': result['status'], 'run_id': result['run_id'],
        'debug_session_status': debug.get('debug_session_status'),
        'inspection_requirements_met': debug.get('inspection_requirements_met'),
        'complete_capture': debug.get('complete_capture'),
        'values': debug.get('values', {}),
        'inferior_outcome': debug.get('inferior_outcome'),
        'frame_count': len(debug.get('frames', [])),
        'thread_count': len(debug.get('threads', [])),
        'evidence_paths': result['evidence_paths'],
    }))
except Exception as error:
    print('python error:', type(error).__name__)
PY
```

Use the same allowlist for demo debugging, adding only the task's requested
scalar values. Keep the complete debugger receipt for later authorized inspection.

## Retained failures and coverage

Every selected test produces a run ID and a retained bundle. Use the actual ID
from its JSON result for `dev diagnose --run-id`,
`dev replay --run-id --snapshot original`, and `dev debug --run-id` with a typed
recipe. Replay uses the original executable, source bytes, input, instrumentation,
environment, and normal test/fuzz profile. A failed replay stays nonzero. A debug
variant is labeled as a separate investigation of the recorded source.
Diagnosis also provides a copyable current-candidate test command when its frozen
regression contract and build inputs still match. It produces a new run and binary
identity; changed test inputs make the comparison unavailable. Current-source
finite fuzz comparison is not exposed. Original finite fuzz replay is supported.

Coverage requires a successful selected test with `--profile coverage`, followed
by `dev coverage --run-id` using that run ID. Its uncovered lines and branches
belong to that exact source, demo input, binary, profile, and selection. Stale or
missing inputs are rejected. Selected coverage does not certify foundation-wide
coverage or correctness.

## Verification and cleanup

All developer commands report partial feedback with `acceptance: false`.
Use `./tools/safety check-fast` during edits, then the relevant separate profiles,
`check-full`, and `ci` for acceptance. A root check does not certify an external
scratch demo; its independently supplied selected test must also pass with its
recorded demo identity. Expensive E/P developer qualification belongs to baseline
maintenance, and does not recursively create child projects.

Read `./tools/safety dev readiness --format json` for the separate developer,
combined-check, independent-enforcement, scripted-trial, and live-trial axes.
Missing evidence never becomes a pass. `handoff_ready` remains false until all
required evidence and independent enforcement are present.
`index_freshness` describes the current namespace's saved build/source state;
navigation still reports its observed local indexing scope separately. Available
debugger recipes and recent matching feedback appear in status/readiness output.
Standalone `dev selftest` leaves the five outer E12 maintenance checks BLOCKED;
run maintenance `ci` to evaluate actual exports, child qualification and runtime
contents. This pending outer work is distinct from a local tool failure.

`./tools/safety dev stop --format json` stops only registered development jobs
for this worktree. It verifies ownership and confinement before cleanup; it does
not prune Docker resources globally. Evidence output remains bounded. Use
`tools/diagnostic_summary.py` to inspect verdicts and counts without printing raw
logs, tracebacks, sanitizer output, or fixture mutation source into agent context.
