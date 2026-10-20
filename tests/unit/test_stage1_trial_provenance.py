from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    DataWindowV1,
    DecisionScheduleV1,
    PrimaryComparisonV1,
    RunAccountBindingV1,
    ScoringWindowV1,
    SessionWindowV1,
    build_arm_spec,
    build_campaign_spec,
    build_run_account_binding,
    verify_experiment_configuration,
)
from drift.experiments.stage1_trial_events import (
    Stage1TrialEvent,
    build_stage1_trial_event,
)
from drift.experiments.stage1_trial_provenance import (
    PROVENANCE_SCHEMA_VERSION,
    Stage1TrialProvenanceSnapshotV1,
    _complete_manifest_fingerprint,
    _provenance_preimage,
    append_stage1_trial_provenance_event,
    build_stage1_trial_provenance_snapshot,
    verify_stage1_trial_provenance_snapshot,
)

GOLDEN_ARM_B_HASH = "84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831"
GOLDEN_ARM_R_HASH = "c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd"
GOLDEN_CAMPAIGN_HASH = (
    "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4"
)
GOLDEN_MANIFEST_HASH = (
    "57a000a61c2cb64a64239d2e52249bbe1ddffe01fbaa2772cd03e162b5a50a29"
)
GOLDEN_ZERO_EVENT_SNAPSHOT_HASH = (
    "09593b447f4c7a49fba0bd143ac5cd217a5d0cb5add50dd66bfeb7d682c990a7"
)
GOLDEN_ROOT_EVENT_HASH = (
    "2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4"
)
GOLDEN_ONE_EVENT_SNAPSHOT_HASH = (
    "833de9527e2ced32ec2f2f80620bd071b2b9b8c2c06dcd5bbb072e60df9582b2"
)


class ImpostorString(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def make_golden_arm_b(
    *,
    arm_account_role: str = "PRIMARY_TEST",
    model_configuration_reference: str = "fixture://model-B-v1",
) -> ArmSpecV1:
    return build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role=arm_account_role,
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-B",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference="fixture://matured-own-arm-v1",
        model_configuration_reference=model_configuration_reference,
        deterministic_seed_reference="fixture://seed-B-001",
        frozen_configuration_reference="b" * 64,
    )


def make_golden_arm_r(
    *,
    arm_account_role: str = "COMPARATOR",
    feedback_policy_reference: str = "fixture://matured-own-arm-v1",
    model_configuration_reference: str = "NONE",
) -> ArmSpecV1:
    return build_arm_spec(
        arm_id="ARM-R",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="DETERMINISTIC_COMPARATOR",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role=arm_account_role,
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-R",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference=feedback_policy_reference,
        model_configuration_reference=model_configuration_reference,
        deterministic_seed_reference="fixture://seed-R-001",
        frozen_configuration_reference="b" * 64,
    )


def make_golden_campaign(
    arm_b_hash: str = GOLDEN_ARM_B_HASH,
    arm_r_hash: str = GOLDEN_ARM_R_HASH,
    *,
    portfolio_mandate_reference: str = "fixture://balanced-mandate-v1",
    execution_policy_reference: str = "fixture://next-open-v1",
    model_and_prompt_policy_reference: str = "fixture://model-B-v1",
) -> CampaignSpecV1:
    return build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1(
            test_arm_id="ARM-B",
            comparator_arm_id="ARM-R",
        ),
        control_arm_references=[],
        arm_spec_references=[arm_b_hash, arm_r_hash],
        qualified_dataset_references=[],
        data_window=DataWindowV1(
            start_date="2024-01-02",
            end_date="2026-01-30",
            calendar_id="fixture://calendar-v1",
        ),
        warmup_window=SessionWindowV1(sessions_count=253),
        observation_window=SessionWindowV1(sessions_count=126),
        scoring_window=ScoringWindowV1(
            start_session="SC-001",
            end_session="SC-021",
            fresh_accounts=True,
        ),
        decision_schedule=DecisionScheduleV1(
            frequency="MONTHLY",
            alignment="LAST_COMPLETED_SESSION",
            execution_timing="NEXT_OPEN",
        ),
        allowed_strategy_families=["B3", "B4", "B5"],
        portfolio_mandate_reference=portfolio_mandate_reference,
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference=execution_policy_reference,
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference=model_and_prompt_policy_reference,
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={
            "synthetic_fixture_only": True,
            "reviewer_receipts": [],
        },
    )


