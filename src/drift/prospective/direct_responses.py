"""Offline-tested building blocks for a future supervised ChatGPT-plan connection.

There is deliberately no live client factory or command: Drift does not yet have
its own verified OAuth session or a verified no-extra-billing gate. The private
transport below is exercised with an in-memory HTTP transport in tests only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from openai import OpenAI

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import PROSPECTIVE_REVIEW, thaw
from drift.manager.models import InvestmentProposal
from drift.prospective.config import MODELS
from drift.prospective.locking import pilot_lock
from drift.prospective.run import (
    _execution_barriers,
    _expired_review_ids,
    _json_object,
    _review_context_time,
    review_prompt,
)
from drift.prospective.window import active_window

MODEL = "gpt-6.2-sol"
EFFORT: Literal["xhigh"] = "xhigh"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


@dataclass(frozen=True)
class SavedReview:
    proposal_id: str
    as_of: datetime
    review_hash: str
    instructions: str
    context: dict[str, Any]


@dataclass(frozen=True)
class _SessionFixture:
    """Test inputs only; fields here do not verify a real OAuth identity."""

    token: str = field(repr=False)
    subject: str
    expected_subject: str
    client_id: str
    scopes: frozenset[str]
    expires_at: datetime


@dataclass(frozen=True)
class GeneratedProposal:
    proposal: InvestmentProposal
    review_hash: str
    requested_model: str
    observed_model: str
    requested_effort: str
    observed_effort: str
    route: str = "chatgpt-plan-responses"


class AdapterError(ValueError):
    """Sanitized failure from the offline adapter."""


def saved_review(state: Path) -> SavedReview:
    """Read a single unresolved observation review from its verified ledger."""
    if not state.is_dir():
        raise ValueError("prospective state does not exist")
    with pilot_lock(state):
        window = active_window()
        if window is None or window.mode != "single-sol":
            raise ValueError("a configured single-Sol window is required")
        root = state / "observation"
        folder = root / "sol"
        ledger = SQLiteLedger.open_existing(root / "sol.sqlite")
        events = ledger.verified_events()
        if not events:
            raise ValueError("empty observation ledger")
        receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or not isinstance(
            receipt.get("proposal_id"), str
        ):
            raise ValueError("invalid review receipt")
        identifier = receipt["proposal_id"]
        reviews = [
            event
            for event in events
            if event.event_type == PROSPECTIVE_REVIEW
            and thaw(event.payload).get("proposal_id") == identifier
        ]
        resolved = set(_execution_barriers(ledger, max(e.timestamp for e in events)))
        resolved |= _expired_review_ids(events)
        if (
            len(reviews) != 1
            or identifier in resolved
            or any(
                event.deduplication_key == f"prospective-intent:{identifier}"
                for event in events
            )
        ):
            raise ValueError("review is missing, resolved, or already submitted")
        event = reviews[0]
        payload = thaw(event.payload)
        as_of = _review_context_time(event)
        context = payload.get("context")
        path = folder / "context.json"
        expected_prompt = review_prompt(
            identity=MODELS["sol"],
            proposal_id=identifier,
            as_of=as_of.astimezone(UTC).isoformat(),
            context_path=str(path),
        )
        if (
            not isinstance(context, dict)
            or payload.get("model_identity") != MODELS["sol"]
            or receipt.get("model_identity") != MODELS["sol"]
            or receipt.get("as_of") != as_of.isoformat()
            or json.loads(path.read_text(encoding="utf-8")) != context
            or payload.get("prompt") != expected_prompt
            or (folder / "prompt.txt").read_text(encoding="utf-8") != expected_prompt
        ):
            raise ValueError("review artifacts do not match the verified ledger")
        # A direct request has no file access; replace the local path with inline data.
        instructions = expected_prompt.removesuffix(f"Context file: {path}\n")
        return SavedReview(identifier, as_of, event.event_hash, instructions, context)


def live_request() -> None:
    """Fail closed until verified Drift authorization and billing gates exist."""
    raise RuntimeError("live ChatGPT-plan inference is not enabled")


def _request_for_test(
    client: OpenAI, session: _SessionFixture, review: SavedReview, *, now: datetime
) -> GeneratedProposal:
    """Run the adapter against a test client; never call with a live client."""
    if (
        not session.token
        or not session.client_id
        or not session.subject
        or session.subject != session.expected_subject
        or PLAN_SCOPE not in session.scopes
        or now.tzinfo is None
        or session.expires_at.tzinfo is None
        or session.expires_at <= now
        or client.api_key != session.token
    ):
        raise ValueError("missing or mismatched plan authorization")
    if not isinstance(client._client._transport, httpx.MockTransport):
        raise ValueError("live ChatGPT-plan inference is not enabled")
    try:
        catalog = client.get("/models", cast_to=dict[str, Any])
        models = catalog.get("models")
        if not isinstance(models, list) or not any(
            isinstance(item, dict)
            and item.get("slug") == MODEL
            and item.get("visibility") == "list"
            and item.get("supported_in_api") is not False
            for item in models
        ):
            raise AdapterError("required model unavailable")
        with client.responses.create(
            model=MODEL,
            reasoning={"effort": EFFORT},
            instructions=review.instructions,
            input=[
                {"role": "user", "content": json.dumps(review.context, sort_keys=True)}
            ],
            tools=[],
            tool_choice="none",
            store=False,
            stream=True,
        ) as stream:
            completed: dict[str, Any] | None = None
            for event in stream:
                data = event.model_dump(mode="json")
                kind = data.get("type")
                if kind in {"error", "response.failed", "response.incomplete"}:
                    raise AdapterError("inference failed or was incomplete")
                if kind == "response.completed":
                    if completed is not None or not isinstance(
                        data.get("response"), dict
                    ):
                        raise AdapterError("invalid completion")
                    completed = data["response"]
            if completed is None:
                raise AdapterError("inference stream ended without completion")
    except AdapterError:
        raise
    except Exception:
        # Provider and SDK errors can contain request bodies or credentials.
        raise AdapterError("plan request failed") from None
    reasoning = completed.get("reasoning")
    output = completed.get("output")
    if (
        completed.get("status") != "completed"
        or completed.get("model") != MODEL
        or not isinstance(reasoning, dict)
        or reasoning.get("effort") != EFFORT
        or not isinstance(output, list)
        or any(
            not isinstance(item, dict)
            or item.get("type") not in {"reasoning", "message"}
            for item in output
        )
    ):
        raise ValueError("completion model, effort, or output is unverified")
    messages = [item for item in output if item.get("type") == "message"]
    if len(messages) != 1 or messages[0].get("role") != "assistant":
        raise ValueError("completion has no single assistant message")
    content = messages[0].get("content")
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or content[0].get("type") != "output_text"
        or not isinstance(content[0].get("text"), str)
    ):
        raise ValueError("completion has no single text proposal")
    proposal = InvestmentProposal.model_validate_json(_json_object(content[0]["text"]))
    if (
        str(proposal.proposal_id) != review.proposal_id
        or proposal.as_of != review.as_of
        or proposal.model_identity != MODELS["sol"]
        or proposal.inference != "native_supervised"
        or proposal.execution != "simulation"
        or proposal.system_cost is not None
    ):
        raise ValueError("proposal does not match its saved review")
    visible = {
        row[key]
        for name, key in (("evidence", "evidence_id"), ("decisions", "outcome_id"))
        for row in review.context.get(name, [])
        if isinstance(row, dict) and isinstance(row.get(key), str)
    }
    if not set(proposal.evidence_ids) <= visible:
        raise ValueError("proposal cites evidence outside the saved review")
    return GeneratedProposal(proposal, review.review_hash, MODEL, MODEL, EFFORT, EFFORT)
