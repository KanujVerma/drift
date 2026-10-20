from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from drift.experiments.stage1_campaign_config import (
    SCHEMA_VERSION,
    ArmSpecV1,
    CampaignSpecV1,
    DataWindowV1,
    DecisionScheduleV1,
    FrozenJSONArray,
    FrozenJSONMap,
    PrimaryComparisonV1,
    RunAccountBindingV1,
    ScoringWindowV1,
    SessionWindowV1,
    _arm_preimage,
    _campaign_preimage,
    _verify_frozen_json,
    build_arm_spec,
    build_campaign_spec,
    build_run_account_binding,
    verify_arm_spec,
    verify_campaign_spec,
    verify_experiment_configuration,
    verify_run_account_binding,
    verify_stage1_synthetic_br_configuration,
)
from drift.serialization.canonical import content_hash

GOLDEN_ARM_B_HASH = "84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831"
GOLDEN_ARM_R_HASH = "c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd"
GOLDEN_CAMPAIGN_HASH = (
    "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4"
)


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


# ==================================================
# POSITIVE TESTS (P01 - P12)
# ==================================================


def test_p01_arm_b_golden_hash() -> None:
    arm_b = make_golden_arm_b()
    assert arm_b.arm_spec_fingerprint == GOLDEN_ARM_B_HASH
    assert verify_arm_spec(arm=arm_b) is True


def test_p02_arm_r_golden_hash() -> None:
    arm_r = make_golden_arm_r()
    assert arm_r.arm_spec_fingerprint == GOLDEN_ARM_R_HASH
    assert verify_arm_spec(arm=arm_r) is True


def test_p03_campaign_golden_hash() -> None:
    campaign = make_golden_campaign()
    assert campaign.campaign_spec_fingerprint == GOLDEN_CAMPAIGN_HASH
    assert verify_campaign_spec(campaign=campaign) is True


def test_p04_binding_identities() -> None:
    bindings = make_golden_bindings()
    b_arm_b, b_arm_r = bindings
    assert b_arm_b.binding_id == "CAMP-E1-SYNTH-001:RUN-001:ARM-B:BINDING"
    assert b_arm_r.binding_id == "CAMP-E1-SYNTH-001:RUN-001:ARM-R:BINDING"
    assert b_arm_b.portfolio_account_id != b_arm_r.portfolio_account_id
    assert verify_run_account_binding(binding=b_arm_b) is True
    assert verify_run_account_binding(binding=b_arm_r) is True


def test_p05_complete_experiment() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    assert (
        verify_stage1_synthetic_br_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )


def test_p06_timezone_equivalence() -> None:
    est = timezone(timedelta(hours=-5))
    dt_utc = datetime(2026, 10, 19, 5, 0, 0, tzinfo=UTC)
    dt_est = datetime(2026, 10, 19, 0, 0, 0, tzinfo=est)

    binding_utc = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="10000",
        bound_at=dt_utc,
    )
    binding_est = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="10000",
        bound_at=dt_est,
    )
    assert binding_utc.bound_at == binding_est.bound_at
    assert binding_utc.bound_at == "2026-10-19T05:00:00.000000Z"


def test_p07_map_insertion_order() -> None:
    evidence_order1 = {"alpha": 1, "beta": 2, "gamma": 3}
    evidence_order2 = {"gamma": 3, "alpha": 1, "beta": 2}

    camp1 = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={"repo1": "a" * 40, "repo2": "b" * 40},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence=evidence_order1,
    )

    camp2 = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={"repo2": "b" * 40, "repo1": "a" * 40},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence=evidence_order2,
    )

    assert camp1.campaign_spec_fingerprint == camp2.campaign_spec_fingerprint


def test_p08_deep_immutability() -> None:
    mutable_evidence: dict[str, Any] = {
        "synthetic_fixture_only": True,
        "nested": {"tags": ["initial", "unmutated"]},
    }
    mutable_families = ["B3", "B4", "B5"]

    campaign = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=mutable_families,
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence=mutable_evidence,
    )
    old_hash = campaign.campaign_spec_fingerprint

    # Caller mutates their data after construction
    mutable_evidence["nested"]["tags"].append("mutated")
    mutable_evidence["extra"] = "hacked"
    mutable_families.append("B6")

    # Assert campaign object is unaffected
    assert campaign.campaign_spec_fingerprint == old_hash
    assert verify_campaign_spec(campaign=campaign) is True
    assert campaign.allowed_strategy_families == ("B3", "B4", "B5")


def test_p09_array_order() -> None:
    # Array ordering is hash-significant:
    # reordering arrays must produce different hashes
    arm1 = build_arm_spec(
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
    arm2 = build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B5", "B4"],
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
    assert arm1.arm_spec_fingerprint != arm2.arm_spec_fingerprint


def test_p10_multiple_runs() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()

    run1_bindings = make_golden_bindings()
    run2_bindings = [
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-002",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-002",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-002",
            arm_id="ARM-R",
            portfolio_account_id="SYNTH-ACC-R-002",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
    ]

    all_bindings = run1_bindings + run2_bindings
    expected_runs = ["RUN-001", "RUN-002"]

    assert (
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=all_bindings,
            expected_run_ids=expected_runs,
        )
        is True
    )
    assert (
        verify_stage1_synthetic_br_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=all_bindings,
            expected_run_ids=expected_runs,
        )
        is True
    )


