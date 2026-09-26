"""M2 adversarial acceptance: a V2 run identity binds strategy parameters.

Issue 112 (gap G1 of the strategy-surface contract inventory, #113, decision
D2, ruled option (b) on 2026-09-24). ``EvaluationRunIdentityV1`` binds the
strategy's ``code_hash`` and nothing about its parameters, so two
parameterizations of one strategy version shared one ``run_identity_hash``
while their results differed (probe P1). ``EvaluationRunIdentityV2`` binds a
``strategy_parameters_hash``: the experiment runner checks it against the
specification's parameters, and the engine checks it against the parameters
the strategy exposes through ``ParameterizedStrategy.strategy_parameters``.
V1 stays frozen and byte-identical, and a V1 run never reads parameters.
"""

# ruff: noqa: E402

import dataclasses
import sys
from collections.abc import Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

_SUPPORT = Path(__file__).resolve().parents[1]
for folder in (_SUPPORT / "unit", _SUPPORT / "integration"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support
from pydantic import TypeAdapter, ValidationError
from test_m2_anti_laundering import (
    REALIZED_RESULT_HASH_SINCE_ISSUE_63_STAGE_2,
    REALIZED_TRACE_HASH_SINCE_ISSUE_63_STAGE_2,
    RECONSTRUCTED_RESULT_HASH_SINCE_ISSUE_63_STAGE_2,
)

from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentity,
    EvaluationRunIdentityV1,
    EvaluationRunIdentityV2,
    StrategyParametersBindingError,
    evaluation_run_identity_hash,
    evaluation_run_identity_v2_hash,
    strategy_parameters_hash,
)
from drift.domain.evaluator_results import EvaluationRunArtifactsV1
from drift.domain.evaluator_strategy import ParameterizedStrategy, RuntimeStrategy
from drift.evaluator.bundles import (
    build_evaluation_run_identity,
    build_evaluation_run_identity_v2,
)
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    require_bound_strategy_parameters,
)
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import content_hash

H = eng.H
TEN = {"target_quantity": 10}
FIVE = {"target_quantity": 5}

ENGINE_MISMATCH = (
    r"^the run identity must bind the parameters the strategy runs with: "
    r"identity binds [0-9a-f]{64}, the strategy exposes [0-9a-f]{64}$"
)
NO_PARAMETERS_SURFACE = (
    r"^a V2 run identity binds strategy parameters, and the strategy exposes "
    r"none: it must implement ParameterizedStrategy\.strategy_parameters "
    r"\(issue 112\)$"
)
SPECIFICATION_MISMATCH = (
    r"^the specification parameters do not match the evaluated run identity: "
    r"specification parameters hash to [0-9a-f]{64}, run identity binds "
    r"[0-9a-f]{64}$"
)
EXPOSED_NOT_CANONICAL = (
    r"^the parameters the strategy exposes must be canonical JSON data "
    r"\(issue 112\): "
)
SPECIFICATION_NOT_CANONICAL = (
    r"^the specification parameters must be canonical JSON data \(issue 112\): "
)

#: `EvaluationRunIdentityV1`, frozen by the issue 112 ruling. Computed at
#: 7213c67, before `EvaluationRunIdentityV2` existed, over the pinned
#: interpreter and the locked pydantic. Any edit to the V1 model moves it.
V1_IDENTITY_SCHEMA_FINGERPRINT = (
    "76874f4975bc8ec30bdb8455bad99bd7e9ec7b26e04fcf092ab7ef740c0d412c"
)
V1_IDENTITY_FIELDS = (
    "schema_version",
    "strategy_hash",
    "protocol_hash",
    "cost_model_hash",
    "admission_hash",
    "bundle_hash",
    "evaluator_evidence_hash",
    "code_version_hash",
    "environment_closure_hash",
    "run_identity_hash",
)
#: The self-excluding hash of one synthetic V1 identity, computed at 7213c67.
#: It pins the V1 hash function's bytes independently of any evidence.
V1_SYNTHETIC_IDENTITY_HASH = (
    "bd3d694ca6f47b15a4972f043867d5728bee99423d75ed7313391a62901759ca"
)


# --- strategies -----------------------------------------------------------


