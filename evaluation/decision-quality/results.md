# Decision-quality results

All ten decisions in `criteria.md` are recorded. Executed models were
`gpt-6.1-terra` and `gpt-6.2-sol` at `xhigh`. Every new decision was
accepted on the first response. The string exit conditions on the one
buy were stored as narrative text. The action, size, and citations
were not changed. Model cost is unknown, not zero. No billed amount
was returned.

This file does not relabel `evaluation/historical-replay/results.md`.
Portfolio figures here are price returns. Dividends are not credited.
This is not an investing edge.

## Decisions

| Case | Model | Baseline | New decision | Ledger |
| --- | --- | --- | --- | --- |
| B-open 2021-03-31 nomemory | Terra | hold SPY | hold SPY | accepted |
| B-open 2021-03-31 nomemory | Sol | hold SPY | hold SPY | accepted |
| R-open 2022-01-03 nomemory | Terra | hold SPY | hold SPY | accepted |
| R-open 2022-01-03 nomemory | Sol | hold SPY | hold SPY | accepted |
| B-buy 2021-04-13 nomemory | Terra | hold SPY | hold MSFT | accepted |
| B-buy 2021-04-13 nomemory | Sol | buy 4 SPY | hold MSFT | accepted |
| B-anchor 2021-04-09 memory | Terra | hold SPY | hold SPY | accepted |
| B-anchor 2021-04-09 memory | Sol | hold AAPL | hold AAPL | accepted |
| B-anchor 2021-04-09 lessons | Terra | hold SPY | hold SPY | accepted |
| B-anchor 2021-04-09 lessons | Sol | hold AAPL | buy 8 AAPL | accepted, filled |

Nine books stayed in cash. The lessons Sol buy filled at the 2021-04-12
open, $132.52, for 8 shares and a $1 fee. Cash after the fill was
$8,938.84. The 2021-04-12 close was $131.24, so `price_value` was
$9,988.76, a price return of -0.1124 percent from $10,000. The
benchmark change on that row is +3.95 percent from the first decision
day, 2021-03-31, through 2021-04-12. The position existed for one
close. The rest of the bullish window was not rerun. The baseline Sol
buy of 4 SPY remains the recorded historical result and ended at
$10,008.52.

The copied 2021-04-09 AAPL buy on the nomemory Sol path was rejected
again because it cited SPY closes. That was the old proposal, not a
new inference.

## Scoring

Grounding. Sol's percentages match the research block: on 2021-03-31,
AAPL +1.88, MSFT +1.69, JNJ -0.40, SPY +0.41; on 2022-01-03, AAPL
+2.50, MSFT -0.47, JNJ +0.27, SPY +0.58; on 2021-04-13, AAPL +12.12,
MSFT +11.49, JNJ -3.35, SPY +4.59; on 2021-04-09, AAPL +10.93, MSFT
+10.35, JNJ -2.28, SPY +4.25. The lessons buy cited three AAPL closes
that were in the context. Its volume comparison, 106.7 million versus
88.8 million, matches the April 9 and April 8 close rows. It did not
cite a stale statement. Terra's later theses used the same directions
and, on the memory arm, the same percentages. No new decision cited
another symbol as trade evidence.

First response. All ten validated. The buy's exit text was bound to
narrative objects. The action stayed buy 8 AAPL.

Thesis. The buy names a volume increase on the highest close in the
window and a downside if the next open is higher or the move reverses.
The holds say the price moves are not a catalyst and that the
statements are outside the 336-hour window.

Abstention. The holds are consistent with short quote histories and
uncitable statements. On 2021-04-13 both models abstained where the
baseline Sol book bought. On 2021-04-09 the memory Sol book abstained
on the same AAPL figures that the lessons Sol book treated as a
catalyst. Compact lessons did not make Terra trade. One Sol pair is
not evidence that lessons improve results.

Risk. The fill is 8 times $132.52 plus $1, inside the 0.25 position
fraction and above the $2,000 cash floor. The ledger accepted it.

Adaptability. Lessons Sol changed from the copied holds. Memory Sol
did not. Terra's memory and lessons decisions match.

Outcome. The only new position was down $11.24 at the next close.
Cash was ahead of that mark. More trades did not occur on the other
nine decisions. The comparison does not show an investing edge.

## Defect found by a response

The opening research block called an MSFT filing "336 hours old,
citable" after truncating the age. Sol computed 336 hours, 36 minutes,
and 54 seconds and did not cite it. The label now uses the validator's
cutoff, so a timestamp past 336 hours is not called citable.

A companyfacts time after the 22:00 UTC decision waits until the next
session open, and that fact is ingested before a fill at the same open.
The citation age uses the source time, so the later ingest does not
make the fact fresh. A cached companyfacts stamp of 21:00 UTC is
rewritten to the end of that filed New York date on load. Growth is
computed only when the two periods cover the same number of days. A
proposal that repeats a key is refused. The bullish window had one
in-window text, an MSFT 8-K accepted at 10:51 a.m. New York on
2021-04-12, which was already inside that session. The ten recorded
decisions did not lose a fact to that gap.

## What did not improve

The research block did not produce a citable fundamental catalyst.
Statements in these windows were older than 336 hours, and the models
treated price and volume as the only eligible evidence. Alpaca still
returns HTTP 401 for the stored paper-shaped keys, so prices remain
Yahoo quote opens and closes. X and filing text were not added.
Unknown model cost is not zero.
