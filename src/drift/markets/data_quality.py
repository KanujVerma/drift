"""Deterministic quality checks over one daily series of dated values.

``assess_daily_values`` examines caller-supplied points in the order they were
supplied and returns a ``DataQualityReportV1`` that accounts for every check.
``require_passing`` turns a report that did not pass into an error.

How the checks read the points:

* Nothing is sorted before the duplicate and order checks, so a shuffled
  series cannot pass by being put in order first.
* A point that carries a missing marker is a row for its date. It counts for
  the calendar checks and is skipped, without ending a run, by the stale-run
  and jump checks, which compare consecutive present values.
* The stale-run, jump and bounds checks read values. When no point carries a
  value they are reported as ``not_evaluated``, never as a pass, so a series
  of markers alone fails any policy that makes one of them hard.
* Arithmetic is exact ``Decimal`` arithmetic with no division. A relative jump
  is tested as ``|change| > limit * |prior|``; a relative jump away from zero
  has no defined size and is always an error. Arithmetic that cannot be exact
  within a fixed number of digits is refused rather than rounded.
* A value cannot be public before its observation day has ended in UTC, so an
  ``available_at`` earlier than that instant is a finding.

Limitations, stated plainly:

* The checks are mechanical. They do not know what the series means, whether
  its values are right, or whether its dates are the right trading days: the
  expected calendar is whatever the caller passes, and when none is passed
  the two calendar checks are reported as ``not_evaluated``.
* ``available_at`` is whatever the caller states. For a public series built
  from a publication-lag rule it is modeled, not observed, and this module
  cannot tell the difference.
* The cutoff bounds only this call. It is not recorded in the report.
* A check that ran over nothing it could object to reports ``pass`` with an
  ``examined_count`` of 0, for example the jump check on a single value. Read
  the count with the status.
* The duplicate and order checks look at the points as supplied. A caller that
  hands over points from a structure which already enforces unique ascending
  dates will never see them fire.
* A passing report is exploratory evidence about supplied values. It is not a
  source qualification and it grants nothing.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)
from itertools import pairwise

from pydantic import ValidationError

from drift.domain.data_quality import (
    DATA_QUALITY_CODE_RELATIVE_JUMP_FROM_ZERO,
    DataQualityCheck,
    DataQualityCheckResultV1,
    DataQualityCheckStatus,
    DataQualityError,
    DataQualityFindingV1,
    DataQualityInputError,
    DataQualityPolicyV1,
    DataQualityReportV1,
    DataQualitySubjectKind,
    data_quality_finding_sort_key,
    expected_dates_content_hash,
    seal_data_quality_report,
)
from drift.domain.dataset_validation import FindingSeverity, ValidationResult

#: Digits kept by the exact arithmetic. A result needing more is refused.
EXACT_ARITHMETIC_DIGITS = 100


@dataclass(frozen=True, slots=True)
class DatedValue:
    """One point of a daily series, as supplied by the caller.

    Exactly one of ``value`` and ``missing_marker`` is set: either the exact
    decimal the source printed for ``observed_on``, or the marker it printed
    instead of a value. ``available_at`` is the instant the caller states the
    point became public, or ``None`` when the caller states nothing.
    """

    observed_on: date
    value: Decimal | None
    missing_marker: str | None
    available_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Present:
    observed_on: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class _Draft:
    """One finding before its severity is known."""

    check: DataQualityCheck
    code: str
    first_date: date
    last_date: date
    count: int
    observed: str | None
    limit: str | None
    always_error: bool = False


@dataclass(frozen=True, slots=True)
class _Outcome:
    """What one check examined. ``examined`` is ``None`` when it could not run."""

    check: DataQualityCheck
    examined: int | None
    drafts: tuple[_Draft, ...]


def assess_daily_values(
    points: Iterable[DatedValue],
    *,
    subject_kind: DataQualitySubjectKind,
    subject_hash: str,
    source_sha256: str,
    policy: DataQualityPolicyV1,
    expected_dates: Iterable[date] | None,
    cutoff: datetime | None,
) -> DataQualityReportV1:
    """Run every check over ``points`` in source order and seal the report.

    ``expected_dates`` is the set of dates the caller expects rows for; with
    ``None`` the calendar-gap and unexpected-date checks are ``not_evaluated``.
    ``cutoff`` is the latest instant a point may have become available; with
    ``None`` that part of the availability check is not applied. The
    availability check as a whole is ``not_evaluated`` when no point states an
    ``available_at``, and the stale-run, jump and bounds checks are
    ``not_evaluated`` when no point carries a value.

    A finding of a check in ``policy.hard_checks`` is an error and any other
    finding is a warning, except a relative jump away from zero, which is
    always an error. The result is ``fail`` when any finding is an error or a
    hard check was not evaluated.

    Raises ``DataQualityInputError`` when the inputs cannot be examined at
    all: no points, a malformed point, a naive datetime, a repeated expected
    date, a policy that fails revalidation, or arithmetic that cannot be
    exact. An empty series is refused rather than passed vacuously.
    """
    checked_policy = _revalidated_policy(policy)
    rows = _checked_points(points)
    latest = _checked_cutoff(cutoff)
    calendar = None if expected_dates is None else tuple(expected_dates)
    calendar_hash = None if calendar is None else expected_dates_content_hash(calendar)
    present = tuple(
        _Present(observed_on=row.observed_on, value=row.value)
        for row in rows
        if row.value is not None
    )
    outcomes = (
        _duplicate_outcome(rows),
        _order_outcome(rows),
        *_calendar_outcomes(rows, calendar),
        _missing_outcome(rows, checked_policy),
        _stale_outcome(present, checked_policy),
        _jump_outcome(present, checked_policy),
        _bounds_outcome(present, checked_policy),
        _availability_outcome(rows, latest),
    )
    hard = frozenset(checked_policy.hard_checks)
    results: list[DataQualityCheckResultV1] = []
    findings: list[DataQualityFindingV1] = []
    for outcome in sorted(outcomes, key=lambda item: item.check.value):
        own = _findings_of(outcome, is_hard=outcome.check in hard)
        findings.extend(own)
        results.append(
            DataQualityCheckResultV1(
                check=outcome.check,
                status=_status_of(outcome, own),
                examined_count=outcome.examined or 0,
                finding_count=len(own),
            )
        )
    failed = any(item.severity is FindingSeverity.ERROR for item in findings) or any(
        item.status == "not_evaluated" and item.check in hard for item in results
    )
    return seal_data_quality_report(
        subject_kind=subject_kind,
        subject_hash=subject_hash,
        source_sha256=source_sha256,
        policy=checked_policy,
        expected_dates_hash=calendar_hash,
        checks=tuple(results),
        findings=tuple(sorted(findings, key=data_quality_finding_sort_key)),
        result=ValidationResult.FAIL if failed else ValidationResult.PASS,
    )


def require_passing(report: DataQualityReportV1) -> None:
    """Raise ``DataQualityError`` unless ``report`` is a valid passing report.

    The report is revalidated first, so one assembled without validation is
    refused with ``DataQualityInputError`` instead of being trusted.

    This looks at the report alone. It does not check that the report is about
    the data or the policy the caller holds: compare ``subject_hash``,
    ``source_sha256`` and ``policy_hash`` for that.
    """
    if not isinstance(report, DataQualityReportV1):
        raise DataQualityInputError(
            "data_quality_report_invalid: a DataQualityReportV1 is required"
        )
    try:
        checked = DataQualityReportV1.model_validate(
            report.model_dump(mode="python", warnings=False)
        )
    except ValidationError as error:
        raise DataQualityInputError(
            "data_quality_report_invalid: the report failed revalidation"
        ) from error
    if checked.result is not ValidationResult.PASS:
        raise DataQualityError(checked)


# --- inputs -------------------------------------------------------------------


def _revalidated_policy(policy: DataQualityPolicyV1) -> DataQualityPolicyV1:
    if not isinstance(policy, DataQualityPolicyV1):
        raise DataQualityInputError(
            "data_quality_policy_invalid: a DataQualityPolicyV1 is required"
        )
    try:
        return DataQualityPolicyV1.model_validate(
            policy.model_dump(mode="python", warnings=False)
        )
    except ValidationError as error:
        raise DataQualityInputError(
            "data_quality_policy_invalid: the policy failed revalidation"
        ) from error


def _checked_points(points: Iterable[DatedValue]) -> tuple[DatedValue, ...]:
    """Refuse malformed points and normalize stated availability to UTC."""
    rows: list[DatedValue] = []
    for index, point in enumerate(points):
        if not isinstance(point, DatedValue):
            raise DataQualityInputError(
                f"data_quality_point_invalid: point {index} is not a DatedValue"
            )
        if type(point.observed_on) is not date:
            raise DataQualityInputError(
                f"data_quality_point_date_invalid: point {index} must carry a "
                "plain calendar date"
            )
        value, marker = point.value, point.missing_marker
        if (value is None) == (marker is None) or (
            marker is not None and (not isinstance(marker, str) or not marker.strip())
        ):
            raise DataQualityInputError(
                f"data_quality_point_state_invalid: point {index} must carry "
                "exactly one of a value and a non-blank missing marker"
            )
        if value is not None and (
            not isinstance(value, Decimal) or not value.is_finite()
        ):
            raise DataQualityInputError(
                f"data_quality_point_value_invalid: point {index} must carry a "
                "finite Decimal"
            )
        rows.append(
            DatedValue(
                observed_on=point.observed_on,
                value=value,
                missing_marker=marker,
                available_at=_checked_instant(
                    point.available_at,
                    f"data_quality_point_availability_naive: point {index}",
                ),
            )
        )
    if not rows:
        raise DataQualityInputError(
            "data_quality_points_empty: an empty series cannot be assessed"
        )
    return tuple(rows)


def _checked_cutoff(cutoff: datetime | None) -> datetime | None:
    return _checked_instant(cutoff, "data_quality_cutoff_naive: the cutoff")


def _checked_instant(value: datetime | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DataQualityInputError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(UTC)


# --- checks -------------------------------------------------------------------


def _duplicate_outcome(rows: tuple[DatedValue, ...]) -> _Outcome:
    check = DataQualityCheck.DUPLICATE_KEY
    counts: dict[date, int] = {}
    for row in rows:
        counts[row.observed_on] = counts.get(row.observed_on, 0) + 1
    drafts = tuple(
        _Draft(check, "duplicate_date", day, day, seen, str(seen), "1")
        for day, seen in sorted(counts.items())
        if seen > 1
    )
    return _Outcome(check, len(rows), drafts)


def _order_outcome(rows: tuple[DatedValue, ...]) -> _Outcome:
    """A date strictly earlier than the one before it, in source order."""
    check = DataQualityCheck.NON_MONOTONIC_ORDER
    drafts = tuple(
        _Draft(
            check,
            "date_out_of_order",
            current.observed_on,
            previous.observed_on,
            1,
            current.observed_on.isoformat(),
            previous.observed_on.isoformat(),
        )
        for previous, current in pairwise(rows)
        if current.observed_on < previous.observed_on
    )
    return _Outcome(check, len(rows) - 1, drafts)


def _calendar_outcomes(
    rows: tuple[DatedValue, ...], calendar: tuple[date, ...] | None
) -> tuple[_Outcome, _Outcome]:
    gap, unexpected = DataQualityCheck.CALENDAR_GAP, DataQualityCheck.UNEXPECTED_DATE
    if calendar is None:
        return _Outcome(gap, None, ()), _Outcome(unexpected, None, ())
    present = {row.observed_on for row in rows}
    gaps: list[_Draft] = []
    run: list[date] = []
    for day in (*sorted(calendar), None):
        if day is not None and day not in present:
            run.append(day)
            continue
        if run:
            size = len(run)
            gaps.append(
                _Draft(
                    gap, "expected_dates_missing", run[0], run[-1], size, str(size), "0"
                )
            )
            run = []
    strays = tuple(
        _Draft(
            unexpected,
            "date_not_in_expected_calendar",
            day,
            day,
            1,
            day.isoformat(),
            None,
        )
        for day in sorted(present.difference(calendar))
    )
    return (
        _Outcome(gap, len(calendar), tuple(gaps)),
        _Outcome(unexpected, len(present), strays),
    )


def _missing_outcome(
    rows: tuple[DatedValue, ...], policy: DataQualityPolicyV1
) -> _Outcome:
    """Runs of consecutive missing-marker points longer than the policy allows."""
    check = DataQualityCheck.MISSING_MARKER
    drafts: list[_Draft] = []
    run: list[date] = []
    for row in (*rows, None):
        if row is not None and row.value is None:
            run.append(row.observed_on)
            continue
        if len(run) > policy.max_missing_run:
            drafts.append(
                _run_draft(
                    check,
                    "missing_marker_run_exceeds_limit",
                    run,
                    policy.max_missing_run,
                )
            )
        run = []
    return _Outcome(check, len(rows), tuple(drafts))


def _stale_outcome(
    present: tuple[_Present, ...], policy: DataQualityPolicyV1
) -> _Outcome:
    """Runs of numerically equal consecutive present values over the limit."""
    check = DataQualityCheck.STALE_RUN
    if not present:
        return _Outcome(check, None, ())
    drafts: list[_Draft] = []
    run: list[_Present] = []
    for item in (*present, None):
        if item is not None and (not run or item.value == run[-1].value):
            run.append(item)
            continue
        if len(run) > policy.max_stale_run:
            drafts.append(
                _run_draft(
                    check,
                    "identical_value_run_exceeds_limit",
                    [member.observed_on for member in run],
                    policy.max_stale_run,
                )
            )
        run = [] if item is None else [item]
    return _Outcome(check, len(present), tuple(drafts))


def _jump_outcome(
    present: tuple[_Present, ...], policy: DataQualityPolicyV1
) -> _Outcome:
    """Changes between consecutive present values larger than the limit."""
    check = DataQualityCheck.EXTREME_JUMP
    if not present:
        return _Outcome(check, None, ())
    exact = Context(
        prec=EXACT_ARITHMETIC_DIGITS,
        traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
    )
    drafts: list[_Draft] = []
    for previous, current in pairwise(present):
        first = min(previous.observed_on, current.observed_on)
        last = max(previous.observed_on, current.observed_on)
        try:
            change = exact.subtract(current.value, previous.value).copy_abs()
            allowed = (
                policy.max_abs_jump
                if policy.jump_mode == "absolute"
                else exact.multiply(policy.max_abs_jump, previous.value.copy_abs())
            )
        except DecimalException as error:
            raise DataQualityInputError(
                "data_quality_arithmetic_inexact: the change between "
                f"{previous.observed_on.isoformat()} and "
                f"{current.observed_on.isoformat()} cannot be computed exactly "
                f"in {EXACT_ARITHMETIC_DIGITS} digits"
            ) from error
        if change == 0:
            continue
        if policy.jump_mode == "relative" and previous.value == 0:
            drafts.append(
                _Draft(
                    check,
                    DATA_QUALITY_CODE_RELATIVE_JUMP_FROM_ZERO,
                    first,
                    last,
                    1,
                    str(change),
                    None,
                    always_error=True,
                )
            )
        elif change > allowed:
            code = f"{policy.jump_mode}_jump_exceeds_limit"
            drafts.append(
                _Draft(check, code, first, last, 1, str(change), str(allowed))
            )
    return _Outcome(check, len(present) - 1, tuple(drafts))


def _bounds_outcome(
    present: tuple[_Present, ...], policy: DataQualityPolicyV1
) -> _Outcome:
    check = DataQualityCheck.OUT_OF_BOUNDS
    if not present:
        return _Outcome(check, None, ())
    drafts: list[_Draft] = []
    for item in present:
        day, value = item.observed_on, item.value
        if value < policy.lower_bound:
            code, bound = "value_below_lower_bound", policy.lower_bound
        elif value > policy.upper_bound:
            code, bound = "value_above_upper_bound", policy.upper_bound
        else:
            continue
        drafts.append(_Draft(check, code, day, day, 1, str(value), str(bound)))
    return _Outcome(check, len(present), tuple(drafts))


def _availability_outcome(
    rows: tuple[DatedValue, ...], cutoff: datetime | None
) -> _Outcome:
    """Stated availability: not inside the day, not going back, not past cutoff."""
    check = DataQualityCheck.AVAILABILITY_VIOLATION
    if all(row.available_at is None for row in rows):
        return _Outcome(check, None, ())
    drafts: list[_Draft] = []
    earlier: tuple[date, datetime] | None = None
    for row in rows:
        day, stamp = row.observed_on, row.available_at
        if stamp is None:
            drafts.append(
                _Draft(check, "availability_not_stated", day, day, 1, None, None)
            )
            continue
        day_end = _day_end(day)
        if stamp < day_end:
            drafts.append(
                _Draft(
                    check,
                    "available_before_observation_day_end",
                    day,
                    day,
                    1,
                    stamp.isoformat(),
                    day_end.isoformat(),
                )
            )
        if earlier is not None and stamp < earlier[1]:
            drafts.append(
                _Draft(
                    check,
                    "availability_not_monotonic",
                    min(day, earlier[0]),
                    max(day, earlier[0]),
                    1,
                    stamp.isoformat(),
                    earlier[1].isoformat(),
                )
            )
        if cutoff is not None and stamp > cutoff:
            drafts.append(
                _Draft(
                    check,
                    "available_after_cutoff",
                    day,
                    day,
                    1,
                    stamp.isoformat(),
                    cutoff.isoformat(),
                )
            )
        earlier = (day, stamp)
    return _Outcome(check, len(rows), tuple(drafts))


# --- assembly -----------------------------------------------------------------


def _run_draft(
    check: DataQualityCheck, code: str, run: list[date], limit: int
) -> _Draft:
    size = len(run)
    return _Draft(check, code, min(run), max(run), size, str(size), str(limit))


def _day_end(day: date) -> datetime:
    """The first instant after ``day`` has ended in UTC."""
    try:
        following = day + timedelta(days=1)
    except OverflowError as error:
        raise DataQualityInputError(
            "data_quality_point_date_invalid: the observation date has no following day"
        ) from error
    return datetime.combine(following, time(0, 0), tzinfo=UTC)


def _findings_of(outcome: _Outcome, *, is_hard: bool) -> list[DataQualityFindingV1]:
    """Typed findings for one check, with identical drafts merged by count."""
    merged: dict[tuple[str, date, date, str | None, str | None], tuple[int, bool]] = {}
    for draft in outcome.drafts:
        key = (
            draft.code,
            draft.first_date,
            draft.last_date,
            draft.observed,
            draft.limit,
        )
        count, forced = merged.get(key, (0, False))
        merged[key] = (count + draft.count, forced or draft.always_error)
    return [
        DataQualityFindingV1(
            check=outcome.check,
            severity=(
                FindingSeverity.ERROR if is_hard or forced else FindingSeverity.WARNING
            ),
            code=code,
            first_date=first_date,
            last_date=last_date,
            count=count,
            observed=observed,
            limit=limit,
        )
        for (code, first_date, last_date, observed, limit), (count, forced) in (
            merged.items()
        )
    ]


def _status_of(
    outcome: _Outcome, own: list[DataQualityFindingV1]
) -> DataQualityCheckStatus:
    if outcome.examined is None:
        return "not_evaluated"
    if any(item.severity is FindingSeverity.ERROR for item in own):
        return "fail"
    return "warn" if own else "pass"
