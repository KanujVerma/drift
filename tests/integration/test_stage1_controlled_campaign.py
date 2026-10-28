"""Controlled synthetic campaign integration and real execution-boundary tests."""

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_evaluator_engine import (  # noqa: E402
    _buy_ten,
    _engine,
    _run_identity,
)

from drift.domain.evaluator_results import (  # noqa: E402
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.evaluator.engine import SessionEvaluatorEngine  # noqa: E402
from drift.evaluator.session_observer import (  # noqa: E402
    ExecutionAuthorizationV1,
    RebalancePreviewV1,
    SessionObservationV1,
)
from drift.serialization.canonical import content_hash  # noqa: E402


class RecordingObserver:
    def __init__(
        self, verdict: Literal["approve", "reject", "contain"] = "approve"
    ) -> None:
        self.verdict = verdict
        self.observations: list[SessionObservationV1] = []
        self.previews: list[RebalancePreviewV1] = []

    def observe_session(self, observation: SessionObservationV1) -> None:
        self.observations.append(observation)

    def authorize_rebalance(
        self, preview: RebalancePreviewV1
    ) -> ExecutionAuthorizationV1:
        self.previews.append(preview)
        return ExecutionAuthorizationV1(
            preview_hash=preview.financial_hash,
            policy_hash="a" * 64,
            verdict=self.verdict,
            reason="Explicit synthetic test policy",
        )


def run_observed(
    engine: SessionEvaluatorEngine, observer: RecordingObserver | None
) -> EvaluationRunArtifactsV2:
    return engine.run(
        strategy=_buy_ten(),
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        session_observer=observer,
    )


def test_observer_approves_exact_atomic_outcome_and_preserves_financial_book() -> None:
    observer = RecordingObserver()
    actual = run_observed(_engine(), observer)
    legacy = run_observed(_engine(), None)
    assert actual.final_state == legacy.final_state
    assert actual.result.metrics == legacy.result.metrics
    assert len(observer.observations) == len(_engine().bundle.session_clock.sessions)
    assert observer.previews
    for observation in observer.observations:
        assert observation.state.is_marked
        assert observation.trace_prefix[-1].kind == "session_observation"
        assert observation.trace_prefix[-1].book_hash == content_hash(observation.state)
    for preview in observer.previews:
        assert preview.open_prices
        assert preview.decision_session.closed_at < preview.session.opened_at
    assert any(event.kind == "execution_authorization" for event in actual.trace.events)
    assert not any(
        event.kind == "execution_authorization" for event in legacy.trace.events
    )


def test_rejected_open_preview_commits_no_fill_and_preserves_cash() -> None:
    observer = RecordingObserver("reject")
    result = run_observed(_engine(), observer)
    assert result.result.classification == EvaluationClassification.COMPLETE
    assert result.result.metrics.committed_fill_count == 0
    assert result.final_state.holdings == ()
    assert result.final_state.cash_balance == Decimal("10000")
    assert observer.previews[0].outcome.committed_fills


def test_containment_stops_before_any_fill() -> None:
    result = run_observed(_engine(), RecordingObserver("contain"))
    assert result.result.classification == EvaluationClassification.INDETERMINATE
    assert result.result.metrics.committed_fill_count == 0
    assert result.final_state.holdings == ()


def test_wrong_preview_authorization_refuses_before_commit() -> None:
    class WrongPreview(RecordingObserver):
        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            return (
                super()
                .authorize_rebalance(preview)
                .model_copy(update={"preview_hash": "b" * 64})
            )

    with pytest.raises(ValueError, match="PREVIEW"):
        run_observed(_engine(), WrongPreview())


def test_observer_receives_detached_book_and_outcome() -> None:
    class MutatingObserver(RecordingObserver):
        def observe_session(self, observation: SessionObservationV1) -> None:
            object.__setattr__(observation.state, "cash_balance", Decimal("1"))

        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            original_hash = preview.financial_hash
            object.__setattr__(preview.outcome.state, "cash_balance", Decimal("2"))
            return ExecutionAuthorizationV1(
                preview_hash=original_hash,
                policy_hash="a" * 64,
                verdict="approve",
                reason="Mutation cannot change captured accounting",
            )

    actual = run_observed(_engine(), MutatingObserver())
    assert actual.final_state == run_observed(_engine(), None).final_state


def test_observer_failure_cannot_authorize_fill() -> None:
    class FailingObserver(RecordingObserver):
        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            raise OSError("synthetic retention failure")

    with pytest.raises(OSError, match="retention failure"):
        run_observed(_engine(), FailingObserver())


def test_controlled_campaign_retains_actual_original_lifecycle(tmp_path: Path) -> None:
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1

    args = controlled_arguments(tmp_path)
    result = execute_controlled_campaign(**args)
    if result.m0_status == "failed":
        events = args["origin"].verified_events()
        pytest.fail(
            str(
                [
                    (event.event_type, event.payload)
                    for event in events
                    if event.event_id == result.m0_audit_event_id
                ]
            )
        )
    assert result.terminal is not None
    captured = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=result.allocation_id,
        observed_at=args["clock"](),
    )
    kinds = [row.record.kind for row in captured.rows]
    assert kinds[0] == "manifest" and kinds[-1] == "terminal"
    assert kinds.count("grant") == 1 and kinds.count("input_witness") == 1
    assert kinds.count("validation") == 1 and kinds.count("attempt") == 2
    assert kinds.count("research_output") == 1
    assert kinds.count("observation") == 4
    assert kinds.count("execution") >= 1
    assert kinds.count("decision") == 3


def test_controlled_campaign_cold_reader_derives_original_trial(tmp_path: Path) -> None:
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    args = controlled_arguments(tmp_path)
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    report = read_controlled_campaign(
        **{
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "provenance",
                "clock",
            )
        },
        allocation_id=execution.allocation_id,
    )
    assert report.status == "VERIFIED_COMPLETE", report.reasons
    assert report.declared_opportunities == 1
    assert report.trials[0].outcome == "COMPLETED"
    assert report.trials[0].complete_interval
    assert report.trials[0].operating_cost.amount == Decimal("0")
    assert report.trials[0].original_result is not None
    assert not report.g2_accepted


