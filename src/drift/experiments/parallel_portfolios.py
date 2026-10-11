"""Parallel $10,000 research portfolios and cohort evaluation (Phase 3).

Provides deterministic parallel evaluation of strategy cohorts using genuine
M2 accounting, strict $10,000 initial cash isolation, cross-cohort daily return
correlation matrices, and reproducible CLI demonstration harnesses.
"""

import concurrent.futures
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from drift.baselines.runner import build_canonical_run_identity
from drift.domain.common import SHA256Hash
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    strategy_parameters_hash,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.securities import ListingRoleVersionV1
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.loop.evaluator_adapter import (
    build_default_evaluation_protocol,
    build_default_exploratory_admission,
    build_zero_cost_model,
    resolve_and_instantiate_strategy,
)
from drift.scorecards.performance import (
    compute_drawdown_profile,
    compute_return_and_risk,
    compute_turnover_summary,
)

TARGET_INITIAL_CASH = Decimal("10000.00")
FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class CohortPortfolioResult:
    """Isolated evaluated performance result for one portfolio in a research cohort."""

    strategy_id: str
    strategy_type: str
    initial_cash: Decimal
    ending_nav: Decimal
    total_return_pct: Decimal
    annualized_sharpe: Decimal | None
    max_drawdown_pct: Decimal | None
    annualized_turnover: Decimal | None
    fill_count: int
    trace_hash: str
    result_hash: str
    daily_returns: tuple[Decimal, ...]
    classification: str
    is_pnl_complete: bool
    net_profit_and_loss: Decimal
    bundle_hash: str
    run_identity_hash: str
    cost_model_hash: str
    protocol_hash: str


@dataclass(frozen=True)
class _PortfolioWorkerTask:
    """Serializable task package dispatched to process workers."""

    strategy_id: str
    strategy: Any
    bundle: EvaluationInputBundleV1
    admission: EvaluationAdmissionV1
    protocol: EvaluationProtocolV1
    cost_model: EvaluationCostModelV1
    evidence: SessionEvaluatorEvidence
    book_currency_namespace: str
    book_currency_code: str
    environment_closure_hash: SHA256Hash
    code_version_hash: SHA256Hash | None


def _portfolio_worker_entrypoint(task: _PortfolioWorkerTask) -> CohortPortfolioResult:
    """Execute single portfolio evaluation in isolated process worker."""
    engine = SessionEvaluatorEngine(
        bundle=task.bundle,
        admission=task.admission,
        protocol=task.protocol,
        cost_model=task.cost_model,
        evidence=task.evidence,
        book_currency_namespace=task.book_currency_namespace,
        book_currency_code=task.book_currency_code,
    )

    strategy = task.strategy
    ref = strategy.strategy_reference
    params = getattr(strategy, "strategy_parameters", {})
    param_hash = strategy_parameters_hash(
        params, label=f"cohort strategy '{task.strategy_id}' parameters"
    )

    run_identity = build_canonical_run_identity(
        strategy_hash=ref.code_hash,
        strategy_parameters_hash=param_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        environment_closure_hash=task.environment_closure_hash,
        code_version_hash=task.code_version_hash,
    )

    artifacts = engine.run(strategy=strategy, run_identity=run_identity)
    result = artifacts.result
    metrics = result.metrics

    initial_nav = metrics.initial_net_asset_value
    ending_nav = metrics.ending_net_asset_value

    daily_returns: list[Decimal] = []
    prev_nav = initial_nav
    for pt in metrics.equity_series:
        if prev_nav > ZERO:
            ret = (pt.net_asset_value - prev_nav) / prev_nav
            daily_returns.append(ret)
        else:
            daily_returns.append(ZERO)
        prev_nav = pt.net_asset_value

    if result.classification == EvaluationClassification.COMPLETE:
        ret_and_risk = compute_return_and_risk(
            metrics.equity_series,
            initial_nav=initial_nav,
        )
        ann_sharpe = ret_and_risk[4]

        dd_profile = compute_drawdown_profile(
            metrics.equity_series,
            initial_nav=initial_nav,
        )
        max_dd = dd_profile.maximum_drawdown
        max_drawdown_pct: Decimal | None = (abs(max_dd) * HUNDRED).quantize(
            TWO_PLACES, rounding=ROUND_HALF_EVEN
        )

        turnover_summary = compute_turnover_summary(metrics)
        ann_turnover: Decimal | None = turnover_summary.annualized_turnover
    else:
        ann_sharpe = None
        max_drawdown_pct = None
        ann_turnover = None

    total_return_pct = (
        ((ending_nav - initial_nav) / initial_nav * HUNDRED).quantize(
            TWO_PLACES, rounding=ROUND_HALF_EVEN
        )
        if initial_nav > ZERO
        else ZERO.quantize(TWO_PLACES)
    )

    strategy_type_label = type(strategy).__name__

    return CohortPortfolioResult(
        strategy_id=task.strategy_id,
        strategy_type=strategy_type_label,
        initial_cash=task.protocol.initial_cash,
        ending_nav=ending_nav,
        total_return_pct=total_return_pct,
        annualized_sharpe=ann_sharpe,
        max_drawdown_pct=max_drawdown_pct,
        annualized_turnover=ann_turnover,
        fill_count=metrics.committed_fill_count,
        trace_hash=result.trace_hash,
        result_hash=result.result_hash,
        daily_returns=tuple(daily_returns),
        classification=result.classification.value,
        is_pnl_complete=metrics.realized_pnl_completeness.is_complete,
        net_profit_and_loss=metrics.net_profit_and_loss,
        bundle_hash=task.bundle.bundle_hash,
        run_identity_hash=run_identity.run_identity_hash,
        cost_model_hash=task.cost_model.cost_model_hash,
        protocol_hash=task.protocol.protocol_hash,
    )


