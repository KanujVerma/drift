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

## Consolidation-specific regression coverage

In addition to the inherited K0/K1-K5 suites, independently exercise:
- Context identity binding for budget, registry, memory, source grade, causal
  feedback, review trigger and source limitations. Equivalent input orderings
  must retain identity; distinct source identity must not be merged by raw hash.
- Typed RawChoice normalization and exact retained response-byte proofs are
  **different commitments**. Both legitimate JSON reserialization and
  tampered raw bytes must have separate controlled expected outcomes.
- Conventional R's attempt budget reference equals the supplied research
  context budget. Verify deterministic finite Decimal scoring, immutable
  candidate identity and rejection of semantically duplicated pool entries.
- Receipt correction lineage survives exported JSONL replay even if
  lexicographic correction ID precedes its original estimate. Truncated,
  malformed or conflicting replay must never commit a partial receipt store.
- Review trigger identity excludes future event payloads and is invariant to
  event arrival ordering. Future conflicts cannot rewrite the past; conflicting
  evidence actually available by cutoff fails closed. Source-local event IDs
  must be namespaced; contradictory availability stamps for one source event
  fail closed. A material-event feed signal without a causal event is unavailable.
- Untrusted structured proposal parameters with non-finite or opaque values
  must return typed INVALID and retain terminal attempt/cost receipts; no
  serialization exception may strand started work. Forged frozen context,
  invocation and typed-choice objects must be revalidated before consumption.
- Completed learning feedback rejects NaN, Infinity, malformed or scientific-
  notation PnL/metrics, including self-rehashed historical snapshots; valid
  complete losing trials remain eligible. Reuse under a changed learning method
  must be refused without an explicit versioned migration.
- Nonadmitted platform requests have **zero actionable target allocations**
  and no cash reallocation weight, including unsupported execution sessions.
- A synthetic B3/B4/B5 fixed-family AI-versus-R choice test uses only
  preregistered fixture values, independently isolated attempts and a
  clearly non-economic ranking function. It does NOT prove K0 warmup/source
  eligibility, actual transition, risk approval, market efficacy or profit.

Additional source-review regressions to execute on the final pinned head:
- Two distinct transformations of one retained source must both survive context
  deduplication; contradictory first-available claims for one revision must
  fail closed regardless of input order.
- A replay with retained response bytes but no recorded provider finish reason
  must preserve an explicit UNKNOWN classification, not invent `stop`.
- A self-rehashed Stage 1 candidate with weights not summing exactly to one
  or with nonfinite/ambiguous cash weight must produce a non-actionable refusal.
- A comparator pool containing noncanonical arbitrary parameter data must
  reject the pool with an explicit attempt and retained cost, never select a
  winner; without a unique supplied attempt ID it must refuse to fabricate
  replay identity before starting work.

## One-shot isolated QA run

Do not overwrite current working trees or start a second implementation writer. Use a fresh isolated worktree from the exact candidate head:

Run precisely one consolidated validation against the **final
immutable SHA** recorded in the PR checkpoint. A running branch may move, so
resolve its head once and check out the commit, never test moving `HEAD`:
  
~~~bash
git fetch origin --prune
QA_SHA="$(git rev-parse origin/krish/456-consolidated-intelligence)"
git worktree add --detach ../drift-qa-456 "$QA_SHA"
cd ../drift-qa-456
test "$(git rev-parse HEAD)" = "$QA_SHA"
git status -sb
git rev-parse HEAD
git remote -v
uv sync --locked
uv run python --version
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
git diff --check origin/main...HEAD
uv run pytest -q -k "intelligence or stage1_switch_preflight or m1e_compatibility"
uv run pytest
~~~

If running Antigravity's standard **Windows PowerShell** terminal instead,
use this equivalent isolated checkout and command sequence:

