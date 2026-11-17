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
from test_evaluator_engine import _buy_ten, _engine, _run, _run_identity
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.evaluator.opening_book_lifecycle import (
    OpeningBookLifecycleError,
    OriginalInvocationBindingV1,
    invocation_binding_payload,
    parse_original_invocation_binding,
)
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
    read_configured_original,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json

START = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)


def _invocation_binding() -> OriginalInvocationBindingV1:
    return OriginalInvocationBindingV1(
        invocation_id=uuid7(),
        m0_run_id=uuid7(),
        m0_audit_event_id=uuid7(),
    )


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
        ALLOCATION,
        WITNESS,
        CLAIM,
        CONSUMED,
    ]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    assert len(origin.verified_events()) == 4
    assert all(event.schema_version == "1" for event in origin.verified_events())
    assert all(
        isinstance(event.payload, Mapping) and "invocation_binding" not in event.payload
        for event in origin.verified_events()
    )


def test_bound_engine_consumption_retains_exact_original_invocation(
    tmp_path: Path,
) -> None:
    """The actual prepared engine emits one bound claim and consumption."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    original = coordinator.verified_original()
    binding = _invocation_binding()
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    artifacts = engine.run(
        strategy=_buy_ten(),
        run_identity=identity,
        original_invocation_binding=binding,
    )
    assert canonical_json(artifacts) == canonical_json(_run(_engine()))
    assert coordinator.local_phase == "consumed"
    events = ConfiguredLocalSyntheticOriginV1(
        ledger_path=store.origin.ledger_path,
        issuer_instance_id=store.origin.issuer_instance_id,
    ).verified_events()
    assert [event.event_type for event in events] == [
        ALLOCATION,
        WITNESS,
        CLAIM,
        CONSUMED,
    ]
    assert [event.schema_version for event in events] == ["1", "1", "2", "2"]
    claim, consumed = events[-2:]
    assert claim.event_id == binding.invocation_id
    expected = invocation_binding_payload(binding)
    for event in (claim, consumed):
        assert isinstance(event.payload, Mapping)
        assert event.payload["profile"] == (
            "drift-stage1-synthetic-account-local/2-candidate"
        )
        assert event.payload["invocation_binding"] == expected
    assert isinstance(consumed.payload, Mapping)
    assert consumed.payload["claim_event_id"] == str(binding.invocation_id)
    assert consumed.payload["claim_event_hash"] == claim.event_hash
    assert coordinator._claim is not None
    assert coordinator._consumption is not None
    for kind, reference in (
        (CLAIM, coordinator._claim),
        (CONSUMED, coordinator._consumption),
    ):
        retained = read_configured_original(
            origin=store.origin,
            reference=reference,
            event_type=kind,
            allocation_id=original.allocation_id,
        )
        assert retained.schema_version == "2"
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        engine.run(
            strategy=_buy_ten(),
            run_identity=identity,
            original_invocation_binding=_invocation_binding(),
        )
    assert len(store.origin.verified_events()) == 4


@pytest.mark.parametrize(
    "identifier", ["invocation_id", "m0_run_id", "m0_audit_event_id"]
)
def test_bound_claim_detaches_uuid_leaves_before_later_consumption(
    tmp_path: Path, identifier: str
) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    book = coordinator._original_book
    assert book is not None
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    supplied = _invocation_binding()
    original_payload = invocation_binding_payload(supplied)
    coordinator.claim_bound_invocation(
        opening_book=book, run_identity=identity, binding=supplied
    )
    object.__setattr__(getattr(supplied, identifier), "int", uuid7().int)
    assert invocation_binding_payload(supplied) != original_payload
    coordinator.observe_bound_consumption(
        opening_book=book,
        run_identity=identity,
        binding=parse_original_invocation_binding(original_payload),
    )
    assert coordinator.local_phase == "consumed"
    for event in store.origin.verified_events()[-2:]:
        assert isinstance(event.payload, Mapping)
        assert event.payload["invocation_binding"] == original_payload


@pytest.mark.parametrize("transition", ["claim", "consume"])
def test_store_binding_snapshot_survives_source_uuid_mutation_in_clock(
    tmp_path: Path, transition: str
) -> None:
    """The injectable clock cannot relabel an already-captured invocation."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    original = coordinator.verified_original()
    binding = _invocation_binding()
    expected = invocation_binding_payload(binding)
    claim_ref = None
    if transition == "consume":
        claim_ref = store.append_invocation_claim(
            original=original, identity_hash="a" * 64, invocation_binding=binding
        )

    def mutating_clock() -> datetime:
        for name in expected:
            object.__setattr__(getattr(binding, name), "int", uuid7().int)
        return START + timedelta(seconds=10)

    store._clock = mutating_clock
    if transition == "claim":
        reference = store.append_invocation_claim(
            original=original, identity_hash="a" * 64, invocation_binding=binding
        )
    else:
        assert claim_ref is not None
        reference = store.append_consumption(
            original=original,
            claim_ref=claim_ref,
            identity_hash="a" * 64,
            invocation_binding=binding,
        )
    event = store.origin.verified_events()[-1]
    assert event.event_id == reference.event_id
    assert isinstance(event.payload, Mapping)
    assert event.payload["invocation_binding"] == expected
    if transition == "claim":
        assert str(event.event_id) == expected["invocation_id"]


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
    store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=ReversedClock())
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
    store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=lambda: bound_at)
    coord = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coord)
    receipt = coord.verified_original()
    events = origin.verified_events()
    assert [e.event_type for e in events] == [ALLOCATION, WITNESS]
    assert events[0].timestamp == bound_at
    assert receipt.receipt_observed_available_by_at >= bound_at
    assert receipt.fields.bound_at == "2026-10-19T00:00:02.000000Z"


def test_changed_provenance_after_allocation_refuses_original_claim(
    tmp_path: Path,
) -> None:
    """Original receipt cannot be associated with later-relabelled E1 scope."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    assert coordinator.local_phase == "ready"
    assert [e.event_type for e in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
    ]
    # This is the original untrusted input object, not the detached verified
    # graph or immutable bytes written into the configured SQLite ledger.
    original_binding = coordinator._source_provenance.scope.run_account_binding
    object.__setattr__(original_binding, "portfolio_account_id", "SYNTH-ACC-R-001")
    with pytest.raises(
        LocalAccountReceiptError, match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
    ):
        coordinator.verified_original()
    with pytest.raises(
        LocalAccountReceiptError, match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
    ):
        _run(engine)
    assert coordinator.local_phase == "failed"
    assert [e.event_type for e in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
    ]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_changed_e1_source_after_claim_refuses_consumption(
    tmp_path: Path,
) -> None:
    """No consumed witness follows a post-claim forged account identity."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    book = coordinator._original_book
    assert book is not None
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    coordinator.claim_invocation(opening_book=book, run_identity=identity)
    assert coordinator.local_phase == "claimed"
    assert [e.event_type for e in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
        CLAIM,
    ]
    object.__setattr__(
        coordinator._source_provenance.scope.run_account_binding,
        "portfolio_account_id",
        "SYNTH-ACC-R-001",
    )
    with pytest.raises(
        LocalAccountReceiptError, match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
    ):
        coordinator.observe_consumption(opening_book=book, run_identity=identity)
    assert coordinator.local_phase == "failed"
    assert [e.event_type for e in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
        CLAIM,
    ]
