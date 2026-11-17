"""Offline parser for Federal Reserve H.15 CSV bytes (exploratory lane only).

This adapter turns caller-supplied bytes in the Federal Reserve Board Data
Download Program CSV layout into a ``PublicDailyRateSeriesV1``. It opens no
connection, reads no file and reads no environment: the caller obtains the
bytes, states their SHA-256, and passes them in. It is a data preparation
utility that executes outside the evaluator core, and the evaluator core never
imports it.

The layout it accepts, and nothing else:

* six header rows whose first cells are exactly ``Series Description``,
  ``Unit:``, ``Multiplier:``, ``Currency:``, ``Unique Identifier: `` (with its
  trailing space) and ``Time Period``, one further cell per series;
* then data rows of an ISO date followed by one cell per series, where a cell
  is a plain decimal such as ``3.22``, the marker ``ND`` (no data that day),
  or empty (the series was not published for that date).

Anything unexpected is refused: a digest or size mismatch (checked before any
decoding), a NUL byte, bytes that are not UTF-8, mixed line endings, a blank
or multi-line record, a wrong label, unit or multiplier, a ragged row, a
duplicate identifier, a date that is not a calendar date, and any cell that is
not one of the three forms above (``NaN``, ``1e-2``, another marker, digits
outside ASCII, stray spaces). Decimals are built from the cell text only.

Limitations, stated plainly:

* The bytes are unauthenticated. The digest check proves the bytes match the
  digest the caller stated, not that either came from the Federal Reserve.
* Values are one current download with no vintages, so revisions are not
  replayable, and each ``available_at`` is modeled by the caller's
  publication-lag rule rather than observed.
* The rights record a series is built with is a recorded assertion by a named
  recorder. It is not a rights assessment.
* The layout is the one recorded in the design note for this slice, which
  states it was confirmed on one real Data Download Program file. The tests
  use synthetic bytes in that layout; no real file is stored in Git, and this
  module has not been run against real H.15 bytes in the test suite.
* Everything produced here is exploratory. Nothing here is promotion-grade
  evidence and nothing here can be converted into it.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from itertools import pairwise

from pydantic import ValidationError

from drift.domain.common import FrozenModel
from drift.domain.public_series import (
    PUBLIC_SERIES_REQUIRED_LIMITATIONS,
    PublicationLagPolicyV1,
    PublicDailyRatePointV1,
    PublicDailyRateSeriesV1,
    PublicDailyRateState,
    PublicSeriesRightsRecordV1,
    modeled_available_at,
    seal_public_daily_rate_series,
)
from drift.errors import DriftError
from drift.markets.data_quality import DatedValue

FED_H15_SOURCE_ID = "federal-reserve-h15-csv"
H15_UNIT_PERCENT_PER_YEAR = "Percent:_Per_Year"
H15_MULTIPLIER_ONE = "1"
H15_MISSING_MARKER = "ND"
H15_NOT_PUBLISHED_QUALITY_MARKER = "not_published"
"""The marker ``quality_points`` gives a date whose cell was empty."""

H15_HEADER_LABELS = (
    "Series Description",
    "Unit:",
    "Multiplier:",
    "Currency:",
    "Unique Identifier: ",
    "Time Period",
)
"""The exact first cell of each of the six header rows, in order."""

_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_VALUE_TEXT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
_SHOWN_TEXT_LIMIT = 40


class H15ParseError(DriftError, ValueError):
    """Raised when H.15 bytes, or a request to build a series, are refused."""


@dataclass(frozen=True, slots=True)
class H15NativeColumn:
    """The header fields of one series column, exactly as printed."""

    description: str
    unit: str
    multiplier: str
    currency: str
    unique_identifier: str
    series_identifier: str


@dataclass(frozen=True, slots=True)
class H15NativeRow:
    """One data row in source order: its line, its date, one cell per column."""

    line_number: int
    observed_on: date
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class H15NativeDocument:
    """A parsed H.15 file: which bytes, which columns, which rows.

    ``source_sha256`` and ``source_byte_size`` describe the bytes that were
    parsed. They do not say where those bytes came from.
    """

    source_sha256: str
    source_byte_size: int
    columns: tuple[H15NativeColumn, ...]
    rows: tuple[H15NativeRow, ...]


def parse_h15_csv(
    data: bytes, *, expected_sha256: str, max_bytes: int
) -> H15NativeDocument:
    """Parse exact H.15 CSV bytes into header columns and rows in source order.

    The size is checked against ``max_bytes`` and the SHA-256 against
    ``expected_sha256`` before a single byte is decoded. Rows are returned in
    the order the file has them and are not sorted or deduplicated here;
    ``build_public_daily_rate_series`` refuses dates that are not strictly
    ascending.
    """
    text = _verified_text(data, expected_sha256=expected_sha256, max_bytes=max_bytes)
    records = _records(_physical_lines(text))
    labels = len(H15_HEADER_LABELS)
    if len(records) < labels:
        raise H15ParseError(
            f"h15_header_incomplete: expected {labels} header rows, found "
            f"{len(records)} rows"
        )
    for line, (label, record) in enumerate(
        zip(H15_HEADER_LABELS, records, strict=False), start=1
    ):
        if record[0] != label:
            raise H15ParseError(
                f"h15_header_label_mismatch: line {line} must start with "
                f"{label!r}, found {_shown(record[0])}"
            )
    width = len(records[0])
    for line, record in enumerate(records[:labels], start=1):
        if len(record) != width:
            raise H15ParseError(
                f"h15_ragged_header: line {line} has {len(record)} cells, "
                f"expected {width}"
            )
    if width < 2:
        raise H15ParseError("h15_no_series_columns: the header names no series")
    columns = _columns(records[:labels], width)
    if len(records) == labels:
        raise H15ParseError("h15_no_data_rows: the file has no data rows")
    rows = tuple(
        _row(line, record, columns)
        for line, record in enumerate(records[labels:], start=labels + 1)
    )
    return H15NativeDocument(
        source_sha256=expected_sha256,
        source_byte_size=len(data),
        columns=columns,
        rows=rows,
    )


def build_public_daily_rate_series(
    document: H15NativeDocument,
    *,
    series_identifier: str,
    lag_policy: PublicationLagPolicyV1,
    rights: PublicSeriesRightsRecordV1,
) -> PublicDailyRateSeriesV1:
    """Build one exploratory series from one column of a parsed document.

    A rights record for exactly this series is required, and both it and the
    lag policy are revalidated before use. Every cell is classified again
    here, so a hand-built document gains nothing over parsed bytes. Empty
    cells before the first published date and after the last are dropped (the
    series starts at its first published date); empty cells between published
    dates are kept as ``"not_published"`` points. ``ND`` is always kept, as a
    ``"missing"`` point.

    Each ``available_at`` is modeled from ``lag_policy``. The result carries
    every required limitation and can only be exploratory.
    """
    checked_document = _checked_document(document)
    checked_rights = _revalidated(
        PublicSeriesRightsRecordV1, rights, "h15_rights_record_invalid"
    )
    checked_lag = _revalidated(
        PublicationLagPolicyV1, lag_policy, "h15_lag_policy_invalid"
    )
    indexes = [
        index
        for index, column in enumerate(checked_document.columns)
        if column.series_identifier == series_identifier
    ]
    if len(indexes) != 1:
        raise H15ParseError(
            "h15_series_unknown: the document has no series "
            f"{_shown(series_identifier)}"
        )
    if checked_rights.series_identifier != series_identifier:
        raise H15ParseError(
            "h15_rights_record_series_mismatch: the rights record names "
            f"{_shown(checked_rights.series_identifier)}, not "
            f"{_shown(series_identifier)}"
        )
    column = checked_document.columns[indexes[0]]
    if column.unit != H15_UNIT_PERCENT_PER_YEAR:
        raise H15ParseError(
            f"h15_unit_unexpected: series unit is {_shown(column.unit)}"
        )
    if column.multiplier != H15_MULTIPLIER_ONE:
        raise H15ParseError(
            "h15_multiplier_unexpected: series multiplier is "
            f"{_shown(column.multiplier)}"
        )
    for earlier, later in pairwise(checked_document.rows):
        if later.observed_on <= earlier.observed_on:
            raise H15ParseError(
                "h15_dates_not_strictly_ascending: line "
                f"{later.line_number} does not follow line {earlier.line_number}"
            )
    cells = [
        (row, _cell_state(row.cells[indexes[0]], row.line_number, series_identifier))
        for row in checked_document.rows
    ]
    published = [
        position
        for position, (_, state) in enumerate(cells)
        if state != "not_published"
    ]
    if not published:
        raise H15ParseError(
            f"h15_series_never_published: series {_shown(series_identifier)} "
            "has no published date"
        )
    description = column.description.strip()
    if not description:
        raise H15ParseError("h15_description_blank: the series has no description")
    try:
        points = tuple(
            PublicDailyRatePointV1(
                observed_on=row.observed_on,
                state=state,
                native_text=row.cells[indexes[0]],
                value_percent=(
                    Decimal(row.cells[indexes[0]]) if state == "value" else None
                ),
                available_at=modeled_available_at(row.observed_on, checked_lag),
            )
            for row, state in cells[published[0] : published[-1] + 1]
        )
        return seal_public_daily_rate_series(
            source_id=FED_H15_SOURCE_ID,
            series_identifier=series_identifier,
            description=description,
            unit=column.unit,
            source_sha256=checked_document.source_sha256,
            source_byte_size=checked_document.source_byte_size,
            points=points,
            lag_policy=checked_lag,
            rights_record_hash=checked_rights.record_hash,
            acknowledged_limitations=PUBLIC_SERIES_REQUIRED_LIMITATIONS,
        )
    except ValueError as error:
        raise H15ParseError(
            "h15_series_invalid: the built series failed validation"
        ) from error


def quality_points(series: PublicDailyRateSeriesV1) -> tuple[DatedValue, ...]:
    """Return the series as points for ``assess_daily_values``.

    A value keeps its exact decimal. A ``"missing"`` date keeps its native
    marker and a ``"not_published"`` date gets a fixed marker, so both remain
    visible to the missing-run check instead of vanishing. ``available_at`` is
    the modeled instant from the series. The series is revalidated first.
    """
    checked = _revalidated(PublicDailyRateSeriesV1, series, "h15_series_invalid")
    return tuple(
        DatedValue(
            observed_on=point.observed_on,
            value=point.value_percent,
            missing_marker=_quality_marker(point),
            available_at=point.available_at,
        )
        for point in checked.points
    )


# --- bytes to records ---------------------------------------------------------


def _verified_text(data: bytes, *, expected_sha256: str, max_bytes: int) -> str:
    """Check type, size and digest, in that order, and only then decode."""
    if not isinstance(data, bytes):
        raise H15ParseError("h15_input_not_bytes: the input must be bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise H15ParseError("h15_max_bytes_invalid: max_bytes must be a positive int")
    if (
        not isinstance(expected_sha256, str)
        or _SHA256_TEXT.fullmatch(expected_sha256) is None
    ):
        raise H15ParseError(
            "h15_expected_sha256_invalid: expected_sha256 must be 64 lowercase "
            "hexadecimal characters"
        )
    if not data:
        raise H15ParseError("h15_input_empty: the input has no bytes")
    if len(data) > max_bytes:
        raise H15ParseError(
            f"h15_input_oversize: {len(data)} bytes exceeds the limit of {max_bytes}"
        )
    actual = sha256(data).hexdigest()
    if actual != expected_sha256:
        raise H15ParseError(
            f"h15_sha256_mismatch: expected {expected_sha256}, got {actual}"
        )
    if b"\x00" in data:
        raise H15ParseError("h15_nul_byte: the input contains a NUL byte")
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise H15ParseError("h15_not_utf8: the input is not valid UTF-8") from error


def _physical_lines(text: str) -> list[str]:
    """Split on LF or on CRLF, never both, and drop one final terminator."""
    returns = text.count("\r")
    if returns:
        pairs = text.count("\r\n")
        if pairs != returns or pairs != text.count("\n"):
            raise H15ParseError(
                "h15_line_endings_mixed: line endings must be all LF or all CRLF"
            )
        lines = text.split("\r\n")
    else:
        lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _records(lines: list[str]) -> list[list[str]]:
    """Read one strict CSV record per physical line."""
    reader = csv.reader(lines, strict=True)
    records: list[list[str]] = []
    try:
        for record in reader:
            line = len(records) + 1
            if reader.line_num != line:
                raise H15ParseError(
                    f"h15_multiline_record: the record at line {line} spans "
                    "more than one line"
                )
            if not record:
                raise H15ParseError(f"h15_blank_line: line {line} is blank")
            records.append(record)
    except csv.Error as error:
        raise H15ParseError(
            f"h15_csv_malformed: line {reader.line_num}: {error}"
        ) from error
    return records


def _columns(header: list[list[str]], width: int) -> tuple[H15NativeColumn, ...]:
    columns: list[H15NativeColumn] = []
    seen: set[str] = set()
    for index in range(1, width):
        description, unit, multiplier, currency, unique, identifier = (
            record[index] for record in header
        )
        if unit != H15_UNIT_PERCENT_PER_YEAR:
            raise H15ParseError(
                f"h15_unit_unexpected: column {index} has unit {_shown(unit)}, "
                f"expected {H15_UNIT_PERCENT_PER_YEAR!r}"
            )
        if multiplier != H15_MULTIPLIER_ONE:
            raise H15ParseError(
                f"h15_multiplier_unexpected: column {index} has multiplier "
                f"{_shown(multiplier)}, expected {H15_MULTIPLIER_ONE!r}"
            )
        if not identifier or any(character.isspace() for character in identifier):
            raise H15ParseError(
                f"h15_identifier_invalid: column {index} has identifier "
                f"{_shown(identifier)}"
            )
        if unique.rsplit("/", maxsplit=1)[-1] != identifier:
            raise H15ParseError(
                f"h15_identifier_mismatch: column {index} is {_shown(unique)} "
                f"in the identifier row but {_shown(identifier)} below it"
            )
        if identifier in seen:
            raise H15ParseError(
                f"h15_duplicate_series_identifier: {_shown(identifier)} names "
                "more than one column"
            )
        seen.add(identifier)
        columns.append(
            H15NativeColumn(
                description=description,
                unit=unit,
                multiplier=multiplier,
                currency=currency,
                unique_identifier=unique,
                series_identifier=identifier,
            )
        )
    return tuple(columns)


def _row(
    line: int, record: list[str], columns: tuple[H15NativeColumn, ...]
) -> H15NativeRow:
    if len(record) != len(columns) + 1:
        raise H15ParseError(
            f"h15_ragged_row: line {line} has {len(record)} cells, expected "
            f"{len(columns) + 1}"
        )
    cells = tuple(record[1:])
    for cell, column in zip(cells, columns, strict=True):
        _cell_state(cell, line, column.series_identifier)
    return H15NativeRow(
        line_number=line, observed_on=_observed_on(record[0], line), cells=cells
    )


def _observed_on(text: str, line: int) -> date:
    if _DATE_TEXT.fullmatch(text) is not None:
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    raise H15ParseError(
        f"h15_date_invalid: line {line} starts with {_shown(text)}, not an ISO "
        "calendar date"
    )


def _cell_state(text: str, line: int, series_identifier: str) -> PublicDailyRateState:
    """Classify one cell: a plain decimal, the ND marker, or empty."""
    if text == "":
        return "not_published"
    if text == H15_MISSING_MARKER:
        return "missing"
    if _VALUE_TEXT.fullmatch(text) is not None:
        return "value"
    raise H15ParseError(
        f"h15_cell_invalid: line {line} series {series_identifier} has "
        f"{_shown(text)}, which is not a plain decimal, ND or empty"
    )


# --- series building ----------------------------------------------------------


def _checked_document(document: H15NativeDocument) -> H15NativeDocument:
    """Refuse anything that is not a well-shaped native document."""
    shaped = (
        isinstance(document, H15NativeDocument)
        and isinstance(document.columns, tuple)
        and isinstance(document.rows, tuple)
        and all(isinstance(column, H15NativeColumn) for column in document.columns)
        and all(
            isinstance(row, H15NativeRow)
            and type(row.observed_on) is date
            and isinstance(row.cells, tuple)
            and len(row.cells) == len(document.columns)
            and all(isinstance(cell, str) for cell in row.cells)
            for row in document.rows
        )
    )
    if not shaped:
        raise H15ParseError(
            "h15_document_invalid: a well-shaped H15NativeDocument is required"
        )
    return document


def _revalidated[M: FrozenModel](declared: type[M], model: M, code: str) -> M:
    """Rebuild a model through validation, so a constructed forgery is refused."""
    if not isinstance(model, declared):
        raise H15ParseError(f"{code}: a {declared.__name__} is required")
    try:
        return declared.model_validate(model.model_dump(mode="python", warnings=False))
    except ValidationError as error:
        raise H15ParseError(f"{code}: the model failed revalidation") from error


def _quality_marker(point: PublicDailyRatePointV1) -> str | None:
    if point.state == "value":
        return None
    if point.state == "missing":
        return point.native_text
    return H15_NOT_PUBLISHED_QUALITY_MARKER


def _shown(text: object) -> str:
    """A bounded, escaped rendering of untrusted text for an error message."""
    return ascii(str(text)[:_SHOWN_TEXT_LIMIT])
