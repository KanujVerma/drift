"""Intelligence and bounded learning package.

Provides pure immutable contracts and validation for the 'drift-research/1-draft'
profile under ADR 0017 and Decision Packet DP-R1.
"""

from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CandidateStrategy,
    ContextInput,
    CostReceipt,
    ModelReplayRecord,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
    Scope,
    StoredArtifactRef,
    StrategySelection,
    TargetWeight,
    TrustedInvocationBinding,
    compute_record_hash,
)
from drift.intelligence.validation import (
    ResolvedDependencies,
    StrategyRegistration,
    ValidationResult,
    validate_candidate,
    validate_raw_choice,
    validate_retained_record,
)

__all__ = [
    "ArtifactReference",
    "AttemptRecord",
    "CandidateStrategy",
    "ContextInput",
    "CostReceipt",
    "ModelReplayRecord",
    "RawChoice",
    "ResearchCandidate",
    "ResearchContext",
    "ResolvedDependencies",
    "Scope",
    "StoredArtifactRef",
    "StrategyRegistration",
    "StrategySelection",
    "TargetWeight",
    "TrustedInvocationBinding",
    "ValidationResult",
    "compute_record_hash",
    "validate_candidate",
    "validate_raw_choice",
    "validate_retained_record",
]
