"""Tests for Stage 1 auditable trial-event chain."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from drift.experiments.stage1_trial_events import (
    ALLOWED_EVENT_KINDS,
    SCHEMA_VERSION,
    Stage1TrialEvent,
    append_stage1_trial_event,
    build_stage1_trial_event,
    verify_stage1_trial_chain,
)
from drift.serialization.canonical import content_hash

# ---------------------------------------------------------------------------
# Section 11 & 12: Positive Tests and Golden Acceptance Fixtures
# ---------------------------------------------------------------------------


def test_golden_payload_digest() -> None:
    """Validate canonical content_hash for the merged synthetic payload fixture."""
    payload = {"amount": "0.042", "currency": "USD", "kind": "SYNTHETIC"}
    expected_hash = "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
    assert content_hash(payload) == expected_hash


def test_golden_event_digest() -> None:
    """Validate canonical event_hash for the Section 3.3 golden event fixture."""
    payload_hash = "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
    recorded_at = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)
    evidence = ["a" * 64, "f" * 64]
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"

    event = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=recorded_at,
        producer_evidence_references=evidence,
        payload_reference="fixture://synthetic-payload-001",
        payload_hash=payload_hash,
    )

    expected_event_hash = (
        "ea79034394c3669c5ea7d884b160f6e98c3f92e43ab445711be3105926d972b9"
    )

    assert event.schema_version == SCHEMA_VERSION
    assert event.trial_id == trial_id
    assert event.event_id == f"{trial_id}:EVT-0"
    assert event.event_index == 0
    assert event.previous_event_reference == "ROOT"
    assert event.event_kind == "OPPORTUNITY_CREATED"
    assert event.recorded_at == "2026-10-18T20:20:30.000000Z"
    assert event.producer_evidence_references == ("a" * 64, "f" * 64)
    assert event.payload_reference == "fixture://synthetic-payload-001"
    assert event.payload_hash == payload_hash
    assert event.event_hash == expected_event_hash


def test_utc_offset_equivalence() -> None:
    """Validate equivalent UTC times with different offsets produce identical hashes."""
    dt_offset = datetime(2026, 10, 18, 15, 20, 30, tzinfo=timezone(timedelta(hours=-5)))
    dt_utc = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    payload_hash = "0" * 64
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"

    event_a = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=dt_offset,
        producer_evidence_references=["a" * 64],
        payload_reference="fixture://payload-0",
        payload_hash=payload_hash,
    )

    event_b = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=dt_utc,
        producer_evidence_references=["a" * 64],
        payload_reference="fixture://payload-0",
        payload_hash=payload_hash,
    )

    assert event_a.recorded_at == "2026-10-18T20:20:30.000000Z"
    assert event_b.recorded_at == "2026-10-18T20:20:30.000000Z"
    assert event_a.event_hash == event_b.event_hash
    assert event_a == event_b


def test_evidence_ordering_invariance() -> None:
    """Validate that evidence order permutations yield identical canonical hash."""
    ref_a = "a" * 64
    ref_f = "f" * 64
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    recorded_at = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    event_a = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=recorded_at,
        producer_evidence_references=[ref_a, ref_f],
        payload_reference="fixture://payload",
        payload_hash="1" * 64,
    )

    event_b = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=recorded_at,
        producer_evidence_references=[ref_f, ref_a],
        payload_reference="fixture://payload",
        payload_hash="1" * 64,
    )

    assert event_a.producer_evidence_references == (ref_a, ref_f)
    assert event_b.producer_evidence_references == (ref_a, ref_f)
    assert event_a.event_hash == event_b.event_hash


def test_duplicate_evidence_preservation() -> None:
    """Validate that duplicate evidence digests are preserved and sorted."""
    ref_a = "a" * 64
    ref_f = "f" * 64
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    recorded_at = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    event = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=recorded_at,
        producer_evidence_references=[ref_f, ref_a, ref_a],
        payload_reference="fixture://payload",
        payload_hash="1" * 64,
    )

    assert event.producer_evidence_references == (ref_a, ref_a, ref_f)


def test_caller_list_immutability() -> None:
    """Validate that mutating caller's evidence list does not affect the built event."""
    evidence_list = ["a" * 64, "b" * 64]
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    recorded_at = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    event = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=recorded_at,
        producer_evidence_references=evidence_list,
        payload_reference="fixture://payload",
        payload_hash="1" * 64,
    )

    evidence_list.append("c" * 64)
    evidence_list[0] = "z" * 64

    assert event.producer_evidence_references == ("a" * 64, "b" * 64)


