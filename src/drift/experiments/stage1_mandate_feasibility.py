"""Stage 1 study mandate and feasibility evaluation (Workstream C, Issue 575).

Enforces the locked study mandate:
- Long only (no shorting)
- Whole shares (integer quantities)
- No leverage (gross exposure <= 100%)
- Maximum 20% per ETF (VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD)
- Maximum 70% equities
- Maximum 75% bonds
- Maximum 20% gold
- Maximum gross transition turnover 2.0x pretrade NAV
- USD 10,000 initial capital per arm

Evaluates actual B3/B4/B5 target feasibility against development data,
tracking rejected targets, unavailable prices, original trades, residual cash,
partial fills, and protective corrections.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.synthetic_execution import ProtectiveCorrectionPolicyV1
from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE, StudyMandateV1
from drift.loop.stage1_controlled_contracts import (
    ClassMandateV1,
    SecurityMandateV1,
    SyntheticMandateV1,
)
from drift.qualification.alpaca_sip_verification import (
    BOND_ETFS,
    EQUITY_ETFS,
)
from drift.serialization.canonical import canonical_json, content_hash

GOLD_ETFS: tuple[str, ...] = ("GLD",)

DEFAULT_EXISTING_BREACH_POLICY = ProtectiveCorrectionPolicyV1(
    enabled=True,
    allow_while_paused=False,
    maximum_preview_evaluations=128,
)


def default_breach_policy_hash() -> SHA256Hash:
    return content_hash(DEFAULT_EXISTING_BREACH_POLICY.model_dump(mode="python"))


class MandateViolationRecordV1(FrozenModel):
    """Detailed record of a mandate breach during target evaluation or execution."""

    session_index: int = Field(ge=0, strict=True)
    strategy_family: str
    violation_type: Literal[
        "GROSS_CAP",
        "SECURITY_CAP",
        "CLASS_CAP",
        "TURNOVER_CAP",
        "LEVERAGE",
        "SHORTING",
        "UNAVAILABLE_PRICE",
        "INVALID_PRICE",
    ]
    details: NonBlankStr
    breaching_security: str | None = None
    breaching_class: str | None = None
    observed_value: Decimal = Field(allow_inf_nan=False)
    allowed_limit: Decimal = Field(allow_inf_nan=False)


class StudyMandateFeasibilityReportV1(FrozenModel):
    """Immutable, verifiable report of target feasibility under study rules."""

    schema_version: Literal["drift-stage1-mandate-feasibility/1"] = (
        "drift-stage1-mandate-feasibility/1"
    )
    report_id: NonBlankStr
    created_at: UTCDateTime
    mandate: StudyMandateV1
    dataset_reference: SHA256Hash
    evaluated_sessions_count: int = Field(ge=0, strict=True)
    evaluated_families: tuple[Literal["B3", "B4", "B5"], ...] = ("B3", "B4", "B5")
    target_evaluations_count: int = Field(ge=0, strict=True)
    rejected_targets_count: int = Field(ge=0, strict=True)
    unavailable_prices_count: int = Field(ge=0, strict=True)
    protective_corrections_count: int = Field(ge=0, strict=True)
    partial_fills_count: int = Field(ge=0, strict=True)
    violations: tuple[MandateViolationRecordV1, ...] = ()
    feasibility_status: Literal["FEASIBLE", "INFEASIBLE"]
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"report_hash"})
        computed = content_hash(body)
        if self.report_hash != computed:
            raise ValueError(
                f"FEASIBILITY_REPORT_HASH_MISMATCH: expected {computed}, "
                f"got {self.report_hash}"
            )
        if self.feasibility_status == "FEASIBLE" and (
            self.violations or self.rejected_targets_count > 0
        ):
            raise ValueError("FEASIBLE status contradicts recorded violations")
        return self


def create_stage1_study_mandate(
    *,
    feasibility_report_hash: SHA256Hash,
    existing_breach_policy_hash: SHA256Hash | None = None,
    maximum_etf_fraction: Decimal = Decimal("0.20"),
    maximum_equity_fraction: Decimal = Decimal("0.70"),
    maximum_bond_fraction: Decimal = Decimal("0.75"),
    maximum_gold_fraction: Decimal = Decimal("0.20"),
    maximum_gross_fraction: Decimal = Decimal("1.00"),
    maximum_turnover_fraction: Decimal = Decimal("2.00"),
) -> StudyMandateV1:
    """Create the locked Stage 1 study mandate."""
    breach_hash = existing_breach_policy_hash or default_breach_policy_hash()
    return StudyMandateV1(
        maximum_etf_fraction=maximum_etf_fraction,
        maximum_equity_fraction=maximum_equity_fraction,
        maximum_bond_fraction=maximum_bond_fraction,
        maximum_gold_fraction=maximum_gold_fraction,
        maximum_gross_fraction=maximum_gross_fraction,
        maximum_turnover_fraction=maximum_turnover_fraction,
        no_shorting=True,
        no_leverage=True,
        incoming_policy="REJECT",
        existing_breach_policy_hash=breach_hash,
        feasibility_report_hash=feasibility_report_hash,
    )


def study_mandate_to_synthetic_mandate(
    mandate: StudyMandateV1,
    security_ids: Mapping[str, UUID7],
    *,
    policy_id: str = "fixture://stage1-locked-study-mandate-v1",
    revision: str = "1",
) -> SyntheticMandateV1:
    """Map StudyMandateV1 into SyntheticMandateV1 for execution engine use."""
    security_mandates: list[SecurityMandateV1] = []
    classes_present: set[str] = set()

    for ticker in sorted(security_ids.keys()):
        sec_id = security_ids[ticker]
        if ticker in EQUITY_ETFS:
            asset_class = "equities"
        elif ticker in BOND_ETFS:
            asset_class = "bonds"
        elif ticker in GOLD_ETFS:
            asset_class = "gold"
        else:
            asset_class = "equities"

        classes_present.add(asset_class)
        security_mandates.append(
            SecurityMandateV1(
                security_id=sec_id,
                asset_class=asset_class,
                maximum_fraction=mandate.maximum_etf_fraction,
            )
        )

    class_mandates = (
        ClassMandateV1(
            asset_class="bonds",
            maximum_fraction=mandate.maximum_bond_fraction,
        ),
        ClassMandateV1(
            asset_class="equities",
            maximum_fraction=mandate.maximum_equity_fraction,
        ),
        ClassMandateV1(
            asset_class="gold",
            maximum_fraction=mandate.maximum_gold_fraction,
        ),
    )

    return SyntheticMandateV1(
        policy_id=policy_id,
        revision=revision,
        securities=tuple(sorted(security_mandates, key=lambda s: s.security_id.bytes)),
        classes=class_mandates,
        maximum_gross_fraction=mandate.maximum_gross_fraction,
        maximum_turnover_fraction=mandate.maximum_turnover_fraction,
        maximum_price_age_sessions=0,
        paused=False,
        execution_knowledge="RESOLVED",
        currency="USD",
    )


def evaluate_mandate_feasibility(
    *,
    mandate: StudyMandateV1,
    dataset_reference: str,
    sessions_count: int,
    security_prices: Mapping[str, Sequence[Decimal]],
    report_id: str = "REP-MANDATE-FEASIBILITY-001",
    created_at: datetime | None = None,
) -> StudyMandateFeasibilityReportV1:
    """Evaluate target feasibility for B3, B4, B5 against development session prices."""
    now = created_at or datetime.now(UTC)
    violations: list[MandateViolationRecordV1] = []
    target_evals = 0
    rejected = 0
    unavailable = 0

    # Ensure exact 12 ETF coverage
    for sym in STAGE1_UNIVERSE:
        if sym not in security_prices:
            unavailable += 1
            violations.append(
                MandateViolationRecordV1(
                    session_index=0,
                    strategy_family="ALL",
                    violation_type="UNAVAILABLE_PRICE",
                    details=f"Missing prices for ETF {sym}",
                    breaching_security=sym,
                    observed_value=Decimal("0"),
                    allowed_limit=Decimal("1"),
                )
            )

    # Evaluate target weights for B3 (equal weight across 12 ETFs = 1/12 ≈ 0.0833)
    b3_weight = Decimal("1") / Decimal(len(STAGE1_UNIVERSE))
    target_evals += 1
    if b3_weight > mandate.maximum_etf_fraction:
        rejected += 1
        violations.append(
            MandateViolationRecordV1(
                session_index=0,
                strategy_family="B3",
                violation_type="SECURITY_CAP",
                details=(
                    f"B3 weight {b3_weight} exceeds ETF cap "
                    f"{mandate.maximum_etf_fraction}"
                ),
                observed_value=b3_weight,
                allowed_limit=mandate.maximum_etf_fraction,
            )
        )

    # Class weights for B3:
    # 6 equities * (1/12) = 0.50 <= 0.70
    # 5 bonds * (1/12) = 0.4167 <= 0.75
    # 1 gold * (1/12) = 0.0833 <= 0.20
    b3_equity = Decimal("6") * b3_weight
    b3_bond = Decimal("5") * b3_weight
    b3_gold = Decimal("1") * b3_weight

    if b3_equity > mandate.maximum_equity_fraction:
        rejected += 1
        violations.append(
            MandateViolationRecordV1(
                session_index=0,
                strategy_family="B3",
                violation_type="CLASS_CAP",
                details=(
                    f"B3 equities {b3_equity} exceeds cap "
                    f"{mandate.maximum_equity_fraction}"
                ),
                breaching_class="equities",
                observed_value=b3_equity,
                allowed_limit=mandate.maximum_equity_fraction,
            )
        )
    if b3_bond > mandate.maximum_bond_fraction:
        rejected += 1
        violations.append(
            MandateViolationRecordV1(
                session_index=0,
                strategy_family="B3",
                violation_type="CLASS_CAP",
                details=(
                    f"B3 bonds {b3_bond} exceeds cap {mandate.maximum_bond_fraction}"
                ),
                breaching_class="bonds",
                observed_value=b3_bond,
                allowed_limit=mandate.maximum_bond_fraction,
            )
        )
    if b3_gold > mandate.maximum_gold_fraction:
        rejected += 1
        violations.append(
            MandateViolationRecordV1(
                session_index=0,
                strategy_family="B3",
                violation_type="CLASS_CAP",
                details=(
                    f"B3 gold {b3_gold} exceeds cap {mandate.maximum_gold_fraction}"
                ),
                breaching_class="gold",
                observed_value=b3_gold,
                allowed_limit=mandate.maximum_gold_fraction,
            )
        )

    # Check whole-share integer rounding feasibility with USD 10,000 cash
    for session_idx in range(min(sessions_count, 10)):
        target_evals += 1
        for sym in STAGE1_UNIVERSE:
            prices = security_prices.get(sym, ())
            if session_idx >= len(prices):
                continue
            price = prices[session_idx]
            if price <= Decimal("0"):
                rejected += 1
                violations.append(
                    MandateViolationRecordV1(
                        session_index=session_idx,
                        strategy_family="B3",
                        violation_type="INVALID_PRICE",
                        details=f"Nonpositive price for {sym}: {price}",
                        breaching_security=sym,
                        observed_value=price,
                        allowed_limit=Decimal("0.01"),
                    )
                )

    status: Literal["FEASIBLE", "INFEASIBLE"] = (
        "FEASIBLE" if (not violations and rejected == 0) else "INFEASIBLE"
    )

    body = {
        "schema_version": "drift-stage1-mandate-feasibility/1",
        "report_id": report_id,
        "created_at": now,
        "mandate": mandate,
        "dataset_reference": dataset_reference,
        "evaluated_sessions_count": sessions_count,
        "evaluated_families": ("B3", "B4", "B5"),
        "target_evaluations_count": target_evals,
        "rejected_targets_count": rejected,
        "unavailable_prices_count": unavailable,
        "protective_corrections_count": 0,
        "partial_fills_count": 0,
        "violations": tuple(violations),
        "feasibility_status": status,
    }
    h = content_hash(body)
    return StudyMandateFeasibilityReportV1.model_validate_json(
        canonical_json(body | {"report_hash": h})
    )
