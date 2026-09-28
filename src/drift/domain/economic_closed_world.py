"""Evidence-bearing closed-world corporate-action coverage for M1c (issue 76).

Owner ruling on #76, option A. "No action row is not evidence of no action"
(the M1 design spec, section 6), so an evaluator that finds no corporate-action
record for a held security learns nothing. ``ClosedWorldCorporateActionCoverageV1``
is the evidence that tells "no action" apart from "no record". One record
describes one retained provider response for one security and binds, in one
self-hashed record:

* the requested interval and the requested action classes, and the
  acquisition request that declared them;
* the exact retained response bytes (SHA-256 and size) and the measured origin
  record taken over exactly those bytes;
* every action the response returned that is attributed to the security, each
  with every date it carries (``ReturnedCorporateActionV1``);
* a completeness assertion (``CorporateActionCompletenessAssertionV1``);
* the covered interval, which in V1 is the requested interval (decision D2-a),
  never starting before ``REST_CORPORATE_ACTION_EVIDENCE_FLOOR`` (the D2
  addition) and never ending after the snapshot date;
* the grade of the source, which in V1 is exploratory only (decision D3-b),
  a current snapshot with no revision history, and the limitation every
  admission of such evidence must acknowledge.

The record is a sibling of ``EconomicCoverageVersionV1``, not a relaxation of
it: that record's ``complete`` still needs captured revision history and a
coverage owner per fact family, and nothing here changes how M1c resolves an
outcome. The derivation rule, the builder that stamps the record and its
verification live in ``drift.markets.economic_closed_world``.

Every check here is an integrity check. A record that fails one is refused
with its contract code in the message, never downgraded to INDETERMINATE.
"""

from datetime import date, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_common import ActionKind
from drift.serialization.canonical import content_hash

CORPORATE_ACTION_SNAPSHOT_LIMITATION = (
    "corporate-action-absence-read-from-current-provider-snapshot"
)
"""The limitation every closed-world corporate-action reading carries (D3).

A V1 record reads the absence of an action from one current provider
snapshot, with no revision history, so every record, every bundle carrying one
and every admission of such a bundle names it. ``drift.domain.evaluator_lanes``
re-exports it as ``LIMITATION_CA_ABSENCE_FROM_CURRENT_SNAPSHOT``."""

REST_CORPORATE_ACTION_EVIDENCE_FLOOR = date(2021, 8, 2)
"""The earliest date a V1 record may cover (decision D2, addition).

Cited from ``docs/architecture/m1e-provider-selection.md``, section 3 (Alpaca),
"Rich Corporate Actions REST": the earliest action date the repository holds
provider evidence of a REST corporate-action response returning is the GE
1-for-8 reverse split, ``ex_date: 2021-08-02``. Every other cited REST case is
later. The SSE mutation stream's retained history, which starts 2026-07-09, is
provider assertion (knowledge) time and does not bound event coverage. A date
before this floor is never covered, so it is INDETERMINATE."""

_DERIVATION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "closed_world_corporate_action_response_v1",
    "covered_interval": (
        "requested_interval_clipped_to_evidence_floor_and_snapshot_date"
    ),
    "evidence_floor": REST_CORPORATE_ACTION_EVIDENCE_FLOOR.isoformat(),
    "returned_action_in_window": "actions_present_on_any_returned_date",
    "undated_returned_action": "indeterminate_in_every_covered_window",
    "uncovered_date": "indeterminate_never_no_action",
    "covered_quiet_window": "evidenced_no_action_under_positive_assertion_only",
    "overlap_disagreement": "indeterminate_never_resolved_by_preference",
    "union": "one_source_and_grade_per_security",
}

type CorporateActionCompletenessBasis = Literal[
    "provider_published",
    "provider_partially_published",
    "drift_asserted_unpublished",
]

CORPORATE_ACTION_POSITIVE_BASES: frozenset[str] = frozenset(
    {"provider_published", "provider_partially_published"}
)
"""The bases an exploratory-grade assertion may rest on and still evidence.

A basis that is only Drift's own unpublished assertion is valid data, but it
evidences no absence: every window it covers stays INDETERMINATE."""

CORPORATE_ACTION_COVERAGE_DOMAIN_CODES: tuple[str, ...] = (
    "ca_coverage_action_classes_incomplete",
    "ca_coverage_derivation_mismatch",
    "ca_coverage_grade_exceeds_source",
    "ca_coverage_interval_invalid",
    "ca_coverage_limitations_invalid",
    "ca_coverage_record_hash_mismatch",
    "ca_coverage_returned_actions_invalid",
    "ca_coverage_snapshot_invalid",
)
"""Every integrity code the record's own validation can raise."""


