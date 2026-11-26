"""Evidence-bearing closed-world session coverage for M1d (issue 71).

Ruling Q18 of #62, option (b). A scheduled calendar that simply omits a date
says nothing on its own: the date might be a non-trading date, or it might be
missing data ("Missing date in unproven calendar list: Unknown, not closed").
``ClosedWorldSessionCoverageV1`` is the evidence that tells the two apart. It
binds, in one self-hashed record:

* the requested interval, and the acquisition request that declared it;
* the exact retained response bytes (SHA-256 and size) and the measured
  origin record taken over exactly those bytes;
* the returned date set, sorted, unique and inside the requested interval;
* a completeness assertion (``ClosedWorldCompletenessAssertionV1``);
* the covered interval, which in V1 is the bracketed hull of the returned
  dates (decision D2-b), so head or tail truncation of the response can never
  be read as a run of closures;
* the grade of the source, which in V1 is exploratory only (D3-a), and the
  M1d evidence identity the record was derived under (D5-a);
* the closed-row template, so the materialization into explicit closed
  ``ScheduledSessionVersionV1`` rows is a pure function of the record bytes.

The derivation rule is: a covered date that was not returned is an evidenced
non-trading date, but only under a positive assertion; a returned date is
schedule evidence of an open date, never a realized session; every other date
is INDETERMINATE and never defaults to closed. The rule itself, its
materialization and its context verification live in
``drift.markets.session_closed_world``.

Every check here is an integrity check. A record that fails one is refused
with its code in the message, never downgraded to INDETERMINATE.
"""

from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.temporal import AvailabilityChannelV1
from drift.serialization.canonical import content_hash

CLOSED_WORLD_RECORD_KIND = "drift-m1d-closed-world-session-coverage"
"""The discriminator every record's canonical bytes carry.

Bytes that carry it claim to be a record and must then be a valid one; bytes
that do not carry it make no claim at all."""

_CLOSED_WORLD_DERIVATION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "closed_world_calendar_response_v1",
    "covered_interval": "bracketed_hull_of_returned_dates_inside_requested_interval",
    "returned_date": "scheduled_open_schedule_evidence_only",
    "covered_unreturned_date": "evidenced_non_trading_under_positive_assertion",
    "every_other_date": "indeterminate_never_closed",
    "overlap_disagreement": "indeterminate_never_resolved_by_preference",
    "union": "same_source_mic_and_grade_only",
    "materialization": "explicit_closed_rows_bound_to_record_bytes",
}

type ClosedWorldBasis = Literal[
    "provider_published",
    "provider_partially_published",
    "drift_asserted_unpublished",
]

CLOSED_WORLD_POSITIVE_BASES: frozenset[str] = frozenset(
    {"provider_published", "provider_partially_published"}
)
"""The bases an exploratory-grade assertion may rest on and still derive.

A basis that is only Drift's own unpublished assertion is valid data, but it
derives no non-trading date: every covered date that was not returned stays
INDETERMINATE."""

CLOSED_WORLD_DOMAIN_CODES: tuple[str, ...] = (
    "closed_world_derivation_mismatch",
    "closed_world_grade_exceeds_source",
    "closed_world_interval_invalid",
    "closed_world_record_hash_mismatch",
    "closed_world_returned_dates_invalid",
    "closed_world_snapshot_invalid",
)
"""Every integrity code the record's own validation can raise."""


def closed_world_derivation_algorithm_hash() -> str:
    """Return the static semantic identity of the V1 derivation rule."""
    return content_hash(_CLOSED_WORLD_DERIVATION_ALGORITHM_V1)


class ClosedWorldCompletenessAssertionV1(FrozenModel):
    """What was checked before a calendar response is read as closed-world.

    ``basis`` mirrors the provider publication status of the retained policy
    statement ``policy_statement_hash`` names. Each structural flag records
    one check that held over the acquisition: the returned dates are unique,
    lie inside the requested interval, came from one unpaginated response, and
    were measured at their origin. The assertion is positive only if every
    flag holds and the basis is one ``CLOSED_WORLD_POSITIVE_BASES`` accepts.
    """

    schema_version: Literal["1"] = "1"
    basis: ClosedWorldBasis
    policy_statement_hash: SHA256Hash
    acquisition_reconciliation_pass: Literal[True]
    returned_dates_unique: bool
    returned_dates_inside_requested_interval: bool
    single_unpaginated_response: bool
    measured_origin: bool

    @property
    def positive(self) -> bool:
        """Whether this assertion lets covered, unreturned dates derive."""
        return (
            self.basis in CLOSED_WORLD_POSITIVE_BASES
            and self.acquisition_reconciliation_pass is True
            and self.returned_dates_unique
            and self.returned_dates_inside_requested_interval
            and self.single_unpaginated_response
            and self.measured_origin
        )


