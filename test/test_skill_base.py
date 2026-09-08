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
        "        return self.mentions(self.utterance(message), 'NewsKeyword',\n"
        "                             self.lang_of(message))\n\n"
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
    assert skill.locale_resources.available_langs() == ("en-US", "fr-FR")


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

    assert skill.mentions("what is the news", "NewsKeyword", "en-US")
    assert skill.mentions("quelles sont les nouvelles", "NewsKeyword", "fr-FR")
    assert not skill.mentions("renews the subscription", "NewsKeyword", "en-US")


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

    # Bypass OVOSSkill.__init__, which wants a bus; the plumbing is the point.
    skill = Empty.__new__(Empty)

    with pytest.raises(NotImplementedError):
        skill.can_answer(Msg())
    with pytest.raises(NotImplementedError):
        skill.handle_fallback(Msg({"utterance": "anything"}))


def test_settings_are_readable_before_the_skill_is_bound(demo):
    """Tests construct a skill without a bus, and reading settings then used to
    raise rather than return the default."""
    skill = demo()

    assert skill.setting("nothing", "fallback") == "fallback"


def test_the_plain_skill_class_carries_the_same_helpers():
    assert hasattr(ThalovantSkill, "mentions")
    assert hasattr(ThalovantSkill, "dialog")
    assert hasattr(ThalovantSkill, "utterance")


@pytest.mark.parametrize(
    "template, expected",
    [
        ("Hello {who}.", "Hello {who}."),        # a placeholder nobody supplied
        ("Hello {", "Hello {"),                  # an unmatched brace: ValueError
        ("Hello {0} {1}", "Hello {0} {1}"),      # positional: IndexError
    ],
)
def test_a_broken_translation_is_spoken_rather_than_raised(demo, tmp_path, template, expected):
    """`str.format` raises ValueError for a malformed template, not just
    KeyError for a missing placeholder. A translation with an unmatched brace
    should sound wrong, which is audible and fixable, rather than crash the
    reply."""
    skill = demo()
    broken = skill.locale_dir() / "en-US" / "dialog" / "broken.dialog"
    broken.write_text(template + "\n", encoding="utf-8")

    assert skill.dialog("broken", "en-US") == expected


def test_nothing_here_shadows_the_framework():
    """The base classes must not take a name OVOSSkill already uses.

    `voc_match` and `resources` were both taken at first. `voc_match` is the
    worse of the two: OVOS's signature is `(utt, voc_filename, ...)` and the
    replacement's was `(voc_name, utterance, ...)`, so any call the framework
    made would have had its arguments silently swapped. `resources` is the
    framework's own per-language resource object, and several OVOSSkill methods
    go through it.
    """
    from ovos_workshop.skills import OVOSSkill

    from thalovant_skillkit import skill as module

    ours = {
        name
        for cls in (module._SkillPlumbing, module.ThalovantFallbackSkill)
        for name in vars(cls)
        if not name.startswith("_")
    }
    # What a fallback skill is *supposed* to define: the framework declares
    # these and expects a skill to fill them in.
    expected = {"initialize", "can_answer", "handle_fallback", "runtime_requirements"}

    from thalovant_skillkit.skill import _ConversationalBase

    collisions = {
        name for name in ours - expected
        if hasattr(OVOSSkill, name) or hasattr(_ConversationalBase, name)
    }

    assert collisions == set(), (
        f"these shadow OVOSSkill and will confuse or break it: {sorted(collisions)}"
    )


class _Spoken(ThalovantFallbackSkill):
    """A skill written the short way: `reply` and nothing else."""

    FALLBACK_PRIORITY = 96
    LOCALE_DIR = "/nonexistent"

    def __init__(self):  # no bus, no config: the point is the plumbing
        self.said = []

    def speak(self, text, *args, **kwargs):
        self.said.append(text)

    def can_answer(self, message):
        return "news" in self.utterance(message)

    def reply(self, utterance, lang, context):
        if "nothing" in utterance:
            return None
        return f"[{lang}] the news is quiet"


