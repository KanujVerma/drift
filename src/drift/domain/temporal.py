"""Asset-neutral temporal evidence and per-query cutoff eligibility."""

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
    _normalize_utc,
)
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.serialization.canonical import content_hash

_OFFSET_SECOND = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class AvailabilityShape(StrEnum):
    """Confidence shape of a channel-scoped availability claim."""

    EXACT = "exact"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class AvailabilityBasis(StrEnum):
    """How the availability claim was obtained."""

    SOURCE_OBSERVED = "source_observed"
    VENDOR_DELIVERY = "vendor_delivery"
    LOCAL_INGEST = "local_ingest"
    RULE_DERIVED = "rule_derived"


class CutoffEligibility(StrEnum):
    """Fail-closed availability status for one query."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class ChannelKind(StrEnum):
    """Information channel category."""

    PUBLIC = "public"
    VENDOR = "vendor"
    SYSTEM = "system"


class SourcePrecision(StrEnum):
    """Precision retained from the source availability evidence."""

    SECOND = "second"
    MINUTE = "minute"
    DATE = "date"
    INTERVAL = "interval"
    SESSION = "session"
    UNKNOWN = "unknown"


class ValidPeriodV1(FrozenModel):
    """A nonempty half-open UTC period for the fact being described."""

    started_at: UTCDateTime
    ended_at: UTCDateTime

    @model_validator(mode="after")
    def validate_nonempty(self) -> ValidPeriodV1:
        if self.ended_at <= self.started_at:
            msg = "valid period must be nonempty"
            raise ValueError(msg)
        return self

    def contains(self, instant: datetime) -> bool:
        """Return whether an instant belongs to this half-open period."""
        instant_utc = _normalize_utc(instant)
        return self.started_at <= instant_utc < self.ended_at


class AvailabilityChannelV1(FrozenModel):
    """A versioned information channel."""

    kind: ChannelKind
    identifier: NonBlankStr
    version: NonBlankStr | None = None


def availability_channel_identity(
    channel: AvailabilityChannelV1,
) -> tuple[str, str, str]:
    """Return the canonical identity ordering key for an information channel."""
    return channel.kind.value, channel.identifier, channel.version or ""


class RuleDerivationV1(FrozenModel):
    """Hash-addressed provenance for a rule-derived availability claim."""

    rule_reference: ArtifactReference
    rule_version: Literal["1"]
    input_evidence_hash: SHA256Hash

    @field_validator("rule_reference")
    @classmethod
    def reject_credential_bearing_locator(
        cls, rule_reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(rule_reference)


class AvailabilityEvidenceV1(FrozenModel):
    """Immutable availability evidence for exactly one information channel."""

    channel: AvailabilityChannelV1
    shape: AvailabilityShape
    lower_bound: UTCDateTime | None = None
    upper_bound: UTCDateTime | None = None
    precision: SourcePrecision
    source_time_label: NonBlankStr | None = None
    source_timezone: NonBlankStr | None = None
    basis: AvailabilityBasis
    evidence_reference: ArtifactReference | None = None
    rule_derivation: RuleDerivationV1 | None = None

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_locator(
        cls, evidence_reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if evidence_reference is None:
            return None
        return validate_safe_provenance_reference(evidence_reference)

    @model_validator(mode="after")
    def validate_evidence(self) -> AvailabilityEvidenceV1:
        is_rule_derived = self.basis is AvailabilityBasis.RULE_DERIVED
        if not is_rule_derived:
            self._validate_channel_basis()
        if self.shape is AvailabilityShape.UNKNOWN:
            self._validate_unknown(is_rule_derived)
            return self

        self._require_source_label()
        if is_rule_derived:
            self._validate_rule_derived()
            return self

        if self.rule_derivation is not None:
            msg = "rule metadata is only permitted for rule-derived evidence"
            raise ValueError(msg)
        if self.shape is AvailabilityShape.EXACT:
            self._validate_source_exact_second()
            return self
        self._validate_raw_bounded()
        return self

    def _validate_channel_basis(self) -> None:
        expected_basis = {
            ChannelKind.PUBLIC: AvailabilityBasis.SOURCE_OBSERVED,
            ChannelKind.VENDOR: AvailabilityBasis.VENDOR_DELIVERY,
            ChannelKind.SYSTEM: AvailabilityBasis.LOCAL_INGEST,
        }[self.channel.kind]
        if self.basis is not expected_basis:
            msg = "non-rule availability channel and basis must be compatible"
            raise ValueError(msg)

    def _validate_unknown(self, is_rule_derived: bool) -> None:
        if self.precision is not SourcePrecision.UNKNOWN:
            msg = "unknown evidence requires unknown precision"
            raise ValueError(msg)
        if self.lower_bound is not None or self.upper_bound is not None:
            msg = "unknown evidence cannot have bounds"
            raise ValueError(msg)
        if is_rule_derived:
            msg = "unknown evidence cannot be rule-derived"
            raise ValueError(msg)
        if self.rule_derivation is not None:
            msg = "rule metadata is only permitted for rule-derived evidence"
            raise ValueError(msg)

    def _require_source_label(self) -> None:
        if self.source_time_label is None:
            msg = "known availability evidence requires a retained source label"
            raise ValueError(msg)

    def _validate_rule_derived(self) -> None:
        if self.shape is not AvailabilityShape.EXACT:
            msg = "rule-derived evidence must be exact"
            raise ValueError(msg)
        if self.rule_derivation is None:
            msg = "rule-derived evidence requires rule metadata"
            raise ValueError(msg)
        if self.precision is SourcePrecision.UNKNOWN:
            msg = "rule-derived evidence cannot retain unknown precision"
            raise ValueError(msg)
        self._require_equal_bounds()
        self._validate_timezone_for_retained_precision()
        if (
            self.precision is SourcePrecision.SESSION
            and self.evidence_reference is None
        ):
            msg = "session evidence requires an evidence artifact"
            raise ValueError(msg)
        if (
            self.rule_derivation.rule_reference.content_hash
            != CONSERVATIVE_UPPER_BOUND_RULE_HASH
        ):
            msg = "rule artifact does not match conservative-upper-bound-v1"
            raise ValueError(msg)

    def _validate_source_exact_second(self) -> None:
        if self.precision is not SourcePrecision.SECOND:
            msg = "exact date, minute, or session precision is only rule-derived"
            raise ValueError(msg)
        expected = expected_exact_second(self.source_time_label or "")
        self._require_equal_bounds()
        if self.lower_bound != expected or self.upper_bound != expected:
            msg = (
                "exact evidence requires an offset-bearing ISO second label and bounds"
            )
            raise ValueError(msg)

    def _validate_raw_bounded(self) -> None:
        if self.precision not in {
            SourcePrecision.SECOND,
            SourcePrecision.MINUTE,
            SourcePrecision.DATE,
            SourcePrecision.INTERVAL,
            SourcePrecision.SESSION,
        }:
            msg = "bounded evidence requires a known bounded precision"
            raise ValueError(msg)
        lower_bound, upper_bound = self._require_ordered_bounds()
        self._validate_timezone_for_retained_precision()
        if self.precision in {SourcePrecision.DATE, SourcePrecision.MINUTE}:
            expected_lower, expected_upper = expected_source_window(
                self.source_time_label or "", self.precision, self.source_timezone or ""
            )
            if (lower_bound, upper_bound) != (expected_lower, expected_upper):
                msg = "bounded evidence bounds must equal the source label window"
                raise ValueError(msg)
        if (
            self.precision is SourcePrecision.SESSION
            and self.evidence_reference is None
        ):
            msg = "session evidence requires an evidence artifact"
            raise ValueError(msg)

    def _validate_timezone_for_retained_precision(self) -> None:
        if self.precision not in {SourcePrecision.DATE, SourcePrecision.MINUTE}:
            return
        if self.source_timezone is None:
            msg = "date or minute precision requires an IANA timezone"
            raise ValueError(msg)
        try:
            ZoneInfo(self.source_timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            msg = "date or minute precision requires an IANA timezone"
            raise ValueError(msg) from error

    def _require_equal_bounds(self) -> None:
        if self.lower_bound is None or self.upper_bound is None:
            msg = "exact evidence requires equal bounds"
            raise ValueError(msg)
        if self.lower_bound != self.upper_bound:
            msg = "exact evidence requires equal bounds"
            raise ValueError(msg)

    def _require_ordered_bounds(self) -> tuple[datetime, datetime]:
        if self.lower_bound is None or self.upper_bound is None:
            msg = "bounded evidence requires ordered bounds"
            raise ValueError(msg)
        if self.lower_bound >= self.upper_bound:
            msg = "bounded evidence requires ordered bounds"
            raise ValueError(msg)
        return self.lower_bound, self.upper_bound


class AvailabilityPolicyV1(FrozenModel):
    """The explicit rule approvals for one availability query policy."""

    policy_id: NonBlankStr
    permitted_rule_hashes: tuple[SHA256Hash, ...] = ()

    @field_validator("permitted_rule_hashes")
    @classmethod
    def canonicalize_rule_hashes(
        cls, rule_hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(rule_hashes)) != len(rule_hashes):
            msg = "permitted rule hashes must be unique"
            raise ValueError(msg)
        return tuple(sorted(rule_hashes))


class CutoffEligibilityResultV1(FrozenModel):
    """A hash-bound eligibility outcome for one evidence, channel, policy, cutoff."""

    classification: CutoffEligibility
    reason: NonBlankStr
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    evidence: AvailabilityEvidenceV1
    evidence_hash: SHA256Hash
    derivation_input_evidence_hash: SHA256Hash | None = None

    @model_validator(mode="after")
    def validate_identity_bindings(self) -> CutoffEligibilityResultV1:
        if self.policy_id != self.policy.policy_id:
            msg = "result policy id must match policy"
            raise ValueError(msg)
        if self.policy_hash != content_hash(self.policy):
            msg = "result policy hash must match policy"
            raise ValueError(msg)
        if self.evidence_hash != content_hash(self.evidence):
            msg = "result evidence hash must match evidence"
            raise ValueError(msg)
        expected_input_hash = (
            None
            if self.evidence.rule_derivation is None
            else self.evidence.rule_derivation.input_evidence_hash
        )
        if self.derivation_input_evidence_hash != expected_input_hash:
            msg = "result derivation input hash must match evidence"
            raise ValueError(msg)
        return self


CONSERVATIVE_UPPER_BOUND_RULE_SPEC = {
    "rule_id": "conservative-upper-bound",
    "version": "1",
    "algorithm": "derived exact availability equals retained bounded upper bound",
}
CONSERVATIVE_UPPER_BOUND_RULE_HASH = content_hash(CONSERVATIVE_UPPER_BOUND_RULE_SPEC)


def expected_exact_second(source_time_label: str) -> datetime:
    """Parse the one source label form that supports exact raw evidence."""
    if _OFFSET_SECOND.fullmatch(source_time_label) is None:
        msg = "exact evidence requires an offset-bearing ISO second"
        raise ValueError(msg)
    parsed = datetime.fromisoformat(source_time_label.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        msg = "exact evidence requires an offset-bearing ISO second"
        raise ValueError(msg)
    return parsed.astimezone(UTC)


def expected_source_window(
    source_time_label: str,
    precision: SourcePrecision,
    source_timezone: str,
) -> tuple[datetime, datetime]:
    """Compute a safe UTC window for a local date or minute source label."""
    try:
        timezone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        msg = "date or minute precision requires an IANA timezone"
        raise ValueError(msg) from error
    if precision is SourcePrecision.DATE:
        if _ISO_DATE.fullmatch(source_time_label) is None:
            msg = "date precision requires an ISO date label"
            raise ValueError(msg)
        local_date = date.fromisoformat(source_time_label)
        lower = datetime.combine(local_date, time.min, timezone)
        upper = datetime.combine(local_date + timedelta(days=1), time.min, timezone)
    elif precision is SourcePrecision.MINUTE:
        if _ISO_MINUTE.fullmatch(source_time_label) is None:
            msg = "minute precision requires an ISO local-minute label"
            raise ValueError(msg)
        naive = datetime.strptime(source_time_label, "%Y-%m-%dT%H:%M")
        first = naive.replace(tzinfo=timezone, fold=0)
        second = naive.replace(tzinfo=timezone, fold=1)
        if first.utcoffset() != second.utcoffset():
            msg = "ambiguous or nonexistent local minute stays unknown"
            raise ValueError(msg)
        if first.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) != naive:
            msg = "ambiguous or nonexistent local minute stays unknown"
            raise ValueError(msg)
        lower = first
        upper = lower + timedelta(minutes=1)
    else:
        msg = "only date and minute labels define mechanical windows"
        raise ValueError(msg)
    return lower.astimezone(UTC), upper.astimezone(UTC)


def derive_conservative_upper_bound(
    raw_evidence: AvailabilityEvidenceV1,
    rule_reference: ArtifactReference,
) -> AvailabilityEvidenceV1:
    """Derive the conservative latest instant from retained raw bounded evidence."""
    if raw_evidence.shape is not AvailabilityShape.BOUNDED:
        msg = "conservative upper-bound rule requires bounded evidence"
        raise ValueError(msg)
    if raw_evidence.basis is AvailabilityBasis.RULE_DERIVED:
        msg = "rule input must be retained raw evidence"
        raise ValueError(msg)
    if rule_reference.content_hash != CONSERVATIVE_UPPER_BOUND_RULE_HASH:
        msg = "rule artifact does not match conservative-upper-bound-v1"
        raise ValueError(msg)
    if raw_evidence.upper_bound is None:
        msg = "bounded evidence requires an upper bound"
        raise ValueError(msg)
    values = {
        "channel": raw_evidence.channel,
        "shape": AvailabilityShape.EXACT,
        "lower_bound": raw_evidence.upper_bound,
        "upper_bound": raw_evidence.upper_bound,
        "precision": raw_evidence.precision,
        "source_time_label": raw_evidence.source_time_label,
        "source_timezone": raw_evidence.source_timezone,
        "basis": AvailabilityBasis.RULE_DERIVED,
        "evidence_reference": raw_evidence.evidence_reference,
        "rule_derivation": RuleDerivationV1(
            rule_reference=rule_reference,
            rule_version="1",
            input_evidence_hash=content_hash(raw_evidence),
        ),
    }
    return AvailabilityEvidenceV1.model_validate(values)


def evaluate_availability(
    evidence: AvailabilityEvidenceV1,
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> CutoffEligibilityResultV1:
    """Evaluate availability conservatively for one channel, policy, and cutoff."""
    cutoff_utc = _normalize_utc(cutoff)
    if evidence.channel != channel:
        return _result(
            CutoffEligibility.INDETERMINATE,
            "no_evidence_for_requested_channel",
            evidence,
            channel,
            policy,
            cutoff_utc,
        )
    if evidence.shape is AvailabilityShape.UNKNOWN:
        return _result(
            CutoffEligibility.INDETERMINATE,
            "availability_unknown",
            evidence,
            channel,
            policy,
            cutoff_utc,
        )
    if evidence.basis is AvailabilityBasis.RULE_DERIVED:
        derivation = evidence.rule_derivation
        if derivation is None:
            msg = "rule-derived evidence requires rule metadata"
            raise ValueError(msg)
        raw_evidence = retained_evidence.get(derivation.input_evidence_hash)
        if (
            raw_evidence is None
            or content_hash(raw_evidence) != derivation.input_evidence_hash
        ):
            return _result(
                CutoffEligibility.INDETERMINATE,
                "rule_input_evidence_unavailable",
                evidence,
                channel,
                policy,
                cutoff_utc,
            )
        if (
            derive_conservative_upper_bound(raw_evidence, derivation.rule_reference)
            != evidence
        ):
            return _result(
                CutoffEligibility.INDETERMINATE,
                "rule_derivation_not_reproducible",
                evidence,
                channel,
                policy,
                cutoff_utc,
            )
        if derivation.rule_reference.content_hash not in policy.permitted_rule_hashes:
            return _result(
                CutoffEligibility.INELIGIBLE,
                "rule_not_permitted_by_policy",
                evidence,
                channel,
                policy,
                cutoff_utc,
            )
    if evidence.lower_bound is None or evidence.upper_bound is None:
        msg = "known availability evidence requires bounds"
        raise ValueError(msg)
    if evidence.upper_bound <= cutoff_utc:
        return _result(
            CutoffEligibility.ELIGIBLE,
            "available_by_cutoff",
            evidence,
            channel,
            policy,
            cutoff_utc,
        )
    if evidence.lower_bound > cutoff_utc:
        return _result(
            CutoffEligibility.INELIGIBLE,
            "not_available_by_cutoff",
            evidence,
            channel,
            policy,
            cutoff_utc,
        )
    return _result(
        CutoffEligibility.INDETERMINATE,
        "cutoff_inside_availability_window",
        evidence,
        channel,
        policy,
        cutoff_utc,
    )


def _result(
    classification: CutoffEligibility,
    reason: str,
    evidence: AvailabilityEvidenceV1,
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
) -> CutoffEligibilityResultV1:
    derivation_input_hash = (
        None
        if evidence.rule_derivation is None
        else evidence.rule_derivation.input_evidence_hash
    )
    return CutoffEligibilityResultV1(
        classification=classification,
        reason=reason,
        cutoff=cutoff,
        requested_channel=channel,
        policy=policy,
        policy_id=policy.policy_id,
        policy_hash=content_hash(policy),
        evidence=evidence,
        evidence_hash=content_hash(evidence),
        derivation_input_evidence_hash=derivation_input_hash,
    )
