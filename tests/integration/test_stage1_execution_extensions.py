"""Original-account proof for opt-in partial execution and protective correction."""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

import test_evaluator_engine as fixture  # noqa: E402
from test_stage1_controlled_campaign import _fresh_controlled_read  # noqa: E402
from test_stage1_controlled_contracts import controlled_arguments  # noqa: E402

from drift.domain.synthetic_execution import (  # noqa: E402
    ProtectiveCorrectionPolicyV1,
    SyntheticExecutionPolicyV1,
    SyntheticOrderFillSpecV1,
    SyntheticSessionFillSpecV1,
)
from drift.loop import stage1_controlled_contracts as C  # noqa: E402
from drift.loop.stage1_controlled_campaign import (  # noqa: E402
    ControlledCampaignExecutionV1,
    execute_controlled_campaign,
)
from drift.loop.stage1_controlled_journal import (  # noqa: E402
    CapturedControlledJournalV1,
)
from drift.loop.stage1_controlled_readback import (  # noqa: E402
    ControlledCampaignReadbackV1,
    read_controlled_campaign,
)
from drift.loop.stage1_controlled_transport import append_envelope  # noqa: E402


def _policy(
    *,
    session: int | None = None,
    quantity: int = 0,
    status: Literal["PARTIAL", "UNFILLED", "UNKNOWN"] = "PARTIAL",
) -> SyntheticExecutionPolicyV1:
    return SyntheticExecutionPolicyV1(
        policy_id="fixture:explicit-original-execution",
        sessions=(
            (
                SyntheticSessionFillSpecV1(
                    session_index=session,
                    orders=(
                        SyntheticOrderFillSpecV1(
                            order_index=0,
                            verified_filled_quantity=quantity,
                            status=status,
                        ),
                    ),
                ),
            )
            if session is not None
            else ()
        ),
    )


def _capture(
    args: dict[str, Any], execution: ControlledCampaignExecutionV1
) -> CapturedControlledJournalV1:
    return CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=execution.allocation_id,
        observed_at=args["clock"](),
    )


def _read(
    args: dict[str, Any], execution: ControlledCampaignExecutionV1
) -> ControlledCampaignReadbackV1:
    return read_controlled_campaign(
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


def _partial_arguments(root: Path) -> dict[str, Any]:
    # The full request is funded, including its explicit fixed fee. Actual
    # partial costs must be repriced for four shares, never copied from 100.
    bundle = fixture._bundle(
        accounting_views=tuple(
            fixture._accounting_view(
                fixture.SEC_A,
                day,
                open_price="99" if day == fixture.DAY_2 else None,
            )
            for day in fixture.DAYS
        )
    )
    engine = fixture._engine(
        bundle=bundle, cost_model=fixture._cost_model(fixed_fee="1")
    )
    args = controlled_arguments(root, engine=engine)
    args["execution_policy"] = _policy(session=2, quantity=4)
    return args


def _correction_arguments(
    root: Path, *, close_breach: bool, final_close_breach: bool = False
) -> dict[str, Any]:
    members = ((fixture.SEC_A, fixture.LISTING_A), (fixture.SEC_B, fixture.LISTING_B))
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
                close_price="400"
                if final_close_breach
                and security == fixture.SEC_A
                and day == fixture.DAY_3
                else "200"
                if close_breach and security == fixture.SEC_A and day == fixture.DAY_2
                else None,
            )
            for day in fixture.DAYS
            for security, listing in members
        ),
        eligibilities=tuple(
            fixture._eligibility(security, listing) for security, listing in members
        ),
    )
    args = controlled_arguments(root, engine=fixture._engine(bundle=bundle))
    policy = args["mandate"]
    args["mandate"] = policy.model_copy(
        update={
            "securities": tuple(
                rule.model_copy(update={"maximum_fraction": Decimal("0.6")})
                for rule in policy.securities
            ),
        }
    )
    args["execution_policy"] = _policy()
    args["protective_policy"] = ProtectiveCorrectionPolicyV1(
        enabled=True, allow_while_paused=False, maximum_preview_evaluations=128
    )
    return args


