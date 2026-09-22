"""Task 4 acquisition receipt, byte-layer, and secret-screening tests."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid7

import pytest
from pydantic import BaseModel, ConfigDict

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import (
    AcquisitionCompleteness,
    AcquisitionExecutionContextV1,
    AcquisitionPlanV1,
    AcquisitionReceiptV1,
    AcquisitionReconciliationV1,
    ByteLayerKind,
    ByteObjectV1,
    ByteTransformationOperation,
    ByteTransformationV1,
    NativeByteGraphV1,
    ObservedObjectV1,
    OriginEvidenceV1,
    OriginStatus,
    ProviderNativeLayerRuleV1,
    RequestIdentityV1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import ImmutableJSONValue
from drift.domain.qualification import (
    ConsumerPurpose,
    M1ePilotStateV1,
    PilotStage,
    PurposeStageStateV1,
)
from drift.qualification.acquisition import (
    build_acquisition_receipt,
    validate_secret_free_acquisition_payload,
    verify_acquisition_receipt,
)
from drift.qualification.lifecycle import transition_acquired
from drift.serialization.canonical import content_hash

FROZEN_PLAN_TIME = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
REQ_START = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
REQ_END = datetime(2026, 9, 13, 11, 5, tzinfo=UTC)


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def test_byte_layer_distinct_descriptor_hashes() -> None:
    data = b'{"bars": [1, 2, 3]}'
    c_hash = _digest(data)
    ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=c_hash,
        location=f"drift+sha256://{c_hash}",
    )

    obj_transport = ByteObjectV1(
        layer=ByteLayerKind.TRANSPORT_ENTITY,
        artifact_reference=ref,
        byte_size=len(data),
        content_hash=c_hash,
        media_type="application/json",
    )
    obj_decompressed = ByteObjectV1(
        layer=ByteLayerKind.DECOMPRESSED_PAYLOAD,
        artifact_reference=ref,
        byte_size=len(data),
        content_hash=c_hash,
        media_type="application/json",
    )

    # Distinct layers have distinct descriptor hashes even with equal content
    assert obj_transport.content_hash == obj_decompressed.content_hash
    assert obj_transport.descriptor_hash != obj_decompressed.descriptor_hash


def test_byte_graph_valid_acyclic_lineage() -> None:
    data_raw = b"compressed-bytes"
    data_decomp = b"decompressed-bytes"
    ref_raw = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=_digest(data_raw),
        location=f"drift+sha256://{_digest(data_raw)}",
    )
    ref_decomp = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=_digest(data_decomp),
        location=f"drift+sha256://{_digest(data_decomp)}",
    )

    root_obj = ByteObjectV1(
        layer=ByteLayerKind.TRANSPORT_ENTITY,
        artifact_reference=ref_raw,
        byte_size=len(data_raw),
        content_hash=ref_raw.content_hash,
        media_type="application/gzip",
    )
    leaf_obj = ByteObjectV1(
        layer=ByteLayerKind.DECODED_PROVIDER_NATIVE_RECORD,
        artifact_reference=ref_decomp,
        byte_size=len(data_decomp),
        content_hash=ref_decomp.content_hash,
        media_type="application/x-parquet",
    )

    transform = ByteTransformationV1(
        input_descriptor_hash=root_obj.descriptor_hash,
        output_descriptor_hash=leaf_obj.descriptor_hash,
        operation=ByteTransformationOperation.DECOMPRESS,
        tool_implementation_hash="a" * 64,
        lossless=True,
    )

    graph = NativeByteGraphV1(
        objects=(root_obj, leaf_obj),
        transformations=(transform,),
        retained_root_descriptor_hashes=(root_obj.descriptor_hash,),
        provider_native_leaf_descriptor_hashes=(leaf_obj.descriptor_hash,),
    )
    assert len(graph.objects) == 2
    assert graph.graph_hash is not None


def test_byte_graph_cycle_rejected() -> None:
    data = b"node-bytes"
    ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=_digest(data),
        location=f"drift+sha256://{_digest(data)}",
    )
    obj1 = ByteObjectV1(
        layer=ByteLayerKind.TRANSPORT_ENTITY,
        artifact_reference=ref,
        byte_size=len(data),
        content_hash=ref.content_hash,
        media_type="application/octet-stream",
    )
    obj2 = ByteObjectV1(
        layer=ByteLayerKind.DECOMPRESSED_PAYLOAD,
        artifact_reference=ref,
        byte_size=len(data),
        content_hash=ref.content_hash,
        media_type="application/octet-stream",
    )

    # Cycle: obj1 -> obj2 and obj2 -> obj1
    t1 = ByteTransformationV1(
        input_descriptor_hash=obj1.descriptor_hash,
        output_descriptor_hash=obj2.descriptor_hash,
        operation=ByteTransformationOperation.DECOMPRESS,
        tool_implementation_hash="a" * 64,
        lossless=True,
    )
    t2 = ByteTransformationV1(
        input_descriptor_hash=obj2.descriptor_hash,
        output_descriptor_hash=obj1.descriptor_hash,
        operation=ByteTransformationOperation.TRANSFER_DECODE,
        tool_implementation_hash="b" * 64,
        lossless=True,
    )

    with pytest.raises(ValueError, match="acyclic|cycle"):
        NativeByteGraphV1(
            objects=(obj1, obj2),
            transformations=(t1, t2),
            retained_root_descriptor_hashes=(obj1.descriptor_hash,),
            provider_native_leaf_descriptor_hashes=(obj2.descriptor_hash,),
        )


def test_provider_native_layer_rule_precedes_drift_normalization() -> None:
    # Attempting to declare DRIFT_CANONICAL_RECORD as provider native layer must fail
    with pytest.raises(
        ValueError, match="precedes Drift normalization|cannot be canonical record"
    ):
        ProviderNativeLayerRuleV1(
            profile_set_hash="1" * 64,
            supported_profile_hashes=("2" * 64,),
            product_schema_hash="3" * 64,
            methodology_hash="4" * 64,
            authoritative_native_layer=ByteLayerKind.DRIFT_CANONICAL_RECORD,
        )


@pytest.mark.parametrize(
    "secret_payload",
    [
        {"api_key": "secret123"},
        {"token": "bearer-abc"},
        {"Authorization": "Bearer xyz"},
        {"cookie": "session=abc"},
        {"url": "https://user:pass@provider.com/data"},
        {"signature": "deadbeef"},
        {"X-Amz-Signature": "sig123"},
        {"error": "Failed request with token sk_live_123456"},
    ],
)
def test_validate_secret_free_acquisition_payload_rejects_credentials(
    secret_payload: object,
) -> None:
    with pytest.raises(ValueError, match="secret|credential|token|api_key|signature"):
        validate_secret_free_acquisition_payload(secret_payload)


def test_acquisition_plan_frozen_after_request_start_rejected() -> None:
    # Acquisition plan frozen_at > request_start must be rejected
    plan = AcquisitionPlanV1(
        plan_id=uuid7(),
        authorization_hash="1" * 64,
        request_scope_hash="2" * 64,
        expected_inventory_hash="3" * 64,
        planned_native_layer_rule_hash="4" * 64,
        max_bytes=1000000,
        max_objects=100,
        max_pages=10,
        frozen_at=datetime(2026, 9, 13, 11, 30, tzinfo=UTC),  # after REQ_START
    )
    request = RequestIdentityV1(
        method="GET",
        authenticated_provider_host="data.provider.test",
        route_template="/v1/quotes",
        canonical_parameters={"symbols": "AAPL,MSFT"},
        requested_universe=("AAPL", "MSFT"),
        requested_fields=("bid", "ask"),
        requested_date_range=("2026-09-01", "2026-09-02"),
        request_start=REQ_START,
        request_end=REQ_END,
        client_request_id="cli-req-001",
    )

    with pytest.raises(
        ValueError, match="frozen_at.*request_start|precede request start"
    ):
        build_acquisition_receipt(
            plan=plan,
            authorization_hash="1" * 64,
            profile_set_hash="5" * 64,
            request=request,
            native_layer_rule=ProviderNativeLayerRuleV1(
                profile_set_hash="5" * 64,
                supported_profile_hashes=("6" * 64,),
                product_schema_hash="7" * 64,
                methodology_hash="8" * 64,
                authoritative_native_layer=ByteLayerKind.DECODED_PROVIDER_NATIVE_RECORD,
            ),
            byte_graph=NativeByteGraphV1(
                objects=(),
                transformations=(),
                retained_root_descriptor_hashes=(),
                provider_native_leaf_descriptor_hashes=(),
            ),
            pages=(),
            retries=(),
            observed_objects=(),
            expected_inventory_hash="3" * 64,
            reconciliation_hash="9" * 64,
            execution=AcquisitionExecutionContextV1(
                collector_id="collector-1",
                collector_version="1.0.0",
                collector_source_hash="a" * 64,
                invocation_id=uuid7(),
                executable_evidence_hashes=("b" * 64,),
                receipt_id=uuid7(),
                receipt_version="1",
                creation_time=REQ_END,
            ),
        )


def _make_sample_receipt() -> tuple[
    AcquisitionReceiptV1,
    dict[str, VerifiedArtifactBytes],
    AcquisitionPlanV1,
    AcquisitionReconciliationV1,
]:
    data = b'{"data": [1, 2, 3]}'
    c_hash = _digest(data)
    art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
    ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=c_hash,
        location=f"drift+sha256://{c_hash}",
    )
    byte_obj = ByteObjectV1(
        layer=ByteLayerKind.DECODED_PROVIDER_NATIVE_RECORD,
        artifact_reference=ref,
        byte_size=len(data),
        content_hash=c_hash,
        media_type="application/json",
    )
    graph = NativeByteGraphV1(
        objects=(byte_obj,),
        transformations=(),
        retained_root_descriptor_hashes=(byte_obj.descriptor_hash,),
        provider_native_leaf_descriptor_hashes=(byte_obj.descriptor_hash,),
    )
    rule = ProviderNativeLayerRuleV1(
        profile_set_hash="1" * 64,
        supported_profile_hashes=("2" * 64,),
        product_schema_hash="3" * 64,
        methodology_hash="4" * 64,
        authoritative_native_layer=ByteLayerKind.DECODED_PROVIDER_NATIVE_RECORD,
    )
    request = RequestIdentityV1(
        method="GET",
        authenticated_provider_host="api.exchange.test",
        route_template="/v1/data",
        canonical_parameters={"format": "json"},
        requested_universe=("TEST",),
        requested_fields=("close",),
        requested_date_range=("2026-09-01", "2026-09-02"),
        request_start=REQ_START,
        request_end=REQ_END,
        client_request_id="client-req-1",
    )
    plan = AcquisitionPlanV1(
        plan_id=uuid7(),
        authorization_hash="a0" + "0" * 62,
        request_scope_hash=content_hash(request),
        expected_inventory_hash="c0" + "0" * 62,
        planned_native_layer_rule_hash=content_hash(rule),
        max_bytes=1000000,
        max_objects=10,
        max_pages=5,
        frozen_at=FROZEN_PLAN_TIME,
    )
    reconciliation = AcquisitionReconciliationV1(
        expected_keys=("k1",),
        received_keys=("k1",),
        missing_keys=(),
        duplicate_keys=(),
        extra_keys=(),
        cursor_cycle_detected=False,
        cursor_chain=(),
        count_reconciled=True,
        snapshot_token_consistent=True,
        snapshot_tokens=("snap_1",),
        result=AcquisitionCompleteness.PASS,
        reasons=(),
    )
    execution = AcquisitionExecutionContextV1(
        collector_id="test-collector",
        collector_version="1.0",
        collector_source_hash="c" * 64,
        invocation_id=uuid7(),
        executable_evidence_hashes=("e" * 64,),
        receipt_id=uuid7(),
        receipt_version="1",
        creation_time=REQ_END,
    )
    receipt = build_acquisition_receipt(
        plan=plan,
        authorization_hash=plan.authorization_hash,
        profile_set_hash=rule.profile_set_hash,
        request=request,
        native_layer_rule=rule,
        byte_graph=graph,
        pages=(),
        retries=(),
        observed_objects=(),
        expected_inventory_hash=plan.expected_inventory_hash,
        reconciliation_hash=content_hash(reconciliation),
        execution=execution,
    )
    return receipt, {c_hash: art}, plan, reconciliation


def test_build_and_verify_acquisition_receipt_success() -> None:
    receipt, artifacts, _, _ = _make_sample_receipt()
    # verify must pass without exception
    verify_acquisition_receipt(receipt, artifacts)


def test_verify_acquisition_receipt_missing_artifact_fails() -> None:
    receipt, artifacts, _, _ = _make_sample_receipt()
    # Remove artifact from mapping
    with pytest.raises(ValueError, match="missing artifact|artifact not found"):
        verify_acquisition_receipt(receipt, {})


def test_verify_acquisition_receipt_hash_mismatch_fails() -> None:
    receipt, artifacts, _, _ = _make_sample_receipt()
    corrupted_data = b'{"data": [9, 9, 9]}'
    c_hash = next(iter(artifacts.keys()))
    corrupted_art = VerifiedArtifactBytes(
        data=corrupted_data, byte_size=len(corrupted_data), content_hash=c_hash
    )
    with pytest.raises(ValueError, match="hash mismatch|corrupt"):
        verify_acquisition_receipt(receipt, {c_hash: corrupted_art})


def test_lifecycle_transition_acquired_advances_stage() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]

    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )

    advanced = transition_acquired(
        state=state,
        receipt=receipt,
        plan=plan,
        reconciliation=reconciliation,
        artifacts=artifacts,
    )
    assert advanced.purpose_states[0].stage is PilotStage.ACQUIRED
    assert (
        content_hash(receipt)
        in advanced.purpose_states[0].reached_stage_artifact_hashes
    )


def test_lifecycle_transition_acquired_rejects_non_pass_reconciliation() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]

    # Modify reconciliation to FAIL
    reconciliation_fail = reconciliation.model_copy(
        update={"result": AcquisitionCompleteness.FAIL}
    )

    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )

    with pytest.raises(ValueError, match="completeness.*pass|cannot advance"):
        transition_acquired(
            state=state,
            receipt=receipt,
            plan=plan,
            reconciliation=reconciliation_fail,
            artifacts=artifacts,
        )


def test_lifecycle_transition_acquired_authorization_mismatch_fails() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    bad_receipt = receipt.model_copy(update={"authorization_hash": "99" * 32})
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]
    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    with pytest.raises(ValueError, match="authorization hash"):
        transition_acquired(
            state=state,
            receipt=bad_receipt,
            plan=plan,
            reconciliation=reconciliation,
            artifacts=artifacts,
        )


def test_lifecycle_transition_acquired_expected_inventory_mismatch_fails() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    bad_receipt = receipt.model_copy(update={"expected_inventory_hash": "88" * 32})
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]
    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    with pytest.raises(ValueError, match="expected inventory hash"):
        transition_acquired(
            state=state,
            receipt=bad_receipt,
            plan=plan,
            reconciliation=reconciliation,
            artifacts=artifacts,
        )


def test_lifecycle_transition_acquired_native_layer_rule_mismatch_fails() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    bad_plan = plan.model_copy(update={"planned_native_layer_rule_hash": "77" * 32})
    matching_receipt = receipt.model_copy(
        update={"acquisition_plan_hash": content_hash(bad_plan)}
    )
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]
    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    with pytest.raises(ValueError, match="native layer rule hash"):
        transition_acquired(
            state=state,
            receipt=matching_receipt,
            plan=bad_plan,
            reconciliation=reconciliation,
            artifacts=artifacts,
        )


def test_lifecycle_transition_acquired_request_scope_mismatch_fails() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    bad_plan = plan.model_copy(update={"request_scope_hash": "66" * 32})
    matching_receipt = receipt.model_copy(
        update={"acquisition_plan_hash": content_hash(bad_plan)}
    )
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]
    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    with pytest.raises(ValueError, match="request scope hash"):
        transition_acquired(
            state=state,
            receipt=matching_receipt,
            plan=bad_plan,
            reconciliation=reconciliation,
            artifacts=artifacts,
        )


def test_lifecycle_transition_acquired_limits_exceeded_fails() -> None:
    receipt, artifacts, plan, reconciliation = _make_sample_receipt()
    tight_plan = plan.model_copy(update={"max_bytes": 1})
    matching_receipt = receipt.model_copy(
        update={"acquisition_plan_hash": content_hash(tight_plan)}
    )
    prof_hash = receipt.native_layer_rule.supported_profile_hashes[0]
    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=receipt.profile_set_hash,
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=prof_hash,
                stage=PilotStage.ACQUISITION_AUTHORIZED,
                reached_stage_artifact_hashes=(plan.authorization_hash,),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    with pytest.raises(ValueError, match="max_bytes"):
        transition_acquired(
            state=state,
            receipt=matching_receipt,
            plan=tight_plan,
            reconciliation=reconciliation,
            artifacts=artifacts,
        )


def test_byte_graph_disconnected_object_fails() -> None:
    data1 = b"node-1"
    data2 = b"disconnected-node"
    ref1 = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=_digest(data1),
        location=f"drift+sha256://{_digest(data1)}",
    )
    ref2 = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=_digest(data2),
        location=f"drift+sha256://{_digest(data2)}",
    )
    obj1 = ByteObjectV1(
        layer=ByteLayerKind.TRANSPORT_ENTITY,
        artifact_reference=ref1,
        byte_size=len(data1),
        content_hash=ref1.content_hash,
        media_type="application/octet-stream",
    )
    obj2 = ByteObjectV1(
        layer=ByteLayerKind.DECOMPRESSED_PAYLOAD,
        artifact_reference=ref2,
        byte_size=len(data2),
        content_hash=ref2.content_hash,
        media_type="application/octet-stream",
    )

    with pytest.raises(ValueError, match="disconnected|undeclared"):
        NativeByteGraphV1(
            objects=(obj1, obj2),
            transformations=(),
            retained_root_descriptor_hashes=(obj1.descriptor_hash,),
            provider_native_leaf_descriptor_hashes=(obj1.descriptor_hash,),
        )


def test_stored_content_object_validation() -> None:
    from drift.domain.acquisition import StoredContentObjectV1

    c_hash = "1" * 64
    ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=c_hash,
        location=f"drift+sha256://{c_hash}",
    )
    # Negative size fails
    with pytest.raises(ValueError, match="byte size cannot be negative"):
        StoredContentObjectV1(
            content_hash=c_hash,
            byte_size=-1,
            location_reference=ref,
            rights_binding_hash="2" * 64,
            object_class="raw_transport",
            store_policy_hash="3" * 64,
        )

    # Mismatched location reference hash fails
    mismatched_ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash="4" * 64,
        location=f"drift+sha256://{'4' * 64}",
    )
    with pytest.raises(ValueError, match="location reference content hash"):
        StoredContentObjectV1(
            content_hash=c_hash,
            byte_size=10,
            location_reference=mismatched_ref,
            rights_binding_hash="2" * 64,
            object_class="raw_transport",
            store_policy_hash="3" * 64,
        )


def test_secret_screening_in_pages_and_json_payloads() -> None:
    from drift.domain.acquisition import PageReceiptV1

    bad_page = PageReceiptV1(
        page_identity="page-1",
        page_order=0,
        cursor_in=None,
        cursor_out=None,
        byte_object_descriptor_hashes=("0" * 64,),
        attempt_identity="attempt-bearer-token-12345",
        result="success",
    )
    with pytest.raises(ValueError, match="credential|pattern"):
        validate_secret_free_acquisition_payload(bad_page)

    json_str_with_secret = '{"api_key": "secret123"}'
    with pytest.raises(ValueError, match="credential|secret"):
        validate_secret_free_acquisition_payload(json_str_with_secret)


def _origin_evidence(
    safe_response_metadata: ImmutableJSONValue = None,
) -> OriginEvidenceV1:
    """Realistic verified origin evidence with populated provider_signatures."""
    return OriginEvidenceV1(
        origin_status=OriginStatus.VERIFIED,
        provider_request_id="req-7f3ac21b",
        provider_object_id="bars/AAPL/2026-09-01",
        safe_response_metadata=safe_response_metadata,
        tls_endpoint_identity="data.provider.test",
        provider_checksums=("crc32c:0e5b2a11",),
        provider_signatures=("sha256:" + "ab" * 32,),
    )


def _observed_object(evidence: OriginEvidenceV1) -> ObservedObjectV1:
    return ObservedObjectV1(
        provider_object_identity="bars/AAPL/2026-09-01",
        matched_expected_key="k1",
        page_identity="page-1",
        byte_object_descriptor_hashes=("d" * 64,),
        origin_evidence=evidence,
        observation_status="complete",
    )


def _build_receipt_with_observed(
    observed_objects: tuple[ObservedObjectV1, ...],
) -> AcquisitionReceiptV1:
    """Build a receipt whose only varying input is observed_objects."""
    rule = ProviderNativeLayerRuleV1(
        profile_set_hash="1" * 64,
        supported_profile_hashes=("2" * 64,),
        product_schema_hash="3" * 64,
        methodology_hash="4" * 64,
        authoritative_native_layer=ByteLayerKind.DECODED_PROVIDER_NATIVE_RECORD,
    )
    request = RequestIdentityV1(
        method="GET",
        authenticated_provider_host="data.provider.test",
        route_template="/v1/bars",
        canonical_parameters={"timeframe": "1Day"},
        requested_universe=("AAPL",),
        requested_fields=("close",),
        requested_date_range=("2026-09-01", "2026-09-02"),
        request_start=REQ_START,
        request_end=REQ_END,
        client_request_id="client-req-obs-1",
    )
    plan = AcquisitionPlanV1(
        plan_id=uuid7(),
        authorization_hash="a0" + "0" * 62,
        request_scope_hash=content_hash(request),
        expected_inventory_hash="c0" + "0" * 62,
        planned_native_layer_rule_hash=content_hash(rule),
        max_bytes=1000000,
        max_objects=10,
        max_pages=5,
        frozen_at=FROZEN_PLAN_TIME,
    )
    execution = AcquisitionExecutionContextV1(
        collector_id="test-collector",
        collector_version="1.0",
        collector_source_hash="c" * 64,
        invocation_id=uuid7(),
        executable_evidence_hashes=("e" * 64,),
        receipt_id=uuid7(),
        receipt_version="1",
        creation_time=REQ_END,
    )
    return build_acquisition_receipt(
        plan=plan,
        authorization_hash=plan.authorization_hash,
        profile_set_hash=rule.profile_set_hash,
        request=request,
        native_layer_rule=rule,
        byte_graph=NativeByteGraphV1(
            objects=(),
            transformations=(),
            retained_root_descriptor_hashes=(),
            provider_native_leaf_descriptor_hashes=(),
        ),
        pages=(),
        retries=(),
        observed_objects=observed_objects,
        expected_inventory_hash=plan.expected_inventory_hash,
        reconciliation_hash="9" * 64,
        execution=execution,
    )


def test_screener_allows_declared_model_field_named_provider_signatures() -> None:
    # provider_signatures is a declared OriginEvidenceV1 field name fixed by
    # Drift source, not a runtime-supplied key, so it is not a credential.
    validate_secret_free_acquisition_payload(_origin_evidence())


def test_build_acquisition_receipt_accepts_non_empty_observed_objects() -> None:
    observed = (_observed_object(_origin_evidence()),)
    receipt = _build_receipt_with_observed(observed)
    assert receipt.observed_objects == observed
    assert receipt.observed_objects[0].origin_evidence.provider_signatures == (
        "sha256:" + "ab" * 32,
    )


@pytest.mark.parametrize(
    ("credential_value", "expected_message"),
    [
        (
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            r"Secret credential pattern detected in payload",
        ),
        (
            "https://data.provider.test/v1/bars?api_key=AKIA1234567890",
            r"Potential credential term 'api_key' found in payload",
        ),
    ],
)
def test_build_acquisition_receipt_rejects_credential_value_in_observed_objects(
    credential_value: str, expected_message: str
) -> None:
    observed = (
        _observed_object(
            _origin_evidence(safe_response_metadata={"upstream_note": credential_value})
        ),
    )
    with pytest.raises(ValueError, match=expected_message):
        _build_receipt_with_observed(observed)


def test_build_acquisition_receipt_rejects_credential_named_data_key() -> None:
    # 'authorization' here is a runtime-supplied mapping key inside
    # safe_response_metadata, not a declared model field, so it stays screened.
    observed = (
        _observed_object(
            _origin_evidence(
                safe_response_metadata={"headers": {"authorization": "redacted"}}
            )
        ),
    )
    with pytest.raises(
        ValueError, match=r"credential parameter or header 'authorization' detected"
    ):
        _build_receipt_with_observed(observed)


def test_screener_still_screens_undeclared_extra_model_keys() -> None:
    # An extra key is runtime-supplied rather than declared in Drift source,
    # so the model-field exemption must not cover it.
    class PermissiveEnvelope(BaseModel):
        model_config = ConfigDict(extra="allow")

        note: str

    envelope = PermissiveEnvelope.model_validate(
        {"note": "ok", "authorization": "redacted"}
    )
    with pytest.raises(
        ValueError, match=r"credential parameter or header 'authorization' detected"
    ):
        validate_secret_free_acquisition_payload(envelope)
