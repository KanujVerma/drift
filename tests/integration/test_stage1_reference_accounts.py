"""Original fixed reference accounts, indicator maturity and causal readback."""

# ruff: noqa: E402
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

import exploratory_decision_test_support as reconstruction
import test_evaluator_engine as engine_fixture
from observation_test_support import ObservationHarness
from stage1_calendar_evidence_support import (
    attach_pinned_calendar,
    pinned_source_calendar,
)
from test_evaluator_reconstruction import make_policy
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)
from test_stage1_synthetic_research_execution import BASE, Tick

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_lanes import ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD
from drift.domain.evaluator_reconstruction import _with_reconstruction_validation_reuse
from drift.evaluator.bundles import assemble_evaluation_input_bundle
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.opening_book_lifecycle import OpeningBookLifecycleError
from drift.evaluator.reconstruction import (
    build_exploratory_reconstructed_session_observation,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    CLAIM,
    CONSUMED,
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_original_result_association import RESULT_EVENT
from drift.loop.stage1_reference_accounts import (
    EVENT,
    CommonReferenceViewV1,
    ReferenceAccountReceiptV1,
    ReferenceAccountsReceiptV1,
    ReferenceEventV1,
    build_reference_configuration,
    execute_reference_accounts,
    read_reference_accounts,
)
from drift.serialization.canonical import canonical_json, content_hash


def _engines(bundle: EvaluationInputBundleV1) -> tuple[SessionEvaluatorEngine, ...]:
    return tuple(
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=reconstruction.exploratory_admission(bundle),
            protocol=engine_fixture._protocol(warmup=1, cash="10000"),
            cost_model=engine_fixture._cost_model(notional_bps="1", slippage_bps="1"),
            evidence=SessionEvaluatorEvidence(
                exploratory_cohort=reconstruction.cohort_of(
                    (reconstruction.SEC, reconstruction.SEC_OTHER)
                ),
                exploratory_reconstruction_replay=reconstruction.replay_of(
                    bundle.exploratory_reconstructed_observations
                ),
                listing_role_records=engine_fixture.ROLE_RECORDS,
            ),
            book_currency_namespace="ISO4217",
            book_currency_code="USD",
        )
        for _ in range(3)
    )


@_with_reconstruction_validation_reuse
def _harness(root: Path, bundle: EvaluationInputBundleV1) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    engines = _engines(bundle)
    origin = ConfiguredLocalSyntheticOriginV1(root / "original.sqlite3", uuid7())
    clock = Tick()
    configuration = build_reference_configuration(
        campaign=make_golden_campaign(),
        arms=(make_golden_arm_b(), make_golden_arm_r()),
        bindings=tuple(make_golden_bindings()),
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        reference_campaign_id="REFERENCE-CAMPAIGN-001",
        bound_at=BASE,
        engines=engines,
    )
    receipt = execute_reference_accounts(
        origin=origin, configuration=configuration, engines=engines, clock=clock
    )
    return {
        "origin": origin,
        "configuration": configuration,
        "receipt": receipt,
        "clock": clock,
        "engines": engines,
    }


def _read(harness: dict[str, Any], index: int) -> CommonReferenceViewV1:
    return read_reference_accounts(
        origin=harness["origin"],
        configuration=harness["configuration"],
        receipt=harness["receipt"],
        decision_cutoff=harness["configuration"].environment.sessions[index].closed_at,
        clock=harness["clock"],
    )


def _receipts(harness: dict[str, Any]) -> tuple[ReferenceAccountReceiptV1, ...]:
    rows = []
    for event in harness["origin"].verified_events():
        if event.event_type == EVENT:
            assert isinstance(event.payload, Mapping)
            rows.append(
                ReferenceAccountReceiptV1.model_validate_json(
                    canonical_json(event.payload["receipt"])
                )
            )
    return tuple(rows)


