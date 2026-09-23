"""EXPLORATORY-only accounting prices read from verified reconstructions.

The issue 42 ruling let reconstructed evidence drive decisions only, so a
trading baseline over a ``scheduled_session_reconstruction`` bundle halted
INDETERMINATE at its first execution open. The issue 54 ruling (Q2 in #62,
option C) admits reconstructed prices into accounting in the EXPLORATORY
reconstructed lane only, through this dedicated record: a reconstructed open
is an exploratory execution price and a reconstructed close is an exploratory
mark.

The record is deliberately not a ``DerivedObservationViewV1`` and shares no
base with one, so a reconstructed price can never be read as an authentic
accounting view. It declares its grade as literals on a frozen model, binds
the reconstruction it was read from together with that reconstruction's
scheduled authority, and carries every limitation the reconstruction states.
It is only ever read from a reconstruction the lane gate has already
re-derived (issue 55); missing or ambiguous evidence is never defaulted, and
the engine halts INDETERMINATE instead.
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    ExploratoryReconstructedEvidenceGrade,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

type ExploratoryAccountingPriceRole = Literal["open", "close"]
"""``open`` prices exploratory execution; ``close`` prices exploratory marks."""

ZERO = Decimal("0")


class ExploratoryReconstructedAccountingPriceV1(FrozenModel):
    """One unadjusted accounting price read from one verified reconstruction."""

    schema_version: Literal["1"] = "1"
    kind: Literal["exploratory_reconstructed_accounting_price"] = (
        "exploratory_reconstructed_accounting_price"
    )
    evidence_grade: ExploratoryReconstructedEvidenceGrade = (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    )
    is_promotion_grade_evidence: Literal[False] = False
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    session_key: SessionKeyV1
    field_role: ExploratoryAccountingPriceRole
    price_basis: Literal["unadjusted"] = "unadjusted"
    unadjusted_price: Decimal
    currency: NonBlankStr
    reconstruction_hash: SHA256Hash
    source_field_hash: SHA256Hash
    scheduled_session_hash: SHA256Hash
    generated_session_row_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    price_hash: SHA256Hash

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("accounting price limitations must be unique")
        required = (
            ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
            ALPACA_LIMITATION_UNVERSIONED_BARS,
        )
        if not set(required).issubset(values):
            raise ValueError(
                "a reconstructed accounting price requires its retrospective "
                "limitations"
            )
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_price(self) -> Self:
        with decimal_context():
            if not self.unadjusted_price.is_finite() or self.unadjusted_price <= ZERO:
                raise ValueError(
                    "a reconstructed accounting price must be strictly positive"
                )
        expected = exploratory_accounting_price_hash(self)
        if self.price_hash != expected:
            raise ValueError(
                f"accounting price hash mismatch: expected {expected}, "
                f"got {self.price_hash}"
            )
        return self


def exploratory_accounting_price_hash(
    price: ExploratoryReconstructedAccountingPriceV1,
) -> SHA256Hash:
    """Compute the self-excluding canonical hash of one accounting price."""
    dump = price.model_dump(mode="python")
    dump.pop("price_hash", None)
    return content_hash(dump)


def reconstructed_accounting_price(
    observation: ExploratoryReconstructedSessionObservationV1,
    field_role: ExploratoryAccountingPriceRole,
) -> ExploratoryReconstructedAccountingPriceV1:
    """Read the ``field_role`` price out of one reconstruction.

    This reads and binds; it does not verify. Only a reconstruction the
    reconstructed lane gate has already re-derived may be passed here.
    """
    field = next(item for item in observation.fields if item.field_name == field_role)
    draft = ExploratoryReconstructedAccountingPriceV1.model_construct(
        schema_version="1",
        kind="exploratory_reconstructed_accounting_price",
        evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
        is_promotion_grade_evidence=False,
        security_id=observation.security_id,
        listing_id=observation.listing_id,
        venue=observation.venue,
        session_key=observation.session_key,
        field_role=field_role,
        price_basis="unadjusted",
        unadjusted_price=field.source_value,
        currency=observation.currency,
        reconstruction_hash=observation.reconstruction_hash,
        source_field_hash=field.source_field_hash,
        scheduled_session_hash=observation.scheduled_session_hash,
        generated_session_row_hash=observation.generated_session_row_hash,
        acknowledged_limitations=observation.acknowledged_limitations,
        price_hash="0" * 64,
    )
    return ExploratoryReconstructedAccountingPriceV1.model_validate(
        draft.model_copy(
            update={"price_hash": exploratory_accounting_price_hash(draft)}
        ).model_dump(mode="python")
    )