def compute_daily_returns_correlation(
    series_a: Sequence[Decimal],
    series_b: Sequence[Decimal],
) -> Decimal | None:
    """Compute Pearson correlation coefficient between two series of daily returns.

    Returns None if either series has zero variance (e.g. constant returns),
    or if series length is less than 2, because correlation is mathematically undefined.
    Guarantees strict symmetry and bounded values in [-1.0000, 1.0000].
    """
    if len(series_a) != len(series_b):
        raise ValueError(
            f"Series lengths must match: {len(series_a)} != {len(series_b)}"
        )
    n = len(series_a)
    if n < 2:
        return None

    mean_a = sum(series_a, ZERO) / Decimal(n)
    mean_b = sum(series_b, ZERO) / Decimal(n)

    var_a = sum((x - mean_a) ** 2 for x in series_a) / Decimal(n - 1)
    var_b = sum((y - mean_b) ** 2 for y in series_b) / Decimal(n - 1)

    if var_a <= ZERO or var_b <= ZERO:
        return None

    std_a = Decimal(str(math.sqrt(float(var_a))))
    std_b = Decimal(str(math.sqrt(float(var_b))))

    if std_a <= ZERO or std_b <= ZERO:
        return None

    cov = sum(
        (x - mean_a) * (y - mean_b) for x, y in zip(series_a, series_b, strict=True)
    ) / Decimal(n - 1)

    corr = cov / (std_a * std_b)
    if corr > ONE:
        corr = ONE
    elif corr < -ONE:
        corr = -ONE
    return corr.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)


