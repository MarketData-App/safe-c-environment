# CI acquisition and activation

`ci/run` remains the provider-neutral trusted aggregate entrypoint. The framework
workflow selects a GitHub-hosted Ubuntu 24.04 VM, records an acquisition
request, transfers the exact SDK/developer images, requires sandbox doctor, and
runs full C/P/D/F/E CI including two exports and the designated fresh child.
Its unconditional aggregate rejects failed, skipped, cancelled and missing
qualification. Native output stays in opaque files. Action revisions remain the
previous immutable pins; checkout does not retain credentials.

Two tiers use two sets of workflows:

- `.github/workflows/example.yml` runs `./tools/safety project check --project
  examples/hello-world` on every push and pull request. This is the project CI
  tier. The target time on a GitHub-hosted runner is 6 to 10 minutes. Nobody has
  measured it yet.
- `ci/project-ci.yml` is the template that `instantiate` copies into a new
  project as `.github/workflows/project-ci.yml`. It checks out at a pinned SHA
  without credentials, downloads the image archive, verifies its digest against
  the manifest, loads it, runs `./tools/safety project check` and uploads the
  report as a bounded artifact. It has read-only permissions.
- `.github/workflows/safety.yml` runs the full framework qualification
  (`./tools/safety ci`). It starts manually and on pull requests that change
  framework files.
- `.github/workflows/privacy.yml` runs the privacy checks.

The portable container layer replaces the machine pin. Any Linux x86-64 host
runs the checks when the capability check passes: local Docker Unix socket
(rootless allowed), cgroup v2 limits, seccomp, AppArmor or SELinux enforcing,
no inherited DOCKER_* settings and non-piped core handling. A failed check
BLOCKS the run. The earlier
[migration proposal](../specs/github-runner-migration.md) is superseded by
[the design](../docs/superpowers/specs/2026-10-06-project-ci-design.md).

The two exact images have a data-only transfer payload, identified in
`ci/image-bundle.json`. It is published as the release `images-sdk-developer-v2`:
https://github.com/MarketData-App/safe-c-environment/releases/download/images-sdk-developer-v2/images.tar.gz
(sha256 `ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624`).
The controller dependencies come from the hashed file
`ci/controller-requirements.txt`. Rebuilding `container/Dockerfile` is
acquisition with mutable-source limitations, not a substitute for those locked
bytes.

The framework qualification workflow reads these independently protected
repository variables:

- `SAFETY_BASELINE_REPOSITORY`: approved trusted evaluator repository.
- `SAFETY_BASELINE_REF`: immutable 40-character approved commit.
- `SAFETY_BASELINE_DIGEST`: externally approved 64-character payload identity.
- `SAFETY_IMAGE_ARCHIVE_URL`: approved immutable GitHub release asset URL.
- `SAFETY_IMAGE_ARCHIVE_SHA256`: reviewed transfer hash from the descriptor.
- `SAFETY_GITHUB_RUNNER_LABEL`: optional owner-approved GitHub-hosted runner label;
  default `ubuntu-24.04`. No paid runner is provisioned automatically.

Host Python 3 and qualified JSON Schema 4.19.2, compatible Docker image-ID/storage
semantics, cgroup v2, seccomp, AppArmor or SELinux, acceptable core handling and
actual policy headroom are required. A missing prerequisite blocks; normal checks never install
packages or acquire/upgrade SDKs. 

On any capable Linux x86-64 host, load the exact data with:

```sh
./ci/images load --archive /absolute/path/images.tar.gz --sha256 REVIEWED_TRANSFER_HASH
./tools/safety sandbox doctor
./tools/safety ci            # framework qualification
./tools/safety project check  # project CI
```

For an acquisition observer, `ci/runner-request --output PATH` records metadata
and a proposed policy copy only. A local file/checksum never approves its own
baseline. Keep native workloads credential-free, offline, read-only and bounded;
the host outer evaluator alone has Docker authority. See the trust-boundary and
containment runbooks for independent controller separation and approval checks.

No script changes a repository permission or publishes implicitly.
ClusterFuzzLite templates remain manual; no corpus service or recurring schedule
was activated. Forked PRs receive no storage credentials. Remote filtering never
replaces committed regression replay or fresh source-bound acceptance.
