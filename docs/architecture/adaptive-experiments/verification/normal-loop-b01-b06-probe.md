# Normal-loop acknowledgement, ordering and cold-readback probes

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
| B04: out-of-order status | Older NEW/cumulative zero replaces FILLED in current status; conformance failure |
| B02: fill before acknowledgement | Earlier acknowledgement delivered after fill regresses the current projection; conformance failure |
| B03: duplicate fills | Same-latest-report positive control passes; original report redelivery after another report raises a uniqueness error; accounting exactly-once is not established |
| B05: cancellation/fill race | Ordered fill-before-cancel raises a duplicate persistence error; ordinary unfilled cancellation passes; concurrent race untested |
| B08: commit then lost acknowledgement | Committed report survives separate writer/reader processes with exact hash and no reader broker calls; financial settlement atomicity untested |
| B07 and B09-B12 | Not exercised here |
| Fresh intent while prior outcome is unresolved | Reproduced account-hold conformance failure |
| Independent LEAN comparison | Not run; optional comparison, not a replacement financial book |

Do not infer cancellation/fill race safety, duplicate-fill accounting under
concurrent delivery, late fills, atomic financial settlement, stale-state
risk refusal, research/risk scheduling independence, durable failure
thresholds or complete oversized evidence from these bounded probes.
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

## B04: delayed status cannot be treated as current truth

A separate injected-status probe found that a one-second-older `NEW`
report with cumulative quantity zero becomes the router's current result
after `FILLED` with cumulative quantity five. The journal retains arrival
order, and subsequent same-intent replay returns the older `NEW`.
The confirmed original fill is still retrievable; actual mock cash remains
USD 499 and holdings five shares. This proves a **status projection
regression**, not erased original accounting. Two duplicate positive lookups
before the delayed report retained only one report and no repeat fill/fee.

