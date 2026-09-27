"""`thalovant-skillkit check` holds every `.ssml` twin to its dialog.

Each test copies the example skill, breaks one thing, and reads the one
problem the check reports for it. The rule runs under `check --fleet-only`
too, since that is the gate every skill's CI runs against the newest kit.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from thalovant_skillkit import cli, fleet
from thalovant_skillkit.checks import check_all, check_locale_contract, check_ssml
from thalovant_skillkit.regions import sync_regions

FIXTURE = Path(__file__).parent / "fixtures" / "thalovant-skill-punchline"
PLAIN = "Why did the scarecrow win an award? Because he was outstanding in his field."


@pytest.fixture
def skill(tmp_path) -> Path:
    root = tmp_path / "thalovant-skill-punchline"
    shutil.copytree(FIXTURE, root)
    return root


def _dialogs(root: Path, lang: str = "en-US") -> Path:
    return root / "thalovant_skill_punchline" / "locale" / lang / "dialog"


def _twin(root: Path, *lines: str, name: str = "joke.ssml", lang: str = "en-US") -> None:
    (_dialogs(root, lang) / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _one_problem(root: Path) -> str:
    problems = check_ssml(root)
    assert len(problems) == 1, problems
    return problems[0]


SECOND = ('I told my wifi a joke about routers. <break time="700ms"/> '
          "It did not get the connection.")


def test_a_skill_with_twins_and_without_passes(skill):
    """The example skill: a twin in English only, and plain dialogs elsewhere."""
    assert check_ssml(skill) == []
    assert check_all(skill) == []


def test_a_twin_is_optional_in_every_other_locale(skill):
    """English's twin does not make French "missing" a file, and French may
    have a twin English lacks."""
    _twin(skill, "Votre code est <say-as interpret-as=\"characters\">{code}</say-as>.",
          name="code.ssml", lang="fr-FR")

    assert check_locale_contract(skill) == []
    assert check_ssml(skill) == []


@pytest.mark.parametrize("line, expected", [
    ('Why did the scarecrow win an award? <break time="1 minute"/> Because he was '
     "outstanding in his field.", "needs a unit"),
    ('<prosody pitch="high">Why</prosody> did the scarecrow win an award? Because he was '
     "outstanding in his field.", "pitch"),
    ('<audio src="drum.wav"/> Why did the scarecrow win an award? Because he was outstanding '
     "in his field.", "<audio> is not rendered"),
    ("Why did the scarecrow win an award? <s>Because he was outstanding in his field.",
     "not well-formed"),
    ("Why did the scarecrow win an award? Because he was out & standing in his field.",
     "not well-formed"),
    ("Why did the scarecrow win an award? <break/> Because he was great in his field.",
     "same words"),
    ("Why did the scarecrow win an award? <break/> Because he was {how} in his field.",
     "placeholders differ"),
    ("(Why|How) did the scarecrow win an award? Because he was outstanding in his field.",
     "cannot be paired"),
])
def test_each_rule_names_the_line_and_the_problem(skill, line, expected):
    _twin(skill, "# a comment line does not count", line, SECOND)

    problem = _one_problem(skill)

    assert problem.startswith("locale/en-US/dialog/joke.ssml:2: "), problem
    assert expected in problem


def test_a_substitution_may_say_either_form(skill):
    """`<sub>` shows one form and says another; the plain line may use either."""
    _twin(skill, 'Why did the scarecrow win an <sub alias="prize">award</sub>? Because he was '
          "outstanding in his field.", SECOND)
    assert check_ssml(skill) == []

    (_dialogs(skill) / "joke.dialog").write_text(
        PLAIN.replace("award", "prize") + "\n"
        + "I told my wifi a joke about routers. It did not get the connection.\n")
    assert check_ssml(skill) == []


def test_line_counts_must_match(skill):
    _twin(skill, SECOND)

    assert "has 1 line(s) and joke.dialog has 2" in _one_problem(skill)


def test_a_twin_needs_its_plain_dialog(skill):
    _twin(skill, "Hi <break/> there.", name="orphan.ssml")

    assert "has no orphan.dialog beside it" in _one_problem(skill)


def test_a_plain_dialog_never_holds_markup(skill):
    """It is what the Android app shows and says as written."""
    (_dialogs(skill, "fr-FR") / "greeting.dialog").write_text("Bonjour <break/> {name}.\n")

    problem = _one_problem(skill)

    assert problem.startswith("locale/fr-FR/dialog/greeting.dialog:1 holds SSML markup")
    assert "greeting.ssml" in problem


def test_a_twin_named_like_a_dialog_is_pointed_at_the_right_name(skill):
    """OVOS loads `joke.ssml.dialog` as a dialog of its own and raises on it."""
    _twin(skill, SECOND, SECOND, name="joke.ssml.dialog")

    problems = check_ssml(skill)

    assert problems and all("name the twin joke.ssml" in p for p in problems)


def test_a_less_than_sign_in_a_plain_dialog_is_not_markup(skill):
    (_dialogs(skill) / "greeting.dialog").write_text("Hello {name} <3 & welcome.\n")

    assert check_ssml(skill) == []


def test_fleet_only_runs_the_markup_check_and_fails_on_it(skill, monkeypatch, capsys):
    """The one kit gate every skill's CI runs; a skill with no intents too."""
    monkeypatch.setattr(fleet, "resolve_model",
                        lambda model: (_ for _ in ()).throw(AssertionError("no model")))
    assert cli.main(["check", "--fleet-only", str(skill)]) == 0
    assert "problem" not in capsys.readouterr().out

    _twin(skill, SECOND)
    assert cli.main(["check", "--fleet-only", str(skill)]) == 1
    out = capsys.readouterr().out
    assert "1 problem(s)" in out and "joke.ssml has 1 line(s)" in out
    assert cli.main(["check", str(skill)]) == 1


