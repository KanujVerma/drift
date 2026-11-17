"""Public daily rate series: rights record, publication-lag rule, points, series.

A public daily rate series is one column of a public statistical release (for
example one maturity of the Federal Reserve H.15 release) held as exact decimal
text, with the instant each observation is treated as public.

Limitations, stated plainly. Each one is also a constant below, and a series
cannot be built without acknowledging all three:

* Availability is modeled. ``available_at`` is computed from a caller-supplied
  publication-lag rule (weekdays, a fixed UTC minute, listed non-release
  dates). It is not an observed release time and there are no vintages: the
  rule cannot know about a late release, an unlisted closure or a change in
  the publisher's schedule, and a fixed UTC minute cannot follow a local
  release time across daylight-saving changes.
* Values come from one current download. A publisher may revise history, and
  the values a past decision could really have seen are not replayable from
  this record.
* The bytes are supplied by the caller. A SHA-256 over them proves which bytes
  were parsed, not where they came from.

A series belongs to the exploratory lane only. Neither it nor its rights
record can state anything else, and nothing here feeds the evaluator.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.serialization.canonical import content_hash

PUBLIC_SERIES_LIMITATION_MODELED_AVAILABILITY = (
    "availability-modeled-by-publication-lag-rule-without-release-vintages"
)
"""Availability comes from a rule, not from an observed release or a vintage."""

PUBLIC_SERIES_LIMITATION_SINGLE_DOWNLOAD = (
    "values-from-one-current-download-revisions-not-replayable"
)
"""Values are one current download, so past revisions cannot be replayed."""

PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES = (
    "origin-of-caller-supplied-bytes-not-authenticated"
)
"""The source bytes are hashed but their origin is not authenticated."""

PUBLIC_SERIES_REQUIRED_LIMITATIONS: tuple[str, ...] = tuple(
    sorted(
        (
            PUBLIC_SERIES_LIMITATION_MODELED_AVAILABILITY,
            PUBLIC_SERIES_LIMITATION_SINGLE_DOWNLOAD,
            PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES,
        )
    )
)
"""The limitations every series must acknowledge, in canonical order."""

PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION = (
    "recorded-assertion-by-named-recorder-not-an-adjudicated-rights-assessment"
)
"""Every rights record must carry this: it is an assertion, not a ruling."""

MAX_RELEASE_LAG_WEEKDAYS = 366
"""Structural ceiling on a lag rule, so the release-day walk stays bounded.
It is not a calibrated threshold and says nothing about any real release."""

_PLACEHOLDER_HASH = "0" * 64
_PLAIN_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_SATURDAY = 5

type PublicDailyRateState = Literal["value", "missing", "not_published"]
type PublicSeriesRightsBasis = Literal["us_federal_government_work_public_domain"]


class _RevalidatedModel(FrozenModel):
    """Frozen model whose instances are validated again wherever they are used.

    Pydantic accepts an existing model instance as a field value without
    looking inside it. With this setting an instance assembled without
    validation is checked again when it is nested in another model or passed
    to ``model_validate``, so it cannot ride in unchecked.
    """

    model_config = ConfigDict(revalidate_instances="always")


class PublicSeriesRightsRecordV1(_RevalidatedModel):
    """A recorded assertion about the rights basis of one public series.

    This is what the named recorder asserted and when, with the hash of the
    terms evidence they looked at. It is NOT a ``RightsAssessmentV1``: no
    profile, topology, entitlement or purpose was adjudicated, nobody
    independent reviewed it, and it is not legal advice. ``rights_basis``
    names the single basis this type can record, a work of the United States
    federal government in the public domain; the recorder, not this type, is
    answerable for whether that is true of the series named, including any
    third-party content a release may carry.

    The record is fixed to the exploratory lane and ``promotion_eligible`` can
    only be ``False``. Promotion-grade use needs the real M1e rights path.
    """

    schema_version: Literal["1"] = "1"
    publisher_legal_name: NonBlankStr
    product: NonBlankStr
    series_identifier: NonBlankStr
    rights_basis: PublicSeriesRightsBasis
    lane: Literal["exploratory"] = "exploratory"
    promotion_eligible: Literal[False] = False
    terms_evidence_sha256: SHA256Hash
    recorded_by: NonBlankStr
    recorded_at: UTCDateTime
    limitations: tuple[NonBlankStr, ...]
    record_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.promotion_eligible is not False:
            raise ValueError(
                "public_series_rights_promotion_refused: promotion_eligible "
                "can only be False"
            )
        _require_canonical_limitations(
            self.limitations,
            required=(PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,),
            code="public_series_rights_limitations",
        )
        expected = public_series_rights_record_hash(self)
        if self.record_hash != expected:
            raise ValueError(
                f"public_series_rights_hash_mismatch: expected {expected}, "
                f"got {self.record_hash}"
            )
        return self


class PublicationLagPolicyV1(_RevalidatedModel):
    """A modeled rule for when a daily observation is treated as public.

    An observation becomes available ``release_lag_weekdays`` release days
    after its date, at ``release_utc_minute_of_day`` minutes past midnight
    UTC. A release day is a Monday to Friday, on the UTC calendar, that is not
    listed in ``non_release_dates``.

    ``basis`` can only be ``"modeled_rule"``: this is a rule the caller chose,
    not a record of when anything was released. The rule stores one fixed UTC
    minute and no time zone, so a publisher that releases at a fixed local
    time is modeled correctly only if the caller picks a minute no earlier
    than the latest UTC time that local time ever maps to. Choosing the rule
    is an owner decision; nothing here supplies a default.
    """

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    release_lag_weekdays: Annotated[int, Field(ge=1, le=MAX_RELEASE_LAG_WEEKDAYS)]
    release_utc_minute_of_day: Annotated[int, Field(ge=0, le=1439)]
    non_release_dates: tuple[date, ...]
    basis: Literal["modeled_rule"] = "modeled_rule"
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.non_release_dates != tuple(sorted(set(self.non_release_dates))):
            raise ValueError(
                "publication_lag_policy_non_release_dates_not_canonical: "
                "non_release_dates must be unique and ascending"
            )
        expected = publication_lag_policy_hash(self)
        if self.policy_hash != expected:
            raise ValueError(
                f"publication_lag_policy_hash_mismatch: expected {expected}, "
                f"got {self.policy_hash}"
            )
        return self


class PublicDailyRatePointV1(_RevalidatedModel):
    """One observation date of a public daily rate series.

    ``state`` separates three things a source can say about a date:
    ``"value"`` (a rate was printed), ``"missing"`` (a marker was printed
    instead, for example ``ND`` on a holiday) and ``"not_published"`` (the
    cell was empty). ``native_text`` is the exact cell text, and for a value
    ``value_percent`` is that same text as an exact ``Decimal``, never a
    binary float and never a re-spelling. ``available_at`` is modeled.
    """

    observed_on: date
    state: PublicDailyRateState
    native_text: str
    value_percent: Decimal | None
    available_at: UTCDateTime

    @model_validator(mode="after")
    def validate_point(self) -> Self:
        if not self._state_fits():
            raise ValueError(
                "public_series_point_state_mismatch: state "
                f"{self.state} does not fit the native text and value on "
                f"{self.observed_on.isoformat()}"
            )
        return self

    def _state_fits(self) -> bool:
        text, value = self.native_text, self.value_percent
        if self.state == "value":
            return (
                value is not None
                and value.is_finite()
                and _PLAIN_DECIMAL.fullmatch(text) is not None
                and Decimal(text).as_tuple() == value.as_tuple()
            )
        if self.state == "missing":
            return (
                value is None
                and text.strip() != ""
                and _PLAIN_DECIMAL.fullmatch(text) is None
            )
        return value is None and text == ""


class PublicDailyRateSeriesV1(_RevalidatedModel):
    """One public daily rate series, exploratory only, with modeled availability.

    The points are unique and ascending by date, and each ``available_at``
    must equal what ``lag_policy`` computes for its date, so availability
    cannot be edited independently of the rule. ``source_sha256`` and
    ``source_byte_size`` name the exact bytes the points were read from;
    ``rights_record_hash`` names the ``PublicSeriesRightsRecordV1`` the
    builder was given. Neither hash authenticates an origin, and the record
    it names is an assertion rather than a rights assessment.

    ``acknowledged_limitations`` must contain every entry of
    ``PUBLIC_SERIES_REQUIRED_LIMITATIONS``. The lane can only be exploratory.

    Nested points and the nested policy are revalidated whenever a series is
    validated, so one assembled without validation cannot ride in unchecked.
    """

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    series_identifier: NonBlankStr
    description: NonBlankStr
    unit: NonBlankStr
    source_sha256: SHA256Hash
    source_byte_size: Annotated[int, Field(ge=1)]
    points: tuple[PublicDailyRatePointV1, ...]
    lag_policy: PublicationLagPolicyV1
    rights_record_hash: SHA256Hash
    lane: Literal["exploratory"] = "exploratory"
    acknowledged_limitations: tuple[NonBlankStr, ...]
    series_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        if not self.points:
            raise ValueError(
                "public_series_points_empty: a series needs at least one point"
            )
        dates = tuple(point.observed_on for point in self.points)
        if any(later <= earlier for earlier, later in pairwise(dates)):
            raise ValueError(
                "public_series_dates_not_ascending: observation dates must be "
                "unique and ascending"
            )
        blocked = frozenset(self.lag_policy.non_release_dates)
        for point in self.points:
            modeled = _release_instant(point.observed_on, self.lag_policy, blocked)
            if point.available_at != modeled:
                raise ValueError(
                    "public_series_available_at_mismatch: available_at on "
                    f"{point.observed_on.isoformat()} is not what the lag "
                    "policy computes"
                )
        _require_canonical_limitations(
            self.acknowledged_limitations,
            required=PUBLIC_SERIES_REQUIRED_LIMITATIONS,
            code="public_series_limitations",
        )
        expected = public_daily_rate_series_hash(self)
        if self.series_hash != expected:
            raise ValueError(
                f"public_series_hash_mismatch: expected {expected}, "
                f"got {self.series_hash}"
            )
        return self

    def value_as_of(self, cutoff: datetime) -> PublicDailyRatePointV1 | None:
        """Return the latest point whose modeled availability is not after ``cutoff``.

        The point is returned exactly as recorded. When the latest available
        date is ``"missing"`` or ``"not_published"`` that point is the answer,
        with no value: an earlier value is never carried forward. ``None``
        means no point was available yet.

        "Available" here means available under the modeled lag rule, which is
        not an observed release time.
        """
        if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
            raise ValueError(
                "public_series_cutoff_naive: the cutoff must be a "
                "timezone-aware datetime"
            )
        # Availability never decreases with the date, so the first available
        # point from the end is the latest one.
        for point in reversed(self.points):
            if point.available_at <= cutoff:
                return point
        return None


def modeled_available_at(observed_on: date, policy: PublicationLagPolicyV1) -> datetime:
    """Return the modeled UTC instant an observation is treated as public.

    Starting the day after ``observed_on``, count ``release_lag_weekdays``
    release days (Monday to Friday, not in ``non_release_dates``) and return
    the last of them at the policy's release minute. The lag is at least one
    release day, so the result is never inside the observation day.

    This is a model. It is not when the publisher released anything.
    """
    return _release_instant(observed_on, policy, frozenset(policy.non_release_dates))


def public_series_rights_record_hash(record: PublicSeriesRightsRecordV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one rights record."""
    dump = record.model_dump(mode="python", warnings=False)
    dump.pop("record_hash", None)
    return content_hash(dump)


