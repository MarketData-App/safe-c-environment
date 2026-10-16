# Checked GLib boundary contract

The public header is `foundation/include/sc-foundation.h`. Its functions use the
`sc_` namespace. The module is first-party runtime support, not an application.
GLib minimum API is 2.70; the source pin is separately locked. All sizes are bytes.
Each raw span must denote initialized caller storage of its declared length.
Opaque handles and GLib references must be live correctly typed objects; the API
cannot authenticate arbitrary pointers. Mutable handles are thread-confined.

Maximum accepted construction limits: text 4096 bytes, byte object 8192 bytes,
list/map 64 entries, map key 64 bytes, logical collection payload 8192 bytes.
These are starter limits, not production recommendations. Zero logical capacity
is allowed for empty-only objects. Logical payload excludes allocator capacity,
reference-object overhead and retained slice backing. A nonempty owned slice can
retain a larger parent allocation. Empty slices are independent owned empties.

Default allocation profile is glib-fail-stop. GLib allocation failures may
terminate the process. Every normal test treats termination as failure. Validation
errors below are recoverable: they leave mutable state and caller ownership
unchanged. Every owning return has the destructor named in the public header.
The allocation-free size helpers leave their output unchanged on failure; pointer
outputs are reset to NULL and associated lengths to zero before validation.

Errors use `ScError`: INVALID, RANGE, LIMIT, ENCODING, NOT_FOUND. An optional error
receiver must be NULL or point to NULL. A pending error causes failure without
overwriting it. Omitted receivers do not change status. Success initializes all
outputs and leaves no error. Destructors accept NULL; all other handle parameters
must be non-NULL. Functions carrying `warn_unused_result` require checking status.

| API | Input, success and ownership | Recoverable failures |
| --- | --- | --- |
| sc_size_add/mul | Non-NULL gsize output; publish representable result only | NULL output or overflow |
| sc_length | Signed nonnegative length, explicit maximum; publish gsize | Negative, limit, NULL output |
| sc_range | offset <= total and length <= total-offset, including end/empty | Invalid or overflowing logical region, without pointer formation |
| sc_text_new/free | Explicit maximum; own ScText, cleanup sc_text_free | Unsupported maximum; invalid error receiver |
| sc_text_append | Complete UTF-8 fragment, no embedded NUL; (NULL,0) allowed | Invalid span/encoding, signed width, length/terminator overflow or logical limit; state unchanged |
| sc_text_length | Live text, byte length excluding terminator | NULL handle yields zero only for introspection convenience |
| sc_text_snapshot | Independent owned NUL-terminated gchar*, g_free; length excludes NUL | Invalid handle/output/error receiver; no borrowed pointer escapes |
| sc_bytes_copy | Copy initialized binary span; (NULL,0) allowed; GBytes owner, g_bytes_unref | Invalid span, configured/project limit, missing output |
| sc_bytes_slice | Checked owned region; nonempty retains backing, caller keeps parent | Invalid offset/length, missing output; empty/full/end all defined |
| sc_bytes_read_u16be | Two checked bytes assembled in explicit wire order; output zero on failure | Invalid handle/range/output; never cast wire storage to a typed pointer |
| sc_list_new/free | Bounded GBytes list; destruction releases each retained entry | Unsupported limits |
| sc_list_append/replace | Retain value; caller keeps its ref; retain before releasing same-reference replacement | NULL value, logical index, count or payload cap; unchanged |
| sc_list_get_ref | Checked index; independent owned GBytes reference | RANGE, including spare-capacity indices and empty list |
| sc_list_remove | Checked index, release retained entry, preserve order | RANGE; indices are not stable identities |
| sc_list_length | Current logical count; NULL gives zero for introspection | No owning/borrowed element is exposed |
| sc_map_new/free | Owned nonempty UTF-8 keys and retained non-NULL GBytes values | Unsupported count/key/payload limits |
| sc_map_put | Copy key, retain value; equal key replaces; acquire before releasing old payload | Invalid key/value, encoding or cap; count/payload state unchanged |
| sc_map_get_ref | Validate key; independent owned ref; caller owns output | NOT_FOUND distinct from malformed key, never nullable stored values |
| sc_map_remove | Validate key; release owned key/value, preserve caller refs | NOT_FOUND or invalid key, unchanged |
| sc_map_length | Current entry count; NULL gives zero for introspection | No generic untyped access is public |

