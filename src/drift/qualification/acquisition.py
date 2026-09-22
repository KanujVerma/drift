"""Acquisition receipt generation, secret screening, and reconciliation."""

import json
import re
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import (
    AcquisitionCompleteness,
    AcquisitionExecutionContextV1,
    AcquisitionPlanV1,
    AcquisitionReceiptV1,
    AcquisitionReconciliationV1,
    ExpectedInventoryV1,
    NativeByteGraphV1,
    ObservedObjectV1,
    OriginStatus,
    PageReceiptV1,
    ProviderNativeLayerRuleV1,
    RequestIdentityV1,
    RetryReceiptV1,
)
from drift.domain.common import SHA256Hash
from drift.serialization.canonical import content_hash

_CREDENTIAL_TERMS = frozenset(
    {
        "apikey",
        "api_key",
        "token",
        "accesstoken",
        "authtoken",
        "secret",
        "password",
        "signature",
        "sig",
        "authorization",
        "cookie",
        "bearer",
        "basic",
        "signedurl",
        "xamzsignature",
        "xgoogsignature",
        "sessionid",
        "session_id",
        "csrftoken",
        "csrf_token",
    }
)

_SECRET_VALUE_PATTERNS = (
    re.compile(r"[a-zA-Z0-9_-]*key[a-zA-Z0-9_-]*=[^\s&]+", re.IGNORECASE),
    re.compile(r"ghp_[0-9a-zA-Z]{36}"),
    re.compile(r"sk_live_[0-9a-zA-Z]+"),
    re.compile(r"Bearer\s+[^\s]+", re.IGNORECASE),
    re.compile(
        r"(?:bearer|token|secret|api[_-]?key)[=:\s_-]+[a-zA-Z0-9_-]+",
        re.IGNORECASE,
    ),
)


