# C17 development policy

Use target-scoped strict C17 with GCC and Clang, no GNU dialect, at O0 and O2.
Mechanically checked: warnings as errors, VLA/implicit-declaration/type mismatch,
format/unused-result diagnostics; AST identification of banned calls including
macro expansion; no_sanitize and sanitizer-dependent behavior restrictions;
source/target inventory, object/link instrumentation and immutable baseline inputs.
Fixture-only no-inline / warn_unused_result attributes and narrow documented
warning exceptions never apply to application targets.

Ban gets, strcpy, strcat, sprintf, atoi, alloca, arbitrary system/popen execution,
inline assembly and sanitizer disabling. Raw allocation/copying/process APIs belong
to named reviewed boundaries. snprintf/strncpy/casts do not establish capacity,
termination, truncation handling or range safety. Use size_t for sizes only after
validating signed/wider conversions. Check addition/multiplication before allocation
or indexing and check offsets before pointer formation. Approve qualified checked
arithmetic builtins explicitly; no large homegrown memory framework.

Contract/test/reviewer obligations, not claimed automated proofs: one documented
owner per resource, explicit borrowed lifetimes and nullable arguments; checked
allocation, temporary realloc owner and explicit zero-allocation behavior; every
field initialized; no serialization/comparison of native struct padding; checked
I/O status, partial transfers, interruption and cleanup; error returns rather than
hostile-input assertions; bounded parser domain; synchronization for shared state.
Volatile is never thread synchronization. Avoid recursion for untrusted input.
Use disciplined goto cleanup where useful. Pointer/integer round trips, type
punning, custom allocators, lock-free code, complex signals and modular arithmetic
need separate independent design/qualification approval.

MSan uses qualified libc interceptors with fully instrumented first-party code.
New opaque dependencies block that lane until their boundary is qualified; no
blanket unpoisoning. TSan observes executed races only. Coverage/property thresholds
are policy, never proofs. Runtime sanitizer reports require real execution and
cannot certify unexecuted paths. ASan, MSan and TSan stay separate.
