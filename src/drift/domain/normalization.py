"""Immutable contracts for source-basis and split-normalized observations."""

import re
from decimal import Decimal
from math import gcd
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationQueryV1,
    m1d_implementation_hash,
)
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

_MAX_INTEGER_DIGITS = 4096
_MAX_OUTPUT_SCALE = 1000

_NORMALIZATION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "causal-source-and-split-normalization-v1",
    "source_basis": "unadjusted-exact-native-decimal-without-economic-context",
    "split_basis": "complete-m1c-history-plus-replayed-first-post-session-mappings",
    "anchor_basis": "exact-open-or-closed-anchor-opening-companion",
    "economic_window": "exact-source-open-through-proven-anchor-open",
    "occurrence_groups": "compare-complete-selected-group-before-neutrality-or-window",
    "split_units": "price-reciprocal-and-share-volume-forward",
    "arithmetic": "exact-rational-single-final-half-even-quantization",
    "computational_guard": "pre-fraction-digit-exponent-scale-product-bound",
    "references": "full-query-role-context-dependent-replay",
}


def normalization_algorithm_hash() -> str:
    """Return the semantic identity of the v1 normalization algorithm."""
    return content_hash(_NORMALIZATION_ALGORITHM_V1)


class ExactRatioV1(FrozenModel):
    """A reduced signed rational represented by canonical integer strings."""

    schema_version: Literal["1"] = "1"
    numerator: str
    denominator: str

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        if (
            re.fullmatch(r"(?:0|-?[1-9][0-9]*)", self.numerator) is None
            or re.fullmatch(r"[1-9][0-9]*", self.denominator) is None
        ):
            raise ValueError("exact ratio requires canonical integer components")
        numerator_digits = self.numerator.removeprefix("-")
        if (
            len(numerator_digits) > _MAX_INTEGER_DIGITS
            or len(self.denominator) > _MAX_INTEGER_DIGITS
        ):
            raise ValueError("exact ratio exceeds the computational digit guard")
        numerator = int(self.numerator)
        denominator = int(self.denominator)
        if numerator == 0 and self.denominator != "1":
            raise ValueError("zero exact ratio must be represented as 0/1")
        if gcd(abs(numerator), denominator) != 1:
            raise ValueError("exact ratio must be reduced")
        return self


