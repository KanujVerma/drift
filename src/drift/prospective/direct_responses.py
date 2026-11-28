"""ChatGPT-plan requests with one-time supervised account setup."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import jwt
from openai import OpenAI

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import (
    PROSPECTIVE_REQUEST_ATTEMPT,
    PROSPECTIVE_REVIEW,
    append_manager_event,
    replay,
    thaw,
)
from drift.manager.models import InvestmentProposal
from drift.prospective.config import MODELS, submission_is_late
from drift.prospective.locking import pilot_lock
from drift.prospective.run import (
    Json,
    _execution_barriers,
    _expired_review_ids,
    _json_object,
    _review_context_time,
    apply_proposal,
    review_prompt,
)
from drift.prospective.window import active_window, verify_current_window

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
class PlanSession:
    """Drift's protected, previously verified OAuth session."""

    token: str = field(repr=False)
    subject: str
    expected_subject: str
    client_id: str
    scopes: frozenset[str]
    expires_at: datetime
    id_token: str = field(default="", repr=False)


@dataclass(frozen=True)
class GeneratedProposal:
    proposal: InvestmentProposal
    review_hash: str
    requested_model: str
    observed_model: str
    requested_effort: str
    observed_effort: str
    response_id: str
    account_subject_sha256: str
    client_id: str
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


def load_session(path: Path, *, expected_subject: str, now: datetime) -> PlanSession:
    """Load only a protected Drift sign-in and match its verified account."""
    if not expected_subject or now.tzinfo is None:
        raise ValueError("expected account and current time are required")
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or parent.st_mode & 0o077
    ):
        raise ValueError("Drift sign-in directory is not private")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 65536
        ):
            raise ValueError("Drift sign-in file is not private")
        try:
            value = json.load(handle)
        except ValueError, UnicodeDecodeError:
            raise ValueError("invalid Drift sign-in file") from None
    if not isinstance(value, dict):
        raise ValueError("invalid Drift sign-in file")
    account = value.get("account")
    registration = value.get("registration")
    tokens = value.get("tokens")
    if not all(isinstance(item, dict) for item in (account, registration, tokens)):
        raise ValueError("Drift sign-in is incomplete")
    assert isinstance(account, dict)
    assert isinstance(registration, dict)
    assert isinstance(tokens, dict)
    subject = account.get("subject")
    client_id = account.get("client_id")
    token = tokens.get("access_token")
    scopes = tokens.get("scopes")
    expires = tokens.get("expires_at")
    if (
        subject != expected_subject
        or not isinstance(client_id, str)
        or not client_id.startswith("oaiapp_")
        or client_id != registration.get("client_id")
        or not isinstance(value.get("host_id"), str)
        or not isinstance(token, str)
        or not token
        or token.startswith("sk-")
        or not isinstance(tokens.get("id_token"), str)
        or not isinstance(scopes, list)
        or not all(isinstance(scope, str) for scope in scopes)
        or not {PLAN_SCOPE, "resource.invoke"} <= set(scopes)
        or isinstance(expires, bool)
        or not isinstance(expires, (int, float))
    ):
        raise ValueError("Drift sign-in account or plan permission is invalid")
    try:
        expiry = datetime.fromtimestamp(expires, UTC)
    except ValueError, OverflowError, OSError:
        raise ValueError("invalid sign-in expiry") from None
    if expiry <= now:
        raise ValueError("Drift sign-in has expired")
    return PlanSession(
        token,
        subject,
        expected_subject,
        client_id,
        frozenset(scopes),
        expiry,
        id_token=tokens["id_token"],
    )


