"""The SSML feature matrix, checked against the kit alone.

Every construct a Thalovant voice reads has a helper that writes it, a validator that accepts
it, one precise message for each way to get it wrong, plain words that need no SSML to say,
and escaping that no value can get out of. `ssml_matrix.py` holds the rows; the same rows are
read by phoonnx's own parser in `test_ssml_phoonnx.py`.
"""
from __future__ import annotations

import re

import pytest
from ssml_matrix import HOSTILE_VALUES, MALFORMED, ROWS, TEXT_HELPERS, covered_tags

from thalovant_skillkit import ssml
from thalovant_skillkit.ssml import (
    Speech,
    markup,
    render_line,
    say,
    speech_parts,
    to_plain,
    validate,
)

ROW_IDS = [row.name for row in ROWS]
ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


@pytest.mark.parametrize("row", ROWS, ids=ROW_IDS)
def test_the_helper_writes_exactly_the_documented_markup(row):
    speech = row.build()
    assert isinstance(speech, Speech)
    assert speech.fragment == row.fragment
    assert speech.plain == row.plain
    assert speech.document == f"<speak>{row.fragment}</speak>"


@pytest.mark.parametrize("row", ROWS, ids=ROW_IDS)
def test_the_validator_accepts_what_the_helper_writes(row):
    assert validate(row.fragment) == []
    assert validate(f"<speak>{row.fragment}</speak>") == []
    assert ssml.looks_like_ssml(row.fragment) or "<" not in row.fragment


@pytest.mark.parametrize("row", ROWS, ids=ROW_IDS)
def test_without_ssml_the_words_still_sound_right(row):
    """A TTS that ignores `utterance_ssml` says `utterance`: words, no tags, no "speak"."""
    speech = row.build()
    text, document = speech_parts(speech)
    assert text == row.plain
    assert "<" not in text and ">" not in text
    assert "speak" not in text.lower().split()
    assert "&amp;" not in text and "&lt;" not in text
    # The plain words are what the markup says once it is read out.
    assert " ".join(to_plain(row.fragment).split()) == " ".join(row.plain.split())
    assert document is None or document.startswith("<speak>")


def test_every_tag_phoonnx_reads_is_written_by_some_row_or_refused_on_purpose():
    from ssml_matrix import REFUSED_ON_PURPOSE

    missing = set(ssml.SUPPORTED_TAGS) - covered_tags()
    assert missing <= {"speak", "voice"} | REFUSED_ON_PURPOSE, missing
    # The tags the kit refuses are exactly the ones its message says it refuses.
    for tag in REFUSED_ON_PURPOSE:
        assert tag not in ssml.SUPPORTED_TAGS
        assert validate(f"<{tag} src='x'/>"), tag


@pytest.mark.parametrize("fragment, message", MALFORMED)
def test_each_way_to_get_it_wrong_has_one_precise_message(fragment, message):
    problems = validate(fragment)
    assert problems, f"{fragment!r} passed"
    assert any(message in problem for problem in problems), problems
    # A message says which tag, not just "invalid".
    assert all(re.search(r"<[\w:-]+|XML|[Hh]ours|speak", problem) for problem in problems), problems


@pytest.mark.parametrize("fragment", ["", "   ", "plain words", "plain 1 &lt; 2 words"])
def test_text_without_markup_is_valid(fragment):
    assert validate(fragment) == []


@pytest.mark.parametrize("value", HOSTILE_VALUES, ids=lambda v: repr(v)[:24])
@pytest.mark.parametrize("name, helper", TEXT_HELPERS, ids=[n for n, _ in TEXT_HELPERS])
def test_no_value_gets_out_of_the_markup(name, helper, value):
    speech = helper(value)
    clean = " ".join(ILLEGAL.sub("", value).split())
    # Well-formed, only the tags the helper meant, nothing the value could add.
    assert validate(speech.fragment) == [], speech.fragment
    assert "</speak>" not in speech.fragment
    assert '<break time="9s"/>' not in speech.fragment
    if name == "sub spoken":
        assert to_plain(speech.fragment) == clean
    elif name == "sub written":
        assert to_plain(speech.fragment, alias=False) == clean
    elif name == "say":
        assert to_plain(speech.fragment) == f"Before {clean} after"
    else:
        assert to_plain(speech.fragment) == clean
    # The words themselves are never changed: that is the plain `utterance`.
    assert speech.plain.count(value) >= 1 or name.startswith("sub")