def test_valid_three_event_chain_and_append_fourth() -> None:
    """Validate building a 3-event chain, appending a 4th event, and verifying chain."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 18, 20, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 18, 20, 10, 0, tzinfo=UTC)
    t3 = datetime(2026, 10, 18, 20, 15, 0, tzinfo=UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=["0" * 64],
        payload_reference="fixture://opp-0",
        payload_hash="a" * 64,
    )

    ev1 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="INPUTS_BOUND",
        recorded_at=t1,
        producer_evidence_references=["1" * 64],
        payload_reference="fixture://inputs-1",
        payload_hash="b" * 64,
    )

    ev2 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=2,
        previous_event_reference=ev1.event_hash,
        event_kind="PROPOSAL_RECORDED",
        recorded_at=t2,
        producer_evidence_references=["2" * 64],
        payload_reference="fixture://proposal-2",
        payload_hash="c" * 64,
    )

    chain = (ev0, ev1, ev2)
    assert verify_stage1_trial_chain(trial_id=trial_id, events=chain) is True

    # Build and append 4th event
    ev3 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=3,
        previous_event_reference=ev2.event_hash,
        event_kind="ELIGIBILITY_RECORDED",
        recorded_at=t3,
        producer_evidence_references=["3" * 64],
        payload_reference="fixture://elig-3",
        payload_hash="d" * 64,
    )

    extended_chain = append_stage1_trial_event(events=chain, event=ev3)
    assert len(extended_chain) == 4
    assert extended_chain[-1] == ev3
    assert verify_stage1_trial_chain(trial_id=trial_id, events=extended_chain) is True


def test_append_root_to_empty_tuple() -> None:
    """Validate appending a valid root event to an empty tuple."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="fixture://opp-0",
        payload_hash="a" * 64,
    )

    empty_chain: tuple[Stage1TrialEvent, ...] = ()
    new_chain = append_stage1_trial_event(events=empty_chain, event=ev0)
    assert len(new_chain) == 1
    assert new_chain[0] == ev0
    assert verify_stage1_trial_chain(trial_id=trial_id, events=new_chain) is True


def test_idempotent_event_replay() -> None:
    """Validate replaying existing identical event returns original chain unchanged."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 18, 20, 5, 0, tzinfo=UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="fixture://opp-0",
        payload_hash="a" * 64,
    )
    ev1 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="INPUTS_BOUND",
        recorded_at=t1,
        producer_evidence_references=[],
        payload_reference="fixture://inputs-1",
        payload_hash="b" * 64,
    )

    chain = (ev0, ev1)
    # Replay ev0
    replay_chain_0 = append_stage1_trial_event(events=chain, event=ev0)
    assert replay_chain_0 is chain
    assert len(replay_chain_0) == 2

    # Replay ev1
    replay_chain_1 = append_stage1_trial_event(events=chain, event=ev1)
    assert replay_chain_1 is chain
    assert len(replay_chain_1) == 2


def test_deterministic_reconstruction() -> None:
    """Validate building identical event twice yields identical fields and hashes."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)

    ev_a = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=["a" * 64],
        payload_reference="fixture://opp-0",
        payload_hash="1" * 64,
    )

    ev_b = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=["a" * 64],
        payload_reference="fixture://opp-0",
        payload_hash="1" * 64,
    )

    assert ev_a == ev_b
    assert ev_a.event_hash == ev_b.event_hash


# ---------------------------------------------------------------------------
# Section 13: Adversarial Tests
# ---------------------------------------------------------------------------


def test_reject_empty_verification_stream() -> None:
    """Validate rejection of empty events sequence."""
    with pytest.raises(
        ValueError, match="events sequence must be a non-empty sequence"
    ):
        verify_stage1_trial_chain(trial_id="TRIAL-1", events=[])


