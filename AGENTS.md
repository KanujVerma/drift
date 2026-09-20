# Drift Agent Operating Contract

This file is the universal repository bootstrap for humans and coding agents
working in any clone or isolated worktree of Drift.

Canonical workspace root:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
```

Operate only inside `REPO_ROOT` unless an explicit GitHub issue authorizes
another isolated Git worktree of this same repository. Do not assume Drift
lives at a particular machine path. Do not assume Cursor or any other single
tool.

For complete operational details, see:

- [Workstream Ownership](docs/architecture/workstreams.md)
- [Agent Operating Workflow](docs/architecture/agent-workflow.md)
- [Project Roadmap](docs/architecture/roadmap.md)

---

## 1. Operating Rules

1. **Workspace Boundary**: Stay inside `REPO_ROOT` unless an issue authorizes
   another isolated worktree of this repository.
2. **Resume First**: Every session begins with the Drift Resume protocol in
   `docs/architecture/agent-workflow.md`.
3. **Repository Truth Wins**: Actual repository code, test results, Git
   history, and GitHub issue/PR state supersede prompt assertions, chat
   memory, and stale handoffs.
4. **Workstream Identity**: Resolve `kanuj` or `krish` per
   `docs/architecture/workstreams.md`. If unresolved, STOP with
   `WORKSTREAM_IDENTITY_UNRESOLVED`. Do not guess.
5. **Issue-Driven Work**: No GitHub issue means no product implementation.
   Select the next READY unblocked issue owned by this workstream. Obey that
   issue's write-set. Treat all other paths as read-only unless the issue is
   amended.
6. **One Milestone, One Owner**: Do not implement another workstream's
   milestone. Do not split a milestone informally.
7. **Zero Human Relay**: Never ask one human to relay instructions to the
   other. Create a GitHub issue owned by the other workstream instead.
8. **Architecture Authority**: External architecture reviewers own system
   architecture, scientific tradeoffs, provider selection, and ADRs. Local
   implementation agents own bounded code implementation, RED/GREEN testing,
   debugging, mechanical refactors, and Checkpoints.
9. **Evidence Hierarchy**: Resolve conflicts using: (1) repo behavior,
   schemas, and persisted SQLite contracts; (2) authenticated provider
   evidence; (3) primary docs and filings; (4) measured external data; (5)
   practitioner analysis; (6) intuition. Test counts alone are not semantic
   proof.
10. **RED/GREEN and Independent Review**: Feature implementation and bug
    fixes must follow test-driven discipline. High-impact tasks require
    independent adversarial review before acceptance.
11. **Commit and Checkpoint Discipline**: Stage and commit only the explicit
    files belonging to a verified slice. Never `git add .`. Run Checkpoint
    after each accepted commit.
12. **Handoff**: If work is unfinished, post a structured Handoff comment on
    the GitHub issue. Use `docs/handoffs/` only for exceptional state that
    cannot reasonably live in GitHub.
13. **Forbidden Destructive Git Behavior**: Never run `git reset --hard` on
    shared branches, broad `git clean` or `git restore .`, force pushes
    (`-f`), or history rewrites.
14. **Zero Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden
    across all code, docstrings, markdown documents, and commit messages.
    Always use the ASCII hyphen (U+002D).
15. **Architecture Escalation**: If empirical evidence contradicts
    architecture or requirements are ambiguous, **STOP** and open a GitHub
    architecture issue with a Decision Packet. Do not silently redesign.
16. **Documentation Impact**: Every Checkpoint must check whether canonical
    docs became false or incomplete, and update or file a `kind:docs` issue
    accordingly.

---

## 2. Mandatory Agent Loop

Every implementation agent MUST:

1. locate repository root;
2. read this file;
3. run Drift Resume;
4. resolve its workstream;
5. identify its GitHub issue;
6. verify the issue is READY and unblocked;
7. verify no competing PR owns the same work;
8. read linked roadmap, spec, ADR, and contracts;
9. obey the issue write-set;
10. treat all non-write-set paths as read-only unless the issue is amended;
11. follow RED/GREEN;
12. perform required review;
13. run the documentation-impact check;
14. Checkpoint;
15. create or update the PR;
16. post Handoff to GitHub if unfinished;
17. never use a human as a cross-workstream message relay;
18. create a GitHub architecture or contract issue when blocked;
19. STOP on material architecture contradiction;
20. use repo, test, and GitHub truth over chat memory.

If blocked on another workstream, file the request in GitHub and move to the
next READY issue in this workstream. If none exists, report blocked.

---

## 3. Current Implementation Boundary

- **Completed**: M0 (evidence kernel), M1a (temporal provenance), M1b
  (historical identity/universes), M1c (economic facts), M1d
  (observations/sessions/normalization), and M1e Tasks 1-7 (offline
  environment closure, golden case grader, replay harness).
- **Sequencing State (ADR 0012)**: M1e Task 8 (promotion-grade real-source
  qualification) is paused/deferred until economically justified. M2
  evaluator architecture and exploratory development are authorized using
  free development data (Alpaca Basic).
- **Ownership (ADR 0013)**: M2 through M10 research/R&D except M5 are Kanuj.
  M5 and M11 through M17 are Krish. M18+ is Krish operationally. See
  [workstreams.md](docs/architecture/workstreams.md).
- **Evidence Boundary**: Exploratory evaluation evidence is strictly
  non-promotable and cannot be upgraded or relabeled into promotion-grade
  evidence. Promotion requires a fresh, independent evaluation run against
  an accepted promotion-qualified M1e dataset.
- **Strictly Forbidden**: Do not add broker connections, order placement,
  live trading, or treat exploratory evaluation results as promotion-grade
  evidence.

---

## 4. Canonical Repository Map

- **System Entry Point**: [`README.md`](README.md)
- **Workstream Ownership**: [`docs/architecture/workstreams.md`](docs/architecture/workstreams.md)
- **Architecture Overview**: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- **Project Roadmap (M0 through M18+)**: [`docs/architecture/roadmap.md`](docs/architecture/roadmap.md)
- **Agent Operating Workflow**: [`docs/architecture/agent-workflow.md`](docs/architecture/agent-workflow.md)
- **M1e Provider Selection State**: [`docs/architecture/m1e-provider-selection.md`](docs/architecture/m1e-provider-selection.md)
- **Trust Boundaries**: [`docs/architecture/trust-boundaries.md`](docs/architecture/trust-boundaries.md)
- **Accepted Architecture Decisions**: [`docs/adr/`](docs/adr/)
- **Active Executable Plan**: [`docs/superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md`](docs/superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md)
  (Deferred M1e plan: [`docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md`](docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md))
- **M2 Design Specification**: [`docs/superpowers/specs/2026-09-19-m2-deterministic-session-evaluator-design.md`](docs/superpowers/specs/2026-09-19-m2-deterministic-session-evaluator-design.md)

Live task state is GitHub Issues and PRs, not this file. Read the canonical
source before modifying any area. Do not duplicate contents.

---

## 5. Standard Verification Commands

Before completing a material change, run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

For documentation-only or workflow tasks, do not rerun the full test suite
unless executable code changed.
