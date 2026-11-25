# Drift

Drift's goal is an autonomous, self-improving AI portfolio manager that makes
evidence-based investment decisions within a balanced, user-authorized mandate.
It combines fundamental, quantitative, and thesis-driven research, with
conversational interaction and bounded autonomy. Research and evaluation support
that product; they are not the product's final purpose.

**Current boundary:** This repository contains research, evaluation, risk,
execution, and offline Robinhood-adapter components. Those components do not
establish a complete autonomous portfolio manager, a proven investing edge, an
authenticated broker connection, or permission to trade. Paper validation is a
future milestone; a $100 live pilot requires separate authorization.

## Find the right context

- [Product](docs/PRODUCT.md): approved direction and boundaries.
- [Architecture](docs/ARCHITECTURE.md): system shape, current capabilities,
  safety boundaries, and unresolved limitations.
- [Roadmap](docs/ROADMAP.md): next outcomes and validation stages.
- [Agent instructions](AGENTS.md): how contributors and agents work in this repo.

GitHub issues and pull requests track work and known gaps. Earlier research
designs and rationale remain under [historical technical docs](docs/architecture/adaptive-experiments/README.md);
read them when relevant, not as a mandatory onboarding sequence.

## Development

The package requires Python 3.14 or newer. The development and replay
environment uses the exact version in [`.python-version`](.python-version) and
the committed `uv.lock`. Do not regenerate pinned replay fixtures to hide a
failure. With [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

Choose verification proportionate to the change and report what actually ran.
The existing GitHub Actions workflow runs the applicable hosted checks; a
passing check is not source qualification or operational authorization.