"""Live reviews use a bounded screen and retain the book's own memory."""

from datetime import UTC, datetime, timedelta
from importlib import import_module, util

from drift.prospective.config import mandate


def test_review_screens_current_evidence_and_keeps_own_outcome_memory() -> None:
    assert util.find_spec("drift.prospective.discovery") is not None
    review_context = import_module("drift.prospective.discovery").review_context
    as_of = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    evidence = []
    for i in range(64):
        observed = as_of - timedelta(days=64 - i)
        evidence.append(
            {
                "available_at": observed.isoformat(),
                "observed_at": observed.isoformat(),
                "evidence_id": f"price-{i}",
                "kind": "observation",
                "limitations": ["fixture"],
                "price": str(100 + i),
                "price_role": "close",
                "source_label": "fixture",
                "summary": f"Daily close {100 + i} for AAPL. Volume 10000000.",
                "symbol": "AAPL",
            }
        )
    context: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "book": {"cash": "10000", "holdings": []},
        "decisions": [{"outcome_id": "outcome:own", "status": "accepted"}],
        "feedback": [],
        "reflections": [],
        "evidence": evidence,
        "untrusted_text": True,
    }
    result = review_context(context, as_of)
    assert result["decisions"] == context["decisions"]
    assert len(result["evidence"]) < len(evidence)
    assert any(
        row["symbol"] == "AAPL" and row["shortlisted"] for row in result["screen"]
    )
    assert "Calculated from the context" in result["research"]


def test_pilot_uses_evidence_specific_citation_policy() -> None:
    from drift.prospective.config import pilot_mandate

    assert mandate().citation_policy == "uniform_age"
    assert pilot_mandate().citation_policy == "research"


def test_prompt_specifies_hold_symbol_and_structured_exit_conditions() -> None:
    from drift.prospective.run import review_prompt

    prompt = review_prompt(
        identity="codex/gpt-6.1-terra@xhigh",
        proposal_id="id",
        as_of="2026-11-27T18:00:00+00:00",
        context_path="context.json",
    )
    assert "symbol must be" in prompt
    assert '"kind": "narrative"' in prompt


def test_outside_suggestion_is_reported_as_an_escalation() -> None:
    review_context = import_module("drift.prospective.discovery").review_context
    as_of = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    context: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "book": {"cash": "10000", "holdings": []},
        "evidence": [
            {
                "symbol": "TSLA",
                "kind": "suggestion",
                "evidence_id": "suggestion-tsla",
                "observed_at": as_of.isoformat(),
                "available_at": as_of.isoformat(),
                "summary": "Review this company.",
                "limitations": ["user suggestion"],
                "source_label": "user",
                "price_role": None,
            }
        ],
    }
    result = review_context(context, as_of)
    assert result["escalations"] == [
        {
            "symbol": "TSLA",
            "reason": "outside simulated trading authorization",
            "evidence_ids": ["suggestion-tsla"],
        }
    ]


def test_outside_user_suggestion_reaches_both_pilot_reviews_without_authority(
    tmp_path: object,
) -> None:
    import json
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.ledger.sqlite import SQLiteLedger
    from drift.manager.book import replay
    from drift.prospective.collect import UserSuggestion
    from drift.prospective.run import perform_daily

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    note = UserSuggestion(
        "TSLA", "Investigate battery demand.", when - timedelta(minutes=1)
    )
    result = perform_daily(
        tmp_path, "observation", when, replace(collection(when), suggestions=(note,))
    )
    assert result["status"] == "processed"
    assert isinstance(result["escalations"], list)
    assert result["escalations"][0]["symbol"] == "TSLA"
    for name in ("terra", "sol"):
        folder = tmp_path / "observation" / name
        context = json.loads((folder / "context.json").read_text())
        assert context["escalations"][0]["symbol"] == "TSLA"
        assert (
            context["external_suggestions"][0]["summary"]
            == "Investigate battery demand."
        )
        ledger = SQLiteLedger.open_existing(tmp_path / "observation" / f"{name}.sqlite")
        packet, rules, *_ = replay(ledger.verified_events())
        assert "TSLA" not in rules.allowed_symbols
        assert "TSLA" not in {item.symbol for item in packet.instruments}