def make_golden_bindings() -> list[RunAccountBindingV1]:
    return [
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-001",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-001",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-001",
            arm_id="ARM-R",
            portfolio_account_id="SYNTH-ACC-R-001",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
    ]


def make_golden_root_event(
    *, trial_id: str = "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001"
) -> Stage1TrialEvent:
    return build_stage1_trial_event(
        trial_id=trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC),
        producer_evidence_references=["a" * 64, "f" * 64],
        payload_reference="fixture://local-provenance-payload-001",
        payload_hash=(
            "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
        ),
    )


def make_two_run_fixture() -> tuple[
    CampaignSpecV1,
    list[ArmSpecV1],
    list[RunAccountBindingV1],
    list[str],
]:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    expected_runs = ["RUN-001", "RUN-002"]
    b1_b = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b1_r = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-R",
        portfolio_account_id="SYNTH-ACC-R-001",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b2_b = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-002",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-002",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b2_r = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-002",
        arm_id="ARM-R",
        portfolio_account_id="SYNTH-ACC-R-002",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    bindings = [b1_b, b1_r, b2_b, b2_r]
    return camp, arms, bindings, expected_runs


# ==============================================================================
# Positive Tests P01 - P12
# ==============================================================================


def test_p01_empty_declared_checkpoint_golden_hash() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    assert snapshot.schema_version == PROVENANCE_SCHEMA_VERSION
    assert snapshot.observation_state == "UNOBSERVED"
    assert snapshot.event_count == 0
    assert snapshot.chain_head_event_hash is None
    assert snapshot.event_envelopes == ()

    scope = snapshot.scope
    assert scope.campaign_id == "CAMP-E1-SYNTH-001"
    assert scope.run_id == "RUN-001"
    assert scope.arm_id == "ARM-B"
    assert scope.checkpoint_id == "CKPT-001"
    assert scope.trial_id == "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001"
    assert scope.campaign_spec_fingerprint == GOLDEN_CAMPAIGN_HASH
    assert scope.arm_spec_fingerprint == GOLDEN_ARM_B_HASH
    assert scope.complete_manifest_fingerprint == GOLDEN_MANIFEST_HASH

    assert snapshot.snapshot_fingerprint == GOLDEN_ZERO_EVENT_SNAPSHOT_HASH
    assert (
        verify_stage1_trial_provenance_snapshot(
            snapshot=snapshot,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )
        is True
    )


def test_p02_single_root_event_golden_hashes() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    root_ev = make_golden_root_event()
    assert root_ev.event_hash == GOLDEN_ROOT_EVENT_HASH

    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[root_ev],
    )

    assert snapshot.observation_state == "EVENTS_RECORDED"
    assert snapshot.event_count == 1
    assert snapshot.chain_head_event_hash == GOLDEN_ROOT_EVENT_HASH
    assert len(snapshot.event_envelopes) == 1
    assert snapshot.event_envelopes[0].event_hash == GOLDEN_ROOT_EVENT_HASH
    assert snapshot.snapshot_fingerprint == GOLDEN_ONE_EVENT_SNAPSHOT_HASH
    assert (
        verify_stage1_trial_provenance_snapshot(
            snapshot=snapshot,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )
        is True
    )


def test_p03_deterministic_identical_builds() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]
    ev = make_golden_root_event()

    s1 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev],
    )
    s2 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev],
    )

    assert s1 == s2
    assert s1.snapshot_fingerprint == s2.snapshot_fingerprint
    assert _provenance_preimage(s1) == _provenance_preimage(s2)


