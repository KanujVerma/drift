from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from drift.serialization.canonical import content_hash

SCHEMA_VERSION = "drift-experiment/1-draft"

CAMPAIGN_TYPES = frozenset(
    {
        "HISTORICAL_BACKTEST",
        "SYNTHETIC_TEST",
        "FORWARD_SHADOW",
    }
)

SELECTOR_TYPES = frozenset(
    {
        "ADAPTIVE_AI",
        "DETERMINISTIC_COMPARATOR",
        "FROZEN_BASELINE",
        "PASSIVE_BENCHMARK",
        "CASH_CONTROL",
    }
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_POSITIVE_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
_CANONICAL_UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")


@dataclass(frozen=True, slots=True)
class PrimaryComparisonV1:
    test_arm_id: str
    comparator_arm_id: str


@dataclass(frozen=True, slots=True)
class DataWindowV1:
    start_date: str
    end_date: str
    calendar_id: str


@dataclass(frozen=True, slots=True)
class SessionWindowV1:
    sessions_count: int


@dataclass(frozen=True, slots=True)
class ScoringWindowV1:
    start_session: str
    end_session: str
    fresh_accounts: bool


@dataclass(frozen=True, slots=True)
class DecisionScheduleV1:
    frequency: str
    alignment: str
    execution_timing: str


@dataclass(frozen=True, slots=True)
class FrozenJSONMap:
    items: tuple[tuple[str, FrozenJSONValue], ...]


@dataclass(frozen=True, slots=True)
class FrozenJSONArray:
    items: tuple[FrozenJSONValue, ...]


type FrozenJSONValue = None | bool | int | str | FrozenJSONMap | FrozenJSONArray


@dataclass(frozen=True, slots=True)
class ArmSpecV1:
    schema_version: str
    arm_id: str
    campaign_id: str
    arm_spec_fingerprint: str
    selector_type: str
    eligible_strategy_references: tuple[str, ...]
    initial_strategy_reference: str
    initial_capital: str
    currency: str
    arm_account_role: str
    mandate_reference: str
    execution_policy_reference: str
    research_budget_reference: str
    information_visibility_policy: str
    feedback_policy_reference: str
    model_configuration_reference: str
    deterministic_seed_reference: str
    frozen_configuration_reference: str


@dataclass(frozen=True, slots=True)
class CampaignSpecV1:
    schema_version: str
    campaign_id: str
    campaign_spec_fingerprint: str
    campaign_type: str
    study_protocol_revision: str
    created_at: str
    frozen_at: str
    accepted_contract_revisions: tuple[tuple[str, str], ...]
    research_question_id: str
    primary_comparison: PrimaryComparisonV1
    control_arm_references: tuple[str, ...]
    arm_spec_references: tuple[str, ...]
    qualified_dataset_references: tuple[str, ...]
    data_window: DataWindowV1
    warmup_window: SessionWindowV1
    observation_window: SessionWindowV1
    scoring_window: ScoringWindowV1
    decision_schedule: DecisionScheduleV1
    allowed_strategy_families: tuple[str, ...]
    portfolio_mandate_reference: str
    source_eligibility_policy_reference: str
    execution_policy_reference: str
    cost_policy_reference: str
    model_and_prompt_policy_reference: str
    learning_and_feedback_policy_reference: str
    evaluation_policy_reference: str
    holdout_access_policy_reference: str
    stopping_policy_reference: str
    authorization_evidence: FrozenJSONMap


@dataclass(frozen=True, slots=True)
class RunAccountBindingV1:
    schema_version: str
    binding_id: str
    campaign_id: str
    run_id: str
    arm_id: str
    portfolio_account_id: str
    initial_cash_allocated: str
    bound_at: str


def _canonical_utc(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be a timezone-aware datetime")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_persisted_utc(value: str) -> None:
    if type(value) is not str:
        raise ValueError("timestamp must be a string")
    if not _CANONICAL_UTC_TS.fullmatch(value):
        raise ValueError(f"timestamp does not match canonical format: {value!r}")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"invalid calendar timestamp: {value!r}") from exc
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if canonical != value:
        raise ValueError(f"timestamp is not canonical: {value!r}")


def _validate_scope_id(value: str, field_name: str) -> None:
    if type(value) is not str or not _SCOPE_ID.fullmatch(value):
        raise ValueError(f"invalid {field_name}: {value!r}")


def _validate_nonempty_str(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError(
            f"{field_name} must be a nonblank string without surrounding whitespace"
        )


def _validate_positive_decimal_text(value: str, field_name: str) -> None:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    if not _POSITIVE_DECIMAL_TEXT.fullmatch(value):
        raise ValueError(
            f"{field_name} does not match canonical decimal format: {value!r}"
        )
    try:
        dec = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} is not a valid decimal: {value!r}") from exc
    if not dec.is_finite() or dec <= Decimal(0):
        raise ValueError(
            f"{field_name} must be finite and strictly greater than zero: {value!r}"
        )


def _freeze_json(value: object, seen: set[int] | None = None) -> FrozenJSONValue:
    if seen is None:
        seen = set()

    if value is None:
        return None
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is str:
        return value

    if isinstance(value, Mapping):
        obj_id = id(value)
        if obj_id in seen:
            raise ValueError("cyclic reference detected in JSON structure")
        nested_seen = seen | {obj_id}
        keys = list(value.keys())
        for k in keys:
            if type(k) is not str:
                raise ValueError("JSON mapping keys must be strings")
        items: list[tuple[str, FrozenJSONValue]] = []
        for k in sorted(keys):
            items.append((k, _freeze_json(value[k], nested_seen)))
        return FrozenJSONMap(tuple(items))

    if isinstance(value, (list, tuple)):
        obj_id = id(value)
        if obj_id in seen:
            raise ValueError("cyclic reference detected in JSON structure")
        nested_seen = seen | {obj_id}
        return FrozenJSONArray(tuple(_freeze_json(item, nested_seen) for item in value))

    raise ValueError(f"unsupported JSON value type: {type(value)}")


def _verify_frozen_json(
    value: object,
    ancestors: set[int] | None = None,
) -> None:
    if value is None:
        return
    if type(value) is bool:
        return
    if type(value) is int:
        return
    if type(value) is str:
        return

    if ancestors is None:
        ancestors = set()

    if type(value) is FrozenJSONMap:
        object_id = id(value)
        if object_id in ancestors:
            raise ValueError("cyclic reference detected in frozen JSON")
        next_ancestors = ancestors | {object_id}

        if type(value.items) is not tuple:
            raise ValueError("FrozenJSONMap items must be a tuple")
        seen_keys: set[str] = set()
        prev_key: str | None = None
        for pair in value.items:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("FrozenJSONMap items must be pairs of (key, value)")
            k, v = pair
            if type(k) is not str:
                raise ValueError("FrozenJSONMap key must be a string")
            if k in seen_keys:
                raise ValueError(f"duplicate key in FrozenJSONMap: {k!r}")
            if prev_key is not None and k <= prev_key:
                raise ValueError(
                    f"FrozenJSONMap keys are not strictly sorted: {prev_key!r} >= {k!r}"
                )
            seen_keys.add(k)
            prev_key = k
            _verify_frozen_json(v, next_ancestors)
        return

    if type(value) is FrozenJSONArray:
        object_id = id(value)
        if object_id in ancestors:
            raise ValueError("cyclic reference detected in frozen JSON")
        next_ancestors = ancestors | {object_id}

        if type(value.items) is not tuple:
            raise ValueError("FrozenJSONArray items must be a tuple")
        for item in value.items:
            _verify_frozen_json(item, next_ancestors)
        return

    raise ValueError(f"invalid persisted frozen JSON value: {type(value)}")


def _json_plain(value: FrozenJSONValue) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, FrozenJSONMap):
        return {k: _json_plain(v) for k, v in value.items}
    if isinstance(value, FrozenJSONArray):
        return [_json_plain(item) for item in value.items]
    raise ValueError(f"unsupported frozen JSON value: {type(value)}")