def test_actual_partial_fill_and_cost_survive_original_m0_and_cold_read(
    tmp_path: Path,
) -> None:
    args = _partial_arguments(tmp_path)
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed" and execution.terminal is not None
    journal = _capture(args, execution)
    actual = [
        row.record
        for row in journal.rows
        if isinstance(row.record, C.ActualExecutionRecordV1)
    ]
    assert len(actual) == 1
    receipt = actual[0].observation.receipt
    assert receipt.requested_plan.planned_fills[0].quantity == 100
    assert receipt.verified_filled_quantity == 4
    assert receipt.verified_execution_costs == Decimal("1")
    assert receipt.state.cash_balance == Decimal("9603")
    assert receipt.state.holdings[0].quantity == 4
    assert receipt.unresolved_order_count == 1 and not receipt.complete
    before = args["origin"].ledger_path.read_bytes()
    report = _read(args, execution)
    assert report.status == "UNRESOLVED" and not report.economics.complete
    assert report.original_result is not None
    artifacts = report.original_result.original_artifacts
    assert artifacts.final_state == receipt.state
    assert artifacts.final_state.mark is None
    assert str(artifacts.result.classification) == "indeterminate"
    assert report.execution_facts[0].receipt == receipt
    assert all(not trial.complete_interval for trial in report.trials)
    assert all(trial.outcome != "COMPLETED" for trial in report.trials)
    cold = _fresh_controlled_read(args, execution.allocation_id, tmp_path / "cold.json")
    assert cold["status"] == "UNRESOLVED"
    assert cold["result_hash"] == report.original_result.result_hash
    assert args["origin"].ledger_path.read_bytes() == before
    with pytest.raises(ValueError, match="ALREADY|CONSUMED|CLAIM|EXIST|JOURNAL"):
        execute_controlled_campaign(**args)


def test_extended_full_execution_retains_complete_original_receipts(
    tmp_path: Path,
) -> None:
    args = controlled_arguments(tmp_path)
    args["execution_policy"] = _policy()
    execution = execute_controlled_campaign(**args)
    report = _read(args, execution)
    assert report.status == "VERIFIED_COMPLETE", report.reasons
    assert report.execution_facts and all(
        x.receipt.complete for x in report.execution_facts
    )
    assert report.trials[0].outcome == "COMPLETED"
    assert report.economics.complete


def test_two_original_orders_preserve_partial_and_unknown_quantities(
    tmp_path: Path,
) -> None:
    args = _correction_arguments(tmp_path, close_breach=False)
    args["protective_policy"] = None
    args["execution_policy"] = SyntheticExecutionPolicyV1(
        policy_id="fixture:two-original-orders",
        sessions=(
            SyntheticSessionFillSpecV1(
                session_index=2,
                orders=(
                    SyntheticOrderFillSpecV1(
                        order_index=0, verified_filled_quantity=4, status="PARTIAL"
                    ),
                    SyntheticOrderFillSpecV1(
                        order_index=1, verified_filled_quantity=0, status="UNKNOWN"
                    ),
                ),
            ),
        ),
    )
    execution = execute_controlled_campaign(**args)
    report = _read(args, execution)
    assert report.status == "UNRESOLVED" and report.original_result is not None
    assert len(report.execution_facts) == 1
    receipt = report.execution_facts[0].receipt
    assert len(receipt.requested_plan.planned_fills) == 2
    assert len(receipt.committed_fills) == 1
    assert receipt.verified_filled_quantity == 4
    assert receipt.unresolved_order_count == 2
    assert tuple(order.status for order in receipt.selection.orders) == (
        "PARTIAL",
        "UNKNOWN",
    )
    assert receipt.state.cash_balance == Decimal("9600")
    assert report.original_result.original_artifacts.final_state == receipt.state
    assert not report.economics.complete
    assert all(trial.outcome != "COMPLETED" for trial in report.trials)


@pytest.mark.parametrize("close_breach", (False, True))
def test_existing_book_corrects_at_original_next_open_independently_of_research(
    tmp_path: Path,
    close_breach: bool,
) -> None:
    args = _correction_arguments(tmp_path, close_breach=close_breach)
    # A failed research attempt must never disable protective correction.
    checkpoint = args["checkpoints"][0]
    args["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={"should_timeout": True}
                )
            }
        ),
    )
    execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed", execution
    journal = _capture(args, execution)
    protective = [
        row.record.observation
        for row in journal.rows
        if isinstance(row.record, C.ActualExecutionRecordV1)
        and row.record.observation.purpose == "protective"
    ]
    assert len(protective) == 1
    assert protective[0].session_index == 3
    fills = protective[0].receipt.committed_fills
    assert len(fills) == 1 and fills[0].side == "sell"
    assert fills[0].security_id == fixture.SEC_A and fills[0].quantity == 5
    assert fills[0].unadjusted_open_price == Decimal("200")
    assert protective[0].receipt.complete
    assert sum(
        isinstance(row.record, C.ProtectiveDetectionRecordV1) for row in journal.rows
    ) == int(close_breach)
    report = _read(args, execution)
    assert report.original_result is not None
    assert report.original_result.classification == "complete"
    assert report.trials[0].outcome == "FAILED_RESEARCH"
    assert report.trials[0].selected_family is None
    assert any(fact.purpose == "protective" for fact in report.execution_facts)
    assert (
        report.original_result.original_artifacts.final_state.cash_balance
        == Decimal("1000")
    )


