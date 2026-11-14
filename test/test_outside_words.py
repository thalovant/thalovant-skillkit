"""Somebody else's words are words: never markup, whatever they hold.

A server, a link or a provider wrote them (a title, a player's name, the whole answer a home
relayed). The recheck of 2026-11-13 showed `strip_tags` returning a tag (entities were read AFTER
the tags were removed) and `speech_parts` promoting a plain string that held well-formed SSML to
`utterance_ssml`: text relayed by a home made the household's speakers obey it. These are that
proof of concept turned round, and the kit-level guard beside it.
"""

from __future__ import annotations

import pytest

from thalovant_skillkit.safety import speakable
from thalovant_skillkit.speech import speak_to
from thalovant_skillkit.ssml import (
    Speech,
    SpeechStyle,
    looks_like_ssml,
    outside_parts,
    pause,
    say,
    speech_parts,
    strip_tags,
)
from thalovant_skillkit.testing import FakeBus, message

EVIL_AUDIO = '<audio src="https://evil.example/x.mp3"/>'
#: The three answers of the proof of concept: the tag's closing bracket is written `&gt;`, so a
#: cleaner that removes tags first sees an unclosed `<` and keeps it.
RELAYED = [
    'Playing <audio src="https://evil.example/x.mp3"/&gt; on Kitchen',
    'Now playing <prosody volume="+40dB"&gt;LOUD&lt;/prosody&gt; on Kitchen',
    'Done <break time="10s"/&gt; ok',
]
STYLE = SpeechStyle(sentence_break="300ms", colon_break="250ms", dash_break="250ms")


class _Skill:
    skill_id = "thalovant-skill-demo"
    SPEECH_STYLE = None

    def __init__(self, style=None):
        self._bus = FakeBus()
        self.SPEECH_STYLE = style


# -- strip_tags: entities first, tags to a fixed point, no bracket left ----------------------------


def test_strip_tags_can_no_longer_return_a_tag():
    """`strip_tags('<audio .../&gt;')` returned the whole tag: nothing matched the tag pattern, and
    the entity was read afterwards."""
    assert strip_tags('<audio src="https://evil.example/x.mp3"/&gt;') == ""
    assert strip_tags('&lt;audio src="https://evil.example/x.mp3"/&gt;') == ""
    assert strip_tags("&#60;break time='9s'/&#62; hello") == "hello"


@pytest.mark.parametrize(
    "text", [*RELAYED, EVIL_AUDIO, "<au<b>dio src='x'>", "a < b > c", "<" * 50]
)
def test_what_strip_tags_returns_holds_no_bracket_and_is_never_read_as_markup(text):
    words = strip_tags(text)
    assert "<" not in words and ">" not in words
    assert not looks_like_ssml(words) and speech_parts(words) == (words, None)


def test_strip_tags_keeps_the_words_and_reads_entities_once():
    assert strip_tags("Hello <s>there</s>") == "Hello there"
    assert strip_tags("Tom &amp; Jerry <break/> again") == "Tom & Jerry again"
    assert strip_tags(RELAYED[0]) == "Playing on Kitchen"
    assert strip_tags("5 < 6 and 7 > 3") == "5 6 and 7 3"
    assert strip_tags("&amp;lt;b&amp;gt;") == "&lt;b&gt;"  # once: still words, still no bracket
    assert strip_tags("") == "" and strip_tags(None) == ""


# -- the proof of concept, turned round ----------------------------------------------------------


@pytest.mark.parametrize("relayed", RELAYED)
def test_relayed_text_cleaned_with_speakable_is_never_promoted(relayed):
    """What every skill does with outside text before it speaks: `speakable`, then `speak`."""
    words = speakable(relayed, 600)
    assert "<" not in words and "&" not in words
    assert speech_parts(words, "skill") == (words, None)
    sent = speak_to(_Skill(), message("what is playing"), words)
    assert "utterance_ssml" not in sent.data and sent.data["utterance"] == words


def test_the_old_cleaner_shape_is_what_was_promoted():
    """Why the fix is in two places: with the tag written back in full, a plain string IS moved
    to `utterance_ssml` (a skill's own markup may be). So outside text must never reach `speak`
    as it came, and `untrusted=True` is the way to say so."""
    live = "Playing <prosody volume='+40dB'>LOUD</prosody> on Kitchen"
    assert speech_parts(live, "skill")[1] == f"<speak>{live}</speak>"  # trusted: promoted
    assert speech_parts(live, "skill", untrusted=True) == ("Playing LOUD on Kitchen", None)


