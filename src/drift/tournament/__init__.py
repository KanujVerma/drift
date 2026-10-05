"""Tournament evaluation, statistical comparison, and runner package (Milestone M10)."""

from drift.tournament.archive import TournamentArchive
from drift.tournament.comparator import (
    TournamentComparisonResult,
    compute_paired_returns_statistics,
    evaluate_head_to_head_match,
)
from drift.tournament.recorder import (
    MATCH_ENTITY_TYPE,
    PROMOTION_ENTITY_TYPE,
    REJECTION_ENTITY_TYPE,
    TournamentRecorder,
)
from drift.tournament.runner import (
    TournamentRecorderProtocol,
    TournamentRunner,
)

__all__ = [
    "MATCH_ENTITY_TYPE",
    "PROMOTION_ENTITY_TYPE",
    "REJECTION_ENTITY_TYPE",
    "TournamentArchive",
    "TournamentComparisonResult",
    "TournamentRecorder",
    "TournamentRecorderProtocol",
    "TournamentRunner",
    "compute_paired_returns_statistics",
    "evaluate_head_to_head_match",
]
