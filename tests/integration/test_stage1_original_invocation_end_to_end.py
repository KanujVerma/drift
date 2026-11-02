"""Offline B3 proof over the complete synthetic Stage 1 input window (#562).

The twelve names label fictional constant-price securities, not qualified ETF
history. The synthetic calendar has weekdays at 14:30-21:00 UTC, including real
market holidays. It does not assert real XNYS venue authority or source rights.
Both arms run the installed B3 implementation without AI selection or scoring.
"""

# ruff: noqa: E402
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

_UNIT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT) not in sys.path:
    sys.path.insert(0, str(_UNIT))

import test_evaluator_engine as engine_fixture
from test_stage1_campaign_config import make_golden_arm_b, make_golden_arm_r

from drift.baselines import B3MonthlyEqualWeightRebalanceStrategy
from drift.baselines.runner import (
    build_canonical_run_identity,
    build_canonical_specification,
    make_bundle_dataset_reference,
)
from drift.domain.artifacts import ArtifactKind
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV2,
    strategy_parameters_hash,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.experiments import ExperimentRunStatus
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.evaluator.bundles import assemble_evaluation_input_bundle
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.evaluator.opening_book_lifecycle import parse_original_invocation_binding
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    DataWindowV1,
    DecisionScheduleV1,
    PrimaryComparisonV1,
    RunAccountBindingV1,
    ScoringWindowV1,
    SessionWindowV1,
    build_campaign_spec,
    build_run_account_binding,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    CLAIM,
    CONSUMED,
    WITNESS,
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import (
    M0_USE_EVENT,
    MAX_ARTIFACT_BYTES,
    RESULT_EVENT,
    Stage1OriginalResultAssociationV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json, content_hash

WARMUP = 253
OBSERVATION = 126
CAMPAIGN_ID = "CAMP-E1-SYNTH-001"
CALENDAR_ID = "fixture://weekday-utc-1430-2100-379-v1"
TICKERS = (
    "VOO",
    "IJH",
    "IJR",
    "VEA",
    "VWO",
    "QQQ",
    "SHY",
    "IEF",
    "TLT",
    "TIP",
    "LQD",
    "GLD",
)
SECURITIES = tuple(
    UUID(f"018e0000-0000-7000-8000-{index:012d}")
    for index in range(1, len(TICKERS) + 1)
)
LISTINGS = tuple(
    UUID(f"018e0000-0000-7000-9000-{index:012d}")
    for index in range(1, len(TICKERS) + 1)
)
BASE = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)


def _session_dates() -> tuple[date, ...]:
    days: list[date] = []
    day = date(2024, 1, 2)
    while len(days) < WARMUP + OBSERVATION:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return tuple(days)


def _constant_view(
    security_id: UUID, listing_id: UUID, day: date, *, decision: bool
) -> DerivedObservationViewV1:
    """Restate the established synthetic M1d fixture with this exact identity.

    B3 needs the current closing observation, not B4/B5 lookback inputs. Every
    session still has all twelve accounting observations, including warmup.
    These are explicitly synthetic views, not authenticated provider evidence.
    """
    cutoff = datetime.combine(day, time(21, 0), tzinfo=UTC)
    template = engine_fixture._template_view().query.observation
    common = {
        "security_id": security_id,
        "listing_id": listing_id,
        "session_date": day,
    }
    if decision:
        observation = template.model_copy(
            update=common
            | {
                "decision_time": cutoff,
                "knowledge_cutoff": cutoff,
                "effective_cutoff": cutoff,
            }
        )
    else:
        values = dict(template)
        for field in ("kind", "decision_time", "knowledge_cutoff", "effective_cutoff"):
            values.pop(field, None)
        observation = ObservationOutcomeQueryV1(
            **(
                values
                | common
                | {
                    "kind": "outcome",
                    "economic_horizon": cutoff,
                    "evidence_vintage_cutoff": cutoff,
                }
            )
        )
    return engine_fixture._restated_view(
        role="decision" if decision else "outcome",
        observation=observation,
        security_id=security_id,
        listing_id=listing_id,
        source_day=day,
        open_price="100.00",
        close_price="100.00",
    )


