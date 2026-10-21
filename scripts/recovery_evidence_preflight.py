"""In-memory recovery evidence preflight for #520 (related to #395).

This module performs *only* structural checks on caller-provided synthetic
records. Passing it is not source authentication, independent review,
restoration, a host safety assessment, or authorization for external execution.
No filesystem, subprocess, network, broker, or private-state operations occur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

_COMPONENTS = ("CODE", "PRIVATE_STATE", "RUNTIME")
_TARGET_REQUIRED: dict[str, tuple[str, ...]] = {
    "FEATURE_OFF": (
        "corrected_kernel_commit",
        "corrected_kernel_acceptance_ref",
        "feature_config_sha256",
        "current_state_receipt_ref",
        "supported_path_receipt_ref",
    ),
    "ISOLATED_ORIGINAL": (
        "historical_tree_commit",
        "custodian_ref",
        "isolation_destination_receipt_ref",
        "snapshot_consistency_receipt_ref",
        "historical_runtime_pin_ref",
        "original_scope_ref",
    ),
    "FROZEN_CONTROL": (
        "corrected_kernel_commit",
        "corrected_kernel_acceptance_ref",
        "frozen_policy_sha256",
        "arm_account_isolation_receipt_ref",
        "comparability_receipt_ref",
        "frozen_arm",
    ),
}
_COMMON_REQUIRED = (
    "run_id",
    "manifest_id",
    "grant_ref",
    "grant_verification_receipt_ref",
    "mechanism_author",
    "independent_verifier",
    "independent_review_ref",
    "external_custody_anchor_ref",
    "append_only_lineage_ref",
    "execution_hold_state",
)
_STATUSES = frozenset(
    {"passed", "failed", "pending", "cancelled", "blocked", "not_run", "unavailable"}
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class RecoveryPreflight:
    """Structural readiness for later review, *never* operational clearance."""

    structurally_reviewable: bool
    reasons: tuple[str, ...]

    @property
    def authorizes_recovery_or_execution(self) -> bool:
        """Always false: no in-memory assertion can establish a valid grant."""
        return False


def _obj(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(key) is not str for key in value):
        return None
    return cast(dict[str, object], value)


def _has_text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _digest(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def preflight_recovery_evidence(payload: object) -> RecoveryPreflight:
    """Check record completeness without trusting a submitted claim of success.

    All provided evidence references are *unverified*. Independent custodians
    must authenticate original bytes, permissions, and the actual environment.
    """
    record = _obj(payload)
    if record is None:
        return RecoveryPreflight(False, ("payload.not_plain_object",))

    problems: list[str] = []
    target = record.get("target")
    if type(target) is not str or target not in _TARGET_REQUIRED:
        problems.append("target.invalid")
        required: tuple[str, ...] = ()
    else:
        required = _TARGET_REQUIRED[target]

    for field in (*_COMMON_REQUIRED, *required):
        if not _has_text(record.get(field)):
            problems.append(f"{field}.missing")

    manifest_hash = record.get("manifest_sha256")
    if not _digest(manifest_hash, _HEX_SHA256):
        problems.append("manifest_sha256.invalid")

    for name in ("corrected_kernel_commit", "historical_tree_commit"):
        if name in required and not _digest(record.get(name), _HEX_SHA1):
            problems.append(f"{name}.invalid")

    for name in ("feature_config_sha256", "frozen_policy_sha256"):
        if name in required and not _digest(record.get(name), _HEX_SHA256):
            problems.append(f"{name}.invalid")

    if target == "FROZEN_CONTROL" and record.get("frozen_arm") != "A":
        problems.append("frozen_control.requires_arm_A")

    author = record.get("mechanism_author")
    reviewer = record.get("independent_verifier")
    if _has_text(author) and author == reviewer:
        problems.append("independent_verifier.self_review")

    hold = record.get("execution_hold_state")
    if hold not in ("CLEAR", "HELD", "UNKNOWN"):
        problems.append("execution_hold_state.invalid")
    elif hold != "CLEAR":
        problems.append("execution_hold_state.not_resolved_for_resumption")

    evidence = _obj(record.get("components"))
    if evidence is None:
        problems.append("components.not_plain_object")
        return RecoveryPreflight(False, tuple(problems))

    if set(evidence) != set(_COMPONENTS):
        problems.append("components.must_contain_exact_dimensions")

    refs: set[str] = set()
    for dimension in _COMPONENTS:
        entry = _obj(evidence.get(dimension))
        if entry is None:
            problems.append(f"{dimension}.missing_or_malformed")
            continue
        status = entry.get("status")
        if status not in _STATUSES or type(status) is not str:
            problems.append(f"{dimension}.status.invalid")
        elif status != "passed":
            problems.append(f"{dimension}.status.not_passed")

        for field in ("receipt_ref", "revision_ref", "environment_ref"):
            if not _has_text(entry.get(field)):
                problems.append(f"{dimension}.{field}.missing")

        ref = entry.get("receipt_ref")
        if _has_text(ref):
            assert isinstance(ref, str)
            if ref in refs:
                problems.append(f"{dimension}.receipt_reused_across_dimensions")
            refs.add(ref)

        if not _digest(entry.get("manifest_sha256"), _HEX_SHA256):
            problems.append(f"{dimension}.manifest_sha256.invalid")
        elif entry["manifest_sha256"] != manifest_hash:
            problems.append(f"{dimension}.manifest_mismatch")

    return RecoveryPreflight(not problems, tuple(problems))
