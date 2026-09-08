"""Immutable M1d source-observation claims and methodology contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from drift.datasets.hashing import assertion_version_payload
from drift.domain.assertions import (
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.securities import ListingVenue
from drift.domain.temporal import (
    AvailabilityEvidenceV1,
    availability_channel_identity,
)
from drift.serialization.canonical import content_hash

type MarketPopulationKind = Literal[
    "consolidated", "primary_exchange", "named_venue", "provider_composite", "unknown"
]
type SessionScope = Literal["regular", "extended", "full_day", "unknown"]
type EventTimeBasis = Literal["execution", "report", "processing", "unknown"]
type RuleDisposition = Literal["included", "excluded", "conditional", "unknown"]
type ObservationFieldMeaning = Literal[
    "first_trade_price",
    "maximum_trade_price",
    "minimum_trade_price",
    "last_trade_price",
    "official_open",
    "official_close",
    "share_volume",
    "dollar_volume",
    "trade_count",
    "lot_count",
    "other",
    "unknown",
]
type TradeOrdering = Literal[
    "execution_time_then_source_sequence",
    "source_sequence",
    "feed_state_policy",
    "not_applicable",
    "unknown",
]
type EffectiveSelector = Literal[
    "first", "maximum", "minimum", "last", "sum", "official", "other", "unknown"
]
type NullMeaning = Literal[
    "no_value",
    "no_eligible_price_trade",
    "not_applicable",
    "source_missing",
    "unknown",
]
type ZeroMeaning = Literal[
    "numeric_zero",
    "no_eligible_price_trade_sentinel",
    "source_missing_sentinel",
    "invalid",
    "unknown",
]
type VolumeUnit = Literal[
    "shares", "currency_notional", "trades", "lots", "other", "unknown"
]
type FieldUnit = Literal[
    "currency_per_share",
    "shares",
    "currency_notional",
    "trades",
    "lots",
    "other",
    "unknown",
]
type AdjustmentBasis = Literal[
    "unadjusted",
    "split_adjusted",
    "dividend_adjusted",
    "total_return_like",
    "mixed",
    "unknown",
]
type MethodAdjustmentBasis = Literal[
    "unadjusted",
    "split_adjusted",
    "dividend_adjusted",
    "total_return_like",
    "unknown",
]
type TimestampMeaning = Literal[
    "exchange_local_session_date",
    "utc_interval",
    "publication_date",
    "other",
    "unknown",
]


class TradePopulationV1(FrozenModel):
    """One exactly identified population of source-reported trades."""

    schema_version: Literal["1"] = "1"
    population_id: NonBlankStr
    feed_identity: NonBlankStr
    feed_version: NonBlankStr | None
    venue_scope: tuple[NonBlankStr, ...]
    session_scope: SessionScope
    event_time_basis: EventTimeBasis
    sale_condition_policy_hash: SHA256Hash
    odd_lot_rule: RuleDisposition
    opening_auction_rule: RuleDisposition
    closing_auction_rule: RuleDisposition
    correction_cancellation_policy_hash: SHA256Hash
    evidence_hash: SHA256Hash

    @field_validator("venue_scope")
    @classmethod
    def canonicalize_venue_scope(
        cls, venues: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if len(set(venues)) != len(venues):
            raise ValueError("population venue scope must be unique")
        return tuple(sorted(venues))


class ObservationFieldMethodV1(FrozenModel):
    """One source field method with its exact semantic dimensions."""

    schema_version: Literal["1"] = "1"
    method_id: NonBlankStr
    field_name: NonBlankStr
    meaning: ObservationFieldMeaning
    population_id: NonBlankStr
    effective_selector: EffectiveSelector
    ordering: TradeOrdering
    ordering_policy_hash: SHA256Hash
    precision: Annotated[int, Field(ge=1)]
    scale: Annotated[int, Field(ge=0)]
    null_meaning: NullMeaning
    zero_meaning: ZeroMeaning
    fallback_branch_id: NonBlankStr | None
    equivalence_evidence_hash: SHA256Hash | None
    adjustment_basis: MethodAdjustmentBasis
    basis_methodology_hash: SHA256Hash
    intraday_basis_homogeneity: Literal["homogeneous", "unknown"]
    unit: FieldUnit


class MethodBranchV1(FrozenModel):
    """A closed, source-marker-selected method branch."""

    schema_version: Literal["1"] = "1"
    branch_id: NonBlankStr
    method_id: NonBlankStr
    trigger_kind: Literal["always", "source_marker_equals"]
    marker_name: NonBlankStr | None
    marker_value: NonBlankStr | None

    @model_validator(mode="after")
    def validate_trigger(self) -> Self:
        if self.trigger_kind == "always":
            if self.marker_name is not None or self.marker_value is not None:
                raise ValueError("always branch trigger cannot carry a marker")
        elif self.marker_name is None or self.marker_value is None:
            raise ValueError("source-marker branch trigger requires name and value")
        return self


class MethodEquivalenceV1(FrozenModel):
    """A synthetic exact-method equivalence claim, never a general proof language."""

    schema_version: Literal["1"] = "1"
    contract_id: UUID7
    source_id: NonBlankStr
    field_name: NonBlankStr
    from_method_id: NonBlankStr
    to_method_id: NonBlankStr
    kind: Literal["identical_trade_selector_population_v1"]
    methodology_artifact_hash: SHA256Hash


class PopulationRelationshipV1(FrozenModel):
    """An exact relation between a price population and volume population."""

    schema_version: Literal["1"] = "1"
    price_population_id: NonBlankStr
    volume_population_id: NonBlankStr
    relation: Literal["price_subset_of_volume", "equal", "different", "unknown"]
    evidence_hash: SHA256Hash


class IntervalPolicyV1(FrozenModel):
    """Exact interval endpoint and auction-event treatment."""

    schema_version: Literal["1"] = "1"
    open_inclusion: RuleDisposition
    close_inclusion: RuleDisposition
    auction_event_inclusion: RuleDisposition
    event_policy_hash: SHA256Hash


class RevisionPolicyV1(FrozenModel):
    """Source correction retention and horizon semantics."""

    schema_version: Literal["1"] = "1"
    kind: Literal["retained_revision_history", "current_snapshot_only", "unknown"]
    correction_horizon: Literal["finite", "unbounded", "unknown"]
    correction_duration_seconds: Annotated[int, Field(gt=0)] | None
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_horizon(self) -> Self:
        if self.correction_horizon == "finite":
            if self.correction_duration_seconds is None:
                raise ValueError("finite correction horizon requires a duration")
        elif self.correction_duration_seconds is not None:
            raise ValueError("only finite correction horizon permits a duration")
        return self


class RowEmissionPolicyV1(FrozenModel):
    """Source row emission and omission semantics."""

    schema_version: Literal["1"] = "1"
    kind: Literal[
        "every_relevant_session",
        "conditional_on_qualifying_activity",
        "explicit_markers",
        "unknown",
    ]
    omission_marker_policy_hash: SHA256Hash


class ObservationContractV1(FrozenModel):
    """Immutable content-addressed methodology for one exact source version."""

    schema_version: Literal["1"] = "1"
    contract_id: UUID7
    version: NonBlankStr
    source_id: NonBlankStr
    methodology_artifact_hash: SHA256Hash
    availability: tuple[AvailabilityEvidenceV1, ...]
    market_population: MarketPopulationKind
    market_venues: tuple[NonBlankStr, ...]
    populations: tuple[TradePopulationV1, ...]
    field_methods: tuple[ObservationFieldMethodV1, ...]
    method_branches: tuple[MethodBranchV1, ...]
    method_equivalences: tuple[MethodEquivalenceV1, ...]
    volume_relationships: tuple[PopulationRelationshipV1, ...]
    currency: NonBlankStr
    timestamp_meaning: TimestampMeaning
    source_label_syntax: NonBlankStr
    source_timezone: NonBlankStr
    interval_policy: IntervalPolicyV1
    revision_policy: RevisionPolicyV1
    row_emission: RowEmissionPolicyV1
    adjustment_basis: AdjustmentBasis

    @field_validator("availability")
    @classmethod
    def canonicalize_availability(
        cls, evidence: tuple[AvailabilityEvidenceV1, ...]
    ) -> tuple[AvailabilityEvidenceV1, ...]:
        if not evidence:
            raise ValueError("contract requires availability evidence")
        channels = tuple(item.channel for item in evidence)
        if len(set(channels)) != len(channels):
            raise ValueError("contract availability channels must be unique")
        return tuple(
            sorted(
                evidence, key=lambda item: availability_channel_identity(item.channel)
            )
        )

    @field_validator("market_venues")
    @classmethod
    def canonicalize_market_venues(
        cls, venues: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if len(set(venues)) != len(venues):
            raise ValueError("contract market venues must be unique")
        return tuple(sorted(venues))

    @field_validator("populations")
    @classmethod
    def canonicalize_populations(
        cls, populations: tuple[TradePopulationV1, ...]
    ) -> tuple[TradePopulationV1, ...]:
        identities = tuple(item.population_id for item in populations)
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("trade population IDs must be nonempty and unique")
        return tuple(sorted(populations, key=lambda item: item.population_id))

    @field_validator("field_methods")
    @classmethod
    def canonicalize_field_methods(
        cls, methods: tuple[ObservationFieldMethodV1, ...]
    ) -> tuple[ObservationFieldMethodV1, ...]:
        identities = tuple(item.method_id for item in methods)
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("field method IDs must be unique and nonempty")
        return tuple(
            sorted(methods, key=lambda item: (item.field_name, item.method_id))
        )

    @field_validator("method_branches")
    @classmethod
    def canonicalize_method_branches(
        cls, branches: tuple[MethodBranchV1, ...]
    ) -> tuple[MethodBranchV1, ...]:
        identities = tuple(item.branch_id for item in branches)
        if len(set(identities)) != len(identities):
            raise ValueError("method branch IDs must be unique")
        return tuple(
            sorted(branches, key=lambda item: (item.method_id, item.branch_id))
        )

    @field_validator("method_equivalences")
    @classmethod
    def canonicalize_method_equivalences(
        cls, relations: tuple[MethodEquivalenceV1, ...]
    ) -> tuple[MethodEquivalenceV1, ...]:
        identities = tuple(
            (item.field_name, item.from_method_id, item.to_method_id)
            for item in relations
        )
        if len(set(identities)) != len(identities):
            raise ValueError("method equivalence identities must be unique")
        return tuple(
            sorted(
                relations,
                key=lambda item: (
                    item.field_name,
                    item.from_method_id,
                    item.to_method_id,
                ),
            )
        )

    @field_validator("volume_relationships")
    @classmethod
    def canonicalize_volume_relationships(
        cls, relations: tuple[PopulationRelationshipV1, ...]
    ) -> tuple[PopulationRelationshipV1, ...]:
        identities = tuple(
            (item.price_population_id, item.volume_population_id) for item in relations
        )
        if len(set(identities)) != len(identities):
            raise ValueError("population relationship endpoints must be unique")
        return tuple(
            sorted(
                relations,
                key=lambda item: (
                    item.price_population_id,
                    item.volume_population_id,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        populations = {item.population_id for item in self.populations}
        methods = {item.method_id: item for item in self.field_methods}
        if any(item.population_id not in populations for item in self.field_methods):
            raise ValueError("field method references an unknown trade population")
        if any(item.method_id not in methods for item in self.method_branches):
            raise ValueError("method branch references an unknown field method")
        branches = {item.branch_id: item for item in self.method_branches}
        for method in self.field_methods:
            if method.fallback_branch_id is None:
                continue
            branch = branches.get(method.fallback_branch_id)
            if branch is None:
                raise ValueError("field method references an unknown fallback branch")
            if branch.method_id != method.method_id:
                raise ValueError("field method fallback branch owner mismatch")
        for relation in self.method_equivalences:
            left = methods.get(relation.from_method_id)
            right = methods.get(relation.to_method_id)
            if (
                relation.contract_id != self.contract_id
                or relation.source_id != self.source_id
                or left is None
                or right is None
                or left.field_name != relation.field_name
                or right.field_name != relation.field_name
            ):
                raise ValueError("method equivalence must bind this contract and field")
        if any(
            item.price_population_id not in populations
            or item.volume_population_id not in populations
            for item in self.volume_relationships
        ):
            raise ValueError("population relationship references an unknown population")
        return self


class ObservationMethodologyV1(FrozenModel):
    """Canonical synthetic methodology bytes interpreted by M1d."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    source_id: NonBlankStr
    method_algorithm: Literal["synthetic_declared_trade_population_v1"]
    market_population: MarketPopulationKind
    market_venues: tuple[NonBlankStr, ...]
    populations: tuple[TradePopulationV1, ...]
    field_methods: tuple[ObservationFieldMethodV1, ...]
    method_branches: tuple[MethodBranchV1, ...]
    method_equivalences: tuple[MethodEquivalenceV1, ...]
    volume_relationships: tuple[PopulationRelationshipV1, ...]
    currency: NonBlankStr
    timestamp_meaning: TimestampMeaning
    source_label_syntax: NonBlankStr
    source_timezone: NonBlankStr
    interval_policy: IntervalPolicyV1
    revision_policy: RevisionPolicyV1
    row_emission: RowEmissionPolicyV1
    adjustment_basis: AdjustmentBasis


