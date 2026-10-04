# Starter lifecycle

The repository is the single starter payload. starter-export.json explicitly lists
exported files; project_name/namespace in starter.json are the only substitutions.
Starter verification writes a versioned candidate archive and a separate manifest
with the archive hash, normalized payload identity and current whole-source identity
under artifacts/releases. It carries no inherited passing report or release authority.
The payload digest excludes starter-baseline.lock.json and the manifest itself;
export inventory is compared against the trusted baseline. Names are validated and
are never executed. Nonempty or symlink destinations are refused without edits.
No history, credentials, machine home paths, build binaries or passing reports are
exported. Deliberate defects remain development-only sources, never install targets.

`./tools/safety instantiate --destination ../example-project --name example-project`
requires complete current local CI evidence. Maintenance qualification internally
exercises candidate exports before that evidence exists, without calling them
accepted releases. Child origin records are factual, not approval. Two temporary
children, one with spaces, are compared with the exact baseline; one receives full
fresh CI and the other an instrumented defect/control replay. All C/P requirements
remain required in instances; the externally selected --instance contract avoids
only recursive starter-maintenance export work. An implementer cannot use an
instance flag without the supplied trusted baseline and expected identity.

Ordinary checks never acquire newer dependencies. Upgrade by acquiring a separate
candidate, inspecting protected-file and upstream patch changes, qualifying all
cases/profiles and both exports, comparing the same frozen benchmark, obtaining
independent approval, then explicitly migrating each consumer. Keep prior approved
identities for deliberate rollback; rollback identity selection needs that same
authority. Application transition is protected configuration and needs separate
owner authorization. This bootstrap makes no application release claim.