class ClosedWorldSessionCoverageV1(FrozenModel):
    """One provider-neutral closed-world reading of one calendar response."""

    schema_version: Literal["1"] = "1"
    kind: Literal["drift-m1d-closed-world-session-coverage"] = (
        "drift-m1d-closed-world-session-coverage"
    )
    source_id: NonBlankStr
    mic: NonBlankStr
    session_scope: Literal["regular"]
    requested_start_date: date
    requested_end_date: date
    request_binding_hash: SHA256Hash
    response_sha256: SHA256Hash
    response_byte_size: Annotated[int, Field(ge=0)]
    origin_observation_hash: SHA256Hash
    returned_dates: tuple[date, ...]
    completeness: ClosedWorldCompletenessAssertionV1
    covered_start_date: date
    covered_end_date: date
    snapshot_as_of: TemporalBoundaryClaimV1
    timezone_identifier: NonBlankStr
    source_methodology_hash: SHA256Hash
    availability_channel: AvailabilityChannelV1
    evidence_grade: Literal["exploratory"]
    derivation_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash
    record_hash: SHA256Hash

    @field_validator("mic")
    @classmethod
    def require_mic_shape(cls, value: str) -> str:
        if len(value) != 4 or value != value.upper():
            raise ValueError("MIC must be an exact four-character uppercase code")
        return value

    @field_validator("evidence_grade", mode="before")
    @classmethod
    def refuse_a_grade_above_the_source(cls, value: object) -> object:
        if value != "exploratory":
            raise ValueError(
                "closed_world_grade_exceeds_source: V1 closed-world coverage "
                "inherits the exploratory grade of its source and can carry no "
                f"other grade, got {value!r}"
            )
        return value

    @field_validator("returned_dates")
    @classmethod
    def require_canonical_returned_dates(
        cls, values: tuple[date, ...]
    ) -> tuple[date, ...]:
        if not values:
            raise ValueError(
                "closed_world_returned_dates_invalid: a closed-world reading "
                "needs at least one returned date to bracket"
            )
        if len(set(values)) != len(values):
            raise ValueError(
                "closed_world_returned_dates_invalid: returned dates repeat a date"
            )
        if tuple(sorted(values)) != values:
            raise ValueError(
                "closed_world_returned_dates_invalid: returned dates must be sorted"
            )
        return values

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        outside = tuple(
            item.isoformat()
            for item in self.returned_dates
            if not self.requested_start_date <= item <= self.requested_end_date
        )
        if outside:
            raise ValueError(
                "closed_world_returned_dates_invalid: returned dates "
                f"{outside} lie outside the requested interval "
                f"{self.requested_start_date.isoformat()} to "
                f"{self.requested_end_date.isoformat()}"
            )
        if not (
            self.requested_start_date
            <= self.covered_start_date
            <= self.covered_end_date
            <= self.requested_end_date
        ):
            raise ValueError(
                "closed_world_interval_invalid: the covered interval must lie "
                "inside the requested interval"
            )
        hull = (self.returned_dates[0], self.returned_dates[-1])
        if (self.covered_start_date, self.covered_end_date) != hull:
            raise ValueError(
                "closed_world_interval_invalid: the V1 covered interval is the "
                "bracketed hull of the returned dates, "
                f"{hull[0].isoformat()} to {hull[1].isoformat()}"
            )
        snapshot = self.snapshot_as_of
        if (
            snapshot.shape is not BoundaryShape.EXACT
            or snapshot.lower_bound is None
            or snapshot.lower_bound != snapshot.upper_bound
        ):
            raise ValueError(
                "closed_world_snapshot_invalid: the snapshot is the exact "
                "acquisition instant"
            )
        if self.derivation_algorithm_hash != closed_world_derivation_algorithm_hash():
            raise ValueError(
                "closed_world_derivation_mismatch: the record names a derivation "
                "rule other than closed_world_calendar_response_v1"
            )
        if self.record_hash != closed_world_record_hash(self):
            raise ValueError(
                "closed_world_record_hash_mismatch: the record hash does not "
                "cover the record's own fields"
            )
        return self


def closed_world_record_hash(record: ClosedWorldSessionCoverageV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one record."""
    dump = record.model_dump(mode="python", warnings=False)
    dump.pop("record_hash", None)
    return content_hash(dump)


def seal_closed_world_session_coverage(
    values: Mapping[str, object],
) -> ClosedWorldSessionCoverageV1:
    """Seal a record's own hash over ``values`` and validate the result.

    ``record_hash`` in ``values``, if any, is ignored and recomputed. Every
    other field is validated as given, so a seal never repairs a record.
    """
    body: dict[str, Any] = {
        key: value for key, value in values.items() if key != "record_hash"
    }
    draft = ClosedWorldSessionCoverageV1.model_construct(
        **(body | {"record_hash": "0" * 64})
    )
    return ClosedWorldSessionCoverageV1.model_validate(
        body | {"record_hash": closed_world_record_hash(draft)}
    )
