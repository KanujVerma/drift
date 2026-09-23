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

What this module proves about decisions. Since issue 46 (the issue 42
adjudication of ADR 0012 Option B), the bridge's scheduled-reconstruction
bundle drives strategy decisions in the EXPLORATORY lane through
``ExploratoryStrategyDecisionContextV1``, scoped by the bridge's own declared
cohort. The decisions-only reference strategy is consulted at every
post-warmup scheduled close and the run completes, every decision recorded
under its own exploratory event kind with the reconstruction limitations
attached.

What this module deliberately does NOT prove. It does not exercise order
execution, corporate-action accounting, or portfolio valuation. The bridge
bundle cannot support them: Alpaca publishes no realized session telemetry,
and ``bind_observation_session`` classifies an observation as bound only
through realized open and close evidence, so the bundle carries no
``DerivedObservationViewV1`` to execute, price, or account on, and the smoke
engine is given no listing-role evidence to resolve an execution listing from.
A strategy that asks to trade therefore halts ``INDETERMINATE`` at the next
open. In this module it halts at execution-listing resolution, the first of
those missing proofs it reaches; the missing-price halt is pinned separately
in ``tests/integration/test_exploratory_reconstructed_experiment_run.py``. The
assertions below say so explicitly, so a green smoke test can never be
mistaken for a trading evaluation.