@pytest.fixture(scope="module")
def short_accounts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    cases = tuple(
        reconstruction.scheduled_session_case(
            day,
            security_id=security,
            listing_id=listing,
            close="100.010",
            cohort_securities=(reconstruction.SEC, reconstruction.SEC_OTHER),
        )
        for day in engine_fixture.DAYS
        for security, listing in (
            (reconstruction.SEC, reconstruction.LISTING),
            (reconstruction.SEC_OTHER, reconstruction.LISTING_OTHER),
        )
    )
    return _harness(
        tmp_path_factory.mktemp("original-reference-short"),
        reconstruction.bundle_of(cases),
    )


def test_short_original_reference_accounts_are_independent_actual_m0_books(
    short_accounts: dict[str, Any],
) -> None:
    harness = short_accounts
    events = harness["origin"].verified_events()
    for kind in (ALLOCATION, CLAIM, CONSUMED, RESULT_EVENT):
        assert sum(event.event_type == kind for event in events) == 3
    receipts = _receipts(harness)
    assert tuple(row.family for row in receipts) == ("B3", "B4", "B5")
    assert len({row.allocation_id for row in receipts}) == 3
    assert len({row.fields.portfolio_account_id for row in receipts}) == 3
    assert len({row.m0_run_id for row in receipts}) == 3
    assert all(row.fields.initial_cash == "10000" for row in receipts)
    assert all(row.m0_status == "completed" for row in receipts)
    assert all(row.result_association is not None for row in receipts)
    assert not any(row.fields.arm_id in ("ARM-B", "ARM-R") for row in receipts)
    view = _read(harness, 3)
    b3, b4, b5 = view.families
    assert b3.first_eligible_decision_index == 0
    assert b3.completed_interval_count == 3
    assert b3.marks[0].net_asset_value == Decimal("10000")
    assert b3.intervals[0].transaction_costs > 0
    assert b3.intervals[0].gross_traded_notional > 0
    assert b4.first_eligible_decision_index is None
    assert b5.first_eligible_decision_index is None
    assert b4.marks == b5.marks == ()
    assert all(family.status == "UNAVAILABLE" for family in view.families)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused engine"):
        execute_reference_accounts(
            origin=harness["origin"],
            configuration=harness["configuration"],
            engines=harness["engines"],
            clock=harness["clock"],
        )


def test_short_common_view_is_detached_and_contains_no_future_terminal_fields(
    short_accounts: dict[str, Any],
) -> None:
    before = _read(short_accounts, 1)
    expected = canonical_json(before)
    assert all(m.session_index <= 1 for f in before.families for m in f.marks)
    assert all(i.end_session_index <= 1 for f in before.families for i in f.intervals)
    assert b"result_hash" not in expected
    assert b"final_state" not in expected
    assert b"classification" not in expected
    object.__setattr__(before.families[0].marks[0], "net_asset_value", Decimal("1"))
    assert canonical_json(_read(short_accounts, 1)) == expected
    between = read_reference_accounts(
        origin=short_accounts["origin"],
        configuration=short_accounts["configuration"],
        receipt=short_accounts["receipt"],
        clock=short_accounts["clock"],
        decision_cutoff=(
            short_accounts["configuration"].environment.sessions[2].closed_at
            - timedelta(microseconds=1)
        ),
    )
    assert between.families == _read(short_accounts, 1).families


