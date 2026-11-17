# Data-quality report and public daily rate series

Status: first slice. Offline only, exploratory lane only. It changes nothing
under `src/drift/evaluator/` and nothing here is promotion-grade evidence.

This note describes what the slice adds, what it refuses, and what it does not
prove. Read the limitations before relying on any output.

## What it adds

| Module | Role |
|---|---|
| [`src/drift/domain/data_quality.py`](../../src/drift/domain/data_quality.py) | Typed quality policy, findings, per-check results, report, hashes, errors |
| [`src/drift/markets/data_quality.py`](../../src/drift/markets/data_quality.py) | `assess_daily_values` and `require_passing` |
| [`src/drift/domain/public_series.py`](../../src/drift/domain/public_series.py) | Rights record, publication-lag policy, rate point, rate series |
| [`src/drift/adapters/fed_h15.py`](../../src/drift/adapters/fed_h15.py) | Offline parser for Federal Reserve H.15 CSV bytes |

Types live in `domain/`, checks in `markets/`, and the publisher-specific parser
in `adapters/`. `domain/` and `markets/` do not import `drift.adapters`, and
none of the four modules imports `drift.evaluator`, a transport module, a
process module, a file module or the environment. The four files are registered
by exact path in `tests/integration/test_m1e_compatibility.py`, so the
source-capability guard scans the real files.

## The path from bytes to a gate

1. The caller obtains H.15 CSV bytes by its own means and states their SHA-256.
   Nothing in this slice downloads anything.
2. `parse_h15_csv(data, expected_sha256=..., max_bytes=...)` checks the size and
   the digest before decoding, then returns the header columns and the data
   rows in source order with line numbers.
3. `build_public_daily_rate_series(document, series_identifier=...,
   lag_policy=..., rights=...)` builds one `PublicDailyRateSeriesV1`. A
   `PublicSeriesRightsRecordV1` for exactly that series is required.
4. `quality_points(series)` turns the series into `DatedValue` points.
5. `assess_daily_values(points, ...)` returns a `DataQualityReportV1`.
6. `require_passing(report)` raises `DataQualityError`, carrying the report,
   unless the report is valid and passed.

`series.value_as_of(cutoff)` returns the latest point whose modeled
availability is not after the cutoff. A missing or unpublished date is returned
as it is, with no value. An earlier value is never carried forward.

## The checks

Points are examined in the order supplied. Nothing is sorted before the
duplicate and order checks.

| Check | Reports | Not evaluated when |
|---|---|---|
| `duplicate_key` | A date that appears more than once | never |
| `non_monotonic_order` | A date earlier than the one before it | never |
| `calendar_gap` | Runs of expected dates with no row | no expected dates given |
| `unexpected_date` | A row whose date is not expected | no expected dates given |
| `missing_marker` | A run of marker rows longer than `max_missing_run` | never |
| `stale_run` | A run of equal values longer than `max_stale_run` | never |
| `extreme_jump` | A change above `max_abs_jump`, absolute or relative | never |
| `out_of_bounds` | A value outside `lower_bound` to `upper_bound` | never |
| `availability_violation` | Availability inside the observation day, going backwards, or after the cutoff | no point states an availability |

Rules that hold for every report:

- Every check appears exactly once. A check that could not run says
  `not_evaluated`. It never looks like a pass.
- A finding of a check listed in the policy's `hard_checks` is an error. Any
  other finding is a warning. One exception: a relative jump away from zero has
  no defined size and is always an error.
- The result is `fail` exactly when a finding is an error or a hard check was
  not evaluated. The report embeds its policy, so the model enforces this and a
  re-hashed edit cannot state otherwise.
- Stale-run and jump checks compare consecutive present values. A marker row
  between them is skipped and does not reset a run.
- Arithmetic is exact `Decimal` arithmetic with no division and no floats. A
  relative jump is tested as `|change| > limit * |prior|`. Arithmetic that
  cannot be exact in 100 digits is refused.
- An empty series is refused. It is not passed vacuously.
- Repeated identical violations are merged into one finding with a count.

## What the H.15 parser accepts

Six header rows whose first cells are exactly `Series Description`, `Unit:`,
`Multiplier:`, `Currency:`, `Unique Identifier: ` (with a trailing space) and
`Time Period`, then data rows of an ISO date and one cell per series. A cell is
a plain decimal such as `3.22`, the marker `ND`, or empty.

