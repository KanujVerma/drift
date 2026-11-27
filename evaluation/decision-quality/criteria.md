# Decision-quality comparison

Frozen before any new model response for this comparison. Do not edit the
cases or the scoring after the first new response. Notes and outcomes
belong in `results.md`. The recorded historical replay stays in
`evaluation/historical-replay/`. Its dates and results are not relabeled.

## Cases

Each case is one new Codex decision. Earlier sessions, when a case needs
them, are copied from the recorded proposals. Those copies are not new
inferences. If a recorded proposal no longer validates, record the
rejection and do not invent a replacement trade.

| Case | Regime | Session | Book | Baseline on that session |
| --- | --- | --- | --- | --- |
| B-open | bullish | 2021-03-31 | nomemory | both models held |
| B-buy | bullish | 2021-04-13 | nomemory | Sol bought 4 SPY; Terra held |
| B-anchor | bullish | 2021-04-09 | memory and lessons | both memory books had only held |
| R-open | bearish | 2022-01-03 | nomemory | both models held |

Models are `gpt-6.1-terra` and `gpt-6.2-sol` at reasoning effort `xhigh`,
each in its own call. Ten new decisions. No other model.

## What is being compared

The baseline is the recorded decision on that session. The new decision
sees the research block, the New York evidence clock, and, on the
`lessons` arm, compact theses and outcomes instead of raw hold text.
Same universe, same local limits, same 336-hour citation rule.

## Scoring

Score each new decision before looking at whether a trade made money.

- Grounding: a buy or sell cites evidence ids for that symbol from the
  context. A stale statement is not cited. Market context is not used as
  another symbol's evidence.
- First response: the proposal validates. A schema-version or exit-text
  bind does not count as a failed action. A change to the action does.
- Thesis: a trade names a catalyst and a downside. An abstention says
  what citable evidence is missing.
- Abstention: a hold is justified when citable evidence is thin. A hold
  that only repeats an earlier hold is not, on its own, a better decision.
- Risk: whole shares, the cash floor, and the position fraction hold.
  An unsupported citation is a compliance failure even if the idea is sound.
- Adaptability: the decision can differ from the prior action when prices
  or the book changed. It does not have to.
- Outcome: price return from `price_value`, against cash and against the
  benchmark change on the decision-date interval. More trades are not
  an improvement. This is not an investing edge.

## Stop

Do not run the other sessions. Do not rerun all 144 decisions unless
these ten show a reason to, and a later note says why.
