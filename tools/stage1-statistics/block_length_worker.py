"""Reference worker for automatic block length estimation using arch 8.0.0.

Receives strict JSON with decimal return series, computes Patton-Politis-White
stationary block length for B, R, and B-minus-R series, and returns exact results.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import warnings
from decimal import Decimal
from typing import Any

import numpy as np


def compute_worker_source_hash() -> str:
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_block_length_worker(input_data: dict[str, Any]) -> dict[str, Any]:
    schema = input_data.get("schema_version")
    if schema != "drift-stage1-block-length-input/1":
        raise ValueError(f"UNSUPPORTED_INPUT_SCHEMA: {schema}")

    b_strs = input_data.get("b_returns")
    r_strs = input_data.get("r_returns")
    diff_strs = input_data.get("difference_returns")
    sessions = input_data.get("sessions")

    if not b_strs or not r_strs or not diff_strs or not sessions:
        raise ValueError("MISSING_RETURN_SERIES_OR_SESSIONS")

    n = len(sessions)
    if len(b_strs) != n or len(r_strs) != n or len(diff_strs) != n:
        raise ValueError("SERIES_LENGTH_MISMATCH")

    # Validate difference array against source decimals exactly
    for i in range(n):
        b_dec = Decimal(b_strs[i])
        r_dec = Decimal(r_strs[i])
        diff_dec = Decimal(diff_strs[i])
        if diff_dec != (b_dec - r_dec):
            raise ValueError(
                f"DIFFERENCE_RETURN_MISMATCH_AT_INDEX_{i}: "
                f"expected {b_dec - r_dec}, got {diff_dec}"
            )

    # Convert once to binary64 numpy array, refusing nonfinite
    try:
        b_arr = np.array([float(s) for s in b_strs], dtype=np.float64)
        r_arr = np.array([float(s) for s in r_strs], dtype=np.float64)
        diff_arr = np.array([float(s) for s in diff_strs], dtype=np.float64)
    except Exception as e:
        raise ValueError(f"FLOAT_CONVERSION_FAILED: {e}") from e

    is_finite = (
        np.all(np.isfinite(b_arr))
        and np.all(np.isfinite(r_arr))
        and np.all(np.isfinite(diff_arr))
    )
    if not is_finite:
        raise ValueError("NON_FINITE_FLOAT_ENCOUNTERED")

    import arch
    from arch.bootstrap import optimal_block_length

    series_map = {
        "b_returns": b_arr,
        "r_returns": r_arr,
        "difference_returns": diff_arr,
    }

    series_results: dict[str, Any] = {}
    diagnostics: list[str] = []
    finite_stationary_values: list[float] = []

    for name, arr in series_map.items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                res_df = optimal_block_length(arr)
                stat_val = float(res_df.loc[0, "stationary"])
                if np.isfinite(stat_val):
                    series_results[name] = {
                        "stationary": stat_val,
                        "status": "FINITE",
                    }
                    finite_stationary_values.append(stat_val)
                else:
                    series_results[name] = {
                        "stationary": None,
                        "status": "UNDEFINED_NON_FINITE",
                    }
            except Exception as e:
                series_results[name] = {
                    "stationary": None,
                    "status": f"ERROR: {e}",
                }

            for w in caught:
                diagnostics.append(f"{name}: {w.category.__name__}: {w.message}")

    aggregated_b: int | None = None
    if finite_stationary_values:
        max_val = max(finite_stationary_values)
        aggregated_b = max(1, math.ceil(max_val))

    raw_input_bytes = json.dumps(input_data, sort_keys=True).encode("utf-8")
    input_hash = hashlib.sha256(raw_input_bytes).hexdigest()

    return {
        "schema_version": "drift-stage1-block-length-output/1",
        "input_hash": input_hash,
        "series_results": series_results,
        "aggregated_block_length": aggregated_b,
        "diagnostics": diagnostics,
        "runtime_identity": sys.version,
        "package_identity": f"arch=={arch.__version__}",
        "worker_source_hash": compute_worker_source_hash(),
    }


def main() -> None:
    raw_in = sys.stdin.read()
    if not raw_in:
        sys.exit("No input provided on stdin")
    input_data = json.loads(raw_in)
    out_data = run_block_length_worker(input_data)
    sys.stdout.write(json.dumps(out_data, indent=2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
