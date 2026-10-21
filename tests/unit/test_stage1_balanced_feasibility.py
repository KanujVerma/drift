"""Unexecuted Stage 1 development cap feasibility oracles for Matthew #380."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from scripts.stage1_balanced_feasibility import (
    DevelopmentTargetCaps,
    ETFStudyMember,
    enumerate_equal_target_subsets,
    review_equal_target_subset,
)


def universe(*, without_qqq: bool = False) -> tuple[ETFStudyMember, ...]:
    roles = {
        "EQUITY": ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"),
        "BOND": ("SHY", "IEF", "TLT", "TIP", "LQD"),
        "GOLD": ("GLD",),
    }
    return tuple(
        ETFStudyMember(ticker=ticker, role=role)
        for role, tickers in roles.items()
        for ticker in tickers
        if not (without_qqq and ticker == "QQQ")
    )


def caps(
    *, etf: str = "0.20", equity: str = "0.70",
    bond: str = "0.75", gold: str = "0.20",
    gross: str = "1",
) -> DevelopmentTargetCaps:
    """Fixture assumptions only; none is an effective risk policy."""
    return DevelopmentTargetCaps(
        per_etf=Decimal(etf),
        equities=Decimal(equity),
        bonds=Decimal(bond),
        gold=Decimal(gold),
        gross=Decimal(gross),
    )


def test_twelve_fund_b3_all_equal_target_class_math_is_exact() -> None:
    result = enumerate_equal_target_subsets(
        members=universe(), policy=caps(),
    ).all_member_b3
    assert result.selected_count == 12
    assert result.per_etf_weight == Fraction(1, 12)
    assert result.equity_weight == Fraction(1, 2)
    assert result.bond_weight == Fraction(5, 12)
    assert result.gold_weight == Fraction(1, 12)
    assert result.gross_weight == Fraction(1)
    assert result.feasible_for_development
    assert not result.approved_for_order_or_risk_control


def test_six_of_twelve_exact_fair_rank_set_math_not_success_probability() -> None:
    sweep = enumerate_equal_target_subsets(
        members=universe(), policy=caps(),
    )
    assert sweep.selected_count == 6
    assert sweep.total_possible_subsets == 924
    assert sweep.feasible_subsets == 880
    assert sweep.infeasible_subsets == 44
    assert not sweep.is_historical_acceptance_rate
    assert not sweep.approves_mandate_or_execution


@pytest.mark.parametrize(
    ("policy", "accepted"),
    [
        (caps(etf="0.15"), 0),
        (caps(equity="0.65"), 655),
        (caps(), 880),
        (caps(etf="0.25"), 880),
        (caps(etf="0.25", equity="0.85", bond="0.85"), 923),
        (caps(gold="0.15"), 425),
    ],
)
def test_owner_development_policy_grid_is_exact_not_approved(
    policy: DevelopmentTargetCaps, accepted: int,
) -> None:
    observed = enumerate_equal_target_subsets(
        members=universe(), policy=policy,
    )
    assert observed.total_possible_subsets == 924
    assert observed.feasible_subsets == accepted
    assert observed.infeasible_subsets == 924 - accepted
    assert observed.rejection_examples == (
        () if accepted == 924 else observed.rejection_examples
    )
    assert not observed.approves_mandate_or_execution


def test_no_qqq_eleven_etf_sensitivity_is_prespecified() -> None:
    sweep = enumerate_equal_target_subsets(
        members=universe(without_qqq=True), policy=caps(),
    )
    assert sweep.selected_count == 6
    assert sweep.total_possible_subsets == 462
    assert sweep.feasible_subsets == 450
    assert sweep.infeasible_subsets == 12
    b3 = sweep.all_member_b3
    assert b3.selected_count == 11
    assert b3.equity_weight == Fraction(5, 11)
    assert b3.bond_weight == Fraction(5, 11)
    assert b3.gold_weight == Fraction(1, 11)


def test_six_equities_violate_class_not_single_etf_under_20pct() -> None:
    selected = ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO")
    result = review_equal_target_subset(
        members=universe(), selected_tickers=selected, policy=caps(),
    )
    assert result.per_etf_weight == Fraction(1, 6)
    assert not result.feasible_for_development
    assert "EQUITY_CLASS" in result.violated_proposed_limits
    assert "SINGLE_ETF" not in result.violated_proposed_limits


def test_five_bonds_sixth_equity_violate_bond_class_only() -> None:
    selected = ("SHY", "IEF", "TLT", "TIP", "LQD", "VOO")
    result = review_equal_target_subset(
        members=universe(), selected_tickers=selected, policy=caps(),
    )
    assert not result.feasible_for_development
    assert "BOND_CLASS" in result.violated_proposed_limits
    assert "SINGLE_ETF" not in result.violated_proposed_limits


def test_gold_limit_15_pct_denies_selected_six_with_gld() -> None:
    selected = ("GLD", "VOO", "IJH", "IJR", "QQQ", "VEA")
    result = review_equal_target_subset(
        members=universe(), selected_tickers=selected,
        policy=caps(gold="0.15"),
    )
    assert "GOLD_CLASS" in result.violated_proposed_limits


def test_order_of_selection_does_not_change_structural_target_review() -> None:
    selected = ("GLD", "VOO", "IJH", "SHY", "TLT", "LQD")
    forward = review_equal_target_subset(
        members=universe(), selected_tickers=selected, policy=caps(),
    )
    reversed_input = review_equal_target_subset(
        members=tuple(reversed(universe())),
        selected_tickers=tuple(reversed(selected)), policy=caps(),
    )
    assert forward == reversed_input
    assert not forward.approved_for_order_or_risk_control


@pytest.mark.parametrize(
    "bad_policy",
    [
        DevelopmentTargetCaps(
            per_etf=Decimal("NaN"), equities=Decimal("0.7"),
            bonds=Decimal("0.75"), gold=Decimal("0.2"),
            gross=Decimal("1"),
        ),
        DevelopmentTargetCaps(
            per_etf=Decimal("0.2"), equities=Decimal("1.05"),
            bonds=Decimal("0.75"), gold=Decimal("0.2"),
            gross=Decimal("1"),
        ),
        DevelopmentTargetCaps(
            per_etf=0.2, equities=Decimal("0.7"),  # type: ignore[arg-type]
            bonds=Decimal("0.75"), gold=Decimal("0.2"),
            gross=Decimal("1"),
        ),
    ],
)
def test_invalid_or_float_policy_never_defaults_to_limits(
    bad_policy: DevelopmentTargetCaps,
) -> None:
    with pytest.raises(ValueError, match="POLICY_"):
        enumerate_equal_target_subsets(members=universe(), policy=bad_policy)


def test_gross_cap_below_100_pct_does_not_silently_trim_targets() -> None:
    sweep = enumerate_equal_target_subsets(
        members=universe(), policy=caps(gross="0.80"),
    )
    assert not sweep.all_member_b3.feasible_for_development
    assert sweep.feasible_subsets == 0
    assert "GROSS_INVESTMENT" in sweep.all_member_b3.violated_proposed_limits


def test_duplicate_member_ticker_is_not_new_asset_class_slot() -> None:
    members = (*universe(), ETFStudyMember("GLD", "EQUITY"))
    with pytest.raises(ValueError, match="STUDY_DUPLICATE_TICKER"):
        enumerate_equal_target_subsets(members=members, policy=caps())


def test_invalid_foreign_asset_role_refuses() -> None:
    members = (*universe()[:-1], ETFStudyMember("ABC", "CASH"))
    with pytest.raises(ValueError, match="STUDY_ROLE_INVALID"):
        enumerate_equal_target_subsets(
            members=members, policy=caps(),
        )


def test_unknown_selected_ticker_and_duplicate_selection_refuse() -> None:
    with pytest.raises(ValueError, match="SELECTION_UNKNOWN_TICKER"):
        review_equal_target_subset(
            members=universe(),
            selected_tickers=("VOO", "UNKNOWN_ETF"),
            policy=caps(),
        )
    with pytest.raises(ValueError, match="SELECTION_DUPLICATE_TICKER"):
        review_equal_target_subset(
            members=universe(), selected_tickers=("VOO", "VOO"),
            policy=caps(),
        )


def test_boolean_count_and_unbounded_rejection_capture_refuse() -> None:
    with pytest.raises(ValueError, match="SELECTION_COUNT_INVALID"):
        enumerate_equal_target_subsets(
            members=universe(), policy=caps(), selected_count=True,
        )
    with pytest.raises(ValueError, match="REJECTION_EXAMPLE_LIMIT_INVALID"):
        enumerate_equal_target_subsets(
            members=universe(), policy=caps(),
            max_rejection_examples=100_000,
        )


def test_study_fixture_classification_is_not_proved_point_in_time() -> None:
    a = ETFStudyMember(ticker="QQQ", role="EQUITY")
    assert a.ticker == "QQQ"
    assert a.role == "EQUITY"
    assert not enumerate_equal_target_subsets(
        members=(a,), policy=caps()
    ).approves_mandate_or_execution
