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

The feasibility report producer is unavailable until original targets, prices,
account evidence and independent mandate review can be authenticated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.synthetic_execution import ProtectiveCorrectionPolicyV1
from drift.experiments.stage1_study_freeze import StudyMandateV1
from drift.loop.stage1_controlled_contracts import (
    ClassMandateV1,
    SecurityMandateV1,
    SyntheticMandateV1,
)
from drift.qualification.alpaca_sip_verification import (
    BOND_ETFS,
    EQUITY_ETFS,
)
from drift.serialization.canonical import content_hash

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
    """Refuse until original feasibility evidence can be authenticated."""
    raise ValueError(
        "MANDATE_FEASIBILITY_UNAVAILABLE: original evidence not authenticated"
    )
