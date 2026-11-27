# Historical replay results

Issue [#686](https://github.com/KanujVerma/drift/issues/686). These are
retrospective simulations. Both models can already know this public
history. The results are not evidence of an investing edge, and they do
not name a winner.

## Identity and cost

Decisions were native Codex calls at reasoning effort `xhigh`.
Completed runs reported `executedModel` `gpt-6.1-terra` or
`gpt-6.2-sol`, matching the requested id. The runtime returned no billed
amount. System cost is unknown, not zero. Observed wall time for a
completed call was usually under one minute.

The prompt told each call to read only its own decision file. That is
an instruction, not a sandbox. Each decision was a new call. Models did
not see each other's outputs.

## Windows and sessions

Windows were frozen before the first model response. Criteria SHA-256
`e999e4a02d7704c551ea45c9f7bf7c17c3c397e199f74cdebd2612f2461586a2`.
The pre-registered return is the change from the first decision close
to the last decision close.

| Regime | Decisions | Settlement | Frozen return |
| --- | --- | --- | --- |
| Bullish | 2021-03-31 through 2021-04-16 | 2021-04-19 | +5.41% |
| Sideways | 2021-02-08 through 2021-02-24 | 2021-02-25 | +0.35% |
| Bearish | 2022-01-03 through 2022-01-19 | 2022-01-20 | -5.45% |

Twelve books each recorded 12 decisions: 144 in total. Universe AAPL,
MSFT, JNJ, SPY. Cash started at $10,000. The local test limits are a
25% position cap, a $2,000 cash floor, a $1 fee, and a 336-hour evidence
age. Those limits are not an approved product mandate.

## What the models did

Ten books never traded. Both models, with and without prior decision
text, held cash through the sideways and bearish windows. Both memory
books also held cash through the bullish window.

The only trades were on the bullish memory-disabled books:

| Book | Action | Result |
| --- | --- | --- |
| Sol, no memory | Buy 12 AAPL on 2021-04-09 | Rejected. Two of five citations were SPY closes. No fill. |
| Sol, no memory | Buy 4 SPY on 2021-04-13 | Accepted. Filled at the 2021-04-14 open, $412.83, plus the $1 fee. Cash left $8,347.68. |
| Terra, no memory | Buy 4 SPY on 2021-04-15 | Accepted. Filled at the 2021-04-16 open, $417.25, plus the $1 fee. Cash left $8,330.00. |

Both later sessions held the four shares. Sol quoted the cash and the
16.5% cost weight. Terra said the recent evidence did not explain the
earlier purchase. The memory-disabled prompt shows positions and hides
prior decision text, so that statement is consistent with the prompt.

Ending value uses the 2021-04-19 SPY close of $415.21. Sol's book is
$10,008.52. Terra's book is $9,990.84. The other ten books are the
$10,000 cash balance. These are price returns. Dividends are not
credited.

## Controls and benchmark

Cash returns 0. A one-shot SPY control buys the most whole shares that
fit the 25% cap and the $2,000 floor, at the first open after the first
decision, and holds through the settlement close.

| Window | Frozen benchmark | Cash | Capped one-shot SPY | Sol, no memory | Terra, no memory |
| --- | --- | --- | --- | --- | --- |
| Bullish | +5.41% | 0 | +1.00% (6 shares from $398.40 to $415.21) | +0.09% | -0.09% |
| Sideways | +0.35% | 0 | -0.45% (6 shares from $389.61 to $382.33) | 0 | 0 |
| Bearish | -5.45% | 0 | -1.63% (5 shares from $479.22 to $446.75) | 0 | 0 |

Memory books match the cash column in every window.

The ledger's own benchmark series is a different interval: the first
ingested level through the settlement level. Those changes are +5.24%
bullish (8208.10 to 8638.42), -1.37% sideways (8039.67 to 7929.56), and
-5.89% bearish (9986.70 to 9398.96). The sideways sign differs from the
frozen return because the settlement close is outside the decision
block. Portfolio comparisons above use the frozen return.

On the two traded books, a path rebuilt from the fill and later Yahoo
closes, not from the report file, has a peak-to-trough drawdown of
about 0.09% for Terra and 0.08% for Sol. Daily close-to-close
volatility on that short path is about 0.05% and 0.12%. Concentration
at the settlement close is about 16.6% of value. Turnover is one buy
and no sell. Cash books have no position, no fee, and no price
drawdown. Most report rows after the first session say valuation is
unavailable because the report time is outside the current book
session, so those rows are not used as the value path.

## Learning

Matched memory and no-memory books saw the same prices, filings, and
limits. Memory text did not lead either model to trade. The only buys
were on books that could not see earlier decisions. After a fill, both
models held. That is an observation about these windows. It does not
show that memory improved, or hurt, investment results. Public knowledge
of 2021 and 2022 is not controlled.

Sol's theses named closes, volumes, and the 336-hour cutoff. Terra's
theses were shorter and usually said the recent observations were not
enough. Sol also proposed buying 12 AAPL shares. That proposal was
rejected and did not fill. The only filled trades are the two SPY buys.
Thesis quality here is a label, not a score.

## Failures

- Alpaca Market Data returned HTTP 401 for the stored paper credentials
  on SIP and on IEX. Entitlement, coverage, timestamps, and adjustment
  were not observable. No new credential was created. Prices are Yahoo
  chart v8 quote opens and closes, not official prints and not
  dividend-adjusted.
- SPY company facts returned HTTP 404. X and historical news were not
  collected.
- Six opening memory responses missed the proposal schema. Five were
  repaired as holds. The sideways memory Sol opening response omitted
  the symbol; the recorded hold uses SPY. Raw text is in that book's
  `first-response.json`.
- Eight later calls asked for authorization instead of returning a
  decision. Those calls were sent again. The recorded decisions are
  the later answers.
- Two accepted buys wrote the exit as a sentence. It was stored as
  narrative text. The action, size, and citations were not changed.
- Known product gaps still apply: dividends are not credited, and the
  report often omits a mark when the request is outside the session.
- The recorded books use 14:30 UTC as the open and 21:00 UTC as the
  close. That is 9:30 a.m. and 4:00 p.m. New York in January and
  February, and one hour later in April. The fill price is still the
  Yahoo daily open, not a later intraday print. The open row also
  carries the day's volume. The decision is at 22:00 UTC, after the
  close row is ingested, so that volume is not a look-ahead at
  decision time.
- SEC company facts are placed at 21:00 UTC on the filed date. A filing
  accepted after that clock can appear early. The accepted trades cited
  prices, not those facts.
- A missing benchmark row can make the selector treat the next
  remaining row as the next session. These three windows had a
  benchmark level on every selected date. Rerunning `prepare` after a
  book exists is now refused, so a later index cannot be paired with
  these ledgers.

## Commands

```bash
uv run python -m drift.historical prepare
uv run python -m drift.historical review --regime bullish --book memory --model terra
uv run python -m drift.historical report
uv run ruff check src/drift/historical tests/unit/test_historical_replay.py
uv run mypy src/drift/historical tests/unit/test_historical_replay.py
uv run pytest tests/unit/test_historical_replay.py
```

`prepare` does not call a model. A supervisor supplies each proposal
file. Ledgers stay under `.local-artifacts/historical`.

## Improvements

1. Mark the book at a time inside the current session so the report
   keeps a value for every decision day.
2. Obtain an Alpaca historical entitlement, or keep the Yahoo quote
   label until that access exists.
3. Credit dividends before comparing these price books with a
   total-return index. Until then, keep both labels.
4. Require the proposal schema, including a symbol on a hold and an
   exit object on a trade, in the model-facing instruction so fewer
   calls need a second round.
5. Do not promote a retrospective result. A longer prospective run is
   a different question.
