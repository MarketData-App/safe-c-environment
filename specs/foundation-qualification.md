# Foundation evaluator contract

The trusted outer evaluator composes the existing foundation component checks.
It never builds or executes candidate code on the host. All native, analyzer,
Python build-helper and test commands use the existing protected Docker runner.

Reports bind source, dependency lock, API policy, fixture inventory, runner,
image and instance identities. F01–F20 have exactly their inventoried subchecks.
A passing subcheck requires an executed observation and unchanged passing
control, with nonempty evidence paths. A passing case requires all subchecks.
Missing observations remain BLOCKED; failed controls are CONTROL_FAILED;
infrastructure failures remain BLOCKED. Functional rejection, policy rejection
and designated sanitizer findings have distinct classifications.

Normal jobs reject nonzero exit, incomplete capture, changed binaries, container
failures, unexpected GLib critical/warning output and native diagnostic output.
Only the isolated F19 experiment accepts the attributable real allocator fatal
path. A container kill, timeout or arbitrary abort never qualifies that path.

Full acceptance additionally requires all normal profiles, foundation-only
90% line/85% branch coverage, real stateful fuzz/oracle replay, all eight pipeline
families and individual variants, exact final-image dependency bytes, two starter
exports and fresh-child combined qualification. The child verifies its inherited
payload and executes all remaining checks without recursively making children.
Scoped commands may pass their local gates while full acceptance remains BLOCKED.

Strict schemas reject missing/duplicate rows and controls, invalid statuses,
stale bindings, substituted profile identities and weakened report semantics.
Pipeline checks keep unchanged controls and record each rejection independently.
Candidate amendments remain unsealed pending independent approval. Application
and deployment readiness are false.
