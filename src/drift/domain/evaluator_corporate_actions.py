"""M2 corporate-action evidence binding and exact entitlement arithmetic.

M1c reports three separable things about one economic action: proposed *terms*,
an *occurred effect*, and a *delivered settlement*. Only the last two move a
book. Terms alone are a schedule, and this module never lets a schedule mutate
cash or shares.

Everything here is exact. Share entitlements are computed as
:class:`fractions.Fraction` values built from the source's own integer ratio,
and a cash amount that has no finite decimal spelling fails closed rather than
being rounded into existence. Binary floating point is never used: a float
would silently change a share count, and a share count is a legal fact.

Three source facts are not mechanically derivable and therefore arrive as
explicit, evidence-bound interpretation artifacts rather than as evaluator
heuristics:

* :class:`TieBreakingRuleV1` -- what ``round_nearest`` means at an exact half.
* :class:`DueBillRuleV1` -- which session a due-bill distribution vests on.
* :class:`CashInLieuRateV1` -- what an aggregate fractional-share sale realized.

Each one must be bound by content hash to the very source artifact that M1c
retained. An unbound, missing, or ambiguous artifact fails closed to
``INDETERMINATE``; none of them has a default.
"""

from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr
from drift.domain.economic_common import (
    CanonicalCash,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
)
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.temporal import SourcePrecision
from drift.serialization.canonical import content_hash

type TieBreak = Literal["half_up", "half_down", "half_even"]

CASH_IN_LIEU_MARKER = "#cash-in-lieu:"
"""Separator that marks a derived cash-in-lieu leg inside a component id.

``PendingCashClaimV1`` has no field for a fractional-share quantum, so the
exact residual fraction is carried in the derived component id. The residual is
therefore part of claim identity, which is correct: two different residuals on
one occurrence are two different entitlements.
"""


def cash_in_lieu_component_id(component_id: str, residual: Fraction) -> str:
    """Derive the component id of one aggregate-sale cash-in-lieu leg."""
    if residual <= 0 or residual >= 1:
        raise ValueError("a cash-in-lieu residual must be a proper positive fraction")
    quantum = f"{residual.numerator}/{residual.denominator}"
    return f"{component_id}{CASH_IN_LIEU_MARKER}{quantum}"


def cash_in_lieu_origin(component_id: str) -> str | None:
    """Return the originating share component id of a cash-in-lieu leg."""
    head, marker, _ = component_id.partition(CASH_IN_LIEU_MARKER)
    return head if marker else None


def ratio_fraction(ratio: PositiveRatioV1) -> Fraction:
    """Exact rational value of one source ratio, without any float step."""
    return Fraction(int(ratio.numerator), int(ratio.denominator))


def exact_entitled_shares(quantity: int, component: ShareComponentV1) -> Fraction:
    """Exact resulting share count for one share component's recipient.

    ``ratio_meaning`` is not interchangeable. ``resulting_per_predecessor``
    replaces the predecessor count; ``additional_per_predecessor`` adds to it
    when the recipient is the same security, and describes a fresh child
    entitlement when the recipient is a different security.
    """
    if quantity <= 0:
        raise ValueError("share entitlement requires a positive predecessor quantity")
    recipient = component.recipient
    if recipient.kind != "security" or recipient.security_id is None:
        raise IndeterminateValuationError(
            "share entitlement requires a resolved security recipient"
        )
    if component.unit_basis.share_basis == "as_reported_unknown":
        raise IndeterminateValuationError(
            "share entitlement requires a known source share basis"
        )
    ratio = ratio_fraction(component.ratio)
    scaled = quantity * ratio
    if component.ratio_meaning == "resulting_per_predecessor":
        return scaled
    if recipient.security_id == component.unit_basis.security_id:
        return quantity + scaled
    return scaled


def resolve_whole_shares(
    exact: Fraction,
    treatment: FractionTreatmentV1,
    *,
    tie_break: TieBreak | None,
) -> tuple[int, Fraction]:
    """Resolve an exact entitlement into whole shares and a cash-in-lieu residual.

    Returns the whole-share count and the residual fraction that must be paid
    as cash in lieu. The residual is nonzero only for ``aggregate_sale_cash``:
    every other resolvable treatment consumes the fraction.
    """
    if exact < 0:
        raise ValueError("share entitlement cannot be negative")
    whole = exact.numerator // exact.denominator
    residual = exact - whole
    if residual == 0:
        return whole, Fraction(0)
    kind = treatment.kind
    if kind in {"fraction_issued", "unknown"}:
        raise IndeterminateValuationError(
            f"fractional share entitlement has no resolvable fraction treatment: {kind}"
        )
    if kind == "round_down":
        return whole, Fraction(0)
    if kind == "round_up":
        return whole + 1, Fraction(0)
    if kind == "aggregate_sale_cash":
        return whole, residual
    if tie_break is None:
        raise IndeterminateValuationError(
            "round_nearest requires an interpreted source tie-breaking rule bound "
            "to its own fraction-treatment evidence"
        )
    half = Fraction(1, 2)
    if residual > half:
        return whole + 1, Fraction(0)
    if residual < half:
        return whole, Fraction(0)
    if tie_break == "half_up":
        return whole + 1, Fraction(0)
    if tie_break == "half_down":
        return whole, Fraction(0)
    return (whole if whole % 2 == 0 else whole + 1), Fraction(0)