def verify_session_identity(session: PlanSession, http: httpx.Client) -> str:
    """Revalidate the retained ID token using OpenAI's current signing keys."""
    try:
        header = jwt.get_unverified_header(session.id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("invalid identity header")
        response = http.get("https://auth.openai.com/.well-known/jwks.json", timeout=10)
        response.raise_for_status()
        data = response.json()
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list):
            raise ValueError("invalid signing keys")
        matches = [
            key
            for key in keys
            if isinstance(key, dict)
            and key.get("kid") == header["kid"]
            and key.get("kty") == "RSA"
            and key.get("alg", "RS256") == "RS256"
            and key.get("use", "sig") == "sig"
        ]
        if len(matches) != 1:
            raise ValueError("identity signing key unavailable")
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
        claims = jwt.decode(
            session.id_token,
            key,
            algorithms=["RS256"],
            audience=session.client_id,
            issuer="https://auth.openai.com",
            leeway=5,
            options={"require": ["iss", "aud", "exp", "sub"]},
        )
        if (
            claims.get("sub") != session.subject
            or session.subject != session.expected_subject
        ):
            raise ValueError("signed identity does not match selected account")
        if "at_hash" in claims:
            digest = hashlib.sha256(session.token.encode("ascii")).digest()[:16]
            expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            if not isinstance(claims["at_hash"], str) or not hmac.compare_digest(
                claims["at_hash"], expected
            ):
                raise ValueError("access token does not match signed identity")
    except Exception:
        raise ValueError(
            "Drift signed account identity could not be verified"
        ) from None
    email = claims.get("email")
    if (
        not isinstance(email, str)
        or not email.isascii()
        or not 3 <= len(email) <= 254
        or email.count("@") != 1
        or any(ord(char) <= 32 or ord(char) == 127 for char in email)
        or claims.get("email_verified") is not True
    ):
        raise ValueError("signed identity lacks a usable verified email")
    return email


def _billing_path() -> Path:
    return Path.home() / ".local/share/drift/chatgpt-signin/billing-setup.json"


def _require_no_extra_billing(session: PlanSession, email: str) -> None:
    """Require the operator's one-time statement for this signed identity.

    This record does not verify the provider's current settings.
    """
    path = _billing_path()
    try:
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077
        ):
            raise ValueError("private directory required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 4096
            ):
                raise ValueError("private record required")
            record = json.load(handle)
        if record != {
            "version": 1,
            "subject": session.subject,
            "client_id": session.client_id,
            "verified_email": email,
            "attestation": "personal-plan-no-app-credits-no-auto-reload",
        }:
            raise ValueError("setup does not match signed identity")
    except OSError, ValueError, UnicodeDecodeError:
        raise RuntimeError("matching no-extra-billing setup required") from None


