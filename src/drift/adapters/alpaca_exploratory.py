"""Bounded Alpaca exploratory development bridge for the M2 exploratory lane.

This module is an operational data preparation utility. It executes strictly
outside the evaluator core, and the evaluator core never imports it. Its job is
to turn exact retained Alpaca REST response bytes into provider-neutral Drift
contracts through the layered pipeline of design spec section 21.1:

1. Retain exact native response bytes in private storage outside Git.
2. Generate an ``AcquisitionReceiptV1`` and a dataset manifest.
3. Map native payloads onto standard Drift source records.
4. Validate every mapped dataset through Drift public validators.
5. Execute the standard M1b/M1c/M1d selection and generation functions.
6. Reconstruct source-basis ``ExploratoryReconstructedSessionObservationV1``.
7. Emit an ``EvaluationInputBundleV1`` through the real builder.

Four layering prohibitions are executable rather than documentary. Each is a
real parameter on a real function, so a caller that asks for the prohibited
conversion is refused rather than quietly served:

* ``map_native_bar(..., target="derived_view")`` is refused. A
  ``DerivedObservationViewV1`` may only come from M1d normalization.
* ``map_calendar_day(..., target="realized_session")`` is refused. A scheduled
  calendar row can never mint realized session authority.
* ``map_cash_dividend(..., target="effect" | "settlement")`` is refused. Alpaca
  terms records map only as terms.
* ``build_bridge_admission(..., lane="promotion")`` is refused. This bridge is
  exploratory-only.

Epistemic scope. Alpaca publishes no historical provider vintage for its
derived bars, no realized session telemetry, and no halt telemetry, and its
corporate action mutation replay is truncated. Therefore:

* The session clock is built in ``scheduled_session_reconstruction`` mode from
  generated schedule rows, never from invented realized sessions.
* No ``DerivedObservationViewV1`` is produced at all. ``bind_observation_session``
  classifies an observation as bound only through realized open and close
  evidence, so forcing scheduled-only history through the M1d materializers
  would either fail honestly or fabricate realized history. The emitted bundle
  therefore carries reconstructions and no authentic decision or accounting
  views, and a downstream evaluation over it fails closed rather than trading
  on evidence that does not exist.
* Corporate actions map to ``CorporateActionTermsVersionV1`` only. No occurred
  effect and no delivered settlement is ever minted, so no portfolio cash or
  share mutation can be derived from an Alpaca terms record.

Nothing produced here is promotion-grade evidence, and nothing produced here can
be converted into promotion-grade evidence.
"""