def test_p04_equivalent_timezones_identical_hash() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev_utc = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC),
        producer_evidence_references=["a" * 64, "f" * 64],
        payload_reference="fixture://local-provenance-payload-001",
        payload_hash=(
            "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
        ),
    )

    ev_tz0 = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=timezone(timedelta(0))),
        producer_evidence_references=["a" * 64, "f" * 64],
        payload_reference="fixture://local-provenance-payload-001",
        payload_hash=(
            "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
        ),
    )

    assert ev_utc.event_hash == ev_tz0.event_hash

    s_utc = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev_utc],
    )
    s_tz0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev_tz0],
    )

    assert s_utc.snapshot_fingerprint == s_tz0.snapshot_fingerprint


def test_p05_append_second_event_creates_new_snapshot_preserves_old() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )
    old_fingerprint = s0.snapshot_fingerprint

    ev1 = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="ELIGIBILITY_RECORDED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 4, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://signal-payload-001",
        payload_hash="c" * 64,
    )

    s1 = append_stage1_trial_provenance_event(
        snapshot=s0,
        event=ev1,
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
    )

    assert s0.snapshot_fingerprint == old_fingerprint
    assert s0.event_count == 1
    assert s1.event_count == 2
    assert s1.chain_head_event_hash == ev1.event_hash
    assert s1.snapshot_fingerprint != old_fingerprint
    assert (
        verify_stage1_trial_provenance_snapshot(
            snapshot=s1,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )
        is True
    )


def test_p06_idempotent_duplicate_replay() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    s_replay = append_stage1_trial_provenance_event(
        snapshot=s0,
        event=ev0,
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
    )

    assert s_replay is s0
    assert s_replay.snapshot_fingerprint == s0.snapshot_fingerprint


def test_p07_caller_event_list_mutation_isolation() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    caller_list = [ev0]

    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=caller_list,
    )

    caller_list.clear()
    assert snapshot.event_count == 1
    assert len(snapshot.event_envelopes) == 1
    assert snapshot.event_envelopes[0].event_hash == ev0.event_hash


def test_p08_caller_leaf_instance_tampering_isolation() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    # Attempt to tamper caller event and caller binding via object.__setattr__
    object.__setattr__(ev0, "event_hash", "0" * 64)
    object.__setattr__(bindings[0], "portfolio_account_id", "MALICIOUS-ACC")

    assert snapshot.event_envelopes[0].event_hash == GOLDEN_ROOT_EVENT_HASH
    assert snapshot.scope.run_account_binding.portfolio_account_id == "SYNTH-ACC-B-001"
    assert snapshot.snapshot_fingerprint == GOLDEN_ONE_EVENT_SNAPSHOT_HASH


def test_p09_changed_legitimate_arm_or_checkpoint_changes_hash() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s_b_ckpt1 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    s_b_ckpt2 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-002",
        events=[],
    )

    s_r_ckpt1 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-R",
        checkpoint_id="CKPT-001",
        events=[],
    )

    assert s_b_ckpt1.snapshot_fingerprint != s_b_ckpt2.snapshot_fingerprint
    assert s_b_ckpt1.snapshot_fingerprint != s_r_ckpt1.snapshot_fingerprint


def test_p10_full_ordered_event_envelopes_retained_and_readable() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    ev1 = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="ELIGIBILITY_RECORDED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 4, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://signal-payload-001",
        payload_hash="c" * 64,
    )

    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0, ev1],
    )

    # Simulated consumer reading envelope fields
    kinds = [e.event_kind for e in snapshot.event_envelopes]
    hashes = [e.event_hash for e in snapshot.event_envelopes]
    assert kinds == ["OPPORTUNITY_CREATED", "ELIGIBILITY_RECORDED"]
    assert hashes == [ev0.event_hash, ev1.event_hash]


