"""Offline producer-driven execution and post-execution M0 clocks (#564).

The large fixture is a platform proof, not a scored study. B is scripted and R
uses an explicit fixture score. No external AI, market feed or broker is used.
"""

# ruff: noqa: E402
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import test_evaluator_experiment_run as m0_fixture
import test_stage1_original_invocation_end_to_end as full_fixture
from test_evaluator_engine import FixedTargetStrategy, _engine
from test_stage1_synthetic_research_execution import (
    BASE,
    cold_read,
    make_harness,
    request,
)

from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.experiments import ExperimentRunStatus
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.intelligence.contracts import RawChoice, StrategySelection, TargetWeight
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.stage1_synthetic_research_execution import (
    OfflineResearchRequestV1,
    execute_synthetic_research,
)


@pytest.mark.parametrize("fail", [False, True])
def test_completion_clock_is_sampled_once_after_actual_strategy_outcome(
    tmp_path: Path, fail: bool
) -> None:
    decided: list[bool] = []
    calls: list[datetime] = []

    class Observed(FixedTargetStrategy):
        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            decided.append(True)
            if fail:
                raise RuntimeError("actual fixture execution failed")
            return super().decide(context)

    strategy = Observed(m0_fixture._buy_ten().targets)
    ledger = SQLiteLedger(tmp_path / "m0.sqlite3")
    context = m0_fixture._context(_engine(), strategy=strategy, ledger=ledger)
    sampled = m0_fixture.LATER + timedelta(minutes=7)

    def after() -> datetime:
        assert decided, "completion must not be guessed before execution"
        assert not ledger.verified_events(), "completion precedes original M0 append"
        calls.append(sampled)
        return sampled

    context = replace(context, completion_clock=after)
    run = execute_experiment_run(m0_fixture._specification(), context)
    assert calls == [sampled]
    assert run.completed_at == sampled
    assert run.status is (
        ExperimentRunStatus.FAILED if fail else ExperimentRunStatus.COMPLETED
    )
    events = ledger.verified_events()
    assert len(events) == 1
    assert events[0].timestamp == sampled
    assert isinstance(events[0].payload, Mapping)
    assert events[0].payload["status"] == run.status.value


@pytest.mark.parametrize("bad", ["naive", "rollback", "throws", "string"])
def test_bad_completion_clock_never_writes_a_false_completed_m0(
    tmp_path: Path, bad: str
) -> None:
    ledger = SQLiteLedger(tmp_path / "m0.sqlite3")
    context = m0_fixture._context(_engine(), ledger=ledger)

    def clock() -> Any:
        if bad == "throws":
            raise OSError("clock unavailable after execution")
        if bad == "naive":
            return datetime(2026, 10, 25)
        if bad == "rollback":
            return context.started_at - timedelta(seconds=1)
        return "2026-10-25T12:00:00Z"

    with pytest.raises((ValueError, OSError)):
        execute_experiment_run(
            m0_fixture._specification(), replace(context, completion_clock=clock)
        )
    assert ledger.verified_events() == ()


def test_legacy_completion_and_hash_contract_is_unchanged(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "m0.sqlite3")
    context = m0_fixture._context(_engine(), ledger=ledger)
    assert context.completion_clock is None
    run = execute_experiment_run(m0_fixture._specification(), context)
    assert run.completed_at == m0_fixture.LATER
    assert ledger.verified_events()[0].schema_version == "1"


def test_full_379_session_pair_is_research_selected_and_cold_readable(
    tmp_path: Path,
) -> None:
    bundle = full_fixture._input_bundle()
    selected = RawChoice(
        disposition="propose",
        selection=StrategySelection(family_id="B3", strategy_version="1"),
        targets=tuple(
            TargetWeight(security_id=str(security), weight="0.08")
            for security in full_fixture.SECURITIES
        ),
        cash_weight="0.04",
        rationale="Twelve fictional USD100 assets, eight whole shares each.",
    )
    results = []
    for arm in ("ARM-B", "ARM-R"):
        harness = make_harness(
            tmp_path / arm, arm=arm, engine=full_fixture._engine(bundle)
        )
        planned = (
            request(selected)
            if arm == "ARM-B"
            else OfflineResearchRequestV1(
                mode="conventional_fixture",
                deadline=BASE + timedelta(minutes=5),
                candidate_pool=(selected,),
                fixture_scores={"B3": "1"},
            )
        )
        result = execute_synthetic_research(**harness, request=planned)
        assert result.state == "LOCAL_EXECUTION_COMPLETE"
        assert result.original_result is not None
        full_fixture._assert_actual_b3_result(result.original_result.original_artifacts)
        assert len(harness["origin"].verified_events()) == 11
        assert len(result.research_receipt_hashes) == 3
        assert result.reported_research_cost_usd == Decimal("0")
        # Destroy the original writer/engine references before verification.
        del harness["account"], harness["engine"]
        again = cold_read(harness, result.opportunity_ref)
        assert again.original_result is not None
        assert (
            again.original_result.original_artifacts_bytes
            == result.original_result.original_artifacts_bytes
        )
        assert again.candidate_hash == result.candidate_hash
        assert not again.g2_accepted
        results.append(again)
    left, right = (item.original_result for item in results)
    assert left is not None and right is not None
    assert left.account_id != right.account_id
    assert left.invocation_binding != right.invocation_binding
    assert left.operational_m0_run_id != right.operational_m0_run_id
    assert left.original_artifacts_bytes == right.original_artifacts_bytes
    assert results[0].research_receipt_hashes != results[1].research_receipt_hashes
