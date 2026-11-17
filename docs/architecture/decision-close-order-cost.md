# Numeric decision-close order costs

Issue [#633](https://github.com/KanujVerma/drift/issues/633) implements the
order-level arithmetic needed by [#613](https://github.com/KanujVerma/drift/issues/613).
It is a read-only numerical component. It is not the original-evidence producer,
an AVAILABLE estimate, a source qualification receipt, or an execution request.

## API and units

`drift.evaluator.execution.estimate_decision_close_order_cost` accepts a signed
integer whole-share `delta`, a positive finite `Decimal` `decision_close`, and an
explicit validated `EvaluationCostModelV1`. Positive deltas buy; negative deltas
sell. This sign convention does not establish holdings or permission to sell.

The frozen `DecisionCloseOrderCost` result contains:

| Field | Meaning |
| --- | --- |
| delta | Supplied signed whole-share change |
| reference_notional | Absolute quantity multiplied by the supplied close |
| fees | Per-share commission, one fixed order fee, and notional fee on the unslipped close |
| adverse_shortfall | Reference notional multiplied by adverse slippage bps / 10000 |
| estimated_cost | Fees plus adverse shortfall, in account currency units |
| cash_delta | Negative buy outflow or net sell inflow, including fees and shortfall |

The result is an internal immutable value, not a versioned persisted domain
record. It has no source grade, account authority, accepted flag or ledger event.
The existing fill builder and this estimator share one private fee expression.
The existing next-open path still uses its listing-bound actual open and original
fill/slippage calculation; the extraction preserves the fee operation order.

## Arithmetic fixtures

The following are synthetic test coefficients, not an approved trading policy:
commission 0.01/share, fixed fee 1/order, notional fee 10 bps, slippage 5 bps.

| Delta at price 100 | Fees | Shortfall | Cost | Cash delta |
| --- | ---: | ---: | ---: | ---: |
| Buy 5 | 1.55 | 0.25 | 1.80 | -501.80 |
| Sell 5 | 1.55 | 0.25 | 1.80 | 498.20 |
| Zero | 0 | 0 | 0 | 0 |

Buying five of one security and selling five of another retains both order fees
and both shortfalls: total cost 3.60 and cash decrease 3.60. No family parameter
exists: an internal rebalance pays the same costs as the same signed delta in a
family switch. A separate computation at price 103 produces cost 1.8225 and cannot
mutate the earlier 1.80 result.

Input prices and quantities must fit the existing portfolio context. Arithmetic
uses the repository's isolated 34-digit ROUND_HALF_EVEN context and canonical
money spelling, including its rounding behavior; no cents rounding or float
tolerance is introduced. Missing/invalid models, forged model hashes, nonfinite
or unrepresentable inputs, and arithmetic overflow raise `ValueError`. A zero
delta still validates its price and cost model before returning zero costs.

## Required producer integration

The calling producer must still authenticate the original account, causal
positions/cash/claims, complete target, close witnesses, listing/currency/session,
cutoff, original issuer and frozen policy. A number supplied as `decision_close`
is not evidence that it came from an eligible close. This component cannot check
those bindings and must not be used to mint a qualified estimate from caller
assertions.

The numerical rebalance helper below supplies cost totals and a cash projection.
Authenticating account funding, authoritative causal NAV, cost/NAV,
pending-execution missingness and mandate admission remain #613 and its producer
dependencies. In particular, unpaid claims are not spendable cash. The caller
must propagate unavailable evidence instead of substituting a zero, trimming a
target, calling the execution engine with a relabelled close, or treating this
numeric result as execution permission.

Regression tests cover the fixtures, an independent exact Fraction oracle over
240 price/quantity/fee combinations, hostile ambient Decimal contexts, strict
types, invalid/tampered input, zero-cost refusal cases, immutable outputs and
overflow. Existing actual-rebalance tests cover the shared fee extraction.
Exact test results and the hosted gate belong to the issue and its PR.

## Complete-target numerical rebalance

`estimate_decision_close_rebalance_cost` extends the same arithmetic to an
explicit existing `PortfolioStateV2`, a complete sequence of existing
`SecurityTargetPositionV1` targets, supplied security-close prices and the same
explicit cost model. It revalidates state, targets and model instead of trusting
unchecked frozen instances. The next-open engine shares the existing target
quantity/uniqueness rule; this helper never calls execution or commits a book.

Every holding needs an explicit target, including zero for liquidation. Every
holding and every nonzero delta needs a positive representable supplied close.
Thus an unchanged holding with a missing close refuses even though it would
incur no order fee. An unheld zero target needs no price and creates no order.
The empty portfolio still validates the state and model before returning zero.
These are numerical completeness checks, not source or cutoff verification.

The frozen `DecisionCloseRebalanceCost` contains nonzero `orders`, as tuples of
security ID and `DecisionCloseOrderCost`, sorted by raw UUID bytes. It also
contains `total_fees`, `total_shortfall`, `estimated_cost`, `required_cash`,
`net_sale_proceeds` and `projected_cash`. Each total is summed in that canonical
order under the pinned context. Cost is the sum of per-order estimated costs;
buys require their full outflow and sales contribute their net proceeds.

```text
projected_cash = state.cash_balance + net_sale_proceeds - required_cash
is_funded = projected_cash >= 0
```

`is_funded` is arithmetic only. It is not a mandate approval, original-account
attestation, resolution of pending executions, permission to trade or a usable
AVAILABLE estimate. Unpaid claims are excluded from spendable cash. A negative
projection remains visible; targets are never trimmed to force affordability.
For a five-share sale and purchase at 100 with the coefficients above, total
cost is 3.60. Starting with 4 cash leaves 0.40. A 501.80 purchase with only 480
cash remains unfunded even if the state also carries a 100 unpaid claim.

The supplied state's existing NAV is not automatically the causal denominator
for these supplied closes. This helper neither revalues an authoritative NAV
nor divides by it. Original allocation, account-prefix consistency, listing and
currency, price availability, claim eligibility, and risk/mandate checks remain
requirements of the qualified #613 producer. No family-selection or score
calculation is performed here.
