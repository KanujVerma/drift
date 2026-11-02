"""Versioned trusted-local-host adapter for original Stage 1 producer evidence.

The host appoints this configuration out of band. Receipts cannot select a
ledger, issuer, account manifest or clock. This is not external authentication,
independent scientific acceptance, or permission to place orders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from drift.domain.observation_query import drift_source_inventory_hash
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_provenance import Stage1TrialProvenanceSnapshotV1
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_controlled_readback import (
    ControlledCampaignReadbackV1,
    read_controlled_campaign,
)
from drift.serialization.canonical import content_hash

LOCAL_AUTHORITY_PROFILE: Literal["drift-stage1-installed-local-authority/1"] = (
    "drift-stage1-installed-local-authority/1"
)


@dataclass(frozen=True, slots=True)
class LocalAuthorityVerificationV1:
    profile: Literal["drift-stage1-installed-local-authority/1"]
    configuration_hash: str
    original: ControlledCampaignReadbackV1

    @property
    def local_contract_verified(self) -> bool:
        return self.original.status == "VERIFIED_COMPLETE"

    @property
    def scientifically_qualified(self) -> bool:
        return False

    @property
    def authorizes_trading(self) -> bool:
        return False


class Stage1OriginalEvidenceReader(Protocol):
    """Replaceable reader, not a receipt-controlled plugin or credential bus."""

    def read(
        self,
        *,
        allocation_id: UUID,
        provenance: Stage1TrialProvenanceSnapshotV1,
        as_of_event_hash: str | None = None,
    ) -> LocalAuthorityVerificationV1: ...


@dataclass(frozen=True, slots=True)
class ConfiguredStage1LocalAuthorityV1:
    """One installed host, source revision, original root and frozen E1 scope.

    Construct only from trusted application configuration, never from model
    output or a receipt. Replacing this with a provider-backed adapter requires
    that provider's original verifier. A matching hash is not issuer authority.
    """

    origin: ConfiguredLocalSyntheticOriginV1
    campaign: CampaignSpecV1
    arms: tuple[ArmSpecV1, ...]
    bindings: tuple[RunAccountBindingV1, ...]
    expected_run_ids: tuple[str, ...]
    installed_source_hash: str
    appointment_reference: str
    clock: Callable[[], datetime]

    def __post_init__(self) -> None:
        if type(self.origin) is not ConfiguredLocalSyntheticOriginV1:
            raise ValueError("AUTHORITY_EXACT_CONFIGURED_ORIGIN_REQUIRED")
        if not self.appointment_reference.strip():
            raise ValueError("AUTHORITY_HOST_APPOINTMENT_REQUIRED")
        if self.installed_source_hash != drift_source_inventory_hash():
            raise ValueError("AUTHORITY_INSTALLED_SOURCE_MISMATCH")
        if any(
            type(value) is not tuple
            for value in (self.arms, self.bindings, self.expected_run_ids)
        ):
            raise ValueError("AUTHORITY_IMMUTABLE_HOST_SCOPE_REQUIRED")
        verify_stage1_synthetic_br_configuration(
            campaign=self.campaign,
            arms=self.arms,
            bindings=self.bindings,
            expected_run_ids=self.expected_run_ids,
        )

    @property
    def configuration_hash(self) -> str:
        return content_hash(
            {
                "profile": LOCAL_AUTHORITY_PROFILE,
                "root": str(self.origin.ledger_path),
                "issuer": self.origin.issuer_instance_id,
                "campaign": self.campaign.campaign_spec_fingerprint,
                "arms": tuple(a.arm_spec_fingerprint for a in self.arms),
                "bindings": tuple(asdict(b) for b in self.bindings),
                "runs": self.expected_run_ids,
                "installed_source": self.installed_source_hash,
                "appointment": self.appointment_reference,
            }
        )

    def read(
        self,
        *,
        allocation_id: UUID,
        provenance: Stage1TrialProvenanceSnapshotV1,
        as_of_event_hash: str | None = None,
    ) -> LocalAuthorityVerificationV1:
        # Recheck the trusted configuration and delegate every original ledger,
        # account, grant, K1, chronology, cost and RESULT check to the real reader.
        self.__post_init__()
        if not self.origin.ledger_path.is_file():
            raise ValueError("AUTHORITY_ORIGINAL_ROOT_UNAVAILABLE")
        report = read_controlled_campaign(
            origin=self.origin,
            allocation_id=allocation_id,
            campaign=self.campaign,
            arms=self.arms,
            bindings=self.bindings,
            expected_run_ids=self.expected_run_ids,
            provenance=provenance,
            clock=self.clock,
            as_of_event_hash=as_of_event_hash,
        )
        return LocalAuthorityVerificationV1(
            profile=LOCAL_AUTHORITY_PROFILE,
            configuration_hash=self.configuration_hash,
            original=report,
        )
