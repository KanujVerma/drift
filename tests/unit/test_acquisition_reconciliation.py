"""Task 4 acquisition reconciliation and closed-world tests."""

from datetime import UTC, datetime
from uuid import uuid7

from drift.domain.acquisition import (
    AcquisitionCompleteness,
    ExpectedInventoryV1,
    ExpectedObjectV1,
    ObservedObjectV1,
    OriginEvidenceV1,
    OriginStatus,
    PageReceiptV1,
    RetryReceiptV1,
)
from drift.qualification.acquisition import reconcile_acquisition

FROZEN_AT = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
REQUEST_START = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)


def _make_expected(
    keys: tuple[str, ...],
    *,
    frozen_at: datetime = FROZEN_AT,
    justification: str = "Authoritative exchange product catalog",
    source: str = "exchange_spec_v1",
    expected_count: int | None = None,
) -> ExpectedInventoryV1:
    return ExpectedInventoryV1(
        inventory_id=uuid7(),
        objects=tuple(
            ExpectedObjectV1(
                object_key=key,
                endpoint_or_file=f"/data/{key}.parquet",
                as_of_universe_rule="russell_3000_as_of",
                fields=("ticker", "open", "high", "low", "close", "volume"),
                dates=("2026-09-01", "2026-09-02"),
                partitions=(),
                expected_count=expected_count,
                source_of_enumeration=source,
                justification=justification,
            )
            for key in sorted(keys)
        ),
        enumeration_source=source,
        justification=justification,
        frozen_at=frozen_at,
    )


def _make_observed(
    key: str,
    *,
    page_id: str = "page_1",
    origin_status: OriginStatus = OriginStatus.VERIFIED,
    desc_hash: str = "0" * 64,
    provider_id: str | None = None,
) -> ObservedObjectV1:
    return ObservedObjectV1(
        provider_object_identity=provider_id or f"prov_{key}",
        matched_expected_key=key,
        page_identity=page_id,
        byte_object_descriptor_hashes=(desc_hash,),
        origin_evidence=OriginEvidenceV1(
            origin_status=origin_status,
            provider_request_id="req-123",
            provider_object_id=provider_id or f"prov_{key}",
            tls_endpoint_identity="api.provider.test:443"
            if origin_status is OriginStatus.VERIFIED
            else None,
        ),
        observation_status="observed",
    )


def _make_page(
    page_id: str,
    order: int,
    *,
    cursor_in: str | None = None,
    cursor_out: str | None = None,
    desc_hashes: tuple[str, ...] = ("0" * 64,),
    attempt_id: str = "attempt_1",
) -> PageReceiptV1:
    return PageReceiptV1(
        page_identity=page_id,
        page_order=order,
        cursor_in=cursor_in,
        cursor_out=cursor_out,
        byte_object_descriptor_hashes=desc_hashes,
        attempt_identity=attempt_id,
        result="success",
    )


def test_reconcile_exact_complete_pass() -> None:
    expected = _make_expected(("obj1", "obj2"))
    pages = (
        _make_page("p1", 0, cursor_out="next_p2"),
        _make_page("p2", 1, cursor_in="next_p2"),
    )
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj2", page_id="p2"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
        snapshot_token="v1_snapshot",
    )
    assert result.result is AcquisitionCompleteness.PASS
    assert result.missing_keys == ()
    assert result.extra_keys == ()
    assert not result.cursor_cycle_detected


def test_reconcile_expected_inventory_not_frozen_before_request_fails() -> None:
    # If inventory was frozen AFTER request started, it cannot verify completeness
    expected = _make_expected(
        ("obj1",), frozen_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    )
    pages = (_make_page("p1", 0),)
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.UNKNOWN
    assert any("not frozen before request start" in reason for reason in result.reasons)


def test_reconcile_missing_expected_object_fails() -> None:
    expected = _make_expected(("obj1", "obj2"))
    pages = (_make_page("p1", 0),)
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert result.missing_keys == ("obj2",)


def test_reconcile_extra_object_fails() -> None:
    expected = _make_expected(("obj1",))
    pages = (_make_page("p1", 0),)
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj_unexpected", page_id="p1"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert "obj_unexpected" in result.extra_keys


def test_reconcile_duplicate_page_without_retry_identity_fails() -> None:
    expected = _make_expected(("obj1",))
    # Two pages with the same page_identity without retry link
    pages = (_make_page("p1", 0), _make_page("p1", 1))
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert any("duplicate page" in reason for reason in result.reasons)


def test_reconcile_conflicting_duplicate_bytes_fails() -> None:
    expected = _make_expected(("obj1",))
    pages = (_make_page("p1", 0), _make_page("p2", 1))
    # Same object observed twice with conflicting descriptor hashes
    obs1 = _make_observed("obj1", page_id="p1", desc_hash="a" * 64)
    obs2 = _make_observed("obj1", page_id="p2", desc_hash="b" * 64)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=(obs1, obs2),
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert any("conflicting duplicate" in reason for reason in result.reasons)