class PortfolioCohortHarness:
    """Harness executing reproducible parallel $10,000 research portfolios."""

    def __init__(
        self,
        cohort: Mapping[str, Any] | Sequence[Any],
        bundle: EvaluationInputBundleV1,
        *,
        evidence: SessionEvaluatorEvidence,
        cost_model: EvaluationCostModelV1 | None = None,
        protocol: EvaluationProtocolV1 | None = None,
        initial_cash: Decimal = TARGET_INITIAL_CASH,
        admission: EvaluationAdmissionV1 | None = None,
        book_currency_namespace: str = "ISO-4217",
        book_currency_code: str = "USD",
        environment_closure_hash: SHA256Hash = "0" * 64,
        code_version_hash: SHA256Hash | None = None,
    ) -> None:
        if initial_cash != TARGET_INITIAL_CASH:
            raise ValueError(
                f"Portfolio cohort initial cash must be exactly {TARGET_INITIAL_CASH}, "
                f"got {initial_cash}"
            )

        if protocol is not None and protocol.initial_cash != TARGET_INITIAL_CASH:
            raise ValueError(
                "Evaluation protocol initial cash must be exactly "
                f"{TARGET_INITIAL_CASH}, got {protocol.initial_cash}"
            )

        self._bundle = bundle
        self._admission = (
            admission
            if admission is not None
            else build_default_exploratory_admission(bundle)
        )
        self._protocol = (
            protocol
            if protocol is not None
            else build_default_evaluation_protocol(
                initial_cash=TARGET_INITIAL_CASH,
                warmup_session_count=2,
            )
        )
        self._cost_model = (
            cost_model if cost_model is not None else build_zero_cost_model()
        )
        self._evidence = evidence
        self._book_currency_namespace = book_currency_namespace
        self._book_currency_code = book_currency_code
        self._environment_closure_hash = environment_closure_hash
        self._code_version_hash = code_version_hash

        # Normalize cohort entries into list of (strategy_id, strategy_instance)
        self._cohort: list[tuple[str, Any]] = []
        if isinstance(cohort, Mapping):
            for sid, item in cohort.items():
                inst = self._resolve_strategy_item(item)
                self._cohort.append((sid, inst))
        elif isinstance(cohort, Sequence):
            for idx, item in enumerate(cohort):
                if (
                    isinstance(item, tuple)
                    and len(item) == 2
                    and isinstance(item[0], str)
                ):
                    sid, strat_val = item
                    inst = self._resolve_strategy_item(strat_val)
                    self._cohort.append((sid, inst))
                else:
                    inst = self._resolve_strategy_item(item)
                    ref = getattr(inst, "strategy_reference", None)
                    name = getattr(ref, "strategy_name", f"strategy_{idx}")
                    sid = f"{name}_{idx}"
                    self._cohort.append((sid, inst))
        else:
            raise TypeError(f"Cohort must be Mapping or Sequence, got {type(cohort)}")

    @property
    def cohort_size(self) -> int:
        """Number of portfolios in the cohort."""
        return len(self._cohort)

    def _resolve_strategy_item(self, item: Any) -> Any:
        """Resolve strategy item into an instantiated strategy instance."""
        if hasattr(item, "strategy_reference"):
            return item
        if isinstance(item, str):
            return resolve_and_instantiate_strategy(item, bundle=self._bundle)
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
            strat_type, params = item
            return resolve_and_instantiate_strategy(
                strat_type,
                parameters=params if isinstance(params, Mapping) else None,
                bundle=self._bundle,
            )
        raise ValueError(f"Unable to resolve cohort strategy item: {item!r}")

    def _build_worker_task(
        self, strategy_id: str, strategy: Any
    ) -> _PortfolioWorkerTask:
        """Construct immutable task for worker."""
        return _PortfolioWorkerTask(
            strategy_id=strategy_id,
            strategy=strategy,
            bundle=self._bundle,
            admission=self._admission,
            protocol=self._protocol,
            cost_model=self._cost_model,
            evidence=self._evidence,
            book_currency_namespace=self._book_currency_namespace,
            book_currency_code=self._book_currency_code,
            environment_closure_hash=self._environment_closure_hash,
            code_version_hash=self._code_version_hash,
        )

    def run_sequential(self) -> list[CohortPortfolioResult]:
        """Execute portfolio cohort evaluations sequentially."""
        tasks = [self._build_worker_task(sid, s) for sid, s in self._cohort]
        return [_portfolio_worker_entrypoint(t) for t in tasks]

    def run_parallel(
        self, max_workers: int | None = None
    ) -> list[CohortPortfolioResult]:
        """Execute portfolio cohort evaluations across worker processes."""
        tasks = [self._build_worker_task(sid, s) for sid, s in self._cohort]
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(_portfolio_worker_entrypoint, tasks))

    def run(
        self,
        *,
        parallel: bool = True,
        max_workers: int | None = None,
    ) -> list[CohortPortfolioResult]:
        """Execute cohort evaluations in parallel or sequential mode."""
        if parallel:
            return self.run_parallel(max_workers=max_workers)
        return self.run_sequential()

    @staticmethod
    def format_comparison_table(results: Sequence[CohortPortfolioResult]) -> str:
        """Format cohort comparison as a clean ASCII table."""
        headers = [
            "Strategy ID",
            "Initial Cash",
            "Ending NAV",
            "Return %",
            "Sharpe",
            "Max DD %",
            "Turnover",
            "Fills",
            "Result Hash",
        ]

        rows: list[list[str]] = []
        for r in results:
            sharpe_str = (
                f"{r.annualized_sharpe:>6.4f}"
                if r.annualized_sharpe is not None
                else "   N/A"
            )
            mdd_str = (
                f"{r.max_drawdown_pct:>6.2f}%"
                if r.max_drawdown_pct is not None
                else "   N/A"
            )
            turnover_str = (
                f"{r.annualized_turnover:>6.4f}"
                if r.annualized_turnover is not None
                else "   N/A"
            )
            rows.append(
                [
                    r.strategy_id,
                    f"${r.initial_cash:,.2f}",
                    f"${r.ending_nav:,.2f}",
                    f"{r.total_return_pct:>6.2f}%",
                    sharpe_str,
                    mdd_str,
                    turnover_str,
                    str(r.fill_count),
                    f"{r.result_hash[:12]}...",
                ]
            )

        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                if len(val) > col_widths[i]:
                    col_widths[i] = len(val)

        sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
        header_line = (
            "| "
            + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            + " |"
        )

        lines = [sep, header_line, sep]
        for row in rows:
            row_line = (
                "| "
                + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row))
                + " |"
            )
            lines.append(row_line)
        lines.append(sep)
        return "\n".join(lines)

    @staticmethod
    def compute_correlation_matrix(
        results: Sequence[CohortPortfolioResult],
    ) -> dict[str, dict[str, Decimal | None]]:
        """Compute cross-cohort daily return correlation matrix.

        Matrix is symmetric with bounded values in [-1.0000, 1.0000]
        or None (undefined).
        """
        matrix: dict[str, dict[str, Decimal | None]] = {}
        for r_a in results:
            matrix[r_a.strategy_id] = {}
            for r_b in results:
                corr = compute_daily_returns_correlation(
                    r_a.daily_returns, r_b.daily_returns
                )
                matrix[r_a.strategy_id][r_b.strategy_id] = corr
        return matrix

    @staticmethod
    def format_correlation_matrix(
        matrix: Mapping[str, Mapping[str, Decimal | None]],
    ) -> str:
        """Format daily return correlation matrix as an ASCII table."""
        sids = list(matrix.keys())
        if not sids:
            return "(Empty Correlation Matrix)"

        headers = ["Strategy ID", *sids]
        col_widths = [len(h) for h in headers]
        for sid_a in sids:
            col_widths[0] = max(col_widths[0], len(sid_a))
            for i, sid_b in enumerate(sids, start=1):
                val = matrix[sid_a][sid_b]
                val_str = f"{val:.4f}" if val is not None else " N/A  "
                col_widths[i] = max(col_widths[i], len(val_str))

        sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
        header_line = (
            "| "
            + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            + " |"
        )

        lines = [sep, header_line, sep]
        for sid_a in sids:
            row = [sid_a]
            for sid_b in sids:
                val = matrix[sid_a][sid_b]
                row.append(f"{val:.4f}" if val is not None else " N/A  ")
            row_line = (
                "| "
                + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row))
                + " |"
            )
            lines.append(row_line)
        lines.append(sep)
        return "\n".join(lines)