def _input_bundle() -> EvaluationInputBundleV1:
    dates = _session_dates()
    return assemble_evaluation_input_bundle(
        evaluation_interval=engine_fixture._interval(),
        session_clock=engine_fixture._clock(dates),
        security_identities=tuple(
            SecurityV1(schema_version="1", security_id=security)
            for security in SECURITIES
        ),
        listing_identities=tuple(
            ListingV1(schema_version="1", listing_id=listing, venue=ListingVenue.XNYS)
            for listing in LISTINGS
        ),
        structural_eligibilities=tuple(
            engine_fixture._eligibility(
                security,
                listing,
                knowledge_cutoff=datetime(2024, 1, 1, tzinfo=UTC),
            )
            for security, listing in zip(SECURITIES, LISTINGS, strict=True)
        ),
        authentic_decision_views=tuple(
            _constant_view(security, listing, day, decision=True)
            for day in dates[WARMUP - 1 :]
            for security, listing in zip(SECURITIES, LISTINGS, strict=True)
        ),
        authentic_accounting_views=tuple(
            _constant_view(security, listing, day, decision=False)
            for day in dates
            for security, listing in zip(SECURITIES, LISTINGS, strict=True)
        ),
        corporate_action_coverage=engine_fixture.quiet_coverage(
            SECURITIES, dates[0], dates[-1]
        ),
    )


def _engine(bundle: EvaluationInputBundleV1) -> SessionEvaluatorEngine:
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=engine_fixture._admission(bundle),
        protocol=engine_fixture._protocol(warmup=WARMUP, cash="10000"),
        cost_model=engine_fixture._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=tuple(
                engine_fixture._role_record(security, listing, suffix=1000 + index)
                for index, (security, listing) in enumerate(
                    zip(SECURITIES, LISTINGS, strict=True)
                )
            ),
        ),
        book_currency_namespace="ISO4217",
        book_currency_code="USD",
    )


def _identity(
    engine: SessionEvaluatorEngine, strategy: B3MonthlyEqualWeightRebalanceStrategy
) -> EvaluationRunIdentityV2:
    return build_canonical_run_identity(
        strategy_hash=strategy.strategy_reference.code_hash,
        strategy_parameters_hash=strategy_parameters_hash(strategy.strategy_parameters),
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
    )


@dataclass(frozen=True)
class _Manifest:
    campaign: CampaignSpecV1
    arms: tuple[ArmSpecV1, ...]
    bindings: tuple[RunAccountBindingV1, ...]


def _manifest(bundle: EvaluationInputBundleV1) -> _Manifest:
    """Keep golden E1 constraints, while declaring the actual fixture calendar."""
    dates = _session_dates()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    campaign = build_campaign_spec(
        campaign_id=CAMPAIGN_ID,
        campaign_type="SYNTHETIC_TEST",
        study_protocol_revision="fixture://b3-original-invocation-379-v1",
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        frozen_at=datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        accepted_contract_revisions={},
        research_question_id="RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
        primary_comparison=PrimaryComparisonV1("ARM-B", "ARM-R"),
        control_arm_references=(),
        arm_spec_references=tuple(arm.arm_spec_fingerprint for arm in arms),
        qualified_dataset_references=(),
        data_window=DataWindowV1(
            start_date=dates[0].isoformat(),
            end_date=dates[-1].isoformat(),
            calendar_id=CALENDAR_ID,
        ),
        warmup_window=SessionWindowV1(WARMUP),
        observation_window=SessionWindowV1(OBSERVATION),
        scoring_window=ScoringWindowV1("SC-001", "SC-021", True),
        decision_schedule=DecisionScheduleV1(
            "MONTHLY", "LAST_COMPLETED_SESSION", "NEXT_OPEN"
        ),
        allowed_strategy_families=("B3", "B4", "B5"),
        portfolio_mandate_reference="fixture://balanced-mandate-v1",
        source_eligibility_policy_reference="fixture://source-policy-v1",
        execution_policy_reference="fixture://next-open-v1",
        cost_policy_reference="fixture://zero-cost-synthetic-v1",
        model_and_prompt_policy_reference="fixture://model-B-v1",
        learning_and_feedback_policy_reference="fixture://feedback-policy-v1",
        evaluation_policy_reference="fixture://unscored-platform-only-v1",
        holdout_access_policy_reference="fixture://holdout-policy-v1",
        stopping_policy_reference="fixture://stop-policy-v1",
        authorization_evidence={
            "synthetic_fixture_only": True,
            "reviewer_receipts": [],
            "synthetic_security_labels": list(TICKERS),
            "synthetic_security_ids": [str(security) for security in SECURITIES],
            "synthetic_listing_ids": [str(listing) for listing in LISTINGS],
            "calendar_id": CALENDAR_ID,
            "input_bundle_hash": bundle.bundle_hash,
            "session_clock_hash": bundle.session_clock.clock_hash,
            "constant_price_usd": "100.00",
            "strategies_executed": ["B3"],
            "scientifically_qualified": False,
        },
    )
    bindings = tuple(
        build_run_account_binding(
            campaign_id=CAMPAIGN_ID,
            run_id="RUN-001",
            arm_id=arm.arm_id,
            portfolio_account_id=f"SYNTH-ACC-{arm.arm_id[-1]}-001",
            initial_cash_allocated="10000",
            bound_at=datetime(2026, 10, 19, 0, 0, 2, tzinfo=UTC),
        )
        for arm in arms
    )
    verify_stage1_synthetic_br_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
    )
    return _Manifest(campaign, arms, bindings)