import ast
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload, manifest_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import (
    AcquisitionCompleteness,
    AcquisitionExecutionContextV1,
    AcquisitionPlanV1,
    AcquisitionReceiptV1,
    AcquisitionReconciliationV1,
    ByteLayerKind,
    ByteObjectV1,
    ExpectedInventoryV1,
    ExpectedObjectV1,
    NativeByteGraphV1,
    ObservedObjectV1,
    OriginEvidenceV1,
    OriginStatus,
    PageReceiptV1,
    ProviderNativeLayerRuleV1,
    RequestIdentityV1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import FrozenModel
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    ValidationRunContextV1,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicDateFactV1,
    EconomicOccurrenceV1,
    EconomicSourceKeyV1,
    EconomicUnitBasisV1,
    PositiveRatioV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    TermsPayloadV1,
)
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_TRUNCATED_CA,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_reconstruction import (
    REQUIRED_RECONSTRUCTION_FIELDS,
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedSessionObservationV1,
    ExploratoryReconstructionPolicyV1,
    cohort_authorization_hash,
    exploratory_reconstruction_semantic_hash,
    reconstruction_policy_hash,
)
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV2,
    DatasetRoleV1,
    LicenseDescriptorV1,
    PartitionDescriptorV1,
    SourceDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import (
    ObservationOutcomeQueryV1,
    ObservationQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
    drift_source_inventory_hash,
    m1d_implementation_hash,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    IntervalPolicyV1,
    MethodBranchV1,
    NativeSourceFlagV1,
    ObservationContractV1,
    ObservationFieldMethodV1,
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
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.domain.sessions import (
    HistoricalBoundaryOffsetV1,
    HistoricalTimezoneMethodologyV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
    SessionInventoryEntryV1,
    SessionKeyV1,
    TimezoneInputV1,
    canonical_session_encoding_contract_hash,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.errors import DriftError
from drift.evaluator.bundles import (
    build_evaluation_input_bundle,
    validate_exploratory_admission,
)
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay
from drift.markets.economic_validation import (
    ECONOMIC_VALIDATION_PROFILE_ID,
    economic_role_contract,
    economic_role_schema,
    economic_validation_profile_hash,
    economic_validator_implementation_hash,
    validate_economic_dataset,
)
from drift.markets.observation_validation import (
    OBSERVATION_VALIDATION_PROFILE_ID,
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
    observation_role_contract,
    observation_role_schema,
    observation_validation_profile_hash,
    observation_validator_implementation_hash,
    validate_observation_dataset,
)
from drift.markets.session_generation import schedule_generation_algorithm_hash
from drift.markets.session_validation import (
    SESSION_VALIDATION_PROFILE_ID,
    session_role_contract,
    session_role_schema,
    session_validation_profile_hash,
    session_validator_implementation_hash,
    validate_session_dataset,
)
from drift.qualification.acquisition import (
    reconcile_acquisition,
    validate_secret_free_acquisition_payload,
    verify_acquisition_receipt,
)
from drift.serialization.canonical import canonical_json, content_hash

# --- identity of this bridge -------------------------------------------------

ALPACA_BAR_SOURCE_ID = "alpaca-historical-bars-v2"
ALPACA_CALENDAR_SOURCE_ID = "alpaca-market-calendar-v2"
ALPACA_ACTION_SOURCE_ID = "alpaca-corporate-actions-v1"
ALPACA_DATA_HOST = "data.alpaca.markets"
#: The calendar comes off Alpaca's *paper* trading API host. Alpaca was selected
#: as the free development source because paper account credentials exist, and
#: paper keys do not authenticate against the live brokerage host
#: ``api.alpaca.markets``. Nothing authorizes this bridge to hold or use live
#: brokerage credentials, so the live host is never named as an endpoint and
#: there is no switch that selects it. Alpaca publishes ``GET /v2/calendar``
#: with the paper host as a server of the same Trading API.
ALPACA_PAPER_TRADING_HOST = "paper-api.alpaca.markets"
ALPACA_BARS_ROUTE = "/v2/stocks/bars"
ALPACA_CALENDAR_ROUTE = "/v2/calendar"
ALPACA_ACTIONS_ROUTE = "/v1/corporate-actions"
BRIDGE_COLLECTOR_ID = "drift-alpaca-exploratory-bridge"
BRIDGE_COLLECTOR_VERSION = "1"
BRIDGE_PROVIDER_LEGAL_NAME = "Alpaca Securities LLC"
BRIDGE_LICENSE_REFERENCE = "alpaca-basic-free-development-tier"

#: Every limitation an Alpaca-backed exploratory admission must acknowledge.
ALPACA_EXPLORATORY_LIMITATIONS: tuple[str, ...] = tuple(
    sorted(
        (
            ALPACA_LIMITATION_ABSENT_HALTS,
            ALPACA_LIMITATION_BOUNDED_COHORT,
            ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
            ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
            ALPACA_LIMITATION_TRUNCATED_CA,
            ALPACA_LIMITATION_UNVERSIONED_BARS,
        )
    )
)

_UUID_NAMESPACE = "drift.adapters.alpaca_exploratory.v1"


def _policy_statement(
    policy_id: str,
    *,
    source_id: str,
    subject: str,
    publication: Literal["published", "partially_published", "not_published"],
    statement: str,
    not_established: tuple[str, ...],
) -> dict[str, Any]:
    """State one named rule, including the part of it that is not known.

    A hash over an empty document attests nothing. Every policy hash this
    bridge emits therefore addresses a distinct document that says what Alpaca
    publishes about that rule, what this bridge relies on, and what remains
    unestablished. Where ``publication`` is ``"not_published"`` the matching
    disposition elsewhere in this module is ``"unknown"``.
    """
    return {
        "kind": "alpaca-exploratory-policy-statement",
        "schema_version": "1",
        "policy_id": policy_id,
        "source_id": source_id,
        "subject": subject,
        "provider_publication": publication,
        "statement": statement,
        "not_established": list(not_established),
    }


_POLICY_DOCUMENTS: dict[str, dict[str, Any]] = {
    str(document["policy_id"]): document
    for document in (
        _policy_statement(
            "alpaca-trade-ordering",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="ordering of eligible trades inside one 1Day SIP bar",
            publication="partially_published",
            statement=(
                "Alpaca documents that a 1Day bar aggregates consolidated SIP "
                "trades over the session, so the bridge records execution time "
                "then source sequence as the ordering it relies on for the "
                "first and last selectors."
            ),
            not_established=(
                "the tie-break applied to trades sharing an execution timestamp",
                "the treatment of prints reported out of execution sequence",
            ),
        ),
        _policy_statement(
            "alpaca-adjustment-basis",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="price adjustment basis of the acquired bars",
            publication="published",
            statement=(
                "The bridge requests adjustment=raw, which Alpaca documents as "
                "unadjusted prices, so every mapped field carries the "
                "unadjusted basis and no split or dividend adjustment is "
                "applied anywhere in this module."
            ),
            not_established=(
                "whether Alpaca retroactively restates raw bars after a "
                "corporate action",
            ),
        ),
        _policy_statement(
            "alpaca-sale-condition",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="sale conditions included in the aggregated trade population",
            publication="not_published",
            statement=(
                "Alpaca publishes no sale-condition eligibility table for its "
                "1Day SIP bars, so this bridge asserts no condition filter and "
                "records the population as reported by the provider."
            ),
            not_established=(
                "which SIP sale conditions are included in the aggregation",
                "whether odd lots contribute to price or to volume",
                "whether opening and closing auction prints are included",
            ),
        ),
        _policy_statement(
            "alpaca-correction-cancellation",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="treatment of trade corrections and cancellations",
            publication="not_published",
            statement=(
                "Alpaca publishes no correction or cancellation replay rule for "
                "its derived bars and rejects point-in-time requests, so the "
                "bridge treats an acquired bar as a current snapshot and "
                "asserts no correction semantics."
            ),
            not_established=(
                "whether a corrected print restates an already published bar",
                "the horizon over which a bar can still change",
            ),
        ),
        _policy_statement(
            "alpaca-trade-population",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="identity of the aggregated trade population",
            publication="partially_published",
            statement=(
                "Alpaca documents the feed identity as the consolidated SIP "
                "tape and the session scope of a 1Day bar as the regular "
                "session, which is what the population records."
            ),
            not_established=(
                "the venue-level composition of the consolidated tape as "
                "aggregated by Alpaca",
                "the auction-print disposition of the population",
            ),
        ),
        _policy_statement(
            "alpaca-volume-relationship",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="relationship between the priced and the counted population",
            publication="published",
            statement=(
                "Price fields and the volume field of one Alpaca bar are "
                "printed on the same row from the same aggregation, so the "
                "priced and counted populations are the same population."
            ),
            not_established=(
                "whether Alpaca excludes from volume any print it excludes from price",
            ),
        ),
        _policy_statement(
            "alpaca-interval-endpoints",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="interval endpoint and auction-event treatment",
            publication="not_published",
            statement=(
                "Alpaca publishes no auction-inclusion methodology for 1Day SIP "
                "bars, so the auction-event disposition recorded by this bridge "
                "is unknown rather than included."
            ),
            not_established=(
                "whether the opening auction print is inside the bar",
                "whether the closing auction print is inside the bar",
            ),
        ),
        _policy_statement(
            "alpaca-revision-policy",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="retention of source corrections",
            publication="published",
            statement=(
                "Alpaca overwrites derived bars in place and rejects "
                "point-in-time requests, so the only truthful revision policy "
                "is a current snapshot with no retained correction history."
            ),
            not_established=("the horizon over which a snapshot can change",),
        ),
        _policy_statement(
            "alpaca-row-emission",
            source_id=ALPACA_BAR_SOURCE_ID,
            subject="when the provider emits a row at all",
            publication="partially_published",
            statement=(
                "Alpaca returns a bar only for a session in which qualifying "
                "activity was aggregated, and emits no marker row for a "
                "session it omits."
            ),
            not_established=(
                "whether an omitted session means no activity or no data",
            ),
        ),
        _policy_statement(
            "alpaca-acquisition-methodology",
            source_id=BRIDGE_COLLECTOR_ID,
            subject="how this bridge acquires and retains provider bytes",
            publication="published",
            statement=(
                "One closed GET per declared endpoint over the declared bounded "
                "window and cohort, retained byte for byte in private "
                "content-addressed storage outside Git, with the measured "
                "response status, content type, and host carried into the "
                "receipt and no value invented where no measurement exists."
            ),
            not_established=(
                "any provider-side checksum, signature, or manifest, none of "
                "which Alpaca returns",
            ),
        ),
        _policy_statement(
            "alpaca-license-terms",
            source_id=BRIDGE_COLLECTOR_ID,
            subject="the licence under which the bytes were acquired",
            publication="partially_published",
            statement=(
                f"The bytes were acquired under the {BRIDGE_LICENSE_REFERENCE} "
                f"tier offered by {BRIDGE_PROVIDER_LEGAL_NAME}. This document "
                "is the licence evidence the manifests reference; the licence "
                "text itself is not retained by this bridge and no operational "
                "redistribution right is concluded from it."
            ),
            not_established=(
                "the exact licence text and version in force at acquisition",
                "any right to redistribute the retained provider bytes",
            ),
        ),
    )
}

BARS_OBJECT_KEY = "alpaca-historical-bars"
CALENDAR_OBJECT_KEY = "alpaca-market-calendar"
ACTIONS_OBJECT_KEY = "alpaca-corporate-actions"

_POPULATION_ID = "alpaca-sip-consolidated-regular-trades"
REGULAR_LOCAL_CLOSE = "16:00:00"
_FIELD_MEANINGS: dict[str, str] = {
    "open": "first_trade_price",
    "high": "maximum_trade_price",
    "low": "minimum_trade_price",
    "close": "last_trade_price",
    "volume": "share_volume",
}
_FIELD_SELECTORS: dict[str, str] = {
    "open": "first",
    "high": "maximum",
    "low": "minimum",
    "close": "last",
    "volume": "sum",
}

type ObservationTarget = Literal["source_observation", "derived_view"]
type SessionTarget = Literal["scheduled_session", "realized_session"]
type EconomicTarget = Literal["terms", "effect", "settlement"]
type BridgeLane = Literal["exploratory", "promotion"]


# --- errors -------------------------------------------------------------------


class AlpacaBridgeProhibitedError(DriftError, ValueError):
    """Raised when a caller asks the bridge for a prohibited layering jump."""


class AlpacaBridgeIncompleteError(DriftError, ValueError):
    """Raised when acquired Alpaca evidence is not closed enough to map."""


# --- native payloads ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlpacaNativeBar:
    """One exact daily bar as the provider printed it."""

    symbol: str
    session_date: date
    native_timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class AlpacaNativeCalendarDay:
    """One exact scheduled calendar row as the provider printed it.

    A calendar row is a schedule claim. It is never realized session evidence.
    """

    session_date: date
    local_open: str
    local_close: str


@dataclass(frozen=True, slots=True)
class AlpacaNativeCashDividend:
    """One exact cash dividend terms row as the provider printed it."""

    native_id: str
    symbol: str
    rate: Decimal
    rate_text: str
    ex_date: date
    record_date: date
    payable_date: date


@dataclass(frozen=True, slots=True)
class AlpacaNativePayloads:
    """The exact retained response bytes for one bounded acquisition."""

    bars: bytes
    calendar: bytes
    corporate_actions: bytes


def _strict_document(data: bytes) -> Any:
    """Parse native JSON without ever materializing a binary float."""
    return json.loads(data.decode("utf-8"), parse_float=Decimal)


def _exact_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise AlpacaBridgeIncompleteError(
            f"{label} must be an exact decimal, got a boolean"
        )
    if isinstance(value, float):
        raise AlpacaBridgeIncompleteError(
            f"{label} must be an exact decimal, got a binary float"
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise AlpacaBridgeIncompleteError(f"{label} must be a finite decimal")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except ArithmeticError as error:
            raise AlpacaBridgeIncompleteError(
                f"{label} must be an exact decimal spelling"
            ) from error
        if not parsed.is_finite():
            raise AlpacaBridgeIncompleteError(f"{label} must be a finite decimal")
        return parsed
    raise AlpacaBridgeIncompleteError(f"{label} must be an exact decimal")


def _require_closed_page(document: Mapping[str, Any], label: str) -> None:
    """Refuse a truncated response, so closed-world claims stay supportable."""
    token = document.get("next_page_token")
    if token is not None:
        raise AlpacaBridgeIncompleteError(
            f"{label} response is paginated and incomplete"
        )


def parse_alpaca_bars(data: bytes) -> tuple[AlpacaNativeBar, ...]:
    """Parse an exact ``/v2/stocks/bars`` response into native bar rows."""
    document = _strict_document(data)
    if not isinstance(document, dict):
        raise AlpacaBridgeIncompleteError("bars response must be a JSON object")
    _require_closed_page(document, "bars")
    grouped = document.get("bars")
    if not isinstance(grouped, dict):
        raise AlpacaBridgeIncompleteError("bars response must carry a bars object")
    rows: list[AlpacaNativeBar] = []
    for symbol, entries in grouped.items():
        if not isinstance(symbol, str) or not isinstance(entries, list):
            raise AlpacaBridgeIncompleteError("bars response has an unexpected shape")
        for entry in entries:
            if not isinstance(entry, dict):
                raise AlpacaBridgeIncompleteError("bar row must be a JSON object")
            stamp = entry.get("t")
            count = entry.get("n")
            if not isinstance(stamp, str) or isinstance(count, bool):
                raise AlpacaBridgeIncompleteError("bar row is missing its identity")
            if not isinstance(count, int):
                raise AlpacaBridgeIncompleteError("bar trade count must be an integer")
            rows.append(
                AlpacaNativeBar(
                    symbol=symbol,
                    session_date=_session_date_from_stamp(stamp),
                    native_timestamp=stamp,
                    open=_exact_decimal(entry.get("o"), "bar open"),
                    high=_exact_decimal(entry.get("h"), "bar high"),
                    low=_exact_decimal(entry.get("l"), "bar low"),
                    close=_exact_decimal(entry.get("c"), "bar close"),
                    volume=_exact_decimal(entry.get("v"), "bar volume"),
                    trade_count=count,
                )
            )
    return tuple(sorted(rows, key=lambda row: (row.symbol, row.session_date)))


def _session_date_from_stamp(stamp: str) -> date:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
    except ValueError as error:
        raise AlpacaBridgeIncompleteError(
            f"bar timestamp is not an ISO instant: {stamp}"
        ) from error


def parse_alpaca_calendar(data: bytes) -> tuple[AlpacaNativeCalendarDay, ...]:
    """Parse an exact ``/v2/calendar`` response into native schedule rows."""
    document = _strict_document(data)
    if not isinstance(document, list):
        raise AlpacaBridgeIncompleteError("calendar response must be a JSON array")
    rows: list[AlpacaNativeCalendarDay] = []
    for entry in document:
        if not isinstance(entry, dict):
            raise AlpacaBridgeIncompleteError("calendar row must be a JSON object")
        day = entry.get("date")
        opened = entry.get("open")
        closed = entry.get("close")
        if (
            not isinstance(day, str)
            or not isinstance(opened, str)
            or not isinstance(closed, str)
        ):
            raise AlpacaBridgeIncompleteError("calendar row is missing its boundaries")
        rows.append(
            AlpacaNativeCalendarDay(
                session_date=date.fromisoformat(day),
                local_open=opened,
                local_close=closed,
            )
        )
    ordered = tuple(sorted(rows, key=lambda row: row.session_date))
    dates = tuple(row.session_date for row in ordered)
    if len(set(dates)) != len(dates):
        raise AlpacaBridgeIncompleteError("calendar response repeats a session date")
    return ordered


def parse_alpaca_cash_dividends(data: bytes) -> tuple[AlpacaNativeCashDividend, ...]:
    """Parse an exact ``/v1/corporate-actions`` response into terms rows."""
    document = _strict_document(data)
    if not isinstance(document, dict):
        raise AlpacaBridgeIncompleteError("actions response must be a JSON object")
    _require_closed_page(document, "corporate actions")
    grouped = document.get("corporate_actions")
    if not isinstance(grouped, dict):
        raise AlpacaBridgeIncompleteError("actions response must carry its actions")
    entries = grouped.get("cash_dividends", [])
    if not isinstance(entries, list):
        raise AlpacaBridgeIncompleteError("cash dividends must be a JSON array")
    rows: list[AlpacaNativeCashDividend] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AlpacaBridgeIncompleteError("dividend row must be a JSON object")
        native_id = entry.get("corporate_action_id")
        symbol = entry.get("symbol")
        if not isinstance(native_id, str) or not isinstance(symbol, str):
            raise AlpacaBridgeIncompleteError("dividend row is missing its identity")
        rate = _exact_decimal(entry.get("rate"), "dividend rate")
        rows.append(
            AlpacaNativeCashDividend(
                native_id=native_id,
                symbol=symbol,
                rate=rate,
                rate_text=_canonical_cash(rate),
                ex_date=_required_date(entry, "ex_date"),
                record_date=_required_date(entry, "record_date"),
                payable_date=_required_date(entry, "payable_date"),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.symbol, row.native_id)))


def _required_date(entry: Mapping[str, Any], name: str) -> date:
    value = entry.get(name)
    if not isinstance(value, str):
        raise AlpacaBridgeIncompleteError(f"dividend row is missing {name}")
    return date.fromisoformat(value)


def _canonical_cash(value: Decimal) -> str:
    """Render an exact nonnegative decimal in the canonical M1c cash spelling."""
    if value < Decimal("0"):
        raise AlpacaBridgeIncompleteError("cash amounts cannot be negative")
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# --- declared intake scope ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlpacaCohortMember:
    """One predeclared exploratory subject bound to Drift internal identity.

    The caller supplies the identity binding. The bridge never projects a
    current Alpaca symbol backward onto a historical universe.
    """

    symbol: str
    security_id: UUID
    listing_id: UUID
    venue: ListingVenue


@dataclass(frozen=True, slots=True)
class AlpacaTimezoneEvidence:
    """Externally attested timezone reconstruction input for schedule generation."""

    timezone_identifier: str
    source_timezone_label: str
    tzif_bytes: bytes
    tzdb_release: str
    reconstruction_observed_at: datetime


@dataclass(frozen=True, slots=True)
class AlpacaReconstructionLineage:
    """Exact retained producer lineage for deterministic schedule generation."""

    producer_source: bytes
    producer_package: bytes
    lockfile: bytes
    python_identity: str


@dataclass(frozen=True, slots=True)
class AlpacaOriginObservation:
    """What the transport actually measured about one provider response.

    Every field here is a measurement, not a declaration. The bridge itself
    opens no connection, so it cannot measure any of this; the caller that did
    the fetching supplies it, and where it supplies nothing the receipt claims
    nothing.

    A measurement is bound to the exact body it was taken over by that body's
    SHA-256 and byte size. The receipt certifies an origin only for the very
    bytes this names, so a measurement of one response can never be attached
    to different bytes, not even bytes that differ by one.
    """

    object_key: str
    request_host: str
    #: The verified TLS peer identity, or ``None`` when the hop was not TLS.
    tls_endpoint_identity: str | None
    http_status: int
    content_type: str | None
    #: The instant the response body finished being read.
    observed_at: datetime
    #: SHA-256 of the exact response body this measurement was taken over.
    body_sha256: str
    #: Byte length of that exact response body.
    body_byte_size: int

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise AlpacaBridgeIncompleteError(
                "a measured acquisition instant must carry a UTC offset"
            )
        if len(self.body_sha256) != 64 or not set(self.body_sha256) <= set(
            "0123456789abcdef"
        ):
            raise AlpacaBridgeIncompleteError(
                "a measured origin must name the lowercase SHA-256 of the exact "
                "body it measured"
            )
        if type(self.body_byte_size) is not int or self.body_byte_size < 0:
            raise AlpacaBridgeIncompleteError(
                "a measured origin must name the byte size of the exact body it "
                "measured"
            )

    def measured(self, data: bytes) -> bool:
        """Return whether this measurement was taken over exactly ``data``."""
        return (
            sha256(data).hexdigest() == self.body_sha256
            and len(data) == self.body_byte_size
        )


@dataclass(frozen=True, slots=True)
class AlpacaIntakeRequest:
    """The complete, credential-free declaration of one bounded intake run."""

    cohort_id: str
    cohort_version: str
    members: tuple[AlpacaCohortMember, ...]
    mic: str
    start_date: date
    end_date: date
    plan_frozen_at: datetime
    request_start: datetime
    request_end: datetime
    evidence_vintage_cutoff: datetime
    timezone_evidence: AlpacaTimezoneEvidence
    lineage: AlpacaReconstructionLineage
    #: Externally attested UTC offset in seconds per local date and boundary.
    boundary_offsets: Mapping[tuple[date, str], int]
    #: Measured origin evidence per expected object key, supplied by whatever
    #: performed the transfer. ``None`` means nothing was measured, which the
    #: receipt reports as an unverified origin rather than papering over.
    origin_observations: Mapping[str, AlpacaOriginObservation] | None = None

    def __post_init__(self) -> None:
        if not self.members:
            raise AlpacaBridgeIncompleteError("intake requires a nonempty cohort")
        symbols = tuple(member.symbol for member in self.members)
        if len(set(symbols)) != len(symbols):
            raise AlpacaBridgeIncompleteError("cohort symbols must be unique")
        securities = tuple(member.security_id for member in self.members)
        if len(set(securities)) != len(securities):
            raise AlpacaBridgeIncompleteError("cohort securities must be unique")
        listings = tuple(member.listing_id for member in self.members)
        if len(set(listings)) != len(listings):
            raise AlpacaBridgeIncompleteError("cohort listings must be unique")
        if self.start_date > self.end_date:
            raise AlpacaBridgeIncompleteError("intake window cannot be reversed")
        # One calendar response describes one venue. A cohort listed somewhere
        # else would silently borrow another venue's session boundaries, so the
        # declaration has to agree with itself before any byte is mapped.
        foreign = tuple(
            sorted(
                {
                    member.venue.value
                    for member in self.members
                    if member.venue.value != self.mic
                }
            )
        )
        if foreign:
            raise AlpacaBridgeIncompleteError(
                f"cohort listings on {foreign} cannot use the {self.mic} calendar"
            )
        if self.plan_frozen_at > self.request_start:
            raise AlpacaBridgeIncompleteError(
                "the acquisition plan must be frozen before the request starts"
            )
        if self.request_end < self.request_start:
            raise AlpacaBridgeIncompleteError("request end cannot precede its start")
        if self.evidence_vintage_cutoff < self.request_end:
            raise AlpacaBridgeIncompleteError(
                "the retrospective evidence cutoff cannot precede acquisition"
            )
        self._validate_origin_observations()

    def _validate_origin_observations(self) -> None:
        """Bind every measured origin to the declared request it belongs to."""
        if self.origin_observations is None:
            return
        expected = {key for key, _host, _route in _OBJECT_ENDPOINTS}
        if set(self.origin_observations) != expected:
            raise AlpacaBridgeIncompleteError(
                "measured origin evidence must cover exactly the declared "
                f"endpoints {tuple(sorted(expected))}"
            )
        for key, observation in self.origin_observations.items():
            if observation.object_key != key:
                raise AlpacaBridgeIncompleteError(
                    f"origin evidence filed under {key} describes "
                    f"{observation.object_key}"
                )
            if observation.request_host != _OBJECT_HOSTS[key]:
                raise AlpacaBridgeIncompleteError(
                    f"{key} was measured against {observation.request_host} but "
                    f"is declared to come from {_OBJECT_HOSTS[key]}"
                )
            if observation.http_status != 200:
                raise AlpacaBridgeIncompleteError(
                    f"{key} returned HTTP {observation.http_status}, which is "
                    "not a complete provider response"
                )
            # The acquisition window has to contain the instants that were
            # actually measured, so it cannot be backdated or forward-dated
            # away from the acquisition it describes.
            if not (self.request_start <= observation.observed_at <= self.request_end):
                raise AlpacaBridgeIncompleteError(
                    f"{key} was observed at "
                    f"{observation.observed_at.isoformat()}, outside the "
                    f"declared acquisition window "
                    f"{self.request_start.isoformat()} to "
                    f"{self.request_end.isoformat()}"
                )

    def observation_for(self, key: str) -> AlpacaOriginObservation | None:
        """Return the measured origin evidence for one expected object key."""
        if self.origin_observations is None:
            return None
        return self.origin_observations.get(key)

    @property
    def acquired_at(self) -> datetime:
        """The instant by which every provider byte had been observed.

        This is the declared end of the acquisition window, and it is only
        meaningful because ``__post_init__`` refuses a window that does not
        contain every measured ``observed_at``. Availability, the BOUNDED
        completion window, and every ``created_at`` in the receipt are anchored
        to it, so a run that supplies no measurement anchors nothing and is
        refused downstream as an unverified origin.
        """
        return self.request_end

    def member_for(self, symbol: str) -> AlpacaCohortMember:
        """Return the declared cohort member owning one provider symbol."""
        for member in self.members:
            if member.symbol == symbol:
                return member
        raise AlpacaBridgeIncompleteError(
            f"symbol {symbol} is outside the declared bounded cohort"
        )


# --- deterministic identity and artifact helpers ---------------------------------


def _derived_uuid7(*parts: str) -> UUID:
    """Derive a stable RFC 4122 version 7 identifier from exact inputs."""
    digest = sha256("\u0000".join((_UUID_NAMESPACE, *parts)).encode("utf-8")).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _verified(data: bytes) -> VerifiedArtifactBytes:
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )


def _reference(digest: str, seed: str, kind: ArtifactKind) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=_derived_uuid7("artifact", seed, digest),
        kind=kind,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _policy_bytes(policy_id: str) -> bytes:
    """Return the exact canonical bytes of one named rule document."""
    return canonical_json(_POLICY_DOCUMENTS[policy_id])


def _policy_hash(policy_id: str) -> str:
    """Return the content address of one named rule document.

    Every policy slot in this module resolves its hash through here, so two
    slots share a hash only when they genuinely share a document.
    """
    return sha256(_policy_bytes(policy_id)).hexdigest()


def _policy_artifacts() -> dict[str, VerifiedArtifactBytes]:
    """Return every rule document keyed by its content address."""
    artifacts: dict[str, VerifiedArtifactBytes] = {}
    for policy_id in _POLICY_DOCUMENTS:
        artifact = _verified(_policy_bytes(policy_id))
        artifacts[artifact.content_hash] = artifact
    return artifacts


def _license_artifact() -> VerifiedArtifactBytes:
    """Return the licence evidence document, which is never market data."""
    return _verified(_policy_bytes("alpaca-license-terms"))


def _license_reference() -> ArtifactReference:
    """Reference the licence document rather than the acquired provider bytes."""
    return _reference(
        _license_artifact().content_hash, "license-terms", ArtifactKind.OTHER
    )


def _channel() -> AvailabilityChannelV1:
    return AvailabilityChannelV1(
        kind=ChannelKind.PUBLIC, identifier="alpaca-rest", version="1"
    )


def _observed_availability(
    observed: datetime, digest: str, seed: str
) -> AvailabilityEvidenceV1:
    """Availability is exactly when Drift observed the bytes, never earlier.

    Alpaca publishes no historical assertion vintage, so the only defensible
    availability claim is the acquisition instant. That is the whole content of
    ``ALPACA_LIMITATION_UNVERSIONED_BARS``.
    """
    return AvailabilityEvidenceV1(
        channel=_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=observed,
        upper_bound=observed,
        precision=SourcePrecision.SECOND,
        source_time_label=observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=_reference(digest, seed, ArtifactKind.OTHER),
        rule_derivation=None,
    )


def _exact_boundary(value: datetime, digest: str, seed: str) -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=_reference(digest, seed, ArtifactKind.OTHER),
    )


