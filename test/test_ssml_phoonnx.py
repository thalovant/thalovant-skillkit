"""What the kit writes, read by phoonnx's own SSML reader: the one the voices use.

Skipped when phoonnx is not installed or is older than its SSML support (1.96.2a2). The CI job
`ssml_phoonnx` installs it, so this file is the proof that the markup the kit writes and the
markup phoonnx reads are the same language. With a voice file at hand (`THALOVANT_TEST_VOICES`
or the workstation's usual folders) the markup is also synthesized end to end.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from ssml_matrix import HOSTILE_VALUES, REFUSED_ON_PURPOSE, ROWS, TEXT_HELPERS

from thalovant_skillkit import ssml
from thalovant_skillkit.ssml import SpeechStyle, auto_twin, render_line, validate

phoonnx_ssml = pytest.importorskip("phoonnx.ssml")
if "pitch" not in getattr(phoonnx_ssml.Piece, "__dataclass_fields__", {}):
    pytest.skip("phoonnx without the SSML parity (1.96.2a2 or later)", allow_module_level=True)

parse_ssml = phoonnx_ssml.parse_ssml
ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
CASES = [(row, lang) for row in ROWS for lang in row.spoken]
CASE_IDS = [f"{row.name}-{lang}" for row, lang in CASES]


def words(pieces) -> str:
    return " ".join(piece.text for piece in pieces if piece.text)


def test_every_tag_phoonnx_reads_is_one_the_kit_accepts_or_refuses_on_purpose():
    unknown = set(phoonnx_ssml.SUPPORTED_TAGS) - set(ssml.SUPPORTED_TAGS) - REFUSED_ON_PURPOSE
    assert unknown == set(), f"phoonnx reads {sorted(unknown)} and the kit does not accept them"


def test_every_interpretation_phoonnx_says_is_one_the_kit_accepts():
    from phoonnx import ssml_say_as

    said = set(ssml_say_as.SPELLED) | set(ssml_say_as.DIGITS) | {
        "cardinal", "number", "ordinal", "fraction", "unit", "date", "time", "currency",
        "address", "expletive", "interjection"}
    assert said <= ssml.SAY_AS, sorted(said - ssml.SAY_AS)


@pytest.mark.parametrize("row, lang", CASES, ids=CASE_IDS)
def test_phoonnx_reads_the_helpers_markup_as_documented(row, lang):
    pieces = parse_ssml(row.build().document, lang)
    assert words(pieces) == row.spoken[lang]
    if row.pieces is not None:
        assert row.pieces(pieces), pieces


@pytest.mark.parametrize("value", HOSTILE_VALUES, ids=lambda v: repr(v)[:24])
@pytest.mark.parametrize("name, helper", TEXT_HELPERS, ids=[n for n, _ in TEXT_HELPERS])
def test_no_value_reaches_phoonnx_as_markup(name, helper, value):
    speech = helper(value)
    document = speech.document or f"<speak>{speech.fragment}</speak>"
    pieces = parse_ssml(document, "en-US")
    # Not one pause, mark or sound came from what the value said (some helpers add their own).
    assert not any(piece.marks for piece in pieces)
    if name not in ("expletive",):
        assert not any(piece.sound for piece in pieces)
    assert not any(piece.pause_ms for piece in pieces)
    clean = " ".join(ILLEGAL.sub("", value).split())
    as_written = ("emphasis", "foreign", "prosody", "pitch", "whisper", "soft", "compress",
                  "vocal_tract", "auto_breaths", "interjection", "say")
    if name in as_written and any(ch.isalnum() for ch in clean):
        said = words(pieces)
        assert clean in said or name == "say" and clean in said.replace("Before ", "")


@pytest.mark.parametrize("fragment", [
    "<speak>Hello <w>there</w>.</speak>",
    '<speak xml:lang="fr-FR">Bonjour</speak>',
    "Hello world",
])
def test_markup_phoonnx_reads_as_words_is_accepted_by_the_kit_too(fragment):
    assert validate(fragment) == [] or "<w>" in fragment and validate(fragment) == []
    assert words(parse_ssml(fragment, "en-US"))


# -- what SPEECH_STYLE derives, read the way a voice reads it ----------------------------------

STYLE = SpeechStyle(sentence_break="300ms", comma_break="200ms", colon_break="250ms")

READINGS = [
    # lang, template, values, the words, the pause before each piece after the first
    ("en-US", "Dinner is at 7:30 pm, then bed. Sleep well.", {},
     ["Dinner is at half past seven p.m.,", "then bed.", "Sleep well."], [200, 300]),
    ("en-US", "It costs $12.50 on 11/09/2026.", {},
     ["It costs twelve dollars and fifty cents on monday, november ninth, twenty twenty six."],
     []),
    ("en-US", "It is 23°C. {chance}% chance of rain.", {"chance": "30"},
     ["It is twenty three degrees celsius.", "thirty per cent chance of rain."], [300]),
    ("en-US", "The 3rd floor, 1,200 people.", {},
     ["The third floor,", "one thousand, two hundred people."], [200]),
    ("en-US", "Open at 9 a.m. on Monday. Come early.", {},
     ["Open at 9 a.m. on Monday.", "Come early."], [300]),
    ("fr-FR", "Il est 14 h 30. Prenez un parapluie.", {},
     ["Il est quatorze heures trente.", "Prenez un parapluie."], [300]),
    ("fr-FR", "Cela coûte 3,50 €. Merci M. Dupont, bonne journée.", {},
     ["Cela coûte trois euros et cinquante centimes.", "Merci M. Dupont,", "bonne journée."],
     [300, 200]),
    ("fr-FR", "Il fait 23 °C. Risque de pluie : {chance} %.", {"chance": "30"},
     ["Il fait vingt-trois degrés celsius.", "Risque de pluie:", "trente pour cent."], [300, 250]),
    ("fr-FR", "C'est le 1er étage.", {}, ["C'est le premier étage."], []),
    ("fr-CA", "Rendez-vous à 14:30, le 09/11/2026.", {},
     ["Rendez-vous à quatorze heures trente,", "le lundi neuf novembre deux-mille-vingt-six."],
     [200]),
]


@pytest.mark.parametrize("lang, template, values, expected, pauses", READINGS,
                         ids=[f"{r[0]}-{r[1][:28]}" for r in READINGS])
def test_a_derived_line_is_read_in_the_words_of_its_language(lang, template, values, expected,
                                                            pauses):
    twin = auto_twin(template, STYLE, lang)
    assert twin is not None
    line = render_line(template, twin, values)
    assert validate(line.ssml) == [], line.ssml
    pieces = parse_ssml(line.document, lang)
    assert [piece.text for piece in pieces] == expected
    assert [piece.pause_ms for piece in pieces[1:]] == pauses
    # And a voice without SSML says the plain line, tags nowhere.
    assert "<" not in str(line)


# -- end to end, with a real voice when there is one ------------------------------------------

VOICE_FOLDERS = [
    os.environ.get("THALOVANT_TEST_VOICES", ""),
    "/home/gtrellu/Development/SmartGic/debug/tts-eval-work/voices-hfc",
    "/home/gtrellu/Development/SmartGic/debug/tts-eval-work/frteach/voices/stock",
    "/home/gtrellu/Development/SmartGic/debug/tts-eval-work/voices-en2",
]


def _voice(prefix: str):
    for folder in VOICE_FOLDERS:
        if folder:
            for path in sorted(Path(folder).glob(f"{prefix}*.onnx")):
                if path.with_suffix(".onnx.json").exists():
                    from phoonnx.voice import TTSVoice

                    return TTSVoice.load(str(path), use_cuda=False)
    return None


@pytest.fixture(scope="module", params=["en_US", "fr_FR"])
def voice(request):
    found = _voice(request.param)
    if found is None:
        pytest.skip(f"no {request.param} voice file here (set THALOVANT_TEST_VOICES)")
    return request.param.replace("_", "-"), found


def _rows_for(lang: str):
    return [row for row in ROWS if lang in row.spoken or (lang == "en-US" and not row.spoken)]


def test_every_helper_renders_to_audio_through_a_real_voice(voice):
    lang, found = voice
    heard = 0
    for row in _rows_for(lang):
        chunks = list(found.synthesize_ssml(row.build().document, lang=lang))
        samples = sum(len(chunk.audio_float_array) for chunk in chunks)
        assert samples > 0, row.name
        assert all(chunk.audio_float_array.size == 0
                   or abs(chunk.audio_float_array).max() <= 1.5 for chunk in chunks), row.name
        heard += 1
    assert heard >= 8


def test_a_derived_line_renders_to_audio_through_a_real_voice(voice):
    lang, found = voice
    for reading_lang, template, values, _expected, _pauses in READINGS:
        if reading_lang.split("-")[0] != lang.split("-")[0]:
            continue
        line = render_line(template, auto_twin(template, STYLE, reading_lang), values)
        chunks = list(found.synthesize_ssml(line.document, lang=lang))
        assert sum(len(chunk.audio_float_array) for chunk in chunks) > 0, template
