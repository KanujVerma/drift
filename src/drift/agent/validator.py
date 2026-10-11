"""Deterministic proposal validator and gatekeeper (M7-3, Issue 221).

Enforces strict research invariants on untrusted agent proposals:
- Parameter deduplication against historical research trials.
- Forbidden variation constraints from diagnosed failure postmortems.
- Dimension coverage against registered parameter search spaces.
- Non-circular hypothesis lineage and ancestor existence.
- Minimum falsification criteria stringency.
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from drift.domain.common import UTCDateTime
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ProposalValidationResultV1,
    ProposalValidationStatus,
    build_proposal_validation_result,
)
from drift.domain.research_memory import ParameterSearchSpaceV1
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import deterministic_memory_uuid7

# Falsification stringency bounds
MIN_REQUIRED_SHARPE = Decimal("0.20")
MAX_ALLOWED_DRAWDOWN = Decimal("0.50")
MAX_ALLOWED_TURNOVER = Decimal("20.00")


class ProposalValidator:
    """Deterministic validation firewall for untrusted research agent proposals."""

    def __init__(
        self,
        archive: ResearchMemoryArchive,
        search_spaces: Mapping[str, ParameterSearchSpaceV1] | None = None,
    ) -> None:
        self.archive = archive
        self.search_spaces = dict(search_spaces) if search_spaces else {}

    def validate_proposal(
        self,
        *,
        hypothesis: HypothesisProposalV1,
        experiment: ExperimentSpecificationProposalV1,
        as_of_time: UTCDateTime,
        validation_id: UUID | None = None,
    ) -> ProposalValidationResultV1:
        """Validate an agent hypothesis and experiment specification proposal."""
        val_id = validation_id or deterministic_memory_uuid7(
            f"{hypothesis.proposal_id}:validation:{as_of_time.isoformat()}"
        )
        rejection_reasons: list[str] = []

        # 1. Circular Lineage / Ancestor Check
        if hypothesis.parent_hypothesis_id is not None:
            if hypothesis.parent_hypothesis_id == hypothesis.proposal_id:
                rejection_reasons.append("Hypothesis parent cannot reference itself")
                return build_proposal_validation_result(
                    validation_id=val_id,
                    proposal_id=hypothesis.proposal_id,
                    status=ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE,
                    is_accepted=False,
                    rejection_reasons=tuple(rejection_reasons),
                    evaluated_at=as_of_time,
                )
            parent = self.archive._hypotheses.get(hypothesis.parent_hypothesis_id)
            if parent is None:
                rejection_reasons.append(
                    f"Parent hypothesis {hypothesis.parent_hypothesis_id} "
                    f"does not exist in archive"
                )
                return build_proposal_validation_result(
                    validation_id=val_id,
                    proposal_id=hypothesis.proposal_id,
                    status=ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE,
                    is_accepted=False,
                    rejection_reasons=tuple(rejection_reasons),
                    evaluated_at=as_of_time,
                )

        # 2. Falsification Criteria Stringency Check
        if hypothesis.min_annualized_sharpe < MIN_REQUIRED_SHARPE:
            rejection_reasons.append(
                f"min_annualized_sharpe ({hypothesis.min_annualized_sharpe}) "
                f"is below required minimum {MIN_REQUIRED_SHARPE}"
            )
        if hypothesis.max_drawdown_limit > MAX_ALLOWED_DRAWDOWN:
            rejection_reasons.append(
                f"max_drawdown_limit ({hypothesis.max_drawdown_limit}) "
                f"exceeds maximum permitted {MAX_ALLOWED_DRAWDOWN}"
            )
        if hypothesis.max_turnover_limit > MAX_ALLOWED_TURNOVER:
            rejection_reasons.append(
                f"max_turnover_limit ({hypothesis.max_turnover_limit}) "
                f"exceeds maximum permitted {MAX_ALLOWED_TURNOVER}"
            )
        if rejection_reasons:
            return build_proposal_validation_result(
                validation_id=val_id,
                proposal_id=hypothesis.proposal_id,
                status=ProposalValidationStatus.REJECTED_INSUFFICIENT_CRITERIA,
                is_accepted=False,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=as_of_time,
            )

        # 2b. Hypothesis and Experiment Target Strategy Alignment
        if hypothesis.target_strategy_type != experiment.strategy_type:
            rejection_reasons.append(
                f"Experiment strategy_type '{experiment.strategy_type}' does not match "
                f"hypothesis target_strategy_type '{hypothesis.target_strategy_type}'"
            )
            return build_proposal_validation_result(
                validation_id=val_id,
                proposal_id=hypothesis.proposal_id,
                status=ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS,
                is_accepted=False,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=as_of_time,
            )

        # 3. Parameter Deduplication Check
        if self.archive.is_parameter_region_evaluated(
            experiment.strategy_type, experiment.parameters_hash
        ):
            rejection_reasons.append(
                f"Parameter set {experiment.parameters_hash} for strategy "
                f"'{experiment.strategy_type}' has already been evaluated"
            )
            return build_proposal_validation_result(
                validation_id=val_id,
                proposal_id=hypothesis.proposal_id,
                status=ProposalValidationStatus.REJECTED_DUPLICATE_PARAMETERS,
                is_accepted=False,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=as_of_time,
            )

        # 4. Forbidden Variation Check
        forbidden_variations: list[str] = []
        for pm in self.archive.get_postmortems():
            forbidden_variations.extend(pm.forbidden_variations)

        if isinstance(experiment.proposed_parameters, Mapping):
            for forbidden in forbidden_variations:
                if forbidden.lower() in str(experiment.proposed_parameters).lower():
                    rejection_reasons.append(
                        f"Proposal violates diagnosed failure variation: '{forbidden}'"
                    )
        if rejection_reasons:
            return build_proposal_validation_result(
                validation_id=val_id,
                proposal_id=hypothesis.proposal_id,
                status=ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION,
                is_accepted=False,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=as_of_time,
            )

        # 5. Parameter Search Space Bounds and Constraints Check
        space = self.search_spaces.get(experiment.strategy_type)
        if space is not None:
            if space.exhaustion_fraction >= Decimal("1.0"):
                rejection_reasons.append(
                    f"Parameter search space for '{experiment.strategy_type}' "
                    f"is fully exhausted ({space.exhaustion_fraction})"
                )

        if space is not None and isinstance(experiment.proposed_parameters, Mapping):
            for dim in space.dimension_names:
                if dim not in experiment.proposed_parameters:
                    rejection_reasons.append(
                        f"Missing required parameter dimension '{dim}' for search space"
                    )
            for param_key in experiment.proposed_parameters:
                if param_key not in space.dimension_names:
                    rejection_reasons.append(
                        f"Unexpected parameter '{param_key}' not in "
                        f"search space dimensions"
                    )

        # Baseline Strategy Parameter Validation
        if isinstance(experiment.proposed_parameters, Mapping):
            strat_key = experiment.strategy_type.strip().lower()
            params = experiment.proposed_parameters
            if strat_key in ("b1", "b1_single_buy_and_hold", "b1_market_cap_weight"):
                sec_val = params.get("target_security_id") or params.get("security_id")
                if sec_val is not None:
                    if isinstance(sec_val, str):
                        try:
                            UUID(sec_val)
                        except ValueError as err:
                            rejection_reasons.append(
                                f"Invalid target_security_id UUID string '{sec_val}': "
                                f"{err}"
                            )
                    elif not isinstance(sec_val, UUID):
                        rejection_reasons.append(
                            "B1 target_security_id must be UUID or UUID string, "
                            f"got {type(sec_val)}"
                        )
            elif strat_key in ("b4", "b4_momentum"):
                for field_name in ("formation_sessions", "min_eligible_count"):
                    if field_name in params:
                        val = params[field_name]
                        if not isinstance(val, int) or val <= 0:
                            rejection_reasons.append(
                                f"B4 parameter '{field_name}' must be positive "
                                f"integer, got {val}"
                            )
                if "skip_sessions" in params:
                    val = params["skip_sessions"]
                    if not isinstance(val, int) or val < 0:
                        rejection_reasons.append(
                            "B4 parameter 'skip_sessions' must be non-negative "
                            f"integer, got {val}"
                        )
            elif strat_key in ("b5", "b5_low_volatility"):
                for field_name in ("lookback_returns", "min_eligible_count"):
                    if field_name in params:
                        val = params[field_name]
                        if not isinstance(val, int) or val <= 0:
                            rejection_reasons.append(
                                f"B5 parameter '{field_name}' must be positive "
                                f"integer, got {val}"
                            )

        if rejection_reasons:
            return build_proposal_validation_result(
                validation_id=val_id,
                proposal_id=hypothesis.proposal_id,
                status=ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS,
                is_accepted=False,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=as_of_time,
            )

        # Passed all gate checks
        return build_proposal_validation_result(
            validation_id=val_id,
            proposal_id=hypothesis.proposal_id,
            status=ProposalValidationStatus.ACCEPTED,
            is_accepted=True,
            rejection_reasons=(),
            evaluated_at=as_of_time,
        )