Every provider byte is a pinned literal and no test here reads `.env`. The
credential-leak tests in the redirect section stand up throwaway local HTTP
servers on `127.0.0.1` to prove, by execution, that a 302 from a provider
cannot carry `APCA-API-KEY-ID` or `APCA-API-SECRET-KEY` to a second origin.
Every other test that fetches does so through the production opener over a
recording transport, with real sockets replaced by a raising stub, so no test
here can reach the network.
"""

import http.client
import http.server
import importlib.util
import io
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from exploratory_decision_test_support import (  # noqa: E402
    ReconstructedTargetStrategy,
)
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
    measured_over,
    pinned_request,
    pinned_tzif_bytes,
    repository_paths,
    run_pinned_intake,
)
from test_evaluator_engine import (  # noqa: E402
    _cost_model,
    _protocol,
    _run_identity,
)

from drift.adapters.alpaca_exploratory import (  # noqa: E402
    AlpacaBridgeIncompleteError,
    AlpacaExploratoryIntakeResult,
    AlpacaIntakeRequest,
)
from drift.domain.acquisition import OriginStatus  # noqa: E402
from drift.domain.evaluator_exploratory_strategy import (  # noqa: E402
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryStrategyDecisionContextV1,
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
#: Every scheduled close the reference strategy is consulted at: the first
#: decision is taken at session ``WARMUP_SESSIONS - 1``.
DECISION_DATES = SESSION_DATES[WARMUP_SESSIONS - 1 :]
#: The next open after the first decision, where a trading target fails closed.
FIRST_EXECUTION_SESSION = WARMUP_SESSIONS
#: A trading target to exercise the fail-closed execution boundary.
BUY_TEN_AAPL = {session_date: ((AAPL_ID, 10),) for session_date in SESSION_DATES}


@pytest.fixture(scope="module")
def intake(tmp_path_factory: pytest.TempPathFactory) -> AlpacaExploratoryIntakeResult:
    """Run the complete offline bridge once for the whole smoke module."""
    return run_pinned_intake(tmp_path_factory.mktemp("alpaca-smoke-private"))


def _engine(intake: AlpacaExploratoryIntakeResult) -> SessionEvaluatorEngine:
    """The real engine over the bridge bundle, scoped by the bridge's cohort.

    The declared cohort is what opens the EXPLORATORY reconstructed decision
    lane for a ``scheduled_session_reconstruction`` bundle (issue 46), so it is
    passed exactly as the bridge minted it.
    """
    return SessionEvaluatorEngine(
        bundle=intake.bundle,
        admission=intake.admission,
        protocol=_protocol(warmup=WARMUP_SESSIONS),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(exploratory_cohort=intake.cohort),
        book_currency_namespace="iso4217",
        book_currency_code="USD",
    )


def _run(
    intake: AlpacaExploratoryIntakeResult,
    targets: Mapping[Any, tuple[tuple[Any, int], ...]] | None = None,
) -> tuple[Any, ReconstructedTargetStrategy]:
    """Run the decisions-only reference strategy unless targets are given."""
    engine = _engine(intake)
    strategy = ReconstructedTargetStrategy({} if targets is None else targets)
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
    # The decisions-only reference run steps and marks every session and
    # decides at every post-warmup close.
    assert kinds.count("session_start") == len(SESSION_DATES)
    assert kinds.count("session_mark") == len(SESSION_DATES)
    assert kinds.count("exploratory_strategy_decision") == len(DECISION_DATES)
    assert kinds[-1] == "exploratory_strategy_decision"
    # Every trace event binds a session the bridge's own clock contains.
    covered = {item.session_key for item in intake.session_clock.sessions}
    assert {item.session_key for item in trace.events} <= covered


def test_the_bridge_bundle_drives_exploratory_decisions_on_reconstructed_evidence(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """The issue 42 gap, closed for the bridge's own bundle.

    The bundle still carries no authentic view of any kind, so every decision
    here is taken on reconstructed evidence, under the weaker context type,
    at each scheduled close, and is traced under its own event kind.
    """
    artifacts, strategy = _run(intake)
    result = artifacts.result

    assert intake.bundle.authentic_decision_views == ()
    assert intake.bundle.authentic_accounting_views == ()
    assert result.classification is EvaluationClassification.COMPLETE
    assert result.is_promotion_grade_evidence is False

    closes = {
        session.session_key.local_date: session.closed_at
        for session in intake.session_clock.sessions
    }
    assert [context.session_key.local_date for context in strategy.seen] == list(
        DECISION_DATES
    )
    for context in strategy.seen:
        assert isinstance(context, ExploratoryStrategyDecisionContextV1)
        assert context.lane == "exploratory"
        assert context.evidence_grade == "exploratory_reconstructed"
        assert context.is_promotion_grade_evidence is False
        assert context.decision_session.authority == "scheduled_reconstruction"
        assert context.decision_cutoff == closes[context.session_key.local_date]
        assert context.cohort_hash == intake.cohort.cohort_hash

    kinds = {item.kind for item in artifacts.trace.events}
    assert "strategy_decision" not in kinds
    decisions = [
        item
        for item in artifacts.trace.events
        if item.kind == "exploratory_strategy_decision"
    ]
    reconstructions = {item.reconstruction_hash for item in intake.reconstructions}
    assert len(decisions) == len(DECISION_DATES)
    for event in decisions:
        assert event.outcome == "staged"
        assert event.reconstruction_hashes
        assert set(event.reconstruction_hashes) <= reconstructions
        assert set(RECONSTRUCTED_DECISION_LIMITATIONS) <= set(
            event.acknowledged_limitations
        )


def test_a_trading_target_fails_closed_at_the_next_open(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """Deciding on reconstructed evidence is admitted; executing on it is not.

    The first decision stages a buy, and the next open halts INDETERMINATE in
    the execution phase instead of inventing an execution listing or price
    the scheduled bundle cannot prove. The cause is pinned so that a
    different fail-closed path cannot stand in for this one. No fill is
    minted.
    """
    artifacts, strategy = _run(intake, BUY_TEN_AAPL)
    result = artifacts.result

    assert result.classification is EvaluationClassification.INDETERMINATE
    assert result.halted_session_index == FIRST_EXECUTION_SESSION
    assert [context.session_key.local_date for context in strategy.seen] == [
        DECISION_DATES[0]
    ]
    kinds = [item.kind for item in artifacts.trace.events]
    assert "fill" not in kinds
    assert kinds.count("exploratory_strategy_decision") == 1
    cause = artifacts.trace.events[-1]
    assert cause.kind == "indeterminate_cause"
    assert cause.phase is EvaluationPhase.OPEN_EXECUTION
    assert cause.cause_kind == "indeterminate_execution"
    assert cause.cause.startswith(
        f"no active primary listing for security {AAPL_ID} at "
    ), cause.cause
    assert artifacts.final_state.holdings == ()


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

    Stated plainly so the quantifier is honest: this smoke run prices zero
    positions, because the decisions-only reference strategy never holds one,
    so "every valuation is exploratory" would range over an empty set and could
    not fail.
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
#: The pinned dividend moved onto 2026-01-06, an early session every run below
#: executes whatever strategy it is given. It was moved when the engine still
#: halted at the first decision cutoff, and the placement is kept so the
#: assertion about what the engine did with the dividend stays unconditional.
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

    payloads = AlpacaNativePayloads(
        bars=PINNED_BARS,
        calendar=PINNED_CALENDAR,
        corporate_actions=actions,
    )
    return run_alpaca_exploratory_intake(
        request=measured_over(pinned_request(), payloads),
        payloads=payloads,
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
    """Replay a real online acquisition offline, with no socket available.

    The origin evidence the replay certifies is the record the online run
    wrote beside the bytes it measured, so the acquisition is performed first,
    through the production fetch path over the recording transport.
    """
    cli = _load_cli()
    private = tmp_path / "private"
    wire, declaration = _acquire_online(cli, tmp_path, private, capsys, monkeypatch)
    requests_before_replay = len(wire.requests)

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline intake must never open a socket")

    monkeypatch.setattr(cli.urllib.request, "urlopen", _refuse)
    raw = _write_offline_bytes(tmp_path, cli)

    code = cli.main(_offline_arguments(private, raw, declaration))

    assert code == 0
    output = capsys.readouterr().out
    assert "reconciliation pass" in output
    assert f"sessions {len(SESSION_DATES)}" in output
    assert "lane exploratory; this evidence is never promotion-grade" in output
    assert output.count("acknowledged limitation ") == 6
    # The replay itself performed no HTTP exchange of any kind.
    assert len(wire.requests) == requests_before_replay


def test_an_offline_replay_without_retained_origin_evidence_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No HTTP exchange happened, so the receipt may not claim one happened."""
    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)

    raw = _write_offline_bytes(tmp_path, cli)
    declaration = _write_declaration(tmp_path)

    with pytest.raises(
        AlpacaBridgeIncompleteError, match="reconciliation did not pass"
    ) as error:
        cli.main(_offline_arguments(tmp_path / "private", raw, declaration))

    assert "unverified origin evidence" in str(error.value)
    output = capsys.readouterr().out
    assert "no retained origin record binds" in output
    for key in (cli.BARS_OBJECT_KEY, cli.CALENDAR_OBJECT_KEY, cli.ACTIONS_OBJECT_KEY):
        assert key in output


