"""Unit tests for deterministic proposal validator and gatekeeper (M7-3, Issue 221)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import (
    ProposalValidationStatus,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_memory import (
    FailureCategory,
    TrialOutcome,
    build_failure_postmortem,
    build_parameter_search_space,
    build_research_trial_record,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
HYPOTHESIS_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")


def test_valid_proposal_accepted(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        title="Momentum with weekly rebalance",
        economic_rationale="Medium term trend persistence",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_sessions": 20},
        universe_id="sp500",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert res.is_accepted is True
    assert res.status == ProposalValidationStatus.ACCEPTED
    assert len(res.rejection_reasons) == 0


def test_insufficient_falsification_criteria(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        title="Weak hypothesis",
        economic_rationale="Weak criteria",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.10"),  # below 0.20
        max_drawdown_limit=Decimal("0.60"),  # above 0.50
        max_turnover_limit=Decimal("25.00"),  # above 20.00
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_sessions": 20},
        universe_id="sp500",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_INSUFFICIENT_CRITERIA
    assert len(res.rejection_reasons) == 3


def test_duplicate_parameters_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    params = {"lookback_sessions": 20}
    t = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd10"),
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters=params,
        headline_metrics={"sharpe_ratio": "0.80"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    recorder.record_trial(t)

    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_2,
        title="Duplicate proposal",
        economic_rationale="Testing duplicate",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_2,
        strategy_type="b4_momentum",
        proposed_parameters=params,
        universe_id="sp500",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_DUPLICATE_PARAMETERS
    assert "already been evaluated" in res.rejection_reasons[0]


def test_forbidden_variation_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    pm = build_failure_postmortem(
        postmortem_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd20"),
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Turnover drag failure",
        lessons_learned="Avoid unhedged intraday rebalance",
        forbidden_variations=("intraday_rebalance",),
        created_at=TIMESTAMP,
    )
    recorder.record_postmortem(pm)

    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        title="Intraday proposal",
        economic_rationale="Testing forbidden",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"mode": "intraday_rebalance", "lookback": 5},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION
    assert "violates diagnosed failure variation" in res.rejection_reasons[0]


def test_circular_and_invalid_parent_lineage(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    # Self reference
    hyp_self = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        parent_hypothesis_id=HYPOTHESIS_ID_1,
        title="Self ref",
        economic_rationale="Self",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback": 20},
        universe_id="sp500",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    res_self = validator.validate_proposal(
        hypothesis=hyp_self,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )
    assert res_self.status == ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE

    # Non-existent parent
    hyp_unknown = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        parent_hypothesis_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        title="Unknown parent",
        economic_rationale="Unknown",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    res_unknown = validator.validate_proposal(
        hypothesis=hyp_unknown,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )
    assert res_unknown.status == ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE


def test_out_of_bounds_search_space(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)

    space = build_parameter_search_space(
        search_space_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd30"),
        strategy_type="b4_momentum",
        dimension_names=("lookback_sessions", "holding_sessions"),
        created_at=TIMESTAMP,
    )
    validator = ProposalValidator(archive, search_spaces={"b4_momentum": space})

    # Missing holding_sessions dimension
    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID_1,
        title="Missing dim",
        economic_rationale="Missing",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("4.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_sessions": 20},  # missing holding_sessions
        universe_id="sp500",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert "Missing required parameter dimension" in res.rejection_reasons[0]
