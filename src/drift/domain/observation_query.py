"""Immutable M1d observation query, policy, proof, and reference contracts."""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.assertions import AssertionSelectionResultV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationCoverageVersionV1,
    ObservationInputRecordV1,
)
from drift.domain.securities import ListingVenue
from drift.domain.semantic_attestation import m1d_evidence_attestation_hash
from drift.domain.temporal import (
    AvailabilityChannelV1,
    CutoffEligibility,
    CutoffEligibilityResultV1,
)
from drift.serialization.canonical import content_hash

type M1dSelectionPurpose = Literal[
    "observation",
    "observation_coverage",
    "scheduled_session",
    "realized_session",
    "session_coverage",
    "contract",
]


class ObservationSourceBindingV1(FrozenModel):
    """One exact source/role/listing/date authority binding."""

    schema_version: Literal["1"] = "1"
    dataset_role: Literal[
        "source_observation",
        "observation_coverage",
        "scheduled_session",
        "realized_session",
        "session_coverage",
    ]
    source_id: NonBlankStr
    contract_hash: SHA256Hash | None
    venue: ListingVenue
    listing_id: UUID7
    start_date: date
    end_date: date
    manifest_hashes: tuple[SHA256Hash, ...]
    methodology_hashes: tuple[SHA256Hash, ...]

    @field_validator("manifest_hashes", "methodology_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if not hashes or len(set(hashes)) != len(hashes):
            raise ValueError("source binding hashes must be nonempty and unique")
        return tuple(sorted(hashes))

    @model_validator(mode="after")
    def validate_date_scope(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("source binding date interval cannot be reversed")
        observation_role = self.dataset_role in {
            "source_observation",
            "observation_coverage",
        }
        if observation_role != (self.contract_hash is not None):
            raise ValueError(
                "only observation bindings carry an observation contract hash"
            )
        return self


class ObservationSourceSelectionPolicyV1(FrozenModel):
    """Closed query-independent authority policy for exact observation sources."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    version: NonBlankStr
    bindings: tuple[ObservationSourceBindingV1, ...]

    @field_validator("bindings")
    @classmethod
    def canonicalize_bindings(
        cls, bindings: tuple[ObservationSourceBindingV1, ...]
    ) -> tuple[ObservationSourceBindingV1, ...]:
        if not bindings or len(set(bindings)) != len(bindings):
            raise ValueError("source policy bindings must be nonempty and unique")
        ordered = tuple(sorted(bindings, key=_binding_order_key))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if _binding_authority_key(left) != _binding_authority_key(right):
                    continue
                if right.start_date > left.end_date:
                    break
                same_inventory = (
                    left.manifest_hashes == right.manifest_hashes
                    and left.methodology_hashes == right.methodology_hashes
                )
                if not same_inventory:
                    raise ValueError(
                        "overlapping source authority must name one inventory"
                    )
        return ordered


class _ObservationQueryBaseV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    listing_id: UUID7
    security_id: UUID7
    venue: ListingVenue
    session_date: date
    source_id: NonBlankStr
    contract_hash: SHA256Hash
    source_selection_policy_hash: SHA256Hash
    profile_hash: SHA256Hash
    requested_channel: AvailabilityChannelV1
    availability_policy_id: NonBlankStr
    availability_policy_hash: SHA256Hash
    input_context_hash: SHA256Hash


class ObservationDecisionQueryV1(_ObservationQueryBaseV1):
    """Decision-time source observation query with independent K and E clocks."""

    kind: Literal["decision"]
    decision_time: UTCDateTime
    knowledge_cutoff: UTCDateTime
    effective_cutoff: UTCDateTime

    @model_validator(mode="after")
    def validate_temporal_window(self) -> Self:
        if self.knowledge_cutoff > self.decision_time:
            raise ValueError("knowledge cutoff cannot follow decision time")
        if self.effective_cutoff > self.decision_time:
            raise ValueError("effective cutoff cannot follow decision time")
        return self


class ObservationOutcomeQueryV1(_ObservationQueryBaseV1):
    """Ex-post observation query with a finite evidence vintage."""

    kind: Literal["outcome"]
    economic_horizon: UTCDateTime
    evidence_vintage_cutoff: UTCDateTime


type ObservationQueryV1 = Annotated[
    ObservationDecisionQueryV1 | ObservationOutcomeQueryV1,
    Field(discriminator="kind"),
]


class ObservationSubjectV1(FrozenModel):
    """The exact observation subject bound into a selection proof."""

    schema_version: Literal["1"] = "1"
    listing_id: UUID7
    security_id: UUID7
    venue: ListingVenue
    session_date: date
    source_id: NonBlankStr
    contract_hash: SHA256Hash


class SessionSubjectV1(FrozenModel):
    """The source/MIC/date/scope subject of one session selection."""

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    mic: NonBlankStr
    session_date: date
    session_scope: Literal["regular"]


class M1dSelectionProofV1(FrozenModel):
    """Complete audit proof for one M1d source-selection request."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    purpose: M1dSelectionPurpose
    context_hash: SHA256Hash
    subject: ObservationSubjectV1 | SessionSubjectV1
    considered_version_hashes: tuple[SHA256Hash, ...]
    selected_hashes: tuple[SHA256Hash, ...]
    assertion_selections: tuple[AssertionSelectionResultV1, ...]
    availability_decisions: tuple[CutoffEligibilityResultV1, ...]
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash
    classification: Literal["selected", "absent", "indeterminate"]

    @field_validator("considered_version_hashes", "selected_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes):
            raise ValueError("selection proof hashes must be unique")
        return tuple(sorted(hashes))

    @field_validator("assertion_selections", "availability_decisions")
    @classmethod
    def canonicalize_decisions[T](cls, values: tuple[T, ...]) -> tuple[T, ...]:
        hashes = tuple(content_hash(item) for item in values)
        if len(set(hashes)) != len(hashes):
            raise ValueError("selection proof decisions must be unique")
        return tuple(item for _, item in sorted(zip(hashes, values, strict=True)))

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("selection proof query hash must match query")
        if self.context_hash != self.query.input_context_hash:
            raise ValueError("selection proof context hash must match query")
        if self.purpose in {"observation", "observation_coverage", "contract"}:
            expected_subject = ObservationSubjectV1(
                listing_id=self.query.listing_id,
                security_id=self.query.security_id,
                venue=self.query.venue,
                session_date=self.query.session_date,
                source_id=self.query.source_id,
                contract_hash=self.query.contract_hash,
            )
            if self.subject != expected_subject:
                raise ValueError("selection proof subject must match query")
        elif not isinstance(self.subject, SessionSubjectV1):
            raise ValueError("session selection proof requires a session subject")
        elif (
            self.subject.mic != self.query.venue.value
            or self.subject.session_date != self.query.session_date
            or self.subject.session_scope != "regular"
        ):
            raise ValueError("session selection proof subject must match query context")
        if not set(self.selected_hashes).issubset(self.considered_version_hashes):
            raise ValueError("selected hashes must be considered")
        if self.classification == "selected":
            if not self.selected_hashes:
                raise ValueError("selected classification requires selected hashes")
            if not self.availability_decisions:
                raise ValueError(
                    "selected classification requires an availability decision witness"
                )
            if self.purpose != "contract" and not self.assertion_selections:
                raise ValueError(
                    "selected source record requires an assertion selection witness"
                )
            if self.purpose != "contract" and not any(
                selection.classification is CutoffEligibility.ELIGIBLE
                and selection.selected_record_hash in self.selected_hashes
                and selection.cutoff == observation_cutoff(self.query)
                and selection.requested_channel == self.query.requested_channel
                and selection.policy_id == self.query.availability_policy_id
                and selection.policy_hash == self.query.availability_policy_hash
                for selection in self.assertion_selections
            ):
                raise ValueError(
                    "selected source record requires an applicable assertion witness"
                )
            if not any(
                decision.classification is CutoffEligibility.ELIGIBLE
                and decision.cutoff == observation_cutoff(self.query)
                and decision.requested_channel == self.query.requested_channel
                and decision.policy_id == self.query.availability_policy_id
                and decision.policy_hash == self.query.availability_policy_hash
                for decision in self.availability_decisions
            ):
                raise ValueError(
                    "selected classification requires an applicable "
                    "availability witness"
                )
        elif self.selected_hashes:
            raise ValueError(
                "absent or indeterminate classification cannot select hashes"
            )
        return self


class M1dSelectedRecordsV1(FrozenModel):
    """Query-, purpose-, and role-bound selected source records."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    purpose: M1dSelectionPurpose
    dataset_role: Literal["source_observation", "observation_coverage"]
    records: tuple[ObservationInputRecordV1, ...]
    proof: M1dSelectionProofV1

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.query != self.proof.query or self.purpose != self.proof.purpose:
            raise ValueError(
                "selected records must match their proof query and purpose"
            )
        actual_hashes = tuple(sorted(content_hash(record) for record in self.records))
        if actual_hashes != self.proof.selected_hashes:
            raise ValueError("selected record hashes must match proof")
        current_contracts: dict[
            str,
            tuple[
                Literal["source_observation", "observation_coverage"],
                type[DailySourceObservationVersionV1 | ObservationCoverageVersionV1],
            ],
        ] = {
            "observation": (
                "source_observation",
                DailySourceObservationVersionV1,
            ),
            "observation_coverage": (
                "observation_coverage",
                ObservationCoverageVersionV1,
            ),
        }
        current = current_contracts.get(self.purpose)
        if current is None:
            raise ValueError("selected-record purpose is not owned by Task 1")
        expected_role, expected_type = current
        if self.dataset_role != expected_role:
            raise ValueError("selected record role must match purpose")
        if any(not isinstance(record, expected_type) for record in self.records):
            raise ValueError("selected record type must match dataset role")
        for record in self.records:
            if isinstance(record, DailySourceObservationVersionV1):
                if (
                    record.source_key.source_id != self.query.source_id
                    or record.contract_hash != self.query.contract_hash
                    or record.listing_id != self.query.listing_id
                    or record.security_id != self.query.security_id
                    or record.venue is not self.query.venue
                    or record.session_date != self.query.session_date
                ):
                    raise ValueError("selected daily record subject must match query")
            elif (
                record.source_id != self.query.source_id
                or record.contract_hash != self.query.contract_hash
                or record.listing_id != self.query.listing_id
                or record.security_id != self.query.security_id
                or record.venue is not self.query.venue
                or not (record.start_date <= self.query.session_date <= record.end_date)
            ):
                raise ValueError("selected coverage record subject must match query")
        return self


def observation_cutoff(query: ObservationQueryV1) -> datetime:
    """Return K for decision queries and V for outcome queries."""
    if isinstance(query, ObservationDecisionQueryV1):
        return query.knowledge_cutoff
    return query.evidence_vintage_cutoff


def observation_horizon(query: ObservationQueryV1) -> datetime:
    """Return E for decision queries and H for outcome queries."""
    if isinstance(query, ObservationDecisionQueryV1):
        return query.effective_cutoff
    return query.economic_horizon


def drift_source_inventory_hash() -> str:
    """Identify the whole installed Drift Python source inventory.

    This is build and repository provenance: it answers which repository state
    ran, so every Python file in the package moves it. It is never an M1d
    evidence identity (issue #63).
    """
    return economic_implementation_hash()


def m1d_implementation_hash() -> str:
    """Identify the code that derives M1d evidence.

    This is the ``m1d-evidence-v1`` semantic attestation, not the whole source
    inventory, so an edit outside its declared closure cannot move it.
    """
    return m1d_evidence_attestation_hash()


def _binding_authority_key(binding: ObservationSourceBindingV1) -> tuple[object, ...]:
    return (
        binding.dataset_role,
        binding.source_id,
        binding.contract_hash or "",
        binding.venue.value,
        str(binding.listing_id),
    )


def _binding_order_key(binding: ObservationSourceBindingV1) -> tuple[object, ...]:
    return (
        *_binding_authority_key(binding),
        binding.start_date,
        binding.end_date,
        binding.manifest_hashes,
        binding.methodology_hashes,
    )
