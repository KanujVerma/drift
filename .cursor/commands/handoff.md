---
description: Post a structured GitHub Handoff for the active issue and leave the repository safe.
---

# /handoff

Execute the Drift Handoff protocol in `docs/architecture/agent-workflow.md`.
This command works for either `kanuj` or `krish`.

Primary medium: GitHub issue comment. Do not write `docs/handoffs/` unless
the unfinished state cannot reasonably live in GitHub issue or PR context.

Post a comment containing:

- workstream
- issue
- branch
- current HEAD
- exact current state
- completed work
- tests already run
- remaining work
- known failures
- architecture questions
- uncommitted files if any
- exact next command or action

Then leave the repository safe:

- do not force-push, reset, or clean;
- do not push secrets;
- do not ask a human to relay this handoff to the other workstream.

If there is no bound GitHub issue, STOP and say so. Do not invent a second
status file.
