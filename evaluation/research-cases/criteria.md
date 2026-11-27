# Research-case comparison

Frozen before any model response for this comparison. Do not edit the dates,
prompts, or scoring after the first response. Outcomes belong in `results.md`.

## Cases

Each case is one decision at 22:00 UTC after the New York close. The next
session open is the only fill. No minimum trade and no return target.

| Case | Session | Why this session |
| --- | --- | --- |
| between | 2026-10-16 | After the 2026-07-31 10-Q and the 2026-09-01 8-K/A, and before the 2026-11-02 earnings 8-K. Those filings are older than 336 hours. |
| development | 2026-11-09 | Apple's 8-K, accepted 2026-11-09T21:30:40Z, describes a note issuance and is available before the decision. |

The same evidence packet is shown under two citation rules.

- Baseline: evidence older than 336 hours cannot be cited, including statements.
- Research: a close inside 336 hours is fresh; an older close is history; a statement or SEC filing stays citable until superseded; other news ages out at 336 hours. The fill is still the next open inside 336 hours.

Models are `gpt-6.1-terra` and `gpt-6.2-sol` at reasoning effort `xhigh`, each in its own call. Four cases, two rules, eight decisions. No other model.

## Scoring

Score each decision before using any later price as a grade.

- Grounding: a buy or sell cites evidence ids for that symbol. A stale headline, a superseded row, or another symbol's id is a miss.
- Filing use: on `between`, citing the still-current 10-Q is allowed only under the research rule. On `development`, the note-issuance 8-K is fresh for both rules.
- Thesis: a trade names a catalyst and a downside. An abstention says what evidence is missing or why cash is better.
- Abstention: a hold is valid. More trades are not an improvement.
- Risk: whole shares, the cash floor, and the position fraction hold. An unsupported citation is a compliance failure.
- Outcome: the next close is a price return, not an investing edge. It is recorded after the score.

## Stop

Do not run the twelve-session replay. Do not retune the dates to the responses.
