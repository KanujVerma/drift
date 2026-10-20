"""Cross-layer Level 0 Stage 1 B/R smoke, not a broker, RESULT or G3 test.

All provenance and coverage records are synthetic structural evidence only.
The separate numeric oracles are caller-provided, not produced from events.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

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
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_checkpoint_coverage import (
    Stage1CheckpointCoverageAuditV1,
    Stage1CoverageCountsV1,
    Stage1RunCheckpointDeclarationV1,
    build_stage1_checkpoint_coverage_audit,
    verify_stage1_checkpoint_coverage_audit,
)
from drift.experiments.stage1_metric_math import (
    REASON_MISSING_OPERATING_COST,
    REASON_MISSING_VALUATION_MARK,
    calculate_comparative_economic_advantage,
    calculate_economic_gain,
    calculate_paired_return_differences,
    calculate_terminal_return,
)
from drift.experiments.stage1_trial_events import build_stage1_trial_event
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    build_stage1_trial_provenance_snapshot,
)

# Existing independent E1 and canonical event hash witnesses.
CAMPAIGN_HASH = "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4"
ROOT_EVENT_HASH = "2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4"
RUNS = ["RUN-001", "RUN-002"]
CKPTS = ("CKPT-001", "CKPT-002", "CKPT-003")


def _arm_b() -> ArmSpecV1:
    return build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role="PRIMARY_TEST",
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-B",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference="fixture://matured-own-arm-v1",
        model_configuration_reference="fixture://model-B-v1",
        deterministic_seed_reference="fixture://seed-B-001",
        frozen_configuration_reference="b" * 64,
    )


def _arm_r() -> ArmSpecV1:
    return build_arm_spec(
        arm_id="ARM-R",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="DETERMINISTIC_COMPARATOR",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role="COMPARATOR",
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-R",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference="fixture://matured-own-arm-v1",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-R-001",
        frozen_configuration_reference="b" * 64,
    )


def _campaign(
    arms: list[ArmSpecV1],
    *,
    test_arm_id: str = "ARM-B",
    comparator_arm_id: str = "ARM-R",
) -> CampaignSpecV1:
    controls = [
        a.arm_id for a in arms if a.arm_id not in {test_arm_id, comparator_arm_id}
    ]
    return build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1(
            test_arm_id=test_arm_id,
            comparator_arm_id=comparator_arm_id,
        ),
        control_arm_references=controls,
        arm_spec_references=[a.arm_spec_fingerprint for a in arms],
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
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={
            "synthetic_fixture_only": True,
            "reviewer_receipts": [],
        },
    )


def _fixture(
    runs: list[str] | None = None,
    arms: list[ArmSpecV1] | None = None,
) -> tuple[CampaignSpecV1, list[ArmSpecV1], list[RunAccountBindingV1], list[str]]:
    actual_runs = list(RUNS if runs is None else runs)
    actual_arms = [_arm_b(), _arm_r()] if arms is None else arms
    campaign = _campaign(actual_arms)
    bindings = [
        build_run_account_binding(
            campaign_id=campaign.campaign_id,
            run_id=run,
            arm_id=arm.arm_id,
            portfolio_account_id=f"SYNTH-ACC-{arm.arm_id[-1]}-{run[-3:]}",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        )
        for run in actual_runs
        for arm in actual_arms
    ]
    return campaign, actual_arms, bindings, actual_runs


def _decls(
    runs: list[str] | None = None,
    checkpoint_ids: tuple[str, ...] = CKPTS,
) -> list[Stage1RunCheckpointDeclarationV1]:
    return [
        Stage1RunCheckpointDeclarationV1(run_id=r, checkpoint_ids=checkpoint_ids)
        for r in (RUNS if runs is None else runs)
    ]


def _snapshot(
    campaign: CampaignSpecV1,
    arms: list[ArmSpecV1],
    bindings: list[RunAccountBindingV1],
    runs: list[str],
    arm_id: str,
    *,
    checkpoint_id: str = "CKPT-001",
    run_id: str = "RUN-001",
    recorded: bool = False,
) -> Stage1TrialProvenanceSnapshotV1:
    trial_id = f"{campaign.campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"
    events = (
        [
            build_stage1_trial_event(
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
        ]
        if recorded
        else []
    )
    return build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
        run_id=run_id,
        arm_id=arm_id,
        checkpoint_id=checkpoint_id,
        events=events,
    )


def _build(
    campaign: CampaignSpecV1,
    arms: list[ArmSpecV1],
    bindings: list[RunAccountBindingV1],
    runs: list[str],
    declarations: list[Stage1RunCheckpointDeclarationV1],
    snapshots: list[Stage1TrialProvenanceSnapshotV1] | None = None,
) -> Stage1CheckpointCoverageAuditV1:
    return build_stage1_checkpoint_coverage_audit(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
        checkpoint_declarations=declarations,
        submitted_snapshots=[] if snapshots is None else snapshots,
    )


def _verify(
    audit: Stage1CheckpointCoverageAuditV1,
    fixture: tuple[
        CampaignSpecV1, list[ArmSpecV1], list[RunAccountBindingV1], list[str]
    ],
) -> bool:
    campaign, arms, bindings, runs = fixture
    return verify_stage1_checkpoint_coverage_audit(
        audit=audit,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
    )



def test_level0_positive_then_remove_submitted_b_snapshot() -> None:
    fixture = _fixture(runs=["RUN-001"])
    camp, arms, bindings, runs = fixture
    assert camp.campaign_spec_fingerprint == CAMPAIGN_HASH
    assert verify_stage1_synthetic_br_configuration(
        campaign=camp,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
    )
    assert bindings[0].portfolio_account_id != bindings[1].portfolio_account_id
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", recorded=True)
    r = _snapshot(camp, arms, bindings, runs, "ARM-R", recorded=False)
    assert b.event_envelopes[0].event_hash == ROOT_EVENT_HASH
    assert b.scope.run_account_binding.portfolio_account_id == "SYNTH-ACC-B-001"
    assert r.scope.run_account_binding.portfolio_account_id == "SYNTH-ACC-R-001"
    assert (
        b.scope.complete_manifest_fingerprint
        == r.scope.complete_manifest_fingerprint
    )
    declarations = _decls(runs=runs, checkpoint_ids=("CKPT-001",))
    positive = _build(*fixture, declarations, snapshots=[b, r])
    assert positive.counts == Stage1CoverageCountsV1(2, 0, 1, 1, 2, 1, 1)
    assert [(s.arm_id, s.coverage_state) for s in positive.slots] == [
        ("ARM-B", "EVENTS_RECORDED"),
        ("ARM-R", "UNOBSERVED"),
    ]
    assert positive.pairs[0].pair_state == "BOTH_SUBMITTED"
    assert _verify(positive, fixture)
    assert (
        positive.audit_fingerprint
        == _build(*fixture, declarations, snapshots=[r, b]).audit_fingerprint
    )

    removed = _build(*fixture, declarations, snapshots=[r])
    assert removed.counts == Stage1CoverageCountsV1(2, 1, 1, 0, 1, 1, 0)
    assert removed.slots[0].coverage_state == "MISSING_SNAPSHOT"
    assert removed.slots[0].provenance_snapshot is None
    assert removed.slots[1].coverage_state == "UNOBSERVED"
    assert removed.slots[1].provenance_snapshot is not None
    assert removed.pairs[0].pair_state == "TEST_MISSING"
    assert removed.audit_fingerprint != positive.audit_fingerprint
    assert (
        removed.checkpoint_manifest_fingerprint
        == positive.checkpoint_manifest_fingerprint
    )
    assert positive.slots[0].provenance_snapshot is not None
    assert positive.pairs[0].pair_state == "BOTH_SUBMITTED"
    assert _verify(removed, fixture)


def test_wrong_account_manifest_is_rejected_before_audit_consumption() -> None:
    fixture = _fixture(runs=["RUN-001"])
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", recorded=True)
    r = _snapshot(camp, arms, bindings, runs, "ARM-R", recorded=False)
    declarations = _decls(runs=runs, checkpoint_ids=("CKPT-001",))
    valid = _build(*fixture, declarations, snapshots=[b, r])
    conflicting = [
        bindings[0],
        replace(
            bindings[1],
            portfolio_account_id=bindings[0].portfolio_account_id,
        ),
    ]
    with pytest.raises(ValueError, match="reused across bindings"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=arms,
            bindings=conflicting,
            expected_run_ids=runs,
        )
    with pytest.raises(ValueError, match="reused across bindings"):
        _build(camp, arms, conflicting, runs, declarations, [b, r])
    with pytest.raises(ValueError, match="reused across bindings"):
        verify_stage1_checkpoint_coverage_audit(
            audit=valid,
            campaign=camp,
            arms=arms,
            bindings=conflicting,
            expected_run_ids=runs,
        )
    assert bindings[0].portfolio_account_id == "SYNTH-ACC-B-001"
    assert bindings[1].portfolio_account_id == "SYNTH-ACC-R-001"
    assert valid.pairs[0].pair_state == "BOTH_SUBMITTED"


def test_pure_mock_br_oracles_include_unknown_costs_and_losing_ai() -> None:
    # No account/result producer is authenticated by this numeric-only test.
    start = Decimal("10000")
    b_return = calculate_terminal_return((start, Decimal("10120")))
    r_return = calculate_terminal_return((start, Decimal("10060")))
    assert (b_return.state, b_return.value) == ("KNOWN", Decimal("0.012"))
    assert (r_return.state, r_return.value) == ("KNOWN", Decimal("0.006"))
    diff = calculate_paired_return_differences(
        b_returns=(b_return,),
        r_returns=(r_return,),
    )
    assert len(diff) == 1
    assert (diff[0].state, diff[0].value) == ("KNOWN", Decimal("0.006"))

    b_gain = calculate_economic_gain(
        initial_net_nav=start,
        terminal_net_nav=Decimal("10120"),
        attributed_operating_cost=Decimal("25"),
    )
    r_gain = calculate_economic_gain(
        initial_net_nav=start,
        terminal_net_nav=Decimal("10060"),
        attributed_operating_cost=Decimal("5"),
    )
    assert (b_gain.state, b_gain.value) == ("KNOWN", Decimal("95"))
    assert (r_gain.state, r_gain.value) == ("KNOWN", Decimal("55"))
    advantage = calculate_comparative_economic_advantage(b_gain, r_gain)
    assert (advantage.state, advantage.value) == ("KNOWN", Decimal("40"))

    unknown = calculate_economic_gain(
        initial_net_nav=start,
        terminal_net_nav=Decimal("10120"),
        attributed_operating_cost=None,
    )
    assert (unknown.state, unknown.value) == ("UNAVAILABLE", None)
    assert unknown.reason_code == REASON_MISSING_OPERATING_COST
    assert b_return.value == Decimal("0.012")
    assert calculate_terminal_return((start, None)).reason_code == (
        REASON_MISSING_VALUATION_MARK
    )

    losing_return = calculate_terminal_return((start, Decimal("9980")))
    losing_gain = calculate_economic_gain(
        initial_net_nav=start,
        terminal_net_nav=Decimal("9980"),
        attributed_operating_cost=Decimal("25"),
    )
    assert (losing_return.state, losing_return.value) == (
        "KNOWN",
        Decimal("-0.002"),
    )
    assert (losing_gain.state, losing_gain.value) == ("KNOWN", Decimal("-45"))
    losing_adv = calculate_comparative_economic_advantage(losing_gain, r_gain)
    assert (losing_adv.state, losing_adv.value) == ("KNOWN", Decimal("-100"))
