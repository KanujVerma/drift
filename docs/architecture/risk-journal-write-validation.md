# Validate risk verdicts before immutable writes

Issue [#643](https://github.com/KanujVerma/drift/issues/643) closes a storage-boundary
defect in `PersistentRiskJournal.record_verdict`. At main
`60d572a339835a8ec8d9bb0ab8c7fd4383daeb33`, a `RiskVerdictV1.model_construct`
instance with an invalid verdict hash can be committed to the append-only table.
The normal `get_verdict_for_order` read then raises `ValidationError`. The supported
`model_copy` path already validates; unsafe construction is the reproducer.

Before opening a write transaction, the journal now validates the exact canonical
JSON payload with the existing `RiskVerdictV1.model_validate_json` rules. Indexed
columns come from the validated representation. The original valid payload bytes
are retained without reserialization or hash repair. Invalid input executes no
SQL and reserves neither order identity nor verdict hash, so a subsequent valid
write for that order remains possible. Prior verdicts and kill-switch events are
unchanged.

This mirrors the bounded execution-journal correction in
[#638](https://github.com/KanujVerma/drift/pull/638). It adds no schema, policy,
dependency, fixture or historical-row migration. Existing duplicate constraints
and append-only triggers remain active. It does not authenticate a producer:
a structurally valid verdict is not proof of legitimate issuance. Direct SQL
bypass, already-corrupt rows, approval-input freshness and operational trading
permission remain separate concerns.

The regression suite produced 11 behavioral failures and four passing controls
on unchanged main. It covers invalid hashes and changed identities/times,
unsupported versions, status/reason inconsistencies, hash-consistent structural
defects, no SQL or database changes on refusal, preserved prior/latch evidence,
valid identity retry, all three verdict statuses, exact payload/index retention,
duplicates, append-only triggers and journal reopening. The deliberately invalid
enum case emits an expected Pydantic serializer warning before validation refuses
the write.

```text
uv run --locked pytest tests/unit/test_risk_journal_write_validation.py
```

The issue and PR record relevant consumer checks, lint/type/build evidence and
the full hosted canonical CI result for the exact published head.
