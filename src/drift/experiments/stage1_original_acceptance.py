"""Concrete host-configured original study evidence verifier.

Checks original issuer, signed/host-appointed trust root, exact receipt bytes,
scope, protocol fingerprint, and reviewer independence.
Fails closed: outages or unaccepted states return False.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    EvidenceRole,
    OriginalStudyEvidenceVerifier,
    StudyEvidenceReferenceV1,
)
from drift.serialization.canonical import canonical_json, content_hash


class OriginalReceiptPayloadV1(FrozenModel):
    role: EvidenceRole
    receipt_id: NonBlankStr
    protocol_hash: SHA256Hash
    authority_id: NonBlankStr
    status: NonBlankStr
    receipt_hash: SHA256Hash
    accepted_at: str | None = None
    assessor_independence: bool = True
    independence_declaration: str | None = None
    signature: str | None = None


def create_original_study_evidence_receipt(
    *,
    role: EvidenceRole,
    receipt_id: str,
    protocol_hash: str,
    authority_id: str,
    accepted_at: datetime,
    status: str = "ACCEPTED",
    assessor_independence: bool = True,
    independence_declaration: str = (
        "Independent assessment conducted under G3 protocol requirements."
    ),
    signature: str | None = None,
    hmac_key: str | bytes | None = None,
) -> tuple[dict[str, Any], str]:
    iso_time = (
        accepted_at.isoformat()
        if accepted_at.tzinfo
        else accepted_at.replace(tzinfo=UTC).isoformat()
    )
    raw: dict[str, Any] = {
        "role": role,
        "receipt_id": receipt_id,
        "protocol_hash": protocol_hash,
        "authority_id": authority_id,
        "status": status,
        "accepted_at": iso_time,
        "assessor_independence": assessor_independence,
        "independence_declaration": independence_declaration,
    }
    if hmac_key is not None:
        raw_bytes = canonical_json(raw)
        key_bytes = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
        sig = hmac.new(key_bytes, raw_bytes, hashlib.sha256).hexdigest()
        raw["signature"] = sig
    elif signature is not None:
        raw["signature"] = signature
    h = content_hash(raw)
    return raw, h


class ProductionStudyEvidenceVerifier(OriginalStudyEvidenceVerifier):
    """Production verifier backed by host trust roots and issuer auth."""

    def __init__(
        self,
        *,
        trust_roots: Mapping[EvidenceRole, set[str] | Mapping[str, Any]],
        receipt_resolver: Callable[[str], bytes | str | dict[str, Any]],
        authenticated_issuers: Mapping[str, Any] | None = None,
        receipt_authenticator: Callable[[dict[str, Any]], bool] | None = None,
        authenticated_receipt_hashes: set[str] | None = None,
    ) -> None:
        self._trust_roots: dict[EvidenceRole, set[str]] = {}
        issuer_creds: dict[str, Any] = dict(authenticated_issuers or {})
        for role, roots in trust_roots.items():
            if isinstance(roots, Mapping):
                self._trust_roots[role] = set(roots.keys())
                for auth_id, creds in roots.items():
                    if auth_id not in issuer_creds:
                        issuer_creds[auth_id] = creds
            else:
                self._trust_roots[role] = set(roots)
        self._resolver = receipt_resolver
        self._authenticated_issuers = issuer_creds
        self._receipt_authenticator = receipt_authenticator
        self._authenticated_receipt_hashes = (
            set(authenticated_receipt_hashes)
            if authenticated_receipt_hashes is not None
            else None
        )

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

            # 1. Exact identity check: receipt_id must match reference
            if payload.get("receipt_id") != reference.receipt_id:
                return False

            # 2. Content hash matches receipt_hash
            actual_hash = content_hash(payload)
            if actual_hash != reference.receipt_hash:
                return False

            # 3. Protocol hash matches
            if payload.get("protocol_hash") != reference.protocol_hash:
                return False

            # 4. Role matches
            if payload.get("role") != reference.role:
                return False

            # 5. Authority is in configured trust roots for this role
            authority = payload.get("authority_id")
            if not authority or authority not in allowed_authorities:
                return False

            # 6. Acceptance status
            if payload.get("status") != "ACCEPTED":
                return False

            # 7. Original acceptance time verification
            raw_accepted = payload.get("accepted_at")
            if not raw_accepted:
                return False
            if isinstance(raw_accepted, str):
                try:
                    p_time = datetime.fromisoformat(raw_accepted)
                except Exception:
                    return False
            elif isinstance(raw_accepted, datetime):
                p_time = raw_accepted
            else:
                return False
            if p_time.tzinfo is None:
                p_time = p_time.replace(tzinfo=UTC)
            ref_time = reference.accepted_at
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=UTC)
            if p_time != ref_time:
                return False

            # 8. Assessor independence check
            if (
                payload.get("assessor_independence") is False
                or payload.get("independent_assessor") is False
            ):
                return False
            is_indep = (
                payload.get("assessor_independence") is True
                or payload.get("independent_assessor") is True
                or bool(payload.get("independence_declaration"))
            )
            if not is_indep:
                return False
            if (
                payload.get("is_self_review") is True
                or payload.get("conflicted") is True
            ):
                return False

            # 9. Issuer authentication verification
            sig = (
                payload.get("signature")
                or payload.get("receipt_signature")
                or payload.get("token")
                or payload.get("hmac")
            )
            authenticated = False

            if self._authenticated_receipt_hashes is not None:
                if actual_hash in self._authenticated_receipt_hashes:
                    authenticated = True
                else:
                    return False

            if self._receipt_authenticator is not None:
                if self._receipt_authenticator(payload):
                    authenticated = True
                else:
                    return False

            if self._authenticated_issuers and authority in self._authenticated_issuers:
                creds = self._authenticated_issuers[authority]
                unsigned = {
                    k: v
                    for k, v in payload.items()
                    if k not in ("signature", "receipt_signature", "token", "hmac")
                }
                canonical_bytes = canonical_json(unsigned)
                unsigned_hash = content_hash(unsigned)

                if callable(creds):
                    if creds(payload):
                        authenticated = True
                    else:
                        return False
                elif isinstance(creds, dict):
                    has_key = (
                        creds.get("hmac_key")
                        or creds.get("secret")
                        or creds.get("secret_key")
                    )
                    verifier_fn = creds.get("signature_verifier") or creds.get(
                        "authenticator"
                    )
                    signed_hashes = creds.get("signed_hashes") or creds.get(
                        "authenticated_hashes"
                    )

                    if has_key:
                        key_val = (
                            creds.get("hmac_key")
                            or creds.get("secret")
                            or creds.get("secret_key")
                        )
                        if isinstance(key_val, str):
                            k_b = key_val.encode("utf-8")
                        elif isinstance(key_val, (bytes, bytearray)):
                            k_b = bytes(key_val)
                        else:
                            return False
                        expected_sig = hmac.new(
                            k_b, canonical_bytes, hashlib.sha256
                        ).hexdigest()
                        if sig and hmac.compare_digest(sig, expected_sig):
                            authenticated = True
                        else:
                            return False
                    elif callable(verifier_fn):
                        if sig and verifier_fn(canonical_bytes, sig):
                            authenticated = True
                        else:
                            return False
                    elif signed_hashes is not None:
                        s_hashes = set(signed_hashes)
                        if (
                            (actual_hash in s_hashes)
                            or (unsigned_hash in s_hashes)
                            or (sig and sig in s_hashes)
                        ):
                            authenticated = True
                        else:
                            return False
                    else:
                        return False

            # Unsigned receipt with no effective authentication must fail closed
            if not authenticated:
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

        resolved_artifacts: dict[str, dict[str, Any]] = {}
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
            if not isinstance(art_obj, dict):
                return False, f"ARTIFACT_NOT_DICT:{art_name}", None
            if content_hash(art_obj) != art_hash:
                return False, f"ARTIFACT_CONTENT_HASH_MISMATCH:{art_name}", None

            # Mandatory freeze and session bindings
            if art_obj.get("freeze_hash") != expected_freeze_hash:
                return False, f"ARTIFACT_BOUND_FREEZE_MISMATCH:{art_name}", None
            if art_obj.get("session_index") != expected_session_index:
                return False, f"ARTIFACT_BOUND_SESSION_MISMATCH:{art_name}", None

            # Mandatory artifact role / type
            a_type = art_obj.get("artifact_type") or art_obj.get("artifact_role")
            if not a_type or str(a_type).lower() != art_name.lower():
                return False, f"ARTIFACT_ROLE_MISMATCH:{art_name}", None

            # Mandatory authority check
            a_auth = art_obj.get("authority_id") or art_obj.get("producer_id")
            if not a_auth or a_auth not in self._trust_roots:
                return False, f"ARTIFACT_UNTRUSTED_AUTHORITY:{art_name}:{a_auth}", None

            resolved_artifacts[art_name.lower()] = art_obj

        # Typed validation for execution artifacts
        p_state = resolved_artifacts.get("portfolio_state")
        if not p_state:
            return False, "MISSING_PORTFOLIO_STATE_ARTIFACT", None
        if "nav" not in p_state or "cash" not in p_state:
            return False, "PORTFOLIO_STATE_MISSING_NAV_OR_CASH", None
        try:
            p_nav = Decimal(str(p_state["nav"]))
            p_cash = Decimal(str(p_state["cash"]))
            if not (p_nav.is_finite() and p_cash.is_finite()):
                return False, "PORTFOLIO_STATE_NAV_OR_CASH_NOT_FINITE", None
        except Exception:
            return False, "PORTFOLIO_STATE_NAV_OR_CASH_NOT_NUMERIC", None
        positions = p_state.get("positions")
        if positions is None or not isinstance(positions, (dict, list, tuple)):
            return False, "PORTFOLIO_STATE_INVALID_POSITIONS", None

        decision_art = resolved_artifacts.get("decision")
        if not decision_art:
            return False, "MISSING_DECISION_ARTIFACT", None
        strat = decision_art.get("strategy_id") or decision_art.get("selected_strategy")
        action = (
            decision_art.get("action")
            or decision_art.get("weights")
            or decision_art.get("selected_weights")
        )
        if (
            not strat
            or not isinstance(strat, str)
            or action is None
            or not isinstance(action, dict)
        ):
            return False, "DECISION_ARTIFACT_INVALID_SCHEMA", None

        fills_art = resolved_artifacts.get("fills")
        if not fills_art:
            return False, "MISSING_FILLS_ARTIFACT", None
        trades = (
            fills_art.get("fills") if "fills" in fills_art else fills_art.get("trades")
        )
        if trades is None or not isinstance(trades, (list, tuple)):
            return False, "FILLS_ARTIFACT_INVALID_SCHEMA", None
        for trade in trades:
            if not isinstance(trade, dict):
                return False, "FILLS_RECORD_MUST_BE_OBJECT_NOT_STRING", None

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

        # Reconcile reported metrics with portfolio evidence
        if "terminal_nav" in metrics:
            m_nav = Decimal(str(metrics["terminal_nav"]))
            if m_nav != p_nav:
                return (
                    False,
                    (
                        "METRIC_RECONCILIATION_FAILED: reported terminal_nav "
                        f"{m_nav} != portfolio_state nav {p_nav}"
                    ),
                    None,
                )

        return True, "OK", payload


def create_historical_execution_artifact(
    *,
    artifact_type: str,
    freeze_hash: str,
    session_index: int,
    authority_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    art: dict[str, Any] = {
        "schema_version": "drift-stage1-historical-artifact/1",
        "artifact_type": artifact_type,
        "freeze_hash": freeze_hash,
        "session_index": session_index,
        "authority_id": authority_id,
        **payload,
    }
    h = content_hash(art)
    return art, h


def create_historical_execution_receipt(
    *,
    receipt_id: str,
    freeze_hash: str,
    session_index: int,
    authority_id: str,
    status: str = "COMPLETED",
    execution_journal: dict[str, Any],
    artifacts: dict[str, str],
    metrics: dict[str, Any],
    **extra: Any,
) -> tuple[dict[str, Any], str]:
    rcpt: dict[str, Any] = {
        "schema_version": "drift-stage1-execution-receipt/1",
        "receipt_id": receipt_id,
        "freeze_hash": freeze_hash,
        "session_index": session_index,
        "authority_id": authority_id,
        "status": status,
        "execution_journal": execution_journal,
        "artifacts": artifacts,
        "metrics": metrics,
        **extra,
    }
    h = content_hash(rcpt)
    return {**rcpt, "receipt_hash": h}, h
