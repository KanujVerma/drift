"""Unit tests for M1d closed-world session coverage (issue 71, ruling Q18 of #62).

The record binds a requested interval, the retained calendar response bytes, a
completeness assertion and the returned date set. A covered date that was not
returned is an evidenced non-trading date; every other date is INDETERMINATE
and never defaults to closed. These tests hold the record, the derivation rule
and the materialization into explicit closed rows to that contract, with no
provider in the loop.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.observation_query import m1d_implementation_hash
from drift.domain.session_closed_world import (
    CLOSED_WORLD_POSITIVE_BASES,
    CLOSED_WORLD_RECORD_KIND,
    ClosedWorldCompletenessAssertionV1,
    ClosedWorldSessionCoverageV1,
    closed_world_derivation_algorithm_hash,
    closed_world_record_hash,
    seal_closed_world_session_coverage,
)
from drift.domain.sessions import ScheduledSessionVersionV1
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind, SourcePrecision
from drift.markets.session_closed_world import (
    closed_world_record_bytes,
    closed_world_record_digest,
    evidenced_closed_dates,
    evidenced_session_date_status,
    expand_closed_world_coverage,
    parse_closed_world_record,
)
from drift.serialization.canonical import canonical_json

MIC = "XNAS"
SOURCE = "synthetic-calendar-v1"
REQUESTED_START = date(2026, 1, 5)
REQUESTED_END = date(2026, 1, 18)
#: Two weeks of weekdays with one weekday holiday (Wednesday 2026-01-14).
RETURNED = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 15, 16))
#: Exactly the covered dates that were not returned: one weekend and the holiday.
EVIDENCED = (date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 14))
SNAPSHOT = datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
CHANNEL = AvailabilityChannelV1(
    kind=ChannelKind.PUBLIC, identifier="synthetic-rest", version="1"
)


def _reference(digest: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=UUID("019b8240-0000-7000-8000-000000000901"),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _snapshot() -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=SNAPSHOT,
        upper_bound=SNAPSHOT,
        source_precision=SourcePrecision.SECOND,
        source_time_label="2026-01-20T12:00:00Z",
        source_timezone=None,
        evidence_reference=_reference("a" * 64),
    )


def _assertion(**overrides: Any) -> ClosedWorldCompletenessAssertionV1:
    values: dict[str, Any] = {
        "schema_version": "1",
        "basis": "provider_partially_published",
        "policy_statement_hash": "b" * 64,
        "acquisition_reconciliation_pass": True,
        "returned_dates_unique": True,
        "returned_dates_inside_requested_interval": True,
        "single_unpaginated_response": True,
        "measured_origin": True,
    }
    values.update(overrides)
    return ClosedWorldCompletenessAssertionV1.model_validate(values)


def _values(**overrides: Any) -> dict[str, Any]:
    returned = overrides.pop("returned_dates", RETURNED)
    values: dict[str, Any] = {
        "schema_version": "1",
        "kind": CLOSED_WORLD_RECORD_KIND,
        "source_id": SOURCE,
        "mic": MIC,
        "session_scope": "regular",
        "requested_start_date": REQUESTED_START,
        "requested_end_date": REQUESTED_END,
        "request_binding_hash": "c" * 64,
        "response_sha256": "d" * 64,
        "response_byte_size": 512,
        "origin_observation_hash": "e" * 64,
        "returned_dates": returned,
        "completeness": _assertion(),
        "covered_start_date": min(returned) if returned else REQUESTED_START,
        "covered_end_date": max(returned) if returned else REQUESTED_END,
        "snapshot_as_of": _snapshot(),
        "timezone_identifier": "America/New_York",
        "source_methodology_hash": "f" * 64,
        "availability_channel": CHANNEL,
        "evidence_grade": "exploratory",
        "derivation_algorithm_hash": closed_world_derivation_algorithm_hash(),
        "implementation_hash": m1d_implementation_hash(),
    }
    values.update(overrides)
    return values


def record(**overrides: Any) -> ClosedWorldSessionCoverageV1:
    """A sealed, valid record over the synthetic fortnight."""
    return seal_closed_world_session_coverage(_values(**overrides))


def _days(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    )


# --- acceptance 1: the derivation -------------------------------------------------


def test_covered_unreturned_dates_are_exactly_the_evidenced_closed_dates() -> None:
    coverage = record()

    assert evidenced_closed_dates(coverage) == EVIDENCED
    for day in _days(REQUESTED_START, REQUESTED_END):
        status = evidenced_session_date_status((coverage,), MIC, day)
        if day in RETURNED:
            assert status == "scheduled_open", day
        elif day in EVIDENCED:
            assert status == "evidenced_non_trading", day
        else:
            # D2-b: the trailing weekend lies inside the requested interval but
            # outside the bracketed hull, so it stays INDETERMINATE.
            assert day in (date(2026, 1, 17), date(2026, 1, 18)), day
            assert status == "indeterminate", day


def test_a_returned_date_is_never_non_trading() -> None:
    """M6: schedule evidence of an open date is never read as a closure."""
    coverage = record()
    for day in RETURNED:
        assert day not in evidenced_closed_dates(coverage)
        assert evidenced_session_date_status((coverage,), MIC, day) == (
            "scheduled_open"
        )


def test_an_uncovered_date_is_indeterminate_and_never_closed() -> None:
    """M5: no coverage at all, or a date outside it, never defaults to closed."""
    coverage = record()
    assert evidenced_session_date_status((), MIC, date(2026, 1, 10)) == (
        "indeterminate"
    )
    for day in (date(2026, 1, 4), date(2026, 1, 17), date(2026, 1, 18)):
        assert evidenced_session_date_status((coverage,), MIC, day) == ("indeterminate")
    # Another venue's calendar says nothing about this one.
    assert evidenced_session_date_status((coverage,), "XNYS", date(2026, 1, 10)) == (
        "indeterminate"
    )


def test_the_hull_endpoints_are_inclusive_and_nothing_beyond_them_is_covered() -> None:
    """M8: the covered interval is inclusive at both ends and no wider."""
    coverage = record(returned_dates=(date(2026, 1, 5), date(2026, 1, 9)))

    assert evidenced_closed_dates(coverage) == (
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    assert evidenced_session_date_status((coverage,), MIC, date(2026, 1, 5)) == (
        "scheduled_open"
    )
    assert evidenced_session_date_status((coverage,), MIC, date(2026, 1, 9)) == (
        "scheduled_open"
    )
    assert evidenced_session_date_status((coverage,), MIC, date(2026, 1, 4)) == (
        "indeterminate"
    )
    assert evidenced_session_date_status((coverage,), MIC, date(2026, 1, 10)) == (
        "indeterminate"
    )
    # A hull may start on the requested start and end on the requested end.
    edge = record(
        returned_dates=(REQUESTED_START, REQUESTED_END),
        requested_start_date=REQUESTED_START,
        requested_end_date=REQUESTED_END,
    )
    assert edge.covered_start_date == REQUESTED_START
    assert edge.covered_end_date == REQUESTED_END


# --- acceptance 2: a non-positive assertion derives nothing -------------------------


@pytest.mark.parametrize(
    "override",
    (
        {"basis": "drift_asserted_unpublished"},
        {"returned_dates_unique": False},
        {"returned_dates_inside_requested_interval": False},
        {"single_unpaginated_response": False},
        {"measured_origin": False},
    ),
    ids=lambda item: next(iter(item)),
)
def test_a_non_positive_assertion_leaves_every_gap_indeterminate(
    override: dict[str, Any],
) -> None:
    """M3: a record whose assertion is not positive is valid data and proves nothing."""
    coverage = record(completeness=_assertion(**override))

    assert coverage.completeness.positive is False
    assert evidenced_closed_dates(coverage) == ()
    assert expand_closed_world_coverage(coverage) == ()
    for day in EVIDENCED:
        assert evidenced_session_date_status((coverage,), MIC, day) == ("indeterminate")
    # Returned dates remain schedule evidence of an open date.
    assert evidenced_session_date_status((coverage,), MIC, RETURNED[0]) == (
        "scheduled_open"
    )


def test_only_the_published_bases_are_positive() -> None:
    assert (
        frozenset({"provider_published", "provider_partially_published"})
        == CLOSED_WORLD_POSITIVE_BASES
    )
    assert _assertion(basis="provider_published").positive is True
    assert _assertion().positive is True


def test_a_missing_completeness_assertion_is_refused() -> None:
    values = _values()
    del values["completeness"]
    with pytest.raises(ValidationError):
        seal_closed_world_session_coverage(values)


# --- acceptance 3: integrity failures are refused, never downgraded -----------------


def test_a_record_whose_bytes_disagree_with_its_hash_is_refused() -> None:
    """V1: a changed binding without a re-seal is an integrity failure."""
    coverage = record()
    tampered = coverage.model_dump(mode="python")
    tampered["response_sha256"] = "9" * 64
    with pytest.raises(ValidationError, match="closed_world_record_hash_mismatch"):
        ClosedWorldSessionCoverageV1.model_validate(tampered)


@pytest.mark.parametrize(
    "returned",
    (
        (date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)),
        (date(2026, 1, 6), date(2026, 1, 5)),
        (),
    ),
    ids=("duplicate", "unsorted", "empty"),
)
def test_a_malformed_returned_date_set_is_refused(returned: tuple[date, ...]) -> None:
    """V3 and M11: sorted, unique and nonempty, or refused."""
    with pytest.raises(ValidationError, match="closed_world_returned_dates_invalid"):
        record(
            returned_dates=returned,
            covered_start_date=REQUESTED_START,
            covered_end_date=REQUESTED_START,
        )


def test_a_returned_date_outside_the_requested_interval_is_refused() -> None:
    """V3 and M1: an out-of-window row cannot widen the covered interval."""
    outside = (date(2026, 1, 2), *RETURNED)
    with pytest.raises(ValidationError, match="closed_world_returned_dates_invalid"):
        record(returned_dates=outside)


_NOT_THE_HULL = "closed_world_interval_invalid: the V1 covered interval is the"
_OUTSIDE_REQUEST = "closed_world_returned_dates_invalid: returned dates"


@pytest.mark.parametrize(
    ("override", "match"),
    (
        # D2-b: the covered interval is the bracketed hull, not the request.
        (
            {"covered_start_date": REQUESTED_START, "covered_end_date": REQUESTED_END},
            _NOT_THE_HULL,
        ),
        ({"covered_end_date": date(2026, 1, 17)}, _NOT_THE_HULL),
        ({"covered_start_date": date(2026, 1, 6)}, _NOT_THE_HULL),
        ({"covered_end_date": date(2026, 1, 15)}, _NOT_THE_HULL),
        # A request that does not contain the returned dates is refused first.
        ({"requested_start_date": date(2026, 1, 6)}, _OUTSIDE_REQUEST),
        ({"requested_end_date": date(2026, 1, 15)}, _OUTSIDE_REQUEST),
    ),
    ids=(
        "widened-to-request",
        "end-past-hull",
        "start-inside-hull",
        "end-inside-hull",
        "request-starts-after-hull",
        "request-ends-before-hull",
    ),
)
def test_a_covered_interval_other_than_the_bracketed_hull_is_refused(
    override: dict[str, Any], match: str
) -> None:
    """V2: requested start <= covered start <= covered end <= requested end, hull."""
    with pytest.raises(ValidationError, match=match):
        record(**override)


def test_a_covered_interval_outside_the_request_is_refused_by_the_ordering() -> None:
    """V2 on its own: the ordering holds even where the hull check would not run."""
    with pytest.raises(
        ValidationError,
        match="closed_world_interval_invalid: the covered interval must lie inside",
    ):
        record(covered_end_date=REQUESTED_END + timedelta(days=1))


def test_a_promotion_grade_record_is_refused() -> None:
    """V7 and M7: exploratory evidence in, exploratory evidence out."""
    for grade in ("promotion_grade", "promotion", "qualified"):
        with pytest.raises(ValidationError, match="closed_world_grade_exceeds_source"):
            record(evidence_grade=grade)


def test_a_foreign_derivation_rule_is_refused() -> None:
    with pytest.raises(ValidationError, match="closed_world_derivation_mismatch"):
        record(derivation_algorithm_hash="1" * 64)


def test_a_non_exact_snapshot_is_refused() -> None:
    bounded = _snapshot().model_copy(
        update={
            "shape": BoundaryShape.BOUNDED,
            "upper_bound": SNAPSHOT + timedelta(hours=1),
            "source_precision": SourcePrecision.INTERVAL,
        }
    )
    with pytest.raises(ValidationError, match="closed_world_snapshot_invalid"):
        record(snapshot_as_of=bounded)


def test_the_record_hash_is_self_excluding_and_binds_every_other_field() -> None:
    coverage = record()
    assert coverage.record_hash == closed_world_record_hash(coverage)
    for field, value in (
        ("request_binding_hash", "1" * 64),
        ("response_sha256", "2" * 64),
        ("response_byte_size", 513),
        ("origin_observation_hash", "3" * 64),
        ("implementation_hash", "4" * 64),
        ("source_methodology_hash", "5" * 64),
        ("timezone_identifier", "America/Chicago"),
    ):
        moved = record(**{field: value})
        assert moved.record_hash != coverage.record_hash, field


# --- conflicts (V9) and unions ----------------------------------------------------


def test_overlapping_records_that_disagree_leave_the_date_indeterminate() -> None:
    """M12: a conflict is never resolved by preference."""
    fortnight = record()
    # A second acquisition of the same source that returned the 14th.
    other = record(
        returned_dates=tuple(sorted({*RETURNED, date(2026, 1, 14)})),
        response_sha256="8" * 64,
    )
    for order in ((fortnight, other), (other, fortnight)):
        assert evidenced_session_date_status(order, MIC, date(2026, 1, 14)) == (
            "indeterminate"
        )
        # Where they agree, the answer is definite.
        assert evidenced_session_date_status(order, MIC, date(2026, 1, 10)) == (
            "evidenced_non_trading"
        )
        assert evidenced_session_date_status(order, MIC, date(2026, 1, 5)) == (
            "scheduled_open"
        )


def test_records_are_unioned_only_within_one_source() -> None:
    """Another source's calendar is never combined with this one."""
    ours = record()
    theirs = record(source_id="another-calendar-v1")
    assert evidenced_session_date_status((ours, theirs), MIC, date(2026, 1, 10)) == (
        "indeterminate"
    )
    # A later week of the same source extends coverage.
    later = record(
        requested_start_date=date(2026, 1, 19),
        requested_end_date=date(2026, 1, 30),
        returned_dates=tuple(
            date(2026, 1, day) for day in (20, 21, 22, 23, 26, 27, 28, 29, 30)
        ),
    )
    assert evidenced_session_date_status((ours, later), MIC, date(2026, 1, 24)) == (
        "evidenced_non_trading"
    )
    # The dates between the two hulls are covered by neither.
    assert evidenced_session_date_status((ours, later), MIC, date(2026, 1, 17)) == (
        "indeterminate"
    )


