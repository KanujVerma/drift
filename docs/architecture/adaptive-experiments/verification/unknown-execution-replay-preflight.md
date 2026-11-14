# Offline UNKNOWN execution replay review (Issue #533)

**Status: code candidate with focused local verification; source-inventory/capability integration and independent acceptance remain blocked. No live execution or settlement authorization.**

## Ownership and authority

This is the second of two independently scoped Matthew-area coding assists. Matthew remains accountable for [issue #411](https://github.com/KanujVerma/drift/issues/411), his [A1 draft PR #413](https://github.com/KanujVerma/drift/pull/413), the [proposed S4 specification](https://github.com/KanujVerma/drift/blob/matthew/411-unknown-execution-design/docs/superpowers/specs/2026-10-15-unknown-execution-design.md) and the [P4 implementation plan](https://github.com/KanujVerma/drift/blob/matthew/411-unknown-execution-design/docs/superpowers/plans/2026-10-15-unknown-execution.md). The original specifications and implementation decisions are not accepted final runtime contracts. An authorized independent architecture ruling and exact runtime writer claims are still required.

The separate authenticated author is GPT-6 via `Krish-Verma` under the user's current two-issue instruction. Companion assist: [#532](https://github.com/KanujVerma/drift/issues/532), an offline #376 RESULT economics checker. See [AGENTS.md](../../../../AGENTS.md), [agent workflow](../../agent-workflow.md) and [decisions](../decisions.md) for governing boundaries.

This PR creates exactly three new files:

- `scripts/unknown_execution_replay_preflight.py`
- `tests/unit/test_unknown_execution_replay_preflight.py`
- `docs/architecture/adaptive-experiments/verification/unknown-execution-replay-preflight.md`

The V1 execution model, real router and journal, original #411 draft files, existing adapters, persisted history, account books, risk, policies, interpreter, locked dependencies and existing PRs remain untouched.

## Pure review function

`preflight_unknown_execution_replay(payload: object) -> UnknownReplayPreflight` consumes a bounded plain JSON-shaped in-memory fixture, not actual broker responses or real retained account state. It has no external I/O and cannot authorize an operation.

The mock profile `synthetic-unknown-replay-review-v1` names one account, environment, journal, context, original intent hash and client token, plus ordered source-labelled event records. Each event carries a unique ID, contiguous sequence, exact predecessor, strictly increasing UTC observation time and claimed evidence reference. Identity changes, malformed inputs, missing chronology and conflicting same-ID redeliveries produce explicit refusal diagnostics. Hash and reference string matching cannot establish provenance.

The event families and their deliberately narrow meanings are:

| Event | Synthetic rule |
| --- | --- |
| PREPARED | Original request is recorded before any possible send |
| SEND_STARTED | Must follow the unique original PREPARED receipt |
| NOT_SENT | Local refusal before a possible send, never a reported broker rejection |
| OBSERVED_UNKNOWN | No final broker state can be inferred, including fabricated zero exposure or zero cost |
| OBSERVED_CONFIRMED | Recognized but unauthenticated broker status; known quantities and fees may remain nullable |
| CANCEL_REQUESTED | Does not establish confirmed cancellation |
| PAUSED | Does not erase pending obligations or late effects |
| FILL_EFFECT | Exact effect ID is counted once, conflicting redelivery refused |
| RESOLVED | Claims account reconciliation, independent authority and executor-quiescence references |
| RESUMED | Requires a prior claimed resolution, fresh separate authority and an unexpired mandate reference |

The result includes `structurally_reviewable`, `claimed_phase`, `account_hold_required`, `latest_broker_knowledge`, `last_confirmed_broker_status`, `last_confirmed_cumulative_qty`, `last_confirmed_cumulative_fee_usd`, `distinct_reported_fill_effect_qty` and `reasons`. The latest UNKNOWN may preserve a historical last-confirmed quantity without asserting actual current holdings or finality. A known cumulative quantity is not the same as a separate posted accounting effect. Duplicate effects are not counted again.

Known cumulative fee observations remain a monotonic lower bound for later supplied fee observations, even when intervening confirmed observations omit their current fee. The latest missing fee remains `None`; it is not replaced with a prior amount or zero. In particular, `5 -> None -> 4` and `5 -> None -> 0` refuse, while `5 -> None -> 6`, equality at the prior known amount, and a final missing fee remain valid diagnostic histories. This closes [Matthew's source-backed review finding](https://github.com/KanujVerma/drift/pull/535#pullrequestreview-5605191451) without introducing any fee correction/refund, settlement, retry or new execution-state policy.

`account_hold_required` remains **true for this untrusted input surface even when a mock resumption is structurally consistent**. Both `authorizes_dispatch_or_resumption` and `authenticates_journal_broker_or_ledger` are permanently false. A mock journal receipt is not a durable committed transaction; a purported trusted reviewer name is not an accepted issuer or effective proof of executor quiescence. The module neither implements the proposed V2 data model nor changes the unsafe existing runtime behavior identified by #411.

## Requirement and limitation map

R01/R11: no UNKNOWN-to-rejection conversion or fabricated measurements. R02: unchanged V1 data and hashes. R03/R04: PREPARED precedes SEND_STARTED in the fixture, with no claim of genuine durable transactional ordering or cross-process uniqueness. R05/R06: no unverified resolution clears the account hold. R07: evidence of fills after PAUSED is preserved, and duplicate effect IDs are not charged twice. R08: fixture IDs must match the original account/environment/journal/intent/token. R09/R10: real runtime entrypoints, migration and corrupt storage handling are out of scope. R12: no external provider or capital-operation authority.

The essential remaining engineering work is Matthew's proposed A1 runtime integration, including one authoritative journal per account, durable unique reservations before transport, truthful observation types, verified facts and account holds, issuer authority, fencing of senders, separate resolution and resumption, legacy readers, and a single-store atomic settlement interface. Passing this code's tests cannot establish any of those properties.

## Local verification and pending AntiGravity acceptance

The original publication deferred tests. The October 23 continuation used unchanged pinned CPython 3.14.6 and `uv.lock`. New fee-floor vectors first produced **6 failed / 9 passed** against the original checker, with increasing quantities isolating fee regression from quantity regression. After separating the known fee bound from the latest nullable fee, **40 focused tests passed**. Positive histories cover known/equal/increasing fees across missing values, final missing fees, UNKNOWN after a known observation, and an unverified resolution/resumption that still preserves the account hold and false authority properties. An additional **3,905 synthetic histories** matched an independently expressed oracle that checks monotonicity of all nonmissing fees while keeping the latest missing output nullable. Targeted Ruff lint/format, strict `mypy src tests` (472 source files) and sdist/wheel build passed.

The exact source-inventory integration test remains **failed**, yielding **1 failed / 40 passed** with the focused tests. It reports only `scripts/unknown_execution_replay_preflight.py` outside `INERT_SOURCE_PATHS`, matching original exact-head canonical CI 39549202158 (1 failed / 6,054 passed / 2 xfailed; later lint/type/build gates skipped). A direct read-only application of the unchanged production AST guard also refuses the existing permanent-false property name `authenticates_journal_broker_or_ledger` under `FORBIDDEN_DEFINITION_TERMS`. Consequently an inventory entry alone is insufficient: the protected guard's writer and capability owner must review an exact-path capability policy/profile and its positive/negative controls. This issue does not edit that guard, rename the authority property, relocate the script, add skips or weaken any check. The separate #502/#487/#394 gates remain unchanged. No lengthy full suite was launched to repeat this known integration failure.

AntiGravity should inspect the exact published PR HEAD and the three paths against the original #411 spec/plan, then run the following checks after the separately authorized source-capability integration is accepted:

```bash
uv run python -m pytest tests/unit/test_unknown_execution_replay_preflight.py -q
uv run ruff check scripts/unknown_execution_replay_preflight.py tests/unit/test_unknown_execution_replay_preflight.py
uv run ruff format --check scripts/unknown_execution_replay_preflight.py tests/unit/test_unknown_execution_replay_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Also verify no other paths changed, the pinned Python version and `uv.lock` are untouched, and no prior or automatically triggered CI run is incorrectly represented as independent AntiGravity acceptance.

The tests cover unconfirmed submissions, partially known fees and retained known fee bounds, UNKNOWN after known partial fills, local NOT_SENT versus broker rejection, second requests while held, cancellation uncertainty, late fill records, exact duplicate versus conflicting receipts, unrecognized status, decreasing cumulative quantities and fees, missing journal predecessor or sequence, modified original identity, incorrect resumption ordering and expired claimed authority. These are synthetic diagnostic oracles, not real broker, account, journal or settlement evidence.

AntiGravity's later integration review should independently include the actual crash-before-send, send-before-receipt, failed journal write, concurrent worker, stale cached broker status, post-cancellation fill and duplicate settlement cases from Matthew's S4/P4 plan, once their real producers and write-sets are approved. This offline checker does not cover those real integration mechanisms.

## Remaining approvals and publication boundary

Matthew must settle the original architecture, issuer, state/store, reconciliation and implementation boundaries. Appropriate consumers and independent reviewers must approve affected safety, accounting and scientific use, and AntiGravity must run the exact-head checks. These new code and documentation files do not authorize a merge, reclassification of any actual UNKNOWN result, resumption or financial operation. Keep this PR and the original issue open until their respective gates are met.