#: The pinned bars with exactly one byte changed: one closing price digit.
ONE_BYTE_CHANGED_BARS = PINNED_BARS.replace(b'"c":191.25', b'"c":191.26', 1)


def _write_offline_bytes(
    root: Path, cli: ModuleType, *, bars: bytes = PINNED_BARS, name: str = "raw"
) -> Path:
    raw = root / name
    raw.mkdir()
    (raw / cli.BARS_FILE_NAME).write_bytes(bars)
    (raw / cli.CALENDAR_FILE_NAME).write_bytes(PINNED_CALENDAR)
    (raw / cli.ACTIONS_FILE_NAME).write_bytes(PINNED_CORPORATE_ACTIONS)
    return raw


def _write_hand_typed_origin(raw: Path, cli: ModuleType) -> None:
    """Type the most convincing origin sidecar possible beside retained bytes.

    Every value is plausible and the body digests are even correct for the
    bytes lying beside it. Nothing in Drift writes this file, so nothing
    measured it, and the bridge must not read it at all.
    """
    bodies = {
        cli.BARS_OBJECT_KEY: (raw / cli.BARS_FILE_NAME).read_bytes(),
        cli.CALENDAR_OBJECT_KEY: (raw / cli.CALENDAR_FILE_NAME).read_bytes(),
        cli.ACTIONS_OBJECT_KEY: (raw / cli.ACTIONS_FILE_NAME).read_bytes(),
    }
    hosts = {
        cli.BARS_OBJECT_KEY: "data.alpaca.markets",
        cli.CALENDAR_OBJECT_KEY: "paper-api.alpaca.markets",
        cli.ACTIONS_OBJECT_KEY: "data.alpaca.markets",
    }
    (raw / "origin.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "objects": {
                    key: {
                        "request_host": hosts[key],
                        "tls_endpoint_identity": hosts[key],
                        "http_status": 200,
                        "content_type": "application/json",
                        "observed_at": datetime.now(UTC).isoformat(),
                        "body_sha256": sha256(body).hexdigest(),
                        "body_byte_size": len(body),
                    }
                    for key, body in bodies.items()
                },
            }
        ),
        encoding="utf-8",
    )


def _offline_arguments(private: Path, raw: Path, declaration: Path) -> list[str]:
    return [
        "--private-root",
        str(private),
        "--offline-bytes",
        str(raw),
        "--declaration",
        str(declaration),
    ]


def _online_arguments(private: Path, declaration: Path) -> list[str]:
    return ["--private-root", str(private), "--declaration", str(declaration)]


def _write_declaration(root: Path, *, around: datetime | None = None) -> Path:
    """Write the pinned intake declaration, optionally around a real instant.

    An online acquisition measures the wall clock, and the bridge refuses a
    declared acquisition window that does not contain its own measurements, so
    online runs declare a window around the moment they actually run.
    """
    overrides: dict[str, Any] = {}
    if around is not None:
        # Declared instants are ISO seconds, as exact availability requires.
        around = around.replace(microsecond=0)
        overrides = {
            "origin_observations": None,
            "plan_frozen_at": around - timedelta(hours=2),
            "request_start": around - timedelta(hours=1),
            "request_end": around + timedelta(hours=1),
            "evidence_vintage_cutoff": around + timedelta(hours=2),
        }
    request = pinned_request(**overrides)
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


# --- a recording transport under the production opener -----------------------------
#
# Everything from `_fetch_bytes` down to `http.client` is production code and
# runs unmodified. `_build_opener()` is called for real, so `_RefuseRedirects`
# and the stock `HTTPErrorProcessor`, `HTTPDefaultErrorHandler`, and
# `HTTPRedirectHandler` logic all run; `urllib` assembles the request headers;
# `http.client` validates and serializes them onto the wire and parses the
# status line, headers, and body back. The one thing replaced is the socket
# underneath: `_recording_transport` is added to the opener the production code
# built, answers every `https://` and `http://` request from a fixed route
# table, and records the exact bytes every origin was sent. Real sockets are
# disabled for the duration, so a fetch that bypasses the production opener
# fails loudly instead of reaching the network.

#: Printable, whitespace-free stand-ins for the two real keys. Neither appears
#: anywhere else, so finding one anywhere but the origin it was sent to is a leak.
PROBE_KEY_ID = "PKFETCHPATHPROBEKEYID0001"
PROBE_SECRET_KEY = "fetchpathprobesecretvalue0000000000000001"
DATA_HOST = "data.alpaca.markets"
PAPER_HOST = "paper-api.alpaca.markets"
LIVE_BROKERAGE_HOST = "api.alpaca.markets"
DATA_ORIGIN = f"https://{DATA_HOST}"
PAPER_ORIGIN = f"https://{PAPER_HOST}"
EVIL_ORIGIN = "http://evil.example.invalid"


@dataclass(frozen=True)
class Canned:
    """One response the recording transport serves for one route."""

    status: int = 200
    reason: str = "OK"
    body: bytes = b"{}"
    content_type: str | None = "application/json"
    headers: tuple[tuple[str, str], ...] = ()
    #: What `geturl()` reports, when it has to differ from the request URL.
    answered_url: str | None = None
    #: Verbatim response bytes, for a response `http.client` must fail to parse.
    raw: bytes | None = None
    #: Raised instead of answering, to model a lower-layer fault.
    fault: Exception | None = None


