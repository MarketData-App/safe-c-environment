# Repair handoff

Follow AGENTS.md and schemas/ledger.json. Create specification assertions and error
cases first, then make small scoped changes and preserve the acceptance contract.
Run check-fast, applicable separate profiles/replay, check-full and ci. Each repair
records cause, files, reproducer and before/after evidence. Stable finding IDs survive
rejection, duplication and handoffs. Five attempts or three identical failures stop.
Reviewer output belongs to a separate assigned area, without implementation/baseline
write access. Current protocol qualification uses scripted responses and real isolated
defect/control executions; it is not a live LLM review benchmark. Provider adapters,
permissions, iteration/cost budgets and model calls require later explicit approval.