def _bounded_boundary(
    lower: datetime, upper: datetime, label: str, digest: str, seed: str
) -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=lower,
        upper_bound=upper,
        source_precision=SourcePrecision.INTERVAL,
        source_time_label=label,
        source_timezone=None,
        evidence_reference=_reference(digest, seed, ArtifactKind.OTHER),
    )


def _date_boundary(value: date, digest: str, seed: str) -> TemporalBoundaryClaimV1:
    lower = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return _bounded_boundary(
        lower, lower + timedelta(days=1), value.isoformat(), digest, seed
    )


def _revision(
    *,
    logical_seed: str,
    version_seed: str,
    availability: AvailabilityEvidenceV1,
    source_digest: str,
) -> RevisionEnvelopeV1:
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=_derived_uuid7("logical", logical_seed),
        record_version_id=_derived_uuid7("version", version_seed),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(availability,),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=_reference(source_digest, logical_seed, ArtifactKind.OTHER),
        payload_hash="0" * 64,
    )


def _seal[T: FrozenModel](kind: type[T], values: dict[str, object]) -> T:
    """Attach the assertion payload hash and revalidate one source record."""
    envelope = values["revision"]
    assert isinstance(envelope, RevisionEnvelopeV1)
    provisional = kind.model_construct(_fields_set=None, **cast(Any, values))
    values["revision"] = envelope.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return kind.model_validate(values)


# --- step 1: retain exact native bytes in private storage outside Git -------------


@dataclass(frozen=True, slots=True)
class RetainedNativeBytes:
    """Content-addressed retention of the exact provider response bytes.

    The mapping validates itself. A content-addressed store whose keys are not
    checked against its values is not content-addressed, and a receipt minted
    over such a mapping would claim a digest for bytes that do not hash to it.
    """

    root: Path
    bars_hash: str
    calendar_hash: str
    corporate_actions_hash: str
    artifacts: Mapping[str, VerifiedArtifactBytes]

    def __post_init__(self) -> None:
        for digest, artifact in self.artifacts.items():
            computed = sha256(artifact.data).hexdigest()
            if computed != digest or artifact.content_hash != digest:
                raise AlpacaBridgeIncompleteError(
                    "a retained object is filed under a digest it does not "
                    f"hash to: key {digest}, content {computed}"
                )
            if artifact.byte_size != len(artifact.data):
                raise AlpacaBridgeIncompleteError(
                    f"retained object {digest} declares the wrong byte size"
                )
        declared = (self.bars_hash, self.calendar_hash, self.corporate_actions_hash)
        missing = tuple(sorted(set(declared) - set(self.artifacts)))
        if missing:
            raise AlpacaBridgeIncompleteError(
                f"retained objects are missing for declared digests {missing}"
            )
        # Three distinct endpoints returning byte-identical bodies is a broken
        # acquisition, and it would also leave the receipt claiming three
        # observed objects over a two-object byte graph.
        if len(set(declared)) != len(declared):
            raise AlpacaBridgeIncompleteError(
                "two declared Alpaca endpoints returned byte-identical bodies, "
                "so the acquisition cannot be reconciled object by object"
            )

    @property
    def ordered_hashes(self) -> tuple[str, ...]:
        """The retained object digests in canonical order."""
        return tuple(sorted(self.artifacts))


