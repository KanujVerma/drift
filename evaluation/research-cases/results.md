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

| Case | Rule | Model | Action | Ledger |
| --- | --- | --- | --- | --- |
| between 2026-10-16 | research | Terra | hold AAPL | accepted abstention |
| between 2026-10-16 | research | Sol | hold SPY | not replayed; empty evidence, same abstention shape |
| between 2026-10-16 | baseline | Terra | hold SPY | not replayed; empty evidence, same abstention shape |
| between 2026-10-16 | baseline | Sol | hold AAPL | not replayed; empty evidence, same abstention shape |
| development 2026-11-09 | research | Terra | hold SPY | not replayed; empty evidence, same abstention shape |
| development 2026-11-09 | research | Sol | hold AAPL | not replayed; empty evidence, same abstention shape |
| development 2026-11-09 | baseline | Terra | buy 5 AAPL | accepted under both citation policies; fill waits for the next open |
| development 2026-11-09 | baseline | Sol | buy 2 AAPL | rejected under both policies: citations include MSFT, JNJ, and SPY |

Token counts are input, output, and reasoning output:

- between Terra research: 129348, 538, 147
- between Sol research: 130846, 1015, 597
- between Terra baseline: 128932, 346, 60
- between Sol baseline: 130419, 1052, 709
- development Terra research: 130890, 527, 152
- development Sol research: 132369, 929, 516
- development Terra baseline: 130476, 691, 161
- development Sol baseline: 122483, 2149, 1206

## Score

On 2026-10-16 the research brief labeled Apple's 2026-07-31 10-Q citable.
The baseline brief labeled that statement not citable at 1842 hours. All
four decisions held. The holds named catalysts and said why cash was
preferable. That is justified abstention. The research rule made the
statement usable. It did not force a trade.

On 2026-11-09 the note-issuance 8-K was in the prompt as filing text, and
the annual figures were inside 336 hours, so both rules could cite them.
Both research decisions held and treated the headlines and the filing as
uncertain. Baseline Terra bought 5 AAPL and cited only Apple revenue, EPS,
and the 2026-11-09 close. Those facts were 137 hours old, so both the
research rule and the 336-hour rule accept them. The book did not fill at
that close. Baseline Sol bought 2 AAPL but also cited MSFT, JNJ, and SPY.
Both policies reject that proposal. The case ledgers themselves use the
research mandate. The baseline statuses above were checked again by running
the same proposals through `decide_proposal` with `citation_policy` set to
`uniform_age`. The shorter baseline prompt did not repeat the cross-symbol
citation rule that the research prompt states, so Sol's rejection is not
by itself a comparison of the age rule.

No decision cited a superseded row or a future filing. No decision was
graded on the next close.

## Limits

Alpaca news did not return a 2024 archive. X is absent. Some primary
documents are XBRL and were kept as accession rows when the excerpt had no
item heading. Dividends are not in the price. The prospective calendar,
ledgers, and 336-hour citation rule are unchanged.