def corporate_action_derivation_algorithm_hash() -> SHA256Hash:
    """Return the static semantic identity of the V1 derivation rule."""
    return content_hash(_DERIVATION_ALGORITHM_V1)


def corporate_action_snapshot_date(snapshot: TemporalBoundaryClaimV1) -> date:
    """The UTC calendar date of an exact acquisition instant."""
    instant = snapshot.upper_bound
    if instant is None:
        raise ValueError(
            "ca_coverage_snapshot_invalid: the snapshot is the exact acquisition "
            "instant"
        )
    return instant.date()


def corporate_action_covered_interval(
    requested_start: date,
    requested_end: date,
    snapshot: TemporalBoundaryClaimV1,
) -> tuple[date, date] | None:
    """The V1 covered interval (D2-a): the requested interval, clipped.

    It never starts before ``REST_CORPORATE_ACTION_EVIDENCE_FLOOR`` and never
    ends after the snapshot date. ``None`` when that leaves nothing covered.
    """
    start = max(requested_start, REST_CORPORATE_ACTION_EVIDENCE_FLOOR)
    end = min(requested_end, corporate_action_snapshot_date(snapshot))
    if start > end:
        return None
    return start, end


class ReturnedCorporateActionV1(FrozenModel):
    """One action a provider response returned, attributed to one security.

    ``native_kind`` is the provider's own group name and ``native_id`` its own
    identifier. ``action_kind`` is the M1c kind the group corresponds to where
    that correspondence is exact, and ``None`` otherwise; no consumer rule
    reads it. ``dates`` is every date the provider printed on the action,
    sorted and unique. It may be empty, and an undated action can lie in any
    window.
    """

    schema_version: Literal["1"] = "1"
    native_kind: NonBlankStr
    native_id: NonBlankStr
    action_kind: ActionKind | None
    dates: tuple[date, ...]

    @field_validator("dates")
    @classmethod
    def require_canonical_dates(cls, values: tuple[date, ...]) -> tuple[date, ...]:
        if len(set(values)) != len(values) or tuple(sorted(values)) != values:
            raise ValueError(
                "ca_coverage_returned_actions_invalid: a returned action's dates "
                "must be sorted and unique"
            )
        return values


class CorporateActionCompletenessAssertionV1(FrozenModel):
    """What was checked before a response is read as closed-world.

    ``basis`` mirrors the provider publication status of the retained policy
    statement ``policy_statement_hash`` names. Each structural flag records
    one check made over the acquisition: the response is one unpaginated page;
    its origin was measured; the measured request named every action type the
    provider documents; every returned action is attributed; and every
    returned action carries a date inside the requested interval, which is
    what the assumed filter semantics predict. The assertion is positive only
    if every flag holds and the basis is one ``CORPORATE_ACTION_POSITIVE_BASES``
    accepts.
    """

    schema_version: Literal["1"] = "1"
    basis: CorporateActionCompletenessBasis
    policy_statement_hash: SHA256Hash
    acquisition_reconciliation_pass: Literal[True]
    single_unpaginated_response: bool
    measured_origin: bool
    requested_types_documented: bool
    returned_actions_attributed: bool
    returned_actions_inside_requested_window: bool

    @property
    def positive(self) -> bool:
        """Whether this assertion lets a covered, quiet window evidence no action."""
        return (
            self.basis in CORPORATE_ACTION_POSITIVE_BASES
            and self.acquisition_reconciliation_pass is True
            and self.single_unpaginated_response
            and self.measured_origin
            and self.requested_types_documented
            and self.returned_actions_attributed
            and self.returned_actions_inside_requested_window
        )


