# Stage 1 Balanced target-weight structural feasibility (Issue #542)

**Status: development-only mathematical candidate. Code and synthetic tests committed but NOT RUN. No operative risk limits are accepted or changed.**

## Why this slice exists

Matthew's original [#380](https://github.com/KanujVerma/drift/issues/380) MANDATE/APPROVAL specification remains a proposed, unmerged [PR #414](https://github.com/KanujVerma/drift/pull/414). The proposed 15%-single-fund/80%-gross synthetic values there conflict with nearly fully invested Stage 1 B3 and six-position B4/B5. Kanuj's accepted **research direction only** (not G3 policy freeze) on #380 is to study the 20%-single-fund, 70%-equities, 75%-bonds, 20%-gold, 100%-gross candidate, with stricter/looser comparisons using development-only data. Its original [ETF risk feasibility packet](../stage1-risk-universe-feasibility.md) contains an independent static combinatorial enumeration. This code provides an **executable mathematical oracle** for those named structural cases; it is not the production mandate, an ETF signal, a backtest, or any source/issuer acceptance.

**Accountable risk producer:** Matthew. **Actual coding publisher:** GPT-6 through authenticated `Krish-Verma`, per user's requested next pair of inactive Matthew-area coding tasks. Exact bounded child [#542](https://github.com/KanujVerma/drift/issues/542); the companion child [#543](https://github.com/KanujVerma/drift/issues/543) reviews actual V1 execution evidence. No original ownership, writer release, scientific signoff or broker authority is assumed.

