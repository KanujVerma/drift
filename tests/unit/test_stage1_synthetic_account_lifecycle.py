"""PR B #548: real local SQLite opening-book receipt and consumption tests.

All outcomes are synthetic engineering evidence only, not scientific G3
admission or authenticated original producer approval for live accounts.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from test_evaluator_engine import _engine, _run
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.evaluator.opening_book_lifecycle import OpeningBookLifecycleError
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    CLAIM,
    CONSUMED,
    WITNESS,
    ConfiguredLocalSyntheticOriginV1,
    LocalAccountReceiptError,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json

START = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)


class _ObservedClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        instant = START + timedelta(seconds=self.calls)
        self.calls += 1
        return instant


def _store(
    tmp_path: Path,
    *,
    clock: _ObservedClock | None = None,
) -> LocalSyntheticAccountReceiptStoreV1:
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "owner-configured-original.db",
        issuer_instance_id=uuid7(),
    )
    return LocalSyntheticAccountReceiptStoreV1(
        origin=origin,
        clock=_ObservedClock() if clock is None else clock,
    )


def _coordinator(
    store: LocalSyntheticAccountReceiptStoreV1, *, arm: str = "ARM-B"
) -> Stage1SyntheticAccountLifecycleV1:
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    provenance = build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id=arm,
        checkpoint_id="CKPT-001",
        events=(),
    )
    return Stage1SyntheticAccountLifecycleV1(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        store=store,
    )


def test_original_engine_book_is_retained_then_claimed_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    origin = store.origin
    original = _coordinator(store)
    engine = _engine()
    baseline = canonical_json(_run(_engine()))

    engine.prepare_opening_book(lifecycle=original)
    proof = original.verified_original()
    assert original.local_phase == "ready"
    assert proof.fields.portfolio_account_id == "SYNTH-ACC-B-001"
    assert proof.fields.initial_cash == "10000"
    assert proof.opening_book.cash_balance == Decimal("10000")
    assert proof.opening_book.holdings == ()
    assert proof.opening_book.pending_cash_claims == ()
    assert proof.original_book_bytes == canonical_json(proof.opening_book)
    assert not proof.original_issuer_authenticated_for_e6b

    before = origin.verified_events()
    assert [e.event_type for e in before] == [ALLOCATION, WITNESS]
    assert proof.receipt_observed_available_by_at > before[0].timestamp

    artifacts = _run(engine)
    assert canonical_json(artifacts) == baseline
    assert original.local_phase == "consumed"
    assert [e.event_type for e in origin.verified_events()] == [
        ALLOCATION, WITNESS, CLAIM, CONSUMED
    ]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    assert len(origin.verified_events()) == 4


def test_distinct_b_r_original_accounts_in_single_configured_ledger(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    b = _coordinator(store, arm="ARM-B")
    r = _coordinator(store, arm="ARM-R")
    _engine().prepare_opening_book(lifecycle=b)
    _engine().prepare_opening_book(lifecycle=r)
    pb = b.verified_original()
    pr = r.verified_original()
    assert pb.fields.portfolio_account_id == "SYNTH-ACC-B-001"
    assert pr.fields.portfolio_account_id == "SYNTH-ACC-R-001"
    assert pb.allocation_id != pr.allocation_id
    assert pb.original_book_bytes == pr.original_book_bytes
    assert pb.allocation_ref != pr.allocation_ref
    assert len(store.origin.verified_events()) == 4


def test_duplicate_account_key_cannot_provision_fresh_cash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=first)
    before = len(store.origin.verified_events())
    duplicate = _coordinator(store)
    with pytest.raises(
        LocalAccountReceiptError, match="DUPLICATE_OR_CONFLICTING_ORIGINAL"
    ):
        _engine().prepare_opening_book(lifecycle=duplicate)
    assert duplicate.local_phase == "failed"
    assert len(store.origin.verified_events()) == before
    assert first.local_phase == "ready"


def test_readonly_independent_reopen_verifies_original_after_writer_exit(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    original = coordinator.verified_original()
    # The verifying path uses a fresh SQLite connection, not the writer's
    # memory or an account path supplied by a model/receipt.
    events = ConfiguredLocalSyntheticOriginV1(
        ledger_path=store.origin.ledger_path,
        issuer_instance_id=store.origin.issuer_instance_id,
    ).verified_events()
    assert events[0].event_hash == original.allocation_ref.event_hash
    assert events[1].event_hash == original.witness_ref.event_hash
    payload = events[0].payload
    assert isinstance(payload, Mapping)
    fields = payload["fields"]
    assert isinstance(fields, Mapping)
    assert original.opening_book.admission_hash == fields["admission_hash"]


def test_missing_retention_witness_does_not_make_an_account_ready(
    tmp_path: Path,
) -> None:
    class ReversedClock:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> datetime:
            self.calls += 1
            return START if self.calls == 1 else START - timedelta(seconds=2)

    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "rollback.db", issuer_instance_id=uuid7()
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=origin, clock=ReversedClock()
    )
    coordinator = _coordinator(store)
    with pytest.raises(
        LocalAccountReceiptError, match="CLOCK_ROLLBACK_BEFORE_ORIGINAL"
    ):
        _engine().prepare_opening_book(lifecycle=coordinator)
    assert coordinator.local_phase == "failed"
    assert [e.event_type for e in origin.verified_events()] == [ALLOCATION]
    assert coordinator.original_issuer_authenticated_for_e6b is False
    # There is no new opening cash on a retry under the same allocation key.
    other = _coordinator(store)
    with pytest.raises(LocalAccountReceiptError, match="DUPLICATE"):
        _engine().prepare_opening_book(lifecycle=other)


def test_account_allocation_refuses_observed_time_before_bound_at(
    tmp_path: Path,
) -> None:
    bound_at = datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC)
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "prebinding.db", issuer_instance_id=uuid7()
    )
    early = LocalSyntheticAccountReceiptStoreV1(
        origin=origin, clock=lambda: bound_at - timedelta(microseconds=1)
    )
    coordinator = _coordinator(early)
    with pytest.raises(
        LocalAccountReceiptError, match="CLOCK_ROLLBACK_BEFORE_ORIGINAL"
    ):
        _engine().prepare_opening_book(lifecycle=coordinator)
    assert coordinator.local_phase == "failed"
    assert origin.verified_events() == ()


def test_allocation_at_exact_e1_binding_time_is_not_backdated(
    tmp_path: Path,
) -> None:
    bound_at = datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC)
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "exactbinding.db", issuer_instance_id=uuid7()
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=origin, clock=lambda: bound_at
    )
    coord = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coord)
    receipt = coord.verified_original()
    events = origin.verified_events()
    assert [e.event_type for e in events] == [ALLOCATION, WITNESS]
    assert events[0].timestamp == bound_at
    assert receipt.receipt_observed_available_by_at >= bound_at
    assert receipt.fields.bound_at == "2026-10-19T00:00:02.000000Z"
