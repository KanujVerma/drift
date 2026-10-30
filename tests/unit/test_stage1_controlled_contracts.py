"""Original producer observation and controlled synthetic contract tests."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_stage1_synthetic_research_execution import make_harness, proposal

from drift.intelligence.contracts import ArtifactReference, TrustedInvocationBinding
from drift.intelligence.conventional_selector import select_conventional_candidate
from drift.intelligence.proposal_producer import (
    FakeTransport,
    produce_proposal,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import ResolvedDependencies, ValidationResult
from drift.loop.stage1_synthetic_research_execution import (
    installed_strategy_registration,
)


def producer_arguments(root: Path) -> dict[str, Any]:
    harness = make_harness(root)
    context = harness["context"]
    return {
        "context": context,
        "resolved_inputs": ResolvedDependencies(
            portfolio_ref=context.portfolio_ref,
            mandate_ref=context.mandate_ref,
            universe_ref=context.universe_ref,
            registry_ref=context.registry_ref,
            method_ref=context.method_ref,
            admitted_securities=tuple(
                str(item.security_id)
                for item in harness["engine"].bundle.security_identities
            ),
            strategy_registry={"B3": installed_strategy_registration("B3")},
        ),
        "validation_policy": ArtifactReference(
            id="synthetic:policy", version="1", sha256="a" * 64
        ),
        "attempt_id": "attempt-original",
        "logical_request_id": "request-original",
        "checked_at": harness["clock"](),
    }


def test_actual_original_validation_observed_before_terminal(tmp_path: Path) -> None:
    args = producer_arguments(tmp_path)
    recorder = ResearchReceiptStore()
    seen: list[tuple[str, TrustedInvocationBinding, ValidationResult]] = []

    def observe(
        raw: str, binding: TrustedInvocationBinding, result: ValidationResult
    ) -> None:
        latest = recorder.get_latest_attempt(binding.attempt_id)
        assert latest is not None and latest.status == "started"
        seen.append((raw, binding, result))
        object.__setattr__(binding, "candidate_id", "tampered")
        object.__setattr__(result, "is_valid", False)

    result = produce_proposal(
        **args,
        frozen_method=args["context"].method_ref,
        recorder=recorder,
        transport=FakeTransport(raw_choice=proposal()),
        validation_observer=observe,
    )
    assert result.is_success
    assert result.candidate is not None and result.candidate.candidate_id != "tampered"
    assert len(seen) == 1 and '"family_id":"B3"' in seen[0][0]
    terminal = recorder.get_latest_attempt("attempt-original")
    assert terminal is not None and terminal.status == "completed"


def test_original_validation_retention_failure_keeps_started_not_completed(
    tmp_path: Path,
) -> None:
    args = producer_arguments(tmp_path)
    recorder = ResearchReceiptStore()

    def fail(
        raw: str, binding: TrustedInvocationBinding, result: ValidationResult
    ) -> None:
        raise OSError("synthetic uncertain retention")

    with pytest.raises(OSError, match="uncertain retention"):
        produce_proposal(
            **args,
            frozen_method=args["context"].method_ref,
            recorder=recorder,
            transport=FakeTransport(raw_choice=proposal()),
            validation_observer=fail,
        )
    events = recorder.get_attempt_events("attempt-original")
    assert len(events) == 1 and events[0].status == "started"
    assert len(recorder.get_cost_receipts_for_attempt("attempt-original")) == 1


def test_conventional_selector_observes_its_actual_validation(tmp_path: Path) -> None:
    args = producer_arguments(tmp_path)
    recorder = ResearchReceiptStore()
    seen: list[ValidationResult] = []

    def observe(
        raw: str, binding: TrustedInvocationBinding, result: ValidationResult
    ) -> None:
        latest = recorder.get_latest_attempt(binding.attempt_id)
        assert latest is not None and latest.status == "started"
        assert raw and binding.producer == "conventional_selector"
        seen.append(result)

    result = select_conventional_candidate(
        **args,
        method_ref=args["context"].method_ref,
        recorder=recorder,
        candidate_pool=(proposal(),),
        objective_fn=lambda _: Decimal("1"),
        validation_observer=observe,
    )
    assert result.is_success and len(seen) == 1 and seen[0].is_valid
    assert seen[0].candidate == result.selected_candidate


def controlled_arguments(
    tmp_path: Path, *, arm: str = "ARM-B", engine: Any = None
) -> dict[str, Any]:
    from datetime import timedelta

    from test_stage1_synthetic_research_execution import BASE, make_harness

    from drift.loop import stage1_controlled_contracts as C

    harness = make_harness(tmp_path, arm=arm, engine=engine)
    evaluator = harness["engine"]
    ids = tuple(
        sorted(
            (s.security_id for s in evaluator.bundle.security_identities),
            key=lambda s: s.bytes,
        )
    )
    policy = C.SyntheticMandateV1(
        policy_id="synthetic:explicit-unit-mandate",
        revision="1",
        securities=tuple(
            C.SecurityMandateV1(
                security_id=s, asset_class="synthetic", maximum_fraction=Decimal("1")
            )
            for s in ids
        ),
        classes=(
            C.ClassMandateV1(asset_class="synthetic", maximum_fraction=Decimal("1")),
        ),
        maximum_gross_fraction=Decimal("1"),
        maximum_turnover_fraction=Decimal("2"),
        maximum_price_age_sessions=0,
        paused=False,
        execution_knowledge="RESOLVED",
    )
    index = evaluator.protocol.warmup_session_count
    checkpoint = C.ControlledCheckpointV1(
        checkpoint_id="CKPT-001",
        session_index=index,
        decision_cutoff=evaluator.bundle.session_clock.sessions[index].closed_at,
        not_before=BASE,
        expires_at=BASE + timedelta(days=1),
        research_budget_usd=Decimal("10"),
        fixture=C.ControlledResearchFixtureV1(
            mode="scripted_fixture",
            disposition="propose",
            selected_family="B3",
            candidate_families=(),
            scores={},
            cost_amount=Decimal("0"),
        ),
    )
    return harness | {
        "mandate": policy,
        "checkpoints": (checkpoint,),
        "initial_decision_index": index - 1,
        "coverage": "DEVELOPMENT",
        "clock_policy": ArtifactReference(
            id="synthetic:tick-clock", version="1", sha256="1" * 64
        ),
    }


@pytest.fixture
def declared_window_plan(tmp_path: Path) -> tuple[Any, Any, Any]:
    """Pure E1/profile-window control, not an executed 456-session claim."""
    from dataclasses import replace
    from datetime import UTC, date, datetime, time, timedelta

    from drift.domain.evaluator_clock import EvaluationSessionV1
    from drift.experiments.stage1_campaign_config import DataWindowV1, ScoringWindowV1
    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.serialization.canonical import canonical_json, content_hash

    args = controlled_arguments(tmp_path)
    execution = execute_controlled_campaign(**args)
    original = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    ).plan
    sessions: list[EvaluationSessionV1] = []
    day = date(2024, 1, 2)
    while len(sessions) < 456:
        if day.weekday() < 5:
            payload = original.sessions[0].model_dump(mode="python")
            payload["session_key"]["local_date"] = day
            payload["opened_at"] = datetime.combine(day, time(14, 30), UTC)
            payload["closed_at"] = datetime.combine(day, time(21), UTC)
            payload.pop("session_hash")
            payload["session_hash"] = content_hash(payload)
            sessions.append(EvaluationSessionV1.model_validate(payload))
        day += timedelta(days=1)
    checkpoints = tuple(
        original.checkpoints[0].model_copy(
            update={
                "checkpoint_id": f"CKPT-{number:03d}",
                "session_index": index,
                "decision_cutoff": sessions[index].closed_at,
            }
        )
        for number, index in enumerate((412, 433), 1)
    )
    payload = original.model_dump(mode="python")
    payload.update(
        sessions=tuple(sessions),
        initial_decision_index=378,
        checkpoints=checkpoints,
        coverage="STAGE1_253_126_MONTHLY",
    )
    plan = C.ControlledCampaignPlanV1.model_validate_json(canonical_json(payload))
    # These objects isolate schedule-policy coupling. Original E1 fingerprint
    # verification is a separate exercised production boundary, not bypassed here.
    campaign = replace(
        args["campaign"],
        data_window=DataWindowV1("2024-01-02", "2025-09-30", "fixture:clock"),
        scoring_window=ScoringWindowV1("SC-001", "SC-077", True),
        portfolio_mandate_reference=plan.mandate.policy_id,
    )
    arms = tuple(
        replace(arm, mandate_reference=plan.mandate.policy_id) for arm in args["arms"]
    )
    return plan, campaign, arms


def test_declared_full_window_and_policy_mapping_positive(
    declared_window_plan: tuple[Any, Any, Any],
) -> None:
    from drift.loop.stage1_controlled_contracts import verify_declared_stage1_plan

    verify_declared_stage1_plan(*declared_window_plan)


@pytest.mark.parametrize("changed", ["start", "end", "scoring", "mandate", "selector"])
def test_declared_full_profile_rejects_contradictory_e1_fields(
    declared_window_plan: tuple[Any, Any, Any], changed: str
) -> None:
    from dataclasses import replace

    from drift.loop.stage1_controlled_contracts import verify_declared_stage1_plan

    plan, campaign, arms = declared_window_plan
    if changed in ("start", "end"):
        campaign = replace(
            campaign,
            data_window=replace(
                campaign.data_window,
                **{f"{changed}_date": "2025-01-01"},
            ),
        )
    elif changed == "scoring":
        campaign = replace(
            campaign,
            scoring_window=replace(campaign.scoring_window, end_session="SC-078"),
        )
    elif changed == "mandate":
        campaign = replace(campaign, portfolio_mandate_reference="different-policy")
    else:
        arms = tuple(
            replace(arm, selector_type="DETERMINISTIC_COMPARATOR") for arm in arms
        )
    with pytest.raises(ValueError, match="CONTROLLED_STAGE1_.*_NOT_DECLARED_E1"):
        verify_declared_stage1_plan(plan, campaign, arms)