def test_reject_malformed_trial_id() -> None:
    """Validate rejection of empty or whitespace trial_id."""
    with pytest.raises(ValueError, match="trial_id must be a non-empty string"):
        build_stage1_trial_event(
            trial_id="",
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=datetime.now(UTC),
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    with pytest.raises(ValueError, match="trial_id must be a non-empty string"):
        build_stage1_trial_event(
            trial_id="   ",
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=datetime.now(UTC),
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    with pytest.raises(ValueError, match="trial_id must be a non-empty string"):
        build_stage1_trial_event(
            trial_id=" TRIAL-1 ",
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=datetime.now(UTC),
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )


def test_reject_wrong_trial_id_in_chain() -> None:
    """Validate rejection when chain verification trial_id does not match events."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    ev = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime.now(UTC),
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="a" * 64,
    )

    with pytest.raises(ValueError, match="does not match expected"):
        verify_stage1_trial_chain(
            trial_id="CAMP-001:RUN-001:ARM-R:CKPT-001", events=[ev]
        )


def test_reject_cross_arm_and_cross_run_mixing() -> None:
    """Validate rejection of cross-arm and cross-run mixing in chain and append."""
    arm_b_trial = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    arm_r_trial = "CAMP-001:RUN-001:ARM-R:CKPT-001"
    run_2_trial = "CAMP-001:RUN-002:ARM-B:CKPT-001"

    ev0 = build_stage1_trial_event(
        trial_id=arm_b_trial,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime.now(UTC),
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="a" * 64,
    )

    ev1_arm_r = build_stage1_trial_event(
        trial_id=arm_r_trial,
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="INPUTS_BOUND",
        recorded_at=datetime.now(UTC),
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="does not match expected"):
        verify_stage1_trial_chain(trial_id=arm_b_trial, events=[ev0, ev1_arm_r])

    with pytest.raises(ValueError, match="Cannot append event with trial_id"):
        append_stage1_trial_event(events=(ev0,), event=ev1_arm_r)

    ev1_run_2 = build_stage1_trial_event(
        trial_id=run_2_trial,
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="INPUTS_BOUND",
        recorded_at=datetime.now(UTC),
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="does not match expected"):
        verify_stage1_trial_chain(trial_id=arm_b_trial, events=[ev0, ev1_run_2])

    with pytest.raises(ValueError, match="Cannot append event with trial_id"):
        append_stage1_trial_event(events=(ev0,), event=ev1_run_2)


def test_reject_duplicate_missing_and_reordered_event_index() -> None:
    """Validate rejection of duplicate, non-sequential, and reordered indices."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime.now(UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="a" * 64,
    )
    ev1 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="INPUTS_BOUND",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="b" * 64,
    )
    ev2 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=2,
        previous_event_reference=ev1.event_hash,
        event_kind="PROPOSAL_RECORDED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="c" * 64,
    )

    # Reordered
    with pytest.raises(ValueError, match="non-sequential event_index"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[ev1, ev0])

    # Gap (0, 2)
    with pytest.raises(ValueError, match="non-sequential event_index"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[ev0, ev2])

    # Duplicate index (0, 0)
    ev0_dup = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="INPUTS_BOUND",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref2",
        payload_hash="d" * 64,
    )
    with pytest.raises(ValueError, match="non-sequential event_index"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[ev0, ev0_dup])


