# Drift Stage 1: Consolidated Antigravity Validation Handoff

## STATUS: IMPLEMENTATION CANDIDATE, NOT ACCEPTED

Repository: https://github.com/KanujVerma/drift
Tracking issue: https://github.com/KanujVerma/drift/issues/456
QA source branch: krish/456-consolidated-intelligence
Original base: 02cb29b9f2ba308e0c9d116e35b13ad0b2de9af2
Accountable producer: Krish. Implementing agent: ChatGPT (GitHub connector).
Independent test/reviewer: Antigravity, read-only.

**At the beginning of QA, pin the exact HEAD of the consolidation PR and print the full SHA.** Do not attribute previous K0/K1-K5 green focused checks to this new source. No full test or independent validation has been performed against this integrated revision yet. A final PR will identify the exact head being handed over.

## What is included

This issue assembles and corrects Krish's source-only offline research system while retaining the previously published PRs as historical inputs:

| Slice | Issue / source PR | Implemented boundary |
|---|---|---|
| Research contract | #375 / #400 | Draft context/candidate/cost/replay specification |
| K0 | #422 / #424 | Synthetic Stage 1 safe-switch preflight |
| K1 | #401 / #447 | Immutable research schemas, raw-choice validation |
| K2 | #402 / #449 | Attempt and cost receipts, offline model replay |
| K3 | #403 / #450 | Scripted proposal and bounded conventional comparator R |
| K4 | #404 / #451 | Point-in-time context and causal learning snapshots |
| K5 | #405 / #452 | Review clocks and typed offline platform requests |
| Shared CI guard | #453 / #454 | Exact allowed module inventory and capability restrictions |
| Unified correction | #456 | Reproducibility, provenance, safety, and regression fixes |

Main corrections include:
- Raw-output and immutable schema verification, strict draft-only research profile, duplicate target refusal.
- Deterministic IDs rather than hidden randomness for context, producer, R, replay, learning, scheduling, platform request.
- Byte-exact SHA256 replay checks, nonfinite/ambiguous JSON rejection, unknown versus proven timeout.
- Complete receipt predecessor chain checks, idempotence, atomic rehydration and canonical JSONL interchange.
- Finite Decimal R scores, deterministic 1e-9 tie band, permutation independence, duplicate-pool rejection.
- Matured and complete learning feedback only, sealed-holdout isolation, cross-arm isolation, method/cutoff/ancestry hash binding.
- Unknown state, pause, pending order, wrong mandate, future observation, stale proposal and empty Stage 1 targets fail closed.
- Source-inventory source files are precisely enumerated and restricted to offline Python/Drift imports, with no transport, subprocess, runtime import, environment or file-opening capability.

## What is NOT authorized or proven