def test_p11_result_bound_or_finalized_remains_structural_events_recorded() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    ev1 = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=1,
        previous_event_reference=ev0.event_hash,
        event_kind="RESULT_BOUND",
        recorded_at=datetime(2026, 10, 19, 0, 0, 4, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://result-payload-001",
        payload_hash="d" * 64,
    )
    ev2 = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=2,
        previous_event_reference=ev1.event_hash,
        event_kind="TRIAL_FINALIZED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 5, tzinfo=UTC),
        producer_evidence_references=["e" * 64],
        payload_reference="fixture://finalized-payload-001",
        payload_hash="f" * 64,
    )

    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0, ev1, ev2],
    )

    assert snapshot.observation_state == "EVENTS_RECORDED"
    assert snapshot.event_count == 3
    assert not hasattr(snapshot, "result")
    assert not hasattr(snapshot, "financial_status")


def test_p12_complete_two_run_manifest_order_invariance() -> None:
    camp, arms, bindings, expected_runs = make_two_run_fixture()

    # Reordered inputs
    reordered_runs = ["RUN-002", "RUN-001"]
    reordered_arms = [arms[1], arms[0]]
    reordered_bindings = [bindings[3], bindings[0], bindings[2], bindings[1]]

    h1 = _complete_manifest_fingerprint(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
    )
    h2 = _complete_manifest_fingerprint(
        campaign=camp,
        arms=reordered_arms,
        bindings=reordered_bindings,
        expected_run_ids=reordered_runs,
    )

    assert h1 == h2

    s1 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )
    s2 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=reordered_arms,
        bindings=reordered_bindings,
        expected_run_ids=reordered_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    assert s1.snapshot_fingerprint == s2.snapshot_fingerprint


# ==============================================================================
# Negative and Adversarial Tests N01 - N13
# ==============================================================================


@pytest.mark.parametrize(
    "bad_ckpt",
    [
        "",
        " ",
        "CKPT:001",
        "CKPT 001",
        "CKPT/001",
        " CKPT-001",
        "CKPT-001 ",
        ImpostorString("CKPT-001"),
    ],
)
def test_n01_invalid_checkpoint_id(bad_ckpt: Any) -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    with pytest.raises(ValueError, match="checkpoint_id"):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id=bad_ckpt,
            events=[],
        )


def test_n02_manifest_mismatch_missing_or_extra_binding() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()

    # expected_run_ids has RUN-002 declared but no bindings for RUN-002
    with pytest.raises(ValueError):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=["RUN-001", "RUN-002"],
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id="CKPT-001",
            events=[],
        )