def test_outcome_memory_uses_only_later_visible_price_evidence() -> None:
    review_context = import_module("drift.prospective.discovery").review_context
    as_of = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    decided = as_of - timedelta(days=2)

    def price(name: str, observed: datetime) -> dict[str, object]:
        return {
            "symbol": "AAPL",
            "kind": "observation",
            "evidence_id": name,
            "observed_at": observed.isoformat(),
            "available_at": observed.isoformat(),
            "summary": "Close 100",
            "limitations": ["fixture"],
            "source_label": "fixture",
            "price_role": "close",
            "price": "100",
        }

    context: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "book": {"cash": "10000", "holdings": []},
        "decisions": [
            {
                "outcome_id": "outcome:1",
                "symbol": "AAPL",
                "as_of": decided.isoformat(),
                "status": "accepted",
            }
        ],
        "evidence": [
            price("before", decided - timedelta(days=1)),
            price("later", decided + timedelta(days=1)),
            price("future", as_of + timedelta(days=1)),
        ],
    }
    result = review_context(context, as_of)
    assert result["outcome_observations"] == [
        {
            "decision_id": "outcome:1",
            "symbol": "AAPL",
            "evidence_id": "later",
            "price": "100",
            "observed_at": (decided + timedelta(days=1)).isoformat(),
        }
    ]
    assert "later" in {item["evidence_id"] for item in result["evidence"]}


def test_screen_does_not_compute_returns_across_a_split() -> None:
    review_context = import_module("drift.prospective.discovery").review_context
    as_of = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    evidence: list[dict[str, object]] = []
    for i in range(65):
        observed = as_of - timedelta(days=65 - i)
        evidence.append(
            {
                "available_at": observed.isoformat(),
                "observed_at": observed.isoformat(),
                "evidence_id": f"price-{i}",
                "kind": "observation",
                "limitations": ["fixture"],
                "price": "100",
                "price_role": "close",
                "source_label": "fixture",
                "summary": "Daily close 100 for AAPL. Volume 10000000.",
                "symbol": "AAPL",
            }
        )
    evidence.append(
        {
            "available_at": as_of.isoformat(),
            "observed_at": as_of.isoformat(),
            "evidence_id": "alpaca:split:AAPL:2026-11-25",
            "kind": "news",
            "limitations": ["fixture"],
            "price": None,
            "price_role": None,
            "source_label": "alpaca-corporate-action",
            "summary": "forward_split AAPL ex_date 2026-11-25",
            "symbol": "AAPL",
        }
    )
    result = review_context(
        {
            "as_of": as_of.isoformat(),
            "book": {"cash": "10000", "holdings": []},
            "evidence": evidence,
        },
        as_of,
    )
    row = next(row for row in result["screen"] if row["symbol"] == "AAPL")
    assert row["sessions"] == 2
    assert row["return_63"] is None


def test_future_split_waits_for_new_york_date_in_review() -> None:
    from drift.prospective.discovery import review_context

    before_midnight = datetime(2026, 1, 6, 0, 30, tzinfo=UTC)
    close = datetime(2026, 1, 5, 21, tzinfo=UTC)
    context: dict[str, object] = {
        "book": {"cash": "10000", "holdings": []},
        "evidence": [
            {
                "available_at": close.isoformat(),
                "observed_at": close.isoformat(),
                "evidence_id": "price-before-split",
                "kind": "observation",
                "price": "100",
                "price_role": "close",
                "source_label": "fixture",
                "summary": "Daily close 100 for AAPL. Volume 10000000.",
                "symbol": "AAPL",
            },
            {
                "available_at": close.isoformat(),
                "observed_at": close.isoformat(),
                "evidence_id": "alpaca:split:AAPL:2026-01-06",
                "kind": "news",
                "price": None,
                "price_role": None,
                "source_label": "alpaca-corporate-action",
                "summary": "forward_split AAPL ex_date 2026-01-06",
                "symbol": "AAPL",
            },
        ],
    }
    before = review_context(context, before_midnight)
    assert before["unadjusted_splits"] == {}
    after = review_context(context, datetime(2026, 1, 6, 5, 0, tzinfo=UTC))
    assert after["unadjusted_splits"] == {"AAPL": "2026-01-06"}


