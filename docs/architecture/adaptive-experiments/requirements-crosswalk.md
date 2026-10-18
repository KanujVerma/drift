# Requirements crosswalk

This page maps accepted research requirements to decisions, producers and issue
lineage. It is not a live status board. Read the issue for current blockers.

Matthew's separate handoff used its own decision numbers. Those numbers are not
D01-D17. The private handoff archive is not in this repository. Unverified
historical details stay marked here instead of being treated as new grants.
Historical scientific deliverables originally assigned to Harsha (#377, #382,
#383, #392, #397) were transferred to Kanuj under accepted
[ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)
following authenticated per-issue migration receipts. Historical Harsha records
remain readable on prior issues, but active scientific ownership resolves to
Kanuj with independent-review obligations preserved.

| Requirement | Decisions and design | Producer | Issue lineage | Evidence still required |
|---|---|---|---|---|
| Research, test and learn inside approved families | D01, D13, D14 | Krish proposes and learns. Kanuj specifies the study (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #375, #392, #377 | Generated strategy code and unrestricted self-modification stay outside the MVP. |
| Causal backtesting | D06, D11, D16, design timing section | Matthew for the evaluator. Kanuj for the study window (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #379, #376, #392 | Daily bars are not intraday-fill proof. The current evaluator protocol stays until a versioned extension is accepted. |
| Realistic costs | D07, D12, D13 | Matthew for trading costs. Krish for raw inference receipts. Kanuj for attribution (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #376, #375, #382 | Unknown cost is not zero. No double counting. Shared preprocessing is disclosed. |
| Experiment tracking | D13, D14 | Kanuj for the canonical trial record (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). Krish for raw receipts and learning state. | #392, #382, #375 | Invalid, rejected and duplicate attempts are recorded. Replay is retained. |
| Separate USD 10,000 accounts A/B/C/D/R | Design research-portfolio section | Matthew for account isolation. Kanuj for the comparison (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #374, #391, #383 | Arms are counterfactual, not pooled capital. Ordinary passive C and a risk-matched control stay distinct. |
| Protected mandates and approvals | D08, D15, D16, D17 | Matthew | #380 | Scientific qualification, risk enforcement, trade approval and operational authority stay separate states. |
| Repeated and independent evidence | D11, D16 | Kanuj (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #377, #382, #383 | Replaying one run shows determinism, not an independent investment result. Missing evidence does not pass. |
| Simulation only | Design approval boundary, ADR 0012, trust boundaries | Matthew for enforcement. All owners for their own claims. | #384, #380 | Offline simulation, provider access, broker-connected paper and real capital are different grants. |
| Conditional multi-agent research | Not a D01-D17 deliverable. #16 remains conditional. | Krish would own producer behavior if activated. Kanuj would own the study design (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #16, #377 | Four humans and five accounts do not authorize runtime agent teams. Ten agents are not required. |
| Recovery | Historical handoff requirement, carried forward here. Not verified as implemented. | Matthew for the mechanism. Kanuj for independent acceptance evidence (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #395, #397 | Three different targets: feature-off on the current kernel, isolated restoration against an exact manifest, and a frozen policy arm on the same corrected kernel. A Git checkout does not prove private-state recovery. This repository does not contain the private archive. |
| Containment and final audit | Historical handoff requirement, carried forward here. Not verified as implemented. | Matthew for mechanisms. Kanuj coordinates independent acceptance and does not self-approve (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md)). | #396, #397 | Negative probes need positive controls. Prompts, folders, CODEOWNERS and worktrees are not the enforcement boundary. No probe is authorized by the setup revision. |

Release parameters that remain unspecified are listed at the end of
[decisions.md](decisions.md). They include the ETF list, risk and spread
thresholds, source rights, model versions and budgets, clocks, optimizer bounds,
statistical thresholds, approval expiry, pause and cancel behavior, news
retention and wire schemas.

## Acceptance obligations

These obligations are the completion bar for the named issues. They do not
authorize a restore, a containment probe, a broker connection or M9 runtime.

### #392 experiment contract

Define frozen campaign and arm identity, and which state may change during a
campaign. Reference Matthew's authoritative RESULT and Krish's attempt receipts.
Specify complete treatment of valid, failed, rejected and duplicate trials.
Allocate cost without a second account ledger. Include eligibility and refusal
states, version and compatibility rules, and examples for malformed, missing,
stale and cross-arm evidence. Krish reviews research and feedback consumption.
Matthew reviews operational eligibility consumption. Kanuj does not approve his
own producer changes (retaining the independent-review requirement).

### #393 and #394

#393 specifies triage behavior and output only: supplied policy, time and
version, exact duplicate versus material revision, alert versus non-alert,
abstention and unavailable, and malicious text kept as inert data. #394 is the
only normative minimal source envelope: source identity, times, quality,
missing values, duplicate versus correction, and empty versus broken. Each
owner reviews the other's compatibility. Neither issue implements runtime types.
#376 cites the accepted #394 revision and does not rewrite that envelope.

### #377 conditional agent study

Retain a conditional 1-versus-3 study with matched information, opportunities
and model capability. Count aggregate team requests, tokens and costs, including
critiques, retries and discarded work. Verification sits outside the proposer
team. A flexible-budget economic study does not replace that controlled
comparison. Ten agents remain conditional. Keeping one agent is a valid outcome.
Do not implement M9 and do not add numerical defaults. #16 stays the conditional
gate. Krish reviews producer-behavior implications. Matthew reviews that the
study grants no operational permission.

### #395 recovery

Distinguish three targets: feature-off fallback on the corrected current kernel,
isolated restoration of original code plus private state plus runtime against an
exact manifest and declared scope, and a frozen scientific control on that same
corrected kernel. Require separate evidence for code, private state and runtime,
including tree state, database and schema consistency, dependencies and replay.
Name the authorized custodian and the isolated target. Preserve later trials,
costs, losses and audit lineage. An old checkout is not verified private-state
recovery and is not a safe active deployment. Do not point old code at an
incompatible current database. This issue does not perform a restore. Kanuj's
#397 (transferred under [ADR 0017](../../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md))
reviews the evidence rules. Matthew does not self-certify them.

### #396 containment

Specify worker, trusted evaluator and recorder, independent holdout evaluation,
and publisher boundaries. Protect results, policy, approvals, original private
state and secrets. State effective IDE, terminal, plugin, MCP, hook and
subprocess capabilities, and allowed versus denied network destinations. An
unconfined fallback is a refusal. Describe inert denial probes and allowed
positive controls, plus the tested revision and environment to record. Do not
run those probes from this issue. Kanuj's #397 reviews independence. Prompts, folders,
CODEOWNERS and worktrees are not the enforcement boundary.

### #397 release acceptance

Build the requirement-to-test matrix, independence and conflict rules, tested
revision and environment, and pass, fail, not-run, blocked and unavailable
treatment. State what forbids a release claim. Kanuj may evaluate Matthew's
mechanisms with evidence. He may not certify his own changes or replace evidence
with an assertion. Operational authority stays a separate grant.
