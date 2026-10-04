# Agent protocol

This is a bootstrap-only safety starter. No application implementation is authorized.
Read the feature specification, safety/contract.json, safety/coding-policy.md and
external baseline identity before any later application work. A local file or
checksum never authorizes its own baseline. Keep src/ and include/ empty until the
owner separately authorizes application development and the independent authority
approves the production contract and target/test inventory.

Define inputs, limits, ownership, borrowed lifetimes, nullable parameters,
invariants, outputs and failure behavior in specs/ before implementation. Derive
boundary and error tests from those assertions. Include zero, one, exact bounds,
one-past, signed-negative and representable maxima; add concurrency, allocation,
partial-I/O and cleanup tests when relevant. Tests use REQUIRE-style checks that
remain active with NDEBUG, never side effects inside assert.

Make small scoped changes. Run ./tools/safety check-fast and inspect structured
findings; repair the cause and preserve the contract. Run applicable separate
sanitizers, fault injection and fuzz regression replay, then check-full and ci.
Evidence is bound to the entire current source tree including dirty/untracked
inputs. A previous report cannot certify a new change. Finish with focused local
commits when requested; never publish or change repository permissions implicitly.

Each finding has a stable ID, detector/reviewer origin, source identity, location,
property, severity rationale, reproducer, state history, attempts and verification.
Use tools/ledger.py and schemas/ledger.json. Default maximum: five attempts per
finding; three identical unresolved attempts stop. Preserve rejected and duplicate
findings with reasons. Behavioral repairs need the same regression failing before
and passing after under identical relevant inputs. Label compile/refactor evidence
separately. Exhausted budgets, unavailable required reviewers and oscillation are
blockers. Never remove tests, shrink input domains, lower budgets, change expected
outputs to match defects, suppress warnings, fabricate success, or self-approve an
exception. Propose mistaken-specification changes to the independent authority.

Implementer edits only candidate implementation. Reviewer reads specification and
source and writes findings/test proposals only to its assigned output area; it
must not edit source or acceptance rules. Trusted tools decide deterministic
results. Submitted unit/question accounting includes actual cited locations and
whole-source fingerprints; it does not prove model comprehension. No model
credentials or commercial provider calls are required or authorized here.

Every dependency needs immutable provenance, file-scope notices, explicit owners,
license review and sanitizer-boundary qualification. Change a toolchain, protected
policy, fixtures, runner platform or runtime setting only through acquisition,
full requalification, independent approval and explicit consumer migration. Ordinary
checks are offline and never upgrade locks. Do not copy credentials into native
sandboxes, mount a home directory or Docker socket there, disable ASLR, use a
privileged container, or add broad ignorelists. The host outer evaluator alone may
launch disposable unprivileged containers; native builds have read-only sources,
offline networking and bounded scratch/resources. Stop before application work in
all bootstrap states. Report missing infrastructure truthfully.
