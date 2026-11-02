"""Portfolio-preserving causality and real cold-process controls (#564/#566).

Adapt test approaches from the reviewed Freqtrade/Passivbot/Hummingbot work,
not their source code. All prices and calendars below are labelled synthetic.
The installed K1, evaluator, prepared account and original RESULT readers run.
These tests neither authenticate external issuers nor certify G2 acceptance.
"""

# ruff: noqa: E402
import base64
import hashlib
import json
import subprocess
import sys
import zlib
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import test_evaluator_engine as fixture
import test_stage1_original_invocation_end_to_end as window_fixture
from test_stage1_synthetic_research_execution import (
    cold_read,
    make_harness,
    request,
)

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_strategy import StrategyDecisionContextV1
from drift.domain.normalization import DerivedObservationViewV1
from drift.errors import DuplicateEventError
from drift.intelligence.contracts import RawChoice, StrategySelection, TargetWeight
from drift.ledger.stage1_synthetic_account_receipts import LocalEventReferenceV1
from drift.loop import stage1_synthetic_research_execution as pipeline
from drift.serialization.canonical import canonical_json

MEMBERS = ((fixture.SEC_A, fixture.LISTING_A), (fixture.SEC_B, fixture.LISTING_B))
CUTOFF_INDEX = 300


def _view(
    security: UUID,
    listing: UUID,
    day: date,
    cutoff: date,
    price: str,
    *,
    decision: bool,
) -> DerivedObservationViewV1:
    original = window_fixture._constant_view(security, listing, day, decision=decision)
    observation = original.query.observation
    if decision:
        at = datetime.combine(cutoff, time(21), tzinfo=UTC)
        observation = observation.model_copy(
            update={"decision_time": at, "knowledge_cutoff": at, "effective_cutoff": at}
        )
    return fixture._restated_view(
        role="decision" if decision else "outcome",
        observation=observation,
        security_id=security,
        listing_id=listing,
        source_day=day,
        open_price="100",
        close_price=price,
    )


@cache
def _history_bundle(
    history: int,
    *,
    future_price: str = "100",
    truncated: bool = False,
    changed_past: str = "",
    cutoff_only: bool = False,
) -> EvaluationInputBundleV1:
    """Keep the exact same final history cutoff and both cross-sectional members.

    Future accounting prices can affect final NAV but cannot change the first
    decision. Historical changes are an explicit sensitivity, not a leak test.
    """
    full_days = window_fixture._session_dates()
    cutoff = full_days[CUTOFF_INDEX]
    end = CUTOFF_INDEX + (1 if cutoff_only else 2 if truncated else 3)
    days = full_days[CUTOFF_INDEX + 1 - history : end]

    def price(security: UUID, day: date) -> str:
        if day > cutoff:
            return future_price
        if changed_past == "B4" and security == fixture.SEC_B:
            if day == full_days[CUTOFF_INDEX - 21]:
                return "200"
        if changed_past == "B5" and security == fixture.SEC_A:
            if day == full_days[CUTOFF_INDEX - 10]:
                return "200"
        return "100"

    return fixture._bundle(
        days=days,
        decision_views=tuple(
            _view(
                security,
                listing,
                source,
                decision_day,
                price(security, source),
                decision=True,
            )
            for decision_day in days[history - 1 :]
            for source in days
            if source <= decision_day
            for security, listing in MEMBERS
        ),
        accounting_views=tuple(
            _view(security, listing, day, day, price(security, day), decision=False)
            for day in days
            for security, listing in MEMBERS
        ),
        eligibilities=tuple(
            fixture._eligibility(
                security, listing, knowledge_cutoff=datetime(2024, 1, 1, tzinfo=UTC)
            )
            for security, listing in MEMBERS
        ),
    )


def _choice(family: str, *, select_second: bool = False) -> RawChoice:
    if family == "B3":
        targets = tuple(
            TargetWeight(security_id=str(s), weight="0.5") for s, _ in MEMBERS
        )
    else:
        targets = (
            TargetWeight(security_id=str(MEMBERS[int(select_second)][0]), weight="1"),
        )
    return RawChoice(
        disposition="propose",
        selection=StrategySelection(family_id=family, strategy_version="1"),
        targets=targets,
        cash_weight="0",
        rationale="Explicit synthetic cross-sectional fixture, no predictive claim.",
    )


