# CI acquisition and activation

`ci/run` remains the provider-neutral trusted aggregate entrypoint. Native
output stays in opaque files. Action revisions use immutable SHA pins. Checkout
does not retain credentials. Every workflow has read-only `contents`
permission and runs on `ubuntu-24.04`.

## Workflows

The workflows that run project or framework checks share the same setup steps:

1. Use a plain core pattern. The step runs `sudo sysctl -w
   kernel.core_pattern=core`. This is the reviewed platform setting for
   disposable GitHub-hosted runners. The capability check rejects piped core
   handlers (apport, systemd-coredump) and stays unchanged. A self-hosted host
   must configure a non-piped core pattern itself.
2. Install the hashed controller dependencies. The step creates a venv in
   `$RUNNER_TEMP/controller`, runs `pip install --require-hashes
   --only-binary=:all: -r ci/controller-requirements.txt` and adds the venv
   `bin` directory to `PATH`.
3. Enable the Docker containerd image store. The step merges
   `{"features":{"containerd-snapshotter":true}}` into `/etc/docker/daemon.json`,
   restarts Docker and fails unless `docker info` reports the driver type
   `io.containerd.snapshotter.v1`. The locked image IDs are manifest digests,
   which only this store names. A self-hosted host must enable the store itself.
4. Load the qualified images. The step reads `url` and `archive_sha256` from
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

- `.github/workflows/example.yml` runs on every push and pull request. It has
  three jobs:
  - `select` (5 minutes) checks out the full history and runs
    `python3 ci/changed-examples --base B --head H --event E`. B is
    `github.event.before` on a push and the base commit on a pull request; H is
    `github.sha`; E is the event name (`push` or `pull_request`). The
    script reads rule S from `tools/project_model.py` (`standalone_examples`):
    `examples/<name>` is a standalone example when it holds `project.json` and
    `starter-export.json` does not list `examples/<name>/project.json`. It
    prints two outputs. `framework` is `true` when a changed path is outside
    every standalone example tree. `examples` is the list of the changed
    standalone examples, or of every standalone example when `framework` is
    `true`. An absent or all-zero B (a new branch) and a B that git cannot
    compare select every example and `framework=true`.
    A pull request that changes only `examples/` skips `safety.yml`, so the
    framework inventory and B18 do not run for it. Before it prints, `select`
    therefore fails (exit 1) in these cases (fail closed):
    - At H, `starter-export.json` must list every file under a framework
      example tree and under an `examples/<name>` without `project.json`. It
      must also list every file directly under `examples/`, and it must list
      no missing file under `examples/`.
    - An `examples/<name>` that exists at B and at H must keep its scope
      (framework example, standalone example, or no `project.json`). A scope
      change fails without a change of `starter-export.json`. A pull request
      that changes that file runs the full qualification.
    - On a pull request, a framework change with 300 or more changed paths
      (or an unknown count) fails. GitHub evaluates path filters over at most
      300 files, so `safety.yml` could skip such a pull request. Split it.
      The job passes GitHub's own count of the pull request's changed files
      (`--pr-files`, from `github.event.pull_request.changed_files`). That
      count covers the three-dot diff, which can be larger than the merge
      diff. The larger count decides, and an empty count is unknown.
    - In framework mode (no root `project.json` at H), a tracked file under a
      project path (`src/`, `include/`, `tests/project/`, `fuzz/project/`,
      `specs/project/`, `review/`) fails, and a root `project.json` that H
      adds to the framework repository fails. `safety.yml` ignores these
      paths, and in the framework repository `src/` and `include/` stay empty.
    `select` exits 2 for a malformed commit id or `--pr-files` value, an
    unreadable export list, a symbolic link at `examples/`, `examples/<name>`
    or `examples/<name>/project.json`, a listed file inside a standalone
    example tree, a refused example directory name, a head that git cannot
    read, and a checkout whose standalone examples differ from those of H.
    A deeper link follows the listing rule: it is a tracked path like any
    other (exit 1 when it is unlisted outside a standalone example tree).
  - `project` runs only when `framework` is `true`. It runs
    `./tools/safety project check --project examples/hello-world` and uploads
    `artifacts/project-report.json` as the `project-report` artifact (14 days).
    The timeout is 30 minutes. The target time is 6 to 10 minutes; nobody has
    measured it yet.
  - `examples` runs one matrix job per entry of `examples` (45 minutes each).
    After setup it runs `./tools/safety project check --project <dir>`, which
    must exit 0 (the project check includes the framework manifest check), and
    uploads the report as `project-report-<index>` (14 days).
  So a push that changes only a standalone example runs the privacy checks and
  that example's project check. It starts no framework qualification and no
  hello-world job. The workflow names no standalone example.
- `ci/project-ci.yml` is the template that `instantiate` copies into a new
  project as `.github/workflows/project-ci.yml`. It runs on every push and
  pull request. It has one job, `project`, and no `select` or `examples` job.
  Its steps are the steps of the `project` job of `example.yml`, except that it
  runs `./tools/safety project check` at the project root.
- `.github/workflows/safety.yml` runs the full framework qualification. It starts
  manually and on pull requests, except pull requests that change only project
  paths (`project.json`, `src/`, `include/`, `tests/project/`, `fuzz/project/`,
  `specs/project/`, `review/`) or paths under `examples/`. A push never starts
  it. GitHub skips a `paths-ignore` workflow only when every changed path
  matches a pattern, so a pull request that also changes a framework file runs
  the full qualification. A pull request that changes only a framework example
  (one that `starter-export.json` lists, such as `examples/bench-demo` or
  `examples/hello-world`) skips it. The manifest check of the `example.yml`
  `project` job then fails on an edit or a removal of a listed file, and the
  `select` job fails on an unlisted file and on a scope change (fail closed).
  GitHub evaluates path filters over at most 300 files, so `select` fails on a
  pull request with a framework change and 300 or more changed paths. After
  setup it runs
  `./tools/safety sandbox doctor` and `./tools/safety ci`, then uploads
  `artifacts/bootstrap-report.json` and `artifacts/bootstrap-report.md` as
  `bounded-safety-evidence` (14 days). The timeout is 240 minutes.
- `.github/workflows/privacy.yml` runs the privacy checks on every push.

## Containers and images

Any Linux x86-64 host runs the checks when the capability check passes: local
Docker Unix socket (rootless allowed), Docker containerd image store, cgroup v2
limits, seccomp, AppArmor or
SELinux enforcing, no inherited DOCKER_* settings and non-piped core handling. A
failed check BLOCKS the run. The earlier
[migration proposal](../specs/github-runner-migration.md) is superseded by
the portable containment and project CI rules in this file and in `AGENTS.md`.

The two exact images have a data-only transfer payload, identified in
`ci/image-bundle.json`. It is the release `images-sdk-developer-v3`:
https://github.com/MarketData-App/safe-c-environment/releases/download/images-sdk-developer-v3/images.tar.gz
(sha256 `e8c9c5d2bfb96073965da6c83260a5aa6f7a9703bbf05307c32c41976b51d99f`).
It is the published release. The earlier release is
`images-sdk-developer-v2` (sha256
`ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624`).
Rebuilding `container/Dockerfile` is acquisition with mutable-source
limitations, not a substitute for those locked bytes.

Host Python 3 and qualified JSON Schema 4.19.2, compatible Docker image-ID and
storage semantics (the Docker containerd image store), cgroup v2, seccomp, AppArmor or SELinux, acceptable core
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
