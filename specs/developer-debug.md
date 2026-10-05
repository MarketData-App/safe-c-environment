# Confined debugger adapter contract

Only the protected development job may invoke this adapter. The executable is
an actual discovered executable target built in the selected debug graph, or a
separately bound debug variant of a retained source snapshot. No PID, remote
target, command file, expression language, shell or user configuration is accepted.

Breakpoint locations are registered source paths and positive source lines.
Values are at most sixteen identifier/field paths, without calls, dereferences,
assignments or subscripts. Source steps are zero through four. Arguments are
bounded literal strings, passed as separate MI C strings with shell startup off.
Zero, unknown, missing, unresolved and unreached locations fail inspection.

The MI parser accepts bounded recursive strings, tuples and lists, correlates
result tokens and treats only GDB's stdout as protocol. Inferior stdout/stderr
use a private pseudo-terminal and cannot supply result or stop records. Both
channels share the finite capture/deadline budget. Incomplete capture, malformed
records, duplicate fields, debugger errors and timeouts remain explicit failures.

Initialization disables init files, automatic loading, debuginfod, shell startup,
function calls and ASLR changes before the executable is loaded. Thread support
uses only the policy's matching image library. All processes remain in the
launcher's existing private namespace and limits; no capabilities are added.

At a reached stop retain bounded frames, arguments/locals, named values, actual
thread IDs and their stacks. Preserve missing or optimized-out values. Record
the executable/source/profile identities, command errors, stop and step events,
inspection completeness and inferior exit/signal separately. Successful capture
of a crash never changes its original test/finding result. Terminate/reap the
private subprocess group and collect finite evidence before Docker teardown.

The selected GDB 16.3 does not correctly preserve whitespace when starting an
inferior without a shell (upstream issue 28392). Use a fixed isolated Python
launcher as the initial owned inferior, with only a fixed ASCII manifest path.
The manifest contains the discovered executable/hash and literal argv vector.
It is bounded, validates the /work build destination and executable identity,
then uses execve in the same PID. GDB follows that exec into the recorded target;
the resolved/reached breakpoint, target symbols and loaded SDK remain mandatory.
This is an internal stdlib-only adapter, not a command/expression API. Python
uses -I -S, sanitized environment and existing confinement. No shell is started,
no toolchain upgrade or runtime permission change is introduced, and the actual
post-exec argv is observed independently through the owned inferior's /proc entry.
