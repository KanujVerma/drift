---
description: Execute the repository-native Drift Resume protocol for either workstream.
---

# /resume

Execute the Drift Resume protocol in `docs/architecture/agent-workflow.md`.
This command works for `drift.workstream=kanuj` and `drift.workstream=krish`.
Do not assume a machine path, Cursor-only workflow, or prior chat memory.

1. `REPO_ROOT="$(git rev-parse --show-toplevel)"`
2. Read root `AGENTS.md`.
3. Run `git status -sb`.
4. Run `git log -5 --oneline`.
5. Resolve workstream identity. If unresolved, STOP with
   `WORKSTREAM_IDENTITY_UNRESOLVED`.
6. Inspect the current branch.
7. If this is an issue branch, read the bound GitHub issue, PR, and
   dependencies.
8. Otherwise query open issues for `workstream:<self>`.
9. Filter to READY and unblocked issues.
10. Select by in-progress bound issue, then `priority:p0`, `p1`, `p2`, then
    oldest READY.
11. Verify no competing PR or overlapping write-set.
12. Read linked roadmap, spec, ADR, and contracts.
13. Verify the allowed write-set.
14. Begin work only after those checks.

If no READY issue exists, do not invent implementation work. Report blocked
or work only on an explicitly READY architecture/preparation issue.

Report `VERIFIED`, `STALE`, or `UNCERTAIN`, then `NEXT`.
