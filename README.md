# Drift

Drift's goal is an autonomous, self-improving AI portfolio manager that makes
evidence-based investment decisions within a balanced, user-authorized mandate.
It combines fundamental, quantitative, and thesis-driven research, with
conversational interaction and bounded autonomy. Research and evaluation support
that product; they are not the product's final purpose.

**Current boundary:** This repository contains offline research proposal
validation, evidence, portfolio accounting, risk building blocks, and a
simulation-only supervised portfolio cycle (`python -m drift.manager`).
`python -m drift.prospective` provides the supervised prospective workflow described
in [docs/V02.md](docs/V02.md). `python -m drift.historical` replays the same
cycle on past prices without writing those books; see
[docs/HISTORICAL.md](docs/HISTORICAL.md). It does not include a broker adapter or order
dispatcher, and it does not establish an investing edge or connected-trading
readiness. Paper validation and a $100 live pilot require separate
authorization and controls.

## Find the right context

- [Product](docs/PRODUCT.md): approved direction and boundaries.
- [Architecture](docs/ARCHITECTURE.md): system shape, current capabilities,
  safety boundaries, and unresolved limitations.
- [Roadmap](docs/ROADMAP.md): next outcomes and validation stages.
- [Agent instructions](AGENTS.md): how contributors and agents work in this repo.

GitHub issues and pull requests track work and known gaps. Retired research,
tests, fixtures and technical documents remain in Git history.

## Development

The package requires Python 3.14 or newer. Development uses the exact version
in [`.python-version`](.python-version) and the committed `uv.lock`. Historical
replay requires its original revision, environment and inputs; it is not part
of the retained test suite. With [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
uv run python -m drift.manager --help
```

Choose verification proportionate to the change and report what actually ran.
The existing GitHub Actions workflow runs the applicable hosted checks; a
passing check is not source qualification or operational authorization.
