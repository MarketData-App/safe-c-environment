# Deferred integrations

These integrations are references only; none is installed, deployed or a green gate.
Pinned inspected revisions and license evidence are in upstream.lock.json.

| Integration | Activation | Evidence | Constraints/resources |
|---|---|---|---|
| Mull | Real application functions and meaningful tests | Bounded narrow module; actual generated/executed mutants; killed/survived/equivalent-unresolved/invalid/timeouts separately | LLVM compatibility and Apache license; CPU/build budget; independent evidence for equivalence |
| CBMC starter kit | Small arithmetic/length/buffer contracts | Models, inputs/assumptions, library/memory semantics, bounds, complete unwinding, assertions and non-vacuity; violating/control qualification | MIT-0 starter kit, separately reviewed CBMC license; solver RAM/CPU |
| OSS-Fuzz-Gen | Real API and trusted build | Generated harness builds, obeys preconditions and improves useful coverage/properties; lower-trust execution | Apache; model cost, disclosure and provider permission; CPU and approved model budget |
| Buttercup | Separate repair-service project with existing targets | Sandbox/repair verification and cost/iteration controls | AGPL-3.0 selected license; multi-service storage/compute/model budget; no deployment here |

A second engine, vulnerability scanning and additional architectures use the same
explicit baseline upgrade process. Deferred capability cannot waive mandatory gates.
