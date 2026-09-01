# Drift Maintenance Context and Reuse Implementation Plan

**Status:** Completed on 2026-09-01. Historical plan, not active work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify Drift's always-loaded guidance, correct stale M0 plan state, revise the proposed M1, and preserve durable reuse decisions without changing runtime behavior.

**Architecture:** Git and checked-in canonical documentation remain project truth. Existing lifecycle skills handle transient continuity. Durable reuse principles live in an ADR, while time-sensitive candidate research lives in a dated architecture note.

**Tech Stack:** Markdown, Git, existing Python 3.14 verification toolchain

**Spec:** `docs/superpowers/specs/2026-09-01-maintenance-context-reuse-design.md`

## Global Constraints

- Do not implement M1.
- Do not modify runtime source, tests, package dependencies, or Python requirements.
- Do not add a handoff, current-state file, continuity database, development ledger, nested `AGENTS.md`, adapter, environment, or external tool configuration.
- Keep all broker, trading, network, agent, backtesting, and production capability absent.
- Use no U+2014 em dash.
- Produce one clean maintenance commit after all verification passes.

---

### Task 1: Complete the focused maintenance pass

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/architecture/roadmap.md`
- Modify: `docs/superpowers/plans/2026-09-01-m0-evidence-kernel.md`
- Create: `docs/adr/0005-external-tools-behind-drift-contracts.md`
- Create: `docs/architecture/tool-evaluation.md`
- Create: `docs/superpowers/specs/2026-09-01-maintenance-context-reuse-design.md`
- Create: `docs/superpowers/plans/2026-09-01-maintenance-context-reuse.md`

**Interfaces:**
- Produces a shorter root instruction map, an unambiguously completed historical M0 plan, a revised roadmap, a durable reuse/environment boundary, and a dated nonbinding tool shortlist.

- [x] **Step 1: Rewrite root instructions**

Retain current orientation, hard capability boundary, `StrategyArtifact` provenance-only exception, untrusted research/PIT invariants, ADR/dependency threshold, documentation map, lifecycle skill separation, repository-wins rule, scientific-ledger separation, and the five existing verification commands. Remove low-level ledger behavior and script invocation details that source/tests or README already own.

- [x] **Step 2: Close the stale M0 plan**

Add a visible completion status naming commit `301dc9d`, state that the plan is historical and inactive, and change all execution checkboxes from `[ ]` to `[x]` without altering their historical text.

- [x] **Step 3: Revise the roadmap**

Replace the previous M1 proposal with the roadmap-level PIT dataset manifest/provenance objective and leakage-sensitive scope. State explicitly that M1 has not started and exclude implementation detail beyond the approved design.

- [x] **Step 4: Record durable and tentative reuse findings separately**

Create ADR 0005 for the Drift-defined-contract, current-review, and versioned-artifact isolation principles. Create a concise dated tool note for Qlib, RD-Agent, OpenTrade, NautilusTrader, LEAN, Zipline-reloaded, vectorbt, Backtrader, and MLflow. Each entry must state problem fit, disposition, decisive caveat, and mandatory reverification. Do not state that any tool is selected.

- [x] **Step 5: Run documentation-specific audits**

Verify exact root line/byte changes, no contradictory active M1 claim, no unchecked item in the historical M0 plan, no U+2014, no new dependency or runtime file change, and no implementation capability hidden behind tool names.

- [x] **Step 6: Run the complete M0 gate**

Run:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

Expected: 103 tests pass, lint/format/type checks exit 0, and both distributions build.

- [x] **Step 7: Run a fresh-context Resume audit**

Give a fresh reviewer only repository entry points and the Resume rules. It must correctly identify Drift, M0 completion at `301dc9d`, absent M1 implementation, trust boundaries, canonical documentation, the inactive M0 plan, proposed M1, verification commands, and repository-over-handoff precedence without loading ledger implementation detail.

- [x] **Step 8: Review and commit**

Inspect the full diff and staged stat. Add a completion status to this maintenance plan and mark its own execution checkboxes complete so it cannot become the next stale resume hazard. Commit only the seven maintenance files with:

```text
docs: streamline agent guidance and roadmap
```

After committing, rerun Git status and the documented Checkpoint workflow. Do not create Session Handoff when the repository is complete and clean.
