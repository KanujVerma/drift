"""Integration tests for parallel $10,000 research portfolios (Phase 3)."""

from decimal import Decimal

import pytest

from drift.baselines.b0_cash import B0CashStrategy
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.experiments.parallel_portfolios import (
    CohortPortfolioResult,
    PortfolioCohortHarness,
    build_offline_cohort_bundle,
    build_offline_cohort_evidence,
    build_reference_baseline_cohort,
    compute_daily_returns_correlation,
)
from drift.experiments.parallel_portfolios import (
    main as cli_main,
)


def test_offline_cohort_bundle_and_evidence_loading() -> None:
    """Offline bundle and evidence load cleanly without external services."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()

    assert bundle is not None
    assert len(bundle.bundle_hash) == 64
    assert len(bundle.session_clock.sessions) == 4
    assert len(bundle.security_identities) >= 2
    assert len(evidence.listing_role_records) >= 2


def test_harness_enforces_strict_10000_initial_cash() -> None:
    """Harness rejects configurations that deviate from strict $10,000 initial cash."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = {"b0_cash": B0CashStrategy()}

    # Reject non-$10,000 initial_cash parameter
    with pytest.raises(ValueError, match="initial cash must be exactly 10000.00"):
        PortfolioCohortHarness(
            cohort=cohort,
            bundle=bundle,
            evidence=evidence,
            initial_cash=Decimal("5000.00"),
        )

    # Reject protocol with non-$10,000 initial cash
    custom_protocol = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="drift-test-proto",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=2,
        initial_cash=Decimal("50000.00"),
        protocol_hash="0" * 64,
    )
    with pytest.raises(
        ValueError, match="protocol initial cash must be exactly 10000.00"
    ):
        PortfolioCohortHarness(
            cohort=cohort,
            bundle=bundle,
            evidence=evidence,
            protocol=custom_protocol,
        )


def test_portfolio_isolation_and_initial_cash() -> None:
    """Every portfolio runs in complete isolation with exactly $10,000 initial cash."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = build_reference_baseline_cohort(bundle)

    harness = PortfolioCohortHarness(
        cohort=cohort,
        bundle=bundle,
        evidence=evidence,
    )
    results = harness.run_sequential()

    assert len(results) == len(cohort)
    for r in results:
        # Strict $10,000 initial cash
        assert r.initial_cash == Decimal("10000.00")
        assert r.classification == "complete"
        assert r.is_pnl_complete is True
        assert len(r.trace_hash) == 64
        assert len(r.result_hash) == 64
        assert len(r.bundle_hash) == 64
        assert len(r.run_identity_hash) == 64
        assert len(r.cost_model_hash) == 64
        assert len(r.protocol_hash) == 64
        assert len(r.daily_returns) == len(bundle.session_clock.sessions)

    # Cash strategy remained at exactly $10,000.00
    b0_res = next(r for r in results if r.strategy_id == "b0_cash")
    assert b0_res.ending_nav == Decimal("10000.00")
    assert b0_res.total_return_pct == Decimal("0.00")
    assert b0_res.fill_count == 0

    # B1 single buy and hold traded and grew to $12,000.00 (+20%)
    b1_res = next(r for r in results if r.strategy_id == "b1_single_buy_and_hold")
    assert b1_res.ending_nav == Decimal("12000.00")
    assert b1_res.total_return_pct == Decimal("20.00")
    assert b1_res.fill_count == 1

    # B2 equal weight traded both securities and grew to $11,000.00 (+10%)
    b2_res = next(r for r in results if r.strategy_id == "b2_equal_weight")
    assert b2_res.ending_nav == Decimal("11000.00")
    assert b2_res.total_return_pct == Decimal("10.00")
    assert b2_res.fill_count == 2


def test_parallel_matches_sequential_bit_for_bit() -> None:
    """Parallel execution produces identical results and hashes to sequential."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = build_reference_baseline_cohort(bundle)

    harness = PortfolioCohortHarness(
        cohort=cohort,
        bundle=bundle,
        evidence=evidence,
    )

    seq_results = harness.run_sequential()
    par_results = harness.run_parallel(max_workers=4)

    assert len(seq_results) == len(par_results)
    for s_res, p_res in zip(seq_results, par_results, strict=True):
        assert s_res.strategy_id == p_res.strategy_id
        assert s_res.strategy_type == p_res.strategy_type
        assert s_res.initial_cash == p_res.initial_cash
        assert s_res.ending_nav == p_res.ending_nav
        assert s_res.total_return_pct == p_res.total_return_pct
        assert s_res.annualized_sharpe == p_res.annualized_sharpe
        assert s_res.max_drawdown_pct == p_res.max_drawdown_pct
        assert s_res.annualized_turnover == p_res.annualized_turnover
        assert s_res.fill_count == p_res.fill_count
        assert s_res.daily_returns == p_res.daily_returns
        assert s_res.bundle_hash == p_res.bundle_hash
        assert s_res.run_identity_hash == p_res.run_identity_hash
        assert s_res.cost_model_hash == p_res.cost_model_hash
        assert s_res.protocol_hash == p_res.protocol_hash
        # Bit-for-bit trace hash and result hash equality across process boundary
        assert s_res.trace_hash == p_res.trace_hash
        assert s_res.result_hash == p_res.result_hash