def test_late_cost_correction_changes_only_new_asof_projection(tmp_path: Path) -> None:
    from datetime import timedelta

    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    from drift.intelligence.contracts import StoredArtifactRef
    from drift.intelligence.receipts import create_cost_receipt
    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import (
        CapturedControlledJournalV1,
        append_controlled_cost_correction,
    )
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    args = controlled_arguments(tmp_path)
    checkpoint = args["checkpoints"][0]
    args["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={"cost_amount": Decimal("8")}
                )
            }
        ),
    )
    result = execute_controlled_campaign(**args)
    assert result.m0_status == "completed"
    captured = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=result.allocation_id,
        observed_at=args["clock"](),
    )
    original = next(
        row.record.original
        for row in captured.rows
        if isinstance(row.record, C.CostRecordV1)
    )
    kwargs = {
        key: args[key]
        for key in (
            "origin",
            "campaign",
            "arms",
            "bindings",
            "expected_run_ids",
            "provenance",
            "clock",
        )
    }
    before = read_controlled_campaign(**kwargs, allocation_id=result.allocation_id)
    assert before.status == "VERIFIED_COMPLETE"
    assert before.trials[0].operating_cost.amount == Decimal("8")
    raw = StoredArtifactRef(
        artifact_id="synthetic-actual-bill",
        kind="other",
        content_hash=content_hash({"amount": "9", "attempt": original.attempt_id}),
        location="synthetic://bill/9",
    )
    correction = create_cost_receipt(
        receipt_id="actual-9",
        scope=original.scope,
        category=original.category,
        billing_identity=original.billing_identity,
        amount_basis="actual",
        attempt_id=original.attempt_id,
        raw_evidence_ref=raw,
        recorded_at=BASE + timedelta(hours=1),
        amount="9",
        currency="USD",
        supersedes_receipt_id=original.receipt_id,
    )
    append_controlled_cost_correction(
        origin=args["origin"],
        allocation_id=result.allocation_id,
        checkpoint_id=checkpoint.checkpoint_id,
        correction=correction,
        clock=lambda: BASE + timedelta(hours=2),
    )
    kwargs["clock"] = lambda: BASE + timedelta(hours=3)
    after = read_controlled_campaign(**kwargs, allocation_id=result.allocation_id)
    assert after.status == "VERIFIED_COMPLETE"
    assert after.trials[0].operating_cost.amount == Decimal("9")
    assert len(after.trials[0].operating_cost.original_receipt_hashes) == 2
    assert after.original_result is not None and before.original_result is not None
    assert (
        after.original_result.original_artifacts_bytes
        == before.original_result.original_artifacts_bytes
    )
    assert after.trials[0].net_investment_gain == before.trials[0].net_investment_gain
    historical = read_controlled_campaign(
        **kwargs,
        allocation_id=result.allocation_id,
        as_of_event_hash=before.snapshot_tip.event_hash,
    )
    assert historical.trials == before.trials
    assert historical.snapshot_tip == before.snapshot_tip
    assert historical.accounted_event_hashes == before.accounted_event_hashes


def _carried_456_bundle() -> object:
    """Twelve fictional assets, 456 exchange dates, full M1d source replay.

    Calendar dates are pinned from an exploratory normalized Alpaca read
    independently compared to exchange_calendars; prices and historical
    availability remain fictional, so no scientific qualification is implied.
    Neither the 253/126 windows nor original evaluator is reduced.
    """
    from dataclasses import replace
    from datetime import date

    import exploratory_decision_test_support as reconstruction
    import test_evaluator_engine as fixture
    import test_stage1_original_invocation_end_to_end as cohort
    from observation_test_support import ObservationHarness
    from stage1_calendar_evidence_support import (
        attach_pinned_calendar,
        pinned_source_calendar,
    )
    from test_evaluator_reconstruction import make_policy

    from drift.domain.evaluator_lanes import ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD
    from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
    from drift.evaluator.bundles import assemble_evaluation_input_bundle
    from drift.evaluator.clock import build_scheduled_reconstruction_clock
    from drift.evaluator.reconstruction import (
        build_exploratory_reconstructed_session_observation,
    )

    # Original normalized Alpaca read of 461 sessions, independently matched
    # against exchange_calendars XNYS. No weekday inference, holiday guess or
    # fabricated provider origin is used. The scoring fixture uses the first
    # 456 actually scheduled sessions; five subsequent sessions remain in the
    # witnessed calendar's closed-world hull.
    published_days, early_closes, _ = pinned_source_calendar()
    days = list(published_days[:456])
    assert days[-1] == date(2025, 10, 24)
    observations = []
    sessions = []
    for index, source_day in enumerate(days):
        for ordinal, (security, listing) in enumerate(
            zip(cohort.SECURITIES, cohort.LISTINGS, strict=True)
        ):
            # Stay within this source fixture's original 99/101 OHLC bounds.
            # The first six have both stronger momentum and greater volatility.
            units = index * (2 if ordinal < 6 else 1)
            if ordinal < 6:
                units += 4 * (index % 2)
            price = Decimal(1000000 + units) / Decimal(10000)
            harness = ObservationHarness(
                session_date=source_day,
                security_id=security,
                listing_id=listing,
                close=format(price, "f"),
                available_at=source_day.isoformat() + "T22:30:00Z",
            )
            # This exploratory corpus does not claim a coverage certification.
            # The generic helper's January-2026 coverage cannot describe 2024/25.
            harness.use_unproven_observation_coverage(mode="absent")
            harness.attach_sessions(
                schedule_state=(
                    "early_close" if source_day in early_closes else "regular"
                ),
                realized_outcome="missing",
            )
            if index == 0 and ordinal == 0:
                # One original M1d context brings the entire independently
                # witnessed regular-session calendar into the replay inputs.
                # The common coverage is retained once, not copied 5,472 times.
                attach_pinned_calendar(harness)
            harness.context = replace(
                harness.context,
                supporting_artifacts={
                    **harness.context.supporting_artifacts,
                    **fixture.CA_COVERAGE_SUPPORT,
                },
            )
            query = harness.outcome(
                economic_horizon="2026-10-24T00:00:00Z",
                evidence_vintage_cutoff="2026-10-24T00:00:00Z",
                session_date=source_day.isoformat(),
            )
            observation = build_exploratory_reconstructed_session_observation(
                query,
                harness.context,
                reconstruction.cohort_of(cohort.SECURITIES),
                make_policy(),
            )
            reconstruction._SOURCE_REQUESTS[observation.reconstruction_hash] = (
                query,
                harness.context,
            )
            session = build_scheduled_reconstruction_clock(
                (query,), harness.context
            ).sessions[0]
            observations.append(observation)
            if ordinal == 0:
                sessions.append(session)
        if index % 60 == 0:
            print("controlled: reconstructed source session", index, flush=True)
    return assemble_evaluation_input_bundle(
        evaluation_interval=fixture._interval(),
        session_clock=reconstruction.merged_scheduled_clock(sessions),
        security_identities=tuple(
            SecurityV1(schema_version="1", security_id=security)
            for security in cohort.SECURITIES
        ),
        listing_identities=tuple(
            ListingV1(schema_version="1", listing_id=listing, venue=ListingVenue.XNYS)
            for listing in cohort.LISTINGS
        ),
        exploratory_reconstructed_observations=tuple(observations),
        corporate_action_coverage=fixture.quiet_coverage(
            cohort.SECURITIES, days[0], days[-1]
        ),
        dataset_limitations=(ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD,),
    )


