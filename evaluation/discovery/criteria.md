# Discovery comparison

One contemporary decision, scored before any later price is used as a grade.
The next open is the fill. It is not a return. No minimum trade and no
investing-edge claim.

## Session

Decision at 2026-11-24 22:00 UTC, after the New York close. The settlement
session is 2026-11-25. The research universe is the configured list in
`drift.research.universe`. Trading authorization on this isolated book stays
AAPL, MSFT, JNJ, and SPY. Cash starts at $10,000. The local test limits are
a 0.25 position fraction, a $2,000 cash floor, and a $1 simulation fee.

## Workflows

- Discovery: screen, calculated research block, and the citable evidence slice.
- Baseline: the existing four-symbol decision prompt with the same window's
  full evidence JSON for AAPL, MSFT, JNJ, and SPY.

Models requested: `gpt-6.1-terra` and `gpt-6.2-sol`, config
`model_reasoning_effort="xhigh"`. Each call is separate and ephemeral.
The Codex JSON stream is the usage record. It is not treated as proof of the
served model or the applied effort unless it carries those fields.

## Scoring

- Coverage: the discovery decision can name a shortlisted symbol outside the
  original four. A baseline decision cannot, because that prompt does not
  offer one.
- Grounding: a buy or sell cites evidence for that symbol. A hold with no
  citations is an abstention.
- Thesis: a trade names a catalyst and a downside. An abstention says why
  cash or no trade is the decision.
- Risk: the ledger accepts, escalates, or rejects the proposal. A fill uses
  the next open. An unauthorized symbol does not fill.
- Cost: report provider token counts when the stream has them. A character
  estimate is not a token count. Unknown dollar cost stays unknown.
