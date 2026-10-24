"""Offline synthetic RESULT book and operating-cost evidence preflight, #532.

This pure helper consumes untrusted fixture metadata, not actual M2 artifacts.
It neither authenticates E1 account allocation nor admits scientific feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import cast

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_DECIMAL = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{1,12})?\Z")

_ROOT = frozenset(
    {
        "profile",
        "as_of_utc",
        "identity",
        "book",
        "cost_scope",
        "operating_receipts",
        "prior_result_hashes",
    }
)
_IDENTITY = frozenset(
    {
        "campaign_id",
        "run_id",
        "arm_id",
        "checkpoint_id",
        "trial_id",
        "portfolio_account_id",
        "e1_binding_hash",
        "result_hash",
        "trace_hash",
        "bundle_hash",
        "book_hash",
        "allocation_receipt_ref",
        "evaluation_classification",
        "result_available_utc",
        "source_lane",
    }
)
_BOOK = frozenset(
    {
        "currency",
        "flow_basis",
        "begin_nav_usd",
        "end_cash_usd",
        "end_holdings_value_usd",
        "end_pending_claims_value_usd",
        "end_net_nav_usd",
        "trading_fees_already_posted_usd",
        "fees_embedded_in_net_nav",
        "marks_complete",
        "trading_costs_complete",
        "realized_pnl_complete",
        "requested_interval_complete",
        "open_execution_state",
        "book_reconciliation_receipt_ref",
    }
)
_SCOPE = frozenset(
    {
        "expected_charge_ids",
        "coverage_complete",
        "coverage_receipt_ref",
        "coverage_available_utc",
        "attribution_policy_ref",
    }
)
_RECEIPT = frozenset(
    {
        "receipt_id",
        "charge_id",
        "arm_id",
        "category",
        "status",
        "amount_usd",
        "first_available_utc",
        "supersedes_receipt_id",
        "evidence_ref",
    }
)
_COST_STATUS = frozenset({"ACTUAL", "VERIFIED_ZERO", "ESTIMATE", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class ResultEconomicsPreflight:
    """Results are deterministic mock arithmetic, never platform authority."""

    structurally_reviewable: bool
    marked_nav_reconciled: bool
    marked_nav_usd: Decimal | None
    trading_net_gain_usd: Decimal | None
    trading_return_fraction: Decimal | None
    economic_gain_usd: Decimal | None
    cost_completeness: str
    excluded_late_receipt_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def proves_account_provisioning_or_result_binding(self) -> bool:
        return False

    @property
    def qualifies_scientific_result_or_execution(self) -> bool:
        return False


def _plain_json(value: object, depth: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value) <= 4096
    if type(value) is list:
        return len(value) <= 512 and all(
            _plain_json(item, depth + 1, budget) for item in value
        )
    if type(value) is dict:
        return len(value) <= 128 and all(
            type(key) is str
            and len(key) <= 128
            and _plain_json(item, depth + 1, budget)
            for key, item in value.items()
        )
    return False


def _mapping(
    value: object, expected: frozenset[str], label: str, problems: list[str]
) -> dict[str, object]:
    if type(value) is not dict:
        problems.append(f"{label}.not_plain_object")
        return {}
    result = cast(dict[str, object], value)
    if set(result) != expected:
        problems.append(f"{label}.fields.not_exact")
    return result


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _sha(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _utc(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timedelta(0) else None


def _money(value: object, *, positive: bool = False) -> Decimal | None:
    if type(value) is not str or len(value) > 42:
        return None
    if _DECIMAL.fullmatch(value) is None:
        return None
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None
    if not d.is_finite() or d < 0 or (positive and d == 0):
        return None
    return d


def _finite_decimal(value: Fraction) -> Decimal | None:
    """Construct an exact finite Decimal without an ambient rounding context.

    A reduced rational terminates in base ten only when its denominator has
    no prime factors other than two and five. All accepted monetary inputs,
    their sums and differences satisfy that condition. A derived return may
    not; return None instead of choosing a financial rounding convention.
    """
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return None
    places = max(twos, fives)
    coefficient = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    digits = tuple(int(digit) for digit in str(coefficient))
    return Decimal((int(value.numerator < 0), digits, -places))


def _costs(
    records: object,
    scope: dict[str, object],
    arm_id: object,
    cutoff: datetime | None,
    problems: list[str],
) -> tuple[Decimal | None, str, tuple[str, ...]]:
    """Compute distinct latest available charge revisions, not copied fees."""
    if type(records) is not list:
        problems.append("operating_receipts.not_plain_list")
        return None, "UNAVAILABLE", ()

    expected = scope.get("expected_charge_ids")
    if (
        type(expected) is not list
        or any(not _text(charge) for charge in expected)
        or len(set(cast(list[str], expected))) != len(expected)
    ):
        problems.append("cost_scope.expected_charge_ids.invalid")
        expected_ids: set[str] = set()
    else:
        expected_ids = set(cast(list[str], expected))
    if type(scope.get("coverage_complete")) is not bool:
        problems.append("cost_scope.coverage_complete.invalid")
    if not _text(scope.get("coverage_receipt_ref")):
        problems.append("cost_scope.coverage_receipt_ref.missing")
    if not _text(scope.get("attribution_policy_ref")):
        problems.append("cost_scope.attribution_policy_ref.missing")
    covered_at = _utc(scope.get("coverage_available_utc"))
    if covered_at is None:
        problems.append("cost_scope.coverage_available_utc.invalid")

    seen_receipts: dict[str, dict[str, object]] = {}
    by_charge: dict[str, dict[str, object]] = {}
    late: list[str] = []
    known_charge_ids: set[str] = set()
    for index, raw in enumerate(records):
        label = f"operating_receipts.{index}"
        rec = _mapping(raw, _RECEIPT, label, problems)
        receipt_id = rec.get("receipt_id")
        charge_id = rec.get("charge_id")
        if not _text(receipt_id) or not _text(charge_id):
            problems.append(f"{label}.identity.missing")
            continue
        assert isinstance(receipt_id, str)
        assert isinstance(charge_id, str)
        prior_exact = seen_receipts.get(receipt_id)
        if prior_exact is not None:
            if prior_exact != rec:
                problems.append(f"{label}.receipt_id.conflicting_redelivery")
            continue
        seen_receipts[receipt_id] = rec
        if rec.get("arm_id") != arm_id:
            problems.append(f"{label}.arm_id.mismatch")
        if rec.get("category") != "RESEARCH_OPERATING_NOT_BOOKED":
            problems.append(f"{label}.category.must_be_separate_from_book")
        if not _text(rec.get("evidence_ref")):
            problems.append(f"{label}.evidence_ref.missing")
        status = rec.get("status")
        if type(status) is not str or status not in _COST_STATUS:
            problems.append(f"{label}.status.invalid")
        amount = rec.get("amount_usd")
        if status == "UNKNOWN":
            if amount is not None:
                problems.append(f"{label}.unknown_cost_cannot_be_zero")
        else:
            value = _money(amount)
            if value is None:
                problems.append(f"{label}.amount_usd.invalid")
            if status == "VERIFIED_ZERO" and value != 0:
                problems.append(f"{label}.verified_zero_nonzero")

        available = _utc(rec.get("first_available_utc"))
        if available is None:
            problems.append(f"{label}.first_available_utc.invalid")
        prior = by_charge.get(charge_id)
        supersedes = rec.get("supersedes_receipt_id")
        if prior is None:
            if supersedes is not None:
                problems.append(f"{label}.unretained_predecessor")
        else:
            if supersedes != prior.get("receipt_id"):
                problems.append(f"{label}.correction_lineage_mismatch")
            prior_at = _utc(prior.get("first_available_utc"))
            if prior_at is not None and available is not None and available <= prior_at:
                problems.append(f"{label}.correction_not_later")
        by_charge[charge_id] = rec

        if cutoff is not None and available is not None:
            if available > cutoff:
                late.append(receipt_id)
            else:
                known_charge_ids.add(charge_id)

    if not known_charge_ids.issubset(expected_ids):
        problems.append("cost_scope.unexpected_charge_id")
    # An expected charge missing at the cutoff means unavailable, not zero.
    available_latest: dict[str, dict[str, object]] = {}
    for charge_id in sorted(known_charge_ids):
        candidates = [
            rec
            for rec in seen_receipts.values()
            if rec.get("charge_id") == charge_id
            and cutoff is not None
            and (at := _utc(rec.get("first_available_utc"))) is not None
            and at <= cutoff
        ]
        if candidates:
            available_latest[charge_id] = max(
                candidates,
                key=lambda rec: cast(datetime, _utc(rec["first_available_utc"])),
            )

    if covered_at is not None and scope.get("coverage_complete") is True:
        if any(
            (observed := _utc(rec.get("first_available_utc"))) is not None
            and observed > covered_at
            for rec in available_latest.values()
        ):
            problems.append("cost_scope.coverage_before_latest_charge")
    if (
        cutoff is None
        or covered_at is None
        or covered_at > cutoff
        or scope.get("coverage_complete") is not True
        or set(available_latest) != expected_ids
    ):
        return None, "UNAVAILABLE", tuple(late)
    if any(
        rec.get("status") not in ("ACTUAL", "VERIFIED_ZERO")
        for rec in available_latest.values()
    ):
        return None, "UNAVAILABLE", tuple(late)

    total = Fraction(0)
    for rec in available_latest.values():
        amount = _money(rec.get("amount_usd"))
        if amount is None:
            return None, "UNAVAILABLE", tuple(late)
        total += Fraction(amount)
    # A sum of finite base-ten money amounts is itself finite in base ten.
    exact_total = _finite_decimal(total)
    assert exact_total is not None
    return exact_total, "COMPLETE", tuple(late)


def preflight_result_economics(payload: object) -> ResultEconomicsPreflight:
    """Compute honest USD/no-flow fixture arithmetic with no producer trust."""

    def refused(causes: list[str]) -> ResultEconomicsPreflight:
        return ResultEconomicsPreflight(
            False,
            False,
            None,
            None,
            None,
            None,
            "UNAVAILABLE",
            (),
            tuple(causes),
        )

    if not _plain_json(payload, 0, [4096]):
        return refused(["payload.not_plain_json"])
    problems: list[str] = []
    root = _mapping(payload, _ROOT, "payload", problems)
    if root.get("profile") != "synthetic-result-economics-review-v1":
        problems.append("profile.invalid")
    cutoff = _utc(root.get("as_of_utc"))
    if cutoff is None:
        problems.append("as_of_utc.invalid")
    identity = _mapping(root.get("identity"), _IDENTITY, "identity", problems)
    book = _mapping(root.get("book"), _BOOK, "book", problems)
    scope = _mapping(root.get("cost_scope"), _SCOPE, "cost_scope", problems)

    for field in (
        "campaign_id",
        "run_id",
        "arm_id",
        "checkpoint_id",
        "trial_id",
        "portfolio_account_id",
    ):
        if not _text(identity.get(field)):
            problems.append(f"identity.{field}.missing")
    for field in (
        "e1_binding_hash",
        "result_hash",
        "trace_hash",
        "bundle_hash",
        "book_hash",
    ):
        if not _sha(identity.get(field)):
            problems.append(f"identity.{field}.invalid")
    # The prospective #508 issuer does not yet exist; treat refs as assertions.
    if identity.get("allocation_receipt_ref") is not None and not _text(
        identity.get("allocation_receipt_ref")
    ):
        problems.append("identity.allocation_receipt_ref.invalid")
    if identity.get("source_lane") != "SYNTHETIC":
        problems.append("identity.source_lane.must_be_synthetic")
    if identity.get("evaluation_classification") not in (
        "COMPLETE",
        "REJECTED",
        "INDETERMINATE",
    ):
        problems.append("identity.evaluation_classification.invalid")
    available_result = _utc(identity.get("result_available_utc"))
    if available_result is None:
        problems.append("identity.result_available_utc.invalid")

    old_hashes = root.get("prior_result_hashes")
    if type(old_hashes) is not list or any(not _sha(value) for value in old_hashes):
        problems.append("prior_result_hashes.invalid")
    else:
        if len(set(cast(list[str], old_hashes))) != len(old_hashes):
            problems.append("prior_result_hashes.duplicate")
        if identity.get("result_hash") in old_hashes:
            problems.append("prior_result_hashes.same_result_not_independent")

    if book.get("currency") != "USD":
        problems.append("book.currency.unsupported")
    if book.get("flow_basis") != "NO_EXTERNAL_FLOWS":
        problems.append("book.flow_basis.unsupported")
    if not _text(book.get("book_reconciliation_receipt_ref")):
        problems.append("book.book_reconciliation_receipt_ref.missing")
    figures: dict[str, Decimal | None] = {}
    for field in (
        "begin_nav_usd",
        "end_cash_usd",
        "end_holdings_value_usd",
        "end_pending_claims_value_usd",
        "end_net_nav_usd",
        "trading_fees_already_posted_usd",
    ):
        figures[field] = _money(book.get(field), positive=(field == "begin_nav_usd"))
        if figures[field] is None:
            problems.append(f"book.{field}.invalid")
    marked_ok = all(value is not None for value in figures.values())
    if marked_ok:
        marked_sum = (
            Fraction(cast(Decimal, figures["end_cash_usd"]))
            + Fraction(cast(Decimal, figures["end_holdings_value_usd"]))
            + Fraction(cast(Decimal, figures["end_pending_claims_value_usd"]))
        )
        if marked_sum != Fraction(cast(Decimal, figures["end_net_nav_usd"])):
            problems.append("book.nav_cash_holdings_claims_mismatch")
            marked_ok = False

    for field in (
        "fees_embedded_in_net_nav",
        "marks_complete",
        "trading_costs_complete",
        "realized_pnl_complete",
        "requested_interval_complete",
    ):
        if type(book.get(field)) is not bool:
            problems.append(f"book.{field}.invalid")
    if book.get("fees_embedded_in_net_nav") is not True:
        problems.append("book.trading_fees_not_proven_embedded")

    if book.get("open_execution_state") not in (
        "NONE",
        "OPEN",
        "UNKNOWN",
    ):
        problems.append("book.open_execution_state.invalid")
    costs, cost_completeness, late = _costs(
        root.get("operating_receipts"),
        scope,
        identity.get("arm_id"),
        cutoff,
        problems,
    )
    structural = not problems
    mark_value = (
        cast(Decimal, figures["end_net_nav_usd"])
        if structural
        and marked_ok
        and cutoff is not None
        and available_result is not None
        and available_result <= cutoff
        else None
    )
    scope_ok = (
        structural
        and identity.get("evaluation_classification") == "COMPLETE"
        and cutoff is not None
        and available_result is not None
        and available_result <= cutoff
        and all(
            book.get(k) is True
            for k in (
                "marks_complete",
                "trading_costs_complete",
                "realized_pnl_complete",
                "requested_interval_complete",
            )
        )
        and book.get("open_execution_state") == "NONE"
    )
    scope_reasons: list[str] = []
    if structural and not scope_ok:
        if available_result is not None and cutoff is not None:
            if available_result > cutoff:
                scope_reasons.append("result.not_available_at_cutoff")
        if book.get("open_execution_state") != "NONE":
            scope_reasons.append("book.unresolved_execution_not_a_complete_result")
        if identity.get("evaluation_classification") != "COMPLETE":
            scope_reasons.append("result.evaluator_not_complete")
        for field in (
            "marks_complete",
            "trading_costs_complete",
            "realized_pnl_complete",
            "requested_interval_complete",
        ):
            if book.get(field) is not True:
                scope_reasons.append(f"book.{field}.not_complete")

    trading_gain: Decimal | None = None
    trading_return: Decimal | None = None
    economic_gain: Decimal | None = None
    if scope_ok and mark_value is not None:
        begin = cast(Decimal, figures["begin_nav_usd"])
        exact_gain = Fraction(mark_value) - Fraction(begin)
        trading_return = _finite_decimal(exact_gain / Fraction(begin))
        if trading_return is None:
            return refused(["book.trading_return_nonterminating_decimal"])
        trading_gain = _finite_decimal(exact_gain)
        assert trading_gain is not None
        # Trading fees are already posted in net NAV. Never charge them again.
        if cost_completeness == "COMPLETE" and costs is not None:
            economic_gain = _finite_decimal(exact_gain - Fraction(costs))
            assert economic_gain is not None
    return ResultEconomicsPreflight(
        structural,
        marked_ok and structural,
        mark_value,
        trading_gain,
        trading_return,
        economic_gain,
        cost_completeness,
        late,
        tuple([*problems, *scope_reasons]),
    )