class ParameterizedFixedTargetStrategy(eng.FixedTargetStrategy):
    """Holds ``target_quantity`` shares of SEC_A, as its parameters declare."""

    def __init__(self, parameters: object) -> None:
        quantity = (
            parameters["target_quantity"] if isinstance(parameters, Mapping) else 0
        )
        quantity = quantity if type(quantity) is int else 0
        super().__init__(
            {day: ((eng.SEC_A, quantity),) for day in (eng.DAY_1, eng.DAY_2, eng.DAY_3)}
        )
        self.parameters = parameters
        self.parameter_reads = 0

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        self.parameter_reads += 1
        return self.parameters  # type: ignore[return-value]


class _ParametersNeverRead(eng.FixedTargetStrategy):
    """A V1 strategy that also exposes parameters, which V1 must never read."""

    reads = 0

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        type(self).reads += 1
        raise AssertionError("a V1 run read the strategy parameters")


class _EqualToEveryInt(int):
    """A parameter value equal to every value, as a forged leaf could be."""

    __hash__ = int.__hash__

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


class _KeyNamedLikeTheTarget(str):
    """A parameter name that looks up as ``target_quantity``, whatever it spells."""

    def __hash__(self) -> int:
        return hash("target_quantity")

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


class _TextEqualToEveryText(str):
    """A hash equal to every string, as a forged identity leaf could be."""

    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


class _LyingDict(dict[str, object]):
    """A dict whose own methods show the declared parameters over other storage."""

    def items(self) -> Any:
        return TEN.items()

    def __iter__(self) -> Iterator[str]:
        return iter(TEN)

    def __getitem__(self, key: str) -> object:
        return TEN[key]


class _RepeatingMapping(Mapping[str, object]):
    """A mapping that names one parameter twice, with two values."""

    def __init__(self) -> None:
        self._answers = iter((5, 10))

    def __getitem__(self, key: str) -> object:
        return next(self._answers)

    def __iter__(self) -> Iterator[str]:
        return iter(("target_quantity", "target_quantity"))

    def __len__(self) -> int:
        return 1


# --- identities -----------------------------------------------------------


def _v2_identity(
    engine: SessionEvaluatorEngine, parameters: object = TEN
) -> EvaluationRunIdentityV2:
    return build_evaluation_run_identity_v2(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        strategy_parameters_hash=strategy_parameters_hash(parameters),
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=eng.CODE_VERSION_HASH,
        environment_closure_hash=eng.ENVIRONMENT_HASH,
    )


def _v1_identity(engine: SessionEvaluatorEngine) -> EvaluationRunIdentityV1:
    return eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )


def _run_v2(
    engine: SessionEvaluatorEngine,
    strategy: object,
    identity: EvaluationRunIdentityV2,
) -> EvaluationRunArtifactsV1:
    return engine.run(strategy=strategy, run_identity=identity)  # type: ignore[arg-type]


def _synthetic_identity_fields() -> dict[str, Any]:
    return {
        "strategy_hash": H["1"],
        "protocol_hash": H["2"],
        "cost_model_hash": H["3"],
        "admission_hash": H["4"],
        "bundle_hash": H["5"],
        "evaluator_evidence_hash": H["6"],
        "code_version_hash": H["7"],
        "environment_closure_hash": H["8"],
    }


def _sealed_v2(**fields: Any) -> EvaluationRunIdentityV2:
    draft = EvaluationRunIdentityV2.model_construct(
        schema_version="2", run_identity_hash="0" * 64, **fields
    )
    return EvaluationRunIdentityV2.model_validate(
        {**dict(draft), "run_identity_hash": evaluation_run_identity_v2_hash(draft)}
    )


# ==========================================================================
# Probe P1: two parameterizations of one strategy version
# ==========================================================================


def test_v1_still_gives_two_parameterizations_one_identity_by_design() -> None:
    """V1 is frozen by the ruling, so probe P1 still collides under V1.

    This is the recorded G1 behavior, kept deliberately: V1 binds no
    parameters. Canonical M3 runs use V2, which the tests below cover.
    """
    engine = eng._engine()
    ten = eng._run(engine, ParameterizedFixedTargetStrategy(TEN))
    five = eng._run(engine, ParameterizedFixedTargetStrategy(FIVE))

    assert type(ten.result.run_identity) is EvaluationRunIdentityV1
    assert (
        ten.result.run_identity.run_identity_hash
        == five.result.run_identity.run_identity_hash
    )
    assert ten.result.result_hash != five.result.result_hash
    assert ten.result.metrics.ending_net_asset_value == 10200
    assert five.result.metrics.ending_net_asset_value == 10100


