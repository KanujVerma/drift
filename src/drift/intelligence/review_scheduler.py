"""Review and adaptation scheduler runtime.

Implements Slice K5 review and adaptation scheduling logic under D04, D05, DP-R2:
- Distinct monitoring, review, adaptation, and execution clocks (D04).
- Routine weekly review, monthly planned adaptation, and event-driven review triggers.
- Feed condition handling: healthy empty, broken feed, unknown coverage,
  and material event (T03).
- Calendar revision currentness and conflicting source version refusal (T02).
- Event cooldown and decision TTL boundaries.
- Defensive-only versus full event response policy evaluation (D05).
- Malicious/untrusted event text isolation (T03).
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator, model_validator

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    TargetWeight,
    compute_record_hash,
)
from drift.serialization.canonical import content_hash

FeedCondition = Literal[
    "healthy_empty", "material_event", "broken_feed", "unknown_coverage"
]
EventActionPolicy = Literal["full_response", "defensive_only"]
ReviewType = Literal["routine", "planned_adaptation", "event_driven"]
VerdictAction = Literal["review", "no_review", "unavailable"]


class FeedEvent(ImmutableModel):
    """Timestamped informational or market feed event."""

    event_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    available_at: datetime
    content_hash: str = Field(min_length=64, max_length=64)
    raw_text: str
    condition: FeedCondition = "material_event"
    is_material: bool = Field(default=True, strict=True)

    @field_validator("content_hash")
    @classmethod
    def require_digest(cls, value: str) -> str:
        if any(c not in "0123456789abcdef" for c in value):
            raise ValueError("INVALID_FEED_EVENT_HASH")
        return value


class CalendarRevision(ImmutableModel):
    """Calendar revision record with effective cutoff and content digest."""

    calendar_id: str = Field(min_length=1)
    revision: int = Field(ge=1, strict=True)
    effective_cutoff: datetime
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("content_hash")
    @classmethod
    def require_digest(cls, value: str) -> str:
        if any(c not in "0123456789abcdef" for c in value):
            raise ValueError("INVALID_CALENDAR_HASH")
        return value


class SchedulerPolicy(ImmutableModel):
    """Configuration policy governing review intervals, cooldowns, and TTLs."""

    routine_interval: timedelta = timedelta(days=7)
    adaptation_interval: timedelta = timedelta(days=30)
    event_cooldown: timedelta = timedelta(seconds=3600)
    decision_ttl: timedelta = timedelta(seconds=86400)
    default_event_policy: EventActionPolicy = "full_response"

    @model_validator(mode="after")
    def check_positive_intervals(self) -> SchedulerPolicy:
        for name, span in (
            ("routine", self.routine_interval),
            ("adaptation", self.adaptation_interval),
            ("event_cooldown", self.event_cooldown),
            ("decision_ttl", self.decision_ttl),
        ):
            if span <= timedelta(0):
                raise ValueError(f"INVALID_SCHEDULER_INTERVAL: {name}")
        return self


class ReviewTriggerVerdict(ImmutableModel):
    """Immutable verdict emitted by the review scheduler."""

    trigger_id: str
    action: VerdictAction
    review_type: ReviewType | None = None
    reason: str
    evaluated_at: datetime
    decision_cutoff: datetime
    action_policy: EventActionPolicy = "full_response"
    event_ref: ArtifactReference | None = None
    record_hash: str

    @model_validator(mode="after")
    def verify_verdict_hash(self) -> ReviewTriggerVerdict:
        if self.record_hash != compute_record_hash(self):
            raise ValueError("REVIEW_TRIGGER_HASH_MISMATCH")
        if self.action == "review" and self.review_type is None:
            raise ValueError("REVIEW_TRIGGER_MISSING_REVIEW_TYPE")
        if self.action != "review" and self.review_type is not None:
            raise ValueError("NON_ACTIONABLE_TRIGGER_HAS_REVIEW_TYPE")
        if (self.action != "review" and self.event_ref is not None) or (
            self.review_type == "event_driven" and self.event_ref is None
        ):
            raise ValueError("INVALID_TRIGGER_EVENT_REFERENCE")
        if (
            self.evaluated_at.tzinfo is None
            or self.evaluated_at.utcoffset() is None
            or self.decision_cutoff.tzinfo is None
            or self.decision_cutoff.utcoffset() is None
        ):
            raise ValueError("INDETERMINATE_TIMEZONE: review verdict")
        if self.decision_cutoff > self.evaluated_at:
            raise ValueError("NON_CAUSAL_REVIEW_CUTOFF")
        return self


def evaluate_review_schedule(
    *,
    now: datetime,
    last_routine_at: datetime | None = None,
    last_adaptation_at: datetime | None = None,
    last_event_review_at: datetime | None = None,
    feed_events: Sequence[FeedEvent] = (),
    feed_condition: FeedCondition = "healthy_empty",
    calendar_history: Sequence[CalendarRevision] = (),
    current_calendar: CalendarRevision | None = None,
    policy: SchedulerPolicy | None = None,
    trigger_id: str | None = None,
) -> ReviewTriggerVerdict:
    """Evaluate scheduling clocks and feed conditions to produce a ReviewTriggerVerdict.

    Enforces:
    - Calendar revision currentness: conflicting byte hashes for identical revisions
      raise SOURCE_DIGEST_CONFLICT (T02).
    - Feed condition handling: distinct reasons for broken feed, unknown coverage,
      healthy empty feed, and material news (T03).
    - Untrusted raw text: article content stays inert prose and cannot alter
      destinations, scopes, or policies (T03).
    - Event cooldown throttling (DP-R2).
    - Distinct routine (weekly) and adaptation (monthly) clock cadences (D04).
    """
    active_policy = SchedulerPolicy.model_validate(
        (policy or SchedulerPolicy()).model_dump(mode="python")
    )
    if feed_condition not in (
        "healthy_empty",
        "material_event",
        "broken_feed",
        "unknown_coverage",
    ):
        raise ValueError("UNKNOWN_FEED_CONDITION")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: scheduler now lacks an offset")
    now_utc = now.astimezone(UTC)
    for label, instant in (
        ("routine", last_routine_at),
        ("adaptation", last_adaptation_at),
        ("event", last_event_review_at),
    ):
        if instant is not None:
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError(f"INDETERMINATE_TIMEZONE: last {label} review")
            if instant > now_utc:
                raise ValueError(
                    f"FUTURE_REVIEW_CLOCK: last {label} review is after now"
                )
    # Verify the actual typed input values before trusting frozen-model fields.
    # model_copy(update=...) bypasses Pydantic validation.
    validated_events = tuple(
        FeedEvent.model_validate(event.model_dump(mode="python"))
        for event in feed_events
    )
    validated_calendar = (
        CalendarRevision.model_validate(current_calendar.model_dump(mode="python"))
        if current_calendar is not None
        else None
    )
    validated_history = tuple(
        CalendarRevision.model_validate(cal.model_dump(mode="python"))
        for cal in calendar_history
    )
    if validated_history and validated_calendar is None:
        raise ValueError("UNAVAILABLE_CALENDAR_CURRENTNESS")
    current_calendar = validated_calendar
    calendar_history = validated_history
    feed_events = validated_events
    # A scheduled review identity must not change when future events arrive,
    # or when the same completed event set is supplied in a different order.
    causal_event_identity: set[tuple[str, str, str, str, datetime, str, bool]] = set()
    for event in feed_events:
        if event.available_at.tzinfo is None or event.available_at.utcoffset() is None:
            raise ValueError("INDETERMINATE_TIMEZONE: feed availability lacks offset")
        availability = event.available_at.astimezone(UTC)
        if availability <= now_utc:
            causal_event_identity.add(
                (
                    event.source_id,
                    event.event_id,
                    event.version,
                    event.content_hash,
                    availability,
                    event.condition,
                    event.is_material,
                )
            )
    identity = content_hash(
        {
            "now": now_utc,
            "routine": last_routine_at.astimezone(UTC) if last_routine_at else None,
            "adaptation": (
                last_adaptation_at.astimezone(UTC) if last_adaptation_at else None
            ),
            "event": last_event_review_at.astimezone(UTC)
            if last_event_review_at
            else None,
            "events": sorted(causal_event_identity),
            "feed_condition": feed_condition,
            "policy": (
                str(active_policy.routine_interval),
                str(active_policy.adaptation_interval),
                str(active_policy.event_cooldown),
                str(active_policy.decision_ttl),
                active_policy.default_event_policy,
            ),
            "calendar": (
                current_calendar.calendar_id,
                current_calendar.revision,
                current_calendar.effective_cutoff,
                current_calendar.content_hash,
            )
            if current_calendar
            else None,
        }
    )
    actual_trigger_id = trigger_id or str(uuid5(NAMESPACE_URL, identity))
    raw_dict: dict[str, Any]

    # 1. Calendar revision currentness check (T02)
    known_calendar_revisions: dict[tuple[str, int], str] = {}
    known_calendar_clocks: dict[tuple[str, int], datetime] = {}
    for past_cal in calendar_history:
        if (
            past_cal.effective_cutoff.tzinfo is None
            or past_cal.effective_cutoff.utcoffset() is None
        ):
            raise ValueError("INDETERMINATE_TIMEZONE: historical calendar lacks offset")
        if past_cal.effective_cutoff.astimezone(UTC) > now_utc:
            continue
        rev_key = (past_cal.calendar_id, past_cal.revision)
        existing_hash = known_calendar_revisions.get(rev_key)
        if existing_hash is not None and existing_hash != past_cal.content_hash:
            raise ValueError("SOURCE_DIGEST_CONFLICT: historical calendar revision")
        previous_cutoff = known_calendar_clocks.get(rev_key)
        effective_cutoff = past_cal.effective_cutoff.astimezone(UTC)
        if previous_cutoff is not None and previous_cutoff != effective_cutoff:
            raise ValueError("CALENDAR_AVAILABILITY_CONFLICT")
        known_calendar_revisions[rev_key] = past_cal.content_hash
        known_calendar_clocks[rev_key] = effective_cutoff
    if current_calendar is not None:
        if (
            current_calendar.effective_cutoff.tzinfo is None
            or current_calendar.effective_cutoff.utcoffset() is None
            or current_calendar.effective_cutoff > now_utc
        ):
            raise ValueError("UNAVAILABLE_CALENDAR_CURRENTNESS")
        for past_cal in calendar_history:
            if (
                past_cal.effective_cutoff.tzinfo is None
                or past_cal.effective_cutoff.utcoffset() is None
            ):
                raise ValueError(
                    "INDETERMINATE_TIMEZONE: historical calendar lacks offset"
                )
        for past_cal in calendar_history:
            if (
                past_cal.effective_cutoff <= now_utc
                and past_cal.calendar_id == current_calendar.calendar_id
                and past_cal.revision > current_calendar.revision
            ):
                raise ValueError("STALE_CALENDAR_REVISION")
        for past_cal in calendar_history:
            if (
                past_cal.effective_cutoff <= now_utc
                and past_cal.calendar_id == current_calendar.calendar_id
                and past_cal.revision == current_calendar.revision
                and past_cal.effective_cutoff.astimezone(UTC)
                != current_calendar.effective_cutoff.astimezone(UTC)
            ):
                raise ValueError("CALENDAR_AVAILABILITY_CONFLICT")
        for past_cal in calendar_history:
            if (
                past_cal.effective_cutoff <= now_utc
                and past_cal.calendar_id == current_calendar.calendar_id
                and past_cal.revision == current_calendar.revision
                and past_cal.content_hash != current_calendar.content_hash
            ):
                raise ValueError(
                    f"SOURCE_DIGEST_CONFLICT: conflicting bytes for calendar revision "
                    f"{current_calendar.calendar_id} rev {current_calendar.revision}"
                )

    # 3. Event-driven trigger evaluation (D03, D04, T03)
    event_versions: dict[tuple[str, str, str], str] = {}
    event_availability: dict[tuple[str, str, str], datetime] = {}
    event_signals: dict[tuple[str, str, str], tuple[str, bool]] = {}
    causal_material_events: list[FeedEvent] = []
    for ev in feed_events:
        if ev.available_at.tzinfo is None or ev.available_at.utcoffset() is None:
            raise ValueError("INDETERMINATE_TIMEZONE: feed availability lacks offset")
        # Evidence received after the current cutoff cannot alter this
        # review's admissibility or event-revision conflict result.
        ev_available_utc = ev.available_at.astimezone(UTC)
        if ev_available_utc > now_utc:
            continue
        # Provider-local event identifiers must not collide across sources.
        # Repeated claims for one exact source event must agree about BOTH
        # bytes and first availability, independent of their input order.
        key = (ev.source_id, ev.event_id, ev.version)
        previous = event_versions.get(key)
        if previous is not None and previous != ev.content_hash:
            raise ValueError(
                "SOURCE_DIGEST_CONFLICT: feed event revision changed bytes"
            )
        previous_available = event_availability.get(key)
        if previous_available is not None and previous_available != ev_available_utc:
            raise ValueError(
                "EVENT_AVAILABILITY_CONFLICT: source event has conflicting "
                "time-availability claims"
            )
        existing_signal = event_signals.get(key)
        current_signal = (ev.condition, ev.is_material)
        if existing_signal is not None and existing_signal != current_signal:
            raise ValueError(
                "EVENT_CONDITION_CONFLICT: source event status has changed"
            )
        event_versions[key] = ev.content_hash
        event_availability[key] = ev_available_utc
        event_signals[key] = current_signal
        if (
            ev.is_material
            and ev.condition == "material_event"
            and ev_available_utc <= now_utc
        ):
            causal_material_events.append(ev)

    # 2. Feed condition evaluation (T03)

    causal_feed_problems = {
        event.condition
        for event in feed_events
        if event.available_at.astimezone(UTC) <= now_utc
        and event.condition in ("broken_feed", "unknown_coverage")
    }
    if feed_condition == "broken_feed" or "broken_feed" in causal_feed_problems:
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "unavailable",
            "review_type": None,
            "reason": "broken_feed: feed offline or corrupt",
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": active_policy.default_event_policy,
            "event_ref": None,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    if (
        feed_condition == "unknown_coverage"
        or "unknown_coverage" in causal_feed_problems
    ):
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "unavailable",
            "review_type": None,
            "reason": "unknown_coverage: insufficient feed coverage",
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": active_policy.default_event_policy,
            "event_ref": None,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    if feed_condition == "material_event" and not causal_material_events:
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "unavailable",
            "review_type": None,
            "reason": "material_event_without_causal_evidence",
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": active_policy.default_event_policy,
            "event_ref": None,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    cooldown_active = bool(
        causal_material_events
        and last_event_review_at is not None
        and now_utc - last_event_review_at.astimezone(UTC)
        < active_policy.event_cooldown
    )
    if causal_material_events and not cooldown_active:
        # Trigger event review; raw_text is strictly untrusted and stays inert (T03)
        latest_event = max(
            causal_material_events,
            key=lambda ev: (
                ev.available_at.astimezone(UTC),
                ev.source_id,
                ev.event_id,
                ev.content_hash,
            ),
        )
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "review",
            "review_type": "event_driven",
            "reason": (
                f"event_triggered: {latest_event.source_id}:{latest_event.version}"
            ),
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": active_policy.default_event_policy,
            "event_ref": ArtifactReference(
                id="event:"
                + content_hash(
                    {
                        "source_id": latest_event.source_id,
                        "event_id": latest_event.event_id,
                    }
                ),
                version=latest_event.version,
                sha256=latest_event.content_hash,
            ).model_dump(mode="python"),
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    # 4. Planned adaptation check (D04: monthly adaptation)
    adaptation_due = False
    if last_adaptation_at is None:
        adaptation_due = True
    else:
        last_adapt_utc = last_adaptation_at.astimezone(UTC)
        if (now_utc - last_adapt_utc) >= active_policy.adaptation_interval:
            adaptation_due = True

    if adaptation_due:
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "review",
            "review_type": "planned_adaptation",
            "reason": "planned_adaptation_due: monthly strategy and parameter update",
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": "full_response",
            "event_ref": None,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    # 5. Routine review check (D04: weekly portfolio review)
    routine_due = False
    if last_routine_at is None:
        routine_due = True
    else:
        last_rout_utc = last_routine_at.astimezone(UTC)
        if (now_utc - last_rout_utc) >= active_policy.routine_interval:
            routine_due = True

    if routine_due:
        raw_dict = {
            "trigger_id": actual_trigger_id,
            "action": "review",
            "review_type": "routine",
            "reason": "routine_review_due: weekly portfolio review",
            "evaluated_at": now_utc,
            "decision_cutoff": now_utc,
            "action_policy": "full_response",
            "event_ref": None,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return ReviewTriggerVerdict.model_validate(raw_dict)

    # 6. Default healthy empty feed: no triggers due
    raw_dict = {
        "trigger_id": actual_trigger_id,
        "action": "no_review",
        "review_type": None,
        "reason": (
            "cooldown_active: event review suppressed by cooldown"
            if cooldown_active
            else "healthy_empty: no review triggers due"
        ),
        "evaluated_at": now_utc,
        "decision_cutoff": now_utc,
        "action_policy": active_policy.default_event_policy,
        "event_ref": None,
    }
    raw_dict["record_hash"] = compute_record_hash(raw_dict)
    return ReviewTriggerVerdict.model_validate(raw_dict)


def validate_defensive_policy(
    *,
    proposed_targets: Sequence[TargetWeight],
    current_weights: dict[str, str],
) -> tuple[bool, str | None]:
    """Check candidate reductions only against explicit current weight evidence.

    This offline policy check does not authenticate the weights or authorize
    a real order. Omitted/empty targets are not an inferred sell-all request.
    """
    if not proposed_targets:
        return False, "DEFENSIVE_POLICY_VIOLATION: empty targets not authorized"
    if not current_weights:
        return False, "UNKNOWN_CURRENT_POSITION: current weights unavailable"
    current: dict[str, Decimal] = {}
    for security, text in current_weights.items():
        if not security or not isinstance(text, str) or text.strip() != text:
            return False, "UNKNOWN_CURRENT_POSITION: malformed current security"
        try:
            weight = Decimal(text)
        except InvalidOperation, TypeError:
            return False, "UNKNOWN_CURRENT_POSITION: invalid current weight"
        if not weight.is_finite() or weight < Decimal("0") or weight > Decimal("1"):
            return False, "UNKNOWN_CURRENT_POSITION: invalid current weight"
        current[security] = weight
    if sum(current.values(), Decimal("0")) > Decimal("1"):
        return False, "UNKNOWN_CURRENT_POSITION: inconsistent current totals"

    seen: set[str] = set()
    proposed_sum = Decimal("0")
    for supplied in proposed_targets:
        try:
            target = TargetWeight.model_validate(supplied.model_dump(mode="python"))
        except TypeError, ValueError:
            return False, "DEFENSIVE_POLICY_VIOLATION: invalid target"
        security = target.security_id
        if security in seen:
            return False, "DEFENSIVE_POLICY_VIOLATION: duplicate security target"
        seen.add(security)
        if security not in current:
            return False, "UNKNOWN_CURRENT_POSITION: no verified current weight"
        try:
            weight = Decimal(target.weight)
        except InvalidOperation:
            return False, "DEFENSIVE_POLICY_VIOLATION: invalid target"
        if not weight.is_finite() or not Decimal("0") <= weight <= Decimal("1"):
            return False, "DEFENSIVE_POLICY_VIOLATION: invalid target"
        proposed_sum += weight
        if weight > current[security]:
            return (
                False,
                f"DEFENSIVE_POLICY_VIOLATION: target weight {weight} for "
                f"{security} exceeds current weight {current[security]}",
            )
    if proposed_sum > Decimal("1"):
        return False, "DEFENSIVE_POLICY_VIOLATION: overallocated targets"
    return True, None
