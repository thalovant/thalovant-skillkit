"""`thalovant-skillkit check` compares a skill with the fleet on its own, and
knows the difference between a laptop that is offline and a CI job that
cannot reach the model."""
from __future__ import annotations

import json
from pathlib import Path

from thalovant_skillkit import cli, fleet


def _skill(root: Path, intents: bool) -> Path:
    package = root / "thalovant_skill_x"
    (package / "locale" / "en-US" / "dialog").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "locale" / "supported.json").write_text(json.dumps({"locales": ["en-US"]}))
    (package / "locale" / "en-US" / "dialog" / "hi.dialog").write_text("hi\n")
    if intents:
        (package / "locale" / "en-US" / "x.intent").write_text("water the garden\n")
    (root / "pyproject.toml").write_text('''
[project]
name = "thalovant-skill-x"
version = "0.0.1"
[project.entry-points."opm.skill"]
"thalovant-skill-x.thalovant" = "thalovant_skill_x:Skill"
[tool.setuptools.package-data]
thalovant_skill_x = ["locale/*.json", "locale/*/*", "locale/*/*/*"]
''')
    (package / "__init__.py").write_text("class Skill:\n    pass\n")
    return root


def _unavailable(model):
    raise fleet.ModelUnavailable(f"no {model} here")


def test_a_skill_without_intents_never_fetches_the_model(tmp_path: Path, monkeypatch, capsys):
    root = _skill(tmp_path, intents=False)
    monkeypatch.setattr(fleet, "resolve_model", lambda model: (_ for _ in ()).throw(AssertionError))
    assert cli.main(["check", str(root)]) == 0
    assert "keeps its contracts" in capsys.readouterr().out
    # ... and says as much when that is all it was asked to do
    assert cli.main(["check", "--fleet-only", str(root)]) == 0
    assert "publishes no intent files" in capsys.readouterr().out


def test_offline_is_a_skip_on_a_laptop_and_a_failure_in_ci(tmp_path: Path, monkeypatch, capsys):
    root = _skill(tmp_path, intents=True)
    monkeypatch.setattr(fleet, "resolve_model", _unavailable)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert cli.main(["check", str(root)]) == 0
    assert "fleet check skipped" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cli.main(["check", str(root)]) == 1
    assert "::error::fleet check did not run" in capsys.readouterr().out


def test_no_fleet_asks_nothing_of_the_network(tmp_path: Path, monkeypatch, capsys):
    root = _skill(tmp_path, intents=True)
    monkeypatch.setattr(fleet, "resolve_model", _unavailable)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cli.main(["check", "--no-fleet", str(root)]) == 0


def test_a_model_directory_with_an_index_fails_a_duplicate(tmp_path: Path, monkeypatch, capsys):
    from thalovant_skillkit.intents import sentence_key

    root = _skill(tmp_path / "skill", intents=True)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    key = sentence_key("en-US", "water the garden")
    (model_dir / "index.json").write_text(json.dumps(
        {"version": 1, "labels": {key: ["thalovant-skill-garden.thalovant:water"]}}))
    monkeypatch.setattr(fleet, "find_predicted", lambda *a, **k: [])
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert cli.main(["check", "--model", str(model_dir), str(root)]) == 1
    out = capsys.readouterr().out
    assert "x.intent:1" in out and "thalovant-skill-garden.thalovant's water" in out
    assert "1 sentence(s) this change claims already belong to another skill" in out