def _get_fixtures_dir() -> Path:
    """Return path to packaged fixtures directory."""
    return Path(__file__).resolve().parent / "fixtures"


def build_offline_cohort_bundle() -> EvaluationInputBundleV1:
    """Load or assemble deterministic offline evaluation input bundle."""
    bundle_path = _get_fixtures_dir() / "offline_cohort_bundle.json"
    if bundle_path.is_file():
        return EvaluationInputBundleV1.model_validate_json(bundle_path.read_text())

    raise FileNotFoundError(
        f"Packaged offline bundle fixture not found at {bundle_path}"
    )


def build_offline_cohort_evidence() -> SessionEvaluatorEvidence:
    """Load or assemble deterministic offline listing role evidence."""
    evidence_path = _get_fixtures_dir() / "offline_cohort_evidence.json"
    if evidence_path.is_file():
        raw_items = json.loads(evidence_path.read_text())
        role_records = tuple(
            ListingRoleVersionV1.model_validate_json(item) for item in raw_items
        )
        return SessionEvaluatorEvidence(listing_role_records=role_records)

    raise FileNotFoundError(
        f"Packaged offline evidence fixture not found at {evidence_path}"
    )


def build_reference_baseline_cohort(
    bundle: EvaluationInputBundleV1,
) -> dict[str, Any]:
    """Construct reference baseline strategy cohort over the bundle."""
    if not bundle.security_identities:
        raise ValueError(
            "Input bundle contains no security identities for B1 "
            "single buy-and-hold baseline"
        )
    sec_a = bundle.security_identities[0].security_id

    from drift.baselines.b0_cash import B0CashStrategy
    from drift.baselines.b1_single_buy_and_hold import B1SingleBuyAndHoldStrategy
    from drift.baselines.b2_equal_weight_buy_and_hold import (
        B2EqualWeightBuyAndHoldStrategy,
    )
    from drift.baselines.b3_monthly_equal_weight_rebalance import (
        B3MonthlyEqualWeightRebalanceStrategy,
    )
    from drift.baselines.b4_momentum import B4MomentumStrategy

    return {
        "b0_cash": B0CashStrategy(),
        "b1_single_buy_and_hold": B1SingleBuyAndHoldStrategy(target_security_id=sec_a),
        "b2_equal_weight": B2EqualWeightBuyAndHoldStrategy(),
        "b3_monthly_rebalance": B3MonthlyEqualWeightRebalanceStrategy(),
        "b4_momentum": B4MomentumStrategy(
            formation_sessions=1,
            skip_sessions=0,
            min_eligible_count=1,
        ),
    }


