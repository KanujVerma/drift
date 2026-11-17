"""Stage 1 synthetic E1 account-origin coordinator, dependent on #547 PR A.

Only the evaluator's actual opening-book observer can create the original
allocation record. This joins verified E1 structure to local SQLite retention,
not to an authenticated production RESULT, scheduler grant, or scored trial.
The origin configuration must be supplied by the trusted local host/harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from threading import Lock
from uuid import UUID

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    EvaluationRunIdentityV2,
)
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.evaluator.opening_book_lifecycle import (
    OriginalInvocationBindingV1,
    copy_original_invocation_binding,
)
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
    money = (
        opening_book.cash_balance,
        opening_book.net_asset_value,
        opening_book.holdings_market_value,
        opening_book.pending_claims_value,
        opening_book.realized_gross_pnl,
        opening_book.realized_net_pnl,
        opening_book.cumulative_transaction_costs,
    )
    if any(type(value) is not Decimal for value in money):
        raise LocalAccountReceiptError("ORIGINAL_BOOK_FORGED_DECIMAL_TYPE")
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
        # Freeze an independent value graph BEFORE any E1 verifier runs.
        # Slots/frozen dataclasses can still be mutated via object.__setattr__.
        # No later allocation field reads a caller-owned E1 object.
        captured_campaign = deepcopy(campaign)
        captured_arms = deepcopy(tuple(arms))
        captured_bindings = deepcopy(tuple(bindings))
        captured_runs = deepcopy(tuple(expected_run_ids))
        captured_provenance = deepcopy(provenance)
        if captured_campaign.campaign_type != "SYNTHETIC_TEST":
            raise LocalAccountReceiptError("ONLY_SYNTHETIC_E1_ALLOCATIONS")
        verify_stage1_synthetic_br_configuration(
            campaign=captured_campaign,
            arms=captured_arms,
            bindings=captured_bindings,
            expected_run_ids=captured_runs,
        )
        verify_stage1_trial_provenance_snapshot(
            snapshot=captured_provenance,
            campaign=captured_campaign,
            arms=captured_arms,
            bindings=captured_bindings,
            expected_run_ids=captured_runs,
        )
        selected = captured_provenance.scope.run_account_binding
        selected_arms = [
            a for a in captured_arms if a.arm_id == captured_provenance.scope.arm_id
        ]
        matching = [
            b
            for b in captured_bindings
            if b.campaign_id == selected.campaign_id
            and b.run_id == selected.run_id
            and b.arm_id == selected.arm_id
        ]
        if len(selected_arms) != 1 or len(matching) != 1 or matching[0] != selected:
            raise LocalAccountReceiptError("E1_ACCOUNT_NOT_IN_FULL_MANIFEST")
        self._campaign = captured_campaign
        self._arms = captured_arms
        self._bindings = captured_bindings
        self._runs = captured_runs
        self._provenance = captured_provenance
        # Source reference is observed only for tamper detection. It is NEVER
        # authoritative for retained account fields or hashes after this point.
        self._source_provenance = provenance
        self._arm = selected_arms[0]
        self._binding = selected
        self._manifest = captured_provenance.scope.complete_manifest_fingerprint
        self._store = store
        self._lock = Lock()
        self._phase = "new"
        self._original_book: PortfolioStateV2 | None = None
        self._original_bytes: bytes | None = None
        self._allocation: (
            tuple[UUID, LocalEventReferenceV1, LocalEventReferenceV1] | None
        ) = None
        self._fields: AccountAllocationFieldsV1 | None = None
        self._claim: LocalEventReferenceV1 | None = None
        self._consumption: LocalEventReferenceV1 | None = None
        self._invocation_binding: OriginalInvocationBindingV1 | None = None

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

    def _assert_e1_source_unchanged(self) -> None:
        """Refuse changed caller provenance, using only trusted captured E1."""
        try:
            verify_stage1_trial_provenance_snapshot(
                snapshot=self._source_provenance,
                campaign=self._campaign,
                arms=self._arms,
                bindings=self._bindings,
                expected_run_ids=self._runs,
            )
        except (TypeError, ValueError) as error:
            raise LocalAccountReceiptError(
                "E1_PROVENANCE_MUTATED_AFTER_VALIDATION"
            ) from error
        if self._source_provenance != self._provenance:
            raise LocalAccountReceiptError("E1_PROVENANCE_MUTATED_AFTER_VALIDATION")

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
            self._assert_e1_source_unchanged()
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
                bound_at=self._binding.bound_at,
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
                fields=fields,
                original_book=original,
                precommit_guard=self._assert_e1_source_unchanged,
            )
            self._assert_e1_source_unchanged()
            witness_ref = self._store.witness_original_readback(
                allocation_id=allocation_id,
                allocation_ref=receipt_ref,
                precommit_guard=self._assert_e1_source_unchanged,
            )
            self._assert_e1_source_unchanged()
            readback = self._store.readback_allocation(
                allocation_id=allocation_id,
                allocation_ref=receipt_ref,
                witness_ref=witness_ref,
                expected_fields=fields,
                postread_guard=self._assert_e1_source_unchanged,
            )
            if readback.original_book_bytes != original:
                raise LocalAccountReceiptError("ORIGINAL_BOOK_READBACK_DIFFERENT")
            self._assert_e1_source_unchanged()
            # Only after original bytes and the witness are independently
            # read from this host's configured read-only ledger.
            self._original_book = opening_book
            self._original_bytes = original
            self._fields = fields
            self._allocation = (allocation_id, receipt_ref, witness_ref)
        except BaseException:
            self._fail()
            raise
        self._transition("retaining", "ready")

    def verified_original(self) -> OriginalLocalAccountReadbackV1:
        # Only the detached original E1 values are allowed to label ledger
        # evidence. A mutable caller-owned alias may change while SQLite
        # readback runs, so verify on both sides of the readback boundary.
        self._assert_e1_source_unchanged()
        if self._allocation is None or self._fields is None:
            raise LocalAccountReceiptError("ORIGINAL_ACCOUNT_NOT_RETAINED")
        allocation_id, allocation_ref, witness_ref = self._allocation
        readback = self._store.readback_allocation(
            allocation_id=allocation_id,
            allocation_ref=allocation_ref,
            witness_ref=witness_ref,
            expected_fields=self._fields,
            postread_guard=self._assert_e1_source_unchanged,
        )
        # Also guard the return boundary if an injected adapter changes
        # caller-owned provenance after the underlying readback completes.
        self._assert_e1_source_unchanged()
        return readback

    def _require_same_original(self, opening_book: PortfolioStateV2) -> None:
        if opening_book is not self._original_book or self._original_bytes is None:
            raise LocalAccountReceiptError("NOT_ORIGINAL_ENGINE_BOOK_INSTANCE")
        money = (
            opening_book.cash_balance,
            opening_book.net_asset_value,
            opening_book.holdings_market_value,
            opening_book.pending_claims_value,
            opening_book.realized_gross_pnl,
            opening_book.realized_net_pnl,
            opening_book.cumulative_transaction_costs,
        )
        if any(type(value) is not Decimal for value in money):
            raise LocalAccountReceiptError("ORIGINAL_BOOK_FORGED_DECIMAL_TYPE")
        if canonical_json(opening_book) != self._original_bytes:
            raise LocalAccountReceiptError("ORIGINAL_ENGINE_BOOK_CHANGED")

    def claim_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        self._claim_original_invocation(
            opening_book=opening_book,
            run_identity=run_identity,
            binding=None,
            bound=False,
        )

    def claim_bound_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1,
    ) -> None:
        """Claim one actual prepared invocation without changing M2 identity."""
        self._claim_original_invocation(
            opening_book=opening_book,
            run_identity=run_identity,
            binding=binding,
            bound=True,
        )

    def _claim_original_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1 | None,
        bound: bool,
    ) -> None:
        self._transition("ready", "claiming")
        try:
            if bound and binding is None:
                raise LocalAccountReceiptError("ORIGINAL_INVOCATION_BINDING_MISSING")
            captured_binding = (
                copy_original_invocation_binding(binding)
                if binding is not None
                else None
            )
            self._assert_e1_source_unchanged()
            self._require_same_original(opening_book)
            if type(run_identity) not in (
                EvaluationRunIdentityV1,
                EvaluationRunIdentityV2,
            ):
                raise LocalAccountReceiptError("INVALID_ORIGINAL_RUN_IDENTITY")
            readback = self.verified_original()
            if (
                run_identity.admission_hash != readback.fields.admission_hash
                or run_identity.protocol_hash != readback.fields.protocol_hash
            ):
                raise LocalAccountReceiptError("RUN_IDENTITY_ACCOUNT_MISMATCH")
            claim = self._store.append_invocation_claim(
                original=readback,
                identity_hash=run_identity.run_identity_hash,
                invocation_binding=(
                    copy_original_invocation_binding(captured_binding)
                    if captured_binding is not None
                    else None
                ),
                precommit_guard=self._assert_e1_source_unchanged,
            )
            # If untrusted source data changes inside an injected ledger
            # adapter after append, preserve the original durable audit
            # event but fail this transition rather than claiming success.
            self._assert_e1_source_unchanged()
            self._claim = claim
            # Neither the caller nor a store adapter receives this captured
            # graph. Each boundary gets another detached set of UUID leaves.
            self._invocation_binding = captured_binding
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
        self._observe_original_consumption(
            opening_book=opening_book,
            run_identity=run_identity,
            binding=None,
            bound=False,
        )

    def observe_bound_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1,
    ) -> None:
        """Consume only under the exact previously retained claim binding."""
        self._observe_original_consumption(
            opening_book=opening_book,
            run_identity=run_identity,
            binding=binding,
            bound=True,
        )

    def _observe_original_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1 | None,
        bound: bool,
    ) -> None:
        self._transition("claimed", "consuming")
        try:
            if bound and binding is None:
                raise LocalAccountReceiptError("ORIGINAL_INVOCATION_BINDING_MISSING")
            captured_binding = (
                copy_original_invocation_binding(binding)
                if binding is not None
                else None
            )
            if captured_binding != self._invocation_binding:
                raise LocalAccountReceiptError("CONSUMPTION_CLAIM_BINDING_MISMATCH")
            self._assert_e1_source_unchanged()
            self._require_same_original(opening_book)
            if type(run_identity) not in (
                EvaluationRunIdentityV1,
                EvaluationRunIdentityV2,
            ):
                raise LocalAccountReceiptError("INVALID_ORIGINAL_RUN_IDENTITY")
            if self._claim is None:
                raise LocalAccountReceiptError("ORIGINAL_INVOCATION_CLAIM_MISSING")
            readback = self.verified_original()
            event_ref = self._store.append_consumption(
                original=readback,
                claim_ref=self._claim,
                identity_hash=run_identity.run_identity_hash,
                invocation_binding=(
                    copy_original_invocation_binding(captured_binding)
                    if captured_binding is not None
                    else None
                ),
                precommit_guard=self._assert_e1_source_unchanged,
            )
            self._assert_e1_source_unchanged()
            self._consumption = event_ref
        except BaseException:
            self._fail()
            raise
        self._transition("consuming", "consumed")
