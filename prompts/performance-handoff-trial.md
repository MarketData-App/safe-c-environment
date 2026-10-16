# Fresh-session performance handoff trial

The outer harness supplies an actual worktree path and records the fresh session
identity. Receive only this task, `AGENTS.md`, and
`docs/performance-laboratory.md`. Do not use the bootstrap conversation or a
supplied repair. The trial calls no commercial model provider and needs no model
credentials.

Task: one bounded Python-first comparison of the framework control case. In the
supplied worktree, run these three public commands in this order:

```
./tools/safety bench run --case bench-control-spin --mode smoke --format json
./tools/safety bench compare --run-id <id> --format json
./tools/safety bench decide --run-id <id> --format json
```

`<id>` is the run id that `bench run` reports. Read results by exit code,
status, outcome and path only.

Report:

- the run id and the exit code and status of each command;
- for each decision policy in the `bench decide` result: the rule outcome and
  the adoption outcome;
- the evidence quality that `bench decide` records;
- the statement "Python retained pending evidence".

Limits: at most 8 public commands, 30 minutes of task execution, and zero edits
of any file. Stop and report the concrete blocker when a limit is exhausted or a
command gives BLOCKED.

Forbidden: C variants and any `--variant` that selects one; `local:` datasets;
edits of policies, locks, cases, tests, tools or documentation; printing
evidence `output` fields, terminal logs or tracebacks. A recommendation is a
review recommendation only: it authorizes no adoption and no deployment.

The outer harness alone writes the receipt `artifacts/bench/handoff-trial.json`
(schema `bench-handoff-trial`): it counts the public commands, checks that no
file changed, and records the source and tooling identities. A fresh model
context is not an independent permission boundary.
