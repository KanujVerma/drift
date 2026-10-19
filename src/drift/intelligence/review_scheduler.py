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
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import model_validator

from drift.serialization.canonical import content_hash

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    TargetWeight,
    compute_record_hash,
)

FeedCondition = Literal[
    "healthy_empty", "material_event", "broken_feed", "unknown_coverage"
]
EventActionPolicy = Literal["full_response", "defensive_only"]
ReviewType = Literal["routine", "planned_adaptation", "event_driven"]
VerdictAction = Literal["review", "no_review", "unavailable"]


class FeedEvent(ImmutableModel):
    """Timestamped informational or market feed event."""

    event_id: str
    source_id: str
    version: str
    available_at: datetime
    content_hash: str
    raw_text: str
    condition: FeedCondition = "material_event"
    is_material: bool = True


class CalendarRevision(ImmutableModel):
    """Calendar revision record with effective cutoff and content digest."""

    calendar_id: str
    revision: int
    effective_cutoff: datetime
    content_hash: str


class SchedulerPolicy(ImmutableModel):
    """Configuration policy governing review intervals, cooldowns, and TTLs."""

    routine_interval: timedelta = timedelta(days=7)
    adaptation_interval: timedelta = timedelta(days=30)
    event_cooldown: timedelta = timedelta(seconds=3600)
    decision_ttl: timedelta = timedelta(seconds=86400)
    default_event_policy: EventActionPolicy = "full_response"

    @model_validator(mode="after")
    def check_positive_intervals(self) -> "SchedulerPolicy":
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
    def verify_verdict_hash(self) -> "ReviewTriggerVerdict":
        if self.record_hash != compute_record_hash(self):
            raise ValueError("REVIEW_TRIGGER_HASH_MISMATCH")
        if self.action == "review" and self.review_type is None:
            raise ValueError("REVIEW_TRIGGER_MISSING_REVIEW_TYPE")
        if self.action != "review" and self.review_type is not None:
            raise ValueError("NON_ACTIONABLE_TRIGGER_HAS_REVIEW_TYPE")
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
    active_policy = policy or SchedulerPolicy()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: scheduler now lacks an offset")
    now_utc = now.astimezone(UTC)
    for label, instant in (
        ("routine", last_routine_at), ("adaptation", last_adaptation_at),
        ("event", last_event_review_at),
    ):
        if instant is not None:
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError(f"INDETERMINATE_TIMEZONE: last {label} review")
            if instant > now_utc:
                raise ValueError(
                    f"FUTURE_REVIEW_CLOCK: last {label} review is after now"
                )
    identity = content_hash({
        "now": now_utc,
        "routine": last_routine_at,
        "adaptation": last_adaptation_at,
        "event": last_event_review_at,
        "events": [(ev.event_id, ev.version, ev.content_hash) for ev in feed_events],
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
            current_calendar.content_hash,
        ) if current_calendar else None,
    })
    actual_trigger_id = trigger_id or str(uuid5(NAMESPACE_URL, identity))
    raw_dict: dict[str, Any]

    # 1. Calendar revision currentness check (T02)
    if current_calendar is not None:
        if (
            current_calendar.effective_cutoff.tzinfo is None
            or current_calendar.effective_cutoff.utcoffset() is None
            or current_calendar.effective_cutoff > now_utc
        ):
            raise ValueError("UNAVAILABLE_CALENDAR_CURRENTNESS")
        for past_cal in calendar_history:
            if (
                past_cal.effective_cutoff <= now_utc
                and past_cal.calendar_id == current_calendar.calendar_id
                and past_cal.revision > current_calendar.revision
            ):
                raise ValueError("STALE_CALENDAR_REVISION")
        for past_cal in calendar_history:
            if (
                past_cal.calendar_id == current_calendar.calendar_id
                and past_cal.revision == current_calendar.revision
                and past_cal.content_hash != current_calendar.content_hash
            ):
                raise ValueError(
                    f"SOURCE_DIGEST_CONFLICT: conflicting bytes for calendar revision "
                    f"{current_calendar.calendar_id} rev {current_calendar.revision}"
                )

    # 2. Feed condition evaluation (T03)
    if feed_condition == "broken_feed":
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

    if feed_condition == "unknown_coverage":
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

    # 3. Event-driven trigger evaluation (D03, D04, T03)
    event_versions: dict[tuple[str, str], str] = {}
    causal_material_events: list[FeedEvent] = []
    for ev in feed_events:
        if ev.available_at.tzinfo is None or ev.available_at.utcoffset() is None:
            raise ValueError("INDETERMINATE_TIMEZONE: feed availability lacks offset")
        key = (ev.event_id, ev.version)
        previous = event_versions.get(key)
        if previous is not None and previous != ev.content_hash:
            raise ValueError(
                "SOURCE_DIGEST_CONFLICT: feed event revision changed bytes"
            )
        event_versions[key] = ev.content_hash
        if ev.is_material and ev.available_at.astimezone(UTC) <= now_utc:
            causal_material_events.append(ev)

    if causal_material_events:
        # Check cooldown
        if last_event_review_at is not None:
            last_event_utc = last_event_review_at.astimezone(UTC)
            if (now_utc - last_event_utc) < active_policy.event_cooldown:
                raw_dict = {
                    "trigger_id": actual_trigger_id,
                    "action": "no_review",
                    "review_type": None,
                    "reason": "cooldown_active: event review suppressed by cooldown",
                    "evaluated_at": now_utc,
                    "decision_cutoff": now_utc,
                    "action_policy": active_policy.default_event_policy,
                    "event_ref": None,
                }
                raw_dict["record_hash"] = compute_record_hash(raw_dict)
                return ReviewTriggerVerdict.model_validate(raw_dict)

        # Trigger event review; raw_text is strictly untrusted and stays inert (T03)
        latest_event = max(
            causal_material_events,
            key=lambda ev: (ev.available_at, ev.event_id, ev.content_hash),
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
                id=latest_event.event_id,
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
        "reason": "healthy_empty: no review triggers due",
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
    """Validate whether proposed target weights satisfy defensive-only policy (D05).

    Under defensive-only policy:
    - Decreasing positions or holding is permitted.
    - Increasing existing positions or opening new positions is forbidden.
    """
    seen: set[str] = set()
    for target in proposed_targets:
        sec_id = target.security_id
        if sec_id in seen:
            return False, "DEFENSIVE_POLICY_VIOLATION: duplicate security target"
        seen.add(sec_id)
        if sec_id not in current_weights:
            return False, "UNKNOWN_CURRENT_POSITION: no verified current weight"
        prop_weight = Decimal(target.weight)
        curr_weight = Decimal(current_weights[sec_id])
        if (
            not curr_weight.is_finite()
            or not Decimal("0") <= curr_weight <= Decimal("1")
        ):
            return False, "UNKNOWN_CURRENT_POSITION: invalid current weight"

        if prop_weight > curr_weight:
            return (
                False,
                f"DEFENSIVE_POLICY_VIOLATION: target weight {prop_weight} for "
                f"{sec_id} exceeds current weight {curr_weight}",
            )

    return True, None
