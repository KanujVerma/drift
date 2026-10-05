"""Trial evaluation adapters and execution interfaces (M8-2, Issue 233).

Provides the protocol for executing quantitative experiments proposed by
research agents and producing evaluated headline performance metrics.
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from drift.domain.research_agent import ExperimentSpecificationProposalV1


@runtime_checkable
class TrialEvaluatorProtocol(Protocol):
    """Protocol implemented by quantitative trial evaluation engines."""

    def evaluate_experiment(
        self,
        experiment: ExperimentSpecificationProposalV1,
    ) -> Mapping[str, Any]:
        """Execute experiment evaluation and return evaluated headline metrics."""
        ...


class DeterministicMockTrialEvaluator:
    """Deterministic mock evaluator producing reproducible simulation metrics."""

    def __init__(
        self,
        metric_overrides: Mapping[str, Mapping[str, Any]] | None = None,
        eval_fn: Callable[[ExperimentSpecificationProposalV1], Mapping[str, Any]]
        | None = None,
    ) -> None:
        self.metric_overrides = dict(metric_overrides) if metric_overrides else {}
        self.eval_fn = eval_fn

    def evaluate_experiment(
        self,
        experiment: ExperimentSpecificationProposalV1,
    ) -> Mapping[str, Any]:
        """Return deterministic metrics for an experiment specification."""
        if self.eval_fn is not None:
            return self.eval_fn(experiment)

        param_hash = experiment.parameters_hash
        if param_hash in self.metric_overrides:
            return self.metric_overrides[param_hash]

        # Deterministic synthetic metrics derived from parameters hash
        int_seed = int(param_hash[:8], 16)
        sharpe = Decimal(str(round(0.40 + (int_seed % 100) / 100.0, 4)))
        drawdown = Decimal(str(round(0.10 + (int_seed % 15) / 100.0, 4)))
        turnover = Decimal(str(round(2.0 + (int_seed % 30) / 10.0, 4)))

        return {
            "annualized_sharpe": sharpe,
            "max_drawdown": drawdown,
            "annualized_turnover": turnover,
        }