def test_v2_gives_two_parameterizations_two_identities() -> None:
    """Probe P1 under V2: one strategy version, two parameterizations."""
    engine = eng._engine()
    ten = _run_v2(engine, ParameterizedFixedTargetStrategy(TEN), _v2_identity(engine))
    five = _run_v2(
        engine, ParameterizedFixedTargetStrategy(FIVE), _v2_identity(engine, FIVE)
    )

    for artifacts, parameters in ((ten, TEN), (five, FIVE)):
        identity = artifacts.result.run_identity
        assert type(identity) is EvaluationRunIdentityV2
        assert identity.strategy_hash == eng.STRATEGY_CODE_HASH
        assert identity.strategy_parameters_hash == content_hash(parameters)
    assert (
        ten.result.run_identity.run_identity_hash
        != five.result.run_identity.run_identity_hash
    )
    assert ten.result.result_hash != five.result.result_hash
    assert ten.result.metrics.ending_net_asset_value == 10200
    assert five.result.metrics.ending_net_asset_value == 10100


def test_a_v2_run_over_the_same_evidence_trades_as_its_v1_run() -> None:
    """V2 changes the identity the result carries, never the evaluation."""
    engine = eng._engine()
    v1 = eng._run(engine, ParameterizedFixedTargetStrategy(TEN))
    v2 = _run_v2(engine, ParameterizedFixedTargetStrategy(TEN), _v2_identity(engine))

    assert v2.trace.trace_hash == v1.trace.trace_hash
    assert v2.final_state == v1.final_state
    assert v2.result.metrics == v1.result.metrics
    assert v2.result.result_hash != v1.result.result_hash


def test_a_v2_result_rebuilds_through_canonical_json() -> None:
    """The runner rebuilds artifacts through JSON; V2 must survive that."""
    engine = eng._engine()
    artifacts = _run_v2(
        engine, ParameterizedFixedTargetStrategy(TEN), _v2_identity(engine)
    )

    rebuilt = EvaluationRunArtifactsV1.model_validate_json(artifacts.model_dump_json())

    assert type(rebuilt.result.run_identity) is EvaluationRunIdentityV2
    assert rebuilt == artifacts
    assert rebuilt.result.result_hash == artifacts.result.result_hash


# ==========================================================================
# The V2 identity and its hash domain
# ==========================================================================


def test_v2_hashing_can_never_collide_with_v1() -> None:
    """Equal shared fields, distinct schema versions: distinct hash domains."""
    shared = _synthetic_identity_fields()
    v1 = EvaluationRunIdentityV1.model_validate(
        {
            **shared,
            "run_identity_hash": evaluation_run_identity_hash(
                EvaluationRunIdentityV1.model_construct(
                    run_identity_hash="0" * 64, **shared
                )
            ),
        }
    )
    v2 = _sealed_v2(**shared, strategy_parameters_hash=H["9"])

    assert v1.schema_version == "1"
    assert v2.schema_version == "2"
    assert v2.run_identity_hash != v1.run_identity_hash
    assert v2.run_identity_hash == evaluation_run_identity_v2_hash(v2)
    with pytest.raises(ValidationError, match="strategy_parameters_hash"):
        EvaluationRunIdentityV1.model_validate(v2.model_dump())
    with pytest.raises(ValidationError, match="strategy_parameters_hash"):
        EvaluationRunIdentityV2.model_validate(v1.model_dump())


def test_the_v2_hash_binds_the_parameters_hash() -> None:
    shared = _synthetic_identity_fields()
    first = _sealed_v2(**shared, strategy_parameters_hash=H["9"])
    second = _sealed_v2(**shared, strategy_parameters_hash=H["a"])

    assert first.run_identity_hash != second.run_identity_hash
    with pytest.raises(ValidationError, match="run identity hash mismatch"):
        first.model_copy(update={"strategy_parameters_hash": H["a"]})


