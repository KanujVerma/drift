"""M2 exploratory cohort authorization and scheduled source-basis reconstruction.

These contracts are deliberately exploratory-only. An
``ExploratoryCohortAuthorizationV1`` is experiment SCOPE evidence: it records
which securities a specific exploratory run is authorized to consider. It is NOT
proof of universe membership, survivorship-free selection, structural listing
eligibility, primary listing, or historical availability of any record. An
``ExploratoryReconstructedSessionObservationV1`` is a source-basis retrospective
projection under scheduled-session reconstruction. It is NOT a
``DerivedObservationViewV1``, not an ``ObservationDecisionReferenceV1`` or
``ObservationOutcomeReferenceV1``, not an M1d ``NormalizationResultV1``, not proof
of a realized session, not proof of historical publication availability, not
proof of the absence of halts, and never promotion-grade evidence.
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import ValidationInfo, field_validator, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

REQUIRED_RECONSTRUCTION_FIELDS: tuple[str, ...] = (
    "close",
    "high",
    "low",
    "open",
    "volume",
)
"""Canonical required exploratory fields for scheduled source-basis reconstruction."""

_COHORT_SORT_KEY = str


def cohort_authorization_hash(cohort: ExploratoryCohortAuthorizationV1) -> SHA256Hash:
    """Compute the canonical content hash for ExploratoryCohortAuthorizationV1."""
    dump = cohort.model_dump(mode="python")
    dump.pop("cohort_hash", None)
    return content_hash(dump)


def reconstruction_policy_hash(policy: ExploratoryReconstructionPolicyV1) -> SHA256Hash:
    """Compute the canonical content hash for ExploratoryReconstructionPolicyV1."""
    dump = policy.model_dump(mode="python")
    dump.pop("policy_hash", None)
    return content_hash(dump)


def exploratory_reconstruction_semantic_hash() -> SHA256Hash:
    """Return the fixed semantic identity of the V1 scheduled source-basis policy."""
    return content_hash(
        {
            "algorithm_id": "drift.exploratory-source-basis-scheduled-reconstruction",
            "version": "1",
            "mode": "source_basis_scheduled_session_reconstruction_v1",
            "required_fields": list(REQUIRED_RECONSTRUCTION_FIELDS),
            "required_basis": "unadjusted",
            "field_meanings": {
                "open": "price",
                "high": "price",
                "low": "price",
                "close": "price",
                "volume": "share_volume",
            },
            "rule": (
                "interpret exact retained current-vintage source fields through "
                "the selected authenticated observation contract without any "
                "adjustment, split factor, or derived normalization"
            ),
        }
    )


class ExploratoryCohortAuthorizationV1(FrozenModel):
    """Predeclared bounded security cohort authorizing exploratory runs.

    Scope only: any input built on this cohort requires
    ``ALPACA_LIMITATION_BOUNDED_COHORT`` to be acknowledged by the exploratory
    admission. This contract makes no universe-membership, listing-history, or
    historical-availability claim.
    """

    schema_version: Literal["1"] = "1"
    kind: Literal["predeclared_bounded_security_cohort"] = (
        "predeclared_bounded_security_cohort"
    )
    cohort_id: NonBlankStr
    cohort_version: NonBlankStr
    security_ids: tuple[UUID7, ...]
    cohort_hash: SHA256Hash

    @field_validator("security_ids")
    @classmethod
    def canonicalize_security_ids(cls, values: tuple[UUID7, ...]) -> tuple[UUID7, ...]:
        if not values:
            raise ValueError("cohort requires at least one security")
        if len(set(values)) != len(values):
            raise ValueError("cohort security IDs must be unique")
        return tuple(sorted(values, key=_COHORT_SORT_KEY))

    @model_validator(mode="after")
    def validate_cohort(self) -> Self:
        expected = cohort_authorization_hash(self)
        if self.cohort_hash != expected:
            raise ValueError(
                f"cohort hash mismatch: expected {expected}, got {self.cohort_hash}"
            )
        return self


class ExploratoryReconstructionPolicyV1(FrozenModel):
    """Fixed source-basis reconstruction policy for scheduled exploratory inputs."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    mode: Literal["source_basis_scheduled_session_reconstruction_v1"] = (
        "source_basis_scheduled_session_reconstruction_v1"
    )
    required_fields: tuple[str, ...] = REQUIRED_RECONSTRUCTION_FIELDS
    required_basis: Literal["unadjusted"] = "unadjusted"
    semantic_policy_hash: SHA256Hash
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if tuple(self.required_fields) != REQUIRED_RECONSTRUCTION_FIELDS:
            raise ValueError(
                "reconstruction policy requires exactly the canonical fields"
            )
        if self.semantic_policy_hash != exploratory_reconstruction_semantic_hash():
            raise ValueError("reconstruction semantic policy hash mismatch")
        expected = reconstruction_policy_hash(self)
        if self.policy_hash != expected:
            raise ValueError(
                f"reconstruction policy hash mismatch: expected {expected}, "
                f"got {self.policy_hash}"
            )
        return self