def setup_billing(*, expected_subject: str) -> None:
    """Record one terminal operator's point-in-time account and settings check."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("setup requires an interactive terminal")
    path = Path.home() / ".local/share/drift/chatgpt-signin/auth.json"
    session = load_session(
        path, expected_subject=expected_subject, now=datetime.now(UTC)
    )
    with httpx.Client(follow_redirects=False, trust_env=False) as http:
        email = verify_session_identity(session, http)
    print(f"Verified Drift account email: {email}")
    print(
        "In ChatGPT settings, check the SAME personal account and its saved settings: "
        "credit balance is zero, app credit use is off and automatic credit "
        "reload is off. Stop if any "
        "account or setting is unclear. This is a one-time operator statement; "
        "Drift cannot continuously verify those settings."
    )
    try:
        observed = input("Type the account email shown in ChatGPT settings: ")
        confirmed = input("Type I CHECKED to attest to the checks above: ")
    except EOFError, KeyboardInterrupt:
        raise RuntimeError("setup was not confirmed") from None
    if observed != email or confirmed != "I CHECKED":
        raise RuntimeError("setup was not confirmed or account did not match")
    # Recheck token validity after the operator's potentially long inspection.
    with httpx.Client(follow_redirects=False, trust_env=False) as http:
        if verify_session_identity(
            session, http
        ) != email or session.expires_at <= datetime.now(UTC):
            raise RuntimeError("signed identity expired or changed during setup")
    record = {
        "version": 1,
        "subject": session.subject,
        "client_id": session.client_id,
        "verified_email": email,
        "attestation": "personal-plan-no-app-credits-no-auto-reload",
    }
    # Exclusive creation avoids silently replacing an existing account binding.
    fd = os.open(
        _billing_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())


def _record_attempt(state: Path, review: SavedReview, session: PlanSession) -> None:
    """Commit an attempt before transmission while holding the pilot lock."""
    ledger = SQLiteLedger(state / "observation" / "sol.sqlite", create_schema=False)
    events = ledger.verified_events()
    key = f"prospective-request-attempt:{review.proposal_id}"
    if any(event.deduplication_key == key for event in events):
        raise ValueError(
            "request already attempted; resolve the review under supervision"
        )
    now = datetime.now(UTC)
    if now < max(event.timestamp for event in events):
        raise ValueError("request clock precedes recorded ledger activity")
    source = next(
        (event for event in events if event.event_hash == review.review_hash), None
    )
    if source is None or submission_is_late(source.timestamp, now):
        raise ValueError("review has passed its submission cutoff")
    _packet, _rules, _ph, _mh, book_id, _kernel = replay(events)
    append_manager_event(
        ledger,
        book_id=book_id,
        event_type=PROSPECTIVE_REQUEST_ATTEMPT,
        dedup_key=key,
        timestamp=now,
        payload={
            "proposal_id": review.proposal_id,
            "review_hash": review.review_hash,
            "route": "chatgpt-plan-responses",
            "account_subject_sha256": hashlib.sha256(
                session.subject.encode()
            ).hexdigest(),
            "client_id": session.client_id,
        },
        expected_previous_hash=events[-1].event_hash,
    )


def live_request(state: Path, *, expected_subject: str) -> dict[str, Any]:
    """Run one request for a review after identity and setup checks."""
    state = state.resolve()
    if state.is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("prospective state must be outside the source tree")
    if not state.is_dir():
        raise ValueError("prospective state does not exist")
    path = Path.home() / ".local/share/drift/chatgpt-signin/auth.json"
    session = load_session(
        path, expected_subject=expected_subject, now=datetime.now(UTC)
    )
    with httpx.Client(follow_redirects=False, trust_env=False) as identity_http:
        email = verify_session_identity(session, identity_http)
    _require_no_extra_billing(session, email)
    if any(
        os.environ.get(name)
        for name in (
            "OPENAI_CUSTOM_HEADERS",
            "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID",
            "OPENAI_ADMIN_KEY",
            "OPENAI_LOG",
        )
    ) or any(
        logging.getLogger(name).isEnabledFor(logging.DEBUG)
        for name in ("openai", "httpx", "httpcore")
    ):
        raise RuntimeError("unsafe ambient OpenAI SDK configuration")
    with pilot_lock(state):
        verify_current_window(state)
        review = saved_review(state)
        _record_attempt(state, review, session)
        with OpenAI(
            api_key=session.token,
            base_url="https://api.openai.com/v1",
            max_retries=0,
            http_client=httpx.Client(
                timeout=180, follow_redirects=False, trust_env=False
            ),
        ) as client:
            result = _request(client, session, review, now=datetime.now(UTC))
        verify_current_window(state)
        evidence: dict[str, Json] = {
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
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        ) as tmp:
            proposal_path = Path(tmp.name)
            tmp.write(result.proposal.model_dump_json())
        try:
            outcome = apply_proposal(
                state, "observation", "sol", proposal_path, runtime_evidence=evidence
            )
        finally:
            proposal_path.unlink()
        return {"proposal": outcome, "runtime_evidence": evidence}


def _request(
    client: OpenAI, session: PlanSession, review: SavedReview, *, now: datetime
) -> GeneratedProposal:
    """Request and validate a proposal after a caller has checked the billing gate."""
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
            deadline = time.monotonic() + 180
            total_bytes = 0
            for event in stream:
                data = event.model_dump(mode="json")
                total_bytes += len(json.dumps(data).encode("utf-8"))
                if time.monotonic() > deadline or total_bytes > 8_000_000:
                    raise AdapterError("inference stream exceeded its bound")
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
    response_id = completed.get("id")
    if not isinstance(response_id, str) or not response_id or len(response_id) > 200:
        raise ValueError("completion has no valid response identifier")
    return GeneratedProposal(
        proposal,
        review.review_hash,
        MODEL,
        MODEL,
        EFFORT,
        EFFORT,
        response_id,
        hashlib.sha256(session.subject.encode("utf-8")).hexdigest(),
        session.client_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervised direct Responses request")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--expected-subject", required=True)
    parser.add_argument("--setup-billing", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.setup_billing:
            if args.state is not None:
                parser.error("--state cannot be used with --setup-billing")
            setup_billing(expected_subject=args.expected_subject)
            print(
                "One-time account setup recorded; provider settings are not monitored."
            )
            return 0
        if args.state is None:
            parser.error("--state is required for a request")
        result = live_request(args.state, expected_subject=args.expected_subject)
    except ValueError as exc:
        if str(exc) == "signed identity lacks a usable verified email":
            print(str(exc), file=sys.stderr)
            return 2
        print(
            "Direct request unavailable; check authorization and billing controls.",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            "Direct request unavailable; check authorization and billing controls.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
