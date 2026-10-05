"""Historical tournament archive and query engine (M10-4, Issue 249).

Reconstructs match records, current champions, and promotion lineages
directly from immutable M0 SQLite ledger events.
"""

from collections.abc import Mapping
from uuid import UUID

from drift.domain.tournament import (
    CHAMPION_PROMOTED_EVENT_TYPE,
    MATCH_COMPLETED_EVENT_TYPE,
    ChampionPromotedAuditEventPayloadV1,
    TournamentMatchRecordV1,
    TournamentParticipantV1,
)
from drift.ledger.interface import Ledger
from drift.serialization.canonical import canonical_json

__all__ = ["TournamentArchive"]


class TournamentArchive:
    """Historical archive reconstructing tournament state from immutable ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._matches: dict[UUID, TournamentMatchRecordV1] = {}
        self._promotions: list[ChampionPromotedAuditEventPayloadV1] = []
        self._champions: dict[str, TournamentParticipantV1] = {}
        self._lineage: dict[str, list[UUID]] = {}
        self.refresh()

    def refresh(self) -> None:
        """Scan ledger events and synchronize tournament state."""
        self._matches.clear()
        self._promotions.clear()
        self._champions.clear()
        self._lineage.clear()

        for event in self.ledger.events():
            if not isinstance(event.payload, Mapping):
                continue

            if event.event_type == MATCH_COMPLETED_EVENT_TYPE:
                match_raw = event.payload.get("match")
                if isinstance(match_raw, Mapping):
                    try:
                        record = TournamentMatchRecordV1.model_validate_json(
                            canonical_json(dict(match_raw))
                        )
                        self._matches[record.match_id] = record

                        # Track champion initialization if not yet set
                        strat = record.champion.strategy_type
                        if strat not in self._champions:
                            self._champions[strat] = record.champion
                            self._lineage[strat] = [record.champion.participant_id]
                    except Exception:
                        continue

            elif event.event_type == CHAMPION_PROMOTED_EVENT_TYPE:
                try:
                    promo = ChampionPromotedAuditEventPayloadV1.model_validate_json(
                        canonical_json(dict(event.payload))
                    )
                    self._promotions.append(promo)

                    # Update current champion
                    if promo.match_id in self._matches:
                        match = self._matches[promo.match_id]
                        strat = match.challenger.strategy_type
                        self._champions[strat] = match.challenger
                        if strat not in self._lineage:
                            self._lineage[strat] = []
                        self._lineage[strat].append(promo.promoted_champion_id)
                except Exception:
                    continue

    @property
    def total_matches_count(self) -> int:
        """Total number of sealed tournament matches."""
        return len(self._matches)

    @property
    def promotions_count(self) -> int:
        """Total number of champion promotions."""
        return len(self._promotions)

    def get_match(self, match_id: UUID) -> TournamentMatchRecordV1 | None:
        """Retrieve match record by match_id."""
        return self._matches.get(match_id)

    def list_matches(
        self, tournament_id: UUID | None = None
    ) -> tuple[TournamentMatchRecordV1, ...]:
        """List all matches, optionally scoped to a tournament_id."""
        if tournament_id is None:
            return tuple(self._matches.values())
        return tuple(
            m for m in self._matches.values() if m.tournament_id == tournament_id
        )

    def get_current_champion(
        self, strategy_type: str
    ) -> TournamentParticipantV1 | None:
        """Retrieve the current reigning Champion for a given strategy type."""
        return self._champions.get(strategy_type)

    def get_champion_lineage(self, strategy_type: str) -> tuple[UUID, ...]:
        """Retrieve the ordered succession lineage of champions."""
        return tuple(self._lineage.get(strategy_type, []))