class _TrackedStream(io.BytesIO):
    """A response stream that remembers how far anyone read into it."""

    def __init__(self, data: bytes, body_offset: int) -> None:
        super().__init__(data)
        self.body_offset = body_offset
        self._position_at_close: int | None = None

    def close(self) -> None:
        if not self.closed:
            self._position_at_close = self.tell()
        super().close()

    @property
    def body_was_read(self) -> bool:
        consumed = self._position_at_close if self.closed else self.tell()
        return consumed is not None and consumed > self.body_offset


@dataclass
class WireRequest:
    """Everything one connection carried towards one origin."""

    scheme: str
    host: str
    port: int
    sent: bytearray = field(default_factory=bytearray)

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"

    @property
    def path(self) -> str:
        line = bytes(self.sent).split(b"\r\n", 1)[0].decode("latin-1")
        return urllib.parse.urlsplit(line.split(" ")[1]).path

    @property
    def header_values(self) -> dict[str, str]:
        head = bytes(self.sent).split(b"\r\n\r\n", 1)[0].decode("latin-1")
        values: dict[str, str] = {}
        for line in head.split("\r\n")[1:]:
            name, _, value = line.partition(":")
            values[name.strip().lower()] = value.strip()
        return values


class _WireSocket:
    """The socket `http.client` writes a request into and reads an answer from."""

    def __init__(self, wire: RecordingWire, request: WireRequest) -> None:
        self._wire = wire
        self._request = request

    def sendall(self, data: bytes) -> None:
        self._request.sent.extend(data)
        # A fault fires while the request is being sent, before http.client has
        # built a response object, exactly where a lower layer would raise.
        fault = self._wire.route(self._request).fault
        if fault is not None:
            raise fault

    def makefile(self, mode: str, *args: object, **kwargs: object) -> _TrackedStream:
        return self._wire.answer(self._request)

    def close(self) -> None:
        return None


class RecordingWire:
    """Serve a fixed route table and record every request that reaches it."""

    def __init__(self, routes: Mapping[tuple[str, str, str], Canned]) -> None:
        self.routes = dict(routes)
        self.requests: list[WireRequest] = []
        self.streams: list[_TrackedStream] = []
        self.served: list[Canned] = []

    def connect(self, scheme: str, host: str, port: int) -> _WireSocket:
        request = WireRequest(scheme=scheme, host=host, port=port)
        self.requests.append(request)
        if not any(route[:2] == (scheme, host) for route in self.routes):
            raise ConnectionRefusedError(f"nothing listens at {scheme}://{host}")
        return _WireSocket(self, request)

    def route(self, request: WireRequest) -> Canned:
        return self.routes.get(
            (request.scheme, request.host, request.path),
            Canned(status=404, reason="Not Found", body=b'{"message":"not found"}'),
        )

    def answer(self, request: WireRequest) -> _TrackedStream:
        canned = self.route(request)
        self.served.append(canned)
        if canned.raw is not None:
            stream = _TrackedStream(canned.raw, len(canned.raw))
        else:
            lines = [f"HTTP/1.1 {canned.status} {canned.reason}"]
            if canned.content_type is not None:
                lines.append(f"Content-Type: {canned.content_type}")
            lines.extend(f"{name}: {value}" for name, value in canned.headers)
            lines.append(f"Content-Length: {len(canned.body)}")
            lines.append("Connection: close")
            head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
            stream = _TrackedStream(head + canned.body, len(head))
        self.streams.append(stream)
        return stream

    @property
    def origins(self) -> list[str]:
        return [item.origin for item in self.requests]

    def everything_sent(self) -> bytes:
        return b"".join(bytes(item.sent) for item in self.requests)


def _recording_transport(wire: RecordingWire) -> urllib.request.HTTPSHandler:
    """Build a stock HTTPS handler whose connections write into `wire`."""

    class _Plain(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = cast(Any, wire.connect("http", self.host, self.port))

    class _Tls(http.client.HTTPSConnection):
        def connect(self) -> None:
            self.sock = cast(Any, wire.connect("https", self.host, self.port))

    class _RecordingTransport(urllib.request.HTTPSHandler):
        #: Consulted before every stock handler for the same scheme.
        handler_order = 50

        def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
            return self._answered(self.do_open(_Tls, req))

        def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
            return self._answered(self.do_open(_Plain, req))

        @staticmethod
        def _answered(response: http.client.HTTPResponse) -> http.client.HTTPResponse:
            canned = wire.served[-1]
            if canned.answered_url is not None:
                cast(Any, response).url = canned.answered_url
            return response

    return _RecordingTransport()


def _disable_real_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a real socket was requested; every fetch must go through the "
            "opener the production code built"
        )

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, _refuse)


def pinned_routes(
    *,
    bars: Canned | None = None,
    calendar: Canned | None = None,
    extra: Mapping[tuple[str, str, str], Canned] | None = None,
) -> dict[tuple[str, str, str], Canned]:
    """Route the three declared endpoints to the pinned bytes, plus a sink."""
    routes = {
        ("https", DATA_HOST, "/v2/stocks/bars"): bars
        or Canned(body=PINNED_BARS, content_type="application/json; charset=utf-8"),
        ("https", PAPER_HOST, "/v2/calendar"): calendar
        or Canned(body=PINNED_CALENDAR, content_type="application/json"),
        ("https", DATA_HOST, "/v1/corporate-actions"): Canned(
            body=PINNED_CORPORATE_ACTIONS,
            content_type="application/json; charset=utf-8",
        ),
        ("http", "evil.example.invalid", "/leak"): Canned(body=b'{"harvested":1}'),
    }
    routes.update(extra or {})
    return routes


