# Drift Stage 1: Consolidated Antigravity Validation Handoff

## AntiGravity audit DEF-01 to DEF-04 remediation (issue #482)

The independent AntiGravity report for commit
`d84fbf1a31b55136a93167f40fe88ce0aabb087d`
is at https://github.com/KanujVerma/drift/pull/457#issuecomment-6282879010.
Its **REJECT** conclusion remains valid for that old SHA; never relabel that
audit a pass. Source corrections are in issue #482 and draft PR #483, and
the final unified PR #457 must publish a **new exact HEAD** for the next
independent AntiGravity evaluation.

Four static gate corrections, all without changing the fixed research
contracts, weakening tests or relaxing the positive offline capability guard:

1. **DEF-01, Git whitespace:** Removed extra blank lines at EOF in this
   handoff and `tests/unit/test_intelligence_proposal_producer.py`. Verify
   `git diff --check origin/main...HEAD` and no U+2014 on the new QA SHA.
2. **DEF-02, Ruff lint:** Applied pinned `ruff check --fix .` results,
   corrected the test import order and quoted annotations, wrapped the
   M1e non-vacuity probe line without changing its asserted source, and
   explicitly captured per-iteration objective callbacks (B023).
3. **DEF-03, Ruff formatting:** Applied actual pinned `ruff format .`
   output to the 22 affected Python source/test files; preserved original
   CRLF convention in the historical M1e compatibility test. Do not change
   the CI rule set or historical replay/lockfile pins.
4. **DEF-04, Mypy strict:** Preserved all explicit validation contracts
   while narrowing registry `type[BaseModel]`, prior receipt time/record
   types, feedback reference loop identities, missing response bytes,
   typed test strategy/source-grade literals and fixtures. Removed
   problematic untyped `**dict` expansion in the scheduler tests.
   No type ignores or blanket typing exemptions were introduced.

### Verified corrective source evidence

- **Read-only focused/static verification:** GitHub Actions
  https://github.com/KanujVerma/drift/actions/runs/39367938465
  completed **SUCCESS** with:
  `ruff check .` exit 0, `ruff format --check .` exit 0,
  `mypy src tests` exit 0 (466 source files), `uv build` exit 0 and
  focused K0-K5/compatibility checks **342 passed, 0 failed,
  5,597 deselected, 6 Pydantic adversarial-fixture warnings**.
- **Scope:** That read-only probe checked the corrected source SHA
  `e649e9aef4d584baa02a110c10302312ee07b696`
  plus a temporary `contents:read` diagnostic workflow in a disposable
  branch. It never pushed code, committed fixes, altered main or ran
  a live broker/model. The source changes subsequently receive a new
  final QA SHA after documentation and main reconciliation.
- **Canonical acceptance remains separate:** Only full pinned pytest,
  source-inventory/replay checks, Ruff, format, Mypy, build, Git diff
  hygiene, five adversarial QA passes and independent review on
  **the new PR #457 HEAD** can establish engineering acceptance.
  The previous successful focused checks are strong corrective evidence,
  not a substitute for the final all-repository gate.
- **Windows portability:** AntiGravity's 114 Windows-only legacy
  failures depend on POSIX timezone/symlink paths. Report these
  distinctly from the canonical Linux CI result. Never modify the
  protected historical M1d/M2 baselines merely to relabel them as passing.

### What to hand AntiGravity

Give AntiGravity only
https://github.com/KanujVerma/drift/pull/457
and this canonical handoff at the **matching pinned HEAD**. It should
check out that exact SHA in a fresh isolated worktree, re-run the entire
independent QA checklist below, compare accepted main, and post one
ACCEPT / REJECT / INDETERMINATE engineering report to PR #457
and issue #456. A failure goes back to the original writer; the next
fixed commit requires a new independent QA run.

---

## START HERE: Final unified K0-K5 QA source and authority

**This section supersedes older status paragraphs later in this file.** The
later K1-K5 sections are retained as historical regression designs, not
claims that the earlier unresolved defects still exist at the final head.

- **Repository:** https://github.com/KanujVerma/drift
- **One integration PR:** https://github.com/KanujVerma/drift/pull/457
- **Single source branch:** `krish/456-consolidated-intelligence`.
- **Final pinned SHA:** take the exact 40-character `head_sha` from PR #457
  and the matching latest checkpoint on issue #456. Checkout that **commit**,
  not the moving branch or the unmerged source PRs. Check both values agree.
