"""Unit tests for the public daily rate series domain types.

Every series here is synthetic and built inline: the identifiers, values and
hashes are invented for the test and are not Federal Reserve data.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from typing import Literal

import pytest
from pydantic import ValidationError

from drift.domain.public_series import (
    MAX_RELEASE_LAG_WEEKDAYS,
    PUBLIC_SERIES_LIMITATION_MODELED_AVAILABILITY,
    PUBLIC_SERIES_LIMITATION_SINGLE_DOWNLOAD,
    PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES,
    PUBLIC_SERIES_REQUIRED_LIMITATIONS,
    PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,
    PublicationLagPolicyV1,
    PublicDailyRatePointV1,
    PublicDailyRateSeriesV1,
    PublicSeriesRightsRecordV1,
    modeled_available_at,
    public_daily_rate_series_hash,
    public_series_rights_record_hash,
    publication_lag_policy_hash,
    seal_public_daily_rate_series,
    seal_public_series_rights_record,
    seal_publication_lag_policy,
)

HASH_ZERO = "0" * 64
SOURCE_SHA256 = "d" * 64
TERMS_SHA256 = "e" * 64
RELEASE_MINUTE = 21 * 60 + 15

THU = date(2024, 1, 4)
FRI = date(2024, 1, 5)
MON = date(2024, 1, 8)
TUE = date(2024, 1, 9)
FRI_BEFORE_HOLIDAY = date(2024, 1, 12)
HOLIDAY_MON = date(2024, 1, 15)
TUE_AFTER_HOLIDAY = date(2024, 1, 16)


def _lag(
    *,
    weekdays: int = 1,
    minute: int = RELEASE_MINUTE,
    non_release_dates: tuple[date, ...] = (),
    policy_id: str = "synthetic-next-weekday-2115z",
) -> PublicationLagPolicyV1:
    return seal_publication_lag_policy(
        policy_id=policy_id,
        release_lag_weekdays=weekdays,
        release_utc_minute_of_day=minute,
        non_release_dates=non_release_dates,
    )


def _rights(
    *,
    series_identifier: str = "SYNTH_A.B",
    limitations: tuple[str, ...] = (
        PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,
    ),
) -> PublicSeriesRightsRecordV1:
    return seal_public_series_rights_record(
        publisher_legal_name="Synthetic Publisher (not a real record)",
        product="Synthetic daily rates",
        series_identifier=series_identifier,
        rights_basis="us_federal_government_work_public_domain",
        terms_evidence_sha256=TERMS_SHA256,
        recorded_by="synthetic-test-recorder",
        recorded_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
        limitations=limitations,
    )


def _point(
    day: date, text: str, policy: PublicationLagPolicyV1 | None = None
) -> PublicDailyRatePointV1:
    state: Literal["value", "missing", "not_published"]
    value: Decimal | None
    if text == "":
        state, value = "not_published", None
    elif text == "ND":
        state, value = "missing", None
    else:
        state, value = "value", Decimal(text)
    return PublicDailyRatePointV1(
        observed_on=day,
        state=state,
        native_text=text,
        value_percent=value,
        available_at=modeled_available_at(day, _lag() if policy is None else policy),
    )


def _series(
    points: tuple[PublicDailyRatePointV1, ...],
    *,
    lag_policy: PublicationLagPolicyV1 | None = None,
    limitations: tuple[str, ...] = PUBLIC_SERIES_REQUIRED_LIMITATIONS,
) -> PublicDailyRateSeriesV1:
    return seal_public_daily_rate_series(
        source_id="synthetic-public-series",
        series_identifier="SYNTH_A.B",
        description="Synthetic rate A (not real data)",
        unit="Percent:_Per_Year",
        source_sha256=SOURCE_SHA256,
        source_byte_size=321,
        points=points,
        lag_policy=_lag() if lag_policy is None else lag_policy,
        rights_record_hash=_rights().record_hash,
        acknowledged_limitations=limitations,
    )


def _three_points() -> tuple[PublicDailyRatePointV1, ...]:
    return (_point(THU, "5.26"), _point(FRI, "ND"), _point(MON, "5.28"))


def _resealed(
    series: PublicDailyRateSeriesV1, **update: object
) -> PublicDailyRateSeriesV1:
    """One series edited and re-hashed, so only a semantic guard can refuse it."""
    draft = PublicDailyRateSeriesV1.model_construct(**(dict(series) | update))
    return PublicDailyRateSeriesV1.model_validate(
        dict(draft) | {"series_hash": public_daily_rate_series_hash(draft)}
    )


def _resealed_rights(
    record: PublicSeriesRightsRecordV1, **update: object
) -> PublicSeriesRightsRecordV1:
    draft = PublicSeriesRightsRecordV1.model_construct(**(dict(record) | update))
    return PublicSeriesRightsRecordV1.model_validate(
        dict(draft) | {"record_hash": public_series_rights_record_hash(draft)}
    )


def _at(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second), tzinfo=UTC)


# --- modeled availability -------------------------------------------------


def test_a_friday_observation_is_available_on_monday_at_the_release_minute() -> None:
    assert FRI.weekday() == 4

    assert modeled_available_at(FRI, _lag()) == _at(MON, 21, 15)
    assert modeled_available_at(THU, _lag()) == _at(FRI, 21, 15)
    assert modeled_available_at(FRI, _lag(minute=0)) == _at(MON, 0, 0)
    assert modeled_available_at(FRI, _lag(minute=1439)) == _at(MON, 23, 59)
    assert modeled_available_at(FRI, _lag()).tzinfo is UTC


def test_non_release_dates_roll_the_release_forward() -> None:
    plain = _lag()
    with_holiday = _lag(non_release_dates=(HOLIDAY_MON,))

    assert modeled_available_at(FRI_BEFORE_HOLIDAY, plain) == _at(HOLIDAY_MON, 21, 15)
    assert modeled_available_at(FRI_BEFORE_HOLIDAY, with_holiday) == _at(
        TUE_AFTER_HOLIDAY, 21, 15
    )
    # An observation made on the non-release date itself still waits a release day.
    assert modeled_available_at(HOLIDAY_MON, with_holiday) == _at(
        TUE_AFTER_HOLIDAY, 21, 15
    )


def test_a_two_weekday_lag_counts_only_release_days() -> None:
    two = _lag(weekdays=2)
    two_with_holiday = _lag(weekdays=2, non_release_dates=(HOLIDAY_MON,))

    assert modeled_available_at(THU, two) == _at(MON, 21, 15)
    assert modeled_available_at(FRI, two) == _at(TUE, 21, 15)
    assert modeled_available_at(FRI_BEFORE_HOLIDAY, two_with_holiday) == _at(
        date(2024, 1, 17), 21, 15
    )


def test_modeled_availability_is_monotonic_and_never_inside_the_observed_day() -> None:
    policy = _lag(minute=0, non_release_dates=(HOLIDAY_MON,))
    days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(60)]

    stamps = [modeled_available_at(day, policy) for day in days]

    for day, stamp in zip(days, stamps, strict=True):
        assert stamp >= _at(day + timedelta(days=1), 0, 0)
        assert stamp.date().weekday() < 5
        assert stamp.date() != HOLIDAY_MON
    assert all(later >= earlier for earlier, later in pairwise(stamps))


def test_modeled_availability_refuses_a_date_it_cannot_represent() -> None:
    with pytest.raises(ValueError, match="public_series_release_date_overflow"):
        modeled_available_at(date.max, _lag())
    with pytest.raises(ValueError, match="public_series_observed_on_invalid"):
        modeled_available_at(_at(FRI, 12, 0), _lag())


# --- value_as_of ----------------------------------------------------------


def test_value_as_of_one_second_before_release_returns_the_prior_point() -> None:
    series = _series(_three_points())
    thursday, friday, monday = series.points

    assert series.value_as_of(_at(FRI, 21, 14, 59)) is None
    assert series.value_as_of(_at(FRI, 21, 15)) == thursday
    assert series.value_as_of(_at(MON, 21, 14, 59)) == thursday
    assert series.value_as_of(_at(MON, 21, 15)) == friday
    assert series.value_as_of(_at(TUE, 21, 14, 59)) == friday
    assert series.value_as_of(_at(TUE, 21, 15)) == monday
    assert series.value_as_of(_at(date(2030, 1, 1), 0, 0)) == monday


def test_a_missing_point_is_returned_as_missing_and_never_forward_filled() -> None:
    series = _series(_three_points())

    seen = series.value_as_of(_at(MON, 21, 15))

    assert seen is not None
    assert seen.observed_on == FRI
    assert seen.state == "missing"
    assert seen.native_text == "ND"
    assert seen.value_percent is None


def test_an_unpublished_interior_point_is_returned_as_not_published() -> None:
    series = _series((_point(THU, "5.26"), _point(FRI, ""), _point(MON, "5.28")))

    seen = series.value_as_of(_at(MON, 21, 15))

    assert seen is not None
    assert (seen.state, seen.native_text, seen.value_percent) == (
        "not_published",
        "",
        None,
    )


def test_value_as_of_compares_instants_and_refuses_a_naive_cutoff() -> None:
    series = _series(_three_points())
    offset = timezone(timedelta(hours=-5))
    local_release = _at(FRI, 21, 15).astimezone(offset)

    assert series.value_as_of(local_release) == series.points[0]
    assert series.value_as_of(local_release - timedelta(seconds=1)) is None
    with pytest.raises(ValueError, match="public_series_cutoff_naive"):
        series.value_as_of(datetime(2024, 1, 5, 21, 15))


# --- the series model -----------------------------------------------------


def test_a_sealed_series_carries_its_inputs_and_a_self_excluding_hash() -> None:
    series = _series(_three_points())

    assert series.schema_version == "1"
    assert series.lane == "exploratory"
    assert series.series_hash == public_daily_rate_series_hash(series)
    assert series.lag_policy == _lag()
    assert series.rights_record_hash == _rights().record_hash
    assert series.acknowledged_limitations == PUBLIC_SERIES_REQUIRED_LIMITATIONS
    assert series == _series(_three_points())
    other = _series((_point(THU, "5.27"), _point(FRI, "ND"), _point(MON, "5.28")))
    assert other.series_hash != series.series_hash


def test_a_tampered_available_at_is_rejected_even_when_rehashed() -> None:
    series = _series(_three_points())
    first = series.points[0]
    early = PublicDailyRatePointV1(
        observed_on=first.observed_on,
        state=first.state,
        native_text=first.native_text,
        value_percent=first.value_percent,
        available_at=first.available_at - timedelta(days=1),
    )

    with pytest.raises(ValidationError, match="public_series_available_at_mismatch"):
        _resealed(series, points=(early, *series.points[1:]))


def test_a_swapped_lag_policy_is_rejected_even_when_rehashed() -> None:
    series = _series(_three_points())

    with pytest.raises(ValidationError, match="public_series_available_at_mismatch"):
        _resealed(series, lag_policy=_lag(minute=0))


def test_a_nested_same_day_lag_policy_cannot_ride_in_unvalidated() -> None:
    """The look-ahead attack: a zero-day lag would publish inside the day."""
    series = _series(_three_points())
    loose = PublicationLagPolicyV1.model_construct(
        **(dict(_lag()) | {"release_lag_weekdays": 0})
    )
    same_day = PublicationLagPolicyV1.model_construct(
        **(dict(loose) | {"policy_hash": publication_lag_policy_hash(loose)})
    )
    points = tuple(
        PublicDailyRatePointV1(
            observed_on=point.observed_on,
            state=point.state,
            native_text=point.native_text,
            value_percent=point.value_percent,
            available_at=_at(point.observed_on, 21, 15),
        )
        for point in series.points
    )

    with pytest.raises(ValidationError, match="release_lag_weekdays"):
        _resealed(series, lag_policy=same_day, points=points)


def test_a_nested_point_assembled_without_validation_is_revalidated() -> None:
    series = _series(_three_points())
    loose = PublicDailyRatePointV1.model_construct(
        **(dict(series.points[0]) | {"value_percent": Decimal("9.99")})
    )
    relabeled = PublicDailyRateSeriesV1.model_construct(
        **(dict(series) | {"description": "Relabeled without rehashing"})
    )

    with pytest.raises(ValidationError, match="public_series_point_state_mismatch"):
        _resealed(series, points=(loose, *series.points[1:]))
    with pytest.raises(ValidationError, match="public_series_hash_mismatch"):
        PublicDailyRateSeriesV1.model_validate(relabeled)
    assert PublicDailyRateSeriesV1.model_validate(series) == series


def test_a_tampered_series_hash_is_rejected() -> None:
    series = _series(_three_points())

    with pytest.raises(ValidationError, match="public_series_hash_mismatch"):
        PublicDailyRateSeriesV1.model_validate(
            dict(series) | {"series_hash": HASH_ZERO}
        )
    with pytest.raises(ValidationError, match="public_series_hash_mismatch"):
        PublicDailyRateSeriesV1.model_validate(
            dict(series) | {"source_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="public_series_hash_mismatch"):
        PublicDailyRateSeriesV1.model_validate(
            dict(series) | {"rights_record_hash": "f" * 64}
        )


def test_the_series_lane_cannot_be_changed() -> None:
    series = _series(_three_points())

    with pytest.raises(ValidationError, match="exploratory"):
        _resealed(series, lane="promotion")
    with pytest.raises(ValidationError, match="exploratory"):
        series.model_copy(update={"lane": "promotion"})
    with pytest.raises(ValidationError, match="frozen"):
        series.lane = "exploratory"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicDailyRateSeriesV1.model_validate(
            dict(series) | {"promotion_eligible": True}
        )


def test_limitations_must_be_nonempty_sorted_unique_and_complete() -> None:
    points = _three_points()
    required = PUBLIC_SERIES_REQUIRED_LIMITATIONS

    assert required == tuple(
        sorted(
            (
                PUBLIC_SERIES_LIMITATION_MODELED_AVAILABILITY,
                PUBLIC_SERIES_LIMITATION_SINGLE_DOWNLOAD,
                PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES,
            )
        )
    )
    with pytest.raises(ValidationError, match="public_series_limitations_empty"):
        _series(points, limitations=())
    with pytest.raises(ValidationError, match="public_series_limitations_not_canon"):
        _series(points, limitations=tuple(reversed(required)))
    with pytest.raises(ValidationError, match="public_series_limitations_not_canon"):
        _series(points, limitations=(required[0], *required))
    for dropped in required:
        kept = tuple(item for item in required if item != dropped)
        with pytest.raises(ValidationError, match="public_series_limitations_incomp"):
            _series(points, limitations=kept)
    extended = tuple(sorted((*required, "another-acknowledged-limitation")))
    assert _series(points, limitations=extended).acknowledged_limitations == extended


def test_dates_must_be_unique_and_ascending() -> None:
    with pytest.raises(ValidationError, match="public_series_dates_not_ascending"):
        _series((_point(FRI, "5.26"), _point(THU, "5.25")))
    with pytest.raises(ValidationError, match="public_series_dates_not_ascending"):
        _series((_point(THU, "5.26"), _point(THU, "5.26")))
    with pytest.raises(ValidationError, match="public_series_points_empty"):
        _series(())


def test_point_state_and_value_must_agree() -> None:
    stamp = modeled_available_at(THU, _lag())

    def build(
        state: Literal["value", "missing", "not_published"],
        native_text: str,
        value: Decimal | None,
    ) -> PublicDailyRatePointV1:
        return PublicDailyRatePointV1(
            observed_on=THU,
            state=state,
            native_text=native_text,
            value_percent=value,
            available_at=stamp,
        )

    kept = build("value", "5.30", Decimal("5.30"))
    assert str(kept.value_percent) == "5.30"
    assert build("value", "-0.05", Decimal("-0.05")).value_percent == Decimal("-0.05")
    assert build("missing", "ND", None).value_percent is None
    assert build("not_published", "", None).native_text == ""
    refused: tuple[
        tuple[Literal["value", "missing", "not_published"], str, Decimal | None], ...
    ] = (
        ("value", "5.30", None),
        ("value", "5.30", Decimal("5.3")),
        ("value", "5.30", Decimal("5.31")),
        ("value", "5.30 ", Decimal("5.30")),
        ("value", "5.3E0", Decimal("5.3")),
        ("value", "ND", Decimal("5.30")),
        ("value", "", Decimal("0")),
        ("missing", "ND", Decimal("5.30")),
        ("missing", "", None),
        ("missing", "  ", None),
        ("missing", "5.30", None),
        ("not_published", "ND", None),
        ("not_published", "", Decimal("0")),
    )
    for state, native_text, value in refused:
        with pytest.raises(ValidationError, match="public_series_point_state"):
            build(state, native_text, value)
    with pytest.raises(ValidationError):
        build("value", "NaN", Decimal("NaN"))


def test_point_fields_are_strict() -> None:
    stamp = modeled_available_at(THU, _lag())
    base = {
        "observed_on": THU,
        "state": "value",
        "native_text": "5.30",
        "value_percent": Decimal("5.30"),
        "available_at": stamp,
    }

    assert PublicDailyRatePointV1.model_validate(base).value_percent == Decimal("5.30")
    for field, bad in (
        ("value_percent", 5.3),
        ("value_percent", "5.30"),
        ("observed_on", "2024-01-04"),
        ("available_at", datetime(2024, 1, 5, 21, 15)),
        ("state", "estimated"),
    ):
        with pytest.raises(ValidationError):
            PublicDailyRatePointV1.model_validate(base | {field: bad})


# --- the lag policy -------------------------------------------------------


def test_the_lag_policy_hash_is_self_excluding_and_checked() -> None:
    policy = _lag(non_release_dates=(HOLIDAY_MON,))

    assert policy.schema_version == "1"
    assert policy.basis == "modeled_rule"
    assert policy.policy_hash == publication_lag_policy_hash(policy)
    assert policy.policy_hash != _lag().policy_hash
    with pytest.raises(ValidationError, match="publication_lag_policy_hash_mismatch"):
        PublicationLagPolicyV1.model_validate(
            dict(policy) | {"release_lag_weekdays": 2}
        )
    with pytest.raises(ValidationError):
        PublicationLagPolicyV1.model_validate(dict(policy) | {"basis": "observed"})


def test_lag_policy_shapes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        _lag(weekdays=0)
    with pytest.raises(ValidationError, match="less than or equal to"):
        _lag(weekdays=MAX_RELEASE_LAG_WEEKDAYS + 1)
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _lag(minute=-1)
    with pytest.raises(ValidationError, match="less than or equal to 1439"):
        _lag(minute=1440)
    with pytest.raises(ValidationError, match="publication_lag_policy_non_release"):
        _lag(non_release_dates=(TUE_AFTER_HOLIDAY, HOLIDAY_MON))
    with pytest.raises(ValidationError, match="publication_lag_policy_non_release"):
        _lag(non_release_dates=(HOLIDAY_MON, HOLIDAY_MON))
    assert _lag(weekdays=MAX_RELEASE_LAG_WEEKDAYS).release_lag_weekdays == (
        MAX_RELEASE_LAG_WEEKDAYS
    )


# --- the rights record ----------------------------------------------------


def test_the_rights_record_is_exploratory_and_never_promotion_eligible() -> None:
    record = _rights()

    assert record.schema_version == "1"
    assert record.lane == "exploratory"
    assert record.promotion_eligible is False
    assert record.rights_basis == "us_federal_government_work_public_domain"
    assert record.record_hash == public_series_rights_record_hash(record)
    assert record.recorded_at.tzinfo is UTC


def test_the_rights_record_lane_and_promotion_eligibility_cannot_be_changed() -> None:
    record = _rights()

    with pytest.raises(ValidationError, match="promotion_eligible"):
        _resealed_rights(record, promotion_eligible=True)
    with pytest.raises(ValidationError, match="promotion_eligible"):
        _resealed_rights(record, promotion_eligible=1)
    with pytest.raises(ValidationError, match="exploratory"):
        _resealed_rights(record, lane="promotion")
    with pytest.raises(ValidationError, match="promotion_eligible"):
        record.model_copy(update={"promotion_eligible": True})
    with pytest.raises(ValidationError, match="frozen"):
        record.promotion_eligible = False
    with pytest.raises(ValidationError, match="rights_basis"):
        _resealed_rights(record, rights_basis="licensed_redistribution")


def test_a_tampered_rights_record_is_rejected() -> None:
    record = _rights()

    with pytest.raises(ValidationError, match="public_series_rights_hash_mismatch"):
        PublicSeriesRightsRecordV1.model_validate(
            dict(record) | {"record_hash": HASH_ZERO}
        )
    with pytest.raises(ValidationError, match="public_series_rights_hash_mismatch"):
        PublicSeriesRightsRecordV1.model_validate(
            dict(record) | {"recorded_by": "someone-else"}
        )
    with pytest.raises(ValidationError):
        PublicSeriesRightsRecordV1.model_validate(
            dict(record) | {"recorded_at": datetime(2026, 11, 17, 12, 0)}
        )


def test_rights_limitations_must_be_canonical_and_name_the_assertion() -> None:
    required = PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION

    with pytest.raises(ValidationError, match="public_series_rights_limitations"):
        _rights(limitations=())
    with pytest.raises(ValidationError, match="public_series_rights_limitations"):
        _rights(limitations=("another-limitation",))
    with pytest.raises(ValidationError, match="public_series_rights_limitations"):
        _rights(limitations=(required, required))
    with pytest.raises(ValidationError, match="public_series_rights_limitations"):
        _rights(limitations=tuple(sorted((required, "zz-later"), reverse=True)))
    extended = tuple(sorted((required, "another-limitation")))
    assert _rights(limitations=extended).limitations == extended
