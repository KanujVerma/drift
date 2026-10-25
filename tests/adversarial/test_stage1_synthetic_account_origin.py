"""#508 PR B adversarial local-origin tests, synthetic-only trust boundary.

A caller-chosen SQLite chain, publisher string, account hash or reference
cannot authenticate an allocation under an independent configured origin.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from test_evaluator_engine import _engine, _run, _run_identity
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)
from test_stage1_synthetic_account_lifecycle import (
    START,
    _coordinator,
    _invocation_binding,
    _store,
)

from drift.domain.common import ImmutableJSONValue
from drift.evaluator.opening_book_lifecycle import (
    OpeningBookLifecycleError,
    invocation_binding_payload,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    CLAIM,
    CONSUMED,
    WITNESS,
    ConfiguredLocalSyntheticOriginV1,
    LocalAccountReceiptError,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    read_configured_original,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)


@pytest.mark.parametrize("reused_token", [False, True])
def test_bound_claim_enforces_both_allocation_and_token_uniqueness(
    tmp_path: Path, reused_token: bool
) -> None:
    store = _store(tmp_path)
    b = _coordinator(store, arm="ARM-B")
    r = _coordinator(store, arm="ARM-R")
    _engine().prepare_opening_book(lifecycle=b)
    _engine().prepare_opening_book(lifecycle=r)
    first = b.verified_original()
    second = r.verified_original() if reused_token else first
    binding = _invocation_binding()
    claim = store.append_invocation_claim(
        original=first, identity_hash="a" * 64, invocation_binding=binding
    )
    with pytest.raises(LocalAccountReceiptError, match="DUPLICATE"):
        store.append_invocation_claim(
            original=second,
            identity_hash="a" * 64,
            invocation_binding=binding if reused_token else _invocation_binding(),
        )
    assert [event.event_type for event in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
        ALLOCATION,
        WITNESS,
        CLAIM,
    ]
    # A refused competing append does not rewrite the retained first claim.
    store.append_consumption(
        original=first,
        claim_ref=claim,
        identity_hash="a" * 64,
        invocation_binding=binding,
    )


@pytest.mark.parametrize("bound_claim", [False, True])
def test_claim_and_consumption_cannot_mix_legacy_and_bound_versions(
    tmp_path: Path, bound_claim: bool
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
    binding = _invocation_binding()
    if bound_claim:
        coordinator.claim_bound_invocation(
            opening_book=book, run_identity=identity, binding=binding
        )
    else:
        coordinator.claim_invocation(opening_book=book, run_identity=identity)
    with pytest.raises(LocalAccountReceiptError, match="BINDING_MISMATCH"):
        if bound_claim:
            coordinator.observe_consumption(opening_book=book, run_identity=identity)
        else:
            coordinator.observe_bound_consumption(
                opening_book=book, run_identity=identity, binding=binding
            )
    assert coordinator.local_phase == "failed"
    assert coordinator._claim is not None
    # Direct store use has the same version refusal, independently of phases.
    with pytest.raises(LocalAccountReceiptError, match="BINDING_MISMATCH"):
        store.append_consumption(
            original=coordinator.verified_original(),
            claim_ref=coordinator._claim,
            identity_hash=identity.run_identity_hash,
            invocation_binding=None if bound_claim else binding,
        )
    assert [event.event_type for event in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
        CLAIM,
    ]


@pytest.mark.parametrize(
    "identifier", ["invocation_id", "m0_run_id", "m0_audit_event_id"]
)
def test_bound_consumption_rejects_each_changed_original_identifier(
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
    binding = _invocation_binding()
    expected = invocation_binding_payload(binding)
    coordinator.claim_bound_invocation(
        opening_book=book, run_identity=identity, binding=binding
    )
    object.__setattr__(getattr(binding, identifier), "int", uuid7().int)
    with pytest.raises(LocalAccountReceiptError, match="BINDING_MISMATCH"):
        coordinator.observe_bound_consumption(
            opening_book=book, run_identity=identity, binding=binding
        )
    assert coordinator.local_phase == "failed"
    assert coordinator._claim is not None
    with pytest.raises(LocalAccountReceiptError, match="BINDING_MISMATCH"):
        store.append_consumption(
            original=coordinator.verified_original(),
            claim_ref=coordinator._claim,
            identity_hash=identity.run_identity_hash,
            invocation_binding=binding,
        )
    events = store.origin.verified_events()
    assert len(events) == 3
    assert isinstance(events[-1].payload, Mapping)
    assert events[-1].payload["invocation_binding"] == expected


@pytest.mark.parametrize(
    "malformation",
    [
        "different_claim_event_id",
        "legacy_schema_with_binding",
        "bound_schema_legacy_profile",
        "missing_binding",
        "extra_binding_field",
        "noncanonical_uuid",
    ],
)
def test_malformed_original_bound_claim_cannot_authorize_consumption(
    tmp_path: Path, malformation: str
) -> None:
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    original = coordinator.verified_original()
    binding = _invocation_binding()
    encoded = invocation_binding_payload(binding)
    payload: dict[str, ImmutableJSONValue] = {
        "profile": "drift-stage1-synthetic-account-local/2-candidate",
        "issuer_instance_id": str(store.origin.issuer_instance_id),
        "allocation_event_hash": original.allocation_ref.event_hash,
        "witness_event_hash": original.witness_ref.event_hash,
        "identity_hash": "a" * 64,
        "invocation_binding": encoded,
    }
    schema = "2"
    event_id = binding.invocation_id
    if malformation == "different_claim_event_id":
        event_id = uuid7()
    elif malformation == "legacy_schema_with_binding":
        schema = "1"
        payload["profile"] = "drift-stage1-synthetic-account-local/1-candidate"
    elif malformation == "bound_schema_legacy_profile":
        payload["profile"] = "drift-stage1-synthetic-account-local/1-candidate"
    elif malformation == "missing_binding":
        del payload["invocation_binding"]
    elif malformation == "extra_binding_field":
        encoded["invented_authority"] = "true"
    else:
        encoded["m0_run_id"] = "{" + encoded["m0_run_id"] + "}"
    malformed = store._writer.append(
        AuditEventDraft(
            event_id=event_id,
            event_type=CLAIM,
            timestamp=START.replace(second=10),
            entity_type="stage1_synthetic_account",
            entity_id=original.allocation_id,
            schema_version=schema,
            payload=payload,
        )
    )
    with pytest.raises(LocalAccountReceiptError):
        store.append_consumption(
            original=original,
            claim_ref=LocalEventReferenceV1(malformed.event_id, malformed.event_hash),
            identity_hash="a" * 64,
            invocation_binding=binding,
        )
    assert len(store.origin.verified_events()) == 3


@pytest.mark.parametrize("transition", ["claim", "consume"])
def test_bound_append_uncertainty_is_terminal_without_recredit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
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
    binding = _invocation_binding()
    if transition == "consume":
        coordinator.claim_bound_invocation(
            opening_book=book, run_identity=identity, binding=binding
        )
    actual_append = store._append

    def lose_return_after_commit(**kwargs: Any) -> Any:
        actual_append(**kwargs)
        raise OSError("synthetic readback interruption after commit")

    monkeypatch.setattr(store, "_append", lose_return_after_commit)
    with pytest.raises(OSError, match="readback interruption"):
        if transition == "claim":
            coordinator.claim_bound_invocation(
                opening_book=book, run_identity=identity, binding=binding
            )
        else:
            coordinator.observe_bound_consumption(
                opening_book=book, run_identity=identity, binding=binding
            )
    assert coordinator.local_phase == "failed"
    events = store.origin.verified_events()
    assert [event.event_type for event in events] == (
        [ALLOCATION, WITNESS, CLAIM]
        if transition == "claim"
        else [ALLOCATION, WITNESS, CLAIM, CONSUMED]
    )
    for supplied in (binding, _invocation_binding()):
        with pytest.raises(LocalAccountReceiptError, match="INVALID_TRANSITION"):
            coordinator.claim_bound_invocation(
                opening_book=book, run_identity=identity, binding=supplied
            )
    with pytest.raises(LocalAccountReceiptError, match="INVALID_TRANSITION"):
        coordinator.claim_invocation(opening_book=book, run_identity=identity)
    with pytest.raises(LocalAccountReceiptError, match="DUPLICATE"):
        _engine().prepare_opening_book(lifecycle=_coordinator(store))
    assert store.origin.verified_events() == events


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
    object.__setattr__(original_account, "portfolio_account_id", "SYNTH-ACC-R-001")
    with pytest.raises(
        LocalAccountReceiptError, match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
    ):
        _engine().prepare_opening_book(lifecycle=coordinator)
    assert store.origin.verified_events() == ()
    assert coordinator.local_phase == "failed"


@pytest.mark.parametrize("transition", ["claim", "consume"])
@pytest.mark.parametrize("bound", [False, True])
def test_mutation_during_original_commit_clock_refuses_before_append(
    tmp_path: Path, transition: str, bound: bool
) -> None:
    """A callback mutating E1 inside the clock cannot publish a new event."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    engine = _engine()
    engine.prepare_opening_book(lifecycle=coordinator)
    assert coordinator.local_phase == "ready"
    book = coordinator._original_book
    assert book is not None
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )

    binding = _invocation_binding()
    expected_events = [ALLOCATION, WITNESS]
    if transition == "consume":
        if bound:
            coordinator.claim_bound_invocation(
                opening_book=book, run_identity=identity, binding=binding
            )
        else:
            coordinator.claim_invocation(opening_book=book, run_identity=identity)
        expected_events.append(CLAIM)

    def mutating_clock() -> datetime:
        object.__setattr__(
            coordinator._source_provenance.scope.run_account_binding,
            "portfolio_account_id",
            "SYNTH-ACC-R-001",
        )
        return datetime(2026, 10, 21, 19, 0, 10, tzinfo=UTC)

    object.__setattr__(store, "_clock", mutating_clock)
    with pytest.raises(
        LocalAccountReceiptError,
        match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION",
    ):
        if transition == "claim":
            if bound:
                coordinator.claim_bound_invocation(
                    opening_book=book, run_identity=identity, binding=binding
                )
            else:
                coordinator.claim_invocation(opening_book=book, run_identity=identity)
        elif bound:
            coordinator.observe_bound_consumption(
                opening_book=book, run_identity=identity, binding=binding
            )
        else:
            coordinator.observe_consumption(opening_book=book, run_identity=identity)

    assert coordinator.local_phase == "failed"
    observed = [event.event_type for event in store.origin.verified_events()]
    assert observed == expected_events
    assert CONSUMED not in observed
    with pytest.raises(LocalAccountReceiptError, match="INVALID_TRANSITION"):
        coordinator.claim_invocation(opening_book=book, run_identity=identity)


