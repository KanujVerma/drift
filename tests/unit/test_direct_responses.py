"""Offline-only Responses adapter checks; no credentials or external calls."""

import base64
import hashlib
import json
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from openai import OpenAI
from test_prospective_pilot_safety import collection
from test_prospective_single_sol import configured

from drift.ledger.sqlite import SQLiteLedger
from drift.prospective.collect import Bar
from drift.prospective.direct_responses import (
    PLAN_SCOPE,
    PlanSession,
    _record_attempt,
    _request,
    live_request,
    load_session,
    saved_review,
    verify_session_identity,
)
from drift.prospective.locking import pilot_lock
from drift.prospective.run import apply_proposal, perform_daily, resolve_expired_review


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


def session() -> PlanSession:
    return PlanSession(
        token="fixture-oauth-token",
        subject="verified-subject",
        expected_subject="verified-subject",
        client_id="oaiapp_fixture",
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


def invoke(client: OpenAI, review: Any, auth: PlanSession | None = None) -> Any:
    return _request(
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
    assert "max_output_tokens" not in body
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


def test_live_path_is_blocked_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "drift.prospective.direct_responses.load_session", lambda *a, **k: session()
    )

    def unexpected_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("network client must not be created")

    monkeypatch.setattr("drift.prospective.direct_responses.OpenAI", unexpected_client)
    with pytest.raises(RuntimeError, match="no-extra-billing"):
        live_request(tmp_path, expected_subject="verified-subject")


def test_ambient_sdk_headers_stop_before_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "drift.prospective.direct_responses.load_session", lambda *a, **k: session()
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses._require_no_extra_billing", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_session_identity", lambda *a: None
    )
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "fixture: untrusted")
    with pytest.raises(RuntimeError, match="unsafe ambient"):
        live_request(tmp_path, expected_subject="verified-subject")


def test_uncited_context_cannot_be_invented(review_state: tuple[Path, Any]) -> None:
    _, review = review_state
    event = completed(review)
    value = proposal(review)
    value["evidence_ids"] = ["not-in-context"]
    value["exit_conditions"] = [{"kind": "narrative", "text": "Reassess."}]
    event["response"]["output"][0]["content"][0]["text"] = json.dumps(value)
    with pytest.raises(ValueError, match="outside the saved review"):
        invoke(client_for([event], []), review)


def test_reads_only_matching_private_drift_session(tmp_path: Path) -> None:
    directory = tmp_path / "drift-auth"
    directory.mkdir(mode=0o700)
    path = directory / "auth.json"
    value: dict[str, Any] = {
        "host_id": "urn:uuid:fixture",
        "registration": {"client_id": "oaiapp_fixture"},
        "account": {"client_id": "oaiapp_fixture", "subject": "verified-subject"},
        "tokens": {
            "access_token": "fixture-oauth-token",
            "id_token": "fixture-id-token",
            "scopes": [PLAN_SCOPE, "resource.invoke"],
            "expires_at": datetime(2026, 12, 2, tzinfo=UTC).timestamp(),
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    now = datetime(2026, 12, 1, tzinfo=UTC)
    loaded = load_session(path, expected_subject="verified-subject", now=now)
    assert loaded.subject == "verified-subject"
    assert "fixture-oauth-token" not in repr(loaded)
    with pytest.raises(ValueError, match="account"):
        load_session(path, expected_subject="different-subject", now=now)
    value["tokens"]["access_token"] = "sk-paid-fixture"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="account"):
        load_session(path, expected_subject="verified-subject", now=now)
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match="not private"):
        load_session(path, expected_subject="verified-subject", now=now)


