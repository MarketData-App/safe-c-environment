# Safety-first C starter candidate

This repository assembles and executes C17 safety infrastructure before application
implementation. See [qualification commands](docs/qualification.md),
[the trust boundary](docs/trust-boundary.md), and the current generated
`artifacts/bootstrap-report.md`. No application code or application release claim
exists. Passing local qualification does not activate independent enforcement.

Two tiers apply. Framework qualification (`./tools/safety ci`) runs in this
repository when framework files change. It covers all 42 required gates (including project-gates), two exports and
a fresh child. Project CI (`./tools/safety project check`) runs in every project
on every push and pull request. It applies the 23 code gates to the project code
and verifies `framework-manifest.json`. The manifest is unsigned. The check is
tamper-evident for accidental or unreviewed framework edits, not tamper-proof;
review and the framework CI on GitHub are the controls. The target time for the hello-world
example on a GitHub-hosted runner is 6 to 10 minutes. Nobody has measured this
time yet.

Prerequisites: Linux x86-64, Docker, Python 3 with JSON Schema 4.19.2. Any host
passes when the capability check at the start of each run passes: local Docker
Unix socket (rootless allowed), Docker containerd image store, cgroup v2 limits, seccomp, AppArmor or SELinux
enforcing, no inherited DOCKER_* settings and non-piped core handling. A failed
check BLOCKS the run. Windows, macOS and ARM64 are out of scope.

The SDK and developer images come as one release archive, `images-sdk-developer-v2`:
https://github.com/MarketData-App/safe-c-environment/releases/download/images-sdk-developer-v2/images.tar.gz
(sha256 `ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624`).
Load it with `ci/images load --archive FILE --sha256 HASH`. The descriptor is
[ci/image-bundle.json](ci/image-bundle.json). See container/README.md. Image
transfer grants no baseline approval. See [CI activation](ci/README.md), the
[hello-world example](examples/hello-world/README.md) and the
[design](docs/superpowers/specs/2026-10-06-project-ci-design.md). The earlier
[runner migration proposal](specs/github-runner-migration.md) is superseded.

```sh
./tools/safety bootstrap
./tools/safety doctor
./tools/safety check-fast
./tools/safety check-full
./tools/safety selftest
./tools/safety fuzz --profile smoke
./tools/safety fuzz --profile extended
./tools/safety ci
./tools/safety report --format json
./tools/safety upstream verify
./tools/safety benchmark --suite curated
./tools/safety starter verify
./tools/safety instantiate --destination ../example-project --name example-project
./tools/safety project check --project examples/hello-world --development
./tools/safety framework manifest
```

Exports require complete current local CI. No history, secrets or passing evidence
is exported. Each child has its own source identity, target-runner qualification and
enforcement status. Give a future agent [the instantiation prompt](docs/instantiate-prompt.md).
Read AGENTS.md before development. Independent approval, owner publication licensing
and actual remote enforcement remain separate activation work. No automatic remote
publishing, paid model calls, corpus provisioning or recurring jobs were performed.

Enable the commit hooks once per clone with `git config core.hooksPath .githooks`.
They block commits, merges and pushes whose author or committer email is not a
GitHub noreply address, and any added or changed file, file name or message that
contains credentials, emails, home paths or the local login and host names. The
pre-push hook also covers cherry-picks and rebases. Personal values are derived on
the committing machine; list further private terms, one regular expression per
line, in the untracked `.git/info/personal-patterns`. Never bypass the hooks with
`--no-verify`. The `privacy` workflow runs the tree and history checks and the
hook regression suite (`.githooks/tests/regression.sh`) on every push, with the
generic rules plus the runner's own login and host name as local values: a GitHub
runner has no owner login, owner host name or private patterns. A first-party
(unpinned) zip, tar, gzip, xz or bzip2 file is blocked. A tar counts when its first
header is a ustar header or a pre-POSIX (v7) header whose checksum validates. To add a reviewed upstream
archive, put it under `third_party/` or `container/foundation-inputs/`, or give it
an upstream archive suffix (`.whl`, `.zip`, `.tar.gz`, `.tgz`, `.tar.xz`,
`.tar.bz2`, `.tar.zst`), and bind its path to its sha256 in a lock file. The
hooks skip the content of a pinned archive. They still expand every other archive
member by member (zip, tar including concatenated tars, gzip, xz, bzip2, every
stream) to a finite depth within a 64 MiB decompression budget per file, and
check the container bytes and metadata too. A corrupt or truncated stream, a zip
local-header signature at an offset that the central directory does not list, a
listed zip member whose local header disagrees with its central record (method,
flag bits 0 and 3, CRC-32 and sizes) or whose deflate stream or data descriptor
does not end where the central record says, and an exceeded member cap, depth
limit or budget are findings. Findings mask every matched value, also inside a
printed path or label, label archive metadata by index and print only printable
characters. Threat model: the hooks and the `privacy` workflow guard against
accidental commits of personal data. They are not a defence against a deliberate
committer, who can bypass client hooks. An archive crafted on purpose so that
standard tools parse it differently from Python's zipfile and tarfile is a
documented residual. Known limits: a commit or
tag that adds a vendored or upstream-archive file together with a lock entry for
it exempts that file's content, locally and in CI; altered local
remote-tracking refs can shorten a push range; a stored zip member whose own
bytes hold a local-header signature (for example a stored nested zip) is also
reported as an unlisted local entry (fail closed); a tar whose first header does
not validate is not blocked as an archive and is expanded only when its size is a
multiple of 512 bytes; other binary and
compressed formats (for example zstd or 7z), and a gzip, xz or bzip2 stream that
does not start at offset 0, are read as text or printable runs.

Reviews and approvals follow [the approval protocol](docs/approval-protocol.md):
fresh-context adversarial agent approvers are the independent authority. The
history was rewritten once before first publication; see
[the history rewrite note](docs/history-rewrite.md).

Docker containment commands: `./tools/safety sandbox plan --profile build`,
`./tools/safety sandbox doctor`, `./tools/safety sandbox selftest`, and
`./tools/safety runtime smoke`. See [the containment runbook](docs/docker-containment.md).
The selftest alias runs the amended complete local suite, including fresh-child
containment. Runtime smoke assembles and tests an infrastructure-only image without
pushing or deploying it. Generated workload execution has no host fallback.