def test_the_identity_union_discriminates_on_the_schema_version() -> None:
    adapter: TypeAdapter[EvaluationRunIdentityV1 | EvaluationRunIdentityV2] = (
        TypeAdapter(EvaluationRunIdentity)
    )
    engine = eng._engine()
    v1 = _v1_identity(engine)
    v2 = _v2_identity(engine)

    assert type(adapter.validate_json(adapter.dump_json(v1))) is EvaluationRunIdentityV1
    assert type(adapter.validate_json(adapter.dump_json(v2))) is EvaluationRunIdentityV2


def test_the_v2_builder_requires_the_admission_to_admit_this_bundle() -> None:
    engine = eng._engine()
    other = eng._bundle(days=eng.DAYS[:3])
    assert other.bundle_hash != engine.bundle.bundle_hash

    with pytest.raises(
        ValueError,
        match=r"^run identity requires the admission to admit this exact bundle: ",
    ):
        build_evaluation_run_identity_v2(
            strategy_hash=eng.STRATEGY_CODE_HASH,
            strategy_parameters_hash=content_hash(TEN),
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=eng._admission(other),
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=eng.CODE_VERSION_HASH,
            environment_closure_hash=eng.ENVIRONMENT_HASH,
        )


# ==========================================================================
# Canonical parameters
# ==========================================================================


def test_the_parameters_hash_is_the_content_hash_of_canonical_parameters() -> None:
    """The ruling's runner check is content_hash(specification.parameters)."""
    specification = run_support._specification()
    nested = {"b": [1, 2.5, True, None, "x"], "a": {"z": 0, "y": "é"}}

    assert strategy_parameters_hash(specification.parameters) == content_hash(
        specification.parameters
    )
    assert strategy_parameters_hash(TEN) == content_hash(TEN)
    assert strategy_parameters_hash(nested) == content_hash(nested)
    # The frozen form a specification holds and the literal a strategy
    # exposes are one parameterization.
    frozen = MappingProxyType(
        {"a": MappingProxyType({"y": "é", "z": 0}), "b": (1, 2.5, True, None, "x")}
    )
    assert strategy_parameters_hash(frozen) == strategy_parameters_hash(nested)


@pytest.mark.parametrize(
    ("parameters", "problem"),
    [
        (
            {"target_quantity": _EqualToEveryInt(5)},
            r"the value at \$\['target_quantity'\] is not exactly",
        ),
        (
            {_KeyNamedLikeTheTarget("quantity"): 10},
            r"the mapping at \$ has a key that is not exactly a str",
        ),
        (_LyingDict(target_quantity=5), r"the value at \$ is not exactly"),
        (_RepeatingMapping(), r"the value at \$ is not exactly"),
        (
            MappingProxyType(_RepeatingMapping()),
            r"the mapping at \$ repeats the key 'target_quantity'",
        ),
        (
            {"a": [MappingProxyType({"b": {_KeyNamedLikeTheTarget("c"): 1}})]},
            r"the mapping at \$\['a'\]\[0\]\['b'\] has a key that is not exactly",
        ),
        (
            {"target_quantity": float("nan")},
            r"the float at \$\['target_quantity'\] is not finite",
        ),
        ({"target_quantity": "\ud800"}, r"they have no canonical form"),
        ({"rate": Decimal("0.05")}, r"the value at \$\['rate'\] is not exactly"),
        ([{"a": {1, 2}}], r"the value at \$\[0\]\['a'\] is not exactly"),
    ],
)
def test_non_canonical_parameters_are_refused(parameters: object, problem: str) -> None:
    with pytest.raises(StrategyParametersBindingError, match=problem):
        strategy_parameters_hash(parameters)


def test_the_parameters_error_is_a_drift_value_error() -> None:
    from drift.errors import DriftError

    assert issubclass(StrategyParametersBindingError, DriftError)
    assert issubclass(StrategyParametersBindingError, ValueError)


# ==========================================================================
# The engine binds the parameters the strategy exposes
# ==========================================================================


def test_the_engine_refuses_a_strategy_running_other_parameters() -> None:
    engine = eng._engine()
    strategy = ParameterizedFixedTargetStrategy(FIVE)

    with pytest.raises(StrategyParametersBindingError, match=ENGINE_MISMATCH):
        _run_v2(engine, strategy, _v2_identity(engine, TEN))
    assert strategy.seen == []


