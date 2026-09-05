"""Exact source-side economic primitives for M1c corporate-action evidence."""

import os
import re
import stat
from enum import StrEnum
from hashlib import sha256
from math import gcd
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import TemporalBoundaryClaimV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.serialization.canonical import content_hash


class ActionKind(StrEnum):
    """Closed economic action vocabulary shared by records and queries."""

    FORWARD_SPLIT = "forward_split"
    REVERSE_SPLIT = "reverse_split"
    REGULAR_CASH_DIVIDEND = "regular_cash_dividend"
    SPECIAL_CASH_DISTRIBUTION = "special_cash_distribution"
    STOCK_DIVIDEND = "stock_dividend"
    CASH_ACQUISITION = "cash_acquisition"
    STOCK_ACQUISITION = "stock_acquisition"
    MIXED_ACQUISITION = "mixed_acquisition"
    SPINOFF = "spinoff"
    CONVERSION = "conversion"
    LIQUIDATION = "liquidation"
    BANKRUPTCY_REORGANIZATION = "bankruptcy_reorganization"
    RIGHTS_WARRANTS_CVR = "rights_warrants_cvr"
    OTHER_UNSUPPORTED = "other_unsupported"


type EconomicFamily = Literal["terms", "effect", "settlement", "coverage"]


def validate_canonical_cash(value: object) -> str:
    """Accept only a nonnegative decimal spelling that is already canonical."""
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", value) is None
    ):
        msg = "cash requires canonical nonnegative decimal text"
        raise ValueError(msg)
    return value


type CanonicalCash = Annotated[str, BeforeValidator(validate_canonical_cash)]


class PositiveRatioV1(FrozenModel):
    """An exact, reduced positive ratio represented without numeric conversion."""

    numerator: str
    denominator: str

    @model_validator(mode="after")
    def exact_positive(self) -> Self:
        if any(
            re.fullmatch(r"[1-9][0-9]*", item) is None
            for item in (self.numerator, self.denominator)
        ):
            msg = "ratio requires positive canonical integers"
            raise ValueError(msg)
        if gcd(int(self.numerator), int(self.denominator)) != 1:
            msg = "ratio must be reduced"
            raise ValueError(msg)
        return self


class EconomicSourceKeyV1(FrozenModel):
    """A stable source-native report key, independent of economic interpretation."""

    source_id: NonBlankStr
    family: EconomicFamily
    native_record_id: NonBlankStr


class EconomicOccurrenceV1(FrozenModel):
    """A source claim about occurrence identity, separate from a source report key."""

    kind: Literal["identified", "unknown"]
    native_occurrence_id: NonBlankStr | None = None
    evidence_reference: ArtifactReference | None = None
    reason: NonBlankStr | None = None

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_union_shape(self) -> Self:
        if self.kind == "identified":
            if self.native_occurrence_id is None or self.evidence_reference is None:
                msg = "identified occurrence requires an ID and evidence"
                raise ValueError(msg)
            if self.reason is not None:
                msg = "identified occurrence cannot carry an unknown reason"
                raise ValueError(msg)
        elif (
            self.native_occurrence_id is not None
            or self.evidence_reference is not None
            or self.reason is None
        ):
            msg = "unknown occurrence requires only a reason"
            raise ValueError(msg)
        return self


class EconomicAssociationV1(FrozenModel):
    """A query-neutral source claim about a parent or related source record."""

    kind: Literal["identified", "native_hint", "unknown"]
    target: EconomicSourceKeyV1 | None = None
    asserted_target_version_hash: SHA256Hash | None = None
    native_hint: NonBlankStr | None = None
    reason: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_union_shape(self) -> Self:
        if self.kind == "identified":
            if self.target is None:
                msg = "identified association requires a target"
                raise ValueError(msg)
            if self.native_hint is not None or self.reason is not None:
                msg = "identified association cannot carry a hint or unknown reason"
                raise ValueError(msg)
        elif self.kind == "native_hint":
            if self.target is not None or self.asserted_target_version_hash is not None:
                msg = "native hint cannot claim an exact target"
                raise ValueError(msg)
            if self.native_hint is None:
                msg = "native hint association requires a native hint"
                raise ValueError(msg)
            if self.reason is not None:
                msg = "native hint association cannot carry an unknown reason"
                raise ValueError(msg)
        elif (
            self.target is not None
            or self.asserted_target_version_hash is not None
            or self.native_hint is not None
            or self.reason is None
        ):
            msg = "unknown association requires only a reason"
            raise ValueError(msg)
        return self


class EconomicRecipientV1(FrozenModel):
    """A source-reported recipient with no implied affiliation or eligibility."""

    kind: Literal["security", "unresolved_property"]
    security_id: UUID7 | None = None
    source_property_key: NonBlankStr | None = None
    reason: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_union_shape(self) -> Self:
        if self.kind == "security":
            if self.security_id is None:
                msg = "security recipient requires a security ID"
                raise ValueError(msg)
            if self.source_property_key is not None or self.reason is not None:
                msg = "security recipient cannot carry unresolved-property fields"
                raise ValueError(msg)
        elif (
            self.security_id is not None
            or self.source_property_key is None
            or self.reason is None
        ):
            msg = "unresolved property recipient requires property key and reason"
            raise ValueError(msg)
        return self