def test_a_forged_unvalidated_record_derives_nothing() -> None:
    """A self-consistent-looking record built past validation is not evidence."""
    genuine = record()
    forged = ClosedWorldSessionCoverageV1.model_construct(
        **(dict(genuine) | {"returned_dates": (date(2026, 1, 5),)})
    )
    assert evidenced_session_date_status((forged,), MIC, date(2026, 1, 7)) == (
        "indeterminate"
    )


# --- materialization (D4-A) -------------------------------------------------------


def test_the_expansion_mints_one_explicit_closed_row_per_evidenced_date() -> None:
    coverage = record()
    rows = expand_closed_world_coverage(coverage)
    digest = closed_world_record_digest(coverage)

    assert tuple(row.session_key.local_date for row in rows) == EVIDENCED
    for row in rows:
        assert isinstance(row, ScheduledSessionVersionV1)
        assert row.state == "closed"
        assert (row.local_open, row.local_close) == (None, None)
        assert (row.open_fold, row.close_fold) == (None, None)
        assert row.historical_boundary_offsets == ()
        assert row.source_id == SOURCE
        assert row.session_key.mic == MIC
        assert row.session_key.session_scope == "regular"
        assert row.timezone_identifier == coverage.timezone_identifier
        assert row.source_methodology_hash == coverage.source_methodology_hash
        # M9: every closed row names the record's canonical bytes, never the
        # raw calendar bytes, so the supporting closure forces the record in.
        assert row.revision.source_artifact.content_hash == digest
        assert row.revision.source_artifact.content_hash != coverage.response_sha256
        assert row.source_temporal_evidence.evidence_reference is not None
        assert row.source_temporal_evidence.evidence_reference.content_hash == digest
        (availability,) = row.revision.availability
        assert availability.channel == CHANNEL
        assert availability.lower_bound == availability.upper_bound == SNAPSHOT
    assert len({row.revision.logical_record_id for row in rows}) == len(rows)
    assert len({row.revision.record_version_id for row in rows}) == len(rows)