def _carried_arguments(root: Path, bundle: object, arm: str) -> dict[str, object]:
    import json
    from dataclasses import fields
    from datetime import UTC, date, datetime, timedelta
    from typing import cast
    from uuid import uuid7

    import test_evaluator_engine as fixture
    import test_stage1_original_invocation_end_to_end as cohort
    from test_stage1_campaign_config import (
        make_golden_arm_b,
        make_golden_arm_r,
        make_golden_bindings,
        make_golden_campaign,
    )
    from test_stage1_synthetic_research_execution import BASE, Tick

    from drift.domain.evaluator_bundles import EvaluationInputBundleV1
    from drift.experiments.stage1_campaign_config import (
        DataWindowV1,
        ScoringWindowV1,
        build_arm_spec,
        build_campaign_spec,
    )
    from drift.experiments.stage1_trial_provenance import (
        build_stage1_trial_provenance_snapshot,
    )
    from drift.intelligence.contracts import (
        ArtifactReference,
        ResearchContext,
        compute_record_hash,
    )
    from drift.ledger.stage1_synthetic_account_receipts import (
        ConfiguredLocalSyntheticOriginV1,
        LocalSyntheticAccountReceiptStoreV1,
    )
    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_synthetic_account_lifecycle import (
        Stage1SyntheticAccountLifecycleV1,
    )
    from drift.loop.stage1_synthetic_research_execution import (
        installed_registry_reference,
        original_portfolio_reference,
        synthetic_universe_reference,
    )

    assert isinstance(bundle, EvaluationInputBundleV1)
    root.mkdir(parents=True, exist_ok=True)
    original_arms = (make_golden_arm_b(), make_golden_arm_r())
    arms = tuple(
        build_arm_spec(
            **(
                {
                    f.name: getattr(a, f.name)
                    for f in fields(a)
                    if f.name not in ("schema_version", "arm_spec_fingerprint")
                }
                | {
                    "mandate_reference": "fixture://controlled-explicit-caps-v1",
                    "model_configuration_reference": (
                        "fixture://scripted-fixed-scores-not-real-model-v1"
                        if a.arm_id == "ARM-B"
                        else "NONE"
                    ),
                }
            )
        )
        for a in original_arms
    )
    template = make_golden_campaign()
    kwargs: dict[str, Any] = {
        f.name: getattr(template, f.name)
        for f in fields(template)
        if f.name not in ("schema_version", "campaign_spec_fingerprint")
    }
    kwargs.update(
        study_protocol_revision="fixture://controlled-456-engineering-v1",
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        arm_spec_references=tuple(a.arm_spec_fingerprint for a in arms),
        data_window=DataWindowV1(
            "2024-01-02", "2025-10-24", "fixture://xnys-456-normalized-source-backed-v1"
        ),
        scoring_window=ScoringWindowV1("SC-001", "SC-077", True),
        portfolio_mandate_reference="fixture://controlled-explicit-caps-v1",
        model_and_prompt_policy_reference="fixture://scripted-fixed-scores-not-real-model-v1",
        authorization_evidence={
            "synthetic_fixture_only": True,
            "calendar_source": (
                "Alpaca normalized connector snapshot, 461 returned days"
            ),
            "calendar_source_qualified": False,
            "reviewer_receipts": [],
            "input_bundle_hash": bundle.bundle_hash,
            "session_clock_hash": bundle.session_clock.clock_hash,
            "fictional_security_labels": list(cohort.TICKERS),
            "scientifically_qualified": False,
        },
    )
    campaign = build_campaign_spec(**kwargs)
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
    origin = ConfiguredLocalSyntheticOriginV1(root / "original.sqlite3", uuid7())
    clock = Tick()
    store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=clock)
    account = Stage1SyntheticAccountLifecycleV1(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        store=store,
    )
    import exploratory_decision_test_support as reconstruction

    from drift.evaluator.engine import SessionEvaluatorEvidence

    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=reconstruction.exploratory_admission(bundle),
        protocol=fixture._protocol(warmup=253, cash="10000"),
        cost_model=fixture._cost_model(notional_bps="1", slippage_bps="1"),
        evidence=SessionEvaluatorEvidence(
            exploratory_cohort=reconstruction.cohort_of(cohort.SECURITIES),
            exploratory_reconstruction_replay=reconstruction.replay_of(
                bundle.exploratory_reconstructed_observations
            ),
            listing_role_records=tuple(
                fixture._role_record(security, listing, suffix=1000 + index)
                for index, (security, listing) in enumerate(
                    zip(cohort.SECURITIES, cohort.LISTINGS, strict=True)
                )
            ),
        ),
        book_currency_namespace="ISO4217",
        book_currency_code="USD",
    )
    engine.prepare_opening_book(lifecycle=account)
    original = account.verified_original()
    data = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/adaptive_research/research_v1.json"
        ).read_text()
    )["fixtures"]["F01"]
    data.pop("record_hash")
    data["context_id"] = provenance.scope.trial_id + ":context"
    data["scope"] = dict(
        experiment_id=campaign.campaign_id,
        arm_id=arm,
        account_id=original.fields.portfolio_account_id,
        campaign_ref=dict(
            id=campaign.campaign_id,
            version=campaign.schema_version,
            sha256=campaign.campaign_spec_fingerprint,
        ),
    )
    cutoff = bundle.session_clock.sessions[252].closed_at
    data["decision_cutoff"] = cutoff
    data["memory_cutoff"] = cutoff
    data["built_at"] = BASE + timedelta(seconds=2)
    data["review_started_at"] = BASE + timedelta(seconds=3)
    data["portfolio_ref"] = original_portfolio_reference(original).model_dump(
        mode="python"
    )
    data["registry_ref"] = installed_registry_reference().model_dump(mode="python")
    data["universe_ref"] = synthetic_universe_reference(cohort.SECURITIES).model_dump(
        mode="python"
    )
    data["record_hash"] = compute_record_hash(data)
    context = ResearchContext.model_validate(data)
    clock.at = BASE + timedelta(seconds=4)
    mandate = C.SyntheticMandateV1(
        policy_id="fixture://controlled-explicit-caps-v1",
        revision="1",
        securities=tuple(
            C.SecurityMandateV1(
                security_id=s, asset_class="synthetic", maximum_fraction=Decimal("0.20")
            )
            for s in cohort.SECURITIES
        ),
        classes=(
            C.ClassMandateV1(asset_class="synthetic", maximum_fraction=Decimal("1")),
        ),
        maximum_gross_fraction=Decimal("1"),
        maximum_turnover_fraction=Decimal("2"),
        maximum_price_age_sessions=0,
        paused=False,
        execution_knowledge="RESOLVED",
    )
    # Scoring starts July 9 at index379. July's month end is before the
    # required 21-session observation boundary at index399 (August 6).
    # Both later eligible month ends must remain declared in the full window.
    calendar_dates = tuple(
        s.session_key.local_date for s in bundle.session_clock.sessions
    )
    august = calendar_dates.index(date(2025, 8, 29))
    september = calendar_dates.index(date(2025, 9, 30))
    assert (august, september) == (416, 437)
    assert calendar_dates[378] == date(2025, 7, 8)
    assert calendar_dates[399] == date(2025, 8, 6)
    checkpoints = []
    for number, (index, family) in enumerate(((august, "B4"), (september, "B5")), 1):
        planned = C.ControlledResearchFixtureV1(
            mode="scripted_fixture" if arm == "ARM-B" else "conventional_fixture",
            disposition="propose",
            selected_family=cast(C.Family, family) if arm == "ARM-B" else None,
            candidate_families=() if arm == "ARM-B" else ("B3", "B4", "B5"),
            scores={}
            if arm == "ARM-B"
            else {f: Decimal("2" if f == family else "1") for f in ("B3", "B4", "B5")},
            cost_amount=Decimal("0"),
        )
        checkpoints.append(
            C.ControlledCheckpointV1(
                checkpoint_id=f"CKPT-{number:03d}",
                session_index=index,
                decision_cutoff=bundle.session_clock.sessions[index].closed_at,
                not_before=BASE,
                expires_at=BASE + timedelta(days=1),
                research_budget_usd=Decimal("10"),
                fixture=planned,
            )
        )
    return dict(
        origin=origin,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        account=account,
        engine=engine,
        context=context,
        clock=clock,
        mandate=mandate,
        checkpoints=tuple(checkpoints),
        initial_decision_index=378,
        coverage="STAGE1_253_126_MONTHLY",
        clock_policy=ArtifactReference(
            id="synthetic-tick", version="1", sha256="1" * 64
        ),
    )