- Not a live LLM agent. Only an offline FakeTransport producer is in scope; no model API key or paid provider requests.
- Not promotion-qualified data; all test inputs here remain synthetic and cannot be upgraded by rehashing.
- No actual orders, broker, real money, paper, prospective operation or risk permission.
- K0's Matthew consumer interface #423 has not been accepted or integrated. A typed research platform request is NOT an M0 risk approval or executed fill.
- ResearchReceiptStore is an in-memory projection with replayable JSONL bytes. Durability requires a separately qualified authoritative M0 ledger adapter and storage guarantees.
- R's injected scoring callable is a synthetic finite-pool seam; actual scientific objective and numeric risk policy require independent approval.
- Kanuj owns the scientific study (#391/#383), independent matched $10,000 accounts, outcome metrics and claims of outperformance. This package is not a completed scored study.
- Historical data rights, calendars, corporate actions, and live/paid source qualification are out of scope.
- M9 activation, M1e Task 8 spending, and operational M15-M17 are not authorized.

## One-shot isolated QA run

Do not overwrite current working trees or start a second implementation writer. Use a fresh isolated worktree from the exact candidate head:

~~~bash
git fetch origin --prune
git worktree add --detach ../drift-qa-456 origin/krish/456-consolidated-intelligence
cd ../drift-qa-456
git status -sb
git rev-parse HEAD
git remote -v
uv sync --locked
uv run python --version
uv run pytest -q -k "intelligence or stage1_switch_preflight or m1e_compatibility"
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
~~~

If one check fails, capture its first reproducible error and continue remaining *independent* checks if practical. Never say the gate passed unless every required check completed successfully. Record exact run ID, SHA, test counts, output and status. Verify the test collection really includes these paths:

- tests/unit/test_stage1_switch_preflight.py
- tests/unit/test_intelligence_contracts.py
- tests/unit/test_intelligence_validation.py
- tests/unit/test_intelligence_receipts.py
- tests/unit/test_intelligence_model_replay.py
- tests/unit/test_intelligence_proposal_producer.py
- tests/unit/test_intelligence_conventional_selector.py
- tests/unit/test_intelligence_context_builder.py
- tests/unit/test_intelligence_learning.py
- tests/unit/test_intelligence_review_scheduler.py
- tests/unit/test_intelligence_platform_bridge.py
- tests/adversarial/test_intelligence_causality.py
- tests/integration/test_stage1_intelligence_end_to_end.py
- tests/integration/test_m1e_compatibility.py

## QA pass A: factual code and contract traceability

Check latest main, ADR 0012, ADR 0017, AGENTS.md, #456 and the accepted boundaries from #375/#406. Map K0-K5 acceptance criteria to exact source, focused tests and the actual diff. Inspect all changed paths against the issue write-set. The original PR branches remain untouched, and historic replay source, Python pin, lockfile and golden upstream M1c/M1d fixtures must remain unchanged.

## QA pass B: deterministic replay and accounting identities

For repeated identical input/method/cutoff, compare context, candidate, attempt, receipts, comparator, learned snapshot, event trigger, request and replay hashes across isolated runs. Raw retained payload bytes changed even by whitespace must invalidate the claimed raw SHA. A timeout must be backed by a retained timeout status. Reject duplicate JSON keys, unknown versions, nonfinite prices or objective scores, duplicate candidate-pool members, duplicate target securities, forged immutable model-copy fields, missing predecessor events and broken JSONL.

Check that an accepted full predecessor chain plus atomic JSONL reload creates identical events. No half-loaded journal should survive a failure. A cost is measured, estimated, verified-zero-only-for-synthetic-offline, or unknown, never treated as zero by default.

## QA pass C: adversarial causality and safety

Probe same-session and subsecond lookahead, unversioned/late source observations, future calendar revisions, stale/future portfolio observations, ambiguous time zones, untrusted news text, arm-to-arm isolation, sealed holdouts, incomplete outcomes, losing valid outcomes and conflicting trial revisions.

K0 must refuse insufficient B4 (under 253 complete sessions), B5 (under 61), missing required ETF/cohort, unknown account or mandate/risk state, and absent trusted clock before any target staging. No empty target is silently converted to deliberate all-cash. A platform request must not generate an order or bypass Matthew M0.

## QA pass D: shared source/replay guard non-vacuity

Review the exact eleven offline intelligence module paths. Inject isolated forbidden operations into scratch copies (never commit): network/process imports, dynamic module/attribute access, environment reads, builtin open and unlisted source paths. The compatibility scan MUST catch each. Confirm M1d pinned replay verification remains intact and unrelated M1e source capabilities were not widened. Do not skip, xfail, rewrite hashes or weaken this gate for a green run.

## QA pass E: integrated K0-K5 engineering demonstration

Run an identical synthetic causal context through the scripted AI producer and conventional R with isolated attempt stores, deterministic candidate validation, correct costs, and next-open typed research request/refusal. Repeat to prove stable hashes and compare results. Verify negatives for unknown state, candidate TTL, wrong mandate, paused account, unresolved pending order, missing response and invalid R objective. Run controlled mutation probes for the strongest guards and confirm new tests fail if removed.

Engineering success is NOT a claim that either arm has a profitable edge or that risk/platform/scientific authorization exists.

## Required single Antigravity report

Post a consolidated read-only review to the integration PR and GitHub issue #456:
1. Exact full SHA, Python/uv/OS, branch/tree and tracked-diff state.
2. All commanded tools, test counts, exit statuses and raw logs.
3. Acceptance traceability and five-pass adversarial report, with mutation non-vacuity evidence.
4. Exact offending file/line/test, reproducer and severity for every defect.
5. Independent ACCEPT / REJECT / INDETERMINATE engineering recommendation.
6. Explicit list of external acceptance still owed by Matthew (#423), Kanuj (#391/#383), and any unapproved source/numeric contracts.
7. Confirmation no broker, credential, network, paid-data, paper or capital operation was used.

Antigravity must not write production code, mark scientific success, modify protected snapshots, or push a new head. Return defects to ChatGPT to fix on an issue-scoped branch. After corrections the entire gate must be rerun against the NEW pinned SHA. Only that exact SHA may receive acceptance.

## Merge and release policy

Do not merge a PR merely because an earlier source snapshot had passing unit tests. Require this exact candidate's full green CI, independent adversarial acceptance, producer/consumer review, accepted contracts, and owner-authorized merge. Research engineering acceptance cannot replace Kanuj's scientific acceptance or future operational permission. Closing original K0-K5 issues and superseding their individual draft PRs is downstream of the integrated code's final acceptance, not an automatic side effect of assembling it.
