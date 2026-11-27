# Historical replay criteria

Frozen before any portfolio-manager response. Criteria file SHA-256
`e999e4a02d7704c551ea45c9f7bf7c17c3c397e199f74cdebd2612f2461586a2`
from `.local-artifacts/historical/criteria.json`. Do not edit the selected
dates after the first model response. Later notes belong in `results.md`.

## Rules

Non-overlapping 12-session blocks on Yahoo `^SP500TR` closes from
2021-01-04 through 2025-12-31. The block needs a prior close and a
following session for the fill. Take the earliest block that matches.
Do not take a later block because the move is larger.

- Bullish: total return at least 4%, then 3%, then 2%, and max drawdown
  not worse than 3%.
- Bearish: total return at most -4%, then -3%, then -2%.
- Sideways: absolute return at most 1%, then 1.5%, then 2%, with
  drawdown and runup inside 2%, then 3%, then 4%.

Blocks that contain a chart split, or any date from 2023-08-14 through
2023-08-25, are ineligible. All three selected blocks matched the first
threshold.

## Selected windows

| Regime | Warmup | Decisions | Settlement | Total return |
| --- | --- | --- | --- | --- |
| Bullish | 2021-03-30 | 2021-03-31 through 2021-04-16 | 2021-04-19 | 0.0541 |
| Sideways | 2021-02-05 | 2021-02-08 through 2021-02-24 | 2021-02-25 | 0.0035 |
| Bearish | 2021-12-31 | 2022-01-03 through 2022-01-19 | 2022-01-20 | -0.0545 |

Twelve decisions in each regime is 36 sessions per model on one memory arm.

## Books

Isolated $10,000 ledgers. Same mandate, evidence, and instructions.
`memory` includes prior decision text. `nomemory` omits decision,
reflection, and feedback text and still shows positions. Models are
`codex/gpt-6.1-terra@xhigh` and `codex/gpt-6.2-sol@xhigh`. A proposal
must use `inference=native_supervised`. Scripted text is not a model
decision.

## Data labeled before inference

- Alpaca SIP and IEX both returned HTTP 401 for the stored paper
  credentials. Entitlement was not observable. No new credential was
  created.
- Prices are Yahoo chart v8 quote opens and closes, rounded half-up to
  cents. They differ from adjusted closes, so dividends are not in the
  price. They are not official exchange prints. No split events were
  in the downloaded chart payload.
- Benchmark is Yahoo `^SP500TR`, labeled S&P 500 total return, not an
  official index print. Portfolio results are price returns because
  dividends are not credited.
- SEC submissions and companyfacts are the filings and fundamentals.
  SPY companyfacts returned HTTP 404. X and historical news were not
  collected.

## Counts

Net and benchmark-relative return, a cash control, a mandate-capped
one-shot SPY hold, drawdown, volatility, concentration, turnover,
abstention, invalid responses, and whether cited ids exist. System
cost stays unknown unless the runtime returns a billed amount.
Simulated return does not by itself name a winner.
