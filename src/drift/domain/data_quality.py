"""Typed data-quality policy, findings, per-check results and report.

These models record the outcome of mechanical checks over one daily series of
dated values: duplicate dates, date order, calendar coverage, missing-marker
runs, stale runs, jumps, bounds and stated availability. The checks themselves
live in ``drift.markets.data_quality``; this module only fixes what a policy
and a report are and keeps a report self-consistent.

Limitations, stated plainly:

* A report says that named checks ran against values the caller supplied. It
  does not authenticate the origin of those values, and it is not evidence
  that a series is correct, complete or fit for any use.
* A passing report is not a source qualification, a rights decision or a
  promotion gate. It belongs to the exploratory lane and changes nothing in
  the evaluator.
* The thresholds in a policy are caller-supplied numbers. Nothing here
  calibrates them, and no default is offered.
* Hashes cover the exact decimal spelling of each number, so ``5.0`` and
  ``5`` give different policy hashes.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.dataset_validation import FindingSeverity, ValidationResult
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

_PLACEHOLDER_HASH = "0" * 64


class DataQualityCheck(StrEnum):
    """The closed set of mechanical checks a report accounts for."""

    DUPLICATE_KEY = "duplicate_key"
    NON_MONOTONIC_ORDER = "non_monotonic_order"
    CALENDAR_GAP = "calendar_gap"
    UNEXPECTED_DATE = "unexpected_date"
    MISSING_MARKER = "missing_marker"
    STALE_RUN = "stale_run"
    EXTREME_JUMP = "extreme_jump"
    OUT_OF_BOUNDS = "out_of_bounds"
    AVAILABILITY_VIOLATION = "availability_violation"


ALL_DATA_QUALITY_CHECKS: tuple[DataQualityCheck, ...] = tuple(
    sorted(DataQualityCheck, key=lambda check: check.value)
)
"""Every check once, in the canonical order a report must use (by value)."""

#: The two checks that can only run against a caller-supplied calendar.
_CALENDAR_CHECKS = (DataQualityCheck.CALENDAR_GAP, DataQualityCheck.UNEXPECTED_DATE)

type DataQualityCheckStatus = Literal["pass", "warn", "fail", "not_evaluated"]
type DataQualitySubjectKind = Literal["public_daily_series", "daily_price_observations"]
type DataQualityJumpMode = Literal["absolute", "relative"]


class DataQualityInputError(DriftError, ValueError):
    """Raised when an input to a quality assessment cannot be examined at all.

    This is distinct from a failed report: nothing was assessed, so there is
    no report to attach.
    """


class _RevalidatedModel(FrozenModel):
    """Frozen model whose instances are validated again wherever they are used.

    Pydantic accepts an existing model instance as a field value without
    looking inside it. With this setting an instance assembled without
    validation is checked again when it is nested in another model or passed
    to ``model_validate``, so it cannot ride in unchecked.
    """

    model_config = ConfigDict(revalidate_instances="always")


class DataQualityPolicyV1(_RevalidatedModel):
    """Caller-supplied limits for one assessment, bound by a content hash.

    ``max_abs_jump`` is an absolute difference when ``jump_mode`` is
    ``"absolute"`` and a fraction of the prior value when it is
    ``"relative"``. ``max_stale_run`` and ``max_missing_run`` are the longest
    runs still accepted. A finding of a check named in ``hard_checks`` is an
    error; a finding of any other check is a warning. A hard check that could
    not be evaluated fails the report.

    The numbers are the caller's own. This type neither supplies nor endorses
    any threshold.
    """

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    lower_bound: Decimal
    upper_bound: Decimal
    max_abs_jump: Decimal
    jump_mode: DataQualityJumpMode
    max_stale_run: Annotated[int, Field(ge=1)]
    max_missing_run: Annotated[int, Field(ge=0)]
    hard_checks: tuple[DataQualityCheck, ...]
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        for label, number in (
            ("lower_bound", self.lower_bound),
            ("upper_bound", self.upper_bound),
            ("max_abs_jump", self.max_abs_jump),
        ):
            if not number.is_finite():
                raise ValueError(
                    f"data_quality_policy_number_not_finite: {label} must be finite"
                )
        if self.lower_bound > self.upper_bound:
            raise ValueError(
                "data_quality_policy_bounds_inverted: lower_bound exceeds upper_bound"
            )
        if self.max_abs_jump < 0:
            raise ValueError(
                "data_quality_policy_jump_limit_negative: max_abs_jump is negative"
            )
        if self.hard_checks != _canonical_checks(self.hard_checks):
            raise ValueError(
                "data_quality_policy_hard_checks_not_canonical: hard_checks must "
                "be unique and sorted by value"
            )
        expected = data_quality_policy_hash(self)
        if self.policy_hash != expected:
            raise ValueError(
                f"data_quality_policy_hash_mismatch: expected {expected}, "
                f"got {self.policy_hash}"
            )
        return self


class DataQualityFindingV1(_RevalidatedModel):
    """One deterministic finding: which check, where, how many, against what.

    ``first_date`` and ``last_date`` bound the observation dates involved and
    ``count`` is how many units the finding covers. ``observed`` and ``limit``
    are the exact text of the measured quantity and of the limit it was held
    to, or ``None`` where no such number exists.
    """

    check: DataQualityCheck
    severity: FindingSeverity
    code: NonBlankStr
    first_date: date
    last_date: date
    count: Annotated[int, Field(ge=1)]
    observed: str | None
    limit: str | None

    @model_validator(mode="after")
    def validate_finding(self) -> Self:
        if self.severity not in (FindingSeverity.WARNING, FindingSeverity.ERROR):
            raise ValueError(
                "data_quality_finding_severity_invalid: a finding is a warning "
                "or an error"
            )
        if self.first_date > self.last_date:
            raise ValueError(
                "data_quality_finding_dates_inverted: first_date is after last_date"
            )
        return self


class DataQualityCheckResultV1(_RevalidatedModel):
    """The status of one check, so a silent skip cannot look like a pass.

    ``examined_count`` is how many units the check looked at and
    ``finding_count`` how many findings it produced. ``not_evaluated`` means
    the check could not run for want of an optional input.
    """

    check: DataQualityCheck
    status: DataQualityCheckStatus
    examined_count: Annotated[int, Field(ge=0)]
    finding_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_check_result(self) -> Self:
        consistent = {
            "pass": self.finding_count == 0,
            "warn": self.finding_count >= 1,
            "fail": self.finding_count >= 1,
            "not_evaluated": self.finding_count == 0 and self.examined_count == 0,
        }[self.status]
        if not consistent:
            raise ValueError(
                "data_quality_check_result_inconsistent: status "
                f"{self.status} does not fit {self.examined_count} examined and "
                f"{self.finding_count} findings"
            )
        return self


class DataQualityReportV1(_RevalidatedModel):
    """Every check accounted for once, with its findings and one result.

    The report embeds the policy it was produced under, so the rules that tie
    severities and the result to the hard checks are enforced by the model
    itself: a finding of a hard check is an error, the result is ``fail``
    exactly when there is an error finding or a hard check was not evaluated,
    and no re-hashed edit can state otherwise.

    What a report does not say: that ``subject_hash`` or ``source_sha256``
    name anything real, or that the cutoff used for the availability check was
    any particular instant (the cutoff is not recorded). A consumer must
    compare ``subject_hash``, ``source_sha256`` and ``policy_hash`` with the
    data and policy it actually holds. Hash consistency is not origin
    authentication.

    The nested policy, check results and findings are revalidated whenever a
    report is validated, so one assembled without validation cannot ride in
    unchecked.
    """

    schema_version: Literal["1"] = "1"
    subject_kind: DataQualitySubjectKind
    subject_hash: SHA256Hash
    source_sha256: SHA256Hash
    policy: DataQualityPolicyV1
    policy_hash: SHA256Hash
    expected_dates_hash: SHA256Hash | None
    checks: tuple[DataQualityCheckResultV1, ...]
    findings: tuple[DataQualityFindingV1, ...]
    result: ValidationResult
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if tuple(item.check for item in self.checks) != ALL_DATA_QUALITY_CHECKS:
            raise ValueError(
                "data_quality_report_checks_not_canonical: every check must "
                "appear exactly once, sorted by value"
            )
        keys = [data_quality_finding_sort_key(item) for item in self.findings]
        if any(later <= earlier for earlier, later in pairwise(keys)):
            raise ValueError(
                "data_quality_report_findings_not_canonical: findings must be "
                "unique and in canonical order"
            )
        if self.policy_hash != data_quality_policy_hash(self.policy):
            raise ValueError(
                "data_quality_report_policy_hash_mismatch: policy_hash does not "
                "cover the embedded policy"
            )
        hard = frozenset(self.policy.hard_checks)
        for finding in self.findings:
            if finding.check in hard and finding.severity is not FindingSeverity.ERROR:
                raise ValueError(
                    "data_quality_report_severity_mismatch: a finding of the "
                    f"hard check {finding.check.value} must be an error"
                )
        for item in self.checks:
            own = tuple(
                finding for finding in self.findings if finding.check is item.check
            )
            if not _status_fits(item, own):
                raise ValueError(
                    "data_quality_report_check_mismatch: the result of "
                    f"{item.check.value} does not agree with its findings"
                )
        calendar_evaluated = {
            item.status != "not_evaluated"
            for item in self.checks
            if item.check in _CALENDAR_CHECKS
        }
        if calendar_evaluated != {self.expected_dates_hash is not None}:
            raise ValueError(
                "data_quality_report_calendar_basis_mismatch: the calendar "
                "checks are evaluated exactly when expected_dates_hash is set"
            )
        if self.result is not _expected_result(self.checks, self.findings, hard):
            raise ValueError(
                "data_quality_report_result_mismatch: the result must be fail "
                "exactly when a finding is an error or a hard check was not "
                "evaluated"
            )
        expected = data_quality_report_hash(self)
        if self.report_hash != expected:
            raise ValueError(
                f"data_quality_report_hash_mismatch: expected {expected}, "
                f"got {self.report_hash}"
            )
        return self


class DataQualityError(DriftError, ValueError):
    """Raised when a data-quality report did not pass. Carries the report."""

    def __init__(self, report: DataQualityReportV1) -> None:
        self.report = report
        hard = frozenset(report.policy.hard_checks)
        reasons = [
            f"{item.check.value}={item.status}"
            for item in report.checks
            if item.status == "fail"
            or (item.status == "not_evaluated" and item.check in hard)
        ]
        super().__init__("data_quality_report_failed: " + "; ".join(reasons))


def data_quality_finding_sort_key(
    finding: DataQualityFindingV1,
) -> tuple[str, date, date, str, str, int, bool, str, bool, str]:
    """Return the total order findings take inside a report."""
    return (
        finding.check.value,
        finding.first_date,
        finding.last_date,
        finding.code,
        finding.severity.value,
        finding.count,
        finding.observed is not None,
        finding.observed or "",
        finding.limit is not None,
        finding.limit or "",
    )


def data_quality_policy_hash(policy: DataQualityPolicyV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one policy."""
    dump = policy.model_dump(mode="python", warnings=False)
    dump.pop("policy_hash", None)
    return content_hash(dump)


