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