def test_the_expansion_is_deterministic_and_bound_to_the_exact_record() -> None:
    coverage = record()
    assert expand_closed_world_coverage(coverage) == expand_closed_world_coverage(
        record()
    )
    other = record(response_sha256="7" * 64)
    ours = expand_closed_world_coverage(coverage)
    theirs = expand_closed_world_coverage(other)
    assert tuple(row.session_key for row in ours) == tuple(
        row.session_key for row in theirs
    )
    # Same dates, different record: every row version is distinct.
    assert {row.revision.record_version_id for row in ours}.isdisjoint(
        row.revision.record_version_id for row in theirs
    )


def test_the_record_bytes_round_trip_and_claim_to_be_a_record() -> None:
    coverage = record()
    data = closed_world_record_bytes(coverage)
    assert data == canonical_json(coverage)
    assert parse_closed_world_record(data) == coverage
    # Bytes that make no claim to be a record are not one.
    assert parse_closed_world_record(b'[{"date":"2026-01-05"}]') is None
    assert parse_closed_world_record(b"not json") is None


def test_bytes_claiming_to_be_a_record_must_be_a_valid_one() -> None:
    """A tampered record is refused by code, never silently ignored."""
    from drift.markets.session_closed_world import ClosedWorldCoverageError

    coverage = record()
    document = coverage.model_dump(mode="json")
    # Drop a date inside the hull, so only the self-hash can notice.
    document["returned_dates"] = [
        item for item in document["returned_dates"] if item != "2026-01-07"
    ]
    with pytest.raises(ClosedWorldCoverageError) as error:
        parse_closed_world_record(canonical_json(document))
    assert error.value.code == "closed_world_record_hash_mismatch"
    # Moving the hull instead is refused on the interval rule first.
    document["returned_dates"] = document["returned_dates"][1:]
    with pytest.raises(ClosedWorldCoverageError) as error:
        parse_closed_world_record(canonical_json(document))
    assert error.value.code == "closed_world_interval_invalid"
    # Canonical bytes are the only encoding of a record.
    loose = closed_world_record_bytes(coverage).replace(b'"kind":', b'"kind" :', 1)
    with pytest.raises(ClosedWorldCoverageError) as error:
        parse_closed_world_record(loose)
    assert error.value.code == "closed_world_record_hash_mismatch"