- **Responsible implementer:** ChatGPT / Krish workstream. **Independent
  tester:** Antigravity, read-only against an isolated checkout.
- **Stage:** implementation + corrective tests published. Engineering acceptance
  requires exact-head green CI, five QA passes, independent review and
  accepted producer/consumer contracts. Do **not** imply scientific or
  operational approval from a green synthetic test.

### Source ancestry and work covered

| Feature | Code origin | Corrections carried into the consolidated ancestry |
|---|---|---|
| K0 safe switching | #422 / PR #424 | #456; independent Matthew #423 consumer acceptance still outstanding |
| K1 contracts, validation | #401 / PR #447 | #464 / PR #465 |
| K2 receipts, offline replay | #402 / PR #449 | #466 / PR #467; final CI repair #478 |
| K3 AI FakeTransport and R selector | #403 / PR #450 | #469 / PR #470; final CI repair #478 |
| K4 causal context and learning | #404 / PR #451 | #473 / PR #474 |
| K5 scheduler, synthetic platform bridge | #405 / PR #452 | #475 / PR #476 |
| Shared offline capability gate | #453 / PR #454 | Consolidated positive allowlist #456, NOT disabled |

All original source PRs remain separate and unmerged. Do not merge both original
and consolidated implementations into main. A fast-forward of the consolidated
feature branch is a source integration step, **not** a release acceptance.

### CI failures resolved in source by final remediation #478

The latest pre-remediation K5 full CI run
https://github.com/KanujVerma/drift/actions/runs/39351538328
reported **5,786 passed, 2 failed, 2 xfailed and zero errors**. Both
failures were K2: forbidden builtin `getattr` in `receipts.py`, and
a timezone-naive cost clock reaching canonical hashing before it raised
`INVALID_COST_TIMESTAMP`. Both are repaired in this source ancestry:
the chronology checker uses explicit fields and validates before hash
construction and store admission. The added store-failure regression
must prove malformed `model_copy` clocks cannot mutate the journal.

The earlier K4 run
https://github.com/KanujVerma/drift/actions/runs/39348668275
also exposed K3's `copy` import as a positive capability violation.
Final remediation replaces that import and its deep-copy call with
`canonical_json` and `json.loads`, preserving an independent, deterministic,
offline and non-executable JSON input snapshot. A noncanonical object with
a hostile copy hook must refuse before its hook executes. **Do not widen or
skip the capability guard to make these checks pass.**

These fixes are source-level, **not yet an observed green rerun**.
The authoritative acceptance result is only the full QA on the new pinned
PR #457 SHA. Older green, failed, cancelled, pending or differently based
runs cannot be reclassified as accepted.

### First reproduce the corrected failures on the final pinned SHA

Use the checkout in the `One-shot isolated QA run` section below, then run:

```bash
uv run pytest -q tests/unit/test_intelligence_receipts.py::test_k2_rejects_noncausal_cost_timestamps_at_creation_and_replay tests/unit/test_intelligence_receipts.py::test_naive_cost_copy_refused_before_store_hash_and_without_partial_state
uv run pytest -q tests/unit/test_intelligence_conventional_selector.py
uv run pytest -q tests/integration/test_m1e_compatibility.py::test_m1e_additions_are_allowlisted_inert_and_leave_m1d_pins_unchanged
```

Then run **all** checks, on the **same SHA**, from `One-shot isolated QA run`:
locked/pinned environment, full pytest, Ruff check/format, mypy, build,
diff/source inventory, adversarial mutation/causality and exact acceptance
trace. No skipping the long full suite or changing repository code to pass.

### Required report and boundaries

Report the exact SHA and main compare base, GitHub run ID, OS/Python/uv,
every command's exit status and test counts, fixed-defect repros, all five
adversarial pass findings, accepted/rejected/indeterminate recommendation,
and the first actionable file/line/reproducer for every failure. Post
read-only evidence to issue #456 and PR #457. If a fix is required, return
it as a scoped finding to the Krish writer; do not edit protected sources.

Passing engineering QA must not claim actual model-provider interaction,
historical market qualification, performance superiority, durable M0 ledger
commit, risk authorization, approved execution, broker connection, paper
or shadow trading, live orders, real capital or promotion eligibility.

---

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
   `INVALID_CANDIDATE_POOL_MEMBER`.