def test_partial_protective_order_remains_original_and_unresolved(
    tmp_path: Path,
) -> None:
    args = _correction_arguments(tmp_path, close_breach=False)
    args["execution_policy"] = _policy(session=3, quantity=2)
    execution = execute_controlled_campaign(**args)
    report = _read(args, execution)
    assert report.status == "UNRESOLVED" and report.original_result is not None
    protective = [x for x in report.execution_facts if x.purpose == "protective"]
    assert len(protective) == 1
    receipt = protective[0].receipt
    assert receipt.requested_plan.planned_fills[0].quantity == 5
    assert receipt.committed_fills[0].quantity == 2 and not receipt.complete
    assert receipt.state.cash_balance == Decimal("400")
    assert report.original_result.original_artifacts.final_state == receipt.state
    assert all(
        not t.complete_interval and t.outcome != "COMPLETED" for t in report.trials
    )


def test_final_close_breach_cannot_complete_without_a_corrective_next_open(
    tmp_path: Path,
) -> None:
    args = _correction_arguments(tmp_path, close_breach=False, final_close_breach=True)
    execution = execute_controlled_campaign(**args)
    report = _read(args, execution)
    assert report.original_result is not None
    assert report.original_result.classification == "complete"
    assert report.status == "UNRESOLVED" and not report.economics.complete
    assert any(
        "PROTECTIVE" in reason or "CORRECTION" in reason for reason in report.reasons
    )
    assert report.trials[0].outcome == "UNRESOLVED"
    assert not report.trials[0].complete_interval


@pytest.mark.parametrize("committed", (False, True))
def test_actual_receipt_retention_loss_never_resets_or_reexecutes_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    committed: bool,
) -> None:
    from drift.loop import stage1_controlled_journal as journal_module

    args = _partial_arguments(tmp_path)
    original_append = append_envelope

    def lose_ack(
        ledger: Any, envelope: C.ControlledEnvelopeV1, *, when: datetime, key: str
    ) -> Any:
        if isinstance(envelope.record, C.ActualExecutionRecordV1):
            if committed:
                original_append(ledger, envelope, when=when, key=key)
            raise OSError("injected actual receipt acknowledgment loss")
        return original_append(ledger, envelope, when=when, key=key)

    with monkeypatch.context() as patch:
        patch.setattr(journal_module, "append_envelope", lose_ack)
        execution = execute_controlled_campaign(**args)
    assert execution.m0_status == "completed"
    assert execution.terminal is None and execution.retention_error is not None
    journal = _capture(args, execution)
    assert sum(
        isinstance(row.record, C.ActualExecutionRecordV1) for row in journal.rows
    ) == int(committed)
    report = _read(args, execution)
    assert report.status == "UNRESOLVED" and report.original_result is not None
    state = report.original_result.original_artifacts.final_state
    assert state.cash_balance == Decimal("9603") and state.holdings[0].quantity == 4
    assert state.cumulative_transaction_costs == Decimal("1")
    assert not report.economics.complete
    assert all(t.outcome != "COMPLETED" for t in report.trials)


def test_undeclared_fill_session_refuses_before_manifest_or_claim(
    tmp_path: Path,
) -> None:
    args = controlled_arguments(tmp_path)
    args["execution_policy"] = _policy(session=99, quantity=4)
    before = args["origin"].verified_events()
    with pytest.raises(ValueError, match="UNDECLARED_SESSION"):
        execute_controlled_campaign(**args)
    assert args["origin"].verified_events() == before