def test_full_456_session_carried_br_campaign_has_real_monthly_switches(
    tmp_path: Path,
) -> None:
    from datetime import date

    from drift.ledger.stage1_synthetic_account_receipts import (
        ALLOCATION,
        CLAIM,
        CONSUMED,
    )
    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.loop.stage1_controlled_readback import (
        compare_controlled_campaigns,
        read_controlled_campaign,
    )

    bundle = _carried_456_bundle()
    print("controlled: original 456-session input bundle constructed", flush=True)
    reports = []
    campaign_inputs: list[dict[str, Any]] = []
    for arm in ("ARM-B", "ARM-R"):
        args: dict[str, Any] = _carried_arguments(tmp_path / arm, bundle, arm)
        executed = execute_controlled_campaign(**args)
        if executed.m0_status != "completed":
            pytest.fail(
                str(
                    [
                        (e.event_type, e.payload)
                        for e in args["origin"].verified_events()
                        if e.event_id == executed.m0_audit_event_id
                    ]
                )
            )
        print("controlled: executed", arm, flush=True)
        journal = CapturedControlledJournalV1(
            origin=args["origin"],
            allocation_id=executed.allocation_id,
            observed_at=args["clock"](),
        )
        original_events = args["origin"].verified_events()
        assert sum(e.event_type == ALLOCATION for e in original_events) == 1
        assert sum(e.event_type == CLAIM for e in original_events) == 1
        assert sum(e.event_type == CONSUMED for e in original_events) == 1
        decisions = [
            r.record
            for r in journal.rows
            if isinstance(r.record, C.DecisionRecordV1)
            and r.record.checkpoint_id is not None
        ]
        assert [
            (d.previous_family, d.staged_family, d.disposition) for d in decisions
        ] == [("B3", "B4", "SELECTED"), ("B4", "B5", "SELECTED")]
        assert [d.session_index for d in decisions] == [416, 437]
        checkpoint_execution = [
            preview
            for row in journal.rows
            if isinstance(row.record, C.ExecutionRecordV1)
            for preview in (row.record.preview.parse(RebalancePreviewV1),)
            if preview.session_index in (417, 438)
        ]
        assert [
            (preview.session_index, preview.session.session_key.local_date)
            for preview in checkpoint_execution
        ] == [(417, date(2025, 9, 2)), (438, date(2025, 10, 1))]
        inputs = [
            r.record
            for r in journal.rows
            if isinstance(r.record, C.InputWitnessRecordV1)
        ]
        assert len(inputs[1].feedback) == 1 and inputs[1].feedback[0].arm_id == arm
        kwargs = {
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "provenance",
                "clock",
            )
        }
        report = read_controlled_campaign(
            **kwargs, allocation_id=executed.allocation_id
        )
        assert report.status == "VERIFIED_COMPLETE", report.reasons
        assert [t.selected_family for t in report.trials] == ["B4", "B5"]
        assert all(
            t.complete_interval and t.outcome == "COMPLETED" for t in report.trials
        )
        assert report.original_result is not None
        assert (
            report.original_result.original_artifacts.result.metrics.committed_fill_count
            > 12
        )
        assert (
            report.original_result.original_artifacts.final_state.cumulative_transaction_costs
            > 0
        )
        assert report.trials[0].end_nav == report.trials[1].start_nav
        assert report.trials[0].start_nav != Decimal("10000")
        assert report.independent_account_count == 1
        recovered = _fresh_controlled_read(
            args, executed.allocation_id, tmp_path / f"cold-{arm}.json"
        )
        assert recovered["status"] == "VERIFIED_COMPLETE"
        assert recovered["result_hash"] == report.original_result.result_hash
        assert recovered["authorizes_trading"] is False
        recovered_trials = recovered["trials"]
        assert isinstance(recovered_trials, list) and len(recovered_trials) == 2
        campaign_inputs.append(args)
        reports.append(report)
        print("controlled: original replay verified", arm, flush=True)
    assert reports[0].allocation_id != reports[1].allocation_id
    assert reports[0].trials[0].account_id != reports[1].trials[0].account_id
    assert (
        reports[0].original_result is not None
        and reports[1].original_result is not None
    )
    assert (
        reports[0].original_result.invocation_binding
        != reports[1].original_result.invocation_binding
    )
    assert (
        reports[0].trials[0].net_investment_gain
        == reports[1].trials[0].net_investment_gain
    )

    compared = compare_controlled_campaigns(
        test_origin=campaign_inputs[0]["origin"],
        comparator_origin=campaign_inputs[1]["origin"],
        test_allocation_id=reports[0].allocation_id,
        comparator_allocation_id=reports[1].allocation_id,
        campaign=campaign_inputs[0]["campaign"],
        arms=campaign_inputs[0]["arms"],
        bindings=campaign_inputs[0]["bindings"],
        expected_run_ids=campaign_inputs[0]["expected_run_ids"],
        test_provenance=campaign_inputs[0]["provenance"],
        comparator_provenance=campaign_inputs[1]["provenance"],
        clock=campaign_inputs[0]["clock"],
    )
    assert compared.test.economics.complete and compared.comparator.economics.complete
    assert compared.test.economics.initial_net_nav == Decimal("10000")
    assert compared.independent_paired_run_count == 1
    assert compared.independent_account_count == 2
    assert compared.economic_advantage.state == "KNOWN"
    assert compared.economic_advantage.value == Decimal("0")
    assert compared.scientific_conclusion == "INSUFFICIENT_INDEPENDENT_QUALIFIED_RUNS"


