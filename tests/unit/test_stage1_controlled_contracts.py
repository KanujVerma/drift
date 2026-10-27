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
