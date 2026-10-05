# Agent protocol

This is a bootstrap-only safety starter with an authorized reusable foundation
in foundation/. No business application implementation is authorized.
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

Docker containment amendment: every candidate build/configure/try_run, Python or
shell build helper, analyzer, test, sanitizer, fuzz job and runtime smoke executes
through the protected Docker launcher. Use ./tools/safety sandbox doctor, sandbox
plan --profile build, sandbox selftest and runtime smoke. The single policy is
safety/container-policy.json; its required D inventory is safety/containment-fixtures.json.
Docker/runner/controller failure BLOCKS execution. Never fall back to host native
execution, pass arbitrary Docker flags, mount a daemon socket, inherit credentials,
weaken confinement, or relax a mandatory limit. Resource probes have independent
finite ceilings and run serially after harmless effective-limit preflight. An old
v2 report does not certify this amendment. Requalify on each actual child runner.
Runtime-demo is infrastructure only; src/ and include/ remain empty. Production
access/deployment requires a later approved application contract.

Foundation amendment: read specs/foundation-contract.md and
safety/foundation-api-policy.json before using the checked GLib boundary. Use
the compiled foundation/tests/recipes.c examples. Ordinary checks use only the
exact qualified /opt/foundation profile from foundation.lock.json; they must
not acquire, upgrade, use ambient pkg-config, or substitute headers/libraries.
The upstream GLib -fno-strict-aliasing option belongs to dependency builds only.
First-party warnings, analyzers and instrumentation remain mandatory.

Prefer initialized g_autoptr owners for GBytes, GError and opaque Sc types;
return an automatic owner only through g_steal_pointer. Obtain owned text
snapshots and free them with g_free. Retain a borrowed immutable byte object
before releasing its current owner. Use checked byte reads, slices and logical
container accessors. Static/take byte constructors, backing-field access,
unchecked copies/indexing and arbitrary GLib APIs are forbidden outside exact
inventoried boundaries. Matching cleanup, live pointer validity, initialized
spans, mutable thread confinement and synchronized immutable publication remain
caller obligations; the AST gate does not prove them.

Check every annotated result. Preserve a pending GError, initialize owned output
slots to NULL, and distinguish recoverable input/range/encoding/cap failures
from the default glib-fail-stop allocation contract. No production allocation
hook or recovery promise is approved. F19's backend injection is confined to an
ordinary same-source static test-link variant in disposable Docker jobs.
Require foundation doctor/check/selftest, its complete F01–F20 controls and named
subchecks, individual pipeline variants, own 90% line/85% branch coverage,
stateful oracle replay, actual linked/loaded profile identities, minimal runtime
closure and fresh child qualification alongside every existing gate. Passing
finite local checks remains VALIDATED_UNSEALED; application readiness is false.