~~~powershell
git fetch origin --prune
$QaSha = (git rev-parse origin/krish/456-consolidated-intelligence).Trim()
git worktree add --detach ..\drift-qa-456 $QaSha
Set-Location ..\drift-qa-456
if ((git rev-parse HEAD).Trim() -ne $QaSha) { throw "Wrong QA commit" }
git status -sb
git rev-parse HEAD
git remote -v
uv sync --locked
uv run python --version
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
git diff --check origin/main...HEAD
uv run pytest -q -k "intelligence or stage1_switch_preflight or m1e_compatibility"
uv run pytest
~~~

Ruff/mypy/build and focused tests precede the hour-long full suite so that
obvious failures can be classified promptly. Continue remaining independent
checks when feasible, but **never** report a passing gate if any command failed.


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

## Stacked K1 and K2 integrity corrections for the final QA SHA

The original K0-K5 consolidated branch is an **unaccepted implementation
candidate**. Its K1 and K2 correctness work also has bounded follow-up branches.
These should be integrated into the final consolidated QA revision using
history-preserving Git operations. Until then, validating the original
consolidated SHA alone will miss these corrections.

- **K1, issue #464 / PR #465:** independently validate candidate cash/weight
  totals, raw strategy parameter digests, hold disposition and context build
  clock, plus registry family-key coherence. Its source branch precedes K2.
- **K2, issue #466:** reject contradictory verified-zero/unknown raw cost
  inputs rather than silently erasing evidence; refuse competing corrections
  to one estimate; validate timezone-aware, ordered observed cost timestamps
  both in producer construction and imported journal records.
- K2's original PR #449 still supplies offline response replay, attempt
  predecessor chaining, idempotent ledger projection and atomic canonical
  JSONL export/import. These corrections complement rather than replace it.
  Do not merge both the original PR and the consolidated equivalent.

K2-specific non-vacuity probes in addition to the baseline T06/T09/T10/T11:

1. Supply `amount="1"` under `verified_zero` together with a zero
   evidence reference. It must be refused, not silently rewritten to zero.
   Unknown cost with supplied amount or currency must likewise be refused.
2. After one estimate-to-actual correction, submit a distinct second actual
   receipt that supersedes the same estimate. It must refuse even if both
   receipts have valid self-consistent hashes. An identical retry of the
   first correction remains idempotent.
3. Recompute a fully valid cost row's outer `record_hash` after moving
   `recorded_at` before `incurred_end`. Deserialization alone is not
   sufficient: store admission and JSONL rehydration must reject the row,
   leaving prior store state byte-identical.
4. Preserve historical valid unknown costs and absent optional timestamp
   evidence as unknown; do not fabricate invoice times or monetary zero.
5. Repeat offline replay with changed raw bytes, ambiguous JSON, a retained
   timeout, an unsupported model response and unchanged trusted evidence;
   compare both normalized decision and raw byte identities.

For *slice development only*, run
`uv run pytest -q tests/unit/test_intelligence_contracts.py
tests/unit/test_intelligence_validation.py
tests/unit/test_intelligence_receipts.py
tests/unit/test_intelligence_model_replay.py`
on the stacked K2 SHA. The **final** Antigravity validation must still run
the complete pinned suite and all five independent review passes on the
eventual integrated `krish/456-consolidated-intelligence` immutable SHA,
not on any older green child head.

**Unresolved external boundary:** K2's `ResearchReceiptStore` is an
in-memory, append-only *projection* with canonical JSONL interchange, not a
durably committed SQLite/M0 event log. Until Matthew's ledger interface and
independent consumption acceptance are qualified, it does not prove fsync,
crash-safe provider invocation admission, cross-arm economic allocation,
provider-invoice authenticity, or monetary cap compliance. The team must not
call K2's offline receipts an operational spending authorization.
## Stacked K3 correctness correction for the final QA SHA

The original K3 implementation #403 / PR #450 is still an unmerged
implementation candidate. K3 issue #469 supplies a separate, issue-scoped
correction branch stacked on the K2 hardening PR #467. Only the final
consolidated immutable QA revision can be accepted; do not count tests
from this separate corrective branch as acceptance of PR #457.