@dataclass
class _Tick:
    now: datetime
    ticks: int = 0

    def __call__(self) -> datetime:
        timestamp = self.now + timedelta(seconds=self.ticks)
        self.ticks += 1
        return timestamp


def _execute_and_retain_pair(
    root: Path, bundle: EvaluationInputBundleV1, manifest: _Manifest
) -> None:
    """Leave durable references only; no running observer escapes this function."""
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=root / "original-accounts.sqlite3",
        issuer_instance_id=uuid7(),
    )
    references: list[dict[str, object]] = []
    for index, arm in enumerate(manifest.arms):
        base = BASE + timedelta(minutes=index * 10)
        store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=_Tick(base))
        provenance = build_stage1_trial_provenance_snapshot(
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            run_id="RUN-001",
            arm_id=arm.arm_id,
            checkpoint_id="CKPT-001",
            events=(),
        )
        account = Stage1SyntheticAccountLifecycleV1(
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            provenance=provenance,
            store=store,
        )
        engine = _engine(bundle)
        engine.prepare_opening_book(lifecycle=account)
        original = account.verified_original()
        assert original.opening_book.cash_balance == Decimal("10000")
        assert original.opening_book.net_asset_value == Decimal("10000")
        assert not original.opening_book.holdings
        assert not original.original_issuer_authenticated_for_e6b

        def result_clock(base: datetime = base) -> datetime:
            return base + timedelta(minutes=1)

        observer = Stage1OriginalResultAssociationV1(
            origin=origin,
            account=account,
            provenance=provenance,
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            clock=result_clock,
        )
        strategy = B3MonthlyEqualWeightRebalanceStrategy()
        identity = _identity(engine, strategy)
        specification = build_canonical_specification(
            strategy=strategy,
            bundle=engine.bundle,
            dataset_reference=make_bundle_dataset_reference(
                bundle,
                source="Offline synthetic constant-price twelve-security B3 fixture",
            ),
        )
        assert identity.schema_version == "2"
        assert specification.parameters == strategy.strategy_parameters
        assert specification.dataset_reference.content_hash == bundle.bundle_hash
        context = ExperimentRunnerContext(
            run_id=uuid7(),
            started_at=base + timedelta(seconds=2),
            completed_at=base + timedelta(seconds=6),
            engine=engine,
            strategy=strategy,
            run_identity=identity,
            result_artifact_id=uuid7(),
            trace_artifact_id=uuid7(),
            result_artifact_location=f"fixture://{arm.arm_id}/result",
            trace_artifact_location=f"fixture://{arm.arm_id}/trace",
            ledger=SQLiteLedger(origin.ledger_path),
            audit_event_id=uuid7(),
            original_result_observer=observer,
        )
        run = execute_experiment_run(specification, context)
        assert run.status is ExperimentRunStatus.COMPLETED, run.error_details
        retained = observer.readback()
        assert retained.operational_m0_run_id == context.run_id
        assert retained.account_id == original.fields.portfolio_account_id
        assert retained.complete_manifest_fingerprint == (
            provenance.scope.complete_manifest_fingerprint
        )
        by_kind = {item.kind: item.content_hash for item in run.artifact_references}
        assert by_kind[ArtifactKind.RESULT] == retained.result_hash
        assert by_kind[ArtifactKind.LOG] == retained.trace_hash
        references.append(
            {
                "arm_id": arm.arm_id,
                "fields": asdict(original.fields),
                "allocation_id": original.allocation_id,
                "allocation_ref": asdict(original.allocation_ref),
                "witness_ref": asdict(original.witness_ref),
                "association_ref": asdict(retained.association_ref),
                "m0_run_id": run.run_id,
                "m0_audit_event_id": context.audit_event_id,
                "result_hash": retained.result_hash,
                "trace_hash": retained.trace_hash,
                "final_book_hash": retained.final_book_hash,
            }
        )
    (root / "readback-references.json").write_bytes(
        canonical_json(
            {
                "issuer_instance_id": origin.issuer_instance_id,
                "accounts": references,
            }
        )
    )


