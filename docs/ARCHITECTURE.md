# Architecture

This is the high-level system and trust boundary for the product in
[PRODUCT.md](PRODUCT.md). The [roadmap](ROADMAP.md) describes intended next
outcomes. Code and tests establish the behavior of a particular revision; a
component's existence is not proof of an integrated product, qualified evidence,
operational safety or permission to trade.

## Intended flow and authority

Source observations and user suggestions feed opportunity discovery, research,
theses and portfolio proposals. Retain provenance and observation/availability
times, distinguish source corrections and missing data, and use only information
available at each decision time. Evaluate proposals and their outcomes against
appropriate baselines and realistic costs; learn from validated outcomes rather
than treating a backtest or a model assertion as truth. Conversational reports
explain evidence, uncertainty, risk, performance and costs.

The user sets the mandate and authorizes material changes, access and spending.
The agent may propose within that mandate or escalate outside it, but cannot
change the mandate, grant its own permissions or bypass deterministic risk and
execution controls. A review or trigger is not an order. For any future
execution, enforce risk at every dispatch path, reconcile uncertain submissions,
cancellations, fills and account state, and preserve a usable stop mechanism.
A pause alone does not prove pending orders were cancelled or holdings liquidated.

Treat source documents, news, social posts and model outputs as untrusted data,
not instructions or authority. A matching hash establishes consistency, not
source origin or truth. Retain evidence only under appropriate rights; respect
point-in-time availability and keep private data and credentials protected.

Use a single authoritative portfolio accounting path for cash, positions, fills,
corporate actions and investment returns; do not create a competing ledger.
Trading costs belong in portfolio results. Measure research, inference, data and
compute costs separately as system economics, disclose unknown costs rather than
assuming zero, and avoid double counting. Investment performance and system
economics are related but distinct measures.

## Existing building blocks and concrete limits

- The retained offline building blocks include proposal validation
  ([`validator.py`](../src/drift/agent/validator.py)), explicit evidence records
  ([`evidence.py`](../src/drift/domain/evidence.py)), an append-only audit ledger
  ([`sqlite.py`](../src/drift/ledger/sqlite.py)), canonical serialization,
  the portfolio accounting kernel ([`portfolio.py`](../src/drift/evaluator/portfolio.py)),
  and risk evaluation and journaling. Supporting domain, market and scorecard
  modules remain where imported by these components or their tests. Proposal
  validator thresholds are historical research criteria, not an approved risk
  mandate; acceptance is not investment or promotion authorization. Evidence
  records and hashes do not authenticate source claims.
- The legacy evaluator engine, broker adapters, router, live dispatch, shadow,
  canary, promotion and study runtimes are retired from the active tree. This
  does not fix their defects. Any future connected implementation needs
  universal intent- and state-bound risk enforcement, durable account-wide
  unknown-outcome reconciliation, and a usable stop mechanism. The retained risk
  gatekeeper alone is not sufficient dispatch authority: for example, it can
  evaluate without a portfolio and can reuse cached verdicts.
- Source qualification is not established by synthetic or exploratory output.
  A fresh evaluation against accepted promotion-qualified data is required.
  [#360](https://github.com/KanujVerma/drift/issues/360) tracks unresolved
  promotion-evidence and completeness concerns; verdict labels or
  caller-supplied hashes alone do not resolve them.
- Historical replay code, tests, hashes and fixtures remain in Git history, not
  the active suite. Replaying them requires their original revision, environment
  and inputs; this reset does not demonstrate replay on the new tree.
  [`.python-version`](../.python-version) and the root lock remain unchanged.
- The standalone `tools/stage1-statistics` worker and its separate lock remain
  solely to preserve that pin; it is not part of the product package or retained
  validation. Its retirement or reuse needs a separate decision.

Known open work includes promotion prerequisites ([#115](https://github.com/KanujVerma/drift/issues/115)),
unknown execution outcomes ([#411](https://github.com/KanujVerma/drift/issues/411)),
Decimal-context-dependent selection ([#469](https://github.com/KanujVerma/drift/issues/469)),
corporate-action coverage ([#648](https://github.com/KanujVerma/drift/issues/648)),
and cash-yield accounting decisions ([#653](https://github.com/KanujVerma/drift/issues/653)).
These are not resolved by documenting them; consult the issues for their current state.

The numerical risk mandate, source rights and availability, operational controls,
model budgets, and exact qualification criteria remain unresolved where not
explicitly approved. Do not invent defaults. Broker-connected paper, live orders,
provider access and paid services are separate permissions, not consequences of
code, tests or this document.