def test_short_cold_process_reopens_original_reference_evidence(
    short_accounts: dict[str, Any],
    tmp_path: Path,
) -> None:
    harness = short_accounts
    cutoff = harness["configuration"].environment.sessions[2].closed_at
    supplied = {
        "origin_path": str(harness["origin"].ledger_path),
        "issuer": str(harness["origin"].issuer_instance_id),
        "configuration": harness["configuration"].model_dump(mode="json"),
        "receipt": harness["receipt"].model_dump(mode="json"),
        "cutoff": cutoff.isoformat(),
        "observed_at": harness["clock"]().isoformat(),
    }
    boot = tmp_path / "trusted-host-configuration.json"
    boot.write_bytes(canonical_json(supplied))
    script = """
import json, sys
from datetime import datetime
from pathlib import Path
from uuid import UUID
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_reference_accounts import (
    ReferenceCampaignConfigurationV1,
    ReferenceAccountsReceiptV1,
    read_reference_accounts,
)
from drift.serialization.canonical import canonical_json
data = json.loads(Path(sys.argv[1]).read_text())
view = read_reference_accounts(
    origin=ConfiguredLocalSyntheticOriginV1(
        Path(data['origin_path']), UUID(data['issuer']),
    ),
    configuration=ReferenceCampaignConfigurationV1.model_validate_json(json.dumps(data['configuration'])),
    receipt=ReferenceAccountsReceiptV1.model_validate_json(json.dumps(data['receipt'])),
    decision_cutoff=datetime.fromisoformat(data['cutoff']),
    clock=lambda: datetime.fromisoformat(data['observed_at']),
)
sys.stdout.buffer.write(canonical_json(view))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(boot)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert result.stdout == canonical_json(_read(harness, 2))


def test_short_wrong_origin_and_substituted_family_receipt_are_refused(
    short_accounts: dict[str, Any],
) -> None:
    harness = short_accounts
    wrong = ConfiguredLocalSyntheticOriginV1(harness["origin"].ledger_path, uuid7())
    with pytest.raises(ValueError, match="REFERENCE_ORIGINAL_SCOPE_MISMATCH"):
        read_reference_accounts(
            origin=wrong,
            configuration=harness["configuration"],
            receipt=harness["receipt"],
            clock=harness["clock"],
            decision_cutoff=harness["configuration"].environment.sessions[-1].closed_at,
        )
    original = harness["receipt"]
    swapped = ReferenceAccountsReceiptV1(
        configuration_hash=original.configuration_hash,
        originals=(original.originals[1], original.originals[0], original.originals[2]),
    )
    with pytest.raises(ValueError, match="REFERENCE_ORIGINAL_ACCOUNTS_NOT_DISTINCT"):
        read_reference_accounts(
            origin=harness["origin"],
            configuration=harness["configuration"],
            receipt=swapped,
            clock=harness["clock"],
            decision_cutoff=harness["configuration"].environment.sessions[-1].closed_at,
        )


def test_short_early_cash_marks_cannot_be_relabelled_eligible(
    short_accounts: dict[str, Any],
) -> None:
    row = _receipts(short_accounts)[1]
    values = row.model_dump(mode="json")
    values["decisions"][0].update(eligible=True, reason=None)
    with pytest.raises(ValueError, match="REFERENCE_ELIGIBILITY_BEFORE_WARMUP"):
        ReferenceAccountReceiptV1.model_validate_json(canonical_json(values))


@pytest.mark.parametrize("mutation", ("duplicate", "contradictory_m0"))
def test_short_original_reference_replacement_or_contradictory_status_is_refused(
    short_accounts: dict[str, Any],
    tmp_path: Path,
    mutation: str,
) -> None:
    """A newly appended local claim cannot replace the original producer join."""
    original = short_accounts["origin"]
    copied = ConfiguredLocalSyntheticOriginV1(
        tmp_path / "copy.sqlite3", original.issuer_instance_id
    )
    ledger = SQLiteLedger(copied.ledger_path)
    last = short_accounts["receipt"].originals[-1]
    new_last = last
    for event in original.verified_events():
        values = event.model_dump(mode="python")
        values.pop("event_hash")
        values.pop("previous_event_hash")
        if event.event_id == last.event_id and mutation == "contradictory_m0":
            # This is the final event: every earlier original account, M0 and
            # RESULT hash remains unchanged in this isolated negative corpus.
            values["payload"]["receipt"]["m0_status"] = "failed"
            values["payload"]["receipt"]["result_association"] = None
        appended = ledger.append(AuditEventDraft.model_validate(values))
        if event.event_id == last.event_id:
            new_last = ReferenceEventV1(
                event_id=appended.event_id, event_hash=appended.event_hash
            )
    if mutation == "duplicate":
        duplicate = ledger.get(last.event_id)
        assert duplicate is not None
        values = duplicate.model_dump(mode="python")
        values.pop("event_hash")
        values.pop("previous_event_hash")
        values.update(
            event_id=uuid7(), deduplication_key="forged-reference-replacement"
        )
        ledger.append(AuditEventDraft.model_validate(values))
    receipt = ReferenceAccountsReceiptV1(
        configuration_hash=short_accounts["receipt"].configuration_hash,
        originals=(*short_accounts["receipt"].originals[:-1], new_last),
    )
    expected = (
        "REFERENCE_ORIGINAL_RECEIPT_NOT_UNIQUE"
        if mutation == "duplicate"
        else "REFERENCE_ORIGINAL_M0_OR_MANIFEST_MISMATCH"
    )
    with pytest.raises(ValueError, match=expected):
        read_reference_accounts(
            origin=copied,
            configuration=short_accounts["configuration"],
            receipt=receipt,
            clock=short_accounts["clock"],
            decision_cutoff=short_accounts["configuration"]
            .environment.sessions[-1]
            .closed_at,
        )


def _original_379_bundle() -> EvaluationInputBundleV1:
    """Two fictional prices on 379 sessions of the witnessed original calendar."""
    days, early_closes, _ = pinned_source_calendar()
    days = days[:379]
    observations = []
    sessions = []
    for index, day in enumerate(days):
        for ordinal, (security, listing) in enumerate(
            (
                (reconstruction.SEC, reconstruction.LISTING),
                (reconstruction.SEC_OTHER, reconstruction.LISTING_OTHER),
            )
        ):
            units = 100 + index * (3 if ordinal == 0 else 1)
            if ordinal == 0:
                units += 5 * (index % 2)
            price = Decimal(1000000 + units) / Decimal("10000")
            harness = ObservationHarness(
                session_date=day,
                security_id=security,
                listing_id=listing,
                close=format(price, "f"),
                available_at=day.isoformat() + "T22:30:00Z",
            )
            harness.use_unproven_observation_coverage(mode="absent")
            harness.attach_sessions(
                schedule_state="early_close" if day in early_closes else "regular",
                realized_outcome="missing",
            )
            if index == 0 and ordinal == 0:
                attach_pinned_calendar(harness)
            harness.context = replace(
                harness.context,
                supporting_artifacts={
                    **harness.context.supporting_artifacts,
                    **engine_fixture.CA_COVERAGE_SUPPORT,
                },
            )
            query = harness.outcome(
                economic_horizon="2026-10-24T00:00:00Z",
                evidence_vintage_cutoff="2026-10-24T00:00:00Z",
                session_date=day.isoformat(),
            )
            observation = build_exploratory_reconstructed_session_observation(
                query,
                harness.context,
                reconstruction.cohort_of(
                    (reconstruction.SEC, reconstruction.SEC_OTHER)
                ),
                make_policy(),
            )
            reconstruction._SOURCE_REQUESTS[observation.reconstruction_hash] = (
                query,
                harness.context,
            )
            observations.append(observation)
            if ordinal == 0:
                sessions.append(
                    build_scheduled_reconstruction_clock(
                        (query,), harness.context
                    ).sessions[0]
                )
    return assemble_evaluation_input_bundle(
        evaluation_interval=engine_fixture._interval(),
        session_clock=reconstruction.merged_scheduled_clock(sessions),
        security_identities=engine_fixture.SECURITIES,
        listing_identities=engine_fixture.LISTINGS,
        exploratory_reconstructed_observations=tuple(observations),
        corporate_action_coverage=engine_fixture.quiet_coverage(
            (reconstruction.SEC, reconstruction.SEC_OTHER), days[0], days[-1]
        ),
        dataset_limitations=(ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD,),
    )


def test_full_reference_windows_use_actual_253_61_starts_and_127_marks(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, _original_379_bundle())
    receipts = _receipts(harness)
    assert all(row.m0_status == "completed" for row in receipts)
    assert tuple(
        next(d.session_index for d in row.decisions if d.eligible) for row in receipts
    ) == (0, 252, 60)
    b4_at_253 = _read(harness, 252).families[1]
    assert b4_at_253.status == "UNAVAILABLE"
    assert b4_at_253.first_eligible_decision_index == 252
    assert b4_at_253.completed_interval_count == 0
    assert len(b4_at_253.marks) == 1
    assert _read(harness, 377).families[1].completed_interval_count == 125
    final = _read(harness, 378)
    for family in final.families:
        assert family.status == "AVAILABLE", family.reason
        assert family.completed_interval_count == 126
        assert len(family.marks) == 127
        assert family.marks[0].session_index == 252
        assert family.marks[-1].session_index == 378
        assert all(
            i.end_session_index == i.start_session_index + 1 for i in family.intervals
        )
    assert final.families[1].intervals[0].gross_traded_notional > 0
    assert final.families[1].intervals[0].transaction_costs > 0
    assert _read(harness, 59).families[2].first_eligible_decision_index is None
    b5_at_61 = _read(harness, 60).families[2]
    assert b5_at_61.first_eligible_decision_index == 60
    assert b5_at_61.completed_interval_count == 0
    assert _read(harness, 186).families[2].status == "AVAILABLE"
    assert _read(harness, 251).families[1].first_eligible_decision_index is None


def test_configured_g3_candidate_locks_policy_but_requires_actual_admission() -> None:
    from drift.experiments.stage1_study_freeze import (
        REQUIRED_ROLES,
        Stage1StudyDraftV1,
        assess_study_readiness,
    )

    path = (
        Path(__file__).parents[1] / "fixtures/stage1/study-protocol-candidate-v1.json"
    )
    candidate = json.loads(path.read_text())
    assert (
        candidate["design_status"] == "LOCKED_SPECIFICATION_PENDING_ORIGINAL_ADMISSION"
    )
    draft = Stage1StudyDraftV1.model_validate_json(canonical_json(candidate["draft"]))
    readiness = assess_study_readiness(draft)
    assert readiness.model_dump(mode="json") == candidate["readiness"]
    assert readiness.status == "BLOCKED"
    assert readiness.verified_roles == ()
    missing_configuration = {
        "calendar_and_universe_hash",
        "comparator",
        "costs",
        "dataset_manifest_hash",
        "mandate",
        "model",
    }
    assert set(readiness.blockers) == {
        *("MISSING_CONFIGURATION:" + key for key in missing_configuration),
        *("MISSING_OR_DUPLICATE_ORIGINAL_EVIDENCE:" + role for role in REQUIRED_ROLES),
    }
    policies = candidate["locked_specification"]["policies"]
    assert candidate["embedded_policy_hashes"] == {
        key: content_hash(value) for key, value in policies.items()
    }
    assert draft.decision_cutoff_policy_hash == content_hash(
        policies["decision_cutoff"]
    )
    assert draft.seed_and_replication_policy_hash == content_hash(
        policies["seed_and_replication"]
    )
    assert draft.statistics is not None
    assert draft.statistics.bootstrap_repetitions == 10000
    assert draft.statistics.bootstrap_seed == 575
    for field, name in (
        ("block_length_policy_hash", "block_length"),
        ("multiplicity_policy_hash", "multiplicity"),
        ("stopping_policy_hash", "stopping"),
        ("risk_free_policy_hash", "risk_free"),
    ):
        assert getattr(draft.statistics, field) == content_hash(policies[name])
    assert candidate["evidence"] == []
    assert not candidate["authorizes_trading"]
    assert not candidate["establishes_efficacy"]
