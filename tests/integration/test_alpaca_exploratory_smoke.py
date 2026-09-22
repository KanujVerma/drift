"""End-to-end exploratory smoke validation of the bounded Alpaca bridge.

What this module proves. Starting from pinned native Alpaca response bytes and
nothing else, the bridge retains the exact bytes in private storage outside
Git, mints an ``AcquisitionReceiptV1`` over a reconciled closed-world
inventory, maps the payloads onto standard Drift source records, gets every
mapped dataset accepted by the Drift public validators, runs the standard M1d
selection and schedule generation functions, reconstructs source-basis
``ExploratoryReconstructedSessionObservationV1`` evidence, builds an
``EvaluationInputBundleV1`` through the real builder, mints an exploratory
admission binding all six canonical Alpaca limitations, and drives the real
``SessionEvaluatorEngine`` to a sealed ``ExploratoryEvaluationResultV1`` with
``is_promotion_grade_evidence=False`` and a complete trace log.

What this module deliberately does NOT prove. It does not exercise strategy
decisioning, order execution, corporate-action accounting, or portfolio
valuation. It cannot: Alpaca publishes no realized session telemetry, and
``bind_observation_session`` classifies an observation as bound only through
realized open and close evidence, so the exploratory lane can supply no
``DerivedObservationViewV1`` for the engine to decide or account on. The
evaluation therefore halts ``INDETERMINATE`` at the first decision cutoff and
the reference strategy is never consulted. That is the honest fail-closed
outcome, and the assertions below state it explicitly so a green smoke test
can never be mistaken for a working evaluation.

Every provider byte is a pinned literal and no test here reads `.env`. Exactly
two tests open a socket, both to `127.0.0.1` and both deliberately: the
credential-leak tests in the redirect section below stand up two throwaway
local HTTP servers to prove, by execution, that a 302 from a provider cannot
carry `APCA-API-KEY-ID` or `APCA-API-SECRET-KEY` to a second origin. Nothing
else here opens a socket, and the bridge itself is exercised with `socket`
replaced by a raising stub.
"""

import http.server
import importlib.util
import os
import sys
import threading
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_alpaca_exploratory_adapter import (  # noqa: E402
    AAPL_ID,
    LOCKFILE_BYTES,
    MSFT_ID,
    PINNED_BARS,
    PINNED_CALENDAR,
    PINNED_CORPORATE_ACTIONS,
    PRODUCER_PACKAGE_BYTES,
    PRODUCER_SOURCE_BYTES,
    SESSION_DATES,
    assert_private_bytes_are_locked_down,
    pinned_origin_observations,
    pinned_request,
    pinned_tzif_bytes,
    repository_paths,
    run_pinned_intake,
)
from test_evaluator_engine import (  # noqa: E402
    FixedTargetStrategy,
    _cost_model,
    _protocol,
    _run_identity,
)

from drift.adapters.alpaca_exploratory import (  # noqa: E402
    AlpacaExploratoryIntakeResult,
)
from drift.domain.evaluator_portfolio import (  # noqa: E402
    LANE_ADMISSIBLE_MARK_GRADES,
    MarkEvidenceV1,
    MarkPriceV1,
)
from drift.domain.evaluator_results import (  # noqa: E402
    EvaluationClassification,
    ExploratoryEvaluationResultV1,
)
from drift.domain.evaluator_trace import (  # noqa: E402
    EvaluationPhase,
    evaluation_trace_log_hash,
)
from drift.evaluator.engine import (  # noqa: E402
    LANE_MARK_GRADE,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)
from drift.serialization.canonical import canonical_json  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "intake_alpaca_exploratory.py"

WARMUP_SESSIONS = 2
#: The exact cause the engine must record. It names the missing evidence class
#: rather than a generic failure, so a different fail-closed path cannot pass.
EXPECTED_HALT_CAUSE = (
    "no authorized decision evidence for the decision cutoff 2026-01-06T21:00:00+00:00"
)


