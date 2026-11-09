"""A skill declares how it speaks once; no `.ssml` twin is needed per line."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from thalovant_skillkit.checks import check_all
from thalovant_skillkit.ssml import SpeechStyle, auto_twin, render_line, validate
from thalovant_skillkit.testing_ovos import skill_harness

FIXTURE = Path(__file__).parent / "fixtures" / "thalovant-skill-punchline"
STYLE = SpeechStyle(rate="95%", sentence_break="350ms", colon_break="300ms",
                    dash_break="300ms", comma_break="250ms")


def test_breaks_follow_the_marks_of_the_line_not_its_values():
    twin = auto_twin("Maybe — {chance} percent, rain. It is {when}.", STYLE)
    assert twin == ('<prosody rate="95%">Maybe — <break time="300ms"/> {chance} percent, '
                    '<break time="250ms"/> rain. <break time="350ms"/> It is {when}.</prosody>')
    # A value with a full stop in it is not cut in two.
    spoken = render_line("Maybe — {chance} percent, rain. It is {when}.", twin,
                         {"chance": "30", "when": "Mr. Smith's day"})
    assert str(spoken) == "Maybe — 30 percent, rain. It is Mr. Smith's day."
    assert spoken.ssml.count("<break") == 3


def test_the_words_are_escaped_and_an_entity_is_not_a_mark():
    twin = auto_twin("Sunny & warm; bring a <coat>. Done.", STYLE)
    assert "&amp; warm; <break" in twin and "&lt;coat&gt;. <break" in twin
    assert validate(twin) == []


def test_times_and_the_end_of_a_line_get_no_pause():
    only = SpeechStyle(sentence_break="350ms", colon_break="300ms")
    assert auto_twin("It is 10:30.", only) is None
    assert auto_twin("Hello!", only) is None
    assert auto_twin("No rules apply: here.", SpeechStyle()) is None


def test_a_rate_alone_marks_the_line():
    assert auto_twin("Hello {name}.", SpeechStyle(rate="slow")) == (
        '<prosody rate="slow">Hello {name}.</prosody>')


def test_literal_braces_are_left_to_the_plain_path():
    assert auto_twin("Use {{braces}}. Then go.", STYLE) is None


def test_a_style_that_no_voice_reads_is_refused():
    with pytest.raises(ValueError):
        SpeechStyle(rate="very-fast-indeed")
    with pytest.raises(ValueError):
        SpeechStyle(sentence_break="soon")


@pytest.fixture(scope="module")
def styled():
    sys.path.insert(0, str(FIXTURE))
    try:
        from thalovant_skill_punchline import PacedPunchlineSkill

        yield PacedPunchlineSkill
    finally:
        sys.path.remove(str(FIXTURE))
        sys.modules.pop("thalovant_skill_punchline", None)


def _say(skill_type, action, session):
    from ovos_bus_client.message import Message

    from thalovant_skillkit.speech import speech_topic

    with skill_harness(skill_type, skill_id="style.test", scheduler=False,
                       bus_options={"emit_legacy": False}) as harness:
        heard = []
        harness.bus.on(speech_topic(), heard.append)
        harness.skill.add_event("test.turn", lambda message: action(harness.skill))
        harness.bus.emit(Message("test.turn", {}, {"session": session}))
        return heard


def test_every_dialog_is_paced_in_every_language(styled):
    [en] = _say(styled, lambda s: s.speak_dialog("briefing", {"name": "Ada"}),
                {"session_id": "a", "lang": "en-US"})
    [fr] = _say(styled, lambda s: s.speak_dialog("briefing", {"name": "Ada"}),
                {"session_id": "b", "lang": "fr-FR"})
    assert en.data["utterance"] == "Two things: say hello to Ada. Then, say goodbye."
    assert en.data["utterance_ssml"] == (
        '<speak><prosody rate="95%">Two things: <break time="300ms"/> say hello to Ada. '
        '<break time="350ms"/> Then, <break time="250ms"/> say goodbye.</prosody></speak>')
    assert fr.data["utterance"] == "Deux choses : saluez Ada. Ensuite, dites au revoir."
    assert fr.data["utterance_ssml"].count("<break") == 3


def test_a_hand_written_twin_wins_over_the_style(styled):
    [joke] = _say(styled, lambda s: s.speak_dialog("joke"),
                  {"session_id": "a", "lang": "en-US"})
    assert "<prosody" not in joke.data["utterance_ssml"]
    assert '<break time="700ms"/>' in joke.data["utterance_ssml"]


def test_a_skill_without_a_style_is_unchanged(styled):
    plain_type = styled.__mro__[1]
    [message] = _say(plain_type, lambda s: s.speak_dialog("briefing", {"name": "Ada"}),
                     {"session_id": "a", "lang": "en-US"})
    assert "utterance_ssml" not in message.data


def test_the_fixture_still_keeps_every_contract():
    assert check_all(FIXTURE) == []


def test_a_twin_the_style_already_says_is_reported(tmp_path):
    from thalovant_skillkit.checks import redundant_twins

    package = tmp_path / "thalovant_skill_x"
    dialog = package / "locale" / "en-US" / "dialog"
    dialog.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (dialog / "a.dialog").write_text("Hello. There.\n")
    (dialog / "a.ssml").write_text('Hello. <break time="350ms"/> There.\n')
    (dialog / "b.dialog").write_text("Hello. There.\n")
    (dialog / "b.ssml").write_text('Hello. <break time="900ms"/> <emphasis>There.</emphasis>\n')
    style = SpeechStyle(sentence_break="350ms")
    assert redundant_twins(tmp_path, style) == [
        "locale/en-US/dialog/a.ssml repeats what the skill's SPEECH_STYLE already says; delete it"
    ]
