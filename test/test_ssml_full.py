"""Everything phoonnx can speak is something a skill can write, check and send."""
from __future__ import annotations

import pytest

from thalovant_skillkit import ssml
from thalovant_skillkit.ssml import (
    SpeechStyle, address, as_date, as_time, auto_breaths, auto_twin, breath, cardinal, compress,
    currency, expletive, fraction, interjection, looks_like_ssml, mark, markup, ordinal, phoneme,
    pitch, prosody, render_line, say, soft, to_plain, unit, validate, vocal_tract, whisper,
)

VALID = [
    '<prosody pitch="+2st">x</prosody>',
    '<prosody rate="slow" pitch="-10%" volume="soft">x</prosody>',
    '<prosody pitch="x-high">x</prosody>',
    '<say-as interpret-as="ordinal">3</say-as>',
    '<say-as interpret-as="date" format="mdy">11/09/2026</say-as>',
    '<say-as interpret-as="time" format="hms24">14:30</say-as>',
    '<say-as interpret-as="currency">$12.50</say-as>',
    '<say-as interpret-as="expletive">darn</say-as>',
    '<phoneme alphabet="x-sampa" ph="tS{ts">chats</phoneme>',
    'Wait <mark name="here"/> now',
    '<amazon:effect name="whispered">secret</amazon:effect>',
    '<amazon:effect name="drc">even</amazon:effect>',
    '<amazon:effect phonation="soft" vocal-tract-length="+20%">soft</amazon:effect>',
    '<amazon:auto-breaths frequency="high" duration="long" volume="loud">One. Two.</amazon:auto-breaths>',
    'One.<amazon:breath duration="short"/> Two.',
    '<amazon:domain name="news">words</amazon:domain>',
]


@pytest.mark.parametrize("fragment", VALID)
def test_every_feature_phoonnx_speaks_is_accepted(fragment):
    assert validate(fragment) == []
    assert looks_like_ssml(fragment)


def test_a_placeholder_is_not_judged_in_the_new_attributes_either():
    assert validate('<prosody pitch="{p}">x</prosody><say-as interpret-as="date" format="{f}">1</say-as>') == []


def test_plain_text_of_the_new_markup_is_the_written_words():
    assert to_plain('Finished <say-as interpret-as="ordinal">3</say-as> of '
                    '<say-as interpret-as="cardinal">1,200</say-as>.') == "Finished 3 of 1,200."
    assert to_plain('<amazon:effect name="whispered">secret</amazon:effect> '
                    'and <mark name="m"/>more<amazon:breath/> text') == "secret and more text"
    assert to_plain('<phoneme alphabet="x-sampa" ph="tS{ts">chats</phoneme>') == "chats"


@pytest.mark.parametrize("built, plain", [
    (cardinal("1,200"), "1,200"), (ordinal(3), "3"), (fraction("1/2"), "1/2"), (unit("5km"), "5km"),
    (currency("$12.50"), "$12.50"), (address("12 Main St."), "12 Main St."),
    (interjection("wow"), "wow"), (expletive("darn"), "darn"),
    (as_date("2026-11-09"), "2026-11-09"), (as_date("11/09/2026", format="mdy"), "11/09/2026"),
    (as_time("2:30pm"), "2:30pm"), (as_time("14:30", "hms24"), "14:30"),
    (phoneme("chats", "tS{ts", "x-sampa"), "chats"), (phoneme("hello", "həˈloʊ"), "hello"),
    (prosody("hi", rate="slow", pitch="+2st", volume="soft"), "hi"), (pitch("Really?", "-2st"), "Really?"),
    (whisper("secret"), "secret"), (soft("softly"), "softly"), (compress("even"), "even"),
    (vocal_tract("deep", "+20%"), "deep"), (auto_breaths("One. Two.", "high", "long", "loud"), "One. Two."),
    (mark("here"), ""), (breath("short"), ""),
])
def test_each_helper_builds_valid_markup_with_the_plain_words(built, plain):
    assert str(built) == plain
    assert built.ssml and validate(built.ssml) == []
    assert to_plain(built.document) == plain


def test_helpers_combine_with_say_and_keep_both_forms():
    line = say("You finished", ordinal(3), "of", cardinal("1,200"), mark("done"), breath())
    assert str(line) == "You finished 3 of 1,200"
    assert line.ssml.count("<say-as") == 2 and '<mark name="done"/>' in line.ssml
    assert "<amazon:breath/>" in line.ssml and validate(line.ssml) == []


def test_helpers_refuse_what_a_voice_would_not_read():
    with pytest.raises(ValueError, match="pitch"):
        pitch("x", "shrill")
    with pytest.raises(ValueError, match="date order"):
        as_date("1/2", format="xyz")
    with pytest.raises(ValueError, match="x-sampa"):
        phoneme("x", "a", "arpabet")
    with pytest.raises(ValueError, match="rate, a pitch or a volume"):
        prosody("x")
    with pytest.raises(ValueError, match="frequency"):
        auto_breaths("x", "often")


def test_values_are_escaped_in_the_new_helpers():
    assert 'name="a&quot;b"' in mark('a"b').ssml
    assert "&lt;" in whisper("a<b").ssml


def test_markup_templates_accept_the_new_tags_and_fill_placeholders():
    line = markup('<amazon:effect name="whispered">{secret}</amazon:effect>', secret="a & b")
    assert str(line) == "a & b"
    assert line.ssml == '<amazon:effect name="whispered">a &amp; b</amazon:effect>'


def test_a_twin_line_with_the_new_tags_renders():
    spoken = render_line("It is {n}.", 'It is <say-as interpret-as="cardinal">{n}</say-as>.', {"n": "1,200"})
    assert str(spoken) == "It is 1,200." and "cardinal" in spoken.ssml
    breathy = render_line("One. Two.", '<amazon:auto-breaths frequency="low">One. Two.</amazon:auto-breaths>')
    assert breathy.ssml.startswith("<amazon:auto-breaths")


def test_speech_style_can_set_pitch_and_breaths():
    style = SpeechStyle(rate="95%", pitch="-1st", breaths="low", sentence_break="300ms")
    twin = auto_twin("First. Second.", style)
    assert twin == ('<amazon:auto-breaths frequency="low"><prosody rate="95%" pitch="-1st">'
                    'First. <break time="300ms"/> Second.</prosody></amazon:auto-breaths>')
    assert validate(twin) == []
    assert auto_twin("Only.", SpeechStyle(pitch="+1st")) == '<prosody pitch="+1st">Only.</prosody>'
    with pytest.raises(ValueError):
        SpeechStyle(pitch="shrill")
    with pytest.raises(ValueError):
        SpeechStyle(breaths="often")


def test_module_exports_every_helper():
    for name in ("cardinal", "ordinal", "fraction", "unit", "currency", "address", "interjection",
                 "expletive", "as_date", "as_time", "phoneme", "mark", "prosody", "pitch", "whisper",
                 "soft", "compress", "vocal_tract", "breath", "auto_breaths"):
        assert name in ssml.__all__