def test_p11_generic_extensibility() -> None:
    # Alternative campaign with initial capital 50000 and custom strategy
    arm_a = build_arm_spec(
        arm_id="ARM-A",
        campaign_id="CAMP-GENERIC-001",
        selector_type="FROZEN_BASELINE",
        eligible_strategy_references=["STRAT-01"],
        initial_strategy_reference="STRAT-01",
        initial_capital="50000",
        currency="USD",
        arm_account_role="BASELINE",
        mandate_reference="fixture://mandate-v1",
        execution_policy_reference="fixture://exec-v1",
        research_budget_reference="fixture://budget-v1",
        information_visibility_policy="fixture://vis-v1",
        feedback_policy_reference="fixture://feedback-v1",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-001",
        frozen_configuration_reference="a" * 64,
    )
    arm_c = build_arm_spec(
        arm_id="ARM-C",
        campaign_id="CAMP-GENERIC-001",
        selector_type="PASSIVE_BENCHMARK",
        eligible_strategy_references=["BENCH-SPY"],
        initial_strategy_reference="BENCH-SPY",
        initial_capital="50000",
        currency="USD",
        arm_account_role="BENCHMARK",
        mandate_reference="fixture://mandate-v1",
        execution_policy_reference="fixture://exec-v1",
        research_budget_reference="fixture://budget-v1",
        information_visibility_policy="fixture://vis-v1",
        feedback_policy_reference="fixture://feedback-v1",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-002",
        frozen_configuration_reference="c" * 64,
    )

    campaign = build_campaign_spec(
        campaign_id="CAMP-GENERIC-001",
        campaign_type="HISTORICAL_BACKTEST",
        study_protocol_revision="fixture://proto-v1",
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-GENERIC-001",
        primary_comparison=PrimaryComparisonV1("ARM-A", "ARM-C"),
        control_arm_references=[],
        arm_spec_references=[arm_a.arm_spec_fingerprint, arm_c.arm_spec_fingerprint],
        qualified_dataset_references=["fixture://dataset-v1"],
        data_window=DataWindowV1("2020-01-01", "2023-12-31", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(100),
        observation_window=SessionWindowV1(50),
        scoring_window=ScoringWindowV1("SC-START", "SC-END", True),
        decision_schedule=DecisionScheduleV1(
            "QUARTERLY", "SESSION_CLOSE", "SAME_CLOSE"
        ),
        allowed_strategy_families=["STRAT-01", "BENCH-SPY"],
        portfolio_mandate_reference="fixture://mandate-v1",
        source_eligibility_policy_reference="fixture://source-v1",
        execution_policy_reference="fixture://exec-v1",
        cost_policy_reference="fixture://cost-v1",
        model_and_prompt_policy_reference="fixture://model-v1",
        learning_and_feedback_policy_reference="fixture://feedback-v1",
        evaluation_policy_reference="fixture://eval-v1",
        holdout_access_policy_reference="fixture://holdout-v1",
        stopping_policy_reference="fixture://stop-v1",
        authorization_evidence={"custom_key": "custom_val"},
    )

    bindings = [
        build_run_account_binding(
            campaign_id="CAMP-GENERIC-001",
            run_id="RUN-GEN-01",
            arm_id="ARM-A",
            portfolio_account_id="ACC-A-01",
            initial_cash_allocated="50000",
            bound_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
        ),
        build_run_account_binding(
            campaign_id="CAMP-GENERIC-001",
            run_id="RUN-GEN-01",
            arm_id="ARM-C",
            portfolio_account_id="ACC-C-01",
            initial_cash_allocated="50000",
            bound_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
        ),
    ]

    # Generic verifier succeeds
    assert (
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_a, arm_c],
            bindings=bindings,
            expected_run_ids=["RUN-GEN-01"],
        )
        is True
    )

    # Stage 1 specific verifier refuses it
    with pytest.raises(ValueError):
        verify_stage1_synthetic_br_configuration(
            campaign=campaign,
            arms=[arm_a, arm_c],
            bindings=bindings,
            expected_run_ids=["RUN-GEN-01"],
        )


def test_p12_synthetic_optional_collections() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=(),
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=(),
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={},
    )
    assert campaign.control_arm_references == ()
    assert campaign.qualified_dataset_references == ()
    assert campaign.accepted_contract_revisions == ()
    assert verify_campaign_spec(campaign=campaign) is True


# ==================================================
# NEGATIVE AND ADVERSARIAL TESTS (GROUPS A - G)
# ==================================================

# GROUP A: INVALID STORED OBJECTS


def test_neg_a01_wrong_schema_version() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, schema_version="drift-experiment/0-invalid")
    with pytest.raises(ValueError, match="schema_version"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a02_forged_fingerprint() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, arm_spec_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a03_changed_hashed_field_with_old_fingerprint() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, initial_capital="20000")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a04_uppercase_sha256() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, arm_spec_fingerprint=arm.arm_spec_fingerprint.upper())
    with pytest.raises(ValueError, match="arm_spec_fingerprint"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a05_wrong_length_sha256() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, arm_spec_fingerprint="a" * 63)
    with pytest.raises(ValueError, match="arm_spec_fingerprint"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a06_mutable_array_in_stored_dataclass() -> None:
    arm = make_golden_arm_b()
    bad_arm = replace(arm, eligible_strategy_references=["B3", "B4", "B5"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tuple"):
        verify_arm_spec(arm=bad_arm)


def test_neg_a07_noncanonical_immutable_mapping_keys() -> None:
    camp = make_golden_campaign()
    # Stored FrozenJSONMap with unsorted keys
    unsorted_map = FrozenJSONMap(items=(("z", 1), ("a", 2)))
    bad_camp = replace(camp, authorization_evidence=unsorted_map)
    with pytest.raises(ValueError, match="strictly sorted"):
        verify_campaign_spec(campaign=bad_camp)


def test_neg_a08_duplicate_keys_in_stored_frozen_json_map() -> None:
    camp = make_golden_campaign()
    dup_map = FrozenJSONMap(items=(("a", 1), ("a", 2)))
    bad_camp = replace(camp, authorization_evidence=dup_map)
    with pytest.raises(ValueError, match="duplicate key"):
        verify_campaign_spec(campaign=bad_camp)


def test_neg_a09_reordered_mapping_with_matching_forged_hash() -> None:
    # Even if fingerprint check is passed or bypassed,
    # noncanonical map order must fail verification
    camp = make_golden_campaign()
    unsorted_map = FrozenJSONMap(items=(("y", 1), ("x", 2)))
    bad_camp = replace(camp, authorization_evidence=unsorted_map)
    with pytest.raises(ValueError, match="strictly sorted"):
        verify_campaign_spec(campaign=bad_camp)


def test_neg_a10_wrong_nested_dataclass_type() -> None:
    camp = make_golden_campaign()
    bad_camp = replace(camp, warmup_window={"sessions_count": 253})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SessionWindowV1"):
        verify_campaign_spec(campaign=bad_camp)


def test_neg_a11_non_string_mapping_key() -> None:
    with pytest.raises(ValueError, match="mapping keys must be strings"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={123: "val"},  # type: ignore[dict-item]
        )


def test_neg_a12_cyclic_nested_authorization_input() -> None:
    cyclic_dict: dict[str, Any] = {"a": 1}
    cyclic_dict["self"] = cyclic_dict
    with pytest.raises(ValueError, match="cyclic reference"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence=cyclic_dict,
        )


def test_neg_a13_unsupported_nested_object() -> None:
    with pytest.raises(ValueError, match="unsupported JSON value type"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"set_val": {1, 2, 3}},
        )


def test_neg_a14_caller_type_confusion() -> None:
    with pytest.raises(ValueError, match="CampaignSpecV1"):
        verify_campaign_spec(campaign="not_a_campaign")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ArmSpecV1"):
        verify_arm_spec(arm={"not": "an_arm"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="RunAccountBindingV1"):
        verify_run_account_binding(binding=None)  # type: ignore[arg-type]


# GROUP B: TIMESTAMPS


def test_neg_b01_naive_datetime_input() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-001",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-001",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2),  # naive
        )


def test_neg_b02_string_passed_where_datetime_required() -> None:
    with pytest.raises(ValueError, match="timezone-aware datetime"):
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-001",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-001",
            initial_cash_allocated="10000",
            bound_at="2026-10-19T00:00:02.000000Z",  # type: ignore[arg-type]
        )


