# Historical replay

Issue [#686](https://github.com/KanujVerma/drift/issues/686). This is a
simulation on past prices. It does not change the prospective calendar,
ledgers, or frozen v0.2 limits, and it is not evidence of an investing edge.
Models may already know the public history.

`python -m drift.historical` reuses the supervised portfolio cycle. Each
book is an isolated SQLite ledger under `.local-artifacts/historical`,
starting at $10,000 simulated cash. The universe and local limits match
[V02](V02.md): AAPL, MSFT, JNJ, SPY, a 0.25 position fraction, a $2,000
cash floor, a $1 simulation fee, and a 336-hour evidence age. Those are
test limits, not an approved product mandate.

A decision is recorded before the next session's open is ingested. That
open is the fill. Closes mark the book. Dividends are not credited and
splits are not applied, because those corporate-action paths are still
unresolved. Portfolio results are price returns net of the simulation fee.
The benchmark prefers Yahoo `^SP500TR` and is labeled total return. A
missing index is a labeled price-only substitute.

Windows are chosen by `drift.historical.select` before any model response:
the earliest non-overlapping 12-session block for bullish, bearish, and
sideways rules. A later, larger move is not preferred. Blocks that contain
a split, or the August 2023 JNJ/Kenvue distribution, are ineligible.

Alpaca's stored paper credentials are probed and the HTTP status is
recorded. No new credential is created. If Alpaca refuses the request,
prices come from Yahoo chart v8 quote opens and closes, which are not
official exchange prints. SEC submissions and companyfacts supply filings
and fundamentals. X and a historical news archive are gaps.

Candidates, when a supervisor runs them, are only
`codex/gpt-6.1-terra@xhigh` and `codex/gpt-6.2-sol@xhigh`. The command
does not call a model. A memory-disabled book sees positions and marks,
not prior decision text.

```bash
uv run python -m drift.historical prepare
uv run python -m drift.historical review --regime bullish --book memory --model terra
uv run python -m drift.historical report
```

The recorded comparison is in
[evaluation/historical-replay/results.md](../evaluation/historical-replay/results.md).
