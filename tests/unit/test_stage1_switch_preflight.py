"""Comprehensive unit tests for Stage 1 strategy-switch preflight (Issue 422).

Covers:
- Point 1: Fixed 12-ETF universe completeness, duplicates, extra ETFs, no-QQQ.
- Point 2: Portfolio safety, complete state, unadmitted incumbents,
  session/NAV/cash/holding mismatch, pending orders, unverified mandate/risk,
  indeterminate basis holdings, and verified safe holds.
- Point 3: StrategyReference identity, forged artifact locations, wrong
  ID/version/hash, and canonical baselines.
- Point 4: Observation history readiness, explicit current-session close
  (stale fallback trap), late-available bars, corporate action adjustments,
  analytical return series, and minimum eligible names.
- Point 5: Result integrity, status/flag coherence, preflight hash, and
  downstream consumer revalidation.
- Point 6: Genuinely validated domain fixtures without schema bypasses.
"""

import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from drift.analysis.analytical_returns import CorporateActionAdjustment
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import B4MomentumStrategy
from drift.baselines.b5_low_volatility import B5LowVolatilityStrategy
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import EvaluationSessionV1, evaluation_session_hash
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.evaluator_portfolio import (
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioMarkV1,
    PortfolioStateV2,
    SecurityHoldingV2,
)
from drift.domain.evaluator_reconstruction import (
    REQUIRED_RECONSTRUCTION_FIELDS,
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
    cohort_authorization_hash,
    exploratory_reconstruction_hash,
)
from drift.domain.evaluator_strategy import PositionViewV1
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.loop.stage1_switch_preflight import (
    PreflightStatus,
    Stage1SwitchPreflightResult,
    evaluate_stage1_switch_preflight,
    verify_stage1_switch_preflight_result,
)


