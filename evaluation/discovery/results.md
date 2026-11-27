# Discovery results

Scored before any later price was used as a grade. These are simulated
decisions on an isolated book. They are not an investing edge. Dollar cost
was not returned, so it is unknown, not zero.

## Data checked before the calls

`python -m drift.research --state .local-artifacts/discovery prepare` on
2026-11-27. The SIP probe returned HTTP 200 and the SIP bar download
returned HTTP 403, so the book used Alpaca IEX daily bars, `adjustment=raw`.
`adjustment=all` changed a sampled close versus raw. 42 cash dividends were
counted and are not credited. SEC companyfacts and recent filings were
collected. Yahoo RSS and Alpaca news supplied headlines. SPY had no headline
inside 336 hours. X was not collected. No new credential was created and no
broker order was sent.

The screen, using a local floor of $20,000,000 median 21-session dollar
volume and 63 sessions of warmup, shortlisted AAPL, JNJ, LIN, and PG.
LIN and PG are outside AAPL, MSFT, JNJ, and SPY. Trading authorization on
this book stayed those four names. PG's 63-session change was 18.98 percent,
from the 2026-08-26 close to the 2026-11-24 close of 172.54. Its latest
statement is the 10-Q filed 2026-10-22, and its 8-K of 2026-11-03 excerpts
a euro note offering. A scripted buy of one PG share, citing
`discovery:alpaca-bars-v2-iex-raw:PG:close:2026-11-24`, was escalated and
did not fill.

## Decisions

Each call was `codex exec -m <model> -c 'model_reasoning_effort="xhigh"'`
with `--ephemeral` and a read-only sandbox. The JSON stream has token counts
and does not have a separate executed-model field or an effort field. The
proposal `model_identity` is the value the prompt told the model to copy.
Requested identifiers were `gpt-6.1-terra` and `gpt-6.2-sol`.

| Workflow | Model | Action | Ledger | Input tokens |
| --- | --- | --- | --- | --- |
| discovery | Terra | buy 6 JNJ | accepted, then filled | 75465 |
| discovery | Sol | hold AAPL | accepted abstention | 67493 |
| baseline | Terra | hold SPY | accepted abstention | 326621 |
| baseline | Sol | hold SPY | accepted abstention | 328103 |

Output tokens were 754, 1225, 470, and 1294. Reasoning output tokens were
214, 851, 76, and 872. Cached input tokens were 13696, 15232, 35584, and
15232.

Terra's discovery buy cited the TREMFYA Phase 4 headline
`alpaca:news:127539498:JNJ`, the 2026-11-24 JNJ close, and the quarterly
diluted EPS of 0.09. The thesis names that study as a catalyst and says the
results may not become sales. The research block's price-over-EPS figure
uses diluted EPS 4.49 for the period ended 2026-09-27, not the 0.09 row.
Both rows are in the slice. The fill was the 2026-11-25 open, 278.12, plus
the $1 fee. Cash left 8330.28. Six shares at that open are inside the 0.25
cap and the $2,000 cash floor. Sol's discovery hold compared AAPL, MSFT,
JNJ, SPY, LIN, PG, and cash, and kept cash. Both baseline holds also kept
cash. The baseline prompt cannot name LIN or PG.

## Context

Same-window prompts, characters, then provider input tokens:

| Prompt | Characters | Input tokens |
| --- | --- | --- |
| baseline Terra | 920243 | 326621 |
| baseline Sol | 920241 | 328103 |
| discovery Terra | 125238 | 75465 |
| discovery Sol | 125236 | 67493 |

`wc -c` produced the character counts. Provider input tokens fell from
326621 to 75465 for Terra and from 328103 to 67493 for Sol. A character
divided by four is not a token count.

The stored PR #690 `between` context, measured without a new model call,
went from 338 evidence rows and 249142 characters to 70 rows and 51759
characters. Every evidence id named by that research block remained in the
slice.

## Limits

The prospective calendar, ledgers, and mandate were not changed. This book
is not a prospective pilot. SIP bars were not usable on this run. X is
absent. SPY had no fresh headline. Dividends are not in the price. The
sample is four decisions. It is not an investing edge.