def test_a_region_that_rewords_a_dialog_does_not_borrow_its_markup(skill):
    """fr-CA rewording joke.dialog must not ship fr-FR's twin for the old words."""
    locale = skill / "thalovant_skill_punchline" / "locale"
    french = ("Pourquoi l'épouvantail a-t-il gagné un prix ? "
              "Parce qu'il était le meilleur dans son domaine.")
    _twin(skill, french.replace(" ? ", ' ? <break time="700ms"/> '),
          "J'ai raconté une blague au routeur. Il n'a pas capté.", lang="fr-FR")
    (locale / "regional.json").write_text(json.dumps({"version": 1, "locales": {
        "fr-CA": {"source": "fr-FR", "overrides": {
            "dialog/code.dialog": "Ton code est {code}.\n",
        }},
        "fr-BE": {"source": "fr-FR", "overrides": {
            "dialog/joke.dialog": "Une blague belge.\nUne autre.\n",
        }},
    }}))

    assert sync_regions(locale, write=True) == []

    assert (locale / "fr-CA/dialog/joke.ssml").is_file()
    assert not (locale / "fr-BE/dialog/joke.ssml").exists()
    assert check_all(skill) == []


def test_a_regional_twin_may_change_its_markup_but_not_its_placeholders(skill):
    locale = skill / "thalovant_skill_punchline" / "locale"
    _twin(skill, 'Votre code est <say-as interpret-as="characters">{code}</say-as>.',
          name="code.ssml", lang="fr-FR")

    def region(twin: str) -> list[str]:
        (locale / "regional.json").write_text(json.dumps({"version": 1, "locales": {
            "fr-CA": {"source": "fr-FR", "overrides": {
                "dialog/code.dialog": "Ton code est {code}.\n", "dialog/code.ssml": twin,
            }},
        }}))
        return sync_regions(locale, write=True)

    assert region("Ton code est <emphasis>{code}</emphasis>.\n") == []
    assert (locale / "fr-CA/dialog/code.ssml").read_text().startswith("Ton code")
    assert "changes source placeholders" in region("Ton code est <emphasis>{kode}</emphasis>.\n")[0]
