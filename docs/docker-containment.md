# Docker containment amendment

Checkpoint: v2 is locally VALIDATED_UNSEALED at commit `6a38fff`. Its 34 detector
cases, 34 repaired controls, 16 pipeline cases (64 executed subcases), full fresh
child, second-child pair, benchmark, and extended fuzz run passed. Those results
predate this amendment. `docs/bootstrap-prompt-v2.md` is an existing untracked owner
input and remains untouched. The uploaded addendum is an owner input under
`.agentwatch/uploads/`, not a workload input. No application development is begun.

The existing trusted Python evaluator uses Docker for CMake configuration,
configure-time probes, compilation, analysis, candidate scripts, C tests, unit
tests, sanitizer executions, and the local ClusterFuzzLite adapter. It snapshots
source read-only and uses offline non-root containers with dropped capabilities,
no-new-privileges, memory/swap/CPU/PID limits, executable bounded tmpfs, bounded
outer output, and an external watchdog. Builds and executions currently share a
long-lived toolchain container. Docker flags are embedded in the runner; effective
kernel controls and runtime packaging are not yet qualified.

Integration plan:

1. Replace embedded options with one strict protected profile policy and validate
   daemon identity, image, paths, environment, resources, namespaces, logging,
   confinement, scratch and effective cgroup limits before candidate execution.
2. Preserve the build adapter; use fresh containers for native test/fuzz execution
   with exact collected binaries. Keep collection live and bounded. Reserve host
   headroom and serialize finite resource probes.
3. Add D01–D14 with named live observations and permitted-operation controls; add
   the Docker sabotage variants to existing P parents without removing subcases.
4. Assemble a glibc-compatible minimal image from the already tested optimized
   safe infrastructure demo and dependencies. Test the same bytes through its
   actual entrypoint under the runtime profile. No image push or deployment.
5. Extend commands, strict reports, source/export inventory, agent instructions
   and independent activation documentation. Run original v2 plus containment
   through the amended paths, including fresh children and extended fuzzing.

The bootstrap agent currently has host and rootful Docker authority on this
development runner. It can edit the candidate launcher and policy. These are not
independent enforcement; the owner must protect the launcher/baseline and separate
permissions before BOOTSTRAP_ACCEPTED. Ordinary workloads never receive daemon
authority, host credentials, evaluator storage or a host fallback.

Initial runner discovery: native Linux x86-64, Docker Engine 29.8.2, kernel
6.12.107+deb13-cloud-amd64, cgroup v2/systemd, overlayfs, rootful daemon, default
seccomp and AppArmor available. Required limit enforcement, collector/retention
coverage and containment remain unqualified until the live suite passes. No host
packages, daemon settings, security policies or shared storage policies will be
changed. Missing capabilities become concrete blockers with operator actions.

Linux process virtual memory already separates pointers. Docker adds namespaces,
filesystem, privilege and resource restrictions while sharing the host kernel.
It does not fix undefined behavior or prove program output correct. Writable
files, service credentials and permitted database/API operations remain part of
the damage surface. Qualification covers only the exercised controls on the
recorded runner/configuration; it does not prove immunity to container escapes,
kernel failures, contention or future bugs. No escape research is in scope.

Production service access, credentials/permissions, writable data, transactions,
backups, request limits, selective egress and restart behavior require a later
application access contract. Runtime smoke stays offline with synthetic data.
Application release/deployment readiness remains false.

