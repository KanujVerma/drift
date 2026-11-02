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
