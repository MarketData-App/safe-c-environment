# Application foundation amendment

This additive candidate follows the completed v2 and Docker stages. Docker commit
`d337897` passed its current parent/fresh-child aggregate: C01–C34 and controls,
P01–P16 with 132 individual subcases, D01–D14 and controls, 33 evaluator unit tests,
all compiler/analyzer/instrumentation lanes, benchmark, real runtime image and
starter exports. `artifacts/final-aggregate-bootstrap-report.json` records run
`1fc59c0b00c546df9e4053ab6346d850`. The separately retained extended Docker fuzz
run `cc083c9edaa3468aa815ab1fb348ebcd` passed 901.4027 seconds and 765813749
executions. These results become historical as this amendment changes inputs;
they do not qualify the foundation. Independent enforcement remains UNSEALED.
The owner's untracked `docs/bootstrap-prompt-v2.md` is preserved.

## Claim and allocation contract

The selected foundation is GLib core with a small first-party checked boundary.
GLib supplies reusable facilities, not a borrow checker or language-enforced
memory safety. A raw span requires actual valid caller storage; checking its
declared size cannot authenticate a pointer. Automatic cleanup covers ordinary
scope exits, not fatal termination, kernel OOM or nonlocal exits. Mutable adapters
are thread-confined. Reference counting requires synchronized publication and an
existing owner; it does not synchronize mutable state.

The default is `glib-fail-stop`: input/encoding/range/logical-cap errors are
recoverable and preserve ownership/state, whereas ordinary GLib allocation
failure may terminate the process. Nullable/recoverable allocation checks remain
mandatory. C30's realloc evaluation is unchanged. Reporting may allocate too.
Logical caps do not promise memory availability or exact physical memory use.
Future durability, transactions, retries, idempotency and availability require
their own application contract; no restart policy is selected here.

Docker remains bounded containment sharing a kernel. It neither validates output
nor restricts damage through future authorized service operations. The claim is
finite qualification of the exact sources, dependency builds, profiles, loaded
libraries, interfaces and exercised controls, with previous gates preserved.
Application/release/deployment readiness stays false.

## Additive implementation plan

1. Verify upstream stable GLib inputs, retain hashes/licenses/build tools and
   dependency closure; configure/build/test offline through the qualified Docker
   launcher. Address MSan early and bind separate immutable profile artifacts.
2. Specify and implement only checked sizes/conversions, bounded UTF-8 text,
   immutable bytes/regions/reads, retained-byte list and owned-text-key map in
   `foundation/`. Apply first-party warnings, analysis, sanitizers and its own
   90% line/85% branch coverage denominator.
3. Extend the existing AST checker with an explicit approved API surface and
   inventoried boundary modules; document what gates enforce and what remains an
   ownership convention. Compile and execute the agent recipes.
4. Freeze F01–F20 subchecks, controls and expected classifiers. Add bounded real
   allocation-backend injection, stateful foundation fuzzing/oracle/replay and
   the eight additive pipeline families without altering older cases.
5. Extend the tested runtime demo with the real library and exact ordinary GLib
   closure. Verify normal/rejected input and final bytes, excluding injection
   machinery, compilers, diagnostics tooling and qualification defects.
6. Extend strict reports, commands, protected/export inventories and provenance;
   require the original aggregate plus foundation on a fresh child without
   grandchildren. Make focused commits using the owner's GitHub identity.

Mechanism references: [GLib build requirements](https://docs.gtk.org/glib/building.html),
[GNOME source releases](https://download.gnome.org/sources/glib/), and
[MSan boundaries](https://clang.llvm.org/docs/MemorySanitizer.html).
The selected immutable release and actual options will be recorded after source
inspection; documentation version strings are not dependency pins. Dynamic LGPL
linking does not by itself fulfill distribution obligations. Retain source,
notices, exact build material and any patches; owner distribution review remains
external. First-party code is not relicensed.

The first strict ASan/UBSan dependency run exposed callback ABI mismatches in
upstream test registrations and library callbacks reached by byte-slice, list/queue cleanup, sorting, and
upstream automatic-cleanup tests.
These are actual function-type diagnostics, not memory-limit failures. The
candidate retains the exact original archive plus a hash-inventoried adaptation:
selected test callbacks gain typed forwarding functions, and narrowly inventoried library callbacks gain forwarding functions with the
actual expected callback signatures. Callback identity comparisons remain
consistent so slice reference flattening is preserved.
Exported signatures, reference-count behavior, test inputs/assertions, and
first-party/third-party sanitizer flags remain unchanged. The amendment is
unsealed and requires the existing independent review; no exception or approval
is inferred from a successful local build. Failed development runs remain opaque
under `artifacts/foundation-sdk-*/` and are not accepted profile evidence.
