# Stage 1 G3: executable protocol freeze and historical readiness

## Scope

Issue #575 is the owner-directed successor to #570, #571 and #572. The source
implements a versioned study manifest, an explicit local-authority adapter and
readiness checks. It is not an accepted historical dataset, model configuration,
independent scientific efficacy review or operational grant.

The owner delegated engineering implementation and normal verified merges on
2026-11-01. That delegation does not supply missing historical source evidence,
make an exposed holdout pristine, choose an unrecorded model build or establish
investment efficacy. G2 synthetic engineering acceptance and G3 study readiness
are separate outputs.

## Frozen architecture

- One authoritative existing evaluator/account ledger. No replacement PnL engine.
- Fixed B3/B4/B5 menu, B3 initial strategy, 253 completed warmup sessions and
  126 further completed observation sessions before a fresh USD 10,000 account.
- Monthly decision close and next eligible open. Calendar identity, availability
  and cutoff policy are explicit. A weekday guess is not exchange evidence.
- AI B versus competent conventional R, matched information/risk/execution.
- Hold/abstain retains only a valid incumbent. No discretionary cash proposal.
- Trading costs remain in NAV; original operating costs are attributed once.
  Unknown costs never become zero.
- Historical 2025 outcomes are initially labelled RETROSPECTIVE_DISCOVERY with
  prior exposure UNKNOWN. Neither a filename nor a date range certifies holdout
  purity. Confirmatory use requires audited exposure and eligible model training.
- No arbitrary code generation, broker connection or capital permission.

## Runtime contract

`drift.experiments.stage1_study_freeze` provides:

- `Stage1StudyDraftV1`: strict, immutable configuration. No default numerical
  investment caps, comparator penalties, AI model, costs or success threshold.
- `assess_study_readiness`: all missing/unaccepted evidence is listed explicitly.
- `freeze_study`: refuses incomplete configuration or absent original acceptance;
  binds the complete protocol and exact receipt inventory in `freeze_hash`.
- `verify_frozen_study`: rechecks both the hash and original acceptance after
  deserialization. A hash-valid self-authored receipt cannot authorize a run.
- `OriginalStudyEvidenceVerifier`: narrow host-configured protocol. Its backend
  must verify original issuer/root, bytes, scope, assessor independence and the
  current complete protocol fingerprint. It is not chosen by a candidate/receipt.

Any change to dates, weights, formula parameters, prompts, source inventory,
execution/cost policies or statistical rules changes the protocol fingerprint
and invalidates prior acceptances. Re-freeze under a new revision before scoring.
A successful readiness check is configuration admission, not evidence of profit.
The actual evaluator's dataset/source gates continue to apply independently.

## Required final inputs, not fabricated approvals

| Input | Required deliverable | Accountable producer |
| --- | --- | --- |
| G2 | Successful full B/R and cold replay on exact accepted source | Integration owner |
| Data | Retained 12-ETF dataset, rights, identity, actions, venue/calendar and availability | Platform |
| Mandate | Numeric ETF/class/gross/turnover limits plus development feasibility and breach policy | Owner research + platform |
| R | Exact executable formula, development-fitted coefficients, ties and comparable information | Research |
| AI | Immutable model revision, prompt/tools/context/feedback/decoding hashes, seed and replay | Research |
| Costs | Dated trading assumptions and original operating receipts | Platform + research |
| Statistics | Materiality, alpha, dependence-aware uncertainty, multiplicity/stopping and cash benchmark | Scientific owner + independent reviewer |
| Holdout | Exposure audit; model pretraining eligibility for confirmatory claims | Independent scientific reviewer |

The existing 20/70/75/20/100 percent ETF/equity/bond/gold/gross values are
research candidates in `stage1-risk-universe-feasibility.md`, not newly approved
production limits. Development feasibility must account for B4/B5 selecting six
of twelve assets and their actual internal turnover. The R schema supports the
existing return-minus-volatility-minus-drawdown-minus-switch-cost proposal; it
requires an exact executable formula hash and development fit, not vague prose.

## Template and acceptance

`tests/fixtures/stage1/study-freeze-template-v1.json` records the agreed structure
and proposed 2021-2023 / 2024 / 2025 discovery split. Its unresolved fields are
`null`. It MUST assess BLOCKED and MUST NOT be represented as a frozen runnable
historical study. Input choices can be resolved independently behind the typed
contracts without modifying the accounting engine or weakening source checks.

Unit tests demonstrate rejection of missing/duplicate/foreign receipts,
protocol changes, verifier outages, unverified holdouts, pretraining overlap,
reversed/overlapping windows and altered 253/126 boundaries. Positive tests use
explicit synthetic verification doubles and do not certify a real study.