Maps use upstream g_str_hash/g_str_equal with bounded key length/count. This does
not promise resistance to all adversarial collisions; no cryptographic hash is
invented. Text has no general formatting, borrowed-view or consuming constructor.
There is no generic container, custom allocator or event loop.

Ownership conventions require initialized automatic owners, exactly paired
cleanup, explicit g_steal_pointer transfer and independent references for aliases.
Unconditional external-input guards do not rely on assert/g_assert/g_return_*.
The policy gate enforces inventoried boundary APIs, calls/macros/member accesses,
ignored results and unauthorized suppression. It does not prove raw pointer
validity, ownership semantics or every indirect call. Unsupported application
indirection is rejected pending a reviewed policy amendment.

## Parallel batch adapter

The public header is `foundation/parallel/sc-parallel.h` (link target `sc_parallel`, spec 6).
`sc_parallel_run` runs task indices 0..task_count-1 of one batch on an exclusive GThreadPool.
The shared input is immutable; each task writes only its own output slots, which the caller
owns until sc_parallel_run returns. No work survives the return; no partial success, no
nesting, no cancellation. Every task completes before the return; afterwards only idle GLib
pool workers (`pool-N`) may remain, and they run no caller code.

Limits: worker_count 1..8 (`SC_PARALLEL_MAX_WORKERS`; policy maximum 4,
`SC_PARALLEL_POLICY_MAX_WORKERS`), max_inflight 1..256 (`SC_PARALLEL_MAX_INFLIGHT`; queued,
executing and not yet completed), task_count 1..65,536 (`SC_PARALLEL_MAX_TASKS`). A NULL
configuration or task, a zero or larger value, and a trace with capacity but no storage are
refused before any pool exists. A nested call from a task is refused.

Errors use `SC_PARALLEL_ERROR` with `ScParallelError`: CONFIG (refused arguments or nesting),
CREATE (pool creation failed or is incomplete), PUSH (a push failed), TASK (the first task
failure; later tasks are skipped and counted), ACCOUNTING (executed plus skipped differs from
submitted). A pending error causes failure without overwriting it. Tasks report a failure
with `sc_parallel_set_task_error`. The adapter creates every GError it makes, task errors
included, under one process-wide lock (finding P2-T14-TSAN-01). The lock serializes only the
GErrors that the adapter creates. A GError that a task or any other thread creates through GLib
or another API is outside the lock, so the lock gives no guarantee for it. The optional report gives
submitted, executed, skipped,
threads observed and the maximum in-flight count; the optional caller-owned trace gives per
index the thread tag, CLOCK_MONOTONIC start and end and the thread CPU time, or
`SC_PARALLEL_NO_TAG` and -1 for an index that did not execute.

Grant (Amendment F item 2): `foundation/parallel/sc-parallel.c` alone holds the
`function_grants` entry of `safety/foundation-api-policy.json`: the GThreadPool, GMutex,
GCond and `g_thread_self` names, the two error helpers, atomic expressions, and one indirect
call (`s->task(...)` of type `ScParallelTaskFn`, only in `sc_parallel_worker`). The grant
is bound to the inventory row (role `parallel-adapter`, target `sc_parallel`, sha256). Every
other AST rule applies to the file unchanged. No other file gains threading. Own coverage:
90% line and 85% branch over `sc-parallel.c` and `sc-parallel.h`.

Test boundary (finding S2-02): the standard error capture of the parallel contract test is a
named reviewed process boundary, "standard error capture". It is `checks_capture_begin`,
`checks_capture_end`, `checks_wait`, `checks_capture_inject` and the drain child in
`foundation/parallel/tests/checks.c`, and `whole_with` and `faulted_with` in
`foundation/parallel/tests/contracts.c` (finding S3-01 added `checks_wait`,
`checks_capture_inject` and `faulted_with`). Only these use pipe2, fork, dup2, fcntl, waitpid
and _exit in the foundation tests; `checks_capture_inject` calls none of them itself but sets
the faults of the next `checks_capture_end`. After a failed restore of standard error,
`checks_capture_end` also opens /dev/null so that descriptor 2 stays occupied and a later open,
pipe or dup cannot take it (finding S3-06). The batch S2 and S3 approvers reviewed them. The
boundary is test code only, it grants no API to any other file, and no other process API belongs in the
foundation tests.
