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

- The repository contains an append-only evidence ledger
  ([`sqlite.py`](../src/drift/ledger/sqlite.py)), a deterministic evaluator and
  portfolio accounting kernel ([`engine.py`](../src/drift/evaluator/engine.py),
  [`portfolio.py`](../src/drift/evaluator/portfolio.py)), and research and
  scorecard components. They are building blocks, not evidence that the intended
  autonomous portfolio manager is complete or profitable.
- The Robinhood adapter and mock transport exist
  ([`adapter.py`](../src/drift/adapters/robinhood/adapter.py),
  [`transport.py`](../src/drift/adapters/robinhood/transport.py));
  [`tests/unit/test_robinhood_adapter.py`](../tests/unit/test_robinhood_adapter.py)
  exercises offline behavior. This is not a verified authenticated connection,
  current-schema conformance, account readiness or authorization to connect.
- Risk enforcement is not universal: the router's gatekeeper is optional
  ([`router.py`](../src/drift/execution/router.py)), and the
  [safety tests](../tests/unit/test_execution_safety_audit.py) reproduce a
  no-gatekeeper dispatch. The adapter can report an unconfirmed submission as
  rejected and cancellation failure may leave status uncertain. Unmapped
  positions are quarantined, not fully reconciled. See the
  [execution safety audit](architecture/execution-safety-audit.md); its detailed
  historical findings must be reconciled with current source before changes.
- Source qualification is not established by synthetic or exploratory output.
  [ADR 0012](adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md)
  keeps exploratory results non-promotable: a fresh evaluation against accepted
  promotion-qualified data is required for that evidence. [#360](https://github.com/KanujVerma/drift/issues/360)
  tracks unresolved promotion-evidence and completeness concerns; verdict labels
  or caller-supplied hashes alone do not resolve them.
- Preserve persisted contracts, source evidence and exact replay requirements.
  [`.python-version`](../.python-version) pins CPython 3.14.6 for development
  and pinned replay; [`tests/_pinned_m1d.py`](../tests/_pinned_m1d.py) records
  replay failure classes. Do not alter the pin, lockfile or fixture expectations
  merely to make a check pass.

The numerical risk mandate, source rights and availability, operational controls,
model budgets, and exact qualification criteria remain unresolved where not
explicitly approved. Do not invent defaults. Broker-connected paper, live orders,
provider access and paid services are separate permissions, not consequences of
code, tests or this document.
