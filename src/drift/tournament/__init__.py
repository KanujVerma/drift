"""Tournament evaluation, statistical comparison, and runner package (Milestone M10)."""

from drift.tournament.comparator import (
    TournamentComparisonResult,
    compute_paired_returns_statistics,
    evaluate_head_to_head_match,
)
from drift.tournament.runner import (
    TournamentRecorderProtocol,
    TournamentRunner,
)

__all__ = [
    "TournamentComparisonResult",
    "TournamentRecorderProtocol",
    "TournamentRunner",
    "compute_paired_returns_statistics",
    "evaluate_head_to_head_match",
]