Read [AGENTS.md](../../../../AGENTS.md), [agent workflow](../../agent-workflow.md), [owner Stage 1 risk research](../stage1-risk-universe-feasibility.md), [Stage 1 decisions](../stage1-decisions.md), [#380](https://github.com/KanujVerma/drift/issues/380) and the actual B3/B4/B5 source (`src/drift/baselines/`) for independent verification.

## Exact new files, no overlap

- `scripts/stage1_balanced_feasibility.py`: typed, in-memory Decimal/Fraction arithmetic and exhaustive subset enumeration.
- `tests/unit/test_stage1_balanced_feasibility.py`: intentionally unrun numeric and adversarial regression tests.
- `docs/architecture/adaptive-experiments/verification/stage1-balanced-feasibility.md`: this source/fixture/test and acceptance handoff.

No existing M2 evaluator, risk-policy, gatekeeper, account, B3/B4/B5, Stage 1 E1/E6B, original #380 proposal, existing #529 approval preflight, CI, source provider, broker, private data, interpreter or lockfile was edited. The helper has no file, network or broker operations.

## Formula and input contract

The caller must explicitly supply a bounded, uniquely named study universe of `ETFStudyMember(ticker, role)`, with role one of `EQUITY`, `BOND`, `GOLD`. The twelve **study-fixture classifications**, not historically verified issuer/venue facts, are:

- Equities: VOO, IJH, IJR, QQQ, VEA, VWO (six)
- Fixed income: SHY, IEF, TLT, TIP, LQD (five)
- Gold: GLD (one)

`DevelopmentTargetCaps(per_etf, equities, bonds, gold, gross)` has **no defaults**. Each cap is caller-supplied as an exact finite Decimal fraction in [0,1]. A float, NaN, infinity, negative number, cap exceeding 100%, forged `Decimal` subclass or wrong policy class refuses. A caller cannot infer a legitimate actual ETF classification from this fixture.

`review_equal_target_subset(members, selected_tickers, policy)` checks only an **equal continuous notional target**: for n distinct selected funds, each fund weight is the exact rational 1/n, each class weight is the number of selected members in that class divided by n, and target gross investment is 1. Each cap check uses the exact inequality `Decimal(class_count) <= proposed_cap * Decimal(n)`; there is **no binary float** and no rounding at a cap boundary. The result returns rational weights, class counts reflected in weights, explicit reason codes for proposed ETF/class/gross violations and `approved_for_order_or_risk_control=False`.

`enumerate_equal_target_subsets(members, policy, selected_count=None)` uses the current B4/B5 rule `ceil(n/2)` unless an explicit valid count is supplied. It deterministically enumerates all unordered possible ticker combinations and reports how many satisfy the supplied cap scenario, with bounded example rejected sets, violation counts and a separate B3 all-member equal-target analysis. Max universe size 16 is a defensive fixture limit, not an accepted investment mandate. It deliberately does **not** call `B4MomentumStrategy`, `B5LowVolatilityStrategy` or a market-data provider; actual history may yield non-uniform monthly rankings. A target being structurally feasible is not evidence that B4/B5 will ever select that set, or that its orders are possible at the next open.

## Exact mathematical acceptance oracles

All values below are research hypotheses/sensitivities, **not accepted deployment constraints**.

| Proposed structural scenario | B4/B5 6-position subsets feasible | Total possibilities |
| --- | ---: | ---: |
| ETF cap 15%; E 70%; bonds 75%; gold 20%; gross 100% | 0 | 924 |
| ETF 20%; E 65%; bonds 75%; gold 20%; gross 100% | 655 | 924 |
| ETF 20%; E 70%; bonds 75%; gold 20%; gross 100% | 880 | 924 |
| ETF 25%; E 70%; bonds 75%; gold 20%; gross 100% | 880 | 924 |
| ETF 25%; E 85%; bonds 85%; gold 20%; gross 100% | 923 | 924 |
| ETF 20%; E 70%; bonds 75%; gold 15%; gross 100% | 425 | 924 |
| Same proposed 20/70/75/20/100 candidate, excluding QQQ (11 ETFs) | 450 | 462 |

For all twelve ETFs, B3's continuous weight vector has exactly 1/12 per fund, 6/12 equity, 5/12 bond, 1/12 gold. Each six-member B4/B5 target has exactly 1/6 per selected fund. With the 20/70/75/20/100 caps, 37 subsets with five or six equities violate the equity cap and seven containing all five bonds violate the bond cap; there is no overlap, yielding 924 - 44 = 880. For the 11-member no-QQQ sensitivity, 12 selections violate class caps and 450 pass. This is a finite *combinatorial* count, not a historical 95.24% chance of a permitted switch or a statistical confidence level.

## Explicit boundaries and safety

A structural B3/B4/B5 equal-dollar plan is **not a whole-share target**. Actual holdings, fresh source prices, sessions, trading costs, working orders, pending fills, price drift, spread/slippage and account NAV require the original M2/EXEC/RESULT producer. Those may make a mathematical selection unexecutable or breach a cap after fills. The accepted Gatekeeper currently considers order-level quantity/notional/exposure; it does not bind all multi-asset target-class caps, an atomic transition or accepted minimum-trim/remediation policy. This study does not call or bypass it.

The project must keep the frozen B3/B4/B5 semantics and apply the **same effective accepted risk policy** to AI B and conventional R. The primary Stage 1 research protocol is **reject** incoming noncompliant proposals; trimming and existing-holding protective remediation are independent *unapproved* mechanisms. Nothing in this helper proposes new position orders, liquidates holdings, forces cash or supplies an accepted user-specific investor mandate. It never uses historical market returns to tune a cap. Fund-role classifications must be independently verified and versioned at the scored decision time. The ETF set itself is not source-qualified and ARCX venue support remains a separate concern.

`EqualTargetReview.approved_for_order_or_risk_control` and `EqualTargetSweep.approves_mandate_or_execution` are always **False**, and `is_historical_acceptance_rate=False` is also permanent. An integer enumeration is never market performance, an actual trader's probability of gain or a risk-policy signature.

## Deferred AntiGravity acceptance

Per user instruction, **no tests, Ruff, mypy, build or scientific simulation have been executed** on this branch. AntiGravity should inspect the exact PR HEAD, all three new paths and the Stage 1 research packet. Under the unchanged pinned interpreter/lockfile run:

```bash
uv run pytest tests/unit/test_stage1_balanced_feasibility.py -q
uv run ruff check scripts/stage1_balanced_feasibility.py tests/unit/test_stage1_balanced_feasibility.py
uv run ruff format --check scripts/stage1_balanced_feasibility.py tests/unit/test_stage1_balanced_feasibility.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Verify the exact numeric matrix above independently and adversarial cases: inverted or duplicate universe members, unrecognized role/ticker, invalid float/NaN caps, boolean selected count, invalid selected/security, class-only limits independent of per-ETF, 80% gross refusing fully invested B3 and six-member B4/B5, a shuffled ticker input yielding the same answer, and zero ability to stage an order. Compare against accepted B4/B5 `ceil(n/2)` source behavior; real fee/price/dynamic target/timing tests belong to Matthew under a newly approved integrated write-set. GitHub Actions may run on draft publication, but its results are separate from the user-requested consolidated AntiGravity pass. **No observed test success or independent approval is asserted here.**

Next Matthew action: approve or amend actual policy and risk/EXEC version semantics after empirical development-only comparison and independent scientific review; Kanuj owns final numerical/methodology freeze. Original #380 remains open, proposal #414 remains draft and unchanged. Keep this draft unmerged until independent test/contract review; no orders, real data or capital.
