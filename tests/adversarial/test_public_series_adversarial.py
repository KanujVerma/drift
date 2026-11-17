"""Adversarial checks for the data-quality report and the public rate series.

Every test here is an attack on a boundary rather than a happy path: the
offline import boundary of the four new modules, the exploratory-only lane,
the rights record a series cannot be built without, and the registration of
the four files in the source-capability guard. Fixture bytes are synthetic and
inline; no real H.15 file is read and nothing is downloaded.
"""

import ast
import importlib.util
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
from pydantic import ValidationError

from drift.adapters.fed_h15 import (
    H15NativeDocument,
    H15NativeRow,
    H15ParseError,
    build_public_daily_rate_series,
    parse_h15_csv,
    quality_points,
)
from drift.domain.data_quality import (
    DataQualityCheck,
    DataQualityInputError,
    seal_data_quality_policy,
)
from drift.domain.dataset_validation import ValidationResult
from drift.domain.public_series import (
    PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES,
    PUBLIC_SERIES_REQUIRED_LIMITATIONS,
    PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,
    PublicationLagPolicyV1,
    PublicDailyRateSeriesV1,
    PublicSeriesRightsRecordV1,
    public_daily_rate_series_hash,
    seal_public_daily_rate_series,
    seal_public_series_rights_record,
    seal_publication_lag_policy,
)
from drift.markets.data_quality import assess_daily_values, require_passing

REPO_ROOT = Path(__file__).resolve().parents[2]

DOMAIN_AND_MARKETS_PATHS = (
    "src/drift/domain/data_quality.py",
    "src/drift/domain/public_series.py",
    "src/drift/markets/data_quality.py",
)
ADAPTER_PATH = "src/drift/adapters/fed_h15.py"
NEW_SOURCE_PATHS = (ADAPTER_PATH, *DOMAIN_AND_MARKETS_PATHS)
NEW_MODULE_NAMES = (
    "drift.adapters.fed_h15",
    "drift.domain.data_quality",
    "drift.domain.public_series",
    "drift.markets.data_quality",
)

#: Import roots that would let a module reach a transport, another program, a
#: file, or the environment. The four modules take caller-supplied bytes only.
REFUSED_IMPORT_ROOTS = frozenset(
    {
        "asyncio",
        "boto3",
        "ctypes",
        "ftplib",
        "http",
        "httpx",
        "importlib",
        "io",
        "multiprocessing",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "urllib",
        "webbrowser",
        "zoneinfo",
    }
)
REFUSED_BUILTIN_CALLS = frozenset(
    {"__import__", "compile", "eval", "exec", "getattr", "input", "open", "setattr"}
)

SERIES_A = "SYNTH_A.B"
#: Synthetic bytes in the H.15 header layout. Not Federal Reserve data.
SYNTHETIC_H15 = (
    b'"Series Description","Synthetic rate A (not real data)"\n'
    b'"Unit:","Percent:_Per_Year"\n'
    b'"Multiplier:","1"\n'
    b'"Currency:","NA"\n'
    b'"Unique Identifier: ","H15/H15/SYNTH_A.B"\n'
    b'"Time Period","SYNTH_A.B"\n'
    b"2024-01-03,5.25\n"
    b"2024-01-04,5.26\n"
    b"2024-01-05,ND\n"
    b"2024-01-08,5.28\n"
)


def _imported_modules(relative: str) -> tuple[str, ...]:
    tree = ast.parse((REPO_ROOT / relative).read_bytes(), filename=relative)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in {relative}"
            assert node.module is not None
            names.add(node.module)
    return tuple(sorted(names))


def _lag() -> PublicationLagPolicyV1:
    return seal_publication_lag_policy(
        policy_id="synthetic-next-weekday-2115z",
        release_lag_weekdays=1,
        release_utc_minute_of_day=21 * 60 + 15,
        non_release_dates=(),
    )