def _refuse_versioned_root(root: Path) -> None:
    """Refuse any retention root inside a Git working tree.

    Native provider bytes are private licensed content. Writing them anywhere a
    Git tree can reach them is the failure this guard exists to prevent, so the
    check is on the resolved path and every ancestor rather than on gitignore.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            raise AlpacaBridgeProhibitedError(
                "native Alpaca bytes must be retained outside Git, but "
                f"{root} lies inside the working tree rooted at {candidate}"
            )


def _private_directory(resolved_root: Path, *parts: str) -> Path:
    """Create one owner-only directory chain under the private retention root."""
    directory = resolved_root.joinpath(*parts)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # ``Path.mkdir(parents=True, mode=...)`` applies the mode to the leaf only
    # and creates every parent at the default umask, which left the private
    # root itself group and world listable.
    for depth in range(len(parts) + 1):
        os.chmod(resolved_root.joinpath(*parts[:depth]), 0o700)
    return directory


def _write_private_object(directory: Path, data: bytes) -> str:
    """Write one owner-only object under its own SHA-256, or verify it is there."""
    digest = sha256(data).hexdigest()
    target = directory / digest
    if target.exists():
        # A half-written object from an interrupted run would otherwise be
        # trusted forever purely because its path already exists.
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise AlpacaBridgeIncompleteError(
                f"a retained private object does not match its content address: "
                f"{digest}"
            )
    else:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return digest


def retain_native_bytes(
    root: Path, payloads: AlpacaNativePayloads
) -> RetainedNativeBytes:
    """Write the exact response bytes into private content-addressed storage."""
    if not root.is_absolute():
        raise AlpacaBridgeProhibitedError("private retention root must be absolute")
    resolved = root.resolve()
    _refuse_versioned_root(resolved)
    objects = _private_directory(resolved, "objects", "sha256")
    artifacts: dict[str, VerifiedArtifactBytes] = {}
    for data in (payloads.bars, payloads.calendar, payloads.corporate_actions):
        artifact = _verified(data)
        _write_private_object(objects, data)
        artifacts[artifact.content_hash] = artifact
    return RetainedNativeBytes(
        root=resolved,
        bars_hash=sha256(payloads.bars).hexdigest(),
        calendar_hash=sha256(payloads.calendar).hexdigest(),
        corporate_actions_hash=sha256(payloads.corporate_actions).hexdigest(),
        artifacts=artifacts,
    )


# --- step 1b: retain what was measured, bound to the bytes it measured -------------

#: Where measured origin records live under the private retention root.
ORIGIN_RECORD_DIRECTORY = "origins"
ORIGIN_RECORD_SCHEMA_VERSION = "1"
_ORIGIN_RECORD_KIND = "drift-alpaca-measured-origin"
_ORIGIN_RECORD_FIELDS = frozenset(
    {
        "body_byte_size",
        "body_sha256",
        "content_type",
        "http_status",
        "kind",
        "object_key",
        "observed_at",
        "request_host",
        "schema_version",
        "tls_endpoint_identity",
    }
)


def _retained_body(retained: RetainedNativeBytes, key: str) -> bytes:
    """Return the exact retained bytes filed under one expected object key."""
    digests = {
        BARS_OBJECT_KEY: retained.bars_hash,
        CALENDAR_OBJECT_KEY: retained.calendar_hash,
        ACTIONS_OBJECT_KEY: retained.corporate_actions_hash,
    }
    return retained.artifacts[digests[key]].data


def _origin_record_bytes(observation: AlpacaOriginObservation) -> bytes:
    """Encode one measured origin as the canonical bytes of its record."""
    document = {
        "body_byte_size": observation.body_byte_size,
        "body_sha256": observation.body_sha256,
        "content_type": observation.content_type,
        "http_status": observation.http_status,
        "kind": _ORIGIN_RECORD_KIND,
        "object_key": observation.object_key,
        "observed_at": observation.observed_at.astimezone(UTC).isoformat(),
        "request_host": observation.request_host,
        "schema_version": ORIGIN_RECORD_SCHEMA_VERSION,
        "tls_endpoint_identity": observation.tls_endpoint_identity,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")


def _parse_origin_record(data: bytes) -> AlpacaOriginObservation | None:
    """Decode one origin record, or ``None`` for anything but a canonical one."""
    try:
        document = json.loads(data.decode("ascii"))
    except UnicodeDecodeError, ValueError:
        return None
    if not isinstance(document, dict) or set(document) != _ORIGIN_RECORD_FIELDS:
        return None
    if (
        document["kind"] != _ORIGIN_RECORD_KIND
        or document["schema_version"] != ORIGIN_RECORD_SCHEMA_VERSION
    ):
        return None
    texts = ("object_key", "body_sha256", "request_host", "observed_at")
    optional_texts = ("tls_endpoint_identity", "content_type")
    integers = ("http_status", "body_byte_size")
    if (
        not all(isinstance(document[name], str) for name in texts)
        or not all(
            document[name] is None or isinstance(document[name], str)
            for name in optional_texts
        )
        or not all(type(document[name]) is int for name in integers)
    ):
        return None
    try:
        observation = AlpacaOriginObservation(
            object_key=document["object_key"],
            request_host=document["request_host"],
            tls_endpoint_identity=document["tls_endpoint_identity"],
            http_status=document["http_status"],
            content_type=document["content_type"],
            observed_at=datetime.fromisoformat(document["observed_at"]),
            body_sha256=document["body_sha256"],
            body_byte_size=document["body_byte_size"],
        )
    except ValueError:
        return None
    # Only the exact bytes this bridge writes are a record. Anything else,
    # however equivalent, was written by something other than this bridge.
    if _origin_record_bytes(observation) != data:
        return None
    return observation


def retain_origin_observations(
    retained: RetainedNativeBytes,
    observations: Mapping[str, AlpacaOriginObservation],
) -> tuple[str, ...]:
    """Persist what an online acquisition measured, beside the bytes it measured.

    Each observation becomes one content-addressed record in the same private
    retention store as the bytes, owner-only like them, carrying the SHA-256
    and byte size of the exact body it was taken over. An offline replay can
    later certify an origin only by reading one of these records back and
    finding that it names the very bytes being replayed.

    Only a caller that performed the transfer should call this, and it refuses
    a measurement of any bytes other than the ones retained for that key.
    Returns the record digests in object key order.
    """
    directory = _private_directory(retained.root, ORIGIN_RECORD_DIRECTORY, "sha256")
    digests: list[str] = []
    for key in sorted(observations):
        observation = observations[key]
        if observation.object_key != key:
            raise AlpacaBridgeIncompleteError(
                f"origin evidence filed under {key} describes {observation.object_key}"
            )
        if not observation.measured(_retained_body(retained, key)):
            raise AlpacaBridgeIncompleteError(
                f"refusing to retain an origin measured over bytes other than the "
                f"ones retained for {key}"
            )
        digests.append(
            _write_private_object(directory, _origin_record_bytes(observation))
        )
    return tuple(digests)


def load_retained_origin_observations(
    retained: RetainedNativeBytes,
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, AlpacaOriginObservation]:
    """Read back the measured origins that bind to exactly these retained bytes.

    A record is used only if it is content addressed under its own SHA-256,
    decodes to exactly the canonical bytes this bridge writes, names one of the
    three expected object keys, names the SHA-256 and byte size of exactly the
    bytes retained for that key, and was measured inside the declared
    acquisition window. Everything else is ignored, so its object stays
    unmeasured: no record, a record that does not parse, a record for other
    bytes, even bytes one byte apart, and any free-standing file beside the
    bytes, which this function never reads. Where several records bind one
    object the latest measurement wins, then the lowest record digest.

    Residual trust, stated plainly: the store is exactly as trustworthy as the
    retained bytes themselves. An operator with write access who forges both
    the bytes and a matching record defeats this, as they could forge the
    bytes alone; what this closes is certifying bytes nothing ever measured.
    """
    directory = retained.root / ORIGIN_RECORD_DIRECTORY / "sha256"
    if directory.is_symlink() or not directory.is_dir():
        return {}
    bodies = {key: _retained_body(retained, key) for key, _, _ in _OBJECT_ENDPOINTS}
    chosen: dict[str, tuple[datetime, str, AlpacaOriginObservation]] = {}
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if sha256(data).hexdigest() != path.name:
            continue
        observation = _parse_origin_record(data)
        if observation is None:
            continue
        body = bodies.get(observation.object_key)
        if body is None or not observation.measured(body):
            continue
        if not window_start <= observation.observed_at <= window_end:
            continue
        current = chosen.get(observation.object_key)
        # Paths are visited in ascending digest order, so a strictly later
        # measurement replaces the current choice and a tie keeps the lower.
        if current is None or observation.observed_at > current[0]:
            chosen[observation.object_key] = (
                observation.observed_at,
                path.name,
                observation,
            )
    return {key: item[2] for key, item in sorted(chosen.items())}


# --- step 2: acquisition receipt --------------------------------------------------


#: Every declared endpoint, as expected object key, authenticated host, and
#: route. The host is part of the endpoint identity: the calendar is served by
#: the paper trading API host and not by the market data host, and a receipt
#: that says otherwise is wrong about where its own bytes came from.
_OBJECT_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    (BARS_OBJECT_KEY, ALPACA_DATA_HOST, ALPACA_BARS_ROUTE),
    (CALENDAR_OBJECT_KEY, ALPACA_PAPER_TRADING_HOST, ALPACA_CALENDAR_ROUTE),
    (ACTIONS_OBJECT_KEY, ALPACA_DATA_HOST, ALPACA_ACTIONS_ROUTE),
)
_OBJECT_HOSTS: dict[str, str] = {key: host for key, host, _ in _OBJECT_ENDPOINTS}

#: The fields each endpoint is expected to return. A calendar row carries no
#: OHLCV and a dividend row carries no OHLCV, so declaring OHLCV for all three
#: would make the closed-world inventory describe an acquisition nobody ran.
_EXPECTED_FIELDS: dict[str, tuple[str, ...]] = {
    BARS_OBJECT_KEY: tuple(sorted(REQUIRED_RECONSTRUCTION_FIELDS)),
    CALENDAR_OBJECT_KEY: ("close", "date", "open"),
    ACTIONS_OBJECT_KEY: (
        "corporate_action_id",
        "ex_date",
        "payable_date",
        "rate",
        "record_date",
        "symbol",
    ),
}


def _document_matches_object_key(key: str, data: bytes) -> bool:
    """Return whether these bytes have the shape the named endpoint returns.

    ``matched_expected_key`` is only worth recording if something checked it.
    The check is on the retained bytes themselves, so filing the calendar
    response under the bars key is refused rather than reconciled.
    """
    try:
        document = _strict_document(data)
    except UnicodeDecodeError, ValueError:
        return False
    if key == BARS_OBJECT_KEY:
        return isinstance(document, dict) and isinstance(document.get("bars"), dict)
    if key == CALENDAR_OBJECT_KEY:
        return isinstance(document, list)
    if key == ACTIONS_OBJECT_KEY:
        return isinstance(document, dict) and isinstance(
            document.get("corporate_actions"), dict
        )
    raise AlpacaBridgeIncompleteError(f"{key} is not a declared Alpaca endpoint")


def _expected_inventory(request: AlpacaIntakeRequest) -> ExpectedInventoryV1:
    window = (request.start_date.isoformat(), request.end_date.isoformat())
    objects = tuple(
        ExpectedObjectV1(
            object_key=key,
            endpoint_or_file=f"https://{host}{route}",
            as_of_universe_rule="predeclared bounded exploratory cohort",
            fields=_EXPECTED_FIELDS[key],
            dates=window,
            partitions=(),
            expected_count=1,
            source_of_enumeration="drift predeclared bounded intake declaration",
            justification=(
                "one closed response per declared endpoint over the declared "
                "bounded window and cohort"
            ),
        )
        for key, host, route in _OBJECT_ENDPOINTS
    )
    return ExpectedInventoryV1(
        inventory_id=_derived_uuid7(
            "inventory", request.cohort_id, window[0], window[1]
        ),
        objects=objects,
        enumeration_source="drift predeclared bounded intake declaration",
        justification=(
            "the exploratory bridge requests exactly three closed endpoints, so "
            "the expected inventory is enumerable before the request starts"
        ),
        frozen_at=request.plan_frozen_at,
    )


def _native_layer_rule() -> ProviderNativeLayerRuleV1:
    return ProviderNativeLayerRuleV1(
        schema_version="1",
        profile_set_hash=content_hash(
            {"kind": "alpaca-exploratory-profile-set", "schema_version": "1"}
        ),
        supported_profile_hashes=(regular_session_trade_bar_profile_hash(),),
        product_schema_hash=content_hash(
            {"kind": "alpaca-rest-json", "schema_version": "1"}
        ),
        methodology_hash=_policy_hash("alpaca-acquisition-methodology"),
        authoritative_native_layer=ByteLayerKind.TRANSPORT_ENTITY,
        exclusions=(),
    )


def _byte_graph(retained: RetainedNativeBytes) -> NativeByteGraphV1:
    """Describe the retained transport entities with no Drift transformation.

    The bridge retains exactly what the provider returned. There is no decode,
    decompress, or archive step to claim, so every object is both a retained
    root and a provider-native leaf.
    """
    objects = tuple(
        ByteObjectV1(
            schema_version="1",
            layer=ByteLayerKind.TRANSPORT_ENTITY,
            artifact_reference=_reference(digest, "native", ArtifactKind.DATASET),
            byte_size=retained.artifacts[digest].byte_size,
            content_hash=digest,
            media_type="application/json",
            content_encoding=None,
            archive_identity=None,
            member_identity=None,
        )
        for digest in retained.ordered_hashes
    )
    descriptors = tuple(sorted(item.descriptor_hash for item in objects))
    return NativeByteGraphV1(
        schema_version="1",
        objects=objects,
        transformations=(),
        retained_root_descriptor_hashes=descriptors,
        provider_native_leaf_descriptor_hashes=descriptors,
    )


def _request_identity(request: AlpacaIntakeRequest) -> RequestIdentityV1:
    return RequestIdentityV1(
        schema_version="1",
        method="GET",
        # Two hosts are authenticated against, not one: the market data host
        # and the paper trading API host. Naming only the market data host
        # would misattribute the calendar response.
        authenticated_provider_host=",".join(
            sorted({host for _, host, _ in _OBJECT_ENDPOINTS})
        ),
        route_template=",".join(
            f"{host}{route}" for _, host, route in _OBJECT_ENDPOINTS
        ),
        canonical_parameters={
            "adjustment": "raw",
            "end": request.end_date.isoformat(),
            "feed": "sip",
            "start": request.start_date.isoformat(),
            "timeframe": "1Day",
        },
        requested_universe=tuple(member.symbol for member in request.members),
        requested_fields=tuple(sorted(REQUIRED_RECONSTRUCTION_FIELDS)),
        requested_date_range=(
            request.start_date.isoformat(),
            request.end_date.isoformat(),
        ),
        requested_cutoff=None,
        request_start=request.request_start,
        request_end=request.request_end,
        client_request_id=f"alpaca-exploratory-{request.cohort_id}",
    )


def _origin_evidence(
    request: AlpacaIntakeRequest, key: str, data: bytes
) -> OriginEvidenceV1:
    """Carry the measured origin of one response, or claim nothing at all.

    Nothing here is asserted unless the transport measured it over exactly
    ``data``, the retained bytes this object is being reconciled from. When no
    observation was supplied, or the one supplied was taken over any other
    bytes, the origin is reported ``UNKNOWN`` with no status, no content type,
    and no TLS peer. Closed-world reconciliation then refuses to pass, which is
    the honest outcome: an unmeasured origin is not a verified one, and a
    measurement of other bytes is not a measurement of these.
    """
    observation = request.observation_for(key)
    if observation is None or not observation.measured(data):
        return OriginEvidenceV1(
            schema_version="1",
            origin_status=OriginStatus.UNKNOWN,
            provider_request_id=None,
            provider_object_id=None,
            safe_response_metadata=None,
            tls_endpoint_identity=None,
            provider_checksums=(),
            provider_signatures=(),
            provider_manifest_references=(),
            evidence_references=(),
        )
    metadata: dict[str, str] = {
        "http_status": str(observation.http_status),
        "observed_at": observation.observed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_host": observation.request_host,
    }
    if observation.content_type is not None:
        metadata["content_type"] = observation.content_type
    return OriginEvidenceV1(
        schema_version="1",
        # A plaintext hop leaves no endpoint identity to verify against, so it
        # is recorded as unknown rather than promoted to verified.
        origin_status=(
            OriginStatus.VERIFIED
            if observation.tls_endpoint_identity
            else OriginStatus.UNKNOWN
        ),
        provider_request_id=None,
        provider_object_id=None,
        safe_response_metadata=metadata,
        tls_endpoint_identity=observation.tls_endpoint_identity,
        provider_checksums=(),
        provider_signatures=(),
        provider_manifest_references=(),
        evidence_references=(),
    )


def _pages_and_objects(
    request: AlpacaIntakeRequest, retained: RetainedNativeBytes
) -> tuple[tuple[PageReceiptV1, ...], tuple[ObservedObjectV1, ...]]:
    graph = _byte_graph(retained)
    by_content = {item.content_hash: item.descriptor_hash for item in graph.objects}
    digests = {
        BARS_OBJECT_KEY: retained.bars_hash,
        CALENDAR_OBJECT_KEY: retained.calendar_hash,
        ACTIONS_OBJECT_KEY: retained.corporate_actions_hash,
    }
    pages: list[PageReceiptV1] = []
    observed: list[ObservedObjectV1] = []
    for order, (key, host, route) in enumerate(_OBJECT_ENDPOINTS):
        digest = digests[key]
        descriptor = by_content[digest]
        if not _document_matches_object_key(key, retained.artifacts[digest].data):
            raise AlpacaBridgeIncompleteError(
                f"the bytes retained for {key} do not have the shape "
                f"https://{host}{route} returns, so they cannot be matched to "
                "that expected object"
            )
        pages.append(
            PageReceiptV1(
                schema_version="1",
                page_identity=f"{key}-page-0",
                page_order=order,
                cursor_in=None,
                cursor_out=None,
                byte_object_descriptor_hashes=(descriptor,),
                attempt_identity=f"{key}-attempt-0",
                result="complete",
                duplicates=(),
                failure_evidence=(),
            )
        )
        observed.append(
            ObservedObjectV1(
                schema_version="1",
                provider_object_identity=f"GET https://{host}{route}",
                matched_expected_key=key,
                page_identity=f"{key}-page-0",
                byte_object_descriptor_hashes=(descriptor,),
                origin_evidence=_origin_evidence(
                    request, key, retained.artifacts[digest].data
                ),
                observation_status="retained",
            )
        )
    return tuple(pages), tuple(observed)


def _screen_acquisition_payloads(
    identity: RequestIdentityV1,
    execution: AcquisitionExecutionContextV1,
    pages: tuple[PageReceiptV1, ...],
    observed: tuple[ObservedObjectV1, ...],
) -> None:
    """Screen every credential-bearing surface before minting a receipt.

    The shared M1e screener keys off field names as well as values. An
    ``OriginEvidenceV1`` declares ``provider_signatures``, whose name contains
    the screened substring "signature", so screening an ``ObservedObjectV1``
    wholesale raises on the schema itself rather than on any acquired content.
    The observed objects are therefore screened value by value, which keeps the
    guarantee without depending on that upstream false positive.
    """
    validate_secret_free_acquisition_payload(identity)
    validate_secret_free_acquisition_payload(execution)
    validate_secret_free_acquisition_payload(pages)
    for item in observed:
        validate_secret_free_acquisition_payload(item.provider_object_identity)
        validate_secret_free_acquisition_payload(item.matched_expected_key)
        validate_secret_free_acquisition_payload(item.page_identity)
        validate_secret_free_acquisition_payload(item.observation_status)
        validate_secret_free_acquisition_payload(item.byte_object_descriptor_hashes)
        evidence = item.origin_evidence
        validate_secret_free_acquisition_payload(evidence.provider_request_id)
        validate_secret_free_acquisition_payload(evidence.provider_object_id)
        validate_secret_free_acquisition_payload(evidence.safe_response_metadata)
        validate_secret_free_acquisition_payload(evidence.tls_endpoint_identity)
        validate_secret_free_acquisition_payload(evidence.provider_checksums)
        validate_secret_free_acquisition_payload(evidence.provider_signatures)
        for reference in (
            *evidence.provider_manifest_references,
            *evidence.evidence_references,
        ):
            validate_secret_free_acquisition_payload(reference)


@dataclass(frozen=True, slots=True)
class AlpacaAcquisitionEvidence:
    """The receipt, plan, and reconciliation backing one bounded acquisition."""

    plan: AcquisitionPlanV1
    expected_inventory: ExpectedInventoryV1
    reconciliation: AcquisitionReconciliationV1
    receipt: AcquisitionReceiptV1


def build_alpaca_acquisition_evidence(
    request: AlpacaIntakeRequest, retained: RetainedNativeBytes
) -> AlpacaAcquisitionEvidence:
    """Reconcile the closed-world inventory and mint the acquisition receipt."""
    inventory = _expected_inventory(request)
    rule = _native_layer_rule()
    identity = _request_identity(request)
    authorization = content_hash(
        {
            "kind": "alpaca-exploratory-self-authorization",
            "schema_version": "1",
            "cohort_id": request.cohort_id,
            "cohort_version": request.cohort_version,
            "lane": "exploratory",
        }
    )
    plan = AcquisitionPlanV1(
        schema_version="1",
        plan_id=_derived_uuid7("plan", request.cohort_id, request.cohort_version),
        authorization_hash=authorization,
        request_scope_hash=content_hash(identity),
        expected_inventory_hash=content_hash(inventory),
        planned_native_layer_rule_hash=content_hash(rule),
        max_bytes=64 * 1024 * 1024,
        max_objects=len(_OBJECT_ENDPOINTS),
        max_pages=len(_OBJECT_ENDPOINTS),
        frozen_at=request.plan_frozen_at,
    )
    pages, observed = _pages_and_objects(request, retained)
    reconciliation = reconcile_acquisition(
        inventory,
        pages,
        observed,
        (),
        request.request_start,
        None,
    )
    # Which code collected is build provenance. The collector sits outside the
    # M1d evidence closure, so only the whole source inventory attests it.
    execution = AcquisitionExecutionContextV1(
        schema_version="1",
        collector_id=BRIDGE_COLLECTOR_ID,
        collector_version=BRIDGE_COLLECTOR_VERSION,
        collector_source_hash=drift_source_inventory_hash(),
        invocation_id=_derived_uuid7("invocation", request.cohort_id, authorization),
        executable_evidence_hashes=(drift_source_inventory_hash(),),
        receipt_id=_derived_uuid7("receipt", request.cohort_id, authorization),
        receipt_version="1",
        creation_time=request.request_end,
        safe_execution_metadata={"lane": "exploratory"},
    )
    if plan.frozen_at > identity.request_start:
        raise AlpacaBridgeIncompleteError(
            "the acquisition plan must be frozen before the request starts"
        )
    _screen_acquisition_payloads(identity, execution, pages, observed)
    graph = _byte_graph(retained)
    receipt = AcquisitionReceiptV1(
        schema_version="1",
        receipt_id=execution.receipt_id,
        receipt_version=execution.receipt_version,
        created_at=execution.creation_time,
        acquisition_plan_hash=content_hash(plan),
        authorization_hash=authorization,
        profile_set_hash=rule.profile_set_hash,
        request=identity,
        native_layer_rule=rule,
        byte_graph=graph,
        byte_graph_hash=content_hash(graph),
        pages=pages,
        retries=(),
        observed_objects=observed,
        expected_inventory_hash=content_hash(inventory),
        reconciliation_hash=content_hash(reconciliation),
        schema_evidence_hashes=(),
        methodology_evidence_hashes=(_policy_hash("alpaca-acquisition-methodology"),),
        license_evidence_hashes=(_policy_hash("alpaca-license-terms"),),
        collector_source_hash=execution.collector_source_hash,
        collector_version=execution.collector_version,
    )
    verify_acquisition_receipt(receipt, retained.artifacts)
    return AlpacaAcquisitionEvidence(
        plan=plan,
        expected_inventory=inventory,
        reconciliation=reconciliation,
        receipt=receipt,
    )


# --- step 3: map native payloads onto Drift source records ------------------------


def map_cohort_identities(
    request: AlpacaIntakeRequest,
) -> tuple[tuple[SecurityV1, ...], tuple[ListingV1, ...]]:
    """Project the declared cohort onto opaque M1b identity records."""
    securities = tuple(
        SecurityV1(schema_version="1", security_id=member.security_id)
        for member in request.members
    )
    listings = tuple(
        ListingV1(schema_version="1", listing_id=member.listing_id, venue=member.venue)
        for member in request.members
    )
    return securities, listings


def build_alpaca_observation_contract(
    request: AlpacaIntakeRequest,
) -> tuple[ObservationContractV1, dict[str, VerifiedArtifactBytes]]:
    """Describe the exact Alpaca daily SIP bar methodology as an M1d contract.

    Every policy hash below addresses its own rule document. Nothing is
    asserted as included, excluded, or conditional unless Alpaca publishes it;
    where it does not, the disposition is ``"unknown"`` and the document says
    so in words as well as in the hash.
    """
    ordering_hash = _policy_hash("alpaca-trade-ordering")
    basis_hash = _policy_hash("alpaca-adjustment-basis")
    sale_condition_hash = _policy_hash("alpaca-sale-condition")
    correction_hash = _policy_hash("alpaca-correction-cancellation")
    population_hash = _policy_hash("alpaca-trade-population")
    volume_relation_hash = _policy_hash("alpaca-volume-relationship")
    interval_hash = _policy_hash("alpaca-interval-endpoints")
    revision_hash = _policy_hash("alpaca-revision-policy")
    row_emission_hash = _policy_hash("alpaca-row-emission")
    venues = tuple(sorted({member.venue.value for member in request.members}))
    methods = tuple(
        ObservationFieldMethodV1(
            schema_version="1",
            method_id=f"alpaca-{name}-v1",
            field_name=name,
            meaning=_FIELD_MEANINGS[name],  # type: ignore[arg-type]
            population_id=_POPULATION_ID,
            effective_selector=_FIELD_SELECTORS[name],  # type: ignore[arg-type]
            ordering="execution_time_then_source_sequence",
            ordering_policy_hash=ordering_hash,
            precision=28,
            scale=9,
            null_meaning="no_value",
            zero_meaning="numeric_zero",
            fallback_branch_id=None,
            equivalence_evidence_hash=None,
            adjustment_basis="unadjusted",
            basis_methodology_hash=basis_hash,
            intraday_basis_homogeneity="homogeneous",
            unit="shares" if name == "volume" else "currency_per_share",
        )
        for name in REQUIRED_RECONSTRUCTION_FIELDS
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "contract_id": _derived_uuid7("contract", ALPACA_BAR_SOURCE_ID, *venues),
        "version": "1",
        "source_id": ALPACA_BAR_SOURCE_ID,
        "methodology_artifact_hash": "0" * 64,
        "availability": (
            _observed_availability(
                request.acquired_at,
                _policy_hash("alpaca-acquisition-methodology"),
                "alpaca-contract-availability",
            ),
        ),
        "market_population": "consolidated",
        "market_venues": venues,
        "populations": (
            TradePopulationV1(
                schema_version="1",
                population_id=_POPULATION_ID,
                feed_identity="sip",
                feed_version="v2",
                venue_scope=venues,
                session_scope="regular",
                event_time_basis="execution",
                sale_condition_policy_hash=sale_condition_hash,
                odd_lot_rule="unknown",
                # Alpaca publishes no auction-inclusion methodology for 1Day
                # SIP bars. "included" would be a positive factual claim about
                # a rule nobody published, and it is load-bearing in
                # session binding, so the honest disposition is "unknown".
                opening_auction_rule="unknown",
                closing_auction_rule="unknown",
                correction_cancellation_policy_hash=correction_hash,
                evidence_hash=population_hash,
            ),
        ),
        "field_methods": methods,
        "method_branches": tuple(
            MethodBranchV1(
                schema_version="1",
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
                schema_version="1",
                price_population_id=_POPULATION_ID,
                volume_population_id=_POPULATION_ID,
                relation="equal",
                evidence_hash=volume_relation_hash,
            ),
        ),
        "currency": "USD",
        "timestamp_meaning": "exchange_local_session_date",
        "source_label_syntax": "YYYY-MM-DD",
        "source_timezone": request.timezone_evidence.timezone_identifier,
        "interval_policy": IntervalPolicyV1(
            schema_version="1",
            open_inclusion="included",
            close_inclusion="included",
            # Same reason as the population dispositions above: unpublished.
            auction_event_inclusion="unknown",
            event_policy_hash=interval_hash,
        ),
        # Alpaca overwrites derived bars in place and rejects pit=true, so the
        # only truthful revision policy is a current snapshot with no retained
        # correction history.
        "revision_policy": RevisionPolicyV1(
            schema_version="1",
            kind="current_snapshot_only",
            correction_horizon="unknown",
            correction_duration_seconds=None,
            policy_hash=revision_hash,
        ),
        "row_emission": RowEmissionPolicyV1(
            schema_version="1",
            kind="conditional_on_qualifying_activity",
            omission_marker_policy_hash=row_emission_hash,
        ),
        "adjustment_basis": "unadjusted",
    }
    provisional = ObservationContractV1.model_validate(values)
    methodology_bytes = canonical_json(
        observation_methodology_for_contract(provisional)
    )
    methodology_hash = sha256(methodology_bytes).hexdigest()
    contract = ObservationContractV1.model_validate(
        {**values, "methodology_artifact_hash": methodology_hash}
    )
    contract_bytes = canonical_json(contract)
    support = _policy_artifacts()
    for artifact in (_verified(methodology_bytes), _verified(contract_bytes)):
        support[artifact.content_hash] = artifact
    return contract, support


def map_native_bar(
    bar: AlpacaNativeBar,
    member: AlpacaCohortMember,
    request: AlpacaIntakeRequest,
    contract: ObservationContractV1,
    session_bounds: tuple[datetime, datetime],
    retained: RetainedNativeBytes,
    *,
    target: ObservationTarget = "source_observation",
) -> tuple[DailySourceObservationVersionV1, VerifiedArtifactBytes]:
    """Map one native bar onto a ``DailySourceObservationVersionV1``.

    ``target="derived_view"`` is refused. A ``DerivedObservationViewV1`` is an
    M1d normalization output and can only be produced by the M1d materializers
    over authentic realized session evidence, which Alpaca does not publish.
    """
    if target != "source_observation":
        raise AlpacaBridgeProhibitedError(
            "the Alpaca bridge cannot construct a DerivedObservationViewV1 from "
            "provider JSON; derived views come only from M1d normalization"
        )
    if bar.symbol != member.symbol:
        raise AlpacaBridgeIncompleteError("bar symbol does not match its cohort member")
    opened_at, closed_at = session_bounds
    if closed_at <= opened_at:
        raise AlpacaBridgeIncompleteError(
            f"session bounds for {bar.session_date} do not close after they open"
        )
    # Alpaca happily returns a still-forming bar for a session that has not
    # closed yet. Admitting one would put a partial print into historical
    # evidence and would invert the completion window below.
    if closed_at > request.acquired_at:
        raise AlpacaBridgeIncompleteError(
            f"session {bar.session_date} had not closed when the bytes were "
            "observed, so its bar is not a completed historical observation"
        )
    projection = canonical_json(
        {
            "kind": "alpaca-native-daily-bar",
            "schema_version": "1",
            "symbol": bar.symbol,
            "t": bar.native_timestamp,
            "o": str(bar.open),
            "h": str(bar.high),
            "l": str(bar.low),
            "c": str(bar.close),
            "v": str(bar.volume),
            "n": bar.trade_count,
        }
    )
    record_artifact = _verified(projection)
    seed = f"{ALPACA_BAR_SOURCE_ID}:{bar.symbol}:{bar.session_date.isoformat()}"
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": _revision(
            logical_seed=seed,
            version_seed=f"{seed}:0",
            availability=_observed_availability(
                request.acquired_at, record_artifact.content_hash, f"{seed}:available"
            ),
            source_digest=retained.bars_hash,
        ),
        "source_key": ObservationSourceKeyV1(
            schema_version="1",
            source_id=ALPACA_BAR_SOURCE_ID,
            native_record_id=f"{bar.symbol}:{bar.session_date.isoformat()}",
        ),
        "source_record_locator": f"alpaca+bars://{bar.symbol}/{bar.session_date}",
        "source_record_hash": record_artifact.content_hash,
        "contract_hash": content_hash(contract),
        "security_id": member.security_id,
        "listing_id": member.listing_id,
        "venue": member.venue,
        "session_date": bar.session_date,
        "source_local_label": bar.session_date.isoformat(),
        "source_timezone": request.timezone_evidence.timezone_identifier,
        "claimed_interval": TemporalIntervalClaimV1(
            schema_version="1",
            start=_exact_boundary(opened_at, retained.calendar_hash, f"{seed}:open"),
            end=_exact_boundary(closed_at, retained.calendar_hash, f"{seed}:close"),
        ),
        # Alpaca publishes no completion or publication timestamp, so the only
        # supportable claim is the window between the scheduled close and the
        # instant Drift observed the bytes.
        "completion_time": _bounded_boundary(
            closed_at,
            request.acquired_at,
            bar.session_date.isoformat(),
            record_artifact.content_hash,
            f"{seed}:completion",
        ),
        "fields": tuple(
            SourceFieldValueV1(
                schema_version="1",
                field_name=name,
                method_id=f"alpaca-{name}-v1",
                native_text=str(value),
                value=value,
                state="value",
                native_flag=None,
            )
            for name, value in (
                ("close", bar.close),
                ("high", bar.high),
                ("low", bar.low),
                ("open", bar.open),
                ("volume", bar.volume),
            )
        ),
        "source_flags": (
            NativeSourceFlagV1(schema_version="1", key="feed", value="sip"),
            NativeSourceFlagV1(
                schema_version="1", key="trade_count", value=str(bar.trade_count)
            ),
        ),
        # Alpaca does not publish first or last eligible trade times, and the
        # bridge does not invent them.
        "first_eligible_trade_time": None,
        "last_eligible_trade_time": None,
        "activity_claim": "unknown",
        "any_trade_claim": "reported" if bar.trade_count > 0 else "unknown",
    }
    return _seal(DailySourceObservationVersionV1, values), record_artifact


def map_calendar_day(
    day: AlpacaNativeCalendarDay,
    request: AlpacaIntakeRequest,
    methodology_hash: str,
    retained: RetainedNativeBytes,
    support: dict[str, VerifiedArtifactBytes],
    retained_evidence: dict[str, AvailabilityEvidenceV1],
    *,
    target: SessionTarget = "scheduled_session",
) -> ScheduledSessionVersionV1:
    """Map one native calendar row onto a ``ScheduledSessionVersionV1``.

    ``target="realized_session"`` is refused. A scheduled calendar row carries
    no realized open, no realized close, and no halt telemetry, so it can never
    mint ``RealizedSessionVersionV1`` authority.
    """
    if target != "scheduled_session":
        raise AlpacaBridgeProhibitedError(
            "the Alpaca bridge cannot convert a scheduled calendar row into a "
            "RealizedSessionVersionV1; scheduled rows carry no realized authority"
        )
    local_date = day.session_date
    local_open = f"{local_date.isoformat()}T{_local_time(day.local_open)}"
    local_close = f"{local_date.isoformat()}T{_local_time(day.local_close)}"
    # The state is read from the provider's own close time rather than from a
    # prefix match, so a 16:30 close is not silently filed as an early close.
    state: Literal["regular", "early_close"] = (
        "early_close"
        if _local_time(day.local_close) < REGULAR_LOCAL_CLOSE
        else "regular"
    )
    offsets: list[HistoricalBoundaryOffsetV1] = []
    for boundary, label in (("open", local_open), ("close", local_close)):
        seconds = request.boundary_offsets.get((local_date, boundary))
        if seconds is None:
            raise AlpacaBridgeIncompleteError(
                "no attested UTC offset for "
                f"{local_date.isoformat()} {boundary}; the bridge does not invent one"
            )
        payload = canonical_json(
            {
                "schema_version": "1",
                "kind": "historical_boundary_offset",
                "source_id": ALPACA_CALENDAR_SOURCE_ID,
                "mic": request.mic,
                "local_date": local_date.isoformat(),
                "boundary": boundary,
                "local_label": label,
                "timezone_identifier": request.timezone_evidence.timezone_identifier,
                "utc_offset_seconds": seconds,
            }
        )
        artifact = _verified(payload)
        support[artifact.content_hash] = artifact
        evidence = _observed_availability(
            request.acquired_at,
            artifact.content_hash,
            f"offset:{local_date.isoformat()}:{boundary}",
        )
        retained_evidence[content_hash(evidence)] = evidence
        offsets.append(
            HistoricalBoundaryOffsetV1(
                schema_version="1",
                boundary=boundary,  # type: ignore[arg-type]
                utc_offset_seconds=seconds,
                methodology_encoding_hash=methodology_hash,
                authority_artifact_hash=artifact.content_hash,
                authority_availability_evidence_hash=content_hash(evidence),
            )
        )
    seed = f"{ALPACA_CALENDAR_SOURCE_ID}:{request.mic}:{local_date.isoformat()}"
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": _revision(
            logical_seed=seed,
            version_seed=f"{seed}:0",
            availability=_observed_availability(
                request.acquired_at, retained.calendar_hash, f"{seed}:available"
            ),
            source_digest=retained.calendar_hash,
        ),
        "source_id": ALPACA_CALENDAR_SOURCE_ID,
        "session_key": SessionKeyV1(
            mic=request.mic, session_scope="regular", local_date=local_date
        ),
        "source_temporal_evidence": _date_boundary(
            local_date, retained.calendar_hash, f"{seed}:temporal"
        ),
        "state": state,
        "local_open": local_open,
        "local_close": local_close,
        "timezone_identifier": request.timezone_evidence.timezone_identifier,
        "open_fold": None,
        "close_fold": None,
        "historical_boundary_offsets": tuple(offsets),
        "source_methodology_hash": methodology_hash,
    }
    return _seal(ScheduledSessionVersionV1, values)


def _local_time(value: str) -> str:
    parts = value.split(":")
    if len(parts) == 2:
        return f"{value}:00"
    if len(parts) == 3:
        return value
    raise AlpacaBridgeIncompleteError(f"calendar boundary is not a local time: {value}")


def map_cash_dividend(
    dividend: AlpacaNativeCashDividend,
    member: AlpacaCohortMember,
    request: AlpacaIntakeRequest,
    retained: RetainedNativeBytes,
    *,
    target: EconomicTarget = "terms",
) -> CorporateActionTermsVersionV1:
    """Map one native cash dividend onto terms, and only onto terms.

    ``target="effect"`` and ``target="settlement"`` are refused. Alpaca reports
    announced terms. It does not prove that an effect occurred or that a
    settlement was delivered, and the bridge never invents either.
    """
    if target != "terms":
        raise AlpacaBridgeProhibitedError(
            "the Alpaca bridge maps corporate actions as terms only; it cannot "
            f"mint an economic {target} the provider never proved"
        )
    seed = f"{ALPACA_ACTION_SOURCE_ID}:{dividend.native_id}"
    occurrence_reference = _reference(
        retained.corporate_actions_hash, f"{seed}:occurrence", ArtifactKind.OTHER
    )
    payload = TermsPayloadV1(
        kind="fixed",
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(
            CashComponentV1(
                kind="cash",
                component_id=f"{dividend.native_id}-cash",
                amount=dividend.rate_text,
                currency_namespace="iso4217",
                currency_code="USD",
                unit_basis=EconomicUnitBasisV1(
                    security_id=member.security_id,
                    denominator=PositiveRatioV1(numerator="1", denominator="1"),
                    share_basis="as_reported_unknown",
                ),
                amount_basis="unknown",
                applicability="ordinary_passive_holder",
                conditions=(),
                source_amount_text=dividend.rate_text,
                source_precision=None,
            ),
        ),
        dates=(
            EconomicDateFactV1(
                role="ex",
                boundary=_date_boundary(
                    dividend.ex_date, retained.corporate_actions_hash, f"{seed}:ex"
                ),
                rule_reference=None,
            ),
            EconomicDateFactV1(
                role="record",
                boundary=_date_boundary(
                    dividend.record_date,
                    retained.corporate_actions_hash,
                    f"{seed}:record",
                ),
                rule_reference=None,
            ),
            EconomicDateFactV1(
                role="payable",
                boundary=_date_boundary(
                    dividend.payable_date,
                    retained.corporate_actions_hash,
                    f"{seed}:payable",
                ),
                rule_reference=None,
            ),
        ),
        conditions=(),
        reason=None,
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": _revision(
            logical_seed=seed,
            version_seed=f"{seed}:0",
            availability=_observed_availability(
                request.acquired_at,
                retained.corporate_actions_hash,
                f"{seed}:available",
            ),
            source_digest=retained.corporate_actions_hash,
        ),
        "source_key": EconomicSourceKeyV1(
            source_id=ALPACA_ACTION_SOURCE_ID,
            family="terms",
            native_record_id=dividend.native_id,
        ),
        "security_id": member.security_id,
        "listing_id": member.listing_id,
        "occurrence": EconomicOccurrenceV1(
            kind="identified",
            native_occurrence_id=dividend.native_id,
            evidence_reference=occurrence_reference,
            reason=None,
        ),
        "source_action_code": "cash_dividend",
        "scheduled_effect_time": _date_boundary(
            dividend.ex_date, retained.corporate_actions_hash, f"{seed}:scheduled"
        ),
        "payload": payload,
    }
    return _seal(CorporateActionTermsVersionV1, values)


# --- step 4: validate every mapped dataset through Drift public validators ---------


def _descriptors(
    *,
    role: str,
    source_id: str,
    request: AlpacaIntakeRequest,
    retained_digest: str,
    data: bytes,
    row_count: int,
    schema: Any,
    contract: Any,
) -> tuple[DatasetManifestV2, dict[str, VerifiedArtifactBytes]]:
    digest = sha256(data).hexdigest()
    evidence = _reference(retained_digest, f"{role}:evidence", ArtifactKind.OTHER)
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=_derived_uuid7("dataset", role, source_id, request.cohort_id),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=request.acquired_at,
        source=SourceDescriptorV1(
            source_id=source_id,
            publisher=BRIDGE_PROVIDER_LEGAL_NAME,
            product="Alpaca Basic free development REST",
            evidence_reference=evidence,
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=request.acquired_at,
            collector_id=BRIDGE_COLLECTOR_ID,
            collector_version=BRIDGE_COLLECTOR_VERSION,
            evidence_reference=evidence,
        ),
        license=LicenseDescriptorV1(
            provider_legal_name=BRIDGE_PROVIDER_LEGAL_NAME,
            license_reference=BRIDGE_LICENSE_REFERENCE,
            acquired_at=request.acquired_at,
            # Licence evidence is a licence document. Pointing this at the
            # acquired market data bytes would make the manifest claim that a
            # bars response is the terms it was acquired under.
            terms_evidence_reference=_license_reference(),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=_derived_uuid7("partition", role, digest),
                partition_key="all",
                artifact=_reference(digest, f"{role}:partition", ArtifactKind.DATASET),
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=row_count,
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(
                    started_at=datetime.combine(
                        request.start_date, datetime.min.time(), tzinfo=UTC
                    ),
                    ended_at=request.acquired_at,
                ),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=contract,
        ),
        lineage=None,
    )
    return manifest, {digest: _verified(data)}


def _validation_run(
    *,
    role: str,
    request: AlpacaIntakeRequest,
    profile_id: str,
    profile_hash: str,
    implementation_hash: str,
) -> ValidationRunContextV1:
    return ValidationRunContextV1(
        decision_id=_derived_uuid7("decision", role, request.cohort_id),
        validator_version="1",
        validator_implementation_hash=implementation_hash,
        validation_profile_id=profile_id,
        validation_profile_hash=profile_hash,
        checked_at=request.acquired_at,
    )


def _observation_dataset(
    records: tuple[DailySourceObservationVersionV1, ...],
    request: AlpacaIntakeRequest,
    support: Mapping[str, VerifiedArtifactBytes],
    retained: RetainedNativeBytes,
) -> M1dDatasetInput[Any]:
    data = canonical_json({"schema_version": "1", "records": records})
    schema = observation_role_schema("source_observation")
    contract = observation_role_contract("source_observation", (_channel(),))
    manifest, artifacts = _descriptors(
        role="source_observation",
        source_id=ALPACA_BAR_SOURCE_ID,
        request=request,
        retained_digest=retained.bars_hash,
        data=data,
        row_count=len(records),
        schema=schema,
        contract=contract,
    )
    run = _validation_run(
        role="source_observation",
        request=request,
        profile_id=OBSERVATION_VALIDATION_PROFILE_ID,
        profile_hash=observation_validation_profile_hash(),
        implementation_hash=observation_validator_implementation_hash(),
    )
    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)
    _require_pass(decision, "source_observation")
    return M1dDatasetInput(
        manifest=manifest,
        validation_run=run,
        artifacts=artifacts,
        records=parsed,
        decision=decision,
        bundle=build_validated_dataset_bundle(
            bundle_id=_derived_uuid7("bundle", "source_observation", request.cohort_id),
            bundle_version="1",
            created_at=request.acquired_at,
            validated_datasets=((manifest, decision),),
        ),
    )


def _session_dataset(
    role: Literal["scheduled_session", "session_coverage"],
    records: tuple[Any, ...],
    request: AlpacaIntakeRequest,
    support: Mapping[str, VerifiedArtifactBytes],
    retained: RetainedNativeBytes,
) -> M1dDatasetInput[Any]:
    data = canonical_json({"schema_version": "1", "records": records})
    schema = session_role_schema(role)
    contract = session_role_contract(role, (_channel(),))
    manifest, artifacts = _descriptors(
        role=role,
        source_id=ALPACA_CALENDAR_SOURCE_ID,
        request=request,
        retained_digest=retained.calendar_hash,
        data=data,
        row_count=len(records),
        schema=schema,
        contract=contract,
    )
    run = _validation_run(
        role=role,
        request=request,
        profile_id=SESSION_VALIDATION_PROFILE_ID,
        profile_hash=session_validation_profile_hash(),
        implementation_hash=session_validator_implementation_hash(),
    )
    decision, parsed = validate_session_dataset(manifest, artifacts, run, support)
    _require_pass(decision, role)
    return M1dDatasetInput(
        manifest=manifest,
        validation_run=run,
        artifacts=artifacts,
        records=parsed,
        decision=decision,
        bundle=build_validated_dataset_bundle(
            bundle_id=_derived_uuid7("bundle", role, request.cohort_id),
            bundle_version="1",
            created_at=request.acquired_at,
            validated_datasets=((manifest, decision),),
        ),
    )


@dataclass(frozen=True, slots=True)
class AlpacaEconomicTermsDataset:
    """Validated Alpaca terms records, carrying no effect and no settlement."""

    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2
    records: tuple[CorporateActionTermsVersionV1, ...]


def _economic_terms_dataset(
    records: tuple[CorporateActionTermsVersionV1, ...],
    request: AlpacaIntakeRequest,
    retained: RetainedNativeBytes,
) -> AlpacaEconomicTermsDataset:
    data = canonical_json({"schema_version": "1", "records": records})
    schema = economic_role_schema("economic_terms")
    contract = economic_role_contract("economic_terms", (_channel(),))
    manifest, artifacts = _descriptors(
        role="economic_terms",
        source_id=ALPACA_ACTION_SOURCE_ID,
        request=request,
        retained_digest=retained.corporate_actions_hash,
        data=data,
        row_count=len(records),
        schema=schema,
        contract=contract,
    )
    run = _validation_run(
        role="economic_terms",
        request=request,
        profile_id=ECONOMIC_VALIDATION_PROFILE_ID,
        profile_hash=economic_validation_profile_hash(),
        implementation_hash=economic_validator_implementation_hash(),
    )
    decision, parsed = validate_economic_dataset(
        manifest, tuple(artifacts.values()), run
    )
    _require_pass(decision, "economic_terms")
    terms = tuple(
        item for item in parsed if isinstance(item, CorporateActionTermsVersionV1)
    )
    if len(terms) != len(parsed):
        raise AlpacaBridgeProhibitedError(
            "the Alpaca terms dataset must carry terms records only"
        )
    return AlpacaEconomicTermsDataset(
        manifest=manifest, decision=decision, records=terms
    )


def _require_pass(decision: DatasetValidationDecisionV2, role: str) -> None:
    if decision.result.value != "pass":
        raise AlpacaBridgeIncompleteError(
            f"Drift validators rejected the mapped {role} dataset: "
            f"{decision.result.value} {tuple(item.code for item in decision.findings)}"
        )


# --- step 5: assemble the standard M1d resolution context --------------------------


def _timezone_support(
    request: AlpacaIntakeRequest,
    support: dict[str, VerifiedArtifactBytes],
    retained_evidence: dict[str, AvailabilityEvidenceV1],
) -> str:
    """Retain the timezone methodology and return its encoding hash."""
    evidence = request.timezone_evidence
    source_payload = canonical_json(
        {
            "schema_version": "1",
            "kind": "historical_timezone_methodology",
            "source_id": ALPACA_CALENDAR_SOURCE_ID,
            "methodology_id": "alpaca-calendar-local-boundaries",
            "methodology_version": "1",
            "source_timezone_label": evidence.source_timezone_label,
            "timezone_identifier": evidence.timezone_identifier,
            "interpretation": "explicit_boundary_offsets_v1",
        }
    )
    source_artifact = _verified(source_payload)
    support[source_artifact.content_hash] = source_artifact
    availability = _observed_availability(
        request.acquired_at, source_artifact.content_hash, "timezone-methodology"
    )
    retained_evidence[content_hash(availability)] = availability
    methodology = HistoricalTimezoneMethodologyV1(
        schema_version="1",
        source_id=ALPACA_CALENDAR_SOURCE_ID,
        methodology_id="alpaca-calendar-local-boundaries",
        methodology_version="1",
        source_timezone_label=evidence.source_timezone_label,
        timezone_identifier=evidence.timezone_identifier,
        interpretation="explicit_boundary_offsets_v1",
        source_methodology_artifact_hash=source_artifact.content_hash,
        source_methodology_availability_evidence_hash=content_hash(availability),
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
    )
    encoded = _verified(canonical_json(methodology))
    support[encoded.content_hash] = encoded
    return encoded.content_hash


def _schedule_policy(
    request: AlpacaIntakeRequest,
    support: dict[str, VerifiedArtifactBytes],
    methodology_hash: str,
) -> ScheduleGenerationPolicyV1:
    evidence = request.timezone_evidence
    tzif = _verified(evidence.tzif_bytes)
    support[tzif.content_hash] = tzif
    timezone_input = TimezoneInputV1(
        schema_version="1",
        timezone_identifier=evidence.timezone_identifier,
        tzif_sha256=tzif.content_hash,
        tzdb_release=evidence.tzdb_release,
        artifact_hash=tzif.content_hash,
        reconstruction_observed_at=evidence.reconstruction_observed_at,
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
    )
    encoded_input = _verified(canonical_json(timezone_input))
    support[encoded_input.content_hash] = encoded_input
    lineage = request.lineage
    producer_source = _verified(lineage.producer_source)
    producer_package = _verified(lineage.producer_package)
    lockfile = _verified(lineage.lockfile)
    for artifact in (producer_source, producer_package, lockfile):
        support[artifact.content_hash] = artifact
    return ScheduleGenerationPolicyV1(
        schema_version="1",
        algorithm="explicit_local_rows_to_utc_v1",
        semantic_algorithm_hash=schedule_generation_algorithm_hash(),
        producer_name="drift",
        producer_version="1",
        producer_source_hash=producer_source.content_hash,
        producer_package_hash=producer_package.content_hash,
        implementation_hash=m1d_implementation_hash(),
        python_identity=lineage.python_identity,
        lockfile_hash=lockfile.content_hash,
        timezone_input_hash=encoded_input.content_hash,
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
        historical_timezone_methodology_encoding_hashes=(methodology_hash,),
    )


def _coverage_record(
    scheduled: M1dDatasetInput[Any],
    request: AlpacaIntakeRequest,
    methodology_hash: str,
    retained: RetainedNativeBytes,
) -> SessionCoverageVersionV1:
    """Claim dense coverage over exactly the acquired calendar snapshot.

    The claim is snapshot-scoped: ``snapshot_as_of`` is the acquisition instant
    and the inventory enumerates exactly the rows the closed calendar response
    returned. It makes no claim about revisions Alpaca may have made before the
    snapshot, which is what the scheduled-reconstruction limitation records.

    Structural ceiling, stated rather than discovered. ``status`` is
    ``"expected_complete"`` with ``expected_daily_cardinality=1``, and upstream
    that means literally every calendar day between the first and last returned
    session carries exactly one session:
    ``drift.markets.session_validation`` walks ``while current <= end_date``
    and applies no exception-date skip, so ``exception_dates`` cannot buy back
    a gap and populating it would change nothing. ``generate_schedule`` in turn
    refuses any coverage row whose status is not ``"expected_complete"``, so
    downgrading the status to ``"partial"`` would stop the pipeline instead of
    widening it. The consequence is that this bridge supports exactly one
    unbroken run of consecutive session days, in practice a single Monday to
    Friday week: a two-week window such as 2026-01-05 to 2026-01-16 contains
    the 01-10 and 01-11 weekend, which no calendar row covers. That case is
    refused here, by name, rather than surfacing later as an opaque
    ``session_coverage_daily_cardinality_mismatch`` from the validator.
    """
    rows = tuple(
        item
        for item in scheduled.records
        if isinstance(item, ScheduledSessionVersionV1)
    )
    if not rows:
        raise AlpacaBridgeIncompleteError("calendar snapshot carries no session rows")
    dates = tuple(item.session_key.local_date for item in rows)
    ordered = tuple(sorted(set(dates)))
    if len(ordered) != len(dates):
        raise AlpacaBridgeIncompleteError(
            "the calendar snapshot repeats a session date, so it cannot claim "
            "one session per day"
        )
    gaps = tuple(
        (ordered[0] + timedelta(days=offset)).isoformat()
        for offset in range((ordered[-1] - ordered[0]).days + 1)
        if ordered[0] + timedelta(days=offset) not in set(ordered)
    )
    if gaps:
        raise AlpacaBridgeIncompleteError(
            "this bridge can only claim dense session coverage over one "
            "unbroken run of consecutive calendar days, and the acquired "
            f"snapshot skips {gaps}; widen the window only once upstream "
            "session coverage honours exception dates"
        )
    seed = f"coverage:{request.mic}:{request.cohort_id}"
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": _revision(
            logical_seed=seed,
            version_seed=f"{seed}:0",
            availability=_observed_availability(
                request.acquired_at, retained.calendar_hash, f"{seed}:available"
            ),
            source_digest=retained.calendar_hash,
        ),
        "source_id": ALPACA_CALENDAR_SOURCE_ID,
        "native_record_id": f"calendar:{request.start_date}:{request.end_date}",
        "mic": request.mic,
        "session_scope": "regular",
        "start_date": min(dates),
        "end_date": max(dates),
        "snapshot_identifier": f"alpaca-calendar-{request.acquired_at.isoformat()}",
        "snapshot_as_of": _exact_boundary(
            request.acquired_at, retained.calendar_hash, f"{seed}:snapshot"
        ),
        "covered_dataset_hashes": (manifest_hash(scheduled.manifest),),
        "covered_partition_hashes": tuple(sorted(scheduled.artifacts)),
        "record_inventory": tuple(
            sorted(
                (
                    SessionInventoryEntryV1(
                        schema_version="1",
                        assertion_id=item.revision.logical_record_id,
                        version_id=item.revision.record_version_id,
                        record_hash=content_hash(item),
                    )
                    for item in rows
                ),
                key=lambda entry: (str(entry.assertion_id), str(entry.version_id)),
            )
        ),
        "expected_daily_cardinality": 1,
        "exception_dates": (),
        "methodology_hash": methodology_hash,
        "status": "expected_complete",
        "missing_artifact_hashes": (),
        "revision_history_completeness": "complete",
    }
    return _seal(SessionCoverageVersionV1, values)


def _source_selection_policy(
    request: AlpacaIntakeRequest,
    contract: ObservationContractV1,
    observations: M1dDatasetInput[Any],
    scheduled: M1dDatasetInput[Any],
    coverage: M1dDatasetInput[Any],
    methodology_hash: str,
) -> ObservationSourceSelectionPolicyV1:
    bindings: list[ObservationSourceBindingV1] = []
    for member in request.members:
        bindings.append(
            ObservationSourceBindingV1(
                schema_version="1",
                dataset_role="source_observation",
                source_id=ALPACA_BAR_SOURCE_ID,
                contract_hash=content_hash(contract),
                venue=member.venue,
                listing_id=member.listing_id,
                start_date=request.start_date,
                end_date=request.end_date,
                manifest_hashes=(manifest_hash(observations.manifest),),
                methodology_hashes=(contract.methodology_artifact_hash,),
            )
        )
        bindings.append(
            ObservationSourceBindingV1(
                schema_version="1",
                dataset_role="scheduled_session",
                source_id=ALPACA_CALENDAR_SOURCE_ID,
                contract_hash=None,
                venue=member.venue,
                listing_id=member.listing_id,
                start_date=request.start_date,
                end_date=request.end_date,
                manifest_hashes=(manifest_hash(scheduled.manifest),),
                methodology_hashes=(methodology_hash,),
            )
        )
        bindings.append(
            ObservationSourceBindingV1(
                schema_version="1",
                dataset_role="session_coverage",
                source_id=ALPACA_CALENDAR_SOURCE_ID,
                contract_hash=None,
                venue=member.venue,
                listing_id=member.listing_id,
                start_date=request.start_date,
                end_date=request.end_date,
                manifest_hashes=(manifest_hash(coverage.manifest),),
                methodology_hashes=(methodology_hash,),
            )
        )
    return ObservationSourceSelectionPolicyV1(
        schema_version="1",
        policy_id="alpaca-exploratory-source-authority",
        version="1",
        bindings=tuple(bindings),
    )


def _outcome_query(
    member: AlpacaCohortMember,
    session_date: date,
    request: AlpacaIntakeRequest,
    contract: ObservationContractV1,
    source_policy_hash: str,
    availability_policy: AvailabilityPolicyV1,
    context_hash: str,
) -> ObservationOutcomeQueryV1:
    return ObservationOutcomeQueryV1(
        schema_version="1",
        kind="outcome",
        economic_horizon=request.evidence_vintage_cutoff,
        evidence_vintage_cutoff=request.evidence_vintage_cutoff,
        listing_id=member.listing_id,
        security_id=member.security_id,
        venue=member.venue,
        session_date=session_date,
        source_id=ALPACA_BAR_SOURCE_ID,
        contract_hash=content_hash(contract),
        source_selection_policy_hash=source_policy_hash,
        profile_hash=regular_session_trade_bar_profile_hash(),
        requested_channel=_channel(),
        availability_policy_id=availability_policy.policy_id,
        availability_policy_hash=content_hash(availability_policy),
        input_context_hash=context_hash,
    )


# --- step 6 and 7: reconstruction, clock, bundle, admission -----------------------


def build_bridge_cohort(
    request: AlpacaIntakeRequest,
) -> ExploratoryCohortAuthorizationV1:
    """Mint the predeclared bounded cohort authorization for this run."""
    draft = ExploratoryCohortAuthorizationV1.model_construct(
        schema_version="1",
        kind="predeclared_bounded_security_cohort",
        cohort_id=request.cohort_id,
        cohort_version=request.cohort_version,
        security_ids=tuple(
            sorted((member.security_id for member in request.members), key=str)
        ),
        cohort_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"cohort_hash": cohort_authorization_hash(draft)}
    )
    return ExploratoryCohortAuthorizationV1.model_validate(candidate.model_dump())


def build_bridge_reconstruction_policy() -> ExploratoryReconstructionPolicyV1:
    """Mint the fixed source-basis scheduled reconstruction policy."""
    draft = ExploratoryReconstructionPolicyV1.model_construct(
        schema_version="1",
        policy_id="alpaca-exploratory-source-basis-reconstruction",
        policy_version="1",
        mode="source_basis_scheduled_session_reconstruction_v1",
        required_fields=REQUIRED_RECONSTRUCTION_FIELDS,
        required_basis="unadjusted",
        semantic_policy_hash=exploratory_reconstruction_semantic_hash(),
        policy_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"policy_hash": reconstruction_policy_hash(draft)}
    )
    return ExploratoryReconstructionPolicyV1.model_validate(candidate.model_dump())


def build_bridge_admission(
    *,
    bundle: EvaluationInputBundleV1,
    lane: BridgeLane = "exploratory",
) -> ExploratoryEvaluationAdmissionV1:
    """Mint the exploratory admission binding all six Alpaca limitations.

    ``lane="promotion"`` is refused. This bridge cannot emit a
    ``PromotionEvaluationAdmissionV1`` under any circumstance: promotion
    requires a new evaluation over an accepted M1e-qualified dataset.
    """
    if lane != "exploratory":
        raise AlpacaBridgeProhibitedError(
            "the Alpaca bridge is exploratory-only and cannot emit a "
            "PromotionEvaluationAdmissionV1"
        )
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=ALPACA_EXPLORATORY_LIMITATIONS,
        admission_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )
    admission = ExploratoryEvaluationAdmissionV1.model_validate(candidate.model_dump())
    validate_exploratory_admission(admission=admission, bundle=bundle)
    return admission


@dataclass(frozen=True, slots=True)
class AlpacaExploratoryIntakeResult:
    """Every artifact the bounded Alpaca intake produced, in pipeline order."""

    retained: RetainedNativeBytes
    acquisition: AlpacaAcquisitionEvidence
    securities: tuple[SecurityV1, ...]
    listings: tuple[ListingV1, ...]
    observation_contract: ObservationContractV1
    validation_decisions: tuple[DatasetValidationDecisionV2, ...]
    economic_terms: AlpacaEconomicTermsDataset
    context: M1dResolutionContext
    cohort: ExploratoryCohortAuthorizationV1
    reconstruction_policy: ExploratoryReconstructionPolicyV1
    outcome_queries: tuple[ObservationOutcomeQueryV1, ...]
    reconstruction_replay: ExploratoryReconstructionReplay
    reconstructions: tuple[ExploratoryReconstructedSessionObservationV1, ...]
    session_clock: SessionClockV1
    bundle: EvaluationInputBundleV1
    admission: ExploratoryEvaluationAdmissionV1


def run_alpaca_exploratory_intake(
    *,
    request: AlpacaIntakeRequest,
    payloads: AlpacaNativePayloads,
    private_root: Path,
    authentic_decision_views: tuple[DerivedObservationViewV1, ...] = (),
    authentic_accounting_views: tuple[DerivedObservationViewV1, ...] = (),
) -> AlpacaExploratoryIntakeResult:
    """Run the complete layered Alpaca exploratory pipeline, offline.

    ``authentic_decision_views`` and ``authentic_accounting_views`` exist only to
    be refused. A caller cannot smuggle hand-built derived views into a bundle
    through this bridge, and the bridge itself never materializes any, because
    Alpaca publishes no realized session evidence for M1d to bind against.
    """
    if authentic_decision_views or authentic_accounting_views:
        raise AlpacaBridgeProhibitedError(
            "the Alpaca bridge cannot place caller-supplied derived views into an "
            "evaluation bundle; views come only from exact M1d replay"
        )

    retained = retain_native_bytes(private_root, payloads)
    acquisition = build_alpaca_acquisition_evidence(request, retained)
    if acquisition.reconciliation.result is not AcquisitionCompleteness.PASS:
        raise AlpacaBridgeIncompleteError(
            "closed-world acquisition reconciliation did not pass: "
            f"{acquisition.reconciliation.result.value} "
            f"{acquisition.reconciliation.reasons}"
        )

    bars = parse_alpaca_bars(payloads.bars)
    calendar = parse_alpaca_calendar(payloads.calendar)
    dividends = parse_alpaca_cash_dividends(payloads.corporate_actions)

    securities, listings = map_cohort_identities(request)
    contract, support_seed = build_alpaca_observation_contract(request)
    support: dict[str, VerifiedArtifactBytes] = dict(support_seed)
    retained_evidence: dict[str, AvailabilityEvidenceV1] = {}
    support.update(retained.artifacts)

    methodology_hash = _timezone_support(request, support, retained_evidence)
    schedule_rows = tuple(
        map_calendar_day(
            day, request, methodology_hash, retained, support, retained_evidence
        )
        for day in calendar
    )
    schedule_policy = _schedule_policy(request, support, methodology_hash)
    policy_artifact = _verified(canonical_json(schedule_policy))
    support[policy_artifact.content_hash] = policy_artifact

    bounds = _session_bounds(schedule_rows, request)
    observation_records: list[DailySourceObservationVersionV1] = []
    for bar in bars:
        member = request.member_for(bar.symbol)
        window = bounds.get(bar.session_date)
        if window is None:
            raise AlpacaBridgeIncompleteError(
                f"bar for {bar.symbol} on {bar.session_date} has no scheduled session"
            )
        record, record_artifact = map_native_bar(
            bar, member, request, contract, window, retained
        )
        support[record_artifact.content_hash] = record_artifact
        observation_records.append(record)
    if not observation_records:
        raise AlpacaBridgeIncompleteError("the bounded window returned no bars")

    terms = tuple(
        map_cash_dividend(
            dividend, request.member_for(dividend.symbol), request, retained
        )
        for dividend in dividends
    )

    observations = _observation_dataset(
        tuple(observation_records), request, support, retained
    )
    scheduled = _session_dataset(
        "scheduled_session", schedule_rows, request, support, retained
    )
    coverage_row = _coverage_record(scheduled, request, methodology_hash, retained)
    coverage = _session_dataset(
        "session_coverage", (coverage_row,), request, support, retained
    )
    economic_terms = _economic_terms_dataset(terms, request, retained)

    source_policy = _source_selection_policy(
        request, contract, observations, scheduled, coverage, methodology_hash
    )
    source_policy_artifact = _verified(canonical_json(source_policy))
    support[source_policy_artifact.content_hash] = source_policy_artifact

    availability_policy = AvailabilityPolicyV1(
        policy_id="alpaca-exploratory-public-exact", permitted_rule_hashes=()
    )
    context = M1dResolutionContext(
        observation_datasets=(observations,),
        session_datasets=(scheduled, coverage),
        availability_policies={content_hash(availability_policy): availability_policy},
        retained_evidence=retained_evidence,
        supporting_artifacts=support,
        schedule_generation_policy_hash=policy_artifact.content_hash,
    )
    context_hash = m1d_context_hash(context)

    cohort = build_bridge_cohort(request)
    reconstruction_policy = build_bridge_reconstruction_policy()
    session_dates = tuple(sorted(bounds))
    queries = tuple(
        _outcome_query(
            member,
            session_date,
            request,
            contract,
            source_policy_artifact.content_hash,
            availability_policy,
            context_hash,
        )
        for member in request.members
        for session_date in session_dates
    )
    reconstruction_replay = ExploratoryReconstructionReplay(
        policy=reconstruction_policy,
        requests=tuple((query, context) for query in queries),
    )

    clock_queries: tuple[ObservationQueryV1, ...] = tuple(
        query
        for query in queries
        if query.security_id == request.members[0].security_id
    )
    session_clock = build_scheduled_reconstruction_clock(clock_queries, context)

    first = session_clock.sessions[0]
    last = session_clock.sessions[-1]
    interval = TemporalIntervalClaimV1(
        schema_version="1",
        start=_exact_boundary(
            first.opened_at, retained.calendar_hash, "interval:start"
        ),
        end=_exact_boundary(last.closed_at, retained.calendar_hash, "interval:end"),
    )
    bundle = build_evaluation_input_bundle(
        evaluation_interval=interval,
        session_clock=session_clock,
        context=context,
        decision_requests=(),
        accounting_requests=(),
        security_identities=securities,
        listing_identities=listings,
        structural_eligibilities=(),
        economic_outcomes=(),
        exploratory_cohort=cohort,
        exploratory_reconstruction_replay=reconstruction_replay,
        source_snapshot_hash=None,
    )
    admission = build_bridge_admission(bundle=bundle)

    return AlpacaExploratoryIntakeResult(
        retained=retained,
        acquisition=acquisition,
        securities=securities,
        listings=listings,
        observation_contract=contract,
        validation_decisions=(
            observations.decision,
            scheduled.decision,
            coverage.decision,
            economic_terms.decision,
        ),
        economic_terms=economic_terms,
        context=context,
        cohort=cohort,
        reconstruction_policy=reconstruction_policy,
        outcome_queries=queries,
        reconstruction_replay=reconstruction_replay,
        reconstructions=bundle.exploratory_reconstructed_observations,
        session_clock=session_clock,
        bundle=bundle,
        admission=admission,
    )


def _session_bounds(
    rows: Sequence[ScheduledSessionVersionV1], request: AlpacaIntakeRequest
) -> dict[date, tuple[datetime, datetime]]:
    """Derive exact scheduled UTC bounds from attested local labels and offsets."""
    bounds: dict[date, tuple[datetime, datetime]] = {}
    for row in rows:
        local_date = row.session_key.local_date
        offsets = {
            item.boundary: item.utc_offset_seconds
            for item in row.historical_boundary_offsets
        }
        if row.local_open is None or row.local_close is None:
            continue
        open_offset = offsets.get("open")
        close_offset = offsets.get("close")
        if open_offset is None or close_offset is None:
            raise AlpacaBridgeIncompleteError(
                f"scheduled session {local_date} lacks an attested UTC offset"
            )
        opened = datetime.fromisoformat(row.local_open).replace(tzinfo=UTC) - timedelta(
            seconds=open_offset
        )
        closed = datetime.fromisoformat(row.local_close).replace(
            tzinfo=UTC
        ) - timedelta(seconds=close_offset)
        if closed <= opened:
            raise AlpacaBridgeIncompleteError(
                f"scheduled session {local_date} does not close after it opens"
            )
        if request.start_date <= local_date <= request.end_date:
            bounds[local_date] = (opened, closed)
    return bounds


# --- architecture boundary --------------------------------------------------------

#: Every package the Drift core is made of. A package named here has to exist:
#: a silently skipped directory is a silently skipped scan.
_CORE_PACKAGES: tuple[str, ...] = (
    "config",
    "datasets",
    "domain",
    "evaluator",
    "ledger",
    "markets",
    "qualification",
    "serialization",
)
#: The only package under the Drift root that is allowed to be an adapter.
_ADAPTER_PACKAGE = "adapters"


def assert_core_isolation(package_root: Path | None = None) -> None:
    """Refuse an installed tree in which the Drift core imports this bridge.

    The bridge depends on the core. The core must never depend on the bridge,
    because a provider adapter inside the evaluation path would let vendor
    quirks reach evidence semantics. This is checked against the exact installed
    source rather than trusted by convention.

    The scan covers every module under the Drift root except the adapter
    package itself, which includes top-level modules such as ``errors.py`` that
    almost everything imports, and it includes packages added after this list
    was written. A declared core package that is absent is a failure, not a
    reason to scan less.
    """
    root = (
        Path(__file__).resolve().parent.parent if package_root is None else package_root
    )
    absent = tuple(name for name in _CORE_PACKAGES if not (root / name).is_dir())
    if absent:
        raise AlpacaBridgeProhibitedError(
            "the Drift core isolation scan cannot be trusted because these "
            f"declared core packages are absent from {root}: {absent}"
        )
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == _ADAPTER_PACKAGE:
            continue
        if _imports_adapters(path):
            offenders.append(relative.as_posix())
    if offenders:
        raise AlpacaBridgeProhibitedError(
            "the Drift core must not import drift.adapters, but these modules do: "
            f"{tuple(sorted(offenders))}"
        )


def _imported_module_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return every module path one import statement can reach.

    ``from .. import adapters`` and ``from drift import adapters`` both name
    the adapter package through an alias rather than through ``node.module``,
    and a relative import has no module prefix at all, so the alias names are
    expanded here instead of being dropped.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    names: list[str] = []
    if node.module:
        names.append(node.module)
        names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    if node.level:
        names.extend(alias.name for alias in node.names)
    return names


def _imports_adapters(path: Path) -> bool:
    tree = ast.parse(path.read_bytes(), str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for name in _imported_module_names(node):
            parts = name.split(".")
            if parts[:2] == ["drift", _ADAPTER_PACKAGE] or parts[:1] == [
                _ADAPTER_PACKAGE
            ]:
                return True
    return False
