"""Speech markup travels beside the plain words and never inside them.

What is tested here is the contract every client relies on: `utterance` is
plain words that say what the SSML says, text from users and services cannot
become markup, and whatever goes wrong with markup costs the markup, never
the reply.
"""
from __future__ import annotations

import copy
import json
import logging
import pickle

import pytest

from thalovant_skillkit import ssml
from thalovant_skillkit.ssml import (
    Speech,
    digits,
    emphasis,
    escape,
    foreign,
    looks_like_ssml,
    markup,
    pause,
    render_line,
    say,
    speech_parts,
    spell,
    sub,
    telephone,
    to_plain,
    validate,
)


@pytest.fixture(autouse=True)
def _fresh_warnings():
    """Each test sees its own first warning."""
    ssml._WARNED.clear()
    yield
    ssml._WARNED.clear()


# -- building a sentence -----------------------------------------------------

def test_a_pause_before_the_punchline_leaves_the_plain_words_alone():
    """The words a phone says are the words the voice says, minus the pause."""
    joke = say("Why did the chicken cross the road?", pause("1s"), "To get to the other side.")

    assert joke == "Why did the chicken cross the road? To get to the other side."
    assert joke.ssml == ('Why did the chicken cross the road? <break time="1s"/> '
                         "To get to the other side.")
    assert joke.document == f"<speak>{joke.ssml}</speak>"


def test_each_helper_says_one_thing_and_keeps_the_written_words():
    """A say-as keeps its text as written; how "XK7" is read is the voice's job."""
    assert spell("XK7").ssml == '<say-as interpret-as="characters">XK7</say-as>'
    assert spell("XK7") == "XK7"
    assert digits("2048").ssml == '<say-as interpret-as="digits">2048</say-as>'
    assert telephone("555-0199").ssml == '<say-as interpret-as="telephone">555-0199</say-as>'
    assert foreign("croissant", "fr-FR").ssml == '<lang xml:lang="fr-FR">croissant</lang>'
    assert emphasis("now").ssml == '<emphasis level="moderate">now</emphasis>'
    assert emphasis("now", "strong").ssml == '<emphasis level="strong">now</emphasis>'
    assert pause().ssml == "<break/>"
    assert pause(strength="strong").ssml == '<break strength="strong"/>'
    assert pause("750ms") == ""


def test_a_substitution_says_the_alias_where_markup_is_not_read():
    """The plain text is what a client without SSML says aloud."""
    speed = sub("km/h", "kilometres per hour")

    assert speed == "kilometres per hour"
    assert speed.ssml == '<sub alias="kilometres per hour">km/h</sub>'


def test_helpers_nest_and_join():
    """A foreign word can be stressed; a sentence is words and pieces."""
    order = say("One", emphasis(foreign("café", "fr-FR")), "please.")

    assert order == "One café please."
    assert order.ssml == ('One <emphasis level="moderate"><lang xml:lang="fr-FR">café</lang>'
                          "</emphasis> please.")


def test_a_pause_refuses_a_number_without_a_unit():
    """SSML has no default unit, so "1" is refused rather than guessed."""
    with pytest.raises(TypeError, match="unit"):
        pause(500)
    with pytest.raises(ValueError, match="unit"):
        pause("500")
    with pytest.raises(ValueError, match="10s"):
        pause("30s")
    with pytest.raises(ValueError):
        pause("1s", strength="strong")
    with pytest.raises(ValueError):
        foreign("x", "not a language")
    with pytest.raises(ValueError):
        emphasis("x", "loud")


# -- nothing a user says becomes markup -------------------------------------

def test_words_from_a_user_are_escaped_not_read_as_markup():
    """A string is words. `<break/>` said by a user is said, not obeyed."""
    echoed = say("You said:", "<break time='9s'/> & more", spell("<3"))

    assert echoed == "You said: <break time='9s'/> & more <3"
    assert echoed.ssml == ("You said: &lt;break time='9s'/&gt; &amp; more "
                           '<say-as interpret-as="characters">&lt;3</say-as>')
    assert validate(echoed.ssml) == []


def test_markup_fills_its_placeholders_with_escaped_values():
    """The template is the skill's; the values are data and cannot add tags."""
    code = markup('<say-as interpret-as="characters">{code}</say-as>, <sub alias="{a}">x</sub>',
                  code='"/><break time="9s"/>', a='" onload="')

    assert "<break" not in code.ssml.replace("&lt;break", "")
    assert code.ssml.count("<say-as") == 1
    assert validate(code.ssml) == []


def test_markup_takes_a_speech_value_as_markup():
    """A Speech was built by the skill, so its tags are kept."""
    line = markup("Your code is {code}.", code=spell("AB1"))

    assert line == "Your code is AB1."
    assert line.ssml == 'Your code is <say-as interpret-as="characters">AB1</say-as>.'