def test_reconcile_exact_duplicate_declared_retry_may_pass() -> None:
    expected = _make_expected(("obj1",))
    pages = (_make_page("p1", 0, attempt_id="att1"),)
    retries = (
        RetryReceiptV1(
            attempt_identity="att0",
            attempt_order=1,
            page_identity="p1",
            result="timeout",
        ),
    )
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        retries=retries,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.PASS


def test_reconcile_cursor_cycle_fails() -> None:
    expected = _make_expected(("obj1", "obj2"))
    # Cursor cycle: p1 -> p2 -> p1
    pages = (
        _make_page("p1", 0, cursor_in="c1", cursor_out="c2"),
        _make_page("p2", 1, cursor_in="c2", cursor_out="c1"),
        _make_page("p3", 2, cursor_in="c1"),
    )
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj2", page_id="p2"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert result.cursor_cycle_detected


def test_reconcile_cursor_discontinuity_fails() -> None:
    expected = _make_expected(("obj1", "obj2"))
    # p1 cursor_out "c2", but p2 cursor_in is "c3" (gap)
    pages = (
        _make_page("p1", 0, cursor_out="c2"),
        _make_page("p2", 1, cursor_in="c3"),
    )
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj2", page_id="p2"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert any("cursor" in reason for reason in result.reasons)


def test_reconcile_missing_origin_proof_is_unknown() -> None:
    expected = _make_expected(("obj1",))
    pages = (_make_page("p1", 0),)
    # Origin status is UNKNOWN
    observed = (
        _make_observed("obj1", page_id="p1", origin_status=OriginStatus.UNKNOWN),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.UNKNOWN
    assert any("origin" in reason for reason in result.reasons)


def test_reconcile_snapshot_token_conflict_fails() -> None:
    expected = _make_expected(("obj1", "obj2"))
    pages = (_make_page("p1", 0), _make_page("p2", 1))
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj2", page_id="p2"),
    )

    # Conflicting snapshot tokens between pages/records
    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
        snapshot_token=("token_A", "token_B"),
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert not result.snapshot_token_consistent


def test_reconcile_different_response_order_preserves_native_order_and_passes() -> None:
    expected = _make_expected(("obj1", "obj2"))
    # Arrived in order obj2 then obj1
    pages = (_make_page("p1", 0),)
    observed = (
        _make_observed("obj2", page_id="p1"),
        _make_observed("obj1", page_id="p1"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.PASS
    # native order preserved in received_keys
    assert result.received_keys == ("obj2", "obj1")


def test_reconcile_unclosed_open_pagination_fails() -> None:
    expected = _make_expected(("obj1",))
    # Terminal page still has cursor_out pointing to unretrieved page
    pages = (_make_page("p1", 0, cursor_out="next_unfetched_page"),)
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert any("unclosed pagination" in r for r in result.reasons)


def test_reconcile_cursor_out_loop_detected() -> None:
    expected = _make_expected(("obj1", "obj2"))
    # p1 cursor_in "c1", cursor_out "c2"
    # p2 cursor_in "c2", cursor_out "c1" (loops back to c1)
    pages = (
        _make_page("p1", 0, cursor_in="c1", cursor_out="c2"),
        _make_page("p2", 1, cursor_in="c2", cursor_out="c1"),
    )
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj2", page_id="p2"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert result.cursor_cycle_detected


def test_reconcile_undeclared_duplicate_object_fails() -> None:
    expected = _make_expected(("obj1",))
    pages = (_make_page("p1", 0),)
    # obj1 observed twice, no retry declared
    observed = (
        _make_observed("obj1", page_id="p1"),
        _make_observed("obj1", page_id="p1"),
    )

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        retries=(),
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert any("without declared retry" in r for r in result.reasons)


def test_reconcile_expected_count_mismatch_fails() -> None:
    # Expected object requires exactly 3 occurrences
    expected_obj = ExpectedObjectV1(
        object_key="obj1",
        endpoint_or_file="/data/obj1.parquet",
        as_of_universe_rule="russell_3000_as_of",
        fields=("ticker", "close"),
        dates=("2026-09-01", "2026-09-02"),
        partitions=(),
        expected_count=3,
        source_of_enumeration="spec",
        justification="authoritative catalog",
    )
    expected = ExpectedInventoryV1(
        inventory_id=uuid7(),
        objects=(expected_obj,),
        enumeration_source="spec",
        justification="authoritative catalog",
        frozen_at=FROZEN_AT,
    )
    pages = (_make_page("p1", 0),)
    observed = (_make_observed("obj1", page_id="p1"),)

    result = reconcile_acquisition(
        expected=expected,
        pages=pages,
        observed=observed,
        request_start=REQUEST_START,
    )
    assert result.result is AcquisitionCompleteness.FAIL
    assert not result.count_reconciled
    assert any("count mismatch" in r for r in result.reasons)
