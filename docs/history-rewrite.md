# History rewrite before first publication

On 2026-10-05, before this history was first published, every unpublished commit
was rewritten with `git filter-repo --replace-text`. The rewrite removed a
personal host path that the containment probe used for the D04 `home` subcheck.

- The literal path check was replaced by a general check: no mount point is at or
  below `/home`, and `/home` is empty. The new check is equal to or stronger than
  the old one.
- The `helper_sha256` pin in `safety/containment-fixtures.json` was updated in
  both historical commits that contain the probe, so each commit stays
  internally consistent.
- Those historical commits never executed the replacement check. It was first
  requalified by full CI run 27727adb1493412d86e394c8ddc20e15 (all 43 gates PASS,
  D04 PASS, control PASS) on source identity 11bbc534.
- Afterwards the check moved into `home_exposed()` in the probe, with positive
  and negative unit controls in `tests/unit/test_containment.py`.
- Commit identifiers before the rewrite are not valid references. A local backup
  of the pre-rewrite history is kept outside the repository and is not published.

The change went through the review and approval protocol in
[approval-protocol.md](approval-protocol.md).