def _rights(series_identifier: str = SERIES_A) -> PublicSeriesRightsRecordV1:
    return seal_public_series_rights_record(
        publisher_legal_name="Synthetic Publisher (not a real record)",
        product="Synthetic daily rates",
        series_identifier=series_identifier,
        rights_basis="us_federal_government_work_public_domain",
        terms_evidence_sha256="e" * 64,
        recorded_by="synthetic-test-recorder",
        recorded_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
        limitations=(PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,),
    )


def _document(data: bytes = SYNTHETIC_H15) -> H15NativeDocument:
    return parse_h15_csv(data, expected_sha256=sha256(data).hexdigest(), max_bytes=4096)


def _series() -> PublicDailyRateSeriesV1:
    return build_public_daily_rate_series(
        _document(), series_identifier=SERIES_A, lag_policy=_lag(), rights=_rights()
    )


def _load_guard() -> ModuleType:
    """Load the source-capability guard module without importing a package."""
    path = REPO_ROOT / "tests/integration/test_m1e_compatibility.py"
    spec = importlib.util.spec_from_file_location("_dq_capability_guard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- the offline import boundary -----------------------------------------


@pytest.mark.parametrize("relative", NEW_SOURCE_PATHS)
def test_no_new_module_imports_a_transport_program_or_file_module(
    relative: str,
) -> None:
    imported = _imported_modules(relative)

    assert imported, "the import scan found nothing to inspect"
    offending = [
        name for name in imported if name.split(".")[0] in REFUSED_IMPORT_ROOTS
    ]
    assert offending == []


@pytest.mark.parametrize("relative", NEW_SOURCE_PATHS)
def test_no_new_module_imports_the_evaluator(relative: str) -> None:
    offending = [
        name
        for name in _imported_modules(relative)
        if name == "drift.evaluator"
        or name.startswith("drift.evaluator.")
        or name.startswith("drift.domain.evaluator_")
    ]

    assert offending == []


@pytest.mark.parametrize("relative", DOMAIN_AND_MARKETS_PATHS)
def test_domain_and_markets_modules_import_no_adapter(relative: str) -> None:
    offending = [
        name
        for name in _imported_modules(relative)
        if name == "drift.adapters" or name.startswith("drift.adapters.")
    ]

    assert offending == []
    # The control: the adapter is the one module allowed to depend inward.
    adapter_imports = _imported_modules(ADAPTER_PATH)
    assert "drift.markets.data_quality" in adapter_imports
    assert "drift.domain.public_series" in adapter_imports


@pytest.mark.parametrize("relative", NEW_SOURCE_PATHS)
def test_no_new_module_calls_a_file_or_dynamic_builtin(relative: str) -> None:
    tree = ast.parse((REPO_ROOT / relative).read_bytes(), filename=relative)
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert len(calls) >= 10, "the call scan found nothing to inspect"
    assert sorted(set(calls) & REFUSED_BUILTIN_CALLS) == []


def test_importing_the_new_modules_loads_no_evaluator_or_vendor_module() -> None:
    """Checked in a fresh interpreter, so this run's own imports cannot hide it."""
    program = (
        "import sys\n"
        + "".join(f"import {name}\n" for name in NEW_MODULE_NAMES)
        + "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('drift'))))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    loaded = completed.stdout.split()
    assert set(NEW_MODULE_NAMES) <= set(loaded)
    offending = [
        name
        for name in loaded
        if name.startswith("drift.evaluator")
        or name.startswith("drift.domain.evaluator_")
        or name in {"drift.adapters.alpaca_exploratory", "drift.adapters.robinhood"}
        or name.startswith("drift.adapters.robinhood.")
    ]
    assert offending == []


# --- the capability guard registration -----------------------------------


def test_the_registered_guard_scan_covers_exactly_the_four_files() -> None:
    guard = _load_guard()

    registered = guard.DATA_QUALITY_PUBLIC_SERIES_SOURCE_PATHS
    assert registered == frozenset(NEW_SOURCE_PATHS)
    assert registered <= guard.INERT_SOURCE_PATHS
    assert registered <= guard.SCANNED_AS_PRODUCTION_PATHS
    for relative in NEW_SOURCE_PATHS:
        assert (REPO_ROOT / relative).is_file()
        guard._assert_m1e_source_file_allowed(relative)
    for unknown in (
        "src/drift/adapters/fed_h15_extra.py",
        "src/drift/domain/public_series_extra.py",
        "./src/drift/adapters/fed_h15.py",
    ):
        assert unknown not in guard.INERT_SOURCE_PATHS
        with pytest.raises(AssertionError, match="unregistered source"):
            guard._assert_m1e_source_file_allowed(unknown)


@pytest.mark.parametrize("relative", NEW_SOURCE_PATHS)
@pytest.mark.parametrize(
    "injection",
    (
        b"import socket\n",
        b"import urllib.request\n",
        b"import subprocess\nsubprocess.run(['true'])\n",
        b"import os\nos.getenv('SECRET')\n",
        b"import os\nos.environ['SECRET']\n",
        b"eval('1 + 1')\n",
        b"def fetch_over_network() -> None:\n    return None\n",
        b"def read_credential() -> None:\n    return None\n",
        b"def run_backtest() -> None:\n    return None\n",
    ),
)
def test_the_guard_scan_of_each_file_is_not_vacuous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, injection: bytes
) -> None:
    """The real file passes; the same bytes plus one capability are refused."""
    guard = _load_guard()
    original = (REPO_ROOT / relative).read_bytes()
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)

    path.write_bytes(original)
    guard._assert_m1e_source_file_allowed(relative)
    path.write_bytes(original + b"\n\n" + injection)
    with pytest.raises(AssertionError):
        guard._assert_m1e_source_file_allowed(relative)


