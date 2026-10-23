# V1 broker-report uncertainty and original-evidence audit (Issue #543)

**Source-backed offline candidate with focused local verification. Full exact-head CI and independent acceptance remain pending. This does not repair live S3/S4 execution or authorize any order.**

## Accountable ownership and live contract

Matthew owns [#411](https://github.com/KanujVerma/drift/issues/411), whose complete A1 UNKNOWN-state and durable-reconciliation [S4 specification and P4 plan](https://github.com/KanujVerma/drift/pull/413) are still unaccepted original producer proposals. The current accepted V1 `src/drift/domain/execution.py` has only `NEW`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REJECTED`, `EXPIRED`; no truthful UNKNOWN. The existing `src/drift/adapters/robinhood/adapter.py` translates certain transport-failure outcomes into a `REJECTED` V1 report, also exposing paths with `cancellation_failed:` while the actual broker cancellation result is not established. The frozen V1 schema also defaults `fee_amount=0` even when an original separate measured fee receipt is missing.

The source-backed facts are known from the merged code; they do **not** authorize rewriting historical V1 rows or silently adding an enum value. A true runtime fix requires Matthew's accepted new A1 producer contracts: append-before-I/O, durable holds, original verifier, single authoritative journal and atomic settlement/resumption, separately tested against legacy clients. **This PR supplies none of those mechanisms.**

The implementation publisher is authenticated `Krish-Verma` / GPT-6 at the user's direction to do two additional inactive Matthew-area code tasks, while Matthew retains contract and runtime ownership. The paired development-only risk-feasibility issue is [#542](https://github.com/KanujVerma/drift/issues/542). Existing offline [#533/#535 synthetic A1 event replay](https://github.com/KanujVerma/drift/pull/535) is distinct; this new script instead **consumes current real V1 Pydantic classes** and probes specific current V1 epistemic failure patterns, not a proposed new event schema.

Read [AGENTS.md](../../../../AGENTS.md), [current V1 execution](../../../../src/drift/domain/execution.py), [current Robinhood V1 adapter](../../../../src/drift/adapters/robinhood/adapter.py), [#411](https://github.com/KanujVerma/drift/issues/411), [#379](https://github.com/KanujVerma/drift/issues/379), [#380](https://github.com/KanujVerma/drift/issues/380) and [agent workflow](../../agent-workflow.md).

## Exact new, nonoverlapping files

- `src/drift/execution/v1_evidence_audit.py`: read-only actual `OrderIntentV1` and `ExecutionReportV1` audit.
- `tests/unit/test_execution_v1_evidence_audit.py`: actual public-builder synthetic/adversarial V1 source tests.
- `docs/architecture/adaptive-experiments/verification/execution-v1-evidence-audit.md`: this contract and AntiGravity packet.

No V1 schema or hash preimage, accepted broker adapter/router/journal, source/rights, account-risk ledger, original Matthew #411 S4/P4 draft, original #533, golden replay, .python-version, uv.lock, live connection or private broker credential was changed. There are no orders, cancellations, host connections, data fetches or account reads. The function accepts supplied in-memory objects and returns only a diagnostic.

## Function contract and important missing evidence

`audit_execution_v1_originals(intent, reports, claims, as_of_utc) -> V1ExecutionAudit` requires an actual `OrderIntentV1`, an ordered sequence of actual `ExecutionReportV1` records and one `V1OriginalEvidenceClaim` per distinct original report. Both V1 object classes are rebuilt using their **accepted current Pydantic validators**, including original self-excluding content hash. No duck-typed or caller equality-object substitutes are accepted. The report/claim collection is bounded to 512 entries as a local review limit, not a real broker limit.

The proposed `V1OriginalEvidenceClaim` is just a descriptive index containing a report ID, declared source kind (`BROKER_OBSERVED`, `LOCAL_BEFORE_SEND`, `UNCONFIRMED_TRANSPORT`, `UNVERIFIED`), an optional original source-ref string, claimed original availability and optional fee-receipt ref. Its names and strings are **not** a new production wire, an authenticated order source or a trusted attestation. No caller-selected value of `BROKER_OBSERVED` can upgrade a V1 status to actual broker-final or grant a side effect.

The script verifies:
- Original report and intent ID must match, with bounded chronological, exact UTC availability and no after-cutoff report accepted as past evidence.
- Distinct V1 reports must not reuse one `report_id` for changed contents. An *exact* repeated report ID/hash is idempotent for this local review, not a second fill or independent broker observation.
- Cumulative quantities cannot decrease, overfill the requested original whole-share quantity or contradict an apparent `FILLED`/partially filled terminal state; known broker order IDs cannot silently change during one V1 intent's record sequence.
- Each report must have an original origin claim; a claimed broker receipt and a separate fee receipt have different evidentiary purposes and **neither source string is authenticated here**.
- The current Robinhood source can emit `REJECTED` alongside `mcp_submission_timeout:` or `mcp_error:` after ambiguous sending. A declared `cancellation_failed:` with CANCELED is also not proof of cancel success. These are expressly flagged `UNCONFIRMED_AS_TERMINAL_V1`, and the overall conservative broker-knowledge outcome is UNKNOWN; they must not be accepted as trusted broker rejection/cancel or safe permission to retry.
- An actual local not-sent rejection is distinct from broker rejection. If the claim is `LOCAL_BEFORE_SEND`, the V1 report must be REJECTED, zero cumulative quantity and have no broker order ID. Even then, the review returns `LOCAL_NO_SEND_CLAIM`, not an independently signed proof that no transport was attempted.
- V1 `fee_amount=0` defaults do not distinguish a known measured zero from missing fee evidence. `claimed_original_fee_complete` is false unless a separate external fee-receipt string is provided for every distinct V1 report. A string can make this **claim** true, but never authenticate original fee/fill/settlement, allocate cash or qualify RESULT.

The result names `structurally_reviewable`, `claimed_last_v1_status`, `conservative_broker_knowledge`, `largest_claimed_cumulative_fill`, `claimed_original_fee_complete`, `distinct_report_hashes` and explanatory `flagged_reasons`. An inconsistent or incomplete original record yields explicit refusal, withholding positive fill and fee metadata. If all supplied data are internally coherent, `V1_ORIGIN_CLAIM_ONLY` still means a data-format/source-claim review, not a verified broker outcome. Even structurally sound `FILLED` cannot prove a live fill or account settlement without actual original verified broker, account and posting receipts.

The three properties `authenticates_original_broker_or_account`, `authorizes_submission_cancellation_or_retry` and `proves_execution_or_settlement_complete` are **always false**. That is deliberate. This script cannot implement #411's account-wide hold or quiescence, guarantee no hidden transport retry, authenticate a source, or create a real V2 observation. Do not use it in execution routing or scientific promotion. Do not relabel old V1 history as an accepted V2 fact.

The October 23 repair ensures a declared original-availability clock passes the existing exact datetime/UTC check before any ordering comparison. Previously, a naive datetime, string or integer was flagged invalid but still compared with the aware cutoff, raising TypeError instead of returning the promised conservative refusal. These malformed values and a non-UTC aware clock now return explicit invalid-clock reasons and UNKNOWN without positive fill/fee evidence. Existing valid UTC controls and all three false authority properties remain unchanged.

## Local verification and pending independent acceptance

The October 23 continuation used unchanged pinned CPython 3.14.6 and `uv.lock`. Before the clock guard, the four new malformed-clock regressions produced **3 failed / 1 passed**; after the correction, all **23** audit tests passed. The combined audit and M1e compatibility run passed **78 tests / 1 warning** in 3.96 seconds. The warning comes from the existing deliberately forged Pydantic status case. Targeted Ruff lint/format, strict `mypy src tests` (473 source files), sdist/wheel build and Git whitespace checks passed. Import cleanup and pinned formatting also repair the earlier lint gate without changing the V1 wire or persisted hashes.

These are local focused checks. Full exact-head hosted CI and independent source/architecture acceptance remain pending; successful checks cannot confer operational approval.

AntiGravity should check the exact published PR HEAD, only these three additive paths and the accepted V1 source, then execute:

```bash
uv run pytest tests/unit/test_execution_v1_evidence_audit.py -q
uv run ruff check src/drift/execution/v1_evidence_audit.py tests/unit/test_execution_v1_evidence_audit.py
uv run ruff format --check src/drift/execution/v1_evidence_audit.py tests/unit/test_execution_v1_evidence_audit.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

The tests use real `build_order_intent`, `build_execution_report` and `SessionKeyV1` models, with no actual broker:

1. Authenticated-looking but untrusted V1 ACK is `V1_ORIGIN_CLAIM_ONLY`, not broker proof.
2. Default zero V1 fee is not a verified zero; fee string claim remains unverified even when present.
3. `mcp_submission_timeout:` and `mcp_error:` REJECTED paths are conservatively UNKNOWN and flagged as false terminal.
4. `cancellation_failed:` CANCELED path cannot be a settlement/cancellation authority.
5. Local pre-send refusal and claimed broker receipt carry different states and cannot be conflated.
6. Actual V1 partially filled then fully filled quantity sequence may be structurally coherent; no settlement guarantee.
7. Exact duplicate report ID/hash counted once; conflicting same-ID status/content refuses.
8. Wrong intent, altered broker order ID, quantity regression, overfill, inconsistent FILLED quantity/partial remainder refuse.
9. Missing original claim, after-cutoff original observation, out-of-order report time, malformed/naive UTC and invalid Pydantic status refuse.
10. Failing these probes must **never** lead to an automatic submit retry, releasing an account hold, resetting unverified fees to zero or placing any order.

Additional actual-source tests should later exercise an accepted adapter's original transport receipt and a trusted broker response, effective account-wide holds across workers/restarts, true durable before-I/O state, quiescence/egress fencing, and the accepted single-store monetary settlement. Those are the actual missing S4 runtime implementation and **remain separately gated** by Matthew's A1 architecture and #411 independent material ruling.

## Disposition

New source code has been written for source-backed diagnostic review, but the original severe broker/transport misclassification in `RobinhoodAgenticAdapter` still exists in the live adapter until Matthew's authorized runtime migration. This candidate cannot be called a fix, a new operational contract, paper/live authorization, or completion of #411. Matthew retains original owner authority and PR #413 unchanged. AntiGravity tests the exact head, Matthew confirms the final A1 design/issuer/custodian and consumer migration, and only then may actual runtime/test paths be separately claimed. No self-review or source-issuer authority is claimed.
