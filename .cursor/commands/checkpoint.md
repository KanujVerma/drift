---
description: Execute the repository-native Drift Checkpoint protocol for the active issue.
---

# /checkpoint

Execute Checkpoint for the active workstream issue using
`docs/architecture/agent-workflow.md`. This command works for either
`kanuj` or `krish`.

1. Run focused tests required by the issue. Skip the full pytest suite for
   documentation-only or workflow slices unless executable code changed.
2. Resolve genuine review findings.
3. Run the full gate when the issue or plan requires it.
4. Documentation-impact check: did this change make canonical docs false or
   incomplete? Update in-write-set docs, or file a `kind:docs` issue.
5. Audit changed files against the issue write-set.
6. Do not use `git add .`.
7. Stage explicit accepted files.
8. Commit the meaningful slice.
9. Push the issue branch. Do not push directly to `main`.
10. Create or update the pull request. Reference the issue. Use `Closes #...`
    only when the PR satisfies the issue.
11. Comment a Checkpoint summary on the GitHub issue.
12. Update issue state and dependencies if affected.
13. Identify the exact next action.

Wait for explicit commit approval when the local committing-changes rule
requires it. Never force-push. Never commit secrets.
