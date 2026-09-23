"""M2 adversarial acceptance: a run identity names everything that changes it.

Issue 86, from the #8 final acceptance review (lanes F7 and F10, accounting
F5). Listing records, economic outcome records, interpretation registries, and
the exploratory cohort and replay sit outside the bundle yet change fills,
claims, and cash. Two runs with one ``run_identity_hash`` could therefore
disagree, a declared corporate action could be silently dropped, and an M0 row
could name a dataset or strategy other than the one evaluated.
"""

# ruff: noqa: E402

import sys
from pathlib import Path
from uuid import uuid7

_SUPPORT = Path(__file__).resolve().parents[1]
for folder in (_SUPPORT / "unit", _SUPPORT / "integration"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support

from drift.domain.strategies import StrategyReference
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    evaluator_evidence_hash,
)
from drift.evaluator.experiment_runner import execute_experiment_run


def _rebuilt(
    engine: SessionEvaluatorEngine, **evidence: object
) -> SessionEvaluatorEngine:
    """The same bundle, admission, protocol, and costs over other evidence."""
    return SessionEvaluatorEngine(
        bundle=engine.bundle,
        admission=engine.admission,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence=SessionEvaluatorEvidence(**evidence),  # type: ignore[arg-type]
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def _identity(engine: SessionEvaluatorEngine) -> object:
    return eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )


def test_an_identity_minted_over_other_evidence_is_refused() -> None:
    """The reviewer's case: equal identities, different listing evidence."""
    genuine = eng._engine()
    identity = _identity(genuine)
    stripped = _rebuilt(genuine)
    assert stripped.evaluator_evidence_hash != genuine.evaluator_evidence_hash

    with pytest.raises(
        ValueError, match=r"^the run identity must bind this evaluation's evaluator"
    ):
        stripped.run(strategy=eng._buy_ten(), run_identity=identity)  # type: ignore[arg-type]


def test_a_declared_outcome_the_engine_is_not_handed_is_refused() -> None:
    """A split the bundle declares cannot be silently read as no action."""
    engine, _ = eng._split_engine()

    with pytest.raises(
        ValueError,
        match=r"^the engine was not handed the economic outcome records for "
        r"declared resolutions: ",
    ):
        _rebuilt(engine, listing_role_records=eng.ROLE_RECORDS)


def test_the_evidence_identity_ignores_member_order() -> None:
    """Order carries no meaning, so it cannot move the identity."""
    forward = SessionEvaluatorEvidence(listing_role_records=eng.ROLE_RECORDS)
    backward = SessionEvaluatorEvidence(
        listing_role_records=tuple(reversed(eng.ROLE_RECORDS))
    )
    assert len(eng.ROLE_RECORDS) > 1

    assert evaluator_evidence_hash(forward) == evaluator_evidence_hash(backward)


class _ImpostorStrategy(eng.FixedTargetStrategy):
    """Decides like the named strategy, but is another code version."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return StrategyReference(
            strategy_id=uuid7(),
            strategy_version="1",
            code_hash="9" * 64,
            artifact_reference=eng.STRATEGY_REFERENCE.artifact_reference,
        )


def test_a_strategy_other_than_the_one_the_identity_names_is_refused() -> None:
    engine = eng._engine()
    impostor = _ImpostorStrategy(eng._buy_ten().targets)

    with pytest.raises(
        ValueError, match=r"^the run identity must bind the strategy that runs"
    ):
        engine.run(strategy=impostor, run_identity=_identity(engine))  # type: ignore[arg-type]
    assert impostor.seen == []


def test_an_experiment_row_cannot_name_another_dataset() -> None:
    engine = eng._engine()

    with pytest.raises(
        ValueError, match=r"^the specification dataset is not the evaluated bundle"
    ):
        execute_experiment_run(
            run_support._specification(dataset_hash="d" * 64),
            run_support._context(engine),
        )


def test_an_experiment_row_cannot_name_a_strategy_other_than_the_one_run() -> None:
    engine = eng._engine()
    context = run_support._context(engine, strategy=_ImpostorStrategy({}))

    with pytest.raises(
        ValueError, match=r"^the strategy that runs does not match the run identity"
    ):
        execute_experiment_run(run_support._specification(), context)
