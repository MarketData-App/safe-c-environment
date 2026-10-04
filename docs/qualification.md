# Qualification commands and evidence

Public interfaces are executable tools/safety subcommands. bootstrap verifies the
retained isolated environment; it performs no destructive host installation or
implicit download. doctor verifies locked tool identities and executes detectors.
check-fast runs formatting, both compilers at O0/O2, CTest exact discovery, all
static/AST lanes and nonempty Python discovery. check-full adds every distinct
runtime profile, measured coverage and ELF hardening inspection. selftest runs
lit-coordinated C01–C34 plus disposable P01–P16 mutations, all subcases and unit tests.
ci aggregates all gates plus the local fuzz adapter, exploration/replay, frozen
benchmark and starter instances. Mandatory gates cannot be skipped. fuzz smoke uses
10,000 executions; CI merge exploration uses 60 seconds; extended uses 900 seconds. The known trigger is excluded from
exploration's initial corpus and independently replayed against both variants.

Reports in artifacts/bootstrap-report.{json,md} contain the current source identity,
runner/toolchain/policy identities, counts, exact commands and bounded evidence.
Artifacts and scratch binaries are ignored by Git. Builds use fresh tmpfs directories
per command; immutable downloaded inputs and the pinned image may be reused.
report --format json refuses stale source/toolchain/policy evidence. CI remote
execution and authority stay explicitly unexecuted/unsealed until independently
verified. Named missing capability and licensing blockers are retained.

CI compares executed gate names with the complete protected inventory and rejects
missing or duplicate execution. Coverage demonstrates both covered and uncovered
lines and branches; future application thresholds remain inapplicable. Hardening
inspects ELF permissions, binding, stack protection and actual fortified libc symbols.
Review protocol qualification runs genuine failing and repaired C33 binaries with
scripted findings, retaining a wrong finding, an unresolved claimed fix and a blocked
repeat. This is simulated review accounting, not a live model review benchmark.
Exploration retains its bounded discovered corpus separately from regression inputs.