# --- the rights record ----------------------------------------------------


def test_the_series_cannot_be_built_without_a_rights_record() -> None:
    document = _document()

    with pytest.raises(TypeError, match="rights"):
        build_public_daily_rate_series(  # type: ignore[call-arg]
            document, series_identifier=SERIES_A, lag_policy=_lag()
        )
    for not_a_record in (None, _rights().record_hash, dict(_rights()), _lag()):
        with pytest.raises(H15ParseError, match="h15_rights_record_invalid"):
            build_public_daily_rate_series(
                document,
                series_identifier=SERIES_A,
                lag_policy=_lag(),
                rights=not_a_record,  # type: ignore[arg-type]
            )


def test_a_rights_record_for_another_series_is_refused() -> None:
    with pytest.raises(H15ParseError, match="h15_rights_record_series_mismatch"):
        build_public_daily_rate_series(
            _document(),
            series_identifier=SERIES_A,
            lag_policy=_lag(),
            rights=_rights("SYNTH_B.B"),
        )


def test_a_forged_rights_record_is_revalidated_before_use() -> None:
    eligible = PublicSeriesRightsRecordV1.model_construct(
        **(dict(_rights()) | {"promotion_eligible": True})
    )
    retargeted = PublicSeriesRightsRecordV1.model_construct(
        **(dict(_rights("SYNTH_B.B")) | {"series_identifier": SERIES_A})
    )

    for forged in (eligible, retargeted):
        with pytest.raises(H15ParseError, match="h15_rights_record_invalid"):
            build_public_daily_rate_series(
                _document(),
                series_identifier=SERIES_A,
                lag_policy=_lag(),
                rights=forged,
            )


def test_a_forged_lag_policy_is_revalidated_before_use() -> None:
    same_day = PublicationLagPolicyV1.model_construct(
        **(dict(_lag()) | {"release_lag_weekdays": 0})
    )

    with pytest.raises(H15ParseError, match="h15_lag_policy_invalid"):
        build_public_daily_rate_series(
            _document(),
            series_identifier=SERIES_A,
            lag_policy=same_day,
            rights=_rights(),
        )
    with pytest.raises(H15ParseError, match="h15_lag_policy_invalid"):
        build_public_daily_rate_series(
            _document(),
            series_identifier=SERIES_A,
            lag_policy=None,  # type: ignore[arg-type]
            rights=_rights(),
        )


