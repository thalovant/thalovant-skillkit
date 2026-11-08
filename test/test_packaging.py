"""The package metadata, which the runtime installs by version.

The runtime bakes a versioned wheel into its wheelhouse and skills pin
`thalovant-skillkit==<version>`, so a version in one file and not the other
means a skill pins something that was never built.
"""
from __future__ import annotations

import re
from pathlib import Path

import thalovant_skillkit


def test_the_declared_version_matches_the_package():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)

    assert declared, "pyproject.toml has no version"
    assert declared.group(1) == thalovant_skillkit.__version__


def test_everything_named_in_all_can_actually_be_imported():
    for name in thalovant_skillkit.__all__:
        assert hasattr(thalovant_skillkit, name), name


def test_the_documented_install_pins_the_version_this_is():
    """The README's Quickstart and the reference's testing install pin a version. 0.31.2 and
    0.32.0 shipped with both still at 0.31.1, so a reader copying them got the kit that runs Lua
    on Redis. (CodeRabbit on #22 found the same, at 0.14.0.)"""
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    reference = (root / "docs" / "reference.md").read_text(encoding="utf-8")
    version = re.escape(thalovant_skillkit.__version__)

    assert re.search(rf'pip install --pre "thalovant-skillkit=={version}"', readme)
    assert re.search(rf"This example pins SkillKit {version}\.", readme)
    assert re.search(rf'"thalovant-skillkit\[testing\]=={version}"', reference)
    pins = re.findall(r"thalovant-skillkit(?:\[[a-z]+\])?==([0-9][^\"\s]*)", readme + reference)
    assert pins and set(pins) == {thalovant_skillkit.__version__}, pins
