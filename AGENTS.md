# Drift repository policy

This file is the authoritative repository-specific policy for Drift. M0 is a
local research evidence kernel. Preserve its narrow scope unless an approved
milestone explicitly changes it.

## M0 safety boundaries

M0 must not add or configure:

- broker integrations, broker credentials, order placement, trading, portfolio
  management, or production execution;
- market-data clients, network clients, URLs, OAuth, MCP, language-model,
  agent, or orchestration capability;
- backtesting or executable strategy behavior;
- production settings, production credentials, deployment configuration, or
  environment-driven credential loading.

Metadata names such as `StrategyArtifact` and `StrategyReference` are allowed
only as immutable research provenance. They must not grow execution behavior.

## Evidence kernel rules

- Keep domain models frozen, strict, and deterministic.
- Canonicalize data before hashing. Reject ambiguous or unsupported values.
- Use the database-assigned sequence for order. Timestamps are evidence, not
  the sole ordering mechanism.
- Append events and their checkpoints transactionally. Preserve database
  update/delete triggers for both tables.
- Verify events and checkpoints from one snapshot, then replay that exact
  verified snapshot.
- Reject noncanonical raw database storage, even when it parses to an
  equivalent logical object.
- Never use future data in research evaluation. Dataset and experiment access
  must preserve explicit point-in-time semantics, including what information
  was actually available at each observation time.
- Describe the ledger accurately as tamper-evident, not tamper-proof against a
  privileged coordinated rewrite.

## Provenance and retention

Compact provenance is retained immutably: research objects, hashes, parameters,
metrics, dataset references, evidence lineage, failures, and future promotion
history. Large artifacts may have an explicit future expiry policy. M0 records
only their references and hashes and does not manage their lifecycle.

## Working rules

- Keep dependencies minimal. Pydantic is the only runtime dependency; SQLite
  and command-line handling use the Python standard library.
- Prefer small public contracts and direct implementations over framework
  abstractions.
- Do not add hidden timestamps, implicit mutable state, environment loading, or
  network side effects.
- Use `uv run python scripts/init_local_db.py [path]` and
  `uv run python scripts/verify_ledger.py [path]` for installed script
  invocation. Do not document source-checkout shebang execution as supported.
- Before a material change is complete, run:

  ```text
  uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src tests
  uv build
  ```

- Inspect all forbidden-capability search matches. A matching metadata name is
  not itself a capability, but it must be reviewed rather than ignored.
