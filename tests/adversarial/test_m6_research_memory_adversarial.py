"""Adversarial acceptance suite for Structured Research Memory (M6-5).

Attacks research memory invariants across:
1. Bit-flip cryptographic hash tampering (detecting corrupted records);
2. Duplicate trial deduplication and deduplication key collisions;
3. Circular hypothesis lineage detection;
4. SQLite append-only ledger tampering attacks (UPDATE / DELETE rejected);
5. Empty archive fail-closed query safety;
6. Selection bias trial accounting preservation (cannot hide trials from K).
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.hypotheses import Hypothesis
from drift.domain.research_memory import (
    FailureCategory,
    HypothesisStatus,
    ParameterSearchSpaceV1,
    TrialOutcome,
    build_failure_postmortem,
    build_hypothesis_lifecycle,
    build_parameter_search_space,
    build_research_trial_record,
)
from drift.errors import DuplicateEventError
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.hypothesis import (
    HypothesisManager,
    InvalidStateTransitionError,
)
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
HYPOTHESIS_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")
TRIAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd05")
POSTMORTEM_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd06")


# =========================================================================
# Attack 1: Cryptographic Bit-Flip Tampering Attacks
# =========================================================================


def test_adversarial_bit_flip_tampering_hypothesis_lifecycle() -> None:
    valid_lc = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.PROPOSED,
        updated_at=TIMESTAMP,
    )
    raw = valid_lc.model_dump(mode="python")

    # Flip the first hex character of the lifecycle hash
    first_char = raw["lifecycle_hash"][0]
    flipped_char = "0" if first_char != "0" else "1"
    raw["lifecycle_hash"] = flipped_char + raw["lifecycle_hash"][1:]

    with pytest.raises(ValidationError, match="hash mismatch"):
        valid_lc.__class__.model_validate(raw)


def test_adversarial_bit_flip_tampering_postmortem() -> None:
    valid_pm = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.DRAWDOWN_BREACH,
        root_cause_summary="Drawdown exceeded 20%",
        lessons_learned="Stop loss required",
        created_at=TIMESTAMP,
    )
    raw = valid_pm.model_dump(mode="python")

    first_char = raw["postmortem_hash"][0]
    flipped_char = "0" if first_char != "0" else "1"
    raw["postmortem_hash"] = flipped_char + raw["postmortem_hash"][1:]

    with pytest.raises(ValidationError, match="hash mismatch"):
        valid_pm.__class__.model_validate(raw)


def test_adversarial_bit_flip_tampering_trial_record() -> None:
    valid_trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "1.2"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    raw = valid_trial.model_dump(mode="python")

    first_char = raw["trial_hash"][0]
    flipped_char = "0" if first_char != "0" else "1"
    raw["trial_hash"] = flipped_char + raw["trial_hash"][1:]

    with pytest.raises(ValidationError, match="hash mismatch"):
        valid_trial.__class__.model_validate(raw)


def test_adversarial_bit_flip_tampering_parameter_space() -> None:
    valid_space = build_parameter_search_space(
        search_space_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd07"),
        strategy_type="b4_momentum",
        dimension_names=("lookback",),
        total_trials=1,
        evaluated_parameter_hashes=("a" * 64,),
        created_at=TIMESTAMP,
    )
    raw = valid_space.model_dump(mode="python")

    first_char = raw["search_space_hash"][0]
    flipped_char = "0" if first_char != "0" else "1"
    raw["search_space_hash"] = flipped_char + raw["search_space_hash"][1:]

    with pytest.raises(ValidationError, match="hash mismatch"):
        ParameterSearchSpaceV1.model_validate(raw)


# =========================================================================
# Attack 2: Duplicate Trial Deduplication & Replay Collisions
# =========================================================================


def test_adversarial_duplicate_trial_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "adversarial.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "1.2"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )

    recorder.record_trial(trial)

    # Attempting to re-record exact same trial fails fail-closed
    with pytest.raises(DuplicateEventError):
        recorder.record_trial(trial)


# =========================================================================
# Attack 3: Circular Hypothesis Lineage Detection
# =========================================================================


def test_adversarial_self_referencing_hypothesis() -> None:
    with pytest.raises(ValueError, match="cannot reference itself"):
        Hypothesis(
            hypothesis_id=HYPOTHESIS_ID_1,
            created_at=TIMESTAMP,
            title="Self-referencing claim",
            statement="Self claim",
            mechanism="Self loop",
            expected_direction="positive",
            universe="all",
            horizon="1d",
            falsification_criteria="None",
            parent_hypothesis_ids=(HYPOTHESIS_ID_1,),
            author_type="adversary",
            author_version="1.0",
        )


def test_adversarial_circular_state_transition(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "adversarial.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = Hypothesis(
        hypothesis_id=HYPOTHESIS_ID_1,
        created_at=TIMESTAMP,
        title="Momentum claim",
        statement="Momentum works",
        mechanism="Drift",
        expected_direction="positive",
        universe="all",
        horizon="1d",
        falsification_criteria="Negative IC",
        author_type="adversary",
        author_version="1.0",
    )
    manager.register_hypothesis(hypo)
    manager.activate_hypothesis(hypo.hypothesis_id)
    manager.falsify_hypothesis(hypo.hypothesis_id, evidence_hashes=("a" * 64,))

    # Once FALSIFIED, cannot transition back to ACTIVE or VALIDATED
    with pytest.raises(InvalidStateTransitionError):
        manager.activate_hypothesis(hypo.hypothesis_id)

    with pytest.raises(InvalidStateTransitionError):
        manager.validate_hypothesis(hypo.hypothesis_id, evidence_hashes=("b" * 64,))


# =========================================================================
# Attack 4: SQLite Append-Only Ledger Tampering Attacks
# =========================================================================


def test_adversarial_sqlite_ledger_tampering_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "tamper.sqlite3"
    ledger = SQLiteLedger(db_path)
    recorder = ResearchMemoryRecorder(ledger)

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "1.2"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    recorder.record_trial(trial)

    # Direct database connection attempting to modify immutable ledger
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Attempt UPDATE
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        cursor.execute(
            "UPDATE audit_events SET payload_json = '{\"tampered\": 1}' "
            "WHERE sequence = 1"
        )

    # Attempt DELETE
    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only"):
        cursor.execute("DELETE FROM audit_events WHERE sequence = 1")

    conn.close()

    # Verify that ledger verification passes and no data was corrupted
    ledger.verify_chain()


# =========================================================================
# Attack 5: Empty Archive Fail-Closed Query Safety
# =========================================================================


def test_adversarial_empty_archive_fail_closed(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "empty.sqlite3")
    archive = ResearchMemoryArchive(ledger)

    assert archive.get_trial_count() == 0
    assert archive.get_trial_sharpe_distribution() == []
    assert archive.find_falsified_hypotheses() == []
    assert archive.get_postmortems() == []
    assert not archive.is_parameter_region_evaluated("any", "any")


# =========================================================================
# Attack 6: Selection Bias Trial Accounting Preservation
# =========================================================================


def test_adversarial_selection_bias_accounting_preservation(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "selection_bias.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    # Record 10 failed or inferior exploratory trials
    for i in range(10):
        t = build_research_trial_record(
            trial_id=UUID(f"018f3a5b-6c7d-7890-8123-456789abcd{i:02x}"),
            hypothesis_id=HYPOTHESIS_ID_1,
            experiment_id=EXPERIMENT_ID_1,
            run_id=RUN_ID_1,
            strategy_type="b4_momentum",
            parameters={"lookback": i + 5},
            headline_metrics={"sharpe_ratio": f"-0.{i}"},
            trial_outcome=TrialOutcome.FAILED,
            created_at=TIMESTAMP,
        )
        recorder.record_trial(t)

    archive = ResearchMemoryArchive(ledger)

    # Invariant: Total exploratory trials K MUST be exactly 10;
    # failed trials cannot be concealed or purged to game the DSR calculation.
    assert archive.get_trial_count() == 10
    assert len(archive.get_trial_sharpe_distribution()) == 10
