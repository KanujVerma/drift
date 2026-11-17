# Stage 1 opt-in synthetic execution extensions

## Scope and authority

Issue #578 extends the [controlled synthetic G2 composition](stage1-synthetic-g2.md)
with explicit partial execution, targeted correction of existing mandate breaches,
and original B3/B4/B5 reference accounts. These are installed-host engineering
contracts under the owner's G2 implementation delegation. They do not grant a
provider identity, qualified historical source, scientific acceptance, broker
connection or capital permission.

The original account remains the sole financial authority. The extensions use
the existing `SessionEvaluatorEngine`, `AtomicRebalanceEngine`, portfolio kernel,
M0 runner and original account/RESULT retention. A policy or planner output is an
instruction or preview. Only an original post-commit receipt and its reconciled
trace establish which simulated fills reached that account.

This document specifies the acceptance boundary. Exact revision, completed tests,
cold-process evidence and independent review belong in the issue/PR checkpoints.
Defining a record or documenting a check does not prove integration has passed.

## Explicit declaration and unchanged default behavior

`ExecutionExtensionRecordV1` is an additive original campaign record with kind
`execution_extension`. It retains the explicit `SyntheticExecutionPolicyV1`, an
optional `ProtectiveCorrectionPolicyV1`, the complete canonical original input
bundle and the original cost model before the account invocation. Policy choices
enter the extended financial strategy parameters; a receipt cannot introduce a
different scenario after execution. Bundle retention supports independent quote
and listing reconstruction rather than accepting a hash as source authority.

When no extension is supplied, the existing manifest shape, financial parameters,
atomic execution path and containment behavior remain the default. No partial
scenario or automatic correction is inferred. No-observer traces retain their
existing V1 contract; opted-in observation remains in the existing V2 artifact
container. `RebalanceOutcomeV2` still describes an all-or-none atomic plan. It
does not acquire a misleading partial-success classification.

The new domain policies live in `drift.domain.synthetic_execution`. Selection
and original-kernel booking live in `drift.evaluator.synthetic_execution`.
The optional observer interfaces live alongside the original detached preview
and authorization contracts in `drift.evaluator.session_observer`.

## Actual partial execution

`SyntheticExecutionPolicyV1` has schema version `drift-synthetic-execution/1`, an
explicit policy ID and ordered, unique session overrides. Each session override
names an order by its position in the actual canonical original plan and supplies
an integer verified quantity and status. Unspecified sessions and orders use full
execution under the original cost model. An out-of-range order index, overfill,
duplicate override or incompatible status/quantity fails validation.

| Status | Required verified quantity | Meaning of the remaining requested quantity |
| --- | --- | --- |
| `FILLED` | Exactly the requested quantity | No remainder |
| `PARTIAL` | Positive and less than requested | Unresolved; full execution is not proved |
| `UNFILLED` | Zero | Known unfilled, without permission to resubmit |
| `UNKNOWN` | Zero or positive, less than requested | Unresolved; zero additional fills cannot be inferred |

`SyntheticExecutionSelectionV1` binds the exact original preview hash, complete
plan hash, policy hash, operational invocation identity and complete ordered
inventory of requested orders. It cannot replace the requested order with a
different security or quantity.

Execution follows this order:

1. Resolve original current-session evidence and compute the complete original
   atomic preview. Apply the ordinary exact-preview mandate authorization.
2. Select the explicit synthetic fill scenario only after approval.
3. Reproduce the complete requested plan from the original account, listings,
   open prices and costs. A self-consistent caller-supplied plan is insufficient.
4. Build a separate actual target vector using only verified filled quantities.
   Reprice that subset through the same atomic engine and test its own funding.
   An unconfirmed sell cannot finance a confirmed buy.
5. Commit the funded actual subset through the original portfolio kernel and
   assign that resulting state to the original evaluator. Emit the ordinary
   fill trace rows for exactly those committed quantities and actual costs.
6. Retain `SyntheticExecutionObservationV1` after commitment. It carries the
   original receipt, session and decision session, invocation binding, original
   preview hash and purpose (`strategy` or `protective`).

