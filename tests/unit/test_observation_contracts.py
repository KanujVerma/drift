"""Behavioral tests for exact M1d source-observation contracts."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

import pytest
from observation_test_support import (
    coverage_dataset,
    observation_dataset,
    observation_validation_inputs,
)
from pydantic import ValidationError

from drift.datasets.assertions import (
    build_validated_dataset_bundle,
    select_assertion_version,
)
from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import FrozenModel
from drift.domain.dataset_validation import (
    DatasetValidationError,
    ValidationResult,
    ValidationScope,
)
from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observation_query import (
    M1dSelectedRecordsV1,
    M1dSelectionProofV1,
    M1dSelectionPurpose,
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
    ObservationQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
    ObservationSubjectV1,
    SessionSubjectV1,
    m1d_implementation_hash,
    observation_cutoff,
    observation_horizon,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    EffectiveSelector,
    FieldUnit,
    IntervalPolicyV1,
    MethodBranchV1,
    MethodEquivalenceV1,
    NativeSourceFlagV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
    ObservationFieldMeaning,
    ObservationFieldMethodV1,
    ObservationInventoryEntryV1,
    ObservationMethodologyV1,
    ObservationSourceKeyV1,
    PopulationRelationshipV1,
    RevisionPolicyV1,
    RowEmissionPolicyV1,
    SourceFieldValueV1,
    TradePopulationV1,
    observation_methodology_for_contract,
    regular_session_trade_bar_profile_hash,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import ListingVenue
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
    evaluate_availability,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    observation_role_contract,
    observation_role_schema,
    validate_m1d_dataset_input,
    validate_m1d_resolution_context,
    validate_observation_dataset,
)
from drift.serialization.canonical import canonical_json, content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64


def uid(suffix: int) -> UUID:
    return UUID(f"01990000-0000-7000-8000-{suffix:012d}")


def instant(day: int) -> datetime:
    return datetime(2026, 1, day, 21, tzinfo=UTC)


def reference(suffix: int, digest: str = HASH_A) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uid(suffix),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def exact_boundary(day: int) -> TemporalBoundaryClaimV1:
    value = instant(day)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=reference(30 + day),
    )


def availability(day: int = 2) -> AvailabilityEvidenceV1:
    value = instant(day)
    return AvailabilityEvidenceV1(
        channel=AvailabilityChannelV1(
            kind=ChannelKind.PUBLIC, identifier="synthetic-public", version="1"
        ),
        shape=AvailabilityShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference(40 + day),
        rule_derivation=None,
    )


def revision(payload_hash: str = HASH_A) -> RevisionEnvelopeV1:
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=uid(100),
        record_version_id=uid(101),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(availability(),),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=reference(102),
        payload_hash=payload_hash,
    )


def population(population_id: str = "regular-trades") -> TradePopulationV1:
    return TradePopulationV1(
        population_id=population_id,
        feed_identity="synthetic-feed",
        feed_version="1",
        venue_scope=("XNYS",),
        session_scope="regular",
        event_time_basis="execution",
        sale_condition_policy_hash=HASH_A,
        odd_lot_rule="included",
        opening_auction_rule="included",
        closing_auction_rule="included",
        correction_cancellation_policy_hash=HASH_B,
        evidence_hash=HASH_A,
    )


def method(
    method_id: str,
    field_name: str,
    meaning: ObservationFieldMeaning,
    selector: EffectiveSelector,
    *,
    population_id: str = "regular-trades",
    unit: FieldUnit = "unknown",
) -> ObservationFieldMethodV1:
    return ObservationFieldMethodV1(
        method_id=method_id,
        field_name=field_name,
        meaning=meaning,
        population_id=population_id,
        effective_selector=selector,
        ordering="execution_time_then_source_sequence",
        ordering_policy_hash=HASH_A,
        precision=12,
        scale=3,
        null_meaning="no_value",
        zero_meaning="numeric_zero",
        fallback_branch_id=None,
        equivalence_evidence_hash=None,
        adjustment_basis="unadjusted",
        basis_methodology_hash=HASH_B,
        intraday_basis_homogeneity="homogeneous",
        unit=unit,
    )


def contract_values() -> dict[str, object]:
    methods = (
        method("open-v1", "open", "first_trade_price", "first"),
        method("high-v1", "high", "maximum_trade_price", "maximum"),
        method("low-v1", "low", "minimum_trade_price", "minimum"),
        method("close-v1", "close", "last_trade_price", "last"),
        method(
            "volume-v1",
            "volume",
            "share_volume",
            "sum",
            unit="shares",
        ),
    )
    return {
        "schema_version": "1",
        "contract_id": uid(1),
        "version": "1",
        "source_id": "synthetic-source",
        "methodology_artifact_hash": HASH_A,
        "availability": (availability(),),
        "market_population": "consolidated",
        "market_venues": ("XNYS",),
        "populations": (population(),),
        "field_methods": methods,
        "method_branches": tuple(
            MethodBranchV1(
                branch_id=f"{item.method_id}-always",
                method_id=item.method_id,
                trigger_kind="always",
                marker_name=None,
                marker_value=None,
            )
            for item in methods
        ),
        "method_equivalences": (),
        "volume_relationships": (
            PopulationRelationshipV1(
                price_population_id="regular-trades",
                volume_population_id="regular-trades",
                relation="equal",
                evidence_hash=HASH_A,
            ),
        ),
        "currency": "USD",
        "timestamp_meaning": "exchange_local_session_date",
        "source_label_syntax": "YYYY-MM-DD",
        "source_timezone": "America/New_York",
        "interval_policy": IntervalPolicyV1(
            open_inclusion="included",
            close_inclusion="included",
            auction_event_inclusion="included",
            event_policy_hash=HASH_A,
        ),
        "revision_policy": RevisionPolicyV1(
            kind="retained_revision_history",
            correction_horizon="finite",
            correction_duration_seconds=86400,
            policy_hash=HASH_A,
        ),
        "row_emission": RowEmissionPolicyV1(
            kind="every_relevant_session", omission_marker_policy_hash=HASH_B
        ),
        "adjustment_basis": "unadjusted",
    }


def sealed_observation(
    *,
    fields: tuple[SourceFieldValueV1, ...] | None = None,
    source_flags: tuple[NativeSourceFlagV1, ...] = (),
) -> DailySourceObservationVersionV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": revision(),
        "source_key": ObservationSourceKeyV1(
            source_id="synthetic-source", native_record_id="record-1"
        ),
        "source_record_locator": "synthetic://record-1",
        "source_record_hash": HASH_B,
        "contract_hash": HASH_A,
        "security_id": uid(200),
        "listing_id": uid(201),
        "venue": ListingVenue.XNYS,
        "session_date": date(2026, 1, 2),
        "source_local_label": "2026-01-02",
        "source_timezone": "America/New_York",
        "claimed_interval": TemporalIntervalClaimV1(
            schema_version="1", start=exact_boundary(1), end=exact_boundary(2)
        ),
        "completion_time": exact_boundary(2),
        "fields": fields
        if fields is not None
        else (
            SourceFieldValueV1(
                field_name="close",
                method_id="close-v1",
                native_text="99.500",
                value=Decimal("99.500"),
                state="value",
                native_flag=None,
            ),
        ),
        "source_flags": source_flags,
        "first_eligible_trade_time": exact_boundary(1),
        "last_eligible_trade_time": exact_boundary(2),
        "activity_claim": "qualifying_price_trade",
        "any_trade_claim": "reported",
    }
    provisional = DailySourceObservationVersionV1.model_construct(
        **values  # type: ignore[arg-type]
    )
    sealed_revision = revision(content_hash(assertion_version_payload(provisional)))
    return DailySourceObservationVersionV1.model_validate(
        {**values, "revision": sealed_revision}
    )


def source_binding(
    *, start: date, end: date, manifest_hash: str = HASH_A
) -> ObservationSourceBindingV1:
    return ObservationSourceBindingV1(
        dataset_role="source_observation",
        source_id="synthetic-source",
        contract_hash=HASH_A,
        venue=ListingVenue.XNYS,
        listing_id=uid(201),
        start_date=start,
        end_date=end,
        manifest_hashes=(manifest_hash,),
        methodology_hashes=(HASH_A,),
    )


def decision_query() -> ObservationDecisionQueryV1:
    policy = AvailabilityPolicyV1(policy_id="public-exact", permitted_rule_hashes=())
    return ObservationDecisionQueryV1(
        schema_version="1",
        kind="decision",
        decision_time=instant(5),
        knowledge_cutoff=instant(4),
        effective_cutoff=instant(3),
        listing_id=uid(201),
        security_id=uid(200),
        venue=ListingVenue.XNYS,
        session_date=date(2026, 1, 2),
        source_id="synthetic-source",
        contract_hash=HASH_A,
        source_selection_policy_hash=HASH_B,
        profile_hash=HASH_A,
        requested_channel=availability().channel,
        availability_policy_id="public-exact",
        availability_policy_hash=content_hash(policy),
        input_context_hash=HASH_A,
    )


def outcome_query() -> ObservationOutcomeQueryV1:
    decision = decision_query()
    return ObservationOutcomeQueryV1(
        kind="outcome",
        economic_horizon=instant(5),
        evidence_vintage_cutoff=instant(31),
        listing_id=decision.listing_id,
        security_id=decision.security_id,
        venue=decision.venue,
        session_date=decision.session_date,
        source_id=decision.source_id,
        contract_hash=decision.contract_hash,
        source_selection_policy_hash=decision.source_selection_policy_hash,
        profile_hash=decision.profile_hash,
        requested_channel=decision.requested_channel,
        availability_policy_id=decision.availability_policy_id,
        availability_policy_hash=decision.availability_policy_hash,
        input_context_hash=decision.input_context_hash,
    )


def decision_query_for_daily(
    record: DailySourceObservationVersionV1,
) -> ObservationDecisionQueryV1:
    return decision_query().model_copy(
        update={
            "listing_id": record.listing_id,
            "security_id": record.security_id,
            "venue": record.venue,
            "session_date": record.session_date,
            "source_id": record.source_key.source_id,
            "contract_hash": record.contract_hash,
        }
    )


def outcome_query_for_coverage(
    record: ObservationCoverageVersionV1,
) -> ObservationOutcomeQueryV1:
    return outcome_query().model_copy(
        update={
            "listing_id": record.listing_id,
            "security_id": record.security_id,
            "venue": record.venue,
            "session_date": record.start_date,
            "source_id": record.source_id,
            "contract_hash": record.contract_hash,
        }
    )


def selected_proof(
    query: ObservationQueryV1,
    record: DailySourceObservationVersionV1 | ObservationCoverageVersionV1,
    purpose: M1dSelectionPurpose,
) -> M1dSelectionProofV1:
    record_hash = content_hash(record)
    policy = AvailabilityPolicyV1(
        policy_id=query.availability_policy_id, permitted_rule_hashes=()
    )
    evidence = next(
        item
        for item in record.revision.availability
        if item.channel == query.requested_channel
    )
    projection = AssertionVersionProjectionV1(
        revision=record.revision, record_hash=record_hash
    )
    cutoff = observation_cutoff(query)
    selection = select_assertion_version(
        (projection,), query.requested_channel, policy, cutoff, {}
    )
    availability_decision = evaluate_availability(
        evidence, query.requested_channel, policy, cutoff, {}
    )
    assert selection.selected_record_hash == record_hash
    subject = (
        SessionSubjectV1(
            source_id=query.source_id,
            mic=query.venue.value,
            session_date=query.session_date,
            session_scope="regular",
        )
        if purpose in {"scheduled_session", "realized_session", "session_coverage"}
        else ObservationSubjectV1(
            listing_id=query.listing_id,
            security_id=query.security_id,
            venue=query.venue,
            session_date=query.session_date,
            source_id=query.source_id,
            contract_hash=query.contract_hash,
        )
    )
    return M1dSelectionProofV1(
        query=query,
        query_hash=content_hash(query),
        purpose=purpose,
        context_hash=query.input_context_hash,
        subject=subject,
        considered_version_hashes=(record_hash,),
        selected_hashes=(record_hash,),
        assertion_selections=(selection,),
        availability_decisions=(availability_decision,),
        semantic_algorithm_hash=HASH_A,
        implementation_hash=HASH_B,
        classification="selected",
    )


def test_source_decimal_round_trip_preserves_exact_native_claim() -> None:
    value = SourceFieldValueV1(
        field_name="close",
        method_id="last-v1",
        native_text="99.500",
        value=Decimal("99.500"),
        state="value",
        native_flag=None,
    )

    loaded = SourceFieldValueV1.model_validate_json(value.model_dump_json())

    assert loaded.value == Decimal("99.500")
    assert loaded.value.as_tuple().exponent == -3
    assert loaded.native_text == "99.500"


def test_every_public_v1_model_defaults_and_serializes_schema_version() -> None:
    models: tuple[type[FrozenModel], ...] = (
        TradePopulationV1,
        ObservationFieldMethodV1,
        MethodBranchV1,
        MethodEquivalenceV1,
        PopulationRelationshipV1,
        IntervalPolicyV1,
        RevisionPolicyV1,
        RowEmissionPolicyV1,
        ObservationContractV1,
        ObservationMethodologyV1,
        ObservationSourceKeyV1,
        NativeSourceFlagV1,
        SourceFieldValueV1,
        DailySourceObservationVersionV1,
        ObservationInventoryEntryV1,
        ObservationCoverageVersionV1,
        ObservationSourceBindingV1,
        ObservationSourceSelectionPolicyV1,
        ObservationDecisionQueryV1,
        ObservationOutcomeQueryV1,
        ObservationSubjectV1,
        M1dSelectionProofV1,
        M1dSelectedRecordsV1,
    )
    for model in models:
        assert model.model_fields["schema_version"].default == "1"
        assert model.model_construct().model_dump()["schema_version"] == "1"

    valid = SourceFieldValueV1(
        field_name="close",
        method_id="last-v1",
        native_text="99.500",
        value=Decimal("99.500"),
        state="value",
        native_flag=None,
    )
    with pytest.raises(ValidationError, match="schema_version"):
        SourceFieldValueV1.model_validate(
            {**valid.model_dump(mode="python"), "schema_version": "2"}
        )


def test_source_decimal_rejects_binary_float_input() -> None:
    with pytest.raises(ValidationError, match="exact decimal string"):
        SourceFieldValueV1.model_validate_json(
            '{"field_name":"close","method_id":"last-v1",'
            '"native_text":"99.5","value":99.5,"state":"value",'
            '"native_flag":null}'
        )


def test_generic_claim_retains_negative_and_unknown_values() -> None:
    negative = SourceFieldValueV1(
        field_name="close",
        method_id="last-v1",
        native_text="-1.250",
        value=Decimal("-1.250"),
        state="value",
        native_flag=None,
    )
    unknown = SourceFieldValueV1(
        field_name="volume",
        method_id="volume-v1",
        native_text=None,
        value=None,
        state="unknown",
        native_flag=None,
    )

    assert negative.value == Decimal("-1.250")
    assert unknown.value is None


@pytest.mark.parametrize("state", ("null", "omitted", "unknown"))
def test_non_numeric_field_states_cannot_carry_fabricated_values(
    state: Literal["null", "omitted", "unknown"],
) -> None:
    with pytest.raises(ValidationError, match="cannot carry a numeric value"):
        SourceFieldValueV1(
            field_name="close",
            method_id="last-v1",
            native_text="0",
            value=Decimal("0"),
            state=state,
            native_flag=None,
        )


def test_contract_rejects_foreign_method_population() -> None:
    values = contract_values()
    methods = list(cast(tuple[ObservationFieldMethodV1, ...], values["field_methods"]))
    methods[0] = method(
        "open-v1",
        "open",
        "first_trade_price",
        "first",
        population_id="not-in-contract",
    )
    values["field_methods"] = tuple(methods)

    with pytest.raises(ValidationError, match="unknown trade population"):
        ObservationContractV1.model_validate(values)


def test_contract_requires_historical_methodology_availability() -> None:
    values = contract_values()
    values["availability"] = ()

    with pytest.raises(ValidationError, match="availability evidence"):
        ObservationContractV1.model_validate(values)


def test_price_method_retains_explicit_currency_per_share_unit() -> None:
    price = method(
        "open-v1",
        "open",
        "first_trade_price",
        "first",
        unit="currency_per_share",
    )

    assert price.unit == "currency_per_share"


def test_regular_session_trade_bar_profile_has_stable_semantic_hash() -> None:
    first = regular_session_trade_bar_profile_hash()
    second = regular_session_trade_bar_profile_hash()

    assert first == second
    assert len(first) == 64


def test_contract_rejects_duplicate_method_and_branch_identities() -> None:
    values = contract_values()
    methods = cast(tuple[ObservationFieldMethodV1, ...], values["field_methods"])
    values["field_methods"] = (*methods, methods[0])

    with pytest.raises(ValidationError, match="method IDs must be unique"):
        ObservationContractV1.model_validate(values)


def test_contract_rejects_fallback_branch_owned_by_another_method() -> None:
    contract = ObservationContractV1.model_validate(contract_values())
    methods = tuple(
        item.model_copy(update={"fallback_branch_id": "open-v1-always"})
        if item.method_id == "close-v1"
        else item
        for item in contract.field_methods
    )

    with pytest.raises(ValidationError, match="fallback branch owner"):
        ObservationContractV1.model_validate(
            {**contract.model_dump(mode="python"), "field_methods": methods}
        )

    values = contract_values()
    branches = cast(tuple[MethodBranchV1, ...], values["method_branches"])
    values["method_branches"] = (*branches, branches[0])
    with pytest.raises(ValidationError, match="branch IDs must be unique"):
        ObservationContractV1.model_validate(values)


def test_contract_canonicalizes_all_ordered_sets() -> None:
    values = contract_values()
    values["market_venues"] = ("XNYS", "XNAS")
    values["populations"] = (population("z-population"), population())
    values["field_methods"] = tuple(
        reversed(cast(tuple[ObservationFieldMethodV1, ...], values["field_methods"]))
    )
    values["method_branches"] = tuple(
        reversed(cast(tuple[MethodBranchV1, ...], values["method_branches"]))
    )

    contract = ObservationContractV1.model_validate(values)

    assert contract.market_venues == ("XNAS", "XNYS")
    assert tuple(item.population_id for item in contract.populations) == (
        "regular-trades",
        "z-population",
    )
    assert contract.field_methods == tuple(
        sorted(
            contract.field_methods, key=lambda item: (item.field_name, item.method_id)
        )
    )
    assert contract.method_branches == tuple(
        sorted(
            contract.method_branches,
            key=lambda item: (item.method_id, item.branch_id),
        )
    )


@pytest.mark.parametrize(
    ("trigger_kind", "marker_name", "marker_value"),
    (("always", "flag", None), ("source_marker_equals", None, "yes")),
)
def test_method_branch_trigger_shape_is_exact(
    trigger_kind: Literal["always", "source_marker_equals"],
    marker_name: str | None,
    marker_value: str | None,
) -> None:
    with pytest.raises(ValidationError, match="branch trigger"):
        MethodBranchV1(
            branch_id="branch",
            method_id="open-v1",
            trigger_kind=trigger_kind,
            marker_name=marker_name,
            marker_value=marker_value,
        )


def test_revision_policy_requires_exact_finite_horizon_shape() -> None:
    with pytest.raises(ValidationError, match="finite correction horizon"):
        RevisionPolicyV1(
            kind="retained_revision_history",
            correction_horizon="finite",
            correction_duration_seconds=None,
            policy_hash=HASH_A,
        )


def test_methodology_is_the_exact_canonical_contract_rule_projection() -> None:
    contract = ObservationContractV1.model_validate(contract_values())

    methodology = observation_methodology_for_contract(contract)

    assert isinstance(methodology, ObservationMethodologyV1)
    assert methodology.policy_id == str(contract.contract_id)
    assert methodology.policy_version == contract.version
    assert methodology.method_algorithm == "synthetic_declared_trade_population_v1"
    assert methodology.field_methods == contract.field_methods
    assert methodology.row_emission == contract.row_emission


def test_daily_source_row_rejects_duplicate_fields_and_flags() -> None:
    duplicate_field = SourceFieldValueV1(
        field_name="close",
        method_id="close-v1",
        native_text="99.500",
        value=Decimal("99.500"),
        state="value",
        native_flag=None,
    )
    with pytest.raises(ValidationError, match="field names must be unique"):
        sealed_observation(fields=(duplicate_field, duplicate_field))

    flag = NativeSourceFlagV1(key="fallback", value="yes")
    with pytest.raises(ValidationError, match="source flag keys must be unique"):
        sealed_observation(source_flags=(flag, flag))


def test_daily_source_row_payload_hash_is_bound_to_all_claims() -> None:
    row = sealed_observation()
    values = row.model_dump(mode="python")
    values["source_local_label"] = "2026-01-02-corrected"

    with pytest.raises(ValidationError, match="observation payload hash mismatch"):
        DailySourceObservationVersionV1.model_validate(values)


def test_coverage_inventory_is_canonical_and_cannot_include_itself() -> None:
    inventory = (
        ObservationInventoryEntryV1(
            assertion_id=uid(501), version_id=uid(502), record_hash=HASH_B
        ),
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": revision(),
        "source_id": "synthetic-source",
        "native_record_id": "coverage-1",
        "contract_hash": HASH_A,
        "venue": ListingVenue.XNYS,
        "listing_id": uid(201),
        "security_id": uid(200),
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
        "snapshot_identifier": "snapshot-1",
        "snapshot_as_of": exact_boundary(31),
        "covered_dataset_hashes": (HASH_A,),
        "covered_partition_hashes": (HASH_B,),
        "record_inventory": inventory,
        "methodology_artifact_hash": HASH_A,
        "omission_rule_hash": HASH_B,
        "status": "expected_complete",
        "exception_keys": (),
        "missing_artifact_hashes": (),
        "revision_history_completeness": "complete",
    }
    provisional = ObservationCoverageVersionV1.model_construct(
        **values  # type: ignore[arg-type]
    )
    values["revision"] = revision(content_hash(assertion_version_payload(provisional)))
    coverage = ObservationCoverageVersionV1.model_validate(values)
    assert coverage.record_inventory == inventory

    reversed_dates = {**values, "start_date": date(2026, 2, 1)}
    with pytest.raises(ValidationError, match="coverage date interval"):
        ObservationCoverageVersionV1.model_validate(reversed_dates)

    own_hash = content_hash(coverage)
    self_inventory = (
        ObservationInventoryEntryV1(
            assertion_id=coverage.revision.logical_record_id,
            version_id=coverage.revision.record_version_id,
            record_hash=own_hash,
        ),
    )
    forged_values = {
        name: getattr(coverage, name) for name in type(coverage).model_fields
    }
    forged_values["record_inventory"] = self_inventory
    forged = ObservationCoverageVersionV1.model_construct(**forged_values)
    with pytest.raises(ValidationError, match="cannot inventory itself"):
        ObservationCoverageVersionV1.model_validate(forged.model_dump(mode="python"))


def test_observation_query_clocks_are_role_specific_and_bounded() -> None:
    decision = decision_query()
    outcome = ObservationOutcomeQueryV1(
        schema_version="1",
        kind="outcome",
        economic_horizon=instant(5),
        evidence_vintage_cutoff=instant(31),
        listing_id=decision.listing_id,
        security_id=decision.security_id,
        venue=decision.venue,
        session_date=decision.session_date,
        source_id=decision.source_id,
        contract_hash=decision.contract_hash,
        source_selection_policy_hash=decision.source_selection_policy_hash,
        profile_hash=decision.profile_hash,
        requested_channel=decision.requested_channel,
        availability_policy_id=decision.availability_policy_id,
        availability_policy_hash=decision.availability_policy_hash,
        input_context_hash=decision.input_context_hash,
    )

    assert observation_cutoff(decision) == decision.knowledge_cutoff
    assert observation_horizon(decision) == decision.effective_cutoff
    assert observation_cutoff(outcome) == outcome.evidence_vintage_cutoff
    assert observation_horizon(outcome) == outcome.economic_horizon

    with pytest.raises(ValidationError, match="knowledge cutoff"):
        decision.model_copy(update={"knowledge_cutoff": instant(6)})
    with pytest.raises(ValidationError, match="effective cutoff"):
        decision.model_copy(update={"effective_cutoff": instant(6)})


def test_source_policy_rejects_unresolved_overlapping_authority() -> None:
    first = source_binding(start=date(2026, 1, 1), end=date(2026, 1, 10))
    conflicting = source_binding(
        start=date(2026, 1, 10), end=date(2026, 1, 20), manifest_hash=HASH_B
    )

    with pytest.raises(ValidationError, match="overlapping source authority"):
        ObservationSourceSelectionPolicyV1(
            schema_version="1",
            policy_id="sources",
            version="1",
            bindings=(first, conflicting),
        )


def test_source_policy_allows_same_inventory_partitions_and_sorts_bindings() -> None:
    later = source_binding(start=date(2026, 1, 10), end=date(2026, 1, 20))
    earlier = source_binding(start=date(2026, 1, 1), end=date(2026, 1, 10))

    policy = ObservationSourceSelectionPolicyV1(
        schema_version="1", policy_id="sources", version="1", bindings=(later, earlier)
    )

    assert policy.bindings == (earlier, later)


def test_m1d_fingerprint_delegates_to_whole_installed_package_inventory() -> None:
    assert m1d_implementation_hash() == economic_implementation_hash()


def test_selection_proof_binds_query_context_and_classification() -> None:
    query = decision_query()
    record = observation_dataset()[0].records[0]
    assert isinstance(record, DailySourceObservationVersionV1)
    proof = selected_proof(query, record, "observation")
    assert proof.considered_version_hashes == tuple(
        sorted(proof.considered_version_hashes)
    )

    with pytest.raises(ValidationError, match="query hash"):
        proof.model_copy(update={"query_hash": HASH_A})
    with pytest.raises(ValidationError, match="selected classification"):
        proof.model_copy(update={"selected_hashes": ()})


def test_selected_source_proof_requires_real_m1a_witness_shapes() -> None:
    query = decision_query()
    record = observation_dataset()[0].records[0]
    assert isinstance(record, DailySourceObservationVersionV1)
    proof = selected_proof(query, record, "observation")

    with pytest.raises(ValidationError, match="assertion selection witness"):
        proof.model_copy(update={"assertion_selections": ()})
    with pytest.raises(ValidationError, match="availability decision witness"):
        proof.model_copy(update={"availability_decisions": ()})

    contract_proof = proof.model_copy(
        update={"purpose": "contract", "assertion_selections": ()}
    )
    assert contract_proof.purpose == "contract"


def test_selected_records_reject_cross_role_and_future_purpose() -> None:
    observation, support = observation_dataset()
    daily = observation.records[0]
    assert isinstance(daily, DailySourceObservationVersionV1)
    coverage = coverage_dataset(observation, support).records[0]
    assert isinstance(coverage, ObservationCoverageVersionV1)

    coverage_query = outcome_query_for_coverage(coverage)
    cross_role_proof = selected_proof(coverage_query, coverage, "observation")
    with pytest.raises(ValidationError, match="record type"):
        M1dSelectedRecordsV1(
            query=coverage_query,
            purpose="observation",
            dataset_role="source_observation",
            records=(coverage,),
            proof=cross_role_proof,
        )

    daily_query = decision_query_for_daily(daily)
    daily_proof = selected_proof(daily_query, daily, "observation")
    selected = M1dSelectedRecordsV1(
        query=daily_proof.query,
        purpose="observation",
        dataset_role="source_observation",
        records=(daily,),
        proof=daily_proof,
    )
    assert selected.records == (daily,)
    with pytest.raises(ValidationError, match="role must match purpose"):
        M1dSelectedRecordsV1(
            query=daily_proof.query,
            purpose="observation",
            dataset_role="observation_coverage",
            records=(daily,),
            proof=daily_proof,
        )

    future_proof = selected_proof(daily_query, daily, "scheduled_session")
    with pytest.raises(ValidationError, match="not owned by Task 1"):
        M1dSelectedRecordsV1(
            query=future_proof.query,
            purpose="scheduled_session",
            dataset_role="source_observation",
            records=(daily,),
            proof=future_proof,
        )


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    (
        ("source_id", "other-source"),
        ("contract_hash", "f" * 64),
        ("listing_id", uid(880)),
        ("security_id", uid(881)),
        ("venue", ListingVenue.XNAS),
        ("session_date", date(2026, 1, 3)),
    ),
)
def test_selected_daily_record_binds_every_query_subject_dimension(
    field_name: str, wrong_value: object
) -> None:
    daily = observation_dataset()[0].records[0]
    assert isinstance(daily, DailySourceObservationVersionV1)
    query = decision_query_for_daily(daily).model_copy(update={field_name: wrong_value})
    proof = selected_proof(query, daily, "observation")

    with pytest.raises(ValidationError, match="daily record subject"):
        M1dSelectedRecordsV1(
            query=query,
            purpose="observation",
            dataset_role="source_observation",
            records=(daily,),
            proof=proof,
        )


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    (
        ("source_id", "other-source"),
        ("contract_hash", "f" * 64),
        ("listing_id", uid(882)),
        ("security_id", uid(883)),
        ("venue", ListingVenue.XNAS),
        ("session_date", date(2026, 2, 1)),
    ),
)
def test_selected_coverage_record_binds_identity_and_inclusive_date_scope(
    field_name: str, wrong_value: object
) -> None:
    observation, support = observation_dataset()
    coverage = coverage_dataset(observation, support).records[0]
    assert isinstance(coverage, ObservationCoverageVersionV1)
    query = outcome_query_for_coverage(coverage).model_copy(
        update={field_name: wrong_value}
    )
    proof = selected_proof(query, coverage, "observation_coverage")

    with pytest.raises(ValidationError, match="coverage record subject"):
        M1dSelectedRecordsV1(
            query=query,
            purpose="observation_coverage",
            dataset_role="observation_coverage",
            records=(coverage,),
            proof=proof,
        )


def test_selected_coverage_accepts_exact_subject_at_inclusive_boundary() -> None:
    observation, support = observation_dataset()
    coverage = coverage_dataset(observation, support).records[0]
    assert isinstance(coverage, ObservationCoverageVersionV1)
    query = outcome_query_for_coverage(coverage).model_copy(
        update={"session_date": coverage.end_date}
    )
    proof = selected_proof(query, coverage, "observation_coverage")

    selected = M1dSelectedRecordsV1(
        query=query,
        purpose="observation_coverage",
        dataset_role="observation_coverage",
        records=(coverage,),
        proof=proof,
    )

    assert selected.records == (coverage,)


def test_observation_role_schema_and_temporal_contract_are_exact() -> None:
    schema = observation_role_schema("source_observation")
    contract = observation_role_contract(
        "source_observation", (availability().channel,)
    )

    assert schema.schema_hash
    assert tuple(item.field_id for item in schema.fields) == tuple(
        sorted(item.field_id for item in schema.fields)
    )
    assert contract.effective_time_field_id == "completion_time"
    assert contract.semantic_state_field_ids == tuple(
        sorted(
            item.field_id
            for item in schema.fields
            if item.field_id
            not in {
                "revision.logical_record_id",
                "revision.record_version_id",
                "revision.revision_kind",
                "revision.supersedes_record_version_id",
                "revision.source_sequence",
                "revision.availability",
                "revision.source_artifact",
                "revision.payload_hash",
                "completion_time",
            }
        )
    )


def test_valid_source_dataset_returns_real_pass_and_replays_from_bytes() -> None:
    dataset, support = observation_dataset()

    assert dataset.decision.result is ValidationResult.PASS
    assert dataset.decision.validation_scope is ValidationScope.RECORDS
    assert dataset.records
    validate_m1d_dataset_input(dataset, support)


def test_dataset_rejects_selected_method_not_owned_by_bound_contract() -> None:
    manifest, artifacts, run, support = observation_validation_inputs()
    valid = observation_dataset()[0].records[0]
    assert isinstance(valid, DailySourceObservationVersionV1)
    foreign = SourceFieldValueV1(
        field_name="close",
        method_id="foreign-method",
        native_text="99.500",
        value=Decimal("99.500"),
        state="value",
        native_flag=None,
    )
    values = {name: getattr(valid, name) for name in type(valid).model_fields}
    values["fields"] = tuple(
        foreign if item.field_name == "close" else item for item in valid.fields
    )
    provisional = DailySourceObservationVersionV1.model_construct(**values)
    values["revision"] = valid.revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    forged = DailySourceObservationVersionV1.model_validate(values)
    manifest, artifacts, run, support = observation_validation_inputs((forged,))

    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)

    assert decision.result is ValidationResult.FAIL
    assert parsed == ()
    assert {item.code for item in decision.findings} == {
        "observation_method_foreign_to_contract"
    }


def test_raw_unsupported_precision_fails_before_timezone_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, artifacts, run, support = observation_validation_inputs()
    artifact = next(iter(artifacts.values()))
    raw = artifact.data.replace(b'"precision":"second"', b'"precision":"date"', 1)
    digest = __import__("hashlib").sha256(raw).hexdigest()
    partition = manifest.partitions[0]
    rebound_reference = partition.artifact.model_copy(
        update={"content_hash": digest, "location": f"drift+sha256://{digest}"}
    )
    rebound_partition = partition.model_copy(
        update={"artifact": rebound_reference, "byte_size": len(raw)}
    )
    rebound_manifest = manifest.model_copy(update={"partitions": (rebound_partition,)})
    artifacts = {
        digest: type(artifact)(data=raw, byte_size=len(raw), content_hash=digest)
    }

    def forbidden_zoneinfo(*args: object, **kwargs: object) -> object:
        raise AssertionError("ambient ZoneInfo must not run for rejected raw precision")

    monkeypatch.setattr("drift.domain.temporal.ZoneInfo", forbidden_zoneinfo)
    decision, parsed = validate_observation_dataset(
        rebound_manifest, artifacts, run, support
    )

    assert decision.result is ValidationResult.FAIL
    assert parsed == ()
    assert {item.code for item in decision.findings} == {
        "observation_unsupported_raw_temporal_precision"
    }


def test_unreferenced_support_precision_metadata_is_not_temporal_evidence() -> None:
    manifest, artifacts, run, support = observation_validation_inputs()
    metadata = canonical_json({"precision": "minute"})
    digest = sha256(metadata).hexdigest()
    support[digest] = VerifiedArtifactBytes(
        data=metadata, byte_size=len(metadata), content_hash=digest
    )

    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)

    assert decision.result is ValidationResult.PASS
    assert parsed


def test_duplicate_json_keys_and_corrupt_mapping_binding_fail_closed() -> None:
    manifest, artifacts, run, support = observation_validation_inputs()
    artifact = next(iter(artifacts.values()))
    duplicate = b'{"schema_version":"1","schema_version":"1","records":[]}'
    digest = __import__("hashlib").sha256(duplicate).hexdigest()
    partition = manifest.partitions[0]
    rebound_reference = partition.artifact.model_copy(
        update={"content_hash": digest, "location": f"drift+sha256://{digest}"}
    )
    rebound_manifest = manifest.model_copy(
        update={
            "partitions": (
                partition.model_copy(
                    update={
                        "artifact": rebound_reference,
                        "byte_size": len(duplicate),
                        "row_count": 0,
                    }
                ),
            )
        }
    )
    duplicate_artifacts = {
        digest: type(artifact)(
            data=duplicate, byte_size=len(duplicate), content_hash=digest
        )
    }
    decision, parsed = validate_observation_dataset(
        rebound_manifest, duplicate_artifacts, run, support
    )
    assert decision.result is ValidationResult.FAIL
    assert parsed == ()
    assert {item.code for item in decision.findings} == {
        "observation_dataset_duplicate_json_key"
    }

    wrong_key = {HASH_A: artifact}
    decision, parsed = validate_observation_dataset(manifest, wrong_key, run, support)
    assert decision.result is ValidationResult.FAIL
    assert parsed == ()
    assert "observation_artifact_mapping_key_mismatch" in {
        item.code for item in decision.findings
    }


def test_dataset_input_and_resolution_context_snapshot_all_mappings() -> None:
    dataset, support = observation_dataset()
    artifacts = dict(dataset.artifacts)
    copied = type(dataset)(
        manifest=dataset.manifest,
        validation_run=dataset.validation_run,
        artifacts=artifacts,
        records=dataset.records,
        decision=dataset.decision,
        bundle=dataset.bundle,
    )
    artifacts.clear()
    assert copied.artifacts

    policy = AvailabilityPolicyV1(policy_id="public-exact", permitted_rule_hashes=())
    policies = {content_hash(policy): policy}
    evidence = availability()
    retained = {content_hash(evidence): evidence}
    mutable_support = dict(support)
    context = M1dResolutionContext(
        observation_datasets=(dataset,),
        availability_policies=policies,
        retained_evidence=retained,
        supporting_artifacts=mutable_support,
    )
    expected_hash = m1d_context_hash(context)
    policies.clear()
    retained.clear()
    mutable_support.clear()

    assert context.availability_policies
    assert context.retained_evidence
    assert context.supporting_artifacts
    assert m1d_context_hash(context) == expected_hash
    validate_m1d_resolution_context(context)


def test_dataset_input_replay_rejects_constructor_bypassed_claimed_records() -> None:
    dataset, support = observation_dataset()
    forged = type(dataset)(
        manifest=dataset.manifest,
        validation_run=dataset.validation_run,
        artifacts=dataset.artifacts,
        records=(),
        decision=dataset.decision,
        bundle=dataset.bundle,
    )

    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_dataset_input(forged, support)
    assert tuple(item.code for item in caught.value.findings) == (
        "observation_parsed_records_mismatch",
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("schema_version", "2"),
        ("bundle_id", UUID(int=1)),
        ("bundle_version", ""),
        ("created_at", datetime(2026, 1, 1)),
    ),
)
def test_dataset_input_revalidates_full_bundle_metadata(
    field_name: str, invalid_value: object
) -> None:
    dataset, support = observation_dataset()
    values = {
        name: getattr(dataset.bundle, name)
        for name in type(dataset.bundle).model_fields
    }
    values[field_name] = invalid_value
    malformed_bundle = type(dataset.bundle).model_construct(**values)
    malformed = replace(dataset, bundle=malformed_bundle)
    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_dataset_input(malformed, support)
    assert tuple(item.code for item in caught.value.findings) == (
        "observation_bundle_invalid",
    )


def test_dataset_input_allows_valid_rebundling() -> None:
    dataset, support = observation_dataset()
    valid_rebundle = build_validated_dataset_bundle(
        bundle_id=uid(990),
        bundle_version="reviewed-rebundle-1",
        created_at=instant(9),
        validated_datasets=((dataset.manifest, dataset.decision),),
    )
    validate_m1d_dataset_input(replace(dataset, bundle=valid_rebundle), support)


def test_context_requires_coverage_inventory_to_match_exact_target_bytes() -> None:
    observation, support = observation_dataset()
    coverage = coverage_dataset(observation, support)
    context = M1dResolutionContext(
        observation_datasets=(observation, coverage),
        availability_policies={},
        retained_evidence={},
        supporting_artifacts=support,
    )
    validate_m1d_resolution_context(context)

    forged_coverage = coverage_dataset(
        observation, support, inventory_record_hash=HASH_A
    )
    forged_context = M1dResolutionContext(
        observation_datasets=(observation, forged_coverage),
        availability_policies={},
        retained_evidence={},
        supporting_artifacts=support,
    )
    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_resolution_context(forged_context)
    assert tuple(item.code for item in caught.value.findings) == (
        "observation_coverage_inventory_mismatch",
    )

    with pytest.raises(ValidationError, match="only finite correction horizon"):
        RevisionPolicyV1(
            kind="unknown",
            correction_horizon="unknown",
            correction_duration_seconds=1,
            policy_hash=HASH_A,
        )


def test_intrinsically_contradictory_source_clock_is_retained_structurally() -> None:
    dataset, support = observation_dataset()
    record = dataset.records[0]
    assert isinstance(record, DailySourceObservationVersionV1)
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values["completion_time"] = record.claimed_interval.start
    provisional = DailySourceObservationVersionV1.model_construct(**values)
    values["revision"] = record.revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    contradictory = DailySourceObservationVersionV1.model_validate(values)
    manifest, artifacts, run, support = observation_validation_inputs((contradictory,))

    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)

    assert decision.result is ValidationResult.PASS
    assert parsed == (contradictory,)
