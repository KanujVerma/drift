# Drift Agent Operating Contract

This file is a lean operating contract for autonomous agents and engineers
working in `/Users/kanuj/Documents/projects/drift`.

For complete operational details, see the
[Agent Operating Workflow](docs/architecture/agent-workflow.md).

---

## 1. Operating Rules

1. **Workspace Boundary**: Work strictly in `/Users/kanuj/Documents/projects/drift`.
   Never touch external mirrors or unapproved local directories.
2. **Resume First**: Every session must begin with the `Resume` workflow (`git
   status -sb`, `git log -5 --oneline`, active plan reconciliation).
3. **Repository Truth Wins**: Actual repository code, test results, and Git
   history supersede prompt assertions, chat memory, and stale handoffs.
4. **Architecture Authority**: External architecture reviewers own system
   architecture, scientific tradeoffs, provider selection, and ADRs. Local
   implementation agents own bounded code implementation, RED/GREEN testing,
   debugging, mechanical refactors, and Checkpoints.
5. **Evidence Hierarchy**: Resolve conflicts using: (1) repo behavior, schemas,
   and persisted SQLite contracts; (2) authenticated provider evidence; (3)
   primary docs and filings; (4) measured external data; (5) practitioner
   analysis; (6) intuition. Test counts alone are not semantic proof.
6. **RED/GREEN and Independent Review**: Feature implementation and bug fixes
   must follow test-driven discipline. High-impact tasks require independent
   adversarial review before acceptance.
7. **Commit and Checkpoint Discipline**: Stage and commit only the explicit files
   belonging to a verified slice. Run Checkpoint after each accepted commit.
8. **Session Handoff Boundary**: Write a `Session Handoff` only when a milestone
   is unfinished and noncanonical context must persist. Never create a handoff
   after a clean canonical completion.
9. **Forbidden Destructive Git Behavior**: Never run `git reset --hard` on
   shared branches, broad `git clean` or `git restore .`, force pushes (`-f`),
   or history rewrites.
10. **Zero Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden across
    all code, docstrings, markdown documents, and commit messages. Always use the
    ASCII hyphen (U+002D).
11. **Architecture Escalation**: If empirical evidence contradicts architecture
    or requirements are ambiguous, **STOP** and return a structured Decision
    Packet (disputed claim, repo evidence, pros/cons, impact, and affected scope).
    Do not silently redesign.

---

## 2. Current Implementation Boundary

- **Completed**: M0 (evidence kernel), M1a (temporal provenance), M1b (historical
  identity/universes), M1c (economic facts), M1d (observations/sessions/normalization),
  and M1e Tasks 1-7 (offline environment closure, golden case grader, replay harness).
- **In Progress**: M1e Task 8 (real provider pilot).
- **Current Milestone State**: Provider research is in progress (algoseek reference
  revisions disqualify it as sole historical source; Databento is strong challenger;
  Alpaca free tier is next empirical target). No real provider profile is frozen, no
  production adapter implemented, and no acquisition authorized.
- **Strictly Forbidden**: Do not add broker connections, order placement,
  evaluators, backtesters, trading models, or portfolio accounting.

---

## 3. Canonical Repository Map

- **System Entry Point**: [`README.md`](README.md)
- **Architecture Overview**: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- **Project Roadmap (M0 through M18+)**: [`docs/architecture/roadmap.md`](docs/architecture/roadmap.md)
- **Agent Operating Workflow**: [`docs/architecture/agent-workflow.md`](docs/architecture/agent-workflow.md)
- **M1e Provider Selection State**: [`docs/architecture/m1e-provider-selection.md`](docs/architecture/m1e-provider-selection.md)
- **Trust Boundaries**: [`docs/architecture/trust-boundaries.md`](docs/architecture/trust-boundaries.md)
- **Accepted Architecture Decisions**: [`docs/adr/`](docs/adr/)
- **Active Executable Plan**: [`docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md`](docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md)

Read the canonical source before modifying any area. Do not duplicate contents.

---

## 4. Standard Verification Commands

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