def test_neg_b03_stored_timezone_offset_rather_than_z() -> None:
    binding = make_golden_bindings()[0]
    bad_binding = replace(binding, bound_at="2026-10-19T00:00:02.000000+00:00")
    with pytest.raises(ValueError, match="canonical format"):
        verify_run_account_binding(binding=bad_binding)


def test_neg_b04_missing_fractional_precision() -> None:
    binding = make_golden_bindings()[0]
    bad_binding = replace(binding, bound_at="2026-10-19T00:00:02Z")
    with pytest.raises(ValueError, match="canonical format"):
        verify_run_account_binding(binding=bad_binding)


def test_neg_b05_three_digit_fractional_precision() -> None:
    binding = make_golden_bindings()[0]
    bad_binding = replace(binding, bound_at="2026-10-19T00:00:02.000Z")
    with pytest.raises(ValueError, match="canonical format"):
        verify_run_account_binding(binding=bad_binding)


def test_neg_b06_invalid_calendar_date() -> None:
    binding = make_golden_bindings()[0]
    bad_binding = replace(binding, bound_at="2026-02-31T00:00:02.000000Z")
    with pytest.raises(ValueError, match="invalid calendar timestamp"):
        verify_run_account_binding(binding=bad_binding)


def test_neg_b07_created_at_after_frozen_at() -> None:
    with pytest.raises(ValueError, match="created_at must be <= frozen_at"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 5, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_b08_bound_at_before_frozen_at() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()  # frozen at 2026-10-19T00:00:01.000000Z

    early_binding = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="10000",
        bound_at=datetime(
            2026, 10, 19, 0, 0, 0, tzinfo=UTC
        ),  # before campaign frozen_at
    )
    b_arm_r = make_golden_bindings()[1]

    with pytest.raises(ValueError, match="is before campaign frozen_at"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=[early_binding, b_arm_r],
            expected_run_ids=["RUN-001"],
        )


def test_neg_b09_whitespace_in_timestamp() -> None:
    binding = make_golden_bindings()[0]
    bad_binding = replace(binding, bound_at=" 2026-10-19T00:00:02.000000Z ")
    with pytest.raises(ValueError, match="canonical format"):
        verify_run_account_binding(binding=bad_binding)


# GROUP C: DECIMALTEXT REJECTIONS


@pytest.mark.parametrize(
    "bad_capital",
    [
        "10000.00",
        "00",
        "01",
        "0",
        "0.0",
        "-0",
        "-1",
        "+1",
        "1e2",
        "1.",
        ".5",
        " 10000",
        "10000 ",
        "NaN",
        "Infinity",
        10000,
        10000.0,
        True,
        False,
        None,
    ],
)
def test_neg_c_decimal_text(bad_capital: Any) -> None:
    with pytest.raises(ValueError):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3"],
            initial_strategy_reference="B3",
            initial_capital=bad_capital,
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


# GROUP D: SESSION AND WINDOW VALIDATION


def test_neg_d01_boolean_sessions_count() -> None:
    with pytest.raises(ValueError, match="integer"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(True),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_d02_floating_point_sessions_count() -> None:
    with pytest.raises(ValueError, match="integer"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253.0),  # type: ignore[arg-type]
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_d03_negative_sessions_count() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(-1),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_d04_reversed_data_window() -> None:
    with pytest.raises(ValueError, match="start_date must be <= end_date"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2026-01-30", "2024-01-02", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_d05_non_boolean_or_false_fresh_accounts() -> None:
    with pytest.raises(ValueError, match="fresh_accounts"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", False),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_d06_identical_scoring_sessions() -> None:
    with pytest.raises(ValueError, match="start_session and end_session must differ"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-001", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


# GROUP E: ARM AND CAMPAIGN IDENTITY


def test_neg_e01_invalid_scope_id_colon() -> None:
    with pytest.raises(ValueError, match="arm_id"):
        build_arm_spec(
            arm_id="ARM:B",  # colon not allowed in scope ID
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3"],
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


def test_neg_e02_duplicate_arm_ids_in_experiment() -> None:
    arm_b1 = make_golden_arm_b()
    # Another arm with same ID
    arm_b2 = replace(arm_b1, arm_account_role="SECOND_TEST")
    # recalculate fingerprint for b2
    from drift.experiments.stage1_campaign_config import _arm_preimage
    from drift.serialization.canonical import content_hash

    arm_b2 = replace(arm_b2, arm_spec_fingerprint=content_hash(_arm_preimage(arm_b2)))
    campaign = make_golden_campaign(
        arm_b1.arm_spec_fingerprint, arm_b2.arm_spec_fingerprint
    )
    bindings = make_golden_bindings()

    with pytest.raises(ValueError, match="duplicate arm ID"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b1, arm_b2],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_e03_duplicate_arm_fingerprints() -> None:
    arm_b = make_golden_arm_b()
    # 1. Builder rejects duplicate arm fingerprints in arm_spec_references
    with pytest.raises(
        ValueError, match="arm_spec_references contains duplicate values"
    ):
        make_golden_campaign(arm_b.arm_spec_fingerprint, arm_b.arm_spec_fingerprint)

    # 2. Stored campaign verifier rejects duplicate arm fingerprints
    # in arm_spec_references
    camp = make_golden_campaign()
    bad_camp = replace(
        camp,
        arm_spec_references=(arm_b.arm_spec_fingerprint, arm_b.arm_spec_fingerprint),
    )
    with pytest.raises(
        ValueError, match="arm_spec_references contains duplicate values"
    ):
        verify_campaign_spec(campaign=bad_camp)


def test_neg_e04_missing_campaign_arm_reference() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    # Campaign only references Arm B
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint],  # missing Arm R
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="arm_spec_references does not match"):
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_e05_cross_campaign_arm() -> None:
    arm_b = make_golden_arm_b()
    arm_r_other = build_arm_spec(
        arm_id="ARM-R",
        campaign_id="CAMP-OTHER-001",  # cross-campaign
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
    campaign = make_golden_campaign(
        arm_b.arm_spec_fingerprint, arm_r_other.arm_spec_fingerprint
    )
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="does not match campaign"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r_other],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_e06_primary_arm_equals_comparator() -> None:
    with pytest.raises(ValueError, match="must be distinct"):
        PrimaryComparisonV1(test_arm_id="ARM-B", comparator_arm_id="ARM-B")
        # In build_campaign_spec:
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-B"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


def test_neg_e07_control_overlaps_primary_pair() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=["ARM-B"],  # overlaps primary comparison!
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="overlaps with primary comparison pair"):
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


# GROUP F: RUN AND ACCOUNT ISOLATION


def test_neg_f01_empty_expected_run_ids() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="expected_run_ids cannot be empty"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=[],
        )


def test_neg_f02_duplicate_expected_run_ids() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="duplicate run IDs"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001", "RUN-001"],
        )