def test_markup_refuses_what_a_voice_does_not_read():
    """A mistake in the skill's own markup fails in its tests, not on air."""
    with pytest.raises(ValueError, match="pitch"):
        markup('<prosody pitch="high">hi</prosody>')
    with pytest.raises(ValueError, match="well-formed"):
        markup("<s>unclosed")


def test_escape_covers_attribute_values():
    assert escape('a&b<c>"d\'') == "a&amp;b&lt;c&gt;&quot;d&apos;"


# -- the value ---------------------------------------------------------------

def test_a_speech_is_a_string_everywhere_a_string_goes():
    """JSON, pickling, copying and equality all see the plain words."""
    joke = say("Wait for it.", pause("1s"), "There.")

    assert isinstance(joke, str)
    assert json.dumps({"utterance": joke}) == '{"utterance": "Wait for it. There."}'
    assert joke == "Wait for it. There."
    assert type(joke.plain) is str
    for clone in (copy.copy(joke), copy.deepcopy(joke), pickle.loads(pickle.dumps(joke))):
        assert isinstance(clone, Speech)
        assert clone.ssml == joke.ssml


def test_adding_text_keeps_the_markup_on_either_side():
    """`+` works both ways; f-strings and str methods keep only the words."""
    code = spell("XK7")

    assert ("Code: " + code).ssml == 'Code: <say-as interpret-as="characters">XK7</say-as>'
    assert (code + ".").ssml == '<say-as interpret-as="characters">XK7</say-as>.'
    assert type(f"{code}!") is str
    assert type(code.upper()) is str


def test_plain_words_without_markup_carry_no_ssml():
    """A Speech of words alone sends no `utterance_ssml`."""
    assert say("just", "words").ssml is None
    assert say("just", "words").document is None
    assert Speech("a & b").fragment == "a &amp; b"


def test_a_speech_can_be_made_from_ssml_alone():
    """The plain words are read out of the markup."""
    line = Speech(ssml='<speak>Dr. <sub alias="Who">W.</sub> <break/> said hi.</speak>')

    assert line == "Dr. Who said hi."
    assert line.document == '<speak>Dr. <sub alias="Who">W.</sub> <break/> said hi.</speak>'


# -- reading markup out -------------------------------------------------------

def test_the_plain_form_of_markup():
    """Breaks and sentence edges become one space; entities are read."""
    assert to_plain('<speak>One<break/>two <say-as interpret-as="characters">XK7</say-as>'
                    "<s>Next</s>end &amp; done</speak>") == "One two XK7 Next end & done"
    assert to_plain('say <sub alias="doctor">Dr.</sub>') == "say doctor"
    assert to_plain('say <sub alias="doctor">Dr.</sub>', alias=False) == "say Dr."
    assert to_plain("broken <s>markup") == "broken markup"


def test_ssml_is_told_apart_from_a_sentence_with_a_less_than_sign():
    """`x < y`, `<3` and OVOS `<vocabulary>` names are not markup."""
    assert looks_like_ssml('wait <break time="1s"/> now')
    assert looks_like_ssml("<s>one</s>")
    assert looks_like_ssml("<amazon:effect>x</amazon:effect>")
    for text in ("x < y", "I <3 this", "a <name> slot", "<sa>", "", None, 42):
        assert not looks_like_ssml(text)


@pytest.mark.parametrize("markup_text, problem", [
    ('<break time="20s"/>', "10s"),
    ('<break time="20"/>', "unit"),
    ('<break strength="loud"/>', "strength"),
    ("<break>words</break>", "no words"),
    ('<prosody pitch="high">x</prosody>', "pitch"),
    ('<prosody rate="warp">x</prosody>', "rate"),
    ('<prosody volume="11">x</prosody>', "volume"),
    ('<say-as interpret-as="date">1/2</say-as>', "interpret-as"),
    ("<say-as>1</say-as>", "needs interpret-as"),
    ("<sub>x</sub>", "alias"),
    ('<phoneme alphabet="x-sampa" ph="a">a</phoneme>', "ipa"),
    ("<phoneme>a</phoneme>", "ph"),
    ("<lang>oui</lang>", "xml:lang"),
    ('<lang xml:lang="not a tag">oui</lang>', "language tag"),
    ('<emphasis level="max">x</emphasis>', "level"),
    ('<audio src="x.wav"/>', "not rendered"),
    ("<amazon:effect>x</amazon:effect>", "not read"),
    ("<s>one <speak>two</speak></s>", "whole line"),
    ("<s>unclosed", "well-formed"),
    ("fish & chips", "well-formed"),
])
def test_validation_names_what_a_voice_cannot_do(markup_text, problem):
    problems = validate(markup_text)

    assert problems and any(problem in found for found in problems), problems


def test_validation_accepts_the_supported_set_and_leaves_placeholders_to_later():
    assert validate(
        '<speak xml:lang="en-US"><p><s>Hi <break time="{t}"/> <sub alias="{a}">{b}</sub></s>'
        '<s><prosody rate="slow" volume="+3dB">slow</prosody> <prosody rate="120%">x</prosody>'
        '</s></p><emphasis level="strong">x</emphasis> <voice xml:lang="fr-FR">oui</voice> '
        '<phoneme alphabet="ipa" ph="bɔ̃ʒuʁ">bonjour</phoneme> '
        '<say-as interpret-as="spell-out">ab</say-as> <break strength="x-weak"/></speak>'
    ) == []