@pytest.mark.parametrize("value", HOSTILE_VALUES, ids=lambda v: repr(v)[:24])
def test_values_in_markup_templates_and_dialog_lines_are_data(value):
    clean = " ".join(ILLEGAL.sub("", value).split())
    built = markup('<say-as interpret-as="characters">{code}</say-as> and {code}', code=value)
    assert validate(built.fragment) == []
    assert to_plain(built.fragment) == f"{clean} and {clean}"
    line = render_line("Code {code}.", "Code <emphasis>{code}</emphasis>.", {"code": value})
    assert str(line) == f"Code {value}."
    assert validate(line.ssml) == []
    assert to_plain(line.ssml) == f"Code {clean}."
    # A value that is a Speech brings its markup; a plain str never does.
    spoken = render_line("Code {code}.", None, {"code": ssml.spell(value)})
    assert validate(spoken.ssml) == []


def test_a_value_that_looks_like_markup_is_said_not_obeyed():
    line = say("Tell me", "<break time='9s'/> now")
    assert line.plain == "Tell me <break time='9s'/> now"
    assert line.fragment == "Tell me &lt;break time='9s'/&gt; now"
    assert validate(line.fragment) == []
    assert to_plain(line.fragment) == line.plain


def test_a_quote_in_an_attribute_cannot_close_it():
    built = ssml.sub("it's", 'say "hi"')
    assert built.fragment == '<sub alias="say &quot;hi&quot;">it\'s</sub>'
    assert validate(built.fragment) == []
    assert ssml.foreign("x", "fr-FR").fragment == '<lang xml:lang="fr-FR">x</lang>'
    with pytest.raises(ValueError):
        ssml.foreign("x", 'fr" onload="x')
    assert ssml.mark('a"b').fragment == '<mark name="a&quot;b"/>'


def test_what_a_helper_refuses_it_refuses_with_the_validators_words():
    refused = [
        (lambda: ssml.as_date("1", "xyz"), "is not a date order"),
        (lambda: ssml.as_time("1", "24"), 'is not "hms12" or "hms24"'),
        (lambda: ssml.phoneme("x", ""), "is empty"),
        (lambda: ssml.phoneme("x", "a]]b"), "must not contain"),
        (lambda: ssml.phoneme("x", "a", alphabet="arpabet"), 'must be "ipa" or "x-sampa"'),
        (lambda: ssml.prosody("x"), "needs a rate"),
        (lambda: ssml.prosody("x", pitch="+5Hz"), "Hz is not rendered"),
        (lambda: ssml.mark(""), "needs name"),
        (lambda: ssml.breath("forever"), "is not one of"),
        (lambda: ssml.vocal_tract("x", "big"), "must be a percentage"),
        (lambda: ssml.auto_breaths("x", "often"), "is not one of"),
        (lambda: ssml.pause("1"), "needs a unit"),
        (lambda: ssml.pause("11s"), "longer than"),
        (lambda: ssml.emphasis("x", "extreme"), "emphasis level"),
    ]
    for build, message in refused:
        with pytest.raises((ValueError, TypeError)) as caught:
            build()
        assert message in str(caught.value), (message, str(caught.value))


def test_control_characters_are_dropped_from_markup_but_not_from_the_plain_words():
    speech = ssml.spell("A\x00B")
    assert speech.plain == "A\x00B"
    assert speech.fragment == '<say-as interpret-as="characters">AB</say-as>'
    assert validate(speech.fragment) == []
    assert ssml.escape("a\x0bb\ud800c") == "abc"


def test_a_brace_in_a_twin_is_doubled_like_any_format_string(tmp_path):
    """X-SAMPA writes "{" for "ae": in a `.ssml` twin that is `{{`, as in any `str.format` line."""
    from thalovant_skillkit.checks import check_ssml

    package = tmp_path / "thalovant_skill_x"
    dialog = package / "locale" / "en-US" / "dialog"
    dialog.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "thalovant-skill-x"\n')
    (package / "__init__.py").write_text("")
    (dialog / "pets.dialog").write_text("Say chats for {name}.\n")
    (dialog / "pets.ssml").write_text(
        'Say <phoneme alphabet="x-sampa" ph="tS{{ts">chats</phoneme> for {name}.\n')
    assert check_ssml(tmp_path) == []
    line = render_line("Say chats for {name}.",
                       'Say <phoneme alphabet="x-sampa" ph="tS{{ts">chats</phoneme> for {name}.',
                       {"name": "Ada"})
    assert 'ph="tS{ts"' in line.ssml and str(line) == "Say chats for Ada."