def test_correlation_matrix_properties() -> None:
    """Correlation matrix is symmetric, bounded, and formats undefined series
    as None.
    """
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = build_reference_baseline_cohort(bundle)

    harness = PortfolioCohortHarness(
        cohort=cohort,
        bundle=bundle,
        evidence=evidence,
    )
    results = harness.run_sequential()
    matrix = harness.compute_correlation_matrix(results)

    sids = [r.strategy_id for r in results]
    for s_a in sids:
        for s_b in sids:
            val_ab = matrix[s_a][s_b]
            val_ba = matrix[s_b][s_a]
            # Symmetry: Corr(A, B) == Corr(B, A)
            assert val_ab == val_ba
            if val_ab is not None:
                # Bounded in [-1.0000, 1.0000]
                assert Decimal("-1.0000") <= val_ab <= Decimal("1.0000")

    # b0_cash has zero variance; correlation with itself or others is undefined (None)
    assert matrix["b0_cash"]["b0_cash"] is None
    # Non-zero variance series with itself is 1.0000
    assert matrix["b1_single_buy_and_hold"]["b1_single_buy_and_hold"] == Decimal(
        "1.0000"
    )


def test_correlation_zero_variance_and_identical() -> None:
    """Correlation helper handles zero-variance cash series and identical series."""
    zero_series = (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    identical_series = (
        Decimal("0.01"),
        Decimal("0.02"),
        Decimal("-0.01"),
        Decimal("0.03"),
    )
    scaled_series = (
        Decimal("0.02"),
        Decimal("0.04"),
        Decimal("-0.02"),
        Decimal("0.06"),
    )
    inverse_series = (
        Decimal("-0.01"),
        Decimal("-0.02"),
        Decimal("0.01"),
        Decimal("-0.03"),
    )

    # Identical series -> 1.0000
    assert compute_daily_returns_correlation(
        identical_series, identical_series
    ) == Decimal("1.0000")
    # Perfectly positively correlated -> 1.0000
    assert compute_daily_returns_correlation(
        identical_series, scaled_series
    ) == Decimal("1.0000")
    # Perfectly negatively correlated -> -1.0000
    assert compute_daily_returns_correlation(
        identical_series, inverse_series
    ) == Decimal("-1.0000")

    # Zero-variance vs non-zero variance -> None (undefined)
    assert compute_daily_returns_correlation(zero_series, identical_series) is None
    assert compute_daily_returns_correlation(identical_series, zero_series) is None

    # Zero-variance with itself -> None (undefined)
    assert compute_daily_returns_correlation(zero_series, zero_series) is None

    # Length mismatch raises ValueError
    with pytest.raises(ValueError, match="Series lengths must match"):
        compute_daily_returns_correlation(zero_series, (Decimal("0.01"),))


def test_table_formatters() -> None:
    """Comparison table and correlation matrix formatters produce readable ASCII."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = build_reference_baseline_cohort(bundle)

    harness = PortfolioCohortHarness(
        cohort=cohort,
        bundle=bundle,
        evidence=evidence,
    )
    results = harness.run_sequential()

    table = harness.format_comparison_table(results)
    assert "Strategy ID" in table
    assert "Initial Cash" in table
    assert "Ending NAV" in table
    assert "$10,000.00" in table
    assert "b0_cash" in table
    assert "b1_single_buy_and_hold" in table

    matrix = harness.compute_correlation_matrix(results)
    matrix_table = harness.format_correlation_matrix(matrix)
    assert "Strategy ID" in matrix_table
    assert "1.0000" in matrix_table
    assert "b0_cash" in matrix_table
    assert "N/A" in matrix_table


def test_cli_main_runs_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI main entrypoint runs cleanly and exits with status 0."""
    exit_code = cli_main()
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "PARALLEL $10,000 RESEARCH PORTFOLIOS COHORT HARNESS" in captured.out
    assert "SYNTHETIC FOUR-SESSION TEST FIXTURE" in captured.out
    assert "NOT PROMOTION-GRADE" in captured.out
    assert "Cohort Performance Summary" in captured.out
    assert "Cross-Cohort Daily Return Correlation Matrix" in captured.out
    assert "Portfolio isolation verified" in captured.out


def test_incomplete_and_pnl_incomplete_portfolio_reporting() -> None:
    """Incomplete and PnL-incomplete portfolios report None return, preserve ending NAV,
    and format as N/A without entering rankings.
    """
    res_complete = CohortPortfolioResult(
        strategy_id="strat_complete",
        strategy_type="B1",
        initial_cash=Decimal("10000.00"),
        ending_nav=Decimal("11000.00"),
        total_return_pct=Decimal("10.00"),
        annualized_sharpe=Decimal("1.5000"),
        max_drawdown_pct=Decimal("0.0500"),
        annualized_turnover=Decimal("2.0000"),
        fill_count=1,
        trace_hash="t" * 64,
        result_hash="r" * 64,
        daily_returns=(
            Decimal("0.02"),
            Decimal("0.03"),
            Decimal("-0.01"),
            Decimal("0.06"),
        ),
        classification="complete",
        is_pnl_complete=True,
        net_profit_and_loss=Decimal("1000.00"),
        bundle_hash="b" * 64,
        run_identity_hash="i" * 64,
        cost_model_hash="c" * 64,
        protocol_hash="p" * 64,
    )
    res_indeterminate = CohortPortfolioResult(
        strategy_id="strat_indeterminate",
        strategy_type="B4",
        initial_cash=Decimal("10000.00"),
        ending_nav=Decimal("10500.00"),
        total_return_pct=None,
        annualized_sharpe=None,
        max_drawdown_pct=None,
        annualized_turnover=None,
        fill_count=2,
        trace_hash="t" * 64,
        result_hash="r" * 64,
        daily_returns=(Decimal("0.02"), Decimal("0.03")),
        classification="indeterminate",
        is_pnl_complete=False,
        net_profit_and_loss=Decimal("500.00"),
        bundle_hash="b" * 64,
        run_identity_hash="i" * 64,
        cost_model_hash="c" * 64,
        protocol_hash="p" * 64,
    )
    res_pnl_incomplete = CohortPortfolioResult(
        strategy_id="strat_pnl_incomplete",
        strategy_type="B2",
        initial_cash=Decimal("10000.00"),
        ending_nav=Decimal("12000.00"),
        total_return_pct=None,
        annualized_sharpe=Decimal("2.0000"),
        max_drawdown_pct=Decimal("0.0200"),
        annualized_turnover=Decimal("1.0000"),
        fill_count=3,
        trace_hash="t" * 64,
        result_hash="r" * 64,
        daily_returns=(
            Decimal("0.04"),
            Decimal("0.05"),
            Decimal("0.05"),
            Decimal("0.06"),
        ),
        classification="complete",
        is_pnl_complete=False,
        net_profit_and_loss=Decimal("2000.00"),
        bundle_hash="b" * 64,
        run_identity_hash="i" * 64,
        cost_model_hash="c" * 64,
        protocol_hash="p" * 64,
    )

    results = [res_complete, res_indeterminate, res_pnl_incomplete]

    # 1. Comparison table formatting
    table = PortfolioCohortHarness.format_comparison_table(results)
    assert "Status" in table
    assert "COMPLETE" in table
    assert "INDETERMINATE" in table
    assert "INCOMPLETE (PNL)" in table
    assert "$10,500.00" in table
    assert "$12,000.00" in table
    assert "10.00%" in table
    assert "   N/A" in table

    # 2. Ranking disqualification: incomplete runs cannot be ranked or win
    ranked = PortfolioCohortHarness.rank_results(results)
    assert len(ranked) == 1
    assert ranked[0].strategy_id == "strat_complete"

    # 3. Correlation matrix resilience: incomplete or unequal-length series return None
    matrix = PortfolioCohortHarness.compute_correlation_matrix(results)
    assert matrix["strat_complete"]["strat_complete"] == Decimal("1.0000")
    assert matrix["strat_complete"]["strat_indeterminate"] is None
    assert matrix["strat_indeterminate"]["strat_complete"] is None
    assert matrix["strat_complete"]["strat_pnl_incomplete"] is None
    assert matrix["strat_pnl_incomplete"]["strat_complete"] is None
    assert matrix["strat_indeterminate"]["strat_indeterminate"] is None