def _event_reference(value: dict[str, str]) -> LocalEventReferenceV1:
    return LocalEventReferenceV1(UUID(value["event_id"]), value["event_hash"])


def _assert_actual_b3_result(artifacts: EvaluationRunArtifactsV2) -> None:
    result, trace, book = artifacts.result, artifacts.trace, artifacts.final_state
    dates = _session_dates()
    assert result.classification is EvaluationClassification.COMPLETE
    assert result.lane == "exploratory"
    assert result.is_promotion_grade_evidence is False
    assert result.run_identity.schema_version == "2"
    metrics = result.metrics
    assert metrics.evaluated_session_count == WARMUP + OBSERVATION
    assert metrics.initial_cash == metrics.initial_net_asset_value == Decimal("10000")
    assert metrics.committed_fill_count == 12
    assert metrics.gross_traded_notional == Decimal("9600")
    assert metrics.cumulative_transaction_costs == 0
    assert metrics.net_profit_and_loss == 0
    assert book.cash_balance == metrics.ending_cash == Decimal("400")
    assert book.holdings_market_value == Decimal("9600")
    assert book.net_asset_value == metrics.ending_net_asset_value == Decimal("10000")
    assert {holding.security_id: holding.quantity for holding in book.holdings} == {
        security: 8 for security in SECURITIES
    }
    assert not book.pending_cash_claims
    assert book.pending_claims_value == 0
    assert len(metrics.equity_series) == len(dates)
    for point in metrics.equity_series[:WARMUP]:
        assert point.cash_balance == point.net_asset_value == Decimal("10000")
        assert point.holdings_market_value == 0
    for point in metrics.equity_series[WARMUP:]:
        assert point.cash_balance == Decimal("400")
        assert point.holdings_market_value == Decimal("9600")
        assert point.net_asset_value == Decimal("10000")

    fills = [event for event in trace.events if event.kind == "fill"]
    assert len(fills) == len(SECURITIES)
    for event in fills:
        assert event.session_index == WARMUP
        assert event.session_key.local_date == dates[WARMUP]
        assert event.fill.side == "buy"
        assert event.fill.quantity == 8
        assert (
            event.fill.unadjusted_open_price == event.fill.fill_price == Decimal("100")
        )
        assert event.fill.gross_notional == Decimal("800")
        assert event.fill.cash_delta == Decimal("-800")
        assert event.fill.transaction_costs == 0
    decisions = [event for event in trace.events if event.kind == "strategy_decision"]
    assert [event.session_index for event in decisions] == list(
        range(WARMUP - 1, WARMUP + OBSERVATION)
    )
    assert decisions[0].session_key.local_date == dates[WARMUP - 1]
    assert decisions[0].decision_cutoff < datetime.combine(
        dates[WARMUP], time(14, 30), tzinfo=UTC
    )
    assert len(trace.events) == 2 * len(dates) + len(decisions) + len(fills)


