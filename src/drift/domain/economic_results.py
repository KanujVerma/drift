"""Audit-side economic comparison and composed-outcome result contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.economic_common import (
    CanonicalCash,
    EconomicComponentGapV1,
    EconomicComponentV1,
    EconomicShareBasisV1,
    EconomicSourceKeyV1,
    EconomicUnitBasisV1,
    PositiveRatioV1,
)
from drift.domain.economic_queries import MarketSelectionQueryV1
from drift.serialization.canonical import content_hash


def _canonical_hashes(hashes: tuple[SHA256Hash, ...]) -> tuple[SHA256Hash, ...]:
    if len(hashes) != len(set(hashes)):
        raise ValueError("economic result hashes must be unique")
    return tuple(sorted(hashes))


def _canonical_reasons(reasons: tuple[NonBlankStr, ...]) -> tuple[NonBlankStr, ...]:
    return tuple(sorted(set(reasons)))


class EconomicBoundaryValueV1(FrozenModel):
    """Normalized comparison value for one source time boundary."""

    shape: BoundaryShape
    lower_bound: UTCDateTime | None
    upper_bound: UTCDateTime | None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.shape is BoundaryShape.UNKNOWN:
            if self.lower_bound is not None or self.upper_bound is not None:
                raise ValueError("unknown economic boundary cannot have bounds")
        elif self.lower_bound is None or self.upper_bound is None:
            raise ValueError("known economic boundary requires both bounds")
        elif self.shape is BoundaryShape.EXACT and self.lower_bound != self.upper_bound:
            raise ValueError("exact economic boundary requires equal bounds")
        elif (
            self.shape is BoundaryShape.BOUNDED and self.lower_bound >= self.upper_bound
        ):
            raise ValueError("bounded economic boundary requires ordered bounds")
        return self


class EconomicRecipientValueV1(FrozenModel):
    """Economic recipient identity without explanatory source metadata."""

    kind: Literal["security", "unresolved_property"]
    security_id: UUID7 | None = None
    source_property_key: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.kind == "security":
            if self.security_id is None or self.source_property_key is not None:
                raise ValueError(
                    "security economic recipient requires only security ID"
                )
        elif self.security_id is not None or self.source_property_key is None:
            raise ValueError(
                "unresolved economic recipient requires only source property key"
            )
        return self


class FractionEconomicValueV1(FrozenModel):
    """Fraction-treatment economics without its evidence locator."""

    kind: Literal[
        "fraction_issued",
        "round_up",
        "round_down",
        "round_nearest",
        "aggregate_sale_cash",
        "unknown",
    ]
    source_rule: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if (self.kind == "unknown") != (self.source_rule is None):
            raise ValueError("fraction comparison source rule must match fraction kind")
        return self


class EconomicAssociationValueV1(FrozenModel):
    """Association economics without its explanatory source reason."""

    kind: Literal["identified", "native_hint", "unknown"]
    target: EconomicSourceKeyV1 | None = None
    asserted_target_version_hash: SHA256Hash | None = None
    native_hint: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.kind == "identified":
            if self.target is None or self.native_hint is not None:
                raise ValueError("identified comparison association requires a target")
        elif self.kind == "native_hint":
            if (
                self.target is not None
                or self.asserted_target_version_hash is not None
                or self.native_hint is None
            ):
                raise ValueError(
                    "native-hint comparison association requires only hint"
                )
        elif (
            self.target is not None
            or self.asserted_target_version_hash is not None
            or self.native_hint is not None
        ):
            raise ValueError("unknown comparison association has no asserted fields")
        return self


class EconomicResidualValueV1(FrozenModel):
    """Residual economics without evidence locators or explanatory reasons."""

    kind: Literal[
        "closed_for_occurrence", "closed_for_action", "outstanding", "unknown"
    ]
    scope_occurrence_id: NonBlankStr | None = None
    scope_action: EconomicAssociationValueV1 | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.kind == "closed_for_occurrence":
            if self.scope_occurrence_id is None or self.scope_action is not None:
                raise ValueError(
                    "occurrence closure comparison requires only occurrence scope"
                )
        elif self.kind == "closed_for_action":
            if (
                self.scope_occurrence_id is not None
                or self.scope_action is None
                or self.scope_action.kind != "identified"
            ):
                raise ValueError("action closure comparison requires identified action")
        elif self.scope_occurrence_id is not None:
            raise ValueError("open residual comparison cannot claim occurrence closure")
        return self


class CashEconomicValueV1(FrozenModel):
    """Cash fields that participate in same-occurrence economic equality."""

    kind: Literal["cash"]
    amount: CanonicalCash
    currency_namespace: NonBlankStr
    currency_code: NonBlankStr
    unit_basis: EconomicUnitBasisV1
    amount_basis: Literal["gross", "net", "unknown"]
    applicability: Literal["ordinary_passive_holder", "conditional", "unknown"]
    conditions: tuple[NonBlankStr, ...]

    @field_validator("conditions")
    @classmethod
    def canonicalize_conditions(
        cls, conditions: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return tuple(sorted(set(conditions)))


class ShareEconomicValueV1(FrozenModel):
    """Share fields that participate in same-occurrence economic equality."""

    kind: Literal["shares"]
    recipient: EconomicRecipientValueV1
    ratio: PositiveRatioV1
    ratio_meaning: Literal["resulting_per_predecessor", "additional_per_predecessor"]
    unit_basis: EconomicShareBasisV1
    fraction: FractionEconomicValueV1
    applicability: Literal["ordinary_passive_holder", "conditional", "unknown"]
    conditions: tuple[NonBlankStr, ...]

    @field_validator("conditions")
    @classmethod
    def canonicalize_conditions(
        cls, conditions: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return tuple(sorted(set(conditions)))


class PropertyEconomicValueV1(FrozenModel):
    """Unsupported property fields retained for exact economic equality."""

    kind: Literal["unsupported_property"]
    recipient: EconomicRecipientValueV1
    source_description: NonBlankStr


type EconomicComparisonComponentV1 = Annotated[
    CashEconomicValueV1 | ShareEconomicValueV1 | PropertyEconomicValueV1,
    Field(discriminator="kind"),
]


class SettlementEconomicPayloadV1(FrozenModel):
    """Canonical multiset comparison payload for one settlement report."""

    schema_version: Literal["1"]
    settled_boundary: EconomicBoundaryValueV1
    components: tuple[EconomicComparisonComponentV1, ...]
    residual: EconomicResidualValueV1


class EconomicAssociationResolutionV1(FrozenModel):
    """Query-bound resolution of one source association."""

    source_record_hash: SHA256Hash
    association_field: Literal["terms", "effect"]
    status: Literal["resolved", "unresolved", "conflicting"]
    selected_target_hash: SHA256Hash | None = None
    reasons: tuple[NonBlankStr, ...]

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "resolved":
            if self.selected_target_hash is None:
                raise ValueError("resolved association requires selected target hash")
        elif self.selected_target_hash is not None:
            raise ValueError("unresolved association cannot select a target")
        if self.status != "resolved" and not self.reasons:
            raise ValueError("unresolved association requires reasons")
        return self


class EconomicDeliveryGroupV1(FrozenModel):
    """One positively identified delivered occurrence and its corroborating reports."""

    source_id: NonBlankStr
    security_id: UUID7
    native_occurrence_id: NonBlankStr
    settled_time: TemporalBoundaryClaimV1
    delivered_components: tuple[EconomicComponentV1, ...]
    component_gaps: tuple[EconomicComponentGapV1, ...]
    residual_status: Literal[
        "closed_for_occurrence", "closed_for_action", "outstanding", "unknown"
    ]
    contributing_record_hashes: tuple[SHA256Hash, ...]
    projection_hashes: tuple[SHA256Hash, ...]
    association_result_hashes: tuple[SHA256Hash, ...]

    @field_validator(
        "contributing_record_hashes", "projection_hashes", "association_result_hashes"
    )
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes)


class EconomicEffectProjectionV1(FrozenModel):
    """Audit composition of one safe occurred-effect projection."""

    source_record_hash: SHA256Hash
    effective_status: Literal["before_window", "effective", "upcoming", "indeterminate"]
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"]
    consideration_status: Literal["components", "explicit_none", "unknown"]
    owed_components: tuple[EconomicComponentV1, ...]
    component_gaps: tuple[EconomicComponentGapV1, ...]
    safe_fact_projection_hash: SHA256Hash


class EconomicCoverageResolutionV1(FrozenModel):
    """Replay-derived coverage authority for one selected fact family."""

    family: Literal["terms", "effect", "settlement"]
    source_id: NonBlankStr
    selected_coverage_hashes: tuple[SHA256Hash, ...]
    target_manifest_hash: SHA256Hash
    status: Literal["complete", "partial", "unknown"]
    occurrence_identity_supported: bool
    reasons: tuple[NonBlankStr, ...]

    @field_validator("selected_coverage_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes)

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.occurrence_identity_supported and self.status != "complete":
            raise ValueError("occurrence identity support requires complete coverage")
        if self.status == "complete" and self.reasons:
            raise ValueError("complete coverage result cannot carry gap reasons")
        if self.status != "complete" and not self.reasons:
            raise ValueError("incomplete coverage result requires reasons")
        return self


class ActionResidualResolutionV1(FrozenModel):
    """Folded residual state for one causally selected corporate action."""

    action_scope: EconomicSourceKeyV1
    selected_action_record_hash: SHA256Hash
    status: Literal["closed", "outstanding", "unknown", "conflicting"]
    covered_settlement_hashes: tuple[SHA256Hash, ...]
    closure_record_hashes: tuple[SHA256Hash, ...]
    reasons: tuple[NonBlankStr, ...]

    @field_validator("covered_settlement_hashes", "closure_record_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes)

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_status_reasons(self) -> Self:
        if self.status == "closed" and self.reasons:
            raise ValueError("closed residual result cannot carry gap reasons")
        if self.status != "closed" and not self.reasons:
            raise ValueError("non-closed residual result requires reasons")
        return self


class EconomicOutcomeResolutionV1(FrozenModel):
    """Complete replayable audit result for bounded economic facts."""

    schema_version: Literal["1"]
    query: MarketSelectionQueryV1
    query_hash: SHA256Hash
    selection_proof_hash: SHA256Hash
    source_selection_policy_hash: SHA256Hash
    input_context_hash: SHA256Hash
    composition_algorithm: Literal["drift-m1c-economic-composition-v1"]
    composition_algorithm_spec_hash: SHA256Hash
    composition_implementation_hash: SHA256Hash
    selected_terms_hashes: tuple[SHA256Hash, ...]
    upcoming_terms_hashes: tuple[SHA256Hash, ...]
    effect_projections: tuple[EconomicEffectProjectionV1, ...]
    cancelled_action_hashes: tuple[SHA256Hash, ...]
    unknown_effect_hashes: tuple[SHA256Hash, ...]
    delivery_groups: tuple[EconomicDeliveryGroupV1, ...]
    uncomposed_settlement_hashes: tuple[SHA256Hash, ...]
    associations: tuple[EconomicAssociationResolutionV1, ...]
    coverage_results: tuple[EconomicCoverageResolutionV1, ...]
    residual_resolutions: tuple[ActionResidualResolutionV1, ...]
    safe_projection_hashes: tuple[SHA256Hash, ...]
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"]
    evidence_completeness: Literal["known", "partial", "unknown"]
    support_status: Literal["supported", "unsupported", "indeterminate"]
    reasons: tuple[NonBlankStr, ...]

    @field_validator(
        "selected_terms_hashes",
        "upcoming_terms_hashes",
        "cancelled_action_hashes",
        "unknown_effect_hashes",
        "uncomposed_settlement_hashes",
        "safe_projection_hashes",
    )
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes)

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("economic outcome query hash mismatch")
        if self.source_selection_policy_hash != self.query.source_selection_policy_hash:
            raise ValueError("economic outcome source policy binding mismatch")
        if self.input_context_hash != self.query.input_context_hash:
            raise ValueError("economic outcome input context binding mismatch")
        return self
