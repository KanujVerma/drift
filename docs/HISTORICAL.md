# Historical replay

Issue [#686](https://github.com/KanujVerma/drift/issues/686). This is a
simulation on past prices. It does not change the prospective calendar,
ledgers, or frozen v0.2 limits, and it is not evidence of an investing edge.
Models may already know the public history.

`python -m drift.historical` reuses the supervised portfolio cycle. Each
book is an isolated SQLite ledger under `.local-artifacts/historical`,
starting at $10,000 simulated cash. The universe and local limits match
[V02](V02.md): AAPL, MSFT, JNJ, SPY, a 0.25 position fraction, a $2,000
cash floor, a $1 simulation fee, and a 336-hour execution-price age. Those are
test limits, not an approved product mandate. The prospective session still
uses that age for every citation. This replay does not.

A decision is recorded at 22:00 UTC, after the New York close. The open
is 9:30 a.m. New York and the close is 4:00 p.m. New York, including
daylight time. The historical review window opens then and still closes
at 23:59 UTC. The prospective session is unchanged. The next session's
open is the fill. A companyfacts time after that day's decision waits
until the next session open. The citation age still uses the source
time, so the later ingest does not make the fact fresh. Closes mark the book. The prompt adds a research block
calculated from visible closes, including up to 63 earlier closes,
volume, volatility, drawdown, filings, and the latest revenue, diluted
EPS, and, when the periods match, margin and liabilities over assets.
A close inside 336 hours is a fresh price. An older close can be cited
as history and is not the fill. News older than 336 hours cannot be
cited. A filing stays citable until a later amendment from the same
issuer, for the same report date, replaces it. A fact is replaced only
when the concept, period, and unit match. A superseded or withdrawn row
cannot be cited.
Market context is not a citation for another symbol. Filing text is an
excerpt, untrusted, and not the whole document. The `lessons` book keeps a short
thesis and outcome for each prior decision and omits the raw decision
text. Each report row includes `price_value`: cash plus shares at that
day's close, labeled as a price return. Its benchmark change uses the
first decision day through that day. The manager report is unchanged
and can still omit a cash day's net asset value. A proposal file may
use schema version `1.0` or a string exit condition; those two fields
are rewritten before validation and the action is not. Dividends are not credited and
splits are not applied, because those corporate-action paths are still
unresolved. Portfolio results are price returns net of the simulation fee.
The benchmark prefers Yahoo `^SP500TR` and is labeled total return. A
missing index is a labeled price-only substitute.

Windows are chosen by `drift.historical.select` before any model response:
the earliest non-overlapping 12-session block for bullish, bearish, and
sideways rules. A later, larger move is not preferred. Blocks that contain
a split, or the August 2023 JNJ/Kenvue distribution, are ineligible.

Alpaca is requested first for SIP, then IEX. The book uses raw daily
bars from the first feed that returns them. Adjustment is checked on a
sample, and cash dividends are counted and not credited. No new
credential is created. If Alpaca refuses the request or misses a symbol,
prices come from Yahoo chart v8 quote opens and closes, which are not
official exchange prints. SEC submissions, companyfacts, and a short
excerpt of the primary 10-K, 10-Q, or 8-K supply filings and fundamentals.
Alpaca news is requested for each frozen window. An empty page is recorded
as a coverage gap. X is not collected.

Candidates, when a supervisor runs them, are only
`codex/gpt-6.1-terra@xhigh` and `codex/gpt-6.2-sol@xhigh`. The command
does not call a model. A memory book sees prior decisions. A lessons
book sees a short thesis and outcome for each one. A memory-disabled
book sees positions and marks, not prior decision text.

```bash
uv run python -m drift.historical prepare
uv run python -m drift.historical review --regime bullish --book memory --model terra
uv run python -m drift.historical report
uv run python -m drift.historical --state .local-artifacts/research-cases cases
```

The recorded comparison is in
[evaluation/historical-replay/results.md](../evaluation/historical-replay/results.md).
A later ten-decision check of the research block is in
[evaluation/decision-quality/results.md](../evaluation/decision-quality/results.md).