def observation_methodology_for_contract(
    contract: ObservationContractV1,
) -> ObservationMethodologyV1:
    """Project the only V1 synthetic methodology accepted for a contract."""
    return ObservationMethodologyV1(
        schema_version="1",
        policy_id=str(contract.contract_id),
        policy_version=contract.version,
        source_id=contract.source_id,
        method_algorithm="synthetic_declared_trade_population_v1",
        market_population=contract.market_population,
        market_venues=contract.market_venues,
        populations=contract.populations,
        field_methods=contract.field_methods,
        method_branches=contract.method_branches,
        method_equivalences=contract.method_equivalences,
        volume_relationships=contract.volume_relationships,
        currency=contract.currency,
        timestamp_meaning=contract.timestamp_meaning,
        source_label_syntax=contract.source_label_syntax,
        source_timezone=contract.source_timezone,
        interval_policy=contract.interval_policy,
        revision_policy=contract.revision_policy,
        row_emission=contract.row_emission,
        adjustment_basis=contract.adjustment_basis,
    )


class ObservationSourceKeyV1(FrozenModel):
    """Stable native revision-chain identity for one observation."""

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    native_record_id: NonBlankStr


class NativeSourceFlagV1(FrozenModel):
    """One retained source-native marker used by closed method branches."""

    schema_version: Literal["1"] = "1"
    key: NonBlankStr
    value: NonBlankStr