def _arm_preimage(arm: ArmSpecV1) -> dict[str, object]:
    return {
        "schema_version": arm.schema_version,
        "arm_id": arm.arm_id,
        "campaign_id": arm.campaign_id,
        "selector_type": arm.selector_type,
        "eligible_strategy_references": list(arm.eligible_strategy_references),
        "initial_strategy_reference": arm.initial_strategy_reference,
        "initial_capital": arm.initial_capital,
        "currency": arm.currency,
        "arm_account_role": arm.arm_account_role,
        "mandate_reference": arm.mandate_reference,
        "execution_policy_reference": arm.execution_policy_reference,
        "research_budget_reference": arm.research_budget_reference,
        "information_visibility_policy": arm.information_visibility_policy,
        "feedback_policy_reference": arm.feedback_policy_reference,
        "model_configuration_reference": arm.model_configuration_reference,
        "deterministic_seed_reference": arm.deterministic_seed_reference,
        "frozen_configuration_reference": arm.frozen_configuration_reference,
    }


def _campaign_preimage(campaign: CampaignSpecV1) -> dict[str, object]:
    return {
        "schema_version": campaign.schema_version,
        "campaign_id": campaign.campaign_id,
        "campaign_type": campaign.campaign_type,
        "study_protocol_revision": campaign.study_protocol_revision,
        "created_at": campaign.created_at,
        "frozen_at": campaign.frozen_at,
        "accepted_contract_revisions": dict(campaign.accepted_contract_revisions),
        "research_question_id": campaign.research_question_id,
        "primary_comparison": {
            "test_arm_id": campaign.primary_comparison.test_arm_id,
            "comparator_arm_id": campaign.primary_comparison.comparator_arm_id,
        },
        "control_arm_references": list(campaign.control_arm_references),
        "arm_spec_references": list(campaign.arm_spec_references),
        "qualified_dataset_references": list(campaign.qualified_dataset_references),
        "data_window": {
            "start_date": campaign.data_window.start_date,
            "end_date": campaign.data_window.end_date,
            "calendar_id": campaign.data_window.calendar_id,
        },
        "warmup_window": {
            "sessions_count": campaign.warmup_window.sessions_count,
        },
        "observation_window": {
            "sessions_count": campaign.observation_window.sessions_count,
        },
        "scoring_window": {
            "start_session": campaign.scoring_window.start_session,
            "end_session": campaign.scoring_window.end_session,
            "fresh_accounts": campaign.scoring_window.fresh_accounts,
        },
        "decision_schedule": {
            "frequency": campaign.decision_schedule.frequency,
            "alignment": campaign.decision_schedule.alignment,
            "execution_timing": campaign.decision_schedule.execution_timing,
        },
        "allowed_strategy_families": list(campaign.allowed_strategy_families),
        "portfolio_mandate_reference": campaign.portfolio_mandate_reference,
        "source_eligibility_policy_reference": (
            campaign.source_eligibility_policy_reference
        ),
        "execution_policy_reference": campaign.execution_policy_reference,
        "cost_policy_reference": campaign.cost_policy_reference,
        "model_and_prompt_policy_reference": campaign.model_and_prompt_policy_reference,
        "learning_and_feedback_policy_reference": (
            campaign.learning_and_feedback_policy_reference
        ),
        "evaluation_policy_reference": campaign.evaluation_policy_reference,
        "holdout_access_policy_reference": campaign.holdout_access_policy_reference,
        "stopping_policy_reference": campaign.stopping_policy_reference,
        "authorization_evidence": _json_plain(campaign.authorization_evidence),
    }


def _validate_primary_comparison(comp: PrimaryComparisonV1) -> None:
    if type(comp) is not PrimaryComparisonV1:
        raise ValueError("primary_comparison must be a PrimaryComparisonV1 instance")
    _validate_scope_id(comp.test_arm_id, "primary_comparison.test_arm_id")
    _validate_scope_id(comp.comparator_arm_id, "primary_comparison.comparator_arm_id")
    if comp.test_arm_id == comp.comparator_arm_id:
        raise ValueError(
            "test_arm_id and comparator_arm_id must be distinct, "
            f"got: {comp.test_arm_id!r}"
        )


def _validate_data_window(dw: DataWindowV1) -> None:
    if type(dw) is not DataWindowV1:
        raise ValueError("data_window must be a DataWindowV1 instance")
    if type(dw.start_date) is not str or not _ISO_DATE.fullmatch(dw.start_date):
        raise ValueError(f"invalid start_date format: {dw.start_date!r}")
    if type(dw.end_date) is not str or not _ISO_DATE.fullmatch(dw.end_date):
        raise ValueError(f"invalid end_date format: {dw.end_date!r}")
    try:
        sd = date.fromisoformat(dw.start_date)
    except ValueError as exc:
        raise ValueError(
            f"invalid start_date calendar date: {dw.start_date!r}"
        ) from exc
    try:
        ed = date.fromisoformat(dw.end_date)
    except ValueError as exc:
        raise ValueError(f"invalid end_date calendar date: {dw.end_date!r}") from exc
    if sd > ed:
        raise ValueError(
            f"start_date must be <= end_date: {dw.start_date!r} > {dw.end_date!r}"
        )
    _validate_nonempty_str(dw.calendar_id, "data_window.calendar_id")


