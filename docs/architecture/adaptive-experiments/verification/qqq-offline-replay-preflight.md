# QQQ offline replay evidence preflight (Issue #536)

**Status: bounded implementation candidate, focused verification passed; integration blocked.**
This is not a source license, historical data qualification, complete experiment or trading authorization.

## Background, accountable owner and preserved implementation

Matthew owns the historical exploratory platform work under [#409](https://github.com/KanujVerma/drift/issues/409). The original assigned Gemini work was **already merged** in [PR #410](https://github.com/KanujVerma/drift/pull/410), merge commit `5583f112dfb45b8f6e8bc652de1cc4334ef8a247`. The original benchmark and four claimed source/test paths are retained untouched. Its issue can be reconciled separately; an old in-progress label does not imply that merged code still needs replacing.

Under the user's request for another batch of exactly two unworked Matthew-area coding tasks, GPT-6 using authenticated `Krish-Verma` owns only this new, disjoint offline evidence-review checker. Matthew remains accountable for real data/source and benchmark semantics. The paired task is [#537](https://github.com/KanujVerma/drift/issues/537), a separate forward-readiness helper.

Read [AGENTS.md](../../../../AGENTS.md), the [agent workflow](../../agent-workflow.md), [accepted decisions](../decisions.md), original [benchmark runner](../../../../scripts/benchmark_qqq_historical.py), [Alpaca exploratory adapter](../../../../src/drift/adapters/alpaca_exploratory.py), [source qualification requirements #378](https://github.com/KanujVerma/drift/issues/378) and [M1e rights](../../../../src/drift/domain/rights.py). This checker does not replace those actual implementation/permission gates.

## Exactly three added paths

- `scripts/qqq_offline_replay_preflight.py`: bounded pure in-memory check of supplied original-byte candidates and their caller-provided metadata.
- `tests/unit/test_qqq_offline_replay_preflight.py`: standalone synthetic positive and adversarial fixtures.
- `docs/architecture/adaptive-experiments/verification/qqq-offline-replay-preflight.md`: this documentation and future AntiGravity test contract.

No edits to the merged QQQ benchmark, `src/drift`, private retained source files, original four #409 paths, historical fixtures, source grades, credentials, broker, runtime permissions, `.python-version`, `uv.lock`, or another writer's documents.

## In-memory input and return contract

`preflight_qqq_offline_replay(payloads: object, manifest: object) -> QQQReplayPreflight` does not open a file, access the network, inspect environment variables, fetch historical data, or create/save receipts. Callers provide a concrete plain dictionary with three **in-memory bytes** payloads and exact concrete string keys `bars.json`, `calendar.json`, `corporate-actions.json`, each bounded here to two million bytes solely as a defensive fixture limit. Filename subclasses and other key types refuse before set comparisons or payload lookups can invoke caller-defined hashing or equality. The maximum is not an Alpaca API or experimental completeness threshold.

The provisional `synthetic-qqq-replay-review-v1` metadata is a closed plain JSON-shaped map with:

- `window`: fixture label, `QQQ`, inclusive start/end date.
- `acquisition`: start and finish in strict UTC `...Z` and explicit `UNKNOWN`, `RESTRICTED` or `CLAIMED_ALLOWED` rights *assertion*.
- `timezone`: `America/New_York`, declared tzdb release, retained TZIF hash/ref; the actual tzif bytes/release are **not verified** here.
- `objects`: one entry per native file, each providing SHA-256, origin receipt ref, claimed measured-request boolean, original first-received UTC, host, route, exact request parameters, and closed pagination assertion.

The three expected endpoint declarations come from the merged [Alpaca adapter](../../../../src/drift/adapters/alpaca_exploratory.py) and [QQQ benchmark runner](../../../../scripts/benchmark_qqq_historical.py), **as implemented on the inspected main source**:

| Native payload | Endpoint host / route | Required declared request |
| --- | --- | --- |
| `bars.json` | `data.alpaca.markets /v2/stocks/bars` | `symbols=QQQ`, `feed=sip`, `adjustment=raw`, `timeframe=1Day`, `limit=10000`, exact window start/end |
| `calendar.json` | `paper-api.alpaca.markets /v2/calendar` | Exact window start/end, not a live brokerage host |
| `corporate-actions.json` | `data.alpaca.markets /v1/corporate-actions` | `symbols=QQQ`, exact window start/end, exact sorted 16-name action-type filter from the current adapter |

Changing the historical benchmark's request contract requires Matthew's real producer approval and an updated review of this auxiliary preflight; the repeated values are *pinned review expectations*, not a replacement implementation. This code makes **no GET requests** and does not use provider credentials, even for the paper calendar endpoint.

For each actual supplied byte string, the script calculates SHA-256 and compares it with the caller-supplied expected digest. It decodes strictly as UTF-8 before JSON parsing, rejects the non-JSON constants `NaN`, `Infinity` and `-Infinity`, and rejects duplicate object keys instead of allowing last-wins ambiguity. UTF-16/UTF-32 bodies and malformed UTF-8 refuse even when their supplied byte digests match. Valid native UTF-8 bytes retain their original digest binding. Bars and corporate action payloads cannot contain a non-null `next_page_token`. A declared pagination state other than `NO_MORE_PAGES` refuses. All three input files, exact hosts/routes/params, original request observations and source scope are required; missing data never defaults to a zero-event response or complete history. First-received times must fall within the declared acquisition interval, but caller claims are never independently authenticated.

The output `QQQReplayPreflight` contains `structurally_reviewable`, `exact_byte_digest_matches`, `sources_with_claimed_origin`, and stable diagnostic `reasons`. If any dimension is structurally inconsistent, the two positive lists are withheld rather than implying partial authorization. The two properties `proves_entitlement_or_historical_origin` and `authorizes_data_access_or_trading` are permanently **False**.

## Scientific and provenance limitations

Digest equality can confirm that *provided bytes* agree with the given digest. It cannot prove bytes were really delivered by Alpaca at the claimed time, that the measured request/entitlement was available, that the provider's pages cover all relevant history, or that the license permits retrospective/saved usage. `rights_state=CLAIMED_ALLOWED` is an untrusted input, not an access grant. A filename, receipt/ref string or URL is not an origin signature.

Calendar dates here are scheduled session evidence, **not realized opening/halt evidence**. Corporate-actions data are terms/snapshots, not delivered settlement. Alpaca-derived bar inputs have previously recorded exploratory limitations in the existing M1e adapter; this checker does not turn them into realized bid/ask, fills or a pristine holdout. Timezone metadata require independent TZIF byte validation and the current runner's `ZoneInfo.from_file` behavior. Historical 2021 publication is not equivalent to proof that the information was available at a real 2021 decision cutoff. There is no exact-day historical data quality certification, profit assertion or scored trading experiment in this PR.

The original offline runner still owns file-path restrictions and private origin evidence. This helper never reads a path and therefore cannot validate symlinks, custody, source-term entitlement, external signatures, OS timezone inventory or durable storage. Those require the original qualified reviewer and separately authorized private evidence. Do not copy native data or secrets into GitHub.

## Verification checkpoint and independent handoff

The [2026-10-23 exclusive continuation claim](https://github.com/KanujVerma/drift/issues/536#issuecomment-6369512646) records the user's current instruction to perform necessary tests, superseding the earlier authoring-session deferral. It preserves Matthew's producer ownership and this exact three-file scope. The repair addresses both parser findings and formatting in [Matthew's formal review](https://github.com/KanujVerma/drift/pull/538#pullrequestreview-5605192363).

Actual local results with pinned CPython 3.14.6 and unchanged `uv.lock`:

- RED before the source repair: 39 failed, 28 passed. Filename spoofing/callbacks, matching-name subclasses, non-JSON constants, and UTF-16/UTF-32 inputs reproduced the reviewed defects.
- GREEN after the repair: 67 focused tests passed. Refusals withhold both positive lists and retain both no-authority properties; hostile filename hash/equality callbacks are never executed. Valid UTF-8 scalar and Unicode controls preserve all three digest/origin lists and identical replay results.
- Whole-repository Ruff lint passed; the locked Ruff format check passed on 564 files. Strict mypy passed on 472 source files. Source distribution and wheel built successfully.
- Git whitespace and nine local Markdown-link checks passed. AST comparison preserved all original fixture/test functions and all source semantics outside the two intended parser changes; Python pins, lockfile, package metadata and shared guard bytes remain unchanged.
- One focused inventory probe failed at `tests/integration/test_m1e_compatibility.py:976`, solely because `scripts/qqq_offline_replay_preflight.py` is absent from `INERT_SOURCE_PATHS`. The shared guard remains unchanged. Read-only inspection also shows that its ordinary definition-name rule rejects the existing constant-False `authorizes_data_access_or_trading` property. Adding the inventory path alone cannot resolve that rule.

Exact-path inventory and positive AST admission require a separately scoped producer decision and implementation. [#553](https://github.com/KanujVerma/drift/issues/553) concerns three other scripts; it does not admit this path. Preserve unknown-path negatives, source pins, and the separate #502 -> #487 / #394 gates. The full pytest suite was not rerun against this known inventory failure. Fresh canonical CI and independent acceptance remain pending; focused success does not qualify integration or source rights.

On the exact PR HEAD, inspect these three changed files, the original #409 PR #410 source, current source/rights/metadata contracts and scope restrictions. Then run:

```bash
uv run python -m pytest tests/unit/test_qqq_offline_replay_preflight.py -q
uv run ruff check scripts/qqq_offline_replay_preflight.py tests/unit/test_qqq_offline_replay_preflight.py
uv run ruff format --check scripts/qqq_offline_replay_preflight.py tests/unit/test_qqq_offline_replay_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Review the canonical [agent workflow](../../agent-workflow.md), ensure exactly the three reserved paths changed, confirm `uv.lock` and Python pins remain identical, review no U+2014/secret material, and independently verify the expected refusal diagnostics. Run the full pytest gate after the exact guard integration is accepted and composed; existing automatic CI remains enabled. No provider calls or native/private replay were performed. GitHub Actions outcomes do not replace independent AntiGravity acceptance.

The committed synthetic test fixtures cover: a complete but **unauthenticated** three-source bundle; unknown versus claimed rights; omission of any required file; changed bytes or digest; date-range/request mismatch; SIP/raw/day/limit constraint; calendar host mix-up; incomplete 16-name action filter; first receipt outside acquisition; unmeasured original request; missing origin ref; incomplete pagination in metadata/native response; repeated native JSON keys; wrong calendar shape; missing timezone evidence; wrong live host; unknown fields; filename subclasses and hostile equality/hash callbacks; non-JSON constants; UTF-16/UTF-32 and malformed UTF-8; and valid UTF-8 replay with exact digest matches. Antigravity should further review boundary sizes and source parser behavior, and report any actual defects. No one may advertise successful financial performance based on these synthetic values.

## Next legitimate action

The publishing integrator records the exact candidate head, obtains the separately scoped guard admission, and queues canonical CI on the composed source. Matthew independently reviews the repaired helper, reconciles #409's old merged implementation status separately, validates real replay source and provider rights under the accepted M1e contract, and decides whether this bounded helper is useful for independent audit. AntiGravity acceptance remains separate. The draft PR remains unmerged; no entitlement, broker data request, operational activation, original-issue closure or new scientific outcome is approved by this helper.