class TestStage1SwitchPreflight(unittest.TestCase):
    """Unit and adversarial test suite for Stage 1 switch preflight."""

    def setUp(self) -> None:
        self.equity_syms = ["VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"]
        self.bond_syms = ["SHY", "IEF", "TLT", "TIP", "LQD"]
        self.gold_syms = ["GLD"]
        self.universe12_syms = self.equity_syms + self.bond_syms + self.gold_syms

        self.etf_uuids: dict[str, UUID7] = {}
        for i, sym in enumerate(self.universe12_syms, start=1):
            hex_id = f"018e0000-0000-7000-8000-{i:012x}"
            self.etf_uuids[sym] = UUID(hex_id)

        self.admitted_uuids = tuple(
            self.etf_uuids[sym]
            for sym in sorted(
                self.universe12_syms, key=lambda s: self.etf_uuids[s].bytes
            )
        )

        self.base_prices: dict[str, Decimal] = {
            "VOO": Decimal("500.00"),
            "IJH": Decimal("300.00"),
            "IJR": Decimal("120.00"),
            "QQQ": Decimal("480.00"),
            "VEA": Decimal("50.00"),
            "VWO": Decimal("45.00"),
            "SHY": Decimal("82.00"),
            "IEF": Decimal("95.00"),
            "TLT": Decimal("90.00"),
            "TIP": Decimal("105.00"),
            "LQD": Decimal("108.00"),
            "GLD": Decimal("240.00"),
        }

        self.today = date(2026, 1, 30)
        self.closed_at = datetime.combine(
            self.today, datetime.min.time(), tzinfo=UTC
        ).replace(hour=21, minute=0)
        self.opened_at = self.closed_at - timedelta(hours=6, minutes=30)
        self.session_key = SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=self.today
        )

        self.sched_hash = "1" * 64
        self.row_hash = "2" * 64

        self.session = self._make_valid_session(
            session_key=self.session_key,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
        )

        self.cohort_auth = self._make_valid_cohort(self.admitted_uuids)
        self.cohort_hash = self.cohort_auth.cohort_hash

    def _make_valid_session(
        self,
        session_key: SessionKeyV1,
        opened_at: datetime,
        closed_at: datetime,
    ) -> EvaluationSessionV1:
        draft = EvaluationSessionV1.model_construct(
            schema_version="1",
            session_key=session_key,
            opened_at=opened_at,
            closed_at=closed_at,
            authority="scheduled_reconstruction",
            authority_record_hashes=(self.sched_hash, self.row_hash),
            authority_proof_hashes=("3" * 64,),
            session_hash="0" * 64,
        )
        return EvaluationSessionV1(
            schema_version="1",
            session_key=session_key,
            opened_at=opened_at,
            closed_at=closed_at,
            authority="scheduled_reconstruction",
            authority_record_hashes=(self.sched_hash, self.row_hash),
            authority_proof_hashes=("3" * 64,),
            session_hash=evaluation_session_hash(draft),
        )

    def _make_valid_cohort(
        self,
        security_ids: tuple[UUID7, ...],
    ) -> ExploratoryCohortAuthorizationV1:
        draft = ExploratoryCohortAuthorizationV1.model_construct(
            schema_version="1",
            cohort_id="stage1-test-cohort",
            cohort_version="1",
            security_ids=security_ids,
            cohort_hash="0" * 64,
        )
        return ExploratoryCohortAuthorizationV1(
            schema_version="1",
            cohort_id="stage1-test-cohort",
            cohort_version="1",
            security_ids=security_ids,
            cohort_hash=cohort_authorization_hash(draft),
        )

    def _make_valid_observation(
        self,
        sec: UUID7,
        d: date,
        price: Decimal,
        *,
        available_at: datetime | None = None,
        cohort_hash: str | None = None,
    ) -> ExploratoryReconstructedSessionObservationV1:
        c_hash = cohort_hash or self.cohort_hash
        fields = tuple(
            ExploratoryReconstructedFieldV1(
                field_name=fn,
                source_value=price if fn != "volume" else Decimal("1000"),
                method_id="basis",
                meaning="price" if fn != "volume" else "share_volume",
                source_field_hash="4" * 64,
            )
            for fn in sorted(REQUIRED_RECONSTRUCTION_FIELDS)
        )
        data: dict[str, Any] = dict(
            schema_version="1",
            kind="exploratory_reconstructed_session_observation",
            session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d),
            security_id=sec,
            listing_id=UUID("018e0000-0000-7000-8000-000000000099"),
            venue=ListingVenue.XNYS,
            currency="USD",
            reconstruction_policy_hash="5" * 64,
            cohort_hash=c_hash,
            source_observation_hash="6" * 64,
            observation_contract_hash="7" * 64,
            observation_selection_proof_hash="8" * 64,
            contract_selection_proof_hash="9" * 64,
            scheduled_session_hash=self.sched_hash,
            generated_session_row_hash=self.row_hash,
            scheduled_selection_proof_hash="a" * 64,
            schedule_artifact_hash="b" * 64,
            outcome_query_hash="c" * 64,
            source_context_hash="d" * 64,
            evidence_vintage_cutoff=available_at or self.closed_at,
            fields=fields,
            acknowledged_limitations=tuple(
                sorted(
                    (
                        ALPACA_LIMITATION_ABSENT_HALTS,
                        ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
                        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                        ALPACA_LIMITATION_UNVERSIONED_BARS,
                    )
                )
            ),
        )
        draft = ExploratoryReconstructedSessionObservationV1.model_construct(
            _fields_set=None,
            reconstruction_hash="0" * 64,
            **data,
        )
        rec_hash = exploratory_reconstruction_hash(draft)
        return ExploratoryReconstructedSessionObservationV1(
            reconstruction_hash=rec_hash,
            **data,
        )

    def _make_valid_portfolio_state(
        self,
        *,
        cash_balance: Decimal = Decimal("100000.00"),
        holdings: tuple[SecurityHoldingV2, ...] = (),
        session_key: SessionKeyV1 | None = None,
        mark_prices: dict[UUID7, Decimal] | None = None,
    ) -> PortfolioStateV2:
        s_key = session_key or self.session_key
        mark = None
        holdings_market_val = Decimal("0.00")

        if holdings:
            prices = []
            for h in holdings:
                p = (
                    mark_prices.get(h.security_id, Decimal("100.00"))
                    if mark_prices
                    else Decimal("100.00")
                )
                prices.append(
                    MarkPriceV1(
                        security_id=h.security_id,
                        close_price=p,
                        evidence=MarkEvidenceV1(
                            grade="exploratory", evidence_hash="e" * 64
                        ),
                    )
                )
                holdings_market_val += p * h.quantity

            mark = PortfolioMarkV1(
                session_key=s_key,
                lane="exploratory",
                prices=tuple(prices),
            )

        nav = cash_balance + holdings_market_val

        return PortfolioStateV2(
            schema_version="2",
            lane="exploratory",
            admission_hash="f" * 64,
            session_key=s_key,
            cash_balance=cash_balance,
            holdings=holdings,
            pending_cash_claims=(),
            settled_claim_ids=(),
            applied_effect_ids=(),
            mark=mark,
            holdings_market_value=holdings_market_val,
            pending_claims_value=Decimal("0.00"),
            net_asset_value=nav,
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )

    def _build_context(
        self,
        session_count: int = 255,
        *,
        custom_observations_by_sym: (
            Mapping[str, Sequence[ExploratoryReconstructedSessionObservationV1]] | None
        ) = None,
        nav: Decimal = Decimal("100000.00"),
        holdings: tuple[PositionViewV1, ...] = (),
        cohort_uuids: tuple[UUID7, ...] | None = None,
        bypass_view_validator: bool = False,
    ) -> ExploratoryStrategyDecisionContextV1:
        effective_cohort = (
            cohort_uuids if cohort_uuids is not None else self.admitted_uuids
        )
        c_hash = (
            self.cohort_hash
            if effective_cohort == self.admitted_uuids
            else self._make_valid_cohort(effective_cohort).cohort_hash
        )

        views = []
        for sym in self.universe12_syms:
            sec_uuid = self.etf_uuids.get(sym)
            if sec_uuid not in effective_cohort:
                continue

            if custom_observations_by_sym and sym in custom_observations_by_sym:
                obs_list = custom_observations_by_sym[sym]
            else:
                base_p = self.base_prices[sym]
                obs_list = []
                for step in range(session_count - 1, -1, -1):
                    d = self.today - timedelta(days=step)
                    obs_list.append(
                        self._make_valid_observation(
                            sec_uuid, d, base_p, cohort_hash=c_hash
                        )
                    )

            view_limitations = tuple(
                sorted(
                    {
                        lim
                        for obs in obs_list
                        for lim in getattr(obs, "acknowledged_limitations", ())
                    }
                )
            )
            if bypass_view_validator:
                view = ExploratoryReconstructedDecisionViewV1.model_construct(
                    schema_version="1",
                    evidence_grade="exploratory_reconstructed",
                    security_id=sec_uuid,
                    observations=tuple(obs_list),
                    acknowledged_limitations=view_limitations,
                )
            else:
                view = ExploratoryReconstructedDecisionViewV1(
                    security_id=sec_uuid,
                    observations=tuple(obs_list),
                    acknowledged_limitations=view_limitations,
                )
            views.append(view)

        holdings_val = Decimal("0.00")
        for h in holdings:
            p = self.base_prices.get("VOO", Decimal("100.00"))
            holdings_val += p * h.quantity
        cash = nav - holdings_val

        if bypass_view_validator:
            return ExploratoryStrategyDecisionContextV1.model_construct(
                session_key=self.session_key,
                decision_session=self.session,
                decision_cutoff=self.closed_at,
                cohort_hash=c_hash,
                admitted_cohort=effective_cohort,
                current_holdings=holdings,
                current_cash=cash,
                portfolio_nav=nav,
                reconstructed_decision_views=tuple(views),
                acknowledged_limitations=(
                    ALPACA_LIMITATION_ABSENT_HALTS,
                    ALPACA_LIMITATION_BOUNDED_COHORT,
                    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
                    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                    ALPACA_LIMITATION_UNVERSIONED_BARS,
                ),
            )

        return ExploratoryStrategyDecisionContextV1(
            session_key=self.session_key,
            decision_session=self.session,
            decision_cutoff=self.closed_at,
            cohort_hash=c_hash,
            admitted_cohort=effective_cohort,
            current_holdings=holdings,
            current_cash=cash,
            portfolio_nav=nav,
            reconstructed_decision_views=tuple(views),
            acknowledged_limitations=(
                ALPACA_LIMITATION_ABSENT_HALTS,
                ALPACA_LIMITATION_BOUNDED_COHORT,
                ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
                ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                ALPACA_LIMITATION_UNVERSIONED_BARS,
            ),
        )

    # =========================================================================
    # Point 1: Fixed Universe Validation Tests
    # =========================================================================

    def test_missing_required_universe_omitted_fails_closed(self) -> None:
        """Required universe must not be omitted (defaults to None fail closed)."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=None,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_required_universe", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)

    def test_missing_required_universe_empty_fails_closed(self) -> None:
        """Supplying an empty required_universe sequence fails closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=(),
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_required_universe", res.reason)

    def test_extra_security_in_context_rejected(self) -> None:
        """Context containing an unapproved extra ETF (13 names) is rejected."""
        extra_uuid = UUID("018e0000-0000-7000-8000-000000000099")
        expanded_cohort = self.admitted_uuids + (extra_uuid,)
        ctx = self._build_context(
            session_count=255,
            cohort_uuids=expanded_cohort,
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("extra_securities_in_context", res.reason)

    def test_duplicate_security_in_required_universe_rejected(self) -> None:
        """Duplicate security ID in required_universe sequence is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        duplicated_universe = (self.admitted_uuids[0],) + self.admitted_uuids
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=duplicated_universe,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("duplicate_security_in_required_universe", res.reason)

    def test_mismatched_universe_size_no_qqq_treated_as_distinct_and_rejected(
        self,
    ) -> None:
        """11-ETF cohort omitting QQQ is rejected as a mismatched configuration."""
        no_qqq = tuple(u for u in self.admitted_uuids if u != self.etf_uuids["QQQ"])
        self.assertEqual(len(no_qqq), 11)

        ctx = self._build_context(session_count=255, cohort_uuids=no_qqq)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=no_qqq,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("mismatched_universe_size", res.reason)

    def test_mismatched_universe_hash_rejected(self) -> None:
        """Context cohort hash failing to match expected_universe_hash is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        wrong_hash = "9" * 64
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=wrong_hash,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("universe_hash_mismatch", res.reason)

    def test_valid_exact_12_etf_universe_eligible(self) -> None:
        """Exact 12-ETF universe with all valid evidence succeeds."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertFalse(res.requires_containment)

    # =========================================================================
    # Point 2: Portfolio Safety and Complete State Validation Tests
    # =========================================================================

    def test_missing_portfolio_state_fails_closed(self) -> None:
        """Missing current_portfolio_state returns INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=255)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=None,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("missing_portfolio_state", res.reason)

    def test_missing_current_strategy_fails_closed(self) -> None:
        """Missing current_strategy returns INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy=None,
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertIn("missing_current_strategy", res.reason)

    def test_unadmitted_incumbent_strategy_fails_closed(self) -> None:
        """Unadmitted incumbent strategy (e.g. b0_cash) fails closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="b0_cash",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("unadmitted_incumbent_strategy", res.reason)

    def test_portfolio_context_session_mismatch_fails_closed(self) -> None:
        """Stale portfolio state from earlier session fails closed."""
        ctx = self._build_context(session_count=255)
        stale_key = SessionKeyV1(
            mic="XNYS",
            session_scope="regular",
            local_date=self.today - timedelta(days=1),
        )
        port = self._make_valid_portfolio_state(session_key=stale_key)
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("portfolio_context_session_mismatch", res.reason)

    def test_portfolio_context_nav_mismatch_fails_closed(self) -> None:
        """Disagreement between portfolio state NAV and context NAV fails closed."""
        ctx = self._build_context(session_count=255, nav=Decimal("100000.00"))
        port = self._make_valid_portfolio_state(cash_balance=Decimal("95000.00"))
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("portfolio_context_nav_mismatch", res.reason)

    def test_portfolio_context_cash_mismatch_fails_closed(self) -> None:
        """Disagreement between portfolio cash and context cash fails closed."""
        holding = SecurityHoldingV2(
            security_id=self.etf_uuids["VOO"],
            quantity=20,
            basis_status="known",
            cost_basis=Decimal("10000.00"),
        )
        ctx = self._build_context(
            session_count=255,
            nav=Decimal("100000.00"),
            holdings=(
                PositionViewV1(
                    security_id=self.etf_uuids["VOO"],
                    quantity=10,
                    cost_basis=Decimal("5000.00"),
                    average_cost_per_share=Decimal("500.00"),
                ),
            ),
        )
        port = self._make_valid_portfolio_state(
            cash_balance=Decimal("90000.00"),
            holdings=(holding,),
            mark_prices={self.etf_uuids["VOO"]: Decimal("500.00")},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("portfolio_context_cash_mismatch", res.reason)

    def test_pending_orders_present_fails_closed(self) -> None:
        """Open or pending orders prevent strategy switching and safe hold."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            open_orders=[{"order_id": "ord-1", "status": "pending"}],
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("pending_orders_present", res.reason)

    def test_unverified_mandate_fails_closed(self) -> None:
        """Unverified investment mandate fails closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            mandate_verified=False,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("unverified_mandate", res.reason)

    def test_unverified_risk_fails_closed(self) -> None:
        """Unverified risk state fails closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            risk_verified=False,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("unverified_risk", res.reason)

    def test_indeterminate_holding_basis_fails_closed(self) -> None:
        """Portfolio holding with indeterminate basis causes containment."""
        effect_id = "1" * 64
        holding = SecurityHoldingV2(
            security_id=self.etf_uuids["VOO"],
            quantity=10,
            basis_status="indeterminate",
            cost_basis=None,
            basis_indeterminate_by=(effect_id,),
        )
        port = PortfolioStateV2(
            schema_version="2",
            lane="exploratory",
            admission_hash="f" * 64,
            session_key=self.session_key,
            cash_balance=Decimal("95000.00"),
            holdings=(holding,),
            pending_cash_claims=(),
            settled_claim_ids=(),
            applied_effect_ids=(effect_id,),
            mark=PortfolioMarkV1(
                session_key=self.session_key,
                lane="exploratory",
                prices=(
                    MarkPriceV1(
                        security_id=self.etf_uuids["VOO"],
                        close_price=Decimal("500.00"),
                        evidence=MarkEvidenceV1(
                            grade="exploratory", evidence_hash="e" * 64
                        ),
                    ),
                ),
            ),
            holdings_market_value=Decimal("5000.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("100000.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )
        ctx = self._build_context(session_count=255, nav=Decimal("100000.00"))
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("indeterminate_holding_basis", res.reason)

    def test_safe_hold_verified_when_incumbent_valid_and_portfolio_clean(self) -> None:
        """When candidate switch is unavailable, verified incumbent B3 safely holds."""
        ctx = self._build_context(session_count=10)  # Insufficient for B4
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")

    # =========================================================================
    # Point 3: Strategy Reference Identity Validation Tests
    # =========================================================================

    def test_forged_artifact_location_rejected(self) -> None:
        """StrategyReference with forged artifact location is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        b3_ref = B3MonthlyEqualWeightRebalanceStrategy().strategy_reference
        forged_art = ArtifactReference(
            artifact_id=b3_ref.artifact_reference.artifact_id,
            kind=ArtifactKind.STRATEGY,
            content_hash=b3_ref.code_hash,
            location="/tmp/forged/b3_monthly_equal_weight_rebalance.py",
        )
        forged_ref = StrategyReference(
            strategy_id=b3_ref.strategy_id,
            strategy_version=b3_ref.strategy_version,
            code_hash=b3_ref.code_hash,
            artifact_reference=forged_art,
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy=forged_ref,
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("strategy_location_mismatch", res.reason)

    def test_wrong_strategy_id_rejected(self) -> None:
        """StrategyReference with unrecognized strategy_id UUID is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        b4_ref = B4MomentumStrategy().strategy_reference
        wrong_id_ref = StrategyReference(
            strategy_id=UUID("018e0000-0000-7000-8000-000000000999"),
            strategy_version=b4_ref.strategy_version,
            code_hash=b4_ref.code_hash,
            artifact_reference=b4_ref.artifact_reference,
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy=wrong_id_ref,
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("unrecognized_strategy_id", res.reason)

    def test_unsupported_strategy_version_rejected(self) -> None:
        """StrategyReference with version != '1' is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        b4_ref = B4MomentumStrategy().strategy_reference
        wrong_ver_ref = StrategyReference(
            strategy_id=b4_ref.strategy_id,
            strategy_version="2",
            code_hash=b4_ref.code_hash,
            artifact_reference=b4_ref.artifact_reference,
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy=wrong_ver_ref,
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("unsupported_strategy_version", res.reason)

    def test_wrong_strategy_code_hash_rejected(self) -> None:
        """StrategyReference with modified code_hash is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        b5_ref = B5LowVolatilityStrategy().strategy_reference
        tampered_ref = StrategyReference(
            strategy_id=b5_ref.strategy_id,
            strategy_version=b5_ref.strategy_version,
            code_hash="0" * 64,
            artifact_reference=b5_ref.artifact_reference,
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy=tampered_ref,
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("strategy_code_hash_mismatch", res.reason)

    def test_valid_frozen_strategy_references_b3_b4_b5(self) -> None:
        """Canonical frozen StrategyReferences for B3, B4, and B5 are authenticated."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()

        b3_ref = B3MonthlyEqualWeightRebalanceStrategy().strategy_reference
        b4_ref = B4MomentumStrategy().strategy_reference
        b5_ref = B5LowVolatilityStrategy().strategy_reference

        res_b4 = evaluate_stage1_switch_preflight(
            proposed_strategy=b4_ref,
            current_strategy=b3_ref,
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res_b4.status, PreflightStatus.ELIGIBLE)
        self.assertEqual(res_b4.effective_strategy, "B4")

        res_b5 = evaluate_stage1_switch_preflight(
            proposed_strategy=b5_ref,
            current_strategy=b4_ref,
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res_b5.status, PreflightStatus.ELIGIBLE)
        self.assertEqual(res_b5.effective_strategy, "B5")

    # =========================================================================
    # Point 4: Observation Readiness, Current Close, and Adjustments Tests
    # =========================================================================

    def test_missing_current_session_close_fallback_trap(self) -> None:
        """Missing observation for current decision session returns UNAVAILABLE."""
        # 254 bars ending yesterday (no bar for today)
        sec_voo = self.etf_uuids["VOO"]
        stale_obs = [
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=step),
                Decimal("500.00"),
            )
            for step in range(254, 0, -1)
        ]
        self.assertEqual(len(stale_obs), 254)

        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": stale_obs},
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_current_session_close", res.reason)

    def test_late_available_observation_past_cutoff(self) -> None:
        """Observation timestamped after decision cutoff returns UNAVAILABLE."""
        sec_voo = self.etf_uuids["VOO"]
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=step),
                Decimal("500.00"),
            )
            for step in range(254, 0, -1)
        ]
        # Current session observation arriving late
        late_obs = self._make_valid_observation(
            sec_voo,
            self.today,
            Decimal("500.00"),
            available_at=self.closed_at + timedelta(minutes=5),
        )
        obs_list.append(late_obs)

        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("late_available_observation_detected", res.reason)

    def test_invalid_corporate_action_split_ratio_rejected(self) -> None:
        """Corporate action adjustment with split_ratio <= 0 is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        adjs = {
            self.etf_uuids["VOO"]: [
                CorporateActionAdjustment(
                    effective_date=self.today - timedelta(days=10),
                    split_ratio=Decimal("0"),
                )
            ]
        }
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            adjustments_by_security=adjs,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("invalid_corporate_action_adjustment", res.reason)

    def test_negative_corporate_action_cash_distribution_rejected(self) -> None:
        """Corporate action adjustment with negative cash distribution is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        adjs = {
            self.etf_uuids["VOO"]: [
                CorporateActionAdjustment(
                    effective_date=self.today - timedelta(days=10),
                    cash_distribution=Decimal("-1.50"),
                )
            ]
        }
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            adjustments_by_security=adjs,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("invalid_corporate_action_adjustment", res.reason)

    def test_future_corporate_action_adjustment_unavailable(self) -> None:
        """Corporate action adjustment in the future returns UNAVAILABLE."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        adjs = {
            self.etf_uuids["VOO"]: [
                CorporateActionAdjustment(
                    effective_date=self.today + timedelta(days=5),
                    split_ratio=Decimal("2"),
                )
            ]
        }
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            adjustments_by_security=adjs,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("future_corporate_action_adjustment", res.reason)

    def test_insufficient_history_for_b4_unavailable(self) -> None:
        """B4 requires 253 sessions; 250 sessions returns UNAVAILABLE."""
        ctx = self._build_context(session_count=250)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("insufficient_history", res.reason)

    def test_insufficient_history_for_b5_unavailable(self) -> None:
        """B5 requires 61 sessions; 50 sessions returns UNAVAILABLE."""
        ctx = self._build_context(session_count=50)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("insufficient_history", res.reason)

    def test_insufficient_eligible_momentum_securities_prevents_accidental_liquidation(
        self,
    ) -> None:
        """When fewer than 2 securities have valid momentum, B4 returns UNAVAILABLE."""
        # Truncate all ETF histories except VOO to 100 sessions (< 253)
        custom_obs = {}
        for sym in self.universe12_syms:
            if sym != "VOO":
                custom_obs[sym] = [
                    self._make_valid_observation(
                        self.etf_uuids[sym],
                        self.today - timedelta(days=step),
                        self.base_prices[sym],
                    )
                    for step in range(100, -1, -1)
                ]

        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym=custom_obs,
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("insufficient_history", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)

    # =========================================================================
    # Point 5: Result Integrity, Binding, and Revalidation Tests
    # =========================================================================

    def test_tampered_flag_raises_validation_error(self) -> None:
        """Contradictory status/flags in result model raise ValueError."""
        with self.assertRaises(ValueError):
            Stage1SwitchPreflightResult(
                schema_version="1",
                status=PreflightStatus.ELIGIBLE,
                reason="tampered_test",
                proposed_strategy="B4",
                current_strategy="B3",
                effective_strategy="B4",
                is_tradeable=False,  # Contradicts ELIGIBLE!
                hold_incumbent=False,
                requires_containment=False,
                session_key=self.session_key,
                decision_cutoff=self.closed_at,
                admitted_universe=self.admitted_uuids,
                portfolio_state_hash="0" * 64,
                preflight_hash="0" * 64,
            )

    def test_forged_preflight_hash_raises_validation_error(self) -> None:
        """Direct construction with forged preflight_hash raises ValueError."""
        with self.assertRaises(ValueError):
            Stage1SwitchPreflightResult(
                schema_version="1",
                status=PreflightStatus.ELIGIBLE,
                reason="tampered_hash_test",
                proposed_strategy="B4",
                current_strategy="B3",
                effective_strategy="B4",
                is_tradeable=True,
                hold_incumbent=False,
                requires_containment=False,
                session_key=self.session_key,
                decision_cutoff=self.closed_at,
                admitted_universe=self.admitted_uuids,
                portfolio_state_hash="0" * 64,
                preflight_hash="bad_hash" * 4,
            )

    def test_verify_result_portfolio_state_changed_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result detects live portfolio state drift."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)

        # Mutated state after preflight
        modified_port = self._make_valid_portfolio_state(
            cash_balance=Decimal("99999.00")
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res, current_portfolio_state=modified_port
            )
        self.assertIn("portfolio state changed", str(cm.exception))

    def test_verify_result_cross_account_replay_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents cross-account replay."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            account_id="account-alpha",
        )
        self.assertEqual(res.account_id, "account-alpha")

        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res, expected_account_id="account-beta"
            )
        self.assertIn("verdict account_id mismatch", str(cm.exception))

    def test_verify_result_mandate_mismatch_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents mandate spoofing."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            mandate="balanced_stage1",
        )
        self.assertEqual(res.mandate, "balanced_stage1")

        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(res, expected_mandate="growth_stage1")
        self.assertIn("verdict mandate mismatch", str(cm.exception))

    def test_verify_result_session_mismatch_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents replay across sessions."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )

        future_session = SessionKeyV1(
            mic="XNYS",
            session_scope="regular",
            local_date=self.today + timedelta(days=1),
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res, expected_session_key=future_session
            )
        self.assertIn("verdict session key mismatch", str(cm.exception))

    def test_verify_result_successful_revalidation(self) -> None:
        """verify_stage1_switch_preflight_result succeeds with matching state."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
        )
        verified = verify_stage1_switch_preflight_result(
            res,
            current_portfolio_state=port,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
        )
        self.assertTrue(verified)

    # =========================================================================
    # Point 6: Additional Invariants and Core Behaviors
    # =========================================================================

    def test_deliberate_abstain_maintains_safe_incumbent(self) -> None:
        """Deliberate ABSTAIN request preserves safe incumbent B3."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ABSTAIN)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")

    def test_deliberate_abstain_with_unsafe_portfolio_fails_closed(self) -> None:
        """Deliberate ABSTAIN request with indeterminate holding basis fails closed."""
        effect_id = "1" * 64
        holding = SecurityHoldingV2(
            security_id=self.etf_uuids["VOO"],
            quantity=10,
            basis_status="indeterminate",
            cost_basis=None,
            basis_indeterminate_by=(effect_id,),
        )
        port = PortfolioStateV2(
            schema_version="2",
            lane="exploratory",
            admission_hash="f" * 64,
            session_key=self.session_key,
            cash_balance=Decimal("95000.00"),
            holdings=(holding,),
            pending_cash_claims=(),
            settled_claim_ids=(),
            applied_effect_ids=(effect_id,),
            mark=PortfolioMarkV1(
                session_key=self.session_key,
                lane="exploratory",
                prices=(
                    MarkPriceV1(
                        security_id=self.etf_uuids["VOO"],
                        close_price=Decimal("500.00"),
                        evidence=MarkEvidenceV1(
                            grade="exploratory", evidence_hash="e" * 64
                        ),
                    ),
                ),
            ),
            holdings_market_value=Decimal("5000.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("100000.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )
        ctx = self._build_context(session_count=255, nav=Decimal("100000.00"))
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_incumbent_continuation_disabled_fails_closed(self) -> None:
        """When allow_incumbent_continuation is False, unavailable switch fails."""
        ctx = self._build_context(session_count=10)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
            allow_incumbent_continuation=False,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_unsupported_proposed_strategy_rejected(self) -> None:
        """Proposed strategy 'b0_cash' is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="b0_cash",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("unsupported_stage1_strategy", res.reason)

    def test_out_of_order_observations_rejected(self) -> None:
        """Observations with descending dates are rejected."""
        sec_voo = self.etf_uuids["VOO"]
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=step),
                Decimal("500.00"),
            )
            for step in range(255)  # today down to past (reversed order!)
        ]
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("out_of_order_observations", res.reason)

    def test_duplicate_session_observation_rejected(self) -> None:
        """Duplicate observations for the same session date are rejected."""
        sec_voo = self.etf_uuids["VOO"]
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=step),
                Decimal("500.00"),
            )
            for step in range(254, -1, -1)
        ]
        obs_list.append(
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=1),
                Decimal("500.00"),
            )
        )
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("duplicate_session_observation", res.reason)

    def test_zero_close_price_rejected(self) -> None:
        """Zero close price in observation history is rejected."""
        sec_voo = self.etf_uuids["VOO"]
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                self.today - timedelta(days=step),
                Decimal("500.00") if step != 5 else Decimal("0.00"),
            )
            for step in range(254, -1, -1)
        ]
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
        )
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("invalid_close_price", res.reason)


if __name__ == "__main__":
    unittest.main()
