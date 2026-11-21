# Evaluator cash yield (optional, exploratory)

Status: draft implementation on branch `claude/evaluator-cash-yield`. This is
an accounting change, so it is a Decision Packet candidate: it needs an owner
ruling and an independent review before it is treated as accepted behavior.
Hosted CI has not run on it. No GitHub issue exists for it yet.

## What it does

By default idle cash in an M2 evaluation book earns nothing. A caller may now
hand the evaluator a `CashYieldPolicyV1`: a point-in-time series of annualized
cash rates plus the conventions needed to accrue them. When a policy is
supplied, the engine credits simple interest on the cash balance once per
session, before that session's other effects. When no policy is supplied,
nothing changes at all (see [Identity impact](#identity-impact)).

The feature is exploratory only. It models a hypothetical cash sweep from a
caller-declared rate series. It is not evidence of interest any account was
paid.

| Piece | Where |
| --- | --- |
| Policy, rate record, accrual function | `src/drift/domain/evaluator_cash_yield.py` |
| Kernel credit | `PortfolioAccountingKernel.credit_cash_interest` in `src/drift/evaluator/portfolio.py` |
| Evidence field, admission checks, accrual step | `src/drift/evaluator/engine.py` |
| Trace event | `CashInterestAccruedTraceEventV1` in `src/drift/domain/evaluator_trace.py` |
| Promotion binding refusal | `_bind_decision_evidence_grade` in `src/drift/domain/evaluator_results.py` |

## Inputs

`SessionEvaluatorEvidence.cash_yield: CashYieldPolicyV1 | None = None`.

`CashYieldPolicyV1` (frozen, strict, no extra fields):

| Field | Meaning |
| --- | --- |
| `source_id` | The caller's name for the rate source. |
| `source_sha256` | Hash of the retained source bytes. It shows the bytes are the same; it does not authenticate their origin. |
| `currency_namespace`, `currency_code` | Must equal the book currency exactly. |
| `day_count` | `ACT/360` or `ACT/365F`. Required, no default. |
| `interest_quantum` | The rounding unit, a positive power of ten such as `0.01`. Required, no default. |
| `rates` | One `CashRateObservationV1` per date, non-empty, unique by date, held in date order whatever order the caller used. |
| `acknowledged_limitations` | Must include `hypothetical-exploratory-modeled-cash-yield`. |

`CashRateObservationV1`:

| Field | Meaning |
| --- | --- |
| `rate_date` | Local date of the session whose closing cash starts accruing at this rate. |
| `annualized_rate` | A fraction per year, so `0.0525` is 5.25%. `0 <= rate <= 1`. A value above 1 is refused, because it is almost always a percentage typed where a fraction belongs. |
| `known_at` | UTC instant the caller's source made the rate knowable. |

## Formula

One function, `cash_interest`, computes every accrual. The engine uses it to
credit the book and the trace event uses it again to check the credit.

```text
basis    = 360 for ACT/360, 365 for ACT/365F
exact    = cash * annualized_rate * accrual_days / basis      (exact rationals)
units    = round_half_even(exact / interest_quantum)          (the only rounding)
interest = units * interest_quantum
```

- `cash` is the whole cash balance the session opened with.
- `accrual_days` is the number of calendar days from the previous session's
  local date to this session's local date. It is always at least 1, so a
  weekend or holiday gap accrues for every calendar day in it, at the rate
  dated on the session before the gap.
- The product is computed with `fractions.Fraction`, so nothing is lost before
  the single rounding. The rounding is half to even, the same rounding the
  pinned portfolio decimal context uses. No float is involved anywhere.
- Cash that is zero or negative accrues nothing. This models interest on idle
  cash, never a borrowing charge.
- An amount the pinned 34-digit portfolio context cannot hold exactly is
  refused, not rounded a second time.

Interest is simple within one accrual period and is credited to cash, so it
compounds at session frequency.

Worked example (ACT/360, 5.25%, quantum 0.01, initial cash 100000, four
consecutive sessions and then a three-day gap):

| Session | Days | Base cash | Exact interest | Credited | Cash after |
| --- | --- | --- | --- | --- | --- |
| 0 | none | 100000.00 | none | none | 100000.00 |
| 1 | 1 | 100000.00 | 14.58333... | 14.58 | 100014.58 |
| 2 | 1 | 100014.58 | 14.58546... | 14.59 | 100029.17 |
| 3 | 1 | 100029.17 | 14.58758... | 14.59 | 100043.76 |
| 4 | 3 | 100043.76 | 43.76914... | 43.77 | 100087.53 |

## Ordering inside a session

```text
advance to the session, clear the stale mark
session start event            (opening cash = previous close cash)
cash interest credit           (this change, only with a policy, never at session 0)
pre-open corporate actions and dividend claims
open execution (fills)
intrasession settlements
close mark
post-close decision
```

Consequences:

- Interest is paid on cash actually held since the previous session, never on
  cash this session's fills create or spend, and never on holdings or pending
  claims.
- The credit happens inside the `pre_open_effects` phase, before
  `_pre_open_effects`, and uses the same trusted or untrusted dispatch as that
  call, so the prepared opening-book executor cannot be redirected through an
  injected hook.
- The credit goes through `PortfolioAccountingKernel.credit_cash_interest`,
  which raises cash and net asset value by exactly the amount inside the
  kernel transaction and the pinned decimal context. Realized PnL, costs,
  holdings, claims and marks are untouched. A promotion-lane book refuses the
  credit.
- The summary metrics report the last marked session. That is the existing
  last-checkpoint rule, and interest follows it. If a session credits interest
  and then halts, for example on a rejected rebalance, the final book's cash
  includes that session's credit and `metrics.ending_cash` does not. The two
  differ by exactly that credit.

## Point-in-time rule and construction checks

For every session `i >= 1` the engine needs the rate dated on session `i - 1`
(the exact date, never the nearest earlier record) and requires
`known_at < opened_at` of session `i`. Both are checked for every session at
engine construction, before any session runs, together with:

- the admission lane must be exploratory;
- the policy currency must equal the book currency;
- the pinned 34-digit portfolio context must hold one unit of the interest
  quantum next to the opening cash.

Records the run never reads are allowed.

Which error a refusal raises depends on where it is caught:

- a malformed policy or rate record (a rate out of range, duplicate or empty
  rates, a quantum that is not a positive power of ten, a missing limitation,
  an unknown day count) raises pydantic `ValidationError`, when the model is
  built and again when the engine revalidates its evidence;
- a promotion admission raises `PromotionLaneDisabledError` before the policy
  is read, because the promotion lane is disabled as a whole;
- the checks listed above raise `CashYieldRefusedError` (a `DriftError` and a
  `ValueError`).

Construction checks everything that can be known before the first session. It
cannot foresee every later balance. If a balance outgrows the precision a very
fine quantum leaves, the kernel refuses that one credit with
`CashYieldRefusedError` at its own step. The accrual step also re-checks the
session it is handed against the accrual it reads. Either failure is a defect
that propagates out of the run. It is never a run classification.

## Trace

A credit emits `CashInterestAccruedTraceEventV1` (`kind =
"cash_interest_accrued"`, phase `pre_open_effects`,
`is_promotion_grade_evidence = False`) carrying `policy_terms_hash`,
`rate_record_hash`, `rate_known_at`, `accrual_start_date`, `accrual_days`,
`annualized_rate`, `day_count`, `interest_quantum`, `accrual_base_cash`,
`interest` and `cash_balance_after`. Its validator recomputes the interest
with `cash_interest`, checks the days against the session date, checks
`cash_balance_after == accrual_base_cash + interest`, and rebuilds the rate
record from `accrual_start_date`, `annualized_rate` and `rate_known_at` to
check `rate_record_hash`. No event is emitted when the interest rounds to
zero.

`policy_terms_hash` is the hash of the policy without its rate series (source,
source hash, currency, day count, quantum, limitations). The one rate an
accrual read is bound by `rate_record_hash`. The complete policy, rates
included, is bound by the evaluator evidence hash in the run identity. The
event deliberately does not carry a hash of the whole rate series, because
that would make an early session's event change when a later-dated rate
changes.

The event is a member of `EvaluatorTraceEventV2` only. The frozen version 1
event union is not extended.

An event can only check itself. The version 2 trace log checks its place in
the run, and refuses a log unless every credit:

- is the only credit in its session;
- immediately follows that session's `session_start` event;
- accrues on exactly the `opening_cash` that event states;
- accrues from the local date of the session before it.

Version 1 logs cannot hold the event, so they are unaffected.

## Identity impact

Policy absent (the default):

- no key is added to the evidence hash payload, so the evaluator evidence
  hash and every run identity are unchanged;
- no event is emitted, the trace stays a version 1 log, and the result,
  trace, portfolio state and every pinned hash are byte-identical;
- no pinned schema, fixture or protected file is touched. `PortfolioStateV2`,
  the metrics model, the protocol, the cost model, the bundle, the version 1
  trace union and the identity schemas are unchanged.

Policy present:

- the evidence hash gains `cash_yield = content_hash(policy)`, so the run
  identity and the result hash change. An identity minted without the policy
  is refused by an engine holding it, and the reverse;
- the trace is a version 2 log when at least one credit occurs;
- a promotion result cannot bind a trace that contains the new event.

How the absent case was tested: characterization tests were written and
passed on unchanged main `60d572a` before any source edit. They pin the empty
evidence hash as a literal. They bind the realized fixture run, plain and
through a prepared opening book, to the trace and result hashes the repository
already pins, and pin every plain member of its final book. They still pass
unchanged. The sha256 of the complete canonical artifacts of that run was also
measured before and after the change on one machine and was identical. It is
not kept as a literal, because it would be a second copy of an existing
identity-bearing pin. The existing pinned-hash and frozen-schema tests are
untouched.

## Limitations and risks

1. **Accounting change.** Nothing pinned moves, but cash and net asset value
   change whenever a policy is supplied. It needs an owner ruling and an
   independent review. It is not self-reviewed work.
2. **Double counting with Stage 1.** Stage 1 metric math already subtracts a
   separate risk-free series (`risk_free_period_returns` in
   `src/drift/experiments/stage1_metric_math.py`). Enabling evaluator cash
   yield inside a Stage 1 study without reconciling the two would count the
   cash return in the portfolio and subtract a risk-free return on top of it.
   This change adds no Stage 1 wiring and no shipped caller builds a policy
   today. Item 3 explains why that is a convention and not a guarantee.
3. **Nothing stops a policy reaching the loop or the cohort harness.** No
   shipped caller builds a policy today, but that is caller convention, not a
   guard. `M2TrialEvaluatorAdapter` in `src/drift/loop/evaluator_adapter.py`
   accepts a ready engine (`engine=`), or evidence it passes to the engine
   unchanged, and runs it as given. The cohort harness in
   `src/drift/experiments/parallel_portfolios.py` passes its `evidence`
   straight to the engine too. Neither refuses a cash-yield policy, and
   neither marks its results as carrying one. The scorecard math in
   `src/drift/scorecards/performance.py` computes Sharpe as annualized return
   over annualized volatility, with no risk-free term. Credited interest
   therefore inflates the raw Sharpe and return metrics of cash-heavy
   strategies: a book that only holds cash earns a steady return at almost no
   volatility. The independent review of this change reported an annualized
   raw Sharpe of 17.78 for a cash-only run. This is the opposite hazard to
   item 2. There the cash return would be subtracted twice; here it is never
   subtracted. Until scorecards use returns in excess of the risk-free rate,
   results with a policy are not comparable with results without one. A
   follow-up issue is needed for a refusal or an explicit label in the loop
   adapter and the cohort harness, and for the scorecard fix. This change
   does not edit those modules.
4. **`known_at` is caller-asserted.** The engine enforces ordering against the
   session clock. It cannot know whether the source really published the rate
   at that instant. `source_sha256` is a consistency binding, not origin
   authentication.
5. **Daily credit is generous.** Interest is credited every session and is
   spendable at that open. A real sweep account usually pays monthly, may
   apply tiers, minimums or fees, and may not pay on unsettled cash. Results
   with a policy overstate what such an account would pay.
6. **Exploratory lane only.** The policy is refused under any other
   admission, the kernel refuses the credit on a promotion-lane book, the
   event states it is not promotion-grade evidence, and a promotion result
   cannot bind a trace that contains it.
7. **Total interest is recoverable only from the trace.** The summary metrics
   have no interest field, by design, so the pinned metrics schema does not
   move. Interest shows up in ending cash, net asset value and net profit and
   loss. Realized PnL does not include it.
8. **One rate per accrual period.** The rate dated on the session before a gap
   applies to every calendar day of the gap. A rate change over a weekend is
   not modeled.
9. **Exact dates only.** A session date with no rate record is refused. The
   engine never carries a rate forward, so the caller must supply a record for
   every session date except the last.
10. **Positive balances only.** No borrowing cost is modeled. The book
    cannot hold negative cash today, so this only matters if that ever changes.
11. **Downstream trace readers.** Consumers that reconcile cash from trace
    events (for example Stage 1 readback code) do not know the new event. No
    shipped caller hands them a policy today, but as item 3 says, nothing
    refuses one.
