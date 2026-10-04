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