class NormalizationPolicyV1(FrozenModel):
    """Versioned source-basis or split-normalization policy."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    mode: Literal["source_basis", "split_normalized"]
    profile_hash: SHA256Hash
    mapping_policy_hash: SHA256Hash | None
    price_output_scale: int | None
    volume_output_scale: int | None
    rounding: Literal["half_even"]
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @field_validator("price_output_scale", "volume_output_scale")
    @classmethod
    def validate_scale(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= _MAX_OUTPUT_SCALE:
            raise ValueError("normalization scale exceeds the computational guard")
        return value

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.semantic_algorithm_hash != normalization_algorithm_hash():
            raise ValueError("normalization semantic algorithm hash mismatch")
        if self.implementation_hash != m1d_implementation_hash():
            raise ValueError("normalization implementation hash mismatch")
        if self.mode == "source_basis":
            if (
                self.mapping_policy_hash is not None
                or self.price_output_scale is not None
                or self.volume_output_scale is not None
            ):
                raise ValueError(
                    "source-basis policy cannot carry mapping or output scales"
                )
        elif (
            self.mapping_policy_hash is None
            or self.price_output_scale is None
            or self.volume_output_scale is None
        ):
            raise ValueError("split-normalized policy requires mapping and scales")
        return self


class FieldTransformV1(FrozenModel):
    """One exact source field and its admitted unit transformation."""

    schema_version: Literal["1"] = "1"
    field_name: Literal["open", "high", "low", "close", "volume"]
    method_id: NonBlankStr
    meaning: Literal["price", "share_volume"]
    source_value: Decimal
    exact_factor: ExactRatioV1
    exact_transformed_value: ExactRatioV1 | None
    quantized_value: Decimal | None
    output_scale: int | None = Field(ge=0, le=_MAX_OUTPUT_SCALE)
    rounded_to_zero: bool

    @model_validator(mode="after")
    def validate_transform(self) -> Self:
        if int(self.exact_factor.numerator) <= 0:
            raise ValueError("field transform factor must be strictly positive")
        expected = "share_volume" if self.field_name == "volume" else "price"
        if self.meaning != expected:
            raise ValueError("field transform meaning does not match admitted field")
        if (self.quantized_value is None) != (self.output_scale is None):
            raise ValueError(
                "quantized value and output scale must be supplied together"
            )
        if self.rounded_to_zero != (
            self.quantized_value == 0
            and self.exact_transformed_value is not None
            and self.exact_transformed_value.numerator != "0"
        ):
            raise ValueError("field rounded-to-zero marker is inconsistent")
        return self


class NormalizationQueryV1(FrozenModel):
    """A full observation query plus one exact target-basis request."""

    schema_version: Literal["1"] = "1"
    observation: ObservationQueryV1
    policy_hash: SHA256Hash
    anchor_session: SessionKeyV1 | None

    @model_validator(mode="after")
    def validate_subject(self) -> Self:
        if self.anchor_session is not None and (
            self.anchor_session.mic != self.observation.venue.value
            or self.anchor_session.local_date < self.observation.session_date
        ):
            raise ValueError("normalization anchor must match venue and follow source")
        return self


class AnchorOpeningEvidenceV1(FrozenModel):
    """Closed exact proof that one realized session reached its opening basis."""

    schema_version: Literal["1"] = "1"
    kind: Literal["anchor_session_opening"] = "anchor_session_opening"
    source_id: NonBlankStr
    logical_record_id: UUID7
    record_version_id: UUID7
    session_key: SessionKeyV1
    actual_open: UTCDateTime
    source_artifact_hash: SHA256Hash
    record_availability_evidence_hash: SHA256Hash


class NormalizationDerivationV1(FrozenModel):
    """Complete replay lineage for one derived observation payload."""

    schema_version: Literal["1"] = "1"
    query: NormalizationQueryV1
    query_hash: SHA256Hash
    role: Literal["decision", "outcome"]
    source_assessment_hash: SHA256Hash
    source_selection_proof_hash: SHA256Hash
    source_binding_hash: SHA256Hash
    normalization_policy_hash: SHA256Hash
    mapping_policy_hash: SHA256Hash | None
    action_mapping_hashes: tuple[SHA256Hash, ...]
    selected_action_hashes: tuple[SHA256Hash, ...]
    action_coverage_hashes: tuple[SHA256Hash, ...]
    session_proof_hashes: tuple[SHA256Hash, ...]
    session_record_hashes: tuple[SHA256Hash, ...]
    artifact_hashes: tuple[SHA256Hash, ...]
    dependency_hashes: tuple[SHA256Hash, ...]
    target_basis: SessionKeyV1
    price_factor: ExactRatioV1
    share_volume_factor: ExactRatioV1
    output_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash
    python_identity: NonBlankStr
    lockfile_hash: SHA256Hash

    @field_validator(
        "action_mapping_hashes",
        "selected_action_hashes",
        "action_coverage_hashes",
        "session_proof_hashes",
        "session_record_hashes",
        "artifact_hashes",
        "dependency_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("normalization derivation hashes must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_derivation(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("normalization derivation query hash mismatch")
        if self.role != self.query.observation.kind:
            raise ValueError("normalization derivation role mismatch")
        if self.normalization_policy_hash != self.query.policy_hash:
            raise ValueError("normalization derivation policy mismatch")
        if self.semantic_algorithm_hash != normalization_algorithm_hash():
            raise ValueError("normalization derivation algorithm mismatch")
        if self.implementation_hash != m1d_implementation_hash():
            raise ValueError("normalization derivation implementation mismatch")
        if (
            int(self.price_factor.numerator) <= 0
            or int(self.share_volume_factor.numerator) <= 0
        ):
            raise ValueError("normalization factors must be strictly positive")
        return self


class DerivedObservationViewV1(FrozenModel):
    """One immutable source-basis or split-normalized numeric view."""

    schema_version: Literal["1"] = "1"
    role: Literal["decision", "outcome"]
    query: NormalizationQueryV1
    query_hash: SHA256Hash
    source_session: SessionKeyV1
    listing_id: UUID7
    security_id: UUID7
    basis_mode: Literal["source_basis", "split_normalized"]
    anchor_session: SessionKeyV1 | None
    fields: tuple[FieldTransformV1, ...]
    usability_hash: SHA256Hash
    output_hash: SHA256Hash
    derivation_hash: SHA256Hash

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[FieldTransformV1, ...]
    ) -> tuple[FieldTransformV1, ...]:
        names = tuple(item.field_name for item in fields)
        if len(names) != len(set(names)) or set(names) != {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }:
            raise ValueError("derived view requires one transform for every field")
        return tuple(sorted(fields, key=lambda item: item.field_name))

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("derived view query hash mismatch")
        if self.role != self.query.observation.kind:
            raise ValueError("derived view role mismatch")
        if (
            self.listing_id != self.query.observation.listing_id
            or self.security_id != self.query.observation.security_id
            or self.source_session.local_date != self.query.observation.session_date
            or self.source_session.mic != self.query.observation.venue.value
        ):
            raise ValueError("derived view source subject mismatch")
        if self.anchor_session != self.query.anchor_session:
            raise ValueError("derived view anchor mismatch")
        if self.output_hash != derived_view_output_hash(self):
            raise ValueError("derived view output hash mismatch")
        return self


def derived_view_output_hash(view: DerivedObservationViewV1) -> str:
    """Hash a view payload without its derivation back-reference or output hash."""
    return content_hash(
        view.model_dump(mode="python", exclude={"derivation_hash", "output_hash"})
    )


class ObservationDecisionReferenceV1(FrozenModel):
    """Compact decision-role capability requiring full dependent replay."""

    schema_version: Literal["1"] = "1"
    kind: Literal["decision_reference"] = "decision_reference"
    query_hash: SHA256Hash
    view_hash: SHA256Hash
    derivation_hash: SHA256Hash
    context_hash: SHA256Hash


class ObservationOutcomeReferenceV1(FrozenModel):
    """Compact outcome-role capability requiring full dependent replay."""

    schema_version: Literal["1"] = "1"
    kind: Literal["outcome_reference"] = "outcome_reference"
    query_hash: SHA256Hash
    view_hash: SHA256Hash
    derivation_hash: SHA256Hash
    context_hash: SHA256Hash


type ObservationNormalizationReferenceV1 = Annotated[
    ObservationDecisionReferenceV1 | ObservationOutcomeReferenceV1,
    Field(discriminator="kind"),
]


class NormalizationResultV1(FrozenModel):
    """Replayable result exposing numeric data only when fully materialized."""

    schema_version: Literal["1"] = "1"
    query: NormalizationQueryV1
    query_hash: SHA256Hash
    classification: Literal["materialized", "unusable", "indeterminate"]
    reasons: tuple[NonBlankStr, ...]
    dependency_hashes: tuple[SHA256Hash, ...]
    selected_action_hashes: tuple[SHA256Hash, ...]
    action_mapping_hashes: tuple[SHA256Hash, ...]
    view: DerivedObservationViewV1 | None
    derivation: NormalizationDerivationV1 | None
    derivation_hash: SHA256Hash | None
    reference: ObservationNormalizationReferenceV1 | None
    context_hash: SHA256Hash
    policy_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @field_validator(
        "dependency_hashes", "selected_action_hashes", "action_mapping_hashes"
    )
    @classmethod
    def canonicalize_result_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("normalization result hashes must be unique")
        return tuple(sorted(values))

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("normalization result requires reasons")
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("normalization result query hash mismatch")
        if self.context_hash != self.query.observation.input_context_hash:
            raise ValueError("normalization result context mismatch")
        if self.policy_hash != self.query.policy_hash:
            raise ValueError("normalization result policy mismatch")
        if self.semantic_algorithm_hash != normalization_algorithm_hash():
            raise ValueError("normalization result algorithm mismatch")
        if self.implementation_hash != m1d_implementation_hash():
            raise ValueError("normalization result implementation mismatch")
        materialized = self.classification == "materialized"
        output_members = (
            self.view,
            self.derivation,
            self.derivation_hash,
            self.reference,
        )
        if materialized and any(value is None for value in output_members):
            raise ValueError("materialized normalization requires complete output")
        if not materialized and any(value is not None for value in output_members):
            raise ValueError("nonmaterialized normalization cannot carry output")
        if materialized:
            assert self.view is not None
            assert self.derivation is not None
            assert self.derivation_hash is not None
            assert self.reference is not None
            if (
                self.derivation_hash != content_hash(self.derivation)
                or self.view.derivation_hash != self.derivation_hash
                or self.derivation.output_hash != self.view.output_hash
                or self.reference.query_hash != self.query_hash
                or self.reference.view_hash != content_hash(self.view)
                or self.reference.derivation_hash != self.derivation_hash
                or self.reference.context_hash != self.context_hash
            ):
                raise ValueError("normalization output lineage mismatch")
            decision = isinstance(self.query.observation, ObservationDecisionQueryV1)
            if decision != isinstance(self.reference, ObservationDecisionReferenceV1):
                raise ValueError("normalization reference role mismatch")
        return self
