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
from drift.domain.evaluator_strategy import (
    PositionViewV1,
    StrategyDecisionContextV1,
    StrategyDecisionViewV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    ExactRatioV1,
    FieldTransformV1,
    NormalizationQueryV1,
    derived_view_output_hash,
)
from drift.domain.observation_query import ObservationDecisionQueryV1
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind
from drift.loop.stage1_switch_preflight import (
    PreflightStatus,
    Stage1SwitchPreflightResult,
    evaluate_stage1_switch_preflight,
    verify_stage1_switch_preflight_result,
)
from drift.serialization.canonical import content_hash

_SENTINEL = object()


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian Computus algorithm for Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l_val = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_val) // 451
    month = (h + l_val - 7 * m + 114) // 31
    day = ((h + l_val - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def good_friday(year: int) -> date:
    """Good Friday (two days before Easter Sunday)."""
    return easter_sunday(year) - timedelta(days=2)


class SyntheticExchangeCalendar:
    """Deterministic synthetic US equities exchange calendar (NYSE/NASDAQ rules)."""

    @classmethod
    def get_holidays(cls, year: int) -> set[date]:
        holidays: set[date] = set()

        def add_observed(d: date) -> None:
            if d.weekday() == 6:  # Sunday -> observed Monday
                holidays.add(d + timedelta(days=1))
            elif d.weekday() == 5:  # Saturday -> observed Friday
                holidays.add(d - timedelta(days=1))
            else:
                holidays.add(d)

        # New Year's Day (Jan 1)
        ny = date(year, 1, 1)
        if ny.weekday() == 6:
            holidays.add(date(year, 1, 2))
        elif ny.weekday() != 5:
            holidays.add(ny)

        # Martin Luther King Jr. Day (3rd Monday in January)
        first_jan = date(year, 1, 1)
        mlk = first_jan + timedelta(days=((0 - first_jan.weekday()) % 7) + 14)
        holidays.add(mlk)

        # Washington's Birthday / Presidents' Day (3rd Monday in February)
        first_feb = date(year, 2, 1)
        pres = first_feb + timedelta(days=((0 - first_feb.weekday()) % 7) + 14)
        holidays.add(pres)

        # Good Friday
        holidays.add(good_friday(year))

        # Memorial Day (last Monday in May)
        last_may = date(year, 5, 31)
        mem = last_may - timedelta(days=last_may.weekday())
        holidays.add(mem)

        # Juneteenth (June 19)
        add_observed(date(year, 6, 19))

        # Independence Day (July 4)
        add_observed(date(year, 7, 4))

        # Labor Day (1st Monday in September)
        first_sep = date(year, 9, 1)
        labor = first_sep + timedelta(days=((0 - first_sep.weekday()) % 7))
        holidays.add(labor)

        # Thanksgiving Day (4th Thursday in November)
        first_nov = date(year, 11, 1)
        thanksgiving = first_nov + timedelta(days=((3 - first_nov.weekday()) % 7) + 21)
        holidays.add(thanksgiving)

        # Christmas Day (December 25)
        add_observed(date(year, 12, 25))

        return holidays

    @classmethod
    def get_half_days(cls, year: int) -> set[date]:
        half_days: set[date] = set()
        first_nov = date(year, 11, 1)
        thanksgiving = first_nov + timedelta(days=((3 - first_nov.weekday()) % 7) + 21)
        # Black Friday
        half_days.add(thanksgiving + timedelta(days=1))
        # Christmas Eve
        xmas_eve = date(year, 12, 24)
        if xmas_eve.weekday() < 5 and date(year, 12, 25).weekday() < 5:
            half_days.add(xmas_eve)
        # July 3
        july_3 = date(year, 7, 3)
        if july_3.weekday() < 5 and date(year, 7, 4).weekday() < 5:
            half_days.add(july_3)
        return half_days

    @classmethod
    def is_trading_session(cls, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        if d in cls.get_holidays(d.year):
            return False
        return True


def generate_synthetic_trading_sessions(count: int, end_date: date) -> list[date]:
    """Generate business days (Monday-Friday, excluding exchange holidays)."""
    dates: list[date] = []
    cur = end_date
    while len(dates) < count:
        if SyntheticExchangeCalendar.is_trading_session(cur):
            dates.append(cur)
        cur -= timedelta(days=1)
    dates.reverse()
    return dates


# Backward compatibility alias
generate_trading_sessions = generate_synthetic_trading_sessions


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

        self.universe_manifest = {u: sym for sym, u in self.etf_uuids.items()}
        self.valid_adjustments: dict[UUID7, Sequence[CorporateActionAdjustment]] = {
            u: () for u in self.admitted_uuids
        }
        self.completed_sessions: set[date | SessionKeyV1] = set(
            generate_synthetic_trading_sessions(300, self.today)
        )
        self.completed_sessions.add(self.today)
        self.completed_sessions.add(self.session_key)

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
                trading_days = generate_trading_sessions(session_count, self.today)
                for d in trading_days:
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

    def _make_valid_derived_view(
        self,
        sec: UUID7,
        d: date,
        price: Decimal,
        *,
        decision_time: datetime | None = None,
        knowledge_cutoff: datetime | None = None,
        effective_cutoff: datetime | None = None,
    ) -> DerivedObservationViewV1:
        listing = UUID("018e0000-0000-7000-8000-000000000099")
        dt = decision_time or self.closed_at
        kc = knowledge_cutoff or self.closed_at
        ec = effective_cutoff or self.closed_at
        q_obs = ObservationDecisionQueryV1(
            kind="decision",
            source_id="synthetic-source",
            contract_hash="1" * 64,
            source_selection_policy_hash="2" * 64,
            profile_hash="3" * 64,
            requested_channel=AvailabilityChannelV1(
                kind=ChannelKind.PUBLIC, identifier="public"
            ),
            availability_policy_id="public-exact",
            availability_policy_hash="4" * 64,
            input_context_hash="5" * 64,
            venue=ListingVenue.XNYS,
            listing_id=listing,
            security_id=sec,
            session_date=d,
            decision_time=dt,
            knowledge_cutoff=kc,
            effective_cutoff=ec,
        )
        q = NormalizationQueryV1(
            observation=q_obs,
            policy_hash="6" * 64,
            anchor_session=None,
        )
        q_hash = content_hash(q)
        fields = tuple(
            FieldTransformV1(
                field_name=fn,
                method_id="identity",
                meaning="share_volume" if fn == "volume" else "price",
                source_value=price if fn != "volume" else Decimal("1000"),
                exact_factor=ExactRatioV1(numerator="1", denominator="1"),
                exact_transformed_value=None,
                quantized_value=None,
                output_scale=None,
                rounded_to_zero=False,
            )
            for fn in ("close", "high", "low", "open", "volume")
        )
        draft = DerivedObservationViewV1.model_construct(
            role="decision",
            query=q,
            query_hash=q_hash,
            source_session=SessionKeyV1(
                mic="XNYS", session_scope="regular", local_date=d
            ),
            listing_id=listing,
            security_id=sec,
            basis_mode="source_basis",
            anchor_session=None,
            fields=fields,
            usability_hash="7" * 64,
            output_hash="0" * 64,
            derivation_hash="8" * 64,
        )
        out_h = derived_view_output_hash(draft)
        return DerivedObservationViewV1(
            role="decision",
            query=q,
            query_hash=q_hash,
            source_session=SessionKeyV1(
                mic="XNYS", session_scope="regular", local_date=d
            ),
            listing_id=listing,
            security_id=sec,
            basis_mode="source_basis",
            anchor_session=None,
            fields=fields,
            usability_hash="7" * 64,
            output_hash=out_h,
            derivation_hash="8" * 64,
        )

    def _build_strong_lane_context(
        self,
        session_count: int = 255,
        *,
        custom_views_by_sym: (
            Mapping[str, Sequence[DerivedObservationViewV1]] | None
        ) = None,
        nav: Decimal = Decimal("100000.00"),
        holdings: tuple[PositionViewV1, ...] = (),
        universe_uuids: tuple[UUID7, ...] | None = None,
    ) -> StrategyDecisionContextV1:
        effective_universe = (
            universe_uuids if universe_uuids is not None else self.admitted_uuids
        )
        groups = []
        for sym in self.universe12_syms:
            sec_uuid = self.etf_uuids.get(sym)
            if sec_uuid not in effective_universe:
                continue
            if custom_views_by_sym and sym in custom_views_by_sym:
                views_list = custom_views_by_sym[sym]
            else:
                base_p = self.base_prices[sym]
                trading_days = generate_synthetic_trading_sessions(
                    session_count, self.today
                )
                views_list = [
                    self._make_valid_derived_view(sec_uuid, d, base_p)
                    for d in trading_days
                ]
            groups.append(
                StrategyDecisionViewV1(
                    security_id=sec_uuid,
                    views=tuple(views_list),
                )
            )

        holdings_val = Decimal("0.00")
        for h in holdings:
            p = self.base_prices.get("VOO", Decimal("100.00"))
            holdings_val += p * h.quantity
        cash = nav - holdings_val

        return StrategyDecisionContextV1(
            session_key=self.session_key,
            decision_session=self.session,
            decision_cutoff=self.closed_at,
            admitted_universe=effective_universe,
            current_holdings=holdings,
            current_cash=cash,
            portfolio_nav=nav,
            decision_views=tuple(groups),
        )

    def _eval(
        self,
        *,
        proposed_strategy: str | StrategyReference,
        current_strategy: str | StrategyReference | None,
        decision_context: Any = None,
        required_universe: Any = _SENTINEL,
        expected_universe_hash: Any = _SENTINEL,
        universe_manifest: Any = _SENTINEL,
        current_portfolio_state: Any = _SENTINEL,
        allow_incumbent_continuation: bool = True,
        adjustments_by_security: Any = _SENTINEL,
        account_id: Any = _SENTINEL,
        mandate: Any = _SENTINEL,
        open_orders: Any = _SENTINEL,
        mandate_verified: Any = _SENTINEL,
        risk_verified: Any = _SENTINEL,
        completed_sessions: Any = _SENTINEL,
    ) -> Stage1SwitchPreflightResult:
        req_u = (
            self.admitted_uuids if required_universe is _SENTINEL else required_universe
        )
        exp_h = (
            self.cohort_hash
            if expected_universe_hash is _SENTINEL
            else expected_universe_hash
        )
        u_man = (
            self.universe_manifest
            if universe_manifest is _SENTINEL
            else universe_manifest
        )
        port = (
            self._make_valid_portfolio_state()
            if current_portfolio_state is _SENTINEL
            else current_portfolio_state
        )
        adjs = (
            self.valid_adjustments
            if adjustments_by_security is _SENTINEL
            else adjustments_by_security
        )
        acc_id = "account-alpha" if account_id is _SENTINEL else account_id
        man = "balanced_stage1" if mandate is _SENTINEL else mandate
        orders = () if open_orders is _SENTINEL else open_orders
        m_ver = True if mandate_verified is _SENTINEL else mandate_verified
        r_ver = True if risk_verified is _SENTINEL else risk_verified
        comp_sess = (
            self.completed_sessions
            if completed_sessions is _SENTINEL
            else completed_sessions
        )

        return evaluate_stage1_switch_preflight(
            proposed_strategy=proposed_strategy,
            current_strategy=current_strategy,
            decision_context=decision_context,
            required_universe=req_u,
            expected_universe_hash=exp_h,
            universe_manifest=u_man,
            current_portfolio_state=port,
            allow_incumbent_continuation=allow_incumbent_continuation,
            adjustments_by_security=adjs,
            account_id=acc_id,
            mandate=man,
            open_orders=orders,
            mandate_verified=m_ver,
            risk_verified=r_ver,
            completed_sessions=comp_sess,
        )

    # =========================================================================
    # Point 1: Fixed Universe Validation Tests
    # =========================================================================

    def test_missing_required_universe_omitted_fails_closed(self) -> None:
        """Required universe must not be omitted (defaults to None fail closed)."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=None,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("missing_required_universe", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_missing_required_universe_empty_fails_closed(self) -> None:
        """Supplying an empty required_universe sequence fails closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=(),
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("missing_required_universe", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_extra_security_in_context_rejected(self) -> None:
        """Context containing an unapproved extra ETF (13 names) is rejected."""
        extra_uuid = UUID("018e0000-0000-7000-8000-000000000099")
        expanded_cohort = self.admitted_uuids + (extra_uuid,)
        ctx = self._build_context(
            session_count=255,
            cohort_uuids=expanded_cohort,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("extra_securities_in_context", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_duplicate_security_in_required_universe_rejected(self) -> None:
        """Duplicate security ID in required_universe sequence is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        duplicated_universe = (self.admitted_uuids[0],) + self.admitted_uuids
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=duplicated_universe,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("duplicate_security_in_required_universe", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_mismatched_universe_size_no_qqq_treated_as_distinct_and_rejected(
        self,
    ) -> None:
        """11-ETF cohort omitting QQQ is rejected as a mismatched configuration."""
        no_qqq = tuple(u for u in self.admitted_uuids if u != self.etf_uuids["QQQ"])
        self.assertEqual(len(no_qqq), 11)

        ctx = self._build_context(session_count=255, cohort_uuids=no_qqq)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=no_qqq,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("mismatched_universe_size", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_mismatched_universe_hash_rejected(self) -> None:
        """Context cohort hash failing to match expected_universe_hash is rejected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        wrong_hash = "9" * 64
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=wrong_hash,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("universe_hash_mismatch", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_valid_exact_12_etf_universe_eligible(self) -> None:
        """Exact 12-ETF universe with all valid evidence succeeds."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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

        res_b4 = self._eval(
            proposed_strategy=b4_ref,
            current_strategy=b3_ref,
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            current_portfolio_state=port,
        )
        self.assertEqual(res_b4.status, PreflightStatus.ELIGIBLE)
        self.assertEqual(res_b4.effective_strategy, "B4")

        res_b5 = self._eval(
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
        trading_days = generate_trading_sessions(255, self.today)
        stale_obs = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00"),
            )
            for d in trading_days[:-1]
        ]
        self.assertEqual(len(stale_obs), 254)

        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": stale_obs},
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_current_session_close", res.reason)

    def test_late_available_observation_past_cutoff(self) -> None:
        """Observation timestamped after decision cutoff returns UNAVAILABLE."""
        sec_voo = self.etf_uuids["VOO"]
        trading_days = generate_trading_sessions(255, self.today)
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00"),
            )
            for d in trading_days[:-1]
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
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        trading_days = generate_trading_sessions(101, self.today)
        for sym in self.universe12_syms:
            if sym != "VOO":
                custom_obs[sym] = [
                    self._make_valid_observation(
                        self.etf_uuids[sym],
                        d,
                        self.base_prices[sym],
                    )
                    for d in trading_days
                ]

        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym=custom_obs,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
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
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)

        # Mutated state after preflight
        modified_port = self._make_valid_portfolio_state(
            cash_balance=Decimal("99999.00")
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
                current_portfolio_state=modified_port,
            )
        self.assertIn("portfolio state changed", str(cm.exception))

    def test_verify_result_cross_account_replay_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents cross-account replay."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            account_id="account-alpha",
        )
        self.assertEqual(res.account_id, "account-alpha")

        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res,
                expected_account_id="account-beta",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
                current_portfolio_state=port,
            )
        self.assertIn("verdict account_id mismatch", str(cm.exception))

    def test_verify_result_mandate_mismatch_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents mandate spoofing."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            mandate="balanced_stage1",
        )
        self.assertEqual(res.mandate, "balanced_stage1")

        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res,
                expected_account_id="account-alpha",
                expected_mandate="growth_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
                current_portfolio_state=port,
            )
        self.assertIn("verdict mandate mismatch", str(cm.exception))

    def test_verify_result_session_mismatch_raises_error(self) -> None:
        """verify_stage1_switch_preflight_result prevents replay across sessions."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )

        future_session = SessionKeyV1(
            mic="XNYS",
            session_scope="regular",
            local_date=self.today + timedelta(days=1),
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=future_session,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
                current_portfolio_state=port,
            )
        self.assertIn("verdict session key mismatch", str(cm.exception))

    def test_verify_result_successful_revalidation(self) -> None:
        """verify_stage1_switch_preflight_result succeeds with matching state."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
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
            expected_decision_cutoff=self.closed_at,
            expected_cohort_hash=self.cohort_hash,
        )
        self.assertTrue(verified)

    # =========================================================================
    # Point 6: Additional Invariants and Core Behaviors
    # =========================================================================

    def test_deliberate_abstain_maintains_safe_incumbent(self) -> None:
        """Deliberate ABSTAIN request preserves safe incumbent B3."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        res = self._eval(
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
        trading_days = generate_trading_sessions(255, self.today)
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00"),
            )
            for d in reversed(trading_days)  # today down to past (reversed order!)
        ]
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("out_of_order_observations", res.reason)

    def test_duplicate_session_observation_rejected(self) -> None:
        """Duplicate observations for the same session date are rejected."""
        sec_voo = self.etf_uuids["VOO"]
        trading_days = generate_trading_sessions(255, self.today)
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00"),
            )
            for d in trading_days
        ]
        obs_list.append(
            self._make_valid_observation(
                sec_voo,
                trading_days[-2],
                Decimal("500.00"),
            )
        )
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("duplicate_session_observation", res.reason)

    def test_zero_close_price_rejected(self) -> None:
        """Zero close price in observation history is rejected."""
        sec_voo = self.etf_uuids["VOO"]
        trading_days = generate_trading_sessions(255, self.today)
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00") if i != 5 else Decimal("0.00"),
            )
            for i, d in enumerate(trading_days)
        ]
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("invalid_close_price", res.reason)

    def test_weekend_observation_rejected(self) -> None:
        """Observation dated on a weekend (Saturday/Sunday) is rejected."""
        sec_voo = self.etf_uuids["VOO"]
        saturday_date = date(2026, 1, 24)
        trading_days = generate_trading_sessions(254, self.today)
        obs_list = [
            self._make_valid_observation(
                sec_voo,
                d,
                Decimal("500.00"),
            )
            for d in trading_days
        ]
        saturday_obs = self._make_valid_observation(
            sec_voo,
            saturday_date,
            Decimal("500.00"),
        )
        obs_list.append(saturday_obs)
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("weekend_observation_detected", res.reason)

    def test_omitted_risk_verification_fails_closed(self) -> None:
        """Omitted or None risk_verified must return INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=True,
            risk_verified=None,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("unverified_risk", res.reason)

    def test_omitted_mandate_verification_fails_closed(self) -> None:
        """Omitted or None mandate_verified must return INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=None,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("unverified_mandate", res.reason)

    def test_unknown_open_orders_status_fails_closed(self) -> None:
        """open_orders=None is unknown order status and must fail closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=None,
            mandate_verified=True,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("unknown_open_orders_status", res.reason)

    def test_rejected_switch_with_mismatched_holdings_cannot_claim_safe_hold(
        self,
    ) -> None:
        """Rejected switch with mismatched holdings cannot safe-hold incumbent."""
        holding_ctx = PositionViewV1(
            security_id=self.etf_uuids["VOO"],
            quantity=10,
            cost_basis=Decimal("5000.00"),
            average_cost_per_share=Decimal("500.00"),
        )
        ctx = self._build_context(
            session_count=10,
            nav=Decimal("100000.00"),
            holdings=(holding_ctx,),
        )
        holding_port = SecurityHoldingV2(
            security_id=self.etf_uuids["IJH"],
            quantity=10,
            basis_status="known",
            cost_basis=Decimal("5000.00"),
        )
        port = self._make_valid_portfolio_state(
            cash_balance=Decimal("95000.00"),
            holdings=(holding_port,),
            mark_prices={self.etf_uuids["IJH"]: Decimal("500.00")},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=True,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("portfolio_context_holdings_mismatch", res.reason)

    def test_rejected_switch_with_mismatched_cash_cannot_claim_safe_hold(
        self,
    ) -> None:
        """Rejected switch with mismatched cash cannot safe-hold incumbent."""
        holding_ctx = PositionViewV1(
            security_id=self.etf_uuids["VOO"],
            quantity=10,
            cost_basis=Decimal("5000.00"),
            average_cost_per_share=Decimal("500.00"),
        )
        ctx = self._build_context(
            session_count=10,
            nav=Decimal("100000.00"),
            holdings=(holding_ctx,),
        )
        holding_port = SecurityHoldingV2(
            security_id=self.etf_uuids["VOO"],
            quantity=20,
            basis_status="known",
            cost_basis=Decimal("10000.00"),
        )
        port = self._make_valid_portfolio_state(
            cash_balance=Decimal("90000.00"),
            holdings=(holding_port,),
            mark_prices={self.etf_uuids["VOO"]: Decimal("500.00")},
        )
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=True,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("portfolio_context_cash_mismatch", res.reason)

    def test_unrelated_etf_identities_rejected(self) -> None:
        """12 securities mapping to foreign symbols are rejected."""
        foreign_manifest = {
            u: f"FOREIGN_{i}" for i, u in enumerate(self.admitted_uuids)
        }
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=self.cohort_hash,
            universe_manifest=foreign_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=True,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("unrecognized_universe_symbol", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_missing_expected_universe_hash_fails_closed(self) -> None:
        """expected_universe_hash=None must fail closed."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = evaluate_stage1_switch_preflight(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            required_universe=self.admitted_uuids,
            expected_universe_hash=None,
            universe_manifest=self.universe_manifest,
            current_portfolio_state=port,
            account_id="account-alpha",
            mandate="balanced_stage1",
            open_orders=(),
            mandate_verified=True,
            risk_verified=True,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertIn("missing_expected_universe_hash", res.reason)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)

    def test_unknown_corporate_action_coverage_unavailable(self) -> None:
        """adjustments_by_security=None is unknown and returns UNAVAILABLE."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            adjustments_by_security=None,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_adjustments_manifest", res.reason)

    # =========================================================================
    # Point 7: C1-C6 Review Corrections Regression Suite
    # =========================================================================

    def test_valid_strong_lane_decision_context_b3_eligible(self) -> None:
        """C1: Strong lane StrategyDecisionContextV1 is eligible for B3."""
        ctx = self._build_strong_lane_context(session_count=1)
        res = self._eval(
            proposed_strategy="B3",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")

    def test_valid_strong_lane_decision_context_b4_eligible(self) -> None:
        """C1: Strong lane StrategyDecisionContextV1 is eligible for B4."""
        ctx = self._build_strong_lane_context(session_count=255)
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B4")

    def test_valid_strong_lane_decision_context_b5_eligible(self) -> None:
        """C1: Strong lane StrategyDecisionContextV1 is eligible for B5."""
        ctx = self._build_strong_lane_context(session_count=65)
        res = self._eval(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B5")

    def test_missing_strong_lane_views_returns_unavailable(self) -> None:
        """C1: Missing views for an admitted security returns UNAVAILABLE."""
        groups = []
        for sym in self.universe12_syms:
            if sym == "VOO":
                continue
            sec_id = self.etf_uuids[sym]
            v = self._make_valid_derived_view(sec_id, self.today, self.base_prices[sym])
            groups.append(StrategyDecisionViewV1(security_id=sec_id, views=(v,)))

        ctx = self._build_strong_lane_context(session_count=255)
        ctx_missing_voo = ctx.model_copy(update={"decision_views": tuple(groups)})
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx_missing_voo,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_observations", res.reason)

    def test_late_available_strong_lane_observation_returns_unavailable(
        self,
    ) -> None:
        """C1: Strong lane observation past cutoff returns UNAVAILABLE."""
        sec_voo = self.etf_uuids["VOO"]
        ctx = self._build_strong_lane_context(session_count=255)
        late_view = self._make_valid_derived_view(
            sec_voo,
            self.today,
            self.base_prices["VOO"],
            decision_time=self.closed_at + timedelta(minutes=5),
        )
        new_groups = []
        for g in ctx.decision_views:
            if g.security_id == sec_voo:
                new_groups.append(
                    StrategyDecisionViewV1.model_construct(
                        security_id=sec_voo,
                        views=(*g.views[:-1], late_view),
                    )
                )
            else:
                new_groups.append(g)

        bad_ctx = StrategyDecisionContextV1.model_construct(
            session_key=ctx.session_key,
            decision_session=ctx.decision_session,
            decision_cutoff=ctx.decision_cutoff,
            admitted_universe=ctx.admitted_universe,
            current_holdings=ctx.current_holdings,
            current_cash=ctx.current_cash,
            portfolio_nav=ctx.portfolio_nav,
            decision_views=tuple(new_groups),
        )
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=bad_ctx,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("late_available_observation_detected", res.reason)

    def test_cross_lane_evidence_contamination_rejected(self) -> None:
        """C1: Cross-lane evidence contamination returns REJECTED."""
        sec_voo = self.etf_uuids["VOO"]
        real_view = self._make_valid_derived_view(
            sec_voo, self.today, Decimal("500.00")
        )
        fake_group = StrategyDecisionViewV1(
            security_id=sec_voo,
            views=(real_view,),
        )
        ctx = ExploratoryStrategyDecisionContextV1.model_construct(
            session_key=self.session_key,
            decision_session=self.session,
            decision_cutoff=self.closed_at,
            cohort_hash=self.cohort_hash,
            admitted_cohort=self.admitted_uuids,
            current_holdings=(),
            current_cash=Decimal("100000.00"),
            portfolio_nav=Decimal("100000.00"),
            reconstructed_decision_views=(fake_group,),
            acknowledged_limitations=(
                ALPACA_LIMITATION_ABSENT_HALTS,
                ALPACA_LIMITATION_BOUNDED_COHORT,
                ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
                ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                ALPACA_LIMITATION_UNVERSIONED_BARS,
            ),
        )
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("cross_lane_evidence_detected", res.reason)

    def test_abstain_with_none_decision_context_fails_safely(self) -> None:
        """C2: ABSTAIN with decision_context=None cannot claim safe hold."""
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=None,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("missing_decision_context", res.reason)

    def test_b4_with_none_decision_context_fails_safely(self) -> None:
        """C2: B4 proposed with decision_context=None cannot claim safe hold."""
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=None,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("missing_decision_context", res.reason)

    def test_missing_decision_cutoff_fails_closed(self) -> None:
        """C2: Missing decision_cutoff returns INDETERMINATE_SAFETY."""
        ctx = self._build_context(session_count=255)
        bad_ctx = ExploratoryStrategyDecisionContextV1.model_construct(
            session_key=ctx.session_key,
            decision_session=ctx.decision_session,
            decision_cutoff=None,
            cohort_hash=ctx.cohort_hash,
            admitted_cohort=ctx.admitted_cohort,
            current_holdings=ctx.current_holdings,
            current_cash=ctx.current_cash,
            portfolio_nav=ctx.portfolio_nav,
            reconstructed_decision_views=ctx.reconstructed_decision_views,
            acknowledged_limitations=ctx.acknowledged_limitations,
        )
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=bad_ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res.is_tradeable)
        self.assertFalse(res.hold_incumbent)
        self.assertTrue(res.requires_containment)
        self.assertIn("missing_decision_cutoff", res.reason)

    def test_valid_incumbent_with_complete_context_safely_holds(self) -> None:
        """C2: Complete context allows safe hold when switch is UNAVAILABLE."""
        ctx = self._build_context(session_count=50)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")

    def test_missing_calendar_evidence_returns_unavailable(self) -> None:
        """C3: Missing trading calendar evidence returns UNAVAILABLE."""
        ctx = self._build_context(session_count=255)
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            completed_sessions=None,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertIn("missing_trading_calendar_evidence", res.reason)

    def test_weekend_observation_detected_rejected(self) -> None:
        """C3: Observation falling on a weekend returns REJECTED."""
        sec_voo = self.etf_uuids["VOO"]
        saturday = date(2026, 1, 24)
        trading_days = generate_synthetic_trading_sessions(254, self.today)
        obs_list = [
            self._make_valid_observation(sec_voo, d, Decimal("500.00"))
            for d in trading_days
        ]
        saturday_obs = self._make_valid_observation(
            sec_voo, saturday, Decimal("500.00")
        )
        obs_list.append(saturday_obs)
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("weekend_observation_detected", res.reason)

    def test_closed_session_holiday_observation_rejected(self) -> None:
        """C3: Observation on exchange holiday (MLK Day) returns REJECTED."""
        sec_voo = self.etf_uuids["VOO"]
        mlk_day = date(2026, 1, 19)
        trading_days = [
            d
            for d in generate_synthetic_trading_sessions(255, self.today)
            if d != mlk_day
        ][:254]
        obs_list = [
            self._make_valid_observation(sec_voo, d, Decimal("500.00"))
            for d in trading_days
        ]
        holiday_obs = self._make_valid_observation(sec_voo, mlk_day, Decimal("500.00"))
        obs_list.append(holiday_obs)
        ctx = self._build_context(
            session_count=255,
            custom_observations_by_sym={"VOO": obs_list},
            bypass_view_validator=True,
        )
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
        )
        self.assertEqual(res.status, PreflightStatus.REJECTED)
        self.assertIn("closed_session_observation_detected", res.reason)

    def test_observed_holiday_observation_rejected(self) -> None:
        """C3: Observation on observed holiday returns REJECTED."""
        holidays_2026 = SyntheticExchangeCalendar.get_holidays(2026)
        self.assertIn(date(2026, 1, 19), holidays_2026)
        self.assertIn(date(2026, 4, 3), holidays_2026)
        self.assertIn(date(2026, 5, 25), holidays_2026)

    def test_half_day_session_accepted_as_valid(self) -> None:
        """C3: Half-day session (Black Friday) is accepted as open session."""
        half_days = SyntheticExchangeCalendar.get_half_days(2026)
        self.assertIn(date(2026, 11, 27), half_days)
        self.assertTrue(
            SyntheticExchangeCalendar.is_trading_session(date(2026, 11, 27))
        )

    def test_b4_sessions_boundary_252_vs_253(self) -> None:
        """C3: B4 requires 253 sessions (252 UNAVAILABLE, 253 ELIGIBLE)."""
        ctx_252 = self._build_context(session_count=252)
        res_252 = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx_252,
        )
        self.assertEqual(res_252.status, PreflightStatus.UNAVAILABLE)

        ctx_253 = self._build_context(session_count=253)
        res_253 = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx_253,
        )
        self.assertEqual(res_253.status, PreflightStatus.ELIGIBLE)

    def test_b5_sessions_boundary_60_vs_61(self) -> None:
        """C3: B5 requires 61 sessions (60 UNAVAILABLE, 61 ELIGIBLE)."""
        ctx_60 = self._build_context(session_count=60)
        res_60 = self._eval(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx_60,
        )
        self.assertEqual(res_60.status, PreflightStatus.UNAVAILABLE)

        ctx_61 = self._build_context(session_count=61)
        res_61 = self._eval(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx_61,
        )
        self.assertEqual(res_61.status, PreflightStatus.ELIGIBLE)

    def test_verify_tampered_is_tradeable_fails(self) -> None:
        """C4: Tampered is_tradeable flag fails downstream verification."""
        port = self._make_valid_portfolio_state()
        res_unavail = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=self._build_context(session_count=50),
            current_portfolio_state=port,
        )
        self.assertFalse(res_unavail.is_tradeable)
        forged = Stage1SwitchPreflightResult.model_construct(**dict(res_unavail))
        object.__setattr__(forged, "is_tradeable", True)
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                forged,
                current_portfolio_state=port,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
            )
        self.assertIn("validation / coherence check", str(cm.exception))

    def test_verify_tampered_status_fails(self) -> None:
        """C4: Tampered status with unchanged hash fails verification."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        forged = Stage1SwitchPreflightResult.model_construct(**dict(res))
        object.__setattr__(forged, "status", PreflightStatus.REJECTED)
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                forged,
                current_portfolio_state=port,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
            )
        self.assertIn("validation / coherence check", str(cm.exception))

    def test_verify_tampered_reason_fails(self) -> None:
        """C4: Tampered reason with unchanged hash fails verification."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        forged = Stage1SwitchPreflightResult.model_construct(**dict(res))
        object.__setattr__(forged, "reason", "forged_clean_reason")
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                forged,
                current_portfolio_state=port,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
            )
        self.assertIn("validation / coherence check", str(cm.exception))

    def test_verify_tampered_hold_incumbent_fails(self) -> None:
        """C4: Tampered hold_incumbent flag fails verification."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        forged = Stage1SwitchPreflightResult.model_construct(**dict(res))
        object.__setattr__(forged, "hold_incumbent", True)
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                forged,
                current_portfolio_state=port,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=self.closed_at,
                expected_cohort_hash=self.cohort_hash,
            )
        self.assertIn("validation / coherence check", str(cm.exception))

    def test_verify_wrong_expected_cutoff_fails(self) -> None:
        """C4/C6: Verification fails if expected cutoff does not match."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        wrong_cutoff = self.closed_at + timedelta(hours=1)
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res,
                current_portfolio_state=port,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_decision_cutoff=wrong_cutoff,
                expected_cohort_hash=self.cohort_hash,
            )
        self.assertIn("decision_cutoff mismatch", str(cm.exception))

    # =========================================================================
    # Regressions for Issue 422 / PR 424: Strong Context Cohort Binding & Hold
    # =========================================================================

    def test_regression_strong_context_b3_incumbent_abstain_verifies(self) -> None:
        """1. Valid strong context + B3 incumbent + ABSTAIN:
        safe hold, cohort bound, verifier passes.
        """
        ctx = self._build_strong_lane_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ABSTAIN)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertEqual(res.cohort_hash, self.cohort_hash)
        self.assertEqual(res.admitted_universe, self.admitted_uuids)

        verified = verify_stage1_switch_preflight_result(
            res,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
            expected_cohort_hash=self.cohort_hash,
            expected_decision_cutoff=self.closed_at,
            current_portfolio_state=port,
            expected_universe=self.admitted_uuids,
        )
        self.assertTrue(verified)

    def test_regression_strong_context_b4_short_history_safe_hold_verifies(
        self,
    ) -> None:
        """2. Strong context + B4 with 252 sessions:
        UNAVAILABLE, safe hold, verifier passes.
        """
        ctx = self._build_strong_lane_context(session_count=252)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertEqual(res.cohort_hash, self.cohort_hash)
        self.assertEqual(res.admitted_universe, self.admitted_uuids)

        verified = verify_stage1_switch_preflight_result(
            res,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
            expected_cohort_hash=self.cohort_hash,
            expected_decision_cutoff=self.closed_at,
            current_portfolio_state=port,
            expected_universe=self.admitted_uuids,
        )
        self.assertTrue(verified)

    def test_regression_strong_context_b5_short_history_safe_hold_verifies(
        self,
    ) -> None:
        """3. Strong context + B5 with 60 sessions:
        UNAVAILABLE, safe hold, verifier passes.
        """
        ctx = self._build_strong_lane_context(session_count=60)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.UNAVAILABLE)
        self.assertFalse(res.is_tradeable)
        self.assertTrue(res.hold_incumbent)
        self.assertFalse(res.requires_containment)
        self.assertEqual(res.effective_strategy, "B3")
        self.assertEqual(res.cohort_hash, self.cohort_hash)
        self.assertEqual(res.admitted_universe, self.admitted_uuids)

        verified = verify_stage1_switch_preflight_result(
            res,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
            expected_cohort_hash=self.cohort_hash,
            expected_decision_cutoff=self.closed_at,
            current_portfolio_state=port,
            expected_universe=self.admitted_uuids,
        )
        self.assertTrue(verified)

    def test_regression_controls_b4_at_253_and_b5_at_61_eligible_verifies(self) -> None:
        """4. B4 at 253 and B5 at 61 remain eligible controls and verify."""
        port = self._make_valid_portfolio_state()

        # B4 at 253
        ctx_b4 = self._build_strong_lane_context(session_count=253)
        res_b4 = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx_b4,
            current_portfolio_state=port,
        )
        self.assertEqual(res_b4.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res_b4.is_tradeable)
        self.assertFalse(res_b4.hold_incumbent)
        self.assertEqual(res_b4.effective_strategy, "B4")
        self.assertEqual(res_b4.cohort_hash, self.cohort_hash)
        verified_b4 = verify_stage1_switch_preflight_result(
            res_b4,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
            expected_cohort_hash=self.cohort_hash,
            expected_decision_cutoff=self.closed_at,
            current_portfolio_state=port,
            expected_universe=self.admitted_uuids,
        )
        self.assertTrue(verified_b4)

        # B5 at 61
        ctx_b5 = self._build_strong_lane_context(session_count=61)
        res_b5 = self._eval(
            proposed_strategy="B5",
            current_strategy="B3",
            decision_context=ctx_b5,
            current_portfolio_state=port,
        )
        self.assertEqual(res_b5.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res_b5.is_tradeable)
        self.assertFalse(res_b5.hold_incumbent)
        self.assertEqual(res_b5.effective_strategy, "B5")
        self.assertEqual(res_b5.cohort_hash, self.cohort_hash)
        verified_b5 = verify_stage1_switch_preflight_result(
            res_b5,
            expected_account_id="account-alpha",
            expected_mandate="balanced_stage1",
            expected_session_key=self.session_key,
            expected_cohort_hash=self.cohort_hash,
            expected_decision_cutoff=self.closed_at,
            current_portfolio_state=port,
            expected_universe=self.admitted_uuids,
        )
        self.assertTrue(verified_b5)

    def test_regression_invalid_missing_cohort_manifest_hash_no_safe_hold(
        self,
    ) -> None:
        """5. Invalid/missing cohort, manifest, or expected hash:
        no tradeable and no safe hold.
        """
        ctx = self._build_strong_lane_context(session_count=255)
        port = self._make_valid_portfolio_state()

        # ABSTAIN with missing manifest
        res_no_man = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            universe_manifest=None,
        )
        self.assertEqual(res_no_man.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res_no_man.is_tradeable)
        self.assertFalse(res_no_man.hold_incumbent)
        self.assertTrue(res_no_man.requires_containment)
        self.assertIsNone(res_no_man.cohort_hash)
        with self.assertRaises(ValueError):
            verify_stage1_switch_preflight_result(
                res_no_man,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_cohort_hash=self.cohort_hash,
                expected_decision_cutoff=self.closed_at,
                current_portfolio_state=port,
            )

        # B4 short history with missing required universe
        res_no_u = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=self._build_strong_lane_context(session_count=252),
            current_portfolio_state=port,
            required_universe=None,
        )
        self.assertEqual(res_no_u.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res_no_u.is_tradeable)
        self.assertFalse(res_no_u.hold_incumbent)
        self.assertTrue(res_no_u.requires_containment)
        self.assertIsNone(res_no_u.cohort_hash)

        # B4 short history with wrong expected universe hash on strong context
        # fails downstream verification
        res_wrong_h = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=self._build_strong_lane_context(session_count=252),
            current_portfolio_state=port,
            expected_universe_hash="f" * 64,
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                res_wrong_h,
                expected_account_id="account-alpha",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_cohort_hash=self.cohort_hash,
                expected_decision_cutoff=self.closed_at,
                current_portfolio_state=port,
            )
        self.assertIn("cohort_hash mismatch", str(cm.exception))

        # On exploratory context where cohort_hash is present on context,
        # preflight returns INDETERMINATE_SAFETY
        res_wrong_h_ctx = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=self._build_context(session_count=252),
            current_portfolio_state=port,
            expected_universe_hash="f" * 64,
        )
        self.assertEqual(res_wrong_h_ctx.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res_wrong_h_ctx.is_tradeable)
        self.assertFalse(res_wrong_h_ctx.hold_incumbent)
        self.assertTrue(res_wrong_h_ctx.requires_containment)
        self.assertIsNone(res_wrong_h_ctx.cohort_hash)

    def test_regression_invalid_portfolio_account_or_cutoff_fails_safe_hold(
        self,
    ) -> None:
        """6. Invalid current portfolio, changed account or cutoff:
        existing rejection/containment remains.
        """
        ctx = self._build_strong_lane_context(session_count=252)
        port = self._make_valid_portfolio_state()

        # Unverified risk blocks safe hold
        res_risk = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            risk_verified=False,
        )
        self.assertEqual(res_risk.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res_risk.is_tradeable)
        self.assertFalse(res_risk.hold_incumbent)
        self.assertTrue(res_risk.requires_containment)

        # Pending orders block safe hold
        res_orders = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            open_orders=("order-1",),
        )
        self.assertEqual(res_orders.status, PreflightStatus.INDETERMINATE_SAFETY)
        self.assertFalse(res_orders.is_tradeable)
        self.assertFalse(res_orders.hold_incumbent)
        self.assertTrue(res_orders.requires_containment)

        # Changed account in verifier rejects verified preflight result
        valid_res = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            account_id="account-alpha",
        )
        with self.assertRaises(ValueError) as cm:
            verify_stage1_switch_preflight_result(
                valid_res,
                expected_account_id="account-beta",
                expected_mandate="balanced_stage1",
                expected_session_key=self.session_key,
                expected_cohort_hash=self.cohort_hash,
                expected_decision_cutoff=self.closed_at,
                current_portfolio_state=port,
            )
        self.assertIn("account_id mismatch", str(cm.exception))

    def test_regression_exploratory_context_controls_continue_to_work(self) -> None:
        """7. Exploratory-context controls continue to work as expected."""
        ctx = self._build_context(session_count=255)
        port = self._make_valid_portfolio_state()
        res = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res.status, PreflightStatus.ELIGIBLE)
        self.assertTrue(res.is_tradeable)
        self.assertEqual(res.cohort_hash, self.cohort_hash)

        res_abstain = self._eval(
            proposed_strategy="ABSTAIN",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
        )
        self.assertEqual(res_abstain.status, PreflightStatus.ABSTAIN)
        self.assertFalse(res_abstain.is_tradeable)
        self.assertTrue(res_abstain.hold_incumbent)
        self.assertEqual(res_abstain.cohort_hash, self.cohort_hash)

    def test_regression_no_caller_state_positions_or_orders_mutate(
        self,
    ) -> None:
        """8. No caller state, positions, or orders mutate during
        preflight evaluation.
        """
        ctx = self._build_strong_lane_context(session_count=255)
        port = self._make_valid_portfolio_state()
        orders: list[str] = ["order-1", "order-2"]

        ctx_holdings_before = tuple(ctx.current_holdings)
        port_holdings_before = tuple(port.holdings)
        orders_before = list(orders)
        port_cash_before = port.cash_balance

        _ = self._eval(
            proposed_strategy="B4",
            current_strategy="B3",
            decision_context=ctx,
            current_portfolio_state=port,
            open_orders=orders,
        )

        self.assertEqual(tuple(ctx.current_holdings), ctx_holdings_before)
        self.assertEqual(tuple(port.holdings), port_holdings_before)
        self.assertEqual(orders, orders_before)
        self.assertEqual(port.cash_balance, port_cash_before)


if __name__ == "__main__":
    unittest.main()
