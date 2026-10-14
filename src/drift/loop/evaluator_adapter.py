"""Trial evaluation adapters and execution interfaces (M8-2, Issue 233).

Provides genuine M2 session evaluation adapters bridging research proposals
to deterministic session execution and reference baseline strategies.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from drift.baselines.b0_cash import B0CashStrategy
from drift.baselines.b1_single_buy_and_hold import B1SingleBuyAndHoldStrategy
from drift.baselines.b2_equal_weight_buy_and_hold import (
    B2EqualWeightBuyAndHoldStrategy,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import B4MomentumStrategy
from drift.baselines.b5_low_volatility import B5LowVolatilityStrategy
from drift.baselines.runner import build_canonical_run_identity
from drift.domain.common import SHA256Hash
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    strategy_parameters_hash,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_protocol import (
    EvaluationProtocolV1,
    evaluation_protocol_hash,
)
from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.research_agent import ExperimentSpecificationProposalV1
from drift.errors import DriftError
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.scorecards.performance import (
    compute_drawdown_profile,
    compute_return_and_risk,
    compute_turnover_summary,
)

# Baseline strategy aliases
CashBaselineStrategy = B0CashStrategy
SingleBuyAndHoldBaselineStrategy = B1SingleBuyAndHoldStrategy
EqualWeightBuyAndHoldBaselineStrategy = B2EqualWeightBuyAndHoldStrategy
MonthlyEqualWeightRebalanceBaselineStrategy = B3MonthlyEqualWeightRebalanceStrategy
MomentumBaselineStrategy = B4MomentumStrategy
LowVolatilityBaselineStrategy = B5LowVolatilityStrategy


class UnknownStrategyTypeError(DriftError, ValueError):
    """Raised when an unrecognized strategy type is requested."""


class StrategyParameterValidationError(DriftError, ValueError):
    """Raised when strategy parameters fail validation for the requested baseline."""


class MockEvaluatorProductionError(DriftError, ValueError):
    """Raised when a mock evaluator is used in production mode."""


STRATEGY_REGISTRY: dict[str, type] = {
    "b0_cash": B0CashStrategy,
    "b0": B0CashStrategy,
    "cashbaselinestrategy": B0CashStrategy,
    "b0cashstrategy": B0CashStrategy,
    "b1_single_buy_and_hold": B1SingleBuyAndHoldStrategy,
    "b1": B1SingleBuyAndHoldStrategy,
    "singlebuyandholdbaselinestrategy": B1SingleBuyAndHoldStrategy,
    "b1singlebuyandholdstrategy": B1SingleBuyAndHoldStrategy,
    "b2_equal_weight_buy_and_hold": B2EqualWeightBuyAndHoldStrategy,
    "b2": B2EqualWeightBuyAndHoldStrategy,
    "equalweightbuyandholdbaselinestrategy": B2EqualWeightBuyAndHoldStrategy,
    "b2equalweightbuyandholdstrategy": B2EqualWeightBuyAndHoldStrategy,
    "b3_monthly_equal_weight_rebalance": B3MonthlyEqualWeightRebalanceStrategy,
    "b3": B3MonthlyEqualWeightRebalanceStrategy,
    "monthlyequalweightrebalancebaselinestrategy": (
        B3MonthlyEqualWeightRebalanceStrategy
    ),
    "b3monthlyequalweightrebalancestrategy": B3MonthlyEqualWeightRebalanceStrategy,
    "b4_momentum": B4MomentumStrategy,
    "b4": B4MomentumStrategy,
    "momentumbaselinestrategy": B4MomentumStrategy,
    "b4momentumstrategy": B4MomentumStrategy,
    "b5_low_volatility": B5LowVolatilityStrategy,
    "b5": B5LowVolatilityStrategy,
    "lowvolatilitybaselinestrategy": B5LowVolatilityStrategy,
    "b5lowvolatilitystrategy": B5LowVolatilityStrategy,
}


def _validate_strict_int(val: Any, param_name: str) -> int:
    """Validate that val is strictly an int (rejecting bool, float, str)."""
    if isinstance(val, bool) or not isinstance(val, int):
        raise StrategyParameterValidationError(
            f"Parameter '{param_name}' must be an integer "
            f"(parameters must be integers), got {type(val).__name__}: {val!r}"
        )
    return val


def resolve_and_instantiate_strategy(
    strategy_type: str,
    parameters: Mapping[str, Any] | None = None,
    *,
    bundle: EvaluationInputBundleV1 | None = None,
) -> Any:
    """Resolve strategy type to M3 implementation with strict parameter validation."""
    norm_key = strategy_type.strip().lower()
    strategy_cls = STRATEGY_REGISTRY.get(norm_key)
    if strategy_cls is None:
        raise UnknownStrategyTypeError(
            f"Unknown or unsupported strategy type: '{strategy_type}'."
        )

    params = dict(parameters) if parameters else {}

    if strategy_cls is B0CashStrategy:
        if params:
            raise StrategyParameterValidationError(
                f"B0CashStrategy accepts no parameters, got: {sorted(params.keys())}"
            )
        return B0CashStrategy()

    elif strategy_cls is B1SingleBuyAndHoldStrategy:
        allowed_b1 = {"target_security_id", "security_id"}
        unknown_b1 = set(params.keys()) - allowed_b1
        if unknown_b1:
            raise StrategyParameterValidationError(
                "B1SingleBuyAndHoldStrategy received unknown parameters: "
                f"{sorted(unknown_b1)}"
            )
        sec_raw = params.get("target_security_id") or params.get("security_id")
        if sec_raw is None:
            raise StrategyParameterValidationError(
                "B1 strategy requires 'target_security_id' parameter."
            )
        if isinstance(sec_raw, str):
            try:
                sec_id = UUID(sec_raw)
            except ValueError as error:
                raise StrategyParameterValidationError(
                    f"Invalid target_security_id UUID string '{sec_raw}': {error}"
                ) from error
        elif isinstance(sec_raw, UUID):
            sec_id = sec_raw
        else:
            raise StrategyParameterValidationError(
                "target_security_id must be a UUID or UUID string, "
                f"got {type(sec_raw).__name__}"
            )
        return B1SingleBuyAndHoldStrategy(target_security_id=sec_id)

    elif strategy_cls is B2EqualWeightBuyAndHoldStrategy:
        if params:
            raise StrategyParameterValidationError(
                "B2EqualWeightBuyAndHoldStrategy accepts no parameters, "
                f"got: {sorted(params.keys())}"
            )
        return B2EqualWeightBuyAndHoldStrategy()

    elif strategy_cls is B3MonthlyEqualWeightRebalanceStrategy:
        allowed_b3 = {"rebalance_dates", "rebalance_on_initial_session"}
        unknown_b3 = set(params.keys()) - allowed_b3
        if unknown_b3:
            raise StrategyParameterValidationError(
                "B3MonthlyEqualWeightRebalanceStrategy received unknown parameters: "
                f"{sorted(unknown_b3)}"
            )
        rebalance_dates = params.get("rebalance_dates")
        dates_arg: tuple[date, ...] | None = None
        if rebalance_dates is not None:
            if not isinstance(rebalance_dates, Sequence) or isinstance(
                rebalance_dates, (str, bytes)
            ):
                raise StrategyParameterValidationError(
                    "rebalance_dates must be a sequence of date objects or strings."
                )
            parsed_dates = []
            for item in rebalance_dates:
                if isinstance(item, str):
                    try:
                        parsed_dates.append(date.fromisoformat(item))
                    except ValueError as error:
                        raise StrategyParameterValidationError(
                            f"Invalid rebalance date string '{item}': {error}"
                        ) from error
                elif isinstance(item, date):
                    parsed_dates.append(item)
                else:
                    raise StrategyParameterValidationError(
                        "rebalance date must be date or ISO string, "
                        f"got {type(item).__name__}"
                    )
            dates_arg = tuple(parsed_dates)
        rebal_initial = params.get("rebalance_on_initial_session", True)
        if not isinstance(rebal_initial, bool):
            raise StrategyParameterValidationError(
                "rebalance_on_initial_session must be bool, "
                f"got {type(rebal_initial).__name__}"
            )
        return B3MonthlyEqualWeightRebalanceStrategy(
            rebalance_dates=dates_arg,
            rebalance_on_initial_session=rebal_initial,
        )

    elif strategy_cls is B4MomentumStrategy:
        allowed_b4 = {"formation_sessions", "skip_sessions", "min_eligible_count"}
        unknown_b4 = set(params.keys()) - allowed_b4
        if unknown_b4:
            raise StrategyParameterValidationError(
                f"B4MomentumStrategy received unknown parameters: {sorted(unknown_b4)}"
            )
        formation = params.get("formation_sessions", 252)
        skip = params.get("skip_sessions", 21)
        min_eligible = params.get("min_eligible_count", 2)
        formation_int = _validate_strict_int(formation, "formation_sessions")
        skip_int = _validate_strict_int(skip, "skip_sessions")
        min_eligible_int = _validate_strict_int(min_eligible, "min_eligible_count")
        if formation_int <= 0 or skip_int < 0 or min_eligible_int <= 0:
            raise StrategyParameterValidationError(
                "B4 parameters must be positive (formation > 0, "
                "min_eligible > 0, skip >= 0)"
            )
        return B4MomentumStrategy(
            formation_sessions=formation_int,
            skip_sessions=skip_int,
            min_eligible_count=min_eligible_int,
        )

    elif strategy_cls is B5LowVolatilityStrategy:
        allowed_b5 = {"lookback_returns", "min_eligible_count"}
        unknown_b5 = set(params.keys()) - allowed_b5
        if unknown_b5:
            raise StrategyParameterValidationError(
                "B5LowVolatilityStrategy received unknown parameters: "
                f"{sorted(unknown_b5)}"
            )
        lookback = params.get("lookback_returns", 60)
        min_eligible = params.get("min_eligible_count", 2)
        lookback_int = _validate_strict_int(lookback, "lookback_returns")
        min_eligible_int = _validate_strict_int(min_eligible, "min_eligible_count")
        if lookback_int <= 0 or min_eligible_int <= 0:
            raise StrategyParameterValidationError(
                "B5 parameters must be positive (lookback > 0, min_eligible > 0)"
            )
        return B5LowVolatilityStrategy(
            lookback_returns=lookback_int,
            min_eligible_count=min_eligible_int,
        )

    raise UnknownStrategyTypeError(f"Unsupported strategy class: {strategy_cls}")


def build_default_exploratory_admission(
    bundle: EvaluationInputBundleV1,
    limitations: tuple[str, ...] | None = None,
) -> ExploratoryEvaluationAdmissionV1:
    """Construct a canonical exploratory admission for the given bundle."""
    acknowledged = (
        tuple(sorted({*bundle.required_limitations, ALPACA_LIMITATION_BOUNDED_COHORT}))
        if limitations is None
        else tuple(sorted(limitations))
    )
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=acknowledged,
        admission_hash="0" * 64,
    )
    return ExploratoryEvaluationAdmissionV1.model_validate(
        draft.model_copy(
            update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
        ).model_dump()
    )


def build_default_evaluation_protocol(
    *,
    initial_cash: Decimal = Decimal("10000.00"),
    warmup_session_count: int = 1,
    protocol_id: str = "drift-m2-protocol-v1",
) -> EvaluationProtocolV1:
    """Construct a canonical evaluation protocol with explicit initial cash."""
    draft = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id=protocol_id,
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=warmup_session_count,
        initial_cash=initial_cash,
        protocol_hash="0" * 64,
    )
    return draft.model_copy(update={"protocol_hash": evaluation_protocol_hash(draft)})


def build_zero_cost_model(
    model_id: str = "drift-m2-zero-cost-v1",
) -> EvaluationCostModelV1:
    """Construct a zero-friction cost model."""
    draft = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id=model_id,
        commission_per_share=Decimal("0.00"),
        fixed_fee_per_order=Decimal("0.00"),
        notional_fee_basis_points=Decimal("0"),
        adverse_slippage_basis_points=Decimal("0"),
        cost_model_hash="0" * 64,
    )
    return draft.model_copy(
        update={"cost_model_hash": evaluation_cost_model_hash(draft)}
    )


@dataclass(frozen=True)
class ExecutionConfigurationV2:
    """Execution and evaluation configuration binding genuine M2 engine inputs."""

    bundle: EvaluationInputBundleV1
    admission: EvaluationAdmissionV1
    protocol: EvaluationProtocolV1
    cost_model: EvaluationCostModelV1
    evidence: SessionEvaluatorEvidence
    book_currency_namespace: str = "ISO-4217"
    book_currency_code: str = "USD"
    environment_closure_hash: SHA256Hash = "0" * 64
    code_version_hash: SHA256Hash | None = None


@runtime_checkable
class TrialEvaluatorProtocol(Protocol):
    """Protocol implemented by quantitative trial evaluation engines."""

    def evaluate_experiment(
        self,
        experiment: ExperimentSpecificationProposalV1,
    ) -> Mapping[str, Any]:
        """Execute experiment evaluation and return evaluated headline metrics."""
        ...


class M2TrialEvaluatorAdapter:
    """Authentic trial evaluator adapter executing proposals via SessionEvaluatorEngine.

    Bridges proposals to genuine M2 deterministic session evaluation
    and M3 baseline strategies. Produces empirical headline metrics and fails closed
    on non-complete or indeterminate evaluations without fabricating metrics.
    """

    is_mock: bool = False
    is_synthetic: bool = False

    def __init__(
        self,
        *,
        engine: SessionEvaluatorEngine | None = None,
        execution_config: ExecutionConfigurationV2 | None = None,
        bundle: EvaluationInputBundleV1 | None = None,
        admission: EvaluationAdmissionV1 | None = None,
        protocol: EvaluationProtocolV1 | None = None,
        cost_model: EvaluationCostModelV1 | None = None,
        evidence: SessionEvaluatorEvidence | None = None,
        initial_cash: Decimal = Decimal("10000.00"),
        book_currency_namespace: str = "ISO-4217",
        book_currency_code: str = "USD",
        environment_closure_hash: SHA256Hash = "0" * 64,
        code_version_hash: SHA256Hash | None = None,
    ) -> None:
        self._environment_closure_hash = environment_closure_hash
        self._code_version_hash = code_version_hash

        if engine is not None:
            self._engine = engine
        elif execution_config is not None:
            self._environment_closure_hash = execution_config.environment_closure_hash
            self._code_version_hash = execution_config.code_version_hash
            self._engine = SessionEvaluatorEngine(
                bundle=execution_config.bundle,
                admission=execution_config.admission,
                protocol=execution_config.protocol,
                cost_model=execution_config.cost_model,
                evidence=execution_config.evidence,
                book_currency_namespace=execution_config.book_currency_namespace,
                book_currency_code=execution_config.book_currency_code,
            )
        elif bundle is not None:
            res_admission = (
                admission
                if admission is not None
                else build_default_exploratory_admission(bundle)
            )
            res_protocol = (
                protocol
                if protocol is not None
                else build_default_evaluation_protocol(initial_cash=initial_cash)
            )
            res_cost = cost_model if cost_model is not None else build_zero_cost_model()
            res_evidence = (
                evidence if evidence is not None else SessionEvaluatorEvidence()
            )
            self._engine = SessionEvaluatorEngine(
                bundle=bundle,
                admission=res_admission,
                protocol=res_protocol,
                cost_model=res_cost,
                evidence=res_evidence,
                book_currency_namespace=book_currency_namespace,
                book_currency_code=book_currency_code,
            )
        else:
            raise ValueError(
                "M2TrialEvaluatorAdapter requires engine, execution_config, or bundle."
            )

    @property
    def engine(self) -> SessionEvaluatorEngine:
        """Underlying SessionEvaluatorEngine instance."""
        return self._engine

    def evaluate_experiment(
        self,
        experiment: ExperimentSpecificationProposalV1,
    ) -> Mapping[str, Any]:
        """Execute genuine M2 evaluation for the proposed strategy and parameters."""
        # 1. Resolve strategy from registry and validate parameters
        strategy = resolve_and_instantiate_strategy(
            strategy_type=experiment.strategy_type,
            parameters=(
                experiment.proposed_parameters
                if isinstance(experiment.proposed_parameters, Mapping)
                else None
            ),
            bundle=self._engine.bundle,
        )

        # 2. Build canonical run identity V2
        ref = strategy.strategy_reference
        params = getattr(strategy, "strategy_parameters", {})
        param_hash = strategy_parameters_hash(
            params, label="the trial strategy parameters"
        )
        run_identity = build_canonical_run_identity(
            strategy_hash=ref.code_hash,
            strategy_parameters_hash=param_hash,
            protocol_hash=self._engine.protocol.protocol_hash,
            cost_model_hash=self._engine.cost_model.cost_model_hash,
            admission=self._engine.admission,
            bundle=self._engine.bundle,
            evaluator_evidence_hash=self._engine.evaluator_evidence_hash,
            environment_closure_hash=self._environment_closure_hash,
            code_version_hash=self._code_version_hash,
        )

        # 3. Execute genuine SessionEvaluatorEngine
        artifacts = self._engine.run(strategy=strategy, run_identity=run_identity)
        result = artifacts.result

        # 4. Handle outcomes
        if result.classification == EvaluationClassification.COMPLETE:
            metrics = result.metrics
            equity_series = metrics.equity_series
            initial_nav = metrics.initial_net_asset_value

            session_returns: list[Decimal] = []
            prev_nav = initial_nav
            for pt in equity_series:
                if prev_nav > Decimal("0"):
                    ret = (pt.net_asset_value - prev_nav) / prev_nav
                else:
                    ret = Decimal("0")
                session_returns.append(ret)
                prev_nav = pt.net_asset_value

            _, ann_ret, ann_vol, _, sharpe, _, _ = compute_return_and_risk(
                equity_series, initial_nav=initial_nav
            )
            drawdown_prof = compute_drawdown_profile(
                equity_series, initial_nav=initial_nav
            )
            mdd = abs(drawdown_prof.maximum_drawdown)
            turnover_summary = compute_turnover_summary(metrics)
            ann_turnover = turnover_summary.annualized_turnover
            is_pnl_complete = metrics.realized_pnl_completeness.is_complete

            return {
                "classification": "complete",
                "annualized_sharpe": sharpe,
                "annualized_return": ann_ret,
                "annualized_volatility": ann_vol,
                "max_drawdown": mdd,
                "annualized_turnover": ann_turnover,
                "session_returns": tuple(session_returns),
                "is_pnl_complete": is_pnl_complete,
                "initial_cash": metrics.initial_cash,
                "ending_cash": metrics.ending_cash,
                "initial_net_asset_value": metrics.initial_net_asset_value,
                "ending_net_asset_value": metrics.ending_net_asset_value,
                "net_profit_and_loss": metrics.net_profit_and_loss,
                "evaluated_session_count": metrics.evaluated_session_count,
                "bundle_hash": self._engine.bundle.bundle_hash,
                "run_identity_hash": run_identity.run_identity_hash,
                "strategy_hash": run_identity.strategy_hash,
                "strategy_parameters_hash": run_identity.strategy_parameters_hash,
                "cost_model_hash": self._engine.cost_model.cost_model_hash,
                "protocol_hash": self._engine.protocol.protocol_hash,
                "result_hash": getattr(result, "result_hash", None),
                "trace_hash": (
                    getattr(artifacts.trace, "trace_hash", None)
                    if hasattr(artifacts, "trace")
                    else None
                ),
                "session_keys": tuple(
                    f"{s.session_key.mic}:{s.session_key.local_date.isoformat()}"
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "session_dates": tuple(
                    s.session_key.local_date
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "is_mock": False,
                "is_synthetic": False,
            }

        elif result.classification == EvaluationClassification.INDETERMINATE:
            return {
                "classification": "indeterminate",
                "is_indeterminate": True,
                "halt_reason": result.halt_reason,
                "annualized_sharpe": None,
                "max_drawdown": None,
                "annualized_turnover": None,
                "session_returns": (),
                "is_pnl_complete": False,
                "bundle_hash": self._engine.bundle.bundle_hash,
                "run_identity_hash": run_identity.run_identity_hash,
                "strategy_hash": run_identity.strategy_hash,
                "strategy_parameters_hash": run_identity.strategy_parameters_hash,
                "cost_model_hash": self._engine.cost_model.cost_model_hash,
                "protocol_hash": self._engine.protocol.protocol_hash,
                "result_hash": getattr(result, "result_hash", None),
                "trace_hash": (
                    getattr(artifacts.trace, "trace_hash", None)
                    if hasattr(artifacts, "trace")
                    else None
                ),
                "session_keys": tuple(
                    f"{s.session_key.mic}:{s.session_key.local_date.isoformat()}"
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "session_dates": tuple(
                    s.session_key.local_date
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "is_mock": False,
                "is_synthetic": False,
            }

        else:
            return {
                "classification": "rejected",
                "is_rejected": True,
                "halt_reason": result.halt_reason,
                "annualized_sharpe": None,
                "max_drawdown": None,
                "annualized_turnover": None,
                "session_returns": (),
                "is_pnl_complete": False,
                "bundle_hash": self._engine.bundle.bundle_hash,
                "run_identity_hash": run_identity.run_identity_hash,
                "strategy_hash": run_identity.strategy_hash,
                "strategy_parameters_hash": run_identity.strategy_parameters_hash,
                "cost_model_hash": self._engine.cost_model.cost_model_hash,
                "protocol_hash": self._engine.protocol.protocol_hash,
                "result_hash": getattr(result, "result_hash", None),
                "trace_hash": (
                    getattr(artifacts.trace, "trace_hash", None)
                    if hasattr(artifacts, "trace")
                    else None
                ),
                "session_keys": tuple(
                    f"{s.session_key.mic}:{s.session_key.local_date.isoformat()}"
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "session_dates": tuple(
                    s.session_key.local_date
                    for s in self._engine.bundle.session_clock.sessions
                ),
                "is_mock": False,
                "is_synthetic": False,
            }


class DeterministicMockTrialEvaluator:
    """Deterministic mock evaluator producing reproducible simulation metrics.

    FOR UNIT TEST USE ONLY. Requires mock=True and cannot be used in production.
    """

    is_mock: bool = True
    is_synthetic: bool = True

    def __init__(
        self,
        metric_overrides: Mapping[str, Mapping[str, Any]] | None = None,
        eval_fn: Callable[[ExperimentSpecificationProposalV1], Mapping[str, Any]]
        | None = None,
        default_metrics: Mapping[str, Any] | None = None,
        *,
        mock: bool = True,
    ) -> None:
        if not mock:
            raise MockEvaluatorProductionError(
                "DeterministicMockTrialEvaluator requires mock=True and cannot "
                "be used in production mode."
            )
        self.mock = mock
        self.metric_overrides = dict(metric_overrides) if metric_overrides else {}
        self.eval_fn = eval_fn
        self.default_metrics = dict(default_metrics) if default_metrics else None

    def evaluate_experiment(
        self,
        experiment: ExperimentSpecificationProposalV1,
    ) -> Mapping[str, Any]:
        """Return deterministic metrics for an experiment specification."""
        if self.eval_fn is not None:
            res = dict(self.eval_fn(experiment))
            res["is_mock"] = True
            res["is_synthetic"] = True
            return res

        param_hash = experiment.parameters_hash
        if param_hash in self.metric_overrides:
            res = dict(self.metric_overrides[param_hash])
            res["is_mock"] = True
            res["is_synthetic"] = True
            return res

        if self.default_metrics is not None:
            res = dict(self.default_metrics)
            res.setdefault("is_pnl_complete", True)
            res["is_mock"] = True
            res["is_synthetic"] = True
            return res

        int_seed = int(param_hash[:8], 16)
        sharpe = Decimal(str(round(0.40 + (int_seed % 100) / 100.0, 4)))
        drawdown = Decimal(str(round(0.10 + (int_seed % 15) / 100.0, 4)))
        turnover = Decimal(str(round(2.0 + (int_seed % 30) / 10.0, 4)))

        return {
            "annualized_sharpe": sharpe,
            "max_drawdown": drawdown,
            "annualized_turnover": turnover,
            "is_pnl_complete": True,
            "is_mock": True,
            "is_synthetic": True,
        }
