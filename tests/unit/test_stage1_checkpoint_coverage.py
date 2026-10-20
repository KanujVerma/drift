"""Synthetic E6A checkpoint coverage: independent goldens and adversarial cases."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

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
)
from drift.experiments.stage1_checkpoint_coverage import (
    COVERAGE_SCHEMA_VERSION,
    Stage1CheckpointCoverageAuditV1,
    Stage1CoverageCountsV1,
    Stage1RunCheckpointDeclarationV1,
    _audit_preimage,
    _full_manifest_fingerprint,
    build_stage1_checkpoint_coverage_audit,
    verify_stage1_checkpoint_coverage_audit,
)
from drift.experiments.stage1_trial_events import build_stage1_trial_event
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    build_stage1_trial_provenance_snapshot,
)
from drift.serialization.canonical import content_hash

CAMPAIGN_HASH = "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4"
ARM_B_HASH = "84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831"
ARM_R_HASH = "c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd"
E1_TWO_RUN_HASH = "7cd97e7e6884d608888497b8688053d51aab11edb4a43cce8c6437fa5ec16b56"
CHECKPOINT_HASH = "6e8ba6d836a02c0f27bc0bc67e253325c96d81a909972177f0bdb876450c79b5"
ALL_MISSING_HASH = "4ba2fcc7cdfa78a3549efb8d7942fd70a9b5f5537db21906ea0c597ee2095ed3"
MIXED_HASH = "87379a6e2147b3d9e1796cc90bf03fcfe32cec325c9b652b92add5270d6232da"
B_TWO_RUN_SNAPSHOT_HASH = (
    "8e2b7a89d9c1aea9c1da6b35bebb995ae414c786c50ec6f0498c98e6c975e91a"
)
R_TWO_RUN_SNAPSHOT_HASH = (
    "271d5198d917597e3083f498e3c10f09871598022ebda6284f97e6a8ed033130"
)
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


def _arm_c() -> ArmSpecV1:
    return build_arm_spec(
        arm_id="ARM-C",
        campaign_id="CAMP-E1-SYNTH-001",
        selector_type="FROZEN_BASELINE",
        eligible_strategy_references=["B3", "B4", "B5"],
        initial_strategy_reference="B3",
        initial_capital="10000",
        currency="USD",
        arm_account_role="CONTROL",
        mandate_reference="fixture://balanced-mandate-v1",
        execution_policy_reference="fixture://next-open-v1",
        research_budget_reference="fixture://budget-C",
        information_visibility_policy="IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
        feedback_policy_reference="fixture://matured-own-arm-v1",
        model_configuration_reference="NONE",
        deterministic_seed_reference="fixture://seed-C-001",
        frozen_configuration_reference="c" * 64,
    )


def _campaign(
    arms: list[ArmSpecV1],
    *,
    test_arm_id: str = "ARM-B",
    comparator_arm_id: str = "ARM-R",
) -> CampaignSpecV1:
    controls = [
        a.arm_id
        for a in arms
        if a.arm_id not in {test_arm_id, comparator_arm_id}
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


def test_p01_all_missing_independent_golden_and_absence() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    assert audit.schema_version == COVERAGE_SCHEMA_VERSION
    assert audit.campaign_spec_fingerprint == CAMPAIGN_HASH
    assert audit.complete_manifest_fingerprint == E1_TWO_RUN_HASH
    assert audit.checkpoint_manifest_fingerprint == CHECKPOINT_HASH
    assert audit.audit_fingerprint == ALL_MISSING_HASH
    assert audit.counts == Stage1CoverageCountsV1(12, 12, 0, 0, 0, 6, 0)
    assert all(slot.coverage_state == "MISSING_SNAPSHOT" for slot in audit.slots)
    assert all(slot.provenance_snapshot is None for slot in audit.slots)
    assert all(pair.pair_state == "BOTH_MISSING" for pair in audit.pairs)
    assert _verify(audit, fixture) is True


def test_p02_mixed_independent_golden_and_preserved_envelopes() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", recorded=True)
    r = _snapshot(camp, arms, bindings, runs, "ARM-R")
    assert b.event_envelopes[0].event_hash == ROOT_EVENT_HASH
    assert b.snapshot_fingerprint == B_TWO_RUN_SNAPSHOT_HASH
    assert r.snapshot_fingerprint == R_TWO_RUN_SNAPSHOT_HASH
    audit = _build(*fixture, _decls(), snapshots=[r, b])
    assert audit.checkpoint_manifest_fingerprint == CHECKPOINT_HASH
    assert audit.audit_fingerprint == MIXED_HASH
    assert audit.counts == Stage1CoverageCountsV1(12, 10, 1, 1, 2, 6, 1)
    assert audit.slots[0].coverage_state == "EVENTS_RECORDED"
    assert audit.slots[1].coverage_state == "UNOBSERVED"
    assert audit.slots[0].provenance_snapshot is not None
    assert (
        audit.slots[0].provenance_snapshot.event_envelopes[0].event_hash
        == ROOT_EVENT_HASH
    )
    assert audit.pairs[0].pair_state == "BOTH_SUBMITTED"
    assert _verify(audit, fixture) is True


@pytest.mark.parametrize(
    ("submitted_arm", "expected"),
    [
        (None, "BOTH_MISSING"),
        ("ARM-B", "COMPARATOR_MISSING"),
        ("ARM-R", "TEST_MISSING"),
    ],
)
def test_p03_p05_missing_pair_states(
    submitted_arm: str | None, expected: str
) -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    snapshots = (
        []
        if submitted_arm is None
        else [_snapshot(camp, arms, bindings, runs, submitted_arm)]
    )
    audit = _build(*fixture, _decls(), snapshots)
    assert audit.pairs[0].pair_state == expected
    assert _verify(audit, fixture) is True


def test_p06_submitted_unobserved_counts_for_pair() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    both = [
        _snapshot(camp, arms, bindings, runs, arm_id)
        for arm_id in ("ARM-R", "ARM-B")
    ]
    audit = _build(*fixture, _decls(), both)
    assert audit.counts == Stage1CoverageCountsV1(12, 10, 2, 0, 2, 6, 1)
    assert audit.pairs[0].pair_state == "BOTH_SUBMITTED"
    assert _verify(audit, fixture) is True


def test_p07_canonical_input_collection_order() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B")
    r = _snapshot(camp, arms, bindings, runs, "ARM-R")
    baseline = _build(*fixture, _decls(), [b, r])
    permuted = _build(
        camp, list(reversed(arms)), list(reversed(bindings)),
        list(reversed(runs)), list(reversed(_decls())), [r, b]
    )
    assert baseline == permuted
    assert baseline.audit_fingerprint == permuted.audit_fingerprint


def test_p08_within_run_checkpoint_order_changes_identity() -> None:
    fixture = _fixture()
    baseline = _build(*fixture, _decls())
    rearranged = _build(*fixture, _decls(checkpoint_ids=tuple(reversed(CKPTS))))
    assert (
        baseline.checkpoint_manifest_fingerprint
        != rearranged.checkpoint_manifest_fingerprint
    )
    assert baseline.audit_fingerprint != rearranged.audit_fingerprint
    assert _verify(rearranged, fixture) is True


def test_p09_control_arm_adds_slots_without_extra_primary_pairs() -> None:
    fixture = _fixture(arms=[_arm_b(), _arm_r(), _arm_c()])
    audit = _build(*fixture, _decls())
    assert audit.counts.declared_slots == 18
    assert audit.counts.declared_pairs == 6
    assert len(audit.slots) == 18
    assert any(slot.arm_id == "ARM-C" for slot in audit.slots)
    assert all(pair.test_arm_id == "ARM-B" for pair in audit.pairs)
    assert _verify(audit, fixture) is True


def test_p10_nonuniform_checkpoint_sets() -> None:
    fixture = _fixture()
    declarations = [
        Stage1RunCheckpointDeclarationV1("RUN-001", ("CKPT-001", "CKPT-002")),
        Stage1RunCheckpointDeclarationV1("RUN-002", ("CKPT-001",)),
    ]
    audit = _build(*fixture, declarations)
    assert audit.counts == Stage1CoverageCountsV1(6, 6, 0, 0, 0, 3, 0)
    assert _verify(audit, fixture) is True


def test_p11_determinism_and_checkpoint_declaration_detachment() -> None:
    fixture = _fixture()
    declarations = _decls()
    audit = _build(*fixture, declarations)
    second = _build(*fixture, _decls())
    assert audit == second
    assert audit.checkpoint_declarations[0] is not declarations[0]
    original_hash = audit.audit_fingerprint
    original_checkpoint_hash = audit.checkpoint_manifest_fingerprint
    object.__setattr__(declarations[0], "run_id", "WRONG")
    object.__setattr__(declarations[0], "checkpoint_ids", ("ALTERED",))
    assert audit.checkpoint_declarations[0].run_id == "RUN-001"
    assert audit.checkpoint_declarations[0].checkpoint_ids == CKPTS
    assert audit.checkpoint_manifest_fingerprint == original_checkpoint_hash
    assert audit.audit_fingerprint == original_hash
    assert _verify(audit, fixture) is True


def test_p11b_snapshot_original_detachment() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", recorded=True)
    audit = _build(*fixture, _decls(), [b])
    old_sha = audit.audit_fingerprint
    assert audit.slots[0].provenance_snapshot is not b
    object.__setattr__(b.scope.run_account_binding, "portfolio_account_id", "TAMPERED")
    assert audit.slots[0].provenance_snapshot is not None
    retained = audit.slots[0].provenance_snapshot
    assert retained is not None
    assert retained.scope.run_account_binding.portfolio_account_id == "SYNTH-ACC-B-001"
    assert audit.audit_fingerprint == old_sha
    assert _verify(audit, fixture) is True


def test_p12_complete_manifest_contract() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    assert camp.campaign_spec_fingerprint == CAMPAIGN_HASH
    assert arms[0].arm_spec_fingerprint == ARM_B_HASH
    assert arms[1].arm_spec_fingerprint == ARM_R_HASH
    assert _full_manifest_fingerprint(
        campaign=camp, arms=arms, bindings=bindings, expected_run_ids=runs
    ) == E1_TWO_RUN_HASH
    assert _build(*fixture, _decls()).complete_manifest_fingerprint == E1_TWO_RUN_HASH


class ImpostorString(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        " ",
        "CKPT:1",
        "CKPT/1",
        "CKPT 1",
        " CKPT-001",
        "CKPT-001 ",
        ImpostorString("OK"),
    ],
)
def test_n01_bad_checkpoint_tokens(invalid: str) -> None:
    fixture = _fixture()
    declarations = _decls()
    declarations[0] = Stage1RunCheckpointDeclarationV1("RUN-001", (invalid,))
    with pytest.raises(ValueError):
        _build(*fixture, declarations)


def test_n01b_missing_extra_duplicate_runs_and_checkpoint_declarations() -> None:
    fixture = _fixture()
    good = _decls()
    bad_cases: list[Any] = [
        good[:1],
        good + [Stage1RunCheckpointDeclarationV1("RUN-003", CKPTS)],
        good + [good[0]],
        [Stage1RunCheckpointDeclarationV1("RUN-001", ())] + good[1:],
        [Stage1RunCheckpointDeclarationV1("RUN-001", ("CP", "CP"))] + good[1:],
        [Stage1RunCheckpointDeclarationV1("RUN-001", cast(Any, ["CP"]))] + good[1:],
        ["INVALID", good[1]],
        "invalid",
    ]
    for bad in bad_cases:
        with pytest.raises(ValueError):
            _build(*fixture, cast(Any, bad))


def test_n02_reject_duplicate_snapshots_even_identical() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B")
    with pytest.raises(ValueError, match="duplicate"):
        _build(*fixture, _decls(), [b, b])


def test_n03_invalid_nested_snapshot_refused() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B")
    forged = replace(b, snapshot_fingerprint="a" * 64)
    with pytest.raises(ValueError):
        _build(*fixture, _decls(), [forged])


def test_n04_snapshot_outside_declared_checkpoint_rejected() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", checkpoint_id="OTHER")
    with pytest.raises(ValueError, match="outside"):
        _build(*fixture, _decls(), [b])


def test_n05_stored_slots_and_pair_tampering_refused_even_with_new_hash() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    bad_slot = replace(audit.slots[0], coverage_state="UNOBSERVED")
    modified = replace(audit, slots=(bad_slot, *audit.slots[1:]))
    modified = replace(
        modified, audit_fingerprint=content_hash(_audit_preimage(modified))
    )
    with pytest.raises(ValueError):
        _verify(modified, fixture)
    bad_pair = replace(audit.pairs[0], pair_state="BOTH_SUBMITTED")
    modified_pair = replace(audit, pairs=(bad_pair, *audit.pairs[1:]))
    modified_pair = replace(
        modified_pair, audit_fingerprint=content_hash(_audit_preimage(modified_pair))
    )
    with pytest.raises(ValueError):
        _verify(modified_pair, fixture)


def test_n06_corrupted_counters_and_hashes_refused() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    corruptions = [
        replace(audit, counts=replace(audit.counts, declared_slots=13)),
        replace(audit, counts=replace(audit.counts, submitted_snapshots=True)),
        replace(audit, counts=replace(audit.counts, declared_pairs=cast(Any, 1.5))),
        replace(audit, checkpoint_manifest_fingerprint="f" * 64),
        replace(audit, complete_manifest_fingerprint="f" * 64),
        replace(audit, audit_fingerprint="f" * 64),
    ]
    for bad in corruptions:
        with pytest.raises(ValueError):
            _verify(bad, fixture)


def test_n07_result_event_label_does_not_assert_economic_success() -> None:
    fixture = _fixture()
    camp, arms, bindings, runs = fixture
    b = _snapshot(camp, arms, bindings, runs, "ARM-B", recorded=True)
    audit = _build(*fixture, _decls(), [b])
    assert audit.slots[0].coverage_state == "EVENTS_RECORDED"
    assert not hasattr(audit, "financial_result")
    assert not hasattr(audit, "scientific_completeness")


def test_n08_input_objects_preserved_after_refusal() -> None:
    fixture = _fixture()
    declarations = _decls()
    snapshot = _snapshot(*fixture, "ARM-B")
    snapshot_hash = snapshot.snapshot_fingerprint
    bad = declarations + [declarations[0]]
    with pytest.raises(ValueError):
        _build(*fixture, bad, [snapshot])
    assert snapshot.snapshot_fingerprint == snapshot_hash
    assert declarations[0].checkpoint_ids == CKPTS


def test_n09_mutable_stored_collections_and_subclasses_refused() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    variants = [
        replace(
            audit,
            checkpoint_declarations=cast(Any, list(audit.checkpoint_declarations)),
        ),
        replace(audit, slots=cast(Any, list(audit.slots))),
        replace(audit, pairs=cast(Any, list(audit.pairs))),
        replace(audit, campaign_id=ImpostorString(audit.campaign_id)),
        replace(audit, schema_version=ImpostorString(COVERAGE_SCHEMA_VERSION)),
        replace(
            audit,
            slots=(
                replace(
                    audit.slots[0], coverage_state=ImpostorString("MISSING_SNAPSHOT")
                ),
                *audit.slots[1:],
            ),
        ),
    ]
    for bad in variants:
        with pytest.raises(ValueError):
            _verify(bad, fixture)


def test_n10_swapped_primary_pair_does_not_reinterpret_audit() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    camp, arms, bindings, runs = fixture
    swapped = _campaign(arms, test_arm_id="ARM-R", comparator_arm_id="ARM-B")
    assert swapped.campaign_spec_fingerprint != camp.campaign_spec_fingerprint
    with pytest.raises(ValueError):
        verify_stage1_checkpoint_coverage_audit(
            audit=audit, campaign=swapped,
            arms=arms, bindings=bindings, expected_run_ids=runs
        )


def test_n11_absence_does_not_build_phantom_snapshots() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    assert all(s.provenance_snapshot is None for s in audit.slots)
    assert audit.counts.unobserved_snapshots == 0


def test_n12_reduced_valid_run_set_cannot_reverify_larger_audit() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    camp, arms, bindings, _ = fixture
    reduced = (camp, arms, bindings[:2], ["RUN-001"])
    with pytest.raises(ValueError, match="manifest"):
        _verify(audit, reduced)


def test_n13_control_snapshot_does_not_change_primary_pair_count() -> None:
    fixture = _fixture(arms=[_arm_b(), _arm_r(), _arm_c()])
    camp, arms, bindings, runs = fixture
    ctrl = _snapshot(camp, arms, bindings, runs, "ARM-C")
    audit = _build(*fixture, _decls(), [ctrl])
    assert audit.counts.submitted_snapshots == 1
    assert audit.counts.declared_pairs == 6
    assert audit.counts.both_submitted_pairs == 0
    assert all(pair.pair_state == "BOTH_MISSING" for pair in audit.pairs)
    assert _verify(audit, fixture) is True


def test_n14_forged_retained_checkpoint_declaration_refused() -> None:
    fixture = _fixture()
    audit = _build(*fixture, _decls())
    first = replace(
        audit.checkpoint_declarations[0],
        checkpoint_ids=("CKPT-003", "CKPT-002", "CKPT-001"),
    )
    forged = replace(
        audit,
        checkpoint_declarations=(first, audit.checkpoint_declarations[1]),
    )
    with pytest.raises(ValueError):
        _verify(forged, fixture)