class DailySourceObservationVersionV1(FrozenModel):
    """One immutable version of a generic daily source observation claim."""

    schema_version: Literal["1"] = "1"
    revision: RevisionEnvelopeV1
    source_key: ObservationSourceKeyV1
    source_record_locator: NonBlankStr
    source_record_hash: SHA256Hash
    contract_hash: SHA256Hash
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    session_date: date
    source_local_label: NonBlankStr
    source_timezone: NonBlankStr
    claimed_interval: TemporalIntervalClaimV1
    completion_time: TemporalBoundaryClaimV1
    fields: tuple[SourceFieldValueV1, ...]
    source_flags: tuple[NativeSourceFlagV1, ...]
    first_eligible_trade_time: TemporalBoundaryClaimV1 | None
    last_eligible_trade_time: TemporalBoundaryClaimV1 | None
    activity_claim: Literal[
        "qualifying_price_trade", "explicit_no_qualifying_price_trade", "unknown"
    ]
    any_trade_claim: Literal["reported", "explicit_none", "unknown"]

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[SourceFieldValueV1, ...]
    ) -> tuple[SourceFieldValueV1, ...]:
        names = tuple(item.field_name for item in fields)
        if len(set(names)) != len(names):
            raise ValueError("observation field names must be unique")
        return tuple(sorted(fields, key=lambda item: item.field_name))

    @field_validator("source_flags")
    @classmethod
    def canonicalize_source_flags(
        cls, flags: tuple[NativeSourceFlagV1, ...]
    ) -> tuple[NativeSourceFlagV1, ...]:
        keys = tuple(item.key for item in flags)
        if len(set(keys)) != len(keys):
            raise ValueError("observation source flag keys must be unique")
        return tuple(sorted(flags, key=lambda item: item.key))

    @model_validator(mode="after")
    def validate_payload_hash(self) -> Self:
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("observation payload hash mismatch")
        return self