def test_the_engine_refuses_a_v2_identity_for_a_strategy_without_parameters() -> None:
    engine = eng._engine()
    strategy = eng._buy_ten()
    assert not isinstance(strategy, ParameterizedStrategy)

    with pytest.raises(StrategyParametersBindingError, match=NO_PARAMETERS_SURFACE):
        _run_v2(engine, strategy, _v2_identity(engine, TEN))
    assert strategy.seen == []


def _equal_to_ten(exposed: object) -> bool:
    return exposed == TEN


def _hashes_as_ten(exposed: object) -> bool:
    return content_hash(exposed) == content_hash(TEN)


@pytest.mark.parametrize(
    ("forge", "deceives"),
    [
        (lambda: {"target_quantity": _EqualToEveryInt(5)}, _equal_to_ten),
        (lambda: {_KeyNamedLikeTheTarget("quantity"): 10}, _equal_to_ten),
        (lambda: _LyingDict(target_quantity=5), _hashes_as_ten),
        (_RepeatingMapping, _hashes_as_ten),
        (lambda: MappingProxyType(_RepeatingMapping()), _hashes_as_ten),
    ],
    ids=[
        "leaf-equal-to-every-value",
        "key-named-like-the-target",
        "dict-lying-about-its-storage",
        "mapping-naming-one-key-twice",
        "proxy-naming-one-key-twice",
    ],
)
def test_forged_exposed_parameters_cannot_fake_a_match(
    forge: Any, deceives: Any
) -> None:
    """Each forgery passes as TEN to Python equality or to a naive content hash.

    None of them holds TEN: the first two hold 5 and ``quantity``, the lying
    dict stores 5, and the repeating mapping answers 5 for the name before it
    answers 10. The engine refuses each before any session.
    """
    assert deceives(forge())
    engine = eng._engine()
    strategy = ParameterizedFixedTargetStrategy(TEN)
    strategy.parameters = forge()

    with pytest.raises(StrategyParametersBindingError, match=EXPOSED_NOT_CANONICAL):
        _run_v2(engine, strategy, _v2_identity(engine, TEN))
    assert strategy.seen == []


def _identity_of_a_parameters_hash_equal_to_every_text(
    engine: SessionEvaluatorEngine,
) -> EvaluationRunIdentityV2:
    """The honest TEN identity, its parameters hash a string equal to all."""
    honest = _v2_identity(engine, TEN)
    forged = EvaluationRunIdentityV2.model_construct(
        **(
            dict(honest)
            | {
                "strategy_parameters_hash": _TextEqualToEveryText(
                    honest.strategy_parameters_hash
                )
            }
        )
    )
    assert type(forged.strategy_parameters_hash) is _TextEqualToEveryText
    assert forged.strategy_parameters_hash == content_hash(FIVE)
    return forged


def test_an_identity_parameters_hash_equal_to_every_text_is_still_refused() -> None:
    """The engine rebuilds the identity canonically before comparing."""
    engine = eng._engine()
    strategy = ParameterizedFixedTargetStrategy(FIVE)

    with pytest.raises(StrategyParametersBindingError, match=ENGINE_MISMATCH):
        _run_v2(
            engine, strategy, _identity_of_a_parameters_hash_equal_to_every_text(engine)
        )
    assert strategy.seen == []


def test_the_binding_check_rebuilds_the_identity_it_is_handed() -> None:
    """Called directly, the public check still compares only exact text."""
    engine = eng._engine()
    forged = _identity_of_a_parameters_hash_equal_to_every_text(engine)

    with pytest.raises(StrategyParametersBindingError, match=ENGINE_MISMATCH):
        require_bound_strategy_parameters(
            forged, ParameterizedFixedTargetStrategy(FIVE)
        )
    require_bound_strategy_parameters(forged, ParameterizedFixedTargetStrategy(TEN))


def test_the_binding_check_never_reads_a_strategy_under_v1() -> None:
    _ParametersNeverRead.reads = 0
    engine = eng._engine()

    require_bound_strategy_parameters(
        _v1_identity(engine), _ParametersNeverRead(eng._buy_ten().targets)
    )
    require_bound_strategy_parameters(_v1_identity(engine), object())

    assert _ParametersNeverRead.reads == 0