def test_provenance_mutation_at_readback_return_refuses_original(
    tmp_path: Path,
) -> None:
    """An injected read adapter cannot return after changing source identity."""
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    _engine().prepare_opening_book(lifecycle=coordinator)
    actual_readback = store.readback_allocation

    def mutate_after_readback(**kwargs: Any) -> Any:
        readback = actual_readback(**kwargs)
        object.__setattr__(
            coordinator._source_provenance.scope.run_account_binding,
            "portfolio_account_id",
            "SYNTH-ACC-R-001",
        )
        return readback

    object.__setattr__(store, "readback_allocation", mutate_after_readback)
    with pytest.raises(
        LocalAccountReceiptError,
        match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION",
    ):
        coordinator.verified_original()
    assert [event.event_type for event in store.origin.verified_events()] == [
        ALLOCATION,
        WITNESS,
    ]


@pytest.mark.parametrize("transition", ["claim", "consume"])
@pytest.mark.parametrize("bound", [False, True])
def test_provenance_change_after_ledger_append_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
    bound: bool,
) -> None:
    """Already-committed audit evidence remains original, never a success."""
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
    binding = _invocation_binding()
    retained_events = [ALLOCATION, WITNESS]
    if transition == "consume":
        if bound:
            coordinator.claim_bound_invocation(
                opening_book=book, run_identity=identity, binding=binding
            )
        else:
            coordinator.claim_invocation(opening_book=book, run_identity=identity)
        retained_events.append(CLAIM)

    actual_append = LocalSyntheticAccountReceiptStoreV1._append

    def mutate_after_write(
        source_store: LocalSyntheticAccountReceiptStoreV1, **kwargs: Any
    ) -> Any:
        receipt = actual_append(source_store, **kwargs)
        if kwargs["kind"] == (CLAIM if transition == "claim" else CONSUMED):
            object.__setattr__(
                coordinator._source_provenance.scope.run_account_binding,
                "portfolio_account_id",
                "SYNTH-ACC-R-001",
            )
        return receipt

    monkeypatch.setattr(
        LocalSyntheticAccountReceiptStoreV1, "_append", mutate_after_write
    )
    with pytest.raises(
        LocalAccountReceiptError,
        match="E1_PROVENANCE_MUTATED_AFTER_VALIDATION",
    ):
        if transition == "claim":
            if bound:
                coordinator.claim_bound_invocation(
                    opening_book=book, run_identity=identity, binding=binding
                )
            else:
                coordinator.claim_invocation(opening_book=book, run_identity=identity)
        elif bound:
            coordinator.observe_bound_consumption(
                opening_book=book, run_identity=identity, binding=binding
            )
        else:
            coordinator.observe_consumption(opening_book=book, run_identity=identity)

    # The original append-only event cannot be erased. It binds only the
    # verified original E1 allocation and the transition is not acknowledged.
    events = store.origin.verified_events()
    assert [event.event_type for event in events] == [
        *retained_events,
        CLAIM if transition == "claim" else CONSUMED,
    ]
    assert coordinator.local_phase == "failed"
    with pytest.raises(LocalAccountReceiptError, match="INVALID_TRANSITION"):
        coordinator.claim_invocation(opening_book=book, run_identity=identity)