_COLD_CONTROLLED_READER = r"""
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID
from pydantic import TypeAdapter
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1, RunAccountBindingV1, PrimaryComparisonV1, DataWindowV1,
    SessionWindowV1, ScoringWindowV1, DecisionScheduleV1, build_campaign_spec,
)
from drift.experiments.stage1_trial_provenance import Stage1TrialProvenanceSnapshotV1
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_controlled_readback import read_controlled_campaign
from drift.serialization.canonical import canonical_json
raw = json.loads(Path(sys.argv[1]).read_text())
def decode(cls, key):
    return TypeAdapter(cls).validate_json(canonical_json(raw[key]))
campaign_data = dict(raw["campaign"])
original_fingerprint = campaign_data.pop("campaign_spec_fingerprint")
campaign_data.pop("schema_version")
for key, cls in (
    ("primary_comparison", PrimaryComparisonV1), ("data_window", DataWindowV1),
    ("warmup_window", SessionWindowV1), ("observation_window", SessionWindowV1),
    ("scoring_window", ScoringWindowV1), ("decision_schedule", DecisionScheduleV1),
):
    campaign_data[key] = cls(**campaign_data[key])
for key in ("created_at", "frozen_at"):
    campaign_data[key] = datetime.fromisoformat(campaign_data[key])
campaign = build_campaign_spec(**campaign_data)
assert campaign.campaign_spec_fingerprint == original_fingerprint
report = read_controlled_campaign(
    origin=ConfiguredLocalSyntheticOriginV1(Path(raw["ledger"]), UUID(raw["issuer"])),
    allocation_id=UUID(raw["allocation"]),
    campaign=campaign,
    arms=decode(tuple[ArmSpecV1, ...], "arms"),
    bindings=decode(tuple[RunAccountBindingV1, ...], "bindings"),
    expected_run_ids=tuple(raw["expected_run_ids"]),
    provenance=decode(Stage1TrialProvenanceSnapshotV1, "provenance"),
    clock=lambda: datetime.fromisoformat(raw["observed"]),
)
print(canonical_json({"status": report.status, "reasons": report.reasons,
    "trials": report.trials, "accounts": report.independent_account_count,
    "result_hash": (
        report.original_result.result_hash if report.original_result else None
    ),
    "authorizes_trading": report.authorizes_trading}).decode())
"""


def _fresh_controlled_read(
    args: dict[str, Any], allocation: object, path: Path
) -> dict[str, object]:
    import json
    import subprocess
    from dataclasses import asdict
    from datetime import timedelta

    from test_stage1_synthetic_research_execution import BASE

    from drift.ledger.stage1_synthetic_account_receipts import (
        ConfiguredLocalSyntheticOriginV1,
    )
    from drift.serialization.canonical import canonical_json

    origin = args["origin"]
    assert isinstance(origin, ConfiguredLocalSyntheticOriginV1)
    from drift.experiments.stage1_campaign_config import _campaign_preimage

    data: dict[str, Any] = {
        "campaign": _campaign_preimage(args["campaign"])
        | {"campaign_spec_fingerprint": args["campaign"].campaign_spec_fingerprint},
        "arms": [asdict(arm) for arm in args["arms"]],
        "bindings": [asdict(binding) for binding in args["bindings"]],
        "expected_run_ids": args["expected_run_ids"],
        "provenance": asdict(args["provenance"]),
    }
    data.update(
        ledger=str(origin.ledger_path),
        issuer=str(origin.issuer_instance_id),
        allocation=str(allocation),
        observed=(BASE + timedelta(days=2)).isoformat(),
    )
    path.write_bytes(canonical_json(data))
    before = origin.ledger_path.read_bytes()
    child = subprocess.run(
        [sys.executable, "-B", "-c", _COLD_CONTROLLED_READER, str(path)],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=180,
        check=True,
    )
    assert origin.ledger_path.read_bytes() == before
    return dict(json.loads(child.stdout))


def test_controlled_cold_read_in_new_process_never_needs_live_writer(
    tmp_path: Path,
) -> None:
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign

    args = controlled_arguments(tmp_path)
    executed = execute_controlled_campaign(**args)
    assert executed.m0_status == "completed"
    del args["account"], args["engine"]
    recovered = _fresh_controlled_read(
        args, executed.allocation_id, tmp_path / "read.json"
    )
    assert recovered["status"] == "VERIFIED_COMPLETE"
    assert recovered["accounts"] == 1
    assert recovered["result_hash"]
    assert recovered["authorizes_trading"] is False