def _validate_session_window(sw: SessionWindowV1, field_name: str) -> None:
    if type(sw) is not SessionWindowV1:
        raise ValueError(f"{field_name} must be a SessionWindowV1 instance")
    if type(sw.sessions_count) is not int:
        raise ValueError(
            f"{field_name}.sessions_count must be an integer, "
            f"got: {type(sw.sessions_count)}"
        )
    if sw.sessions_count < 0:
        raise ValueError(
            f"{field_name}.sessions_count must be non-negative, "
            f"got: {sw.sessions_count}"
        )


def _validate_scoring_window(sc: ScoringWindowV1) -> None:
    if type(sc) is not ScoringWindowV1:
        raise ValueError("scoring_window must be a ScoringWindowV1 instance")
    _validate_nonempty_str(sc.start_session, "scoring_window.start_session")
    _validate_nonempty_str(sc.end_session, "scoring_window.end_session")
    if sc.start_session == sc.end_session:
        raise ValueError(
            f"start_session and end_session must differ, got: {sc.start_session!r}"
        )
    if type(sc.fresh_accounts) is not bool:
        raise ValueError(
            "scoring_window.fresh_accounts must be a bool, "
            f"got: {type(sc.fresh_accounts)}"
        )
    if sc.fresh_accounts is not True:
        raise ValueError("scoring_window.fresh_accounts must be True")


def _validate_decision_schedule(ds: DecisionScheduleV1) -> None:
    if type(ds) is not DecisionScheduleV1:
        raise ValueError("decision_schedule must be a DecisionScheduleV1 instance")
    _validate_nonempty_str(ds.frequency, "decision_schedule.frequency")
    _validate_nonempty_str(ds.alignment, "decision_schedule.alignment")
    _validate_nonempty_str(ds.execution_timing, "decision_schedule.execution_timing")


def build_arm_spec(
    *,
    arm_id: str,
    campaign_id: str,
    selector_type: str,
    eligible_strategy_references: Sequence[str],
    initial_strategy_reference: str,
    initial_capital: str,
    currency: str,
    arm_account_role: str,
    mandate_reference: str,
    execution_policy_reference: str,
    research_budget_reference: str,
    information_visibility_policy: str,
    feedback_policy_reference: str,
    model_configuration_reference: str,
    deterministic_seed_reference: str,
    frozen_configuration_reference: str,
) -> ArmSpecV1:
    _validate_scope_id(arm_id, "arm_id")
    _validate_scope_id(campaign_id, "campaign_id")
    if type(selector_type) is not str or selector_type not in SELECTOR_TYPES:
        raise ValueError(f"invalid selector_type: {selector_type!r}")

    if not isinstance(eligible_strategy_references, Sequence) or isinstance(
        eligible_strategy_references, (str, bytes)
    ):
        raise ValueError("eligible_strategy_references must be a sequence of strings")
    if not eligible_strategy_references:
        raise ValueError("eligible_strategy_references cannot be empty")
    frozen_eligible = tuple(eligible_strategy_references)
    for ref in frozen_eligible:
        _validate_nonempty_str(ref, "eligible_strategy_reference")
    if len(frozen_eligible) != len(set(frozen_eligible)):
        raise ValueError("eligible_strategy_references contains duplicate values")

    _validate_nonempty_str(initial_strategy_reference, "initial_strategy_reference")
    if initial_strategy_reference not in frozen_eligible:
        raise ValueError(
            f"initial_strategy_reference {initial_strategy_reference!r} "
            "not in eligible strategies"
        )

    _validate_positive_decimal_text(initial_capital, "initial_capital")
    if currency != "USD":
        raise ValueError(f"currency must be USD, got: {currency!r}")

    _validate_nonempty_str(arm_account_role, "arm_account_role")
    _validate_nonempty_str(mandate_reference, "mandate_reference")
    _validate_nonempty_str(execution_policy_reference, "execution_policy_reference")
    _validate_nonempty_str(research_budget_reference, "research_budget_reference")
    _validate_nonempty_str(
        information_visibility_policy, "information_visibility_policy"
    )
    _validate_nonempty_str(feedback_policy_reference, "feedback_policy_reference")
    _validate_nonempty_str(
        model_configuration_reference, "model_configuration_reference"
    )
    _validate_nonempty_str(deterministic_seed_reference, "deterministic_seed_reference")

    if type(frozen_configuration_reference) is not str or not _SHA256.fullmatch(
        frozen_configuration_reference
    ):
        raise ValueError(
            "frozen_configuration_reference must be a lowercase 64-char "
            f"SHA256 string: {frozen_configuration_reference!r}"
        )

    placeholder = ArmSpecV1(
        schema_version=SCHEMA_VERSION,
        arm_id=arm_id,
        campaign_id=campaign_id,
        arm_spec_fingerprint="0" * 64,
        selector_type=selector_type,
        eligible_strategy_references=frozen_eligible,
        initial_strategy_reference=initial_strategy_reference,
        initial_capital=initial_capital,
        currency=currency,
        arm_account_role=arm_account_role,
        mandate_reference=mandate_reference,
        execution_policy_reference=execution_policy_reference,
        research_budget_reference=research_budget_reference,
        information_visibility_policy=information_visibility_policy,
        feedback_policy_reference=feedback_policy_reference,
        model_configuration_reference=model_configuration_reference,
        deterministic_seed_reference=deterministic_seed_reference,
        frozen_configuration_reference=frozen_configuration_reference,
    )
    computed_hash = content_hash(_arm_preimage(placeholder))
    arm = replace(placeholder, arm_spec_fingerprint=computed_hash)
    verify_arm_spec(arm=arm)
    return arm