def test_evening_fundamental_uses_new_york_date_without_future_leak() -> None:
    from drift.prospective.discovery import review_context

    as_of = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)
    close_at = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    fact_at = datetime(2026, 11, 28, 3, 30, tzinfo=UTC)
    close: dict[str, object] = {
        "available_at": close_at.isoformat(),
        "observed_at": close_at.isoformat(),
        "evidence_id": "aapl-close",
        "kind": "observation",
        "price": "100",
        "price_role": "close",
        "source_label": "fixture",
        "summary": "Daily close 100 for AAPL. Volume 10000000.",
        "symbol": "AAPL",
    }
    fact: dict[str, object] = {
        "available_at": fact_at.isoformat(),
        "observed_at": fact_at.isoformat(),
        "evidence_id": "aapl-eps",
        "kind": "fundamental",
        "price": None,
        "price_role": None,
        "source_label": "sec-companyfacts",
        "summary": "EarningsPerShareDiluted 5 USD period end 2025-12-31.",
        "symbol": "AAPL",
    }
    future = dict(fact)
    future.update(
        available_at=(as_of + timedelta(minutes=1)).isoformat(),
        observed_at=(as_of + timedelta(minutes=1)).isoformat(),
        evidence_id="future-eps",
        summary="EarningsPerShareDiluted 10 USD period end 2026-09-30.",
    )
    result = review_context(
        {"book": {"cash": "10000", "holdings": []}, "evidence": [close, fact, future]},
        as_of,
    )
    rows = result["screen"]
    assert isinstance(rows, list)
    row = next(row for row in rows if row["symbol"] == "AAPL")
    assert row["price_over_eps"] == "20.00"


def test_daily_saves_screen_and_compact_context_in_both_books(tmp_path: object) -> None:
    import json
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.prospective.collect import Bar
    from drift.prospective.run import perform_daily

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    days = [when - timedelta(days=offset) for offset in range(100, 0, -1)]
    sessions = [day for day in days if day.weekday() < 5][-64:]
    bars = tuple(
        Bar(
            "AAPL",
            day,
            "100",
            str(100 + i),
            when,
            "alpaca-bars-v2-iex-raw",
            "10000000",
            when,
        )
        for i, day in enumerate(sessions)
    )
    perform_daily(tmp_path, "observation", when, replace(collection(when), bars=bars))
    for name in ("terra", "sol"):
        root = tmp_path / "observation" / name
        saved = json.loads((root / "context.json").read_text())
        prompt = (root / "prompt.txt").read_text()
        assert any(
            row["symbol"] == "AAPL" and row["shortlisted"] for row in saved["screen"]
        )
        assert len(saved["evidence"]) < 64
        assert "screen" in prompt.lower() and "research" in prompt.lower()


def test_first_observation_cannot_start_after_the_fixed_window_begins(
    tmp_path: object,
) -> None:
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.prospective.run import perform_daily

    assert isinstance(tmp_path, Path)
    monday = datetime(2026, 11, 30, 18, 0, tzinfo=UTC)
    result = perform_daily(tmp_path, "observation", monday, collection(monday))
    assert result["status"] == "fresh_window_required"
    assert list(tmp_path.rglob("*.sqlite")) == []


def test_experimental_citation_guidance_is_opt_in() -> None:
    from drift.prospective.run import review_prompt

    args = dict(
        identity="codex/gpt-6.2-sol@xhigh",
        proposal_id="id",
        as_of="2024-01-31T22:00:00+00:00",
        context_path="context.json",
    )
    baseline = review_prompt(**args)
    assert baseline == review_prompt(**args, same_symbol_guidance=False)
    candidate = review_prompt(**args, same_symbol_guidance=True)
    assert (
        "every ID in evidence_ids must refer to the proposed trade's own symbol"
        in candidate
    )
    assert (
        "every ID in evidence_ids must refer to the proposed trade's own symbol"
        not in baseline
    )
    assert "If the evidence is not enough, abstain." in candidate
    assert "25% position cap" in candidate