def test_neg_f03_missing_expected_run_in_bindings() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bindings = make_golden_bindings()  # only has RUN-001
    with pytest.raises(ValueError, match="does not match expected_run_ids"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001", "RUN-002"],
        )


def test_neg_f04_unexpected_run_in_bindings() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bindings = make_golden_bindings()
    extra_binding = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-999",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-EXTRA",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="not in expected_run_ids"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=bindings + [extra_binding],
            expected_run_ids=["RUN-001"],
        )


def test_neg_f05_same_account_id_assigned_to_arm_b_and_arm_r() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    b_arm_b = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SAME-ACCOUNT-ID",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b_arm_r = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-R",
        portfolio_account_id="SAME-ACCOUNT-ID",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="reused across bindings"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=[b_arm_b, b_arm_r],
            expected_run_ids=["RUN-001"],
        )


def test_neg_f06_same_account_id_across_two_runs() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    run1 = make_golden_bindings()
    run2 = [
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-002",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-001",  # reused from run 1
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-002",
            arm_id="ARM-R",
            portfolio_account_id="SYNTH-ACC-R-002",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
    ]
    with pytest.raises(ValueError, match="reused across bindings"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=run1 + run2,
            expected_run_ids=["RUN-001", "RUN-002"],
        )


def test_neg_f07_missing_arm_r_binding_within_run() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    run1 = make_golden_bindings()
    # run 2 only has ARM-B binding
    run2 = [
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-002",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-002",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        ),
    ]
    with pytest.raises(ValueError, match="does not bind exactly every declared arm"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=run1 + run2,
            expected_run_ids=["RUN-001", "RUN-002"],
        )


def test_neg_f08_binding_starting_cash_mismatch() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    bad_binding = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="5000",  # arm has 10000
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b_arm_r = make_golden_bindings()[1]
    with pytest.raises(ValueError, match="does not match arm initial_capital"):
        verify_experiment_configuration(
            campaign=campaign,
            arms=[arm_b, arm_r],
            bindings=[bad_binding, b_arm_r],
            expected_run_ids=["RUN-001"],
        )


def test_neg_f09_input_collections_unchanged_on_rejection() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    campaign = make_golden_campaign()
    arms_list = [arm_b, arm_r]
    bindings_list = make_golden_bindings()
    run_ids = ["RUN-001", "RUN-002"]  # will fail because RUN-002 missing from bindings

    with pytest.raises(ValueError):
        verify_experiment_configuration(
            campaign=campaign,
            arms=arms_list,
            bindings=bindings_list,
            expected_run_ids=run_ids,
        )

    assert len(arms_list) == 2
    assert len(bindings_list) == 2
    assert run_ids == ["RUN-001", "RUN-002"]


# GROUP G: STAGE 1-SPECIFIC REFUSALS


def test_neg_g01_wrong_primary_arm_ids() -> None:
    arm_x = build_arm_spec(
        arm_id="ARM-X",
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
    arm_r = make_golden_arm_r()
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-X", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_x.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    b_x = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-X",
        portfolio_account_id="ACC-X",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b_r = make_golden_bindings()[1]
    with pytest.raises(ValueError, match="Stage 1 test_arm_id must be ARM-B"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_x, arm_r],
            bindings=[b_x, b_r],
            expected_run_ids=["RUN-001"],
        )