# --- the exploratory lane -------------------------------------------------


def test_the_types_can_only_state_the_exploratory_lane() -> None:
    series_lane = PublicDailyRateSeriesV1.model_fields["lane"].annotation
    rights_lane = PublicSeriesRightsRecordV1.model_fields["lane"].annotation
    eligibility = PublicSeriesRightsRecordV1.model_fields["promotion_eligible"]
    basis = PublicationLagPolicyV1.model_fields["basis"].annotation

    assert get_args(series_lane) == ("exploratory",)
    assert get_args(rights_lane) == ("exploratory",)
    assert get_args(eligibility.annotation) == (False,)
    assert get_args(basis) == ("modeled_rule",)
    assert "promotion_eligible" not in PublicDailyRateSeriesV1.model_fields


def test_a_built_series_cannot_drop_a_limitation_or_change_lane() -> None:
    series = _series()
    assert series.acknowledged_limitations == PUBLIC_SERIES_REQUIRED_LIMITATIONS

    def resealed(**update: object) -> PublicDailyRateSeriesV1:
        draft = PublicDailyRateSeriesV1.model_construct(**(dict(series) | update))
        return PublicDailyRateSeriesV1.model_validate(
            dict(draft) | {"series_hash": public_daily_rate_series_hash(draft)}
        )

    assert resealed() == series
    with pytest.raises(ValidationError, match="public_series_limitations_incomp"):
        resealed(acknowledged_limitations=PUBLIC_SERIES_REQUIRED_LIMITATIONS[:2])
    with pytest.raises(ValidationError, match="exploratory"):
        resealed(lane="promotion")


def test_a_forged_series_is_revalidated_before_quality_points() -> None:
    series = _series()
    forged = PublicDailyRateSeriesV1.model_construct(
        **(dict(series) | {"points": tuple(reversed(series.points))})
    )

    assert len(quality_points(series)) == 4
    with pytest.raises(H15ParseError, match="h15_series_invalid"):
        quality_points(forged)
    with pytest.raises(H15ParseError, match="h15_series_invalid"):
        quality_points(None)  # type: ignore[arg-type]


# --- the parser boundary --------------------------------------------------


def test_a_hand_built_document_states_its_own_digest_unchecked() -> None:
    """Known limit, pinned: only ``parse_h15_csv`` ties the digest to bytes."""
    parsed = _document()
    invented = "9" * 64
    hand_built = H15NativeDocument(
        source_sha256=invented,
        source_byte_size=1,
        identifier_label=parsed.identifier_label,
        columns=parsed.columns,
        rows=parsed.rows,
    )

    series = build_public_daily_rate_series(
        hand_built, series_identifier=SERIES_A, lag_policy=_lag(), rights=_rights()
    )

    assert (series.source_sha256, series.source_byte_size) == (invented, 1)
    assert series.source_sha256 != parsed.source_sha256
    assert series.points == _series().points
    unauthenticated = PUBLIC_SERIES_LIMITATION_UNAUTHENTICATED_BYTES
    assert unauthenticated in series.acknowledged_limitations


def test_only_the_adapter_path_requires_a_rights_record_object() -> None:
    """Known limit, pinned: the domain seal accepts any well-formed hash."""
    series = _series()
    invented = "9" * 64

    unbacked = seal_public_daily_rate_series(
        source_id=series.source_id,
        series_identifier=series.series_identifier,
        description=series.description,
        unit=series.unit,
        source_sha256=series.source_sha256,
        source_byte_size=series.source_byte_size,
        points=series.points,
        lag_policy=series.lag_policy,
        rights_record_hash=invented,
        acknowledged_limitations=series.acknowledged_limitations,
    )

    assert unbacked.rights_record_hash == invented
    assert unbacked.rights_record_hash != _rights().record_hash
    assert unbacked.lane == "exploratory"


