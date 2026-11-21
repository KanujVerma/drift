"""Unit tests for the offline Federal Reserve H.15 CSV parser.

SYNTHETIC FIXTURES ONLY. Every byte string below is invented for these tests
and merely follows the header layout of a Data Download Program file. The
series identifiers, descriptions and values are not Federal Reserve data, no
real H.15 file is stored in Git, and nothing here downloads anything.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from drift.adapters.fed_h15 import (
    FED_H15_SOURCE_ID,
    H15_IDENTIFIER_LABEL_SPELLINGS,
    H15_NOT_PUBLISHED_QUALITY_MARKER,
    H15NativeDocument,
    H15ParseError,
    build_public_daily_rate_series,
    parse_h15_csv,
    quality_points,
)
from drift.domain.data_quality import ALL_DATA_QUALITY_CHECKS, seal_data_quality_policy
from drift.domain.dataset_validation import ValidationResult
from drift.domain.public_series import (
    PUBLIC_SERIES_REQUIRED_LIMITATIONS,
    PUBLIC_SERIES_RIGHTS_LIMITATION_RECORDED_ASSERTION,
    PublicationLagPolicyV1,
    PublicDailyRateSeriesV1,
    PublicSeriesRightsRecordV1,
    modeled_available_at,
    seal_public_series_rights_record,
    seal_publication_lag_policy,
)
from drift.errors import DriftError
from drift.markets.data_quality import (
    DatedValue,
    assess_daily_values,
    require_passing,
)

SERIES_A = "SYNTH_A.B"
SERIES_B = "SYNTH_B.B"

#: Synthetic header rows in the six-row Data Download Program layout.
SYNTHETIC_HEADER_ROWS = (
    b'"Series Description","Synthetic rate A (not real data)",'
    b'"Synthetic rate B (not real data)"',
    b'"Unit:","Percent:_Per_Year","Percent:_Per_Year"',
    b'"Multiplier:","1","1"',
    b'"Currency:","NA","NA"',
    b'"Unique Identifier: ","H15/H15/SYNTH_A.B","H15/H15/SYNTH_B.B"',
    b'"Time Period","SYNTH_A.B","SYNTH_B.B"',
)
#: Synthetic data rows: decimals, the ND marker and empty cells.
SYNTHETIC_DATA_ROWS = (
    b"2024-01-02,,5.30",
    b"2024-01-03,5.25,5.31",
    b"2024-01-04,5.26,ND",
    b"2024-01-05,,5.33",
    b"2024-01-08,5.28,5.34",
    b"2024-01-09,5.29,",
)


def _document_bytes(
    *,
    header: tuple[bytes, ...] = SYNTHETIC_HEADER_ROWS,
    rows: tuple[bytes, ...] = SYNTHETIC_DATA_ROWS,
    newline: bytes = b"\n",
) -> bytes:
    return b"".join(line + newline for line in (*header, *rows))


def _parse(data: bytes, *, max_bytes: int = 8192) -> H15NativeDocument:
    return parse_h15_csv(
        data, expected_sha256=sha256(data).hexdigest(), max_bytes=max_bytes
    )


def _with_header_row(index: int, replacement: bytes) -> bytes:
    header = list(SYNTHETIC_HEADER_ROWS)
    header[index] = replacement
    return _document_bytes(header=tuple(header))


def _with_cell(text: str) -> bytes:
    """The synthetic document with one data cell of series A replaced."""
    rows = list(SYNTHETIC_DATA_ROWS)
    rows[1] = b"2024-01-03," + text.encode("utf-8") + b",5.31"
    return _document_bytes(rows=tuple(rows))


def _lag() -> PublicationLagPolicyV1:
    return seal_publication_lag_policy(
        policy_id="synthetic-next-weekday-2115z",
        release_lag_weekdays=1,
        release_utc_minute_of_day=21 * 60 + 15,
        non_release_dates=(),
    )


def _rights(series_identifier: str) -> PublicSeriesRightsRecordV1:
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


def _series(data: bytes, series_identifier: str) -> PublicDailyRateSeriesV1:
    return build_public_daily_rate_series(
        _parse(data),
        series_identifier=series_identifier,
        lag_policy=_lag(),
        rights=_rights(series_identifier),
    )


# --- parsing the layout ---------------------------------------------------


def test_the_layout_parses_into_columns_and_rows_in_source_order() -> None:
    data = _document_bytes()

    document = _parse(data)

    assert document.source_sha256 == sha256(data).hexdigest()
    assert document.source_byte_size == len(data)
    first, second = document.columns
    assert first.description == "Synthetic rate A (not real data)"
    assert (first.unit, first.multiplier, first.currency) == (
        "Percent:_Per_Year",
        "1",
        "NA",
    )
    assert first.unique_identifier == "H15/H15/SYNTH_A.B"
    assert (first.series_identifier, second.series_identifier) == (SERIES_A, SERIES_B)
    assert [row.line_number for row in document.rows] == [7, 8, 9, 10, 11, 12]
    assert document.rows[0].observed_on == date(2024, 1, 2)
    assert document.rows[0].cells == ("", "5.30")
    assert document.rows[2].cells == ("5.26", "ND")
    assert document.rows[5].cells == ("5.29", "")


def test_a_quoted_description_keeps_its_commas_and_doubled_quotes() -> None:
    data = _with_header_row(
        0,
        b'"Series Description","Synthetic rate A, quoted on an ""invented"" basis",'
        b'"Synthetic rate B (not real data)"',
    )

    document = _parse(data)
    series = _series(data, SERIES_A)

    expected = 'Synthetic rate A, quoted on an "invented" basis'
    assert document.columns[0].description == expected
    assert series.description == expected
    assert len(document.columns) == 2


def test_a_wide_sparse_row_with_a_trailing_comma_keeps_every_column() -> None:
    """Eleven synthetic columns, most of them empty, and an empty last cell."""
    names = tuple(f"SYNTH_{number:02d}.B" for number in range(1, 12))

    def header_row(label: str, cells: tuple[str, ...]) -> bytes:
        return ",".join(f'"{cell}"' for cell in (label, *cells)).encode("ascii")

    header = (
        header_row("Series Description", tuple(f"Synthetic {n}" for n in names)),
        header_row("Unit:", ("Percent:_Per_Year",) * 11),
        header_row("Multiplier:", ("1",) * 11),
        header_row("Currency:", ("NA",) * 11),
        header_row("Unique Identifier: ", tuple(f"H15/H15/{n}" for n in names)),
        header_row("Time Period", names),
    )
    rows = (
        b"2024-01-02,,,,1.11,,2.22,3.33,,4.44,5.55,",
        b"2024-01-03,,,,1.12,,2.23,3.34,,4.45,5.56,",
    )
    data = _document_bytes(header=header, rows=rows)

    document = _parse(data)

    assert tuple(column.series_identifier for column in document.columns) == names
    assert document.rows[0].cells == (
        "",
        "",
        "",
        "1.11",
        "",
        "2.22",
        "3.33",
        "",
        "4.44",
        "5.55",
        "",
    )
    fourth = build_public_daily_rate_series(
        document,
        series_identifier=names[3],
        lag_policy=_lag(),
        rights=_rights(names[3]),
    )
    assert [point.native_text for point in fourth.points] == ["1.11", "1.12"]
    with pytest.raises(H15ParseError, match="h15_series_never_published"):
        build_public_daily_rate_series(
            document,
            series_identifier=names[10],
            lag_policy=_lag(),
            rights=_rights(names[10]),
        )


def test_a_missing_final_newline_parses_to_the_same_rows() -> None:
    data = _document_bytes()

    assert _parse(data[:-1]).rows == _parse(data).rows
    assert _parse(data[:-1]).source_sha256 != _parse(data).source_sha256


# --- integrity before parsing --------------------------------------------


def test_a_wrong_sha256_is_refused_before_parsing() -> None:
    """Bytes that could never parse still fail on the digest, not the parser."""
    unparseable = b'\xff\xfe"not utf-8 and not a table\x00'
    wrong = sha256(b"some other bytes").hexdigest()

    with pytest.raises(H15ParseError, match="h15_sha256_mismatch"):
        parse_h15_csv(unparseable, expected_sha256=wrong, max_bytes=8192)
    with pytest.raises(H15ParseError, match="h15_sha256_mismatch"):
        parse_h15_csv(_document_bytes(), expected_sha256=wrong, max_bytes=8192)
    with pytest.raises(H15ParseError, match="h15_nul_byte"):
        _parse(unparseable)


def test_a_malformed_expected_digest_is_refused() -> None:
    data = _document_bytes()
    digest = sha256(data).hexdigest()

    for bad in (digest.upper(), digest[:-1], digest + "0", "", "sha256:" + digest):
        with pytest.raises(H15ParseError, match="h15_expected_sha256_invalid"):
            parse_h15_csv(data, expected_sha256=bad, max_bytes=8192)


def test_oversize_input_is_refused_before_hashing() -> None:
    data = _document_bytes()
    wrong = sha256(b"some other bytes").hexdigest()

    with pytest.raises(H15ParseError, match="h15_input_oversize"):
        _parse(data, max_bytes=len(data) - 1)
    with pytest.raises(H15ParseError, match="h15_input_oversize"):
        parse_h15_csv(data, expected_sha256=wrong, max_bytes=len(data) - 1)
    assert _parse(data, max_bytes=len(data)).source_byte_size == len(data)
    for bad_limit in (0, -1):
        with pytest.raises(H15ParseError, match="h15_max_bytes_invalid"):
            _parse(data, max_bytes=bad_limit)
    with pytest.raises(H15ParseError, match="h15_max_bytes_invalid"):
        _parse(data, max_bytes=True)


def test_empty_and_non_bytes_input_is_refused() -> None:
    with pytest.raises(H15ParseError, match="h15_input_empty"):
        _parse(b"")
    with pytest.raises(H15ParseError, match="h15_input_not_bytes"):
        parse_h15_csv(
            "text",  # type: ignore[arg-type]
            expected_sha256="0" * 64,
            max_bytes=8192,
        )


def test_undecodable_and_nul_bytes_are_refused() -> None:
    data = _document_bytes()

    with pytest.raises(H15ParseError, match="h15_not_utf8"):
        _parse(data.replace(b"Synthetic rate A", b"Synthetic rate \xff"))
    with pytest.raises(H15ParseError, match="h15_nul_byte"):
        _parse(data.replace(b"5.25", b"5.2\x00"))
    with pytest.raises(H15ParseError, match="h15_header_label_mismatch"):
        _parse(b"\xef\xbb\xbf" + data)


# --- refused cells --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    (
        "1e-2",
        "1E2",
        "NaN",
        "nan",
        "Infinity",
        "-",
        "+5.25",
        ".25",
        "5.",
        "5.2.5",
        " 5.25",
        "5.25 ",
        "5 .25",
        "N/A",
        "nd",
        "ND ",
        "NC",
        "0x10",
        "5_25",
        "\u0665.\u0662\u0665",
        "\uff15.\uff12\uff15",
        "5.25\u200b",
        "--5.25",
    ),
)
def test_a_cell_that_is_not_a_plain_decimal_or_a_known_marker_is_refused(
    text: str,
) -> None:
    with pytest.raises(H15ParseError, match="h15_cell_invalid") as caught:
        _parse(_with_cell(text))

    assert "line 8" in str(caught.value)
    assert SERIES_A in str(caught.value)


@pytest.mark.parametrize("text", ("5.25", "-0.05", "0", "0.000", "12", "0012.5000"))
def test_a_plain_decimal_cell_is_kept_as_its_native_text(text: str) -> None:
    series = _series(_with_cell(text), SERIES_A)

    first = series.points[0]
    assert (first.state, first.native_text) == ("value", text)
    assert first.value_percent is not None
    assert first.value_percent.as_tuple() == Decimal(text).as_tuple()


# --- refused headers and shapes ------------------------------------------


@pytest.mark.parametrize(
    ("index", "replacement"),
    (
        (0, b'"Series Descriptions","a","b"'),
        (0, b'"Series Description ","a","b"'),
        (1, b'"Unit","Percent:_Per_Year","Percent:_Per_Year"'),
        (1, b'"Unit: ","Percent:_Per_Year","Percent:_Per_Year"'),
        (2, b'"multiplier:","1","1"'),
        (2, b'"Multiplier: ","1","1"'),
        (3, b'"Currency","NA","NA"'),
        (3, b'"Currency: ","NA","NA"'),
        (4, b'"Unique Identifiers: ","H15/H15/SYNTH_A.B","H15/H15/SYNTH_B.B"'),
        (5, b'"Time Period ","SYNTH_A.B","SYNTH_B.B"'),
        (5, b'"Time Period:","SYNTH_A.B","SYNTH_B.B"'),
    ),
)
def test_a_wrong_header_label_is_refused(index: int, replacement: bytes) -> None:
    with pytest.raises(H15ParseError, match="h15_header_label_mismatch") as caught:
        _parse(_with_header_row(index, replacement))

    assert f"line {index + 1}" in str(caught.value)


#: The rest of the synthetic row-5 line, after its label cell.
SYNTHETIC_IDENTIFIER_CELLS = b',"H15/H15/SYNTH_A.B","H15/H15/SYNTH_B.B"'


def _with_identifier_label(label: str) -> bytes:
    """The synthetic document with the quoted row-5 label replaced."""
    quoted = b'"' + label.encode("ascii") + b'"'
    return _with_header_row(4, quoted + SYNTHETIC_IDENTIFIER_CELLS)


@pytest.mark.parametrize("label", ("Unique Identifier: ", "Unique Identifier:"))
def test_both_observed_spellings_of_the_identifier_label_are_accepted(
    label: str,
) -> None:
    """With and without the trailing space: the two spellings seen in real files."""
    data = _with_identifier_label(label)
    reference = _parse(_document_bytes())

    document = _parse(data)
    series = _series(data, SERIES_A)

    assert document.identifier_label == label
    assert document.columns == reference.columns
    assert document.rows == reference.rows
    assert series.points == _series(_document_bytes(), SERIES_A).points
    assert H15_IDENTIFIER_LABEL_SPELLINGS == (
        "Unique Identifier: ",
        "Unique Identifier:",
    )


def test_the_two_identifier_label_spellings_are_different_bytes() -> None:
    spaced = _with_identifier_label("Unique Identifier: ")
    bare = _with_identifier_label("Unique Identifier:")

    assert spaced == _document_bytes()
    assert len(spaced) == len(bare) + 1
    assert _parse(spaced).source_sha256 != _parse(bare).source_sha256
    assert _parse(spaced).identifier_label != _parse(bare).identifier_label


@pytest.mark.parametrize(
    "label",
    (
        "Unique Identifier:  ",
        "Unique Identifier:   ",
        " Unique Identifier:",
        " Unique Identifier: ",
        "unique identifier:",
        "unique identifier: ",
        "UNIQUE IDENTIFIER:",
        "Unique identifier:",
        "Unique Identifier",
        "Unique Identifier ",
        "Unique  Identifier:",
        "UniqueIdentifier:",
        "Unique Identifier::",
        "Unique Identifier: :",
        "Unique Identifier;",
        "Unique Identifiers:",
        "",
    ),
)
def test_any_third_spelling_of_the_identifier_label_is_refused(label: str) -> None:
    with pytest.raises(H15ParseError, match="h15_header_label_mismatch") as caught:
        _parse(_with_identifier_label(label))

    message = str(caught.value)
    assert "line 5" in message
    assert "'Unique Identifier: '" in message
    assert "'Unique Identifier:'" in message


def test_a_whitespace_variant_of_the_identifier_label_is_refused() -> None:
    for trailing in (b"\t", b"\xc2\xa0", b"\xe3\x80\x80"):
        row = b'"Unique Identifier:' + trailing + b'"' + SYNTHETIC_IDENTIFIER_CELLS

        with pytest.raises(H15ParseError, match="h15_header_label_mismatch"):
            _parse(_with_header_row(4, row))


def test_swapped_header_rows_are_refused() -> None:
    header = list(SYNTHETIC_HEADER_ROWS)
    header[2], header[3] = header[3], header[2]

    with pytest.raises(H15ParseError, match="h15_header_label_mismatch"):
        _parse(_document_bytes(header=tuple(header)))


def test_a_wrong_unit_or_multiplier_is_refused() -> None:
    with pytest.raises(H15ParseError, match="h15_unit_unexpected"):
        _parse(_with_header_row(1, b'"Unit:","Percent:_Per_Year","Index"'))
    with pytest.raises(H15ParseError, match="h15_unit_unexpected"):
        _parse(_with_header_row(1, b'"Unit:","percent:_per_year","Percent:_Per_Year"'))
    with pytest.raises(H15ParseError, match="h15_multiplier_unexpected"):
        _parse(_with_header_row(2, b'"Multiplier:","1","100"'))
    with pytest.raises(H15ParseError, match="h15_multiplier_unexpected"):
        _parse(_with_header_row(2, b'"Multiplier:","1.0","1"'))


def test_a_currency_other_than_na_is_refused_for_every_column() -> None:
    for replacement in (
        b'"Currency:","NA","USD"',
        b'"Currency:","USD","NA"',
        b'"Currency:","na","NA"',
        b'"Currency:","","NA"',
    ):
        with pytest.raises(H15ParseError, match="h15_currency_unexpected"):
            _parse(_with_header_row(3, replacement))
    assert {column.currency for column in _parse(_document_bytes()).columns} == {"NA"}


@pytest.mark.parametrize(
    ("index", "replacement"),
    (
        (0, b"Series Description,Synthetic rate A,Synthetic rate B"),
        (0, b'"Series Description",Synthetic rate A,"Synthetic rate B"'),
        (1, b'"Unit:",Percent:_Per_Year,"Percent:_Per_Year"'),
        (2, b'"Multiplier:", "1","1"'),
        (2, b'"Multiplier:","1",1'),
        (3, b'"Currency:",\'NA\',"NA"'),
        (4, b'"Unique Identifier: ",H15/H15/SYNTH_A.B,H15/H15/SYNTH_B.B'),
        (4, b'"Unique Identifier:",H15/H15/SYNTH_A.B,H15/H15/SYNTH_B.B'),
        (4, b'Unique Identifier:,"H15/H15/SYNTH_A.B","H15/H15/SYNTH_B.B"'),
        (4, b'Unique Identifier: ,"H15/H15/SYNTH_A.B","H15/H15/SYNTH_B.B"'),
        (5, b"Time Period,SYNTH_A.B,SYNTH_B.B"),
    ),
)
def test_a_header_row_not_in_the_exact_quoted_form_is_refused(
    index: int, replacement: bytes
) -> None:
    with pytest.raises(H15ParseError, match="h15_header_quoting_unexpected") as caught:
        _parse(_with_header_row(index, replacement))

    assert f"line {index + 1}" in str(caught.value)


def test_a_fully_unquoted_header_is_refused() -> None:
    unquoted = tuple(row.replace(b'"', b"") for row in SYNTHETIC_HEADER_ROWS)

    with pytest.raises(H15ParseError, match="h15_header_quoting_unexpected"):
        _parse(_document_bytes(header=unquoted))


@pytest.mark.parametrize(
    "row",
    (
        b'2024-01-03,"5.25",5.31',
        b'2024-01-03,5.25,"ND"',
        b'2024-01-03,"",5.31',
        b'"2024-01-03",5.25,5.31',
        b'2024-01-03,5.25,5.31"',
        b'2024-01-03,5.""25,5.31',
    ),
)
def test_a_double_quote_on_a_data_line_is_refused(row: bytes) -> None:
    rows = list(SYNTHETIC_DATA_ROWS)
    rows[1] = row

    with pytest.raises(H15ParseError, match="h15_data_quote_refused") as caught:
        _parse(_document_bytes(rows=tuple(rows)))

    assert "line 8" in str(caught.value)


def test_a_duplicate_or_inconsistent_identifier_is_refused() -> None:
    duplicate_ids = _document_bytes(
        header=(
            *SYNTHETIC_HEADER_ROWS[:4],
            b'"Unique Identifier: ","H15/H15/SYNTH_A.B","H15/H15/SYNTH_A.B"',
            b'"Time Period","SYNTH_A.B","SYNTH_A.B"',
        )
    )

    with pytest.raises(H15ParseError, match="h15_duplicate_series_identifier"):
        _parse(duplicate_ids)
    with pytest.raises(H15ParseError, match="h15_identifier_mismatch"):
        _parse(_with_header_row(5, b'"Time Period","SYNTH_A.B","SYNTH_C.B"'))
    with pytest.raises(H15ParseError, match="h15_identifier_invalid"):
        _parse(_with_header_row(5, b'"Time Period","SYNTH_A.B",""'))
    with pytest.raises(H15ParseError, match="h15_identifier_invalid"):
        _parse(_with_header_row(5, b'"Time Period","SYNTH_A.B"," SYNTH_B.B"'))


def test_a_ragged_row_is_refused() -> None:
    short = list(SYNTHETIC_DATA_ROWS)
    short[3] = b"2024-01-05,5.27"
    long = list(SYNTHETIC_DATA_ROWS)
    long[3] = b"2024-01-05,5.27,5.33,5.40"

    with pytest.raises(H15ParseError, match="h15_ragged_row") as caught:
        _parse(_document_bytes(rows=tuple(short)))
    assert "line 10" in str(caught.value)
    with pytest.raises(H15ParseError, match="h15_ragged_row"):
        _parse(_document_bytes(rows=tuple(long)))
    with pytest.raises(H15ParseError, match="h15_ragged_header"):
        _parse(_with_header_row(3, b'"Currency:","NA"'))
    with pytest.raises(H15ParseError, match="h15_no_series_columns"):
        _parse(
            _document_bytes(
                header=tuple(
                    row.split(b",", maxsplit=1)[0] for row in SYNTHETIC_HEADER_ROWS
                ),
                rows=(b"2024-01-02",),
            )
        )


def test_a_document_without_data_rows_is_refused() -> None:
    with pytest.raises(H15ParseError, match="h15_no_data_rows"):
        _parse(_document_bytes(rows=()))
    with pytest.raises(H15ParseError, match="h15_header_incomplete"):
        _parse(_document_bytes(header=SYNTHETIC_HEADER_ROWS[:5], rows=()))


@pytest.mark.parametrize(
    "text",
    (b"2024-02-30", b"2024-1-05", b"20240105", b"2024-01-05T00:00", b"", b"01/05/2024"),
)
def test_a_date_that_is_not_an_iso_calendar_date_is_refused(text: bytes) -> None:
    rows = list(SYNTHETIC_DATA_ROWS)
    rows[3] = text + b",,5.33"

    with pytest.raises(H15ParseError, match="h15_date_invalid") as caught:
        _parse(_document_bytes(rows=tuple(rows)))

    assert "line 10" in str(caught.value)


def test_a_blank_line_or_a_multi_line_cell_is_refused() -> None:
    blank = list(SYNTHETIC_DATA_ROWS)
    blank.insert(2, b"")
    multi_line = _with_header_row(
        0, b'"Series Description","Synthetic rate A\n(not real data)","b"'
    )
    unterminated = _document_bytes(rows=(*SYNTHETIC_DATA_ROWS, b'2024-01-10,"5.30,'))

    with pytest.raises(H15ParseError, match="h15_blank_line"):
        _parse(_document_bytes(rows=tuple(blank)))
    # A header cell split over two lines leaves an unterminated quote on line 1.
    with pytest.raises(H15ParseError, match="h15_csv_malformed") as caught:
        _parse(multi_line)
    assert "line 1" in str(caught.value)
    with pytest.raises(H15ParseError, match="h15_data_quote_refused"):
        _parse(unterminated)
    with pytest.raises(H15ParseError, match="h15_blank_line"):
        _parse(_document_bytes() + b"\n")
    with pytest.raises(H15ParseError, match="h15_blank_line"):
        _parse(_with_header_row(2, b""))


# --- line endings ---------------------------------------------------------


def test_crlf_and_lf_inputs_hash_differently_but_parse_to_equal_points() -> None:
    lf = _document_bytes(newline=b"\n")
    crlf = _document_bytes(newline=b"\r\n")

    assert sha256(lf).hexdigest() != sha256(crlf).hexdigest()
    assert _parse(lf).rows == _parse(crlf).rows
    assert _parse(lf).columns == _parse(crlf).columns
    series_lf = _series(lf, SERIES_B)
    series_crlf = _series(crlf, SERIES_B)
    assert series_lf.points == series_crlf.points
    assert series_lf.source_sha256 != series_crlf.source_sha256
    assert series_lf.source_byte_size + 12 == series_crlf.source_byte_size
    assert series_lf.series_hash != series_crlf.series_hash


def test_mixed_or_bare_carriage_returns_are_refused() -> None:
    lf = _document_bytes(newline=b"\n")
    crlf = _document_bytes(newline=b"\r\n")

    with pytest.raises(H15ParseError, match="h15_line_endings_mixed"):
        _parse(crlf.replace(b"\r\n", b"\n", 1))
    with pytest.raises(H15ParseError, match="h15_line_endings_mixed"):
        _parse(lf.replace(b"\n", b"\r"))
    with pytest.raises(H15ParseError, match="h15_line_endings_mixed"):
        _parse(lf.replace(b"5.25", b"5.2\r5"))


# --- building the series --------------------------------------------------


def test_nd_is_missing_and_an_empty_cell_is_not_published() -> None:
    data = _document_bytes()

    series_a = _series(data, SERIES_A)
    series_b = _series(data, SERIES_B)

    # Series A: the leading empty cell is dropped, the interior one is kept.
    assert [(p.observed_on.day, p.state, p.native_text) for p in series_a.points] == [
        (3, "value", "5.25"),
        (4, "value", "5.26"),
        (5, "not_published", ""),
        (8, "value", "5.28"),
        (9, "value", "5.29"),
    ]
    # Series B: ND is a missing observation, the trailing empty cell is kept.
    assert [(p.observed_on.day, p.state, p.native_text) for p in series_b.points] == [
        (2, "value", "5.30"),
        (3, "value", "5.31"),
        (4, "missing", "ND"),
        (5, "value", "5.33"),
        (8, "value", "5.34"),
        (9, "not_published", ""),
    ]
    assert series_b.points[2].value_percent is None
    assert series_a.points[2].value_percent is None


def test_a_fixed_cutoff_answer_does_not_change_when_later_rows_are_appended() -> None:
    """Trailing unpublished dates are kept, so an old value is not carried forward."""
    rows = (
        b"2024-01-04,3.10,5.30",
        b"2024-01-05,,5.31",
        b"2024-01-08,,5.32",
    )
    appended = (*rows, b"2024-01-10,3.40,5.33")
    cutoff = datetime(2024, 1, 9, 23, 0, tzinfo=UTC)

    before = _series(_document_bytes(rows=rows), SERIES_A)
    after = _series(_document_bytes(rows=appended), SERIES_A)

    assert [(p.observed_on.day, p.state) for p in before.points] == [
        (4, "value"),
        (5, "not_published"),
        (8, "not_published"),
    ]
    seen = before.value_as_of(cutoff)
    assert seen is not None
    assert (seen.observed_on, seen.state, seen.value_percent) == (
        date(2024, 1, 8),
        "not_published",
        None,
    )
    assert after.value_as_of(cutoff) == seen
    assert after.points[: len(before.points)] == before.points
    # Every instant before the appended row is released answers the same.
    first_new_release = after.points[-1].available_at
    instant = datetime(2024, 1, 4, 0, 0, tzinfo=UTC)
    compared = 0
    while instant < first_new_release:
        assert after.value_as_of(instant) == before.value_as_of(instant)
        instant += timedelta(hours=3)
        compared += 1
    assert compared > 50
    assert after.value_as_of(first_new_release) == after.points[-1]


def test_empty_cells_before_the_first_published_date_are_still_dropped() -> None:
    rows = (
        b"2024-01-02,,5.30",
        b"2024-01-03,,5.31",
        b"2024-01-04,3.10,5.32",
        b"2024-01-05,,5.33",
    )

    series = _series(_document_bytes(rows=rows), SERIES_A)

    assert [(p.observed_on.day, p.state) for p in series.points] == [
        (4, "value"),
        (5, "not_published"),
    ]
    assert series.value_as_of(datetime(2024, 1, 4, 23, 0, tzinfo=UTC)) is None


def test_a_value_keeps_its_native_text_and_exact_decimal() -> None:
    series = _series(_document_bytes(), SERIES_B)

    first = series.points[0]
    assert first.native_text == "5.30"
    assert first.value_percent == Decimal("5.30")
    assert str(first.value_percent) == "5.30"
    assert first.value_percent.as_tuple().exponent == -2


def test_the_built_series_records_its_source_and_modeled_availability() -> None:
    data = _document_bytes()

    series = _series(data, SERIES_A)

    assert series.source_id == FED_H15_SOURCE_ID
    assert series.series_identifier == SERIES_A
    assert series.description == "Synthetic rate A (not real data)"
    assert series.unit == "Percent:_Per_Year"
    assert series.source_sha256 == sha256(data).hexdigest()
    assert series.source_byte_size == len(data)
    assert series.lane == "exploratory"
    assert series.lag_policy == _lag()
    assert series.rights_record_hash == _rights(SERIES_A).record_hash
    assert series.acknowledged_limitations == PUBLIC_SERIES_REQUIRED_LIMITATIONS
    for point in series.points:
        assert point.available_at == modeled_available_at(point.observed_on, _lag())
    # Friday 5 January is released on Monday 8 January at the release minute.
    assert series.points[2].available_at == datetime.combine(
        date(2024, 1, 8), time(21, 15), tzinfo=UTC
    )


def test_an_unknown_series_is_refused() -> None:
    document = _parse(_document_bytes())

    for unknown in ("SYNTH_C.B", "synth_a.b", "H15/H15/SYNTH_A.B", ""):
        with pytest.raises(H15ParseError, match="h15_series_unknown"):
            build_public_daily_rate_series(
                document,
                series_identifier=unknown,
                lag_policy=_lag(),
                rights=_rights(SERIES_A),
            )
    with pytest.raises(H15ParseError, match="h15_series_unknown"):
        build_public_daily_rate_series(
            document,
            series_identifier=None,  # type: ignore[arg-type]
            lag_policy=_lag(),
            rights=_rights(SERIES_A),
        )


def test_a_series_that_was_never_published_is_refused() -> None:
    rows = tuple(row.rsplit(b",", maxsplit=1)[0] + b"," for row in SYNTHETIC_DATA_ROWS)

    with pytest.raises(H15ParseError, match="h15_series_never_published"):
        _series(_document_bytes(rows=rows), SERIES_B)


def test_dates_that_are_not_strictly_ascending_are_refused_when_building() -> None:
    swapped = list(SYNTHETIC_DATA_ROWS)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    repeated = list(SYNTHETIC_DATA_ROWS)
    repeated[2] = b"2024-01-03,5.26,ND"

    for rows in (swapped, repeated):
        document = _parse(_document_bytes(rows=tuple(rows)))
        assert len(document.rows) == 6
        with pytest.raises(H15ParseError, match="h15_dates_not_strictly_ascending"):
            build_public_daily_rate_series(
                document,
                series_identifier=SERIES_A,
                lag_policy=_lag(),
                rights=_rights(SERIES_A),
            )


def test_errors_are_drift_value_errors() -> None:
    with pytest.raises(H15ParseError) as caught:
        _parse(b"")

    assert isinstance(caught.value, DriftError)
    assert isinstance(caught.value, ValueError)


# --- quality points and the end-to-end path -------------------------------


def test_quality_points_keep_missing_and_unpublished_dates_as_markers() -> None:
    data = _document_bytes()

    points_a = quality_points(_series(data, SERIES_A))
    points_b = quality_points(_series(data, SERIES_B))

    assert all(isinstance(point, DatedValue) for point in points_a)
    assert [(p.value, p.missing_marker) for p in points_a] == [
        (Decimal("5.25"), None),
        (Decimal("5.26"), None),
        (None, H15_NOT_PUBLISHED_QUALITY_MARKER),
        (Decimal("5.28"), None),
        (Decimal("5.29"), None),
    ]
    assert points_b[2] == DatedValue(
        observed_on=date(2024, 1, 4),
        value=None,
        missing_marker="ND",
        available_at=datetime.combine(date(2024, 1, 5), time(21, 15), tzinfo=UTC),
    )


def test_end_to_end_parse_build_assess_and_require_passing() -> None:
    data = _document_bytes()
    series = _series(data, SERIES_A)
    policy = seal_data_quality_policy(
        policy_id="synthetic-daily-rate-policy",
        lower_bound=Decimal("-1"),
        upper_bound=Decimal("25"),
        max_abs_jump=Decimal("1"),
        jump_mode="absolute",
        max_stale_run=5,
        max_missing_run=1,
        hard_checks=ALL_DATA_QUALITY_CHECKS,
    )
    weekdays = tuple(date(2024, 1, day) for day in (3, 4, 5, 8, 9))
    cutoff = datetime(2024, 1, 10, 21, 15, tzinfo=UTC)

    report = assess_daily_values(
        quality_points(series),
        subject_kind="public_daily_series",
        subject_hash=series.series_hash,
        source_sha256=series.source_sha256,
        policy=policy,
        expected_dates=weekdays,
        cutoff=cutoff,
    )

    assert report.result is ValidationResult.PASS
    assert report.findings == ()
    assert {item.status for item in report.checks} == {"pass"}
    assert report.subject_hash == series.series_hash
    assert report.source_sha256 == sha256(data).hexdigest()
    require_passing(report)
    seen = series.value_as_of(cutoff)
    assert seen is not None
    assert (seen.observed_on, seen.value_percent) == (
        date(2024, 1, 9),
        Decimal("5.29"),
    )


def test_end_to_end_a_bad_series_fails_the_gate() -> None:
    rows = list(SYNTHETIC_DATA_ROWS)
    rows[4] = b"2024-01-08,95.28,5.34"
    series = _series(_document_bytes(rows=tuple(rows)), SERIES_A)
    policy = seal_data_quality_policy(
        policy_id="synthetic-daily-rate-policy",
        lower_bound=Decimal("-1"),
        upper_bound=Decimal("25"),
        max_abs_jump=Decimal("1"),
        jump_mode="absolute",
        max_stale_run=5,
        max_missing_run=1,
        hard_checks=ALL_DATA_QUALITY_CHECKS,
    )

    report = assess_daily_values(
        quality_points(series),
        subject_kind="public_daily_series",
        subject_hash=series.series_hash,
        source_sha256=series.source_sha256,
        policy=policy,
        expected_dates=None,
        cutoff=None,
    )

    assert report.result is ValidationResult.FAIL
    assert {item.code for item in report.findings} == {
        "absolute_jump_exceeds_limit",
        "value_above_upper_bound",
    }
    with pytest.raises(DriftError, match="data_quality_report_failed"):
        require_passing(report)
