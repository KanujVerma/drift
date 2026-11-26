"""Retained point-in-time evidence identities must have real source closures."""

from collections.abc import Callable

import pytest

from drift.domain.semantic_attestation import (
    SemanticAttestationV1,
    m1c_corporate_action_coverage_attestation,
    m1c_evidence_attestation,
    m1c_validation_attestation,
    m1d_evidence_attestation,
    m1d_semantic_attestation,
)


@pytest.mark.parametrize(
    "build",
    [
        m1d_semantic_attestation,
        m1d_evidence_attestation,
        m1c_validation_attestation,
        m1c_evidence_attestation,
        m1c_corporate_action_coverage_attestation,
    ],
)
def test_retained_attestation_builds_from_declared_sources(
    build: Callable[[], SemanticAttestationV1],
) -> None:
    attestation = build()
    assert attestation.declared_modules
    assert len(attestation.attestation_hash) == 64
    assert tuple(item.module for item in attestation.module_digests) == (
        attestation.declared_modules
    )
