"""Offline-only Responses adapter checks; no credentials or external calls."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import OpenAI
from test_prospective_pilot_safety import collection
from test_prospective_single_sol import configured

from drift.ledger.sqlite import SQLiteLedger
from drift.prospective.collect import Bar
from drift.prospective.direct_responses import (
    PLAN_SCOPE,
    _request_for_test,
    _SessionFixture,
    live_request,
    saved_review,
)
from drift.prospective.run import apply_proposal, perform_daily


@pytest.fixture
def review_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Any]:
    issued = configured(tmp_path, monkeypatch)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    return tmp_path, saved_review(tmp_path)


def session() -> _SessionFixture:
    return _SessionFixture(
        token="fixture-oauth-token",
        subject="verified-subject",
        expected_subject="verified-subject",
        client_id="fixture-client",
        scopes=frozenset({PLAN_SCOPE}),
        expires_at=datetime(2026, 12, 2, tzinfo=UTC),
    )


def proposal(review: Any) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "proposal_id": review.proposal_id,
        "as_of": review.as_of.isoformat(),
        "action": "hold",
        "symbol": "AAPL",
        "quantity": 0,
        "thesis": "Insufficient evidence",
        "evidence_ids": [],
        "uncertainty": "Fixture",
        "allocation_reasoning": "Remain in cash",
        "exit_conditions": [],
        "execution": "simulation",
        "inference": "native_supervised",
        "model_identity": "codex/gpt-6.2-sol@xhigh",
    }


def completed(review: Any, **changes: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "id": "response-fixture",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "gpt-6.2-sol",
        "reasoning": {"effort": "xhigh"},
        "output": [
            {
                "id": "msg-fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(proposal(review)),
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
    }
    response.update(changes)
    return {"type": "response.completed", "sequence_number": 1, "response": response}


def client_for(events: list[dict[str, Any]], calls: list[httpx.Request]) -> OpenAI:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"models": [{"slug": "gpt-6.2-sol", "visibility": "list"}]}
            )
        data = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(
            200, text=data, headers={"content-type": "text/event-stream"}
        )

    return OpenAI(
        api_key="fixture-oauth-token",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def invoke(client: OpenAI, review: Any, auth: _SessionFixture | None = None) -> Any:
    return _request_for_test(
        client, auth or session(), review, now=datetime(2026, 12, 1, tzinfo=UTC)
    )


def test_inline_context_and_completed_response(review_state: tuple[Path, Any]) -> None:
    _, review = review_state
    calls: list[httpx.Request] = []
    result = invoke(client_for([completed(review)], calls), review)
    assert result.proposal.action == "hold"
    assert result.review_hash == review.review_hash
    assert result.requested_model == result.observed_model == "gpt-6.2-sol"
    assert result.requested_effort == result.observed_effort == "xhigh"
    assert len(calls) == 2
    assert calls[0].headers["authorization"] == "Bearer fixture-oauth-token"
    body = json.loads(calls[1].content)
    assert body["model"] == "gpt-6.2-sol"
    assert body["reasoning"] == {"effort": "xhigh"}
    assert body["store"] is False and body["stream"] is True and body["tools"] == []
    assert json.loads(body["input"][0]["content"]) == review.context
    assert "Context file:" not in body["instructions"]


@pytest.mark.parametrize("kind", ["response.failed", "response.incomplete", "error"])
def test_failed_or_incomplete_stream(review_state: tuple[Path, Any], kind: str) -> None:
    _, review = review_state
    event = completed(review)
    event["type"] = kind
    if kind == "error":
        event.update(
            {"code": "subscription_sharing_usage_limit_exceeded", "message": "limit"}
        )
    with pytest.raises(ValueError):
        invoke(client_for([event], []), review)


@pytest.mark.parametrize(
    "events", [[], [{"type": "response.created", "sequence_number": 1}]]
)
def test_interrupted_stream(
    review_state: tuple[Path, Any], events: list[dict[str, Any]]
) -> None:
    _, review = review_state
    with pytest.raises(ValueError):
        invoke(client_for(events, []), review)


@pytest.mark.parametrize(
    "change",
    [
        {"model": "gpt-other"},
        {"reasoning": {"effort": "high"}},
        {"reasoning": None},
        {"output": [{"type": "function_call", "name": "unsafe"}]},
    ],
)
def test_unverified_completion(
    review_state: tuple[Path, Any], change: dict[str, Any]
) -> None:
    _, review = review_state
    with pytest.raises(ValueError):
        invoke(client_for([completed(review, **change)], []), review)


@pytest.mark.parametrize(
    "change",
    [
        {"token": ""},
        {"subject": "wrong"},
        {"scopes": frozenset()},
        {"expires_at": datetime(2026, 11, 30, tzinfo=UTC)},
    ],
)
def test_missing_or_wrong_authorization_stops_before_request(
    review_state: tuple[Path, Any], change: dict[str, Any]
) -> None:
    _, review = review_state
    calls: list[httpx.Request] = []
    with pytest.raises(ValueError):
        invoke(
            client_for([completed(review)], calls), review, replace(session(), **change)
        )
    assert not calls


def test_invalid_proposal_and_tampered_review(review_state: tuple[Path, Any]) -> None:
    state, review = review_state
    event = completed(review)
    event["response"]["output"][0]["content"][0]["text"] = '{"action":"buy"}'
    with pytest.raises(ValueError):
        invoke(client_for([event], []), review)
    context = state / "observation" / "sol" / "context.json"
    context.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="do not match"):
        saved_review(state)


def test_live_path_is_disabled() -> None:
    with pytest.raises(RuntimeError, match="not enabled"):
        live_request()


def test_real_transport_is_blocked_before_network(
    review_state: tuple[Path, Any],
) -> None:
    _, review = review_state
    with OpenAI(api_key="fixture-oauth-token", max_retries=0) as client:
        with pytest.raises(ValueError, match="not enabled"):
            invoke(client, review)


def test_uncited_context_cannot_be_invented(review_state: tuple[Path, Any]) -> None:
    _, review = review_state
    event = completed(review)
    value = proposal(review)
    value["evidence_ids"] = ["not-in-context"]
    value["exit_conditions"] = [{"kind": "narrative", "text": "Reassess."}]
    event["response"]["output"][0]["content"][0]["text"] = json.dumps(value)
    with pytest.raises(ValueError, match="outside the saved review"):
        invoke(client_for([event], []), review)


def test_provider_usage_limit_is_sanitized(review_state: tuple[Path, Any]) -> None:
    _, review = review_state
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"models": [{"slug": "gpt-6.2-sol", "visibility": "list"}]}
            )
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": "subscription_sharing_usage_limit_exceeded",
                    "message": "sensitive fixture text",
                    "type": "limit",
                }
            },
        )

    client = OpenAI(
        api_key="fixture-oauth-token",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="plan request failed") as error:
        invoke(client, review)
    assert "sensitive fixture text" not in str(error.value)
    assert len(calls) == 2


def test_model_unavailable_stops_before_inference(
    review_state: tuple[Path, Any],
) -> None:
    _, review = review_state
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"models": [{"slug": "other", "visibility": "list"}]}
        )

    client = OpenAI(
        api_key="fixture-oauth-token",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="model unavailable"):
        invoke(client, review)
    assert len(calls) == 1


def test_proposal_reuses_submission_and_seal(
    review_state: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = review_state
    result = invoke(client_for([completed(review)], []), review)
    path = state / "generated-proposal.json"
    path.write_text(result.proposal.model_dump_json(), encoding="utf-8")
    clocks = iter(
        (
            review.as_of + timedelta(minutes=5),
            review.as_of + timedelta(minutes=5, seconds=1),
            review.as_of + timedelta(minutes=5, seconds=2),
        )
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return next(clocks)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    accepted = apply_proposal(state, "observation", "sol", path)
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
    kinds = [event.event_type for event in ledger.verified_events()]
    assert kinds.index("manager.decision") < kinds.index("manager.prospective_seal")
    with pytest.raises(ValueError, match="resolved|submitted"):
        saved_review(state)