# -- dialog lines ------------------------------------------------------------

def test_a_twin_is_rendered_from_the_same_data_escaped():
    """The plain line gets the value; the SSML line gets it escaped."""
    line = render_line("Knock knock. {who}.", 'Knock knock. <break time="500ms"/> {who}.',
                       {"who": "Tom & Jerry"})

    assert line == "Knock knock. Tom & Jerry."
    assert line.ssml == 'Knock knock. <break time="500ms"/> Tom &amp; Jerry.'


def test_a_marked_value_marks_up_a_line_with_no_twin():
    """No locale file changes: the value knows how it should be said."""
    line = render_line("Votre code est {code}.", None, {"code": spell("XK7")})

    assert line == "Votre code est XK7."
    assert line.ssml == 'Votre code est <say-as interpret-as="characters">XK7</say-as>.'


def test_a_line_with_neither_is_a_plain_string():
    """Exactly what `str.format` gives, with no Speech in the way."""
    line = render_line("It is {n} degrees & rising.", None, {"n": 21})

    assert type(line) is str
    assert line == "It is 21 degrees & rising."


def test_a_twin_that_breaks_costs_the_markup_not_the_reply(caplog):
    """A twin missing a value, or broken by one, is dropped and logged once."""
    with caplog.at_level(logging.WARNING, logger="thalovant_skillkit.ssml"):
        missing = render_line("Hi {name}.", "Hi <break/> {nom}.", {"name": "Ada"})
        again = render_line("Hi {name}.", "Hi <break/> {nom}.", {"name": "Ada"})
        broken = render_line("Hi {name}.", "Hi <s>{name}.", {"name": "Ada"})

    assert (missing, again, broken) == ("Hi Ada.", "Hi Ada.", "Hi Ada.")
    assert not any(isinstance(line, Speech) for line in (missing, again, broken))
    assert len(caplog.records) == 2


def test_a_broken_plain_line_raises_as_str_format_does():
    """The caller decides what a broken translation costs, as before."""
    with pytest.raises(KeyError):
        render_line("Hi {name}.", "Hi {name}.", {})


# -- what goes on the bus ----------------------------------------------------

def test_a_plain_string_passes_through_untouched():
    text = "It is 5 < 6 & fine."

    plain, markup_text = speech_parts(text, "skill")

    assert plain is text
    assert markup_text is None


def test_markup_passed_as_plain_text_is_moved_and_logged_once(caplog):
    """No skill can put a tag in front of the Android app."""
    with caplog.at_level(logging.WARNING, logger="thalovant_skillkit.ssml"):
        first = speech_parts("Wait <break time='1s'/> for it.", "skill-a")
        second = speech_parts("Wait <break/> again.", "skill-a")

    assert first == ("Wait for it.", "<speak>Wait <break time='1s'/> for it.</speak>")
    assert second == ("Wait again.", "<speak>Wait <break/> again.</speak>")
    assert len(caplog.records) == 1
    assert "skill-a" in caplog.records[0].getMessage()


def test_markup_that_does_not_parse_is_taken_out_of_the_plain_text():
    assert speech_parts("Hello <s>there", "skill") == ("Hello there", None)


def test_a_speech_gives_its_words_and_its_document():
    joke = say("Why?", pause(), "Because.")

    assert speech_parts(joke, "skill") == ("Why? Because.", "<speak>Why? <break/> Because.</speak>")
    assert type(speech_parts(joke, "skill")[0]) is str


def test_a_speech_with_broken_markup_sends_its_words_only():
    assert speech_parts(Speech("hi", "<s>hi"), "skill") == ("hi", None)


def test_a_speech_whose_words_hold_tags_has_them_taken_out():
    assert speech_parts(Speech("hi <break/>", "hi <break/>"), "skill")[0] == "hi"


@pytest.mark.parametrize("written, expected", [
    ('<speak xml:lang="en-US">Why? <break/> Because.</speak>',
     '<speak><lang xml:lang="en-US">Why? <break/> Because.</lang></speak>'),
    ("<speak xml:lang='fr-FR'>Oui.<break/></speak>",
     '<speak><lang xml:lang="fr-FR">Oui.<break/></lang></speak>'),
    ('<?xml version="1.0"?><speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis">'
     "Hi <break/> there.</speak>", "<speak>Hi <break/> there.</speak>"),
])
def test_a_whole_document_gets_one_root_and_keeps_its_language(written, expected):
    """SSML forbids a <speak> inside a <speak>; its xml:lang says the same as <lang>."""
    assert Speech(ssml=written).document == expected
    assert speech_parts(written, "skill")[1] == expected
    assert validate(expected) == []
