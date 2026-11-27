# Research-case results

Scored before any later price was used as a grade. These are simulated
decisions. They are not an investing edge. System cost was not returned,
so it is unknown, not zero.

## Data checked before the calls

`load_alpaca_bars` for AAPL, MSFT, JNJ, and SPY from 2020-12-01 through
2026-01-16 returned feed `sip`, HTTP 200. The same probe returned HTTP 200
for IEX. The book uses raw SIP bars. `adjustment=all` changed a sampled
close versus raw. 82 cash dividends were counted and are not credited.
Alpaca news for 2024-05-01 through 2024-05-08 returned no articles. The
2026-11-20 through 2026-11-26 window returned 29 headlines. An empty page
is a coverage gap, not proof that nothing was published. X was not collected.
No new credential was created and no order was sent.

The case prompts were written by:

```bash
uv run python -m drift.historical --state .local-artifacts/research-cases cases
```

Each call was `codex exec -m <model> -c 'model_reasoning_effort="xhigh"'`
with `--ephemeral` and a read-only sandbox. Terra was `gpt-6.1-terra`.
Sol was `gpt-6.2-sol`. The JSON stream has token counts and does not have
a separate executed-model field. The proposal `model_identity` is the value
the prompt told the model to copy.

## Decisions

An earlier eight-call round used a shorter baseline prompt that omitted the
same-symbol citation rule and the numeric limits. That round is discarded.
The table below uses one prompt template. Only the citation rule and the
labels in the research block differ. Each proposal was checked with
`decide_proposal` under the rule it was given. Baseline buys were also
checked under the research rule.

| Case | Rule | Model | Action | Ledger |
| --- | --- | --- | --- | --- |
| between 2026-10-16 | research | Terra | hold SPY | accepted abstention |
| between 2026-10-16 | research | Sol | hold MSFT | accepted abstention |
| between 2026-10-16 | baseline | Terra | hold AAPL | accepted abstention |
| between 2026-10-16 | baseline | Sol | buy 4 AAPL | accepted under both rules; cites fresh headlines and closes, not the old 10-Q |
| development 2026-11-09 | research | Terra | hold AAPL | accepted abstention |
| development 2026-11-09 | research | Sol | hold AAPL | accepted abstention |
| development 2026-11-09 | baseline | Terra | hold AAPL | accepted abstention |
| development 2026-11-09 | baseline | Sol | buy 4 AAPL | accepted under both rules; cites the annual EPS facts, the close, and a headline |

Token counts are input, output, and reasoning output:

- between Terra research: 132881, 529, 176
- between Sol research: 134366, 987, 562
- between Terra baseline: 132806, 451, 93
- between Sol baseline: 134291, 1980, 1365
- development Terra research: 133350, 590, 197
- development Sol research: 134838, 869, 448
- development Terra baseline: 133277, 671, 288
- development Sol baseline: 134758, 1957, 1317

## Score

On 2026-10-16 the research brief labeled Apple's 2026-07-31 10-Q citable.
The baseline brief labeled that statement not citable at 1842 hours. Terra
held under both rules. Sol held when the statement was citable and bought
when it was not. The buy cited October headlines and closes, and the thesis
said the financial statements were outside the 336-hour window. Both
decisions are valid. The research rule did not force a trade, and it did
not make Sol treat a headline as a substitute for the 10-Q.

On 2026-11-09 the note-issuance 8-K and the annual figures were inside 336
hours, so both rules could cite them. Terra held under both. Sol held when
the research labels were present and bought 4 AAPL when the blanket age
rule was present. The buy cited the fiscal-year EPS facts, the November 9
close, and a launch headline. It was accepted under both policies because
those facts were fresh. The fill remains the next open. No proposal cited
another symbol, a superseded row, or a future filing.

Six of eight decisions were justified abstentions. The two buys named a
catalyst and a downside and stayed inside the position cap and cash floor
at the cited close. More trades are not an improvement. This is not an
investing edge. No decision was graded on a later close.

## Limits

Alpaca news did not return a 2024 archive. X is absent. Some primary
documents are XBRL and were kept as accession rows when the excerpt had no
item heading. Dividends are not in the price. The prospective calendar,
ledgers, and 336-hour citation rule are unchanged. The case books use the
research mandate. Baseline statuses were checked again with
`citation_policy` set to `uniform_age`.
