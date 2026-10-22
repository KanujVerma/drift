"""#508 PR A: engine-owned opening book without a caller-provided book.

These tests verify the mechanical prepare/consume lifecycle. They do not
authenticate a Matthew account provisioner, retained SQLite event, research
grant, or original M0 RESULT. Those are separately gated PR B and PR C.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from exploratory_decision_test_support import (
    ReconstructedTargetStrategy,
    bundle_of,
    reconstructed_engine,
    run_engine,
    three_regular_sessions,
)
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
from drift.evaluator.portfolio import initial_portfolio_state
from drift.serialization.canonical import canonical_json


class _SpoofedCash(Decimal):
    """Value 1 whose string representation impersonates original 10000 cash."""

    def __str__(self) -> str:
        return "10000"


@dataclass
class _Recorder:
    """A local fake lifecycle: no trusted issuer or durable receipt exists."""

    fail: str | None = None
    tamper: str | None = None
    spoof_at: str | None = None
    mutate_identity_at: str | None = None
    mutate_retention_config: bool = False
    seen: list[str] = field(default_factory=list)
    retained: PortfolioStateV2 | None = None
    claimed: PortfolioStateV2 | None = None
    consumed: PortfolioStateV2 | None = None
    currency: str | None = None

    def _visit(self, phase: str, book: PortfolioStateV2) -> None:
        self.seen.append(phase)
        if self.tamper == phase:
            object.__setattr__(book, "cash_balance", Decimal("1"))
        if self.spoof_at == phase:
            object.__setattr__(book, "cash_balance", _SpoofedCash("1"))
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
        if self.mutate_retention_config:
            object.__setattr__(admission, "admission_hash", "0" * 64)
            object.__setattr__(protocol, "initial_cash", Decimal("1"))

    def claim_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        assert run_identity.admission_hash == opening_book.admission_hash
        self.claimed = opening_book
        self._visit("claim", opening_book)
        if self.mutate_identity_at == "claim":
            object.__setattr__(run_identity, "code_version_hash", "1" * 64)

    def observe_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        assert run_identity.admission_hash == opening_book.admission_hash
        self.consumed = opening_book
        self._visit("consume", opening_book)
        if self.mutate_identity_at == "consume":
            object.__setattr__(run_identity, "code_version_hash", "1" * 64)


def _refuse_session_start(
    engine: evaluator_engine.SessionEvaluatorEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a session began despite a failed opening-book lifecycle")

    monkeypatch.setattr(type(engine), "_emit_session_start", forbidden)


def test_prepared_engine_consumes_same_original_and_matches_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_artifacts = _run(_engine())
    actual_initializer = initial_portfolio_state
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
    assert lifecycle.retained is not None
    assert lifecycle.retained is not originals[0]
    assert canonical_json(lifecycle.retained) == canonical_json(originals[0])
    assert lifecycle.currency == "USD"
    assert lifecycle.retained.net_asset_value == Decimal("10000")
    assert lifecycle.retained.holdings == ()
    assert lifecycle.retained.pending_cash_claims == ()
    assert lifecycle.seen == ["retain"]
    saw_private_original = False
    emit_original = type(engine)._emit_session_start

    def inspect_original(*args: Any, **kwargs: Any) -> None:
        nonlocal saw_private_original
        if args[2] == 0:
            saw_private_original = True
            # Only the privately revalidated runner receives the original.
            assert args[0] is not engine
            assert args[1].state is originals[0]
        emit_original(*args, **kwargs)

    monkeypatch.setattr(type(engine), "_emit_session_start", inspect_original)
    prepared_artifacts = _run(engine)
    assert originals == [lifecycle.retained]
    assert lifecycle.retained is lifecycle.claimed is lifecycle.consumed
    assert saw_private_original
    assert not hasattr(engine, "_prepared_opening_book")
    assert lifecycle.seen == ["retain", "claim", "consume"]
    assert canonical_json(prepared_artifacts) == canonical_json(legacy_artifacts)
    assert prepared_artifacts.result.result_hash == legacy_artifacts.result.result_hash
    assert prepared_artifacts.trace.trace_hash == legacy_artifacts.trace.trace_hash


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
    expected = ["retain", "claim"]
    if phase == "consume":
        expected.append("consume")
    assert lifecycle.seen == expected
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
    # Construct malformed input without invoking FrozenModel.model_copy's
    # *own* validator before the engine can inspect it.
    forged = type(good).model_construct(
        **(good.model_dump(mode="python") | {"admission_hash": "0" * 64})
    )
    with pytest.raises(ValueError):
        engine.run(strategy=_buy_ten(), run_identity=forged)
    assert lifecycle.seen == ["retain"]
    assert _run(engine).result.classification.value == "complete"
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


@pytest.mark.parametrize("phase", ["claim", "consume"])
def test_observer_cannot_relabel_the_sealed_run_identity(phase: str) -> None:
    """An observer may mutate its input, but never the engine's original."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    lifecycle = _Recorder(mutate_identity_at=phase)
    engine.prepare_opening_book(lifecycle=lifecycle)
    result = _run(engine)
    assert canonical_json(result) == baseline
    assert lifecycle.seen == ["retain", "claim", "consume"]


