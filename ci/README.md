# CI acquisition and activation

`ci/run` remains the provider-neutral trusted aggregate entrypoint. The concrete
workflow now selects a GitHub-hosted Ubuntu 24.04 VM, records an acquisition
request, transfers the exact SDK/developer images, requires sandbox doctor, and
runs full C/P/D/F/E CI including two exports and the designated fresh child.
Its unconditional aggregate rejects failed, skipped, cancelled and missing
qualification. Native output stays in opaque files. Action revisions remain the
previous immutable pins; checkout does not retain credentials.

**GitHub activation is BLOCKED.** The current single policy pins the qualified
local daemon ID. A fresh GitHub VM has a different ID and cannot inherit that
approval. The workflow must fail before native execution until the independent
authority approves and qualifies the portable binding protocol described in
[the migration proposal](../specs/github-runner-migration.md). Its protected
adapter is not yet implemented or qualified; this is an executable gap, not
merely pending repository protection. No script changes the active policy,
impersonates a daemon, disables confinement or relaxes limits.

The two exact images have a local data-only transfer payload, identified in
`ci/image-bundle.json`. Export and same-daemon load were verified; that does not
certify a fresh Docker image store. Publication/licensing remain pending. There
is no public image URL yet. Rebuilding `container/Dockerfile` is acquisition with
mutable-source limitations, not a substitute for those locked bytes.

Configure these independently protected repository variables after approval:

- `SAFETY_BASELINE_REPOSITORY`: approved trusted evaluator repository.
- `SAFETY_BASELINE_REF`: immutable 40-character approved commit.
- `SAFETY_BASELINE_DIGEST`: externally approved 64-character payload identity.
- `SAFETY_IMAGE_ARCHIVE_URL`: approved immutable GitHub release asset URL.
- `SAFETY_IMAGE_ARCHIVE_SHA256`: reviewed transfer hash from the descriptor.
- `SAFETY_GITHUB_RUNNER_LABEL`: optional owner-approved GitHub-hosted runner label;
  default `ubuntu-24.04`. No paid runner is provisioned automatically.

Host Python 3 and qualified JSON Schema 4.19.2, compatible Docker image-ID/storage
semantics, cgroup v2, seccomp/AppArmor, acceptable core handling and actual policy
headroom are required. A missing prerequisite blocks; normal checks never install
packages or acquire/upgrade SDKs. Platform acquisition must specify and qualify
necessary controller/bootstrap changes before activating ordinary CI.

For an already approved local machine, load the exact data with:

```sh
./ci/images load --archive /absolute/path/images.tar.gz --sha256 REVIEWED_TRANSFER_HASH
./tools/safety sandbox doctor
./tools/safety ci
```

For an acquisition observer, `ci/runner-request --output PATH` records metadata
and a proposed policy copy only. A local file/checksum never approves its own
baseline. Keep native workloads credential-free, offline, read-only and bounded;
the host outer evaluator alone has Docker authority. See the trust-boundary and
containment runbooks for independent controller separation and approval checks.

No repository push, release publication, GitHub variable/permission change,
remote workflow execution, paid service or production deployment has occurred.
ClusterFuzzLite templates remain manual; no corpus service or recurring schedule
was activated. Forked PRs receive no storage credentials. Remote filtering never
replaces committed regression replay or fresh source-bound acceptance.
