# Later application implementation protocol

Application development requires separate owner authorization and an independently
approved production contract and target/test inventory. This starter grants none.
Before authorized application work, read AGENTS.md, the feature specification,
safety/contract.json, safety/coding-policy.md, the external baseline identity,
specs/foundation-contract.md and safety/foundation-api-policy.json.

Use the qualified checked foundation by default. Specify raw-input storage,
limits, ownership, borrowed lifetimes, nullability, outputs, failure state and
thread confinement before implementation. Use only the locked /opt/foundation
profile; new primitives or GLib APIs need independent qualification and approval.

Read foundation/tests/recipes.c, whose compiled recipes run in every normal
profile. They demonstrate bounded UTF-8 text, copied/retained immutable bytes,
checked list/map lookup, early recoverable failure and g_steal_pointer transfer.
Use initialized g_autoptr owners; match cleanup types; retain references before
releasing another owner. Text snapshots are owned and freed with g_free. No raw
backing fields, unchecked indexing or static/take constructors are approved for
application callers. Check every annotated result and preserve pending GError.

Input/range/encoding/cap errors are recoverable. Ordinary GLib allocation failure
may terminate the process; the foundation does not promise request-local OOM
recovery. Application durability, retries and availability require their own
approved contract. Mutable adapters are thread-confined; immutable publication
requires synchronization and a live owner.

Derive boundary/error tests from the specification. Run the existing Docker
gates, including foundation checks, coverage and regression replay. Read evidence
only through diagnostic_summary.py and bounded structured summaries. Follow the
finding ledger and repair budgets. Stop on missing mandatory infrastructure or
review authority; never bypass a gate or infer approval from local hashes.
