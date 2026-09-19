# Agent Operating Workflow and Continuity

## Status

Active operational guide, 2026-09-19.

This document defines the operating contract, authority boundaries, verification
standards, and Git lifecycle for autonomous AI agents and human engineers working
on Drift.

---

## 1. Authority Boundaries

Drift separates architecture and scientific governance from local implementation:

### External Architecture Reviewer
The external architecture reviewer owns:
- System architecture, domain schemas, and trust boundaries;
- Scientific tradeoffs and roadmap progression;
- Provider selection, qualification rulings, and licensing decisions;
- Final interpretation of adversarial review findings;
- Defining and updating Architecture Decision Records (ADRs).

Implementation agents **must not** independently alter architecture, weaken
invariants, change product scope, or bypass licensing requirements.

### Local Implementation Agent
The local implementation agent owns:
- Repository exploration and code inspection;
- Bounded feature implementation and test-driven development (RED/GREEN);
- Debugging, regression analysis, and mechanical refactors inside established architecture;
- Running focused and integration test suites;
- Executing authenticated local provider/API probes within authorized boundaries;
- Proposing commits, maintaining Checkpoint discipline, and pushing accepted boundaries.

### Evidence-Backed Disagreement Protocol
Implementation agents are expected to challenge architecture decisions when
actual repository, compiler, or provider API evidence contradicts them.
A challenge must not be a speculative opinion or silent redesign. It must be
presented as a structured Decision Packet containing:
1. **Exact disputed claim**: What specific requirement or assumption is contradicted.
2. **Repository or API evidence**: Verifiable output, tracebacks, response payloads, or schema definitions.
3. **Strongest argument for the current architecture**: The intended benefit or invariant being protected.
4. **Strongest argument against it**: Why the current architecture fails or is unworkable.
5. **Impact and significance**: Why the resolution matters to the scientific goals.
6. **Affected scope**: Which modules, tests, or milestones are impacted.

If resolving the disagreement requires a material architectural change: **STOP**.
Do not proceed with implementation until the user or external architect decides.

---

## 2. Evidence Hierarchy

When resolving technical, historical, or domain questions, agents must adhere to
this strict evidence hierarchy:

1. **Repository Reality**: Executable test behavior, domain models, schemas,
   persisted SQLite contracts, and byte-exact fixtures.
2. **Authenticated Provider Evidence**: Empirically observed API responses,
   downloaded payloads, status codes, and sandbox query traces.
3. **Primary First-Party Documentation**: Official provider manuals, API schemas,
   regulatory filings (SEC EDGAR), and exchange notices.
4. **Measured External Evidence**: Benchmarks, empirical timing measurements, and
   documented technical specifications.
5. **Credible Practitioner Analysis**: Industry engineering reports, postmortems,
   and documented operational case studies.
6. **Model Intuition**: Unsupported completions, training-set memories, or
   generic heuristics.

*Passing test counts alone or reviewer consensus alone is never semantic proof.*
Evidence must be independently verifiable.

---

## 3. Recommended Model Allocation

The following allocation is an operational recommendation to maximize speed and
rigor. Authority resides in the role boundaries, not the specific model brand:

- **External Reviewer / Architect (e.g., ChatGPT / Claude Opus)**: Broad research,
  architectural synthesis, ADR drafting, and review of pushed commits.
- **Fast Bounded Prober (e.g., Kimi / NVIDIA NIM)**: Targeted code edits, local
  debugging, and authenticated schema probes.
- **Local Implementation Root (e.g., Gemini / Anti-Gravity)**: Long-running
  implementation tasks, multi-file refactoring, integration testing, and
  repository publication.
- **Adversarial Specialist (e.g., Sol)**: Deep invariant verification, temporal
  edge cases, and security boundary reviews.
- **High-Ambiguity Audit (e.g., Astra)**: Whole-milestone acceptance audits and
  architectural reconciliation before major milestone transitions.

---

## 4. Task Lifecycle: Resume, Checkpoint, and Session Handoff

### Resume
Every work session must begin with the `Resume` workflow:
1. Reconcile Git reality (`git status -sb`, `git log -5 --oneline`).
2. Identify current branch, HEAD commit, active implementation plan, and
   verification status.
3. Check for any uncommitted changes or recent handoffs.
4. **Repository truth beats prompt claims or chat history.** If the repository
   shows a task is already completed, do not redo it. If code contradicts chat,
   the code wins.

### Checkpoint
After completing each meaningful, reviewable slice of work:
1. Run focused tests to ensure GREEN status.
2. Complete independent adversarial review if mandated by the task plan.
3. Repair genuine review findings and verify fixes.
4. Update the task's execution record in the active plan.
5. Stage only the explicit files belonging to that slice.
6. Commit with a concise, conventional commit message (e.g., `feat: ...`, `fix: ...`, `docs: ...`).
7. Report the Checkpoint status.

### Session Handoff
A `Session Handoff` (`docs/handoffs/YYYY-MM-DD-<topic>.md`) is used **only** when:
- A session must end while a task or milestone remains unfinished;
- Important noncanonical context, in-flight decisions, or operational state must
  survive context compaction.

**Do not write a handoff when a task is cleanly completed, the repository is
clean, and Git plus active plans already capture the canonical truth.**
Never invent duplicate continuity tracking systems.

---

## 5. Git and Remote Review Workflow

### Normal Accepted Slice
```text
local edit/test loop
  -> focused review
  -> accepted meaningful commit
  -> Checkpoint
  -> push to private GitHub main
  -> external architecture reviewer inspects commit via GitHub
```
Do not push microcommits for every individual edit. Push when a verified,
self-contained slice is accepted.

### Unaccepted or Risky Review Candidate
If a proposed change is substantial, complex, or requires external review before
landing on `main`:
1. Create a short-lived review branch: `git checkout -b review/<short-topic>`.
2. Commit only the bounded review candidate.
3. Push the review branch: `git push -u origin review/<short-topic>`.
4. **STOP** and await external architecture review.
5. Merge to `main` only after explicit acceptance.

### Forbidden Git Actions
The following operations are strictly forbidden on Drift repositories:
- `git reset --hard` (unless explicitly instructed on a temporary branch);
- Broad destructive resets (`git clean -fd`, `git restore .`);
- Force pushes (`git push --force` or `git push -f`) to `main`;
- Rewriting pushed historical commits.

---

## 6. Secret and Credential Handling

Drift enforces strict boundaries regarding sensitive files:
- All credentials, API keys, private tokens, and environment configurations must
  reside in `.env` or external environment variables outside Git.
- `.env` must remain strictly ignored in `.gitignore` and have restricted file
  permissions (`0600`).
- Agents must **never** print `.env`, `cat` secrets into command output, display
  API keys in transcripts or reports, or commit secrets to Git.
- Real provider data payloads, confidential contracts, or private storage paths
  must never be tracked in Git.
- Before pushing to any remote, agents must perform a mandatory pre-push secret
  audit.