def test_the_engine_binds_parameters_in_the_reconstructed_lane_too() -> None:
    from exploratory_decision_test_support import (
        JAN5,
        JAN6,
        SEC,
        ReconstructedTargetStrategy,
        bundle_of,
        reconstructed_engine,
        three_regular_sessions,
    )

    class _Parameterized(ReconstructedTargetStrategy):
        @property
        def strategy_parameters(self) -> ImmutableJSONValue:
            return FIVE

    engine = reconstructed_engine(bundle_of(three_regular_sessions()))
    strategy = _Parameterized({JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)})

    with pytest.raises(StrategyParametersBindingError, match=ENGINE_MISMATCH):
        _run_v2(engine, strategy, _v2_identity(engine, TEN))
    assert strategy.seen == []

    artifacts = _run_v2(engine, strategy, _v2_identity(engine, FIVE))
    assert type(artifacts.result.run_identity) is EvaluationRunIdentityV2
    assert artifacts.result.metrics.committed_fill_count == 1


# ==========================================================================
# The experiment runner binds the specification's parameters
# ==========================================================================


def _v2_context(
    engine: SessionEvaluatorEngine,
    strategy: object,
    identity: EvaluationRunIdentityV2,
    ledger: SQLiteLedger | None = None,
) -> Any:
    return dataclasses.replace(
        run_support._context(engine, ledger=ledger),
        strategy=cast(Any, strategy),
        run_identity=identity,
    )