@pytest.fixture(scope="module")
def intake(tmp_path_factory: pytest.TempPathFactory) -> AlpacaExploratoryIntakeResult:
    """Run the complete offline bridge once for the whole smoke module."""
    return run_pinned_intake(tmp_path_factory.mktemp("alpaca-smoke-private"))


def _engine(intake: AlpacaExploratoryIntakeResult) -> SessionEvaluatorEngine:
    return SessionEvaluatorEngine(
        bundle=intake.bundle,
        admission=intake.admission,
        protocol=_protocol(warmup=WARMUP_SESSIONS),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(),
        book_currency_namespace="iso4217",
        book_currency_code="USD",
    )


def _run(
    intake: AlpacaExploratoryIntakeResult,
) -> tuple[Any, FixedTargetStrategy]:
    engine = _engine(intake)
    strategy = FixedTargetStrategy(
        {session_date: ((AAPL_ID, 10),) for session_date in SESSION_DATES}
    )
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
    )
    return engine.run(strategy=strategy, run_identity=identity), strategy


# --- the layered pipeline, end to end ---------------------------------------------


def test_the_pipeline_completes_every_declared_layer(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    # 1 retained exact native bytes, 2 receipt, 3 mapped records,
    # 4 public validation, 5 M1d selection and generation,
    # 6 reconstruction, 7 bundle.
    assert (intake.retained.root / "objects" / "sha256").is_dir()
    assert intake.acquisition.receipt.byte_graph.objects
    assert intake.securities and intake.listings and intake.economic_terms.records
    assert [item.result.value for item in intake.validation_decisions] == ["pass"] * 4
    assert len(intake.session_clock.sessions) == len(SESSION_DATES)
    assert len(intake.reconstructions) == 2 * len(SESSION_DATES)
    assert intake.bundle.bundle_hash == intake.admission.input_bundle_hash


def test_the_quiet_window_smoke_run_yields_exploratory_evidence_only(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    artifacts, _strategy = _run(intake)
    result = artifacts.result

    assert isinstance(result, ExploratoryEvaluationResultV1)
    assert result.lane == "exploratory"
    assert result.is_promotion_grade_evidence is False
    assert result.admission.admission_hash == intake.admission.admission_hash
    assert result.run_identity.bundle_hash == intake.bundle.bundle_hash


def test_the_smoke_run_seals_a_complete_trace_log(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    artifacts, _strategy = _run(intake)
    trace = artifacts.trace

    assert trace.events
    assert trace.trace_hash == evaluation_trace_log_hash(trace)
    assert artifacts.result.trace_hash == trace.trace_hash
    assert tuple(item.sequence for item in trace.events) == tuple(
        range(len(trace.events))
    )
    kinds = [item.kind for item in trace.events]
    assert kinds.count("session_start") == WARMUP_SESSIONS
    assert kinds[-1] == "indeterminate_cause"
    # Every trace event binds a session the bridge's own clock contains.
    covered = {item.session_key for item in intake.session_clock.sessions}
    assert {item.session_key for item in trace.events} <= covered


def test_the_exploratory_lane_supplies_no_decision_evidence_and_halts(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    artifacts, strategy = _run(intake)
    result = artifacts.result

    assert intake.bundle.authentic_decision_views == ()
    assert intake.bundle.authentic_accounting_views == ()
    assert result.classification is EvaluationClassification.INDETERMINATE
    assert result.halted_session_index == WARMUP_SESSIONS - 1
    assert result.halt_reason == EXPECTED_HALT_CAUSE
    # Stated rather than hidden: the reference strategy is never consulted,
    # so this run proves pipeline plumbing and not strategy behaviour.
    assert strategy.seen == []
    cause = artifacts.trace.events[-1]
    assert cause.kind == "indeterminate_cause"
    assert cause.phase is EvaluationPhase.POST_CLOSE_DECISION
    assert cause.cause_kind == "indeterminate_valuation"
    assert cause.cause == EXPECTED_HALT_CAUSE


def test_the_smoke_run_replays_bitwise_identically(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    first, _ = _run(intake)
    second, _ = _run(intake)

    assert first.result.result_hash == second.result.result_hash
    assert first.trace.trace_hash == second.trace.trace_hash


def test_the_bridges_admission_can_only_produce_inadmissible_promotion_marks(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """The mark-grade half of non-promotability, asserted on the grade itself.

    Stated plainly so the quantifier is honest: this smoke run mints zero
    marks, because it halts INDETERMINATE before any position exists, so "every
    valuation is exploratory" would range over an empty set and could not fail.
    What is checked instead is the mapping the engine reads the grade from, the
    grade the engine actually resolved for this bridge's admission, and a
    `MarkPriceV1` carrying that grade: it is admissible in the exploratory lane
    and inadmissible in the promotion lane. Point `LANE_MARK_GRADE` at
    `promotion_grade` for the exploratory lane and every assertion below dies.
    """
    engine = _engine(intake)
    artifacts, _strategy = _run(intake)

    assert engine.admission.lane == "exploratory"
    assert engine.bundle.has_exploratory_reconstructions is True
    assert engine.bundle.source_snapshot_hash is None
    # No mark was taken, and the test says so rather than quantifying over none.
    assert artifacts.final_state.holdings == ()

    grade = LANE_MARK_GRADE[engine.admission.lane]
    assert grade == "exploratory"
    assert engine._mark_grade == grade
    assert grade in LANE_ADMISSIBLE_MARK_GRADES["exploratory"]
    assert grade not in LANE_ADMISSIBLE_MARK_GRADES["promotion"]

    mark = MarkPriceV1(
        security_id=AAPL_ID,
        close_price=Decimal("191.25"),
        evidence=MarkEvidenceV1(grade=grade, evidence_hash="a" * 64),
    )
    assert mark.evidence.grade == "exploratory"
    assert mark.evidence.grade not in LANE_ADMISSIBLE_MARK_GRADES["promotion"]
    # And the promotion lane is not simply empty of grades.
    assert LANE_ADMISSIBLE_MARK_GRADES["promotion"] == frozenset({"promotion_grade"})
    assert LANE_MARK_GRADE["promotion"] == "promotion_grade"


#: The same closed response with the dividend removed. Byte-for-byte the shape
#: Alpaca returns for a quiet window, so the with/without comparison below
#: differs in exactly one thing: whether a dividend exists.
NO_DIVIDEND_ACTIONS = (
    b'{"corporate_actions":{"cash_dividends":[]},"next_page_token":null}'
)
#: The pinned dividend moved onto 2026-01-06, which is inside the two sessions
#: the engine actually executes before it halts. With the pinned 2026-01-07 ex
#: date the engine never reaches the dividend at all, so an assertion about
#: what it did with it could not fail.
REACHED_DIVIDEND_ACTIONS = (
    PINNED_CORPORATE_ACTIONS.replace(
        b'"ex_date":"2026-01-07"', b'"ex_date":"2026-01-06"'
    )
    .replace(b'"record_date":"2026-01-08"', b'"record_date":"2026-01-07"')
    .replace(b'"process_date":"2026-01-07"', b'"process_date":"2026-01-06"')
)


def _intake_with_actions(root: Path, actions: bytes) -> AlpacaExploratoryIntakeResult:
    from drift.adapters.alpaca_exploratory import (
        AlpacaNativePayloads,
        run_alpaca_exploratory_intake,
    )

    return run_alpaca_exploratory_intake(
        request=pinned_request(),
        payloads=AlpacaNativePayloads(
            bars=PINNED_BARS,
            calendar=PINNED_CALENDAR,
            corporate_actions=actions,
        ),
        private_root=root,
    )


def test_a_terms_only_corporate_action_moves_no_cash_or_shares(
    tmp_path: Path,
) -> None:
    """Run the same window with and without a dividend the engine reaches.

    The pinned dividend has an ex date the engine never reaches, and
    `bundle.economic_outcomes` is a literal empty tuple, so the original form
    of this test produced byte-identical values whether or not a dividend
    existed. Here the dividend is moved onto an executed session and the two
    runs are compared: the evidence provably differs, and the book provably
    does not.
    """
    assert REACHED_DIVIDEND_ACTIONS != PINNED_CORPORATE_ACTIONS
    assert NO_DIVIDEND_ACTIONS != PINNED_CORPORATE_ACTIONS

    with_dividend = _intake_with_actions(tmp_path / "with", REACHED_DIVIDEND_ACTIONS)
    without_dividend = _intake_with_actions(tmp_path / "without", NO_DIVIDEND_ACTIONS)

    # Sensitive: the dividend really is present in one run and absent in the
    # other, and it really does change the acquired evidence.
    assert len(with_dividend.economic_terms.records) == 1
    assert without_dividend.economic_terms.records == ()
    terms = with_dividend.economic_terms.records[0]
    assert terms.source_key.family == "terms"
    assert terms.payload is not None
    assert with_dividend.retained.corporate_actions_hash != (
        without_dividend.retained.corporate_actions_hash
    )
    assert with_dividend.acquisition.receipt.byte_graph_hash != (
        without_dividend.acquisition.receipt.byte_graph_hash
    )

    # Sensitive: announced terms are carried, and no occurred effect and no
    # delivered settlement is minted from them, in either run.
    assert with_dividend.bundle.economic_outcomes == ()
    assert without_dividend.bundle.economic_outcomes == ()

    dividend_artifacts, _ = _run(with_dividend)
    quiet_artifacts, _ = _run(without_dividend)

    # The ex date now falls on a session the engine executed, so it had the
    # opportunity to act on it and did not.
    executed = [
        item.session_key.local_date
        for item in dividend_artifacts.trace.events
        if item.kind == "session_start"
    ]
    assert datetime(2026, 1, 6).date() in executed

    for artifacts in (dividend_artifacts, quiet_artifacts):
        kinds = [item.kind for item in artifacts.trace.events]
        assert kinds.count("corporate_action_applied") == 0
        assert kinds.count("claim_settled") == 0
        assert artifacts.final_state.holdings == ()
        assert artifacts.final_state.pending_cash_claims == ()
        assert (
            artifacts.final_state.cash_balance
            == _protocol(warmup=WARMUP_SESSIONS).initial_cash
        )
    # Corroborating, and stated as such: with no holdings to pay a dividend
    # on, an identical book is weaker evidence than the empty outcome
    # collection above. It is kept because a settlement minted anywhere in the
    # pipeline would still have to move cash through this state.
    assert (
        dividend_artifacts.final_state.cash_balance
        == quiet_artifacts.final_state.cash_balance
    )


def test_the_bundle_covers_both_declared_cohort_members(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    assert {item.security_id for item in intake.bundle.security_identities} == {
        AAPL_ID,
        MSFT_ID,
    }
    assert {
        item.security_id
        for item in intake.bundle.exploratory_reconstructed_observations
    } == {AAPL_ID, MSFT_ID}


# --- CLI behaviour without credentials ----------------------------------------------


def _load_cli() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "_alpaca_exploratory_cli", CLI_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_a_missing_api_key_skips_acquisition_without_raising(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("acquisition must not run without both keys")

    monkeypatch.setattr(cli.urllib.request, "urlopen", _refuse)

    code = cli.main(["--private-root", str(tmp_path / "private")])

    assert code == 0
    output = capsys.readouterr().out
    assert "skipping Alpaca acquisition" in output
    assert not (tmp_path / "private").exists()


def test_a_half_configured_environment_also_skips_acquisition(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    monkeypatch.setenv(cli.KEY_ID_VARIABLE, "unused-placeholder-id")
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("acquisition must not run with one key missing")

    monkeypatch.setattr(cli.urllib.request, "urlopen", _refuse)

    code = cli.main(["--private-root", str(tmp_path / "private")])

    assert code == 0
    output = capsys.readouterr().out
    assert "skipping Alpaca acquisition" in output
    # The configured key must never be echoed, not even partially.
    assert "unused-placeholder-id" not in output


def test_the_cli_runs_the_whole_bridge_offline_from_retained_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline intake must never open a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(cli.urllib.request, "urlopen", _refuse)

    raw = _write_offline_bytes(tmp_path, cli, with_origin=True)
    declaration = _write_declaration(tmp_path)

    code = cli.main(
        [
            "--private-root",
            str(tmp_path / "private"),
            "--offline-bytes",
            str(raw),
            "--declaration",
            str(declaration),
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "reconciliation pass" in output
    assert f"sessions {len(SESSION_DATES)}" in output
    assert "lane exploratory; this evidence is never promotion-grade" in output
    assert output.count("acknowledged limitation ") == 6


def test_an_offline_replay_without_retained_origin_evidence_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No HTTP exchange happened, so the receipt may not claim one happened."""
    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)

    raw = _write_offline_bytes(tmp_path, cli, with_origin=False)
    declaration = _write_declaration(tmp_path)

    with pytest.raises(Exception) as error:
        cli.main(
            [
                "--private-root",
                str(tmp_path / "private"),
                "--offline-bytes",
                str(raw),
                "--declaration",
                str(declaration),
            ]
        )

    assert "reconciliation did not pass" in str(error.value)
    assert "unverified origin evidence" in str(error.value)
    assert "no retained origin evidence beside those bytes" in capsys.readouterr().out


def _write_offline_bytes(root: Path, cli: ModuleType, *, with_origin: bool) -> Path:
    raw = root / ("raw-with-origin" if with_origin else "raw-bare")
    raw.mkdir()
    (raw / cli.BARS_FILE_NAME).write_bytes(PINNED_BARS)
    (raw / cli.CALENDAR_FILE_NAME).write_bytes(PINNED_CALENDAR)
    (raw / cli.ACTIONS_FILE_NAME).write_bytes(PINNED_CORPORATE_ACTIONS)
    if with_origin:
        import json

        (raw / cli.ORIGIN_FILE_NAME).write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "objects": {
                        key: {
                            "request_host": item.request_host,
                            "tls_endpoint_identity": item.tls_endpoint_identity,
                            "http_status": item.http_status,
                            "content_type": item.content_type,
                            "observed_at": item.observed_at.isoformat(),
                        }
                        for key, item in pinned_origin_observations().items()
                    },
                }
            ),
            encoding="utf-8",
        )
    return raw


def _write_declaration(root: Path) -> Path:
    import json

    request = pinned_request()
    (root / "tz.tzif").write_bytes(pinned_tzif_bytes())
    (root / "producer-source.json").write_bytes(PRODUCER_SOURCE_BYTES)
    (root / "producer-package.json").write_bytes(PRODUCER_PACKAGE_BYTES)
    (root / "lockfile.json").write_bytes(LOCKFILE_BYTES)
    document = {
        "cohort_id": request.cohort_id,
        "cohort_version": request.cohort_version,
        "mic": request.mic,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "plan_frozen_at": request.plan_frozen_at.isoformat(),
        "request_start": request.request_start.isoformat(),
        "request_end": request.request_end.isoformat(),
        "evidence_vintage_cutoff": request.evidence_vintage_cutoff.isoformat(),
        "members": [
            {
                "symbol": member.symbol,
                "security_id": str(member.security_id),
                "listing_id": str(member.listing_id),
                "venue": member.venue.value,
            }
            for member in request.members
        ],
        "timezone": {
            "identifier": request.timezone_evidence.timezone_identifier,
            "label": request.timezone_evidence.source_timezone_label,
            "tzif_path": "tz.tzif",
            "tzdb_release": request.timezone_evidence.tzdb_release,
        },
        "lineage": {
            "producer_source_path": "producer-source.json",
            "producer_package_path": "producer-package.json",
            "lockfile_path": "lockfile.json",
            "python_identity": request.lineage.python_identity,
        },
        "boundary_offsets": [
            {
                "date": key[0].isoformat(),
                "boundary": key[1],
                "utc_offset_seconds": value,
            }
            for key, value in sorted(
                request.boundary_offsets.items(), key=lambda item: str(item[0])
            )
        ],
    }
    path = root / "declaration.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --- the credentials cannot survive a redirect ---------------------------------------

#: Values that look exactly like the two real headers and appear nowhere else.
LEAK_KEY_ID = "PKREDIRECTPROBEKEYID"
LEAK_SECRET_KEY = "redirectprobesecretvalue0000000000000"


class _CapturingServer(http.server.ThreadingHTTPServer):
    """A second origin that records whatever headers reach it."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        self.received: list[dict[str, str]] = []
        super().__init__(address, _CapturingHandler)


class _CapturingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        server = self.server
        assert isinstance(server, _CapturingServer)
        server.received.append({k.lower(): v for k, v in self.headers.items()})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args: object) -> None:
        return


def _redirecting_server(target: str) -> http.server.ThreadingHTTPServer:
    class _RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    server.daemon_threads = True
    return server


def _serve(server: http.server.HTTPServer) -> Iterator[str]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _credentialed_request(url: str) -> urllib.request.Request:
    request = urllib.request.Request(url, method="GET")
    request.add_header("APCA-API-KEY-ID", LEAK_KEY_ID)
    request.add_header("APCA-API-SECRET-KEY", LEAK_SECRET_KEY)
    request.add_header("Accept", "application/json")
    return request


def test_the_unguarded_default_opener_would_hand_the_keys_to_a_second_origin() -> None:
    """The negative control. This is the behaviour the guard below exists for.

    `urllib`'s default redirect handler copies every request header onto the
    redirect target and follows a plaintext `http://` destination on a
    different origin. Without this test the guard could be deleted and nothing
    would show what it was defending against.
    """
    sink = _CapturingServer(("127.0.0.1", 0))
    sink_urls = _serve(sink)
    sink_url = next(sink_urls)
    provider = _redirecting_server(f"{sink_url}/leak")
    provider_urls = _serve(provider)
    provider_url = next(provider_urls)
    try:
        with urllib.request.urlopen(
            _credentialed_request(f"{provider_url}/v2/stocks/bars"), timeout=10
        ) as response:
            response.read()
    finally:
        for generator in (provider_urls, sink_urls):
            next(generator, None)

    assert len(sink.received) == 1
    assert sink.received[0]["apca-api-key-id"] == LEAK_KEY_ID
    assert sink.received[0]["apca-api-secret-key"] == LEAK_SECRET_KEY


def test_a_provider_redirect_cannot_carry_the_api_keys_to_another_origin() -> None:
    """Same two servers, this tool's opener: the second origin sees nothing."""
    cli = _load_cli()
    sink = _CapturingServer(("127.0.0.1", 0))
    sink_urls = _serve(sink)
    sink_url = next(sink_urls)
    provider = _redirecting_server(f"{sink_url}/leak")
    provider_urls = _serve(provider)
    provider_url = next(provider_urls)
    try:
        with pytest.raises(cli.RedirectRefusedError) as error:
            with cli._build_opener().open(
                _credentialed_request(f"{provider_url}/v2/stocks/bars"), timeout=10
            ) as response:
                response.read()
    finally:
        for generator in (provider_urls, sink_urls):
            next(generator, None)

    assert "refuses HTTP 302 redirects" in str(error.value)
    # The whole point: no second request was ever made, so no header was copied.
    assert sink.received == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_redirect_status_is_refused(status: int) -> None:
    """A guard that only covers 302 is not a guard against redirects."""
    cli = _load_cli()
    sink = _CapturingServer(("127.0.0.1", 0))
    sink_urls = _serve(sink)
    sink_url = next(sink_urls)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self.send_response(status)
            self.send_header("Location", f"{sink_url}/leak")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    provider.daemon_threads = True
    provider_urls = _serve(provider)
    provider_url = next(provider_urls)
    try:
        with pytest.raises(OSError):
            with cli._build_opener().open(
                _credentialed_request(f"{provider_url}/v2/stocks/bars"), timeout=10
            ) as response:
                response.read()
    finally:
        for generator in (provider_urls, sink_urls):
            next(generator, None)

    assert sink.received == []


def test_a_response_from_another_origin_is_refused_even_without_a_redirect() -> None:
    """TLS is required on every hop, and the origin has to be the one asked for."""
    cli = _load_cli()

    cli._assert_same_tls_origin(
        "https://data.alpaca.markets/v2/stocks/bars?a=1",
        "https://data.alpaca.markets/v2/stocks/bars?a=1",
    )
    for answered in (
        "http://data.alpaca.markets/v2/stocks/bars",
        "https://evil.example.invalid/v2/stocks/bars",
        "https://data.alpaca.markets.evil.example.invalid/v2/stocks/bars",
    ):
        with pytest.raises(cli.RedirectRefusedError):
            cli._assert_same_tls_origin(
                "https://data.alpaca.markets/v2/stocks/bars", answered
            )


# --- offline and secret hygiene -------------------------------------------------------


def test_the_whole_smoke_path_runs_with_every_socket_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the exploratory smoke run must never open a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)

    result = run_pinned_intake(tmp_path / "private")
    artifacts, strategy = _run(result)

    assert artifacts.result.is_promotion_grade_evidence is False
    assert strategy.seen == []


def test_the_bridge_reads_no_credential_even_when_one_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Set the credentials, then prove none of them reached anything.

    Deleting the variables and then asserting they are unset verifies
    `monkeypatch`, not the bridge. Here the opposite is done: every credential
    variable is set to a value that appears nowhere else in the repository,
    the whole pipeline runs, and the sentinel is then hunted for in every
    artifact the bridge produced and every byte it wrote to disk.
    """
    sentinel = "ZZSENTINELCREDENTIALVALUEZZ"
    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY"):
        monkeypatch.setenv(name, sentinel)
    assert not (REPO_ROOT / ".env").exists()
    assert os.environ["APCA_API_KEY_ID"] == sentinel

    result = run_pinned_intake(tmp_path / "private")

    assert result.admission.lane == "exploratory"
    emitted = b"".join(
        canonical_json(item)
        for item in (
            result.acquisition.receipt,
            result.acquisition.plan,
            result.acquisition.expected_inventory,
            result.acquisition.reconciliation,
            result.observation_contract,
            result.bundle,
            result.admission,
            result.session_clock,
            result.reconstructions,
            result.outcome_queries,
        )
    )
    assert sentinel.encode("utf-8") not in emitted
    written = [path for path in result.retained.root.rglob("*") if path.is_file()]
    assert written
    for path in written:
        assert sentinel.encode("utf-8") not in path.read_bytes()


def test_no_retained_provider_byte_reaches_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the CLI over the real write path and diff the whole working tree.

    Comparing file *names* under `src/drift` against a content hash can never
    fail, and neither can asserting that a `tmp_path` chosen by the test is
    outside the repository. This runs the acquisition CLI end to end and
    asserts that not one path anywhere under the repository changed, then
    asserts every byte it did write is owner-only.
    """
    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)
    raw = _write_offline_bytes(tmp_path, cli, with_origin=True)
    declaration = _write_declaration(tmp_path)
    private = tmp_path / "private"

    before = repository_paths()
    code = cli.main(
        [
            "--private-root",
            str(private),
            "--offline-bytes",
            str(raw),
            "--declaration",
            str(declaration),
        ]
    )
    after = repository_paths()

    assert code == 0
    assert after - before == set(), (
        f"the acquisition CLI created paths inside the repository: "
        f"{sorted(after - before)}"
    )
    assert before - after == set()
    assert_private_bytes_are_locked_down(private)
    # Every retained object really is the pinned provider byte string, so the
    # scan above ran against a real retention and not an empty directory.
    stored = private / "objects" / "sha256"
    assert {path.read_bytes() for path in stored.iterdir()} == {
        PINNED_BARS,
        PINNED_CALENDAR,
        PINNED_CORPORATE_ACTIONS,
    }


def test_the_pinned_window_is_quiet_and_fully_scheduled(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    clock = intake.session_clock

    assert clock.mode == "scheduled_session_reconstruction"
    assert clock.sessions[0].opened_at == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert clock.sessions[-1].closed_at == datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
    assert all(item.authority == "scheduled_reconstruction" for item in clock.sessions)