def verify_arm_spec(*, arm: ArmSpecV1) -> bool:
    if type(arm) is not ArmSpecV1:
        raise ValueError("arm must be an ArmSpecV1 instance")

    if arm.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {arm.schema_version!r}")
    _validate_scope_id(arm.arm_id, "arm_id")
    _validate_scope_id(arm.campaign_id, "campaign_id")
    if type(arm.selector_type) is not str or arm.selector_type not in SELECTOR_TYPES:
        raise ValueError(f"invalid selector_type: {arm.selector_type!r}")

    if type(arm.eligible_strategy_references) is not tuple:
        raise ValueError("eligible_strategy_references must be a tuple")
    if not arm.eligible_strategy_references:
        raise ValueError("eligible_strategy_references cannot be empty")
    for ref in arm.eligible_strategy_references:
        _validate_nonempty_str(ref, "eligible_strategy_reference")
    if len(arm.eligible_strategy_references) != len(
        set(arm.eligible_strategy_references)
    ):
        raise ValueError("eligible_strategy_references contains duplicate values")

    _validate_nonempty_str(arm.initial_strategy_reference, "initial_strategy_reference")
    if arm.initial_strategy_reference not in arm.eligible_strategy_references:
        raise ValueError(
            f"initial_strategy_reference {arm.initial_strategy_reference!r} "
            "not in eligible strategies"
        )

    _validate_positive_decimal_text(arm.initial_capital, "initial_capital")
    if arm.currency != "USD":
        raise ValueError(f"currency must be USD, got: {arm.currency!r}")

    _validate_nonempty_str(arm.arm_account_role, "arm_account_role")
    _validate_nonempty_str(arm.mandate_reference, "mandate_reference")
    _validate_nonempty_str(arm.execution_policy_reference, "execution_policy_reference")
    _validate_nonempty_str(arm.research_budget_reference, "research_budget_reference")
    _validate_nonempty_str(
        arm.information_visibility_policy, "information_visibility_policy"
    )
    _validate_nonempty_str(arm.feedback_policy_reference, "feedback_policy_reference")
    _validate_nonempty_str(
        arm.model_configuration_reference, "model_configuration_reference"
    )
    _validate_nonempty_str(
        arm.deterministic_seed_reference, "deterministic_seed_reference"
    )

    if type(arm.frozen_configuration_reference) is not str or not _SHA256.fullmatch(
        arm.frozen_configuration_reference
    ):
        raise ValueError(
            "frozen_configuration_reference must be a lowercase 64-char "
            f"SHA256 string: {arm.frozen_configuration_reference!r}"
        )

    if type(arm.arm_spec_fingerprint) is not str or not _SHA256.fullmatch(
        arm.arm_spec_fingerprint
    ):
        raise ValueError(f"invalid arm_spec_fingerprint: {arm.arm_spec_fingerprint!r}")

    expected_hash = content_hash(_arm_preimage(arm))
    if arm.arm_spec_fingerprint != expected_hash:
        raise ValueError(
            "arm_spec_fingerprint mismatch: "
            f"expected {expected_hash}, got {arm.arm_spec_fingerprint}"
        )

    return True