@pytest.mark.parametrize(
    ("case", "expected_outcome", "expected_reason", "expected_fills"),
    [
        ("expired", "NO_ATTEMPT", "EXPIRED", 1),
        ("not_before", "NO_ATTEMPT", "NOT_YET_VALID", 1),
        ("revoked", "NO_ATTEMPT", "REVOKED", 1),
        ("budget", "NO_ATTEMPT", "BUDGET_UNAVAILABLE", 1),
        ("B4", "NO_ATTEMPT", "INPUT_UNAVAILABLE", 1),
        ("B5", "NO_ATTEMPT", "INPUT_UNAVAILABLE", 1),
        ("timeout", "FAILED_RESEARCH", "RESEARCH_TIMEOUT", 1),
        ("malformed", "FAILED_RESEARCH", "RESEARCH_MALFORMED_OUTPUT", 1),
        ("hold", "RETAINED", "RESEARCH_HOLD", 1),
        ("abstain", "RETAINED", "RESEARCH_ABSTAIN", 1),
        ("unavailable", "RETAINED", "RESEARCH_UNAVAILABLE", 1),
        ("paused", "REFUSED", "PAUSED", 0),
        ("security", "REFUSED", "SECURITY_CAP", 0),
        ("class", "REFUSED", "CLASS_CAP", 0),
        ("gross", "REFUSED", "GROSS_CAP", 0),
        ("turnover", "REFUSED", "TURNOVER_CAP", 0),
        ("UNKNOWN", "UNRESOLVED", "ORIGINAL_OPPORTUNITY_UNAVAILABLE", 0),
        ("PARTIAL", "UNRESOLVED", "ORIGINAL_OPPORTUNITY_UNAVAILABLE", 0),
    ],
)
def test_actual_controlled_failure_paths_keep_original_lifecycle_and_costs(
    tmp_path: Path,
    case: str,
    expected_outcome: str,
    expected_reason: str,
    expected_fills: int,
) -> None:
    from datetime import timedelta

    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    args = controlled_arguments(tmp_path)
    checkpoint = args["checkpoints"][0]
    fixture = checkpoint.fixture
    if case == "expired":
        checkpoint = checkpoint.model_copy(
            update={"expires_at": BASE + timedelta(seconds=1)}
        )
    elif case == "not_before":
        checkpoint = checkpoint.model_copy(
            update={
                "not_before": BASE + timedelta(days=1),
                "expires_at": BASE + timedelta(days=2),
            }
        )
    elif case == "revoked":
        checkpoint = checkpoint.model_copy(
            update={"revoked_at": BASE + timedelta(seconds=1)}
        )
    elif case == "budget":
        checkpoint = checkpoint.model_copy(
            update={
                "research_budget_usd": Decimal(0),
                "fixture": fixture.model_copy(update={"cost_amount": Decimal(1)}),
            }
        )
    elif case in ("B4", "B5"):
        checkpoint = checkpoint.model_copy(
            update={
                "fixture": fixture.model_copy(update={"selected_family": case}),
            }
        )
    elif case == "timeout":
        checkpoint = checkpoint.model_copy(
            update={
                "fixture": fixture.model_copy(update={"should_timeout": True}),
            }
        )
    elif case == "malformed":
        checkpoint = checkpoint.model_copy(
            update={
                "fixture": fixture.model_copy(update={"malformed_output": "not JSON"}),
            }
        )
    elif case in ("hold", "abstain", "unavailable"):
        checkpoint = checkpoint.model_copy(
            update={
                "fixture": fixture.model_copy(
                    update={"disposition": case, "selected_family": None}
                ),
            }
        )
    policy = args["mandate"]
    if case == "paused":
        args["mandate"] = policy.model_copy(update={"paused": True})
    elif case in ("UNKNOWN", "PARTIAL"):
        args["mandate"] = policy.model_copy(update={"execution_knowledge": case})
    elif case == "security":
        args["mandate"] = policy.model_copy(
            update={
                "securities": tuple(
                    rule.model_copy(update={"maximum_fraction": Decimal("0.01")})
                    for rule in policy.securities
                )
            }
        )
    elif case == "class":
        args["mandate"] = policy.model_copy(
            update={
                "classes": tuple(
                    rule.model_copy(update={"maximum_fraction": Decimal("0.01")})
                    for rule in policy.classes
                )
            }
        )
    elif case == "gross":
        args["mandate"] = policy.model_copy(
            update={"maximum_gross_fraction": Decimal("0.01")}
        )
    elif case == "turnover":
        args["mandate"] = policy.model_copy(
            update={"maximum_turnover_fraction": Decimal(0)}
        )
    args["checkpoints"] = (checkpoint,)
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    report = read_controlled_campaign(
        **{
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "provenance",
                "clock",
            )
        },
        allocation_id=execution.allocation_id,
    )
    trial = report.trials[0]
    assert (trial.outcome, trial.reason) == (expected_outcome, expected_reason)
    assert report.original_result is not None
    assert (
        report.original_result.original_artifacts.result.metrics.committed_fill_count
        == expected_fills
    )
    journal = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    )
    attempts = [
        r.record for r in journal.rows if isinstance(r.record, C.AttemptRecordV1)
    ]
    if expected_outcome == "NO_ATTEMPT":
        assert not attempts
        assert trial.operating_cost.amount is None and trial.economic_gain is None
    elif case in ("UNKNOWN", "PARTIAL"):
        assert not attempts
        assert report.status == "UNRESOLVED" and not report.economics.complete
        assert any(isinstance(r.record, C.ContainmentRecordV1) for r in journal.rows)
    else:
        assert len(attempts) == 2 and attempts[0].original.status == "started"
    if case == "timeout":
        assert trial.operating_cost.status == "UNAVAILABLE"
    if case in ("hold", "abstain", "unavailable"):
        assert trial.selected_family is None
        assert trial.complete_interval
        assert trial.operating_cost.status == "VERIFIED_ZERO"
        decision = next(
            row.record
            for row in journal.rows
            if isinstance(row.record, C.DecisionRecordV1)
            and row.record.checkpoint_id == checkpoint.checkpoint_id
        )
        assert decision.disposition == "RETAINED"
        assert decision.previous_family == decision.staged_family == "B3"
        execution_record, preview = next(
            (row.record, preview)
            for row in journal.rows
            if isinstance(row.record, C.ExecutionRecordV1)
            for preview in (row.record.preview.parse(RebalancePreviewV1),)
            if preview.session_index == checkpoint.session_index + 1
        )
        assert execution_record.authorization.verdict == "approve"
        assert preview.outcome.committed_fills == ()
    if expected_fills:
        assert report.original_result.original_artifacts.final_state.holdings
    assert not report.authorizes_trading and not report.scientifically_qualified


