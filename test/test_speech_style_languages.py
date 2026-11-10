"""`auto_twin` in the languages the skills ship: pauses where the language puts them, and
numbers, times, amounts and units wrapped so the voice reads them as its language reads them."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from thalovant_skillkit.ssml import SpeechStyle, auto_twin, to_plain, validate
from thalovant_skillkit.text import fold_words

STYLE = SpeechStyle(sentence_break="300ms", comma_break="200ms", colon_break="250ms",
                    dash_break="250ms")
SENTENCE = SpeechStyle(sentence_break="300ms")
SHARED = Path(__file__).parents[1] / "thalovant_skillkit" / "shared_dialog"


def br(ms: int) -> str:
    return f'<break time="{ms}ms"/>'


# -- where the pauses go -------------------------------------------------------------------

PAUSES = [
    # Scripts that put no space after a full stop: the mark itself is the end of a sentence.
    ("ja-JP", "念のため傘があると安心です。降水確率は {c} パーセントです。",
     f"念のため傘があると安心です。{br(300)}降水確率は {{c}} パーセントです。"),
    ("zh-CN", "{p}气温 {t} 度，体感 {f} 度；最高 {h} 度。明天有雨。",
     f"{{p}}气温 {{t}} 度，{br(200)}体感 {{f}} 度；{br(250)}最高 {{h}} 度。{br(300)}明天有雨。"),
    ("zh-TW", "今天會下雨嗎？不會。", f"今天會下雨嗎？{br(300)}不會。"),
    ("hi-IN", "आज बारिश होगी। छाता ले जाइए।", f"आज बारिश होगी। {br(300)} छाता ले जाइए।"),
    ("ar-SA", "هل سيمطر؟ نعم، خذ مظلة.", f"هل سيمطر؟ {br(300)} نعم، {br(200)} خذ مظلة."),
    ("fa-IR", "فردا باران می‌آید؛ چتر ببر.", f"فردا باران می‌آید؛ {br(250)} چتر ببر."),
    # An abbreviation's full stop is not the end of a sentence.
    ("en-US", "Dr. Smith opens at 9 a.m. on Monday. Come early.",
     f"Dr. Smith opens at 9 a.m. on Monday. {br(300)} Come early."),
    ("en-US", "Ask Mr. Jones or J. R. Smith. Then go.",
     f"Ask Mr. Jones or J. R. Smith. {br(300)} Then go."),
    ("en-US", "It was 9 p.m. Then it rained.", f"It was 9 p.m. {br(300)} Then it rained."),
    ("en-US", "I said no. Then I left.", f"I said no. {br(300)} Then I left."),
    ("en-US", "We left on Nov. 9 for St. Louis. Back soon.",
     f"We left on Nov. 9 for St. Louis. {br(300)} Back soon."),
    ("fr-FR", "Merci M. Dupont. Mme Martin arrive.",
     f"Merci M. Dupont. {br(300)} Mme Martin arrive."),
    ("fr-FR", "Voir p. 5 et av. de la Gare. Fin.", f"Voir p. 5 et av. de la Gare. {br(300)} Fin."),
    ("es-ES", "Habla con la Sra. García. Después, vuelve.",
     f"Habla con la Sra. García. {br(300)} Después, {br(200)} vuelve."),
    # "9. November": a number and a full stop is an ordinal where the language writes it so.
    ("de-DE", "Am 9. November regnet es. Dann nicht.",
     f"Am 9. November regnet es. {br(300)} Dann nicht."),
    ("en-US", "Version 2. Then 3.", f"Version 2. {br(300)} Then 3."),
    # A spaced en dash between numbers is a range, not a pause.
    ("en-US", "Open 9 – 5 daily — except Sunday.", f"Open 9 – 5 daily — {br(250)} except Sunday."),
    # A decimal or a thousands mark is not a clause.
    ("en-US", "It is 3.5 degrees, or 1,200 feet.", f"It is 3.5 degrees, {br(200)} or 1,200 feet."),
]


def _without_say_as(twin: str) -> str:
    return re.sub(r'<say-as interpret-as="\w+">(.*?)</say-as>', r"\1", twin)


@pytest.mark.parametrize("lang, template, expected", PAUSES, ids=[p[1][:30] for p in PAUSES])
def test_the_pauses_follow_the_language_of_the_line(lang, template, expected):
    twin = auto_twin(template, STYLE, lang)
    assert twin is not None
    assert _without_say_as(twin) == expected
    assert validate(twin) == []
    assert fold_words(to_plain(twin)) == fold_words(template)


def test_no_space_is_made_where_the_language_has_none():
    twin = auto_twin("明日は雨です。傘を持って。", SENTENCE, "ja-JP")
    assert twin == f"明日は雨です。{br(300)}傘を持って。"


# -- numbers, times, dates, amounts and units ------------------------------------------------

WRAPPED = [
    ("en-US", "It is 7:30 pm, so wait.",
     f'It is <say-as interpret-as="time">7:30 pm</say-as>, {br(200)} so wait.'),
    ("en-US", "Open at 14:30.", 'Open at <say-as interpret-as="time">14:30</say-as>.'),
    ("fr-FR", "Il est 14 h 30. Venez.",
     f'Il est <say-as interpret-as="time">14 h 30</say-as>. {br(300)} Venez.'),
    ("fr-FR", "Rendez-vous à 14h30.", 'Rendez-vous à <say-as interpret-as="time">14h30</say-as>.'),
    ("en-US", "Bring $12.50 today.",
     'Bring <say-as interpret-as="currency">$12.50</say-as> today.'),
    ("fr-FR", "Cela coûte 3,50 € aujourd'hui.",
     'Cela coûte <say-as interpret-as="currency">3,50 €</say-as> aujourd\'hui.'),
    ("fr-CA", "Cela coûte 12,99 $ ici.",
     'Cela coûte <say-as interpret-as="currency">12,99 $</say-as> ici.'),
    ("en-GB", "It costs £4.20 now.",
     'It costs <say-as interpret-as="currency">£4.20</say-as> now.'),
    ("en-US", "It is 23°C outside.", 'It is <say-as interpret-as="unit">23°C</say-as> outside.'),
    ("fr-FR", "Il fait 23 °C dehors.",
     'Il fait <say-as interpret-as="unit">23 °C</say-as> dehors.'),
    ("fr-FR", "Vent de 15 km/h demain.",
     'Vent de <say-as interpret-as="unit">15 km/h</say-as> demain.'),
    ("en-US", "{chance}% chance of rain.",
     '<say-as interpret-as="unit">{chance}%</say-as> chance of rain.'),
    ("fr-FR", "Risque de pluie : {chance} %.",
     f'Risque de pluie : {br(250)} <say-as interpret-as="unit">{{chance}} %</say-as>.'),
    ("de-DE", "Es sind {t} °C draußen.",
     'Es sind <say-as interpret-as="unit">{t} °C</say-as> draußen.'),
    ("en-US", "On 2026-11-09 or 11/09/2026.",
     'On <say-as interpret-as="date">2026-11-09</say-as> or '
     '<say-as interpret-as="date">11/09/2026</say-as>.'),
    ("en-US", "The 3rd floor and the 21st.",
     'The <say-as interpret-as="ordinal">3rd</say-as> floor and the '
     '<say-as interpret-as="ordinal">21st</say-as>.'),
    ("fr-FR", "Au 1er étage, le 2e.",
     'Au <say-as interpret-as="ordinal">1er</say-as> étage, '
     f'{br(200)} le <say-as interpret-as="ordinal">2e</say-as>.'),
    ("en-US", "About 1,200 people came.",
     'About <say-as interpret-as="cardinal">1,200</say-as> people came.'),
    ("fr-FR", "Environ 1 200 personnes.",
     'Environ <say-as interpret-as="cardinal">1 200</say-as> personnes.'),
]


@pytest.mark.parametrize("lang, template, expected", WRAPPED, ids=[w[1][:30] for w in WRAPPED])
def test_a_literal_quantity_is_read_as_one_in_its_language(lang, template, expected):
    twin = auto_twin(template, STYLE, lang)
    assert twin == expected
    assert validate(twin) == []
    # The plain words are the line itself: a screen and a voice without SSML lose nothing.
    assert fold_words(to_plain(twin)) == fold_words(template)


NOT_WRAPPED = [
    # A comma is the decimal mark in French: "1,200" is one and a fifth, not a thousand.
    ("fr-FR", "Il y a 1,200 mètre."),
    # A bare hour, a plain count, a version and a year are left to the voice.
    ("en-US", "At 9 am or 5 pm, 3 times, version 1.2.3, in 2026."),
    ("de-DE", "Um 5 am Bahnhof, 3 Mal."),
    # Languages phoonnx's say-as has no word tables for are read by the voice as before.
    ("ja-JP", "気温は 23 °C です。14:30 に会います。"),
    ("zh-CN", "气温 23°C，价格 3.5 €"),
    ("hi-IN", "तापमान 23°C है"),
    # No language, no wrapping: the pause rules only.
    (None, "It is 14:30 and 23°C."),
]


@pytest.mark.parametrize("lang, template", NOT_WRAPPED, ids=[n[1][:30] for n in NOT_WRAPPED])
def test_what_the_voice_would_read_worse_is_left_alone(lang, template):
    twin = auto_twin(template, STYLE, lang)
    assert twin is None or "<say-as" not in twin


def test_a_style_can_turn_the_wrapping_off():
    off = SpeechStyle(sentence_break="300ms", say_as=False)
    assert auto_twin("It is 14:30. Go.", off, "en-US") == f"It is 14:30. {br(300)} Go."
    assert auto_twin("It is 14:30.", off, "en-US") is None
    assert "<say-as" in auto_twin("It is 14:30. Go.", SENTENCE, "en-US")


def test_a_quantity_alone_marks_the_line_even_without_any_pause():
    assert auto_twin("It is 14:30.", SpeechStyle(), "en-US") == (
        'It is <say-as interpret-as="time">14:30</say-as>.')
    assert auto_twin("It is 14:30.", SpeechStyle()) is None


def test_a_placeholder_is_never_looked_into():
    twin = auto_twin("Time: {time}. Cost: {price}.", STYLE, "en-US")
    assert twin == f"Time: {br(250)} {{time}}. {br(300)} Cost: {br(250)} {{price}}."


def test_the_words_are_escaped_around_a_wrapped_quantity():
    twin = auto_twin("Tom & Jerry at 14:30 <now>.", SENTENCE, "en-US")
    assert twin == 'Tom &amp; Jerry at <say-as interpret-as="time">14:30</say-as> &lt;now&gt;.'
    assert validate(twin) == []


# -- every dialog the kit ships, in every language it ships them -----------------------------

def _shared_lines():
    for path in sorted(SHARED.glob("*/dialog/*.dialog")):
        lang = path.parent.parent.name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() and not line.lstrip().startswith("#"):
                yield pytest.param(lang, line.strip(), id=f"{lang}-{path.stem}-{number}")


@pytest.mark.parametrize("lang, line", list(_shared_lines()))
def test_every_shipped_line_derives_markup_that_says_the_same_words(lang, line):
    twin = auto_twin(line, STYLE, lang)
    if twin is None:
        return
    assert validate(twin) == [], twin
    assert fold_words(to_plain(twin)) == fold_words(line), twin
