"""Exact structural ETF target feasibility for proposed Stage 1 risk studies.

All policies and ETF classifications are explicit caller-owned development
inputs. Never an effective portfolio mandate, market data, fill simulator,
risk-override path, source entitlement, or approval for broker orders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from typing import Literal, Sequence

type AssetRole = Literal["EQUITY", "BOND", "GOLD"]

_TICKER = re.compile(r"[A-Z][A-Z0-9.]{0,15}\Z")
_ROLES = ("EQUITY", "BOND", "GOLD")
_MAX_STUDY_UNIVERSE = 16


@dataclass(frozen=True, slots=True)
class ETFStudyMember:
    ticker: str
    role: AssetRole


@dataclass(frozen=True, slots=True)
class DevelopmentTargetCaps:
    """Explicit research cap fractions, not an accepted mandate."""

    per_etf: Decimal
    equities: Decimal
    bonds: Decimal
    gold: Decimal
    gross: Decimal


@dataclass(frozen=True, slots=True)
class EqualTargetReview:
    selected_tickers: tuple[str, ...]
    selected_count: int
    per_etf_weight: Fraction
    equity_weight: Fraction
    bond_weight: Fraction
    gold_weight: Fraction
    gross_weight: Fraction
    feasible_for_development: bool
    violated_proposed_limits: tuple[str, ...]

    @property
    def approved_for_order_or_risk_control(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class EqualTargetSweep:
    """Enumeration only, never a market-ranking or success-frequency estimate."""

    all_member_b3: EqualTargetReview
    selected_count: int
    total_possible_subsets: int
    feasible_subsets: int
    infeasible_subsets: int
    violation_occurrences: tuple[tuple[str, int], ...]
    rejection_examples: tuple[tuple[str, ...], ...]

    @property
    def is_historical_acceptance_rate(self) -> bool:
        return False

    @property
    def approves_mandate_or_execution(self) -> bool:
        return False


def _check_policy(policy: DevelopmentTargetCaps) -> None:
    if type(policy) is not DevelopmentTargetCaps:
        raise ValueError("DEVELOPMENT_POLICY_EXACT_TYPE_REQUIRED")
    for name in ("per_etf", "equities", "bonds", "gold", "gross"):
        value = getattr(policy, name)
        if type(value) is not Decimal or not value.is_finite():
            raise ValueError(f"POLICY_{name}_FINITE_DECIMAL_REQUIRED")
        if value < 0 or value > 1:
            raise ValueError(f"POLICY_{name}_OUT_OF_UNIT_RANGE")


def _check_members(
    members: Sequence[ETFStudyMember],
) -> tuple[ETFStudyMember, ...]:
    if type(members) not in (tuple, list):
        raise ValueError("STUDY_MEMBERS_IMMUTABLE_VIEW_REQUIRED")
    copied = tuple(members)
    if not 1 <= len(copied) <= _MAX_STUDY_UNIVERSE:
        raise ValueError("STUDY_UNIVERSE_SIZE_INVALID")
    seen: set[str] = set()
    for item in copied:
        if type(item) is not ETFStudyMember:
            raise ValueError("STUDY_MEMBER_EXACT_TYPE_REQUIRED")
        if type(item.ticker) is not str or not _TICKER.fullmatch(
            item.ticker
        ):
            raise ValueError("STUDY_TICKER_INVALID")
        if type(item.role) is not str or item.role not in _ROLES:
            raise ValueError("STUDY_ROLE_INVALID")
        if item.ticker in seen:
            raise ValueError("STUDY_DUPLICATE_TICKER")
        seen.add(item.ticker)
    return tuple(sorted(copied, key=lambda item: item.ticker))


def _evaluate_validated(
    members: tuple[ETFStudyMember, ...],
    selected: tuple[str, ...],
    policy: DevelopmentTargetCaps,
) -> EqualTargetReview:
    role_by_ticker = {m.ticker: m.role for m in members}
    size = len(selected)
    count_e = sum(role_by_ticker[s] == "EQUITY" for s in selected)
    count_b = sum(role_by_ticker[s] == "BOND" for s in selected)
    count_g = sum(role_by_ticker[s] == "GOLD" for s in selected)
    one = Decimal(size)
    rejected: list[str] = []
    if Decimal(1) > policy.per_etf * one:
        rejected.append("SINGLE_ETF")
    if Decimal(count_e) > policy.equities * one:
        rejected.append("EQUITY_CLASS")
    if Decimal(count_b) > policy.bonds * one:
        rejected.append("BOND_CLASS")
    if Decimal(count_g) > policy.gold * one:
        rejected.append("GOLD_CLASS")
    # Exactly 100% continuous target investment, before whole-share rounding.
    if Decimal(size) > policy.gross * one:
        rejected.append("GROSS_INVESTMENT")
    return EqualTargetReview(
        selected_tickers=selected,
        selected_count=size,
        per_etf_weight=Fraction(1, size),
        equity_weight=Fraction(count_e, size),
        bond_weight=Fraction(count_b, size),
        gold_weight=Fraction(count_g, size),
        gross_weight=Fraction(1),
        feasible_for_development=not rejected,
        violated_proposed_limits=tuple(rejected),
    )


def review_equal_target_subset(
    *,
    members: Sequence[ETFStudyMember],
    selected_tickers: Sequence[str],
    policy: DevelopmentTargetCaps,
) -> EqualTargetReview:
    """Assess proposed continuous equal targets; never stage orders."""
    universe = _check_members(members)
    _check_policy(policy)
    if type(selected_tickers) not in (tuple, list):
        raise ValueError("SELECTION_INPUT_PLAIN_SEQUENCE_REQUIRED")
    selected = tuple(selected_tickers)
    if not selected or any(type(t) is not str for t in selected):
        raise ValueError("SELECTION_INVALID")
    if len(set(selected)) != len(selected):
        raise ValueError("SELECTION_DUPLICATE_TICKER")
    known = {m.ticker for m in universe}
    if not set(selected).issubset(known):
        raise ValueError("SELECTION_UNKNOWN_TICKER")
    return _evaluate_validated(universe, tuple(sorted(selected)), policy)


def enumerate_equal_target_subsets(
    *,
    members: Sequence[ETFStudyMember],
    policy: DevelopmentTargetCaps,
    selected_count: int | None = None,
    max_rejection_examples: int = 5,
) -> EqualTargetSweep:
    """Enumerate all possible equal-rank sets, not observed B4/B5 outcomes.

    The accepted baseline source selects ceil(n/2) members for B4/B5 after
    eligible price histories; this is only a structural no-price enumeration.
    """
    universe = _check_members(members)
    _check_policy(policy)
    if selected_count is None:
        selected_count = (len(universe) + 1) // 2
    if type(selected_count) is not int or not 1 <= selected_count <= len(universe):
        raise ValueError("SELECTION_COUNT_INVALID")
    if (
        type(max_rejection_examples) is not int
        or not 0 <= max_rejection_examples <= 20
    ):
        raise ValueError("REJECTION_EXAMPLE_LIMIT_INVALID")

    full = _evaluate_validated(
        universe, tuple(item.ticker for item in universe), policy
    )
    total = 0
    feasible = 0
    violations = {key: 0 for key in (
        "SINGLE_ETF", "EQUITY_CLASS", "BOND_CLASS",
        "GOLD_CLASS", "GROSS_INVESTMENT",
    )}
    examples: list[tuple[str, ...]] = []
    for selected in combinations((m.ticker for m in universe), selected_count):
        review = _evaluate_validated(universe, selected, policy)
        total += 1
        if review.feasible_for_development:
            feasible += 1
        else:
            for violation in review.violated_proposed_limits:
                violations[violation] += 1
            if len(examples) < max_rejection_examples:
                examples.append(selected)
    return EqualTargetSweep(
        all_member_b3=full,
        selected_count=selected_count,
        total_possible_subsets=total,
        feasible_subsets=feasible,
        infeasible_subsets=total - feasible,
        violation_occurrences=tuple(sorted(violations.items())),
        rejection_examples=tuple(examples),
    )