class ObservationInventoryEntryV1(FrozenModel):
    """Exact source assertion/version/hash entry retained by coverage."""

    schema_version: Literal["1"] = "1"
    assertion_id: UUID7
    version_id: UUID7
    record_hash: SHA256Hash


class ObservationCoverageVersionV1(FrozenModel):
    """One source claim about exact observation and revision inventory coverage."""

    schema_version: Literal["1"] = "1"
    revision: RevisionEnvelopeV1
    source_id: NonBlankStr
    native_record_id: NonBlankStr
    contract_hash: SHA256Hash
    venue: ListingVenue
    listing_id: UUID7
    security_id: UUID7
    start_date: date
    end_date: date
    snapshot_identifier: NonBlankStr
    snapshot_as_of: TemporalBoundaryClaimV1
    covered_dataset_hashes: tuple[SHA256Hash, ...]
    covered_partition_hashes: tuple[SHA256Hash, ...]
    record_inventory: tuple[ObservationInventoryEntryV1, ...]
    methodology_artifact_hash: SHA256Hash
    omission_rule_hash: SHA256Hash
    status: Literal["expected_complete", "not_expected", "partial", "unknown"]
    exception_keys: tuple[NonBlankStr, ...]
    missing_artifact_hashes: tuple[SHA256Hash, ...]
    revision_history_completeness: Literal["complete", "current_only", "unknown"]

    @field_validator(
        "covered_dataset_hashes",
        "covered_partition_hashes",
        "missing_artifact_hashes",
    )
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes):
            raise ValueError("coverage hashes must be unique")
        return tuple(sorted(hashes))

    @field_validator("record_inventory")
    @classmethod
    def canonicalize_inventory(
        cls, entries: tuple[ObservationInventoryEntryV1, ...]
    ) -> tuple[ObservationInventoryEntryV1, ...]:
        identities = tuple((item.assertion_id, item.version_id) for item in entries)
        hashes = tuple(item.record_hash for item in entries)
        if len(set(identities)) != len(identities) or len(set(hashes)) != len(hashes):
            raise ValueError("coverage inventory entries must be unique")
        return tuple(
            sorted(
                entries, key=lambda item: (str(item.assertion_id), str(item.version_id))
            )
        )

    @field_validator("exception_keys")
    @classmethod
    def canonicalize_exceptions(
        cls, keys: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if len(set(keys)) != len(keys):
            raise ValueError("coverage exception keys must be unique")
        return tuple(sorted(keys))

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("coverage date interval cannot be reversed")
        if any(
            item.assertion_id == self.revision.logical_record_id
            or item.version_id == self.revision.record_version_id
            for item in self.record_inventory
        ):
            raise ValueError("coverage cannot inventory itself")
        if self.status == "expected_complete" and (
            not self.covered_dataset_hashes
            or not self.covered_partition_hashes
            or not self.record_inventory
            or self.exception_keys
            or self.missing_artifact_hashes
        ):
            raise ValueError(
                "expected-complete coverage requires an exact closed inventory"
            )
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("observation coverage payload hash mismatch")
        return self


type ObservationInputRecordV1 = (
    DailySourceObservationVersionV1 | ObservationCoverageVersionV1
)

REGULAR_SESSION_TRADE_BAR_PROFILE_ID = "regular-session-trade-bar-v1"
_REGULAR_SESSION_TRADE_BAR_PROFILE_SPEC = {
    "schema_version": "1",
    "profile_id": REGULAR_SESSION_TRADE_BAR_PROFILE_ID,
    "currency": "USD",
    "adjustment_basis": "unadjusted",
    "price_fields": ("open", "high", "low", "close"),
    "price_unit": "currency_per_share",
    "price_population": "one_nonempty_regular_execution_population",
    "price_selectors": ("first", "maximum", "minimum", "last"),
    "price_domain": "positive_finite_decimal",
    "price_inequality": "low<=min(open,close)<=max(open,close)<=high",
    "volume_field": "volume",
    "volume_unit": "shares",
    "volume_domain": "positive_finite_decimal",
    "volume_population_relation": (
        "equal",
        "price_subset_of_volume",
    ),
    "coverage": "exact_completed_realized_regular_session",
    "unknown_or_conflicting": "indeterminate",
    "prohibited_transforms": (
        "imputation",
        "forward_fill",
        "resampling",
        "zero_price_synthesis",
        "outlier_clipping",
    ),
}


def regular_session_trade_bar_profile_hash() -> str:
    """Return the semantic hash of the initial narrow M1d admission profile."""
    return content_hash(_REGULAR_SESSION_TRADE_BAR_PROFILE_SPEC)


class SourceFieldValueV1(FrozenModel):
    """One exact source field claim before research-profile admission."""

    schema_version: Literal["1"] = "1"
    field_name: NonBlankStr
    method_id: NonBlankStr
    native_text: str | None
    value: Decimal | None
    state: Literal["value", "null", "omitted", "sentinel", "unknown"]
    native_flag: str | None

    @field_validator("value", mode="before")
    @classmethod
    def require_exact_decimal(
        cls, value: object, info: ValidationInfo
    ) -> Decimal | None:
        if value is None:
            return None
        if info.mode == "json" and isinstance(value, str):
            try:
                parsed = Decimal(value)
            except (ArithmeticError, ValueError) as error:
                raise ValueError("value requires an exact decimal string") from error
            if parsed.is_finite():
                return parsed
        elif info.mode == "python" and isinstance(value, Decimal):
            if value.is_finite():
                return value
        raise ValueError("value requires an exact decimal string")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state in {"value", "sentinel"}:
            if self.value is None:
                raise ValueError("numeric field state requires a numeric value")
        elif self.value is not None:
            raise ValueError(f"{self.state} field state cannot carry a numeric value")
        return self