def test_retained_decision_prefix_awaits_original_next_open_execution(
    tmp_path: Path,
) -> None:
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    args = controlled_arguments(tmp_path)
    checkpoint = args["checkpoints"][0]
    args["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={"disposition": "hold", "selected_family": None}
                )
            }
        ),
    )
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    journal = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    )
    decision = next(
        row
        for row in journal.rows
        if isinstance(row.record, C.DecisionRecordV1)
        and row.record.checkpoint_id == checkpoint.checkpoint_id
    )
    kwargs = {
        key: args[key]
        for key in (
            "origin",
            "campaign",
            "arms",
            "bindings",
            "expected_run_ids",
            "provenance",
            "clock",
        )
    }
    before = args["origin"].ledger_path.read_bytes()
    pending = read_controlled_campaign(
        **kwargs,
        allocation_id=execution.allocation_id,
        as_of_event_hash=decision.event.event_hash,
    )
    assert pending.trials[0].outcome == "UNRESOLVED"
    assert pending.trials[0].reason == "ORIGINAL_EXECUTION_UNAVAILABLE"
    assert not pending.trials[0].complete_interval
    assert pending.trials[0].selected_family is None
    assert pending.trials[0].operating_cost.status == "VERIFIED_ZERO"
    complete = read_controlled_campaign(**kwargs, allocation_id=execution.allocation_id)
    assert complete.trials[0].outcome == "RETAINED"
    assert args["origin"].ledger_path.read_bytes() == before


def test_next_open_expiry_preserves_original_execution_refusal_reason(
    tmp_path: Path,
) -> None:
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    # Derive the boundary from a real execution using the same declared tick
    # clock, rather than depending on an unexplained number of clock calls.
    baseline = controlled_arguments(tmp_path / "baseline")
    first = execute_controlled_campaign(**baseline)
    assert first.m0_status == "completed"
    original = CapturedControlledJournalV1(
        origin=baseline["origin"],
        allocation_id=first.allocation_id,
        observed_at=baseline["clock"](),
    )
    next_open = next(
        row
        for row in original.rows
        if isinstance(row.record, C.ExecutionRecordV1)
        and row.record.preview.parse(RebalancePreviewV1).session_index
        == baseline["checkpoints"][0].session_index + 1
    )

    args = controlled_arguments(tmp_path / "expires-at-next-open")
    checkpoint = args["checkpoints"][0].model_copy(
        update={"expires_at": next_open.event.timestamp}
    )
    args["checkpoints"] = (checkpoint,)
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    journal = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    )
    decision = next(
        row
        for row in journal.rows
        if isinstance(row.record, C.DecisionRecordV1)
        and row.record.checkpoint_id == checkpoint.checkpoint_id
    )
    rejected = next(
        row
        for row in journal.rows
        if isinstance(row.record, C.ExecutionRecordV1)
        and row.record.preview.parse(RebalancePreviewV1).session_index
        == checkpoint.session_index + 1
    )
    assert isinstance(decision.record, C.DecisionRecordV1)
    assert decision.record.disposition == "SELECTED"
    assert decision.event.timestamp < checkpoint.expires_at <= rejected.event.timestamp
    assert isinstance(rejected.record, C.ExecutionRecordV1)
    assert rejected.record.authorization.verdict == "reject"
    assert (
        rejected.record.authorization.reason
        == "PROPOSAL_EXPIRED_OR_REVOKED_BEFORE_EXECUTION"
    )
    before = args["origin"].ledger_path.read_bytes()
    report = read_controlled_campaign(
        **{
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "provenance",
                "clock",
            )
        },
        allocation_id=execution.allocation_id,
    )
    assert report.original_result is not None
    artifacts = report.original_result.original_artifacts
    assert artifacts.result.metrics.committed_fill_count == 1
    assert not any(
        event.kind == "fill" and event.session_index == checkpoint.session_index + 1
        for event in artifacts.trace.events
    )
    trial = report.trials[0]
    assert trial.outcome == "REFUSED"
    assert trial.reason == rejected.record.authorization.reason
    assert trial.selected_family is None
    assert trial.operating_cost.status == "VERIFIED_ZERO"
    assert args["origin"].ledger_path.read_bytes() == before
    assert not report.authorizes_trading and not report.scientifically_qualified