@pytest.mark.parametrize(
    "bad", [None, "bound", "wrong_hash", "subject", "audience", "signature", "expired"]
)
def test_saved_session_identity_is_verified_against_signing_key(
    bad: str | None,
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signing = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if bad == "signature"
        else private
    )
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update({"kid": "fixture", "alg": "RS256", "use": "sig"})
    claims = {
        "iss": "https://auth.openai.com",
        "aud": "wrong" if bad == "audience" else "oaiapp_fixture",
        "sub": "wrong" if bad == "subject" else "verified-subject",
        "exp": datetime.now(UTC) + timedelta(seconds=-30 if bad == "expired" else 600),
    }
    if bad in {"bound", "wrong_hash"}:
        value = b"fixture-oauth-token" if bad == "bound" else b"different-token"
        claims["at_hash"] = (
            base64.urlsafe_b64encode(hashlib.sha256(value).digest()[:16])
            .rstrip(b"=")
            .decode()
        )
    token = jwt.encode(claims, signing, algorithm="RS256", headers={"kid": "fixture"})
    auth = replace(session(), id_token=token)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://auth.openai.com/.well-known/jwks.json"
        return httpx.Response(200, json={"keys": [public]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        if bad in {None, "bound"}:
            verify_session_identity(auth, http)
            if bad is None:
                # Without at_hash, this verifies the ID token, not token pairing.
                verify_session_identity(replace(auth, token="different-token"), http)
        else:
            with pytest.raises(ValueError, match="could not be verified"):
                verify_session_identity(auth, http)


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
    evidence = {
        "route": result.route,
        "requested_model": result.requested_model,
        "observed_model": result.observed_model,
        "requested_effort": result.requested_effort,
        "observed_effort": result.observed_effort,
        "response_id": result.response_id,
        "account_subject_sha256": result.account_subject_sha256,
        "client_id": result.client_id,
        "review_hash": result.review_hash,
    }
    accepted = apply_proposal(
        state, "observation", "sol", path, runtime_evidence=evidence
    )
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
    events = ledger.verified_events()
    kinds = [event.event_type for event in events]
    assert kinds.index("manager.decision") < kinds.index("manager.prospective_seal")
    from drift.manager.book import thaw

    intent = next(
        event for event in events if event.event_type == "manager.prospective_intent"
    )
    assert thaw(intent.payload)["runtime_evidence"] == evidence
    with pytest.raises(ValueError, match="resolved|submitted"):
        saved_review(state)


def test_supervised_path_uses_shared_transport_and_persists_provenance(
    review_state: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = review_state
    calls: list[httpx.Request] = []
    auth = replace(session(), expires_at=review.as_of + timedelta(days=1))
    monkeypatch.setattr(
        "drift.prospective.direct_responses.load_session", lambda *a, **k: auth
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses._require_no_extra_billing", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_session_identity", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_current_window", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.OpenAI",
        lambda **k: client_for([completed(review)], calls),
    )
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

    class RequestClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return review.as_of + timedelta(minutes=4)

    monkeypatch.setattr("drift.prospective.direct_responses.datetime", RequestClock)
    outcome = live_request(state, expected_subject="verified-subject")
    assert outcome["proposal"]["status"] == "accepted"
    assert outcome["runtime_evidence"]["response_id"] == "response-fixture"
    assert outcome["runtime_evidence"]["route"] == "chatgpt-plan-responses"
    assert len(calls) == 2
    ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
    from drift.manager.book import thaw

    intent = next(
        event
        for event in ledger.verified_events()
        if event.event_type == "manager.prospective_intent"
    )
    assert thaw(intent.payload)["runtime_evidence"] == outcome["runtime_evidence"]


@pytest.mark.parametrize("failure", [TimeoutError, SystemExit])
def test_ambiguous_attempt_survives_failure_and_blocks_retry(
    review_state: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
) -> None:
    state, review = review_state
    auth = replace(session(), expires_at=review.as_of + timedelta(days=1))
    monkeypatch.setattr(
        "drift.prospective.direct_responses.load_session", lambda *a, **k: auth
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses._require_no_extra_billing", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_session_identity", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_current_window", lambda *a: None
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return review.as_of + timedelta(minutes=4)

    monkeypatch.setattr("drift.prospective.direct_responses.datetime", Clock)
    calls: list[httpx.Request] = []

    def interrupted(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"models": [{"slug": "gpt-6.2-sol", "visibility": "list"}]}
            )
        assert request.url.path == "/v1/responses"
        ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
        assert any(
            e.deduplication_key == f"prospective-request-attempt:{review.proposal_id}"
            for e in ledger.verified_events()
        )
        raise failure()

    def client(**kwargs: object) -> OpenAI:
        return OpenAI(
            api_key="fixture-oauth-token",
            base_url="https://api.openai.com/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(interrupted)),
        )

    monkeypatch.setattr("drift.prospective.direct_responses.OpenAI", client)
    expected_error = ValueError if failure is TimeoutError else SystemExit
    with pytest.raises(expected_error):
        live_request(state, expected_subject="verified-subject")
    with pytest.raises(ValueError, match="already attempted"):
        live_request(state, expected_subject="verified-subject")
    assert [call.url.path for call in calls] == ["/v1/models", "/v1/responses"]
    path = state / "manual-proposal.json"
    path.write_text(json.dumps(proposal(review)), encoding="utf-8")
    with pytest.raises(ValueError, match="direct request attempted"):
        apply_proposal(state, "observation", "sol", path)

    class AfterCutoff(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return review.as_of + timedelta(days=2)

    monkeypatch.setattr("drift.prospective.run.datetime", AfterCutoff)
    outcome = resolve_expired_review(
        state,
        "sol",
        review.proposal_id,
        "ambiguous request abandoned under supervision",
    )
    assert outcome["status"] == "expired"
    with pytest.raises(ValueError, match="resolved|submitted"):
        saved_review(state)


def test_parallel_requests_cannot_both_start(
    review_state: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = review_state
    auth = replace(session(), expires_at=review.as_of + timedelta(days=1))
    monkeypatch.setattr(
        "drift.prospective.direct_responses.load_session", lambda *a, **k: auth
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses._require_no_extra_billing", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_session_identity", lambda *a: None
    )
    monkeypatch.setattr(
        "drift.prospective.direct_responses.verify_current_window", lambda *a: None
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return review.as_of + timedelta(minutes=4)

    monkeypatch.setattr("drift.prospective.direct_responses.datetime", Clock)
    monkeypatch.setattr(
        "drift.prospective.direct_responses.OpenAI", lambda **k: client_for([], [])
    )
    entered, release = threading.Event(), threading.Event()

    def interrupted(*args: object, **kwargs: object) -> None:
        entered.set()
        assert release.wait(5)
        raise TimeoutError()

    monkeypatch.setattr("drift.prospective.direct_responses._request", interrupted)
    failures: list[BaseException] = []

    def first() -> None:
        try:
            live_request(state, expected_subject="verified-subject")
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(ValueError, match="busy"):
            live_request(state, expected_subject="verified-subject")
    finally:
        release.set()
        thread.join(5)
    assert (
        not thread.is_alive()
        and len(failures) == 1
        and isinstance(failures[0], TimeoutError)
    )


def test_expired_review_does_not_record_an_attempt(
    review_state: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = review_state
    ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
    before = ledger.verified_events()

    class AfterCutoff(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return review.as_of + timedelta(days=2)

    monkeypatch.setattr("drift.prospective.direct_responses.datetime", AfterCutoff)
    with pilot_lock(state), pytest.raises(ValueError, match="cutoff"):
        _record_attempt(state, review, session())
    assert ledger.verified_events() == before


def test_invalid_runtime_evidence_does_not_write_intent(
    review_state: tuple[Path, Any],
) -> None:
    state, review = review_state
    result = invoke(client_for([completed(review)], []), review)
    path = state / "generated-proposal.json"
    path.write_text(result.proposal.model_dump_json(), encoding="utf-8")
    ledger = SQLiteLedger.open_existing(state / "observation" / "sol.sqlite")
    before = ledger.verified_events()
    invalid = {
        "route": result.route,
        "requested_model": result.requested_model,
        "observed_model": "wrong-model",
        "requested_effort": result.requested_effort,
        "observed_effort": result.observed_effort,
        "response_id": result.response_id,
        "account_subject_sha256": result.account_subject_sha256,
        "client_id": result.client_id,
        "review_hash": result.review_hash,
    }
    with pytest.raises(ValueError, match="runtime evidence"):
        apply_proposal(state, "observation", "sol", path, runtime_evidence=invalid)
    assert ledger.verified_events() == before
