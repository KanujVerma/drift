"""#508 PR B adversarial local-origin tests, synthetic-only trust boundary.

A caller-chosen SQLite chain, publisher string, account hash or reference
cannot authenticate an allocation under an independent configured origin.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest
from test_evaluator_engine import _engine, _run, _run_identity
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)
from test_stage1_synthetic_account_lifecycle import _coordinator, _store

from drift.evaluator.opening_book_lifecycle import OpeningBookLifecycleError
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    ConfiguredLocalSyntheticOriginV1,
    LocalAccountReceiptError,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    read_configured_original,
)


def test_forged_ledger_and_self_consistent_hash_do_not_cross_origin(
    tmp_path: Path,
) -> None:
    good_store = _store(tmp_path)
    good_coordinator = _coordinator(good_store)
    _engine().prepare_opening_book(lifecycle=good_coordinator)
    real = good_coordinator.verified_original()

    forged_home = tmp_path / "attacker"
    forged_home.mkdir()
    fake_store = _store(forged_home)
    fake_coordinator = _coordinator(fake_store)
    _engine().prepare_opening_book(lifecycle=fake_coordinator)
    fake = fake_coordinator.verified_original()

    # Both sets are individually hash-consistent, but only the trusted
    # origin host path/issuer is eligible for this verification.
    assert fake_store.origin.verified_events()
    assert real.allocation_ref != fake.allocation_ref
    with pytest.raises(
        LocalAccountReceiptError, match="ORIGINAL_EVENT_NOT_IN_CONFIGURED_LEDGER"
    ):
        read_configured_original(
            origin=good_store.origin,
            reference=fake.allocation_ref,
            event_type=ALLOCATION,
            allocation_id=fake.allocation_id,
        )


def test_same_path_with_wrong_issuer_claim_is_not_original(tmp_path: Path) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    proof = coordinator.verified_original()
    impostor = ConfiguredLocalSyntheticOriginV1(
        ledger_path=store.origin.ledger_path,
        issuer_instance_id=uuid7(),
    )
    with pytest.raises(LocalAccountReceiptError, match="ISSUER_MISMATCH"):
        read_configured_original(
            origin=impostor,
            reference=proof.allocation_ref,
            event_type=ALLOCATION,
            allocation_id=proof.allocation_id,
        )


def test_crossed_account_scope_and_rehashed_metadata_are_refused(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    proof = coordinator.verified_original()
    for wrong in (
        replace(proof.fields, portfolio_account_id="SYNTH-ACC-R-001"),
        replace(proof.fields, run_id="RUN-002"),
        replace(proof.fields, initial_cash="1"),
        replace(proof.fields, complete_manifest_fingerprint="0" * 64),
    ):
        with pytest.raises(LocalAccountReceiptError, match="SCOPE_OR_WITNESS"):
            store.readback_allocation(
                allocation_id=proof.allocation_id,
                allocation_ref=proof.allocation_ref,
                witness_ref=proof.witness_ref,
                expected_fields=wrong,
            )


def test_forged_hash_and_wrong_original_event_type_are_refused(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    coord = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coord)
    proof = coord.verified_original()
    forged = LocalEventReferenceV1(proof.allocation_ref.event_id, "0" * 64)
    with pytest.raises(LocalAccountReceiptError, match="ISSUER_MISMATCH"):
        read_configured_original(
            origin=store.origin,
            reference=forged,
            event_type=ALLOCATION,
            allocation_id=proof.allocation_id,
        )
    with pytest.raises(LocalAccountReceiptError, match="ORIGINAL_EVENT"):
        store.readback_allocation(
            allocation_id=proof.allocation_id,
            allocation_ref=proof.allocation_ref,
            witness_ref=proof.allocation_ref,
            expected_fields=proof.fields,
        )


def test_equal_hash_book_from_another_engine_is_not_original_instance(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    original_engine = _engine()
    original_engine.prepare_opening_book(lifecycle=coordinator)
    another_engine = _engine()
    other_book = coordinator.verified_original().opening_book
    identity = _run_identity(
        admission=another_engine.admission,
        bundle=another_engine.bundle,
        protocol=another_engine.protocol,
        cost_model=another_engine.cost_model,
        evidence_hash=another_engine.evaluator_evidence_hash,
    )
    assert (
        other_book.cash_balance
        == coordinator.verified_original().opening_book.cash_balance
    )
    with pytest.raises(
        LocalAccountReceiptError, match="NOT_ORIGINAL_ENGINE_BOOK_INSTANCE"
    ):
        coordinator.claim_invocation(
            opening_book=other_book,
            run_identity=identity,
        )
    assert coordinator.local_phase == "failed"
    assert len(store.origin.verified_events()) == 2


def test_claim_clock_rollback_cannot_create_success_or_fresh_cash(
    tmp_path: Path,
) -> None:
    moments = iter(
        (
            datetime(2026, 10, 21, 19, 0, tzinfo=UTC),
            datetime(2026, 10, 21, 19, 0, 1, tzinfo=UTC),
            datetime(2026, 10, 21, 18, 59, tzinfo=UTC),
        )
    )
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "timing.db",
        issuer_instance_id=uuid7(),
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=origin, clock=lambda: next(moments)
    )
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    with pytest.raises(
        LocalAccountReceiptError, match="CLOCK_ROLLBACK_BEFORE_ORIGINAL"
    ):
        _run(engine)
    assert coordinator.local_phase == "failed"
    assert [event.event_type for event in origin.verified_events()] == [
        "stage1.synthetic_account.allocation",
        "stage1.synthetic_account.allocation_observed",
    ]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_caller_mutation_after_e1_verification_cannot_redirect_account(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    camp = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    provenance = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=(),
    )
    coordinator = Stage1SyntheticAccountLifecycleV1(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        store=store,
    )
    original_account = provenance.scope.run_account_binding
    object.__setattr__(
        original_account, "portfolio_account_id", "SYNTH-ACC-R-001"
    )
    with pytest.raises(
        LocalAccountReceiptError, match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
    ):
        _engine().prepare_opening_book(lifecycle=coordinator)
    assert store.origin.verified_events() == ()
    assert coordinator.local_phase == "failed"
