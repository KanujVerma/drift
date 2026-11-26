"""The installed foundation must not expose retired dispatch paths."""

from importlib import import_module
from pkgutil import walk_packages

import pytest

import drift


def test_all_installed_foundation_modules_import() -> None:
    for module in walk_packages(drift.__path__, drift.__name__ + "."):
        import_module(module.name)


@pytest.mark.parametrize(
    "module",
    (
        "drift.execution.router",
        "drift.adapters.robinhood.adapter",
        "drift.shadow.broker",
        "drift.canary.orchestrator",
        "drift.agent.gemini_agent",
    ),
)
def test_no_dispatch_or_provider_module(module: str) -> None:
    with pytest.raises(ModuleNotFoundError) as error:
        import_module(module)
    assert error.value.name is not None
    assert module == error.value.name or module.startswith(error.value.name + ".")
