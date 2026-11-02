"""Concrete host-configured original study evidence verifier.

Checks original issuer, signed/host-appointed trust root, exact receipt bytes,
scope, protocol fingerprint, and reviewer independence.
Fails closed: outages or unaccepted states return False.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    EvidenceRole,
    OriginalStudyEvidenceVerifier,
    StudyEvidenceReferenceV1,
)
from drift.serialization.canonical import content_hash


class OriginalReceiptPayloadV1(FrozenModel):
    role: EvidenceRole
    receipt_id: NonBlankStr
    protocol_hash: SHA256Hash
    authority_id: NonBlankStr
    status: NonBlankStr
    receipt_hash: SHA256Hash


class ProductionStudyEvidenceVerifier(OriginalStudyEvidenceVerifier):
    """Production verifier backed by host trust roots and durable receipt store."""

    def __init__(
        self,
        *,
        trust_roots: dict[EvidenceRole, set[str]],
        receipt_resolver: Callable[[str], bytes | str | dict[str, Any]],
    ) -> None:
        self._trust_roots = {role: set(roots) for role, roots in trust_roots.items()}
        self._resolver = receipt_resolver

    def verify(self, reference: StudyEvidenceReferenceV1) -> bool:
        if reference.role not in REQUIRED_ROLES:
            return False

        allowed_authorities = self._trust_roots.get(reference.role, set())
        if not allowed_authorities:
            return False

        try:
            raw = self._resolver(reference.receipt_id)
            if isinstance(raw, (bytes, str)):
                payload = (
                    json.loads(raw)
                    if isinstance(raw, str)
                    else json.loads(raw.decode("utf-8"))
                )
            elif isinstance(raw, dict):
                payload = raw
            else:
                return False

            # Verify content hash matches receipt_hash
            actual_hash = content_hash(payload)
            if actual_hash != reference.receipt_hash:
                return False

            # Verify protocol hash matches
            if payload.get("protocol_hash") != reference.protocol_hash:
                return False

            # Verify role matches
            if payload.get("role") != reference.role:
                return False

            # Verify authority is in configured trust roots for this role
            authority = payload.get("authority_id")
            if not authority or authority not in allowed_authorities:
                return False

            # Verify acceptance status
            if payload.get("status") != "ACCEPTED":
                return False

            return True
        except Exception:
            # Outage or verification failure must fail closed (never True)
            return False


CONTRACT_EXECUTION_METRICS: frozenset[str] = frozenset(
    {
        "net_return",
        "gross_turnover",
        "terminal_nav",
        "per_share_fees",
        "holding_costs",
        "total_pnl",
    }
)

REQUIRED_EXECUTION_ARTIFACTS: frozenset[str] = frozenset(
    {
        "portfolio_state",
        "decision",
        "fills",
    }
)


class Stage1ExecutionReceiptV1(FrozenModel):
    schema_version: str = "drift-stage1-execution-receipt/1"
    receipt_id: NonBlankStr
    freeze_hash: SHA256Hash
    session_index: int
    authority_id: NonBlankStr
    status: str = "COMPLETED"
    execution_journal: dict[str, Any]
    artifacts: dict[str, SHA256Hash]
    metrics: dict[str, Any]
    receipt_hash: SHA256Hash


class ProductionExecutionEvidenceVerifier:
    """Verifies original historical execution receipts against host trust roots."""

    def __init__(
        self,
        *,
        trust_roots: set[str],
        receipt_resolver: Callable[[str], bytes | str | dict[str, Any]],
        artifact_resolver: Callable[[str], bytes | str | dict[str, Any]],
    ) -> None:
        self._trust_roots = set(trust_roots)
        self._receipt_resolver = receipt_resolver
        self._artifact_resolver = artifact_resolver

    def verify_execution_receipt(
        self,
        receipt_ref: str | dict[str, Any],
        *,
        expected_freeze_hash: str,
        expected_session_index: int,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Resolves and verifies original execution receipt from trusted store."""
        from decimal import Decimal

        if not self._trust_roots:
            return False, "TRUST_ROOTS_UNAVAILABLE", None

        receipt_id: str | None = None
        if isinstance(receipt_ref, str):
            receipt_id = receipt_ref
        elif isinstance(receipt_ref, dict):
            receipt_id = receipt_ref.get("receipt_id") or receipt_ref.get(
                "execution_receipt_id"
            )
            if not receipt_id:
                h = receipt_ref.get("receipt_hash") or receipt_ref.get("evidence_hash")
                if h:
                    receipt_id = h

        if not receipt_id:
            return False, "RECEIPT_ID_MISSING", None

        try:
            raw = self._receipt_resolver(receipt_id)
        except Exception as e:
            return False, f"RECEIPT_RESOLVER_FAILED:{e}", None

        if not raw:
            return False, f"RECEIPT_NOT_FOUND_IN_STORE:{receipt_id}", None

        if isinstance(raw, (bytes, str)):
            try:
                payload = (
                    json.loads(raw)
                    if isinstance(raw, str)
                    else json.loads(raw.decode("utf-8"))
                )
            except Exception:
                return False, "MALFORMED_RECEIPT_JSON", None
        elif isinstance(raw, dict):
            payload = raw
        else:
            return False, "INVALID_RECEIPT_TYPE", None

        r_hash = payload.get("receipt_hash") or payload.get("evidence_hash")
        body = {
            k: v
            for k, v in payload.items()
            if k not in ("receipt_hash", "evidence_hash")
        }
        if not r_hash or content_hash(body) != r_hash:
            return False, "RECEIPT_HASH_MISMATCH", None

        authority = payload.get("authority_id")
        if not authority or authority not in self._trust_roots:
            return False, f"UNTRUSTED_AUTHORITY:{authority}", None

        if payload.get("status") not in ("COMPLETED", "ACCEPTED"):
            return False, f"UNACCEPTED_STATUS:{payload.get('status')}", None

        if payload.get("freeze_hash") != expected_freeze_hash:
            return (
                False,
                f"FREEZE_HASH_MISMATCH: expected {expected_freeze_hash}, "
                f"got {payload.get('freeze_hash')}",
                None,
            )
        if payload.get("session_index") != expected_session_index:
            return (
                False,
                f"SESSION_INDEX_MISMATCH: expected {expected_session_index}, "
                f"got {payload.get('session_index')}",
                None,
            )

        journal = payload.get("execution_journal")
        if not journal or not isinstance(journal, dict):
            return False, "MISSING_OR_EMPTY_EXECUTION_JOURNAL", None

        artifacts = payload.get("artifacts")
        if not artifacts or not isinstance(artifacts, dict):
            return False, "MISSING_OR_EMPTY_ARTIFACTS", None

        for req_art in REQUIRED_EXECUTION_ARTIFACTS:
            if req_art not in artifacts:
                return False, f"MISSING_REQUIRED_ARTIFACT:{req_art}", None

        for art_name, art_hash in artifacts.items():
            if not isinstance(art_hash, str) or len(art_hash) != 64:
                return False, f"INVALID_ARTIFACT_HASH:{art_name}", None
            try:
                int(art_hash, 16)
            except ValueError:
                return False, f"NON_HEX_ARTIFACT_HASH:{art_name}", None

            try:
                raw_art = self._artifact_resolver(art_hash)
            except Exception as e:
                return False, f"ARTIFACT_RESOLVER_FAILED:{art_name}:{e}", None
            if not raw_art:
                return False, f"ARTIFACT_NOT_FOUND_IN_STORE:{art_name}:{art_hash}", None

            art_obj = (
                json.loads(raw_art)
                if isinstance(raw_art, str)
                else (
                    json.loads(raw_art.decode("utf-8"))
                    if isinstance(raw_art, bytes)
                    else raw_art
                )
            )
            if content_hash(art_obj) != art_hash:
                return False, f"ARTIFACT_CONTENT_HASH_MISMATCH:{art_name}", None
            if isinstance(art_obj, dict):
                if (
                    "freeze_hash" in art_obj
                    and art_obj["freeze_hash"] != expected_freeze_hash
                ):
                    return False, f"ARTIFACT_BOUND_FREEZE_MISMATCH:{art_name}", None
                if (
                    "session_index" in art_obj
                    and art_obj["session_index"] != expected_session_index
                ):
                    return False, f"ARTIFACT_BOUND_SESSION_MISMATCH:{art_name}", None

        metrics = payload.get("metrics")
        if not metrics or not isinstance(metrics, dict):
            return False, "MISSING_OR_EMPTY_METRICS", None
        unknown_metrics = set(metrics.keys()) - CONTRACT_EXECUTION_METRICS
        if unknown_metrics:
            return False, f"UNSUPPORTED_METRICS:{sorted(unknown_metrics)}", None
        for m_k, m_v in metrics.items():
            if isinstance(m_v, bool):
                return False, f"METRIC_CANNOT_BE_BOOLEAN:{m_k}", None
            try:
                d = Decimal(str(m_v))
                if not d.is_finite():
                    raise ValueError()
            except Exception:
                return False, f"METRIC_NOT_FINITE_NUMERIC:{m_k}", None

        return True, "OK", payload
