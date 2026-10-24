# Offline RESULT economics preflight for Matthew #376 (Issue #532)

**State: locally verified bounded candidate, pending inventory integration and independent acceptance. This is not an authenticated M2 RESULT adapter.**

## Existing producer contracts and ownership

This is the first of two user-requested inactive Matthew-area coding slices. Matthew remains producer of [#376](https://github.com/KanujVerma/drift/issues/376) and the unmerged [platform SRC/RESULT draft PR #407](https://github.com/KanujVerma/drift/pull/407). The draft [platform.md at its original branch](https://github.com/KanujVerma/drift/blob/matthew/376-m-contract/docs/architecture/adaptive-experiments/contracts/platform.md) is *proposal content*, not the accepted runtime schema. [P0 #508](https://github.com/KanujVerma/drift/issues/508) currently owns the missing real E1 original-account provisioner, issuer and authoritative RESULT-to-trial association. That user-specific, producer-owned decision remains active and **is not taken over or solved here**. The companion new assist is #533, for #411 UNKNOWN attempt safety.

Authenticated implementation publisher: `Krish-Verma` / GPT-6 on an isolated code-assist issue. Accountable original source/accounting producer: Matthew. Publication does **not** reassign Matthew's write reservations or count as a review approval. Read [AGENTS.md](../../../../AGENTS.md), the [agent workflow](../../agent-workflow.md), [D01-D17](../decisions.md), Matthew #376 / #508, and the implemented [M2 result model](../../../../src/drift/domain/evaluator_results.py) before independent acceptance.

## Exact new write-set

- `scripts/result_economics_preflight.py`: exact arithmetic with Decimal outputs, receipt chronology and completeness checks over an untrusted synthetic fixture
- `tests/unit/test_result_economics_preflight.py`: positive, adversarial, precision, cost-replay and cutoff cases
- `docs/architecture/adaptive-experiments/verification/result-economics-preflight.md`: this test and migration/ownership handoff

All three are additive files. No modifications to Matthew #407, the actual M2 evaluator/ledger, SRC/RESULT schema, E1 manifest, #508 allocator, source grades, retained replay or artifacts, other PRs, interpreter/lockfile, accounts, broker or risk state. The helper does not connect to a repository private dataset, call an evaluator or open an external API.

## Synthetic-only input and result contract

`preflight_result_economics(payload: object) -> ResultEconomicsPreflight` accepts only bounded plain JSON-shaped Python dictionaries/lists/scalars (no float, user-defined equality or unbounded object graphs), not actual trusted Pydantic objects. Profile: `synthetic-result-economics-review-v1`. The exact top-level fields are `profile`, `as_of_utc`, `identity`, `book`, `cost_scope`, `operating_receipts`, and `prior_result_hashes`. This is a **local fixture format only**, not a proposed platform wire, hash preimage, source-grade elevation or issuer verification protocol.

`identity` is a claimed campaign/run/arm/checkpoint/trial/account plus original E1 binding hash, RESULT/trace/bundle/book hashes, source lane, result classification and earliest result availability. The synthetic `allocation_receipt_ref` may be missing. Even a present receipt string or matching digest does *not* verify the actual account/book provenance. Identical deterministic `result_hash` in `prior_result_hashes` refuses counting the same replay as another independent observation. Only `SYNTHETIC` is accepted here; historical or promotion-grade datasets need separate actual proof.

`book` contains claimed original starting NAV, final cash, marked holdings, marked pending claims, marked total NAV and separately disclosed fees **already embedded in ending NAV**, with declared source/book reconciliation and separate flags for marks, trading costs, realized PnL and entire requested interval. Money uses exact nonnegative decimal strings, positive initial NAV, USD, no external funding flows and a single explicit currency; a second FX basis is not inferred. The existing parser accepts at most 42 characters and 12 fractional digits, without exponent notation. Those input limits are unchanged. The checker reconciles:

```text
end_marked_nav = end_cash + end_holdings_value + end_pending_claims_value
net_trading_gain = end_marked_nav - begin_nav       (no external flows)
net_trading_return = net_trading_gain / begin_nav
economic_gain = net_trading_gain - eligible_operating_costs
```

NAV reconciliation, charge aggregation, gain and economic subtraction use exact rational arithmetic internally. Finite results are constructed directly as Decimal sign/coefficient/exponent tuples, with no ambient precision or rounding. A finite exact return may require more digits than an input amount; it remains exact rather than being truncated to an arbitrary display width. A nonterminating return such as positive or negative `1/3` cannot be represented by the existing finite Decimal output. The helper explicitly refuses that unsupported arithmetic case with `book.trading_return_nonterminating_decimal`, sets `structurally_reviewable=False` and suppresses numeric metrics. It does not round the return, change the original supplied book, or invent an economic rounding policy. All pre-existing finite B/R examples retain their exact values.

The trading fees in `trading_fees_already_posted_usd` have **already reduced posted book cash/NAV**; they are never deducted twice. Slippage embedded in execution prices also is not added as another cash fee. The script does not claim to independently prove the posted fees are true, derive gross pre-slippage PnL or authenticate the book.

`operating_receipts` use an exact independent logical `charge_id`, immutable `receipt_id`, arm, `RESEARCH_OPERATING_NOT_BOOKED` category, `ACTUAL` / `VERIFIED_ZERO` / `UNKNOWN` / `ESTIMATE` status, decimal amount or explicit missing value, first availability and an optional exact superseded receipt. The checker does not treat any of these self-asserted labels as actual invoices. Identical receipt replay is idempotent; conflicting same-ID data, unknown disguised as zero, swapped arm or accidental trading-fee category refuse. A later correction supersedes the earlier charge only after it becomes available: it does not rewrite an earlier as-of economic comparison or double bill.

`cost_scope` states the full **declared** expected logical charge IDs, scope-closure evidence/availability and named attribution policy. Missing expected charges, an incomplete/unavailable scope or estimates/unknown amounts leave `economic_gain_usd=None`. Even with this closure label, full external bill/usage coverage is unverified until accepted custody and scientific attribution. A future invoice is listed as an excluded late receipt rather than leaked into earlier economic metrics.

**Independent arithmetic example**, *not proof of M2 fills or G3 success*: initial B/R cash/NAV $10,000 each, simulated B end NAV $10,120, R $10,060, net trading return 1.2% versus 0.6%. If separately accepted operating expenses were B $25 and R $5, their illustrative economic gains are $95 and $55, difference $40. With an unknown B invoice, B trading gain remains $120 but B economic gain is `None`. A separate fully realized example with posted fee $5, starting NAV $10,000, ending $10,095 and operating charge $7 yields net trading gain $95 and economic gain $88, not $83.

## Return value and fail-closed interpretation

`ResultEconomicsPreflight` contains `structurally_reviewable`, `marked_nav_reconciled`, `marked_nav_usd`, `trading_net_gain_usd`, `trading_return_fraction`, `economic_gain_usd`, `cost_completeness`, `excluded_late_receipt_ids`, and stable `reasons`.

- Malformed/mismatched book arithmetic, unsupported floats, duplicate result replay and inconsistent cost receipts render the fixture not structurally reviewable and suppress output metrics. A nonterminating derived return also refuses explicitly because this helper has no accepted rounding policy.
- A structurally consistent, as-of-available marked book may preserve its candidate `marked_nav_usd` even when pending/UNKNOWN orders or incomplete realized PnL prevent a full-interval trading result. This is a labelled mock mark, **not** proof of real spendable cash or terminal exposure.
- REJECTED / INDETERMINATE evaluation, absent full interval, marks/trading costs/realized PnL incomplete, unresolved execution, or result not yet available at cutoff prevent full-interval trading/economic metrics. The result's `reasons` explain missing qualification without silently changing the original evaluator classification.
- `proves_account_provisioning_or_result_binding=False` and `qualifies_scientific_result_or_execution=False` **always**. An apparent positive numeric result is not an accepted scientific trial, live account balance, broker proof, source grade or trading authorization.

`structurally_reviewable=True` means only that the data the caller supplied is internally coherent, not that any hash, evidence reference, allocation, price, finality or original account is independently verified. Actual **authoritative** book provisioning, consumed operation/trace identity, cost categorization and canonical RESULT hash must come from Matthew's accepted M2/#508 producer, not from this fixture.

## Local verification and independent review queue

The October 23 continuation uses pinned CPython 3.14.6 and unchanged `uv.lock`. Tests added before the arithmetic repair produced **23 failed, 46 passed**, including the pre-existing float-reason mismatch and the reviewer's false NAV reconciliation. After the repair, all **69 focused tests passed**. Whole-repository Ruff lint and formatting (564 files), strict `mypy src tests` (472 files), package sdist/wheel build and Git whitespace checks passed. The float test now asserts the earlier `payload.not_plain_json` refusal; input validation remains unchanged.

The protected M1e inventory test still fails solely because `scripts/result_economics_preflight.py` is absent from its explicit source inventory. This three-file issue does not authorize editing that guard or relocating the source. Exact-path admission, source capability review and its non-vacuous negative controls require the separately coordinated guard writer and producer acceptance. No skip, pin change or capability waiver is introduced. Full-suite/hosted success is not claimed while that integration blocker remains.

On the exact published PR head, independently read the three scoped files, this contract, #376/#407, #508 and real M2 result/portfolio types. Then run:

```bash
uv run python -m pytest tests/unit/test_result_economics_preflight.py -q
uv run ruff check scripts/result_economics_preflight.py tests/unit/test_result_economics_preflight.py
uv run ruff format --check scripts/result_economics_preflight.py tests/unit/test_result_economics_preflight.py
uv run mypy src tests
uv run python -m pytest
uv build
git diff --check
```

Use [canonical verification](../../agent-workflow.md) with the pinned interpreter and lockfile, check only the three new paths changed, and read any GitHub Actions result on **this** head rather than old test reports. Automated CI does not replace independent producer/consumer review. The local focused results above do not qualify the full source composition or authorize the protected inventory change.

The precision regressions cover false and correct large-NAV reconciliation, fractional pending claims at the admitted scale, maximum-width input amounts, large operating-cost sums, an exact terminating `1/(2**139)` return, signed nonterminating refusal and positive/zero/losing finite returns at precisions 6, 28, 60 and 80.

The independent review must rederive B/R arithmetic and no-double-fee examples, inspect negative/unknown research costs, late invoices and their supersession, exact receipt duplicate and conflict, cross-arm attribution, flow assumptions, unrealized pending claim visibility, unvalued holdings, gaps in realized PnL, earlier decision cutoff, same deterministic RESULT replay and hostile custom equality. Add adversarial property cases and tests against actual M2 producer evidence **only after a new accepted contract and exact integration writer claim**; do not modify another owner's files under this PR.

## Remaining blocks

Matthew: accept original E1 book provisioning and result/account/trace issuer/verifier in [#508](https://github.com/KanujVerma/drift/issues/508), reconcile broader SRC/RESULT [#376](https://github.com/KanujVerma/drift/issues/376) and all cost completeness/settlement requirements. Krish: review research candidate/feedback consumption. Kanuj/effective scientific owner: review attribution, eligibility, result-account identity and comparable arms. AntiGravity: run and inspect exact PR head. None of these approvals is claimed here. Keep draft and do not close the original issues, merge or trigger any paid, broker, source or production operation.