def test_reject_boolean_float_and_negative_event_index() -> None:
    """Validate rejection of boolean, float, and negative event_index."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime.now(UTC)

    # Boolean indices
    with pytest.raises(ValueError, match="non-negative non-Boolean integer"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=True,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    with pytest.raises(ValueError, match="non-negative non-Boolean integer"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=False,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # Float indices
    with pytest.raises(ValueError, match="non-negative non-Boolean integer"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0.0,  # type: ignore[arg-type]
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # Negative indices
    with pytest.raises(ValueError, match="non-negative non-Boolean integer"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=-1,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )


def test_reject_incorrect_root_and_predecessor_hash() -> None:
    """Validate rejection of invalid parent references."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime.now(UTC)

    # Root with non-ROOT
    with pytest.raises(ValueError, match="must have previous_event_reference 'ROOT'"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="0" * 64,
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # Non-root with ROOT
    with pytest.raises(
        ValueError, match="Non-root previous_event_reference must be lowercase 64-hex"
    ):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=1,
            previous_event_reference="ROOT",
            event_kind="INPUTS_BOUND",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # Non-root with incorrect predecessor hash in chain
    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="a" * 64,
    )
    ev1_wrong_parent = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=1,
        previous_event_reference="1" * 64,
        event_kind="INPUTS_BOUND",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="expected"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[ev0, ev1_wrong_parent])


def test_reject_malformed_hashes() -> None:
    """Validate rejection of uppercase, short, or non-hex digests."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime.now(UTC)

    # Uppercase payload hash
    with pytest.raises(ValueError, match="payload_hash"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="A" * 64,
        )

    # Short payload hash
    with pytest.raises(ValueError, match="payload_hash"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 63,
        )

    # Non-hex payload hash
    with pytest.raises(ValueError, match="payload_hash"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="g" * 64,
        )

    # Invalid evidence reference
    with pytest.raises(ValueError, match="producer_evidence_references"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=t0,
            producer_evidence_references=["a" * 63],
            payload_reference="ref",
            payload_hash="a" * 64,
        )


def test_reject_unknown_event_kind() -> None:
    """Validate rejection of unapproved event kinds."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime.now(UTC)

    with pytest.raises(ValueError, match="not an allowed event kind"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="TRADE_EXECUTED",
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # Confirm all 10 allowed kinds can be constructed
    for kind in ALLOWED_EVENT_KINDS:
        ev = build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind=kind,
            recorded_at=t0,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )
        assert ev.event_kind == kind


def test_reject_tampered_stored_event() -> None:
    """Validate rejection of events with forged hash, tampered payload, or evidence."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    ev = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=["a" * 64],
        payload_reference="fixture://payload-0",
        payload_hash="1" * 64,
    )

    # Forged event_hash
    forged_hash_ev = replace(ev, event_hash="b" * 64)
    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[forged_hash_ev])

    # Tampered payload_reference
    tampered_ref_ev = replace(ev, payload_reference="fixture://payload-tampered")
    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[tampered_ref_ev])

    # Tampered payload_hash with old event_hash
    tampered_payload_ev = replace(ev, payload_hash="2" * 64)
    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[tampered_payload_ev])

    # Tampered evidence reference
    tampered_evidence_ev = replace(ev, producer_evidence_references=("c" * 64,))
    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[tampered_evidence_ev])


def test_reject_unsorted_persisted_evidence_even_with_recomputed_hash() -> None:
    """Validate unsorted evidence is rejected even if forged event_hash matches."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    ref_a = "a" * 64
    ref_f = "f" * 64
    unsorted_evidence = (ref_f, ref_a)

    preimage = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"{trial_id}:EVT-0",
        "trial_id": trial_id,
        "event_index": 0,
        "previous_event_reference": "ROOT",
        "event_kind": "OPPORTUNITY_CREATED",
        "recorded_at": "2026-10-18T20:20:30.000000Z",
        "producer_evidence_references": list(unsorted_evidence),
        "payload_reference": "fixture://payload-0",
        "payload_hash": "1" * 64,
    }
    recomputed_hash = content_hash(preimage)

    forged_event = Stage1TrialEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"{trial_id}:EVT-0",
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at="2026-10-18T20:20:30.000000Z",
        producer_evidence_references=unsorted_evidence,
        payload_reference="fixture://payload-0",
        payload_hash="1" * 64,
        event_hash=recomputed_hash,
    )

    with pytest.raises(
        ValueError,
        match="producer_evidence_references must be sorted lexicographically",
    ):
        verify_stage1_trial_chain(trial_id=trial_id, events=[forged_event])


