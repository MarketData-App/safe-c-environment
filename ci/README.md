# CI acquisition and activation

`ci/run` remains the provider-neutral trusted aggregate entrypoint. Native
output stays in opaque files. Action revisions use immutable SHA pins. Checkout
does not retain credentials. Every workflow has read-only `contents`
permission and runs on `ubuntu-24.04`.

## Workflows

Three workflows share the same setup steps:

1. Use a plain core pattern. The step runs `sudo sysctl -w
   kernel.core_pattern=core`. This is the reviewed platform setting for
   disposable GitHub-hosted runners. The capability check rejects piped core
   handlers (apport, systemd-coredump) and stays unchanged. A self-hosted host
   must configure a non-piped core pattern itself.
2. Install the hashed controller dependencies. The step creates a venv in
   `$RUNNER_TEMP/controller`, runs `pip install --require-hashes
   --only-binary=:all: -r ci/controller-requirements.txt` and adds the venv
   `bin` directory to `PATH`.
3. Load the qualified images. The step reads `url` and `archive_sha256` from
   `ci/image-bundle.json`, downloads the archive with `curl` (HTTPS only, also across redirects; retries,
   size limit 3 GiB), and runs `ci/images load --archive FILE --sha256 HASH`.
   The load verifies the digest.

## Manifest trust

`framework-manifest.json` is unsigned. The manifest check is tamper-evident for
accidental or unreviewed framework edits. It is not tamper-proof: a person who
edits the framework files can recompute the manifest. The controls are code
review and the framework CI on GitHub.

`qualification.source_identity` in the manifest is a local evidence binding of the
qualifying checkout. Projects verify `framework_identity` over the exported
framework files.

The workflows differ in the steps after setup:

- `.github/workflows/example.yml` runs on every push and pull request. It runs
  `./tools/safety project check --project examples/hello-world` and uploads
  `artifacts/project-report.json` as the `project-report` artifact (14 days).
  The timeout is 30 minutes. The target time is 6 to 10 minutes; nobody has
  measured it yet.
- `ci/project-ci.yml` is the template that `instantiate` copies into a new
  project as `.github/workflows/project-ci.yml`. It is the same as `example.yml`,
  except that it runs `./tools/safety project check` at the project root.
- `.github/workflows/safety.yml` runs the full framework qualification. It starts
  manually and on pull requests, except pull requests that change only project
  paths (`project.json`, `src/`, `include/`, `tests/project/`, `fuzz/project/`,
  `specs/project/`, `review/`) or example READMEs. After setup it runs
  `./tools/safety sandbox doctor` and `./tools/safety ci`, then uploads
  `artifacts/bootstrap-report.json` and `artifacts/bootstrap-report.md` as
  `bounded-safety-evidence` (14 days). The timeout is 240 minutes.
- `.github/workflows/privacy.yml` runs the privacy checks on every push.

## Containers and images

Any Linux x86-64 host runs the checks when the capability check passes: local
Docker Unix socket (rootless allowed), cgroup v2 limits, seccomp, AppArmor or
SELinux enforcing, no inherited DOCKER_* settings and non-piped core handling. A
failed check BLOCKS the run. The earlier
[migration proposal](../specs/github-runner-migration.md) is superseded by
[the design](../docs/superpowers/specs/2026-10-06-project-ci-design.md).

The two exact images have a data-only transfer payload, identified in
`ci/image-bundle.json`. It is published as the release `images-sdk-developer-v2`:
https://github.com/MarketData-App/safe-c-environment/releases/download/images-sdk-developer-v2/images.tar.gz
(sha256 `ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624`).
Rebuilding `container/Dockerfile` is acquisition with mutable-source
limitations, not a substitute for those locked bytes.

Host Python 3 and qualified JSON Schema 4.19.2, compatible Docker image-ID and
storage semantics, cgroup v2, seccomp, AppArmor or SELinux, acceptable core
handling and actual policy headroom are required. A missing prerequisite blocks.
Normal checks never install packages or acquire or upgrade SDKs.

On any capable Linux x86-64 host, load the exact data with:

```sh
./ci/images load --archive /absolute/path/images.tar.gz --sha256 REVIEWED_TRANSFER_HASH
./tools/safety sandbox doctor
./tools/safety ci            # framework qualification
./tools/safety project check # project CI
```

`ci/runner-request` is a retired acquisition helper. No workflow uses it. The
repository keeps it for its unit tests.

A local file or checksum never approves its own baseline. Keep native workloads
credential-free, offline, read-only and bounded; the host outer evaluator alone
has Docker authority. See the trust-boundary and containment runbooks for
independent controller separation and approval checks.

No script changes a repository permission or publishes implicitly.
ClusterFuzzLite templates remain manual; no corpus service or recurring schedule
was activated. Forked PRs receive no storage credentials. Remote filtering never
replaces committed regression replay or fresh source-bound acceptance.
