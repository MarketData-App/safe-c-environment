# CI activation

ci/run is provider neutral; .github/workflows/safety.yml is a concrete adapter,
configured but not remotely executed. Use an ephemeral isolated self-hosted runner
with the retained image; never expose credentials in candidate/native containers.
The final aggregate requires qualification success even on skipped/cancelled/missing
jobs. All third-party action revisions are immutable. Pin the external baseline ref
and protect the expected digest/workflow through independent repository rules.
See docs/trust-boundary.md for actual approval/protection verification. Do not infer
that workflow configuration or CODEOWNERS activates enforcement.

ClusterFuzzLite PR/batch/corpus adapters in the adjacent templates are configured
for manual evaluation only; no recurring schedule or corpus service was enabled.
Remote code-change filtering never replaces committed regression replay. Forked PRs
receive no storage credentials and cannot overwrite trusted corpora. Artifact inputs
must be path/size validated before replay. Retain corpus by project/target namespace.

Before enabling the amended baseline, qualify the native Linux x86-64/glibc runner
with `sandbox doctor` and `sandbox selftest`. Independently approve its exact
Docker endpoint/daemon identity and protected container policy. Separate the
launcher account's Docker authority from generated workloads and protect the
policy/evaluator/export manifest and expected payload digest. The bootstrap account
currently has broad host/rootful daemon authority: local tests cannot prove this
separation. Pin the toolchain image; reserve the policy's host headroom, concurrency,
collector/log/image retention budgets and inspect real cgroup enforcement.

Missing controllers, an unapproved daemon, absent seccomp/AppArmor, piped core
handlers needing review, exhausted retention, or insufficient headroom require an
operator-approved runner change and requalification. Do not restart/reconfigure a
shared daemon or weaken a container flag to make CI green. Example activation
work must follow completion of the containment addendum; no remote enforcement or
production deployment has been activated by this local amendment.
