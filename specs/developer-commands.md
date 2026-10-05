# Developer command and state contract

These commands provide local feedback inside the existing launcher. They never
replace C/P/D/F/E acceptance, authorize application sources, grant independent
approval, download missing inputs, or invoke a native helper on the host.

## Requests and selection

Extend `tools/safety dev` with the addendum's doctor, prepare, status, targets,
tests, build, test, nav, diagnose, replay, debug, coverage, selftest, readiness
and stop operations. Parse argv into typed records, never shell programs. Reject
unknown operations/options/selections before native execution. Validate identifiers
against actual CMake File API and CTest JSON discovery; zero or ambiguous selected
tests fail. Ordinary selection excludes negative/qualification-only targets.
Qualification demos require the separate explicit E evaluator route.

Profiles bind a named compiler, optimization/instrumentation, SDK and container
profile. Debug is ordinary Clang `-O0 -g`, frame pointers, no LTO, with all warning
and API controls. Original sanitizer/test replay retains its original profile and
limits. Debugging a failure builds an explicitly identified debug variant and does
not relabel the original artifact. Source and dependency identities are mandatory.

Use the real CMake graph, Ninja and CTest. Developer-only test registration may
add foundation discovery while preserving the existing default CTest inventory.
Generate the database inside Docker. Reject ambient compiler options, arbitrary
compiler/plugin/configuration paths and an unregistered or stale database entry.
Header navigation requires a known including TU and reports the selected context.
No manually invented compile command or generic clangd fallback qualifies a query.

## Paths and coordinates

File arguments are repository-relative UTF-8 paths, without traversal, absolute
paths, links, NUL/newline or unregistered source destinations. Support spaces and
non-ASCII characters. Native source/build/dependency prefixes remain `/src`,
`/work/developer-build`, and locked `/opt/foundation/PROFILE`. Map returned file
URIs explicitly to source, dependency or toolchain locations; never substitute an
arbitrary host path. CLI lines and Unicode-scalar columns are one based. Reject
zero, negative, overlong and non-boundary positions. Convert through the negotiated
LSP UTF-8/UTF-16/UTF-32 encoding, including non-BMP characters and escaped URIs.
Saved UTF-8 file bytes and document versions are the only initial buffer source.

## Semantic protocol

Use clangd's stdio LSP with explicit initialization, capability negotiation,
correlated request IDs, notifications, versioned didOpen/diagnostics, server
requests, cancellation, errors, shutdown and exit. Definitions, references, hover,
document symbols, workspace symbols and diagnostics come from real server results.
They are advisory. No text search stands in for references or definitions.

Disable ambient/project clangd configuration. No query driver is needed for the
matched Clang default; any future driver requires an exact immutable executable
allowlist. No remote index or compiler plugin is accepted. Background index storage
is private and writable under the build context, never the read-only source tree.
Readiness requires observed protocol progress/document completion, never a sleep.
Track observed local indexing separately from global completeness: incomplete
cross-file results stay explicitly partial, including empty results.

## State, incremental builds and lifecycle

Namespace state by canonical worktree identity, baseline, compiler/toolchain,
developer payload, dependency/configuration and profile. Track source revision
separately. Caches are bounded acceleration data; no cache certifies a source tree.
Retain real Ninja build state and dependency relationships. Source/header content
changes must invalidate affected objects even with misleading timestamps; changes
to build definitions, generated headers or profile must invalidate their actual
consumers. Preserve a no-change warm path. A fresh acceptance job never restores
these development caches. Optional ccache is absent until separately measured.

Each public job has one finite overall deadline no greater than the protected
build ceiling. Index/debug subprocesses have shorter finite deadlines and bounded
output, files, storage, threads and process counts. A worktree/profile admits at
most one active development job; global launcher limits also apply. Every job
collects required artifacts before teardown. No externally reachable daemon is
created. Cancel, timeout, overflow and abandoned-job handling report incomplete
evidence and reap only owned resources; they never turn into success.

The launcher marks development jobs with a fixed purpose and hashed canonical
worktree scope. `stop` accepts only registered IDs whose inspected purpose, scope,
image and container controls match the current project. It cannot stop qualification
jobs, another worktree, services, or host processes. Do not trust a registry entry
alone as ownership. Record actual stop/cleanup outcomes and preserve failure history.

## Diagnostics, replay and outputs

Human output is concise. Strict JSON distinguishes partial feedback, complete
inspection, real inferior/test outcome, source/context identity and evidence paths.
Raw diagnostics remain bounded opaque artifacts; incomplete/truncated capture is
visible. Reports cannot clear an original failure merely because GDB succeeded.

A failure bundle retains the complete relevant source bytes, immutable locks,
literal argv/environment/cwd, profile, actual binary, inputs/seeds and original
outcome. Hashes alone do not count as retained inputs. Validate paths, chunk
inventories, regular-file modes and storage bounds before restoring. Missing,
changed or revoked inputs block original replay. Current-candidate comparison has
a new run ID and the same relevant regression inputs. A failed replay remains
nonzero. Coverage must match source, binary and profile identity; stale coverage
cannot be blended with a current targeted test.

Readiness has separate developer, combined-check, independent-enforcement,
scripted-trial and live-trial axes. Required unexecuted cases remain BLOCKED;
trials remain NOT_EXECUTED until actually run. `handoff_ready` is false until all
specified current evidence, independent enforcement and a live fresh-worker trial
pass. Application-started and production-authorized remain false.

## Combined qualification and fresh-instance evidence

Baseline qualification executes the complete local E inventory and all added P
variants once per actual worktree. The five E12 maintenance observations are
completed only by trusted outer starter/runtime results. A project instance
verifies its inherited payload, local workflow, complete local C/P/D/F/E gates
and absence of grandchildren; its outer parent verifies the two exports and
actual child completion. These scopes must be explicit in each observation.

The trusted parent executes the child developer suite immediately before the
child combined CI. That separate finite operation uses the child's own sources,
image, worktree namespace and fresh containers. The existing child CI deadline
remains 1200 seconds. Only instance CI with an independently selected baseline
may consume that child's prequalification path plus its exact outer SHA-256.
Validate source, development image, locks/policies, command and native receipts,
all required controls and unchanged evidence digests. Parent evidence, paths
outside the child's owned run area, symlinks and partial local suites fail.
Development state never enters the clean acceptance build path.

Readiness exposes index freshness, available debugger recipes and recent feedback
separately from acceptance. A stale report stays pending and cannot grant a pass.
Live trial evidence binds all relevant adapter, specification, schema, quickstart
and frozen-test inputs; changes to those inputs invalidate its usability claim.

Diagnosis offers a copyable current-candidate selected-test command only when the
frozen test, contract and build-definition inputs still match. It uses the same
selection/profile and a new run/binary identity; it never changes original replay.
Changed regression inputs make that comparison unavailable. Finite current-source
fuzz comparison is not exposed; original finite fuzz replay remains supported.