def install_recording_transport(
    monkeypatch: pytest.MonkeyPatch,
    cli: ModuleType,
    routes: Mapping[tuple[str, str, str], Canned] | None = None,
) -> RecordingWire:
    """Put the recording wire under the opener the production code builds."""
    wire = RecordingWire(pinned_routes() if routes is None else routes)
    production = cli._build_opener

    def _production_opener_over_the_recording_wire() -> urllib.request.OpenerDirector:
        opener = cast(urllib.request.OpenerDirector, production())
        opener.add_handler(_recording_transport(wire))
        return opener

    monkeypatch.setattr(
        cli, "_build_opener", _production_opener_over_the_recording_wire
    )
    _disable_real_sockets(monkeypatch)
    return wire


def _set_probe_keys(monkeypatch: pytest.MonkeyPatch, cli: ModuleType) -> None:
    monkeypatch.setenv(cli.KEY_ID_VARIABLE, PROBE_KEY_ID)
    monkeypatch.setenv(cli.SECRET_KEY_VARIABLE, PROBE_SECRET_KEY)


def _fetch_bars(cli: ModuleType) -> tuple[bytes, Any]:
    """Call the production `_fetch_bytes` exactly as `_acquire_payloads` does."""
    return cast(
        tuple[bytes, Any],
        cli._fetch_bytes(
            cli.BARS_OBJECT_KEY,
            DATA_HOST,
            "/v2/stocks/bars",
            {"symbols": "AAPL,MSFT", "timeframe": "1Day"},
            (PROBE_KEY_ID, PROBE_SECRET_KEY),
        ),
    )


def _files_under(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


def _assert_no_key_escaped(
    captured: tuple[str, str], *roots: Path, fragments: tuple[str, ...] = ()
) -> None:
    """Hunt both probe keys, and any extra fragments, everywhere output can go."""
    out, err = captured
    for fragment in (PROBE_KEY_ID, PROBE_SECRET_KEY, *fragments):
        assert fragment not in out
        assert fragment not in err
        for root in roots:
            for path in _files_under(root):
                assert fragment.encode("utf-8") not in path.read_bytes(), path


def _acquire_online(
    cli: ModuleType,
    tmp_path: Path,
    private: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RecordingWire, Path]:
    """Run one real online acquisition through the recording transport."""
    wire = install_recording_transport(monkeypatch, cli)
    _set_probe_keys(monkeypatch, cli)
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    assert cli.main(_online_arguments(private, declaration)) == 0
    assert "reconciliation pass" in capsys.readouterr().out
    # The replay that follows needs no keys, so none are left set.
    monkeypatch.delenv(cli.KEY_ID_VARIABLE)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE)
    return wire, declaration


def _spy_on_intake(
    monkeypatch: pytest.MonkeyPatch, cli: ModuleType
) -> list[tuple[AlpacaIntakeRequest, AlpacaExploratoryIntakeResult]]:
    """Record what the CLI handed the real bridge, and what it got back."""
    seen: list[tuple[AlpacaIntakeRequest, AlpacaExploratoryIntakeResult]] = []
    real = cli.run_alpaca_exploratory_intake

    def _spy(**kwargs: Any) -> AlpacaExploratoryIntakeResult:
        result = cast(AlpacaExploratoryIntakeResult, real(**kwargs))
        seen.append((kwargs["request"], result))
        return result

    monkeypatch.setattr(cli, "run_alpaca_exploratory_intake", _spy)
    return seen


# --- the production fetch path, end to end ------------------------------------------


def test_a_302_to_another_origin_is_refused_and_that_origin_receives_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(
        monkeypatch,
        cli,
        pinned_routes(
            bars=Canned(
                status=302,
                reason="Found",
                body=b"",
                headers=(("Location", f"{EVIL_ORIGIN}/leak"),),
            )
        ),
    )

    with pytest.raises(cli.RedirectRefusedError, match="refuses HTTP 302 redirects"):
        _fetch_bars(cli)

    # Exactly one request left, to the origin it was addressed to.
    assert wire.origins == [DATA_ORIGIN]
    headers = wire.requests[0].header_values
    assert headers["apca-api-key-id"] == PROBE_KEY_ID
    assert headers["apca-api-secret-key"] == PROBE_SECRET_KEY
    # The second origin was never contacted, so no key can have reached it.
    assert all(item.origin == DATA_ORIGIN for item in wire.requests)


def test_a_redirect_during_acquisition_fails_without_printing_a_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(
        monkeypatch,
        cli,
        pinned_routes(
            bars=Canned(
                status=307,
                reason="Temporary Redirect",
                body=b"",
                headers=(("Location", f"{EVIL_ORIGIN}/leak"),),
            )
        ),
    )
    _set_probe_keys(monkeypatch, cli)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    code = cli.main(_online_arguments(private, declaration))

    captured = capsys.readouterr()
    assert code == 1
    assert "Alpaca acquisition failed: RedirectRefusedError" in captured.out
    assert EVIL_ORIGIN not in wire.origins
    assert not private.exists()
    _assert_no_key_escaped(captured, private)