`SyntheticExecutionReceiptV1` retains both the complete requested plan and the
actual repriced plan, the complete order selection, committed fills, original
before-state hash, cost-model hash and resulting immutable book. It reports
verified fills/quantities/costs and unresolved-order counts without upgrading a
partial order to full completion. A fixed order fee applies to an actual
nonzero executed order under the existing cost model; an unfilled order does
not receive invented fill costs.

An incomplete receipt stops stepping as indeterminate. This includes a known
unfilled order as well as an unknown or partial remainder. Verified fills and
costs remain in the original book and trace. A post-commit retention failure
also stops stepping; it cannot erase already committed fills, repeat the batch,
refund capability consumption or allocate replacement capital.

A strategy transition activates only after its complete approved actual
execution. Partial or unfilled execution cannot inherit full incumbent returns
as completed feedback. A completed protective correction does not activate a
new strategy family.

## Existing-breach correction

`ProtectiveCorrectionPolicyV1` has schema version
`drift-protective-correction/1` and algorithm `WHOLE_SHARE_TARGETED_V1`. Its
`enabled`, `allow_while_paused` and `maximum_preview_evaluations` fields are
explicit. The required preview limit is a strict integer from 1 through 4096.
The policy creates no numerical mandate defaults and does not waive the existing
turnover, evidence, funding, no-short or execution-knowledge requirements.

The independent marked-book check detects security, class or gross breaches
even on sessions with no monthly research request. A detected breach is retained
as `ProtectiveDetectionRecordV1`, referring to the original observation. The next
eligible simulated open supplies a detached `ProtectiveExecutionContextV1` with
the actual unmarked account, session and original clock, staged targets, complete
held/target quote and listing inventory, cost model and invocation binding.
Correction does not wait for an AI proposal. Missing current evidence or prior
unresolved execution still contains the account.

`plan_protective_correction` is a pure planner in
`drift.loop.stage1_protective_correction`. It validates the supplied originals,
requires the current session to belong to the original clock, and checks every
held security against the mandate and matching listing/venue evidence. The
evaluator remains responsible for collecting those quotes from the actual
current session: `ListingOpenPriceV1` alone has no source timestamp.

The deterministic planning rule is:

- Check exposure at original open prices using exact rational comparisons. NAV
  includes original cash, pending claims and all currently held marked notional.
- Correct individual-security breaches first, then class breaches in canonical
  class-name order, then gross exposure. Within a constraint, use descending
  original open notional and UUID bytes as the tie-break.
- Reduce one whole share from an eligible offending position. Include every
  held security in the cumulative target vector, including explicit zero targets.
- Reprice the complete cumulative candidate from the unchanged original book.
  Recheck all caps against the resulting post-cost open NAV, including adverse
  slippage, commission, notional fees and each order's single fixed fee. Costs
  may create another breach in a formerly compliant holding.
- Respect the original turnover limit. If a first small sale is unfunded because
  of a fixed fee, additional shares of an already selected position may fund
  the complete plan. No candidate preview changes the real account.
- Stop at the first funded compliant plan on this deterministic path, verified
  through the original accounting kernel, or at the explicit preview bound.

`ProtectiveCorrectionPlanV1` returns `READY`, `NOT_REQUIRED` or `UNRESOLVED` with
input/state/policy/mandate/session/clock/cost bindings, before and projected open
NAV, preview count and initial/final breach inventory. Only `READY` carries
targets and an M2 preview outcome. That outcome is not an actual receipt.

The algorithm is a bounded targeted trim, not a claim of globally optimal
liquidation. Exhausted resources, nonpositive NAV, indeterminate basis, inability
to fund a compliant plan or a binding turnover limit remain unresolved. The
explicit paused-operation flag permits only this constrained protective path;
it does not enable an incoming strategy change or bypass unknown execution.

