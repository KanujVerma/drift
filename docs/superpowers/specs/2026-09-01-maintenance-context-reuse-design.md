# Drift Maintenance Context and Reuse Design

**Status:** Completed on 2026-09-01. Historical maintenance design, not active work.

## Purpose

This maintenance pass improves Codex orientation and repository continuity without implementing M1 or changing Drift runtime behavior. It keeps durable project truth in Git, code, tests, ADRs, architecture documentation, the roadmap, and active execution plans. Drift's scientific evidence ledger remains separate from development-session context.

## Root instructions

The root `AGENTS.md` will become a concise map and repository-wide policy. It will retain:

- the current M0 capability boundary;
- the provenance-only meaning of strategy artifact metadata;
- repository-wide evidence, point-in-time, and architecture-change invariants;
- canonical documentation pointers;
- the Checkpoint, Session Handoff, and Resume responsibility split;
- the normal verification commands.

Detailed ledger mechanics already enforced by source, database constraints, and tests will be removed from the always-loaded file. No nested `AGENTS.md` files will be created.

## Continuity

Drift will not add `CURRENT.md`, `STATUS.md`, a handoff index, a continuity database, a development ledger, or structured checkpoint files. Checkpoint owns verified repository state. Session Handoff records unfinished task context that is not already canonical. Resume verifies plans and handoffs against Git before continuing. Repository state wins conflicts, and development continuity never enters the scientific evidence ledger.

The completed M0 plan will be marked historical, linked to completion commit `301dc9d`, and have its execution checkboxes marked complete so Resume cannot treat it as active work.

## Roadmap

The next proposed milestone will be M1: point-in-time dataset manifests and provenance validation. M1's objective is to establish what information existed when, what universe was observable, how revisions and corporate actions are represented, and how later evaluation can detect temporal leakage. This maintenance pass does not implement M1.

## Reuse boundary

Drift will build its scientific and trust contracts, then reuse commodity components only when they satisfy those contracts with lower total complexity and acceptable licensing, security, reproducibility, compatibility, and operational tradeoffs.

A focused ADR will record this durable boundary and the use of versioned artifact interfaces for external tooling with incompatible runtimes. A separate dated tool-evaluation note will retain concise current dispositions for evaluated but unselected tools. The note is not an adoption decision and must be reverified before use.

Python remains `>=3.14`. Qlib remains only a candidate. No external tool, adapter, environment, dependency, or configuration is added.

## Acceptance

- Root instructions are materially shorter while retaining all non-mechanical safety decisions.
- The historical M0 plan is unambiguously complete.
- The roadmap names PIT dataset manifests as the next proposed milestone and states that M1 has not started.
- The ADR records only durable architecture principles; the tool note clearly separates tentative candidates.
- No product/runtime file or dependency changes.
- The full M0 test, lint, formatting, type, and build gate passes.
- Forbidden-capability, documentation contradiction, and U+2014 scans pass.
- A fresh-context Resume audit can identify M0 completion, boundaries, canonical sources, and the proposed next milestone without redoing M0.