| Cell | Point state | Kept |
|---|---|---|
| plain decimal | `value` | always, with its native text and an exact `Decimal` |
| `ND` | `missing` | always |
| empty | `not_published` | only between published dates |

Everything else is refused with an `H15ParseError`: a wrong digest or size, a
NUL byte, bytes that are not UTF-8 (a byte order mark fails the first label),
mixed line endings, a blank or multi-line record, a wrong label, a unit other
than `Percent:_Per_Year`, a multiplier other than `1`, a ragged row, a
duplicate or inconsistent identifier, a date that is not a calendar date, and
any other cell (`NaN`, `1e-2`, another marker, digits outside ASCII, stray
spaces). Dates that are not strictly ascending are refused when a series is
built.

## Limitations

- **Availability is modeled.** `available_at` comes from a caller-supplied
  rule: a number of weekdays, one fixed UTC minute, and listed non-release
  dates. It is not an observed release time. The rule cannot know about a late
  release or an unlisted closure, and a fixed UTC minute cannot follow a local
  release time across daylight-saving changes.
- **No vintages.** Values come from one current download. A publisher may
  revise history, so what a past decision could really have seen is not
  replayable from this record.
- **Unauthenticated bytes.** The digest check proves the bytes match the digest
  the caller stated. It does not prove where they came from. Hash consistency
  is not origin authentication.
- **Not a rights assessment.** `PublicSeriesRightsRecordV1` records what a
  named recorder asserted, with the hash of the terms evidence they looked at.
  It is not a `RightsAssessmentV1`, nobody independent reviewed it, and it is
  not legal advice. It can only say exploratory and never promotion eligible.
- **Exploratory lane only.** The series and the rights record can state no
  other lane. A passing quality report is not a source qualification.
- **Mechanical checks.** The checks do not know whether a value is right or
  whether the expected calendar is the right one. The thresholds are whatever
  the caller put in the policy. No default policy is shipped.
- **The cutoff is not recorded.** The report does not say which cutoff, if any,
  the availability check used.
- **Synthetic test bytes.** The tests use inline synthetic bytes in the H.15
  layout. No real H.15 file is stored in Git, and the test suite does not run
  the parser against real bytes.

## Non-goals

- No network code and no download helper.
- No change under `src/drift/evaluator/` and no risk-free input for it.
- No promotion-grade claim, no source qualification and no M1e rights record.
- No default thresholds, no default lag rule and no bundled holiday list.
- No real H.15 bytes in the repository.

## Decisions recorded while implementing

These go beyond the short design note. Each is small and local to this slice.

- `DataQualityReportV1` embeds the `policy` beside `policy_hash`. Without the
  policy the model could not tell which checks are hard, so it could not
  enforce the result rules.
- A series must acknowledge all three limitation constants, and a rights
  record must carry the recorded-assertion limitation.
- Every model here is revalidated when it is nested in another model or passed
  to `model_validate`, and the adapter and the checks revalidate their inputs,
  so an object assembled without validation is refused.
- `release_lag_weekdays` has a structural ceiling of 366 so the release-day
  walk stays bounded. It is not a calibrated threshold.
- Inputs that cannot be examined at all raise `DataQualityInputError`, which is
  separate from `DataQualityError` because there is no report to attach.

## Open questions for the owner

- **The publication-lag rule.** Which lag, which UTC minute and which
  non-release dates should model H.15 availability? The publisher's stated
  schedule has to be confirmed from the publisher before a study relies on it.
  Because the rule holds one UTC minute, a local release time needs the later
  of its two UTC equivalents to stay conservative.
- **Should the report record the cutoff?** It does not today.
- **The expected calendar.** A series has no calendar of its own, so the
  calendar checks only run when the caller supplies one.

## Verification

Focused checks for this slice:

```bash
uv run python -m pytest tests/unit/test_data_quality.py \
  tests/unit/test_public_series.py tests/unit/test_fed_h15_adapter.py \
  tests/adversarial/test_public_series_adversarial.py \
  tests/integration/test_m1e_compatibility.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
git diff --check
```

The hosted Linux workflow is the canonical gate.