def test_the_runner_records_a_v2_run_under_its_parameters(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    specification = run_support._specification()
    assert specification.parameters == TEN
    identity = _v2_identity(engine, TEN)

    run = execute_experiment_run(
        specification,
        _v2_context(engine, ParameterizedFixedTargetStrategy(TEN), identity, ledger),
    )

    assert run.status.value == "completed"
    assert run.parameters_hash == content_hash(specification.parameters)
    assert run.parameters_hash == identity.strategy_parameters_hash
    assert run_support._metric(run, "run_identity_hash") == identity.run_identity_hash
    assert len(ledger.verified_events()) == 1


def test_the_runner_refuses_a_specification_of_other_parameters(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    specification = run_support._specification().model_copy(update={"parameters": FIVE})
    strategy = ParameterizedFixedTargetStrategy(TEN)

    with pytest.raises(StrategyParametersBindingError, match=SPECIFICATION_MISMATCH):
        execute_experiment_run(
            specification,
            _v2_context(engine, strategy, _v2_identity(engine, TEN), ledger),
        )
    assert strategy.seen == []
    assert ledger.verified_events() == ()


def test_the_runner_refuses_a_running_strategy_of_other_parameters(
    tmp_path: Path,
) -> None:
    """Refused before the engine runs, never recorded as a FAILED run."""
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    strategy = ParameterizedFixedTargetStrategy(FIVE)

    with pytest.raises(StrategyParametersBindingError, match=ENGINE_MISMATCH):
        execute_experiment_run(
            run_support._specification(),
            _v2_context(engine, strategy, _v2_identity(engine, TEN), ledger),
        )
    assert strategy.seen == []
    assert ledger.verified_events() == ()


def test_the_runner_refuses_a_running_strategy_without_parameters(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    strategy = eng._buy_ten()

    with pytest.raises(StrategyParametersBindingError, match=NO_PARAMETERS_SURFACE):
        execute_experiment_run(
            run_support._specification(),
            _v2_context(engine, strategy, _v2_identity(engine, TEN), ledger),
        )
    assert strategy.seen == []
    assert ledger.verified_events() == ()


def test_the_runner_refuses_forged_specification_parameters(tmp_path: Path) -> None:
    """A leaf equal to every value cannot stand in for the declared one."""
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    specification = run_support._specification().model_copy(
        update={"parameters": {"target_quantity": _EqualToEveryInt(5)}}
    )
    assert specification.parameters == TEN
    strategy = ParameterizedFixedTargetStrategy(TEN)

    with pytest.raises(
        StrategyParametersBindingError, match=SPECIFICATION_NOT_CANONICAL
    ):
        execute_experiment_run(
            specification,
            _v2_context(engine, strategy, _v2_identity(engine, TEN), ledger),
        )
    assert strategy.seen == []
    assert ledger.verified_events() == ()


def test_the_runner_compares_the_specification_with_the_canonical_identity(
    tmp_path: Path,
) -> None:
    """A context identity whose parameters hash equals every text is rebuilt."""
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = eng._engine()
    specification = run_support._specification().model_copy(update={"parameters": FIVE})
    strategy = ParameterizedFixedTargetStrategy(FIVE)
    forged = _identity_of_a_parameters_hash_equal_to_every_text(engine)

    with pytest.raises(StrategyParametersBindingError, match=SPECIFICATION_MISMATCH):
        execute_experiment_run(
            specification, _v2_context(engine, strategy, forged, ledger)
        )
    assert strategy.seen == []
    assert ledger.verified_events() == ()


# ==========================================================================
# V1 is unchanged
# ==========================================================================


def test_the_v1_identity_schema_is_frozen() -> None:
    assert tuple(EvaluationRunIdentityV1.model_fields) == V1_IDENTITY_FIELDS
    assert (
        content_hash(EvaluationRunIdentityV1.model_json_schema())
        == V1_IDENTITY_SCHEMA_FINGERPRINT
    )


def test_the_v1_identity_hash_function_is_frozen() -> None:
    fields = _synthetic_identity_fields()
    draft = EvaluationRunIdentityV1.model_construct(
        run_identity_hash="0" * 64, **fields
    )

    assert evaluation_run_identity_hash(draft) == V1_SYNTHETIC_IDENTITY_HASH
    built = build_evaluation_run_identity(
        strategy_hash=H["1"],
        protocol_hash=H["2"],
        cost_model_hash=H["3"],
        admission=eng._admission(eng._bundle()),
        bundle=eng._bundle(),
        evaluator_evidence_hash=H["6"],
        code_version_hash=H["7"],
        environment_closure_hash=H["8"],
    )
    assert type(built) is EvaluationRunIdentityV1
    assert built.run_identity_hash == evaluation_run_identity_hash(built)


def test_a_v1_run_never_reads_strategy_parameters() -> None:
    """V1 runs are byte-identical and never consult the parameters surface."""
    _ParametersNeverRead.reads = 0
    engine = eng._engine()
    strategy = _ParametersNeverRead(eng._buy_ten().targets)
    assert isinstance(strategy, ParameterizedStrategy)
    assert isinstance(strategy, RuntimeStrategy)

    artifacts = engine.run(strategy=strategy, run_identity=_v1_identity(engine))

    assert _ParametersNeverRead.reads == 0
    assert type(artifacts.result.run_identity) is EvaluationRunIdentityV1
    assert artifacts.trace.trace_hash == REALIZED_TRACE_HASH_SINCE_ISSUE_63_STAGE_2
    assert artifacts.result.result_hash == REALIZED_RESULT_HASH_SINCE_ISSUE_63_STAGE_2


def test_a_v1_experiment_run_never_reads_strategy_parameters() -> None:
    _ParametersNeverRead.reads = 0
    engine = eng._engine()
    specification = run_support._specification()
    context = dataclasses.replace(
        run_support._context(engine),
        strategy=_ParametersNeverRead(eng._buy_ten().targets),
    )

    run = execute_experiment_run(specification, context)

    assert _ParametersNeverRead.reads == 0
    assert run.status.value == "completed"
    assert run.parameters_hash == content_hash(specification.parameters)
    assert (
        run_support._metric(run, "result_hash")
        == REALIZED_RESULT_HASH_SINCE_ISSUE_63_STAGE_2
    )


def test_a_reconstructed_v1_run_never_reads_strategy_parameters() -> None:
    from exploratory_decision_test_support import (
        JAN5,
        JAN6,
        SEC,
        ReconstructedTargetStrategy,
        bundle_of,
        reconstructed_engine,
        run_engine,
        three_regular_sessions,
    )

    class _NeverRead(ReconstructedTargetStrategy):
        reads = 0

        @property
        def strategy_parameters(self) -> ImmutableJSONValue:
            type(self).reads += 1
            raise AssertionError("a V1 run read the strategy parameters")

    artifacts = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        _NeverRead({JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)}),
    )

    assert _NeverRead.reads == 0
    assert type(artifacts.result.run_identity) is EvaluationRunIdentityV1
    assert (
        artifacts.result.result_hash == RECONSTRUCTED_RESULT_HASH_SINCE_ISSUE_63_STAGE_2
    )
