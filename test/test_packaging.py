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