def _execute(
    root: Path,
    family: str,
    history: int,
    *,
    future_price: str = "100",
    truncated: bool = False,
    changed_past: bool = False,
) -> tuple[dict[str, Any], pipeline.SyntheticResearchExecutionReadback]:
    bundle = _history_bundle(
        history,
        future_price=future_price,
        truncated=truncated,
        changed_past=family if changed_past else "",
    )
    harness = make_harness(
        root,
        engine=fixture._engine(
            bundle=bundle, protocol=fixture._protocol(warmup=history)
        ),
    )
    result = pipeline.execute_synthetic_research(
        **harness, request=request(_choice(family, select_second=changed_past))
    )
    return harness, result


def _first_proof(harness: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    event = next(
        e
        for e in harness["origin"].verified_events()
        if e.event_type == pipeline.OUTCOME
    )
    assert isinstance(event.payload, Mapping)
    body = json.loads(str(event.payload["body_utf8"]))
    if body["first_context_utf8"] is not None:
        raw = body["first_context_utf8"].encode()
    else:
        artifact = body["first_context_artifact"]
        # Decode a trusted test-produced proof with a separate bounded oracle.
        stream = zlib.decompressobj()
        raw = stream.decompress(
            base64.b64decode(artifact["data"], validate=True), 8_388_609
        )
        assert len(raw) <= 8_388_608 and stream.eof
        assert not stream.unused_data and not stream.unconsumed_tail
        assert len(raw) == artifact["uncompressed_size"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
    context = json.loads(raw)
    intent = json.loads(body["first_intent_utf8"])
    assert context["admitted_universe"] == [str(s) for s, _ in MEMBERS]
    assert len(context["decision_views"]) == 2
    return context, intent


@pytest.mark.parametrize(("family", "history"), [("B3", 2), ("B4", 253), ("B5", 61)])
def test_future_poison_changes_outcome_but_not_the_actual_first_decision(
    tmp_path: Path, family: str, history: int
) -> None:
    baseline, left = _execute(tmp_path / "base", family, history)
    poisoned, right = _execute(tmp_path / "future", family, history, future_price="200")
    assert left.state == right.state == "LOCAL_EXECUTION_COMPLETE"
    assert left.original_result is not None and right.original_result is not None
    first_left = _first_proof(baseline)
    first_right = _first_proof(poisoned)
    assert canonical_json(first_left) == canonical_json(first_right)
    # Non-vacuous: the input bundle and economic outcome really changed.
    assert (
        baseline["engine"].bundle.bundle_hash != poisoned["engine"].bundle.bundle_hash
    )
    assert left.original_result.final_book_hash != right.original_result.final_book_hash
    assert (
        left.original_result.original_artifacts.result.metrics.ending_net_asset_value
        != (
            right.original_result.original_artifacts.result.metrics.ending_net_asset_value
        )
    )
    assert (
        left.original_result.operational_m0_run_id
        != right.original_result.operational_m0_run_id
    )
    assert not left.g2_accepted and not right.g2_accepted


@pytest.mark.parametrize(("family", "history"), [("B4", 253), ("B5", 61)])
def test_post_fill_prefix_preserves_the_whole_portfolio_first_decision(
    tmp_path: Path, family: str, history: int
) -> None:
    full, full_result = _execute(tmp_path / "full", family, history)
    prefix, prefix_result = _execute(
        tmp_path / "prefix", family, history, truncated=True
    )
    assert full_result.original_result is not None
    assert prefix_result.original_result is not None
    assert len(full["engine"].bundle.session_clock.sessions) == history + 2
    assert len(prefix["engine"].bundle.session_clock.sessions) == history + 1
    assert canonical_json(_first_proof(full)) == canonical_json(_first_proof(prefix))
    assert (
        full_result.original_result.original_artifacts.result.metrics.committed_fill_count
        == 1
    )
    assert (
        prefix_result.original_result.original_artifacts.result.metrics.committed_fill_count
        == 1
    )
    # A prefix run is not a completed holding-period scientific trial.
    assert not prefix_result.scientifically_qualified


@pytest.mark.parametrize(("family", "history"), [("B4", 253), ("B5", 61)])
def test_genuine_past_cross_sectional_change_can_change_the_selected_security(
    tmp_path: Path, family: str, history: int
) -> None:
    baseline, left = _execute(tmp_path / "base", family, history)
    changed, right = _execute(tmp_path / "past", family, history, changed_past=True)
    assert left.state == right.state == "LOCAL_EXECUTION_COMPLETE"
    context_left, intent_left = _first_proof(baseline)
    context_right, intent_right = _first_proof(changed)
    assert context_left["admitted_universe"] == context_right["admitted_universe"]
    assert context_left["decision_cutoff"] == context_right["decision_cutoff"]
    assert intent_left["targets"][0]["security_id"] == str(fixture.SEC_A)
    assert intent_right["targets"][0]["security_id"] == str(fixture.SEC_B)
    assert canonical_json(intent_left) != canonical_json(intent_right)


@pytest.mark.parametrize(("family", "history"), [("B4", 253), ("B5", 61)])
def test_extra_old_history_preserves_the_declared_fixed_lookback_decision(
    tmp_path: Path, family: str, history: int
) -> None:
    minimal, left = _execute(tmp_path / "minimal", family, history)
    extended, right = _execute(tmp_path / "extended", family, history + 21)
    assert left.state == right.state == "LOCAL_EXECUTION_COMPLETE"
    first_left, intent_left = _first_proof(minimal)
    first_right, intent_right = _first_proof(extended)
    assert len(first_right["decision_views"][0]["views"]) > len(
        first_left["decision_views"][0]["views"]
    )
    assert canonical_json(intent_left) == canonical_json(intent_right)


@pytest.mark.parametrize(("family", "history"), [("B4", 252), ("B5", 60)])
def test_below_required_history_cannot_become_a_successful_empty_target(
    tmp_path: Path, family: str, history: int
) -> None:
    harness, result = _execute(tmp_path, family, history)
    assert result.state == "EXECUTION_FAILED"
    assert "RESEARCH_INSTALLED_TARGET_MISMATCH" in result.reason
    assert result.original_result is None
    assert cold_read(harness, result.opportunity_ref).state == "EXECUTION_FAILED"
    assert not any(
        e.event_type == "stage1.synthetic_result.original_retained"
        for e in harness["origin"].verified_events()
    )


@pytest.mark.parametrize(("family", "history"), [("B4", 253), ("B5", 61)])
def test_cutoff_only_diagnostic_cannot_bypass_minimum_evaluation_window(
    family: str, history: int
) -> None:
    # Unlike a diagnostic that disables production guards, preserve the actual
    # runner rule: a valid run needs at least one post-warmup session.
    bundle = _history_bundle(history, cutoff_only=True)
    assert len(bundle.session_clock.sessions) == history
    with pytest.raises(ValueError, match="at least one non-warmup session"):
        fixture._engine(bundle=bundle, protocol=fixture._protocol(warmup=history))


def test_deliberately_future_sourced_view_is_refused_by_the_actual_context(
    tmp_path: Path,
) -> None:
    harness, result = _execute(tmp_path, "B3", 2)
    assert result.original_result is not None
    context, _ = _first_proof(harness)
    valid = StrategyDecisionContextV1.model_validate_json(canonical_json(context))
    future_view = next(
        view
        for view in harness["engine"].bundle.authentic_decision_views
        if view.source_session.local_date > valid.session_key.local_date
    )
    assert future_view.source_session.local_date > valid.session_key.local_date
    poisoned = dict(context)
    groups = json.loads(json.dumps(context["decision_views"]))
    selected = next(
        g for g in groups if g["security_id"] == str(future_view.security_id)
    )
    selected["views"].append(future_view.model_dump(mode="json"))
    poisoned["decision_views"] = groups
    with pytest.raises(ValueError, match="sourced after its decision session"):
        StrategyDecisionContextV1.model_validate_json(canonical_json(poisoned))


_CHILD_READER = r"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from test_stage1_campaign_config import (
    make_golden_arm_b, make_golden_arm_r, make_golden_bindings, make_golden_campaign,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1, LocalEventReferenceV1,
)
from drift.loop.stage1_synthetic_research_execution import (
    read_synthetic_research_execution,
)
from drift.serialization.canonical import canonical_json

source = json.loads(Path(sys.argv[1]).read_bytes())
campaign = make_golden_campaign()
arms = (make_golden_arm_b(), make_golden_arm_r())
bindings = tuple(make_golden_bindings())
provenance = build_stage1_trial_provenance_snapshot(
    campaign=campaign, arms=arms, bindings=bindings, expected_run_ids=('RUN-001',),
    run_id='RUN-001', arm_id='ARM-B', checkpoint_id='CKPT-001', events=(),
)
result = read_synthetic_research_execution(
    origin=ConfiguredLocalSyntheticOriginV1(
        Path(source['ledger']), UUID(source['issuer']),
    ),
    opportunity_ref=LocalEventReferenceV1(
        UUID(source['event_id']), source['event_hash'],
    ),
    campaign=campaign, arms=arms, bindings=bindings, expected_run_ids=('RUN-001',),
    provenance=provenance, clock=lambda: datetime(2026, 10, 25, 13, tzinfo=UTC),
)
print(canonical_json({
    'state': result.state, 'candidate_hash': result.candidate_hash,
    'result_hash': (
        None if result.original_result is None else result.original_result.result_hash
    ),
    'g2_accepted': result.g2_accepted, 'authorizes_trading': result.authorizes_trading,
}).decode())
"""


@pytest.mark.parametrize(
    "failure", ["none", "lost_ack", "missing_outcome", "missing_research"]
)
def test_fresh_process_recovers_only_retained_truth_without_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    harness = make_harness(tmp_path)
    append = pipeline._append

    def injected(*args: Any, **kwargs: Any) -> Any:
        phase = kwargs["phase"]
        if (failure == "missing_outcome" and phase == pipeline.OUTCOME) or (
            failure == "missing_research" and phase == pipeline.RESEARCH
        ):
            raise OSError("injected failure before original commit")
        event = append(*args, **kwargs)
        if failure == "lost_ack" and phase == pipeline.OUTCOME:
            raise OSError("injected failure after original commit")
        return event

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", injected)
        if failure == "none":
            pipeline.execute_synthetic_research(**harness, request=request())
        else:
            with pytest.raises(OSError, match="injected failure"):
                pipeline.execute_synthetic_research(**harness, request=request())
    origin = harness["origin"]
    events = origin.verified_events()
    opportunity = next(e for e in events if e.event_type == pipeline.OPPORTUNITY)
    reference = LocalEventReferenceV1(opportunity.event_id, opportunity.event_hash)
    descriptor = tmp_path / "test-reader-locators.json"
    descriptor.write_bytes(
        canonical_json(
            {
                "ledger": str(origin.ledger_path),
                "issuer": str(origin.issuer_instance_id),
                "event_id": str(reference.event_id),
                "event_hash": reference.event_hash,
            }
        )
    )
    ledger_before = origin.ledger_path.read_bytes()
    # The child receives scalar locators only, no pickled/live writer or engine.
    child = subprocess.run(
        [sys.executable, "-c", _CHILD_READER, str(descriptor)],
        cwd=Path(__file__).resolve().parents[2],
        env=_child_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    recovered = json.loads(child.stdout)
    expected = (
        "LOCAL_EXECUTION_COMPLETE" if failure in ("none", "lost_ack") else "UNRESOLVED"
    )
    assert recovered["state"] == expected
    assert (
        recovered["g2_accepted"] is False and recovered["authorizes_trading"] is False
    )
    assert (recovered["result_hash"] is not None) == (
        expected == "LOCAL_EXECUTION_COMPLETE"
    )
    assert origin.ledger_path.read_bytes() == ledger_before
    assert origin.verified_events() == events
    before_count = sum(e.event_type == "m2.evaluation.run.recorded" for e in events)
    assert before_count == (0 if failure == "missing_research" else 1)
    with pytest.raises(DuplicateEventError):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert origin.verified_events() == events


def _child_environment() -> dict[str, str]:
    import os

    # No network/provider/broker invocation is part of the reader program.
    environment = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    extra = [str(root / "tests/unit"), str(root / "src")]
    existing = environment.get("PYTHONPATH")
    if existing:
        extra.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(extra)
    return environment
