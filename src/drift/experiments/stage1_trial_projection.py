"""Exact derived synthetic trial economics, separate from original accounting.

Each trial is a chronological interval of ONE carried account. A whole-run
RESULT is never counted as a fresh independent account at each checkpoint.
Trading costs already in NAV are reported, never subtracted twice. Operating
costs keep unknown/estimated/actual/verified-zero distinctions and immutable
supersession. Nothing in these arithmetic objects grants source qualification.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from math import gcd
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.intelligence.contracts import CostReceipt
from drift.intelligence.receipts import ResearchReceiptStore
from drift.loop.stage1_controlled_contracts import (
    OriginalReferenceV1,
    exact_decimal,
    finite_fraction,
)
from drift.serialization.canonical import content_hash


class ExactRatioV1(FrozenModel):
    numerator: int = Field(strict=True)
    denominator: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def require_reduced(self) -> Self:
        if gcd(abs(self.numerator), self.denominator) != 1:
            raise ValueError("TRIAL_RATIO_NOT_REDUCED")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> Self:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class OperatingCostProjectionV1(FrozenModel):
    currency: Literal["USD"] = "USD"
    status: Literal["UNAVAILABLE", "ESTIMATED", "ACTUAL", "VERIFIED_ZERO"]
    amount: Decimal | None
    original_receipt_hashes: tuple[SHA256Hash, ...]
    effective_receipt_hashes: tuple[SHA256Hash, ...]

    @model_validator(mode="after")
    def require_cost_shape(self) -> Self:
        if len(set(self.original_receipt_hashes)) != len(self.original_receipt_hashes):
            raise ValueError("TRIAL_DUPLICATE_ORIGINAL_COST")
        if len(set(self.effective_receipt_hashes)) != len(
            self.effective_receipt_hashes
        ):
            raise ValueError("TRIAL_DUPLICATE_EFFECTIVE_COST")
        if not set(self.effective_receipt_hashes) <= set(self.original_receipt_hashes):
            raise ValueError("TRIAL_EFFECTIVE_COST_NOT_ORIGINAL")
        if self.status == "UNAVAILABLE":
            if self.amount is not None:
                raise ValueError("TRIAL_UNKNOWN_COST_CANNOT_HAVE_AMOUNT")
        elif not self.effective_receipt_hashes or self.amount is None:
            raise ValueError("TRIAL_KNOWN_COST_REQUIRES_ORIGINAL_EVIDENCE")
        elif finite_fraction(self.amount) < 0:
            raise ValueError("TRIAL_NEGATIVE_COST")
        elif self.status == "VERIFIED_ZERO" and self.amount != 0:
            raise ValueError("TRIAL_ZERO_COST_CONTRADICTION")
        return self


def project_operating_costs(costs: Sequence[CostReceipt]) -> OperatingCostProjectionV1:
    """Revalidate immutable lineage and sum only unsuperseded original receipts."""
    recorder = ResearchReceiptStore()
    originals: list[CostReceipt] = []
    seen: set[str] = set()
    for source in costs:
        cost = CostReceipt.model_validate_json(source.model_dump_json())
        if cost.receipt_id in seen:
            raise ValueError("TRIAL_DUPLICATE_COST_RECEIPT")
        recorder.record_cost_receipt(cost)
        originals.append(cost)
        seen.add(cost.receipt_id)
    superseded = {
        cost.supersedes_receipt_id for cost in originals if cost.supersedes_receipt_id
    }
    effective = [cost for cost in originals if cost.receipt_id not in superseded]
    hashes = tuple(cost.record_hash for cost in originals)
    effective_hashes = tuple(cost.record_hash for cost in effective)
    if not effective or any(
        cost.amount_basis == "unknown" or cost.amount is None or cost.currency != "USD"
        for cost in effective
    ):
        return OperatingCostProjectionV1(
            status="UNAVAILABLE",
            amount=None,
            original_receipt_hashes=hashes,
            effective_receipt_hashes=effective_hashes,
        )
    amount = exact_decimal(
        sum(
            (
                Fraction(Decimal(cost.amount))
                for cost in effective
                if cost.amount is not None
            ),
            Fraction(0),
        )
    )
    status: Literal["ESTIMATED", "ACTUAL", "VERIFIED_ZERO"] = "ACTUAL"
    if any(cost.amount_basis == "estimate" for cost in effective):
        status = "ESTIMATED"
    elif all(cost.amount_basis == "verified_zero" for cost in effective):
        status = "VERIFIED_ZERO"
    return OperatingCostProjectionV1(
        status=status,
        amount=amount,
        original_receipt_hashes=hashes,
        effective_receipt_hashes=effective_hashes,
    )


class ControlledTrialProjectionV1(FrozenModel):
    profile: Literal["drift-local-synthetic-trial/1"] = "drift-local-synthetic-trial/1"
    campaign_id: NonBlankStr
    run_id: NonBlankStr
    arm_id: NonBlankStr
    account_id: NonBlankStr
    checkpoint_id: NonBlankStr
    trial_id: NonBlankStr
    manifest_hash: SHA256Hash
    original_allocation: OriginalReferenceV1
    original_result: OriginalReferenceV1 | None
    snapshot_tip: OriginalReferenceV1
    original_event_hashes: tuple[SHA256Hash, ...]
    start_session_index: int = Field(strict=True, ge=0)
    end_session_index: int | None = Field(default=None, strict=True, ge=0)
    outcome: Literal[
        "COMPLETED",
        "RETAINED",
        "REFUSED",
        "NO_ATTEMPT",
        "FAILED_RESEARCH",
        "UNRESOLVED",
        "NOT_YET_DUE",
    ]
    complete_interval: bool = Field(strict=True)
    selected_family: Literal["B3", "B4", "B5"] | None
    start_nav: Decimal | None
    end_nav: Decimal | None
    trading_costs: Decimal | None
    net_investment_gain: Decimal | None
    net_investment_return: ExactRatioV1 | None
    operating_cost: OperatingCostProjectionV1
    economic_gain: Decimal | None
    economic_return: ExactRatioV1 | None
    reason: NonBlankStr
    projection_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if (
            self.end_session_index is not None
            and self.end_session_index < self.start_session_index
        ):
            raise ValueError("TRIAL_NEGATIVE_INTERVAL")
        if len(set(self.original_event_hashes)) != len(self.original_event_hashes):
            raise ValueError("TRIAL_DUPLICATE_ORIGINAL_EVENT")
        derived = (
            self.net_investment_gain,
            self.net_investment_return,
            self.economic_gain,
            self.economic_return,
        )
        if self.complete_interval:
            if (
                self.original_result is None
                or self.start_nav is None
                or self.end_nav is None
                or self.end_session_index is None
                or self.end_session_index <= self.start_session_index
                or self.trading_costs is None
            ):
                raise ValueError("TRIAL_COMPLETE_INTERVAL_WITHOUT_ORIGINALS")
            if self.outcome in ("UNRESOLVED", "NOT_YET_DUE"):
                raise ValueError("TRIAL_UNRESOLVED_CANNOT_BE_COMPLETE")
            start, end = finite_fraction(self.start_nav), finite_fraction(self.end_nav)
            if start <= 0 or end < 0 or finite_fraction(self.trading_costs) < 0:
                raise ValueError("TRIAL_INVALID_ACCOUNT_VALUE")
            gain = end - start
            if self.net_investment_gain != exact_decimal(
                gain
            ) or self.net_investment_return != ExactRatioV1.from_fraction(gain / start):
                raise ValueError("TRIAL_FALSE_NET_ARITHMETIC")
            if self.operating_cost.amount is None:
                if self.economic_gain is not None or self.economic_return is not None:
                    raise ValueError("TRIAL_UNKNOWN_OPERATING_COST_NOT_ZERO")
            else:
                economic = gain - finite_fraction(self.operating_cost.amount)
                if self.economic_gain != exact_decimal(
                    economic
                ) or self.economic_return != ExactRatioV1.from_fraction(
                    economic / start
                ):
                    raise ValueError("TRIAL_FALSE_ECONOMIC_ARITHMETIC")
        elif any(value is not None for value in derived):
            raise ValueError("TRIAL_INCOMPLETE_CANNOT_CLAIM_GAIN")
        data = self.model_dump(mode="python")
        data.pop("projection_hash")
        if content_hash(data) != self.projection_hash:
            raise ValueError("TRIAL_PROJECTION_HASH_MISMATCH")
        return self

    @property
    def scientifically_qualified(self) -> bool:
        return False

    @property
    def authorizes_trading(self) -> bool:
        return False


def make_trial_projection(
    *,
    campaign_id: str,
    run_id: str,
    arm_id: str,
    account_id: str,
    checkpoint_id: str,
    trial_id: str,
    manifest_hash: str,
    original_allocation: OriginalReferenceV1,
    original_result: OriginalReferenceV1 | None,
    snapshot_tip: OriginalReferenceV1,
    original_event_hashes: tuple[str, ...],
    start_session_index: int,
    end_session_index: int | None,
    outcome: Literal[
        "COMPLETED",
        "RETAINED",
        "REFUSED",
        "NO_ATTEMPT",
        "FAILED_RESEARCH",
        "UNRESOLVED",
        "NOT_YET_DUE",
    ],
    complete_interval: bool,
    selected_family: Literal["B3", "B4", "B5"] | None,
    start_nav: Decimal | None,
    end_nav: Decimal | None,
    trading_costs: Decimal | None,
    costs: Sequence[CostReceipt],
    reason: str,
) -> ControlledTrialProjectionV1:
    operating = project_operating_costs(costs)
    net_gain = economic_gain = None
    net_return = economic_return = None
    if complete_interval and start_nav is not None and end_nav is not None:
        start = finite_fraction(start_nav)
        gain = finite_fraction(end_nav) - start
        net_gain, net_return = (
            exact_decimal(gain),
            ExactRatioV1.from_fraction(gain / start),
        )
        if operating.amount is not None:
            economic = gain - finite_fraction(operating.amount)
            economic_gain, economic_return = (
                exact_decimal(economic),
                ExactRatioV1.from_fraction(economic / start),
            )
    data = dict(
        profile="drift-local-synthetic-trial/1",
        campaign_id=campaign_id,
        run_id=run_id,
        arm_id=arm_id,
        account_id=account_id,
        checkpoint_id=checkpoint_id,
        trial_id=trial_id,
        manifest_hash=manifest_hash,
        original_allocation=original_allocation,
        original_result=original_result,
        snapshot_tip=snapshot_tip,
        original_event_hashes=original_event_hashes,
        start_session_index=start_session_index,
        end_session_index=end_session_index,
        outcome=outcome,
        complete_interval=complete_interval,
        selected_family=selected_family,
        start_nav=start_nav,
        end_nav=end_nav,
        trading_costs=trading_costs,
        net_investment_gain=net_gain,
        net_investment_return=net_return,
        operating_cost=operating,
        economic_gain=economic_gain,
        economic_return=economic_return,
        reason=reason,
    )
    data["projection_hash"] = content_hash(data)
    return ControlledTrialProjectionV1.model_validate(data)
