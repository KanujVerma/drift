"""Genuine M1c and session fixtures for action-to-session mapping tests."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID

from economic_test_support import (
    HASH_A,
    EconomicHarness,
    cash_component,
    economic_dataset,
    effect_record,
    history_assignments,
    identity_assignment,
    identity_input,
    parse_utc,
    rebind_record_evidence,
    revise_record,
    support_bytes,
    terms_record,
)
from economic_test_support import (
    coverage_record as economic_coverage_record,
)
from economic_test_support import (
    public_availability as economic_public_availability,
)
from economic_test_support import (
    source_policy as economic_source_policy,
)
from economic_test_support import (
    uid as economic_uid,
)
from pydantic import BaseModel
from session_test_support import (
    AUTHORITY_HASH,
    generation_case,
    realized_record,
    schedule_record,
    session_dataset,
    session_supporting_artifacts,
)
from session_test_support import (
    boundary_at as session_boundary_at,
)
from session_test_support import (
    coverage_record as session_coverage_record,
)
from session_test_support import (
    public_channel as session_public_channel,
)
from session_test_support import (
    uid as session_uid,
)

from drift.datasets.hashing import assertion_version_payload, manifest_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.action_sessions import (
    ActionDateRoleMethodologyV1,
    ActionSessionPolicyV1,
    ActionSessionQueryV1,
    FirstPostActionSessionResultV1,
    action_session_algorithm_hash,
)
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.economic_common import (
    ActionKind,
    EconomicAssociationV1,
    EconomicDateFactV1,
    EconomicOccurrenceV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
)
from drift.domain.economic_coverage import DatasetBindingV1, EconomicSourceOwnerV1
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    OccurredEffectV1,
    ResidualClaimV1,
    TermsPayloadV1,
)
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
    m1d_implementation_hash,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import ListingVenue
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SessionInputRecordV1,
    SessionKeyV1,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    SourcePrecision,
)
from drift.markets.action_sessions import map_action_to_session
from drift.markets.economic_validation import EconomicResolutionContext
from drift.markets.observation_validation import (
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
)
from drift.serialization.canonical import canonical_json, content_hash

MappingMode = Literal["explicit_first_basis_date", "exact_trading_basis_transition"]
DateRole = Literal[
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

ACTION_LISTING_ID = economic_uid(24)
FOREIGN_LISTING_ID = economic_uid(25)


@dataclass(frozen=True)
class ActionSessionCase:
    """One exact combined context plus its public mapping query."""

    context: M1dResolutionContext
    query: ActionSessionQueryV1
    terms: tuple[CorporateActionTermsVersionV1, ...]
    effects: tuple[EconomicEffectVersionV1, ...]

    def map(self) -> FirstPostActionSessionResultV1:
        return map_action_to_session(self.query, self.context)


def _basis_boundary(
    basis: str,
    evidence: CorporateActionTermsVersionV1 | EconomicEffectVersionV1,
) -> TemporalBoundaryClaimV1:
    reference = evidence.revision.source_artifact
    if "T" in basis:
        instant = parse_utc(basis)
        return TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.EXACT,
            lower_bound=instant,
            upper_bound=instant,
            source_precision=SourcePrecision.SECOND,
            source_time_label=basis,
            source_timezone=None,
            evidence_reference=reference,
        )
    local_date = date.fromisoformat(basis)
    lower = datetime.combine(local_date, time(5), tzinfo=UTC)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=lower,
        upper_bound=lower + timedelta(days=1),
        source_precision=SourcePrecision.DATE,
        source_time_label=basis,
        source_timezone="America/New_York",
        evidence_reference=reference,
    )


def _split_terms(
    suffix: int,
    basis: str,
    role: DateRole,
    *,
    ratio: tuple[str, str] = ("2", "1"),
    known_at: str = "2026-11-20T00:00:00Z",
    action_kind: ActionKind = ActionKind.FORWARD_SPLIT,
    source_id: str = "terms-source",
    listing_id: UUID | None = ACTION_LISTING_ID,
    payload_kind: Literal["fixed", "incomplete"] = "fixed",
    extra_component: bool = False,
) -> CorporateActionTermsVersionV1:
    base = terms_record(
        suffix,
        action_kind=action_kind,
        known_at=known_at,
        scheduled_at=(basis if "T" in basis else f"{basis}T12:00:00Z"),
    )
    component = ShareComponentV1(
        kind="shares",
        component_id="same-security-split",
        recipient=EconomicRecipientV1(kind="security", security_id=economic_uid(21)),
        ratio=PositiveRatioV1(numerator=ratio[0], denominator=ratio[1]),
        ratio_meaning="resulting_per_predecessor",
        unit_basis=EconomicShareBasisV1(
            security_id=economic_uid(21),
            share_basis="predecessor_pre_action",
        ),
        fraction_treatment=FractionTreatmentV1(kind="unknown"),
        applicability="ordinary_passive_holder",
        conditions=(),
    )
    components = (component, cash_component()) if extra_component else (component,)
    values = {name: getattr(base, name) for name in type(base).model_fields}
    values["source_key"] = base.source_key.model_copy(update={"source_id": source_id})
    values["listing_id"] = listing_id
    values["payload"] = TermsPayloadV1(
        kind=payload_kind,
        action_kind=action_kind,
        components=components,
        dates=(
            EconomicDateFactV1(
                role=role,
                boundary=_basis_boundary(basis, base),
                rule_reference=base.revision.source_artifact,
            ),
        ),
        conditions=(),
        reason=None if payload_kind == "fixed" else "split terms remain incomplete",
    )
    values["scheduled_effect_time"] = _basis_boundary(basis, base)
    return rebind_record_evidence(type(base), values)


def _split_effect(
    suffix: int,
    terms: CorporateActionTermsVersionV1,
    basis: str,
    *,
    effect_kind: Literal["occurred", "cancelled_action", "unknown"] = "occurred",
    occurrence_id: str = "split-occurrence-1",
    ratio: tuple[str, str] = ("2", "1"),
    known_at: str | None = None,
    unresolved_terms: bool = False,
    action_kind: ActionKind = ActionKind.FORWARD_SPLIT,
    source_id: str = "effect-source",
    listing_id: UUID = ACTION_LISTING_ID,
    extra_component: bool = False,
) -> EconomicEffectVersionV1:
    effective_at = basis if "T" in basis else f"{basis}T12:00:00Z"
    base = effect_record(
        suffix,
        kind=effect_kind,
        effective_at=effective_at,
        known_at=effective_at if known_at is None else known_at,
    )
    if effect_kind != "occurred":
        values = {name: getattr(base, name) for name in type(base).model_fields}
        assert base.payload is not None
        values["source_key"] = base.source_key.model_copy(
            update={"source_id": source_id}
        )
        values["listing_id"] = listing_id
        values["payload"] = base.payload.model_copy(update={"action_kind": action_kind})
        return rebind_record_evidence(type(base), values)
    component = ShareComponentV1(
        kind="shares",
        component_id="same-security-split",
        recipient=EconomicRecipientV1(kind="security", security_id=economic_uid(21)),
        ratio=PositiveRatioV1(numerator=ratio[0], denominator=ratio[1]),
        ratio_meaning="resulting_per_predecessor",
        unit_basis=EconomicShareBasisV1(
            security_id=economic_uid(21),
            share_basis="predecessor_pre_action",
        ),
        fraction_treatment=FractionTreatmentV1(kind="unknown"),
        applicability="ordinary_passive_holder",
        conditions=(),
    )
    association = (
        EconomicAssociationV1(kind="unknown", reason="terms association omitted")
        if unresolved_terms
        else EconomicAssociationV1(kind="identified", target=terms.source_key)
    )
    components = (component, cash_component()) if extra_component else (component,)
    values = {name: getattr(base, name) for name in type(base).model_fields}
    values["source_key"] = base.source_key.model_copy(update={"source_id": source_id})
    values["listing_id"] = listing_id
    values["occurrence"] = EconomicOccurrenceV1(
        kind="identified",
        native_occurrence_id=occurrence_id,
        evidence_reference=base.revision.source_artifact,
    )
    values["terms_association"] = association
    values["payload"] = OccurredEffectV1(
        kind="occurred",
        action_kind=action_kind,
        claim_status="continuing",
        consideration_status="components",
        owed_components=components,
        residual=ResidualClaimV1(
            kind="outstanding",
            scope_action=association,
            reason="settlement is independent of split unit occurrence",
        ),
        evidence_reference=base.revision.source_artifact,
    )
    return rebind_record_evidence(type(base), values)


def _identified_neutral_effect(
    effect: EconomicEffectVersionV1, occurrence_id: str, source_id: str
) -> EconomicEffectVersionV1:
    values = {name: getattr(effect, name) for name in type(effect).model_fields}
    values["source_key"] = effect.source_key.model_copy(update={"source_id": source_id})
    values["occurrence"] = EconomicOccurrenceV1(
        kind="identified",
        native_occurrence_id=occurrence_id,
        evidence_reference=effect.revision.source_artifact,
    )
    values["listing_id"] = ACTION_LISTING_ID
    return rebind_record_evidence(type(effect), values)


def _realized_session(
    local_date: date, *, opened: bool, suffix: int
) -> RealizedSessionVersionV1:
    base = realized_record(suffix=suffix)
    key = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=local_date)
    actual_open = (
        datetime.combine(local_date, time(9, 30), tzinfo=UTC) + timedelta(hours=5)
        if opened
        else None
    )
    actual_close = (
        datetime.combine(
            local_date,
            time(13 if local_date == date(2026, 11, 27) else 16),
            tzinfo=UTC,
        )
        + timedelta(hours=5)
        if opened
        else None
    )
    available_at = (
        actual_close + timedelta(minutes=5)
        if actual_close is not None
        else datetime.combine(local_date, time(22), tzinfo=UTC)
    )
    evidence = AvailabilityEvidenceV1(
        channel=session_public_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=available_at,
        upper_bound=available_at,
        precision=SourcePrecision.SECOND,
        source_time_label=available_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=base.revision.source_artifact,
    )
    revision = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=session_uid(suffix),
        record_version_id=session_uid(suffix + 1),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(evidence,),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=base.revision.source_artifact,
        payload_hash="0" * 64,
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": revision,
        "source_id": "calendar-source",
        "session_key": key,
        "outcome": "opened" if opened else "did_not_open",
        "actual_open": actual_open,
        "actual_close": actual_close,
        "reported_as_scheduled": "asserted",
        "late_open": "denied" if opened else "unknown",
        "early_close": "denied" if opened else "unknown",
        "interruption_intervals": (),
        "interruption_coverage": "complete",
        "source_evidence_hashes": (AUTHORITY_HASH,),
        "methodology_hashes": (AUTHORITY_HASH,),
        "compared_schedule_hash": None,
    }
    provisional = RealizedSessionVersionV1.model_construct(**values)  # type: ignore[arg-type]
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return RealizedSessionVersionV1.model_validate(values)


def _with_contradicted_schedule_offsets(
    record: ScheduledSessionVersionV1,
) -> ScheduledSessionVersionV1:
    """Change only claimed offsets while retaining their original authority bytes."""
    revision = record.revision.model_copy(update={"payload_hash": "0" * 64})
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values.update(
        {
            "revision": revision,
            "historical_boundary_offsets": tuple(
                item.model_copy(
                    update={"utc_offset_seconds": item.utc_offset_seconds - 3_600}
                )
                if item.utc_offset_seconds is not None
                else item
                for item in record.historical_boundary_offsets
            ),
        }
    )
    provisional = ScheduledSessionVersionV1.model_construct(**values)
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return ScheduledSessionVersionV1.model_validate(values)


def _session_inputs(
    *,
    coverage_status: Literal["expected_complete", "partial", "unknown"] = (
        "expected_complete"
    ),
    emergency_date: date | None = None,
    corrected_schedule_state: Literal["closed", "unknown"] | None = None,
    include_prior_open: bool = False,
    contradict_schedule_offsets: bool = False,
) -> tuple[
    tuple[M1dDatasetInput[SessionInputRecordV1], ...],
    dict[str, VerifiedArtifactBytes],
    dict[str, AvailabilityEvidenceV1],
    tuple[ObservationSourceBindingV1, ...],
]:
    methodology_hash, support, retained = session_supporting_artifacts()
    prior_states: tuple[
        tuple[date, Literal["regular", "early_close", "closed", "unknown"]], ...
    ] = ((date(2026, 11, 25), "regular"),) if include_prior_open else ()
    states: tuple[
        tuple[date, Literal["regular", "early_close", "closed", "unknown"]], ...
    ] = (
        *prior_states,
        (date(2026, 11, 26), "closed"),
        (date(2026, 11, 27), "early_close"),
        (date(2026, 11, 28), "closed"),
        (date(2026, 11, 29), "closed"),
        (date(2026, 11, 30), "regular"),
    )
    schedules = tuple(
        schedule_record(
            local_date,
            state,
            methodology_hash,
            support,
            retained,
            suffix=5000 + index * 10,
        )
        for index, (local_date, state) in enumerate(states)
    )
    if contradict_schedule_offsets:
        schedules = tuple(
            _with_contradicted_schedule_offsets(item) for item in schedules
        )
    if corrected_schedule_state is not None:
        schedules = (
            *schedules,
            schedule_record(
                date(2026, 11, 27),
                corrected_schedule_state,
                methodology_hash,
                support,
                retained,
                suffix=5090,
                predecessor=schedules[1],
            ),
        )
        schedules = tuple(
            sorted(
                schedules,
                key=lambda record: (
                    str(record.revision.logical_record_id),
                    str(record.revision.record_version_id),
                ),
            )
        )
    scheduled = session_dataset("scheduled_session", schedules, support)
    coverage_record = session_coverage_record(
        scheduled,
        methodology_hash,
        suffix=5100,
        start_date=date(2026, 11, 25) if include_prior_open else date(2026, 11, 26),
        end_date=date(2026, 11, 30),
        status=coverage_status,
    )
    coverage = session_dataset("session_coverage", (coverage_record,), support)
    realized_records = (
        *(
            (_realized_session(date(2026, 11, 25), opened=True, suffix=5180),)
            if include_prior_open
            else ()
        ),
        _realized_session(
            date(2026, 11, 27),
            opened=emergency_date != date(2026, 11, 27),
            suffix=5200,
        ),
        _realized_session(date(2026, 11, 30), opened=True, suffix=5220),
    )
    if emergency_date == date(2026, 11, 27):
        emergency = realized_records[0]
        assert emergency.revision.availability[0].upper_bound is not None
        companion = {
            "schema_version": "1",
            "kind": "realized_session_completion",
            "source_id": emergency.source_id,
            "session_key": emergency.session_key,
            "outcome": emergency.outcome,
            "logical_record_id": emergency.revision.logical_record_id,
            "record_version_id": emergency.revision.record_version_id,
            "source_artifact_hash": emergency.revision.source_artifact.content_hash,
            "record_availability_evidence_hash": content_hash(
                emergency.revision.availability[0]
            ),
            "completion_time": session_boundary_at(
                emergency.revision.availability[0].upper_bound, 5210
            ),
        }
        companion_bytes = canonical_json(companion)
        companion_hash = sha256(companion_bytes).hexdigest()
        support[companion_hash] = VerifiedArtifactBytes(
            data=companion_bytes,
            byte_size=len(companion_bytes),
            content_hash=companion_hash,
        )
        values = {
            name: getattr(emergency, name) for name in type(emergency).model_fields
        }
        values["source_evidence_hashes"] = tuple(
            sorted((*emergency.source_evidence_hashes, companion_hash))
        )
        provisional = type(emergency).model_construct(**values)
        values["revision"] = emergency.revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        emergency = type(emergency).model_validate(values)
        realized_records = (emergency, realized_records[1])
    realized = session_dataset("realized_session", realized_records, support)
    bindings = (
        ObservationSourceBindingV1(
            dataset_role="scheduled_session",
            source_id="calendar-source",
            contract_hash=None,
            venue=ListingVenue.XNYS,
            listing_id=ACTION_LISTING_ID,
            start_date=(
                date(2026, 11, 25) if include_prior_open else date(2026, 11, 26)
            ),
            end_date=date(2026, 11, 30),
            manifest_hashes=(manifest_hash(scheduled.manifest),),
            methodology_hashes=(methodology_hash,),
        ),
        ObservationSourceBindingV1(
            dataset_role="session_coverage",
            source_id="calendar-source",
            contract_hash=None,
            venue=ListingVenue.XNYS,
            listing_id=ACTION_LISTING_ID,
            start_date=(
                date(2026, 11, 25) if include_prior_open else date(2026, 11, 26)
            ),
            end_date=date(2026, 11, 30),
            manifest_hashes=(manifest_hash(coverage.manifest),),
            methodology_hashes=(methodology_hash,),
        ),
        ObservationSourceBindingV1(
            dataset_role="realized_session",
            source_id="calendar-source",
            contract_hash=None,
            venue=ListingVenue.XNYS,
            listing_id=ACTION_LISTING_ID,
            start_date=(
                date(2026, 11, 25) if include_prior_open else date(2026, 11, 26)
            ),
            end_date=date(2026, 11, 30),
            manifest_hashes=(manifest_hash(realized.manifest),),
            methodology_hashes=(AUTHORITY_HASH,),
        ),
    )
    return (scheduled, coverage, realized), support, retained, bindings


def _artifact_references(value: object) -> tuple[ArtifactReference, ...]:
    references: list[ArtifactReference] = []

    def visit(item: object) -> None:
        if isinstance(item, ArtifactReference):
            references.append(item)
        elif isinstance(item, BaseModel):
            for name in type(item).model_fields:
                visit(getattr(item, name))
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, tuple | list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(references)


def _validated_action_economic_case(
    records: tuple[EconomicRecordV1, ...],
    *,
    through: str,
    coverage_action_kinds: tuple[ActionKind, ...],
    settlement_coverage: Literal["complete", "partial", "unknown"],
    settlement_source_id: str = "settlement-source",
    coverage_evidence: EconomicRecordV1 | None = None,
    history_start: str = "2020-01-01T00:00:00Z",
) -> EconomicHarness:
    """Build a closed M1c fixture locally without changing protected M1c support."""
    channel = session_public_channel()
    rechanneled: list[EconomicRecordV1] = []
    for record in records:
        values = {name: getattr(record, name) for name in type(record).model_fields}
        values["revision"] = record.revision.model_copy(
            update={
                "availability": tuple(
                    item.model_copy(update={"channel": channel})
                    for item in record.revision.availability
                ),
                "payload_hash": HASH_A,
            }
        )
        rechanneled.append(rebind_record_evidence(type(record), values))
    owned_records = tuple(rechanneled)
    evidence_record = owned_records[0] if owned_records else coverage_evidence
    if evidence_record is None:
        raise ValueError("empty economic fixture requires retained coverage evidence")
    families: tuple[Literal["terms", "effect", "settlement"], ...] = (
        "terms",
        "effect",
        "settlement",
    )
    roles = ("economic_terms", "economic_effect", "economic_settlement")
    family_records: tuple[tuple[EconomicRecordV1, ...], ...] = (
        tuple(
            record
            for record in owned_records
            if isinstance(record, CorporateActionTermsVersionV1)
        ),
        tuple(
            record
            for record in owned_records
            if isinstance(record, EconomicEffectVersionV1)
        ),
        (),
    )
    family_sources: tuple[str, ...] = tuple(
        next(iter(sources))
        if sources
        else settlement_source_id
        if family == "settlement"
        else f"{family}-source"
        for family, records_for_family in zip(families, family_records, strict=True)
        for sources in ({record.source_key.source_id for record in records_for_family},)
    )
    if any(
        len({record.source_key.source_id for record in records_for_family}) > 1
        for records_for_family in family_records
    ):
        raise ValueError("Task 5 fixture requires one source owner per fact family")
    fact_inputs = tuple(
        economic_dataset(
            role,
            records_for_family,
            source_id,
            declared_channels=(channel,),
        )
        for role, records_for_family, source_id in zip(
            roles, family_records, family_sources, strict=True
        )
    )
    through_value = parse_utc(through)
    snapshot = max(
        (
            through_value + timedelta(days=1),
            *(
                evidence.upper_bound
                for record in owned_records
                for evidence in record.revision.availability
                if evidence.upper_bound is not None
            ),
        )
    )
    snapshot_text = snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")
    coverage_end = (through_value + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    coverage_records = tuple(
        economic_coverage_record(
            7000 + index,
            family,
            manifest_hash(dataset.manifest),
            dataset.decision.validated_artifact_hashes,
            dataset.decision.validated_record_hashes,
            completeness=(
                settlement_coverage if family == "settlement" else "complete"
            ),
            action_kinds=coverage_action_kinds,
            snapshot_at=snapshot_text,
            coverage_end=coverage_end,
            source_id=source_id,
            availability=(
                economic_public_availability(
                    snapshot_text, evidence_record.revision.source_artifact
                ).model_copy(update={"channel": channel}),
            ),
        )
        for index, (family, dataset, source_id) in enumerate(
            zip(families, fact_inputs, family_sources, strict=True)
        )
    )
    coverage_inputs = tuple(
        economic_dataset(
            "economic_coverage",
            (record,),
            source_id,
            declared_channels=(channel,),
        )
        for record, source_id in zip(coverage_records, family_sources, strict=True)
    )
    listing_ids = {
        record.listing_id for record in owned_records if record.listing_id is not None
    }
    listing_assignments = tuple(
        identity_assignment(
            7100 + index * 10,
            24 if listing_id == ACTION_LISTING_ID else 25,
            identity_kind="listing",
        ).model_copy(
            update={
                "identity": identity_assignment(
                    7100 + index * 10,
                    24 if listing_id == ACTION_LISTING_ID else 25,
                    identity_kind="listing",
                ).identity.model_copy(update={"venue": ListingVenue.XNYS})
            }
        )
        for index, listing_id in enumerate(sorted(listing_ids, key=str))
    )
    assignments = (*history_assignments(), *listing_assignments)
    rechanneled_assignments = []
    for assignment in assignments:
        revision = assignment.revision.model_copy(
            update={
                "availability": tuple(
                    item.model_copy(update={"channel": channel})
                    for item in assignment.revision.availability
                ),
                "payload_hash": HASH_A,
            }
        )
        provisional = assignment.model_copy(update={"revision": revision})
        rechanneled_assignments.append(
            provisional.model_copy(
                update={
                    "revision": revision.model_copy(
                        update={
                            "payload_hash": content_hash(
                                assertion_version_payload(provisional)
                            )
                        }
                    )
                }
            )
        )
    identity = identity_input(tuple(rechanneled_assignments), (channel,))
    datasets = (*fact_inputs, *coverage_inputs)
    references_by_hash: dict[str, ArtifactReference] = {}
    for dataset in datasets:
        for reference in _artifact_references(
            (
                dataset.records,
                dataset.manifest.source,
                dataset.manifest.acquisition,
                dataset.manifest.license,
            )
        ):
            references_by_hash.setdefault(reference.content_hash, reference)
    supporting_artifacts = tuple(
        sorted(
            (support_bytes(reference) for reference in references_by_hash.values()),
            key=lambda artifact: artifact.content_hash,
        )
    )
    context = EconomicResolutionContext(
        datasets=datasets,
        identity=identity,
        availability_policy=AvailabilityPolicyV1(
            policy_id="public-v1", permitted_rule_hashes=()
        ),
        retained_evidence={},
        supporting_artifacts=supporting_artifacts,
    )
    bindings = tuple(
        DatasetBindingV1(
            manifest_hash=manifest_hash(dataset.manifest),
            decision_hash=content_hash(dataset.decision),
            bundle_hash=content_hash(dataset.bundle),
            role=dataset.manifest.dataset_role.name,
            source_id=dataset.manifest.source.source_id,
        )
        for dataset in datasets
    )
    owners = tuple(
        EconomicSourceOwnerV1(
            family=family,
            source_id=source_id,
            fact_manifest_hash=manifest_hash(dataset.manifest),
            coverage_manifest_hash=manifest_hash(coverage.manifest),
        )
        for family, source_id, dataset, coverage in zip(
            families, family_sources, fact_inputs, coverage_inputs, strict=True
        )
    )
    policy = economic_source_policy(
        economic_uid(21),
        bindings,
        owners,
        parse_utc(history_start),
        through_value,
    )
    return EconomicHarness(context=context, source_policy=policy)


def action_session_case(
    basis: str,
    mode: MappingMode,
    *,
    date_role: DateRole | None = None,
    effect_kind: Literal["occurred", "cancelled_action", "unknown"] = "occurred",
    method_mic: str = "XNYS",
    selected_terms: Literal["primary", "substitute", "arbitrary", "absent"] = "primary",
    unresolved_terms: bool = False,
    duplicate: Literal[
        "none", "equal", "conflict_outside_window", "effect_time_conflict"
    ] = "none",
    coverage_action_kinds: tuple[ActionKind, ...] = tuple(ActionKind),
    settlement_coverage: Literal["complete", "partial", "unknown"] = "complete",
    session_coverage: Literal["expected_complete", "partial", "unknown"] = (
        "expected_complete"
    ),
    emergency_date: date | None = None,
    correction_basis: str | None = None,
    corrected_schedule_state: Literal["closed", "unknown"] | None = None,
    effect_basis: str | None = None,
    outer_kind: Literal["decision", "outcome"] = "outcome",
    terms_action_kind: ActionKind = ActionKind.FORWARD_SPLIT,
    action_kind: ActionKind = ActionKind.FORWARD_SPLIT,
    ratio: tuple[str, str] = ("2", "1"),
    terms_payload_kind: Literal["fixed", "incomplete"] = "fixed",
    extra_component: bool = False,
    terms_source_id: str = "terms-source",
    effect_source_id: str = "effect-source",
    terms_listing_id: UUID | None = ACTION_LISTING_ID,
    method_source_id: str | None = None,
    field_origin: Literal["selected_terms_date", "selected_effect_time"] = (
        "selected_terms_date"
    ),
    open_endpoint_designation: Literal["none", "post_basis"] = "none",
    close_endpoint_designation: Literal["none", "pre_basis"] = "none",
    omit_effect: bool = False,
    omit_terms: bool = False,
    include_cash_only_effect: bool = False,
    additional_splits: tuple[tuple[str, tuple[str, str], ActionKind], ...] = (),
    economic_through: str | None = None,
    occurrence_group_case: Literal[
        "base",
        "cancelled_conflict",
        "cash_conflict",
        "cancelled_neutral",
        "cash_neutral",
    ] = "base",
    neutral_suffix: int = 6110,
    include_prior_open: bool = False,
    contradict_schedule_offsets: bool = False,
    economic_history_start: str = "2020-01-01T00:00:00Z",
) -> ActionSessionCase:
    """Build one exact, validated action/session composition fixture."""
    if omit_terms and not omit_effect:
        raise ValueError("omitting terms requires omitting the dependent effect")
    role: DateRole = (
        ("ex" if mode == "explicit_first_basis_date" else "trading_basis")
        if date_role is None
        else date_role
    )
    primary = _split_terms(
        6000,
        basis,
        role,
        action_kind=terms_action_kind,
        ratio=ratio,
        source_id=terms_source_id,
        listing_id=terms_listing_id,
        payload_kind=terms_payload_kind,
        extra_component=extra_component,
    )
    primary_effect = _split_effect(
        6010,
        primary,
        basis if effect_basis is None else effect_basis,
        effect_kind=effect_kind,
        unresolved_terms=unresolved_terms,
        action_kind=action_kind,
        ratio=ratio,
        source_id=effect_source_id,
        extra_component=extra_component,
    )
    terms: tuple[CorporateActionTermsVersionV1, ...] = () if omit_terms else (primary,)
    effects: tuple[EconomicEffectVersionV1, ...] = (
        () if omit_effect else (primary_effect,)
    )
    if occurrence_group_case in {"cancelled_conflict", "cancelled_neutral"}:
        cancelled_one = _identified_neutral_effect(
            _split_effect(
                neutral_suffix,
                primary,
                basis,
                effect_kind="cancelled_action",
                source_id=effect_source_id,
            ),
            "split-occurrence-1",
            effect_source_id,
        )
        if occurrence_group_case == "cancelled_conflict":
            effects = (*effects, cancelled_one)
        else:
            cancelled_two = _identified_neutral_effect(
                _split_effect(
                    neutral_suffix + 1,
                    primary,
                    basis,
                    effect_kind="cancelled_action",
                    source_id=effect_source_id,
                ),
                "split-occurrence-1",
                effect_source_id,
            )
            effects = (cancelled_one, cancelled_two)
    elif occurrence_group_case in {"cash_conflict", "cash_neutral"}:
        cash_one = _identified_neutral_effect(
            effect_record(
                neutral_suffix,
                effective_at=basis,
                known_at=basis,
            ),
            "split-occurrence-1",
            effect_source_id,
        )
        if occurrence_group_case == "cash_conflict":
            effects = (*effects, cash_one)
        else:
            cash_two = _identified_neutral_effect(
                effect_record(
                    neutral_suffix + 1,
                    effective_at=basis,
                    known_at=basis,
                ),
                "split-occurrence-1",
                effect_source_id,
            )
            effects = (cash_one, cash_two)
    if include_cash_only_effect:
        cash_effect = effect_record(
            6070,
            effective_at="2026-11-28T00:00:00Z",
            known_at="2026-11-28T00:00:00Z",
        )
        cash_values = {
            name: getattr(cash_effect, name) for name in type(cash_effect).model_fields
        }
        cash_values["source_key"] = cash_effect.source_key.model_copy(
            update={"source_id": effect_source_id}
        )
        effects = (
            *effects,
            rebind_record_evidence(type(cash_effect), cash_values),
        )
    for index, (additional_basis, additional_ratio, additional_kind) in enumerate(
        additional_splits
    ):
        additional_terms = _split_terms(
            6080 + index * 20,
            additional_basis,
            role,
            ratio=additional_ratio,
            action_kind=additional_kind,
            source_id=terms_source_id,
            listing_id=terms_listing_id,
        )
        additional_effect = _split_effect(
            6090 + index * 20,
            additional_terms,
            additional_basis,
            occurrence_id=f"split-occurrence-{index + 2}",
            action_kind=additional_kind,
            ratio=additional_ratio,
            source_id=effect_source_id,
        )
        terms = (*terms, additional_terms)
        effects = (*effects, additional_effect)
    if correction_basis is not None:
        assert primary.payload is not None
        corrected_payload = primary.payload.model_copy(
            update={
                "dates": (
                    EconomicDateFactV1(
                        role=role,
                        boundary=_basis_boundary(correction_basis, primary),
                        rule_reference=primary.revision.source_artifact,
                    ),
                )
            }
        )
        correction = revise_record(
            primary,
            6060,
            "2026-11-29T00:00:00Z",
            {
                "payload": corrected_payload,
                "scheduled_effect_time": _basis_boundary(correction_basis, primary),
            },
        )
        terms = (*terms, correction)
    substitute = _split_terms(
        6020,
        "2026-11-30",
        "ex",
        source_id=terms_source_id,
        listing_id=terms_listing_id,
    )
    if selected_terms == "substitute":
        terms = (*terms, substitute)
    if duplicate == "equal":
        effects = (
            *effects,
            _split_effect(
                6030,
                primary,
                basis,
                occurrence_id="split-occurrence-1",
                action_kind=action_kind,
                ratio=ratio,
                source_id=effect_source_id,
                extra_component=extra_component,
            ),
        )
    elif duplicate == "effect_time_conflict":
        effects = (
            *effects,
            _split_effect(
                6035,
                primary,
                "2026-12-02T14:00:00Z",
                occurrence_id="split-occurrence-1",
                action_kind=action_kind,
                ratio=ratio,
                source_id=effect_source_id,
                extra_component=extra_component,
            ),
        )
    elif duplicate == "conflict_outside_window":
        outside_terms = _split_terms(
            6040,
            "2026-12-02T14:00:00Z",
            "trading_basis",
            source_id=terms_source_id,
            listing_id=terms_listing_id,
        )
        outside_effect = _split_effect(
            6050,
            outside_terms,
            "2026-12-02T14:00:00Z",
            occurrence_id="split-occurrence-1",
            action_kind=action_kind,
            ratio=ratio,
            source_id=effect_source_id,
        )
        terms = (*terms, outside_terms)
        effects = (*effects, outside_effect)
    economic = _validated_action_economic_case(
        (*terms, *effects),
        through=economic_through
        or (
            "2026-12-03T00:00:00Z"
            if duplicate in {"conflict_outside_window", "effect_time_conflict"}
            else "2026-12-01T00:00:00Z"
        ),
        coverage_action_kinds=coverage_action_kinds,
        settlement_coverage=settlement_coverage,
        coverage_evidence=primary,
        history_start=economic_history_start,
    )
    actual_terms = tuple(
        record
        for dataset in economic.context.datasets
        for record in dataset.records
        if isinstance(record, CorporateActionTermsVersionV1)
    )
    actual_effects = tuple(
        record
        for dataset in economic.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicEffectVersionV1)
    )
    if actual_terms:
        primary = max(
            (
                record
                for record in actual_terms
                if record.source_key == primary.source_key
            ),
            key=lambda record: record.revision.source_sequence,
        )
    if occurrence_group_case in {"cancelled_neutral", "cash_neutral"}:
        primary_effect = actual_effects[0]
    elif not omit_effect:
        primary_effect = next(
            record
            for record in actual_effects
            if record.source_key == primary_effect.source_key
        )
    if selected_terms == "substitute":
        substitute = next(
            record
            for record in actual_terms
            if record.source_key == substitute.source_key
        )
    terms = actual_terms
    effects = actual_effects
    session_datasets, support, retained, bindings = _session_inputs(
        coverage_status=session_coverage,
        emergency_date=emergency_date,
        corrected_schedule_state=corrected_schedule_state,
        include_prior_open=include_prior_open,
        contradict_schedule_offsets=contradict_schedule_offsets,
    )
    generation_context, _generation_query, generation_policy = generation_case(
        local_date=date(2026, 11, 27)
    )
    support.update(generation_context.supporting_artifacts)
    generation_policy_bytes = canonical_json(generation_policy)
    generation_policy_hash = sha256(generation_policy_bytes).hexdigest()
    support[generation_policy_hash] = VerifiedArtifactBytes(
        data=generation_policy_bytes,
        byte_size=len(generation_policy_bytes),
        content_hash=generation_policy_hash,
    )
    source_policy = ObservationSourceSelectionPolicyV1(
        policy_id="action-session-source-authority",
        version="1",
        bindings=bindings,
    )
    source_policy_bytes = canonical_json(source_policy)
    source_policy_hash = sha256(source_policy_bytes).hexdigest()
    support[source_policy_hash] = VerifiedArtifactBytes(
        data=source_policy_bytes,
        byte_size=len(source_policy_bytes),
        content_hash=source_policy_hash,
    )
    methodology = ActionDateRoleMethodologyV1(
        effect_source_id=effect_source_id,
        date_source_id=(
            method_source_id
            if method_source_id is not None
            else terms_source_id
            if field_origin == "selected_terms_date"
            else effect_source_id
        ),
        security_id=economic_uid(21),
        listing_id=ACTION_LISTING_ID,
        mic=method_mic,
        field_origin=field_origin,
        date_role=role if field_origin == "selected_terms_date" else None,
        mapping_mode=mode,
        meaning=(
            "first_post_basis_session_date"
            if mode == "explicit_first_basis_date"
            else "exact_trading_basis_transition"
        ),
        before_open_rule="current_proven_open_session",
        after_close_rule="next_proven_open_with_complete_intervening_coverage",
        open_endpoint_designation=open_endpoint_designation,
        close_endpoint_designation=close_endpoint_designation,
    )
    methodology_bytes = canonical_json(methodology)
    methodology_hash = sha256(methodology_bytes).hexdigest()
    support[methodology_hash] = VerifiedArtifactBytes(
        data=methodology_bytes,
        byte_size=len(methodology_bytes),
        content_hash=methodology_hash,
    )
    policy = ActionSessionPolicyV1(
        policy_id="synthetic-action-session-policy",
        policy_version="1",
        mapping_mode=mode,
        date_role_methodology_hash=methodology_hash,
        endpoint_policy="require_explicit_designation",
        semantic_algorithm_hash=action_session_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )
    policy_bytes = canonical_json(policy)
    policy_hash = sha256(policy_bytes).hexdigest()
    support[policy_hash] = VerifiedArtifactBytes(
        data=policy_bytes,
        byte_size=len(policy_bytes),
        content_hash=policy_hash,
    )
    availability_policy = AvailabilityPolicyV1(
        policy_id="public-exact", permitted_rule_hashes=()
    )
    availability_policy_hash = content_hash(availability_policy)
    context = M1dResolutionContext(
        observation_datasets=(),
        session_datasets=session_datasets,
        availability_policies={availability_policy_hash: availability_policy},
        retained_evidence=retained,
        supporting_artifacts=support,
        economic_context=economic.context,
        economic_source_policy=economic.source_policy,
        schedule_generation_policy_hash=generation_policy_hash,
    )
    horizon = economic.source_policy.through
    context_hash = m1d_context_hash(context)
    outer = (
        ObservationDecisionQueryV1(
            kind="decision",
            decision_time=horizon + timedelta(days=1),
            knowledge_cutoff=horizon + timedelta(days=1),
            effective_cutoff=horizon,
            listing_id=ACTION_LISTING_ID,
            security_id=economic_uid(21),
            venue=ListingVenue.XNYS,
            session_date=date(2026, 11, 27),
            source_id="bar-source",
            contract_hash="9" * 64,
            source_selection_policy_hash=source_policy_hash,
            profile_hash="8" * 64,
            requested_channel=session_public_channel(),
            availability_policy_id="public-exact",
            availability_policy_hash=availability_policy_hash,
            input_context_hash=context_hash,
        )
        if outer_kind == "decision"
        else ObservationOutcomeQueryV1(
            kind="outcome",
            economic_horizon=horizon,
            evidence_vintage_cutoff=horizon + timedelta(days=1),
            listing_id=ACTION_LISTING_ID,
            security_id=economic_uid(21),
            venue=ListingVenue.XNYS,
            session_date=date(2026, 11, 27),
            source_id="bar-source",
            contract_hash="9" * 64,
            source_selection_policy_hash=source_policy_hash,
            profile_hash="8" * 64,
            requested_channel=session_public_channel(),
            availability_policy_id="public-exact",
            availability_policy_hash=availability_policy_hash,
            input_context_hash=context_hash,
        )
    )
    selected_terms_hash = (
        None
        if omit_terms
        else content_hash(substitute)
        if selected_terms == "substitute"
        else "a" * 64
        if selected_terms == "arbitrary"
        else None
        if selected_terms == "absent"
        else content_hash(primary)
    )
    query = ActionSessionQueryV1(
        outer_query=outer,
        source_id=effect_source_id,
        native_occurrence_id="split-occurrence-1",
        selected_terms_hash=selected_terms_hash,
        selected_effect_hash=(
            "f" * 64 if omit_effect else content_hash(primary_effect)
        ),
        listing_id=ACTION_LISTING_ID,
        security_id=economic_uid(21),
        mic="XNYS",
        candidate_start_date=date(2026, 11, 26),
        candidate_end_date=date(2026, 11, 30),
        economic_history_start=economic.source_policy.history_start,
        economic_through=economic.source_policy.through,
        action_session_policy_hash=policy_hash,
        economic_source_policy_hash=content_hash(economic.source_policy),
    )
    return ActionSessionCase(context=context, query=query, terms=terms, effects=effects)
