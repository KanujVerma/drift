# Decision-close transition cost contract, draft v1

Status: design proposal for [#613](https://github.com/KanujVerma/drift/issues/613).
Accountable producer: Matthew. This document specifies a read-only projection;
the estimator and proposed types below are not implemented or activated by it.
It does not establish source rights, original-issuer authority, scientific
acceptance, a new fee policy, or execution permission.

Source baseline: `60d572a339835a8ec8d9bb0ab8c7fd4383daeb33`.
[The G3 protocol](stage1-g3-protocol-v1.md) remains authoritative for the R
objective. [#508](https://github.com/KanujVerma/drift/issues/508) supplies the
original account/RESULT association; [#379](https://github.com/KanujVerma/drift/issues/379)
retains execution-policy ownership. A later implementation must map this draft
to accepted producer types and claim its own exact source/test paths.

## 1. Purpose and existing gap

For each candidate family, estimate the complete cost of moving the active
original account to that family's actual whole-share target using only evidence
eligible at the decision close. Divide that estimate by the same account's
causal decision-close NAV to obtain `C_s`.

A scheduled internal rebalance within the incumbent family can cost money.
A switch need not have a fixed cost. A zero is an evidenced result, never the
default for missing information.

The existing [execution engine](../../../src/drift/evaluator/execution.py)
prices fills from listing-bound unadjusted opens. Its fee/funding rules are useful,
but calling that engine with a close relabelled as an open would misstate origin.
The [decision context builder](../../../src/drift/evaluator/engine.py) exposes
account-state NAV beside cutoff-selected views; their co-location alone does not
prove that both describe one causal projection.

The proposed estimator must not emit an order, fill, ledger event, account
allocation, grant, accepted RESULT, or historical-calibration artifact.

## 2. Proposed typed boundary

The identifiers in this section are design identifiers, not existing Python
classes, schema versions, exported symbols, or accepted authority profiles.

```text
estimate_decision_close_transition_v1(
    request: DecisionCloseEstimateRequestV1,
    *,
    original_platform_reader: AcceptedOriginalPlatformReader,
    cutoff_evidence_reader: AcceptedCutoffEvidenceReader,
) -> DecisionCloseEstimateOutcomeV1
```

The host binds both read-only readers to the accepted original issuer/profile.
The request cannot supply a verifier, nominate its own trusted root, or turn
caller-computed hashes into authentication.

Common field types reuse the repository meanings of `SHA256Hash`, `NonBlankStr`,
`UTCDateTime`, `SessionKeyV1`, finite `Decimal`, and strict nonnegative integer
whole-share quantity. A reference below means an immutable producer-issued
record reference plus its content hash, not an arbitrary matching string.
The concrete reference/schema mapping must be fixed before runtime publication.

| Request group | Required fields and verification |
| --- | --- |
| Contract | Version/profile reference and numeric-policy reference; reject unsupported versions rather than infer defaults. |
| Experiment | Complete campaign/spec/manifest, run, arm, checkpoint and trial references. Verify the complete tuple against original records under #508. |
| Account | Original account/allocation reference, ledger-prefix checkpoint and state reference, all belonging to that experiment tuple. |
| Decision | Session key, decision cutoff UTC time, and the original decision-query/availability witness. |
| Target | Installed family, implementation/parameter revision, target-decision reference, complete unique security/listing identities and strict whole-share quantities. Every current holding must appear, including explicit zero for liquidation. |
| Valuation | Close-price evidence for every holding and every nonzero delta, including listing, venue, currency, session, unadjusted price, source/revision, observation time and availability witness. |
| Policies | Frozen cost-model reference with explicit fee units; current mandate/risk and funding-policy references; target-generation and numeric-policy versions. |

Resolve, rather than trust a duplicate caller copy of, the following state:
cash, holdings, eligible pending corporate-action cash claims, pending executions,
resolutions and supersession/correction lineage. A consistent causal account
prefix is required. Unresolved execution that makes holdings or spendable cash
ambiguous yields UNAVAILABLE; never assume a pending order did or did not fill.

A target is already generated and admitted by its candidate producer. This
estimator does not select a family, round weights into a new target, repair
duplicates, trim an unfundable order, introduce a risk override, or invent an
FX rate. An unchanged holding still needs a valid mark to establish NAV.

## 3. Causal projection and denominator

All candidates evaluated at one decision must use the same verified account
prefix, cutoff, valuation policy and causal NAV decomposition. Candidate target
and target-specific deltas/costs may differ. Reject inconsistent denominator
references rather than allowing each candidate to supply a convenient NAV.

1. Authenticate the experiment/account association and original state prefix.
2. Reconstruct only state, claims, corrections and evidence available under the
   accepted policy at the decision cutoff.
3. Verify each held-security mark and each mark needed for a nonzero delta.
4. Revalue the read-only projection with the existing portfolio money and
   pending-claim rules. Retain the original ledger and later accounting view.
5. Require finite, representable, strictly positive NAV before dividing.

Use the accepted session and availability policy. Do not invent an age limit.
A close with the correct number but wrong listing, source or availability witness
is not interchangeable with the required original close. Late evidence and later
corrections cannot overwrite the earlier projection.

For eligible account cash `cash`, holdings `h_i`, causal close marks `p_i`,
and eligible unpaid corporate-action cash claims `claims`:

```text
decision_close_NAV = cash + sum(h_i * p_i) + claims
```

Claims contribute according to the existing valuation rules. An unpaid claim
does not become spendable cash merely because it contributes to NAV.

## 4. Cost and funding arithmetic

For target quantity `t_i`, current quantity `h_i`, signed delta
`d_i = t_i - h_i`, and nonzero absolute quantity `q_i = abs(d_i)`:

```text
notional_i = q_i * p_i
fee_i = q_i * commission_per_share
      + fixed_fee_per_order
      + notional_i * notional_fee_bps / 10000
adverse_shortfall_i = notional_i * slippage_bps / 10000
estimated_transition_cost = sum(fee_i + adverse_shortfall_i)
C_s = estimated_transition_cost / decision_close_NAV

buy_outflow_i = notional_i + adverse_shortfall_i + fee_i
sell_inflow_i = notional_i - adverse_shortfall_i - fee_i
projected_spendable_cash =
    eligible_cash + sum(sell_inflows) - sum(buy_outflows)
```

The notional fee uses the unslipped close as its base, mirroring the current
engine's unslipped execution-price convention. The estimate does not compound
slippage into that fee. A verified zero delta creates no order and pays no fixed
order fee. Buys and sells remain distinct orders; equal opposing notionals do
not cancel their fees or shortfall.

Apply the same accepted funding and mandate constraints as the authoritative
account. A finite negative projected spendable balance is unavailable, not a
silently scaled target. If pending execution prevents determining a trustworthy
balance or delta, return unavailable even when a guessed scenario would fund it.

Use the [portfolio numeric policy](../../../src/drift/domain/evaluator_portfolio.py):
34 significant digits, ROUND_HALF_EVEN, an isolated context, and existing
canonical money validation/spelling. Reject nonfinite or unrepresentable values.
Do not add float tolerances, cents quantization, changed coefficients, or ambient
Decimal-context dependence. Exact rational arithmetic is an independent test
oracle, not a replacement production numeric policy.

Trading fees and slippage already present in reference net returns remain there.
Only the prospective candidate transition enters this `C_s`. Research/operating
invoices are excluded from trading NAV and this estimate.

## 5. Proposed outcome contract

`DecisionCloseEstimateOutcomeV1` is a proposed discriminated union:

| Outcome | Required content | Consumer behavior |
| --- | --- | --- |
| AVAILABLE | Verified request/input references, profile and source grade; causal NAV and cash/holdings/claims decomposition; canonically ordered security/listing deltas; per-order fee/shortfall; total cost, cost/NAV and projected spendable cash; projection content hash. | Use only for the bound candidate, cutoff, account and admitted evidence lane. A projection hash proves integrity, not origin or acceptance. |
| UNAVAILABLE | Stable reason category, failed reference(s), and optional diagnostic details. | Do not rank using zero or a normal estimate payload. Propagate missingness to the caller's accepted unavailable/hold behavior. |

Proposed reason categories are unsupported profile/policy, unresolved original
association, inconsistent account prefix, unavailable claim/execution state,
missing/late/conflicting mark, wrong listing/currency/session, invalid or
incomplete target, nonpositive/invalid NAV, insufficient funding, mandate
ineligibility, and numeric failure. Names and encoded values must be fixed with
the implementation schema; these are not claims that repository error codes exist.

A diagnostic partial calculation cannot populate the usable AVAILABLE fields.
No diagnostic or source-grade label upgrades exploratory evidence to promotion
grade. Every AVAILABLE zero must pass the same identity, state, target and
NAV-evidence checks required to prove that zero.

## 6. Hand-computable fixture oracle

These supplied synthetic coefficients are test inputs, not a fee-policy choice:
0.01 per share, 1 per order, 10 bps notional fee and 5 bps adverse slippage.
Use supplied NAV 1000 for the cost-ratio examples.

| Fixture | Fees | Shortfall | Cost | Funding/result |
| --- | ---: | ---: | ---: | --- |
| Buy five shares at close 100 | 1.55 | 0.25 | 1.80 | Outflow 501.80; C_s 0.0018 |
| Sell five shares at close 100 | 1.55 | 0.25 | 1.80 | Inflow 498.20; C_s 0.0018 |
| Fully verified zero delta | 0 | 0 | 0 | No fixed order fee |
| Incumbent-family rebalance with a five-share delta | 1.55 | 0.25 | 1.80 | Staying is not automatically free |
| Buy five of A and sell five of B, both priced 100 | 3.10 | 0.50 | 3.60 | Net cash decrease 3.60; C_s 0.0036 |
| Separate actual-open comparison at 103 | 1.565 | 0.2575 | 1.8225 | Later arithmetic does not revise the close estimate of 1.80 |

NAV example: 9000 cash + ten shares at 100 + an eligible unpaid claim of 20
equals 10020. A later corrected mark of 99.50 gives 10015 in the later view;
it cannot rewrite the earlier causal projection.

Funding negative: 480 spendable cash cannot fund a 501.80 buy outflow merely
because an unpaid 100 claim is included in NAV.

The arithmetic oracle must compare the pinned-context result with independent
integer/rational arithmetic, including hostile ambient precision/trap settings.
An arithmetic pass establishes neither input provenance nor runtime conformance.

## 7. Required conformance matrix

Each refusal needs a genuine eligible positive control and a single changed
condition. Run these through the actual producer implementation, not a replacement
calculator or a caller-created verifier that approves its own evidence.

| Case | Positive control | Perturbation and required result |
| --- | --- | --- |
| C01 | Bound original account and complete target | Wrong account, trial, manifest or allocation; unavailable despite matching numbers. |
| C02 | Complete original close witnesses | Missing close, later availability or conflicting revision; unavailable. |
| C03 | Correct listing/venue/currency/session | Equal numeric price with a wrong identity; unavailable. |
| C04 | Explicit whole-share quantities for all holdings | Duplicate identity, omitted holding, negative/fractional quantity or fabricated target revision; unavailable. |
| C05 | Resolved causal account prefix | UNKNOWN/pending fill prevents authoritative deltas or funding; unavailable, no hypothetical netting. |
| C06 | Cash and eligible unpaid claims distinguished | Unfundable cash balance despite sufficient NAV; unavailable. |
| C07 | Valid positive representable NAV | Zero, negative, nonfinite or unrepresentable NAV/cost input; unavailable. |
| C08 | Buy, sell and complete no-trade cases | Missing evidence in a zero-delta request; unavailable, never default zero. |
| C09 | Same-family internal rebalance | Nonzero target delta still incurs complete fees and shortfall. |
| C10 | Same close projection and candidate | Change only next-open price; earlier estimate and denominator remain identical. |
| C11 | Original available close revision | Add only a later correction; earlier projection is invariant and later view retains its own lineage. |
| C12 | Explicit frozen cost and risk/funding policies | Unknown policy/version or mandate-infeasible target; unavailable, no defaults or trimming. |
| C13 | Fixed complete inputs | Change ambient Decimal precision/traps; result, canonical ordering and hash remain invariant. |
| C14 | Original reader and bound accepted profile | Caller replaces authority with self-hashed/copied receipts; unavailable. |
| C15 | Read-only projection and every refusal above | Compare database events, files, stores and account state before/after; exactly zero writes, not merely zero dispatched orders. |
| C16 | Shared decision across several candidates | Conflicting account/NAV/cutoff binding; reject inconsistent comparison inputs. |

## 8. Implementation boundary and remaining decisions

This draft resolves the proposed causal arithmetic and explicit missingness
semantics for implementation planning. It does not claim an implemented reader
or an accepted issuer/profile. The implementation claim must name the exact
account-state/quote/target reference mappings, error encodings, read-only reader
dependencies, canonical preimage/schema and scoped source/test paths.

Preserve existing source/issuer, execution, mandate and scientific acceptance
boundaries. Do not implement a second account engine or use this projection to
commit a hypothetical book. [#606](https://github.com/KanujVerma/drift/issues/606)
still needs the qualified original nine-account producer, and
[#596](https://github.com/KanujVerma/drift/issues/596) containment is not supplied
historical data. Tests and release evidence belong on the implementing issue/PR.
