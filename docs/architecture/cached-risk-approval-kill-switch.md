# Cached risk approvals and the emergency kill switch

Issue [#639](https://github.com/KanujVerma/drift/issues/639) corrects a reproducible
emergency-stop bypass in `HardRiskGatekeeper`. At main
`60d572a339835a8ec8d9bb0ab8c7fd4383daeb33`, an order could receive `ALLOWED`, the
persistent kill switch could then trip, and a configured execution router could
submit the same original intent because the gatekeeper returned the old approval
without reading the latch. An offline reproduction with the actual router and
mock adapter filled one share at 100 plus a fee of 1, reducing cash from 1000 to
899 while the latch remained active. No real transport was involved.

## Corrected behavior

Before returning a cached `ALLOWED` verdict, `evaluate_order` reads the current
persistent kill switch. An active latch raises `CachedRiskApprovalBlockedError`,
a `DriftError`, before approval or downstream dispatch. `evaluate_intent` delegates
to that same path. A failed latch read propagates; there is no approval fallback.
A separately connected writer's committed trip and a journal reopened by a new
gatekeeper have the same effect.

Cached denials remain denials. Cached approvals under an untripped latch retain
their existing idempotent return behavior. A fresh order under an active latch
still receives the existing journaled `KILL_SWITCH_ACTIVE` verdict.

The original approval and kill-switch event remain immutable. The V1 risk journal
allows one verdict per order ID, so this change cannot append a second verdict for
the same order, overwrite the old one, or pretend an unrecorded verdict was
journaled. The typed exception reports the current refusal while preserving that
historical evidence. No schema, policy threshold, hash or fixture changes are
required.

## Consumer and recovery boundary

The configured router evaluates risk before `submit_intent`. For an already
approved but never dispatched intent, the new exception stops that submission.
The router has already recorded the outbound intent at this point, so a refusal
can leave a retained intent without an execution report. The exception is not a
broker rejection or proof of broker absence. Callers must preserve that distinction;
this change does not authorize retry, create a replacement intent, clear the latch,
or resume trading.

This check is not a transaction spanning the later adapter call. It does not close
a concurrent trip between the read and dispatch, revalidate all historical risk
inputs, require currently optional gatekeepers, alter previously submitted orders,
implement account-wide UNKNOWN reconciliation from #411, or make a governor or
paper-trading system production-ready. Those remain separate contracts.

## Verification

The new regression suite first ran against unchanged main: 10 behavioral failures
and four passing controls. It covers cached approvals through `evaluate_order`,
`evaluate_intent` and simulated orders, repeated refusal, a second journal
connection, journal reopening, the actual configured router and mock adapter,
latch-read failure, untripped approvals, cached denials and fresh blocked orders.
Router assertions require zero submission attempts, unchanged cash and holdings,
no execution reports, and unchanged historical risk evidence.

Run the focused suite with the repository's pinned interpreter and locked tools:

```text
uv run --locked pytest tests/unit/test_risk_cached_approval_kill_switch.py
```

The issue and pull request record relevant consumer/adversarial regressions,
lint, type and build checks and the full hosted canonical CI result for the exact
published head. Local source snapshots do not contain historical git replay
objects and are not claimed as substitutes for that full CI gate.
