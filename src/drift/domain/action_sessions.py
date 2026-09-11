"""Immutable M1c action-to-M1d session mapping contracts."""

from datetime import date
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.assertions import BoundaryShape
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.economic_common import ActionKind, PositiveRatioV1
from drift.domain.economic_queries import MarketSelectionQueryV1
from drift.domain.observation_query import (
    ObservationQueryV1,
    m1d_implementation_hash,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.temporal import SourcePrecision
from drift.serialization.canonical import content_hash

type ActionSessionMappingMode = Literal[
    "explicit_first_basis_date", "exact_trading_basis_transition"
]
type EconomicDateRole = Literal[
    "announcement",
    "approval",
    "ex",
    "record",
    "payable",
    "due_bill_start",
    "due_bill_end",
    "due_bill_redemption",
    "legal_effect",
    "trading_basis",
]

_ACTION_SESSION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "verified-m1c-action-to-session-v1",
    "economic_selection": "exact-m1c-resolution-and-association-replay",
    "date_authority": ("date-bearing-source-role-methodology-bound-trading-basis-only"),
    "session_authority": "actual-open-bounds-plus-complete-selected-calendar",
    "roll_rule": "none-without-explicit-after-close-method-and-dense-coverage",
    "endpoint_truth": "equality-preserved-separately-from-basis-designation",
    "exact_instant_attribution": (
        "selected-schedule-local-day-bounds-and-realized-utc-interval"
    ),
    "effect_time_only": "complete-occurred-split-with-absent-terms-lineage",
    "split_predicate": "fixed-single-same-security-directional-ratio",
    "occurrence_equality": "single-owner-source-native-economic-occurrence",
    "output_authority": "mapping-only-not-factor-authorization",
}


def action_session_algorithm_hash() -> str:
    """Return the semantic identity of the v1 action/session mapper."""
    return content_hash(_ACTION_SESSION_ALGORITHM_V1)