def build_campaign_spec(
    *,
    campaign_id: str,
    campaign_type: str,
    study_protocol_revision: str,
    created_at: datetime,
    frozen_at: datetime,
    accepted_contract_revisions: Mapping[str, str],
    research_question_id: str,
    primary_comparison: PrimaryComparisonV1,
    control_arm_references: Sequence[str],
    arm_spec_references: Sequence[str],
    qualified_dataset_references: Sequence[str],
    data_window: DataWindowV1,
    warmup_window: SessionWindowV1,
    observation_window: SessionWindowV1,
    scoring_window: ScoringWindowV1,
    decision_schedule: DecisionScheduleV1,
    allowed_strategy_families: Sequence[str],
    portfolio_mandate_reference: str,
    source_eligibility_policy_reference: str,
    execution_policy_reference: str,
    cost_policy_reference: str,
    model_and_prompt_policy_reference: str,
    learning_and_feedback_policy_reference: str,
    evaluation_policy_reference: str,
    holdout_access_policy_reference: str,
    stopping_policy_reference: str,
    authorization_evidence: Mapping[str, object],
) -> CampaignSpecV1:
    _validate_scope_id(campaign_id, "campaign_id")
    if type(campaign_type) is not str or campaign_type not in CAMPAIGN_TYPES:
        raise ValueError(f"invalid campaign_type: {campaign_type!r}")
    _validate_nonempty_str(study_protocol_revision, "study_protocol_revision")

    created_at_utc = _canonical_utc(created_at)
    frozen_at_utc = _canonical_utc(frozen_at)
    if created_at_utc > frozen_at_utc:
        raise ValueError(
            f"created_at must be <= frozen_at: {created_at_utc!r} > {frozen_at_utc!r}"
        )

    if not isinstance(accepted_contract_revisions, Mapping):
        raise ValueError(
            "accepted_contract_revisions must be a mapping of "
            "contract names to git SHAs"
        )
    keys = list(accepted_contract_revisions.keys())
    for k in keys:
        if type(k) is not str or not k or not k.strip() or k != k.strip():
            raise ValueError(
                "accepted_contract_revisions keys must be nonblank strings "
                "without surrounding whitespace"
            )
    revisions_list: list[tuple[str, str]] = []
    for k in sorted(keys):
        v = accepted_contract_revisions[k]
        if type(v) is not str or not _GIT_SHA.fullmatch(v):
            raise ValueError(
                "accepted_contract_revisions values must be lowercase "
                f"40-char git SHAs: {v!r}"
            )
        revisions_list.append((k, v))
    frozen_accepted_contracts = tuple(revisions_list)

    _validate_scope_id(research_question_id, "research_question_id")
    _validate_primary_comparison(primary_comparison)

    if not isinstance(control_arm_references, Sequence) or isinstance(
        control_arm_references, (str, bytes)
    ):
        raise ValueError("control_arm_references must be a sequence of strings")
    frozen_controls = tuple(control_arm_references)
    for c_id in frozen_controls:
        _validate_scope_id(c_id, "control_arm_reference")
    if len(frozen_controls) != len(set(frozen_controls)):
        raise ValueError("control_arm_references contains duplicate values")

    if not isinstance(arm_spec_references, Sequence) or isinstance(
        arm_spec_references, (str, bytes)
    ):
        raise ValueError("arm_spec_references must be a sequence of strings")
    frozen_arms = tuple(arm_spec_references)
    if not frozen_arms:
        raise ValueError("arm_spec_references cannot be empty")
    for a_ref in frozen_arms:
        if type(a_ref) is not str or not _SHA256.fullmatch(a_ref):
            raise ValueError(
                "arm_spec_reference must be a lowercase 64-char "
                f"SHA256 string: {a_ref!r}"
            )
    if len(frozen_arms) != len(set(frozen_arms)):
        raise ValueError("arm_spec_references contains duplicate values")

    if not isinstance(qualified_dataset_references, Sequence) or isinstance(
        qualified_dataset_references, (str, bytes)
    ):
        raise ValueError("qualified_dataset_references must be a sequence of strings")
    frozen_datasets = tuple(qualified_dataset_references)
    for ds_ref in frozen_datasets:
        _validate_nonempty_str(ds_ref, "qualified_dataset_reference")
    if len(frozen_datasets) != len(set(frozen_datasets)):
        raise ValueError("qualified_dataset_references contains duplicate values")

    _validate_data_window(data_window)
    _validate_session_window(warmup_window, "warmup_window")
    _validate_session_window(observation_window, "observation_window")
    _validate_scoring_window(scoring_window)
    _validate_decision_schedule(decision_schedule)

    if not isinstance(allowed_strategy_families, Sequence) or isinstance(
        allowed_strategy_families, (str, bytes)
    ):
        raise ValueError("allowed_strategy_families must be a sequence of strings")
    frozen_families = tuple(allowed_strategy_families)
    if not frozen_families:
        raise ValueError("allowed_strategy_families cannot be empty")
    for f in frozen_families:
        _validate_nonempty_str(f, "allowed_strategy_family")
    if len(frozen_families) != len(set(frozen_families)):
        raise ValueError("allowed_strategy_families contains duplicate values")

    _validate_nonempty_str(portfolio_mandate_reference, "portfolio_mandate_reference")
    _validate_nonempty_str(
        source_eligibility_policy_reference, "source_eligibility_policy_reference"
    )
    _validate_nonempty_str(execution_policy_reference, "execution_policy_reference")
    _validate_nonempty_str(cost_policy_reference, "cost_policy_reference")
    _validate_nonempty_str(
        model_and_prompt_policy_reference, "model_and_prompt_policy_reference"
    )
    _validate_nonempty_str(
        learning_and_feedback_policy_reference, "learning_and_feedback_policy_reference"
    )
    _validate_nonempty_str(evaluation_policy_reference, "evaluation_policy_reference")
    _validate_nonempty_str(
        holdout_access_policy_reference, "holdout_access_policy_reference"
    )
    _validate_nonempty_str(stopping_policy_reference, "stopping_policy_reference")

    if not isinstance(authorization_evidence, Mapping):
        raise ValueError("authorization_evidence must be a mapping")
    frozen_auth = _freeze_json(authorization_evidence)
    if type(frozen_auth) is not FrozenJSONMap:
        raise ValueError("authorization_evidence must be a JSON map")

    placeholder = CampaignSpecV1(
        schema_version=SCHEMA_VERSION,
        campaign_id=campaign_id,
        campaign_spec_fingerprint="0" * 64,
        campaign_type=campaign_type,
        study_protocol_revision=study_protocol_revision,
        created_at=created_at_utc,
        frozen_at=frozen_at_utc,
        accepted_contract_revisions=frozen_accepted_contracts,
        research_question_id=research_question_id,
        primary_comparison=primary_comparison,
        control_arm_references=frozen_controls,
        arm_spec_references=frozen_arms,
        qualified_dataset_references=frozen_datasets,
        data_window=data_window,
        warmup_window=warmup_window,
        observation_window=observation_window,
        scoring_window=scoring_window,
        decision_schedule=decision_schedule,
        allowed_strategy_families=frozen_families,
        portfolio_mandate_reference=portfolio_mandate_reference,
        source_eligibility_policy_reference=source_eligibility_policy_reference,
        execution_policy_reference=execution_policy_reference,
        cost_policy_reference=cost_policy_reference,
        model_and_prompt_policy_reference=model_and_prompt_policy_reference,
        learning_and_feedback_policy_reference=learning_and_feedback_policy_reference,
        evaluation_policy_reference=evaluation_policy_reference,
        holdout_access_policy_reference=holdout_access_policy_reference,
        stopping_policy_reference=stopping_policy_reference,
        authorization_evidence=frozen_auth,
    )
    computed_hash = content_hash(_campaign_preimage(placeholder))
    campaign = replace(placeholder, campaign_spec_fingerprint=computed_hash)
    verify_campaign_spec(campaign=campaign)
    return campaign