def exact_decimal(value: Fraction) -> Decimal:
    """Convert an exact rational into a Decimal without losing a cent.

    A quotient whose denominator has a prime factor other than two or five has
    no finite decimal spelling. Rounding one into a book invents or destroys
    money, so this fails closed instead.
    """
    denominator = value.denominator
    residue = denominator
    for prime in (2, 5):
        while residue % prime == 0:
            residue //= prime
    if residue != 1:
        raise IndeterminateValuationError(
            f"cash amount {value.numerator}/{denominator} is not exactly "
            "representable as a decimal"
        )
    scale = 0
    power = 1
    while power % denominator != 0:
        power *= 10
        scale += 1
    scaled = value.numerator * (power // denominator)
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).rjust(scale + 1, "0")
    text = digits if scale == 0 else f"{digits[:-scale]}.{digits[-scale:]}"
    # Decimal built from text is exact and never consults the active context.
    return Decimal(f"{sign}{text}")


def boundary_session_date(boundary: TemporalBoundaryClaimV1, *, role: str) -> date:
    """Read the source's own calendar date out of an exact time boundary.

    The source label is used rather than a converted UTC instant so that no
    timezone is invented on the evaluator's behalf. A boundary that does not
    pin a single source date fails closed.
    """
    label = boundary.source_time_label
    if label is not None:
        if boundary.shape is BoundaryShape.EXACT:
            return date.fromisoformat(label[:10])
        if (
            boundary.shape is BoundaryShape.BOUNDED
            and boundary.source_precision is SourcePrecision.DATE
        ):
            return date.fromisoformat(label)
    raise IndeterminateValuationError(
        f"source {role} does not pin an exact session date"
    )


class TieBreakingRuleV1(FrozenModel):
    """An explicitly interpreted source tie-breaking rule for ``round_nearest``.

    ``round_nearest`` is ambiguous at an exact half, and the ambiguity is worth
    a whole share. This artifact records the interpretation actually read out
    of one retained source artifact; it is matched by that artifact's content
    hash, never by guessing at rule text.
    """

    schema_version: Literal["1"] = "1"
    source_rule: NonBlankStr
    evidence_reference: ArtifactReference
    tie_break: TieBreak

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        validate_safe_provenance_reference(self.evidence_reference)
        return self


class DueBillRuleV1(FrozenModel):
    """A proven executable due-bill entitlement rule, or an explicit ambiguity.

    Due-bill entitlement is a venue rule, not an arithmetic identity. The
    evaluator therefore never derives the entitlement session from any other
    date. It reads it from here, or it fails closed.
    """

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    security_id: UUID7
    occurrence_id: NonBlankStr
    rule_reference: ArtifactReference
    source_rule: NonBlankStr
    executability: Literal["executable", "ambiguous"]
    entitlement_session: date | None = None
    redemption_session: date | None = None
    reason: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        validate_safe_provenance_reference(self.rule_reference)
        if self.executability == "executable":
            if (
                self.entitlement_session is None
                or self.redemption_session is None
                or self.reason is not None
            ):
                raise ValueError(
                    "executable due-bill rule requires both proven sessions and "
                    "carries no ambiguity reason"
                )
        elif (
            self.entitlement_session is not None
            or self.redemption_session is not None
            or self.reason is None
        ):
            raise ValueError(
                "ambiguous due-bill rule requires a reason and asserts no session"
            )
        return self


class CashInLieuRateV1(FrozenModel):
    """A source-proven aggregate-sale cash rate per whole predecessor share.

    An aggregate fractional-share sale realizes a price that no ratio predicts.
    Recording the residual without this rate would either invent a number or
    strand real proceeds, so the rate is required evidence.
    """

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    security_id: UUID7
    occurrence_id: NonBlankStr
    component_id: NonBlankStr
    evidence_reference: ArtifactReference
    cash_per_whole_share: CanonicalCash
    currency_namespace: NonBlankStr
    currency_code: NonBlankStr

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        validate_safe_provenance_reference(self.evidence_reference)
        return self


class SecurityEconomicOutcomeV1(FrozenModel):
    """One security's M1c outcome resolution bound to the records it selected.

    ``EconomicOutcomeResolutionV1`` is an audit artifact: its effect
    projections name source records only by hash. Accounting needs the records
    themselves for occurrence identity, effective dates, and source terms, so
    this model carries both halves and proves they describe each other.
    """

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    resolution: EconomicOutcomeResolutionV1
    terms_records: tuple[CorporateActionTermsVersionV1, ...] = ()
    effect_records: tuple[EconomicEffectVersionV1, ...] = ()

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.resolution.query.security_id != self.security_id:
            raise ValueError(
                "economic outcome resolution must be scoped to the same security"
            )
        allowed_terms = set(self.resolution.selected_terms_hashes) | set(
            self.resolution.upcoming_terms_hashes
        )
        seen_terms: set[str] = set()
        for record in self.terms_records:
            if record.security_id != self.security_id:
                raise ValueError("terms record must describe the outcome security")
            digest = content_hash(record)
            if digest in seen_terms:
                raise ValueError("terms records must be unique")
            seen_terms.add(digest)
            if digest not in allowed_terms:
                raise ValueError(
                    "terms record is not selected by its outcome resolution"
                )
        projections = self.resolution.effect_projections
        projection_hashes = {item.source_record_hash for item in projections}
        if len(projection_hashes) != len(projections):
            raise ValueError("effect projections must be unique by source record")
        effect_hashes: set[str] = set()
        for effect in self.effect_records:
            if effect.security_id != self.security_id:
                raise ValueError("effect record must describe the outcome security")
            digest = content_hash(effect)
            if digest in effect_hashes:
                raise ValueError("effect records must be unique")
            effect_hashes.add(digest)
        if effect_hashes != projection_hashes:
            raise ValueError(
                "effect records and effect projections must correspond exactly"
            )
        for group in self.resolution.delivery_groups:
            if group.security_id != self.security_id:
                raise ValueError("delivery group must describe the outcome security")
        return self
