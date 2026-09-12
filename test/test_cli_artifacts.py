"""Artifact validation is an explicit offline command, separate from fleet checks."""
from __future__ import annotations

import pytest
from test_artifacts import package_files, source_tree, write_sdist, write_wheel

from thalovant_skillkit import cli, fleet


def test_cli_checks_built_resources_without_loading_the_fleet(tmp_path, monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("artifact checks must not fetch a fleet model")

    monkeypatch.setattr(fleet, "resolve_model", unexpected)
    package, files = source_tree(tmp_path)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", files)
    assert cli.main([
        "check-artifacts", str(tmp_path), "--wheel", str(wheel), "--sdist", str(sdist),
        "--package", str(package), "--source", "scripts", "--wheel-exclude", "*.mp3",
        "--wheel-count", "*.ogg=1", "--sdist-count", "*.mp3=1",
    ]) == 0
    assert "built artifacts match" in capsys.readouterr().out


def test_cli_reports_artifact_failures_without_a_traceback(tmp_path, capsys):
    source_tree(tmp_path)
    assert cli.main(["check-artifacts", str(tmp_path), "--wheel", "missing.whl"]) == 1
    assert "cannot validate wheel" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [[], ["--wheel", "x", "--wheel-count", "bad"],
                                       ["--sdist", "x", "--sdist-count", "*.mp3=-1"]])
def test_cli_rejects_missing_archives_and_invalid_counts(arguments):
    with pytest.raises(SystemExit) as failure:
        cli.main(["check-artifacts", *arguments])
    assert failure.value.code == 2
