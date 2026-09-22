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

Every byte is a pinned literal. No test here opens a socket or reads `.env`.
"""

import importlib.util
import os
import sys
from datetime import UTC, datetime
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
    pinned_request,
    pinned_tzif_bytes,
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
from drift.domain.evaluator_results import (  # noqa: E402
    EvaluationClassification,
    ExploratoryEvaluationResultV1,
)
from drift.domain.evaluator_trace import (  # noqa: E402
    EvaluationPhase,
    evaluation_trace_log_hash,
)
from drift.evaluator.engine import (  # noqa: E402
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)

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


def test_the_smoke_run_marks_every_valuation_as_exploratory_grade(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    engine = _engine(intake)

    # The engine reads the grade from the admission, so an exploratory
    # admission can never mint a promotion-grade valuation.
    assert engine.admission.lane == "exploratory"
    assert engine.bundle.has_exploratory_reconstructions is True
    assert engine.bundle.source_snapshot_hash is None


def test_a_terms_only_corporate_action_moves_no_cash_or_shares(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    artifacts, _strategy = _run(intake)

    # The pinned window carries one cash dividend with an ex date inside it.
    assert len(intake.economic_terms.records) == 1
    assert intake.bundle.economic_outcomes == ()
    assert artifacts.final_state.holdings == ()
    assert artifacts.final_state.pending_cash_claims == ()
    # Terms alone move no money: the book still holds exactly its seed capital.
    assert (
        artifacts.final_state.cash_balance
        == _protocol(warmup=WARMUP_SESSIONS).initial_cash
    )
    assert [item.kind for item in artifacts.trace.events].count(
        "corporate_action_applied"
    ) == 0
    assert [item.kind for item in artifacts.trace.events].count("claim_settled") == 0


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

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / cli.BARS_FILE_NAME).write_bytes(PINNED_BARS)
    (raw / cli.CALENDAR_FILE_NAME).write_bytes(PINNED_CALENDAR)
    (raw / cli.ACTIONS_FILE_NAME).write_bytes(PINNED_CORPORATE_ACTIONS)
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


def test_the_smoke_run_needs_no_dotenv_and_no_credential_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    assert not (REPO_ROOT / ".env").exists()
    result = run_pinned_intake(tmp_path / "private")

    assert result.admission.lane == "exploratory"
    assert os.environ.get("APCA_API_KEY_ID") is None


def test_no_retained_provider_byte_reaches_the_repository(tmp_path: Path) -> None:
    result = run_pinned_intake(tmp_path / "private")
    tracked = {path.name for path in (REPO_ROOT / "src" / "drift").rglob("*")}

    assert result.retained.bars_hash not in tracked
    assert REPO_ROOT not in result.retained.root.parents


def test_the_pinned_window_is_quiet_and_fully_scheduled(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    clock = intake.session_clock

    assert clock.mode == "scheduled_session_reconstruction"
    assert clock.sessions[0].opened_at == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert clock.sessions[-1].closed_at == datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
    assert all(item.authority == "scheduled_reconstruction" for item in clock.sessions)