def test_a_hand_built_column_with_another_unit_multiplier_or_currency_is_refused() -> (
    None
):
    parsed = _document()
    (column,) = parsed.columns
    for field, value, code in (
        ("unit", "Index", "h15_unit_unexpected"),
        ("multiplier", "100", "h15_multiplier_unexpected"),
        ("currency", "USD", "h15_currency_unexpected"),
    ):
        forged = H15NativeDocument(
            source_sha256=parsed.source_sha256,
            source_byte_size=parsed.source_byte_size,
            identifier_label=parsed.identifier_label,
            columns=(replace(column, **{field: value}),),
            rows=parsed.rows,
        )

        with pytest.raises(H15ParseError, match=code):
            build_public_daily_rate_series(
                forged, series_identifier=SERIES_A, lag_policy=_lag(), rights=_rights()
            )


def test_a_hand_built_document_cannot_smuggle_a_cell_form_the_parser_refuses() -> None:
    """The builder classifies every cell again. It does not check the digest."""
    parsed = _document()
    for smuggled in ("1e-2", "NaN", "5.25 ", "N/A"):
        forged = H15NativeDocument(
            source_sha256=parsed.source_sha256,
            source_byte_size=parsed.source_byte_size,
            identifier_label=parsed.identifier_label,
            columns=parsed.columns,
            rows=(
                H15NativeRow(
                    line_number=7, observed_on=date(2024, 1, 3), cells=(smuggled,)
                ),
                *parsed.rows[1:],
            ),
        )

        with pytest.raises(H15ParseError, match="h15_cell_invalid"):
            build_public_daily_rate_series(
                forged, series_identifier=SERIES_A, lag_policy=_lag(), rights=_rights()
            )


def test_a_hand_built_document_with_a_bad_shape_is_refused() -> None:
    parsed = _document()
    ragged = H15NativeDocument(
        source_sha256=parsed.source_sha256,
        source_byte_size=parsed.source_byte_size,
        identifier_label=parsed.identifier_label,
        columns=parsed.columns,
        rows=(
            H15NativeRow(line_number=7, observed_on=date(2024, 1, 3), cells=()),
            *parsed.rows[1:],
        ),
    )

    with pytest.raises(H15ParseError, match="h15_document_invalid"):
        build_public_daily_rate_series(
            ragged, series_identifier=SERIES_A, lag_policy=_lag(), rights=_rights()
        )
    with pytest.raises(H15ParseError, match="h15_document_invalid"):
        build_public_daily_rate_series(
            SYNTHETIC_H15,  # type: ignore[arg-type]
            series_identifier=SERIES_A,
            lag_policy=_lag(),
            rights=_rights(),
        )


def test_a_hand_built_document_with_a_third_label_spelling_is_refused() -> None:
    parsed = _document()
    assert parsed.identifier_label == "Unique Identifier: "

    for accepted in ("Unique Identifier: ", "Unique Identifier:"):
        series = build_public_daily_rate_series(
            replace(parsed, identifier_label=accepted),
            series_identifier=SERIES_A,
            lag_policy=_lag(),
            rights=_rights(),
        )
        assert series.points == _series().points
    for refused in ("Unique Identifier:  ", "unique identifier:", "Unique Identifier"):
        with pytest.raises(H15ParseError, match="h15_document_invalid"):
            build_public_daily_rate_series(
                replace(parsed, identifier_label=refused),
                series_identifier=SERIES_A,
                lag_policy=_lag(),
                rights=_rights(),
            )


def test_the_digest_binds_every_byte_of_the_input() -> None:
    digest = sha256(SYNTHETIC_H15).hexdigest()
    edited = SYNTHETIC_H15.replace(b"5.25", b"5.35")
    padded = SYNTHETIC_H15 + b" "

    assert parse_h15_csv(SYNTHETIC_H15, expected_sha256=digest, max_bytes=4096)
    for other in (edited, padded, SYNTHETIC_H15[:-1]):
        with pytest.raises(H15ParseError, match="h15_sha256_mismatch"):
            parse_h15_csv(other, expected_sha256=digest, max_bytes=4096)


# --- the quality gate -----------------------------------------------------


