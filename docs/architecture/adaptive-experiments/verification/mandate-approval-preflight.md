# Offline mandate and approval consumption preflight (Issue #529)

**Implementation candidate, not executed and not an authorization system.**
Accountable Matthew producer: [#380](https://github.com/KanujVerma/drift/issues/380), original [MANDATE M2 draft PR #414](https://github.com/KanujVerma/drift/pull/414). The draft `docs/architecture/adaptive-experiments/contracts/mandate.md` is **not** accepted as an operational wire, numeric risk rule or persisted approval schema. Kanuj accepted its conceptual deterministic safeguards only and separately asked for development-only Balanced feasibility studies; neither acceptance authorizes broker/paper/live trading. The paired user-requested coding issue is [#528](https://github.com/KanujVerma/drift/issues/528), covering Matthew's minimal SRC envelope.

## Scope, owner, protected code and state

- Accountable producer: Matthew (`matthew-philip`). Authenticated isolated coding assistant: GPT-6 through `Krish-Verma` by the user's request for another pair of unclaimed Matthew-area tasks.
- This PR adds exactly `scripts/mandate_approval_preflight.py`, `tests/unit/test_mandate_approval_preflight.py`, and this documentation file.
- Existing #380/#414 mandate draft, #411 UNKNOWN/settlement, #379 EXEC timing, #376/#508 RESULT and Stage 1 identity, #423/#491 admission, current `RiskPolicyV1` / hard gatekeeper, replay/hash contracts, immutable records, account/broker adapters, interpreter, dependencies, private state and accepted risk decisions all remain read-only.
- No live state, account, model, issuer, financial balance, provider, quote feed, broker or original saved record is read or modified. The module uses only Python standard-library deterministic functions on untrusted in-memory input.

Read [AGENTS.md](../../../../AGENTS.md), [decisions](../decisions.md), the [agent workflow](../../agent-workflow.md), [ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), owner [#380 approval and 2026-10-20 research direction](https://github.com/KanujVerma/drift/issues/380), draft [PR #414](https://github.com/KanujVerma/drift/pull/414), [#411](https://github.com/KanujVerma/drift/issues/411) and [#423](https://github.com/KanujVerma/drift/issues/423). These are separate governing surfaces; unmerged drafts do not constitute approved risk values.

## Data and code contract

`preflight_mandate_approval(payload: object) -> MandateApprovalPreflight` reads a closed `synthetic-mandate-review-v1` fixture. This is a local review profile, **not** an installed or proposed production wire.

The fixture contains one `as_of_utc` and requested operation, an immutable claimed mandate/epoch, one full request preimage, a claimed approval grant, current state/quote observations, mandatory policy thresholds, optional Smart policy and observed measurements, and retained attempt/fill-effect history. All claimed authority and external receipt strings remain **unverified**.

**Full request binding.** `canonical_fixture_intent_sha256(request)` deterministically hashes an exact, fixed fixture-only request preimage containing original logical operation and client token, candidate revision, account/arm/environment, mandate/epoch/manifest, state snapshot, effective policy, source cutoff, eligibility, security, side, quantity, USD notional and USD NAV. It refuses unknown fields, malformed digests, bool-as-integer, nonfinite/negative/zero notional or NAV and missing identities. Approval must bind this calculated intent digest, identical current state and mandate hashes and the exact original account, arm, environment and epoch. This detects mock mutation, not trustworthy issuer signature, real account allocation or authoritative M2 provenance. Source/manifest fingerprints named by a caller alone are also **not** independent evidence.

**Mandatory checks always precede mode routing.** The fixture requires eight independent PASS/evidence references (issuer authority, mandate and allowed assets, complete account state, open orders, source/market capabilities, deterministic risk/eligibility, budget reservation and durable dispatch). No assistant, human, model confidence or approval mode may change a mandatory FAIL/UNKNOWN into a pass. It also refuses kill, pause, uncertain execution, revoked/expired mandate or grant, unissued future grant, missing state, epoch mismatch, price from the future, state or quote older than the supplied mandatory policy bound, and absent policy references. Neither PASS labels nor `accepted_policy_ref` string is authenticated by this helper. A complete looking state payload cannot establish actual holdings, pending orders or source freshness.

**Ask/Smart/Auto are not execution permission.** Ask requires a claimed HUMAN grant; Smart/Auto a claimed SYSTEM-derived grant. Mode must equal the declared mandate/grant. For Smart only, the caller supplies every numeric bound and observed value explicitly: USD notional, notional/NAV basis points, gross target weight-change basis points, quote/state age, spread bps, and an evidenced window and order counter. All bounds are deterministic Decimal comparisons. Missing/invalid values refuse; values outside Smart bounds return `ASK_REVIEW_REQUIRED` only when other mandatory conditions hold. The fixture's $500 / 100-bps synthetic boundary is **not an approved Stage 1 threshold**. An automatic system grant outside bounds is not permitted to dispatch while it waits for a *fresh* human review. The accepted issuer/custodian and actual policy numeric thresholds remain pending owner rulings.

**One-shot grant and unresolved attempts.** Retained attempts with matching grant, original logical operation or token are never grounds for another placement; this preflight refuses reuse even if a prior attempt was reserved but no SEND_STARTED receipt exists. Distinct IDs cannot bypass account holds; every existing attempt has account/arm identity checked and intent hash compared. Actual atomic uniqueness, fencing, broker readback, settlement and safe retry protocol belong to #411/#379, not this script. The in-memory list cannot prove absence of concurrent dispatches.

**Pause is not cancellation.** The preflight refuses any new risk while paused or under a kill/uncertainty hold. A record with a separately labelled `PROTECTIVE` action cannot bypass; the helper deliberately refuses all operations other than `NEW_RISK`, requiring a different accepted authority and enforcement implementation. Existing immutable fill-effect receipts are retained as separate claimed facts, including quantity after pause, duplicate same-ID redelivery and conflicts. `reported_post_pause_fill_quantity` is a **self-described diagnostic count**, not an actual account reconciliation, known exposure, filled order or net NAV. Missing fee evidence prevents a claimed complete portfolio in this review model.

The result fields are `review_ready`, `route`, `grant_already_consumed`, `reported_post_pause_fill_quantity`, `reasons`, and permanent false properties `authorizes_order_or_protective_action` and `authenticates_mandate_or_account`. `route` values such as `MANUAL_REVIEW_ONLY`, `POLICY_REVIEW_ONLY`, `ASK_REVIEW_REQUIRED` and `REFUSED` are **diagnostic labels only**. They never create human approval, policy issuance, user permission, an executable permit or an accepted order.

## Explicit acceptance limits and missing material interfaces

This tool performs **no trusted control authentication**; even a green synthetic fixture cannot prove actual authoritative issuer signature, account provisioning, holdings, real-time quote validity, mandatory risk evaluation, acceptable class/position/turnover budgets, operation-grant expiry, durable reservation, idempotent broker execution, or source rights. Matthew must design and bind trusted producer semantics. Kanuj's 2026-10-20 20%-position / 70%-equity / 75%-bond / 20%-gold / 100%-gross development candidate remains a **development study**, not G3 freeze. No such numeric cap has been embedded here.

The fixture-only canonical request digest is not a commitment to a future persisted wire. Missing status or revocation cannot default to false. The preflight is not wired into any real risk gatekeeper, strategy evaluator, broker, network, exchange clock, source adapter or ledger. Existing #411 critical UNKNOWN-state defects are **not fixed** by this code.

## AntiGravity test instructions (all deferred by user)

The author has **not run** the unit tests, Ruff, mypy, build, canonical CI or independent tests. On the precise published PR head, AntiGravity should review all three new files and PR #414/issue #380, then run:

```bash
uv run pytest tests/unit/test_mandate_approval_preflight.py -q
uv run ruff check scripts/mandate_approval_preflight.py tests/unit/test_mandate_approval_preflight.py
uv run ruff format --check scripts/mandate_approval_preflight.py tests/unit/test_mandate_approval_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Follow the full pinned [agent workflow](../../agent-workflow.md), inspect branch/main file diffs, confirm no lockfile/policy/legacy hash changes, and keep automatic hosted GitHub CI separate from actual AntiGravity testing.

### Non-vacuous acceptance and adversarial oracles (test code committed, unrun)

1. Exact synthetic ASK/SMART/AUTO records can be structurally reviewable but have **zero authority** to send a trade.
2. Change original request quantity, candidate/account, arm, state digest, token or mandate epoch after approval: calculated full-intent binding no longer matches.
3. Identical grant at expiry boundary, revoked mandate or incompatible issuer mode: refuse.
4. ASK human approval does not cure an expired quote, stale portfolio, unknown open order, failing deterministic risk, kill, pause or UNKNOWN execution hold.
5. Smart synthetic $500 and 100-bps boundary can be checked only against explicit caller-provided fixture values. $500.01, excessive trailing order count or missing bounds cannot become Auto by default; strict bounds and window semantics need later ratification.
6. A previous durable reserved/started attempt for the same grant/operation/token blocks a second call. A fresh client token while the account is held is not a workaround.
7. New-risk refusal on pause retains a separate claimed two-share late fill; exact repeated effect receipt counts once; changed same-ID receipt conflicts.
8. Unknown fee with a claimed complete account is refused, not rounded to zero.
9. A `PROTECTIVE` SELL label cannot bypass missing independent protective policy. Actual bounded corrective trade belongs to a separately accepted mechanism and complete state.
10. Bool quantities/counters, NaN/not-a-decimal, wrong namespace/foreign arm, future clocks, unsolicited schema fields and subclassed containers fail closed.
11. Independent reviewers should add concurrency/restart, stale snapshot, cross-branch/arm replays, precision and serialized canonical preimage oracles once the producer freezes a real wire.
12. Tests may prove only this bounded synthetic checker; true cryptographic issuer proofs and durable account writes require a later **separately authorized** implementation and environment.

## Required future approvals

Matthew: accept exact trusted mandate/policy/issuer/grant semantics, effective risk ceiling and #411 durable lease and resumption interface. Kanuj and Krish: review scientific/B-versus-R applicability and accepted Stage 1 policy identity. Independent engineering/security/scientific reviewers: check the complete binding, no duplicate dispatch, fake-source refusals and resulting policy as applicable. AntiGravity: run and inspect the exact-head code/tests. Keep draft; no autonomous merge, issue closure, paper/live/personal financial execution or claims of authorization.
