"""M2 proof-carrying evaluation input bundle and deterministic run identity."""

from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.securities import ListingV1, SecurityV1
from drift.domain.universes import StructuralEligibilityResultV1
from drift.serialization.canonical import content_hash


def evaluation_input_bundle_hash(bundle: EvaluationInputBundleV1) -> SHA256Hash:
    """Compute the self-excluding canonical content hash for a bundle."""
    dump = bundle.model_dump(mode="python")
    dump.pop("bundle_hash", None)
    return content_hash(dump)


def evaluation_run_identity_hash(identity: EvaluationRunIdentityV1) -> SHA256Hash:
    """Compute the self-excluding canonical content hash for a run identity."""
    dump = identity.model_dump(mode="python")
    dump.pop("run_identity_hash", None)
    return content_hash(dump)


def _canonicalize[T](members: tuple[T, ...], label: str) -> tuple[T, ...]:
    """Order members by exact content hash and reject duplicates."""
    paired = tuple((content_hash(member), member) for member in members)
    digests = tuple(digest for digest, _ in paired)
    if len(set(digests)) != len(digests):
        raise ValueError(f"{label} must not repeat an identical member")
    return tuple(member for _, member in sorted(paired, key=lambda pair: pair[0]))


class EvaluationInputBundleV1(FrozenModel):
    """Complete, proof-carrying input bundle for one evaluation interval.

    The bundle is immutable historical evidence and is deliberately independent
    of the lane under which it is evaluated. It carries no admission reference,
    so bundle hashing stays acyclic: an admission binds a bundle by hash, never
    the reverse.
    """

    schema_version: Literal["1"] = "1"
    evaluation_interval: TemporalIntervalClaimV1
    source_snapshot_hash: SHA256Hash | None = None
    session_clock: SessionClockV1
    security_identities: tuple[SecurityV1, ...]
    listing_identities: tuple[ListingV1, ...]
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...]
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...]
    authentic_decision_views: tuple[DerivedObservationViewV1, ...]
    authentic_accounting_views: tuple[DerivedObservationViewV1, ...]
    exploratory_reconstructed_observations: tuple[
        ExploratoryReconstructedSessionObservationV1, ...
    ] = ()
    # Limitations of the producer's dataset itself, which no evidence member
    # declares, such as a truncated corporate-action window (issue 92).
    dataset_limitations: tuple[NonBlankStr, ...] = ()
    bundle_hash: SHA256Hash

    @field_validator("security_identities")
    @classmethod
    def canonicalize_securities(
        cls, members: tuple[SecurityV1, ...]
    ) -> tuple[SecurityV1, ...]:
        return _canonicalize(members, "security identities")

    @field_validator("listing_identities")
    @classmethod
    def canonicalize_listings(
        cls, members: tuple[ListingV1, ...]
    ) -> tuple[ListingV1, ...]:
        return _canonicalize(members, "listing identities")

    @field_validator("structural_eligibilities")
    @classmethod
    def canonicalize_eligibilities(
        cls, members: tuple[StructuralEligibilityResultV1, ...]
    ) -> tuple[StructuralEligibilityResultV1, ...]:
        return _canonicalize(members, "structural eligibilities")

    @field_validator("economic_outcomes")
    @classmethod
    def canonicalize_economics(
        cls, members: tuple[EconomicOutcomeResolutionV1, ...]
    ) -> tuple[EconomicOutcomeResolutionV1, ...]:
        return _canonicalize(members, "economic outcomes")

    @field_validator("authentic_decision_views")
    @classmethod
    def canonicalize_decision_views(
        cls, members: tuple[DerivedObservationViewV1, ...]
    ) -> tuple[DerivedObservationViewV1, ...]:
        # An outcome-role view is ex-post information. Admitting one into the
        # decision bucket would be a lookahead channel, so bind role to bucket.
        for member in members:
            if member.role != "decision":
                raise ValueError(
                    "authentic decision views require decision-role evidence, "
                    f"got role {member.role}"
                )
        return _canonicalize(members, "authentic decision views")

    @field_validator("authentic_accounting_views")
    @classmethod
    def canonicalize_accounting_views(
        cls, members: tuple[DerivedObservationViewV1, ...]
    ) -> tuple[DerivedObservationViewV1, ...]:
        for member in members:
            if member.role != "outcome":
                raise ValueError(
                    "authentic accounting views require outcome-role evidence, "
                    f"got role {member.role}"
                )
            if member.basis_mode != "source_basis":
                raise ValueError(
                    "authentic accounting views require unadjusted source basis, "
                    f"got basis mode {member.basis_mode}"
                )
        return _canonicalize(members, "authentic accounting views")

    @field_validator("exploratory_reconstructed_observations")
    @classmethod
    def canonicalize_reconstructions(
        cls, members: tuple[ExploratoryReconstructedSessionObservationV1, ...]
    ) -> tuple[ExploratoryReconstructedSessionObservationV1, ...]:
        return _canonicalize(members, "exploratory reconstructions")

    @field_validator("dataset_limitations")
    @classmethod
    def canonicalize_dataset_limitations(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("bundle dataset limitations must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if not self.session_clock.sessions:
            raise ValueError("bundle requires a nonempty session clock")
        self._validate_session_coherence()
        expected = evaluation_input_bundle_hash(self)
        if self.bundle_hash != expected:
            raise ValueError(
                f"bundle hash mismatch: expected {expected}, got {self.bundle_hash}"
            )
        return self

    def _validate_session_coherence(self) -> None:
        """Bind every bundle member to the clock the bundle itself declares.

        Without this a bundle can carry evidence for sessions its own clock
        never contains, which lets evidence from one corpus ride into an
        evaluation authorized over a different one. Fail closed on any member
        outside the clock, and on a clock that escapes the declared interval.

        A split-normalization `anchor_session` is deliberately not required to
        be in the clock: it is a normalization reference point, not evidence
        the evaluation consumes over its own interval.
        """
        covered = {session.session_key for session in self.session_clock.sessions}
        for label, views in (
            ("decision", self.authentic_decision_views),
            ("accounting", self.authentic_accounting_views),
        ):
            for view in views:
                if view.source_session not in covered:
                    raise ValueError(
                        f"authentic {label} view binds session "
                        f"{view.source_session.mic} {view.source_session.local_date}, "
                        "which the bundle session clock does not contain"
                    )
        for observation in self.exploratory_reconstructed_observations:
            if observation.session_key not in covered:
                raise ValueError(
                    "exploratory reconstruction binds session "
                    f"{observation.session_key.mic} "
                    f"{observation.session_key.local_date}, "
                    "which the bundle session clock does not contain"
                )

        # Sessions are chronologically ordered by the clock's own validator.
        first = self.session_clock.sessions[0]
        last = self.session_clock.sessions[-1]
        start = self.evaluation_interval.start.lower_bound
        if start is not None and first.opened_at < start:
            raise ValueError(
                f"bundle session clock opens before its evaluation interval: "
                f"session opens {first.opened_at}, interval starts {start}"
            )
        end = self.evaluation_interval.end
        if end is not None and end.upper_bound is not None:
            if last.closed_at > end.upper_bound:
                raise ValueError(
                    f"bundle session clock closes after its evaluation interval: "
                    f"session closes {last.closed_at}, interval ends {end.upper_bound}"
                )

    @property
    def has_exploratory_reconstructions(self) -> bool:
        """Whether any exploratory reconstruction evidence backs this bundle."""
        return bool(self.exploratory_reconstructed_observations) or (
            self.session_clock.mode == "scheduled_session_reconstruction"
        )

    @property
    def required_limitations(self) -> tuple[str, ...]:
        """Every limitation this bundle obliges an admission to carry.

        That is every limitation its evidence carries and every limitation its
        producer declares of the dataset itself.
        """
        required = set(self.session_clock.acknowledged_limitations)
        required.update(self.dataset_limitations)
        for observation in self.exploratory_reconstructed_observations:
            required.update(observation.acknowledged_limitations)
        return tuple(sorted(required))


class EvaluationRunIdentityV1(FrozenModel):
    """Deterministic semantic identity of one evaluation run.

    Two runs share an identity exactly when strategy, protocol, costs, lane
    admission, input bundle, evaluator evidence, code version, and environment
    closure all match. The evaluator evidence (listing records, economic
    outcome records, interpretation registries, and exploratory cohort and
    replay) sits outside the bundle but changes results, so it is bound here
    (issue 86).
    """

    schema_version: Literal["1"] = "1"
    strategy_hash: SHA256Hash
    protocol_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    admission_hash: SHA256Hash
    bundle_hash: SHA256Hash
    evaluator_evidence_hash: SHA256Hash
    code_version_hash: SHA256Hash
    environment_closure_hash: SHA256Hash
    run_identity_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = evaluation_run_identity_hash(self)
        if self.run_identity_hash != expected:
            raise ValueError(
                f"run identity hash mismatch: expected {expected}, "
                f"got {self.run_identity_hash}"
            )
        return self
