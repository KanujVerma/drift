# Stage 1 Prospective Study Runbook (G5)

**Specification Version:** drift-stage1-prospective-runbook/1
**Scope:** Operational runbook for registering, executing, and stepping prospective study sessions under G5.
**Predecessor References:** [Stage 1 Study Execution Contract v1](stage1-study-execution-contract-v1.md), [G3 Protocol v1](stage1-g3-protocol-v1.md).

---

## 1. Safety Boundaries and Capability Refusal

The Stage 1 prospective evaluation protocol is strictly analytical. The execution orchestrator must assert and enforce the following invariant:

> **CAPABILITY INVARIANT:**
> `has_broker_dispatch_capability == False`

If any capability granting live broker interaction, automated order submission, capital transfer, or unauthorized runtime mutation is detected, prospective registration and execution must immediately abort with a non-zero exit code (Exit Code 2).

---

## 2. Prospective Study Lifecycle

```
[Draft Plan] -> [Readiness Assessment] -> [Study Freeze] -> [Registration] -> [504 Sequential Steps] -> [Final Evaluation]
```

### 2.1 Step 1: Pre-Registration Readiness Assessment
Before freezing, verify that:
1. Target plan `ProspectiveStudyPlanV1` specifies exactly 504 scheduled sessions.
2. Market admission evidence for the 12-instrument universe is verified against trusted roots.
3. Model binding is immutable (pinned commit/SHA, no "latest" tags).
4. Development calibration and historical baseline receipts are accepted.

CLI Invocation:
```sh
python scripts/stage1_study.py assess \
  --draft path/to/plan_draft.json \
  --host-config path/to/host_config.json \
  --output path/to/readiness_assessment.json
```

### 2.2 Step 2: Protocol Freeze & Registration
Once assessment passes with status `ACCEPTED`:
1. Generate canonical `FrozenProspectiveStudyV1` artifact.
2. Create `ProspectiveRegistrationV1` entry storing registration ID, timestamp, and frozen study hash.
3. Store registration artifact in durable private storage root.

CLI Invocation:
```sh
python scripts/stage1_study.py prospective-register \
  --plan path/to/prospective_plan.json \
  --host-config path/to/host_config.json \
  --private-root var/drift/prospective/
```

### 2.3 Step 3: Sequential Session Stepping
Prospective evaluation runs sequentially across 504 trading sessions:
- Sessions must execute in strictly increasing order (`session_index = 1` through `504`).
- Each step ingests market data for the admitted session.
- AI selector policy (Arm B) and deterministic comparator (Arm R) emit selection decisions.
- Step outcome is appended to the durable append-only log.

CLI Invocation:
```sh
python scripts/stage1_study.py prospective-step \
  --registration var/drift/prospective/REG-DRIFT-STAGE1-P504.json \
  --session-index 1 \
  --session-data path/to/session_1_data.json \
  --host-config path/to/host_config.json \
  --output var/drift/prospective/steps/step_001.json
```

---

## 3. Crash Recovery and Idempotency

- In the event of process interruption, the orchestrator inspects the latest completed step artifact in `var/drift/prospective/steps/`.
- If step `k` already has a verified receipt, repeating step `k` produces the identical hash-verified receipt (idempotent replay).
- Stepping non-consecutively (e.g. attempting step `k+2` when step `k` is the latest) fails closed with an error.

---

## 4. Final Evaluation & Report Generation

Upon completion of session 504:
1. Run paired uncertainty quantification over all 504 sessions.
2. Evaluate primary economic advantage against the $200 prospective materiality hurdle.
3. Emit `StudyReportArtifactV1` with canonical SHA-256 hash binding.
4. If economic advantage is non-positive or risk limits are breached, classify outcome as `UNSUCCESSFUL` (a valid negative research outcome).