Mechanism references: [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/),
[tmpfs lifecycle](https://docs.docker.com/engine/storage/tmpfs/),
[bind mount recursion](https://docs.docker.com/engine/storage/bind-mounts/), and
[cgroup v2 interfaces](https://docs.kernel.org/admin-guide/cgroup-v2.html).
These document mechanisms; the project policy and live observations define the
qualification claim. Runner/kernel/runtime/image/profile changes require fresh
qualification.

## Implemented profiles and commands

`safety/container-policy.json` is the single strict profile source. `build` covers
CMake configuration/try_run, compilers, analyzers and candidate Python/shell build
helpers. Native tests use fresh `test-*` containers with separate ASan/UBSan,
integer, MSan, TSan, coverage and release profiles. CTest receives collected exact
read-only binaries and private writable test logs. The local ClusterFuzzLite
adapter builds in `build`, then replay/exploration runs in `fuzz`; the benchmark
uses an ASan test profile. `integration` is a disposable internal network with
synthetic fixtures; tests otherwise use network none with loopback available.
`runtime-demo` runs the exact tested optimized infrastructure binary. `acquire`
and the production `runtime` template cannot be launched by ordinary commands.

Public `sandbox plan --profile build` validates a redacted plan without contacting
the daemon. `sandbox doctor` runs harmless effective-control probes. `sandbox
selftest` aliases the amended full local aggregate, including the original v2
suite and fresh child. `runtime smoke` tests/assembles only the safe demo; it never
pushes images, deploys services or opens a port. Original commands remain present.
Docker failure means BLOCKED execution, never a host fallback.

The launcher uses an explicit approved local Unix endpoint and daemon identity,
an empty private Docker client config and an environment allowlist. It refuses
inherited daemon/context/TLS selections, remote/emulated/unapproved runners,
unknown or merged launch options, broad/socket/special/link mounts, nested mounts,
missing controls, unexpected image volumes/health checks and profile mismatches.
Sources are filtered private snapshots; `.env*`, agent/session metadata, home and
Git history are excluded. Bind recursion is disabled. Inspection and resolved
kernel cgroup files precede candidate execution. The bootstrap runner is rootful;
rootless migration is not performed or claimed.

Normal build/sanitizer reservations preserve the already successful v2 3-GiB,
2-CPU, 128-task budget, with 2-GiB executable build tmpfs. Other normal lanes have
separate smaller reservations; there is no virtual-address cap. Live counters,
including memory/task peaks where available, accompany each container record.
Stress calibration passed at 96-MiB memory/192-MiB independent allocation ceiling,
32 tasks/64 finite attempts, 0.25 CPU/three-second busy interval, 16-MiB scratch/
24-MiB write ceiling and 64 inodes/96 finite file attempts. Resource probes acquire
one cross-process serial slot with a bounded admission wait. These are
qualification budgets, not recommendations for an eventual application.

At most four project containers, 12 GiB aggregate memory, eight CPUs and 512 tasks
are admitted; compiler parallelism is two and fuzz workers one. Eight GiB memory
and eight GiB disk headroom are checked before admission. Fixtures, nested child
jobs, normal builds and runtime helpers all count. The network probe disposes its
offline job before creating the permitted job so nested qualification fits this
budget. An external owner must protect host-wide capacity against unrelated jobs.
The local launcher does not claim control over unrelated projects.

## Collection, storage and runtime packaging

Root filesystems are read-only; private `/work`, `/tmp`, `/run`, and `/dev/shm`
are explicitly capacity-bounded and charged to memory. `/tmp` and `/run` are
noexec/nosuid/nodev; generated binaries execute only in scoped build scratch or
read-only collected inputs. Work inode limits and actual filesystem sizes are
read during harmless preflight. Core dumps are disabled; a piped host core handler
requires operator review before crash qualification. The current handler is
`core`. No small sanitizer RLIMIT_AS is applied.

Each native execution has an external deadline and its entire container is
terminated/reaped on timeout or capture overflow. Lifecycle evidence records
process status, cgroup events, cleanup and Docker state before removal. Logs use
an explicit `local` rotating driver (one MiB/two files) and independent four-MiB
outer capture with a one-MiB record limit. Diagnostic truncation cannot count as
complete passing evidence. D11 exercises real PID-1 log rotation through supported
`docker logs`, separately from exec-output overflow.

The collector reads regular, non-link allowlisted files while tmpfs is alive,
with a 32-MiB file cap, 256-MiB destination cap and 4096-file cap. It rejects
traversal, oversized files, links and special files. Candidate code has no writable
report mount. Project evidence retention admission is two GiB/20000 files. Ordinary
checks acquire no dependencies, invoke no image builders and create no unbounded
volumes/cache. The retained toolchain image is bounded at five GiB; runtime
assembly accepts only a finite eight-MiB archive and at most four owned demo images.
No global prune or shared storage policy change occurs. Admission/free-space checks
are not a generic filesystem quota: writable workload state is bounded by actual
tmpfs limits, and collector/log/import operations have separate finite bounds.
Daemon metadata and other projects' storage are outside this project's quota.
Archive obsolete owned evidence/images through the operator before retention is
exhausted; a failed admission does not automatically delete historical results.

Runtime assembly executes no candidate command in BuildKit/Docker build. The
outer evaluator imports an allowlisted archive containing the exact already tested
hardened O2 binary plus its matching glibc/loader. It inspects the final filesystem
through the Engine export API, compares bytes and runs the real `/demo` entrypoint
under the restrictive runtime profile. No shell/compiler/test fixtures/corpora or
credentials are included. Docker-managed marker, console/bind placeholders and
`etc/mtab -> /proc/mounts` are separately recorded; pseudo-filesystems and Docker
managed files are not falsely described as immutable application payload.
Local-only images have an image ID and no invented registry digest.

## Reports, operators and activation

D01–D14 have exact named subchecks and permitted-operation controls in
`safety/containment-fixtures.json`; the same inventory enumerates every additive
Docker P variant. Strict validation rejects missing, duplicate, mismatched,
malformed, control-free or incomplete evidence. Container binding includes whole
source, immutable image, protected profile hash, actual daemon/kernel/runtime and
child-instance identity. Fresh child reports cannot inherit parent qualification.
Reports expose native C, local Docker, containment, runtime-demo, remote CI,
independent enforcement and later production approval as separate axes.

An operator moving this candidate to another native Linux runner must independently
approve its endpoint/daemon identity and capacity budget, ensure working cgroup v2
memory/swap/CPU/PID controllers and enabled default seccomp/AppArmor, provide
bounded evidence/image retention capacity, review core handling, and requalify the
exact image/policy/kernel/runtime. Do not add privileged flags, disable confinement,
change sysctls or install host infrastructure as a workaround. A missing executable
capability is BLOCKED, not VALIDATED_UNSEALED. Independent policy protection,
permissions and merge enforcement remain external until actually demonstrated.

Mechanism references additionally include [default seccomp](https://docs.docker.com/engine/security/seccomp/),
[local log rotation](https://docs.docker.com/engine/logging/drivers/local/),
[offline networking](https://docs.docker.com/engine/network/drivers/none/) and
[bridge scope](https://docs.docker.com/engine/network/drivers/bridge/). A default
internal bridge is not a per-service egress allowlist. Later application access
requires least-privilege service accounts, input/transaction validation, backups
and service-side limits; those choices remain unset in
`safety/runtime-access-template.json`.