# -- the kit-level guard: untrusted words are never promoted ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        *RELAYED,
        EVIL_AUDIO + " now",
        "Wait <break time='10s'/> for it.",
        "<speak>Hi <voice xml:lang='fr-FR'>there</voice></speak>",
        "<prosody volume='+40dB'>LOUD</prosody>",
        "&lt;break time='10s'/&gt; ok",
        "＜break time='10s'/＞ ok",
    ],
)
def test_untrusted_words_are_never_markup_with_or_without_a_style(text):
    for style in (None, STYLE):
        words, ssml = speech_parts(text, "skill", untrusted=True, style=style, lang="en-US")
        assert "<" not in words and ">" not in words
        if ssml is not None:  # only the kit's own pacing, around the escaped words
            assert "audio" not in ssml and "prosody" not in ssml and "voice" not in ssml
            assert "10s" not in ssml
            assert ssml.count("<") == 2 + ssml.count("<break time=")  # <speak>, </speak>, pauses
        sent = speak_to(_Skill(style), message("x"), text, untrusted=True)
        assert sent.data["utterance"] == words
        assert sent.data.get("utterance_ssml") == ssml


def test_a_one_clause_answer_gets_no_markup_at_all():
    """The proof of concept's own case: "A one-clause answer gets no pacing twin", so the plain
    string went to `speech_parts` as it was."""
    sent = speak_to(_Skill(STYLE), message("x"), RELAYED[0], untrusted=True)
    assert sent.data["utterance"] == "Playing on Kitchen" and "utterance_ssml" not in sent.data


def test_untrusted_words_are_paced_by_the_skills_own_style_and_escaped():
    text = "The garage is open. Tom & Jerry <b>said</b>: the front door is locked."
    words, ssml = outside_parts(text, STYLE, "en-US")
    assert words == "The garage is open. Tom & Jerry said : the front door is locked."
    assert ssml == (
        '<speak>The garage is open. <break time="300ms"/> Tom &amp; Jerry said : '
        '<break time="250ms"/> the front door is locked.</speak>'
    )
    # without a style there is nothing to add
    assert outside_parts(text) == (words, None)


def test_markup_that_travelled_with_outside_words_is_not_believed():
    """A `Speech` is a skill's own markup. Marked untrusted, only its words are kept."""
    speech = say("Why?", pause("9s"), "Because.")
    assert speech_parts(speech, "skill")[1] is not None
    assert speech_parts(speech, "skill", untrusted=True) == ("Why? Because.", None)
    forged = Speech("Elf", EVIL_AUDIO + "Elf")
    assert speech_parts(forged, "skill", untrusted=True) == ("Elf", None)


def test_words_with_a_brace_are_said_plainly():
    """The pacing would read `{x}` as a placeholder."""
    assert outside_parts("Set {level}. Done.", STYLE, "en-US") == ("Set {level}. Done.", None)


def test_nothing_left_to_say_is_nothing_sent():
    skill = _Skill(STYLE)
    assert speak_to(skill, message("x"), EVIL_AUDIO, untrusted=True) is None
    assert speak_to(skill, message("x"), "", untrusted=True) is None
    assert skill._bus.emitted == []
    assert outside_parts(None) == (None, None) and outside_parts(7, STYLE) == (7, None)


def test_a_pacing_failure_costs_the_markup_not_the_reply(monkeypatch):
    from thalovant_skillkit import ssml

    def boom(*args, **kwargs):
        raise RuntimeError("pacing broke")

    monkeypatch.setattr(ssml, "auto_twin", boom)
    assert outside_parts("One. Two.", STYLE, "en-US") == ("One. Two.", None)
    monkeypatch.setattr(ssml, "auto_twin", lambda *a, **k: "One. <break")  # not well-formed
    assert outside_parts("One. Two.", STYLE, "en-US") == ("One. Two.", None)


def test_trusted_text_is_sent_exactly_as_before():
    """The default did not change: a skill's own plain string and its own Speech."""
    skill = _Skill(STYLE)
    sent = speak_to(skill, message("x"), "It is 5 < 6 & fine.")
    assert sent.data["utterance"] == "It is 5 < 6 & fine." and "utterance_ssml" not in sent.data
    sent = speak_to(skill, message("x"), say("Why?", pause(), "Because."))
    assert sent.data["utterance_ssml"] == "<speak>Why? <break/> Because.</speak>"


def test_the_skill_base_passes_the_mark_on(monkeypatch):
    from thalovant_skillkit.skill import ThalovantSkill

    skill = ThalovantSkill.__new__(ThalovantSkill)
    bus = FakeBus()
    monkeypatch.setattr(ThalovantSkill, "bus", property(lambda self: bus), raising=False)
    monkeypatch.setattr(ThalovantSkill, "skill_id", "demo.skill", raising=False)
    monkeypatch.setattr(ThalovantSkill, "lang", "en-US", raising=False)
    monkeypatch.setattr(ThalovantSkill, "SPEECH_STYLE", STYLE, raising=False)
    sent = skill.speak_to(message("x"), "One <audio src='x'/>. Two.", untrusted=True)
    assert sent.data["utterance"] == "One . Two."
    assert "audio" not in sent.data.get("utterance_ssml", "")
    live = skill.speak_to(message("x"), "One <break/> two.")  # the skill's own markup still is
    assert live.data["utterance_ssml"] == "<speak>One <break/> two.</speak>"