2. **Comparator tie rule**: Within the existing 1e-9 Decimal score
   equivalence band, compare `(family_id, parameters_hash, candidate_id)`.
   `strategy_ref.sha256` is a code artifact identity, not the actual
   strategy-parameter digest. Include an adversarial fixture in which
   candidate-ID order and parameter-digest order disagree, and permute
   the pool to demonstrate identical selection.
3. **Invocation and candidate identity**: The comparator's deterministic
   seed must bind context, method, pool, validation policy, explicit
   logical request ID, candidate expiry and clock. Candidate IDs also
   bind the generated attempt, so a distinct invocation cannot reuse
   an earlier candidate ID. Started context references must use the
   actual `context.profile`, not a hard-coded `v1`.
   Exact identical offline invocation retries remain idempotent.
   An actual *new* attempt needs a distinct caller-supplied
   `logical_request_id` or `attempt_id`; no hidden random identity.
4. **Receipt ordering**: R persists its synthetic compute cost before
   committing a completed/rejected terminal attempt that references
   that cost. Both success and rejection preserve the cost; no
   provider usage or verified provider invoice is implied.
5. **Scripted provider-free producer**: A fake cost recorded as
   scientific notation, non-finite text, or a nonzero amount with
   blank currency must be classed `unknown` instead of throwing after
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
7. **Fixed inputs despite callback effects**: R snapshots the entire
   pool before objective scoring begins, validates all members as one
   unit, and passes the scoring callback a fresh candidate clone.
   A scorer that mutates its input or the caller's later pool members
   must neither rewrite a candidate record nor alter the precommitted
   pool that is being ranked. A callback itself is NOT a security
   sandbox or an approved scientific objective. An independent
   capability-denied harness is required before claiming untrusted
   external scorer execution is safe. Opaque noncanonical pool objects
   must be refused before running custom Python `__deepcopy__` hooks, with
   a retained explicit-attempt rejection and synthetic cost.
8. **Full reference and clock binding**: Both scripted and R attempts
   bind method and policy ID/version/hash rather than digest alone.
   The conventional clock and expiry are normalized to UTC after
   refusing missing timezone offsets. Changes to any of these
   commitments require separate invocation identities.

### Dedicated K3 tests on its own stacked SHA

```bash
uv sync --locked
uv run pytest -q tests/unit/test_intelligence_proposal_producer.py tests/unit/test_intelligence_conventional_selector.py
uv run pytest -q tests/unit/test_intelligence_contracts.py tests/unit/test_intelligence_validation.py tests/unit/test_intelligence_receipts.py tests/unit/test_intelligence_model_replay.py tests/unit/test_intelligence_proposal_producer.py tests/unit/test_intelligence_conventional_selector.py
uv run ruff check src/drift/intelligence tests/unit/test_intelligence_*
uv run ruff format --check src/drift/intelligence tests/unit/test_intelligence_*
uv run mypy src/drift/intelligence tests/unit/test_intelligence_*
uv build
git diff --check
```

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
## Stacked K4 causal memory correction and final QA additions

**Scope/lineage:** Original K4 #404 / PR #451 is an unaccepted
implementation candidate and already appears in the original consolidated
PR #457. K4 correction issue #473 branches from the K3 corrective head
`936c97236a85b1b768b2c9ad8e5cef7e068506f8`. Its independent
source/test write-set consists of `context_builder.py`, `learning.py`,
their two corresponding unit-test files, `test_intelligence_causality.py`,
and this consolidated handoff. K0-K3, K5 and platform paths remain protected.

### K4 trust-boundary changes to independently validate

1. **Typed causal input readback:** Even Pydantic frozen objects can be
   forged through `model_copy(update=...)`. K4 now validates the entire
   `CandidateInput` payload including nested `ArtifactReference`
   immediately before looking at holdout flags, availability timestamps,
   arm identity or deduplication. Tampered digests and invalid timestamps
   must be refused with `INVALID_CONTEXT_INPUT`; these inputs may never
   silently become a new hash-valid context. Boolean holdout flags
   must be actual booleans, not coerced strings such as `"false"`.

2. **Feedback reference hygiene:** Every `feedback_refs` entry is
   revalidated. A `holdout:` or `sealed_holdout:` reference must be
   refused (case-insensitive); two entries with the same ID/version but
   different digests must produce `FEEDBACK_REVISION_CONFLICT`.
   Exact repeated references are idempotently deduplicated and input
   order is irrelevant to the resulting `ResearchContext` hash.

