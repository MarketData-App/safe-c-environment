# Safety-first C starter candidate

This repository assembles and executes C17 safety infrastructure before application
implementation. See [qualification commands](docs/qualification.md),
[the trust boundary](docs/trust-boundary.md), and the current generated
`artifacts/bootstrap-report.md`. No application code or application release claim
exists. Passing local qualification does not activate independent enforcement.

Prerequisites: Linux x86-64/glibc, Docker, Python 3 with JSON Schema 4.19.2, and the
exact retained image in toolchain.lock.json. Image acquisition is separate from
ordinary offline checks; see container/README.md. The Makefile routes normal commands to the required safety entrypoint; its original
skeleton is retained in docs/legacy-Makefile.txt.

The exact SDK and developer images can be transferred together with
`ci/images load --archive FILE --sha256 HASH`. The current payload descriptor is
[ci/image-bundle.json](ci/image-bundle.json); its publication and owner licensing
review are pending. Image transfer grants no baseline or runner approval. A newly
cloned project on another machine still needs an independently approved target
policy and its own complete qualification. See [CI activation](ci/README.md) and
the [proposed GitHub runner migration](specs/github-runner-migration.md).

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
`--no-verify`. The `privacy` workflow repeats the tree and history checks and the
hook regression suite (`.githooks/tests/regression.sh`) on every push.

Docker containment commands: `./tools/safety sandbox plan --profile build`,
`./tools/safety sandbox doctor`, `./tools/safety sandbox selftest`, and
`./tools/safety runtime smoke`. See [the containment runbook](docs/docker-containment.md).
The selftest alias runs the amended complete local suite, including fresh-child
containment. Runtime smoke assembles and tests an infrastructure-only image without
pushing or deploying it. Generated workload execution has no host fallback.