def verify_campaign_spec(*, campaign: CampaignSpecV1) -> bool:
    if type(campaign) is not CampaignSpecV1:
        raise ValueError("campaign must be a CampaignSpecV1 instance")

    if campaign.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {campaign.schema_version!r}")
    _validate_scope_id(campaign.campaign_id, "campaign_id")
    if (
        type(campaign.campaign_type) is not str
        or campaign.campaign_type not in CAMPAIGN_TYPES
    ):
        raise ValueError(f"invalid campaign_type: {campaign.campaign_type!r}")
    _validate_nonempty_str(campaign.study_protocol_revision, "study_protocol_revision")

    _validate_persisted_utc(campaign.created_at)
    _validate_persisted_utc(campaign.frozen_at)
    if campaign.created_at > campaign.frozen_at:
        raise ValueError(
            "created_at must be <= frozen_at: "
            f"{campaign.created_at!r} > {campaign.frozen_at!r}"
        )

    if type(campaign.accepted_contract_revisions) is not tuple:
        raise ValueError("accepted_contract_revisions must be a tuple")
    prev_k: str | None = None
    for item in campaign.accepted_contract_revisions:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError(
                "accepted_contract_revisions item must be a pair of (key, sha)"
            )
        k, v = item
        if type(k) is not str or not k or not k.strip() or k != k.strip():
            raise ValueError(
                "accepted_contract_revisions keys must be nonblank strings "
                f"without surrounding whitespace: {k!r}"
            )
        if type(v) is not str or not _GIT_SHA.fullmatch(v):
            raise ValueError(
                "accepted_contract_revisions value must be a lowercase "
                f"40-char git SHA: {v!r}"
            )
        if prev_k is not None and k <= prev_k:
            raise ValueError(
                "accepted_contract_revisions keys are not strictly sorted: "
                f"{prev_k!r} >= {k!r}"
            )
        prev_k = k

    _validate_scope_id(campaign.research_question_id, "research_question_id")
    _validate_primary_comparison(campaign.primary_comparison)

    if type(campaign.control_arm_references) is not tuple:
        raise ValueError("control_arm_references must be a tuple")
    for c_id in campaign.control_arm_references:
        _validate_scope_id(c_id, "control_arm_reference")
    if len(campaign.control_arm_references) != len(
        set(campaign.control_arm_references)
    ):
        raise ValueError("control_arm_references contains duplicate values")

    if type(campaign.arm_spec_references) is not tuple:
        raise ValueError("arm_spec_references must be a tuple")
    if not campaign.arm_spec_references:
        raise ValueError("arm_spec_references cannot be empty")
    for a_ref in campaign.arm_spec_references:
        if type(a_ref) is not str or not _SHA256.fullmatch(a_ref):
            raise ValueError(
                "arm_spec_reference must be a lowercase 64-char "
                f"SHA256 string: {a_ref!r}"
            )
    if len(campaign.arm_spec_references) != len(set(campaign.arm_spec_references)):
        raise ValueError("arm_spec_references contains duplicate values")

    if type(campaign.qualified_dataset_references) is not tuple:
        raise ValueError("qualified_dataset_references must be a tuple")
    for ds_ref in campaign.qualified_dataset_references:
        _validate_nonempty_str(ds_ref, "qualified_dataset_reference")
    if len(campaign.qualified_dataset_references) != len(
        set(campaign.qualified_dataset_references)
    ):
        raise ValueError("qualified_dataset_references contains duplicate values")

    _validate_data_window(campaign.data_window)
    _validate_session_window(campaign.warmup_window, "warmup_window")
    _validate_session_window(campaign.observation_window, "observation_window")
    _validate_scoring_window(campaign.scoring_window)
    _validate_decision_schedule(campaign.decision_schedule)

    if type(campaign.allowed_strategy_families) is not tuple:
        raise ValueError("allowed_strategy_families must be a tuple")
    if not campaign.allowed_strategy_families:
        raise ValueError("allowed_strategy_families cannot be empty")
    for f in campaign.allowed_strategy_families:
        _validate_nonempty_str(f, "allowed_strategy_family")
    if len(campaign.allowed_strategy_families) != len(
        set(campaign.allowed_strategy_families)
    ):
        raise ValueError("allowed_strategy_families contains duplicate values")

    _validate_nonempty_str(
        campaign.portfolio_mandate_reference, "portfolio_mandate_reference"
    )
    _validate_nonempty_str(
        campaign.source_eligibility_policy_reference,
        "source_eligibility_policy_reference",
    )
    _validate_nonempty_str(
        campaign.execution_policy_reference, "execution_policy_reference"
    )
    _validate_nonempty_str(campaign.cost_policy_reference, "cost_policy_reference")
    _validate_nonempty_str(
        campaign.model_and_prompt_policy_reference, "model_and_prompt_policy_reference"
    )
    _validate_nonempty_str(
        campaign.learning_and_feedback_policy_reference,
        "learning_and_feedback_policy_reference",
    )
    _validate_nonempty_str(
        campaign.evaluation_policy_reference, "evaluation_policy_reference"
    )
    _validate_nonempty_str(
        campaign.holdout_access_policy_reference, "holdout_access_policy_reference"
    )
    _validate_nonempty_str(
        campaign.stopping_policy_reference, "stopping_policy_reference"
    )

    if type(campaign.authorization_evidence) is not FrozenJSONMap:
        raise ValueError("authorization_evidence must be a FrozenJSONMap instance")
    _verify_frozen_json(campaign.authorization_evidence)

    if type(campaign.campaign_spec_fingerprint) is not str or not _SHA256.fullmatch(
        campaign.campaign_spec_fingerprint
    ):
        raise ValueError(
            f"invalid campaign_spec_fingerprint: {campaign.campaign_spec_fingerprint!r}"
        )

    expected_hash = content_hash(_campaign_preimage(campaign))
    if campaign.campaign_spec_fingerprint != expected_hash:
        raise ValueError(
            "campaign_spec_fingerprint mismatch: "
            f"expected {expected_hash}, got {campaign.campaign_spec_fingerprint}"
        )

    return True


def build_run_account_binding(
    *,
    campaign_id: str,
    run_id: str,
    arm_id: str,
    portfolio_account_id: str,
    initial_cash_allocated: str,
    bound_at: datetime,
) -> RunAccountBindingV1:
    _validate_scope_id(campaign_id, "campaign_id")
    _validate_scope_id(run_id, "run_id")
    _validate_scope_id(arm_id, "arm_id")
    _validate_nonempty_str(portfolio_account_id, "portfolio_account_id")
    _validate_positive_decimal_text(initial_cash_allocated, "initial_cash_allocated")
    bound_at_utc = _canonical_utc(bound_at)

    binding_id = f"{campaign_id}:{run_id}:{arm_id}:BINDING"

    binding = RunAccountBindingV1(
        schema_version=SCHEMA_VERSION,
        binding_id=binding_id,
        campaign_id=campaign_id,
        run_id=run_id,
        arm_id=arm_id,
        portfolio_account_id=portfolio_account_id,
        initial_cash_allocated=initial_cash_allocated,
        bound_at=bound_at_utc,
    )
    verify_run_account_binding(binding=binding)
    return binding


def verify_run_account_binding(*, binding: RunAccountBindingV1) -> bool:
    if type(binding) is not RunAccountBindingV1:
        raise ValueError("binding must be a RunAccountBindingV1 instance")

    if binding.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {binding.schema_version!r}")
    _validate_scope_id(binding.campaign_id, "campaign_id")
    _validate_scope_id(binding.run_id, "run_id")
    _validate_scope_id(binding.arm_id, "arm_id")

    expected_binding_id = (
        f"{binding.campaign_id}:{binding.run_id}:{binding.arm_id}:BINDING"
    )
    if binding.binding_id != expected_binding_id:
        raise ValueError(
            "binding_id mismatch: "
            f"expected {expected_binding_id!r}, got {binding.binding_id!r}"
        )

    _validate_nonempty_str(binding.portfolio_account_id, "portfolio_account_id")
    _validate_positive_decimal_text(
        binding.initial_cash_allocated, "initial_cash_allocated"
    )
    _validate_persisted_utc(binding.bound_at)

    return True