class FractionTreatmentV1(FrozenModel):
    """The sourced treatment of fractional share entitlements."""

    kind: Literal[
        "fraction_issued",
        "round_up",
        "round_down",
        "round_nearest",
        "aggregate_sale_cash",
        "unknown",
    ]
    source_rule: NonBlankStr | None = None
    evidence_reference: ArtifactReference | None = None

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_union_shape(self) -> Self:
        if self.kind == "unknown":
            if self.source_rule is not None or self.evidence_reference is not None:
                msg = "unknown fraction treatment has no source rule or evidence"
                raise ValueError(msg)
        elif self.source_rule is None or self.evidence_reference is None:
            msg = "known fraction treatment requires source rule and evidence"
            raise ValueError(msg)
        return self


class EconomicUnitBasisV1(FrozenModel):
    """The explicit unit denominator for a cash amount."""

    security_id: UUID7
    denominator: PositiveRatioV1
    share_basis: Literal[
        "predecessor_pre_action", "predecessor_post_action", "as_reported_unknown"
    ]


class EconomicShareBasisV1(FrozenModel):
    """The share basis for a share ratio that already expresses its denominator."""

    security_id: UUID7
    share_basis: Literal[
        "predecessor_pre_action", "predecessor_post_action", "as_reported_unknown"
    ]


class CashComponentV1(FrozenModel):
    """A nonnegative source-reported cash component."""

    kind: Literal["cash"]
    component_id: NonBlankStr
    amount: CanonicalCash
    currency_namespace: NonBlankStr
    currency_code: NonBlankStr
    unit_basis: EconomicUnitBasisV1
    amount_basis: Literal["gross", "net", "unknown"]
    applicability: Literal["ordinary_passive_holder", "conditional", "unknown"]
    conditions: tuple[NonBlankStr, ...]
    source_amount_text: str | None = None
    source_precision: int | None = Field(default=None, ge=0)


class ShareComponentV1(FrozenModel):
    """A source-reported share entitlement ratio without implicit normalization."""

    kind: Literal["shares"]
    component_id: NonBlankStr
    recipient: EconomicRecipientV1
    ratio: PositiveRatioV1
    ratio_meaning: Literal["resulting_per_predecessor", "additional_per_predecessor"]
    unit_basis: EconomicShareBasisV1
    fraction_treatment: FractionTreatmentV1
    applicability: Literal["ordinary_passive_holder", "conditional", "unknown"]
    conditions: tuple[NonBlankStr, ...]


class UnsupportedPropertyComponentV1(FrozenModel):
    """A retained property receipt that M1c does not value or normalize."""

    kind: Literal["unsupported_property"]
    component_id: NonBlankStr
    recipient: EconomicRecipientV1
    source_description: NonBlankStr
    reason: NonBlankStr
    evidence_reference: ArtifactReference

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)


type EconomicComponentV1 = Annotated[
    CashComponentV1 | ShareComponentV1 | UnsupportedPropertyComponentV1,
    Field(discriminator="kind"),
]


class EconomicComponentGapV1(FrozenModel):
    """A typed withholding of one source component from a safe projection."""

    component_id: NonBlankStr
    source_component_hash: SHA256Hash
    reason: NonBlankStr


class EconomicDateFactV1(FrozenModel):
    """A uniquely named source date claim without imposed global date ordering."""

    role: Literal[
        "announcement",
        "approval",
        "ex",
        "record",
        "payable",
        "due_bill_start",
        "due_bill_end",
        "due_bill_redemption",
        "legal_effect",
        "trading_basis",
    ]
    boundary: TemporalBoundaryClaimV1
    rule_reference: ArtifactReference | None = None

    @field_validator("rule_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return validate_safe_provenance_reference(reference)


def economic_implementation_hash() -> str:
    """Hash the exact bytes of every Python source file in this installed package."""
    module_path = Path(__file__).absolute()
    package_root = module_path.parent.parent
    if module_path.is_symlink() or package_root.is_symlink():
        msg = "economic implementation source tree cannot contain symlinks"
        raise ValueError(msg)
    if package_root.is_symlink() or not package_root.is_dir():
        msg = "economic implementation package root must be a real directory"
        raise ValueError(msg)
    files: list[dict[str, str]] = []
    for path in _source_paths(package_root):
        digest = sha256(_read_source_bytes(path)).hexdigest()
        files.append(
            {"path": path.relative_to(package_root).as_posix(), "sha256": digest}
        )
    return content_hash({"profile": "drift-python-source-inventory-v1", "files": files})


def _source_paths(package_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    pending = [package_root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            msg = f"economic implementation directory is unreadable: {directory}"
            raise ValueError(msg) from error
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                msg = (
                    "economic implementation source tree cannot contain symlinks: "
                    f"{path}"
                )
                raise ValueError(msg)
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False) and path.suffix == ".py":
                paths.append(path)
    return tuple(
        sorted(paths, key=lambda path: path.relative_to(package_root).as_posix())
    )


def _read_source_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        msg = f"economic implementation source is unreadable: {path}"
        raise ValueError(msg) from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            msg = f"economic implementation source must be a regular file: {path}"
            raise ValueError(msg)
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            return source.read()
    except OSError as error:
        msg = f"economic implementation source is unreadable: {path}"
        raise ValueError(msg) from error
    finally:
        os.close(descriptor)