def test_retention_observer_cannot_rewrite_engine_policy_inputs() -> None:
    """Admission and protocol passed to a callback are detached copies."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    lifecycle = _Recorder(mutate_retention_config=True)
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert engine.protocol.initial_cash == Decimal("10000")
    assert lifecycle.retained is not None
    assert engine.admission.admission_hash == lifecycle.retained.admission_hash
    assert canonical_json(_run(engine)) == baseline


@pytest.mark.parametrize("phase", ["retain", "claim", "consume"])
def test_spoofed_decimal_cash_cannot_pass_original_book_hash(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """The exact engine-created instance must remain type-valid after callbacks."""
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)
    lifecycle = _Recorder(spoof_at=phase)
    if phase == "retain":
        with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
            engine.prepare_opening_book(lifecycle=lifecycle)
    else:
        engine.prepare_opening_book(lifecycle=lifecycle)
        with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
            _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    expected = ["retain"]
    if phase in ("claim", "consume"):
        expected.append("claim")
    if phase == "consume":
        expected.append("consume")
    assert lifecycle.seen == expected


def test_spoofed_book_between_prepare_and_claim_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert lifecycle.retained is not None
    object.__setattr__(lifecycle.retained, "cash_balance", _SpoofedCash("1"))
    with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
        _run(engine)
    assert lifecycle.seen == ["retain"]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_prepared_book_session_key_cannot_alias_mutable_bundle_clock() -> None:
    """A callback replacing its book key may not mutate the input clock."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    first_session = engine.bundle.session_clock.sessions[0].session_key
    original_day = first_session.local_date

    class KeySwappingObserver(_Recorder):
        def retain_original_book(
            self,
            *,
            opening_book: PortfolioStateV2,
            admission: EvaluationAdmissionV1,
            protocol: EvaluationProtocolV1,
            currency_code: str,
        ) -> None:
            held = opening_book.session_key
            assert held is not first_session
            equivalent = SessionKeyV1.model_validate_json(held.model_dump_json())
            object.__setattr__(opening_book, "session_key", equivalent)
            object.__setattr__(held, "local_date", date(2000, 1, 1))
            super().retain_original_book(
                opening_book=opening_book,
                admission=admission,
                protocol=protocol,
                currency_code=currency_code,
            )

    observer = KeySwappingObserver()
    engine.prepare_opening_book(lifecycle=observer)
    assert first_session.local_date == original_day
    assert observer.retained is not None
    assert observer.retained.session_key.local_date == original_day
    assert canonical_json(_run(engine)) == baseline
    assert observer.seen == ["retain", "claim", "consume"]


class _MutatingFieldKey(str):
    """A str subclass that modifies model storage during equal-text lookups."""

    def __new__(
        cls, spelling: str, owner: PortfolioStateV2 | SessionKeyV1, bad: object
    ) -> _MutatingFieldKey:
        return str.__new__(cls, spelling)

    def __init__(
        self, spelling: str, owner: PortfolioStateV2 | SessionKeyV1, bad: object
    ) -> None:
        self.owner = owner
        self.bad = bad
        self.lookups = 0

    def __hash__(self) -> int:
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        self.lookups += 1
        if self.lookups == 3:
            vars(self.owner)[self] = self.bad
        return str.__eq__(self, other) is True