def publication_lag_policy_hash(policy: PublicationLagPolicyV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one lag policy."""
    dump = policy.model_dump(mode="python", warnings=False)
    dump.pop("policy_hash", None)
    return content_hash(dump)


def public_daily_rate_series_hash(series: PublicDailyRateSeriesV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one series."""
    dump = series.model_dump(mode="python", warnings=False)
    dump.pop("series_hash", None)
    return content_hash(dump)


def seal_public_series_rights_record(
    *,
    publisher_legal_name: str,
    product: str,
    series_identifier: str,
    rights_basis: PublicSeriesRightsBasis,
    terms_evidence_sha256: str,
    recorded_by: str,
    recorded_at: datetime,
    limitations: tuple[str, ...],
) -> PublicSeriesRightsRecordV1:
    """Seal a rights record's own hash and validate the result.

    The lane and ``promotion_eligible`` are not parameters: a record is always
    exploratory and never promotion eligible. A seal never repairs a record,
    so ``limitations`` must already be unique and sorted.
    """
    draft = PublicSeriesRightsRecordV1.model_construct(
        schema_version="1",
        publisher_legal_name=publisher_legal_name,
        product=product,
        series_identifier=series_identifier,
        rights_basis=rights_basis,
        lane="exploratory",
        promotion_eligible=False,
        terms_evidence_sha256=terms_evidence_sha256,
        recorded_by=recorded_by,
        recorded_at=recorded_at,
        limitations=limitations,
        record_hash=_PLACEHOLDER_HASH,
    )
    return PublicSeriesRightsRecordV1.model_validate(
        draft.model_dump(mode="python", warnings=False)
        | {"record_hash": public_series_rights_record_hash(draft)}
    )


def seal_publication_lag_policy(
    *,
    policy_id: str,
    release_lag_weekdays: int,
    release_utc_minute_of_day: int,
    non_release_dates: tuple[date, ...],
) -> PublicationLagPolicyV1:
    """Seal a lag policy's own hash and validate the result.

    The basis is not a parameter: a policy is always a modeled rule.
    """
    draft = PublicationLagPolicyV1.model_construct(
        schema_version="1",
        policy_id=policy_id,
        release_lag_weekdays=release_lag_weekdays,
        release_utc_minute_of_day=release_utc_minute_of_day,
        non_release_dates=non_release_dates,
        basis="modeled_rule",
        policy_hash=_PLACEHOLDER_HASH,
    )
    return PublicationLagPolicyV1.model_validate(
        draft.model_dump(mode="python", warnings=False)
        | {"policy_hash": publication_lag_policy_hash(draft)}
    )


def seal_public_daily_rate_series(
    *,
    source_id: str,
    series_identifier: str,
    description: str,
    unit: str,
    source_sha256: str,
    source_byte_size: int,
    points: tuple[PublicDailyRatePointV1, ...],
    lag_policy: PublicationLagPolicyV1,
    rights_record_hash: str,
    acknowledged_limitations: tuple[str, ...],
) -> PublicDailyRateSeriesV1:
    """Seal a series' own hash and validate the result.

    The lane is not a parameter: a series is always exploratory. Nothing is
    reordered or recomputed, so points with a wrong ``available_at`` or
    limitations that are not canonical are refused.
    """
    draft = PublicDailyRateSeriesV1.model_construct(
        schema_version="1",
        source_id=source_id,
        series_identifier=series_identifier,
        description=description,
        unit=unit,
        source_sha256=source_sha256,
        source_byte_size=source_byte_size,
        points=points,
        lag_policy=lag_policy,
        rights_record_hash=rights_record_hash,
        lane="exploratory",
        acknowledged_limitations=acknowledged_limitations,
        series_hash=_PLACEHOLDER_HASH,
    )
    return PublicDailyRateSeriesV1.model_validate(
        draft.model_dump(mode="python", warnings=False)
        | {"series_hash": public_daily_rate_series_hash(draft)}
    )


def _release_instant(
    observed_on: date, policy: PublicationLagPolicyV1, blocked: frozenset[date]
) -> datetime:
    if type(observed_on) is not date:
        raise ValueError(
            "public_series_observed_on_invalid: the observation date must be "
            "a plain calendar date"
        )
    day = observed_on
    remaining = policy.release_lag_weekdays
    try:
        while remaining > 0:
            day += timedelta(days=1)
            if day.weekday() < _SATURDAY and day not in blocked:
                remaining -= 1
    except OverflowError as error:
        raise ValueError(
            "public_series_release_date_overflow: no release day exists after "
            f"{observed_on.isoformat()}"
        ) from error
    minute = policy.release_utc_minute_of_day
    return datetime.combine(day, time(minute // 60, minute % 60), tzinfo=UTC)


def _require_canonical_limitations(
    limitations: tuple[str, ...], *, required: tuple[str, ...], code: str
) -> None:
    if not limitations:
        raise ValueError(f"{code}_empty: at least one limitation is required")
    if limitations != tuple(sorted(set(limitations))):
        raise ValueError(f"{code}_not_canonical: limitations must be unique and sorted")
    missing = [item for item in required if item not in limitations]
    if missing:
        raise ValueError(f"{code}_incomplete: missing required limitation {missing[0]}")
