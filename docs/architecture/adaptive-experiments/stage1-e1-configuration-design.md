# Stage 1 E1: Reusable Campaign, Arm and Run-Account Configuration

## Status, owner and precedence

- **Owner:** Kanuj, `workstream:kanuj`.
- **Architecture issue and owner decisions:** [#460](https://github.com/KanujVerma/drift/issues/460), decisions E1-A through E1-E, October 19, 2026.
- **Parent:** [#391](https://github.com/KanujVerma/drift/issues/391). **Next integration:** [#383](https://github.com/KanujVerma/drift/issues/383).
- **Merged logical contract:** [`contracts/experiment.md`](contracts/experiment.md), Sections 3.1 and 3.2, PR #434.
- **Stage 1 direction:** [`stage1-decisions.md`](stage1-decisions.md), [`methodology.md`](methodology.md).
- **Existing hashing primitive:** `drift.serialization.canonical.canonical_json` and `content_hash`.
- **Approval:** Owner-approved **local implementation design**. This document is not an accepted producer wire schema, historical source qualification, independent scientific approval, G3 protocol freeze, or permission to create accounts/trades. Its documentation PR must pass its own review; a separate READY code issue with exclusive file claims authorizes implementation.

## 1. Decisions and reasons

| ID | Chosen design | Reason | Rejected/deferred |
| --- | --- | --- | --- |
| E1-A | Complete reusable logical `CampaignSpecV1`, `ArmSpecV1`, `RunAccountBindingV1`. | B/R plus controls, independent replicates and sensitivity studies must share stable identities. | B/R-only reduced schema, second portfolio ledger. |
| E1-B | Structural validation and reference identity only, separate G1/G2/G3 qualification and operational authority. | Synthetic hash consistency does not authenticate a producer or approve scoring. | Treating placeholders and synthetic accounts as approved market/platform evidence. |
| E1-C | All required fields supplied; immutable snapshot; explicit `frozen_at` with no editable draft state. | Stable, reproducible fingerprints and fewer partial states. | Implicit freeze/clock, mutable draft, missing fields silently filled. |
| E1-D | Canonical DecimalText monetary strings (`"10000"`, `"10000.5"`). | One byte representation per amount, as prescribed by contract Section 3.3; no float ambiguity. | The illustrative Section 3.2 noncanonical value `"10000.00"`, float coercion, source receipt rewrites. |
| E1-E | Frozen slots dataclasses, dedicated typed nested structures, deeply immutable opaque JSON for truly under-specified objects. | No nested mutation can alter a frozen hash and known fields can be validated without guessing producer internals. | A permissive dictionary-first API or a second JSON serializer. |

**Architect-specified mechanical decisions within those choices:** typed nested value classes; UTC six-digit timestamps; immutable JSON-map and array wrappers; exact content preimages; validation of isolated bindings as a complete collection; generic configuration rules separate from an optional Stage 1 synthetic B/R check. These choices must be challenged with concrete contract/source evidence rather than silently changed.

## 2. Exact implementation boundary

**Proposed code issue, to be created separately: exactly two new tracked files**

1. `src/drift/experiments/stage1_campaign_config.py`
2. `tests/unit/test_stage1_campaign_config.py`

This architecture document is authored under #460, **not** under the eventual implementation issue. Do not edit existing `__init__.py`, `stage1_trial_events.py` (#448/#455), `stage1_preparation.py`, `stage1_metric_math.py`, `parallel_portfolios.py`, platform ledger/evaluator, Krish producer code, old M1c/M1d evidence, tests outside this unit file, CI or `uv.lock`. Use direct module imports. Reuse existing canonical serializer. CPython 3.14.6 pinned.

**Zero side effects:** no file, provider, database, network, broker, API, clock default, account creation, mutable global registries, alternate simulator, metrics scoring or claim that `drift-experiment/1-draft` is an accepted external persisted schema.

## 3. Deeply immutable value graph

Every class below uses `@dataclass(frozen=True, slots=True)`.

**Typed nested logical objects:**

- `PrimaryComparisonV1(test_arm_id: str, comparator_arm_id: str)`; distinct nonblank scoped arm identifiers.
- `DataWindowV1(start_date: str, end_date: str, calendar_id: str)`; dates are exact `YYYY-MM-DD`, real Gregorian dates and ascending; calendar is an inert nonblank reference, not a qualified exchange schedule.
- `SessionWindowV1(sessions_count: int)`; genuine non-boolean, nonnegative `int`. A window's existence does not prove sessions are complete or genuine.
- `ScoringWindowV1(start_session: str, end_session: str, fresh_accounts: bool)`; distinct nonblank session identifiers; `fresh_accounts is True`. E1 cannot infer session order from unqualified opaque IDs.
- `DecisionScheduleV1(frequency: str, alignment: str, execution_timing: str)`; all nonblank, preserve exact declared values. The generic model does not invent an exchange-calendar enumeration.

**Opaque nested JSON:** `FrozenJSONMap(items: tuple[tuple[str, FrozenJSONValue], ...])` and `FrozenJSONArray(items: tuple[FrozenJSONValue, ...])`, with recursive `FrozenJSONValue = None | bool | int | str | FrozenJSONMap | FrozenJSONArray`. Provide private `_freeze_json`, `_json_plain` and `_verify_frozen_json` helpers. They must:

1. Deep-copy supported caller mappings and list/tuple arrays into frozen dataclasses/tuples; sort object keys lexicographically; preserve array order and repeated array elements.
2. Refuse floats, `Decimal`, byte strings, NaN, sets, arbitrary objects, non-string map keys, cycles, duplicate immutable-map keys, reordered immutable-map keys, invalid wrapper element types, and booleans where an integer is required.
3. At verification, validate the **original** stored wrappers rather than silently sorting/replacing tampered data; map ordering is canonical, array order is semantic.
4. `_json_plain` returns new ordinary `dict`/`list` data for the canonical preimage. It must never expose a mutable reference stored inside a frozen object. No parallel JSON serializer is permitted.
5. Support an empty object and empty arrays. `authorization_evidence` is an opaque object: never interpret an `approved` label, metadata hash or sign-off placeholder as independent acceptance.

**CampaignSpecV1: exactly the 29 Section 3.1 fields**, typed as follows:

- `schema_version: str`, `campaign_id: str`, `campaign_spec_fingerprint: str`, `campaign_type: str`, `study_protocol_revision: str`, `created_at: str`, `frozen_at: str`;
- `accepted_contract_revisions: tuple[tuple[str, str], ...]` (canonical ascending key-value entries representing the contract's map);
- `research_question_id: str`, `primary_comparison: PrimaryComparisonV1`;
- `control_arm_references: tuple[str, ...]`, `arm_spec_references: tuple[str, ...]`, `qualified_dataset_references: tuple[str, ...]`;
- `data_window: DataWindowV1`, `warmup_window: SessionWindowV1`, `observation_window: SessionWindowV1`, `scoring_window: ScoringWindowV1`, `decision_schedule: DecisionScheduleV1`;
- `allowed_strategy_families: tuple[str, ...]`;
- exactly nine policy/reference strings: `portfolio_mandate_reference`, `source_eligibility_policy_reference`, `execution_policy_reference`, `cost_policy_reference`, `model_and_prompt_policy_reference`, `learning_and_feedback_policy_reference`, `evaluation_policy_reference`, `holdout_access_policy_reference`, `stopping_policy_reference`;
- `authorization_evidence: FrozenJSONMap`.

**ArmSpecV1: exactly the 18 Section 3.2 fields:**

`schema_version`, `arm_id`, `campaign_id`, `arm_spec_fingerprint`, `selector_type`, `eligible_strategy_references: tuple[str, ...]`, `initial_strategy_reference`, `initial_capital`, `currency`, `arm_account_role`, `mandate_reference`, `execution_policy_reference`, `research_budget_reference`, `information_visibility_policy`, `feedback_policy_reference`, `model_configuration_reference`, `deterministic_seed_reference`, `frozen_configuration_reference`. All unspecified fields are strict strings, not loosely typed objects.

**RunAccountBindingV1: exactly the eight Section 3.2 fields:**

`schema_version`, `binding_id`, `campaign_id`, `run_id`, `arm_id`, `portfolio_account_id`, `initial_cash_allocated`, `bound_at`. No invented binding digest or duplicate account ledger.

Builders accept timezone-aware `datetime` for new `created_at`, `frozen_at` and `bound_at`, and store exact UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Verifiers of existing dataclass records reject offsets, naive instances, malformed strings, changed precision and noncanonical dates without repair.

## 4. Public implementation API

Expose exactly these functions in addition to the above value classes:

- `build_campaign_spec(*, campaign_id, campaign_type, study_protocol_revision, created_at: datetime, frozen_at: datetime, accepted_contract_revisions: Mapping[str, str], research_question_id, primary_comparison: PrimaryComparisonV1, control_arm_references: Sequence[str], arm_spec_references: Sequence[str], qualified_dataset_references: Sequence[str], data_window: DataWindowV1, warmup_window: SessionWindowV1, observation_window: SessionWindowV1, scoring_window: ScoringWindowV1, decision_schedule: DecisionScheduleV1, allowed_strategy_families: Sequence[str], portfolio_mandate_reference, source_eligibility_policy_reference, execution_policy_reference, cost_policy_reference, model_and_prompt_policy_reference, learning_and_feedback_policy_reference, evaluation_policy_reference, holdout_access_policy_reference, stopping_policy_reference, authorization_evidence: Mapping[str, object]) -> CampaignSpecV1`. Every otherwise unannotated parameter above is `str`.
- `verify_campaign_spec(*, campaign: CampaignSpecV1) -> bool`.
- `build_arm_spec(*, arm_id: str, campaign_id: str, selector_type: str, eligible_strategy_references: Sequence[str], initial_strategy_reference: str, initial_capital: str, currency: str, arm_account_role: str, mandate_reference: str, execution_policy_reference: str, research_budget_reference: str, information_visibility_policy: str, feedback_policy_reference: str, model_configuration_reference: str, deterministic_seed_reference: str, frozen_configuration_reference: str) -> ArmSpecV1`.
- `verify_arm_spec(*, arm: ArmSpecV1) -> bool`.
- `build_run_account_binding(*, campaign_id: str, run_id: str, arm_id: str, portfolio_account_id: str, initial_cash_allocated: str, bound_at: datetime) -> RunAccountBindingV1`.
- `verify_run_account_binding(*, binding: RunAccountBindingV1) -> bool`.
- `verify_experiment_configuration(*, campaign: CampaignSpecV1, arms: Sequence[ArmSpecV1], bindings: Sequence[RunAccountBindingV1], expected_run_ids: Sequence[str]) -> bool`. The caller supplies the complete expected run manifest for this verification snapshot, not one run at a time.
- `verify_stage1_synthetic_br_configuration(*, campaign: CampaignSpecV1, arms: Sequence[ArmSpecV1], bindings: Sequence[RunAccountBindingV1], expected_run_ids: Sequence[str]) -> bool`, a separate optional Stage 1-specific check after the generic collection verifier.

**Return discipline:** every verifier returns `True` only on intact input and otherwise raises `ValueError`, never an optimistic fallback or `False` on corruption. Builders raise `ValueError` on invalid fields and never coerce malformed values. No public mutator or default clock.

## 5. Strict structural rules

- `schema_version` exactly `drift-experiment/1-draft`, an INTERNAL local profile.
- `campaign_type` exactly one of `HISTORICAL_BACKTEST`, `SYNTHETIC_TEST`, `FORWARD_SHADOW`. Constructing a type name does not qualify it to run.
- `selector_type` exactly one of `ADAPTIVE_AI`, `DETERMINISTIC_COMPARATOR`, `FROZEN_BASELINE`, `PASSIVE_BENCHMARK`, `CASH_CONTROL`.
- `currency` exactly `USD`; no foreign-exchange assumptions.
- Scope token IDs (`campaign_id`, `run_id` and `arm_id`) use ASCII `[A-Za-z0-9][A-Za-z0-9._-]*`, so delimiters cannot make `binding_id` ambiguous. All other scalar refs are exact nonempty strings with no surrounding whitespace. Do not treat bare reference shape as authenticity.
- New timestamp inputs must be aware `datetime`; normalizer uses `value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")`. Stored timestamps require full exact-string parse/roundtrip; campaign `created_at <= frozen_at`.
- Each stored campaign arm fingerprint and `frozen_configuration_reference` is lowercase 64-hex SHA-256. `accepted_contract_revisions` is an immutable ascending map of nonblank producer-contract keys to exact lowercase 40-character Git commit SHAs (empty permitted as unaccepted synthetic configuration). This validates only syntax, not actual acceptance.
- `control_arm_references` and `qualified_dataset_references` may be empty, especially for synthetic fixtures. No missing field is defaulted; all supplied tuples contain unique, exact nonempty references. `arm_spec_references` is nonempty and contains distinct 64-hex hashes. `allowed_strategy_families` is nonempty and unique; list order is preserved as part of the fingerprint.
- `eligible_strategy_references` is nonempty and unique; `initial_strategy_reference` belongs to that exact arm-local set. E1 must NOT automatically assume those refs are already qualified or comparable to the campaign's *family* labels because provider-specific strategy reference mappings are unaccepted.
- `data_window` contains real canonical ISO dates with start <= end. Both `SessionWindowV1.sessions_count` are real non-boolean integers >= 0. The generic model does not hardcode Stage 1 window sizes. `ScoringWindowV1.fresh_accounts` must be the actual Boolean `True`; opaque session identifiers are not converted to dates or ordered by string sorting.
- `initial_capital` and `initial_cash_allocated` are finite, **strictly positive**, exact canonical DecimalText strings: `10000`, `10000.5` valid, `10000.00`, `1e4`, `+10000`, `010000`, `-0`, `0`, `-1`, floats/bools invalid. Use `Decimal(value)` after lexical validation, never float. Positive start is a structural requirement for an active valued portfolio, not a declaration that a run may be scientifically scored.
- `accepted_contract_revisions` map is sorted by key and retains exact value text. Anonymous `authorization_evidence` may be empty or contain synthetic fixture markers, but E1 **never** parses it to grant approval.
- Generic model never defaults to B3, $10,000, 253/126, 12 ETFs, Balanced mandate or a particular execution model. Keep these in the separate Stage 1 checker.

## 6. Canonical fingerprint preimages

Use existing `drift.serialization.canonical.content_hash` on **plain JSON-compatible dictionaries only**. Build the preimage with explicit named fields. `campaign_spec_fingerprint` and `arm_spec_fingerprint` are omitted from their OWN preimage; all other logical fields, including `schema_version` and inert references, are included exactly once.

Expected nested wire objects:

`primary_comparison` => `{"test_arm_id":"ARM-B","comparator_arm_id":"ARM-R"}`;
`data_window` => `{"start_date":"2024-01-02","end_date":"2026-01-30","calendar_id":"fixture://calendar-v1"}`;
`warmup_window` / `observation_window` => `{"sessions_count":253}` / `{"sessions_count":126}`;
`scoring_window` => `{"start_session":"SC-001","end_session":"SC-021","fresh_accounts":true}`;
`decision_schedule` => `{"frequency":"MONTHLY","alignment":"LAST_COMPLETED_SESSION","execution_timing":"NEXT_OPEN"}`;
`accepted_contract_revisions` => JSON object from the frozen tuple-map;
`authorization_evidence` => JSON object through `_json_plain`.

**Do not hash `dataclasses.asdict` blindly, JSON strings containing nested JSON, or internal wrapper field names (`items`).** Canonical JSON object key ordering is handled by the existing serializer. Preserve logical array order in every declared tuple except mapping keys. Two equivalent independently supplied mappings with different insertion order have identical fingerprints. Reordered array elements produce different fingerprints (not silently sorted). A mutation to ANY hashed field with an old fingerprint is rejected by verification, even when the mutable source list was changed after the builder returned.

A direct dataclass constructor or `dataclasses.replace` does not authenticate an object; verification must check the original stored field types, every nested value and the full fingerprint. Recompute via the same private preimage function used by the builder. Zero `U+2014` and no change to accepted serializer.

## 7. Collection-level verification: reproducible isolation

`verify_experiment_configuration`:

1. Verify the campaign and every supplied arm/binding independently. Reject empty arms or bindings; reject strings, maps, unexpected types and duplicate objects where a sequence is required. Require a caller-supplied, nonempty, duplicate-free, strictly validated `expected_run_ids` manifest. The manifest's exact run IDs must match the set represented in supplied bindings. Neither absent runs nor extra runs may be ignored.
2. Every arm's `campaign_id` equals the campaign ID. Arm IDs and arm fingerprints are unique.
3. Campaign `arm_spec_references` (hashes) exactly identifies the supplied arm set, with equal cardinality; order of the **supplied arm sequence** does not matter. The declared `arm_spec_references` array order remains hash-significant inside CampaignSpec.
4. Both primary comparison arm IDs are present and distinct. Every declared control arm ID exists, is unique and is disjoint from the primary comparison; a campaign may have zero controls. The generic reusable validator does not assume every declared arm must be primary or a control (future explicitly designed categories may be added under later accepted protocols), but the **separate Stage 1 synthetic checker** requires the exact partition described in Section 8.
5. Every binding refers to the campaign and an existing arm, and has exact `binding_id = campaign_id + ":" + run_id + ":" + arm_id + ":BINDING"`. All triples `(campaign_id, run_id, arm_id)`, binding IDs, and concrete `portfolio_account_id` values are unique across the **entire collection**, including different runs.
6. Every run in `expected_run_ids` binds **every declared arm exactly once**. This collection completeness rule cannot be proven by validating an individual binding. Every binding's `initial_cash_allocated` exactly equals its matched arm's canonical `initial_capital` text, both already valid DecimalText. Its `bound_at` is not earlier than the campaign's `frozen_at`. A reference value itself does not prove Matthew issued/verified the account.
7. On any mismatch or missing/duplicate arm/account/ref/run manifest, raise `ValueError`. No partial materialization, fill, cash movement, account lookup or mutation. On success, return `True`.

**Explicit proof boundary:** E1 proves non-reuse **only across the complete caller-declared manifest and all its supplied bindings in the current call**. Separate calls with independently incomplete manifests cannot establish global uniqueness. The authoritative complete manifest and reconciliation with historical Matthew account identities are separate accepted producer obligations. Do not invent a persistent registry or label local uniqueness globally verified.

## 8. Explicit optional Stage 1 synthetic B/R profile

`verify_stage1_synthetic_br_configuration` calls the complete generic verifier and additionally requires:

- `campaign_type == "SYNTHETIC_TEST"` and primary comparison exactly `ARM-B` vs. `ARM-R`.
- B `selector_type == "ADAPTIVE_AI"`, R `selector_type == "DETERMINISTIC_COMPARATOR"`.
- B and R each have initial strategy `B3`, admitted strategy *set* exactly `{B3,B4,B5}` (input order retained in fingerprints), exact `initial_capital == "10000"` and currency USD. **EVERY supplied active arm**, including controls and any other candidate, must have `initial_capital == "10000"` and `currency == "USD"`, each with a unique account binding per expected run. There is no exemption for an arm absent from `control_arm_references`.
- B and R have matching `mandate_reference`, `execution_policy_reference`, and `information_visibility_policy == "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"`. This checks equality only, not validity of a numeric Balanced mandate.
- `warmup_window.sessions_count >= 253`, `observation_window.sessions_count == 126`, `decision_schedule.frequency == "MONTHLY"`, `decision_schedule.alignment == "LAST_COMPLETED_SESSION"`, `decision_schedule.execution_timing == "NEXT_OPEN"` and fresh accounts true. This alignment token is an **E1 synthetic fixture marker**, not an accepted exchange calendar enum; real last eligible month-end close and next eligible open must be proved with the qualified session clock. `SAME_CLOSE` and other earlier execution requests are rejected.
- The supplied arm IDs must partition **exactly** into the primary pair `{ARM-B, ARM-R}` plus the declared `control_arm_references`: reject any extra or unclassified arm (e.g., `ARM-X` with no control declaration), and reject any missing declared control. This strict partition applies only to the Stage 1 synthetic B/R checker, not to generic E1 configurations.
- The campaign's `allowed_strategy_families` must include `B3`, `B4` and `B5` as distinct entries, regardless of the arm-local pools. It may contain explicitly declared additional control families. The generic verifier must not assume a mapping from arbitrary control strategy IDs to producer family IDs.
- Optional controls can declare other frozen families/strategies and need not start in B3.
- Do NOT certify qualification of a real 12-ETF cohort, account provisioning, scored duration, actual month-end exchange calendar, first-switch timing, AI/R information equality at a future cutoff, G3 freeze, strategy performance, or empirical advantage. Those require other accepted producers/gates.

## 9. Deterministic synthetic golden fixture, exact oracle values

All fixture timestamps are inert synthetic data, **not** historical market evidence. The following dictionaries represent the PREIMAGE excluding each calculated fingerprint. They are complete contract field sets, not abbreviated fixtures.

### Arm B preimage

```json
{
  "schema_version": "drift-experiment/1-draft",
  "campaign_id": "CAMP-E1-SYNTH-001",
  "arm_id": "ARM-B",
  "selector_type": "ADAPTIVE_AI",
  "eligible_strategy_references": ["B3", "B4", "B5"],
  "initial_strategy_reference": "B3",
  "initial_capital": "10000",
  "currency": "USD",
  "arm_account_role": "PRIMARY_TEST",
  "mandate_reference": "fixture://balanced-mandate-v1",
  "execution_policy_reference": "fixture://next-open-v1",
  "research_budget_reference": "fixture://budget-B",
  "information_visibility_policy": "IDENTICAL_MARKET_AND_REFERENCE_COMPLETED",
  "feedback_policy_reference": "fixture://matured-own-arm-v1",
  "model_configuration_reference": "fixture://model-B-v1",
  "deterministic_seed_reference": "fixture://seed-B-001",
  "frozen_configuration_reference": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Expected `arm_spec_fingerprint`: `84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831`.

### Arm R preimage

Same 17 fields as Arm B, with exactly these replacements:

```json
{
  "arm_id": "ARM-R",
  "selector_type": "DETERMINISTIC_COMPARATOR",
  "arm_account_role": "COMPARATOR",
  "research_budget_reference": "fixture://budget-R",
  "model_configuration_reference": "NONE",
  "deterministic_seed_reference": "fixture://seed-R-001"
}
```

Expected `arm_spec_fingerprint`: `c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd`.

### Campaign preimage

```json
{
  "schema_version": "drift-experiment/1-draft",
  "campaign_id": "CAMP-E1-SYNTH-001",
  "campaign_type": "SYNTHETIC_TEST",
  "study_protocol_revision": "fixture://methodology-v1",
  "created_at": "2026-10-19T00:00:00.000000Z",
  "frozen_at": "2026-10-19T00:00:01.000000Z",
  "accepted_contract_revisions": {},
  "research_question_id": "RQ-STAGE1-SELECTOR-NET-ADVANTAGE",
  "primary_comparison": {"test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R"},
  "control_arm_references": [],
  "arm_spec_references": [
    "84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831",
    "c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd"
  ],
  "qualified_dataset_references": [],
  "data_window": {"start_date": "2024-01-02", "end_date": "2026-01-30", "calendar_id": "fixture://calendar-v1"},
  "warmup_window": {"sessions_count": 253},
  "observation_window": {"sessions_count": 126},
  "scoring_window": {"start_session": "SC-001", "end_session": "SC-021", "fresh_accounts": true},
  "decision_schedule": {"frequency": "MONTHLY", "alignment": "LAST_COMPLETED_SESSION", "execution_timing": "NEXT_OPEN"},
  "allowed_strategy_families": ["B3", "B4", "B5"],
  "portfolio_mandate_reference": "fixture://balanced-mandate-v1",
  "source_eligibility_policy_reference": "fixture://source-policy-v1",
  "execution_policy_reference": "fixture://next-open-v1",
  "cost_policy_reference": "fixture://cost-policy-v1",
  "model_and_prompt_policy_reference": "fixture://model-B-v1",
  "learning_and_feedback_policy_reference": "fixture://feedback-policy-v1",
  "evaluation_policy_reference": "fixture://eval-policy-v1",
  "holdout_access_policy_reference": "fixture://holdout-policy-v1",
  "stopping_policy_reference": "fixture://stop-policy-v1",
  "authorization_evidence": {"synthetic_fixture_only": true, "reviewer_receipts": []}
}
```

Expected `campaign_spec_fingerprint`: `2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4`.

### Synthetic run bindings

Use `bound_at = 2026-10-19T00:00:02.000000Z` for both, `run_id = RUN-001`, `initial_cash_allocated = "10000"`, and `schema_version = "drift-experiment/1-draft"`.

- `ARM-B`: `portfolio_account_id = "SYNTH-ACC-B-001"`, `binding_id = "CAMP-E1-SYNTH-001:RUN-001:ARM-B:BINDING"`.
- `ARM-R`: `portfolio_account_id = "SYNTH-ACC-R-001"`, `binding_id = "CAMP-E1-SYNTH-001:RUN-001:ARM-R:BINDING"`.

The exact oracles were independently calculated from Drift's documented canonical JSON contract: UTF-8, lexically sorted mapping keys, preserved array order, separators `(",",":")`, `ensure_ascii=False`, `allow_nan=False` and SHA-256. **Implementation must recalculate with Drift's existing `content_hash` and not change the expected values if a mismatch occurs.** Adding `campaign_spec_fingerprint` or `arm_spec_fingerprint` to its own preimage changes the hash and is a bug.

## 10. Positive, negative and adversarial acceptance

Required focused tests in the authorized new unit test file:

1. Goldens: exact Arm B, Arm R, campaign SHA-256, field/array counts and two exact derived binding IDs. Use `expected_run_ids=("RUN-001",)` in collection and optional Stage 1 verification.
2. Same canonical hash with different object-map insertion order and equivalent UTC timezone offsets; same constructed bytes on replay; no wall-clock default.
3. Preserve declared array order, duplicate array elements inside opaque JSON, empty control/data/accepted revision collections. Reordered *hashed arrays* should create different legitimate fingerprints; reordered map keys should not.
4. Deep immutability: mutate caller-owned lists, dictionaries, nested map/array *after* building, verify frozen objects and fingerprints unchanged; frozen assignment fails; `dataclasses.replace` of hashed fields without new digest fails.
5. Corruption: mismatched/uppercase/wrong-length fingerprint, wrong schema, bad selector/currency, invalid seed/policy refs, bad or duplicated strategy/ref/member lists, tampered nested authorization object even with a newly forged matching digest when map ordering itself is noncanonical.
6. Reject malformed IDs containing `:`/whitespace, wrong derived binding ID, noncanonical/out-of-range/naive timestamps, created after frozen, binding earlier than frozen, invalid/descending Gregorian date strings, nonbool `fresh_accounts`, negative/boolean/nonint session counts.
7. Monetary refusal table: `10000.00`, `00`, `01`, `0.0`, `-0`, `+1`, `1e2`, `1.`, `.5`, ` 10000`, whitespace, float, bool, NaN, Infinity, nonpositive amounts. Valid: `10000`, `0.5`, `10000.5`.
8. Collection: swapped input arm order remains valid; absent arm, extra arm, unknown primary/control, duplicate arm/fingerprint, same account across arms, same account across two runs, duplicate binding ID/scope, wrong campaign/arm, mismatched initial cash and cross-run account reuse all fail closed. Manifest adversaries: empty/duplicate expected runs, missing declared RUN-002 binding, unexpected RUN-003 binding, missing one arm for RUN-002. Test that separate single-run verifications cannot prove *global* uniqueness: require combined expected-run snapshot.
9. Generic independence: valid alternative campaign with controls and non-B3 starting strategies remains structurally valid; optional Stage 1 profile rejects it if it does not match B/R requirements. All supplied active Stage 1 arms require USD 10,000: reject a `"1"` control arm even when its binding matches, **and** reject undeclared extra `ARM-X` despite a correct $10,000 binding. Reject a Stage 1 campaign with `allowed_strategy_families=("OTHER",)` lacking B3/B4/B5 even when both arms individually admit them. Reject Stage 1 `SAME_CLOSE` and wrong alignment. No **generic** $10k, B3, 253 or 126 defaults.
10. Scope boundaries: zero provider/broker/disk/system clock calls; hashes/refs alone are not authentic approvals, filled trades or qualified historical source. No imports of unmerged K0/K1-K5 or PR #455 code.

Exact refusal API: `ValueError` on every malformed/unsafe object or collection, including caller type confusion; `True` for valid verification. No automatic correction/rehashing of a mutated *persisted* object and no verifier that reports success by omitting invalid participants.

## 11. Delivery and review

Use the repository's required [implementation handoff standard](../implementation-handoff.md), [AGENTS.md](../../../AGENTS.md), and [agent workflow](../agent-workflow.md). A separate READY implementation issue reserves exactly the two code/test paths. Gemini executes the approved design and may challenge with exact file/line/test/contract evidence; it must not reinterpret undecided producer authority or change files outside its write-set. Run pinned CPython 3.14.6 focused and relevant Stage 1 tests, Ruff, mypy, build, full hosted CI, git whitespace/unauthorized-file checks and zero U+2014. One issue branch, one draft PR, actual SHA and checkpoint.

Architect independently reviews actual diff and tests, requests Codex review on exact HEAD and verifies its completion, fixes findings and rechecks final HEAD. Matthew's independent account/RESULT consumer review is required before claiming this shared scientific-to-platform binding semantics accepted. No auto merge without separately recorded exact-PR/HEAD merge authorization by Kanuj; no G3 or scored historical run from this code.

**Next scientific integration after E1:** #448/#455 event integrity, trial projection, producer admission/RESULT, research receipts, metric aggregation, E6 synthetic B/R, and only later source-qualified preregistered historical benchmarking.


## 12. Codex-reviewed architecture corrections (October 19, 2026)

Owner-approved Option A and E1-A through E1-E are preserved. The first exact-head Codex review of PR #461 reported three actionable design faults: [complete run universe](https://github.com/KanujVerma/drift/pull/461#discussion_r4317401516), [next-open timing](https://github.com/KanujVerma/drift/pull/461#discussion_r4317401526), and [all-arm capital](https://github.com/KanujVerma/drift/pull/461#discussion_r4317401534).

- **Run manifest:** E1 must not claim global cross-run account isolation if it only checked a selected subset. Every collection verifier requires an explicit complete expected-run ID manifest, rejects omitted/extra/duplicate runs, and checks all run-arm bindings and account IDs together. The guarantee is scoped to the supplied manifest, not unseen platform history. Actual manifest provenance remains Matthew's future work. Rejected a competing global mutable account registry.
- **Next eligible open:** The Stage 1 synthetic profile must require `decision_schedule.execution_timing == "NEXT_OPEN"` and fixed synthetic marker `decision_schedule.alignment == "LAST_COMPLETED_SESSION"`, in addition to monthly frequency. Neither token proves exchange-calendar eligibility; the simulator/source producer must do so later. Rejected `SAME_CLOSE` to prevent lookahead.
- **Equal initial accounts:** Every active Stage 1 control arm, not merely B/R, must have canonical `initial_capital == "10000"`, matching the owner's accepted primary scientific method. The generic models remain capital configurable. Rejected unequal cash controls in a supposedly matched study.

These changes are architect-owned verification obligations in the Kanuj scientific E1 workstream, not a revision of Krish/Matthew producer contracts, an approved scored study, or a real cash-account certification.

## 13. Follow-up Codex corrections: complete Stage 1 arm partition and campaign pool

The second exact-head Codex review at [PR #461](https://github.com/KanujVerma/drift/pull/461) identified two valid loopholes: [unclassified active arm](https://github.com/KanujVerma/drift/pull/461#discussion_r4317483078) and [campaign-level strategy exclusion](https://github.com/KanujVerma/drift/pull/461#discussion_r4317483089).

- **Complete active arm partition:** For the Stage 1 synthetic B/R protocol, all supplied arms must be either the two primary IDs or explicitly listed control IDs, with no extra arms omitted from both. Independently check canonical `"10000"` and USD on **every supplied arm**, not just declared controls. This makes the scientific comparison's population explicit rather than allowing an extra $1 account to escape matching rules.
- **Campaign-level allowed pool:** Require `{ "B3", "B4", "B5" }` to be contained within `set(campaign.allowed_strategy_families)` in the Stage 1 synthetic checker, not only each selector's private pool. Extra accepted control families are not prohibited. Without this condition a campaign fingerprint can formally exclude the very strategy menu it purports to test.

Do not impose these Stage 1-specific rules globally on generic E1 configurations. Do not alter previously computed golden fixture bytes or independently verified hashes, since the original synthetic campaign already meets the corrected constraints. Add negative tests for both loopholes and verify no accidental extra-account authorizations.
