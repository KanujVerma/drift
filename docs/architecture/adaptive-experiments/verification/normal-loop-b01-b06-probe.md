# Normal-loop lost-acknowledgement conformance probe

## Scope and observed result

This is executed engineering evidence for [#568](https://github.com/KanujVerma/drift/issues/568),
recorded on November 16, 2026 against main
`60d572a339835a8ec8d9bb0ab8c7fd4383daeb33`.
It uses Drift's actual `BrokerNeutralExecutionRouter`,
`PersistentOrderIntentJournal` and `MockBrokerAdapter`, a temporary SQLite
journal, and a deterministic injected acknowledgement loss. It makes no
network or real broker calls and incorporates no external project code.

**The account-wide hold requirement fails in the current legacy path.**
A new intent can dispatch while a previous submission's outcome remains
unresolved. The diagnostic below succeeds by reproducing that defect;
its successful exit is not UNKNOWN architecture conformance.

The original two probes and exact outcomes are also recorded in
[the issue evidence](https://github.com/KanujVerma/drift/issues/568#issuecomment-6908975767).
The result does not change [#411](https://github.com/KanujVerma/drift/issues/411)'s
versioned durable-attempt, account-hold, evidence and settlement requirements.

## Controls and outcomes

All prices, quantities, cash and fees below are synthetic fixture values.

| Scenario | Exact observation | What it establishes |
| --- | --- | --- |
| Submit buy 5 shares at USD 100; mock fills then raises timeout | One adapter submission; cash USD 499; five shares; no persisted execution report | The injected loss occurs after an actual mock fill and USD 1 fee |
| Close journal, recreate journal/router, repeat same intent after three lookup misses | Three uniqueness refusals; still one adapter submission and cash USD 499 | Same-token replay does not resend in this bounded case |
| Reveal the original status and retry same intent | One persisted FILLED report, cumulative quantity 5; later replay returns that report | Positive lookup can recover the original result without a second fill or fee |
| Separate fixture: submit a fresh intent after unresolved first submission | Two adapter submissions; cash USD 398; six shares | Account-wide new-risk hold is absent in this legacy route; conformance failure |

A lookup miss is not broker rejection. In this path the observed
`DuplicateIntentRecordError` is a uniqueness refusal, not a durable,
truthful UNKNOWN observation. The mocked broker survives journal/router
reconstruction in the same process; this is not a separate-process broker
restart or a concurrency/fencing proof.

## Coverage status

| #568 scenario | Status in this evidence |
| --- | --- |
| B01: accepted submission, lost acknowledgement and restart | Partially exercised: journal/router reconstruction with preserved mock transport |
| B06: repeated lookup misses | No resend demonstrated, but durable UNKNOWN semantics not implemented/proven |
| B02-B05 and B07-B12 | Not exercised here |
| Fresh intent while prior outcome is unresolved | Reproduced account-hold conformance failure |
| Independent LEAN comparison | Not run; optional comparison, not a replacement financial book |

Do not infer cancellation/fill race safety, duplicate-fill accounting under
concurrent delivery, late fills, atomic financial settlement, stale-state
risk refusal, research/risk scheduling independence, durable failure
thresholds or complete oversized evidence from these two probes.
The proposed [UNKNOWN design PR](https://github.com/KanujVerma/drift/pull/413)
and [V1 audit PR](https://github.com/KanujVerma/drift/pull/545) have different
scopes; an audit helper does not add a durable router state machine.

## Reproduction

Use the repository-pinned CPython 3.14.6 and unchanged locked environment.
Save the Python block below to a temporary file outside the checkout, then run
`uv run --locked python <temporary-file.py>` from the repository root.
The only generated data is a temporary SQLite journal that is removed after
the probe. The snippet deliberately asserts the observed legacy behavior.
After a future repair, replace this diagnostic with the accepted behavioral
conformance tests; do not preserve the defect to keep this snippet passing.

```python
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid7

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import (
    DuplicateIntentRecordError,
    PersistentOrderIntentJournal,
)
from drift.execution.router import BrokerNeutralExecutionRouter


class LostAcknowledgement(MockBrokerAdapter):
    def __init__(self):
        super().__init__(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
        self.submit_count = 0
        self.hide_status = True

    def submit_intent(self, intent):
        self.submit_count += 1
        super().submit_intent(intent)
        raise TimeoutError("synthetic acknowledgement lost after mock fill")

    def get_intent_status(self, intent_id):
        return None if self.hide_status else super().get_intent_status(intent_id)


def order(security, quantity, label):
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=label,
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
        ),
        security_id=security,
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100"),
        created_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
    )


with TemporaryDirectory(prefix="drift568_") as tmp:
    security = uuid7()
    adapter = LostAcknowledgement()
    intent = order(security, 5, "fixture-lost-ack")
    db = Path(tmp) / "same-token.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        router.route_intent(intent)
        raise AssertionError("expected lost acknowledgement")
    except TimeoutError:
        pass
    assert adapter.submit_count == 1 and adapter.cash == Decimal("499")
    assert adapter.get_positions()[0].quantity == 5
    assert journal.list_execution_reports_for_intent(intent.intent_id) == ()
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    for _ in range(3):
        try:
            router.route_intent(intent)
            raise AssertionError("expected uniqueness refusal")
        except DuplicateIntentRecordError:
            pass
    assert adapter.submit_count == 1 and adapter.cash == Decimal("499")
    adapter.hide_status = False
    report = router.route_intent(intent)
    assert report.status == ExecutionStatus.FILLED and report.cum_quantity == 5
    assert len(journal.list_execution_reports_for_intent(intent.intent_id)) == 1
    assert router.route_intent(intent) == report
    assert adapter.submit_count == 1 and adapter.cash == Decimal("499")
    journal.close()
    print(
        "B01/B06 bounded probe: reopened journal/router; three lookup misses caused uniqueness refusal and no resend; later positive lookup retained one report, one fill, one fee. No durable UNKNOWN observation is established."
    )

    adapter = LostAcknowledgement()
    journal = PersistentOrderIntentJournal(Path(tmp) / "fresh-id.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    for quantity, label in ((5, "fixture-uncertain-first"), (1, "fixture-fresh-id")):
        try:
            router.route_intent(order(security, quantity, label))
            raise AssertionError("expected lost acknowledgement")
        except TimeoutError:
            pass
    assert adapter.submit_count == 2 and adapter.cash == Decimal("398")
    assert adapter.get_positions()[0].quantity == 6
    journal.close()
    print(
        "Account-hold negative reproduced: fresh intent after unresolved submit dispatched again; 2 mock submissions, cash 398, 6 shares. This is a conformance failure, not an accepted UNKNOWN/hold implementation. No real transport was used."
    )
```

## Next implementation boundary

The next repair must define and implement the accepted durable UNKNOWN,
account hold, evidence-resolution and settlement behavior under #411,
with an explicit source/test write set. It must prove both same-intent
idempotency and new-intent account gating across supported crash boundaries.
An exception-only catch, optimistic lookup miss, invented broker rejection,
automatic retry or assumed safe resume would not satisfy that requirement.

This document changes no runtime API, V1 persisted report, policy threshold,
fixture, dependency, broker state or operational permission.
