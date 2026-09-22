"""Proof-bearing provenance binding a replay context to a qualified snapshot.

`EvaluationInputBundleV1.source_snapshot_hash` is a self-declaration. Adversarial
review proved that views can be materialized through genuine M1d replay over a
resolution context entirely unrelated to the qualified snapshot whose hash the
bundle asserts, and the promotion gate would still admit it. Replay-boundness
was proven; provenance was not.

This module closes that gap with the chain ruled in issue 31 and frozen in
issue 34:

    qualified source snapshot
        -> verified replay context identity
        -> verified component/bundle provenance proof
        -> promotion admission

Two properties keep it honest. First, binding is total rather than sampled:
every artifact a resolution context supplies must appear exactly once in the
containment witness, and every witness entry must resolve to a real replay
input entry of the snapshot. Second, the bundle gains nothing. The proof
references the bundle and never the reverse, so the hash graph stays acyclic
and the bundle stays lane-independent.
"""

from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import FrozenModel, SHA256Hash
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.serialization.canonical import content_hash

BUNDLE_PROVENANCE_PROOF_VERSION = "m2-bundle-provenance-v1"
"""Pinned schema/version tag the promotion gate validates against."""


def _sorted_unique_hashes(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


def replay_context_identity_hash(identity: ReplayContextIdentityV1) -> SHA256Hash:
    """Compute the self-excluding canonical hash for a replay context identity."""
    dump = identity.model_dump(mode="python")
    dump.pop("identity_hash", None)
    return content_hash(dump)


def snapshot_binding_witness_hash(
    witness: tuple[SnapshotBindingEntryV1, ...],
) -> SHA256Hash:
    """Compute the canonical digest over a containment witness.

    The witness is sorted before hashing, so witness order is not part of the
    binding identity and a reordered witness keeps the same proof hash.
    """
    ordered = sorted(witness, key=lambda entry: entry.artifact_hash)
    return content_hash([entry.model_dump(mode="python") for entry in ordered])


def qualified_replay_context_hash(qualified: QualifiedReplayContextV1) -> SHA256Hash:
    """Compute the self-excluding canonical hash for a qualified replay context."""
    dump = qualified.model_dump(mode="python")
    dump.pop("qualified_hash", None)
    return content_hash(dump)


def bundle_provenance_proof_hash(proof: BundleProvenanceProofV1) -> SHA256Hash:
    """Compute the self-excluding canonical hash for a bundle provenance proof."""
    dump = proof.model_dump(mode="python")
    dump.pop("proof_hash", None)
    return content_hash(dump)


class ReplayContextIdentityV1(FrozenModel):
    """Deterministic identity of one M1d resolution context.

    The preimage is the exact content hashes of everything the context supplies.
    `M1dResolutionContext` itself is never modified: identity is derived from it
    by a pure function, which keeps this contract additive across every existing
    construction site.
    """

    schema_version: Literal["1"] = "1"
    observation_dataset_hashes: tuple[SHA256Hash, ...] = ()
    session_dataset_hashes: tuple[SHA256Hash, ...] = ()
    availability_policy_hashes: tuple[SHA256Hash, ...] = ()
    retained_evidence_hashes: tuple[SHA256Hash, ...] = ()
    supporting_artifact_hashes: tuple[SHA256Hash, ...] = ()
    m1b_context_hash: SHA256Hash | None = None
    m1c_context_hash: SHA256Hash | None = None
    identity_hash: SHA256Hash

    @field_validator(
        "observation_dataset_hashes",
        "session_dataset_hashes",
        "availability_policy_hashes",
        "retained_evidence_hashes",
        "supporting_artifact_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(values, label="replay context identity hashes")

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = replay_context_identity_hash(self)
        if self.identity_hash != expected:
            raise ValueError(
                f"identity_hash mismatch: expected {expected}, got {self.identity_hash}"
            )
        return self


def context_supplied_artifact_hashes(
    identity: ReplayContextIdentityV1,
) -> tuple[SHA256Hash, ...]:
    """Return every artifact hash the identified context supplies, sorted.

    This is the exact set the containment witness must cover. Verification is
    total, not sampled, so an artifact absent from the witness fails closed.
    """
    hashes = {
        *identity.observation_dataset_hashes,
        *identity.session_dataset_hashes,
        *identity.availability_policy_hashes,
        *identity.retained_evidence_hashes,
        *identity.supporting_artifact_hashes,
    }
    if identity.m1b_context_hash is not None:
        hashes.add(identity.m1b_context_hash)
    if identity.m1c_context_hash is not None:
        hashes.add(identity.m1c_context_hash)
    return tuple(sorted(hashes))


class SnapshotBindingEntryV1(FrozenModel):
    """One containment witness entry: a context artifact and the snapshot entry
    that attests it.
    """

    schema_version: Literal["1"] = "1"
    artifact_hash: SHA256Hash
    snapshot_entry_hash: SHA256Hash


class QualifiedReplayContextV1(FrozenModel):
    """A replay context identity bound to a qualified source snapshot.

    The binding is checked, not asserted. The witness is retained in full rather
    than reduced to a digest, so promotion provenance stays independently
    auditable without needing the original snapshot at audit time, matching how
    M1e already retains evidence hashes rather than only conclusions.

    An unqualified context remains perfectly constructible. Exploratory work
    simply has no `QualifiedReplayContextV1`; this wrapper is required only
    where a promotion-grade claim is made.
    """

    schema_version: Literal["1"] = "1"
    source_snapshot_hash: SHA256Hash
    context_identity: ReplayContextIdentityV1
    snapshot_binding_witness: tuple[SnapshotBindingEntryV1, ...]
    snapshot_binding_proof_hash: SHA256Hash
    qualified_hash: SHA256Hash

    @field_validator("snapshot_binding_witness")
    @classmethod
    def canonicalize_witness(
        cls, witness: tuple[SnapshotBindingEntryV1, ...]
    ) -> tuple[SnapshotBindingEntryV1, ...]:
        artifacts = tuple(entry.artifact_hash for entry in witness)
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("snapshot binding witness must be unique by artifact_hash")
        return tuple(sorted(witness, key=lambda entry: entry.artifact_hash))

    @model_validator(mode="after")
    def validate_qualified_context(self) -> Self:
        if not self.snapshot_binding_witness:
            raise ValueError(
                "a qualified replay context requires a nonempty binding witness"
            )
        expected_artifacts = context_supplied_artifact_hashes(self.context_identity)
        witnessed = tuple(
            entry.artifact_hash for entry in self.snapshot_binding_witness
        )
        if witnessed != expected_artifacts:
            raise ValueError(
                "snapshot binding witness must cover every context artifact exactly "
                f"once: expected {len(expected_artifacts)} artifacts, "
                f"witness carries {len(witnessed)}"
            )
        expected_proof = snapshot_binding_witness_hash(self.snapshot_binding_witness)
        if self.snapshot_binding_proof_hash != expected_proof:
            raise ValueError(
                f"snapshot_binding_proof_hash mismatch: expected {expected_proof}, "
                f"got {self.snapshot_binding_proof_hash}"
            )
        expected = qualified_replay_context_hash(self)
        if self.qualified_hash != expected:
            raise ValueError(
                f"qualified_hash mismatch: expected {expected}, "
                f"got {self.qualified_hash}"
            )
        return self


class BundleProvenanceProofV1(FrozenModel):
    """Deterministic, versioned proof that one bundle came from one snapshot.

    Minting runs the expensive replay verification once. The promotion gate then
    validates this artifact cheaply and fail-closed, so trust never depends on a
    caller remembering to invoke a separate verifier.
    """

    schema_version: Literal["1"] = "1"
    proof_version: Literal["m2-bundle-provenance-v1"] = "m2-bundle-provenance-v1"
    qualified_context_hash: SHA256Hash
    source_snapshot_hash: SHA256Hash
    decision_request_hashes: tuple[SHA256Hash, ...] = ()
    accounting_request_hashes: tuple[SHA256Hash, ...] = ()
    component_hashes: tuple[SHA256Hash, ...]
    bundle_hash: SHA256Hash
    proof_hash: SHA256Hash

    @field_validator(
        "decision_request_hashes",
        "accounting_request_hashes",
        "component_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(values, label="provenance proof hashes")

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if not self.component_hashes:
            raise ValueError("provenance proof requires at least one component hash")
        expected = bundle_provenance_proof_hash(self)
        if self.proof_hash != expected:
            raise ValueError(
                f"proof_hash mismatch: expected {expected}, got {self.proof_hash}"
            )
        return self


def bind_context_identity_to_snapshot(
    *,
    identity: ReplayContextIdentityV1,
    snapshot: RealSourceSnapshotV1,
) -> QualifiedReplayContextV1:
    """Prove containment of every context artifact in a real source snapshot.

    Verification is total. Each artifact the context supplies must resolve to
    exactly one replay input entry of the snapshot, and the resulting witness
    records that mapping so it can be re-audited later.
    """
    artifacts = context_supplied_artifact_hashes(identity)
    if not artifacts:
        raise ValueError(
            "replay context supplies no artifacts, so no binding can be proven"
        )

    entries_by_content: dict[str, list[SHA256Hash]] = {}
    for entry in snapshot.replay_inputs:
        entries_by_content.setdefault(entry.content_hash, []).append(
            content_hash(entry)
        )

    witness: list[SnapshotBindingEntryV1] = []
    for artifact_hash in artifacts:
        matches = entries_by_content.get(artifact_hash, [])
        if not matches:
            raise ValueError(
                f"replay context artifact {artifact_hash} is absent from source "
                f"snapshot {snapshot.snapshot_hash}"
            )
        if len(matches) != 1:
            raise ValueError(
                f"replay context artifact {artifact_hash} is ambiguous in source "
                f"snapshot {snapshot.snapshot_hash}"
            )
        witness.append(
            SnapshotBindingEntryV1(
                schema_version="1",
                artifact_hash=artifact_hash,
                snapshot_entry_hash=matches[0],
            )
        )

    ordered = tuple(sorted(witness, key=lambda entry: entry.artifact_hash))
    draft = QualifiedReplayContextV1.model_construct(
        schema_version="1",
        source_snapshot_hash=snapshot.snapshot_hash,
        context_identity=identity,
        snapshot_binding_witness=ordered,
        snapshot_binding_proof_hash=snapshot_binding_witness_hash(ordered),
        qualified_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"qualified_hash": qualified_replay_context_hash(draft)}
    )
    return QualifiedReplayContextV1.model_validate(candidate.model_dump())


def verify_snapshot_binding(
    *,
    qualified: QualifiedReplayContextV1,
    snapshot: RealSourceSnapshotV1,
) -> None:
    """Re-audit a retained containment witness against the original snapshot.

    Fails closed when the witness does not cover the context, when the recorded
    binding digest is stale, when a witness entry names a snapshot entry that
    does not exist, or when the named entry attests a different artifact.
    """
    if qualified.source_snapshot_hash != snapshot.snapshot_hash:
        raise ValueError(
            "qualified replay context snapshot hash mismatch: bound to "
            f"{qualified.source_snapshot_hash}, verified against "
            f"{snapshot.snapshot_hash}"
        )

    expected_artifacts = context_supplied_artifact_hashes(qualified.context_identity)
    witnessed = tuple(
        entry.artifact_hash for entry in qualified.snapshot_binding_witness
    )
    if tuple(sorted(witnessed)) != expected_artifacts:
        raise ValueError(
            "snapshot binding witness must cover every context artifact exactly once"
        )

    expected_proof = snapshot_binding_witness_hash(qualified.snapshot_binding_witness)
    if qualified.snapshot_binding_proof_hash != expected_proof:
        raise ValueError(
            f"snapshot_binding_proof_hash mismatch: expected {expected_proof}, "
            f"got {qualified.snapshot_binding_proof_hash}"
        )

    entries_by_identity = {
        content_hash(entry): entry for entry in snapshot.replay_inputs
    }
    for entry in qualified.snapshot_binding_witness:
        resolved = entries_by_identity.get(entry.snapshot_entry_hash)
        if resolved is None:
            raise ValueError(
                f"witness entry {entry.snapshot_entry_hash} does not resolve to a "
                f"snapshot entry of {snapshot.snapshot_hash}"
            )
        if resolved.content_hash != entry.artifact_hash:
            raise ValueError(
                f"witness entry {entry.snapshot_entry_hash} does not attest artifact "
                f"{entry.artifact_hash}"
            )


def bundle_component_hashes(bundle: EvaluationInputBundleV1) -> tuple[SHA256Hash, ...]:
    """Return the exact hashes of every authority-bearing bundle component.

    Covers all six classes named in the issue 31 Decision 4 ruling: decision
    views, accounting views, structural eligibility, economic outcomes, security
    and listing identity, and session-clock authority.
    """
    members: tuple[object, ...] = (
        bundle.session_clock,
        *bundle.security_identities,
        *bundle.listing_identities,
        *bundle.structural_eligibilities,
        *bundle.economic_outcomes,
        *bundle.authentic_decision_views,
        *bundle.authentic_accounting_views,
    )
    return tuple(sorted({content_hash(member) for member in members}))


def _build_bundle_provenance_proof(
    *,
    qualified_context_hash: SHA256Hash,
    source_snapshot_hash: SHA256Hash,
    bundle: EvaluationInputBundleV1,
    decision_request_hashes: tuple[SHA256Hash, ...] = (),
    accounting_request_hashes: tuple[SHA256Hash, ...] = (),
) -> BundleProvenanceProofV1:
    """Assemble a provenance proof over an already-verified bundle.

    Module-private on purpose. This is pure assembly: it accepts any 64-hex
    `qualified_context_hash` and verifies nothing, so an exported version is a
    minting oracle for proofs over contexts that were never qualified. The only
    sanctioned way in is `mint_bundle_provenance_proof`, which runs the
    expensive check first, and the leading underscore is what enforces that at
    the module boundary rather than in a docstring.
    """
    draft = BundleProvenanceProofV1.model_construct(
        schema_version="1",
        proof_version=BUNDLE_PROVENANCE_PROOF_VERSION,
        qualified_context_hash=qualified_context_hash,
        source_snapshot_hash=source_snapshot_hash,
        decision_request_hashes=tuple(sorted(set(decision_request_hashes))),
        accounting_request_hashes=tuple(sorted(set(accounting_request_hashes))),
        component_hashes=bundle_component_hashes(bundle),
        bundle_hash=bundle.bundle_hash,
        proof_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"proof_hash": bundle_provenance_proof_hash(draft)}
    )
    return BundleProvenanceProofV1.model_validate(candidate.model_dump())


def validate_bundle_component_coverage(
    *,
    proof: BundleProvenanceProofV1,
    bundle: EvaluationInputBundleV1,
) -> None:
    """Require the proof to cover exactly the bundle's authority-bearing members.

    A bundle member absent from the proof fails closed rather than passing
    unverified, and a proof naming a component the bundle does not carry fails
    closed too.
    """
    expected = bundle_component_hashes(bundle)
    if proof.component_hashes != expected:
        missing = tuple(
            item for item in expected if item not in set(proof.component_hashes)
        )
        declared = set(expected)
        extra = tuple(item for item in proof.component_hashes if item not in declared)
        raise ValueError(
            "provenance proof component coverage mismatch: "
            f"missing {missing}, unexpected {extra}"
        )