def test_full_window_b3_accounts_have_distinct_original_invocations_and_cold_readback(
    tmp_path: Path,
) -> None:
    # Imported here so the input fixture can be measured before C's reader is
    # integrated. This public reader must not use the original observer object.
    from drift.loop.stage1_original_result_association import read_original_result

    bundle = _input_bundle()
    manifest = _manifest(bundle)
    dates = _session_dates()
    assert manifest.campaign.warmup_window.sessions_count == WARMUP
    assert manifest.campaign.observation_window.sessions_count == OBSERVATION
    assert manifest.campaign.data_window.start_date == dates[0].isoformat()
    assert manifest.campaign.data_window.end_date == dates[-1].isoformat()
    assert (
        tuple(
            session.session_key.local_date for session in bundle.session_clock.sessions
        )
        == dates
    )
    assert len(bundle.authentic_accounting_views) == len(dates) * len(SECURITIES)
    assert len(bundle.authentic_decision_views) == (OBSERVATION + 1) * len(SECURITIES)
    assert {member.security_id for member in bundle.security_identities} == set(
        SECURITIES
    )

    # Retain the complete source fixture, distinct from the bounded RESULT
    # artifact. The reader revalidates those bytes before using the E1 manifest.
    bundle_file = tmp_path / "synthetic-input-bundle.json"
    bundle_file.write_bytes(canonical_json(bundle))
    _execute_and_retain_pair(tmp_path, bundle, manifest)
    reopened_bundle = EvaluationInputBundleV1.model_validate_json(
        bundle_file.read_bytes()
    )
    assert reopened_bundle.bundle_hash == bundle.bundle_hash
    reopened_manifest = _manifest(reopened_bundle)
    assert reopened_manifest == manifest
    references: dict[str, Any] = json.loads(
        (tmp_path / "readback-references.json").read_bytes()
    )
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "original-accounts.sqlite3",
        issuer_instance_id=UUID(references["issuer_instance_id"]),
    )
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=origin, clock=lambda: BASE + timedelta(hours=1)
    )
    readbacks = []
    invocation_ids: set[str] = set()
    events = SQLiteLedger.open_existing(origin.ledger_path).verified_events()
    assert len(events) == 14
    for reference in references["accounts"]:
        fields = AccountAllocationFieldsV1(**reference["fields"])
        original = store.readback_allocation(
            allocation_id=UUID(reference["allocation_id"]),
            allocation_ref=_event_reference(reference["allocation_ref"]),
            witness_ref=_event_reference(reference["witness_ref"]),
            expected_fields=fields,
        )
        provenance = build_stage1_trial_provenance_snapshot(
            campaign=reopened_manifest.campaign,
            arms=reopened_manifest.arms,
            bindings=reopened_manifest.bindings,
            expected_run_ids=("RUN-001",),
            run_id="RUN-001",
            arm_id=reference["arm_id"],
            checkpoint_id="CKPT-001",
            events=(),
        )
        retained = read_original_result(
            origin=origin,
            original_account=original,
            association_ref=_event_reference(reference["association_ref"]),
            provenance=provenance,
            campaign=reopened_manifest.campaign,
            arms=reopened_manifest.arms,
            bindings=reopened_manifest.bindings,
            expected_run_ids=("RUN-001",),
            clock=lambda: BASE + timedelta(hours=1),
        )
        assert retained.original_issuer_authenticated_for_e6b is False
        assert retained.scientifically_qualified is False
        assert retained.arm_id == fields.arm_id
        assert retained.account_id == fields.portfolio_account_id
        assert retained.result_hash == reference["result_hash"]
        assert retained.trace_hash == reference["trace_hash"]
        assert retained.final_book_hash == reference["final_book_hash"]
        assert retained.original_artifacts_bytes == canonical_json(
            retained.original_artifacts
        )
        artifact_size = len(retained.original_artifacts_bytes)
        assert 0 < artifact_size <= MAX_ARTIFACT_BYTES == 4_194_304
        _assert_actual_b3_result(retained.original_artifacts)

        chain = [
            event
            for event in events
            if event.entity_id == original.allocation_id
            or str(event.event_id) == reference["m0_audit_event_id"]
        ]
        assert [event.event_type for event in chain] == [
            ALLOCATION,
            WITNESS,
            CLAIM,
            CONSUMED,
            "m2.evaluation.run.recorded",
            M0_USE_EVENT,
            RESULT_EVENT,
        ]
        assert [event.schema_version for event in chain] == [
            "1",
            "1",
            "2",
            "2",
            "3",
            "2",
            "2",
        ]
        payloads: list[Mapping[str, ImmutableJSONValue]] = []
        for event in chain:
            payload = event.payload
            assert isinstance(payload, Mapping)
            payloads.append(payload)
        encoded_binding = payloads[2]["invocation_binding"]
        assert isinstance(encoded_binding, Mapping)
        assert set(encoded_binding) == {
            "invocation_id",
            "m0_run_id",
            "m0_audit_event_id",
        }
        binding = parse_original_invocation_binding(encoded_binding)
        assert binding.invocation_id.version == 7
        assert str(binding.m0_run_id) == reference["m0_run_id"]
        assert str(binding.m0_audit_event_id) == reference["m0_audit_event_id"]
        assert all(
            payload["invocation_binding"] == encoded_binding for payload in payloads[3:]
        )
        assert (
            content_hash(retained.original_artifacts.final_state)
            == retained.final_book_hash
        )
        invocation_ids.add(str(binding.invocation_id))
        readbacks.append(retained)
        print(f"{fields.arm_id}: {artifact_size} complete retained artifact bytes")

    assert len(invocation_ids) == len(readbacks) == 2
    left, right = readbacks
    assert left.account_id != right.account_id
    assert left.allocation_ref != right.allocation_ref
    assert left.association_ref != right.association_ref
    assert left.operational_m0_run_id != right.operational_m0_run_id
    assert left.complete_manifest_fingerprint == right.complete_manifest_fingerprint
    assert (
        left.original_artifacts.result.run_identity
        == right.original_artifacts.result.run_identity
    )
    assert left.result_hash == right.result_hash
    assert left.trace_hash == right.trace_hash
    assert left.final_book_hash == right.final_book_hash
    assert left.original_artifacts_bytes == right.original_artifacts_bytes