[The executed B04 evidence](https://github.com/KanujVerma/drift/issues/568#issuecomment-6909299425)
belongs to the same legacy source baseline. Append this block to the same
temporary Python file after the B01/B06 block. It reuses the fixture order
constructor, not a real transport or source receipt.

```python
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from drift.domain.execution import ExecutionStatus, build_execution_report
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter

# Append after the B01/B06 block, reusing its order constructor and uuid7.


class DelayedOldStatus(MockBrokerAdapter):
    delayed = None

    def get_intent_status(self, intent_id):
        return (
            self.delayed
            if self.delayed is not None
            else super().get_intent_status(intent_id)
        )


with TemporaryDirectory(prefix="drift568_b04_") as tmp:
    adapter = DelayedOldStatus(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    journal = PersistentOrderIntentJournal(Path(tmp) / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = order(uuid7(), 5, "fixture-out-of-order")
    fill = router.route_intent(intent)
    assert fill.status is ExecutionStatus.FILLED and fill.cum_quantity == 5
    # Positive duplicate lookup: one report, no repeated financial effect.
    assert router.get_intent_status(intent.intent_id) == fill
    assert router.get_intent_status(intent.intent_id) == fill
    assert len(journal.list_execution_reports_for_intent(intent.intent_id)) == 1
    adapter.delayed = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id=fill.broker_order_id,
        status=ExecutionStatus.NEW,
        cum_quantity=0,
        leaves_quantity=5,
        reported_at=fill.reported_at - timedelta(seconds=1),
    )
    observed = router.get_intent_status(intent.intent_id)
    assert observed.status is ExecutionStatus.NEW and observed.cum_quantity == 0
    assert journal.get_latest_execution_report(intent.intent_id) == observed
    assert router.route_intent(intent) == observed
    assert journal.get_execution_report(fill.report_id) == fill
    assert adapter.cash == Decimal("499") and adapter.get_positions()[0].quantity == 5
    assert len(journal.list_execution_reports_for_intent(intent.intent_id)) == 2
    journal.close()
    print(
        "B04 conformance failure reproduced: delayed older NEW/cum=0 becomes latest status and replay result after confirmed FILLED/cum=5. Original fill remains retained; cash 499 and five shares unchanged. Positive duplicate lookups retained one report."
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


## Additional event-ordering and separate-process probes

The standalone program below exercises the same current-main sources and locked
environment. Save it as a separate temporary Python file and run it with
`uv run --locked python <temporary-file.py>`. It invokes that same pinned
interpreter in two child processes for B08. Its synthetic manifests and SQLite
databases remain in temporary directories and are removed on completion.

| Case | Observed result | Limit and required follow-up |
| --- | --- | --- |
| B02: fill visible before submit acknowledgement | The normal mock books five shares and a USD 1 fee. A reentrant status query persists the FILLED report before submit returns an earlier ACKNOWLEDGED/cumulative-zero report. Current projection and same-intent replay then return the acknowledgement. Cash remains USD 499 and shares five; both reports survive. | Deterministic event interleaving, not a concurrent transport test. Do not allow an earlier acknowledgement to lower already-confirmed exposure. |
| B03: duplicate original fill after an intervening report | Querying the adapter again returns its original FILLED report. The router compares only the latest report ID, then attempts a duplicate insert and raises DuplicateIntentRecordError. Two records remain, cash USD 499 and shares five. | This is duplicate-delivery handling failure, not double settlement. Deduplication must cover retained report identity, and conflicting observations need explicit handling. |
| B05 positive control | With auto-fill off, ordinary ACKNOWLEDGED to CANCELED succeeds: two reports, cash USD 1,000, no shares. | A confirmed unfilled cancellation still needs to work. |
| B05: fill completes before cancellation | The mock correctly returns the existing FILLED report. The router tries to persist it again and raises DuplicateIntentRecordError. One original fill remains, cash USD 499 and shares five. | Ordered race boundary only. No false cancellation is stored, but the consumer gets a persistence exception instead of the confirmed outcome. Concurrent/partial/late-fill cases remain. |
| B08: report commit followed by lost application response | The writer routes and commits a fill, then injects response loss. It exits. A distinct reader process loads the intent and returns the exact original report twice; submit/status methods are configured to fail if called. One report remains and the closed SQLite file SHA256 is unchanged. | Positive cold readback at the already-committed-report boundary. This does not cover a crash before report commit, persistent broker state, account settlement, issuer authenticity or sender fencing. |

These observations were reproduced under CPython 3.14.6. The first complete run
used separate writer PID 26644 and reader PID 56052. Process IDs are diagnostic
observations, not origin or authority credentials. Every fixture has positive
cash/position/report assertions. A successful program exit confirms the
observations above, including the defects; it does not certify conformance.

The next runtime work remains the explicit producer implementation in
[#411](https://github.com/KanujVerma/drift/issues/411): truthful observations,
idempotent report acceptance across the retained history, durable account holds,
ordered/conflicting evidence handling, transactional settlement and complete
consumer migration. No report is rewritten, discarded or relabelled here.

```python
"""Offline diagnostics for #568; successful assertions can reproduce defects."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid7

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import (
    DuplicateIntentRecordError,
    PersistentOrderIntentJournal,
)
from drift.execution.router import BrokerNeutralExecutionRouter


def order(label):
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=label,
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
        ),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100"),
        created_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
    )


def emit(case, **values):
    print(json.dumps({"case": case, **values}, sort_keys=True))


class EarlyFill(MockBrokerAdapter):
    router = None

    def submit_intent(self, intent):
        fill = super().submit_intent(intent)
        assert self.router.get_intent_status(intent.intent_id) == fill
        # Represent an earlier acknowledgement delivered after its fill.
        return build_execution_report(
            report_id=uuid7(),
            intent_id=intent.intent_id,
            broker_order_id=fill.broker_order_id,
            status=ExecutionStatus.ACKNOWLEDGED,
            cum_quantity=0,
            leaves_quantity=intent.quantity,
            reported_at=fill.reported_at - timedelta(seconds=1),
        )


def ordering_probes():
    with TemporaryDirectory(prefix="drift568_ordering_") as tmp:
        adapter = EarlyFill(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
        journal = PersistentOrderIntentJournal(Path(tmp) / "early.sqlite")
        router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
        adapter.router = router
        intent = order("fixture-fill-before-ack")
        ack = router.route_intent(intent)
        reports = journal.list_execution_reports_for_intent(intent.intent_id)
        fill = reports[0]
        assert len(reports) == 2 and fill.status is ExecutionStatus.FILLED
        assert fill.cum_quantity == 5 and fill.fee_amount == Decimal("1")
        assert ack.status is ExecutionStatus.ACKNOWLEDGED and ack.cum_quantity == 0
        assert journal.get_latest_execution_report(intent.intent_id) == ack
        assert router.route_intent(intent) == ack
        assert (
            adapter.cash == Decimal("499") and adapter.get_positions()[0].quantity == 5
        )
        emit("B02", outcome="projection_regression", cash="499", shares=5, reports=2)
        # The same original fill now reappears after a different latest report.
        try:
            router.get_intent_status(intent.intent_id)
        except DuplicateIntentRecordError:
            pass
        else:
            raise AssertionError("expected duplicate report uniqueness refusal")
        assert journal.list_execution_reports_for_intent(intent.intent_id) == reports
        assert (
            adapter.cash == Decimal("499") and adapter.get_positions()[0].quantity == 5
        )
        emit("B03", outcome="duplicate_after_intervening_report_raises", reports=2)
        journal.close()

        adapter = MockBrokerAdapter(
            initial_cash=Decimal("1000"), default_fee=Decimal("1"), auto_fill=False
        )
        journal = PersistentOrderIntentJournal(Path(tmp) / "cancel-control.sqlite")
        router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
        intent = order("fixture-cancel-before-fill")
        ack = router.route_intent(intent)
        cancel = router.cancel_intent(intent.intent_id)
        assert ack.status is ExecutionStatus.ACKNOWLEDGED
        assert cancel.status is ExecutionStatus.CANCELED and cancel.cum_quantity == 0
        assert adapter.cash == Decimal("1000") and adapter.get_positions() == ()
        assert len(journal.list_execution_reports_for_intent(intent.intent_id)) == 2
        emit("B05_control", outcome="cancel_unfilled_passed", cash="1000", shares=0)
        journal.close()

        adapter = MockBrokerAdapter(
            initial_cash=Decimal("1000"), default_fee=Decimal("1")
        )
        journal = PersistentOrderIntentJournal(Path(tmp) / "fill-before-cancel.sqlite")
        router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
        intent = order("fixture-filled-before-cancel")
        fill = router.route_intent(intent)
        assert fill.status is ExecutionStatus.FILLED
        # The mock truthfully returns the existing fill instead of a cancellation.
        assert adapter.cancel_intent(intent.intent_id) == fill
        try:
            router.cancel_intent(intent.intent_id)
        except DuplicateIntentRecordError:
            pass
        else:
            raise AssertionError("expected duplicate report persistence refusal")
        assert journal.get_latest_execution_report(intent.intent_id) == fill
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (fill,)
        assert (
            adapter.cash == Decimal("499") and adapter.get_positions()[0].quantity == 5
        )
        emit(
            "B05",
            outcome="filled_before_cancel_raises",
            cash="499",
            shares=5,
            reports=1,
        )
        journal.close()


class NoBrokerAccess(MockBrokerAdapter):
    def submit_intent(self, intent):
        raise AssertionError("cold replay must not submit")

    def get_intent_status(self, intent_id):
        raise AssertionError("committed report needs no broker lookup")


def writer(directory):
    adapter = MockBrokerAdapter(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    journal = PersistentOrderIntentJournal(directory / "committed.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = order("fixture-commit-before-client-ack")
    try:
        report = router.route_intent(intent)
        # The report committed successfully, but the application response is lost.
        raise TimeoutError("fixture response lost after report commit")
    except TimeoutError:
        pass
    assert report.status is ExecutionStatus.FILLED
    assert report.cum_quantity == 5 and report.fee_amount == Decimal("1")
    assert adapter.cash == Decimal("499") and adapter.get_positions()[0].quantity == 5
    (directory / "fixture.json").write_text(
        json.dumps(
            {"intent_id": str(intent.intent_id), "report_hash": report.report_hash}
        ),
        encoding="utf-8",
    )
    journal.close()
    emit("B08_writer", pid=os.getpid(), cash="499", shares=5)


def reader(directory):
    fixture = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))
    db = directory / "committed.sqlite"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    journal = PersistentOrderIntentJournal(db)
    intent = journal.get_intent(UUID(fixture["intent_id"]))
    assert intent is not None
    router = BrokerNeutralExecutionRouter(adapter=NoBrokerAccess(), journal=journal)
    report = router.route_intent(intent)
    assert report.report_hash == fixture["report_hash"]
    assert report.status is ExecutionStatus.FILLED and report.cum_quantity == 5
    assert report.fee_amount == Decimal("1")
    assert router.route_intent(intent) == report
    assert journal.list_execution_reports_for_intent(intent.intent_id) == (report,)
    journal.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    emit("B08_reader", pid=os.getpid(), outcome="cold_readback_passed", reports=1)


def main():
    if len(sys.argv) == 3:
        action, directory = sys.argv[1], Path(sys.argv[2])
        {"writer": writer, "reader": reader}[action](directory)
        return
    ordering_probes()
    with TemporaryDirectory(prefix="drift568_cold_") as tmp:
        outputs = []
        for mode in ("writer", "reader"):
            completed = subprocess.run(
                [sys.executable, __file__, mode, tmp],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert not completed.stderr
            print(completed.stdout, end="")
            outputs.append(json.loads(completed.stdout))
        assert outputs[0]["pid"] != outputs[1]["pid"]


if __name__ == "__main__":
    main()
```
