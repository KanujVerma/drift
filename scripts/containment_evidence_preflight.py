"""Pure synthetic containment evidence preflight for #521 and #396.

This checker reads only an in-memory value. It never performs an attack,
launches a worker, tests network connectivity or evaluates a live sandbox.
A matching self-asserted receipt is not authenticated enforcement proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

_REQUIRED_CASES = frozenset(f"A{i:02}" for i in range(1, 12))
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_POSSIBLE_STATUSES = frozenset(
    {"passed", "failed", "pending", "cancelled", "blocked", "not_run", "unavailable"}
)
_REQUIRED_ROOT_TEXT = (
    "run_id",
    "environment_ref",
    "sandbox_image_ref",
    "grant_verification_receipt_ref",
    "capability_inventory_ref",
    "network_policy_receipt_ref",
    "trusted_enforcer_ref",
    "external_enforcer_receipt_ref",
    "mechanism_author",
    "independent_verifier",
    "independent_review_ref",
    "independent_custody_anchor_ref",
)


@dataclass(frozen=True, slots=True)
class ContainmentPreflight:
    """A report prepared for human review, not permission to run a worker."""

    structurally_reviewable: bool
    reasons: tuple[str, ...]

    @property
    def authorizes_worker_launch(self) -> bool:
        return False


def _obj(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(key) is not str for key in value):
        return None
    return cast(dict[str, object], value)


def _has_text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _hex_digest(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def preflight_containment_evidence(payload: object) -> ContainmentPreflight:
    """Fail closed on incomplete paired canary claims and recorded scope.

    Only a separate trusted enforcer, evidence custodian, and independent review
    can establish the truth of these *unverified* submitted references.
    """
    data = _obj(payload)
    if data is None:
        return ContainmentPreflight(False, ("payload.not_plain_object",))

    problems: list[str] = []
    for field in _REQUIRED_ROOT_TEXT:
        if not _has_text(data.get(field)):
            problems.append(f"{field}.missing")

    if not _hex_digest(data.get("source_commit"), _HEX_COMMIT):
        problems.append("source_commit.invalid")
    if not _hex_digest(data.get("policy_sha256"), _HEX_SHA256):
        problems.append("policy_sha256.invalid")

    if (
        type(data.get("network_profile")) is not str
        or data.get("network_profile") != "offline"
    ):
        problems.append("network_profile.must_be_offline_for_this_preflight")
    if (
        type(data.get("unconfined_fallback")) is not str
        or data.get("unconfined_fallback") != "refused"
    ):
        problems.append("unconfined_fallback.not_refused")

    author = data.get("mechanism_author")
    reviewer = data.get("independent_verifier")
    if _has_text(author) and _has_text(reviewer) and author == reviewer:
        problems.append("independent_verifier.self_review")
    if (
        type(data.get("evidence_origin")) is not str
        or data.get("evidence_origin") != "independent_enforcer"
    ):
        problems.append("evidence_origin.not_external_enforcer")

    cases_value = data.get("cases")
    if type(cases_value) is not list:
        return ContainmentPreflight(False, tuple([*problems, "cases.not_plain_list"]))

    seen: set[str] = set()
    for index, item in enumerate(cases_value):
        case = _obj(item)
        if case is None:
            problems.append(f"cases.{index}.not_plain_object")
            continue
        case_id = case.get("case_id")
        if type(case_id) is not str or case_id not in _REQUIRED_CASES:
            problems.append(f"cases.{index}.unknown_id")
            continue
        if case_id in seen:
            problems.append(f"{case_id}.duplicate")
            continue
        seen.add(case_id)

        for status_field in ("denial_status", "control_status"):
            status = case.get(status_field)
            if type(status) is not str or status not in _POSSIBLE_STATUSES:
                problems.append(f"{case_id}.{status_field}.invalid")
            elif status != "passed":
                problems.append(f"{case_id}.{status_field}.not_passed")

        for field in (
            "denial_receipt_ref",
            "control_receipt_ref",
            "enforcer_path_ref",
            "environment_ref",
        ):
            if not _has_text(case.get(field)):
                problems.append(f"{case_id}.{field}.missing")

        if (
            _has_text(case.get("denial_receipt_ref"))
            and _has_text(case.get("control_receipt_ref"))
            and case.get("denial_receipt_ref") == case.get("control_receipt_ref")
        ):
            problems.append(f"{case_id}.denial_control_receipt_identical")

        case_environment = case.get("environment_ref")
        root_environment = data.get("environment_ref")
        if (
            type(case_environment) is str
            and type(root_environment) is str
            and case_environment != root_environment
        ):
            problems.append(f"{case_id}.environment_mismatch")
        if (
            type(case.get("evidence_origin")) is not str
            or case.get("evidence_origin") != "independent_enforcer"
        ):
            problems.append(f"{case_id}.worker_claim_not_enforcement_proof")

        if case_id in ("A01", "A11") and not _has_text(
            case.get("independent_before_after_anchor_ref")
        ):
            problems.append(f"{case_id}.independent_anchor.missing")
        if case_id == "A07" and not _has_text(
            case.get("direct_alternate_path_denial_receipt_ref")
        ):
            problems.append("A07.direct_alternate_path_receipt.missing")
        if case_id == "A08":
            if (
                type(case.get("control_kind")) is not str
                or case.get("control_kind") != "offline_local_fixture"
            ):
                problems.append("A08.offline_control_kind.invalid")
            if not _has_text(case.get("egress_policy_denial_receipt_ref")):
                problems.append("A08.egress_denial_receipt.missing")
        if case_id == "A10" and not _has_text(
            case.get("no_unconfined_retry_receipt_ref")
        ):
            problems.append("A10.fallback_denial_receipt.missing")

    for missing in sorted(_REQUIRED_CASES - seen):
        problems.append(f"{missing}.missing")

    return ContainmentPreflight(not problems, tuple(problems))