The evaluator verifies the returned context binding and sell-only complete
targets, then recomputes and authorizes the actual preview itself. A protective
batch is the sole batch at that open and supersedes a pending strategy batch.
The full context and planner result are retained in `ProtectivePlanRecordV1`.
Actual corrective fills use the same receipt path as strategy fills and retain
purpose `protective` and the protective-policy hash. An unresolved partial
correction does not schedule another attempt against a guessed book.

## Cold verification and recovery boundary

`ActualExecutionRecordV1` joins the original authorization to the original
post-commit observation. The extension, detection, plan, authorization and actual
execution records remain distinct phases in the same verified append-only
campaign journal. The existing bounded payload/chunk transport applies.

Cold acceptance requires the original configured issuer/root and one immutable
ledger prefix, then all of the following:

- Inventory every applicable extension and execution record exactly once; reject
  duplicates, unknown versions, orphans, wrong account/invocation/session joins
  and contradictory chronology, including equal-timestamp append order.
- Recover the retained original bundle, costs and policies, verify their original
  campaign identity, and independently reproduce the complete requested plan and
  actual subset. Never accept arbitrary receipt arithmetic or a matching hash
  as proof of quote origin.
- Match every committed receipt fill and resulting book to the original evaluator
  trace and original M0/RESULT association. Verify that missing receipt retention
  cannot be treated as a successful no-fill outcome.
- Recompute each protective plan from its retained original context, verify the
  causal detection and next eligible open, and recheck post-cost mandate caps.
- Preserve incomplete and indeterminate classifications and the unresolved
  requested quantities. Verified committed quantities are not proof that the
  unknown remainder could not have executed.
- Restore the original installed source and pinned environment, reopen in a new
  process without writer capabilities, and leave the original ledger unchanged.

Recovery here means reconstructing and checking retained original evidence. It
does not resolve an unknown remainder without new authoritative evidence, resume
an indeterminate account, retry an order or turn a partial interval into complete
scientific economics. Those require a separately supported reconciliation
transition; neither a declaration nor successful neighboring rows supply it.

## Original reference accounts

`drift.loop.stage1_reference_accounts` provides `build_reference_configuration`,
`execute_reference_accounts` and `read_reference_accounts`. Its profile is
`drift-stage1-original-reference-accounts/1`.

B3, B4 and B5 each receive a distinct original E1 account and USD 10,000 opening
book, run their fixed installed family through the same evaluator and M0 runner,
and retain original allocation, consumption, result and trace evidence. Reference
capital and gains never transfer to scored B/R accounts. The wrapper records
whether the original family has enough eligible history: B4 requires 253
completed observations and B5 requires 61. It does not manufacture a signal or
rename one baseline's algorithm as another.

The audit layer retains original terminal locators. The common selector-facing
view exposes only the eligible original trace prefix at the requested decision
cutoff. Available history requires 127 contiguous completed marks and 126
completed intervals; insufficient history remains `UNAVAILABLE`. Later terminal
classification or future marks cannot enter an earlier candidate context. Both
selectors must receive the same detached common view. Reference histories are
account evidence, not fitted comparator coefficients or proof of superiority.

## G3 boundary and verification evidence

The [G3 protocol specification](../stage1-g3-protocol-v1.md) fixes development
procedure and execution choices under the owner's delegation. The existing
[G3 admission contract](../stage1-g3-freeze.md) still requires original evidence
before an executable historical study can be frozen and admitted.

Qualified data and calendar history, rights and retained source availability,
actual immutable AI model/replay configuration, development-only R calibration,
mandate feasibility, costs and the required original review receipts remain
separate inputs. Synthetic partial fills, protective correction and reference
accounts do not supply these inputs. No scored historical result or confirmatory
holdout claim follows from this extension.

Focused tests exercise the new quantity/status contracts and kernel booking,
protective planning and inert-source registration. Campaign integration and
fresh-process recovery must additionally cover genuine partial fills, unresolved
remainders, original receipt mutation/omission, real correction at a later open,
monthly-no-research correction, independent reference histories and unchanged
legacy paths. Exact completed outcomes and failures must be reported on the
current issue/PR revision before G2 is marked complete.
