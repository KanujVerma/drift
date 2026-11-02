"""A configured original root is not replaceable through candidate evidence."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid7

import pytest
from test_stage1_controlled_contracts import controlled_arguments

from drift.domain.observation_query import drift_source_inventory_hash
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
from drift.loop.stage1_local_authority import ConfiguredStage1LocalAuthorityV1


def test_original_local_authority_reader_is_bound_and_nonoperational(
    tmp_path: Path,
) -> None:
    args = controlled_arguments(tmp_path)
    execution = execute_controlled_campaign(**args)
    configured = ConfiguredStage1LocalAuthorityV1(
        **{
            key: args[key]
            for key in (
                "origin",
                "campaign",
                "arms",
                "bindings",
                "expected_run_ids",
                "clock",
            )
        },
        installed_source_hash=drift_source_inventory_hash(),
        appointment_reference="synthetic-test:owner-appointed-local-root",
    )
    verified = configured.read(
        allocation_id=execution.allocation_id, provenance=args["provenance"]
    )
    assert verified.local_contract_verified
    assert not verified.scientifically_qualified
    assert not verified.authorizes_trading
    assert not verified.original.g2_accepted
    assert verified.configuration_hash == configured.configuration_hash
    with pytest.raises(ValueError):
        configured.read(allocation_id=uuid7(), provenance=args["provenance"])
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        replace(configured, installed_source_hash="f" * 64)
    with pytest.raises(ValueError, match="APPOINTMENT_REQUIRED"):
        replace(configured, appointment_reference=" ")
    wrong_issuer = replace(
        configured,
        origin=ConfiguredLocalSyntheticOriginV1(configured.origin.ledger_path, uuid7()),
    )
    with pytest.raises(ValueError):
        wrong_issuer.read(
            allocation_id=execution.allocation_id, provenance=args["provenance"]
        )
    missing_root = replace(
        configured,
        origin=ConfiguredLocalSyntheticOriginV1(
            tmp_path / "not-the-original.sqlite3", configured.origin.issuer_instance_id
        ),
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        missing_root.read(
            allocation_id=execution.allocation_id, provenance=args["provenance"]
        )
    assert not missing_root.origin.ledger_path.exists()