def test_neg_g02_wrong_selector_roles() -> None:
    # ARM-B with FROZEN_BASELINE
    arm_b = build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="FROZEN_BASELINE",
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
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint)
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="selector_type must be ADAPTIVE_AI"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g03_b_does_not_start_in_b3() -> None:
    arm_b = build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B4",  # does not start in B3
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
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint)
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="ARM-B initial_strategy_reference must be B3"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g04_b_admits_unauthorized_strategy() -> None:
    arm_b = build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B4", "B5", "B6"],
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
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint)
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="ARM-B eligible strategies"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g05_warmup_and_observation_counts() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    bindings = make_golden_bindings()

    # Warmup < 253
    camp_bad_warmup = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(252),  # < 253
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    with pytest.raises(ValueError, match="warmup_window.sessions_count must be >= 253"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_bad_warmup,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )

    # Observation != 126
    camp_bad_obs = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(100),  # != 126
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    with pytest.raises(
        ValueError, match="observation_window.sessions_count must be 126"
    ):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_bad_obs,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g06_schedule_timing_same_close() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    bindings = make_golden_bindings()
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "SAME_CLOSE"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    with pytest.raises(ValueError, match="execution_timing must be NEXT_OPEN"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g07_b_and_r_mismatched_policies() -> None:
    arm_b = make_golden_arm_b()
    arm_r = build_arm_spec(
        arm_id="ARM-R",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="DETERMINISTIC_COMPARATOR",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role="COMPARATOR",
        mandate_reference="fixture://mismatched-mandate-v2",  # mismatch
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-R",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference="fixture://matured-own-arm-v1",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-R-001",
        frozen_configuration_reference="b" * 64,
    )
    camp = make_golden_campaign(arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint)
    bindings = make_golden_bindings()
    with pytest.raises(ValueError, match="mandate_reference mismatch"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g08_arm_initial_capital_not_10000() -> None:
    arm_b = build_arm_spec(
        arm_id="ARM-B",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="ADAPTIVE_AI",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="5000",  # not 10000
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
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint)
    b_b = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        initial_cash_allocated="5000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    b_r = make_golden_bindings()[1]
    with pytest.raises(ValueError, match="initial_capital must be 10000"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=[b_b, b_r],
            expected_run_ids=["RUN-001"],
        )


def test_neg_g09_control_with_capital_1() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    arm_c = build_arm_spec(
        arm_id="ARM-C",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="PASSIVE_BENCHMARK",
        eligible_strategy_references=["C-BENCH"],
        initial_strategy_reference="C-BENCH",
        initial_capital="1",  # control has 1 instead of 10000
        currency="USD",
        arm_account_role="CONTROL",
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-C",
        information_visibility_policy="fixture://vis-c",
        feedback_policy_reference="fixture://feed-c",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-c",
        frozen_configuration_reference="c" * 64,
    )
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=["ARM-C"],
        arm_spec_references=[
            arm_b.arm_spec_fingerprint,
            arm_r.arm_spec_fingerprint,
            arm_c.arm_spec_fingerprint,
        ],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=["B3", "B4", "B5", "C-BENCH"],
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={"synthetic_fixture_only": True},
    )
    b_b, b_r = make_golden_bindings()
    b_c = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-C",
        portfolio_account_id="SYNTH-ACC-C-001",
        initial_cash_allocated="1",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="arm ARM-C initial_capital must be 10000"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r, arm_c],
            bindings=[b_b, b_r, b_c],
            expected_run_ids=["RUN-001"],
        )


def test_neg_g10_extra_arm_not_declared_as_control() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    arm_x = build_arm_spec(
        arm_id="ARM-X",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="PASSIVE_BENCHMARK",
        eligible_strategy_references=["X-STRAT"],
        initial_strategy_reference="X-STRAT",
        initial_capital="10000",
        currency="USD",
        arm_account_role="CONTROL",
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-X",
        information_visibility_policy="fixture://vis-x",
        feedback_policy_reference="fixture://feed-x",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-x",
        frozen_configuration_reference="e" * 64,
    )
    # Campaign does NOT declare ARM-X in control_arm_references,
    # but includes it in arm_spec_references
    camp = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],  # empty controls!
        arm_spec_references=[
            arm_b.arm_spec_fingerprint,
            arm_r.arm_spec_fingerprint,
            arm_x.arm_spec_fingerprint,
        ],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=["B3", "B4", "B5", "X-STRAT"],
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={"synthetic_fixture_only": True},
    )
    b_b, b_r = make_golden_bindings()
    b_x = build_run_account_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        run_id="RUN-001",
        arm_id="ARM-X",
        portfolio_account_id="SYNTH-ACC-X-001",
        initial_cash_allocated="10000",
        bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
    )
    # Generic verifier succeeds
    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r, arm_x],
            bindings=[b_b, b_r, b_x],
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    # Stage 1 specific verifier rejects undeclared active arm
    with pytest.raises(ValueError, match="do not match primary plus declared controls"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r, arm_x],
            bindings=[b_b, b_r, b_x],
            expected_run_ids=["RUN-001"],
        )


def test_neg_g11_campaign_allowed_strategy_families_lacks_b3_or_b4_or_b5() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp_missing_b4 = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=["B3", "B5"],  # missing B4!
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={"synthetic_fixture_only": True},
    )
    bindings = make_golden_bindings()
    with pytest.raises(
        ValueError, match="allowed_strategy_families must include B3, B4, B5"
    ):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_missing_b4,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_g12_campaign_allowed_strategy_families_other_only() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp_other = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[arm_b.arm_spec_fingerprint, arm_r.arm_spec_fingerprint],
        qualified_dataset_references=[],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=["OTHER"],  # only OTHER
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://cost-policy-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://eval-policy-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={"synthetic_fixture_only": True},
    )
    bindings = make_golden_bindings()
    with pytest.raises(
        ValueError, match="allowed_strategy_families must include B3, B4, B5"
    ):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_other,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


# ==================================================
# REGRESSION TESTS FOR PR #463 REVIEW DEFECTS
# ==================================================


