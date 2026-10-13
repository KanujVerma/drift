# Requirements crosswalk

This page maps accepted research requirements to decisions, producers and issue
lineage. It is not a live status board. Read the issue for current blockers.

Matthew's separate handoff used its own decision numbers. Those numbers are not
D01-D17. The private handoff archive is not in this repository. Unverified
historical details stay marked here instead of being treated as new grants.

| Requirement | Decisions and design | Producer | Issue lineage | Evidence still required |
|---|---|---|---|---|
| Research, test and learn inside approved families | D01, D13, D14 | Krish proposes and learns. Harsha specifies the study. | #375, #392, #377 | Generated strategy code and unrestricted self-modification stay outside the MVP. |
| Causal backtesting | D06, D11, D16, design timing section | Matthew for the evaluator. Harsha for the study window. | #379, #376, #392 | Daily bars are not intraday-fill proof. The current evaluator protocol stays until a versioned extension is accepted. |
| Realistic costs | D07, D12, D13 | Matthew for trading costs. Krish for raw inference receipts. Harsha for attribution. | #376, #375, #382 | Unknown cost is not zero. No double counting. Shared preprocessing is disclosed. |
| Experiment tracking | D13, D14 | Harsha for the canonical trial record. Krish for raw receipts and learning state. | #392, #382, #375 | Invalid, rejected and duplicate attempts are recorded. Replay is retained. |
| Separate USD 10,000 accounts A/B/C/D/R | Design research-portfolio section | Matthew for account isolation. Harsha for the comparison. | #374, #391, #383 | Arms are counterfactual, not pooled capital. Ordinary passive C and a risk-matched control stay distinct. |
| Protected mandates and approvals | D08, D15, D16, D17 | Matthew | #380 | Scientific qualification, risk enforcement, trade approval and operational authority stay separate states. |
| Repeated and independent evidence | D11, D16 | Harsha | #377, #382, #383 | Replaying one run shows determinism, not an independent investment result. Missing evidence does not pass. |
| Simulation only | Design approval boundary, ADR 0012, trust boundaries | Matthew for enforcement. All owners for their own claims. | #384, #380 | Offline simulation, provider access, broker-connected paper and real capital are different grants. |
| Conditional multi-agent research | Not a D01-D17 deliverable. #16 remains conditional. | Krish would own producer behavior if activated. Harsha would own the study design. | #16, #377 | Four humans and five accounts do not authorize runtime agent teams. Ten agents are not required. |
| Recovery | Historical handoff requirement, carried forward here. Not verified as implemented. | Matthew for the mechanism. Harsha for independent acceptance evidence. | #395, #397 | Three different targets: feature-off on the current kernel, isolated restoration against an exact manifest, and a frozen policy arm on the same corrected kernel. A Git checkout does not prove private-state recovery. This repository does not contain the private archive. |
| Containment and final audit | Historical handoff requirement, carried forward here. Not verified as implemented. | Matthew for mechanisms. Harsha coordinates independent acceptance and does not self-approve. | #396, #397 | Negative probes need positive controls. Prompts, folders, CODEOWNERS and worktrees are not the enforcement boundary. No probe is authorized by the setup revision. |

Release parameters that remain unspecified are listed at the end of
[decisions.md](decisions.md). They include the ETF list, risk and spread
thresholds, source rights, model versions and budgets, clocks, optimizer bounds,
statistical thresholds, approval expiry, pause and cancel behavior, news
retention and wire schemas.