@pytest.mark.parametrize("case", ("propose", "hold", "timeout", "expired"))
def test_next_open_current_book_containment_is_unresolved(
    tmp_path: Path, case: str
) -> None:
    from datetime import timedelta

    import test_evaluator_engine as fixture
    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    from drift.loop import stage1_controlled_contracts as C
    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
    from drift.loop.stage1_controlled_readback import read_controlled_campaign

    members = (
        (fixture.SEC_A, fixture.LISTING_A),
        (fixture.SEC_B, fixture.LISTING_B),
    )
    bundle = fixture._bundle(
        decision_views=tuple(
            fixture._decision_view(security, day, listing_id=listing)
            for day in fixture.DAYS[1:]
            for security, listing in members
        ),
        accounting_views=tuple(
            fixture._accounting_view(
                security,
                day,
                listing_id=listing,
                open_price="200"
                if security == fixture.SEC_A and day == fixture.DAY_3
                else None,
            )
            for day in fixture.DAYS
            for security, listing in members
        ),
        eligibilities=tuple(
            fixture._eligibility(security, listing) for security, listing in members
        ),
    )
    args = controlled_arguments(tmp_path, engine=fixture._engine(bundle=bundle))
    policy = args["mandate"]
    args["mandate"] = policy.model_copy(
        update={
            "securities": tuple(
                rule.model_copy(update={"maximum_fraction": Decimal("0.6")})
                for rule in policy.securities
            )
        }
    )
    checkpoint = args["checkpoints"][0]
    if case == "expired":
        checkpoint = checkpoint.model_copy(
            update={"expires_at": BASE + timedelta(seconds=1)}
        )
    args["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={
                        "disposition": "hold" if case == "hold" else "propose",
                        "selected_family": None if case == "hold" else "B3",
                        "should_timeout": case == "timeout",
                    }
                )
            }
        ),
    )
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    checkpoint = args["checkpoints"][0]
    journal = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    )
    decision = next(
        row.record
        for row in journal.rows
        if isinstance(row.record, C.DecisionRecordV1)
        and row.record.checkpoint_id == checkpoint.checkpoint_id
    )
    assert decision.disposition == ("SELECTED" if case == "propose" else "RETAINED")
    contained = next(
        row.record
        for row in journal.rows
        if isinstance(row.record, C.ExecutionRecordV1)
        and row.record.preview.parse(RebalancePreviewV1).session_index
        == checkpoint.session_index + 1
    )
    assert contained.authorization.verdict == "contain"
    assert contained.authorization.reason == "SECURITY_CAP"
    before = args["origin"].ledger_path.read_bytes()
    report = read_controlled_campaign(
        **{
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "provenance",
                "clock",
            )
        },
        allocation_id=execution.allocation_id,
    )
    assert report.original_result is not None
    artifacts = report.original_result.original_artifacts
    assert artifacts.result.classification == EvaluationClassification.INDETERMINATE
    assert artifacts.final_state.mark is None
    assert len(artifacts.final_state.holdings) == 2
    assert artifacts.final_state.net_asset_value == Decimal("0")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10500")
    assert artifacts.result.metrics.committed_fill_count == 2
    assert not any(
        event.kind == "fill" and event.session_index == checkpoint.session_index + 1
        for event in artifacts.trace.events
    )
    trial = report.trials[0]
    assert trial.outcome == "UNRESOLVED"
    assert trial.reason == "SECURITY_CAP"
    assert trial.selected_family is None and not trial.complete_interval
    assert trial.net_investment_gain is None and trial.economic_gain is None
    assert trial.operating_cost.status == (
        "UNAVAILABLE" if case in ("timeout", "expired") else "VERIFIED_ZERO"
    )
    attempts = [
        row.record.original
        for row in journal.rows
        if isinstance(row.record, C.AttemptRecordV1)
    ]
    if case == "timeout":
        assert [attempt.status for attempt in attempts] == ["started", "failed"]
    elif case == "expired":
        assert not attempts
        assert any(isinstance(row.record, C.NoAttemptRecordV1) for row in journal.rows)
    assert report.status == "UNRESOLVED" and not report.economics.complete
    assert "ORIGINAL_EXECUTION_CONTAINED:3" in report.reasons
    assert args["origin"].ledger_path.read_bytes() == before
    assert not report.authorizes_trading and not report.scientifically_qualified


def test_actual_next_open_gap_is_checked_against_exact_target_cap(
    tmp_path: Path,
) -> None:
    import test_evaluator_engine as fixture
    from test_stage1_controlled_contracts import controlled_arguments

    from drift.loop.stage1_controlled_campaign import authorize_preview

    base_policy = controlled_arguments(tmp_path)["mandate"]
    policy = base_policy.model_copy(
        update={
            "securities": tuple(
                rule.model_copy(update={"maximum_fraction": Decimal("0.15")})
                for rule in base_policy.securities
            )
        }
    )
    bundle = fixture._bundle(
        accounting_views=tuple(
            fixture._accounting_view(
                fixture.SEC_A,
                day,
                open_price="200.00" if day == fixture.DAY_2 else None,
            )
            for day in fixture.DAYS
        )
    )

    class ActualMandateObserver(RecordingObserver):
        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            self.previews.append(preview)
            return authorize_preview(policy, preview)

    observer = ActualMandateObserver()
    observed = run_observed(fixture._engine(bundle=bundle), observer)
    legacy = run_observed(fixture._engine(bundle=bundle), None)
    first = observer.previews[0]
    assert first.outcome.committed_fills[0].unadjusted_open_price == Decimal("200")
    assert authorize_preview(policy, first).reason == "SECURITY_CAP"
    # A later separately declared close can legitimately produce a new accepted
    # intent. The refused gapped open itself must commit nothing.
    assert any(
        event.kind == "fill" and event.session_index == first.session_index
        for event in legacy.trace.events
    )
    assert observer.observations[first.session_index].state.cash_balance == Decimal(
        "10000"
    )
    assert not any(
        event.kind == "fill" and event.session_index == first.session_index
        for event in observed.trace.events
    )


def test_whole_campaign_comparison_includes_initial_period_and_distinct_accounts(
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_readback import compare_controlled_campaigns

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
        clock=lambda: BASE + timedelta(days=2),
    )
    compared = compare_controlled_campaigns(**kwargs)
    assert compared.test.economics.complete and compared.comparator.economics.complete
    assert compared.test.economics.initial_net_nav == Decimal("10000")
    assert compared.test.trials[0].start_nav != compared.test.economics.initial_net_nav
    assert compared.economic_advantage.state == "KNOWN"
    assert compared.economic_advantage.value == Decimal(0)
    assert compared.independent_account_count == 2
    assert compared.independent_paired_run_count == 1
    assert compared.scientific_conclusion == "INSUFFICIENT_INDEPENDENT_QUALIFIED_RUNS"
    with pytest.raises(ValueError, match="DISTINCT_MATCHED"):
        compare_controlled_campaigns(
            **(
                kwargs
                | {
                    "comparator_origin": left["origin"],
                    "comparator_allocation_id": b.allocation_id,
                    "comparator_provenance": left["provenance"],
                }
            )
        )


@pytest.mark.parametrize("validity_field", ["not_before", "expires_at", "revoked_at"])
def test_comparison_refuses_different_original_grant_validity(
    tmp_path: Path, validity_field: str
) -> None:
    """B/R accounting cannot turn asymmetric grant permission into equal policy."""
    from datetime import timedelta

    from test_stage1_controlled_contracts import controlled_arguments
    from test_stage1_synthetic_research_execution import BASE

    from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
    from drift.loop.stage1_controlled_readback import compare_controlled_campaigns

    left = controlled_arguments(tmp_path / "B")
    right = controlled_arguments(tmp_path / "R", arm="ARM-R")
    checkpoint = right["checkpoints"][0]
    changes = {
        "not_before": BASE - timedelta(minutes=1),
        "expires_at": BASE + timedelta(days=1, minutes=1),
        "revoked_at": BASE + timedelta(days=1),
    }
    right["checkpoints"] = (
        checkpoint.model_copy(update={validity_field: changes[validity_field]}),
    )
    b = execute_controlled_campaign(**left)
    r = execute_controlled_campaign(**right)
    with pytest.raises(
        ValueError, match="CONTROLLED_COMPARISON_NOT_DISTINCT_MATCHED_B_R"
    ):
        compare_controlled_campaigns(
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
            clock=lambda: BASE + timedelta(days=2),
        )
