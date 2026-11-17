"""Unit tests for the typed data-quality report and the daily-value checks.

Every input is synthetic and built inline. No file is read and nothing is
downloaded. Each check is exercised with a control beside the attack: the same
points with the offending property removed must behave differently, so no
assertion here can pass vacuously.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

import pytest
from pydantic import ValidationError

from drift.domain.data_quality import (
    ALL_DATA_QUALITY_CHECKS,
    DataQualityCheck,
    DataQualityCheckResultV1,
    DataQualityError,
    DataQualityFindingV1,
    DataQualityInputError,
    DataQualityPolicyV1,
    DataQualityReportV1,
    data_quality_policy_hash,
    data_quality_report_hash,
    expected_dates_content_hash,
    seal_data_quality_policy,
)
from drift.domain.dataset_validation import FindingSeverity, ValidationResult
from drift.errors import DriftError
from drift.markets.data_quality import (
    DatedValue,
    assess_daily_values,
    require_passing,
)

SUBJECT_HASH = "a" * 64
SOURCE_SHA256 = "b" * 64
HASH_ZERO = "0" * 64

MON = date(2024, 1, 8)
TUE = date(2024, 1, 9)
WED = date(2024, 1, 10)
THU = date(2024, 1, 11)
FRI = date(2024, 1, 12)
SAT = date(2024, 1, 13)
WEEK = (MON, TUE, WED, THU, FRI)

#: The six checks that never depend on an optional input, in canonical order.
ALWAYS_EVALUATED = (
    DataQualityCheck.DUPLICATE_KEY,
    DataQualityCheck.EXTREME_JUMP,
    DataQualityCheck.MISSING_MARKER,
    DataQualityCheck.NON_MONOTONIC_ORDER,
    DataQualityCheck.OUT_OF_BOUNDS,
    DataQualityCheck.STALE_RUN,
)


def _policy(
    *,
    hard_checks: tuple[DataQualityCheck, ...] = ALWAYS_EVALUATED,
    policy_id: str = "synthetic-daily-rate-policy",
    lower_bound: str = "-1",
    upper_bound: str = "25",
    max_abs_jump: str = "1",
    jump_mode: Literal["absolute", "relative"] = "absolute",
    max_stale_run: int = 3,
    max_missing_run: int = 1,
) -> DataQualityPolicyV1:
    return seal_data_quality_policy(
        policy_id=policy_id,
        lower_bound=Decimal(lower_bound),
        upper_bound=Decimal(upper_bound),
        max_abs_jump=Decimal(max_abs_jump),
        jump_mode=jump_mode,
        max_stale_run=max_stale_run,
        max_missing_run=max_missing_run,
        hard_checks=hard_checks,
    )


def _value(day: date, text: str, available_at: datetime | None = None) -> DatedValue:
    return DatedValue(
        observed_on=day,
        value=Decimal(text),
        missing_marker=None,
        available_at=available_at,
    )


def _marker(day: date, available_at: datetime | None = None) -> DatedValue:
    return DatedValue(
        observed_on=day, value=None, missing_marker="ND", available_at=available_at
    )


def _day_end(day: date) -> datetime:
    """The first instant after ``day`` ends in UTC."""
    return datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=UTC)


def _released(day: date) -> datetime:
    """A synthetic release instant on the calendar day after ``day``."""
    return datetime.combine(day + timedelta(days=1), time(21, 15), tzinfo=UTC)


def _assess(
    points: Sequence[DatedValue],
    *,
    policy: DataQualityPolicyV1 | None = None,
    expected_dates: Sequence[date] | None = None,
    cutoff: datetime | None = None,
) -> DataQualityReportV1:
    return assess_daily_values(
        points,
        subject_kind="public_daily_series",
        subject_hash=SUBJECT_HASH,
        source_sha256=SOURCE_SHA256,
        policy=_policy() if policy is None else policy,
        expected_dates=expected_dates,
        cutoff=cutoff,
    )


def _check(
    report: DataQualityReportV1, check: DataQualityCheck
) -> DataQualityCheckResultV1:
    (found,) = (item for item in report.checks if item.check is check)
    return found


def _findings(
    report: DataQualityReportV1, check: DataQualityCheck
) -> tuple[DataQualityFindingV1, ...]:
    return tuple(item for item in report.findings if item.check is check)


def _resealed(report: DataQualityReportV1, **update: object) -> DataQualityReportV1:
    """One report edited and re-hashed, so only a semantic guard can refuse it."""
    draft = DataQualityReportV1.model_construct(**(dict(report) | update))
    return DataQualityReportV1.model_validate(
        dict(draft) | {"report_hash": data_quality_report_hash(draft)}
    )


def _clean_week() -> tuple[DatedValue, ...]:
    return (
        _value(MON, "5.00"),
        _value(TUE, "5.01"),
        _value(WED, "5.02"),
        _value(THU, "5.03"),
        _value(FRI, "5.04"),
    )


def _clean_week_with_availability() -> tuple[DatedValue, ...]:
    return tuple(
        DatedValue(
            observed_on=point.observed_on,
            value=point.value,
            missing_marker=None,
            available_at=_released(point.observed_on),
        )
        for point in _clean_week()
    )


# --- the clean control ----------------------------------------------------


def test_a_clean_series_passes_with_all_nine_checks_present() -> None:
    policy = _policy(hard_checks=ALL_DATA_QUALITY_CHECKS)

    report = _assess(
        _clean_week_with_availability(),
        policy=policy,
        expected_dates=WEEK,
        cutoff=_released(FRI),
    )

    assert len(ALL_DATA_QUALITY_CHECKS) == 9
    assert set(ALL_DATA_QUALITY_CHECKS) == set(DataQualityCheck)
    assert tuple(item.check for item in report.checks) == ALL_DATA_QUALITY_CHECKS
    assert {item.status for item in report.checks} == {"pass"}
    assert all(item.examined_count > 0 for item in report.checks)
    assert report.findings == ()
    assert report.result is ValidationResult.PASS
    assert report.policy == policy
    assert report.policy_hash == policy.policy_hash
    assert report.expected_dates_hash == expected_dates_content_hash(WEEK)
    assert report.subject_kind == "public_daily_series"
    assert report.subject_hash == SUBJECT_HASH
    assert report.source_sha256 == SOURCE_SHA256
    require_passing(report)


# --- one test per check ---------------------------------------------------


def test_a_duplicate_date_is_reported() -> None:
    points = (_value(MON, "5.00"), _value(TUE, "5.01"), _value(TUE, "5.02"))

    report = _assess(points)

    assert _check(report, DataQualityCheck.DUPLICATE_KEY).status == "fail"
    (finding,) = _findings(report, DataQualityCheck.DUPLICATE_KEY)
    assert finding.code == "duplicate_date"
    assert (finding.first_date, finding.last_date) == (TUE, TUE)
    assert (finding.count, finding.observed, finding.limit) == (2, "2", "1")
    assert finding.severity is FindingSeverity.ERROR
    assert report.result is ValidationResult.FAIL
    assert _check(_assess(points[:2]), DataQualityCheck.DUPLICATE_KEY).status == "pass"


def test_out_of_order_dates_are_not_hidden_by_sorting() -> None:
    """Points are examined in source order: the same dates sorted would pass."""
    shuffled = (_value(MON, "5.00"), _value(WED, "5.02"), _value(TUE, "5.01"))

    report = _assess(shuffled)

    assert _check(report, DataQualityCheck.NON_MONOTONIC_ORDER).status == "fail"
    assert _check(report, DataQualityCheck.DUPLICATE_KEY).status == "pass"
    (finding,) = _findings(report, DataQualityCheck.NON_MONOTONIC_ORDER)
    assert finding.code == "date_out_of_order"
    assert (finding.first_date, finding.last_date) == (TUE, WED)
    assert (finding.observed, finding.limit) == (TUE.isoformat(), WED.isoformat())
    assert report.result is ValidationResult.FAIL

    in_order = sorted(shuffled, key=lambda point: point.observed_on)
    control = _assess(in_order)
    assert _check(control, DataQualityCheck.NON_MONOTONIC_ORDER).status == "pass"
    assert control.result is ValidationResult.PASS


def test_a_calendar_gap_is_reported_as_one_run() -> None:
    points = (_value(MON, "5.00"), _value(TUE, "5.01"), _value(FRI, "5.04"))
    policy = _policy(hard_checks=(DataQualityCheck.CALENDAR_GAP,))

    report = _assess(points, policy=policy, expected_dates=WEEK)

    gap = _check(report, DataQualityCheck.CALENDAR_GAP)
    assert (gap.status, gap.examined_count, gap.finding_count) == ("fail", 5, 1)
    (finding,) = _findings(report, DataQualityCheck.CALENDAR_GAP)
    assert finding.code == "expected_dates_missing"
    assert (finding.first_date, finding.last_date, finding.count) == (WED, THU, 2)
    assert _check(report, DataQualityCheck.UNEXPECTED_DATE).status == "pass"
    assert report.result is ValidationResult.FAIL

    control = _assess(_clean_week(), policy=policy, expected_dates=WEEK)
    assert _check(control, DataQualityCheck.CALENDAR_GAP).status == "pass"
    assert control.result is ValidationResult.PASS


def test_a_date_outside_the_expected_calendar_is_reported() -> None:
    points = (*_clean_week(), _value(SAT, "5.05"))
    policy = _policy(hard_checks=(DataQualityCheck.UNEXPECTED_DATE,))

    report = _assess(points, policy=policy, expected_dates=WEEK)

    unexpected = _check(report, DataQualityCheck.UNEXPECTED_DATE)
    assert (unexpected.status, unexpected.examined_count) == ("fail", 6)
    (finding,) = _findings(report, DataQualityCheck.UNEXPECTED_DATE)
    assert finding.code == "date_not_in_expected_calendar"
    assert (finding.first_date, finding.last_date) == (SAT, SAT)
    assert _check(report, DataQualityCheck.CALENDAR_GAP).status == "pass"
    assert report.result is ValidationResult.FAIL


def test_a_missing_marker_run_longer_than_the_limit_is_reported() -> None:
    points = (
        _value(MON, "5.00"),
        _marker(TUE),
        _marker(WED),
        _value(THU, "5.03"),
        _marker(FRI),
    )

    report = _assess(points, policy=_policy(max_missing_run=1))

    missing = _check(report, DataQualityCheck.MISSING_MARKER)
    assert (missing.status, missing.examined_count) == ("fail", 5)
    (finding,) = _findings(report, DataQualityCheck.MISSING_MARKER)
    assert finding.code == "missing_marker_run_exceeds_limit"
    assert (finding.first_date, finding.last_date, finding.count) == (TUE, WED, 2)
    assert (finding.observed, finding.limit) == ("2", "1")

    control = _assess(points, policy=_policy(max_missing_run=2))
    assert _check(control, DataQualityCheck.MISSING_MARKER).status == "pass"
    zero_tolerance = _assess(points, policy=_policy(max_missing_run=0))
    assert len(_findings(zero_tolerance, DataQualityCheck.MISSING_MARKER)) == 2


def test_a_stale_run_longer_than_the_limit_is_reported() -> None:
    """Equal values are compared numerically and a missing day does not reset."""
    points = (
        _value(MON, "5.30"),
        _value(TUE, "5.3"),
        _marker(WED),
        _value(THU, "5.300"),
        _value(FRI, "5.30"),
    )

    report = _assess(points, policy=_policy(max_stale_run=3))

    stale = _check(report, DataQualityCheck.STALE_RUN)
    assert (stale.status, stale.examined_count) == ("fail", 4)
    (finding,) = _findings(report, DataQualityCheck.STALE_RUN)
    assert finding.code == "identical_value_run_exceeds_limit"
    assert (finding.first_date, finding.last_date, finding.count) == (MON, FRI, 4)
    assert (finding.observed, finding.limit) == ("4", "3")

    control = _assess(points, policy=_policy(max_stale_run=4))
    assert _check(control, DataQualityCheck.STALE_RUN).status == "pass"


def test_an_absolute_jump_above_the_limit_is_reported() -> None:
    points = (_value(MON, "5.00"), _value(TUE, "6.50"), _value(WED, "5.50"))

    report = _assess(points, policy=_policy(max_abs_jump="1", jump_mode="absolute"))

    jump = _check(report, DataQualityCheck.EXTREME_JUMP)
    assert (jump.status, jump.examined_count, jump.finding_count) == ("fail", 2, 1)
    (finding,) = _findings(report, DataQualityCheck.EXTREME_JUMP)
    assert finding.code == "absolute_jump_exceeds_limit"
    assert (finding.first_date, finding.last_date) == (MON, TUE)
    assert (finding.observed, finding.limit) == ("1.50", "1")
    # The step back down is exactly the limit, which is allowed.
    assert finding.count == 1


def test_a_jump_skips_missing_points_between_present_values() -> None:
    points = (_value(MON, "5.00"), _marker(TUE), _value(WED, "6.01"))

    report = _assess(points)

    (finding,) = _findings(report, DataQualityCheck.EXTREME_JUMP)
    assert (finding.first_date, finding.last_date) == (MON, WED)
    assert finding.observed == "1.01"


def test_a_relative_jump_above_the_limit_is_reported_without_division() -> None:
    policy = _policy(max_abs_jump="0.10", jump_mode="relative")
    above = (_value(MON, "5.00"), _value(TUE, "5.60"))
    at_limit = (_value(MON, "5.00"), _value(TUE, "5.50"))

    report = _assess(above, policy=policy)

    (finding,) = _findings(report, DataQualityCheck.EXTREME_JUMP)
    assert finding.code == "relative_jump_exceeds_limit"
    # Observed absolute change against the largest change the limit allows.
    assert (finding.observed, finding.limit) == ("0.60", "0.5000")
    assert report.result is ValidationResult.FAIL
    assert _assess(at_limit, policy=policy).result is ValidationResult.PASS


def test_a_relative_jump_from_zero_is_always_an_error() -> None:
    soft = _policy(
        hard_checks=(DataQualityCheck.DUPLICATE_KEY,),
        max_abs_jump="0.10",
        jump_mode="relative",
    )
    from_zero = (_value(MON, "0.00"), _value(TUE, "0.05"))
    zero_to_zero = (_value(MON, "0.00"), _value(TUE, "0"))

    report = _assess(from_zero, policy=soft)

    (finding,) = _findings(report, DataQualityCheck.EXTREME_JUMP)
    assert finding.code == "relative_jump_from_zero_undefined"
    assert finding.severity is FindingSeverity.ERROR
    assert (finding.observed, finding.limit) == ("0.05", None)
    assert _check(report, DataQualityCheck.EXTREME_JUMP).status == "fail"
    assert report.result is ValidationResult.FAIL
    assert _assess(zero_to_zero, policy=soft).result is ValidationResult.PASS


def test_values_outside_the_bounds_are_reported() -> None:
    points = (_value(MON, "-1.01"), _value(TUE, "-1"), _value(WED, "25.5"))
    policy = _policy(
        hard_checks=(DataQualityCheck.OUT_OF_BOUNDS,),
        lower_bound="-1",
        upper_bound="25",
        max_abs_jump="100",
    )

    report = _assess(points, policy=policy)

    bounds = _check(report, DataQualityCheck.OUT_OF_BOUNDS)
    assert (bounds.status, bounds.examined_count, bounds.finding_count) == (
        "fail",
        3,
        2,
    )
    below, above = _findings(report, DataQualityCheck.OUT_OF_BOUNDS)
    assert (below.code, below.first_date) == ("value_below_lower_bound", MON)
    assert (below.observed, below.limit) == ("-1.01", "-1")
    assert (above.code, above.first_date) == ("value_above_upper_bound", WED)
    assert (above.observed, above.limit) == ("25.5", "25")


def test_availability_before_the_observation_day_ends_is_reported() -> None:
    policy = _policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,))
    same_day = datetime.combine(MON, time(21, 15), tzinfo=UTC)
    early = (_value(MON, "5.00", same_day), _value(TUE, "5.01", _released(TUE)))
    boundary = (
        _value(MON, "5.00", _day_end(MON)),
        _value(TUE, "5.01", _released(TUE)),
    )

    report = _assess(early, policy=policy)

    availability = _check(report, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert (availability.status, availability.examined_count) == ("fail", 2)
    (finding,) = _findings(report, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert finding.code == "available_before_observation_day_end"
    assert (finding.first_date, finding.last_date) == (MON, MON)
    assert finding.observed == same_day.isoformat()
    assert finding.limit == _day_end(MON).isoformat()
    assert _assess(boundary, policy=policy).result is ValidationResult.PASS


def test_non_monotonic_availability_is_reported() -> None:
    policy = _policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,))
    points = (
        _value(MON, "5.00", _released(WED)),
        _value(TUE, "5.01", _released(TUE)),
    )

    report = _assess(points, policy=policy)

    (finding,) = _findings(report, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert finding.code == "availability_not_monotonic"
    assert (finding.first_date, finding.last_date) == (MON, TUE)
    assert finding.observed == _released(TUE).isoformat()
    assert finding.limit == _released(WED).isoformat()
    assert report.result is ValidationResult.FAIL


def test_availability_after_the_cutoff_is_reported() -> None:
    policy = _policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,))
    points = _clean_week_with_availability()
    cutoff = _released(FRI) - timedelta(seconds=1)

    report = _assess(points, policy=policy, cutoff=cutoff)

    (finding,) = _findings(report, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert finding.code == "available_after_cutoff"
    assert (finding.first_date, finding.last_date) == (FRI, FRI)
    assert finding.observed == _released(FRI).isoformat()
    assert finding.limit == cutoff.isoformat()
    assert report.result is ValidationResult.FAIL
    at_cutoff = _assess(points, policy=policy, cutoff=_released(FRI))
    assert at_cutoff.result is ValidationResult.PASS
    assert _assess(points, policy=policy, cutoff=None).result is ValidationResult.PASS


def test_a_cutoff_in_another_zone_is_compared_as_the_same_instant() -> None:
    policy = _policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,))
    fixed_offset = timezone(timedelta(hours=-5))
    cutoff = _released(FRI).astimezone(fixed_offset)
    points = _clean_week_with_availability()

    report = _assess(points, policy=policy, cutoff=cutoff)
    early = _assess(points, policy=policy, cutoff=cutoff - timedelta(seconds=1))

    assert report.result is ValidationResult.PASS
    assert early.result is ValidationResult.FAIL
    (finding,) = early.findings
    assert finding.limit == (_released(FRI) - timedelta(seconds=1)).isoformat()


def test_availability_is_not_evaluated_when_no_point_states_it() -> None:
    soft = _assess(_clean_week())
    hard = _assess(
        _clean_week(),
        policy=_policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,)),
    )

    availability = _check(soft, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert (availability.status, availability.examined_count) == (
        "not_evaluated",
        0,
    )
    assert soft.result is ValidationResult.PASS
    assert hard.result is ValidationResult.FAIL
    assert hard.findings == ()


def test_partly_stated_availability_is_a_finding_not_a_silent_skip() -> None:
    policy = _policy(hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,))
    points = (_value(MON, "5.00", _released(MON)), _value(TUE, "5.01"))

    report = _assess(points, policy=policy)

    (finding,) = _findings(report, DataQualityCheck.AVAILABILITY_VIOLATION)
    assert finding.code == "availability_not_stated"
    assert (finding.first_date, finding.last_date) == (TUE, TUE)
    assert report.result is ValidationResult.FAIL


# --- optional inputs, severity and result ---------------------------------


def test_no_expected_dates_gives_not_evaluated_and_fails_when_the_gap_is_hard() -> None:
    hard = _assess(
        _clean_week(),
        policy=_policy(hard_checks=(DataQualityCheck.CALENDAR_GAP,)),
        expected_dates=None,
    )
    soft = _assess(_clean_week(), expected_dates=None)

    for report in (hard, soft):
        gap = _check(report, DataQualityCheck.CALENDAR_GAP)
        unexpected = _check(report, DataQualityCheck.UNEXPECTED_DATE)
        assert (gap.status, gap.examined_count) == ("not_evaluated", 0)
        assert (unexpected.status, unexpected.examined_count) == ("not_evaluated", 0)
        assert report.expected_dates_hash is None
        assert report.findings == ()
    assert hard.result is ValidationResult.FAIL
    assert soft.result is ValidationResult.PASS
    with pytest.raises(DataQualityError, match="calendar_gap=not_evaluated"):
        require_passing(hard)


def test_a_finding_of_a_check_that_is_not_hard_is_only_a_warning() -> None:
    points = (_value(MON, "5.00"), _value(TUE, "9.00"))
    soft = _policy(hard_checks=(DataQualityCheck.DUPLICATE_KEY,))

    report = _assess(points, policy=soft)

    (finding,) = report.findings
    assert finding.check is DataQualityCheck.EXTREME_JUMP
    assert finding.severity is FindingSeverity.WARNING
    assert _check(report, DataQualityCheck.EXTREME_JUMP).status == "warn"
    assert report.result is ValidationResult.PASS
    require_passing(report)


def test_findings_are_in_canonical_order() -> None:
    points = (
        _value(WED, "30"),
        _value(TUE, "5.00"),
        _value(TUE, "5.00"),
        _value(MON, "-9"),
    )

    report = _assess(points)

    keys = [(item.check.value, item.first_date, item.code) for item in report.findings]
    assert keys == sorted(keys)
    assert len(report.findings) >= 5


def test_repeated_identical_violations_merge_into_one_counted_finding() -> None:
    points = (
        _value(WED, "5.02"),
        _value(TUE, "5.01"),
        _value(WED, "5.02"),
        _value(TUE, "5.01"),
    )
    policy = _policy(hard_checks=(DataQualityCheck.NON_MONOTONIC_ORDER,))

    report = _assess(points, policy=policy)

    (finding,) = _findings(report, DataQualityCheck.NON_MONOTONIC_ORDER)
    assert (finding.first_date, finding.last_date, finding.count) == (TUE, WED, 2)
    order = _check(report, DataQualityCheck.NON_MONOTONIC_ORDER)
    assert (order.status, order.examined_count, order.finding_count) == ("fail", 3, 1)
    duplicates = _findings(report, DataQualityCheck.DUPLICATE_KEY)
    assert [(item.first_date, item.count) for item in duplicates] == [
        (TUE, 2),
        (WED, 2),
    ]
    assert {item.severity for item in duplicates} == {FindingSeverity.WARNING}
    assert report.report_hash == data_quality_report_hash(report)


# --- hashes ---------------------------------------------------------------


def test_the_report_hash_is_stable_and_sensitive_to_the_policy() -> None:
    points = _clean_week()
    first = _assess(points)
    second = _assess(points)
    renamed = _assess(points, policy=_policy(policy_id="another-policy"))
    tighter = _assess(points, policy=_policy(max_stale_run=2))

    assert first == second
    assert first.report_hash == second.report_hash
    assert first.report_hash == data_quality_report_hash(first)
    assert first.policy_hash == _policy().policy_hash
    assert renamed.policy_hash != first.policy_hash
    assert renamed.report_hash != first.report_hash
    assert tighter.report_hash != first.report_hash
    assert len({first.report_hash, renamed.report_hash, tighter.report_hash}) == 3


def test_the_report_hash_binds_the_subject_and_the_source_bytes() -> None:
    points = _clean_week()
    base = _assess(points)
    other_subject = assess_daily_values(
        points,
        subject_kind="daily_price_observations",
        subject_hash=SUBJECT_HASH,
        source_sha256=SOURCE_SHA256,
        policy=_policy(),
        expected_dates=None,
        cutoff=None,
    )
    other_source = assess_daily_values(
        points,
        subject_kind="public_daily_series",
        subject_hash=SUBJECT_HASH,
        source_sha256="c" * 64,
        policy=_policy(),
        expected_dates=None,
        cutoff=None,
    )

    assert len({base.report_hash, other_subject.report_hash}) == 2
    assert other_source.report_hash != base.report_hash


def test_a_tampered_report_hash_is_rejected() -> None:
    report = _assess(_clean_week())

    with pytest.raises(ValidationError, match="data_quality_report_hash_mismatch"):
        DataQualityReportV1.model_validate(dict(report) | {"report_hash": HASH_ZERO})
    with pytest.raises(ValidationError, match="data_quality_report_hash_mismatch"):
        DataQualityReportV1.model_validate(dict(report) | {"subject_hash": "c" * 64})


def test_the_policy_hash_is_self_excluding_and_checked() -> None:
    policy = _policy()

    assert policy.policy_hash == data_quality_policy_hash(policy)
    assert policy.schema_version == "1"
    with pytest.raises(ValidationError, match="data_quality_policy_hash_mismatch"):
        DataQualityPolicyV1.model_validate(dict(policy) | {"max_stale_run": 99})
    with pytest.raises(ValidationError, match="data_quality_policy_hash_mismatch"):
        DataQualityPolicyV1.model_validate(dict(policy) | {"policy_hash": HASH_ZERO})


# --- model consistency ----------------------------------------------------


def test_a_passing_report_carrying_an_error_finding_is_rejected() -> None:
    failing = _assess((_value(MON, "5.00"), _value(MON, "5.01")))
    assert failing.result is ValidationResult.FAIL

    with pytest.raises(ValidationError, match="data_quality_report_result_mismatch"):
        _resealed(failing, result=ValidationResult.PASS)


def test_a_failed_report_needs_an_error_or_an_unevaluated_hard_check() -> None:
    passing = _assess(_clean_week())
    assert passing.result is ValidationResult.PASS

    with pytest.raises(ValidationError, match="data_quality_report_result_mismatch"):
        _resealed(passing, result=ValidationResult.FAIL)


def test_an_unevaluated_hard_check_cannot_be_resealed_as_passing() -> None:
    strict = _policy(hard_checks=(DataQualityCheck.CALENDAR_GAP,))
    soft = _policy(hard_checks=())
    failing = _assess(_clean_week(), policy=strict)
    assert failing.result is ValidationResult.FAIL

    with pytest.raises(ValidationError, match="data_quality_report_result_mismatch"):
        _resealed(failing, result=ValidationResult.PASS)
    # Swapping in a softer policy under the strict policy's hash is refused.
    with pytest.raises(ValidationError, match="data_quality_report_policy_hash"):
        _resealed(failing, policy=soft, result=ValidationResult.PASS)
    # Softening both is a different report that names the softer policy.
    softened = _resealed(
        failing,
        policy=soft,
        policy_hash=soft.policy_hash,
        result=ValidationResult.PASS,
    )
    assert softened.policy_hash != strict.policy_hash
    assert softened.report_hash != failing.report_hash


def test_a_hard_check_finding_cannot_be_downgraded_to_a_warning() -> None:
    failing = _assess((_value(MON, "5.00"), _value(MON, "5.01")))
    (finding,) = failing.findings
    downgraded = finding.model_copy(update={"severity": FindingSeverity.WARNING})
    checks = tuple(
        item.model_copy(update={"status": "warn"})
        if item.check is DataQualityCheck.DUPLICATE_KEY
        else item
        for item in failing.checks
    )

    with pytest.raises(ValidationError, match="data_quality_report_severity_mismatch"):
        _resealed(
            failing,
            findings=(downgraded,),
            checks=checks,
            result=ValidationResult.PASS,
        )


def test_every_check_must_appear_exactly_once_in_canonical_order() -> None:
    report = _assess(_clean_week())

    with pytest.raises(ValidationError, match="data_quality_report_checks_not_canon"):
        _resealed(report, checks=report.checks[1:])
    with pytest.raises(ValidationError, match="data_quality_report_checks_not_canon"):
        _resealed(report, checks=tuple(reversed(report.checks)))
    with pytest.raises(ValidationError, match="data_quality_report_checks_not_canon"):
        _resealed(report, checks=(*report.checks, report.checks[0]))


def test_check_results_must_agree_with_the_findings() -> None:
    failing = _assess((_value(MON, "5.00"), _value(MON, "5.01")))

    with pytest.raises(ValidationError, match="data_quality_report_check_mismatch"):
        _resealed(failing, findings=())
    with pytest.raises(ValidationError, match="data_quality_report_findings_not_can"):
        _resealed(failing, findings=(*failing.findings, *failing.findings))


def test_findings_out_of_canonical_order_are_rejected() -> None:
    points = (_value(MON, "-9"), _value(TUE, "30"), _value(WED, "5.00"))
    report = _assess(points, policy=_policy(max_abs_jump="100"))
    assert len(report.findings) == 2

    with pytest.raises(ValidationError, match="data_quality_report_findings_not_can"):
        _resealed(report, findings=tuple(reversed(report.findings)))


def test_the_calendar_basis_must_agree_with_the_calendar_checks() -> None:
    without = _assess(_clean_week())
    with_calendar = _assess(_clean_week(), expected_dates=WEEK)

    with pytest.raises(ValidationError, match="data_quality_report_calendar_basis"):
        _resealed(without, expected_dates_hash=expected_dates_content_hash(WEEK))
    with pytest.raises(ValidationError, match="data_quality_report_calendar_basis"):
        _resealed(with_calendar, expected_dates_hash=None)


def test_a_nested_model_assembled_without_validation_is_revalidated() -> None:
    report = _assess(_clean_week())
    loose = DataQualityPolicyV1.model_construct(
        **(dict(report.policy) | {"max_stale_run": 0})
    )
    rehashed = DataQualityPolicyV1.model_construct(
        **(dict(loose) | {"policy_hash": data_quality_policy_hash(loose)})
    )
    relabeled = DataQualityReportV1.model_construct(
        **(dict(report) | {"result": ValidationResult.FAIL})
    )

    with pytest.raises(ValidationError, match="max_stale_run"):
        _resealed(report, policy=rehashed, policy_hash=rehashed.policy_hash)
    with pytest.raises(ValidationError, match="data_quality_report_result_mismatch"):
        DataQualityReportV1.model_validate(relabeled)
    assert DataQualityReportV1.model_validate(report) == report


def test_finding_and_check_result_shapes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="data_quality_finding_dates_inverted"):
        DataQualityFindingV1(
            check=DataQualityCheck.DUPLICATE_KEY,
            severity=FindingSeverity.ERROR,
            code="duplicate_date",
            first_date=TUE,
            last_date=MON,
            count=2,
            observed="2",
            limit="1",
        )
    with pytest.raises(ValidationError, match="data_quality_finding_severity"):
        DataQualityFindingV1(
            check=DataQualityCheck.DUPLICATE_KEY,
            severity=FindingSeverity.INFO,
            code="duplicate_date",
            first_date=MON,
            last_date=MON,
            count=2,
            observed="2",
            limit="1",
        )
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        DataQualityFindingV1(
            check=DataQualityCheck.DUPLICATE_KEY,
            severity=FindingSeverity.ERROR,
            code="duplicate_date",
            first_date=MON,
            last_date=MON,
            count=0,
            observed=None,
            limit=None,
        )
    for status, examined, found in (
        ("pass", 3, 1),
        ("warn", 3, 0),
        ("fail", 3, 0),
        ("not_evaluated", 3, 0),
        ("not_evaluated", 0, 1),
    ):
        with pytest.raises(ValidationError, match="data_quality_check_result"):
            DataQualityCheckResultV1.model_validate(
                {
                    "check": DataQualityCheck.STALE_RUN,
                    "status": status,
                    "examined_count": examined,
                    "finding_count": found,
                }
            )


def test_models_are_frozen_and_refuse_unknown_fields() -> None:
    report = _assess(_clean_week())

    with pytest.raises(ValidationError, match="frozen"):
        report.result = ValidationResult.FAIL
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataQualityReportV1.model_validate(dict(report) | {"note": "x"})
    with pytest.raises(ValidationError):
        DataQualityReportV1.model_validate(dict(report) | {"subject_kind": "other"})
    with pytest.raises(ValidationError):
        DataQualityReportV1.model_validate(dict(report) | {"schema_version": "2"})


# --- policy validation ----------------------------------------------------


def test_policy_shapes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="data_quality_policy_bounds_inverted"):
        _policy(lower_bound="5", upper_bound="4")
    with pytest.raises(ValidationError, match="data_quality_policy_jump_limit"):
        _policy(max_abs_jump="-0.01")
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        _policy(max_stale_run=0)
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _policy(max_missing_run=-1)
    with pytest.raises(ValidationError, match="data_quality_policy_hard_checks"):
        _policy(hard_checks=tuple(reversed(ALWAYS_EVALUATED)))
    with pytest.raises(ValidationError, match="data_quality_policy_hard_checks"):
        _policy(hard_checks=(ALWAYS_EVALUATED[0], ALWAYS_EVALUATED[0]))
    with pytest.raises(ValidationError):
        _policy(lower_bound="NaN")
    with pytest.raises(ValidationError):
        _policy(upper_bound="Infinity")
    with pytest.raises(ValidationError):
        _policy(policy_id="   ")


def test_a_policy_may_have_no_hard_checks_and_then_never_fails_on_findings() -> None:
    policy = _policy(hard_checks=())
    points = (_value(MON, "5.00"), _value(MON, "99"))

    report = _assess(points, policy=policy)

    assert report.findings != ()
    assert {item.severity for item in report.findings} == {FindingSeverity.WARNING}
    assert report.result is ValidationResult.PASS


# --- refused inputs -------------------------------------------------------


def test_an_empty_series_is_refused_rather_than_passed_vacuously() -> None:
    with pytest.raises(DataQualityInputError, match="data_quality_points_empty"):
        _assess(())


def test_malformed_points_are_refused() -> None:
    naive = datetime(2024, 1, 9, 21, 15)
    both = DatedValue(
        observed_on=MON, value=Decimal("5"), missing_marker="ND", available_at=None
    )
    neither = DatedValue(
        observed_on=MON, value=None, missing_marker=None, available_at=None
    )
    blank = DatedValue(
        observed_on=MON, value=None, missing_marker="  ", available_at=None
    )
    stamped = DatedValue(
        observed_on=datetime(2024, 1, 8, tzinfo=UTC),
        value=Decimal("5"),
        missing_marker=None,
        available_at=None,
    )

    for bad in (both, neither, blank):
        with pytest.raises(DataQualityInputError, match="data_quality_point_state"):
            _assess((bad,))
    with pytest.raises(DataQualityInputError, match="data_quality_point_date"):
        _assess((stamped,))
    for text in ("NaN", "Infinity", "-Infinity", "sNaN"):
        with pytest.raises(DataQualityInputError, match="data_quality_point_value"):
            _assess((_value(MON, text),))
    with pytest.raises(DataQualityInputError, match="data_quality_point_availabil"):
        _assess((_value(MON, "5.00", naive),))
    with pytest.raises(DataQualityInputError, match="data_quality_cutoff_naive"):
        _assess(_clean_week(), cutoff=naive)


def test_a_binary_float_value_is_refused() -> None:
    floated = DatedValue(
        observed_on=MON,
        value=5.3,  # type: ignore[arg-type]
        missing_marker=None,
        available_at=None,
    )

    with pytest.raises(DataQualityInputError, match="data_quality_point_value"):
        _assess((floated,))


def test_an_ambiguous_expected_calendar_is_refused() -> None:
    with pytest.raises(DataQualityInputError, match="data_quality_expected_dates"):
        _assess(_clean_week(), expected_dates=(MON, MON, TUE))
    # Order alone carries no meaning: the calendar is a set of dates.
    shuffled = _assess(_clean_week(), expected_dates=tuple(reversed(WEEK)))
    assert shuffled.expected_dates_hash == expected_dates_content_hash(WEEK)
    assert shuffled == _assess(_clean_week(), expected_dates=WEEK)


def test_a_forged_policy_is_revalidated_before_use() -> None:
    forged = DataQualityPolicyV1.model_construct(
        **(dict(_policy()) | {"upper_bound": Decimal("1000000")})
    )

    with pytest.raises(DataQualityInputError, match="data_quality_policy_invalid"):
        _assess(_clean_week(), policy=forged)


def test_arithmetic_that_cannot_be_exact_is_refused() -> None:
    points = (_value(MON, "1E+400"), _value(TUE, "1E-400"))
    policy = _policy(
        hard_checks=(), lower_bound="-1E+500", upper_bound="1E+500", max_abs_jump="1"
    )

    with pytest.raises(DataQualityInputError, match="data_quality_arithmetic_inexact"):
        _assess(points, policy=policy)


# --- require_passing ------------------------------------------------------


def test_require_passing_raises_with_the_report_attached() -> None:
    failing = _assess((_value(MON, "5.00"), _value(MON, "5.01")))

    with pytest.raises(DataQualityError, match="duplicate_key=fail") as caught:
        require_passing(failing)

    assert caught.value.report == failing
    assert isinstance(caught.value, DriftError)
    assert isinstance(caught.value, ValueError)


def test_require_passing_refuses_a_forged_passing_report() -> None:
    failing = _assess((_value(MON, "5.00"), _value(MON, "5.01")))
    forged = DataQualityReportV1.model_construct(
        **(dict(failing) | {"result": ValidationResult.PASS})
    )

    with pytest.raises(DataQualityInputError, match="data_quality_report_invalid"):
        require_passing(forged)
    with pytest.raises(DataQualityInputError, match="data_quality_report_invalid"):
        require_passing(None)  # type: ignore[arg-type]
