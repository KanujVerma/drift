"""Stage 1 synthetic E1 account-origin coordinator, dependent on #547 PR A.

Only the evaluator's actual opening-book observer can create the original
allocation record. This joins verified E1 structure to local SQLite retention,
not to an authenticated production RESULT, scheduler grant, or scored trial.
The origin configuration must be supplied by the trusted local host/harness.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from threading import Lock
from typing import Sequence

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    EvaluationRunIdentityV2,
)
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    AccountAllocationFieldsV1,
    LocalAccountReceiptError,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    OriginalLocalAccountReadbackV1,
)
from drift.serialization.canonical import canonical_json, content_hash


def _fresh_book_bytes(
    *,
    opening_book: PortfolioStateV2,
    admission: EvaluationAdmissionV1,
    protocol: EvaluationProtocolV1,
    expected_initial_cash: Decimal,
) -> bytes:
    """Refuse type-forged or nonfresh book before its bytes reach the ledger."""
    if type(opening_book) is not PortfolioStateV2:
        raise LocalAccountReceiptError("ORIGINAL_BOOK_WRONG_EXACT_TYPE")
    if type(opening_book.cash_balance) is not Decimal:
        raise LocalAccountReceiptError("ORIGINAL_BOOK_FORGED_DECIMAL_TYPE")
    if type(opening_book.net_asset_value) is not Decimal:
        raise LocalAccountReceiptError("ORIGINAL_NAV_FORGED_DECIMAL_TYPE")
    if (
        opening_book.admission_hash != admission.admission_hash
        or opening_book.cash_balance != protocol.initial_cash
        or opening_book.cash_balance != expected_initial_cash
        or opening_book.net_asset_value != expected_initial_cash
        or opening_book.lane != admission.lane
        or opening_book.holdings
        or opening_book.pending_cash_claims
        or opening_book.settled_claim_ids
        or opening_book.applied_effect_ids
        or opening_book.mark is not None
        or opening_book.holdings_market_value != 0
        or opening_book.pending_claims_value != 0
        or opening_book.realized_gross_pnl != 0
        or opening_book.realized_net_pnl != 0
        or opening_book.cumulative_transaction_costs != 0
    ):
        raise LocalAccountReceiptError("ORIGINAL_BOOK_NOT_ENGINE_FRESH")
    source = canonical_json(opening_book)
    rebuilt = PortfolioStateV2.model_validate_json(source)
    if canonical_json(rebuilt) != source:
        raise LocalAccountReceiptError("ORIGINAL_BOOK_NOT_CANONICAL")
    return source


class Stage1SyntheticAccountLifecycleV1:
    """One allocation for (campaign, run, arm) with immutable issuer readback.

    The selected E1 checkpoint identifies a request's source manifest. It is
    never part of the platform allocation key, which survives checkpoints.
    No issuer-authenticated E6B or trading eligibility is returned here.
    """

    def __init__(
        self,
        *,
        campaign: CampaignSpecV1,
        arms: Sequence[ArmSpecV1],
        bindings: Sequence[RunAccountBindingV1],
        expected_run_ids: Sequence[str],
        provenance: Stage1TrialProvenanceSnapshotV1,
        store: LocalSyntheticAccountReceiptStoreV1,
    ) -> None:
        captured_arms = tuple(arms)
        captured_bindings = tuple(bindings)
        captured_runs = tuple(expected_run_ids)
        if campaign.campaign_type != "SYNTHETIC_TEST":
            raise LocalAccountReceiptError("ONLY_SYNTHETIC_E1_ALLOCATIONS")
        verify_stage1_synthetic_br_configuration(
            campaign=campaign, arms=captured_arms,
            bindings=captured_bindings, expected_run_ids=captured_runs,
        )
        verify_stage1_trial_provenance_snapshot(
            snapshot=provenance, campaign=campaign, arms=captured_arms,
            bindings=captured_bindings, expected_run_ids=captured_runs,
        )
        selected = provenance.scope.run_account_binding
        selected_arms = [
            a for a in captured_arms if a.arm_id == provenance.scope.arm_id
        ]
        matching = [
            b for b in captured_bindings
            if b.campaign_id == selected.campaign_id
            and b.run_id == selected.run_id and b.arm_id == selected.arm_id
        ]
        if (
            len(selected_arms) != 1 or len(matching) != 1
            or matching[0] != selected
        ):
            raise LocalAccountReceiptError("E1_ACCOUNT_NOT_IN_FULL_MANIFEST")
        self._campaign = campaign
        self._arm = selected_arms[0]
        self._binding = selected
        self._manifest = provenance.scope.complete_manifest_fingerprint
        self._store = store
        self._lock = Lock()
        self._phase = "new"
        self._original_book: PortfolioStateV2 | None = None
        self._original_bytes: bytes | None = None
        self._allocation: tuple[
            object, LocalEventReferenceV1, LocalEventReferenceV1
        ] | None = None
        self._claim: LocalEventReferenceV1 | None = None
        self._consumption: LocalEventReferenceV1 | None = None

    @property
    def local_phase(self) -> str:
        return self._phase

    @property
    def original_issuer_authenticated_for_e6b(self) -> bool:
        return False

    def _transition(self, expected: str, next_phase: str) -> None:
        with self._lock:
            if self._phase != expected:
                raise LocalAccountReceiptError(
                    f"ACCOUNT_LIFECYCLE_INVALID_TRANSITION:{self._phase}"
                )
            self._phase = next_phase

    def _fail(self) -> None:
        with self._lock:
            self._phase = "failed"

    def retain_original_book(
        self,
        *,
        opening_book: PortfolioStateV2,
        admission: EvaluationAdmissionV1,
        protocol: EvaluationProtocolV1,
        currency_code: str,
    ) -> None:
        self._transition("new", "retaining")
        try:
            if type(currency_code) is not str or currency_code != self._arm.currency:
                raise LocalAccountReceiptError("ORIGINAL_BOOK_CURRENCY_MISMATCH")
            original = _fresh_book_bytes(
                opening_book=opening_book,
                admission=admission,
                protocol=protocol,
                expected_initial_cash=Decimal(self._binding.initial_cash_allocated),
            )
            fields = AccountAllocationFieldsV1(
                campaign_id=self._campaign.campaign_id,
                run_id=self._binding.run_id,
                arm_id=self._binding.arm_id,
                portfolio_account_id=self._binding.portfolio_account_id,
                binding_id=self._binding.binding_id,
                binding_hash=content_hash(asdict(self._binding)),
                campaign_fingerprint=self._campaign.campaign_spec_fingerprint,
                arm_fingerprint=self._arm.arm_spec_fingerprint,
                complete_manifest_fingerprint=self._manifest,
                admission_hash=admission.admission_hash,
                protocol_hash=protocol.protocol_hash,
                first_session_fingerprint=content_hash(opening_book.session_key),
                initial_cash=self._binding.initial_cash_allocated,
                currency=currency_code,
            )
            allocation_id, receipt_ref = self._store.append_allocation(
                fields=fields, original_book=original,
            )
            witness_ref = self._store.witness_original_readback(
                allocation_id=allocation_id, allocation_ref=receipt_ref,
            )
            readback = self._store.readback_allocation(
                allocation_id=allocation_id, allocation_ref=receipt_ref,
                witness_ref=witness_ref, expected_fields=fields,
            )
            if readback.original_book_bytes != original:
                raise LocalAccountReceiptError("ORIGINAL_BOOK_READBACK_DIFFERENT")
            # Only after original bytes and the witness are independently
            # read from this host's configured read-only ledger.
            self._original_book = opening_book
            self._original_bytes = original
            self._allocation = (allocation_id, receipt_ref, witness_ref)
        except BaseException:
            self._fail()
            raise
        self._transition("retaining", "ready")

    def verified_original(self) -> OriginalLocalAccountReadbackV1:
        if self._allocation is None or self._original_book is None:
            raise LocalAccountReceiptError("ORIGINAL_ACCOUNT_NOT_RETAINED")
        allocation_id, allocation_ref, witness_ref = self._allocation
        fields = AccountAllocationFieldsV1(
            campaign_id=self._campaign.campaign_id,
            run_id=self._binding.run_id,
            arm_id=self._binding.arm_id,
            portfolio_account_id=self._binding.portfolio_account_id,
            binding_id=self._binding.binding_id,
            binding_hash=content_hash(asdict(self._binding)),
            campaign_fingerprint=self._campaign.campaign_spec_fingerprint,
            arm_fingerprint=self._arm.arm_spec_fingerprint,
            complete_manifest_fingerprint=self._manifest,
            admission_hash=self._original_book.admission_hash,
            protocol_hash=self._protocol_hash,
            first_session_fingerprint=content_hash(self._original_book.session_key),
            initial_cash=self._binding.initial_cash_allocated,
            currency=self._arm.currency,
        )
        return self._store.readback_allocation(
            allocation_id=allocation_id,
            allocation_ref=allocation_ref,
            witness_ref=witness_ref,
            expected_fields=fields,
        )

    def _require_same_original(self, opening_book: PortfolioStateV2) -> None:
        if opening_book is not self._original_book or self._original_bytes is None:
            raise LocalAccountReceiptError("NOT_ORIGINAL_ENGINE_BOOK_INSTANCE")
        if type(opening_book.cash_balance) is not Decimal:
            raise LocalAccountReceiptError("ORIGINAL_BOOK_FORGED_DECIMAL_TYPE")
        if canonical_json(opening_book) != self._original_bytes:
            raise LocalAccountReceiptError("ORIGINAL_ENGINE_BOOK_CHANGED")

    def claim_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        self._transition("ready", "claiming")
        try:
            self._require_same_original(opening_book)
            if type(run_identity) not in (
                EvaluationRunIdentityV1, EvaluationRunIdentityV2
            ):
                raise LocalAccountReceiptError("INVALID_ORIGINAL_RUN_IDENTITY")
            readback = self.verified_original()
            if (
                run_identity.admission_hash != readback.fields.admission_hash
                or run_identity.protocol_hash != readback.fields.protocol_hash
            ):
                raise LocalAccountReceiptError("RUN_IDENTITY_ACCOUNT_MISMATCH")
            claim = self._store.append_invocation_claim(
                original=readback, identity_hash=run_identity.run_identity_hash,
            )
            self._claim = claim
        except BaseException:
            self._fail()
            raise
        self._transition("claiming", "claimed")

    def observe_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        self._transition("claimed", "consuming")
        try:
            self._require_same_original(opening_book)
            if self._claim is None:
                raise LocalAccountReceiptError("ORIGINAL_INVOCATION_CLAIM_MISSING")
            readback = self.verified_original()
            event_ref = self._store.append_consumption(
                original=readback,
                claim_ref=self._claim,
                identity_hash=run_identity.run_identity_hash,
            )
            self._consumption = event_ref
        except BaseException:
            self._fail()
            raise
        self._transition("consuming", "consumed")