def test_n03_stale_fingerprint_mismatch() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    tampered_scope = replace(
        s0.scope,
        campaign_spec_fingerprint="0" * 64,
    )
    tampered_snapshot = replace(s0, scope=tampered_scope)

    with pytest.raises(ValueError, match="campaign_spec_fingerprint"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=tampered_snapshot,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_n04_forged_binding_fields_in_stored_snapshot() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    forged_binding = replace(
        s0.scope.run_account_binding,
        portfolio_account_id="FORGED-ACCOUNT",
    )
    tampered_scope = replace(s0.scope, run_account_binding=forged_binding)
    tampered_snapshot = replace(s0, scope=tampered_scope)

    with pytest.raises(ValueError, match="portfolio_account_id"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=tampered_snapshot,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_n05_nonempty_events_broken_chain() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    root = make_golden_root_event()
    # Tamper root event index to 1 to produce a broken chain
    bad_chain_event = replace(root, event_index=1)

    with pytest.raises(ValueError):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id="CKPT-001",
            events=[bad_chain_event],
        )


def test_n06_stored_snapshot_count_state_head_disagreements() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    # 1. Empty events labelled EVENTS_RECORDED
    t1 = replace(s0, observation_state="EVENTS_RECORDED")
    with pytest.raises(ValueError, match="observation_state"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t1,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # 2. Empty events with non-null head
    t2 = replace(s0, chain_head_event_hash="a" * 64)
    with pytest.raises(ValueError, match="chain_head_event_hash"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t2,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # 3. Empty events with wrong count
    t3 = replace(s0, event_count=1)
    with pytest.raises(ValueError, match="event_count"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t3,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_n07_tampered_fingerprint_or_mutable_list_injected() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    # Forged snapshot fingerprint
    t1 = replace(s0, snapshot_fingerprint="f" * 64)
    with pytest.raises(ValueError, match="snapshot_fingerprint"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t1,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # Injected mutable list instead of tuple
    t2 = replace(s0, event_envelopes=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="event_envelopes"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t2,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_n08_invalid_untyped_collections_or_bool_count() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    # String passed as events
    with pytest.raises(ValueError, match="events"):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id="CKPT-001",
            events="not-a-sequence",  # type: ignore[arg-type]
        )

    # Mapping passed as events
    with pytest.raises(ValueError, match="events"):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id="CKPT-001",
            events={"a": 1},  # type: ignore[arg-type]
        )

    # Boolean passed as event_count in stored snapshot
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )
    t_bool = replace(s0, event_count=True)
    with pytest.raises(ValueError, match="event_count"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t_bool,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_n09_replay_root_event_into_different_trial_rejected() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    # Root event created for CKPT-001
    ev_ckpt1 = make_golden_root_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001"
    )

    # Attempt to build CKPT-002 using CKPT-001's root event
    with pytest.raises(ValueError):
        build_stage1_trial_provenance_snapshot(
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
            run_id="RUN-001",
            arm_id="ARM-B",
            checkpoint_id="CKPT-002",
            events=[ev_ckpt1],
        )


def test_n10_missing_payload_remains_structural_only() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    # Prove snapshot does not assert or verify unseen payload contents
    assert snapshot.event_envelopes[0].payload_hash is not None
    assert snapshot.observation_state == "EVENTS_RECORDED"
    # No promotion to producer_verified or authenticated
    assert not hasattr(snapshot, "producer_verified")


def test_n11_object_originals_remain_unchanged_after_refusals() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    # Try appending invalid event (wrong parent)
    bad_ev = build_stage1_trial_event(
        trial_id="CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
        event_index=1,
        previous_event_reference="0" * 64,
        event_kind="ELIGIBILITY_RECORDED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 4, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://signal-payload-001",
        payload_hash="c" * 64,
    )

    with pytest.raises(ValueError):
        append_stage1_trial_provenance_event(
            snapshot=s0,
            event=bad_ev,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # s0 must be completely intact
    assert s0.event_count == 1
    assert s0.chain_head_event_hash == ev0.event_hash
    assert s0.snapshot_fingerprint == GOLDEN_ONE_EVENT_SNAPSHOT_HASH


def test_n12_read_only_consumer_isolation() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    snapshot = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    # Read attributes through frozen dataclass
    assert snapshot.scope.trial_id == "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001"

    with pytest.raises(AttributeError):
        snapshot.observation_state = "TAMPERED"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        snapshot.scope.run_id = "TAMPERED"  # type: ignore[misc]


def test_n13_exact_manifest_binding_regression_subset_refusal() -> None:
    # 1. Build from two-run complete manifest
    camp, arms, two_run_bindings, two_runs = make_two_run_fixture()

    s_two_run = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=two_run_bindings,
        expected_run_ids=two_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    # 2. Try to verify using only the single-run valid subset
    single_run_bindings = two_run_bindings[:2]
    single_run = ["RUN-001"]

    # Confirm single-run subset passes E1 verification on its own
    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=arms,
            bindings=single_run_bindings,
            expected_run_ids=single_run,
        )
        is True
    )

    # Must raise ValueError when verifying s_two_run due to manifest mismatch
    with pytest.raises(ValueError, match="complete_manifest_fingerprint"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=s_two_run,
            campaign=camp,
            arms=arms,
            bindings=single_run_bindings,
            expected_run_ids=single_run,
        )

    # Must raise ValueError when appending to s_two_run with one-run subset
    ev0 = make_golden_root_event()
    with pytest.raises(ValueError, match="complete_manifest_fingerprint"):
        append_stage1_trial_provenance_event(
            snapshot=s_two_run,
            event=ev0,
            campaign=camp,
            arms=arms,
            bindings=single_run_bindings,
            expected_run_ids=single_run,
        )


def test_impostor_string_rejections() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[],
    )

    # Impostor schema_version
    t_schema = replace(s0, schema_version=ImpostorString(PROVENANCE_SCHEMA_VERSION))
    with pytest.raises(ValueError, match="schema_version"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t_schema,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # Impostor observation_state
    t_state = replace(s0, observation_state=ImpostorString("UNOBSERVED"))
    with pytest.raises(ValueError, match="observation_state"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t_state,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    # Impostor scope fields
    t_scope_camp = replace(
        s0,
        scope=replace(
            s0.scope,
            campaign_id=ImpostorString("CAMP-E1-SYNTH-001"),
        ),
    )
    with pytest.raises(ValueError, match="scope.campaign_id"):
        verify_stage1_trial_provenance_snapshot(
            snapshot=t_scope_camp,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


class ImpostorTrialEvent(Stage1TrialEvent):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = Stage1TrialEvent.__hash__


def make_impostor_event(event: Stage1TrialEvent) -> ImpostorTrialEvent:
    kwargs = {f.name: getattr(event, f.name) for f in fields(Stage1TrialEvent)}
    return ImpostorTrialEvent(**kwargs)


def test_regression_append_conflicting_subclass_event_rejected() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )
    old_fingerprint = s0.snapshot_fingerprint

    ev_diff = build_stage1_trial_event(
        trial_id=ev0.trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://diff-payload-002",
        payload_hash="e" * 64,
    )
    assert ev_diff.event_hash != ev0.event_hash
    assert ev_diff.event_id == ev0.event_id

    impostor = make_impostor_event(ev_diff)
    assert impostor == ev0

    with pytest.raises(
        ValueError, match="event must be an exact Stage1TrialEvent instance"
    ):
        append_stage1_trial_provenance_event(
            snapshot=s0,
            event=impostor,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )

    assert s0.snapshot_fingerprint == old_fingerprint
    assert s0.event_count == 1
    assert s0.event_envelopes[0].event_hash == ev0.event_hash


def test_regression_append_identical_subclass_event_rejected() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    impostor_same = make_impostor_event(ev0)

    with pytest.raises(
        ValueError, match="event must be an exact Stage1TrialEvent instance"
    ):
        append_stage1_trial_provenance_event(
            snapshot=s0,
            event=impostor_same,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


def test_append_valid_ordinary_replay_and_conflict_rejection() -> None:
    camp = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    expected_runs = ["RUN-001"]

    ev0 = make_golden_root_event()
    s0 = build_stage1_trial_provenance_snapshot(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=[ev0],
    )

    # 1. Valid ordinary replay returns the exact original snapshot object
    s_replay = append_stage1_trial_provenance_event(
        snapshot=s0,
        event=ev0,
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_runs,
    )
    assert s_replay is s0

    # 2. Different valid base-type event with existing event ID raises ValueError
    ev_conflict = build_stage1_trial_event(
        trial_id=ev0.trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://diff-payload-002",
        payload_hash="e" * 64,
    )
    with pytest.raises(ValueError):
        append_stage1_trial_provenance_event(
            snapshot=s0,
            event=ev_conflict,
            campaign=camp,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_runs,
        )


# ---------------------------------------------------------------------------
# Issue #503: one captured event view, not caller-controlled length/iterator
# ---------------------------------------------------------------------------


class _MisleadingLengthEvents(list[Stage1TrialEvent]):
    def __init__(self, values: list[Stage1TrialEvent], reported_size: int) -> None:
        super().__init__(values)
        self.reported_size = reported_size

    def __len__(self) -> int:
        return self.reported_size


class _ChangingIterationEvents(list[Stage1TrialEvent]):
    def __init__(
        self,
        first: Sequence[Stage1TrialEvent],
        later: Sequence[Stage1TrialEvent],
    ) -> None:
        super().__init__(first)
        self.first = tuple(first)
        self.later = tuple(later)
        self.read_count = 0

    def __iter__(self) -> Iterator[Stage1TrialEvent]:
        self.read_count += 1
        return iter(self.first if self.read_count == 1 else self.later)


def _snapshot_from_caller_events(
    events: Sequence[Stage1TrialEvent],
) -> Stage1TrialProvenanceSnapshotV1:
    return build_stage1_trial_provenance_snapshot(
        campaign=make_golden_campaign(),
        arms=[make_golden_arm_b(), make_golden_arm_r()],
        bindings=make_golden_bindings(),
        expected_run_ids=["RUN-001"],
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-001",
        events=events,
    )


def test_provenance_does_not_erase_real_event_on_false_empty_length() -> None:
    root = make_golden_root_event()
    supplied = _MisleadingLengthEvents([root], reported_size=0)
    assert len(supplied) == 0
    assert tuple(supplied) == (root,)

    snapshot = _snapshot_from_caller_events(supplied)
    assert snapshot.observation_state == "EVENTS_RECORDED"
    assert snapshot.event_count == 1
    assert snapshot.event_envelopes[0].event_hash == GOLDEN_ROOT_EVENT_HASH
    assert snapshot.chain_head_event_hash == GOLDEN_ROOT_EVENT_HASH
    assert snapshot.snapshot_fingerprint == GOLDEN_ONE_EVENT_SNAPSHOT_HASH
    assert tuple(supplied) == (root,)


def test_provenance_actual_empty_view_stays_unobserved_despite_length() -> None:
    supplied = _MisleadingLengthEvents([], reported_size=1)
    assert len(supplied) == 1
    assert tuple(supplied) == ()

    snapshot = _snapshot_from_caller_events(supplied)
    assert snapshot.observation_state == "UNOBSERVED"
    assert snapshot.event_count == 0
    assert snapshot.event_envelopes == ()
    assert snapshot.chain_head_event_hash is None
    assert snapshot.snapshot_fingerprint == GOLDEN_ZERO_EVENT_SNAPSHOT_HASH


def test_provenance_reads_mutable_iterable_once_into_stable_snapshot() -> None:
    valid_root = make_golden_root_event()
    changed_root = build_stage1_trial_event(
        trial_id=valid_root.trial_id,
        event_index=0,
        previous_event_reference="ROOT",
        event_kind="OPPORTUNITY_CREATED",
        recorded_at=datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC),
        producer_evidence_references=["b" * 64],
        payload_reference="fixture://altered-payload-002",
        payload_hash="e" * 64,
    )
    assert changed_root.event_hash != valid_root.event_hash
    supplied = _ChangingIterationEvents([valid_root], [changed_root])

    snapshot = _snapshot_from_caller_events(supplied)
    assert supplied.read_count == 1
    assert snapshot.observation_state == "EVENTS_RECORDED"
    assert snapshot.event_envelopes[0].event_hash == valid_root.event_hash
    assert snapshot.snapshot_fingerprint == GOLDEN_ONE_EVENT_SNAPSHOT_HASH


def test_provenance_refuses_invalid_events_hidden_by_false_empty_len() -> None:
    bad_item: Any = "not-a-trial-event"
    supplied = _MisleadingLengthEvents([bad_item], reported_size=0)
    assert len(supplied) == 0
    with pytest.raises(ValueError, match=r"events\[0\] must be a Stage1TrialEvent"):
        _snapshot_from_caller_events(supplied)