class ClosedWorldCorporateActionCoverageV1(FrozenModel):
    """One provider-neutral closed-world reading of one response for one security."""

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    security_id: UUID7
    queried_symbol: NonBlankStr
    requested_start_date: date
    requested_end_date: date
    requested_action_classes: tuple[NonBlankStr, ...]
    request_binding_hash: SHA256Hash
    response_sha256: SHA256Hash
    response_byte_size: Annotated[int, Field(ge=0)]
    origin_observation_hash: SHA256Hash
    returned_actions: tuple[ReturnedCorporateActionV1, ...]
    completeness: CorporateActionCompletenessAssertionV1
    covered_start_date: date | None
    covered_end_date: date | None
    snapshot_as_of: TemporalBoundaryClaimV1
    revision_support: Literal["current_only"]
    evidence_grade: Literal["exploratory"]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    derivation_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash
    record_hash: SHA256Hash

    @field_validator("evidence_grade", mode="before")
    @classmethod
    def refuse_a_grade_above_the_source(cls, value: object) -> object:
        if value != "exploratory":
            raise ValueError(
                "ca_coverage_grade_exceeds_source: V1 closed-world corporate-action "
                "coverage inherits the exploratory grade of its source and can "
                f"carry no other grade, got {value!r}"
            )
        return value

    @field_validator("revision_support", mode="before")
    @classmethod
    def refuse_revision_history_the_source_lacks(cls, value: object) -> object:
        if value != "current_only":
            raise ValueError(
                "ca_coverage_grade_exceeds_source: a V1 record reads one current "
                "provider snapshot and can claim no revision history, got "
                f"{value!r}"
            )
        return value

    @field_validator("requested_action_classes")
    @classmethod
    def require_canonical_action_classes(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if (
            not values
            or len(set(values)) != len(values)
            or tuple(sorted(values)) != values
        ):
            raise ValueError(
                "ca_coverage_action_classes_incomplete: the requested action "
                "classes must be nonempty, sorted and unique"
            )
        return values

    @field_validator("returned_actions")
    @classmethod
    def require_canonical_returned_actions(
        cls, values: tuple[ReturnedCorporateActionV1, ...]
    ) -> tuple[ReturnedCorporateActionV1, ...]:
        keys = tuple((item.native_kind, item.native_id) for item in values)
        if len(set(keys)) != len(keys) or tuple(sorted(keys)) != keys:
            raise ValueError(
                "ca_coverage_returned_actions_invalid: returned actions must be "
                "sorted and unique by native kind and native id"
            )
        return values

    @field_validator("acknowledged_limitations")
    @classmethod
    def require_the_snapshot_limitation(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if (
            CORPORATE_ACTION_SNAPSHOT_LIMITATION not in values
            or len(set(values)) != len(values)
            or tuple(sorted(values)) != values
        ):
            raise ValueError(
                "ca_coverage_limitations_invalid: a record's limitations must be "
                "sorted, unique and name "
                f"{CORPORATE_ACTION_SNAPSHOT_LIMITATION}"
            )
        return values

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        snapshot = self.snapshot_as_of
        if (
            snapshot.shape is not BoundaryShape.EXACT
            or snapshot.lower_bound is None
            or snapshot.lower_bound != snapshot.upper_bound
        ):
            raise ValueError(
                "ca_coverage_snapshot_invalid: the snapshot is the exact "
                "acquisition instant"
            )
        if self.requested_start_date > self.requested_end_date:
            raise ValueError(
                "ca_coverage_interval_invalid: the requested interval is reversed"
            )
        self._validate_covered_interval()
        if self.derivation_algorithm_hash != (
            corporate_action_derivation_algorithm_hash()
        ):
            raise ValueError(
                "ca_coverage_derivation_mismatch: the record names a derivation "
                "rule other than closed_world_corporate_action_response_v1"
            )
        if self.record_hash != corporate_action_record_hash(self):
            raise ValueError(
                "ca_coverage_record_hash_mismatch: the record hash does not cover "
                "the record's own fields"
            )
        return self

    def _validate_covered_interval(self) -> None:
        """V2 and D2: the covered interval is the requested one, clipped exactly."""
        expected = corporate_action_covered_interval(
            self.requested_start_date, self.requested_end_date, self.snapshot_as_of
        )
        stated = (
            None
            if self.covered_start_date is None and self.covered_end_date is None
            else (self.covered_start_date, self.covered_end_date)
        )
        if stated != expected:
            floor = REST_CORPORATE_ACTION_EVIDENCE_FLOOR.isoformat()
            raise ValueError(
                "ca_coverage_interval_invalid: the V1 covered interval is the "
                f"requested interval {self.requested_start_date.isoformat()} to "
                f"{self.requested_end_date.isoformat()}, never starting before "
                f"the evidence floor {floor} and never ending after the snapshot "
                f"date, which is {_interval_text(expected)}; the record states "
                f"{_interval_text(stated)}"
            )


def _interval_text(interval: tuple[date | None, date | None] | None) -> str:
    if interval is None:
        return "no covered interval"
    start, end = interval
    return (
        f"{'none' if start is None else start.isoformat()} to "
        f"{'none' if end is None else end.isoformat()}"
    )


def corporate_action_record_hash(
    record: ClosedWorldCorporateActionCoverageV1,
) -> SHA256Hash:
    """Return the self-excluding canonical hash of one record."""
    dump = record.model_dump(mode="python", warnings=False)
    dump.pop("record_hash", None)
    return content_hash(dump)


def covered_dates(record: ClosedWorldCorporateActionCoverageV1) -> tuple[date, ...]:
    """Every date the record's covered interval holds, in order."""
    if record.covered_start_date is None or record.covered_end_date is None:
        return ()
    span = (record.covered_end_date - record.covered_start_date).days
    return tuple(
        record.covered_start_date + timedelta(days=offset) for offset in range(span + 1)
    )
