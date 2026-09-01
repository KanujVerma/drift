from importlib.metadata import version

import drift


def test_package_exposes_its_installed_version() -> None:
    assert drift.__version__ == version("drift")