class ExploratoryReconstructedFieldV1(FrozenModel):
    """One exact source-basis field projected from a source record field."""

    schema_version: Literal["1"] = "1"
    field_name: NonBlankStr
    source_value: Decimal
    method_id: NonBlankStr
    meaning: Literal["price", "share_volume"]
    source_field_hash: SHA256Hash

    @field_validator("source_value", mode="before")
    @classmethod
    def require_exact_decimal(cls, value: object, info: ValidationInfo) -> Decimal:
        if info.mode == "json" and isinstance(value, str):
            try:
                parsed = Decimal(value)
            except (ArithmeticError, ValueError) as error:
                raise ValueError(
                    "reconstructed field requires an exact decimal string"
                ) from error
            if parsed.is_finite():
                return parsed
        elif info.mode == "python" and isinstance(value, Decimal):
            if value.is_finite():
                return value
        raise ValueError("reconstructed field requires an exact decimal value")

    @model_validator(mode="after")
    def validate_field(self) -> Self:
        if self.field_name not in REQUIRED_RECONSTRUCTION_FIELDS:
            raise ValueError(f"unsupported reconstruction field: {self.field_name}")
        expected_meaning = "share_volume" if self.field_name == "volume" else "price"
        if self.meaning != expected_meaning:
            raise ValueError(
                f"reconstructed field {self.field_name} requires meaning "
                f"'{expected_meaning}'"
            )
        return self


class ExploratoryReconstructedSessionObservationV1(FrozenModel):
    """Exploratory-only scheduled source-basis reconstruction of one session.

    This artifact deliberately binds weaker evidence than strict M1d views. It
    carries no realized-session claim, no historical publication-time proof, no
    universe or structural eligibility proof, and no split normalization.
    """

    schema_version: Literal["1"] = "1"
    kind: Literal["exploratory_reconstructed_session_observation"] = (
        "exploratory_reconstructed_session_observation"
    )
    session_key: SessionKeyV1
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    cohort_hash: SHA256Hash
    source_observation_hash: SHA256Hash
    observation_contract_hash: SHA256Hash
    observation_selection_proof_hash: SHA256Hash
    contract_selection_proof_hash: SHA256Hash
    scheduled_session_hash: SHA256Hash
    scheduled_selection_proof_hash: SHA256Hash
    schedule_artifact_hash: SHA256Hash
    generated_session_row_hash: SHA256Hash
    outcome_query_hash: SHA256Hash
    source_context_hash: SHA256Hash
    evidence_vintage_cutoff: UTCDateTime
    reconstruction_policy_hash: SHA256Hash
    currency: NonBlankStr
    fields: tuple[ExploratoryReconstructedFieldV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    reconstruction_hash: SHA256Hash

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[ExploratoryReconstructedFieldV1, ...]
    ) -> tuple[ExploratoryReconstructedFieldV1, ...]:
        names = tuple(item.field_name for item in fields)
        if len(set(names)) != len(names):
            raise ValueError("reconstructed fields must not repeat a name")
        if set(names) != set(REQUIRED_RECONSTRUCTION_FIELDS):
            raise ValueError("reconstruction requires exactly the five OHLCV fields")
        return tuple(sorted(fields, key=lambda item: item.field_name))

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("reconstruction limitations must be unique")
        required = (
            ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
            ALPACA_LIMITATION_UNVERSIONED_BARS,
        )
        if not set(required).issubset(values):
            raise ValueError("reconstruction requires its retrospective limitations")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_reconstruction(self) -> Self:
        expected = exploratory_reconstruction_hash(self)
        if self.reconstruction_hash != expected:
            raise ValueError(
                f"reconstruction hash mismatch: expected {expected}, "
                f"got {self.reconstruction_hash}"
            )
        return self


def exploratory_reconstruction_hash(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> SHA256Hash:
    """Compute the canonical hash of an exploratory reconstructed observation."""
    dump = observation.model_dump(mode="python")
    dump.pop("reconstruction_hash", None)
    return content_hash(dump)


def cohort_required_limitations(
    cohort: ExploratoryCohortAuthorizationV1,
) -> tuple[NonBlankStr, ...]:
    """Return the limitation any exploratory run over this cohort must bind."""
    return (ALPACA_LIMITATION_BOUNDED_COHORT,)


def exploratory_required_limitations(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> tuple[NonBlankStr, ...]:
    """Return the limitations the exploratory reconstruction always binds."""
    return observation.acknowledged_limitations
