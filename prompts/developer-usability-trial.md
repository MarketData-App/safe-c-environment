# Fresh-session developer usability trial

The outer harness supplies an actual workspace path and records the fresh
session identity. Receive only this task, `AGENTS.md`, and the normal developer
quickstart. Do not use the bootstrap conversation or a supplied repair.

Your sole editable file is `candidate.c` in the supplied workspace under
`artifacts/developer/workspaces/`. Do not edit other source, policies, locks,
expectations, controllers, tests, documentation, or evaluator files. Additional
tests cannot replace the independent `developer.pair` test. Do not create an
application or write to `src/` or `include/`.

The implementation reads a big-endian unsigned 16-bit value from the first two
bytes of an immutable `GBytes`. With fewer than two bytes, return false, leave
the initialized output zero, and provide the checked boundary's recoverable
range error. With at least two bytes, return true, store the first two bytes'
value, and leave the error slot clear. For bytes `12 34 56` in hexadecimal,
lengths two and three both produce 4660. Keep the checked foundation API and
ownership/error rules. The independently frozen test covers lengths 0, 1, 2,
and 3 with REQUIRE checks active under NDEBUG.

Repair the candidate through the ordinary developer workflow. Demonstrate a
real semantic navigation query, the independently supplied targeted test, a
useful GDB state observation, an implementation repair, and normal verification.
Use the actual workspace path with `--demo-workspace`, discover
`developer_demo` and `developer.pair`, and retain the failed run ID before repair.
Saved `candidate.c` line 13 column 38 is a checked-API query location; the
breakpoint `demo/candidate.c:13` permits a bounded `offset` value observation.
These are navigation locations, not a suggested repair.

Limits: at most six implementation edits, 30 public developer/verification
commands, and 600 seconds of task execution. Stop and report the concrete blocker
if those limits are exhausted. All native execution must use the protected
entrypoint. No package installation, host debugger, shell-based replay, arbitrary
GDB expressions, policy edits, or new provider clients are allowed.

Return the actual commands and run IDs, failed-before and passed-after test
results, navigation and debugger observations, current candidate hash, and
verification report path. State explicitly that root-only `check-fast` does not
certify an external scratch candidate. Report any manual intervention. The outer
harness independently reruns the frozen test and checks that only the designated
candidate changed. A fresh model context is not an independent permission boundary.