def test_a_200_answered_from_another_origin_is_refused_before_its_body_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(
        monkeypatch,
        cli,
        pinned_routes(
            bars=Canned(
                body=PINNED_BARS,
                answered_url="https://evil.example.invalid/v2/stocks/bars",
            )
        ),
    )

    with pytest.raises(
        cli.RedirectRefusedError,
        match="answered from a different origin than the one it was sent to",
    ):
        _fetch_bars(cli)

    assert len(wire.streams) == 1
    assert wire.streams[0].body_was_read is False


def test_a_plaintext_answer_is_refused_before_its_body_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(
        monkeypatch,
        cli,
        pinned_routes(
            bars=Canned(
                body=PINNED_BARS,
                answered_url="http://data.alpaca.markets/v2/stocks/bars",
            )
        ),
    )

    with pytest.raises(
        cli.RedirectRefusedError, match="requires TLS on every hop, got http"
    ):
        _fetch_bars(cli)

    assert len(wire.streams) == 1
    assert wire.streams[0].body_was_read is False


@pytest.mark.parametrize(
    ("status", "reason"), [(429, "Too Many Requests"), (500, "Internal Server Error")]
)
def test_a_provider_error_status_fails_with_its_measured_status_and_no_key(
    status: int,
    reason: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    routes = pinned_routes(
        bars=Canned(status=status, reason=reason, body=b'{"message":"no"}')
    )
    install_recording_transport(monkeypatch, cli, routes)

    with pytest.raises(urllib.error.HTTPError, match=f"HTTP Error {status}") as error:
        _fetch_bars(cli)
    assert error.value.code == status

    _set_probe_keys(monkeypatch, cli)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))
    code = cli.main(_online_arguments(private, declaration))

    captured = capsys.readouterr()
    assert code == 1
    assert f"Alpaca acquisition failed: HTTPError (HTTP {status})" in captured.out
    assert not private.exists()
    _assert_no_key_escaped(captured, private)


def test_a_clean_200_is_measured_from_the_response_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(monkeypatch, cli)

    before = datetime.now(UTC)
    body, observation = _fetch_bars(cli)
    after = datetime.now(UTC)

    assert body == PINNED_BARS
    # The positive control for the tracker the refusal tests rely on.
    assert wire.streams[0].body_was_read is True
    assert observation.object_key == cli.BARS_OBJECT_KEY
    assert observation.http_status == 200
    # Served verbatim by the transport, and not the constant a guess would use.
    assert observation.content_type == "application/json; charset=utf-8"
    assert observation.request_host == DATA_HOST
    assert observation.tls_endpoint_identity == DATA_HOST
    assert before <= observation.observed_at <= after
    assert wire.origins == [DATA_ORIGIN]
    sent = wire.requests[0]
    assert sent.path == "/v2/stocks/bars"
    assert sent.header_values["apca-api-key-id"] == PROBE_KEY_ID
    assert sent.header_values["apca-api-secret-key"] == PROBE_SECRET_KEY
    assert sent.header_values["accept"] == "application/json"


def test_a_2xx_other_than_200_is_recorded_as_measured_not_as_200(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy's 203 or a partial 206 is a 2xx, so urllib does not raise on it."""
    cli = _load_cli()
    partial = Canned(status=206, reason="Partial Content", body=PINNED_BARS[:40])
    wire = install_recording_transport(monkeypatch, cli, pinned_routes(bars=partial))

    body, observation = _fetch_bars(cli)
    assert observation.http_status == 206
    assert body == PINNED_BARS[:40]

    _set_probe_keys(monkeypatch, cli)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))
    with pytest.raises(
        AlpacaBridgeIncompleteError,
        match="alpaca-historical-bars returned HTTP 206, which is not a complete",
    ):
        cli.main(_online_arguments(private, declaration))
    assert set(wire.origins) == {DATA_ORIGIN, PAPER_ORIGIN}
    assert not private.exists()


# --- an unusable key never reaches a header, and never reaches output ---------------

#: A key value that appears nowhere else, in each shape `http.client` either
#: rejects with the value in its message or sends onto the wire unchanged.
_UNUSABLE_CORE = "ZZUNUSABLEKEYSENTINEL0001"
UNUSABLE_KEY_SHAPES = {
    "trailing-cr": _UNUSABLE_CORE + "\r",
    "trailing-lf": _UNUSABLE_CORE + "\n",
    "leading-space": " " + _UNUSABLE_CORE,
    "embedded-nul": _UNUSABLE_CORE[:12] + "\x00" + _UNUSABLE_CORE[12:],
}