def validate_secret_free_acquisition_payload(value: object) -> None:
    """Recursively reject credentials, tokens, signatures, and cookies.

    Every value is screened. Keys are screened only when they are arbitrary
    mapping keys carried in payload data, since those can be provider-supplied
    at runtime; declared Pydantic model field names are not screened.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return

    if isinstance(value, str):
        lowered = value.lower()
        for term in _CREDENTIAL_TERMS:
            # Check if term appears as a standalone header, param, or token
            if f"{term}=" in lowered or f"{term}:" in lowered:
                raise ValueError(
                    f"Potential credential term '{term}' found in payload: {value}"
                )
        for pat in _SECRET_VALUE_PATTERNS:
            if pat.search(value):
                raise ValueError(
                    f"Secret credential pattern detected in payload: {value}"
                )
        if "@" in value and (
            value.startswith("http://") or value.startswith("https://")
        ):
            host_segment = value.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
            if "@" in host_segment:
                raise ValueError("URL userinfo credentials detected in payload")

        stripped = value.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                parsed = json.loads(stripped)
            except Exception:
                parsed = None
            if parsed is not None and isinstance(parsed, (dict, list)):
                validate_secret_free_acquisition_payload(parsed)
        return

    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str):
                normalized_k = k.casefold().replace("-", "").replace("_", "")
                for term in _CREDENTIAL_TERMS:
                    clean_term = term.replace("-", "").replace("_", "")
                    if clean_term in normalized_k:
                        raise ValueError(
                            f"credential parameter or header '{k}' detected"
                        )
            validate_secret_free_acquisition_payload(k)
            validate_secret_free_acquisition_payload(v)
        return

    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            validate_secret_free_acquisition_payload(item)
        return

    if isinstance(value, BaseModel):
        # A declared model field name is fixed by Drift source code, so it can
        # never carry a credential smuggled in at runtime. Screening it only
        # produces false positives on legitimate schema vocabulary such as
        # OriginEvidenceV1.provider_signatures. Field values are still screened
        # in full, and any undeclared extra key is runtime-supplied, so it is
        # routed back through the arbitrary-mapping key screen.
        for field_name in type(value).model_fields:
            validate_secret_free_acquisition_payload(getattr(value, field_name))
        extra = value.model_extra
        if extra:
            validate_secret_free_acquisition_payload(extra)
        return

    if hasattr(value, "model_dump"):
        validate_secret_free_acquisition_payload(value.model_dump(mode="python"))
        return

    if hasattr(value, "__dict__"):
        validate_secret_free_acquisition_payload(vars(value))
        return


def reconcile_acquisition(
    expected: ExpectedInventoryV1,
    pages: tuple[PageReceiptV1, ...],
    observed: tuple[ObservedObjectV1, ...],
    retries: tuple[RetryReceiptV1, ...] = (),
    request_start: datetime | None = None,
    snapshot_token: str | tuple[str, ...] | None = None,
) -> AcquisitionReconciliationV1:
    """Evaluate expected vs observed inventory, pagination, retries, and tokens."""
    reasons: list[str] = []
    is_unknown = False
    is_fail = False

    # 1. Timing check
    if request_start is not None and expected.frozen_at > request_start:
        reasons.append("expected inventory not frozen before request start")
        is_unknown = True

    if not expected.justification.strip() or not expected.enumeration_source.strip():
        reasons.append("expected inventory unjustified or lacks authoritative source")
        is_unknown = True

    # 2. Key reconciliation
    expected_keys = tuple(sorted(obj.object_key for obj in expected.objects))
    expected_set = set(expected_keys)

    received_keys_list: list[str] = []
    observed_key_descriptors: dict[str, set[tuple[str, ...]]] = {}

    for obs in observed:
        key = obs.matched_expected_key or obs.provider_object_identity
        received_keys_list.append(key)
        if key not in observed_key_descriptors:
            observed_key_descriptors[key] = set()
        observed_key_descriptors[key].add(obs.byte_object_descriptor_hashes)

    received_keys = tuple(received_keys_list)
    received_set = set(received_keys)

    missing_keys = tuple(sorted(expected_set - received_set))
    extra_keys = tuple(sorted(received_set - expected_set))

    if missing_keys:
        reasons.append(f"missing expected objects: {missing_keys}")
        is_fail = True

    if extra_keys:
        reasons.append(f"unexpected extra objects: {extra_keys}")
        is_fail = True

    # 3. Duplicate objects & conflicting bytes
    duplicate_keys = tuple(
        sorted({k for k in received_keys if received_keys_list.count(k) > 1})
    )

    for k, desc_sets in observed_key_descriptors.items():
        if len(desc_sets) > 1:
            reasons.append(f"conflicting duplicate bytes for key {k}")
            is_fail = True

    retry_page_ids = {r.page_identity for r in retries}
    retry_descriptors = {h for r in retries for h in r.byte_object_descriptor_hashes}
    declared_duplicates = {dup for p in pages for dup in p.duplicates}

    for dup_key in duplicate_keys:
        key_obs = [
            obs
            for obs in observed
            if (obs.matched_expected_key or obs.provider_object_identity) == dup_key
        ]
        accounted = 0
        for obs in key_obs:
            if (
                obs.page_identity in retry_page_ids
                or any(
                    h in retry_descriptors for h in obs.byte_object_descriptor_hashes
                )
                or dup_key in declared_duplicates
            ):
                accounted += 1
        if accounted < len(key_obs) - 1:
            reasons.append(f"duplicate object key '{dup_key}' without declared retry")
            is_fail = True

    # 4. Duplicate pages without retry identity
    page_ids = [p.page_identity for p in pages]
    for pid in set(page_ids):
        if page_ids.count(pid) > 1 and pid not in retry_page_ids:
            reasons.append(f"duplicate page identity '{pid}' without declared retry")
            is_fail = True

    # 5. Cursor chain and cycles
    cursor_chain: list[str | None] = []
    cursor_cycle_detected = False
    seen_cursors: set[str] = set()

    sorted_pages = sorted(pages, key=lambda p: p.page_order)
    for i, p in enumerate(sorted_pages):
        cursor_chain.append(p.cursor_in)
        if p.cursor_in:
            if p.cursor_in in seen_cursors:
                cursor_cycle_detected = True
                reasons.append(f"cursor cycle detected at cursor {p.cursor_in}")
                is_fail = True
            seen_cursors.add(p.cursor_in)

        if p.cursor_out:
            if p.cursor_out in seen_cursors:
                cursor_cycle_detected = True
                reasons.append(f"cursor cycle detected at cursor_out {p.cursor_out}")
                is_fail = True

        if i > 0:
            prev_p = sorted_pages[i - 1]
            if prev_p.cursor_out != p.cursor_in:
                reasons.append(
                    f"cursor discontinuity: page {prev_p.page_identity} cursor_out "
                    f"'{prev_p.cursor_out}' != page {p.page_identity} "
                    f"cursor_in '{p.cursor_in}'"
                )
                is_fail = True

    # Check terminal page closure
    if sorted_pages:
        terminal_page = sorted_pages[-1]
        cursor_chain.append(terminal_page.cursor_out)
        if terminal_page.cursor_out:
            reasons.append(
                f"unclosed pagination: terminal page {terminal_page.page_identity} "
                f"has non-empty cursor_out '{terminal_page.cursor_out}'"
            )
            is_fail = True

    # 6. Origin status
    for obs in observed:
        if obs.origin_evidence.origin_status is OriginStatus.UNKNOWN:
            reasons.append(
                "unverified origin evidence for observed object "
                f"{obs.provider_object_identity}"
            )
            is_unknown = True

    # 7. Snapshot token consistency
    snapshot_tokens: tuple[str, ...] = ()
    snapshot_token_consistent = True
    if snapshot_token is not None:
        if isinstance(snapshot_token, str):
            snapshot_tokens = (snapshot_token,)
        else:
            snapshot_tokens = tuple(sorted(set(snapshot_token)))
            if len(snapshot_tokens) > 1:
                snapshot_token_consistent = False
                reasons.append(f"conflicting snapshot tokens: {snapshot_tokens}")
                is_fail = True

    # 8. Expected object count checks
    count_reconciled = len(missing_keys) == 0 and len(extra_keys) == 0
    for exp in expected.objects:
        if exp.expected_count is not None:
            actual_count = received_keys_list.count(exp.object_key)
            if actual_count != exp.expected_count:
                reasons.append(
                    f"object count mismatch for key '{exp.object_key}': "
                    f"expected {exp.expected_count}, observed {actual_count}"
                )
                is_fail = True
                count_reconciled = False

    # Determine final result
    if is_fail:
        result = AcquisitionCompleteness.FAIL
    elif is_unknown:
        result = AcquisitionCompleteness.UNKNOWN
    elif missing_keys:
        result = AcquisitionCompleteness.PARTIAL
    else:
        result = AcquisitionCompleteness.PASS

    return AcquisitionReconciliationV1(
        expected_keys=expected_keys,
        received_keys=received_keys,
        missing_keys=missing_keys,
        duplicate_keys=duplicate_keys,
        extra_keys=extra_keys,
        cursor_cycle_detected=cursor_cycle_detected,
        cursor_chain=tuple(cursor_chain),
        count_reconciled=count_reconciled,
        snapshot_token_consistent=snapshot_token_consistent,
        snapshot_tokens=snapshot_tokens,
        result=result,
        reasons=tuple(reasons),
    )


def build_acquisition_receipt(
    plan: AcquisitionPlanV1,
    authorization_hash: SHA256Hash,
    profile_set_hash: SHA256Hash,
    request: RequestIdentityV1,
    native_layer_rule: ProviderNativeLayerRuleV1,
    byte_graph: NativeByteGraphV1,
    pages: tuple[PageReceiptV1, ...],
    retries: tuple[RetryReceiptV1, ...],
    observed_objects: tuple[ObservedObjectV1, ...],
    expected_inventory_hash: SHA256Hash,
    reconciliation_hash: SHA256Hash,
    execution: AcquisitionExecutionContextV1,
    schema_evidence_hashes: tuple[SHA256Hash, ...] = (),
    methodology_evidence_hashes: tuple[SHA256Hash, ...] = (),
    license_evidence_hashes: tuple[SHA256Hash, ...] = (),
) -> AcquisitionReceiptV1:
    """Validate timing, secret screening, and build an AcquisitionReceiptV1."""
    if plan.frozen_at > request.request_start:
        raise ValueError("acquisition plan frozen_at must precede request_start")

    validate_secret_free_acquisition_payload(request)
    validate_secret_free_acquisition_payload(execution)
    validate_secret_free_acquisition_payload(pages)
    validate_secret_free_acquisition_payload(retries)
    validate_secret_free_acquisition_payload(observed_objects)

    return AcquisitionReceiptV1(
        receipt_id=execution.receipt_id,
        receipt_version=execution.receipt_version,
        created_at=execution.creation_time,
        acquisition_plan_hash=content_hash(plan),
        authorization_hash=authorization_hash,
        profile_set_hash=profile_set_hash,
        request=request,
        native_layer_rule=native_layer_rule,
        byte_graph=byte_graph,
        byte_graph_hash=content_hash(byte_graph),
        pages=pages,
        retries=retries,
        observed_objects=observed_objects,
        expected_inventory_hash=expected_inventory_hash,
        reconciliation_hash=reconciliation_hash,
        schema_evidence_hashes=schema_evidence_hashes,
        methodology_evidence_hashes=methodology_evidence_hashes,
        license_evidence_hashes=license_evidence_hashes,
        collector_source_hash=execution.collector_source_hash,
        collector_version=execution.collector_version,
    )


def verify_acquisition_receipt(
    receipt: AcquisitionReceiptV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None:
    """Verify receipt byte graph self-consistency and retained artifact integrity."""
    if receipt.byte_graph_hash != content_hash(receipt.byte_graph):
        raise ValueError(
            "receipt byte graph hash does not match computed graph content"
        )

    for obj in receipt.byte_graph.objects:
        artifact = artifacts.get(obj.content_hash)
        if artifact is None:
            raise ValueError(f"missing artifact for content hash {obj.content_hash}")
        if artifact.byte_size != obj.byte_size:
            raise ValueError(
                f"artifact byte size mismatch for {obj.content_hash}: "
                f"expected {obj.byte_size}, got {artifact.byte_size}"
            )
        computed_hash = sha256(artifact.data).hexdigest()
        if (
            computed_hash != obj.content_hash
            or artifact.content_hash != obj.content_hash
        ):
            raise ValueError(
                f"artifact hash mismatch for {obj.content_hash}: "
                f"computed {computed_hash}"
            )