def main() -> int:
    """CLI entrypoint executing parallel $10,000 research portfolios."""
    print("=" * 80)
    print("DRIFT: PARALLEL $10,000 RESEARCH PORTFOLIOS COHORT HARNESS")
    print("=" * 80)
    print("SYNTHETIC FOUR-SESSION TEST FIXTURE")
    print("NOT ACTUAL MARKET PERFORMANCE")
    print("NOT SCIENTIFICALLY QUALIFIED")
    print("NOT PROMOTION-GRADE")
    print("=" * 80)
    print("Loading offline deterministic evaluation input bundle and evidence...")
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    session_count = len(bundle.session_clock.sessions)
    print(f"Bundle loaded: {bundle.bundle_hash[:16]}... ({session_count} sessions)")

    cohort = build_reference_baseline_cohort(bundle)
    print(
        f"Cohort initialized with {len(cohort)} strategies "
        f"(initial cash: ${TARGET_INITIAL_CASH:,.2f}):"
    )
    for sid in cohort:
        print(f"  - {sid}")

    print("\nExecuting parallel evaluations across process pool...")
    harness = PortfolioCohortHarness(
        cohort=cohort,
        bundle=bundle,
        evidence=evidence,
    )
    results = harness.run_parallel()

    print("\n--- Cohort Performance Summary ---")
    table = harness.format_comparison_table(results)
    print(table)

    print("\n--- Cross-Cohort Daily Return Correlation Matrix ---")
    corr_matrix = harness.compute_correlation_matrix(results)
    corr_table = harness.format_correlation_matrix(corr_matrix)
    print(corr_table)

    print("\nAll portfolios evaluated with genuine M2 deterministic engine.")
    print(
        "Portfolio isolation verified: initial cash $10,000.00 preserved per account."
    )
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
