"""The checks every skill's CI runs, tested against a skill built on the fly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from thalovant_skillkit.checks import (
    check_all,
    check_entry_point,
    check_fallback_priority,
    check_locale_contract,
    check_package_data,
)


@pytest.fixture
def skill(tmp_path: Path) -> Path:
    """A correct skill. Each test then breaks one thing."""
    root = tmp_path / "thalovant-skill-demo"
    pkg = root / "thalovant_skill_demo"
    for lang in ("en-US", "fr-FR", "de-DE"):
        (pkg / "locale" / lang / "dialog").mkdir(parents=True)
        (pkg / "locale" / lang / "intents").mkdir(parents=True)
        (pkg / "locale" / lang / "dialog" / "hello.dialog").write_text(
            "Hello {who}\n", encoding="utf-8")
        (pkg / "locale" / lang / "intents" / "hello.intent").write_text(
            "hello {who}\nhi {who}\n", encoding="utf-8")
        (pkg / "locale" / lang / "skill.json").write_text(
            json.dumps({"skill_id": "thalovant-skill-demo", "name": "Demo"}), encoding="utf-8")
    (pkg / "locale" / "supported.json").write_text(
        json.dumps({"locales": ["en-US", "fr-FR", "de-DE"]}), encoding="utf-8")
    (pkg / "__init__.py").write_text(
        "FALLBACK_PRIORITY = 96\n\nclass DemoSkill:\n    pass\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "thalovant-skill-demo"\nversion = "0.1.0"\n\n'
        '[project.entry-points."opm.skill"]\n'
        '"thalovant-skill-demo.thalovant" = "thalovant_skill_demo:DemoSkill"\n\n'
        '[project.entry-points."ovos.performance.metrics"]\n'
        'demo = "thalovant_skill_demo._metrics:histograms"\n\n'
        '[tool.setuptools.package-data]\nthalovant_skill_demo = ["locale/*/*/*"]\n',
        encoding="utf-8")
    return root


def test_a_correct_skill_has_no_problems(skill):
    assert check_all(skill) == []


def test_a_locale_missing_a_file_is_named(skill):
    (skill / "thalovant_skill_demo/locale/de-DE/dialog/hello.dialog").unlink()

    problems = check_locale_contract(skill)

    assert problems == ["locale/de-DE/dialog/hello.dialog is missing (en-US has it)"]


def test_a_dropped_placeholder_is_named_with_what_is_missing(skill):
    (skill / "thalovant_skill_demo/locale/de-DE/dialog/hello.dialog").write_text(
        "Hallo\n", encoding="utf-8")

    problems = check_locale_contract(skill)

    assert len(problems) == 1
    assert "de-DE/dialog/hello.dialog" in problems[0] and "missing ['{who}']" in problems[0]


def test_french_may_reorder_or_drop_placeholders(skill):
    """Every vendored copy of this check exempted fr-FR; adopting the shared
    one must not start failing skills that were passing."""
    (skill / "thalovant_skill_demo/locale/fr-FR/dialog/hello.dialog").write_text(
        "Bonjour\n", encoding="utf-8")

    assert check_locale_contract(skill) == []


def test_a_translation_may_offer_fewer_variants_but_not_lose_a_placeholder(skill):
    """English offers two variant lines and most translations write one, so
    a placeholder may appear fewer times. It may not disappear, and a new one
    may not be invented -- that raises KeyError mid-reply."""
    for relative in ("intents/hello.intent", "dialog/hello.dialog"):
        path = skill / "thalovant_skill_demo/locale/de-DE" / relative
        (skill / "thalovant_skill_demo/locale/en-US" / relative).write_text(
            "Hello {who}\nHi there {who}\n", encoding="utf-8")   # two variants
        path.write_text("Hallo {who}\n", encoding="utf-8")         # one, complete
        assert check_locale_contract(skill) == [], relative

        path.write_text("Hallo\n", encoding="utf-8")               # placeholder gone
        assert len(check_locale_contract(skill)) == 1, relative

        path.write_text("Hallo {who} um {when}\n", encoding="utf-8")   # invented
        assert "unexpected ['{when}']" in check_locale_contract(skill)[0], relative
        path.write_text("Hallo {who}\n", encoding="utf-8")


def test_a_supported_locale_without_a_directory_is_named(skill):
    (skill / "thalovant_skill_demo/locale/supported.json").write_text(
        json.dumps({"locales": ["en-US", "fr-FR", "de-DE", "es-ES"]}), encoding="utf-8")

    assert check_locale_contract(skill) == [
        "locale/es-ES is listed in supported.json but has no directory"]


def test_a_regex_that_does_not_compile_is_named_with_its_line(skill):
    for lang in ("en-US", "fr-FR", "de-DE"):
        (skill / f"thalovant_skill_demo/locale/{lang}/regex").mkdir()
        (skill / f"thalovant_skill_demo/locale/{lang}/regex/x.rx").write_text(
            "ok\n", encoding="utf-8")
    (skill / "thalovant_skill_demo/locale/de-DE/regex/x.rx").write_text(
        "# comment\nok\n(unclosed\n", encoding="utf-8")

    problems = check_locale_contract(skill)

    assert len(problems) == 1 and "de-DE/regex/x.rx:3" in problems[0]


def test_package_metadata_must_not_differ_between_locales(skill):
    (skill / "thalovant_skill_demo/locale/de-DE/skill.json").write_text(
        json.dumps({"skill_id": "something-else", "name": "Demo"}), encoding="utf-8")

    assert check_locale_contract(skill) == [
        "locale/de-DE/skill.json: skill_id differs from en-US but is not a translatable field"]


def test_a_priority_outside_the_band_is_refused(skill):
    (skill / "thalovant_skill_demo/__init__.py").write_text(
        "FALLBACK_PRIORITY = 50\nclass DemoSkill: pass\n", encoding="utf-8")

    assert len(check_fallback_priority(skill)) == 1


def test_an_entry_point_naming_a_missing_class_is_caught(skill):
    (skill / "thalovant_skill_demo/__init__.py").write_text(
        "class Renamed:\n    pass\n", encoding="utf-8")

    problems = check_entry_point(skill)

    assert len(problems) == 1 and "'DemoSkill'" in problems[0]


def test_a_metrics_hook_is_not_mistaken_for_the_skill(skill):
    """A skill may register other entry points; only the skill groups count."""
    assert check_entry_point(skill) == []


def test_the_fleets_setup_py_shape_is_understood(skill):
    (skill / "pyproject.toml").unlink()
    (skill / "setup.py").write_text(
        'SKILL_CLAZZ = "DemoSkill"\nPYPI_NAME = "thalovant-skill-demo"\n'
        'SKILL_PKG = "thalovant_skill_demo"\nSKILL_AUTHOR = "thalovant"\n'
        'SKILL_NAME = "thalovant-skill-demo"\n'
        'def find_resource_files(): ...\n', encoding="utf-8")

    assert check_entry_point(skill) == []
    assert check_package_data(skill) == []


def test_a_locale_tree_left_out_of_the_wheel_is_caught(skill):
    (skill / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.entry-points."opm.skill"]\n'
        'a = "thalovant_skill_demo:DemoSkill"\n', encoding="utf-8")

    problems = check_package_data(skill)

    assert len(problems) == 1 and "package_data" in problems[0]