3. **Historical learning-state integrity:** An attacker must not be able
   to rehash an old `LearningSnapshot` with duplicate `trial_id` values,
   out-of-order matured feedback or impossible version/previous-reference
   relationships and make that history admissible. Version one has no
   predecessor; higher versions have a preceding `vN` reference and
   cannot refer to their own snapshot ID. All historical members must
   be same-arm, complete, finite, causal and outside sealed holdouts.

4. **Causal feedback ingestion:** The update path must reparse caller
   feedback before incorporating any matured same-arm result, and
   store an independent nested metrics copy. Holdout and completion flags
   must be strict booleans, and snapshot versions strict positive integers.
   Subsequent caller mutation
   must not change the stored learning snapshot. Valid complete losing
   trials are included (T12), while malformed same-arm completed
   trials refuse; feedback that matures after cutoff remains excluded
   (T01/T02) even when it contradicts a previously mature trial.
   Peer-arm outcomes cannot enter the arm snapshot (T04), and
   sealed reports are refused even if they nominally belong to a
   different arm (T05). Both input-order permutations must agree.

5. **Negative and mutation cases:** Rehash forged duplicates and
   reordered snapshots with the repository's canonical hash function.
   Force impossible predecessor version and self-cycle variants.
   Supply forged nested digest and non-datetime `model_copy` inputs,
   unparseable metric values, tampered source metrics, conflicting
   same-revision feedback references, and a delayed contrary result.
   Each check must fail for its intended causal/security reason, not
   through an unrelated setup exception.

### Dedicated K4 verification commands on its pinned corrective SHA

```bash
uv sync --locked
uv run pytest -q tests/unit/test_intelligence_context_builder.py tests/unit/test_intelligence_learning.py tests/adversarial/test_intelligence_causality.py
uv run pytest -q tests/unit/test_intelligence_*.py tests/adversarial/test_intelligence_causality.py
uv run ruff check src/drift/intelligence tests/unit/test_intelligence_* tests/adversarial/test_intelligence_causality.py
uv run ruff format --check src/drift/intelligence tests/unit/test_intelligence_* tests/adversarial/test_intelligence_causality.py
uv run mypy src/drift/intelligence tests/unit/test_intelligence_* tests/adversarial/test_intelligence_causality.py
uv build
git diff --check
```

Commands above are the **test plan**, not reported passing results.
Use the canonical pinned interpreter and exact GitHub Actions run for
observed results. The final Antigravity run remains the *full*
repository-wide pinned suite and five adversarial passes on a newly
integrated, immutable K0-K5 SHA with these K4 corrections included.

### Scientific and operational limits unchanged

A supplied `ArtifactReference`, `CandidateInput.available_at`, or
`TrialFeedbackRecord.matured_at` is not independent evidence of source
publication, original receipt time, trial maturity, source rights or
scientific feedback eligibility. An unauthenticated caller can still
lie by supplying internally consistent references/timestamps. Kanuj's
independent EXPERIMENT/ELIGIBILITY producer and Matthew's accepted
source/RESULT and M0 interfaces must authenticate their own records
before qualified use. This K4 slice performs *intrinsic* fail-closed
validation, not origin attestation.

Likewise, `feed_state_ref` binds a supplied feed-status revision but
does not itself classify or authenticate an external data feed; T03
requires independently qualified source/feed evidence and separate
consumer acceptance. A Pydantic frozen model with nested dictionaries
still requires trusted readback at every consumer boundary, not direct
use of mutable internals. No local test can establish live LLM
learning quality, scientific superiority, safe broker execution,
model spend authorization or a valid trading mandate.
## Stacked K5 schedule and platform bridge acceptance

**Status:** K5 original #405/PR #452 exists but remains unmerged and not
independently accepted. K5 issue #475 records a bounded, stacked correction
branch on the frozen K4 source #474. This section supplements, rather than
replaces, the five QA passes and complete pinned tests above. The K0-K5
consolidation #456/#457 must be moved by a history-preserving, writer-owned
operation to a final **immutable** QA SHA after all accepted corrections.
Child-PR CI is not the final engineering qualification.

### K5 changes to verify

1. **K1 and K5 compatibility:** K5 synthetic candidate fixture parameters
   now use exact canonical `parameters_hash`, not an arbitrary 64-character
   placeholder. Invalid/forged K1 candidates must fail their own
   `ResearchCandidate` constructor or K5 trust-boundary validation, not
   deserialize as authorized proposals. A `hold` fixture cannot retain a
   proposed strategy, allocation or cash target. Never weaken K1 to get K5 green.