def test_neg_g13_br_frozen_configuration_reference_mismatch() -> None:
    arm_b = make_golden_arm_b()
    # ARM-R with mismatched frozen_configuration_reference
    arm_r = build_arm_spec(
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
        frozen_configuration_reference="c" * 64,  # ARM-B has "b" * 64
    )
    # Rebuild campaign with new ARM-R fingerprint so preimages are valid
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    # Generic configuration verification intentionally permits
    # distinct frozen references
    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    # Stage 1 specific verification refuses mismatched frozen references
    with pytest.raises(ValueError, match="frozen_configuration_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


@pytest.mark.parametrize(
    "bad_str",
    ["   ", "  ref", "ref  ", "\tref", "ref\n"],
)
def test_neg_whitespace_reference_strings(bad_str: str) -> None:
    # 1. study_protocol_revision
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision=bad_str,
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )

    # 2. data_window.calendar_id
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        camp = make_golden_campaign()
        bad_camp = replace(
            camp,
            data_window=DataWindowV1("2024-01-02", "2026-01-30", bad_str),
        )
        verify_campaign_spec(campaign=bad_camp)

    # 3. mandate_reference
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3"],
            initial_strategy_reference="B3",
            initial_capital="10000",
            currency="USD",
            arm_account_role="PRIMARY_TEST",
            mandate_reference=bad_str,
            execution_policy_reference="fixture://next-open-v1",
            research_budget_reference="fixture://budget-B",
            information_visibility_policy=("IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"),
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="fixture://model-B-v1",
            deterministic_seed_reference="fixture://seed-B-001",
            frozen_configuration_reference="b" * 64,
        )

    # 4. execution_policy_reference
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3"],
            initial_strategy_reference="B3",
            initial_capital="10000",
            currency="USD",
            arm_account_role="PRIMARY_TEST",
            mandate_reference="fixture://balanced-mandate-v1",
            execution_policy_reference=bad_str,
            research_budget_reference="fixture://budget-B",
            information_visibility_policy=("IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"),
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="fixture://model-B-v1",
            deterministic_seed_reference="fixture://seed-B-001",
            frozen_configuration_reference="b" * 64,
        )

    # 5. qualified_dataset_references elements
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[bad_str],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )

    # 6. portfolio_account_id
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_run_account_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            run_id="RUN-001",
            arm_id="ARM-B",
            portfolio_account_id=bad_str,
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        )

    # 7. eligible_strategy_references elements
    with pytest.raises(
        ValueError, match="nonblank string without surrounding whitespace"
    ):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=[bad_str],
            initial_strategy_reference=bad_str,
            initial_capital="10000",
            currency="USD",
            arm_account_role="PRIMARY_TEST",
            mandate_reference="fixture://balanced-mandate-v1",
            execution_policy_reference="fixture://next-open-v1",
            research_budget_reference="fixture://budget-B",
            information_visibility_policy=("IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"),
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="fixture://model-B-v1",
            deterministic_seed_reference="fixture://seed-B-001",
            frozen_configuration_reference="b" * 64,
        )


def test_neg_dataset_references_duplicate() -> None:
    # Builder input with duplicate dataset references raises ValueError
    with pytest.raises(
        ValueError,
        match="qualified_dataset_references contains duplicate values",
    ):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[
                "fixture://data-A",
                "fixture://data-A",
            ],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )

    # Stored forged campaign containing duplicate qualified_dataset_references
    camp = make_golden_campaign()
    bad_camp = replace(
        camp,
        qualified_dataset_references=("fixture://data-A", "fixture://data-A"),
    )
    with pytest.raises(
        ValueError,
        match="qualified_dataset_references contains duplicate values",
    ):
        verify_campaign_spec(campaign=bad_camp)

    # Two distinct references remain valid
    camp_two_datasets = build_campaign_spec(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://methodology-v1",
        created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=[],
        arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
        qualified_dataset_references=["fixture://data-A", "fixture://data-B"],
        data_window=DataWindowV1("2024-01-02", "2026-01-30", "fixture://calendar-v1"),
        warmup_window=SessionWindowV1(253),
        observation_window=SessionWindowV1(126),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
        authorization_evidence={"synthetic_fixture_only": True},
    )
    assert verify_campaign_spec(campaign=camp_two_datasets) is True


def test_neg_mixed_type_mapping_keys() -> None:
    # 1. Mixed keys in authorization_evidence must raise ValueError, not TypeError
    with pytest.raises(ValueError, match="JSON mapping keys must be strings"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={1: "invalid", "valid": "value"},  # type: ignore[dict-item]
        )

    # 2. Mixed keys in accepted_contract_revisions must raise ValueError, not TypeError
    with pytest.raises(
        ValueError,
        match="accepted_contract_revisions keys must be nonblank strings",
    ):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={1: "a" * 40, "valid": "b" * 40},  # type: ignore[dict-item]
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )

    # 3. Whitespace-only revision keys
    with pytest.raises(
        ValueError,
        match="accepted_contract_revisions keys must be nonblank strings",
    ):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type="SYNTHETIC_TEST",
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={"   ": "a" * 40},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )


@pytest.mark.parametrize(
    "bad_enum",
    [[1, 2], {"a": "b"}, 123, None, "UNSUPPORTED_TYPE"],
)
def test_neg_enum_input_types(bad_enum: Any) -> None:
    # 1. campaign_type builder input
    with pytest.raises(ValueError, match="invalid campaign_type"):
        build_campaign_spec(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_type=bad_enum,
            study_protocol_revision="fixture://methodology-v1",
            created_at=datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC),
            frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
            accepted_contract_revisions={},
            research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
            primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
            control_arm_references=[],
            arm_spec_references=[GOLDEN_ARM_B_HASH, GOLDEN_ARM_R_HASH],
            qualified_dataset_references=[],
            data_window=DataWindowV1(
                "2024-01-02", "2026-01-30", "fixture://calendar-v1"
            ),
            warmup_window=SessionWindowV1(253),
            observation_window=SessionWindowV1(126),
            scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
            decision_schedule=DecisionScheduleV1(
                "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
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
            authorization_evidence={"synthetic_fixture_only": True},
        )

    # 2. campaign_type stored verifier
    camp = make_golden_campaign()
    bad_camp = replace(camp, campaign_type=bad_enum)
    with pytest.raises(ValueError, match="invalid campaign_type"):
        verify_campaign_spec(campaign=bad_camp)

    # 3. selector_type builder input
    with pytest.raises(ValueError, match="invalid selector_type"):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type=bad_enum,
            eligible_strategy_references=["B3"],
            initial_strategy_reference="B3",
            initial_capital="10000",
            currency="USD",
            arm_account_role="PRIMARY_TEST",
            mandate_reference="fixture://balanced-mandate-v1",
            execution_policy_reference="fixture://next-open-v1",
            research_budget_reference="fixture://budget-B",
            information_visibility_policy=("IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"),
            feedback_policy_reference="fixture://matured-own-arm-v1",
            model_configuration_reference="fixture://model-B-v1",
            deterministic_seed_reference="fixture://seed-B-001",
            frozen_configuration_reference="b" * 64,
        )

    # 4. selector_type stored verifier
    arm = make_golden_arm_b()
    bad_arm = replace(arm, selector_type=bad_enum)
    with pytest.raises(ValueError, match="invalid selector_type"):
        verify_arm_spec(arm=bad_arm)


