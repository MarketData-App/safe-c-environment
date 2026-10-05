# Acceptance model

The required claim is finite: all 34 designated defects, all 34 repaired controls,
all 16 pipeline mutations and every named subcase, ordinary infrastructure gates,
executed upstream fixtures, lit/FileCheck, local fuzz adapter, frozen benchmark,
protocol tests and starter instances. GCC and Clang static analysis are bug finders;
clang-tidy analyzer checks and CSA share an implementation. Runtime detectors need
execution. Fuzzing is incomplete. Memory-safe incorrect behavior needs properties
and specifications. No universal C safety or application release readiness is claimed.

Missing tools, skipped tests, analyzer complexity truncation, startup failures,
wrong diagnostics, zero discovery, missing evidence and timeouts fail closed.
Ordinary baseline compilation demonstrates that defects can enter C17 builds;
undefined behavior is never executed unsanitized as a passing criterion. Repaired
controls retain useful operations and are built separately. Actual build commands,
source/input/binary hashes, statuses, bounded output and FileCheck results are kept.
The outer evaluator compares lit statuses against all required IDs and accepts only
completed PASS with actual evidence. Broader benchmark observations are separate.

The MSan boundary is the pinned glibc 2.41 system library plus LLVM19 compiler-rt
interceptors for the exercised malloc/free, memory/string and stdio operations.
First-party parser, harness, fixtures and support translation units are instrumented
with origins; C11/C12 demonstrate real uninitialized data and clean initialized
controls across that boundary. System libraries are uninstrumented and their internal
instructions are not certified. There are no additional opaque application libraries.
Adding one requires a separately qualified boundary; no blanket unpoisoning or
automatic variable initialization is used in the MSan profile.

The Docker containment amendment is specified in [docker-containment.md](docker-containment.md).
Docker adds namespace, filesystem, privilege and resource restrictions to Linux
process virtual-memory separation. The C correctness gates remain mandatory.
Accessible writable data and service permissions remain part of the workload's
damage surface. D01–D14 qualify specific recorded controls, not arbitrary escape
immunity or application correctness. The host kernel and independent launcher
permissions remain trust dependencies. Final reports distinguish original native
qualification, containment, runtime demo, remote CI and production authority.
