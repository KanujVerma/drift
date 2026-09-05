"""Immutable M1c market-query, proof, reference, and safe-projection contracts."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.assertions import AssertionSelectionResultV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.economic_common import (
    ActionKind,
    EconomicComponentGapV1,
    EconomicComponentV1,
)
from drift.domain.temporal import AvailabilityChannelV1
from drift.serialization.canonical import content_hash

type EconomicProjectionFamily = Literal["terms", "effect", "settlement"]


class _MarketQueryBaseV1(FrozenModel):
    """The shared immutable identity and policy binding for economic selection."""

    schema_version: Literal["1"]
    security_id: UUID7
    action_kinds: tuple[ActionKind, ...]
    history_start: UTCDateTime
    requested_channel: AvailabilityChannelV1
    availability_policy_id: NonBlankStr
    availability_policy_hash: SHA256Hash
    source_selection_policy_hash: SHA256Hash
    input_context_hash: SHA256Hash

    @field_validator("action_kinds")
    @classmethod
    def require_canonical_action_kinds(
        cls, action_kinds: tuple[ActionKind, ...]
    ) -> tuple[ActionKind, ...]:
        if not action_kinds or action_kinds != tuple(
            sorted(set(action_kinds), key=lambda item: item.value)
        ):
            msg = "action kinds must be nonempty, sorted and unique"
            raise ValueError(msg)
        return action_kinds


class MarketDecisionQueryV1(_MarketQueryBaseV1):
    """A decision-time request bounded by knowledge and economic effect clocks."""

    kind: Literal["decision"]
    purpose: Literal["economic_facts"]
    decision_time: UTCDateTime
    knowledge_cutoff: UTCDateTime
    effective_cutoff: UTCDateTime

    @model_validator(mode="after")
    def validate_temporal_window(self) -> Self:
        if self.knowledge_cutoff > self.decision_time:
            msg = "knowledge cutoff cannot follow decision time"
            raise ValueError(msg)
        if self.effective_cutoff > self.decision_time:
            msg = "effective cutoff cannot follow decision time"
            raise ValueError(msg)
        if self.history_start > self.effective_cutoff:
            msg = "history start cannot follow effective cutoff"
            raise ValueError(msg)
        return self


class MarketOutcomeQueryV1(_MarketQueryBaseV1):
    """An ex-post request with independent economic horizon and evidence vintage."""

    kind: Literal["outcome"]
    purpose: Literal["economic_outcome"]
    economic_horizon: UTCDateTime
    evidence_vintage_cutoff: UTCDateTime

    @model_validator(mode="after")
    def validate_temporal_window(self) -> Self:
        if self.history_start > self.economic_horizon:
            msg = "history start cannot follow economic horizon"
            raise ValueError(msg)
        return self


type MarketSelectionQueryV1 = Annotated[
    MarketDecisionQueryV1 | MarketOutcomeQueryV1,
    Field(discriminator="kind"),
]


def market_cutoff(query: MarketSelectionQueryV1) -> datetime:
    """Return the source-availability cutoff for a decision or outcome query."""
    if isinstance(query, MarketDecisionQueryV1):
        return query.knowledge_cutoff
    return query.evidence_vintage_cutoff


def market_horizon(query: MarketSelectionQueryV1) -> datetime:
    """Return the requested economic horizon for a decision or outcome query."""
    if isinstance(query, MarketDecisionQueryV1):
        return query.effective_cutoff
    return query.economic_horizon


class RetainedEconomicIdentityV1(FrozenModel):
    """A cutoff-bound retained security or listing identity proof."""

    schema_version: Literal["1"]
    identity_kind: Literal["security", "listing"]
    identity_id: UUID7
    cutoff: UTCDateTime
    channel: AvailabilityChannelV1
    availability_policy_hash: SHA256Hash
    assignment_manifest_hash: SHA256Hash
    assignment_decision_hash: SHA256Hash
    assignment_bundle_hash: SHA256Hash
    selected_assignment_hashes: tuple[SHA256Hash, ...]
    selection_evidence_hashes: tuple[SHA256Hash, ...]
    status: Literal["known", "unknown", "conflicting"]
    reasons: tuple[NonBlankStr, ...]

    @field_validator("selected_assignment_hashes", "selection_evidence_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "retained identity hashes")

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_status_reasons(self) -> Self:
        if self.status in {"unknown", "conflicting"} and not self.reasons:
            msg = "unknown or conflicting retained identity requires reasons"
            raise ValueError(msg)
        return self


class EconomicApplicabilityV1(FrozenModel):
    """A derived source-time relationship, not an authorization to expose a row."""

    source_record_hash: SHA256Hash
    family: EconomicProjectionFamily
    status: Literal["before_window", "in_window", "upcoming", "indeterminate"]
    reasons: tuple[NonBlankStr, ...]

    @field_validator("reasons")
    @classmethod
    def require_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if not reasons:
            msg = "economic applicability requires reasons"
            raise ValueError(msg)
        return _canonical_reasons(reasons)


class MarketDatasetSelectionV1(FrozenModel):
    """Audit-side chain selections for one validated economic source dataset."""

    manifest_hash: SHA256Hash
    decision_hash: SHA256Hash
    bundle_hash: SHA256Hash
    role: NonBlankStr
    source_id: NonBlankStr
    considered_record_hashes: tuple[SHA256Hash, ...]
    chain_selections: tuple[AssertionSelectionResultV1, ...]
    selected_record_hashes: tuple[SHA256Hash, ...]

    @field_validator("considered_record_hashes", "selected_record_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "dataset selection hashes")

    @model_validator(mode="after")
    def validate_selected_records(self) -> Self:
        if not set(self.selected_record_hashes).issubset(self.considered_record_hashes):
            msg = "dataset selected record hashes must be considered"
            raise ValueError(msg)
        return self


class MarketSelectionProofV1(FrozenModel):
    """Complete audit proof for one selection request without a self-hash field."""

    schema_version: Literal["1"]
    query: MarketSelectionQueryV1
    query_hash: SHA256Hash
    input_context_hash: SHA256Hash
    source_selection_policy_hash: SHA256Hash
    selection_algorithm: Literal["drift-m1c-economic-selection-v1"]
    selection_algorithm_spec_hash: SHA256Hash
    selection_implementation_hash: SHA256Hash
    dataset_proofs: tuple[MarketDatasetSelectionV1, ...]
    identity_proofs: tuple[RetainedEconomicIdentityV1, ...]
    revision_selected_record_hashes: tuple[SHA256Hash, ...]
    applicability: tuple[EconomicApplicabilityV1, ...]
    raw_materializable_record_hashes: tuple[SHA256Hash, ...]
    projection_hashes: tuple[SHA256Hash, ...]
    unresolved_chain_hashes: tuple[SHA256Hash, ...]

    @field_validator(
        "revision_selected_record_hashes",
        "raw_materializable_record_hashes",
        "projection_hashes",
        "unresolved_chain_hashes",
    )
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "selection proof hashes")

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            msg = "selection proof query hash must match query"
            raise ValueError(msg)
        if self.input_context_hash != self.query.input_context_hash:
            msg = "selection proof input context hash must match query"
            raise ValueError(msg)
        if self.source_selection_policy_hash != self.query.source_selection_policy_hash:
            msg = "selection proof source selection policy hash must match query"
            raise ValueError(msg)
        if not set(self.raw_materializable_record_hashes).issubset(
            self.revision_selected_record_hashes
        ):
            msg = "raw materializable record hashes must be revision-selected"
            raise ValueError(msg)
        return self


class MarketDecisionReferenceV1(FrozenModel):
    """A decision-safe capability exposing only materializable economic hashes."""

    schema_version: Literal["1"]
    kind: Literal["decision_reference"]
    query_hash: SHA256Hash
    selection_proof_hash: SHA256Hash
    selected_record_hashes: tuple[SHA256Hash, ...]
    projection_hashes: tuple[SHA256Hash, ...]

    @field_validator("selected_record_hashes", "projection_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "decision reference hashes")


class MarketOutcomeReferenceV1(FrozenModel):
    """An outcome capability exposing only materializable economic hashes."""

    schema_version: Literal["1"]
    kind: Literal["outcome_reference"]
    query_hash: SHA256Hash
    selection_proof_hash: SHA256Hash
    selected_record_hashes: tuple[SHA256Hash, ...]
    projection_hashes: tuple[SHA256Hash, ...]

    @field_validator("selected_record_hashes", "projection_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "outcome reference hashes")


type MarketSelectionReferenceV1 = Annotated[
    MarketDecisionReferenceV1 | MarketOutcomeReferenceV1,
    Field(discriminator="kind"),
]


class EconomicSafeFactProjectionV1(FrozenModel):
    """A derived, minimal economic fact safe to materialize for one query."""

    schema_version: Literal["1"]
    query_hash: SHA256Hash
    source_record_hash: SHA256Hash
    family: EconomicProjectionFamily
    security_id: UUID7
    action_kind: ActionKind
    applicability: EconomicApplicabilityV1
    component_role: Literal["terms", "owed", "delivered"]
    known_components: tuple[EconomicComponentV1, ...]
    withheld_components: tuple[EconomicComponentGapV1, ...]
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"]
    fact_status: Literal[
        "terms", "occurred", "cancelled_action", "unknown", "delivered"
    ]
    consideration_status: Literal["components", "explicit_none", "unknown"]
    residual_status: Literal[
        "closed_for_occurrence", "closed_for_action", "outstanding", "unknown"
    ]
    optional_context_reasons: tuple[NonBlankStr, ...]
    dependency_proof_hashes: tuple[SHA256Hash, ...]
    projection_algorithm_spec_hash: SHA256Hash
    projection_implementation_hash: SHA256Hash

    @field_validator("known_components")
    @classmethod
    def canonicalize_known_components(
        cls, components: tuple[EconomicComponentV1, ...]
    ) -> tuple[EconomicComponentV1, ...]:
        component_ids = tuple(component.component_id for component in components)
        if len(set(component_ids)) != len(component_ids):
            msg = "known economic component IDs must be unique"
            raise ValueError(msg)
        return tuple(sorted(components, key=lambda component: component.component_id))

    @field_validator("withheld_components")
    @classmethod
    def canonicalize_withheld_components(
        cls, components: tuple[EconomicComponentGapV1, ...]
    ) -> tuple[EconomicComponentGapV1, ...]:
        component_ids = tuple(component.component_id for component in components)
        if len(set(component_ids)) != len(component_ids):
            msg = "withheld economic component IDs must be unique"
            raise ValueError(msg)
        return tuple(sorted(components, key=lambda component: component.component_id))

    @field_validator("dependency_proof_hashes")
    @classmethod
    def canonicalize_dependency_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        return _canonical_hashes(hashes, "projection dependency hashes")

    @field_validator("optional_context_reasons")
    @classmethod
    def canonicalize_optional_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        return _canonical_reasons(reasons)

    @model_validator(mode="after")
    def validate_projection_semantics(self) -> Self:
        if self.applicability.source_record_hash != self.source_record_hash:
            msg = "projection applicability must bind its source record"
            raise ValueError(msg)
        if self.applicability.family != self.family:
            msg = "projection applicability family must match projection family"
            raise ValueError(msg)
        known_ids = {component.component_id for component in self.known_components}
        withheld_ids = {
            component.component_id for component in self.withheld_components
        }
        if known_ids & withheld_ids:
            msg = "known and withheld economic component IDs cannot overlap"
            raise ValueError(msg)
        matrix = {
            ("terms", "terms"): {
                "component_role": "terms",
                "claim_statuses": {"unknown"},
                "consideration_statuses": {"components", "unknown"},
                "residual_statuses": {"unknown"},
            },
            ("effect", "occurred"): {
                "component_role": "owed",
                "claim_statuses": {
                    "continuing",
                    "converted",
                    "extinguished",
                    "unknown",
                },
                "consideration_statuses": {"components", "explicit_none", "unknown"},
                "residual_statuses": {
                    "closed_for_occurrence",
                    "closed_for_action",
                    "outstanding",
                    "unknown",
                },
            },
            ("effect", "cancelled_action"): {
                "component_role": "owed",
                "claim_statuses": {"unknown"},
                "consideration_statuses": {"unknown"},
                "residual_statuses": {"unknown"},
            },
            ("effect", "unknown"): {
                "component_role": "owed",
                "claim_statuses": {"unknown"},
                "consideration_statuses": {"unknown"},
                "residual_statuses": {"unknown"},
            },
            ("settlement", "delivered"): {
                "component_role": "delivered",
                "claim_statuses": {"unknown"},
                "consideration_statuses": {"components"},
                "residual_statuses": {
                    "closed_for_occurrence",
                    "closed_for_action",
                    "outstanding",
                    "unknown",
                },
            },
        }.get((self.family, self.fact_status))
        if matrix is None:
            msg = "projection fact status is incompatible with its family"
            raise ValueError(msg)
        if self.component_role != matrix["component_role"]:
            msg = "projection component role is incompatible with its family"
            raise ValueError(msg)
        if self.claim_status not in matrix["claim_statuses"]:
            msg = "projection claim status is incompatible with its fact status"
            raise ValueError(msg)
        if self.consideration_status not in matrix["consideration_statuses"]:
            msg = "projection consideration status is incompatible with its fact status"
            raise ValueError(msg)
        if self.residual_status not in matrix["residual_statuses"]:
            msg = "projection residual status is incompatible with its fact status"
            raise ValueError(msg)
        has_components = bool(self.known_components or self.withheld_components)
        if self.consideration_status == "components" and not has_components:
            msg = "component consideration requires a known or withheld component"
            raise ValueError(msg)
        if self.consideration_status in {"explicit_none", "unknown"} and has_components:
            msg = "non-component consideration cannot expose components"
            raise ValueError(msg)
        return self


def _canonical_hashes(
    hashes: tuple[SHA256Hash, ...], label: str
) -> tuple[SHA256Hash, ...]:
    if len(set(hashes)) != len(hashes):
        msg = f"{label} must be unique"
        raise ValueError(msg)
    return tuple(sorted(hashes))


def _canonical_reasons(reasons: tuple[NonBlankStr, ...]) -> tuple[NonBlankStr, ...]:
    return tuple(sorted(set(reasons)))