def test_an_unevaluated_hard_check_fails_the_gate_for_a_real_series() -> None:
    series = _series()
    policy = seal_data_quality_policy(
        policy_id="synthetic-daily-rate-policy",
        lower_bound=Decimal("-1"),
        upper_bound=Decimal("25"),
        max_abs_jump=Decimal("1"),
        jump_mode="absolute",
        max_stale_run=5,
        max_missing_run=1,
        hard_checks=(DataQualityCheck.CALENDAR_GAP,),
    )

    without_calendar = assess_daily_values(
        quality_points(series),
        subject_kind="public_daily_series",
        subject_hash=series.series_hash,
        source_sha256=series.source_sha256,
        policy=policy,
        expected_dates=None,
        cutoff=None,
    )
    with_calendar = assess_daily_values(
        quality_points(series),
        subject_kind="public_daily_series",
        subject_hash=series.series_hash,
        source_sha256=series.source_sha256,
        policy=policy,
        expected_dates=tuple(point.observed_on for point in series.points),
        cutoff=None,
    )

    assert without_calendar.result is ValidationResult.FAIL
    assert with_calendar.result is ValidationResult.PASS
    with pytest.raises(ValueError, match="calendar_gap=not_evaluated"):
        require_passing(without_calendar)
    require_passing(with_calendar)


def test_a_look_ahead_cutoff_is_reported_for_a_real_series() -> None:
    series = _series()
    last = series.points[-1]
    policy = seal_data_quality_policy(
        policy_id="synthetic-daily-rate-policy",
        lower_bound=Decimal("-1"),
        upper_bound=Decimal("25"),
        max_abs_jump=Decimal("1"),
        jump_mode="absolute",
        max_stale_run=5,
        max_missing_run=1,
        hard_checks=(DataQualityCheck.AVAILABILITY_VIOLATION,),
    )

    report = assess_daily_values(
        quality_points(series),
        subject_kind="public_daily_series",
        subject_hash=series.series_hash,
        source_sha256=series.source_sha256,
        policy=policy,
        expected_dates=None,
        cutoff=datetime(2024, 1, 8, 23, 59, tzinfo=UTC),
    )

    assert last.available_at == datetime(2024, 1, 9, 21, 15, tzinfo=UTC)
    assert report.result is ValidationResult.FAIL
    (finding,) = report.findings
    assert finding.code == "available_after_cutoff"
    assert (finding.first_date, finding.last_date) == (last.observed_on,) * 2
    seen = series.value_as_of(datetime(2024, 1, 8, 23, 59, tzinfo=UTC))
    assert seen is not None
    assert (seen.observed_on, seen.state) == (date(2024, 1, 5), "missing")


def test_the_gate_refuses_a_subject_it_cannot_name() -> None:
    series = _series()
    policy = seal_data_quality_policy(
        policy_id="synthetic-daily-rate-policy",
        lower_bound=Decimal("-1"),
        upper_bound=Decimal("25"),
        max_abs_jump=Decimal("1"),
        jump_mode="absolute",
        max_stale_run=5,
        max_missing_run=1,
        hard_checks=(),
    )

    with pytest.raises(ValidationError):
        assess_daily_values(
            quality_points(series),
            subject_kind="public_daily_series",
            subject_hash="not-a-hash",
            source_sha256=series.source_sha256,
            policy=policy,
            expected_dates=None,
            cutoff=None,
        )
    with pytest.raises(ValidationError):
        assess_daily_values(
            quality_points(series),
            subject_kind="promotion_series",  # type: ignore[arg-type]
            subject_hash=series.series_hash,
            source_sha256=series.source_sha256,
            policy=policy,
            expected_dates=None,
            cutoff=None,
        )
    with pytest.raises(DataQualityInputError, match="data_quality_policy_invalid"):
        assess_daily_values(
            quality_points(series),
            subject_kind="public_daily_series",
            subject_hash=series.series_hash,
            source_sha256=series.source_sha256,
            policy=None,  # type: ignore[arg-type]
            expected_dates=None,
            cutoff=None,
        )
