# GitHub-hosted runner acquisition proposal

Status: PROPOSED; no platform or policy migration is activated. The existing
single container policy remains machine-pinned. A new GitHub VM cannot inherit
the current daemon's approval, and no script may impersonate that daemon.

The target is a disposable GitHub-hosted Linux x86-64 Ubuntu 24.04 VM. Use the
standard public-repository runner when its actual headroom meets the policy.
Private-repository standard capacity is insufficient for the 8 GiB independent
reserve plus a build job; an owner-selected larger runner needs separate approval.
No paid runner is created by this proposal.

The immutable SDK/development payload preserves both existing OCI index IDs and
all dependency profiles. The target Docker image store must preserve those IDs.
Image load transfers data only; it grants no runner or baseline authority. Host
Python 3 and the qualified JSON Schema 4.19.2 controller profile are prerequisites.
No ordinary check installs packages or changes locks.

`ci/runner-request --output PATH` is a read-only acquisition observation. It
captures bounded daemon/platform/security/controller metadata, the source policy
hash and a proposed copy differing only in daemon identity. It never writes the
active policy, starts a native workload, or issues an approval. The 15-second
metadata operation has a 1 MiB capture ceiling. Missing Docker or malformed data
is BLOCKED. The current local and proposed identities stay separate.

Before activation, the independent authority must approve a reusable ephemeral
runner binding protocol. A literal GitHub daemon ID changes between VMs; silently
replacing it, a wildcard identity, or a locally generated approval file would not
preserve the current trust boundary. The proposed protocol must bind the actual
daemon to an independently protected approved workflow/revision and platform
profile, retain the single policy's exact endpoint/security/resource settings,
and provide a finite, run-specific qualification-only grant outside candidate
mounts. Candidate code cannot mint or alter that grant. Ordinary checks remain
offline after the acquisition phase. Expired, copied, unapproved, cross-run,
wrong-source/image or malformed grants must block before container creation.

Acquisition must also review actual cgroup controllers, AppArmor/seccomp, core
handling, Docker storage/ID semantics, host controller dependencies and free
memory/disk. A piped core handler, insufficient capacity or missing controller
needs an independently reviewed platform change, never a relaxed check. Native
jobs retain every existing cap, namespace, read-only/offline mount restriction,
collector budget and cleanup obligation.

After that protocol is independently approved, implement its protected adapter
and rejection controls, then execute the full C/P/D/F/E qualification, both
exports, designated fresh-child CI, runtime exclusion and relevant live trial on
the actual GitHub platform. The existing 1200-second child deadline stays intact.
Source-bound local results on the current host do not certify the new platform.
Do not label this executable gap as independent-enforcement-only readiness.

The GitHub-hosted workflow is configured to fail closed at the existing doctor
until an approved platform binding exists. It retains the mandatory aggregate,
opaque bounded evidence and immutable action revisions. Image publication and
repository pushes require explicit owner authorization; licensing review remains
pending. Performance work remains queued until the current ordered task finishes.
