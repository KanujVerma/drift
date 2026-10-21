# Intraday execution trace preflight (Issue #525)

**Status: separate candidate implementation, tests deliberately not run, NOT execution authorization.**
Matthew remains accountable for [#379](https://github.com/KanujVerma/drift/issues/379). His E3 [draft PR #412](https://github.com/KanujVerma/drift/pull/412) is a proposed **documentation** contract and remains unmerged and unchanged; its proposed `drift-exec-intraday-v1` identifier is **not accepted as a runtime wire version** by this code.

## Ownership, exact added paths and protected boundaries

User-directed isolated assist pair: #524 (source options) and #525 (execution timing). GitHub publisher: Krish-Verma / GPT-6, separate from Matthew's active producer reservations. Exactly these new files are owned by this issue:

- `scripts/execution_trace_preflight.py`
- `tests/unit/test_execution_trace_preflight.py`
- `docs/architecture/adaptive-experiments/verification/execution-trace-preflight.md`

No modification to existing source adapters, venue/calendar, M2 account ledger, evaluator/protocol, shadow broker, reconciliation/UNKNOWN stores, risk/mandate, schema/migrations, persisted replay results, interpreter or locked dependencies. Read [AGENTS.md](../../../../AGENTS.md), [D01-D17](../decisions.md), Matthew's E3/A01-A12 draft, and the relevant [#365](https://github.com/KanujVerma/drift/issues/365) real venue, [#394](https://github.com/KanujVerma/drift/issues/394) SRC, [#376](https://github.com/KanujVerma/drift/issues/376) RESULT, [#380](https://github.com/KanujVerma/drift/issues/380) MANDATE and [#411](https://github.com/KanujVerma/drift/issues/411) UNKNOWN-state decisions. Their acceptance and owned implementations remain separate and gated.

## Pure code contract

`preflight_execution_trace(payload: object) -> ExecutionTracePreflight` accepts only an in-memory, JSON-shaped, **untrusted** candidate trace and returns stable diagnostic reason strings. It does not read a file, schedule work, connect to a provider, call a broker, modify a ledger, submit/cancel/resend an order, model fill probability or authenticate any claimed receipt.

The provisional payload has exact top-level fields `profile`, `request`, `evidence`, `timeline`, `tie_proofs`, `quote`, `attempts`, `reports` and `state`. The request names run/arm/account, original client token and SHA-256 request preimage identity, side, positive whole-share quantity, session, order type and optional exact decimal limit. Evidence names retained input, cutoff, mandate/risk, true venue, order and session capability, policy revision and halt-at-arrival state. All those fields are unverified **references**, not trusted grants.

The proposed timeline includes distinct source receipt, normalization availability, analysis completion, decision, approval and risk checks, submission and modeled arrival. Arrival cannot precede known checks. The quote must have an observed event and received clock no later than the decision, be no older than the **caller supplied synthetic freshness bound** at arrival, and carry a quoted evidence reference. This bound is not an accepted production threshold. Unknown quote age, out-of-order timestamp, future receipt and an impossible timezone refuse. Equality at a coarse clock resolution requires an explicit `tie_proofs` reference for the particular causal edge; the helper **cannot verify** the external processing/order proof. An ID sort order is not accepted as a substitute.

All time fields are strict UTC `...Z` strings; quantities are Python integers (not booleans); prices, fees and synthetic quote age are finite nonnegative decimal **strings** with bounded scale, never binary floats, negative values or NaN. BUY fills cannot exceed a declared buy limit; SELL fills cannot be below the sell limit. PRE/POST requests require a LIMIT in this conservative fixture, but even that does not authenticate extended-hours order capability, real holidays, order sizes, quote liquidity or halts. A bar-only observation cannot prove a reported fill.

The evidence list stores one original client token and unchanged request hash across attempts. Any second `dispatched=True` record is refused; a fresh ID cannot bypass an UNKNOWN hold. `reports` preserve the latest monotonic **cumulative** known quantity, with exact identical report-ID redelivery ignored for economic count and conflicting redelivery refused. A report fee may be `known` with an exact amount including verified-looking zero as a mere *claim*, or `unknown` with `fee=None`. The checker cannot interpret a missing fee as zero. Re-used effect references for positive quantity increments refuse. The returned `reported_cumulative_qty` is a diagnostic count of the submitted evidence, **not** actual exposure, a reconciled filled quantity or authority to post accounting.

A syntactically coherent `UNKNOWN` dispatch is allowed with `claimed_accounting_complete=False` even when its reports show no known shares: zero *reported* shares is not proven zero actual exposure. A pending/open/partial/UNKNOWN lifecycle, missing trusted terminal/ledger/valuation reference, unknown fees and conflicting state cannot assert structural accounting completeness. Refusal, expiry/cancellation and lack of an order are not transmuted into actual broker acknowledgements. Even the structurally possible complete fixture needs real independent platform verification and scientific/result acceptance.

The return is `ExecutionTracePreflight(review_ready, reported_cumulative_qty, claimed_accounting_structurally_possible, reasons)`. Invalid records return `reported_cumulative_qty=None`, not fabricated zero. `authorizes_order_placement` and `proves_fill_or_settlement` **always return False**. Any `review_ready=True` is only a self-consistency result over untrusted mock values. The script cannot be used as a runtime permit, M2 ledger substitute, fee/cost proof, E1/E6B RESULT binding or trading permission.

## Acceptance map to E3's synthetic A01-A12

| Draft E3 case | Offline check / known limit |
| --- | --- |
| A01 10:32 causal event | Distinct source-to-arrival sequencing with explicit receipt/decision/approval/risk |
| A02 minute bar | `BAR_ONLY` cannot accompany a claimed evidenced fill |
| A03 correction | Cutoff requires already normalized input; original/correction retention must be checked in #524 / #394 |
| A04 partial after-hours limit | LIMIT-only proposed extended session; cumulative 20/100 remains PARTIAL, never all filled |
| A05 halt | A claimed fill while halt-at-arrival is HALTED or UNKNOWN refuses |
| A06 stale quote | Exact decimal freshness comparison at modeled arrival, no implied validity after it |
| A07 UNKNOWN timeout | Cannot claim terminal/complete or create a second/fresh placement |
| A08 equal clock | Exact per-edge tie reference required; its authenticity is outside the helper |
| A09 fallback | No fallback or next-session order is executed/authorized; absence of trusted evidence stays gated |
| A10 duplicate fill | Same report-ID replay ignored, conflicting replay refused, latest cumulative count not summed |
| A11 mixed venues | Genuine venue reference required; real venue/multi-clock admission belongs to #365 |
| A12 old protocol / cross-arm | No old protocol edits or account bindings; exact original account/arm verification belongs to M2/#508 |

The table does not claim full conformance to E3. Specifically absent: trusted venue/calendar/halt evidence, quote depth and queue allocation, permission expiry, source/correction authentication, historical replay, actual book settlement, durable concurrency recovery, authoritative account assignment, experimental policy acceptance, scientific scoring and old V1/V2 compatibility migration. Those need **separate** owner-scoped implementations and independent tests; do not fill them from guessed defaults.

## Deferred AntiGravity verification

Tests are **written but intentionally unrun** at user direction. Inspect exact head, provenance, isolated changed files and candidate/producer boundaries before testing:

```bash
uv run pytest tests/unit/test_execution_trace_preflight.py -q
uv run ruff check scripts/execution_trace_preflight.py tests/unit/test_execution_trace_preflight.py
uv run ruff format --check scripts/execution_trace_preflight.py tests/unit/test_execution_trace_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

AntiGravity must also run the canonical workflows/whitespace/build guards in [agent workflow](../../agent-workflow.md), verify clean pinned interpreter and dependencies, check no unrelated paths changed and independently construct at least these negative oracles: decision/submission before receipt or approval, equality without tie proof, late correction, quote received after decision, stale/unknown quote, bar-only fills, unsupported after-hours type, halt, partial/overfill, descending cumulative counts, duplicate reports and economic effect reuse, LIMIT violation, unknown fee, UNKNOWN resend after restart, changed token/hash, bogus terminal receipt and cross-arm account mismatch. Some cases require future producer adapters and cannot be certified solely by this helper.

**No manual or independent checks were run in this authoring session.** Hosted GitHub Actions may run automatically after a PR is opened, but their outcome is separate from the future independently accepted AntiGravity packet. No order, fill, book, source, rights, schema, scientific result or production readiness is established. Keep this PR draft until Matthew and relevant consumer/independent reviewers accept the exact candidate and downstream real contract separately.
