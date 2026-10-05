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
