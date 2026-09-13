"""A new project must pass the same tests its author is told to run."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from thalovant_skillkit import cli


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Generated projects require Python 3.11+")
@pytest.mark.parametrize("name", ["garden-watering", "quelle-heure", "window", "travaux"])
def test_new_skill_passes_its_own_tests(tmp_path, name):
    # Include a name with a question word, and keywords present in the sample
    # chatter. Generated examples must work with both kinds of names.
    project = tmp_path / f"thalovant-skill-{name}"
    assert cli.main(["new", name, "--directory", str(project)]) == 0
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
