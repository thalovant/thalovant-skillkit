"""The SSML feature matrix: one row per construct a voice reads, shared by two test files.

`test_ssml_matrix.py` checks each row against the kit alone (the helper, the validator, the
plain words, the escaping). `test_ssml_phoonnx.py` checks the same rows against phoonnx's own
reader, `phoonnx.ssml.parse_ssml`, the one the Thalovant voices use, so a construct the kit
writes and phoonnx does not read (or reads differently from what the kit documents) fails here.

Each `Row` names the construct, builds it with the kit's helper, gives the SSML fragment the
helper must produce and the plain words it must leave, and says what phoonnx must read, per
language: `spoken` is the text of the pieces joined, `lang` the language to read in.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from thalovant_skillkit import ssml
from thalovant_skillkit.ssml import (
    address,
    as_date,
    as_time,
    auto_breaths,
    breath,
    cardinal,
    compress,
    currency,
    digits,
    emphasis,
    expletive,
    foreign,
    fraction,
    interjection,
    mark,
    markup,
    ordinal,
    pause,
    phoneme,
    pitch,
    prosody,
    say,
    soft,
    spell,
    sub,
    telephone,
    unit,
    vocal_tract,
    whisper,
)


@dataclass(frozen=True)
class Row:
    """One construct: how it is built, what it must be, and what a voice reads from it."""

    name: str
    build: Callable[[], Any]
    fragment: str
    plain: str
    #: `{language: words}` the voice must say, pieces joined by a space. A language left
    #: out is not read in that test.
    spoken: dict[str, str] = field(default_factory=dict)
    #: A check on the pieces phoonnx returns (the first language in `spoken`, or en-US).
    pieces: Callable[[list], bool] | None = None
    #: Tags this row exercises, to prove every tag phoonnx reads is covered.
    tags: tuple[str, ...] = ()


def _only(pieces: list) -> Any:
    return pieces[0]


ROWS: list[Row] = [
    Row("pause time", lambda: say("Why?", pause("1s"), "Because."),
        'Why? <break time="1s"/> Because.', "Why? Because.",
        {"en-US": "Why? Because."},
        lambda p: len(p) == 2 and p[1].pause_ms == 1000, ("break",)),
    Row("pause strength", lambda: say("One", pause(strength="strong"), "two"),
        'One <break strength="strong"/> two', "One two", {"en-US": "One two"},
        lambda p: p[1].pause_ms == 750, ("break",)),
    Row("pause default", lambda: say("One", pause(), "two"),
        "One <break/> two", "One two", {"en-US": "One two"},
        lambda p: p[1].pause_ms == 500, ("break",)),
    Row("spell", lambda: spell("XK7"),
        '<say-as interpret-as="characters">XK7</say-as>', "XK7",
        {"en-US": "X K 7", "fr-FR": "X K 7"}, tags=("say-as",)),
    Row("digits", lambda: digits("2048"),
        '<say-as interpret-as="digits">2048</say-as>', "2048",
        {"en-US": "2 0 4 8", "fr-FR": "2 0 4 8"}),
    Row("telephone", lambda: telephone("555-0199"),
        '<say-as interpret-as="telephone">555-0199</say-as>', "555-0199",
        {"en-US": "5 5 5 0 1 9 9"}),
    Row("foreign", lambda: foreign("café au lait", "fr-FR"),
        '<lang xml:lang="fr-FR">café au lait</lang>', "café au lait",
        {"en-US": "café au lait"}, lambda p: p[0].lang == "fr-FR", ("lang",)),
    Row("emphasis", lambda: emphasis("now", "strong"),
        '<emphasis level="strong">now</emphasis>', "now", {"en-US": "now"},
        lambda p: p[0].rate < 1.0 and p[0].volume > 1.0, ("emphasis",)),
    Row("sub", lambda: sub("km/h", "kilometres per hour"),
        '<sub alias="kilometres per hour">km/h</sub>', "kilometres per hour",
        {"en-US": "kilometres per hour"}, tags=("sub",)),
    Row("cardinal", lambda: cardinal("1,200"),
        '<say-as interpret-as="cardinal">1,200</say-as>', "1,200",
        {"en-US": "one thousand, two hundred"}),
    Row("cardinal fr", lambda: cardinal("1 200"),
        '<say-as interpret-as="cardinal">1 200</say-as>', "1 200",
        {"fr-FR": "mille deux cents"}),
    Row("ordinal", lambda: ordinal(3),
        '<say-as interpret-as="ordinal">3</say-as>', "3",
        {"en-US": "third", "fr-FR": "troisième"}),
    Row("fraction", lambda: fraction("1/2"),
        '<say-as interpret-as="fraction">1/2</say-as>', "1/2",
        {"en-US": "one half", "fr-FR": "un demi"}),
    Row("unit", lambda: unit("5 km"),
        '<say-as interpret-as="unit">5 km</say-as>', "5 km",
        {"en-US": "five kilometers", "fr-FR": "cinq kilomètres"}),
    Row("unit degrees", lambda: unit("23 °C"),
        '<say-as interpret-as="unit">23 °C</say-as>', "23 °C",
        {"en-US": "twenty three degrees celsius", "fr-FR": "vingt-trois degrés celsius"}),
    Row("unit speed", lambda: unit("15 km/h"),
        '<say-as interpret-as="unit">15 km/h</say-as>', "15 km/h",
        {"en-US": "fifteen kilometers per hour", "fr-FR": "quinze kilomètres par heure"}),
    Row("unit percent", lambda: unit("10 %"),
        '<say-as interpret-as="unit">10 %</say-as>', "10 %",
        {"en-US": "ten per cent", "fr-FR": "dix pour cent"}),
    Row("currency en", lambda: currency("$12.50"),
        '<say-as interpret-as="currency">$12.50</say-as>', "$12.50",
        {"en-US": "twelve dollars and fifty cents"}),
    Row("currency fr", lambda: currency("3,50 €"),
        '<say-as interpret-as="currency">3,50 €</say-as>', "3,50 €",
        {"fr-FR": "trois euros et cinquante centimes"}),
    Row("address", lambda: address("221 Baker St."),
        '<say-as interpret-as="address">221 Baker St.</say-as>', "221 Baker St.",
        {"en-US": "two twenty one Baker Street"}),
    Row("address fr", lambda: address("12 av. Foch"),
        '<say-as interpret-as="address">12 av. Foch</say-as>', "12 av. Foch",
        {"fr-FR": "douze avenue Foch"}),
    Row("interjection", lambda: interjection("wow"),
        '<say-as interpret-as="interjection">wow</say-as>', "wow", {"en-US": "wow"}),
    Row("expletive", lambda: say("Well", expletive("darn"), "it."),
        'Well <say-as interpret-as="expletive">darn</say-as> it.', "Well darn it.",
        {"en-US": "Well it."},
        lambda p: any(piece.sound and piece.sound[0] == "beep" for piece in p)),
    Row("date en", lambda: as_date("11/09/2026", "mdy"),
        '<say-as interpret-as="date" format="mdy">11/09/2026</say-as>', "11/09/2026",
        {"en-US": "monday, november ninth, twenty twenty six"}),
    Row("date fr", lambda: as_date("09/11/2026", "dmy"),
        '<say-as interpret-as="date" format="dmy">09/11/2026</say-as>', "09/11/2026",
        {"fr-FR": "lundi neuf novembre deux-mille-vingt-six"}),
    Row("date iso", lambda: as_date("2026-11-09"),
        '<say-as interpret-as="date">2026-11-09</say-as>', "2026-11-09",
        {"en-US": "monday, november ninth, twenty twenty six",
         "fr-FR": "lundi neuf novembre deux-mille-vingt-six"}),
    Row("time en", lambda: as_time("7:30 pm"),
        '<say-as interpret-as="time">7:30 pm</say-as>', "7:30 pm",
        {"en-US": "half past seven p.m."}),
    Row("time fr", lambda: as_time("14 h 30"),
        '<say-as interpret-as="time">14 h 30</say-as>', "14 h 30",
        {"fr-FR": "quatorze heures trente"}),
    Row("time 24", lambda: as_time("14:30", "hms24"),
        '<say-as interpret-as="time" format="hms24">14:30</say-as>', "14:30",
        {"fr-FR": "quatorze heures trente"}),
    Row("phoneme ipa", lambda: phoneme("tomato", "təˈmeɪtoʊ"),
        '<phoneme alphabet="ipa" ph="təˈmeɪtoʊ">tomato</phoneme>', "tomato",
        {"en-US": "[[ təˈmeɪtoʊ ]]"}, tags=("phoneme",)),
    Row("phoneme x-sampa", lambda: phoneme("chats", "tS{ts", alphabet="x-sampa"),
        '<phoneme alphabet="x-sampa" ph="tS{ts">chats</phoneme>', "chats",
        {"en-US": "[[ tʃæts ]]"}),
    Row("mark", lambda: say("Wait", mark("here"), "now."),
        'Wait <mark name="here"/> now.', "Wait now.", {"en-US": "Wait now."},
        lambda p: any("here" in piece.marks for piece in p), ("mark",)),
    Row("prosody", lambda: prosody("slowly", rate="slow", pitch="-10%", volume="soft"),
        '<prosody rate="slow" pitch="-10%" volume="soft">slowly</prosody>', "slowly",
        {"en-US": "slowly"},
        lambda p: p[0].rate == 0.8 and p[0].pitch < 0 and p[0].volume == 0.65, ("prosody",)),
    Row("pitch", lambda: pitch("Really?", "+2st"),
        '<prosody pitch="+2st">Really?</prosody>', "Really?", {"en-US": "Really?"},
        lambda p: p[0].pitch == 2.0),
    Row("whisper", lambda: whisper("secret"),
        '<amazon:effect name="whispered">secret</amazon:effect>', "secret",
        {"en-US": "secret"}, lambda p: p[0].effects == ("whisper",), ("amazon:effect",)),
    Row("soft", lambda: soft("gently"),
        '<amazon:effect phonation="soft">gently</amazon:effect>', "gently",
        {"en-US": "gently"}, lambda p: p[0].effects == ("soft",)),
    Row("compress", lambda: compress("evenly"),
        '<amazon:effect name="drc">evenly</amazon:effect>', "evenly",
        {"en-US": "evenly"}, lambda p: p[0].effects == ("drc",)),
    Row("vocal tract", lambda: vocal_tract("deeper", "+20%"),
        '<amazon:effect vocal-tract-length="+20%">deeper</amazon:effect>', "deeper",
        {"en-US": "deeper"}, lambda p: p[0].pitch < 0),
    Row("breath", lambda: say("One.", breath("short"), "Two."),
        'One. <amazon:breath duration="short"/> Two.', "One. Two.",
        {"en-US": "One. Two."},
        lambda p: any(piece.sound and piece.sound[0] == "breath" for piece in p),
        ("amazon:breath",)),
    Row("auto breaths", lambda: auto_breaths("One. Two. Three.", "high"),
        '<amazon:auto-breaths frequency="high">One. Two. Three.</amazon:auto-breaths>',
        "One. Two. Three.", {"en-US": "One. Two. Three."},
        lambda p: p[0].breaths is not None, ("amazon:auto-breaths",)),
    Row("domain", lambda: markup('<amazon:domain name="news">Good evening.</amazon:domain>'),
        '<amazon:domain name="news">Good evening.</amazon:domain>', "Good evening.",
        {"en-US": "Good evening."}, tags=("amazon:domain",)),
    Row("paragraph and sentence", lambda: markup("<p><s>One.</s><s>Two.</s></p><p>Three.</p>"),
        "<p><s>One.</s><s>Two.</s></p><p>Three.</p>", "One. Two. Three.",
        {"en-US": "One. Two. Three."}, lambda p: p[1].pause_ms > 0 and p[2].pause_ms > 0,
        ("p", "s")),
    Row("word", lambda: markup('<w role="amazon:VB">read</w> it'),
        '<w role="amazon:VB">read</w> it', "read it", {"en-US": "read it"}, tags=("w",)),
    Row("voice", lambda: markup('<voice xml:lang="fr-FR">bonjour</voice>'),
        '<voice xml:lang="fr-FR">bonjour</voice>', "bonjour", {"en-US": "bonjour"},
        lambda p: p[0].lang == "fr-FR", ("voice",)),
]

#: Tags the kit refuses on purpose, with the reason it gives. phoonnx reads them as plain
#: words (an `<audio src>` is never fetched), so a skill writing one is told rather than
#: left with silence where it expected a sound.
REFUSED_ON_PURPOSE = {"audio"}

#: Values a skill is handed that must never become markup or break it.
HOSTILE_VALUES = [
    "Tom & Jerry",
    "a < b > c",
    'she said "hi"',
    "it's",
    "&lt;already escaped&gt;",
    "</speak><break time=\"9s\"/>",
    "café 日本語 العربية 🙂",
    "two\nlines\tand   spaces",
    "nul\x00 and \x0b control",
]

#: Helpers that take one text and say it as written, with the SSML each makes.
TEXT_HELPERS: list[tuple[str, Callable[[str], Any]]] = [
    ("spell", spell),
    ("digits", digits),
    ("telephone", telephone),
    ("cardinal", cardinal),
    ("ordinal", ordinal),
    ("fraction", fraction),
    ("unit", unit),
    ("currency", currency),
    ("address", address),
    ("interjection", interjection),
    ("expletive", expletive),
    ("as_date", as_date),
    ("as_time", as_time),
    ("emphasis", emphasis),
    ("foreign", lambda text: foreign(text, "fr-FR")),
    ("sub written", lambda text: sub(text, "spoken")),
    ("sub spoken", lambda text: sub("written", text)),
    ("phoneme", lambda text: phoneme(text, "ˈtɛst")),
    ("prosody", lambda text: prosody(text, rate="90%")),
    ("pitch", lambda text: pitch(text, "+1st")),
    ("whisper", whisper),
    ("soft", soft),
    ("compress", compress),
    ("vocal_tract", lambda text: vocal_tract(text, "+10%")),
    ("auto_breaths", auto_breaths),
    ("say", lambda text: say("Before", text, "after")),
]

#: What the kit must refuse, and the words it must say about it. One precise line each.
MALFORMED: list[tuple[str, str]] = [
    ("<break time='1'/>", 'needs a unit'),
    ("<break time='1 minute'/>", 'needs a unit'),
    ("<break time='-1s'/>", 'is negative'),
    ("<break time='soon'/>", 'is not a duration'),
    ("<break time='11s'/>", 'longer than the 10s'),
    ("<break strength='huge'/>", 'is not one of'),
    ("<break>words</break>", 'takes no words'),
    ("<prosody>x</prosody>", 'needs rate, pitch or volume'),
    ("<prosody rate='quick'>x</prosody>", 'not a named rate'),
    ("<prosody volume='loudish'>x</prosody>", 'not a named volume'),
    ("<prosody pitch='+5Hz'>x</prosody>", 'Hz is not rendered'),
    ("<emphasis level='extreme'>x</emphasis>", 'is not one of'),
    ("<lang>x</lang>", 'needs xml:lang'),
    ("<lang xml:lang='not a tag'>x</lang>", 'is not a language tag'),
    ("<say-as>x</say-as>", 'needs interpret-as'),
    ("<say-as interpret-as='shout'>x</say-as>", 'is not one of'),
    ("<say-as interpret-as='date' format='xyz'>1</say-as>", 'is not a date order'),
    ("<say-as interpret-as='time' format='24'>1</say-as>", 'is not "hms12" or "hms24"'),
    ("<say-as interpret-as='cardinal' format='mdy'>1</say-as>", 'takes no format'),
    ("<say-as interpret-as='digits'><b>1</b></say-as>", 'holds words, not other tags'),
    ("<sub>x</sub>", 'needs alias'),
    ("<phoneme>x</phoneme>", 'needs ph'),
    ("<phoneme ph=''>x</phoneme>", 'is empty'),
    ("<phoneme ph='a ]] b'>x</phoneme>", 'must not contain'),
    ("<phoneme ph='a' alphabet='arpabet'>x</phoneme>", 'must be "ipa" or "x-sampa"'),
    ("<mark/>", 'needs name'),
    ("<amazon:effect>x</amazon:effect>", 'needs name='),
    ("<amazon:effect name='shout'>x</amazon:effect>", 'is not one of'),
    ("<amazon:effect phonation='loud'>x</amazon:effect>", 'must be "soft"'),
    ("<amazon:effect vocal-tract-length='big'>x</amazon:effect>", 'must be a percentage'),
    ("<amazon:auto-breaths frequency='often'>x</amazon:auto-breaths>", 'is not one of'),
    ("<amazon:breath duration='forever'/>", 'is not one of'),
    ("<amazon:emotion name='happy'>x</amazon:emotion>", 'is not read by Thalovant voices'),
    ("<audio src='https://x/y.mp3'/>", 'is not rendered by Thalovant voices'),
    ("<speak>one <speak>two</speak></speak>", 'goes around the whole line'),
    ("<p>unclosed", 'not well-formed XML'),
    ("<break time=1s/>", 'not well-formed XML'),
    ("a & b", 'not well-formed XML'),
    ("<b>bold</b>", 'is not rendered by Thalovant voices'),
]


def covered_tags() -> set[str]:
    """Every tag some row exercises, for the test that no tag phoonnx reads is left out."""
    found = {tag for row in ROWS for tag in row.tags}
    for row in ROWS:
        for tag in ssml.SUPPORTED_TAGS:
            if f"<{tag}" in row.fragment:
                found.add(tag)
    return found