def test_both_selectors_receive_same_original_reference_view_without_book_credit(
    tmp_path: Path,
) -> None:
    from drift.experiments.stage1_trial_provenance import (
        build_stage1_trial_provenance_snapshot,
    )
    from drift.intelligence.contracts import ResearchContext, compute_record_hash
    from drift.ledger.stage1_synthetic_account_receipts import (
        CLAIM,
        LocalSyntheticAccountReceiptStoreV1,
    )
    from drift.loop.stage1_reference_accounts import (
        build_reference_configuration,
        execute_reference_accounts,
    )
    from drift.loop.stage1_synthetic_account_lifecycle import (
        Stage1SyntheticAccountLifecycleV1,
    )
    from drift.loop.stage1_synthetic_research_execution import (
        original_portfolio_reference,
    )

    left = _correction_arguments(tmp_path, close_breach=False)
    engine = left["engine"]
    reference_engines = tuple(
        fixture._engine(
            bundle=engine.bundle,
            protocol=fixture._protocol(warmup=1),
            cost_model=engine.cost_model,
        )
        for _ in range(3)
    )
    configuration = build_reference_configuration(
        campaign=left["campaign"],
        arms=left["arms"],
        bindings=left["bindings"],
        expected_run_ids=left["expected_run_ids"],
        run_id="RUN-001",
        reference_campaign_id="SHARED-REFERENCE-CAMPAIGN",
        bound_at=left["clock"](),
        engines=reference_engines,
    )
    receipt = execute_reference_accounts(
        origin=left["origin"],
        configuration=configuration,
        engines=reference_engines,
        clock=left["clock"],
    )
    left.update(reference_configuration=configuration, reference_receipt=receipt)
    left_execution = execute_controlled_campaign(**left)
    left_report = _read(left, left_execution)
    assert left_report.original_result is not None

    right = dict(left)
    right["engine"] = fixture._engine(
        bundle=engine.bundle, cost_model=engine.cost_model
    )
    right["provenance"] = build_stage1_trial_provenance_snapshot(
        campaign=left["campaign"],
        arms=left["arms"],
        bindings=left["bindings"],
        expected_run_ids=left["expected_run_ids"],
        run_id="RUN-001",
        arm_id="ARM-R",
        checkpoint_id="CKPT-001",
        events=(),
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=left["origin"], clock=left["clock"]
    )
    right["account"] = Stage1SyntheticAccountLifecycleV1(
        campaign=left["campaign"],
        arms=left["arms"],
        bindings=left["bindings"],
        expected_run_ids=left["expected_run_ids"],
        provenance=right["provenance"],
        store=store,
    )
    right["engine"].prepare_opening_book(lifecycle=right["account"])
    original = right["account"].verified_original()
    context = left["context"].model_dump(mode="python")
    context["scope"]["arm_id"] = "ARM-R"
    context["scope"]["account_id"] = original.fields.portfolio_account_id
    context["portfolio_ref"] = original_portfolio_reference(original).model_dump(
        mode="python"
    )
    context["record_hash"] = compute_record_hash(context)
    right["context"] = ResearchContext.model_validate(context)
    point = right["checkpoints"][0]
    right["checkpoints"] = (
        point.model_copy(
            update={
                "fixture": point.fixture.model_copy(
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
    right_execution = execute_controlled_campaign(**right)
    right_report = _read(right, right_execution)
    assert right_report.original_result is not None
    views = []
    for args, execution in ((left, left_execution), (right, right_execution)):
        journal = _capture(args, execution)
        reference_rows = [
            row.record
            for row in journal.rows
            if isinstance(row.record, C.ReferenceViewRecordV1)
        ]
        assert len(reference_rows) == 1
        views.append(reference_rows[0].view.original_bytes())
        witnesses = [
            row.record
            for row in journal.rows
            if isinstance(row.record, C.InputWitnessRecordV1)
        ]
        assert len(witnesses) == 1
        assert witnesses[0].research_context.inputs[-1].role == (
            "causal_completed_b3_b4_b5_reference_accounts"
        )
        assert not witnesses[0].feedback
    assert views[0] == views[1]
    assert left_execution.allocation_id != right_execution.allocation_id
    assert (
        sum(event.event_type == CLAIM for event in left["origin"].verified_events())
        == 5
    )
    for report in (left_report, right_report):
        assert report.independent_account_count == 1
        assert report.economics.initial_net_nav == Decimal("10000")
        assert report.original_result is not None
        assert (
            report.original_result.original_artifacts.final_state.cash_balance
            == Decimal("1000")
        )