def test_reject_naive_datetime_and_string_at_builder() -> None:
    """Validate naive datetimes and non-datetime objects are rejected at the builder."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"

    # Naive datetime
    naive_dt = datetime(2026, 10, 18, 20, 20, 30)
    with pytest.raises(ValueError, match="recorded_at must be timezone-aware"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at=naive_dt,
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )

    # String passed instead of datetime
    with pytest.raises(ValueError, match="recorded_at must be datetime"):
        build_stage1_trial_event(
            trial_id=trial_id,
            event_index=0,
            previous_event_reference="ROOT",
            event_kind="OPPORTUNITY_CREATED",
            recorded_at="2026-10-18T20:20:30.000000Z",  # type: ignore[arg-type]
            producer_evidence_references=[],
            payload_reference="ref",
            payload_hash="a" * 64,
        )


def test_reject_noncanonical_persisted_timestamps() -> None:
    """Validate rejection of noncanonical timestamp formats in stored events."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    ev = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref",
        payload_hash="a" * 64,
    )

    # Numeric offset in stored timestamp
    offset_ev = replace(ev, recorded_at="2026-10-18T15:20:30-05:00")
    with pytest.raises(ValueError, match="does not match canonical format"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[offset_ev])

    # Missing fractional digits
    no_frac_ev = replace(ev, recorded_at="2026-10-18T20:20:30Z")
    with pytest.raises(ValueError, match="does not match canonical format"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[no_frac_ev])

    # Three fractional digits
    three_frac_ev = replace(ev, recorded_at="2026-10-18T20:20:30.000Z")
    with pytest.raises(ValueError, match="does not match canonical format"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[three_frac_ev])

    # Invalid calendar date (Feb 30)
    invalid_date_ev = replace(ev, recorded_at="2026-02-30T20:20:30.000000Z")
    with pytest.raises(ValueError, match="contains invalid calendar date or time"):
        verify_stage1_trial_chain(trial_id=trial_id, events=[invalid_date_ev])


def test_reject_mutable_evidence_container_in_stored_event() -> None:
    """Validate rejection if producer_evidence_references is a mutable list."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 20, 30, tzinfo=UTC)

    ev = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=["a" * 64],
        payload_reference="ref",
        payload_hash="a" * 64,
    )

    mutable_ev = replace(
        ev,
        producer_evidence_references=["a" * 64],  # type: ignore[arg-type]
    )
    with pytest.raises(
        ValueError, match="producer_evidence_references must be an immutable tuple"
    ):
        verify_stage1_trial_chain(trial_id=trial_id, events=[mutable_ev])


def test_reject_conflicting_duplicate_event_id_on_append() -> None:
    """Validate rejection when appending event with existing ID and changed content."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref0",
        payload_hash="a" * 64,
    )

    conflicting_ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref0-conflicting",
        payload_hash="b" * 64,
    )

    chain = (ev0,)
    with pytest.raises(ValueError, match="conflicting event with existing event_id"):
        append_stage1_trial_event(events=chain, event=conflicting_ev0)

    # Chain remains unchanged
    assert len(chain) == 1
    assert chain[0] == ev0


def test_reject_append_to_invalid_existing_chain() -> None:
    """Validate that append cannot bypass an invalid or corrupt existing chain."""
    trial_id = "CAMP-001:RUN-001:ARM-B:CKPT-001"
    t0 = datetime(2026, 10, 18, 20, 0, 0, tzinfo=UTC)

    ev0 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref0",
        payload_hash="a" * 64,
    )

    # Corrupt chain with forged hash
    corrupt_ev0 = replace(ev0, event_hash="9" * 64)
    corrupt_chain = (corrupt_ev0,)

    ev1 = build_stage1_trial_event(
        trial_id=trial_id,
        event_index=1,
        previous_event_reference="9" * 64,
        event_kind="INPUTS_BOUND",
        recorded_at=t0,
        producer_evidence_references=[],
        payload_reference="ref1",
        payload_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="event_hash mismatch"):
        append_stage1_trial_event(events=corrupt_chain, event=ev1)

    # Replay corrupt_ev0 also fails: chain validated before replay check
    with pytest.raises(ValueError, match="event_hash mismatch"):
        append_stage1_trial_event(events=corrupt_chain, event=corrupt_ev0)
