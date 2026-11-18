# Mixed-venue clock preparation

Issue [#365](https://github.com/KanujVerma/drift/issues/365) records the owner
decision and the scope of this work. This contract is an exploratory preparation
boundary. It does not admit a source, authenticate an issuer, authorize an
account, or establish an investment result.

`CommonSessionAssociationV1` identifies one logical step without inventing a
market identifier. Each member retains its own venue session key, boundaries,
source policy, query, context and availability evidence. A
`CommonSessionClockV1` freezes the ordered associations and the full requested
interval. Its own hash and structural validation do not authenticate the
members or prove that omitted dates were closed.

The scheduled replay path requires exactly one decision-time query for every
member, rederives each session through the existing M1d selector and clock
builder, and verifies selected, complete coverage against the selected source
dataset and retained calendar response. Each venue requires a configured
source-specific verifier that checks the retained response, request and origin
against the claimed inventory. The selected source policy must cover the full
interval, and its selected coverage snapshot must match the coverage record and
be available by the cutoff. It compares every date in the frozen
interval against each venue's closed-world coverage. A missing date, conflicting
claim, reused acquisition across venues, late or unselected coverage, different
session boundaries, or absent original query stops replay. The source policy
configuration must come from an independently authenticated authority; a
caller-supplied hash is not an issuer or source authentication. The current
replay path does not admit realized clocks.

The bounded Alpaca diagnostic parser takes one symbol per window, at most 200
verified session dates, explicit raw SIP parameters and a complete continuation
chain. It rejects missing, extra, duplicated or stale bars, contradictory prices,
unrecognized symbols, incomplete pages and wrong date labels. The mixed-venue
preparation helper requires all twelve declared Stage 1 symbols and binds their
diagnostic windows to a replayed common clock. Bar date labels must match local
midnight reconstructed with the clock's retained timezone rules and match an
independently configured trusted timezone input. Matching labels are sufficient
even if the retained timezone files have different bytes. Its identity, source authority
and snapshot status remain explicitly unverified or caller configured. Pages and
provider values are processed in memory; this helper writes no source bytes.
Its output is not an evaluation input or a G1-qualified data receipt.

This slice does not prove a point-in-time ticker-to-listing mapping, first usable
bar availability, a provider snapshot across pages, corporate-action coverage,
or a common-step account and RESULT. It leaves the original evaluator's #97
same-date refusal intact. The successor atomic execution boundary is requested
from the existing #613/#634 writer, and #507/#508 remain responsible for the
original producer and RESULT association. Without those interfaces and the
independent source evidence, no mixed-venue B/R account run is claimed.

The separately labeled synthetic calendar tests include the early closes on
July 3 and November 24, 2023, as well as the July 4 and Thanksgiving closures
and a daylight-saving transition. The published [NYSE calendar](https://ir.theice.com/press/news-details/2022/NYSE-Group-Announces-2023-2024-and-2025-Holiday-and-Early-Closings-Calendar/default.aspx)
and [Nasdaq calendar](https://www.nasdaqtrader.com/content/technicalsupport/2023tradingcalendar.pdf)
are reference material for those dates. A matching test value does not establish
that the fictional fixture or a particular provider response came from a venue.