### Exact K3 behavior and adversarial acceptance

1. **Whole-pool admission**: Optimizer R must reject an entire finite
   preregistered candidate pool if *any* member fails deterministic
   validation, including when a valid, high-scoring candidate appears
   first. No silently reduced pool, selected candidate, or score list
   survives this rejection. Preserve one synthetic zero-cost receipt
   and both lifecycle events with the error
   \`INVALID_CANDIDATE_POOL_MEMBER\`.
2. **Comparator tie rule**: Within the existing 1e-9 Decimal score
   equivalence band, compare \`(family_id, parameters_hash, candidate_id)\`.
   \`strategy_ref.sha256\` is a code artifact identity, not the actual
   strategy-parameter digest. Include an adversarial fixture in which
   candidate-ID order and parameter-digest order disagree, and permute
   the pool to demonstrate identical selection.
3. **Invocation and candidate identity**: The comparator's deterministic
   seed must bind context, method, pool, validation policy, explicit
   logical request ID, candidate expiry and clock. Candidate IDs also
   bind the generated attempt, so a distinct invocation cannot reuse
   an earlier candidate ID. Started context references must use the
   actual \`context.profile\`, not a hard-coded \`v1\`.
   Exact identical offline invocation retries remain idempotent.
   An actual *new* attempt needs a distinct caller-supplied
   \`logical_request_id\` or \`attempt_id\`; no hidden random identity.
4. **Receipt ordering**: R persists its synthetic compute cost before
   committing a completed/rejected terminal attempt that references
   that cost. Both success and rejection preserve the cost; no
   provider usage or verified provider invoice is implied.
5. **Scripted provider-free producer**: A fake cost recorded as
   scientific notation, non-finite text, or a nonzero amount with
   blank currency must be classed \`unknown\` instead of throwing after
   a started attempt. Invalid candidate TTL timezones are refused
   before an attempt begins. Distinct valid expiry instants or logical
   requests create separate deterministic identities. This does
   not make offline FakeTransport an authenticated live provider.
6. **T07 / T09 / T13**: Replay a valid and invalid scripted response;
   validate the entire conventional pool; preserve all terminal and
   cost receipts; test distinct AI and R attempts and separate
   arm-specific stores against the same frozen context reference.
   No callback objective is deemed scientifically accepted merely
   because the finite pool and scoring seam run.

### Dedicated K3 tests on its own stacked SHA

\`\`\`bash
uv sync --locked
uv run pytest -q tests/unit/test_intelligence_proposal_producer.py tests/unit/test_intelligence_conventional_selector.py
uv run pytest -q tests/unit/test_intelligence_contracts.py tests/unit/test_intelligence_validation.py tests/unit/test_intelligence_receipts.py tests/unit/test_intelligence_model_replay.py tests/unit/test_intelligence_proposal_producer.py tests/unit/test_intelligence_conventional_selector.py
uv run ruff check src/drift/intelligence tests/unit/test_intelligence_*
uv run ruff format --check src/drift/intelligence tests/unit/test_intelligence_*
uv run mypy src/drift/intelligence tests/unit/test_intelligence_*
uv build
git diff --check
\`\`\`

These commands are **validation instructions, not an assertion of passing
results**. On final consolidation, run all five independently reviewed QA
passes and the *full* pinned test suite documented above. Publish actual
command output, pinned commit, Python/OS, failures and reviewer evidence.

### External boundaries and release prerequisites

The scorer is an injected, deterministic synthetic objective. This change
does not authenticate a scientifically preregistered candidate universe,
commit to a particular risk-adjusted objective, establish matched
historical B3/B4/B5 investment performance, or authorize an LLM or trade.
Kanuj's experiment approvals and Matthew's platform contract acceptance
remain separate. Existing original K3 and integration branches must be
preserved; integrate the corrective commit history without forcing or
resetting them, then retest at the new integration SHA.

