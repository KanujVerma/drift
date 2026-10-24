"""Synthetic-only offline news screening (Issue #381).

No source ingestion, source qualification, LLM, persistence or trading action.
The Matthew SRC producer contract #394 remains a separate acceptance gate.
"""

from drift.news_triage.screen import (
    EventEvidence,
    EventKey,
    EvidenceRef,
    FeedCoverage,
    FeedScreeningResult,
    PriorScreening,
    ScreeningPolicy,
    ScreeningResult,
    policy_digest,
    screen_event,
    screen_feed_coverage,
)

__all__ = [
    "EventEvidence",
    "EventKey",
    "EvidenceRef",
    "FeedCoverage",
    "FeedScreeningResult",
    "PriorScreening",
    "ScreeningPolicy",
    "ScreeningResult",
    "policy_digest",
    "screen_event",
    "screen_feed_coverage",
]
