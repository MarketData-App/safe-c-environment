# Independent enforcement

The bootstrap author can edit this candidate and therefore cannot independently
approve it. No remote rules, permissions or approval records were configured.
Local successful qualification is VALIDATED_UNSEALED only after every executable
requirement passes. Failed or unavailable requirements stay FAILED/BLOCKED.

The trusted authority must review the exact payload digest reported by `starter
verify` and CI, plus locks, licenses, fixture patches and evidence. Store the
approved baseline in a control repository or immutable directory the implementation
agent cannot write; keep its expected digest in an externally protected CI setting.
Invoke that baseline's tools/safety with --candidate, --baseline and
--expected-baseline. Invoking editable candidate code or keeping the expected hash
beside it is insufficient. CI workflow protection must also be independently
required by actual repository rules; CODEOWNERS alone does not enforce review.

Native candidate build scripts/programs run in unprivileged offline containers,
without tokens, Docker socket, host home, SSH agents, evaluator writable mounts or
prior reports. Sources are read-only; scratch is a 2 GiB tmpfs; memory is cgroup
limited to 3 GiB including scratch; CPU 2; pids 128; output is capped at 4 MiB;
individual files at 32 MiB. The outer host captures logs and writes final reports.
Timeouts kill the complete container and reap descendants. No virtual-memory cap
is imposed on sanitizer shadow mappings. The qualified target is Linux x86-64 /
glibc; the container still uses the host kernel. Deliberately malicious native code
may require a disposable VM. Diagnostic text is not cryptographically authenticated;
P06 qualifies a defined decoy under frozen-fixture integrity, not arbitrary forgery.

Activation steps: resolve first-party publication licensing; provision the exact
retained image on an isolated qualified runner; approve the exact candidate payload
only after final technical qualification; restrict baseline writes to an independent
authority; require the aggregate
workflow by repository rules, verify an actual intentionally broken PR is refused,
and remove implementer administration over those controls. Then verify enforcement
and record BOOTSTRAP_ACCEPTED through an independently controlled report. This
candidate deliberately has no command that self-awards that state.
