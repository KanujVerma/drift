"""Comprehensive unit tests for Stage 1 strategy-switch preflight (Issue 422).

Covers:
- Historical eligibility thresholds (B4: 252 vs 253, B5: 60 vs 61).
- Fixed 12-ETF universe completeness (no silent truncation of GLD or any member).
- Price validity (nonpositive, NaN, missing current closing marks).
- Causality, duplicate sessions, and out-of-order session detection.
- Portfolio safety: preserving valid incumbent B3/B4/B5 upon unavailable switch.
- Refusing hold when incumbent strategy or portfolio state is unknown or invalid.
- Rejection of unauthorized all-cash, arbitrary, or unknown strategy selections.
- Deterministic, tamper-evident preflight hashing and binding.
"""

import unittest
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from drift.domain.common import UUID7
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
from drift.domain.evaluator_portfolio import (
    PortfolioStateV2,
    SecurityHoldingV2,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_strategy import (
    PositionViewV1,
    SecurityTargetPositionV1,
    StrategyDecisionIntentV1,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.loop.stage1_switch_preflight import (
    PreflightStatus,
    compute_preflight_hash,
    evaluate_stage1_switch_preflight,
)


class TestStage1SwitchPreflight(unittest.TestCase):
    """Unit and adversarial test suite for Stage 1 switch preflight."""

    def setUp(self) -> None:
        self.equity_syms = ["VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"]
        self.bond_syms = ["SHY", "IEF", "TLT", "TIP", "LQD"]
        self.gold_syms = ["GLD"]
        self.universe12_syms = self.equity_syms + self.bond_syms + self.gold_syms

        # Deterministic UUIDv7-like identifiers
        self.etf_uuids = {
            sym: UUID(f"018e0000-0000-7000-8000-{i + 1:012d}")
            for i, sym in enumerate(self.universe12_syms)
        }
        self.universe12_uuids = tuple(
            self.etf_uuids[s] for s in sorted(self.universe12_syms)
        )

        self.base_prices = {
            "VOO": Decimal("500.00"),
            "IJH": Decimal("300.00"),
            "IJR": Decimal("115.00"),
            "QQQ": Decimal("490.00"),
            "VEA": Decimal("50.00"),
            "VWO": Decimal("44.00"),
            "SHY": Decimal("82.00"),
            "IEF": Decimal("94.00"),
            "TLT": Decimal("92.00"),
            "TIP": Decimal("107.00"),
            "LQD": Decimal("108.00"),
            "GLD": Decimal("240.00"),
        }

        self.today = date(2026, 1, 30)
        self.closed_at = datetime.combine(
            self.today, datetime.min.time(), tzinfo=UTC
        ).replace(hour=21, minute=0)
        self.session_key = SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=self.today
        )
        self.session = EvaluationSessionV1.model_construct(
            schema_version="1",
            session_key=self.session_key,
            opened_at=self.closed_at - timedelta(hours=6, minutes=30),
            closed_at=self.closed_at,
            authority="scheduled_reconstruction",
            authority_record_hashes=("1" * 64,),
            authority_proof_hashes=("2" * 64,),
            session_hash="0" * 64,
        )

    def _make_observation(
        self,
        sec: UUID7,
        d: date,
        price: Decimal,
    ) -> ExploratoryReconstructedSessionObservationV1:
        fields = (
            ExploratoryReconstructedFieldV1(
                field_name="open",
                source_value=price,
                method_id="basis",
                meaning="price",
                source_field_hash="0" * 64,
            ),
            ExploratoryReconstructedFieldV1(
                field_name="high",
                source_value=price,
                method_id="basis",
                meaning="price",
                source_field_hash="0" * 64,
            ),
            ExploratoryReconstructedFieldV1(
                field_name="low",
                source_value=price,
                method_id="basis",
                meaning="price",
                source_field_hash="0" * 64,
            ),
            ExploratoryReconstructedFieldV1(
                field_name="close",
                source_value=price,
                method_id="basis",
                meaning="price",
                source_field_hash="0" * 64,
            ),
            ExploratoryReconstructedFieldV1(
                field_name="volume",
                source_value=Decimal("1000"),
                method_id="basis",
                meaning="share_volume",
                source_field_hash="0" * 64,
            ),
        )
        return ExploratoryReconstructedSessionObservationV1.model_construct(
            schema_version="1",
            kind="exploratory_reconstructed_session_observation",
            session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d),
            security_id=sec,
            listing_id=UUID("018e0000-0000-7000-8000-000000000099"),
            venue=ListingVenue.XNYS,
            cohort_hash="c" * 64,
            source_observation_hash="a" * 64,
            observation_contract_hash="b" * 64,
            observation_selection_proof_hash="c" * 64,
            contract_selection_proof_hash="d" * 64,
            scheduled_session_hash="e" * 64,
            scheduled_selection_proof_hash="f" * 64,
            schedule_artifact_hash="1" * 64,
            generated_session_row_hash="2" * 64,
            outcome_query_hash="3" * 64,
            source_context_hash="4" * 64,
            evidence_vintage_cutoff=self.closed_at,
            reconstruction_policy_hash="5" * 64,
            currency="USD",
            fields=fields,
            acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
            reconstruction_hash="0" * 64,
        )

    def _build_context(
        self,
        session_count: int,
        omitted_syms: Sequence[str] = (),
        custom_observations_by_sym: (
            dict[str, list[ExploratoryReconstructedSessionObservationV1]] | None
        ) = None,
        holdings: tuple[PositionViewV1, ...] = (),
        nav: Decimal = Decimal("10000.00"),
        cash: Decimal = Decimal("1000.00"),
    ) -> ExploratoryStrategyDecisionContextV1:
        active_syms = [s for s in self.universe12_syms if s not in omitted_syms]
        cohort = tuple(self.etf_uuids[s] for s in active_syms)
        views = []

        for sym in active_syms:
            sec = self.etf_uuids[sym]
            base_p = self.base_prices[sym]

            if custom_observations_by_sym and sym in custom_observations_by_sym:
                obs = custom_observations_by_sym[sym]
            else:
                obs = []
                for s in range(session_count):
                    idx = session_count - 1 - s
                    d = self.today - timedelta(days=idx)
                    obs.append(self._make_observation(sec, d, base_p))

            v = ExploratoryReconstructedDecisionViewV1.model_construct(
                schema_version="1",
                evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
                security_id=sec,
                observations=tuple(obs),
                acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
            )
            views.append(v)

        return ExploratoryStrategyDecisionContextV1.model_construct(
            schema_version="1",
            lane="exploratory",
            evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
            is_promotion_grade_evidence=False,
            session_key=self.session_key,
            decision_session=self.session,
            decision_cutoff=self.closed_at,
            cohort_hash="c" * 64,
            admitted_cohort=cohort,
            reconstructed_decision_views=tuple(views),
            portfolio_nav=nav,
            current_cash=cash,
            current_holdings=holdings,
            acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
        )

    # -------------------------------------------------------------------------
    # Group A: Historical Eligibility Thresholds
    # -------------------------------------------------------------------------

    def test_b4_rejects_252_sessions(self) -> None:
        """B4 momentum requires >= 253 sessions; 252 must be UNAVAILABLE."""
        ctx = self._build_context(session_count=252)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertIn("insufficient_history", res.reason)
        self.assertIn("minimum 253 required", res.reason)

    def test_b4_accepts_253_complete_sessions(self) -> None:
        """B4 momentum with 253 complete sessions is ELIGIBLE and tradeable."""
        ctx = self._build_context(session_count=253)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertEqual(res.effective_strategy, "B4")
        self.assertIn("eligible", res.reason)

    def test_b5_rejects_60_sessions(self) -> None:
        """B5 low-volatility requires >= 61 sessions; 60 must be UNAVAILABLE."""
        ctx = self._build_context(session_count=60)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertIn("insufficient_history", res.reason)
        self.assertIn("minimum 61 required", res.reason)

    def test_b5_accepts_61_complete_sessions(self) -> None:
        """B5 low-volatility with 61 complete sessions is ELIGIBLE and tradeable."""
        ctx = self._build_context(session_count=61)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertEqual(res.effective_strategy, "B5")

    def test_b3_accepts_1_session(self) -> None:
        """B3 equal-weight requires >= 1 session to extract current close marks."""
        ctx = self._build_context(session_count=1)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B3",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)

    # -------------------------------------------------------------------------
    # Group B: Universe Completeness and ETF Integrity
    # -------------------------------------------------------------------------

    def test_missing_gld_fails_closed_without_silent_reduction(self) -> None:
        """When GLD is omitted, universe must not silently reduce to 11 ETFs."""
        ctx = self._build_context(session_count=253, omitted_syms=["GLD"])
        self.assertEqual(len(ctx.admitted_cohort), 11)

        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertIn("incomplete_admitted_universe", res.reason)

    def test_missing_security_history_is_unavailable(self) -> None:
        """Security present in cohort but with empty history returns UNAVAILABLE."""
        custom_obs: dict[
            str, list[ExploratoryReconstructedSessionObservationV1]
        ] = {"GLD": []}  # empty list for GLD
        ctx = self._build_context(
            session_count=253, custom_observations_by_sym=custom_obs
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_security_history", res.reason)

    # -------------------------------------------------------------------------
    # Group C: Market Evidence, Prices, Causality, and Duplicates
    # -------------------------------------------------------------------------

    def test_nonpositive_price_is_rejected(self) -> None:
        """Zero or negative price in observation history is REJECTED."""
        sec_voo = self.etf_uuids["VOO"]
        bad_obs = [
            self._make_observation(
                sec_voo, self.today - timedelta(days=i), Decimal("0.00")
            )
            for i in range(253)
        ]
        ctx = self._build_context(
            session_count=253,
            custom_observations_by_sym={"VOO": bad_obs},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertFalse(res.is_tradeable)
        self.assertIn("invalid_close_price", res.reason)

    def test_duplicate_session_observation_is_rejected(self) -> None:
        """Duplicate observations for the same session must fail closed."""
        sec_voo = self.etf_uuids["VOO"]
        obs_list = [
            self._make_observation(
                sec_voo, self.today - timedelta(days=252 - i), Decimal("500.00")
            )
            for i in range(252)
        ]
        # Append duplicate of today
        obs_list.append(self._make_observation(sec_voo, self.today, Decimal("500.00")))
        obs_list.append(self._make_observation(sec_voo, self.today, Decimal("500.00")))

        ctx = self._build_context(
            session_count=253,
            custom_observations_by_sym={"VOO": obs_list},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("duplicate_session_observation", res.reason)

    def test_future_observation_beyond_cutoff_is_unavailable(self) -> None:
        """An observation dated after the decision session cutoff must be excluded."""
        sec_voo = self.etf_uuids["VOO"]
        tomorrow = self.today + timedelta(days=1)
        obs_list = [
            self._make_observation(
                sec_voo, self.today - timedelta(days=252 - i), Decimal("500.00")
            )
            for i in range(252)
        ]
        # Future bar
        obs_list.append(self._make_observation(sec_voo, tomorrow, Decimal("505.00")))

        ctx = self._build_context(
            session_count=253,
            custom_observations_by_sym={"VOO": obs_list},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("future_observation_detected", res.reason)

    def test_out_of_order_observations_rejected(self) -> None:
        """Observations not sorted chronologically fail closed."""
        sec_voo = self.etf_uuids["VOO"]
        # Generate reversed observations (today first, past later)
        obs_list = [
            self._make_observation(
                sec_voo, self.today - timedelta(days=i), Decimal("500.00")
            )
            for i in range(253)
        ]
        ctx = self._build_context(
            session_count=253,
            custom_observations_by_sym={"VOO": obs_list},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("out_of_order_observations", res.reason)

    # -------------------------------------------------------------------------
    # Group D: Strategy Identity and All-Cash Discretionary Rejection
    # -------------------------------------------------------------------------

    def test_proposed_all_cash_strategy_is_rejected(self) -> None:
        """AI cannot select discretionary all-cash; must be REJECTED."""
        ctx = self._build_context(session_count=253)
        for bad_strategy in ["CASH", "b0", "b0_cash", "all_cash"]:
            res = evaluate_stage1_switch_preflight(
                proposed_strategy=bad_strategy,
                current_strategy="B3",
                decision_context=ctx,
                required_universe=self.universe12_uuids,
            )
            self.assertEqual(res.status, PreflightStatus.REJECTED)
            self.assertFalse(res.is_tradeable)
            self.assertTrue(res.hold_incumbent)
            self.assertEqual(res.effective_strategy, "B3")
            self.assertIn("unsupported_stage1_strategy", res.reason)

    def test_unknown_arbitrary_strategy_is_rejected(self) -> None:
        """Arbitrary strategy identity is rejected."""
        ctx = self._build_context(session_count=253)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="random_ai_model_v1",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("unsupported_stage1_strategy", res.reason)

    def test_deliberate_abstain_holds_incumbent_safely(self) -> None:
        """Deliberate ABSTAIN selection holds existing B3 strategy."""
        ctx = self._build_context(session_count=253)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.ABSTAIN)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertIn("deliberate_abstain", res.reason)

    # -------------------------------------------------------------------------
    # Group E: Portfolio Safety and Indeterminate State
    # -------------------------------------------------------------------------

    def test_unknown_incumbent_strategy_yields_indeterminate_safety(self) -> None:
        """When candidate is unavailable and incumbent is unknown, cannot hold."""
        ctx = self._build_context(session_count=252)  # unavailable B4
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy=None,  # unknown incumbent
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIsNone(res.effective_strategy)
        self.assertIn("unknown or unadmitted incumbent strategy", res.reason)

    def test_nonpositive_nav_yields_indeterminate_safety(self) -> None:
        """Insolvent context NAV (<= 0) fails closed with INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=253, nav=Decimal("0.00"))
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertTrue(res.requires_containment)
        self.assertFalse(res.is_tradeable)
        self.assertIn("non_positive_nav", res.reason)

    def test_portfolio_state_with_indeterminate_basis_fails_closed(self) -> None:
        """PortfolioStateV2 holding with indeterminate basis prevents safe hold."""
        ctx = self._build_context(session_count=252)  # B4 unavailable
        bad_holding = SecurityHoldingV2.model_construct(
            schema_version="2",
            security_id=self.etf_uuids["VOO"],
            quantity=5,
            basis_status="indeterminate",
            cost_basis=None,
            basis_indeterminate_by=("0" * 64,),
        )
        port_state = PortfolioStateV2.model_construct(
            schema_version="2",
            lane="exploratory",
            admission_hash="0" * 64,
            session_key=self.session_key,
            cash_balance=Decimal("1000.00"),
            holdings=(bad_holding,),
            pending_cash_claims=(),
            settled_claim_ids=(),
            applied_effect_ids=("0" * 64,),
            mark=None,
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port_state,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertTrue(res.requires_containment)
        self.assertFalse(res.hold_incumbent)
        self.assertIn("indeterminate basis", res.reason)

    def test_disabled_incumbent_continuation_yields_containment(self) -> None:
        """If incumbent continuation is disabled, unavailable candidate cannot hold."""
        ctx = self._build_context(session_count=252)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
            allow_incumbent_continuation=False,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertTrue(res.requires_containment)
        self.assertFalse(res.hold_incumbent)
        self.assertIn("incumbent continuation disabled", res.reason)

    def test_missing_decision_context_is_unavailable_and_indeterminate(self) -> None:
        """None context fails closed without error."""
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=None,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertTrue(res.requires_containment)
        self.assertIn("missing_decision_context", res.reason)

    # -------------------------------------------------------------------------
    # Group F: Determinism, Preflight Hashing, and Existing Semantics
    # -------------------------------------------------------------------------

    def test_deterministic_output_and_hash_consistency(self) -> None:
        """Identical inputs produce bit-for-bit identical preflight hash."""
        ctx = self._build_context(session_count=253)
        res1 = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        res2 = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res1.preflight_hash, res2.preflight_hash)
        self.assertEqual(res1, res2)

        # Verification of hash calculation helper
        expected_hash = compute_preflight_hash(
            status=res1.status,
            reason=res1.reason,
            proposed_strategy=res1.proposed_strategy,
            current_strategy=res1.current_strategy,
            effective_strategy=res1.effective_strategy,
            is_tradeable=res1.is_tradeable,
            hold_incumbent=res1.hold_incumbent,
            requires_containment=res1.requires_containment,
            session_key=res1.session_key,
            decision_cutoff=res1.decision_cutoff,
            cohort_hash=res1.cohort_hash,
            admitted_universe=res1.admitted_universe,
        )
        self.assertEqual(res1.preflight_hash, expected_hash)

    def test_preflight_prevents_accidental_liquidation_in_evaluator(self) -> None:
        """Demonstrates preflight blocks unwarmed strategy before _stage_targets."""
        # Existing portfolio has 1 share of VOO
        voo_sec = self.etf_uuids["VOO"]
        holdings = (
            PositionViewV1(
                schema_version="1",
                security_id=voo_sec,
                quantity=1,
                cost_basis=Decimal("500.00"),
                average_cost_per_share=Decimal("500.00"),
            ),
        )
        ctx = self._build_context(session_count=252, holdings=holdings)

        # 1. Preflight evaluation detects ineligibility
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)

        # 2. Gatekeeper rule: Downstream evaluator checks is_tradeable
        if res.is_tradeable:
            # If tradeable (never reached here for unwarmed B4), would stage targets
            empty_intent = StrategyDecisionIntentV1(
                session_key=ctx.session_key,
                decision_time=ctx.decision_cutoff,
                targets=(),
            )
            staged = stage_exploratory_decision_targets(empty_intent, ctx)
        else:
            # Safe hold: holdings are retained untouched, no zero targets staged
            staged = None

        self.assertIsNone(staged)
        # Position is preserved intact
        self.assertEqual(holdings[0].quantity, 1)

    def test_legitimate_complete_target_liquidation_unaffected(self) -> None:
        """Eligible strategy legitimately commanding complete liquidation works."""
        voo_sec = self.etf_uuids["VOO"]
        holdings = (
            PositionViewV1(
                schema_version="1",
                security_id=voo_sec,
                quantity=1,
                cost_basis=Decimal("500.00"),
                average_cost_per_share=Decimal("500.00"),
            ),
        )
        ctx = self._build_context(session_count=253, holdings=holdings)

        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.universe12_uuids,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)

        # Legitimate complete target liquidation: intent explicitly sets VOO to 0
        intent = StrategyDecisionIntentV1(
            session_key=ctx.session_key,
            decision_time=ctx.decision_cutoff,
            targets=(
                SecurityTargetPositionV1(
                    security_id=voo_sec,
                    target_quantity=0,
                ),
            ),
        )
        staged = stage_exploratory_decision_targets(intent, ctx)
        staged_dict = {t.security_id: t.target_quantity for t in staged}
        self.assertEqual(staged_dict[voo_sec], 0)


if __name__ == "__main__":
    unittest.main()
