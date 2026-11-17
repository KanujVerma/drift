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

Account-level summation, authoritative causal NAV, cost/NAV, spendable funding,
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