def _canonical_hashes(values: tuple[SHA256Hash, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


class ActionDateRoleMethodologyV1(FrozenModel):
    """Source method proving one field's exact trading-basis interpretation."""

    schema_version: Literal["1"] = "1"
    effect_source_id: NonBlankStr
    date_source_id: NonBlankStr
    security_id: UUID7
    listing_id: UUID7
    mic: NonBlankStr
    field_origin: Literal["selected_terms_date", "selected_effect_time"]
    date_role: EconomicDateRole | None
    mapping_mode: ActionSessionMappingMode
    meaning: Literal["first_post_basis_session_date", "exact_trading_basis_transition"]
    before_open_rule: Literal["current_proven_open_session", "indeterminate"]
    after_close_rule: Literal[
        "next_proven_open_with_complete_intervening_coverage", "indeterminate"
    ]
    open_endpoint_designation: Literal["none", "post_basis"]
    close_endpoint_designation: Literal["none", "pre_basis"]

    @field_validator("mic")
    @classmethod
    def require_mic_shape(cls, value: str) -> str:
        if len(value) != 4 or value != value.upper():
            raise ValueError("methodology MIC must be exact uppercase MIC")
        return value

    @model_validator(mode="after")
    def validate_method_shape(self) -> Self:
        expected = (
            "first_post_basis_session_date"
            if self.mapping_mode == "explicit_first_basis_date"
            else "exact_trading_basis_transition"
        )
        if self.meaning != expected:
            raise ValueError("methodology meaning must match mapping mode")
        if self.field_origin == "selected_terms_date" and self.date_role is None:
            raise ValueError("terms-date methodology requires an exact date role")
        if self.field_origin == "selected_effect_time" and self.date_role is not None:
            raise ValueError("effect-time methodology cannot claim a terms date role")
        return self


class ActionSessionPolicyV1(FrozenModel):
    """Versioned mapper policy bound to one retained source methodology."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    mapping_mode: ActionSessionMappingMode
    date_role_methodology_hash: SHA256Hash
    endpoint_policy: Literal["require_explicit_designation"]
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_known_algorithm(self) -> Self:
        if self.semantic_algorithm_hash != action_session_algorithm_hash():
            raise ValueError("action session semantic algorithm hash mismatch")
        if self.implementation_hash != m1d_implementation_hash():
            raise ValueError("action session implementation hash mismatch")
        return self


class ActionSessionQueryV1(FrozenModel):
    """Exact M1c occurrence and candidate-session application request."""

    schema_version: Literal["1"] = "1"
    outer_query: ObservationQueryV1
    source_id: NonBlankStr
    native_occurrence_id: NonBlankStr
    selected_terms_hash: SHA256Hash | None
    selected_effect_hash: SHA256Hash
    listing_id: UUID7
    security_id: UUID7
    mic: NonBlankStr
    candidate_start_date: date
    candidate_end_date: date
    action_session_policy_hash: SHA256Hash
    economic_source_policy_hash: SHA256Hash

    @field_validator("mic")
    @classmethod
    def require_mic_shape(cls, value: str) -> str:
        if len(value) != 4 or value != value.upper():
            raise ValueError("action query MIC must be exact uppercase MIC")
        return value

    @model_validator(mode="after")
    def validate_query_shape(self) -> Self:
        if (
            self.listing_id != self.outer_query.listing_id
            or self.security_id != self.outer_query.security_id
            or self.mic != self.outer_query.venue.value
        ):
            raise ValueError("action query subject must match outer query")
        if self.candidate_start_date > self.candidate_end_date:
            raise ValueError("candidate session date range cannot be reversed")
        return self


class ActionBasisBoundaryV1(FrozenModel):
    """Locator-free exact source boundary used by the mapper."""

    shape: BoundaryShape
    lower_bound: UTCDateTime | None
    upper_bound: UTCDateTime | None
    source_precision: SourcePrecision
    source_time_label: NonBlankStr
    source_timezone: str | None

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.shape is BoundaryShape.UNKNOWN:
            if self.lower_bound is not None or self.upper_bound is not None:
                raise ValueError("unknown action boundary cannot carry bounds")
        elif self.lower_bound is None or self.upper_bound is None:
            raise ValueError("known action boundary requires both bounds")
        elif self.shape is BoundaryShape.EXACT and self.lower_bound != self.upper_bound:
            raise ValueError("exact action boundary requires equal bounds")
        elif (
            self.shape is BoundaryShape.BOUNDED and self.lower_bound >= self.upper_bound
        ):
            raise ValueError("bounded action boundary requires ordered bounds")
        return self


class ActionShareComponentProjectionV1(FrozenModel):
    """Applicable same-security occurred share component without source locators."""

    source_component_hash: SHA256Hash
    component_id: NonBlankStr
    recipient_security_id: UUID7
    predecessor_security_id: UUID7
    ratio: PositiveRatioV1
    ratio_meaning: Literal["resulting_per_predecessor"]
    share_basis: Literal["predecessor_pre_action"]
    applicability: Literal["ordinary_passive_holder"]


class ActionDateProjectionV1(FrozenModel):
    """Minimal replayed M1c action boundary used for session mapping."""

    schema_version: Literal["1"] = "1"
    query_hash: SHA256Hash
    effect_source_id: NonBlankStr
    date_source_id: NonBlankStr
    native_occurrence_id: NonBlankStr
    action_kind: Literal[ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT]
    listing_id: UUID7
    security_id: UUID7
    mic: NonBlankStr
    selected_terms_hash: SHA256Hash | None
    selected_effect_hash: SHA256Hash
    same_occurrence_effect_hashes: tuple[SHA256Hash, ...]
    association_result_hashes: tuple[SHA256Hash, ...]
    date_role: EconomicDateRole | None
    basis_boundary: ActionBasisBoundaryV1
    share_component: ActionShareComponentProjectionV1
    date_role_methodology_hash: SHA256Hash
    economic_query_hash: SHA256Hash
    economic_outcome_hash: SHA256Hash
    economic_selection_proof_hash: SHA256Hash
    economic_source_policy_hash: SHA256Hash

    @field_validator("same_occurrence_effect_hashes", "association_result_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_hashes(values, "action projection hashes")


class ActionSessionTransitionClaimV1(FrozenModel):
    """Exact relationship between the basis evidence and selected session."""

    mapping_mode: ActionSessionMappingMode
    relationship: Literal[
        "explicit_first_basis_date",
        "strictly_before_open",
        "strictly_after_close",
        "exactly_at_open",
        "exactly_at_close",
    ]
    basis_boundary: ActionBasisBoundaryV1
    source_session_key: SessionKeyV1
    source_actual_open: UTCDateTime
    source_actual_close: UTCDateTime
    session_key: SessionKeyV1
    actual_open: UTCDateTime
    actual_close: UTCDateTime
    applied_rule: Literal[
        "exact_date_is_actual_open_session",
        "before_open_current_session",
        "after_close_next_open_complete_coverage",
        "designated_open_post_basis",
        "designated_close_pre_basis_next_open_complete_coverage",
    ]

    @model_validator(mode="after")
    def validate_session_interval(self) -> Self:
        if self.source_actual_close <= self.source_actual_open:
            raise ValueError("action transition source close must follow source open")
        if self.actual_close <= self.actual_open:
            raise ValueError("action transition actual close must follow actual open")
        if self.session_key.mic == "":
            raise ValueError("action transition session MIC cannot be empty")
        return self


class FirstPostActionSessionResultV1(FrozenModel):
    """Replayable mapping result that grants no split-factor authority by itself."""

    schema_version: Literal["1"] = "1"
    query: ActionSessionQueryV1
    query_hash: SHA256Hash
    classification: Literal["mapped", "not_applicable", "indeterminate"]
    first_post_session: SessionKeyV1 | None
    transition_claim: ActionSessionTransitionClaimV1 | None
    economic_query: MarketSelectionQueryV1
    economic_query_hash: SHA256Hash
    economic_outcome_hash: SHA256Hash | None
    economic_selection_proof_hash: SHA256Hash | None
    source_selection_policy_hash: SHA256Hash
    selected_terms_hash: SHA256Hash | None
    selected_effect_hash: SHA256Hash
    same_occurrence_effect_hashes: tuple[SHA256Hash, ...]
    selected_session_proof_hashes: tuple[SHA256Hash, ...]
    selected_session_record_hashes: tuple[SHA256Hash, ...]
    date_projection_hash: SHA256Hash | None
    association_result_hash: SHA256Hash | None
    reasons: tuple[NonBlankStr, ...]
    dependency_hashes: tuple[SHA256Hash, ...]
    policy_hash: SHA256Hash
    context_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @field_validator(
        "same_occurrence_effect_hashes",
        "selected_session_proof_hashes",
        "selected_session_record_hashes",
        "dependency_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_hashes(values, "action mapping hashes")

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("action mapping result requires reasons")
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("action mapping query hash mismatch")
        if self.economic_query_hash != content_hash(self.economic_query):
            raise ValueError("action mapping economic query hash mismatch")
        if self.economic_query.kind != self.query.outer_query.kind:
            raise ValueError("action mapping nested role mismatch")
        if self.source_selection_policy_hash != self.query.economic_source_policy_hash:
            raise ValueError("action mapping economic source policy mismatch")
        if self.selected_effect_hash != self.query.selected_effect_hash:
            raise ValueError("action mapping selected effect mismatch")
        if self.selected_terms_hash != self.query.selected_terms_hash:
            raise ValueError("action mapping selected terms mismatch")
        if self.policy_hash != self.query.action_session_policy_hash:
            raise ValueError("action mapping policy hash mismatch")
        if self.context_hash != self.query.outer_query.input_context_hash:
            raise ValueError("action mapping context hash mismatch")
        if self.semantic_algorithm_hash != action_session_algorithm_hash():
            raise ValueError("action mapping algorithm hash mismatch")
        if self.implementation_hash != m1d_implementation_hash():
            raise ValueError("action mapping implementation hash mismatch")
        mapped = self.classification == "mapped"
        if mapped != (
            self.first_post_session is not None
            and self.transition_claim is not None
            and self.date_projection_hash is not None
            and self.economic_outcome_hash is not None
            and self.economic_selection_proof_hash is not None
        ):
            raise ValueError("mapped action result requires exact mapping dependencies")
        if not mapped and (
            self.first_post_session is not None or self.transition_claim is not None
        ):
            raise ValueError("non-mapped action result cannot carry a session")
        return self