def data_quality_report_hash(report: DataQualityReportV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one report."""
    dump = report.model_dump(mode="python", warnings=False)
    dump.pop("report_hash", None)
    return content_hash(dump)


def expected_dates_content_hash(expected_dates: Iterable[date]) -> SHA256Hash:
    """Return the canonical hash of one expected calendar, as a set of dates.

    The dates are hashed sorted, so the order they were supplied in carries no
    meaning. A repeated date is refused rather than collapsed.
    """
    supplied = tuple(expected_dates)
    if any(type(day) is not date for day in supplied):
        raise DataQualityInputError(
            "data_quality_expected_dates_invalid: every expected date must be "
            "a plain calendar date"
        )
    ordered = tuple(sorted(set(supplied)))
    if len(ordered) != len(supplied):
        raise DataQualityInputError(
            "data_quality_expected_dates_duplicated: the expected calendar "
            "repeats a date"
        )
    return content_hash({"expected_dates": ordered})


def seal_data_quality_policy(
    *,
    policy_id: str,
    lower_bound: Decimal,
    upper_bound: Decimal,
    max_abs_jump: Decimal,
    jump_mode: DataQualityJumpMode,
    max_stale_run: int,
    max_missing_run: int,
    hard_checks: tuple[DataQualityCheck, ...],
) -> DataQualityPolicyV1:
    """Seal a policy's own hash over the given fields and validate the result.

    Every field is validated as given: a seal never repairs a policy, so
    ``hard_checks`` must already be unique and sorted by value.
    """
    draft = DataQualityPolicyV1.model_construct(
        schema_version="1",
        policy_id=policy_id,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        max_abs_jump=max_abs_jump,
        jump_mode=jump_mode,
        max_stale_run=max_stale_run,
        max_missing_run=max_missing_run,
        hard_checks=hard_checks,
        policy_hash=_PLACEHOLDER_HASH,
    )
    return DataQualityPolicyV1.model_validate(
        draft.model_dump(mode="python", warnings=False)
        | {"policy_hash": data_quality_policy_hash(draft)}
    )


def seal_data_quality_report(
    *,
    subject_kind: DataQualitySubjectKind,
    subject_hash: str,
    source_sha256: str,
    policy: DataQualityPolicyV1,
    expected_dates_hash: str | None,
    checks: tuple[DataQualityCheckResultV1, ...],
    findings: tuple[DataQualityFindingV1, ...],
    result: ValidationResult,
) -> DataQualityReportV1:
    """Seal a report's own hash over the given fields and validate the result.

    Nothing is recomputed or reordered: checks, findings and the result are
    validated exactly as given, so an inconsistent report is refused.
    """
    draft = DataQualityReportV1.model_construct(
        schema_version="1",
        subject_kind=subject_kind,
        subject_hash=subject_hash,
        source_sha256=source_sha256,
        policy=policy,
        policy_hash=policy.policy_hash,
        expected_dates_hash=expected_dates_hash,
        checks=checks,
        findings=findings,
        result=result,
        report_hash=_PLACEHOLDER_HASH,
    )
    return DataQualityReportV1.model_validate(
        draft.model_dump(mode="python", warnings=False)
        | {"report_hash": data_quality_report_hash(draft)}
    )


def _canonical_checks(
    checks: Iterable[DataQualityCheck],
) -> tuple[DataQualityCheck, ...]:
    return tuple(sorted(set(checks), key=lambda check: check.value))


def _status_fits(
    item: DataQualityCheckResultV1, own: tuple[DataQualityFindingV1, ...]
) -> bool:
    """Whether one check result agrees with the findings of its own check."""
    if len(own) != item.finding_count:
        return False
    if item.status == "not_evaluated":
        return not own and item.examined_count == 0
    if any(finding.severity is FindingSeverity.ERROR for finding in own):
        return item.status == "fail"
    return item.status == ("warn" if own else "pass")


def _expected_result(
    checks: tuple[DataQualityCheckResultV1, ...],
    findings: tuple[DataQualityFindingV1, ...],
    hard: frozenset[DataQualityCheck],
) -> ValidationResult:
    has_error = any(item.severity is FindingSeverity.ERROR for item in findings)
    hard_unevaluated = any(
        item.status == "not_evaluated" and item.check in hard for item in checks
    )
    if has_error or hard_unevaluated:
        return ValidationResult.FAIL
    return ValidationResult.PASS
