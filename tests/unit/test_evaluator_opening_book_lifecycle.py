"""#508 PR A: engine-owned opening book without a caller-provided book.

These tests verify the mechanical prepare/consume lifecycle. They do not
authenticate a Matthew account provisioner, retained SQLite event, research
grant, or original M0 RESULT. Those are separately gated PR B and PR C.
"""

from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from test_evaluator_engine import _buy_ten, _engine, _run, _run_identity

import drift.evaluator.engine as evaluator_engine
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    EvaluationRunIdentityV2,
)
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.opening_book_lifecycle import OpeningBookLifecycleError
from drift.serialization.canonical import canonical_json


@dataclass
class _Recorder:
    """A local fake lifecycle: no trusted issuer or durable receipt exists."""

    fail: str | None = None
    tamper: str | None = None
    seen: list[str] = field(default_factory=list)
    retained: PortfolioStateV2 | None = None
    claimed: PortfolioStateV2 | None = None
    consumed: PortfolioStateV2 | None = None
    currency: str | None = None

    def _visit(self, phase: str, book: PortfolioStateV2) -> None:
        self.seen.append(phase)
        if self.tamper == phase:
            object.__setattr__(book, "cash_balance", Decimal("1"))
        if self.fail == phase:
            raise RuntimeError(f"synthetic observer {phase} failed")

    def retain_original_book(
        self,
        *,
        opening_book: PortfolioStateV2,
        admission: EvaluationAdmissionV1,
        protocol: EvaluationProtocolV1,
        currency_code: str,
    ) -> None:
        assert opening_book.admission_hash == admission.admission_hash
        assert opening_book.cash_balance == protocol.initial_cash
        self.retained = opening_book
        self.currency = currency_code
        self._visit("retain", opening_book)

    def claim_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        assert run_identity.admission_hash == opening_book.admission_hash
        self.claimed = opening_book
        self._visit("claim", opening_book)

    def observe_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        assert run_identity.admission_hash == opening_book.admission_hash
        self.consumed = opening_book
        self._visit("consume", opening_book)


def _refuse_session_start(engine: evaluator_engine.SessionEvaluatorEngine,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("a session began despite a failed opening-book lifecycle")

    monkeypatch.setattr(engine, "_emit_session_start", forbidden)


def test_prepared_engine_consumes_same_original_and_matches_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_artifacts = _run(_engine())
    actual_initializer = evaluator_engine.initial_portfolio_state
    originals: list[PortfolioStateV2] = []

    def counted(
        *,
        session_key: SessionKeyV1,
        initial_cash: Decimal,
        admission: EvaluationAdmissionV1,
    ) -> PortfolioStateV2:
        book = actual_initializer(
            session_key=session_key, initial_cash=initial_cash, admission=admission
        )
        originals.append(book)
        return book

    monkeypatch.setattr(evaluator_engine, "initial_portfolio_state", counted)
    engine = _engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert originals == [lifecycle.retained]
    assert lifecycle.retained is originals[0]
    assert lifecycle.currency == "USD"
    assert lifecycle.retained.net_asset_value == Decimal("10000")
    assert lifecycle.retained.holdings == ()
    assert lifecycle.retained.pending_cash_claims == ()
    assert lifecycle.seen == ["retain"]

    prepared_artifacts = _run(engine)
    assert originals == [lifecycle.retained]
    assert lifecycle.retained is lifecycle.claimed is lifecycle.consumed
    assert lifecycle.seen == ["retain", "claim", "consume"]
    assert canonical_json(prepared_artifacts) == canonical_json(legacy_artifacts)
    assert (
        prepared_artifacts.result.result_hash
        == legacy_artifacts.result.result_hash
    )
    assert (
        prepared_artifacts.trace.trace_hash
        == legacy_artifacts.trace.trace_hash
    )


def test_prepared_run_cannot_execute_twice_or_reset_cash() -> None:
    engine = _engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())
    assert lifecycle.seen == ["retain", "claim", "consume"]


def test_legacy_engine_still_replays_and_cannot_be_retroactively_prepared() -> None:
    engine = _engine()
    first = _run(engine)
    second = _run(engine)
    assert canonical_json(first) == canonical_json(second)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())


def test_retention_failure_permanently_refuses_new_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)
    lifecycle = _Recorder(fail="retain")
    with pytest.raises(RuntimeError, match="observer retain failed"):
        engine.prepare_opening_book(lifecycle=lifecycle)
    assert lifecycle.seen == ["retain"]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())


@pytest.mark.parametrize("phase", ["claim", "consume"])
def test_claim_or_consume_failure_prevents_sessions_and_replay(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)
    lifecycle = _Recorder(fail=phase)
    engine.prepare_opening_book(lifecycle=lifecycle)
    with pytest.raises(RuntimeError, match=f"observer {phase} failed"):
        _run(engine)
    assert lifecycle.seen == (
        ["retain", "claim"] if phase == "claim"
        else ["retain", "claim", "consume"]
    )
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_invalid_run_identity_does_not_claim_or_consume() -> None:
    engine = _engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    good = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    forged = good.model_copy(update={"admission_hash": "0" * 64})
    with pytest.raises(ValueError):
        engine.run(strategy=_buy_ten(), run_identity=forged)
    assert lifecycle.seen == ["retain"]
    assert _run(engine).result.classification.value == "COMPLETE"
    assert lifecycle.seen == ["retain", "claim", "consume"]


@pytest.mark.parametrize("phase", ["retain", "claim", "consume"])
def test_observer_cannot_change_engine_owned_original_book(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)
    lifecycle = _Recorder(tamper=phase)
    if phase == "retain":
        with pytest.raises(OpeningBookLifecycleError, match="changed"):
            engine.prepare_opening_book(lifecycle=lifecycle)
    else:
        engine.prepare_opening_book(lifecycle=lifecycle)
        with pytest.raises(OpeningBookLifecycleError, match="changed"):
            _run(engine)
    with pytest.raises(OpeningBookLifecycleError):
        _run(engine)


def test_reentrant_preparation_is_refused_before_original_ack() -> None:
    engine = _engine()

    class Reentering(_Recorder):
        def retain_original_book(
            self,
            *,
            opening_book: PortfolioStateV2,
            admission: EvaluationAdmissionV1,
            protocol: EvaluationProtocolV1,
            currency_code: str,
        ) -> None:
            with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
                engine.prepare_opening_book(lifecycle=_Recorder())
            super().retain_original_book(
                opening_book=opening_book,
                admission=admission,
                protocol=protocol,
                currency_code=currency_code,
            )

    lifecycle = Reentering()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert lifecycle.seen == ["retain"]
    _run(engine)
    assert lifecycle.seen == ["retain", "claim", "consume"]
