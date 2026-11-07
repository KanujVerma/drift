"""Synthetic/adversarial execution-trace vectors for #525/#379."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.execution_trace_preflight import preflight_execution_trace

SHA = "a" * 64


def trace_fixture() -> dict[str, object]:
    return {
        "profile": "drift-exec-intraday-v1",
        "request": {
            "run_id": "mock-run",
            "arm_id": "A",
            "account_id": "mock-account-A",
            "listing_ref": "mock-listed-instrument",
            "original_account_binding_ref": "mock-original-account-binding",
            "client_token": "original-token-A",
            "request_hash": SHA,
            "side": "BUY",
            "order_type": "LIMIT",
            "session": "REGULAR",
            "requested_qty": 100,
            "limit_price": "100.00",
        },
        "evidence": {
            "source_version_ref": "mock-version-v1",
            "input_cutoff_utc": "2026-01-02T10:32:06Z",
            "mandate_ref": "mock-mandate",
            "risk_ref": "mock-risk",
            "session_capability_ref": "mock-venue-capability",
            "venue_ref": "mock-listed-venue",
            "policy_revision_ref": "mock-sim-policy",
            "order_capability_ref": "mock-order-capability",
            "halt_at_arrival": "CLEAR",
        },
        "timeline": {
            "source_received_utc": "2026-01-02T10:32:03Z",
            "normalized_available_utc": "2026-01-02T10:32:04Z",
            "analysis_completed_utc": "2026-01-02T10:32:08Z",
            "decision_utc": "2026-01-02T10:32:09Z",
            "approval_utc": "2026-01-02T10:32:10Z",
            "risk_utc": "2026-01-02T10:32:10Z",
            "submission_utc": "2026-01-02T10:32:11Z",
            "arrival_utc": "2026-01-02T10:32:12Z",
        },
        "tie_proofs": {},
        "quote": {
            "kind": "EXECUTABLE_QUOTE",
            "quote_event_utc": "2026-01-02T10:32:06Z",
            "quote_received_utc": "2026-01-02T10:32:07Z",
            "max_age_seconds": "10",
            "quote_receipt_ref": "mock-quote",
            "venue_ref": "mock-listed-venue",
            "listing_ref": "mock-listed-instrument",
        },
        "attempts": [
            {
                "client_token": "original-token-A",
                "request_hash": SHA,
                "dispatched": True,
            },
        ],
        "reports": [
            {
                "report_id": "fill-1",
                "run_id": "mock-run",
                "arm_id": "A",
                "account_id": "mock-account-A",
                "client_token": "original-token-A",
                "request_hash": SHA,
                "cumulative_qty": 100,
                "execution_utc": "2026-01-02T10:32:13Z",
                "received_utc": "2026-01-02T10:32:14Z",
                "price": "99.99",
                "fee": "1.20",
                "fee_status": "known",
                "effect_ref": "ledger-effect-1",
            }
        ],
        "state": {
            "dispatch_knowledge": "ACKNOWLEDGED",
            "lifecycle": "FILLED",
            "claimed_accounting_complete": True,
            "terminal_receipt_ref": "mock-terminal",
            "ledger_receipt_ref": "mock-ledger",
            "valuation_receipt_ref": "mock-valuation",
        },
    }


def _inner(payload: dict[str, object], field: str) -> dict[str, object]:
    return cast(dict[str, object], payload[field])


def _reports(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], payload["reports"])


def _attempts(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], payload["attempts"])


def _fail(payload: dict[str, object], expected: str) -> None:
    report = preflight_execution_trace(payload)
    assert not report.review_ready
    assert report.reported_cumulative_qty is None
    assert not report.claimed_accounting_structurally_possible
    assert expected in report.reasons
    assert report.authorizes_order_placement is False
    assert report.proves_fill_or_settlement is False


_SCALAR_BOUNDARIES = (
    ("payload", "profile"),
    ("request", "run_id"),
    ("request", "arm_id"),
    ("request", "account_id"),
    ("request", "client_token"),
    ("request", "request_hash"),
    ("request", "listing_ref"),
    ("request", "original_account_binding_ref"),
    ("request", "side"),
    ("request", "order_type"),
    ("request", "session"),
    ("evidence", "halt_at_arrival"),
    ("evidence", "venue_ref"),
    ("quote", "kind"),
    ("quote", "venue_ref"),
    ("quote", "listing_ref"),
    ("attempts", "client_token"),
    ("attempts", "request_hash"),
    ("reports", "run_id"),
    ("reports", "arm_id"),
    ("reports", "account_id"),
    ("reports", "client_token"),
    ("reports", "request_hash"),
    ("reports", "fee_status"),
    ("state", "dispatch_knowledge"),
    ("state", "lifecycle"),
)


def _scalar_record(payload: dict[str, object], group: str) -> dict[str, object]:
    if group == "payload":
        return payload
    if group == "attempts":
        return _attempts(payload)[0]
    if group == "reports":
        return _reports(payload)[0]
    return _inner(payload, group)


@pytest.mark.parametrize(("group", "field"), _SCALAR_BOUNDARIES)
@pytest.mark.parametrize("behavior", ["spoof", "raise", "matching_subclass"])
def test_nested_scalar_subclasses_refuse_before_callbacks(
    group: str, field: str, behavior: str
) -> None:
    callbacks: list[str] = []

    class UntrustedScalar(str):
        def __eq__(self, other: object) -> bool:
            callbacks.append("equality")
            if behavior == "raise":
                raise RuntimeError("untrusted equality invoked")
            return True

        def __ne__(self, other: object) -> bool:
            callbacks.append("inequality")
            if behavior == "raise":
                raise RuntimeError("untrusted inequality invoked")
            return False

        def __hash__(self) -> int:
            callbacks.append("hash")
            raise RuntimeError("untrusted hash invoked")

    payload = trace_fixture()
    record = _scalar_record(payload, group)
    original = record[field]
    assert type(original) is str
    record[field] = UntrustedScalar(
        original if behavior == "matching_subclass" else "foreign-value"
    )
    _fail(payload, "payload.not_plain_json")
    assert callbacks == []


@pytest.mark.parametrize(("group", "field"), _SCALAR_BOUNDARIES)
def test_nested_foreign_objects_refuse_without_equality(group: str, field: str) -> None:
    callbacks: list[str] = []

    class ForeignScalar:
        def __eq__(self, other: object) -> bool:
            callbacks.append("equality")
            raise RuntimeError("foreign equality invoked")

        def __ne__(self, other: object) -> bool:
            callbacks.append("inequality")
            raise RuntimeError("foreign inequality invoked")

    payload = trace_fixture()
    _scalar_record(payload, group)[field] = ForeignScalar()
    _fail(payload, "payload.not_plain_json")
    assert callbacks == []


@pytest.mark.parametrize(
    "field",
    [
        "report_id",
        "run_id",
        "arm_id",
        "account_id",
        "client_token",
        "request_hash",
        "cumulative_qty",
        "execution_utc",
        "received_utc",
        "price",
        "fee",
        "fee_status",
        "effect_ref",
    ],
)
def test_redelivery_checks_concrete_values_before_dict_equality(field: str) -> None:
    callbacks: list[str] = []

    class RedeliveryScalar(str):
        def __eq__(self, other: object) -> bool:
            callbacks.append("equality")
            raise RuntimeError("redelivery equality invoked")

        def __ne__(self, other: object) -> bool:
            callbacks.append("inequality")
            raise RuntimeError("redelivery inequality invoked")

    payload = trace_fixture()
    replay = deepcopy(_reports(payload)[0])
    replay[field] = RedeliveryScalar("foreign-value")
    _reports(payload).append(replay)
    _fail(payload, "payload.not_plain_json")
    assert callbacks == []


@pytest.mark.parametrize(
    ("group", "field", "wrong", "reason"),
    [
        (
            "attempts",
            "client_token",
            "foreign-token",
            "attempts.0.new_or_foreign_token",
        ),
        ("attempts", "request_hash", "b" * 64, "attempts.0.changed_intent"),
        ("reports", "run_id", "foreign-run", "reports.0.run_id.identity_mismatch"),
        ("reports", "arm_id", "B", "reports.0.arm_id.identity_mismatch"),
        (
            "reports",
            "account_id",
            "foreign-account",
            "reports.0.account_id.identity_mismatch",
        ),
        (
            "reports",
            "client_token",
            "foreign-token",
            "reports.0.client_token.identity_mismatch",
        ),
        (
            "reports",
            "request_hash",
            "b" * 64,
            "reports.0.request_hash.identity_mismatch",
        ),
        ("request", "side", "OTHER", "request.side.invalid"),
        ("request", "order_type", "OTHER", "request.order_type.invalid"),
        ("request", "session", "OTHER", "request.session.invalid"),
        ("quote", "kind", "OTHER", "quote.kind.invalid"),
        ("evidence", "halt_at_arrival", "OTHER", "evidence.halt_at_arrival.invalid"),
        ("reports", "fee_status", "OTHER", "reports.0.fee_status.invalid"),
        ("state", "dispatch_knowledge", "OTHER", "state.dispatch_knowledge.invalid"),
        ("state", "lifecycle", "OTHER", "state.lifecycle.invalid"),
    ],
)
def test_plain_identity_and_enum_mismatches_still_refuse(
    group: str, field: str, wrong: str, reason: str
) -> None:
    payload = trace_fixture()
    _scalar_record(payload, group)[field] = wrong
    _fail(payload, reason)


@pytest.mark.parametrize("session", ["REGULAR", "PRE", "POST"])
def test_plain_limit_sessions_remain_reviewable(session: str) -> None:
    payload = trace_fixture()
    _inner(payload, "request")["session"] = session
    assert preflight_execution_trace(payload) == preflight_execution_trace(
        trace_fixture()
    )


def test_plain_market_order_and_shared_identical_redelivery_remain_reviewable() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["order_type"] = "MARKET"
    _inner(payload, "request")["limit_price"] = None
    _reports(payload).append(_reports(payload)[0])
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 100
    assert report.claimed_accounting_structurally_possible
    assert report.authorizes_order_placement is False
    assert report.proves_fill_or_settlement is False


def test_unknown_fee_remains_reviewable_only_without_complete_accounting() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["fee_status"] = "unknown"
    _reports(payload)[0]["fee"] = None
    _inner(payload, "state")["claimed_accounting_complete"] = False
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 100
    assert not report.claimed_accounting_structurally_possible
    assert report.authorizes_order_placement is False
    assert report.proves_fill_or_settlement is False


def test_cyclic_container_refuses_as_non_json() -> None:
    payload = trace_fixture()
    _reports(payload).append(payload)
    _fail(payload, "payload.not_plain_json")


def test_scalar_metaclass_equality_is_not_used_for_concrete_type_checks() -> None:
    callbacks: list[str] = []

    class UntrustedType(type):
        def __eq__(cls, other: object) -> bool:
            callbacks.append("type_equality")
            raise RuntimeError("untrusted type equality invoked")

        def __ne__(cls, other: object) -> bool:
            callbacks.append("type_inequality")
            raise RuntimeError("untrusted type inequality invoked")

    class ForeignScalar(metaclass=UntrustedType):
        pass

    payload = trace_fixture()
    _attempts(payload)[0]["client_token"] = ForeignScalar()
    _fail(payload, "payload.not_plain_json")
    assert callbacks == []


def test_shared_deep_plain_containers_keep_the_existing_unknown_field_refusal() -> None:
    payload = trace_fixture()
    shared: object = None
    for _ in range(3000):
        shared = [shared, shared]
    payload["unrecognized"] = shared
    _fail(payload, "payload.fields.not_exact")


@pytest.mark.parametrize("field", ["fee", "effect_ref"])
def test_deep_container_report_leaves_refuse_before_redelivery_equality(
    field: str,
) -> None:
    left: object = None
    right: object = None
    for _ in range(50_000):
        left = [left]
        right = [right]
    payload = trace_fixture()
    first = _reports(payload)[0]
    first[field] = left
    replay = dict(first)
    replay[field] = right
    _reports(payload).append(replay)
    _fail(payload, "reports.0.not_plain_scalars")


@pytest.mark.parametrize("field", ["client_token", "request_hash"])
def test_deep_container_attempt_identities_validate_both_operands(field: str) -> None:
    left: object = None
    right: object = None
    for _ in range(50_000):
        left = [left]
        right = [right]
    payload = trace_fixture()
    _inner(payload, "request")[field] = left
    _attempts(payload)[0][field] = right
    result = preflight_execution_trace(payload)
    assert not result.review_ready
    assert result.reported_cumulative_qty is None
    assert not result.claimed_accounting_structurally_possible
    assert "request.not_plain_scalars" in result.reasons
    assert "attempts.0.not_plain_scalars" in result.reasons
    assert result.authorizes_order_placement is False
    assert result.proves_fill_or_settlement is False


@pytest.mark.parametrize("container", ["list", "dict"])
@pytest.mark.parametrize(
    ("left_group", "left_field", "right_group", "right_field"),
    [
        ("request", "client_token", "attempts", "client_token"),
        ("request", "request_hash", "attempts", "request_hash"),
        ("request", "run_id", "reports", "run_id"),
        ("request", "arm_id", "reports", "arm_id"),
        ("request", "account_id", "reports", "account_id"),
        ("request", "client_token", "reports", "client_token"),
        ("request", "request_hash", "reports", "request_hash"),
        ("evidence", "venue_ref", "quote", "venue_ref"),
        ("request", "listing_ref", "quote", "listing_ref"),
    ],
)
def test_paired_identity_records_refuse_containers_on_both_sides(
    container: str,
    left_group: str,
    left_field: str,
    right_group: str,
    right_field: str,
) -> None:
    payload = trace_fixture()
    _scalar_record(payload, left_group)[left_field] = [] if container == "list" else {}
    _scalar_record(payload, right_group)[right_field] = (
        [] if container == "list" else {}
    )
    result = preflight_execution_trace(payload)
    assert not result.review_ready
    assert result.reported_cumulative_qty is None
    assert not result.claimed_accounting_structurally_possible
    for group in (left_group, right_group):
        prefix = group + ".0" if group in ("attempts", "reports") else group
        assert f"{prefix}.not_plain_scalars" in result.reasons
    assert result.authorizes_order_placement is False
    assert result.proves_fill_or_settlement is False


@pytest.mark.parametrize("container", ["list", "dict"])
@pytest.mark.parametrize(
    ("group", "field", "prefix"),
    [
        ("request", "order_type", "request"),
        ("evidence", "halt_at_arrival", "evidence"),
        ("timeline", "arrival_utc", "timeline"),
        ("quote", "kind", "quote"),
        ("attempts", "dispatched", "attempts.0"),
        ("reports", "fee_status", "reports.0"),
        ("state", "lifecycle", "state"),
    ],
)
def test_every_nested_leaf_record_requires_scalars_before_comparisons(
    container: str, group: str, field: str, prefix: str
) -> None:
    payload = trace_fixture()
    _scalar_record(payload, group)[field] = [] if container == "list" else {}
    _fail(payload, f"{prefix}.not_plain_scalars")


def test_coherent_synthetic_trace_still_grants_nothing() -> None:
    report = preflight_execution_trace(trace_fixture())
    assert report.review_ready
    assert report.reported_cumulative_qty == 100
    assert report.claimed_accounting_structurally_possible
    assert report.reasons == ()
    assert not report.authorizes_order_placement
    assert not report.proves_fill_or_settlement


def test_partially_filled_order_retains_open_obligation() -> None:
    payload = trace_fixture()
    _inner(payload, "state")["lifecycle"] = "PARTIAL"
    _inner(payload, "state")["claimed_accounting_complete"] = False
    _reports(payload)[0]["cumulative_qty"] = 20
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 20
    assert not report.claimed_accounting_structurally_possible


def test_cumulative_fills_are_not_summed_or_recounted() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["requested_qty"] = 10
    first = _reports(payload)[0]
    first["cumulative_qty"] = 5
    later = deepcopy(first)
    later["report_id"] = "fill-2"
    later["cumulative_qty"] = 10
    later["effect_ref"] = "ledger-effect-2"
    later["execution_utc"] = "2026-01-02T10:32:15Z"
    later["received_utc"] = "2026-01-02T10:32:16Z"
    _reports(payload).extend([later, deepcopy(first)])
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 10


def test_duplicate_id_with_mutated_payload_refuses() -> None:
    payload = trace_fixture()
    replay = deepcopy(_reports(payload)[0])
    replay["price"] = "80.00"
    _reports(payload).append(replay)
    _fail(payload, "reports.1.conflicting_redelivery")


def test_cumulative_decrease_refuses() -> None:
    payload = trace_fixture()
    earlier = _reports(payload)[0]
    earlier["cumulative_qty"] = 80
    second = deepcopy(earlier)
    second["report_id"] = "later-lower"
    second["cumulative_qty"] = 60
    _reports(payload).append(second)
    _fail(payload, "reports.1.cumulative_decreased")


@pytest.mark.parametrize(
    ("changed", "value", "reason"),
    [
        (
            "submission_utc",
            "2026-01-02T10:32:09Z",
            "causal.approval_utc->submission_utc.reversed",
        ),
        (
            "normalized_available_utc",
            "2026-01-02T10:32:10Z",
            "causal.normalized_available_utc->input_cutoff_utc.reversed",
        ),
        (
            "arrival_utc",
            "2026-01-02T10:32:10Z",
            "causal.submission_utc->arrival_utc.reversed",
        ),
    ],
)
def test_early_actions_and_late_information_fail(
    changed: str, value: str, reason: str
) -> None:
    payload = trace_fixture()
    _inner(payload, "timeline")[changed] = value
    _fail(payload, reason)


def test_coarse_timestamp_requires_external_causal_proof() -> None:
    payload = trace_fixture()
    _inner(payload, "timeline")["normalized_available_utc"] = "2026-01-02T10:32:03Z"
    _fail(
        payload,
        "causal.source_received_utc->normalized_available_utc.tie_unproven",
    )
    _inner(payload, "tie_proofs")["source_received_utc->normalized_available_utc"] = (
        "untrusted-external-ordering-reference"
    )
    assert preflight_execution_trace(payload).review_ready


def test_quote_staleness_and_bar_only_fill_fail() -> None:
    payload = trace_fixture()
    _inner(payload, "quote")["max_age_seconds"] = "2"
    _fail(payload, "quote.stale_at_arrival")
    payload = trace_fixture()
    _inner(payload, "quote")["kind"] = "BAR_ONLY"
    _fail(payload, "fills.bar_only_cannot_prove_execution")


def test_extended_market_order_without_capability_refuses() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["session"] = "POST"
    _inner(payload, "request")["order_type"] = "MARKET"
    _inner(payload, "request")["limit_price"] = None
    _fail(payload, "request.extended_session_requires_limit")


def test_halt_or_unknown_at_arrival_forbids_claimed_fill() -> None:
    payload = trace_fixture()
    _inner(payload, "evidence")["halt_at_arrival"] = "UNKNOWN"
    _fail(payload, "fills.halt_or_unknown_at_arrival")


def test_unknown_dispatch_cannot_be_reported_complete_or_resubmitted() -> None:
    payload = trace_fixture()
    _reports(payload).clear()
    state = _inner(payload, "state")
    state["dispatch_knowledge"] = "UNKNOWN"
    state["lifecycle"] = "UNKNOWN"
    state["claimed_accounting_complete"] = False
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 0
    assert not report.claimed_accounting_structurally_possible
    state["claimed_accounting_complete"] = True
    _fail(payload, "state.open_or_unknown_cannot_be_complete")
    state["claimed_accounting_complete"] = False
    _attempts(payload).append(
        {"client_token": "fresh-token", "request_hash": SHA, "dispatched": True}
    )
    _fail(payload, "attempts.1.new_or_foreign_token")


def test_unknown_fee_does_not_become_zero() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["fee_status"] = "unknown"
    _reports(payload)[0]["fee"] = None
    _fail(payload, "state.unknown_dispatch_or_fee_cannot_be_complete")


def test_buy_limit_sell_limit_and_unknown_price() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["price"] = "100.01"
    _fail(payload, "reports.0.buy_limit_exceeded")
    payload = trace_fixture()
    _inner(payload, "request")["side"] = "SELL"
    _reports(payload)[0]["price"] = "99.99"
    _fail(payload, "reports.0.sell_limit_exceeded")
    payload = trace_fixture()
    _reports(payload)[0]["price"] = "NaN"
    _fail(payload, "reports.0.price.invalid")


def test_duplicate_dispatch_and_foreign_intent_fail_closed() -> None:
    payload = trace_fixture()
    _attempts(payload).append(deepcopy(_attempts(payload)[0]))
    _fail(payload, "attempts.duplicate_placement")
    payload = trace_fixture()
    _attempts(payload)[0]["request_hash"] = "b" * 64
    _fail(payload, "attempts.0.changed_intent")


def test_partial_and_terminal_state_cannot_fake_completeness() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["cumulative_qty"] = 20
    _inner(payload, "state")["lifecycle"] = "PARTIAL"
    _fail(payload, "state.open_or_unknown_cannot_be_complete")
    payload = trace_fixture()
    _inner(payload, "state")["ledger_receipt_ref"] = ""
    _fail(payload, "state.ledger_receipt_ref.missing_for_complete")


def test_malformed_payload_or_bools_cannot_be_accepted_as_counts() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["requested_qty"] = True
    _fail(payload, "request.requested_qty.invalid")
    payload = trace_fixture()
    _reports(payload)[0]["cumulative_qty"] = True
    _fail(payload, "reports.0.cumulative_qty.invalid")
    assert not preflight_execution_trace([]).review_ready


def test_quote_and_report_identity_mismatch_are_refused() -> None:
    payload = trace_fixture()
    _inner(payload, "quote")["venue_ref"] = "unrelated-venue"
    _fail(payload, "quote.venue_mismatch")
    payload = trace_fixture()
    _inner(payload, "quote")["listing_ref"] = "unrelated-security"
    _fail(payload, "quote.listing_mismatch")
    payload = trace_fixture()
    _reports(payload)[0]["arm_id"] = "B"
    _fail(payload, "reports.0.arm_id.identity_mismatch")
    payload = trace_fixture()
    _reports(payload)[0]["account_id"] = "wrong-account"
    _fail(payload, "reports.0.account_id.identity_mismatch")


def test_late_report_with_earlier_event_time_is_refused() -> None:
    payload = trace_fixture()
    earlier = _reports(payload)[0]
    earlier["cumulative_qty"] = 25
    earlier["execution_utc"] = "2026-01-02T10:32:18Z"
    earlier["received_utc"] = "2026-01-02T10:32:19Z"
    later = deepcopy(earlier)
    later["report_id"] = "fill-backdated"
    later["cumulative_qty"] = 100
    later["effect_ref"] = "new-ledger-effect"
    later["execution_utc"] = "2026-01-02T10:32:16Z"
    later["received_utc"] = "2026-01-02T10:32:17Z"
    _reports(payload).append(later)
    _fail(payload, "reports.1.execution_time_reversed")