@pytest.mark.parametrize("phase", ["retain", "claim", "consume"])
def test_forged_cash_field_key_is_refused_before_any_comparison(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)

    class KeyPoison(_Recorder):
        def _visit(self, where: str, book: PortfolioStateV2) -> None:
            if where == phase:
                values = vars(book)
                original = values.pop("cash_balance")
                values[_MutatingFieldKey("cash_balance", book, Decimal("1"))] = original
            super()._visit(where, book)

    observer = KeyPoison()
    if phase == "retain":
        with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
            engine.prepare_opening_book(lifecycle=observer)
    else:
        engine.prepare_opening_book(lifecycle=observer)
        with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
            _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_forged_session_field_key_is_refused_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)

    class SessionKeyPoison(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            if phase == "retain":
                session = book.session_key
                values = vars(session)
                original = values.pop("local_date")
                values[_MutatingFieldKey("local_date", session, date(2000, 1, 1))] = (
                    original
                )
            super()._visit(phase, book)

    observer = SessionKeyPoison()
    with pytest.raises(OpeningBookLifecycleError, match="untrusted field types"):
        engine.prepare_opening_book(lifecycle=observer)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_post_callback_async_observer_tamper_cannot_change_original_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observer-held books cannot change execution after the last check."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert lifecycle.retained is not None
    assert not hasattr(engine, "_prepared_opening_book")
    actual_emit = type(engine)._emit_session_start
    changed = False

    def after_last_callback(*args: Any, **kwargs: Any) -> None:
        nonlocal changed
        if args[0] is not engine and not changed:
            changed = True
            # The test harness signals a retained-witness mutation after
            # observe_consumption and the last guard, immediately before the
            # engine emits its first session.
            object.__setattr__(lifecycle.retained, "cash_balance", Decimal("1"))
            object.__setattr__(lifecycle.retained, "net_asset_value", Decimal("1"))
        actual_emit(*args, **kwargs)

    monkeypatch.setattr(type(engine), "_emit_session_start", after_last_callback)
    artifacts = _run(engine)
    assert changed
    assert canonical_json(artifacts) == baseline
    assert lifecycle.retained.cash_balance == Decimal("1")
    assert artifacts.result.metrics.initial_cash == Decimal("10000")
    assert not hasattr(engine, "_prepared_opening_book")


def test_private_original_not_exposed_to_retention_claim_or_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The genuine initializer book is used, without an exposed attribute."""
    source_initializer = initial_portfolio_state
    issued: list[PortfolioStateV2] = []

    def issue(
        *,
        session_key: SessionKeyV1,
        initial_cash: Decimal,
        admission: EvaluationAdmissionV1,
    ) -> PortfolioStateV2:
        book = source_initializer(
            session_key=session_key, initial_cash=initial_cash, admission=admission
        )
        issued.append(book)
        return book

    monkeypatch.setattr(evaluator_engine, "initial_portfolio_state", issue)
    engine = _engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert len(issued) == 1
    original = issued[0]
    twin = lifecycle.retained
    assert twin is not None and original is not twin
    assert canonical_json(original) == canonical_json(twin)
    assert not hasattr(engine, "_prepared_opening_book")
    _run(engine)
    assert lifecycle.retained is lifecycle.claimed is lifecycle.consumed
    assert lifecycle.claimed is not original
    assert original.cash_balance == Decimal("10000")


def test_captured_engine_callback_cannot_reach_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callback holding the engine cannot fetch a mutable original field."""
    engine = _engine()
    baseline = canonical_json(_run(_engine()))

    class CapturedEngine(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            assert not hasattr(engine, "_prepared_opening_book")
            if phase == "retain":
                # The engine publishes the twin after retain succeeds.
                assert engine._observer_opening_book is None
            else:
                assert engine._observer_opening_book is book
            super()._visit(phase, book)

    lifecycle = CapturedEngine()
    engine.prepare_opening_book(lifecycle=lifecycle)
    assert not hasattr(engine, "_prepared_opening_book")
    assert canonical_json(_run(engine)) == baseline
    assert lifecycle.seen == ["retain", "claim", "consume"]


def test_callback_installed_instance_hook_cannot_mutate_prepared_book() -> None:
    """Reject post-consumption dispatch injection without changing legacy hooks."""
    engine = _engine()
    expected = canonical_json(_run(_engine()))
    calls = 0

    class HookInstallingObserver(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            nonlocal calls
            if phase == "consume":
                def injected(loop: Any, index: int, session: Any) -> None:
                    nonlocal calls
                    calls += 1
                    object.__setattr__(loop.state, "cash_balance", Decimal("1"))
                    object.__setattr__(loop.state, "net_asset_value", Decimal("1"))

                object.__setattr__(engine, "_emit_session_start", injected)
            super()._visit(phase, book)

    observer = HookInstallingObserver()
    engine.prepare_opening_book(lifecycle=observer)
    outcome = _run(engine)
    assert canonical_json(outcome) == expected
    assert calls == 0
    assert observer.seen == ["retain", "claim", "consume"]


@pytest.mark.parametrize(
    "hook_name",
    [
        "_step_session",
        "_advance",
        "_pre_open_effects",
        "_open_execution",
        "_intrasession_effects",
        "_close_mark",
        "_metrics",
        "_seal_result",
        "_post_close_decision",
    ],
)
def test_observer_cannot_inject_prepared_accounting_phase_hooks(
    hook_name: str,
) -> None:
    """Only trusted declared platform phase methods handle original book."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    calls = 0

    class HookInstallingObserver(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            nonlocal calls
            if phase == "consume":

                def injected(*args: Any, **kwargs: Any) -> Any:
                    nonlocal calls
                    calls += 1
                    raise AssertionError("observer-injected accounting hook executed")

                setattr(engine, hook_name, injected)
            super()._visit(phase, book)

    lifecycle = HookInstallingObserver()
    engine.prepare_opening_book(lifecycle=lifecycle)
    outcome = _run(engine)
    assert canonical_json(outcome) == baseline
    assert calls == 0
    assert lifecycle.seen == ["retain", "claim", "consume"]


def test_reconstructed_prepared_decision_ignores_instance_injection() -> None:
    """The weaker exploratory lane needs the same class-bound phase five."""
    bundle = bundle_of(three_regular_sessions())
    baseline = canonical_json(
        run_engine(
            reconstructed_engine(bundle),
            ReconstructedTargetStrategy({}),
        )
    )
    engine = reconstructed_engine(bundle)
    called = 0

    class ReconstructedPoison(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            nonlocal called
            if phase == "consume":

                def injected(*args: Any, **kwargs: Any) -> Any:
                    nonlocal called
                    called += 1
                    raise AssertionError("observer intercepted reconstructed decision")

                object.__setattr__(
                    engine, "_post_close_reconstructed_decision", injected
                )
            super()._visit(phase, book)

    observer = ReconstructedPoison()
    engine.prepare_opening_book(lifecycle=observer)
    result = run_engine(engine, ReconstructedTargetStrategy({}))
    assert canonical_json(result) == baseline
    assert called == 0
    assert observer.seen == ["retain", "claim", "consume"]


@pytest.mark.parametrize("phase", ["retain", "claim", "consume"])
def test_captured_engine_cannot_replace_private_accounting_collaborators(
    phase: str,
) -> None:
    """A callback-visible engine mutation cannot reach the original book."""
    baseline = _run(_engine())
    expected = canonical_json(baseline)
    engine = _engine()
    poisoned_calls = 0

    class PoisonCorporateActions:
        def apply_pre_open_actions(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal poisoned_calls
            poisoned_calls += 1
            state = args[0]
            object.__setattr__(state, "cash_balance", Decimal("1"))
            object.__setattr__(state, "net_asset_value", Decimal("1"))
            raise AssertionError("observer replaced the actual accounting processor")

    class PoisonRebalance:
        def rebalance(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal poisoned_calls
            poisoned_calls += 1
            raise AssertionError("observer replaced the actual rebalance processor")

    class CapturedEngineObserver(_Recorder):
        def _visit(self, at: str, book: PortfolioStateV2) -> None:
            if at == phase:
                # These fields are directly accessible on the engine captured
                # by a lifecycle closure. A shared execution self would invoke
                # the forged collaborator after the final book-integrity check.
                object.__setattr__(
                    engine, "_corporate_actions", PoisonCorporateActions()
                )
                object.__setattr__(engine, "_rebalance", PoisonRebalance())
                assert not any(
                    isinstance(value, evaluator_engine.SessionEvaluatorEngine)
                    for value in vars(engine).values()
                )
            super()._visit(at, book)

    observer = CapturedEngineObserver()
    engine.prepare_opening_book(lifecycle=observer)
    result = _run(engine)
    assert canonical_json(result) == expected
    assert result.result.metrics.initial_cash == Decimal("10000")
    assert result.final_state.cash_balance == baseline.final_state.cash_balance
    assert poisoned_calls == 0
    assert observer.seen == ["retain", "claim", "consume"]


def test_consume_observer_cannot_replace_private_evidence_and_bundle() -> None:
    """The actual run must not consult post-claim public engine references."""
    expected = canonical_json(_run(_engine()))
    engine = _engine()

    class CorruptPublicEngine(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            if phase == "consume":
                object.__setattr__(engine, "_bundle", object())
                object.__setattr__(engine, "_evidence", object())
                object.__setattr__(engine, "_accounting_index", object())
                object.__setattr__(engine, "_protocol", object())
            super()._visit(phase, book)

    observer = CorruptPublicEngine()
    engine.prepare_opening_book(lifecycle=observer)
    result = _run(engine)
    assert canonical_json(result) == expected
    assert observer.seen == ["retain", "claim", "consume"]

@pytest.mark.parametrize("spoofed_phase", ["new", "prepared", "failed"])
def test_consumed_engine_phase_spoof_never_restores_fresh_cash(
    spoofed_phase: str,
) -> None:
    """Even a forged 'new' phase cannot make the prepared engine legacy."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()
    observer = _Recorder()
    engine.prepare_opening_book(lifecycle=observer)
    assert canonical_json(_run(engine)) == baseline
    assert observer.seen == ["retain", "claim", "consume"]

    object.__setattr__(engine, "_opening_book_phase", spoofed_phase)
    object.__setattr__(engine, "_legacy_run_started", False)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())


def test_consumption_phase_spoof_refuses_before_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claimed original cannot step or be replayed after phase tampering."""
    actual_initializer = initial_portfolio_state
    initialized: list[PortfolioStateV2] = []

    def tracked_initializer(
        *,
        session_key: SessionKeyV1,
        initial_cash: Decimal,
        admission: EvaluationAdmissionV1,
    ) -> PortfolioStateV2:
        book = actual_initializer(
            session_key=session_key, initial_cash=initial_cash, admission=admission
        )
        initialized.append(book)
        return book

    monkeypatch.setattr(evaluator_engine, "initial_portfolio_state", tracked_initializer)
    engine = _engine()
    _refuse_session_start(engine, monkeypatch)

    class ResetsDuringConsume(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            if phase == "consume":
                object.__setattr__(engine, "_opening_book_phase", "new")
                object.__setattr__(engine, "_legacy_run_started", False)
            super()._visit(phase, book)

    observer = ResetsDuringConsume()
    engine.prepare_opening_book(lifecycle=observer)
    assert len(initialized) == 1
    with pytest.raises(OpeningBookLifecycleError, match="phase changed"):
        _run(engine)
    assert observer.seen == ["retain", "claim", "consume"]
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    object.__setattr__(engine, "_opening_book_phase", "new")
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())
    assert len(initialized) == 1


def test_retention_phase_spoof_cannot_reenter_or_reset_original() -> None:
    """The private reservation exists before any observer executes."""
    baseline = canonical_json(_run(_engine()))
    engine = _engine()

    class ResetsDuringRetain(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            if phase == "retain":
                object.__setattr__(engine, "_opening_book_phase", "new")
                with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
                    engine.prepare_opening_book(lifecycle=_Recorder())
                with pytest.raises(OpeningBookLifecycleError, match="not available"):
                    _run(engine)
            super()._visit(phase, book)

    observer = ResetsDuringRetain()
    engine.prepare_opening_book(lifecycle=observer)
    assert canonical_json(_run(engine)) == baseline
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)


def test_failed_retention_cannot_be_relabelled_as_unused() -> None:
    """Failed pre-claim retention permanently forbids new seed capital."""
    engine = _engine()

    class FailedRetain(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            if phase == "retain":
                object.__setattr__(engine, "_opening_book_phase", "new")
                raise RuntimeError("synthetic retain unavailable")
            super()._visit(phase, book)

    with pytest.raises(RuntimeError, match="synthetic retain unavailable"):
        engine.prepare_opening_book(lifecycle=FailedRetain())
    object.__setattr__(engine, "_opening_book_phase", "new")
    object.__setattr__(engine, "_legacy_run_started", False)
    with pytest.raises(OpeningBookLifecycleError, match="not available"):
        _run(engine)
    with pytest.raises(OpeningBookLifecycleError, match="fresh, unused"):
        engine.prepare_opening_book(lifecycle=_Recorder())