def verify_experiment_configuration(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool:
    verify_campaign_spec(campaign=campaign)

    if not isinstance(arms, Sequence) or isinstance(arms, (str, bytes)):
        raise ValueError("arms must be a sequence of ArmSpecV1 instances")
    if not arms:
        raise ValueError("arms collection cannot be empty")

    arm_ids: list[str] = []
    arm_fps: list[str] = []
    arms_by_id: dict[str, ArmSpecV1] = {}

    for arm in arms:
        verify_arm_spec(arm=arm)
        if arm.campaign_id != campaign.campaign_id:
            raise ValueError(
                f"arm campaign_id {arm.campaign_id!r} does not match "
                f"campaign {campaign.campaign_id!r}"
            )
        if arm.arm_id in arms_by_id:
            raise ValueError(f"duplicate arm ID: {arm.arm_id!r}")
        arm_ids.append(arm.arm_id)
        arm_fps.append(arm.arm_spec_fingerprint)
        arms_by_id[arm.arm_id] = arm

    if len(arm_fps) != len(set(arm_fps)):
        raise ValueError("duplicate arm fingerprints in arms collection")

    if set(campaign.arm_spec_references) != set(arm_fps) or len(
        campaign.arm_spec_references
    ) != len(arm_fps):
        raise ValueError(
            "campaign.arm_spec_references does not match supplied arms fingerprints"
        )

    primary = campaign.primary_comparison
    if primary.test_arm_id not in arms_by_id:
        raise ValueError(
            f"primary test_arm_id {primary.test_arm_id!r} not found in arms"
        )
    if primary.comparator_arm_id not in arms_by_id:
        raise ValueError(
            f"primary comparator_arm_id {primary.comparator_arm_id!r} not found in arms"
        )
    if primary.test_arm_id == primary.comparator_arm_id:
        raise ValueError("primary comparison arm IDs must be distinct")

    for c_id in campaign.control_arm_references:
        if c_id not in arms_by_id:
            raise ValueError(f"declared control arm {c_id!r} not found in arms")

    if len(campaign.control_arm_references) != len(
        set(campaign.control_arm_references)
    ):
        raise ValueError("control_arm_references contains duplicates")

    primary_pair = {primary.test_arm_id, primary.comparator_arm_id}
    if set(campaign.control_arm_references) & primary_pair:
        raise ValueError("control_arm_references overlaps with primary comparison pair")

    if not isinstance(expected_run_ids, Sequence) or isinstance(
        expected_run_ids, (str, bytes)
    ):
        raise ValueError("expected_run_ids must be a sequence of strings")
    if not expected_run_ids:
        raise ValueError("expected_run_ids cannot be empty")
    for r_id in expected_run_ids:
        _validate_scope_id(r_id, "expected_run_id")
    if len(expected_run_ids) != len(set(expected_run_ids)):
        raise ValueError("duplicate run IDs in expected_run_ids")
    expected_runs_set = set(expected_run_ids)

    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise ValueError("bindings must be a sequence of RunAccountBindingV1 instances")

    seen_binding_ids: set[str] = set()
    seen_cra: set[tuple[str, str, str]] = set()
    seen_accounts: set[str] = set()
    runs_in_bindings: set[str] = set()

    for binding in bindings:
        verify_run_account_binding(binding=binding)
        if binding.campaign_id != campaign.campaign_id:
            raise ValueError(
                f"binding campaign_id {binding.campaign_id!r} does not match "
                f"campaign {campaign.campaign_id!r}"
            )
        if binding.arm_id not in arms_by_id:
            raise ValueError(f"binding refers to unknown arm_id: {binding.arm_id!r}")
        if binding.run_id not in expected_runs_set:
            raise ValueError(
                f"binding run_id {binding.run_id!r} not in expected_run_ids"
            )

        if binding.binding_id in seen_binding_ids:
            raise ValueError(f"duplicate binding_id: {binding.binding_id!r}")
        seen_binding_ids.add(binding.binding_id)

        cra = (binding.campaign_id, binding.run_id, binding.arm_id)
        if cra in seen_cra:
            raise ValueError(f"duplicate (campaign_id, run_id, arm_id) binding: {cra}")
        seen_cra.add(cra)

        if binding.portfolio_account_id in seen_accounts:
            raise ValueError(
                f"portfolio_account_id {binding.portfolio_account_id!r} "
                "reused across bindings"
            )
        seen_accounts.add(binding.portfolio_account_id)

        matched_arm = arms_by_id[binding.arm_id]
        if binding.initial_cash_allocated != matched_arm.initial_capital:
            raise ValueError(
                f"binding initial_cash_allocated ({binding.initial_cash_allocated}) "
                f"does not match arm initial_capital ({matched_arm.initial_capital})"
            )

        if binding.bound_at < campaign.frozen_at:
            raise ValueError(
                f"binding bound_at ({binding.bound_at}) is before "
                f"campaign frozen_at ({campaign.frozen_at})"
            )

        runs_in_bindings.add(binding.run_id)

    if runs_in_bindings != expected_runs_set:
        raise ValueError(
            f"bindings run set ({runs_in_bindings}) does not match "
            f"expected_run_ids ({expected_runs_set})"
        )

    declared_arm_ids = set(arm_ids)
    for run_id in expected_run_ids:
        run_bindings = [b for b in bindings if b.run_id == run_id]
        bound_arms = {b.arm_id for b in run_bindings}
        if bound_arms != declared_arm_ids:
            missing = declared_arm_ids - bound_arms
            extra = bound_arms - declared_arm_ids
            raise ValueError(
                f"run {run_id!r} does not bind exactly every declared arm "
                f"(missing: {missing}, extra: {extra})"
            )
        if len(run_bindings) != len(declared_arm_ids):
            raise ValueError(f"run {run_id!r} has incorrect binding count")

    return True


def verify_stage1_synthetic_br_configuration(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool:
    verify_experiment_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    if campaign.campaign_type != "SYNTHETIC_TEST":
        raise ValueError(
            "Stage 1 synthetic campaign_type must be SYNTHETIC_TEST, "
            f"got: {campaign.campaign_type!r}"
        )

    if campaign.primary_comparison.test_arm_id != "ARM-B":
        raise ValueError(
            "Stage 1 test_arm_id must be ARM-B, "
            f"got: {campaign.primary_comparison.test_arm_id!r}"
        )
    if campaign.primary_comparison.comparator_arm_id != "ARM-R":
        raise ValueError(
            "Stage 1 comparator_arm_id must be ARM-R, "
            f"got: {campaign.primary_comparison.comparator_arm_id!r}"
        )

    arms_by_id = {arm.arm_id: arm for arm in arms}
    arm_b = arms_by_id["ARM-B"]
    arm_r = arms_by_id["ARM-R"]

    if arm_b.arm_account_role != "PRIMARY_TEST":
        raise ValueError("ARM-B arm_account_role must be PRIMARY_TEST")
    if arm_r.arm_account_role != "COMPARATOR":
        raise ValueError("ARM-R arm_account_role must be COMPARATOR")

    if arm_b.frozen_configuration_reference != arm_r.frozen_configuration_reference:
        raise ValueError("ARM-B and ARM-R frozen_configuration_reference must match")

    if arm_b.selector_type != "ADAPTIVE_AI":
        raise ValueError(
            f"ARM-B selector_type must be ADAPTIVE_AI, got: {arm_b.selector_type!r}"
        )
    if arm_r.selector_type != "DETERMINISTIC_COMPARATOR":
        raise ValueError(
            "ARM-R selector_type must be DETERMINISTIC_COMPARATOR, "
            f"got: {arm_r.selector_type!r}"
        )

    if arm_b.initial_strategy_reference != "B3":
        raise ValueError(
            "ARM-B initial_strategy_reference must be B3, "
            f"got: {arm_b.initial_strategy_reference!r}"
        )
    if set(arm_b.eligible_strategy_references) != {"B3", "B4", "B5"}:
        raise ValueError(
            "ARM-B eligible strategies must be {B3, B4, B5}, "
            f"got: {set(arm_b.eligible_strategy_references)}"
        )

    if arm_r.initial_strategy_reference != "B3":
        raise ValueError(
            "ARM-R initial_strategy_reference must be B3, "
            f"got: {arm_r.initial_strategy_reference!r}"
        )
    if set(arm_r.eligible_strategy_references) != {"B3", "B4", "B5"}:
        raise ValueError(
            "ARM-R eligible strategies must be {B3, B4, B5}, "
            f"got: {set(arm_r.eligible_strategy_references)}"
        )

    if not {"B3", "B4", "B5"}.issubset(set(campaign.allowed_strategy_families)):
        raise ValueError(
            "campaign allowed_strategy_families must include B3, B4, B5; "
            f"got: {campaign.allowed_strategy_families}"
        )

    primary_ids = {"ARM-B", "ARM-R"}
    control_ids = set(campaign.control_arm_references)
    supplied_ids = set(arms_by_id.keys())
    if supplied_ids != primary_ids | control_ids:
        raise ValueError(
            f"supplied arms ({supplied_ids}) do not match primary plus "
            f"declared controls ({primary_ids | control_ids})"
        )

    for arm in arms:
        if arm.initial_capital != "10000":
            raise ValueError(
                f"arm {arm.arm_id} initial_capital must be 10000, "
                f"got: {arm.initial_capital!r}"
            )
        if arm.currency != "USD":
            raise ValueError(
                f"arm {arm.arm_id} currency must be USD, got: {arm.currency!r}"
            )

    if arm_b.mandate_reference != arm_r.mandate_reference:
        raise ValueError(
            "ARM-B and ARM-R mandate_reference mismatch: "
            f"{arm_b.mandate_reference!r} != {arm_r.mandate_reference!r}"
        )
    if arm_b.execution_policy_reference != arm_r.execution_policy_reference:
        raise ValueError(
            "ARM-B and ARM-R execution_policy_reference mismatch: "
            f"{arm_b.execution_policy_reference!r} != "
            f"{arm_r.execution_policy_reference!r}"
        )
    if arm_b.mandate_reference != campaign.portfolio_mandate_reference:
        raise ValueError(
            "primary arm mandate_reference must match "
            "campaign.portfolio_mandate_reference"
        )
    if arm_b.execution_policy_reference != campaign.execution_policy_reference:
        raise ValueError(
            "primary arm execution_policy_reference "
            "must match campaign.execution_policy_reference"
        )
    if arm_b.feedback_policy_reference != arm_r.feedback_policy_reference:
        raise ValueError("ARM-B and ARM-R feedback_policy_reference must match")
    if (
        arm_b.information_visibility_policy
        != "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"
    ):
        raise ValueError(
            "ARM-B information_visibility_policy must be "
            "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED, "
            f"got: {arm_b.information_visibility_policy!r}"
        )
    if (
        arm_r.information_visibility_policy
        != "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"
    ):
        raise ValueError(
            "ARM-R information_visibility_policy must be "
            "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED, "
            f"got: {arm_r.information_visibility_policy!r}"
        )

    if arm_b.model_configuration_reference == "NONE":
        raise ValueError("ARM-B requires a non-NONE model_configuration_reference")
    if (
        arm_b.model_configuration_reference
        != campaign.model_and_prompt_policy_reference
    ):
        raise ValueError(
            "ARM-B model_configuration_reference must "
            "match campaign.model_and_prompt_policy_reference"
        )
    if arm_r.model_configuration_reference != "NONE":
        raise ValueError("ARM-R model_configuration_reference must be NONE")

    if campaign.warmup_window.sessions_count < 253:
        raise ValueError(
            "warmup_window.sessions_count must be >= 253, "
            f"got: {campaign.warmup_window.sessions_count}"
        )
    if campaign.observation_window.sessions_count != 126:
        raise ValueError(
            "observation_window.sessions_count must be 126, "
            f"got: {campaign.observation_window.sessions_count}"
        )

    if campaign.decision_schedule.frequency != "MONTHLY":
        raise ValueError(
            "decision_schedule.frequency must be MONTHLY, "
            f"got: {campaign.decision_schedule.frequency!r}"
        )
    if campaign.decision_schedule.alignment != "LAST_COMPLETED_SESSION":
        raise ValueError(
            "decision_schedule.alignment must be LAST_COMPLETED_SESSION, "
            f"got: {campaign.decision_schedule.alignment!r}"
        )
    if campaign.decision_schedule.execution_timing != "NEXT_OPEN":
        raise ValueError(
            "decision_schedule.execution_timing must be NEXT_OPEN, "
            f"got: {campaign.decision_schedule.execution_timing!r}"
        )

    return True