def test_reply_is_spoken_on_the_hub_and_returned_to_the_showroom():
    """Nineteen skills kept a `preview_reply` in step with their speaking path
    by hand. Deriving both from one `reply` makes drift impossible."""
    skill = _Spoken()

    assert skill.handle_fallback(Msg({"utterance": "the news"}, {"lang": "fr-FR"})) is True
    assert skill.said == ["[fr-FR] the news is quiet"]
    assert skill.preview_reply("the news", "fr-FR") == "[fr-FR] the news is quiet"


def test_no_reply_means_the_skill_did_not_answer():
    """Returning False from the fallback is what lets the next skill be asked."""
    skill = _Spoken()

    assert skill.handle_fallback(Msg({"utterance": "news about nothing"})) is False
    assert skill.said == []
    assert skill.preview_reply("news about nothing") == ""


def test_preview_falls_back_to_the_skills_language():
    skill = _Spoken()

    assert skill.preview_reply("the news").startswith("[en-US]")


def test_a_skill_that_writes_neither_reply_nor_handle_fallback_says_so():
    class Silent(ThalovantFallbackSkill):
        pass

    with pytest.raises(NotImplementedError):
        Silent.reply(object(), "x", "en-US", {})
    # ...but the showroom must never crash because a skill has no preview.
    assert _Spoken.preview_reply.__name__ == "preview_reply"


def test_preview_reply_is_exposed_over_the_skill_api():
    """The preview bridge finds it through OVOS's skill-API decorator."""
    assert getattr(ThalovantFallbackSkill.preview_reply, "api_method", False) is True


def test_a_conversational_skill_carries_the_same_plumbing_and_converse():
    from thalovant_skillkit.skill import ThalovantConversationalSkill

    assert hasattr(ThalovantConversationalSkill, "mentions")
    assert hasattr(ThalovantConversationalSkill, "reply")
    assert hasattr(ThalovantConversationalSkill, "converse")


def test_a_subclass_defined_elsewhere_still_finds_the_skills_locale(demo, tmp_path):
    """A test harness subclasses the skill inside test/, which has no locale
    tree. Reading only the leaf class looked for test/locale/ and the skill
    answered with dialog names instead of dialog. The first real skill moved
    onto the kit found this within a minute."""
    harness_module = tmp_path / "elsewhere" / "harness.py"
    harness_module.parent.mkdir()
    harness_module.write_text(
        "from demo_skill_pkg import DemoSkill\n\nclass Harness(DemoSkill):\n    pass\n",
        encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("harness_mod", harness_module)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.Harness.locale_dir() == demo.locale_dir()
    assert module.Harness.locale_dir().is_dir()


def test_common_play_base_carries_the_plumbing_without_touching_ocp():
    """The fleet's news skill answers OCP searches, so it cannot use
    ThalovantSkill; it should not have to reach for the private mixin."""
    pytest.importorskip("ovos_workshop.skills.common_play")
    from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill

    from thalovant_skillkit.skill import ThalovantCommonPlaySkill, _SkillPlumbing

    assert ThalovantCommonPlaySkill is not None
    assert issubclass(ThalovantCommonPlaySkill, OVOSCommonPlaybackSkill)
    assert issubclass(ThalovantCommonPlaySkill, _SkillPlumbing)
    # The plumbing comes first, and adds nothing that shadows the OCP base
    # beyond runtime_requirements, which a skill overrides anyway.
    mro = ThalovantCommonPlaySkill.__mro__
    assert mro.index(_SkillPlumbing) < mro.index(OVOSCommonPlaybackSkill)
    shared = {n for n in vars(_SkillPlumbing) if not n.startswith("__")} & set(
        dir(OVOSCommonPlaybackSkill))
    assert shared == {"runtime_requirements"}, shared
    for helper in ("utterance", "lang_of", "dialog", "mentions", "locale_resources"):
        assert hasattr(ThalovantCommonPlaySkill, helper)