2. **Trusted request identity:** K5-generated `request_id` commits to the
   candidate, full observed account state and verification reference,
   observation time, pause/order flags, dispatch time, and intraday/fallback
   capability. Distinct policy or state inputs must not alias one request.
   Replay-identical inputs yield exactly identical request IDs and record
   digests. Consumer idempotency still requires an independent M0 ledger.
3. **Complete reference checks:** Equal SHA-256 bytes do not make a different
   portfolio ID/version or mandate ID/version authorized. Both full references
   must match exactly. Unverified, stale/future, paused, pending, wrong-account
   or wrong-arm states must refuse with **zero target allocations and no cash
   reallocation**. Unknown timezone evidence refuses.
4. **Intrinsic request integrity:** Even a self-rehashed
   `PlatformExecutionRequest` marked admitted must reject empty targets,
   duplicated securities, out-of-range/nonfinite/scientific-notation weights,
   sums not exactly one including cash, unavailable dispositions, or
   contradictory refusal state. Nonadmitted states cannot contain actionable
   allocations and cannot be relabeled to valid admissions.
5. **Event references and causal scheduling:** A feed event reference is
   derived from the canonical hash of BOTH `source_id` and `event_id`,
   preventing collisions when either contains a delimiter. Event materiality
   and condition join the trigger's identity. A changed feed signal or same
   revision with contradictory bytes/times refuses in both input orders.
   Exact duplicate events are idempotent, while conflicting status
   or availability for one source revision refuses. Future feed observations
   do not rewrite the current cutoff, while observed feed failures have a
   deterministic broken-before-unknown precedence.
6. **Calendar and distinct review clocks:** Revalidate caller-supplied
   calendar/policy/event objects at the boundary, refuse contradictory
   historical revisions even when the current revision is newer, refuse
   contradictory effective times for the same revision even with identical
   content bytes, and refuse history without an identified current calendar.
   Event cooldown may
   suppress an event-driven review but must not suppress an independently due
   routine weekly or planned monthly review.
7. **Defensive-only policy:** In a locally checked candidate allocation,
   refuse an empty implied liquidation, unknown or nonfinite current
   positions, negative weights, inconsistent current totals, duplicate
   targets or an increase in an existing security. This function is *not*
   a platform-authenticated risk gate, position accounting rule or order.
   M0 must authorize any actual consequence and tie policy to the specific
   immutable accepted review trigger.

### Isolated K5 commands (new exact stacked SHA)

```bash
uv sync --locked
uv run pytest -q tests/unit/test_intelligence_review_scheduler.py tests/unit/test_intelligence_platform_bridge.py
uv run pytest -q tests/unit/test_intelligence_contracts.py tests/unit/test_intelligence_validation.py tests/unit/test_intelligence_review_scheduler.py tests/unit/test_intelligence_platform_bridge.py
uv run ruff check src/drift/intelligence tests/unit/test_intelligence_*
uv run ruff format --check src/drift/intelligence tests/unit/test_intelligence_*
uv run mypy src/drift/intelligence tests/unit/test_intelligence_*
uv build
git diff --check
```

**These commands are planned checks, not passing evidence.** The exact
K5 PR and canonical CI report must record actual outcomes. Inspect mutation
tests, positive controls, failure-path zero allocations and strict typed
readback. The final Anti-Gravity run remains the entire pinned offline
repository test suite, coverage/source guard, Ruff, mypy, build, Git checks,
five adversarial QA passes and independent consumer/scientific review on
the final integrated SHA.

### Existing integration blockers and authority boundary

Prior exact-head K3 canonical CI run
https://github.com/KanujVerma/drift/actions/runs/39344312724
reported 5,731 passing, 2 failing and 23 erroring tests. It contains
a K2 `getattr` source-capability refusal, a K2 naive-cost-clock hashing
exception, and K5 fixture violations of the new K1 parameter-hash
invariant. This K5 correction addresses the **fixture violations only**.
The two K2 problems must be repaired within a distinct K2-owned
corrective write-set and retested before final integration acceptance.
No broad static guard disablement or K1 schema relaxation is permitted.

Matthew's proposed/under-review source, risk and execution interfaces
(#379, #380, #423) are not proof of an accepted M0 consumer. Kanuj owns
independent campaign science. Research requests marked `admitted` at
this synthetic seam are **not orders, approved fills, authorized
trades, risk-enforced dispatches, or evidence of strategy performance**.
No provider credential, network inference, paid data, paper/shadow/live
broker call, promotion or capital permission is introduced.