@pytest.mark.parametrize("variable", ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"])
@pytest.mark.parametrize("shape", sorted(UNUSABLE_KEY_SHAPES))
def test_an_unusable_key_is_refused_by_name_before_any_request(
    variable: str,
    shape: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire = install_recording_transport(monkeypatch, cli)
    _set_probe_keys(monkeypatch, cli)
    value = UNUSABLE_KEY_SHAPES[shape]
    if "\x00" in value:
        # A real process environment cannot carry a NUL, because putenv
        # refuses one, so the mapping the CLI reads is replaced instead.
        monkeypatch.setattr(os, "environ", {**os.environ, variable: value})
    else:
        monkeypatch.setenv(variable, value)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    code = cli.main(_online_arguments(private, declaration))

    captured = capsys.readouterr()
    assert code == 2
    assert f"{variable} is set but is not a usable Alpaca API key" in captured.out
    # Refused before any request was built, so nothing reached any wire.
    assert wire.requests == []
    assert not private.exists()
    _assert_no_key_escaped(
        captured,
        private,
        fragments=(_UNUSABLE_CORE, _UNUSABLE_CORE[:12], _UNUSABLE_CORE[12:]),
    )


def test_a_transport_value_error_is_reported_by_type_name_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lower layer that echoes a header value into a ValueError must not leak it."""
    cli = _load_cli()
    fault = ValueError(f"simulated transport fault echoing {PROBE_SECRET_KEY}")
    install_recording_transport(
        monkeypatch, cli, pinned_routes(bars=Canned(fault=fault))
    )
    _set_probe_keys(monkeypatch, cli)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    code = cli.main(_online_arguments(private, declaration))

    captured = capsys.readouterr()
    assert code == 1
    assert "Alpaca acquisition failed: ValueError" in captured.out
    _assert_no_key_escaped(captured, private)


def test_an_unparseable_response_is_reported_by_type_name_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`http.client.HTTPException` carries the raw status line in its message."""
    cli = _load_cli()
    echoed = f"ECHO {PROBE_KEY_ID} {PROBE_SECRET_KEY}\r\n".encode("ascii")
    install_recording_transport(
        monkeypatch, cli, pinned_routes(bars=Canned(raw=echoed))
    )
    _set_probe_keys(monkeypatch, cli)
    private = tmp_path / "private"
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    code = cli.main(_online_arguments(private, declaration))

    captured = capsys.readouterr()
    assert code == 1
    assert "Alpaca acquisition failed: BadStatusLine" in captured.out
    _assert_no_key_escaped(captured, private)


# --- the calendar comes off the paper trading host, never the live one ---------------


def test_acquisition_contacts_only_the_market_data_and_paper_trading_hosts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    wire, _declaration = _acquire_online(
        cli, tmp_path, tmp_path / "private", capsys, monkeypatch
    )

    assert set(wire.origins) == {DATA_ORIGIN, PAPER_ORIGIN}
    calendar = [item for item in wire.requests if item.path == "/v2/calendar"]
    assert [item.origin for item in calendar] == [PAPER_ORIGIN]
    assert all(item.host != LIVE_BROKERAGE_HOST for item in wire.requests)


def test_the_live_brokerage_host_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    # Even a live host that would answer is never asked.
    live = ("https", LIVE_BROKERAGE_HOST, "/v2/calendar")
    wire = install_recording_transport(
        monkeypatch, cli, pinned_routes(extra={live: Canned(body=PINNED_CALENDAR)})
    )

    with pytest.raises(ValueError, match=r"refuses to contact api\.alpaca\.markets"):
        cli._fetch_bytes(
            cli.CALENDAR_OBJECT_KEY,
            LIVE_BROKERAGE_HOST,
            "/v2/calendar",
            {"start": "2026-01-05", "end": "2026-01-09"},
            (PROBE_KEY_ID, PROBE_SECRET_KEY),
        )

    assert wire.requests == []
    assert frozenset({DATA_HOST, PAPER_HOST}) == cli.PERMITTED_HOSTS


# --- a replayed origin is only ever the record an online run measured ---------------


def test_an_online_acquisition_replayed_offline_reproduces_its_measured_origin(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    seen = _spy_on_intake(monkeypatch, cli)
    private = tmp_path / "private"
    wire, declaration = _acquire_online(cli, tmp_path, private, capsys, monkeypatch)
    requests_before_replay = len(wire.requests)
    raw = _write_offline_bytes(tmp_path, cli)

    assert cli.main(_offline_arguments(private, raw, declaration)) == 0
    assert "reconciliation pass" in capsys.readouterr().out
    assert len(wire.requests) == requests_before_replay

    (online_request, online), (offline_request, offline) = seen
    # The replay certifies exactly what the online run measured, instant for
    # instant, and nothing a constant or a sidecar supplied.
    assert online_request.origin_observations is not None
    assert offline_request.origin_observations == online_request.origin_observations

    def _origins(result: AlpacaExploratoryIntakeResult) -> dict[str, Any]:
        return {
            str(item.matched_expected_key): item.origin_evidence
            for item in result.acquisition.receipt.observed_objects
        }

    assert _origins(offline) == _origins(online)
    replayed = _origins(offline)
    assert {key: item.origin_status for key, item in replayed.items()} == {
        cli.BARS_OBJECT_KEY: OriginStatus.VERIFIED,
        cli.CALENDAR_OBJECT_KEY: OriginStatus.VERIFIED,
        cli.ACTIONS_OBJECT_KEY: OriginStatus.VERIFIED,
    }
    assert replayed[cli.BARS_OBJECT_KEY].safe_response_metadata["content_type"] == (
        "application/json; charset=utf-8"
    )
    assert replayed[cli.CALENDAR_OBJECT_KEY].tls_endpoint_identity == PAPER_HOST
    assert replayed[cli.BARS_OBJECT_KEY].tls_endpoint_identity == DATA_HOST


def test_a_hand_typed_origin_sidecar_is_never_read(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's reproduction: one byte changed, a sidecar typed by hand."""
    cli = _load_cli()
    monkeypatch.delenv(cli.KEY_ID_VARIABLE, raising=False)
    monkeypatch.delenv(cli.SECRET_KEY_VARIABLE, raising=False)
    raw = _write_offline_bytes(tmp_path, cli, bars=ONE_BYTE_CHANGED_BARS)
    _write_hand_typed_origin(raw, cli)
    declaration = _write_declaration(tmp_path, around=datetime.now(UTC))

    with pytest.raises(AlpacaBridgeIncompleteError, match="unverified origin evidence"):
        cli.main(_offline_arguments(tmp_path / "private", raw, declaration))

    assert "no retained origin record binds" in capsys.readouterr().out


def _record_paths(private: Path) -> dict[str, Path]:
    """Every retained origin record, by the object key it measured."""
    directory = private / "origins" / "sha256"
    return {
        str(json.loads(path.read_bytes())["object_key"]): path
        for path in sorted(directory.iterdir())
    }


def _replace_every_record_with_garbage(
    cli: ModuleType, private: Path, raw: Path
) -> Path:
    for index, path in enumerate(_record_paths(private).values()):
        path.unlink()
        # Still content addressed, so only the parse can refuse it.
        garbage = f"not an origin record {index}".encode("ascii")
        (path.parent / sha256(garbage).hexdigest()).write_bytes(garbage)
    return raw


def _edit_every_record_in_place(cli: ModuleType, private: Path, raw: Path) -> Path:
    for path in _record_paths(private).values():
        original = path.read_bytes()
        edited = original.replace(b'"http_status":200', b'"http_status":201')
        assert edited != original
        path.write_bytes(edited)
    return raw


def _drop_the_corporate_actions_record(
    cli: ModuleType, private: Path, raw: Path
) -> Path:
    _record_paths(private)[cli.ACTIONS_OBJECT_KEY].unlink()
    return raw


def _replay_other_bytes_beside_a_hand_typed_sidecar(
    cli: ModuleType, private: Path, raw: Path
) -> Path:
    other = _write_offline_bytes(
        raw.parent, cli, bars=ONE_BYTE_CHANGED_BARS, name="raw-other"
    )
    _write_hand_typed_origin(other, cli)
    return other


_ALL_OBJECT_KEYS = (
    "alpaca-historical-bars",
    "alpaca-market-calendar",
    "alpaca-corporate-actions",
)

#: Every way a replay can be handed origin evidence nobody measured over the
#: bytes being replayed, and the object keys that must then stay unverified.
UNBOUND_REPLAYS: dict[
    str, tuple[Callable[[ModuleType, Path, Path], Path], tuple[str, ...]]
] = {
    "a-record-that-does-not-parse": (
        _replace_every_record_with_garbage,
        _ALL_OBJECT_KEYS,
    ),
    "a-record-edited-in-place": (_edit_every_record_in_place, _ALL_OBJECT_KEYS),
    "an-object-with-no-record-entry": (
        _drop_the_corporate_actions_record,
        ("alpaca-corporate-actions",),
    ),
    "a-record-for-different-bytes": (
        _replay_other_bytes_beside_a_hand_typed_sidecar,
        ("alpaca-historical-bars",),
    ),
}


@pytest.mark.parametrize("case", sorted(UNBOUND_REPLAYS))
def test_a_replay_without_a_bound_measured_record_stays_unverified(
    case: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    private = tmp_path / "private"
    _wire, declaration = _acquire_online(cli, tmp_path, private, capsys, monkeypatch)
    tamper, unbound = UNBOUND_REPLAYS[case]
    raw = tamper(cli, private, _write_offline_bytes(tmp_path, cli))

    with pytest.raises(AlpacaBridgeIncompleteError, match="unverified origin evidence"):
        cli.main(_offline_arguments(private, raw, declaration))

    output = capsys.readouterr().out
    line = next(item for item in output.splitlines() if "no retained origin" in item)
    for key in (cli.BARS_OBJECT_KEY, cli.CALENDAR_OBJECT_KEY, cli.ACTIONS_OBJECT_KEY):
        assert (key in line) is (key in unbound), (key, line)


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
    # The whole decision path ran offline too, not only the intake.
    assert [context.session_key.local_date for context in strategy.seen] == list(
        DECISION_DATES
    )


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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the CLI over the real write path and diff the whole working tree.

    Comparing file *names* under `src/drift` against a content hash can never
    fail, and neither can asserting that a `tmp_path` chosen by the test is
    outside the repository. This runs the acquisition CLI end to end and
    asserts that not one path anywhere under the repository changed, then
    asserts every byte it did write is owner-only.
    """
    cli = _load_cli()
    raw = _write_offline_bytes(tmp_path, cli)
    private = tmp_path / "private"

    before = repository_paths()
    _wire, declaration = _acquire_online(cli, tmp_path, private, capsys, monkeypatch)
    code = cli.main(_offline_arguments(private, raw, declaration))
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
    # And the measured origin of each one sits beside it, just as private.
    assert set(_record_paths(private)) == set(_ALL_OBJECT_KEYS)


def test_the_pinned_window_is_quiet_and_fully_scheduled(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    clock = intake.session_clock

    assert clock.mode == "scheduled_session_reconstruction"
    assert clock.sessions[0].opened_at == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert clock.sessions[-1].closed_at == datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
    assert all(item.authority == "scheduled_reconstruction" for item in clock.sessions)
