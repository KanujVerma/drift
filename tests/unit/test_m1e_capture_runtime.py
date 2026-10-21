"""Synthetic, side-effect-free checks of measured M1e interpreter identity (#52)."""

import platform
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import capture_m1e_environment as capture


@pytest.fixture
def measured(tmp_path: Path) -> capture._RuntimeObservation:
    interpreter = tmp_path / "python3.14"
    interpreter.write_bytes(b"synthetic-runtime-file")
    return capture._RuntimeObservation(
        implementation="cpython",
        version="3.14.6",
        build="3.14.6 (synthetic build; not an original distribution attestation)",
        executable=str(interpreter),
        operating_system="Darwin",
        machine="arm64",
    )


def test_current_observation_reads_actual_running_interpreter() -> None:
    result = capture._current_runtime_observation()
    release = sys.version_info
    assert result.implementation == sys.implementation.name
    assert result.version == f"{release.major}.{release.minor}.{release.micro}"
    assert result.build == sys.version.replace("\n", " ").strip()
    assert result.executable == sys.executable
    assert result.operating_system == platform.system()
    assert result.machine == platform.machine()


def test_exact_host_and_repo_pin_produce_measured_runtime(
    measured: capture._RuntimeObservation,
) -> None:
    runtime = capture._validated_runtime_identity(
        observed=measured,
        pinned_version="3.14.6",
        stdlib_hash="a" * 64,
        distribution_hash="b" * 64,
    )
    assert runtime.implementation == "cpython"
    assert runtime.version == "3.14.6"
    assert runtime.build == measured.build
    assert runtime.executable == str(Path(measured.executable).resolve())
    assert runtime.standard_library_inventory_hash == "a" * 64
    assert runtime.distribution_artifact_hash == "b" * 64
    assert runtime.native_library_links == ()


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"version": "3.14.5"}, "M1E_RUNTIME_PIN_MISMATCH"),
        ({"implementation": "pypy"}, "M1E_RUNTIME_PIN_MISMATCH"),
        ({"operating_system": "Linux"}, "M1E_UNSUPPORTED_CAPTURE_PLATFORM"),
        ({"machine": "x86_64"}, "M1E_UNSUPPORTED_CAPTURE_PLATFORM"),
        ({"build": ""}, "M1E_RUNTIME_BUILD_UNAVAILABLE"),
        ({"executable": ""}, "M1E_RUNTIME_EXECUTABLE_UNAVAILABLE"),
        ({"executable": "python"}, "M1E_RUNTIME_EXECUTABLE_UNVERIFIED"),
    ],
)
def test_stale_fake_or_wrong_platform_cannot_claim_m1e_closure(
    measured: capture._RuntimeObservation,
    changed: dict[str, str],
    reason: str,
) -> None:
    forged = replace(measured, **changed)
    with pytest.raises(ValueError, match=reason):
        capture._validated_runtime_identity(
            observed=forged,
            pinned_version="3.14.6",
            stdlib_hash="a" * 64,
            distribution_hash="b" * 64,
        )


def test_absent_interpreter_file_is_not_an_original_capture(
    measured: capture._RuntimeObservation,
    tmp_path: Path,
) -> None:
    bad = replace(measured, executable=str(tmp_path / "not-present"))
    with pytest.raises(ValueError, match="M1E_RUNTIME_EXECUTABLE_UNVERIFIED"):
        capture._validated_runtime_identity(
            observed=bad,
            pinned_version="3.14.6",
            stdlib_hash="a" * 64,
            distribution_hash="b" * 64,
        )


@pytest.mark.parametrize("pin", ["", "3.14", "3.14.6.0", "3.14.5\n3.14.6", "x"])
def test_invalid_repository_pin_is_not_guessed(
    measured: capture._RuntimeObservation, pin: str
) -> None:
    with pytest.raises(ValueError, match="M1E_INVALID_PYTHON_PIN"):
        capture._validated_runtime_identity(
            observed=measured,
            pinned_version=pin,
            stdlib_hash="a" * 64,
            distribution_hash="b" * 64,
        )


def test_capture_path_reads_repo_pin_before_identity(
    measured: capture._RuntimeObservation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "_current_runtime_observation", lambda: measured)
    runtime = capture._measure_pinned_runtime(
        stdlib_hash="c" * 64, distribution_hash="d" * 64
    )
    pinned = (
        Path(capture.__file__).resolve().parents[1] / ".python-version"
    ).read_text(encoding="utf-8").strip()
    assert pinned == "3.14.6"
    assert runtime.version == pinned


def test_staging_runtime_does_not_override_measured_host(
    measured: capture._RuntimeObservation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capture, "_current_runtime_observation", lambda: replace(measured, version="3.14.5")
    )
    with pytest.raises(ValueError, match="M1E_RUNTIME_PIN_MISMATCH"):
        capture._measure_pinned_runtime(
            stdlib_hash="a" * 64, distribution_hash="b" * 64
        )
