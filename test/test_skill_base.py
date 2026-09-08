"""The base classes, which exist to delete plumbing from every skill.

The smallest skill in the fleet was 369 lines and about 120 of them were the
helpers these classes now carry. What is tested here is the behaviour those
helpers had to get right and sometimes did not: reading the language from
anywhere the message puts it, matching a vocabulary without claiming words that
merely spell it, and registering a fallback exactly once.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("ovos_workshop", reason="install the 'skill' extra")

from thalovant_skillkit.skill import ThalovantFallbackSkill, ThalovantSkill  # noqa: E402


def _skill_package(tmp_path: Path, name: str) -> Path:
    """A skill laid out the way every skill in the fleet is."""
    package = tmp_path / name
    for lang, vocab, dialog in (
        ("en-US", "news\nheadlines\n", "The news is quiet.\nNothing is happening.\n"),
        ("fr-FR", "nouvelles\n", "Les nouvelles sont calmes.\n"),
    ):
        (package / "locale" / lang / "vocab").mkdir(parents=True)
        (package / "locale" / lang / "dialog").mkdir(parents=True)
        (package / "locale" / lang / "vocab" / "NewsKeyword.voc").write_text(
            vocab, encoding="utf-8")
        (package / "locale" / lang / "dialog" / "quiet.dialog").write_text(dialog, encoding="utf-8")
    (package / "locale" / "en-US" / "dialog" / "named.dialog").write_text(
        "Hello {who}.\n", encoding="utf-8")
    (package / "__init__.py").write_text(
        "from thalovant_skillkit.skill import ThalovantFallbackSkill\n\n\n"
        "class DemoSkill(ThalovantFallbackSkill):\n"
        "    FALLBACK_PRIORITY = 95\n\n"
        "    def can_answer(self, message):\n"
        "        return self.voc_match('NewsKeyword', self.utterance(message),\n"
        "                              self.lang_of(message))\n\n"
        "    def handle_fallback(self, message):\n"
        "        return True\n",
        encoding="utf-8")
    return package


@pytest.fixture
def demo(tmp_path):
    package = _skill_package(tmp_path, "demo_skill_pkg")
    spec = importlib.util.spec_from_file_location("demo_skill_pkg", package / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_skill_pkg"] = module
    spec.loader.exec_module(module)
    try:
        yield module.DemoSkill
    finally:
        sys.modules.pop("demo_skill_pkg", None)


class Msg:
    def __init__(self, data=None, context=None):
        self.data = data or {}
        self.context = context or {}


def test_the_locale_tree_is_found_without_the_skill_saying_where(demo):
    """Every skill carried `LOCALE_DIR = Path(__file__).parent / "locale"`."""
    skill = demo()

    assert skill.locale_dir().name == "locale"
    assert skill.resources.available_langs() == ("en-US", "fr-FR")


def test_the_language_is_read_from_wherever_the_message_puts_it(demo):
    """Five skills read only `context["lang"]` and answered in the wrong
    language when it arrived in the data or the session."""
    skill = demo()

    assert skill.lang_of(Msg(data={"lang": "fr-FR"})) == "fr-FR"
    assert skill.lang_of(Msg(context={"lang": "fr-FR"})) == "fr-FR"
    assert skill.lang_of(Msg(context={"session": {"lang": "fr-FR"}})) == "fr-FR"
    assert skill.lang_of(Msg()) == "en-US"


def test_the_utterance_is_read_from_every_key_a_message_uses(demo):
    skill = demo()

    assert skill.utterance(Msg({"utterance": " the news "})) == "the news"
    assert skill.utterance(Msg({"phrase": "a podcast"})) == "a podcast"
    assert skill.utterance(Msg()) == ""


def test_vocabulary_matching_does_not_claim_a_word_that_spells_a_term(demo):
    """The bug that had five skills answering for each other."""
    skill = demo()

    assert skill.voc_match("NewsKeyword", "what is the news", "en-US")
    assert skill.voc_match("NewsKeyword", "quelles sont les nouvelles", "fr-FR")
    assert not skill.voc_match("NewsKeyword", "renews the subscription", "en-US")


def test_dialog_renders_falls_back_and_never_raises(demo):
    skill = demo()

    assert skill.dialog("quiet", "en-US") in ("The news is quiet.", "Nothing is happening.")
    assert skill.dialog("quiet", "fr-FR") == "Les nouvelles sont calmes."
    assert skill.dialog("named", "en-US", {"who": "Ada"}) == "Hello Ada."
    # A missing translation should sound wrong, not raise mid-answer.
    assert skill.dialog("absent", "en-US") == "absent"
    # ...and neither should a line whose placeholder was not supplied.
    assert skill.dialog("named", "en-US") == "Hello {who}."


def test_dialog_varies_when_the_file_offers_more_than_one_line(demo):
    """A skill asked the same thing twice should not answer identically."""
    skill = demo()

    seen = {skill.dialog("quiet", "en-US") for _ in range(40)}

    assert len(seen) == 2, "every line in the file should be reachable"


def test_runtime_requirements_come_from_three_attributes(demo):
    """Every skill was copying a thirteen-line RuntimeRequirements block."""
    offline = demo.runtime_requirements

    assert offline.requires_internet is False
    assert offline.no_internet_fallback is True

    class Online(demo):
        REQUIRES_INTERNET = True
        REQUIRES_NETWORK = True

    assert Online.runtime_requirements.requires_internet is True
    assert Online.runtime_requirements.no_internet_fallback is False


def test_the_fallback_registers_once_however_often_initialize_runs(demo):
    """Skills re-run registration on reload and on a settings change, and
    ovos-core will hold the same handler twice -- which then answers twice."""
    skill = demo()
    skill._fallback_handlers = []
    skill.register_fallback = lambda handler, priority: skill._fallback_handlers.append(
        (priority, handler))

    assert skill.register_thalovant_fallback() is True
    assert skill.register_thalovant_fallback() is False
    assert [p for p, _ in skill._fallback_handlers] == [95]


def test_an_operator_can_move_the_rung_within_the_low_band(demo):
    skill = demo()
    skill.settings = {"fallback_priority": 97}

    assert skill.fallback_priority() == 97

    skill.settings = {"fallback_priority": 5}  # outside the band: refused
    assert skill.fallback_priority() == 95


def test_a_skill_that_forgets_to_answer_says_so_loudly(demo):
    class Empty(ThalovantFallbackSkill):
        pass

    with pytest.raises(NotImplementedError):
        Empty.can_answer(object(), Msg())
    with pytest.raises(NotImplementedError):
        Empty.handle_fallback(object(), Msg())


def test_settings_are_readable_before_the_skill_is_bound(demo):
    """Tests construct a skill without a bus, and reading settings then used to
    raise rather than return the default."""
    skill = demo()

    assert skill.setting("nothing", "fallback") == "fallback"


def test_the_plain_skill_class_carries_the_same_helpers():
    assert hasattr(ThalovantSkill, "voc_match")
    assert hasattr(ThalovantSkill, "dialog")
    assert hasattr(ThalovantSkill, "utterance")
