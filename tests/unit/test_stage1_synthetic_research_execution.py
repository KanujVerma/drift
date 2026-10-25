"""Unit controls for the bounded research-to-execution candidate (#564)."""

# The same fixture is used by integration and adversarial tests. Only inputs
# are synthetic; the K1 producer, ledger and M0 execution are real implementations.
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from test_evaluator_engine import SEC_A, _engine
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import (
    RawChoice,
    ResearchContext,
    StrategySelection,
    TargetWeight,
    compute_record_hash,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.loop.stage1_synthetic_research_execution import (
    OfflineResearchRequestV1,
    execute_synthetic_research,
    installed_registry_reference,
    installed_strategy_registration,
    original_portfolio_reference,
    read_synthetic_research_execution,
    synthetic_universe_reference,
)

BASE = datetime(2026, 10, 25, 12, tzinfo=UTC)


@dataclass
class Tick:
    at: datetime = BASE

    def __call__(self) -> datetime:
        value = self.at
        self.at += timedelta(seconds=1)
        return value


def make_harness(
    root: Path, *, arm: str = "ARM-B", engine: Any = None
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    engine = _engine() if engine is None else engine
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    provenance = build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id=arm,
        checkpoint_id="CKPT-001",
        events=(),
    )
    clock = Tick()
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=root / "original.sqlite3",
        issuer_instance_id=uuid7(),
    )
    store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=clock)
    account = Stage1SyntheticAccountLifecycleV1(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        store=store,
    )
    engine.prepare_opening_book(lifecycle=account)
    original = account.verified_original()
    path = Path(__file__).parents[1] / "fixtures/adaptive_research/research_v1.json"
    data = json.loads(path.read_text())["fixtures"]["F01"]
    data.pop("record_hash")
    data["context_id"] = f"{provenance.scope.trial_id}:context"
    data["scope"] = {
        "experiment_id": campaign.campaign_id,
        "arm_id": arm,
        "account_id": original.fields.portfolio_account_id,
        "campaign_ref": {
            "id": campaign.campaign_id,
            "version": campaign.schema_version,
            "sha256": campaign.campaign_spec_fingerprint,
        },
    }
    cutoff = engine.bundle.session_clock.sessions[
        engine.protocol.warmup_session_count - 1
    ].closed_at
    data["decision_cutoff"] = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    data["memory_cutoff"] = data["decision_cutoff"]
    data["built_at"] = (BASE + timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    data["review_started_at"] = (BASE + timedelta(seconds=3)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    data["portfolio_ref"] = original_portfolio_reference(original).model_dump(
        mode="python"
    )
    data["registry_ref"] = installed_registry_reference().model_dump(mode="python")
    securities = tuple(item.security_id for item in engine.bundle.security_identities)
    data["universe_ref"] = synthetic_universe_reference(securities).model_dump(
        mode="python"
    )
    data["record_hash"] = compute_record_hash(data)
    clock.at = BASE + timedelta(seconds=4)
    return {
        "origin": origin,
        "campaign": campaign,
        "arms": arms,
        "bindings": bindings,
        "expected_run_ids": ("RUN-001",),
        "provenance": provenance,
        "account": account,
        "engine": engine,
        "context": ResearchContext.model_validate(data),
        "clock": clock,
    }


def proposal(family: str = "B3", *, weight: str = "1", cash: str = "0") -> RawChoice:
    return RawChoice(
        disposition="propose",
        selection=StrategySelection(family_id=family, strategy_version="1"),
        targets=(TargetWeight(security_id=str(SEC_A), weight=weight),),
        cash_weight=cash,
        rationale="Explicit offline installed-strategy fixture; not AI efficacy.",
    )


def request(
    choice: RawChoice | None = None, **changes: Any
) -> OfflineResearchRequestV1:
    return OfflineResearchRequestV1.model_validate(
        {
            "mode": "scripted_fixture",
            "deadline": BASE + timedelta(minutes=5),
            "scripted_choice": proposal() if choice is None else choice,
        }
        | changes
    )


def cold_read(harness: dict[str, Any], reference: Any) -> Any:
    return read_synthetic_research_execution(
        **{
            key: value
            for key, value in harness.items()
            if key not in ("account", "engine", "context")
        },
        opportunity_ref=reference,
    )


def test_actual_scripted_research_executes_original_account_and_cold_reads(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    result = execute_synthetic_research(**harness, request=request())
    assert result.state == "LOCAL_EXECUTION_COMPLETE"
    assert result.disposition == "propose"
    assert result.original_result is not None
    assert (
        result.original_result.original_artifacts.result.metrics.committed_fill_count
        == 1
    )
    assert (
        result.original_result.original_artifacts.final_state.net_asset_value
        == Decimal("12000")
    )
    assert result.reported_research_cost_usd == Decimal("0")
    assert len(result.research_receipt_hashes) == 3
    assert not result.g2_accepted
    assert not result.scientifically_qualified
    assert not result.authorizes_trading
    again = cold_read(harness, result.opportunity_ref)
    assert again.original_result is not None
    assert (
        again.original_result.original_artifacts_bytes
        == result.original_result.original_artifacts_bytes
    )
    assert again.candidate_hash == result.candidate_hash


def test_installed_registry_is_exact_and_not_a_dynamic_import() -> None:
    assert installed_strategy_registration("B3").family_id == "B3"
    for invalid in ("B0", "B6", "b3", "os.system", "drift.baselines.B3"):
        with pytest.raises(ValueError, match="UNSUPPORTED_INSTALLED_STRATEGY"):
            installed_strategy_registration(invalid)


def test_request_refuses_mixed_transport_modes() -> None:
    with pytest.raises(ValueError, match="SCRIPTED_REQUEST_CANNOT_HAVE_COMPARATOR"):
        OfflineResearchRequestV1(
            mode="scripted_fixture",
            deadline=datetime(2026, 10, 25, tzinfo=UTC),
            fixture_scores={"B3": "1"},
        )


def test_request_requires_explicit_finite_fixture_score() -> None:
    for score in ("NaN", "Infinity", "1e5", " 1", ""):
        with pytest.raises(ValueError):
            OfflineResearchRequestV1(
                mode="conventional_fixture",
                deadline=datetime(2026, 10, 25, tzinfo=UTC),
                fixture_scores={"B3": score},
            )


def test_conventional_research_drives_original_account(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, arm="ARM-R")
    result = execute_synthetic_research(
        **harness,
        request=OfflineResearchRequestV1(
            mode="conventional_fixture",
            deadline=BASE + timedelta(minutes=5),
            candidate_pool=(proposal(),),
            fixture_scores={"B3": "1"},
        ),
    )
    assert result.state == "LOCAL_EXECUTION_COMPLETE"
    assert result.original_result is not None
    assert result.original_result.account_id.endswith("R-001")
    assert (
        result.original_result.original_artifacts.final_state.net_asset_value == 12000
    )
    assert cold_read(harness, result.opportunity_ref).state == result.state


@pytest.mark.parametrize("disposition", ["abstain", "unavailable", "hold"])
def test_nonproposal_never_dispatches_m0(tmp_path: Path, disposition: Any) -> None:
    harness = make_harness(tmp_path)
    choice = RawChoice(
        disposition=disposition,
        selection=None,
        targets=(),
        cash_weight=None,
        reason_codes=(f"fixture-{disposition}",),
        rationale="Explicit fixture refusal.",
    )
    result = execute_synthetic_research(**harness, request=request(choice))
    assert result.state == "NO_DISPATCH"
    assert result.original_result is None
    assert not any(
        event.event_type == "m2.evaluation.run.recorded"
        for event in harness["origin"].verified_events()
    )
    assert len(result.research_receipt_hashes) == 3
    assert cold_read(harness, result.opportunity_ref).reason == result.reason


@pytest.mark.parametrize("cost", ["0.12", "NaN"])
def test_estimate_or_unknown_is_not_reported_as_verified_zero(
    tmp_path: Path, cost: str
) -> None:
    harness = make_harness(tmp_path)
    result = execute_synthetic_research(
        **harness, request=request(synthetic_cost_amount=cost)
    )
    assert result.reported_research_cost_usd is None
    assert len(result.research_receipt_hashes) == 3


def test_timeout_retains_failed_attempt_and_unknown_cost(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    result = execute_synthetic_research(**harness, request=request(should_timeout=True))
    assert result.state == "NO_DISPATCH"
    assert result.candidate_hash is None
    assert result.reported_research_cost_usd is None
    assert result.original_result is None
    assert len(result.research_receipt_hashes) == 3
    assert cold_read(harness, result.opportunity_ref).state == "NO_DISPATCH"


def test_proposed_weights_cannot_be_ignored_by_installed_strategy(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    result = execute_synthetic_research(
        **harness, request=request(proposal(weight="0.5", cash="0.5"))
    )
    assert result.state == "EXECUTION_FAILED"
    assert "RESEARCH_INSTALLED_TARGET_MISMATCH" in result.reason
    assert result.original_result is None
    assert cold_read(harness, result.opportunity_ref).state == "EXECUTION_FAILED"


def test_insufficient_b4_history_is_not_a_successful_sell_all(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    result = execute_synthetic_research(**harness, request=request(proposal("B4")))
    assert result.state == "EXECUTION_FAILED"
    assert "RESEARCH_INSTALLED_TARGET_MISMATCH" in result.reason
    assert result.original_result is None
