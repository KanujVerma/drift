# Offline forward readiness evidence-gap preflight (Issue #537)

**Status: preparatory code with unrun synthetic tests. This is not forward-operations clearance.**

## Scope and live ownership

Matthew owns [#384](https://github.com/KanujVerma/drift/issues/384), the prospective shadow/paper-readiness **architecture** issue. The original task is **BLOCKED**, and its only original authorized writing surface is `docs/architecture/adaptive-experiments/forward-readiness.md`. That file is not modified, created or claimed by this assist. The original dependent source (#378), timing (#379) and mandate (#380) proposals are not accepted operational contracts, and the research/methodology and execution-uncertainty boundaries still need appropriate independent acceptance. A closed setup issue or passing synthetic test does not release these dependencies.

This is the second of two user-requested separate unused Matthew-area coding assists. The other is [#536](https://github.com/KanujVerma/drift/issues/536), a review of the existing merged QQQ offline-replay evidence. Publishing agent: GPT-6 through authenticated `Krish-Verma` with the user's direct code-and-documentation instruction. Matthew remains the authoritative platform producer and original file owner.

Read [AGENTS.md](../../../../AGENTS.md), [D01-D17](../decisions.md), [agent workflow](../../agent-workflow.md), [#384](https://github.com/KanujVerma/drift/issues/384), [#378](https://github.com/KanujVerma/drift/issues/378), [#379](https://github.com/KanujVerma/drift/issues/379), [#380](https://github.com/KanujVerma/drift/issues/380), [#411](https://github.com/KanujVerma/drift/issues/411), [#396](https://github.com/KanujVerma/drift/issues/396) and [#508](https://github.com/KanujVerma/drift/issues/508). None of the unmerged draft producer documents gains runtime authority from this checker.

## Exact three-file branch scope

- `scripts/forward_readiness_preflight.py`: pure in-memory evidence-index classifier; no I/O.
- `tests/unit/test_forward_readiness_preflight.py`: synthetic positive, missingness, revocation, alias, feed-failure and adversarial acceptance vectors, **not yet executed**.
- `docs/architecture/adaptive-experiments/verification/forward-readiness-preflight.md`: this contract and future AntiGravity handoff.

No existing producer path, real broker/order/credential adapter, risk gatekeeper, M2 account state, actual source history, experiment admission, UNKNOWN journal, containment mechanism, private data, `.python-version`, `uv.lock`, or original #384 design file is edited. The code never opens a file, accesses the host, creates credentials, contacts a provider or launches a trading process.

## Pure review contract, not an operational gate

`preflight_forward_readiness(payload: object) -> ForwardReadinessPreflight` processes one *untrusted*, strictly JSON-shaped fixture with a bounded declared campaign, fixed evaluation cutoff, intended mode, claimed accounts and evidence dimensions, producer contracts, feed/hold state, credential mode, separate operation-grant claim where applicable and reviewed-issuer references.

Three explicitly distinct **candidate modes** are supported. They are not authorizations or an accepted production rollout ladder:

| Candidate mode | What its untrusted fixture can review | Critical limitations |
| --- | --- | --- |
| `LOCAL_SHADOW` | Offline, non-connected synthetic arm/account and source/replay planning with `NO_EXTERNAL_CREDENTIALS` | Cannot infer provider entitlement, real trades, order execution or external data rights |
| `CONNECTED_PAPER` | Additional provider-account/feed claims, credential custody, order capability, unknown reconciliation, external budget, containment and an explicitly scoped paper-operation-grant claim | No confirmation of actual paper account existence, original issuer, broker/API access, filled orders or authority |
| `LIVE` | All paper dimensions plus separate live-capital account/authority, operational signoff, loss/liquidity scope and production containment claims | **No real-money activation, grant of capital, issuer or live brokerage verification** |

The base evidence dimension set deliberately includes source use/retention, original information availability, venue/session, mandate/risk, execution/fill model, complete account/open-orders state, unique arm-account allocation, cost attribution, audit retention, data protection, feed-failure handling, and rollback/fencing. The connected modes additionally demand separately named external-custody/account/feed, broker, durable UNKNOWN, budget and containment dimensions. LIVE requires its own explicit live-capital and operational-review claims.

Each dimension has a `claim`, evidence reference, campaign scope, claimed first availability, producer identity and independent review reference. `CLAIMED_COMPLETE` means **only that a caller asserted completeness**; the checker does not verify the source, reviewer authority, signature, retention rights, broker account or actual content. A claim other than `CLAIMED_COMPLETE` is returned as a specific missing/unaccepted dimension. Future-available evidence cannot be backdated. Missing scope, malformed UTC, empty reference or author self-review refuses.

Similarly, the conservative proposed contract list includes original #384 dependencies #378, #379, #380 and #377 for all modes, plus explicit UNKNOWN, RESULT/account provisioning and containment gaps for connected modes, and separate live authority for LIVE. `CLAIMED_ACCEPTED` is **not evidence of an actual merged or accepted contract**: Antigravity/owners must compare it to authoritative GitHub release, reviews, contracts and native dependency state. These are a preparatory *review checklist*, not a newly adopted normative dependency graph or alternative owner ruling.

Every candidate account must bind a unique arm and original internal account identity, with a claimed original allocation receipt, issuer and environment. In connected modes, an additional external account reference must be nonblank and unique. If a prospective experiment asks for five arms, five aliases or duplicated paper-account references cannot be declared five independent connected accounts. Conversely, five distinct strings are **still not proof** that the broker issued five accounts. The original provisioner/issuer and their retained evidence are unresolved in [#508](https://github.com/KanujVerma/drift/issues/508), so this code does not create one.

External candidate modes additionally require an explicit campaign-scoped, purpose-specific, unexpired, unrevoked and claimed-issuer/verification **operation-grant reference**. This is a synthetic paper document input and cannot issue/consume a real permit or satisfy a provider's terms. In LOCAL_SHADOW, an external operation grant is rejected rather than quietly activating a connected mode. Neither an empty paper account list, successful source query nor a claimed clear account hold can imply no obligations or safe execution. Missing feed coverage, uncertain settlement and an UNKNOWN hold produce explicit review gaps.

The return `ForwardReadinessPreflight` contains `structurally_reviewable`, `checked_mode`, `claimed_distinct_account_count`, `missing_or_unaccepted_dimensions`, `unresolved_contracts`, and `reasons`. A structural success means **only internally complete mock paperwork**, not operational readiness. If an input is invalid, it cannot claim a positive independent account count.

The three irreversible permission safeguards are unconditional:

- `authorizes_provider_connection=False`
- `authorizes_paper_live_or_deployment=False`
- `proves_real_account_entitlement=False`

No consumer should reinterpret `structurally_reviewable` as permission to connect feeds, fetch private data, launch a paper broker, modify policy, spend money or trade. There is no hidden network call, button, subprocess, issuer, token or side effect.

## Boundaries and remaining decisions

The current #384 scope is a future operational design request that cannot yet be accepted. The original producer and independent reviewers must decide and authenticate rights/retention, actual source vintage and coverage, eligible venue hours/quotes, EXEC timing, effective risk/mandate and refusal rules, E1 original arm-account provisioning, account-wide UNKNOWN resolution, ordering/late fills, budget and cost attribution, audit custody, connection/credential limits, rollback and executor-fencing. These facts cannot be demonstrated by a submitted JSON fixture.

The externally scoped `operation_grant` is *not* an accepted live credential permission or trading order mandate. Full LIVE remains independently gated; neither Conservative/Aggressive naming nor model confidence can bypass mandatory platform protection. There is no promise that five independent paper accounts are available, that Alpaca news/history is complete, or that a shadow backtest proves profits.

## Deferred AntiGravity verification

The user expressly requested code and documentation now, with AntiGravity handling testing later. **No unit suite, Ruff, mypy, build, canonical CI inspection, provider probe, credential operation or paper/live test was executed during this authoring session.**

At the exact GitHub PR head, AntiGravity should read the three new files, #384, and the current producer/consumer documents and run:

```bash
uv run pytest tests/unit/test_forward_readiness_preflight.py -q
uv run ruff check scripts/forward_readiness_preflight.py tests/unit/test_forward_readiness_preflight.py
uv run ruff format --check scripts/forward_readiness_preflight.py tests/unit/test_forward_readiness_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Review the complete [agent workflow](../../agent-workflow.md), confirm the branch changes exactly three new paths, no U+2014 or secrets appear, and Python and `uv.lock` are unchanged. GitHub Actions may run automatically but does not constitute independent AntiGravity or platform-owner acceptance.

### Synthetic test oracles, written but unrun

1. Structurally coherent LOCAL_SHADOW, CONNECTED_PAPER and LIVE fixture packets are all permanently unauthorized for network, paper and live operations.
2. Five distinct *claimed* external accounts remain unverified; reusing one external account string for two arms refuses.
3. Cross-arm reuse of an internal account, missing original allocation evidence, duplicate arm and incorrect arm count refuse.
4. LOCAL_SHADOW with external credentials or broker-account reference refuses; paper/live need their own declared grant purpose and credentials mode.
5. Revoked, expired, future or wrong-campaign grant claims refuse without substituting a grace window.
6. Unaccepted source/EXEC/mandate/methodology contract, missing required authority or unknown source rights and cost dimensions remain explicit separate gaps.
7. Feed failure or UNKNOWN account hold refuses structural completeness, not quiet no-news or flat-account assumptions.
8. Future-available audit evidence and cross-campaign mandate or grant claims refuse.
9. Self-reviewed producer receipts, absent external capability dimension, unsolicited permission-bypass field, and caller-defined Python comparison objects refuse.
10. Repeated review of identical mock input is deterministic, read-only and cannot mint a grant.

Further real deployment testing, account proofs, source acquisition or broker validation **requires separate grants and accepted contracts**; the present candidate cannot authorize them.

## Review and final disposition

Matthew owns final #384 architecture and producer decisions, supported by source, EXEC, mandate, scientific, containment, account and rights custodians. AntiGravity independently verifies this exact code head and reports actual failures/corrections. Do not merge this preparatory draft based solely on green synthetic tests. Keep original #384 blocked and open, with no paper/live permission or attempt to override its dependencies.