def test_neg_stage1_campaign_mandate_mismatch() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(
        portfolio_mandate_reference="fixture://different-mandate-v1"
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="campaign.portfolio_mandate_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_campaign_execution_policy_mismatch() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(
        execution_policy_reference="fixture://different-execution-v1"
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="campaign.execution_policy_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_br_feedback_policy_mismatch() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r(
        feedback_policy_reference="fixture://different-feedback-v1"
    )
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="feedback_policy_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_swapped_account_roles() -> None:
    arm_b = make_golden_arm_b(arm_account_role="COMPARATOR")
    arm_r = make_golden_arm_r(arm_account_role="PRIMARY_TEST")
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="arm_account_role"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_arbitrary_account_roles() -> None:
    # 1. ARM-B with arbitrary role OTHER
    arm_b_other = make_golden_arm_b(arm_account_role="OTHER")
    arm_r = make_golden_arm_r()
    camp_b = make_golden_campaign(
        arm_b_hash=arm_b_other.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp_b,
            arms=[arm_b_other, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    with pytest.raises(ValueError, match="ARM-B arm_account_role"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_b,
            arms=[arm_b_other, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )

    # 2. ARM-R with arbitrary role OTHER
    arm_b = make_golden_arm_b()
    arm_r_other = make_golden_arm_r(arm_account_role="OTHER")
    camp_r = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r_other.arm_spec_fingerprint,
    )

    assert (
        verify_experiment_configuration(
            campaign=camp_r,
            arms=[arm_b, arm_r_other],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    with pytest.raises(ValueError, match="ARM-R arm_account_role"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp_r,
            arms=[arm_b, arm_r_other],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_arm_b_model_policy_mismatch() -> None:
    arm_b = make_golden_arm_b(model_configuration_reference="fixture://model-B-v2")
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
        model_and_prompt_policy_reference="fixture://model-B-v1",
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="model_configuration_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_arm_b_model_none() -> None:
    arm_b = make_golden_arm_b(model_configuration_reference="NONE")
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="model_configuration_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_neg_stage1_arm_r_must_remain_model_free() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r(model_configuration_reference="fixture://model-R-v1")
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

    with pytest.raises(ValueError, match="model_configuration_reference"):
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )


def test_stage1_generic_extensibility_alternative_roles_and_models() -> None:
    arm_b = make_golden_arm_b(
        arm_account_role="RESEARCH_EXPLORATORY",
        model_configuration_reference="fixture://custom-llm-v1",
    )
    arm_r = make_golden_arm_r(
        arm_account_role="BENCHMARK_INDEX",
        model_configuration_reference="fixture://heuristic-v1",
    )
    camp = make_golden_campaign(
        arm_b_hash=arm_b.arm_spec_fingerprint,
        arm_r_hash=arm_r.arm_spec_fingerprint,
        model_and_prompt_policy_reference="fixture://global-policy-v1",
    )
    bindings = make_golden_bindings()

    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )


def test_neg_frozen_json_direct_array_cycle() -> None:
    arr = FrozenJSONArray(items=())
    object.__setattr__(arr, "items", (arr,))
    forged = FrozenJSONMap(items=(("cycle", arr),))
    camp = replace(make_golden_campaign(), authorization_evidence=forged)

    with pytest.raises(ValueError, match="cyclic"):
        verify_campaign_spec(campaign=camp)


def test_neg_frozen_json_indirect_map_array_map_cycle() -> None:
    nested_map = FrozenJSONMap(items=())
    nested_array = FrozenJSONArray(items=(nested_map,))
    object.__setattr__(nested_map, "items", (("cycle", nested_array),))
    forged = FrozenJSONMap(items=(("root", nested_map),))
    camp = replace(make_golden_campaign(), authorization_evidence=forged)

    with pytest.raises(ValueError, match="cyclic"):
        verify_campaign_spec(campaign=camp)


def test_frozen_json_valid_shared_immutable_child() -> None:
    shared_child = FrozenJSONArray(items=(1, "test", True))
    shared_map = FrozenJSONMap(
        items=(
            ("a_ref", shared_child),
            ("b_ref", shared_child),
        )
    )
    _verify_frozen_json(shared_map)


class ImpostorString(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def test_neg_build_arm_spec_impostor_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        build_arm_spec(
            arm_id="ARM-B",
            campaign_id="CAMP-E1-SYNTH-001",
            selector_type="ADAPTIVE_AI",
            eligible_strategy_references=["B3", "B4", "B5"],
            initial_strategy_reference="B3",
            initial_capital="10000",
            currency=ImpostorString("EUR"),
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


def test_neg_verify_arm_spec_impostor_currency_recomputed_hash() -> None:
    golden_arm = make_golden_arm_b()
    forged_arm = replace(golden_arm, currency=ImpostorString("EUR"))
    recomputed_hash = content_hash(_arm_preimage(forged_arm))
    forged_arm = replace(forged_arm, arm_spec_fingerprint=recomputed_hash)

    with pytest.raises(ValueError, match="currency"):
        verify_arm_spec(arm=forged_arm)


def test_neg_verify_arm_spec_impostor_schema_version_recomputed_hash() -> None:
    golden_arm = make_golden_arm_b()
    forged_arm = replace(golden_arm, schema_version=ImpostorString("wrong-schema"))
    recomputed_hash = content_hash(_arm_preimage(forged_arm))
    forged_arm = replace(forged_arm, arm_spec_fingerprint=recomputed_hash)

    with pytest.raises(ValueError, match="schema_version"):
        verify_arm_spec(arm=forged_arm)


def test_neg_verify_campaign_spec_impostor_schema_version_recomputed_hash() -> None:
    golden_camp = make_golden_campaign()
    forged_camp = replace(golden_camp, schema_version=ImpostorString("wrong-schema"))
    recomputed_hash = content_hash(_campaign_preimage(forged_camp))
    forged_camp = replace(forged_camp, campaign_spec_fingerprint=recomputed_hash)

    with pytest.raises(ValueError, match="schema_version"):
        verify_campaign_spec(campaign=forged_camp)


def test_neg_verify_run_account_binding_impostor_schema_version() -> None:
    binding = make_golden_bindings()[0]
    forged_binding = replace(binding, schema_version=ImpostorString("wrong-schema"))

    with pytest.raises(ValueError, match="schema_version"):
        verify_run_account_binding(binding=forged_binding)


def test_neg_verify_run_account_binding_impostor_binding_id() -> None:
    binding = make_golden_bindings()[0]
    forged_binding = replace(binding, binding_id=ImpostorString("WRONG-BINDING"))

    with pytest.raises(ValueError, match="binding_id"):
        verify_run_account_binding(binding=forged_binding)


def test_strict_type_valid_builtin_strings() -> None:
    arm_b = make_golden_arm_b()
    arm_r = make_golden_arm_r()
    camp = make_golden_campaign()
    bindings = make_golden_bindings()

    assert type(arm_b.currency) is str and arm_b.currency == "USD"
    assert type(arm_b.schema_version) is str and arm_b.schema_version == SCHEMA_VERSION
    assert type(camp.schema_version) is str and camp.schema_version == SCHEMA_VERSION
    assert (
        type(bindings[0].schema_version) is str
        and bindings[0].schema_version == SCHEMA_VERSION
    )
    assert type(bindings[0].binding_id) is str

    assert verify_arm_spec(arm=arm_b) is True
    assert verify_arm_spec(arm=arm_r) is True
    assert verify_campaign_spec(campaign=camp) is True
    assert verify_run_account_binding(binding=bindings[0]) is True
    assert (
        verify_experiment_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    assert (
        verify_stage1_synthetic_br_configuration(
            campaign=camp,
            arms=[arm_b, arm_r],
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
        is True
    )

# ---------------------------------------------------------------------------
# Issue #489: Snapshot each caller-provided E1 collection exactly once
# ---------------------------------------------------------------------------


class _FalseNonemptyRuns(list[str]):
    def __bool__(self) -> bool:
        return True


class _ChangingBindings(list[RunAccountBindingV1]):
    def __init__(
        self,
        first: list[RunAccountBindingV1],
        later: list[RunAccountBindingV1],
    ) -> None:
        super().__init__(later)
        self.first = first
        self.later = later
        self.read_count = 0

    def __iter__(self) -> Iterator[RunAccountBindingV1]:
        self.read_count += 1
        return iter(self.first if self.read_count == 1 else self.later)


class _ChangingArms(list[ArmSpecV1]):
    def __init__(self, first: list[ArmSpecV1], later: list[ArmSpecV1]) -> None:
        super().__init__(later)
        self.first = first
        self.later = later
        self.read_count = 0

    def __iter__(self) -> Iterator[ArmSpecV1]:
        self.read_count += 1
        return iter(self.first if self.read_count == 1 else self.later)


class _ChangingRuns(list[str]):
    def __init__(self, first: list[str], later: list[str]) -> None:
        super().__init__(later)
        self.first = first
        self.later = later
        self.read_count = 0

    def __iter__(self) -> Iterator[str]:
        self.read_count += 1
        return iter(self.first if self.read_count == 1 else self.later)


@pytest.mark.parametrize(
    "verifier",
    [verify_experiment_configuration, verify_stage1_synthetic_br_configuration],
)
def test_e1_rejects_false_nonempty_empty_run_manifest(verifier: Any) -> None:
    with pytest.raises(ValueError, match="expected_run_ids cannot be empty"):
        verifier(
            campaign=make_golden_campaign(),
            arms=(make_golden_arm_b(), make_golden_arm_r()),
            bindings=[],
            expected_run_ids=_FalseNonemptyRuns(),
        )


@pytest.mark.parametrize(
    "verifier",
    [verify_experiment_configuration, verify_stage1_synthetic_br_configuration],
)
def test_e1_rejects_changing_binding_completeness(verifier: Any) -> None:
    b, r = make_golden_bindings()
    invalid_r = replace(
        r,
        portfolio_account_id=b.portfolio_account_id,
        initial_cash_allocated="1",
        bound_at="2026-10-18T00:00:00.000000Z",
    )
    bindings = _ChangingBindings(first=[b], later=[b, invalid_r])
    with pytest.raises(ValueError, match="does not bind exactly every declared arm"):
        verifier(
            campaign=make_golden_campaign(),
            arms=(make_golden_arm_b(), make_golden_arm_r()),
            bindings=bindings,
            expected_run_ids=["RUN-001"],
        )
    assert bindings.read_count == 1
    assert bindings.first == [b]
    assert bindings.later == [b, invalid_r]


@pytest.mark.parametrize(
    "verifier",
    [verify_experiment_configuration, verify_stage1_synthetic_br_configuration],
)
def test_e1_rejects_changing_expected_run_set(verifier: Any) -> None:
    runs = _ChangingRuns(first=["RUN-001", "RUN-002"], later=["RUN-001"])
    with pytest.raises(ValueError, match="bindings run set"):
        verifier(
            campaign=make_golden_campaign(),
            arms=(make_golden_arm_b(), make_golden_arm_r()),
            bindings=make_golden_bindings(),
            expected_run_ids=runs,
        )
    assert runs.read_count == 1


def test_stage1_uses_original_arm_snapshot_across_generic_and_profile() -> None:
    arm_b, arm_r = make_golden_arm_b(), make_golden_arm_r()
    arms = _ChangingArms(first=[arm_b, arm_r], later=[arm_b])
    assert (
        verify_stage1_synthetic_br_configuration(
            campaign=make_golden_campaign(),
            arms=arms,
            bindings=make_golden_bindings(),
            expected_run_ids=["RUN-001"],
        )
        is True
    )
    assert arms.read_count == 1


def test_e1_unmodified_golden_controls_still_validate() -> None:
    campaign = make_golden_campaign()
    arms = [make_golden_arm_b(), make_golden_arm_r()]
    bindings = make_golden_bindings()
    for verifier in (
        verify_experiment_configuration,
        verify_stage1_synthetic_br_configuration,
    ):
        assert (
            verifier(
                campaign=campaign,
                arms=arms,
                bindings=bindings,
                expected_run_ids=["RUN-001"],
            )
            is True
        )
        with pytest.raises(ValueError, match="expected_run_ids cannot be empty"):
            verifier(campaign=campaign, arms=arms, bindings=[], expected_run_ids=[])
        shared = replace(bindings[1], portfolio_account_id=bindings[0].portfolio_account_id)
        with pytest.raises(ValueError, match="reused across bindings"):
            verifier(
                campaign=campaign,
                arms=arms,
                bindings=[bindings[0], shared],
                expected_run_ids=["RUN-001"],
            )
    assert campaign.campaign_spec_fingerprint == GOLDEN_CAMPAIGN_HASH
    assert arms[0].arm_spec_fingerprint == GOLDEN_ARM_B_HASH
    assert arms[1].arm_spec_fingerprint == GOLDEN_ARM_R_HASH
