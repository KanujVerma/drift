# Opportunity discovery

Issue [#691](https://github.com/KanujVerma/drift/issues/691). This is an
isolated simulation. It does not change the prospective calendar, ledgers,
or mandate, and it is not evidence of an investing edge.

`python -m drift.research --state .local-artifacts/discovery prepare`
collects a configured US stock and ETF universe, screens it, and opens one
SQLite book under that directory. The research universe is wider than
AAPL, MSFT, JNJ, and SPY. Those four remain the default trading
authorization. A shortlist also includes current holdings and any
`suggestions.json` notes. A screen pass is not an order. Buying a
researched name that is not trading-authorized is recorded as an
escalation and does not fill.

Prices prefer Alpaca SIP, then IEX, then Yahoo chart bars. SEC
companyfacts and recent filings supply statements and official
announcements. Alpaca news and Yahoo headline RSS supply contemporary
headlines. X is not called. Empty responses stay gaps. The decision
prompt calculates indicators from the visible series and cites a short
slice: anchor closes, the current statement, a superseded predecessor
when one exists, the latest filing, and a few fresh headlines. Older
rows remain in `cache.json` and can be printed with `detail`.

The local screen floor, warmup, and shortlist size are research
configuration, not an approved product mandate. The book's numeric limits
match the existing local test limits: $10,000 cash, a 0.25 position
fraction, a $2,000 cash floor, and a $1 simulation fee. The next open is
the fill. Abstaining remains valid.

```bash
python -m drift.research propose --model terra --proposal proposal.json
python -m drift.research execute
python -m drift.research review
python -m drift.research detail --symbol PG --kind fundamental
python -m drift.research ingest --batch batch.json
```

`review` reads the ledger's cash and shares into the next weekday's
prompt. Cited rows are evidence the ledger already holds. The fill for
that review is the weekday after it. `detail` hides rows after the
active decision. `ingest` adds a batch to the cache only after the
ledger accepts it.
