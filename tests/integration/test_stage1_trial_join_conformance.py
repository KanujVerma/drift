"""Original paired-trial evidence at independently retained B/R prefixes."""

import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from drift.loop import stage1_controlled_contracts as C
from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
from drift.loop.stage1_controlled_readback import compare_controlled_campaigns

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))


def test_complete_b_keeps_original_unfinished_r_prefix_unresolved(
    tmp_path: Path,
) -> None:
    """J03: later R completion cannot leak into a pinned earlier paired view."""
    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    left = controlled_arguments(tmp_path / "B")
    right = controlled_arguments(tmp_path / "R", arm="ARM-R")
    checkpoint = right["checkpoints"][0]
    right["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={
                        "mode": "conventional_fixture",
                        "selected_family": None,
                        "candidate_families": ("B3",),
                        "scores": {"B3": Decimal(1)},
                    }
                )
            }
        ),
    )
    b = execute_controlled_campaign(**left)
    r = execute_controlled_campaign(**right)
    assert b.m0_status == r.m0_status == "completed"
    observed_at = BASE + timedelta(days=2)
    original_r = CapturedControlledJournalV1(
        origin=right["origin"],
        allocation_id=r.allocation_id,
        observed_at=observed_at,
    )
    decision = next(
        row
        for row in original_r.rows
        if isinstance(row.record, C.DecisionRecordV1)
        and row.record.checkpoint_id == checkpoint.checkpoint_id
    )
    before_b = left["origin"].ledger_path.read_bytes()
    before_r = right["origin"].ledger_path.read_bytes()
    kwargs: dict[str, Any] = dict(
        test_origin=left["origin"],
        comparator_origin=right["origin"],
        test_allocation_id=b.allocation_id,
        comparator_allocation_id=r.allocation_id,
        campaign=left["campaign"],
        arms=left["arms"],
        bindings=left["bindings"],
        expected_run_ids=left["expected_run_ids"],
        test_provenance=left["provenance"],
        comparator_provenance=right["provenance"],
        clock=lambda: observed_at,
    )
    pending = compare_controlled_campaigns(
        **kwargs, comparator_as_of=decision.event.event_hash
    )
    assert pending.test.status == "VERIFIED_COMPLETE"
    assert pending.test.economics.complete
    assert pending.test.original_result is not None
    assert pending.comparator.status == "UNRESOLVED"
    assert pending.comparator.original_result is None
    assert not pending.comparator.economics.complete
    assert pending.comparator.snapshot_tip == decision.ref
    assert pending.test.allocation_id == b.allocation_id
    assert pending.comparator.allocation_id == r.allocation_id
    assert b.allocation_id != r.allocation_id
    assert len(pending.test.trials) == len(pending.comparator.trials) == 1
    for arm_report, provenance in (
        (pending.test, left["provenance"]),
        (pending.comparator, right["provenance"]),
    ):
        trial = arm_report.trials[0]
        scope = provenance.scope
        assert trial.campaign_id == scope.campaign_id
        assert trial.run_id == scope.run_id
        assert trial.arm_id == scope.arm_id
        assert trial.account_id == scope.run_account_binding.portfolio_account_id
        assert trial.checkpoint_id == scope.checkpoint_id
        assert trial.trial_id == scope.trial_id
        assert trial.manifest_hash == arm_report.manifest_hash
        assert (
            arm_report.economics.full_manifest_fingerprint
            == scope.complete_manifest_fingerprint
        )
    assert pending.test.trials[0].trial_id != pending.comparator.trials[0].trial_id
    r_trial = pending.comparator.trials[0]
    assert decision.event.event_hash in pending.comparator.accounted_event_hashes
    assert r_trial.snapshot_tip == decision.ref
    assert r_trial.outcome == "UNRESOLVED"
    assert r_trial.reason == "ORIGINAL_EXECUTION_UNAVAILABLE"
    assert r_trial.operating_cost.status == "VERIFIED_ZERO"
    assert pending.economic_advantage.state == "UNAVAILABLE"
    assert pending.economic_advantage.value is None

    complete = compare_controlled_campaigns(**kwargs)
    assert complete.test.status == complete.comparator.status == "VERIFIED_COMPLETE"
    assert complete.economic_advantage.state == "KNOWN"
    assert complete.economic_advantage.value == Decimal(0)
    assert complete.test == pending.test
    assert complete.comparator.snapshot_tip != pending.comparator.snapshot_tip
    assert complete.evidence_hash != pending.evidence_hash
    replay = compare_controlled_campaigns(
        **kwargs, comparator_as_of=decision.event.event_hash
    )
    assert replay == pending
    for report in (pending, complete, replay):
        assert report.independent_account_count == 2
        assert report.independent_paired_run_count == 1
        assert report.scientific_conclusion == "INSUFFICIENT_INDEPENDENT_QUALIFIED_RUNS"
        assert not report.authorizes_trading
        assert not report.test.scientifically_qualified
        assert not report.comparator.scientifically_qualified
    assert left["origin"].ledger_path.read_bytes() == before_b
    assert right["origin"].ledger_path.read_bytes() == before_r
