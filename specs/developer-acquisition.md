# Development-tool acquisition contract

This contract covers acquisition and the early capability experiment only. Later
CLI/navigation/debugger/replay/session contracts must precede their implementation.

## Inputs and authority

Inputs are the exact existing toolchain and foundation locks, Debian amd64 package
metadata authenticated by the retained Debian archive keyring, and an explicit
clangd 19.1.7/GDB 16.3 acquisition request. The release and Packages bytes, signer
identity, metadata hashes, selected package versions, dependency relationships,
archive sizes/hashes and URLs are retained. A local hash does not grant approval.
Package notices and review status are explicit; unresolved license/independent
approval cannot become an accepted-baseline claim.

Host orchestration may download bytes and validate metadata. Package helpers,
archive extraction, ELF inspection and capability probes execute only inside the
protected offline Docker runner. No host package manager, maintainer script,
compiler or candidate native helper executes during acquisition. No ordinary
command downloads or silently changes a lock.

## Bounds, ownership and failure

Each acquisition uses a new owned artifact directory. Reject path traversal,
external symlinks, special files, set-ID executables, duplicate package identities,
archive hash/size mismatch and an unverified metadata signature. Downloads have
finite wall time and byte limits. Extracted payloads stay inside bounded private
scratch; collect only regular files through the existing collector. Explicitly
inventory any normalized package aliases. Retain rejected attempts and their
summary; do not print native diagnostic output or tracebacks into agent context.

For a package documentation-directory alias, materialize only its regular
`copyright` notice, resolving within the immutable image's `/usr/share/doc`.
Do not copy an arbitrary directory tree or preserve a live directory symlink.
Record the alias, final notice identity and package owner explicitly.

Never overwrite a different existing base-image file. Satisfied dependencies use
the installed exact package identity; missing dependencies require retained pinned
archives and closure accounting. Base compiler/tool files and all qualified GLib
profile files must keep their exact hashes. GDB/clangd and their payloads belong
only in the development image. Image assembly uses a validated data-only COPY
layer over the exact base, offline with pulling disabled, and no Dockerfile RUN.
Existing image, disk, memory, process and artifact ceilings remain mandatory.
Partition the regular-file payload into archives with at most 16 MiB of member
data per chunk (a single larger member is permitted only within the existing
32 MiB individual-file ceiling). Validate each compressed chunk against the
collector's existing 32 MiB ceiling; record exact per-chunk membership and hashes.

## Early debugger experiment

Compile the real foundation recipe using its registered CMake target and ordinary
Clang `-O0 -g` profile in Docker. Freeze the intended stop at `sc_text_new` and its
argument `maximum == 16` from the recipe before evaluating GDB. Require a
resolved breakpoint, actual stop, observed argument, source step and identified
inferior outcome, all with matching source/binary/dependency identity. A debugger
startup/version result alone is insufficient.

Also run clangd's real check operation on that CMake-registered recipe using the
generated database and exact ordinary Clang GLib include context. Verify the
entry exists uniquely and names the qualified profile. Disable ambient clangd
configuration. This prerequisite check is not semantic LSP/E-suite qualification.

GDB and inferior share the private non-root container. Keep capabilities empty,
default seccomp/AppArmor, offline networking, cores disabled and all resource
bounds. Use `-nx`, early auto-load disabling, debuginfod off, no startup shell,
function calls disabled, and `set disable-randomization off`. No PID attach,
remote target, arbitrary expression, shell command, Python extension, untrusted
startup file or downloaded symbol is permitted. Denied tracing blocks this
capability and requires an observed, separately approved narrow amendment;
acquisition does not authorize changing confinement.

## Outputs and verification

Output is a candidate development lock with immutable archive/tool/image identities,
notice and owner records, plus bounded capability evidence. Status distinguishes
acquisition, actual capability validation and independent acceptance. Missing
tools, unsatisfied dependency constraints, changed base bytes, incomplete capture,
unreached breakpoint, incorrect values, debugger failure, timeout or incomplete
cleanup fail or block their requirement. All acquired data and owned containers
have a recorded cleanup/retention outcome. Subsequent combined and child gates
must independently qualify the completed amendment before technical completion.
