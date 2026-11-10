"""Speech markup (SSML) that travels beside the plain words, never inside them.

A reply is sent as `utterance`, the plain words every client can say or show,
and may carry `utterance_ssml` beside it: the same words with pauses, spelling
and languages marked up. thalovant-voice reads the markup. The Android app and
the Kotlin SDK read only `utterance`, and a tag written into it is shown and
said as the tag itself. So markup never goes into `utterance`, and the two
always say the same words.

There are three ways to add markup, from least to most code:

* A `.ssml` twin beside a dialog: `locale/<lang>/dialog/joke.ssml` next to
  `joke.dialog`, line for line, with the same `{placeholders}`. Speaking
  `joke` sends both, rendered from the same line and the same data.
* A value that knows how it should be said, passed as dialog data:
  `self.speak_dialog("code", {"code": spell(code)})` spells the code even
  when `code.dialog` has no twin, in every language the skill has.
* A sentence built in Python: `say("Why?", pause("1s"), "Because.")`.

Each of these returns a `Speech`: a `str` whose text is the plain words and
whose `.ssml` is the marked-up version. A Speech can go anywhere a string
goes, and code that only understands strings gets the plain words.

Why `.ssml` and not `.ssml.dialog`: OVOS reads every `*.dialog` as a plain
template in which `<name>` names a vocabulary. Its renderer loads
`joke.ssml.dialog` as a dialog called `joke.ssml` and raises on the first
`<break/>`, and `ovos-spec-lint` reports two errors for the file. OVOS
ignores a `.ssml` file, and so does anything that translates `*.dialog`.
"""
from __future__ import annotations

import html
import logging
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from string import Formatter
from typing import Any

__all__ = [
    "SSML_KEY",
    "SUPPORTED_TAGS",
    "Speech",
    "SpeechStyle",
    "address",
    "as_date",
    "as_time",
    "auto_breaths",
    "auto_twin",
    "breath",
    "cardinal",
    "compress",
    "currency",
    "expletive",
    "fraction",
    "interjection",
    "mark",
    "ordinal",
    "phoneme",
    "pitch",
    "prosody",
    "soft",
    "unit",
    "vocal_tract",
    "whisper",
    "carries_markup",
    "digits",
    "emphasis",
    "escape",
    "foreign",
    "looks_like_ssml",
    "markup",
    "pause",
    "render_line",
    "say",
    "speech_parts",
    "spell",
    "strip_tags",
    "sub",
    "telephone",
    "to_plain",
    "validate",
]

LOG = logging.getLogger(__name__)

#: Where the markup travels in a speak message's data.
SSML_KEY = "utterance_ssml"

#: What Thalovant's voices render, and the attributes each tag may carry.
#: Anything else is read as plain words by thalovant-voice, and the check
#: reports it, so nobody writes markup that does nothing.
SUPPORTED_TAGS: dict[str, frozenset[str]] = {
    "speak": frozenset({"xml:lang"}),
    "break": frozenset({"time", "strength"}),
    "p": frozenset(),
    "s": frozenset(),
    "prosody": frozenset({"rate", "volume", "pitch"}),
    "emphasis": frozenset({"level"}),
    "lang": frozenset({"xml:lang"}),
    "voice": frozenset({"xml:lang"}),
    "say-as": frozenset({"interpret-as", "format", "detail"}),
    "sub": frozenset({"alias"}),
    "w": frozenset({"role"}),
    "phoneme": frozenset({"alphabet", "ph"}),
    "mark": frozenset({"name"}),
    "amazon:effect": frozenset({"name", "phonation", "vocal-tract-length"}),
    "amazon:auto-breaths": frozenset({"volume", "frequency", "duration"}),
    "amazon:breath": frozenset({"volume", "duration"}),
    "amazon:domain": frozenset({"name"}),
}
SAY_AS = frozenset({"characters", "spell-out", "digits", "telephone", "cardinal", "number",
                    "ordinal", "fraction", "unit", "date", "time", "currency", "address",
                    "expletive", "interjection", "letters", "verbatim"})
BREAK_STRENGTHS = frozenset({"none", "x-weak", "weak", "medium", "strong", "x-strong"})
RATES = frozenset({"x-slow", "slow", "medium", "fast", "x-fast", "default"})
VOLUMES = frozenset({"silent", "x-soft", "soft", "medium", "loud", "x-loud", "default"})
PITCHES = frozenset({"x-low", "low", "medium", "high", "x-high", "default"})
EMPHASIS_LEVELS = frozenset({"strong", "moderate", "reduced", "none"})
ALPHABETS = frozenset({"ipa", "x-sampa"})
EFFECT_NAMES = frozenset({"whispered", "drc"})
PHONATIONS = frozenset({"soft"})
BREATH_FREQUENCIES = frozenset({"off", "x-low", "low", "medium", "high", "x-high", "default"})
BREATH_DURATIONS = frozenset({"x-short", "short", "medium", "long", "x-long", "default"})
#: thalovant-voice caps a pause at ten seconds; a longer one reads as a hang.
MAX_BREAK_MS = 10_000

_XML_NS = "{http://www.w3.org/XML/1998/namespace}"
# A complete tag with one of the names an SSML reader knows, including the
# ones thalovant-voice reads as plain words. A '<' in a sentence, `x < y`,
# or an OVOS `<vocabulary>` reference is not one.
_TAG = re.compile(
    r"<\s*/?\s*(?:speak|break|prosody|emphasis|say-as|sub|phoneme|lang|voice|p|s|audio|mark|w"
    r"|amazon:[a-z-]+)(?:\s[^<>]*)?/?\s*>",
    re.IGNORECASE,
)
_ANY_TAG = re.compile(r"<[^<>]*>")
# `<amazon:effect>` and friends: a namespace prefix nobody declares.
_PREFIXED = re.compile(r"<\s*/?\s*([A-Za-z][\w.-]*):([\w.-]+)")
_SPEAK_ROOT = re.compile(r"^\s*<speak(\s[^<>]*)?>(.*)</speak>\s*$", re.DOTALL)
_XML_LANG_ATTRIBUTE = re.compile(r"""\bxml:lang\s*=\s*(["'])(.*?)\1""")
_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s)\s*$")
_PERCENT = re.compile(r"^[+-]?\d+(?:\.\d+)?%$")
_SEMITONES = re.compile(r"^[+-]?\d+(?:\.\d+)?st$")
_DATE_FORMAT = re.compile(r"^(?:ymd|ydm|mdy|myd|dmy|dym|ym|my|md|dm|y|m|d)$")
_TIME_FORMATS = frozenset({"hms12", "hms24"})
#: `<amazon:effect>` and friends are read; any other prefix nobody declares is not.
_AMAZON = re.compile(r"(<\s*/?\s*)amazon:([A-Za-z-]+)", re.IGNORECASE)
_PREFIXED_OK = frozenset(name for name in SUPPORTED_TAGS if name.startswith("amazon:"))
_DECIBELS = re.compile(r"^[+-]?\d+(?:\.\d+)?dB$", re.IGNORECASE)
_LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")
_BOUNDARY = "\x00"


# -- escaping -----------------------------------------------------------------

# Characters XML 1.0 cannot carry at all, not even as an entity: a NUL or a stray escape
# byte in a value from a service would make the whole line "not well-formed" and cost the
# reply its markup. They are said as nothing, which is what a voice would do with them.
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def escape(value: Any) -> str:
    """`value` as text that is safe anywhere in SSML, attribute values included."""
    return (_XML_ILLEGAL.sub("", str(value)).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def _entities(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_text(text: str) -> str:
    """Words for an element's text. Quotes stay readable there."""
    return _entities(_XML_ILLEGAL.sub("", text))


# -- reading markup ----------------------------------------------------------

def looks_like_ssml(text: Any) -> bool:
    """Whether `text` holds an SSML tag, rather than a '<' in a sentence."""
    return isinstance(text, str) and bool(_TAG.search(text))


def _inner(ssml: str) -> str:
    """The markup without an XML declaration or the `<speak>` around it.

    `utterance_ssml` gets exactly one `<speak>`, added when it is sent, so a
    root the author or a service wrote is taken off here rather than nested
    inside it, which SSML forbids. Its `xml:lang` is kept as a `<lang>`
    around the words, which says the same thing; `version` and `xmlns` have
    nothing to say once the words are inside the kit's own root.
    """
    source = _DECLARATION.sub("", ssml or "").strip()
    match = _SPEAK_ROOT.match(source)
    if not match:
        return source
    attributes, words = match.group(1) or "", match.group(2)
    lang = _XML_LANG_ATTRIBUTE.search(attributes)
    if lang:
        return f'<lang xml:lang="{escape(lang.group(2))}">{words}</lang>'
    return words


def _namespaced(source: str) -> str:
    """`source` with the prefixed tags the kit reads (`amazon:effect`) made parseable.

    XML refuses a prefix nobody declared, so `amazon:effect` is parsed as
    `amazon-effect`; `_local` turns the name back.
    """
    return _AMAZON.sub(lambda m: f"{m.group(1)}amazon-{m.group(2)}"
                       if f"amazon:{m.group(2).lower()}" in _PREFIXED_OK else m.group(0), source)


def _parse(fragment: str) -> ET.Element | None:
    try:
        return ET.fromstring(f"<speak>{_namespaced(fragment)}</speak>")
    except ET.ParseError:
        return None


def _local(tag: Any) -> str:
    name = str(tag).rsplit("}", 1)[-1].lower()
    return "amazon:" + name[len("amazon-"):] if name.startswith("amazon-") else name


def _normalize(text: str) -> str:
    return " ".join(text.replace(_BOUNDARY, " ").split())


def strip_tags(text: str) -> str:
    """`text` with anything shaped like a tag removed and entities read."""
    return _normalize(html.unescape(_ANY_TAG.sub(" ", text or "")))


#: Marks of the scripts that write no space after them (CJK, Devanagari, Arabic, Armenian ...).
_BARE_MARKS = frozenset("。！？｡؟۔।॥։።။។‼⁇⁈⁉，、､،၊：；؛」』）】》〉")


def to_plain(ssml: str, *, alias: bool = True) -> str:
    """The words of an SSML string: what `utterance` should say.

    A `<sub>` gives its alias, the form it asks to be spoken as; with
    `alias=False` it gives the written text instead. A `<say-as>` keeps the
    text as written: how "XK7" or "2026" is read aloud depends on the
    language and the voice, and the plain text is also what a screen shows.
    Pauses, sentences and paragraphs become single spaces. Markup that does
    not parse loses its tags and keeps its words.
    """
    root = _parse(_inner(ssml))
    if root is None:
        return strip_tags(ssml)
    parts: list[str] = []

    def walk(element: ET.Element) -> None:
        tag = _local(element.tag)
        if tag == "break":
            # "。<break/>ソース": the pause paces the voice, it is not a space in the words.
            # A script that writes no space after its mark must read back as written.
            if not (parts and parts[-1][-1:] in _BARE_MARKS):
                parts.append(_BOUNDARY)
            return
        if tag == "sub":
            spoken = element.get("alias")
            parts.append(spoken if alias and spoken is not None else "".join(element.itertext()))
            return
        edge = tag in ("p", "s")
        if edge:
            parts.append(_BOUNDARY)
        if element.text:
            parts.append(element.text)
        for child in element:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if edge:
            parts.append(_BOUNDARY)

    walk(root)
    return _normalize("".join(parts))


def _attribute_name(name: str) -> str:
    return "xml:" + name[len(_XML_NS):] if name.startswith(_XML_NS) else name


def _duration_ms(value: str) -> float | None:
    match = _DURATION.match(value)
    if not match:
        return None
    number = float(match.group(1))
    return number * 1000 if match.group(2) == "s" else number


def validate(ssml: str) -> list[str]:
    """What is wrong with `ssml` for a Thalovant voice, or [] when nothing is.

    Well-formed XML, only the tags and attributes in `SUPPORTED_TAGS`, and
    values a voice can use. A value holding a `{placeholder}` is filled in
    later and is not judged here. The markup may be wrapped in `<speak>` or
    not.
    """
    source = _DECLARATION.sub("", ssml or "").strip()
    prefixed = sorted({f"{m.group(1)}:{m.group(2)}" for m in _PREFIXED.finditer(source)
                       if m.group(1).lower() != "xml"
                       and f"{m.group(1)}:{m.group(2)}".lower() not in _PREFIXED_OK})
    if prefixed:
        return [f"<{name}> is not read by Thalovant voices" for name in prefixed]
    source = _namespaced(source)
    wrapped = not re.match(r"<\s*speak\b", source)
    try:
        root = ET.fromstring(f"<speak>{source}</speak>" if wrapped else source)
    except ET.ParseError as failure:
        line, column = getattr(failure, "position", (1, 0))
        if wrapped and line == 1:
            column = max(0, column - len("<speak>"))
        reason = str(failure).split(":", 1)[0]
        return [f"not well-formed XML: {reason} at column {column + 1}"]

    problems: list[str] = []
    for element in root.iter():
        tag = _local(element.tag)
        if tag not in SUPPORTED_TAGS:
            problems.append(f"<{tag}> is not rendered by Thalovant voices; use one of "
                            + ", ".join(sorted(SUPPORTED_TAGS)))
            continue
        if tag == "speak" and element is not root:
            problems.append("<speak> goes around the whole line, not inside it")
        attributes = {_attribute_name(name): value for name, value in element.attrib.items()}
        for name in sorted(attributes.keys() - SUPPORTED_TAGS[tag]):
            problems.append(f"<{tag}> takes no {name!r} attribute")
        problems.extend(_value_problems(tag, element, attributes))
    return problems


def _value_problems(tag: str, element: ET.Element, attributes: dict[str, str]) -> list[str]:
    def given(name: str) -> str | None:
        value = attributes.get(name)
        # A placeholder is data; the rendered line is checked when it is sent.
        return None if value is None or "{" in value else value.strip()

    problems: list[str] = []
    if tag == "break":
        if len(element) or (element.text or "").strip():
            problems.append("<break> takes no words; close it with <break/>")
        time = given("time")
        if time is not None:
            ms = _duration_ms(time)
            if ms is None:
                if time.startswith("-"):
                    problems.append(f'<break time="{time}"> is negative; a pause cannot be')
                elif re.match(r"\d+(?:\.\d+)?", time):
                    problems.append(f'<break time="{time}"> needs a unit, as in "500ms" or "1s"')
                else:
                    problems.append(f'<break time="{time}"> is not a duration such as "500ms" '
                                    'or "1.5s"')
            elif ms > MAX_BREAK_MS:
                problems.append(f'<break time="{time}"> is longer than the 10s a voice allows')
        strength = given("strength")
        if strength is not None and strength not in BREAK_STRENGTHS:
            problems.append(f'<break strength="{strength}"> is not one of '
                            + ", ".join(sorted(BREAK_STRENGTHS)))
    elif tag == "prosody":
        rate, volume = given("rate"), given("volume")
        if not ({"rate", "volume", "pitch"} & attributes.keys()):
            problems.append("<prosody> needs rate, pitch or volume, or it changes nothing")
        if rate is not None and rate not in RATES and not _PERCENT.match(rate):
            problems.append(f'<prosody rate="{rate}"> is not a named rate or a percentage')
        if volume is not None and volume not in VOLUMES and not _DECIBELS.match(volume):
            problems.append(f'<prosody volume="{volume}"> is not a named volume or dB change')
        pitch = given("pitch")
        if pitch is not None and pitch not in PITCHES and not _PERCENT.match(pitch) \
                and not _SEMITONES.match(pitch):
            problems.append(f'<prosody pitch="{pitch}"> is not a named pitch, a percentage or '
                            "semitones such as \"+2st\" (Hz is not rendered)")
    elif tag == "emphasis":
        level = given("level")
        if level is not None and level not in EMPHASIS_LEVELS:
            problems.append(f'<emphasis level="{level}"> is not one of '
                            + ", ".join(sorted(EMPHASIS_LEVELS)))
    elif tag in ("lang", "voice"):
        if "xml:lang" not in attributes:
            problems.append(f'<{tag}> needs xml:lang, as in <{tag} xml:lang="fr-FR">')
        else:
            code = given("xml:lang")
            if code is not None and not _LANG_TAG.match(code):
                problems.append(f'<{tag} xml:lang="{code}"> is not a language tag')
    elif tag == "say-as":
        kind = attributes.get("interpret-as")
        if kind is None:
            problems.append("<say-as> needs interpret-as")
        elif "{" not in kind and kind not in SAY_AS:
            problems.append(f'<say-as interpret-as="{kind}"> is not one of '
                            + ", ".join(sorted(SAY_AS)))
        if len(element):
            problems.append("<say-as> holds words, not other tags")
        fmt = given("format")
        if fmt is not None and kind is not None and "{" not in kind \
                and kind not in ("date", "time"):
            problems.append(f'<say-as interpret-as="{kind}"> takes no format; '
                            "format is for date and time")
        if fmt is not None and kind == "date" and not _DATE_FORMAT.match(fmt.lower()):
            problems.append(f'<say-as format="{fmt}"> is not a date order such as "mdy" or "dmy"')
        if fmt is not None and kind == "time" and fmt.lower() not in _TIME_FORMATS:
            problems.append(f'<say-as format="{fmt}"> is not "hms12" or "hms24"')
    elif tag == "sub":
        if "alias" not in attributes:
            problems.append("<sub> needs alias, the words to say instead")
        if len(element):
            problems.append("<sub> holds words, not other tags")
    elif tag == "phoneme":
        if "ph" not in attributes:
            problems.append("<phoneme> needs ph, the pronunciation in IPA or X-SAMPA")
        elif "{" not in attributes["ph"] and not attributes["ph"].strip():
            problems.append("<phoneme ph> is empty; write the pronunciation in IPA or X-SAMPA")
        elif "[[" in attributes["ph"] or "]]" in attributes["ph"]:
            problems.append("<phoneme ph> must not contain [[ or ]], which a voice reads as "
                            "the start and end of phonemes")
        if len(element):
            problems.append("<phoneme> holds words, not other tags")
        alphabet = given("alphabet")
        if alphabet is not None and alphabet.lower() not in ALPHABETS:
            problems.append(f'<phoneme alphabet="{alphabet}"> must be "ipa" or "x-sampa"')
    elif tag == "mark":
        if not attributes.get("name"):
            problems.append("<mark> needs name, the label the event carries")
    elif tag == "amazon:effect":
        name, phonation = given("name"), given("phonation")
        tract = given("vocal-tract-length")
        if name is None and phonation is None and tract is None:
            problems.append('<amazon:effect> needs name="whispered" or "drc", phonation="soft" '
                            "or vocal-tract-length")
        if name is not None and name not in EFFECT_NAMES:
            problems.append(f'<amazon:effect name="{name}"> is not one of '
                            + ", ".join(sorted(EFFECT_NAMES)))
        if phonation is not None and phonation not in PHONATIONS:
            problems.append(f'<amazon:effect phonation="{phonation}"> must be "soft"')
        if tract is not None and not _PERCENT.match(tract):
            problems.append(f'<amazon:effect vocal-tract-length="{tract}"> must be a percentage '
                            'such as "+10%"')
    elif tag == "amazon:auto-breaths":
        frequency, duration, volume = given("frequency"), given("duration"), given("volume")
        if frequency is not None and frequency not in BREATH_FREQUENCIES:
            problems.append(f'<amazon:auto-breaths frequency="{frequency}"> is not one of '
                            + ", ".join(sorted(BREATH_FREQUENCIES)))
        if duration is not None and duration not in BREATH_DURATIONS:
            problems.append(f'<amazon:auto-breaths duration="{duration}"> is not one of '
                            + ", ".join(sorted(BREATH_DURATIONS)))
        if volume is not None and volume not in VOLUMES and not _DECIBELS.match(volume):
            problems.append(f'<amazon:auto-breaths volume="{volume}"> is not a named volume '
                            "or dB change")
    elif tag == "amazon:breath":
        if len(element) or (element.text or "").strip():
            problems.append("<amazon:breath> takes no words; close it with <amazon:breath/>")
        duration = given("duration")
        if duration is not None and duration not in BREATH_DURATIONS:
            problems.append(f'<amazon:breath duration="{duration}"> is not one of '
                            + ", ".join(sorted(BREATH_DURATIONS)))
    return problems


def _well_formed(fragment: str) -> bool:
    return _parse(fragment) is not None


# -- the value ---------------------------------------------------------------

class Speech(str):
    """Plain words that may carry SSML for the same words.

    The string itself is the plain text: what `utterance` says and what a
    screen shows. `.ssml` is the marked-up fragment, or None when there is
    no markup; `.document` wraps it in `<speak>` for `utterance_ssml`.

    `+` keeps both sides, in either order. `str` methods, f-strings and
    `str.format` return plain `str` and drop the markup, which is always
    safe: the plain words are still right. Two Speech values are equal when
    their words are.
    """

    _fragment: str

    def __new__(cls, plain: str | None = None, ssml: str | None = None):
        fragment = _inner(ssml) if ssml else None
        if plain is None:
            plain = to_plain(fragment) if fragment else ""
        self = super().__new__(cls, plain)
        self._fragment = fragment if fragment is not None else _escape_text(str(plain))
        return self

    @property
    def plain(self) -> str:
        """The words, as an ordinary `str`."""
        return str.__str__(self)

    @property
    def fragment(self) -> str:
        """The SSML without `<speak>`: the escaped words when there is no markup."""
        return self._fragment

    @property
    def ssml(self) -> str | None:
        """The SSML fragment, or None when these words carry no markup."""
        # Text is escaped on the way in, so any '<' left is a tag.
        return self._fragment if "<" in self._fragment else None

    @property
    def document(self) -> str | None:
        """`<speak>...</speak>` for `utterance_ssml`, or None without markup."""
        return f"<speak>{self._fragment}</speak>" if self.ssml else None

    def __add__(self, other: Any):
        if not isinstance(other, str):
            return NotImplemented
        return _join((self, other), "")

    def __radd__(self, other: Any):
        if not isinstance(other, str):
            return NotImplemented
        return _join((other, self), "")

    def __reduce__(self):
        return (Speech, (self.plain, self._fragment))

    def __repr__(self) -> str:
        return f"Speech({self.plain!r}, ssml={self.ssml!r})"


def _part(value: Any) -> tuple[str, str]:
    """(plain, fragment) for one piece of a sentence."""
    if value is None:
        return "", ""
    if isinstance(value, Speech):
        return value.plain, value.fragment
    text = str(value)
    return text, _escape_text(text)


def _join(parts, sep: str) -> Speech:
    plains: list[str] = []
    fragments: list[str] = []
    for part in parts:
        plain, fragment = _part(part)
        if plain:
            plains.append(plain)
        if fragment:
            fragments.append(fragment)
    return Speech(sep.join(plains), sep.join(fragments))


def carries_markup(values: Mapping[str, Any] | None) -> bool:
    """Whether any of these dialog values is a Speech with markup."""
    return any(isinstance(value, Speech) and value.ssml for value in (values or {}).values())


# -- building a sentence -----------------------------------------------------

def say(*parts: Any, sep: str = " ") -> Speech:
    """One sentence from words and marked-up pieces, joined by spaces.

    A plain string is words: it is escaped in the SSML, never read as
    markup, so text from a user or a service cannot add tags. Use the
    helpers here, or `markup()`, for tags. `None` and empty parts are left
    out, and a pause adds no words to the plain text.

        say("Why did the chicken cross the road?", pause("1s"),
            "To get to the other side.")
    """
    return _join(parts, sep)


def pause(duration: str | None = None, *, strength: str | None = None) -> Speech:
    """A silence: `pause("1s")`, `pause("750ms")`, or `pause(strength="strong")`.

    With neither, a medium pause. A number without a unit is refused rather
    than guessed, since SSML has no default unit and "1" could mean either.
    """
    if duration is not None and strength is not None:
        raise ValueError("pause takes a duration or a strength, not both")
    if duration is not None:
        if not isinstance(duration, str):
            raise TypeError(f"write the unit: pause('{duration}ms') or pause('{duration}s')")
        ms = _duration_ms(duration)
        if ms is None:
            raise ValueError(f"pause({duration!r}) needs a unit, as in '500ms' or '1s'")
        if ms > MAX_BREAK_MS:
            raise ValueError(f"pause({duration!r}) is longer than the 10s a voice allows")
        return Speech("", f'<break time="{duration.strip()}"/>')
    if strength is not None:
        if strength not in BREAK_STRENGTHS:
            raise ValueError(f"pause strength must be one of {sorted(BREAK_STRENGTHS)}")
        return Speech("", f'<break strength="{strength}"/>')
    return Speech("", "<break/>")


def _say_as(text: Any, kind: str) -> Speech:
    plain = _part(text)[0]
    return Speech(plain, f'<say-as interpret-as="{kind}">{_escape_text(plain)}</say-as>')


def spell(text: Any) -> Speech:
    """Say `text` one character at a time: a code, a call sign, an acronym."""
    return _say_as(text, "characters")


def digits(text: Any) -> Speech:
    """Say each digit of `text`: "2 0 4 8", not "two thousand forty-eight"."""
    return _say_as(text, "digits")


def telephone(text: Any) -> Speech:
    """Say `text` as a phone number, digit by digit."""
    return _say_as(text, "telephone")


def foreign(text: Any, lang: str) -> Speech:
    """Say `text` in another language's voice: `foreign("croissant", "fr-FR")`."""
    code = str(lang or "").strip()
    if not _LANG_TAG.match(code):
        raise ValueError(f"{lang!r} is not a language tag such as 'fr-FR'")
    plain, fragment = _part(text)
    return Speech(plain, f'<lang xml:lang="{escape(code)}">{fragment}</lang>')


def emphasis(text: Any, level: str = "moderate") -> Speech:
    """Say `text` with weight: a little slower and a little louder."""
    if level not in EMPHASIS_LEVELS:
        raise ValueError(f"emphasis level must be one of {sorted(EMPHASIS_LEVELS)}")
    plain, fragment = _part(text)
    return Speech(plain, f'<emphasis level="{level}">{fragment}</emphasis>')


def sub(written: Any, spoken: Any) -> Speech:
    """Write `written`, say `spoken`: `sub("km/h", "kilometres per hour")`.

    The plain text is the spoken form, since the plain text is what a
    client without SSML says aloud.
    """
    shown, said = _part(written)[0], _part(spoken)[0]
    return Speech(said, f'<sub alias="{escape(said)}">{_escape_text(shown)}</sub>')


def _checked(plain: str, fragment: str) -> Speech:
    """A Speech built by a helper: refused here when a voice would not read it."""
    problems = validate(fragment)
    if problems:
        raise ValueError("; ".join(problems))
    return Speech(plain, fragment)


def cardinal(text: Any) -> Speech:
    """Say `text` as a number: `cardinal("1,200")` is "one thousand, two hundred"."""
    return _say_as(text, "cardinal")


def ordinal(text: Any) -> Speech:
    """Say `text` as an ordinal: `ordinal(3)` is "third"."""
    return _say_as(text, "ordinal")


def fraction(text: Any) -> Speech:
    """Say `text` as a fraction: "1/2" is "one half", "2 3/4" is "two and three quarters"."""
    return _say_as(text, "fraction")


def unit(text: Any) -> Speech:
    """Say a quantity with its unit: `unit("5km")` is "five kilometers"."""
    return _say_as(text, "unit")


def currency(text: Any) -> Speech:
    """Say an amount of money: `currency("$12.50")` is "twelve dollars and fifty cents"."""
    return _say_as(text, "currency")


def address(text: Any) -> Speech:
    """Say a street address: abbreviations spelled out, house numbers read as people say them."""
    return _say_as(text, "address")


def interjection(text: Any) -> Speech:
    """Mark `text` as an interjection ("wow", "oh"), said as written."""
    return _say_as(text, "interjection")


def expletive(text: Any) -> Speech:
    """Bleep `text` out of the spoken reply. The plain text keeps the word for a screen."""
    return _say_as(text, "expletive")


def _formatted(text: Any, kind: str, fmt: str | None) -> Speech:
    plain = _part(text)[0]
    attribute = f' format="{escape(fmt)}"' if fmt else ""
    return _checked(
        plain, f'<say-as interpret-as="{kind}"{attribute}>{_escape_text(plain)}</say-as>')


def as_date(text: Any, format: str | None = None) -> Speech:  # noqa: A002 - SSML's attribute name
    """Say `text` as a date. `format` orders numeric fields: "mdy", "dmy" or "ymd"."""
    return _formatted(text, "date", format)


def as_time(text: Any, format: str | None = None) -> Speech:  # noqa: A002
    """Say `text` as a clock time. `format` is "hms12" or "hms24"."""
    return _formatted(text, "time", format)


def phoneme(text: Any, ph: str, alphabet: str = "ipa") -> Speech:
    """Say `text` with the pronunciation `ph`, written in IPA or X-SAMPA (`alphabet="x-sampa"`)."""
    plain, fragment = _part(text)
    return _checked(plain, f'<phoneme alphabet="{escape(alphabet)}" ph="{escape(ph)}">'
                           f"{fragment}</phoneme>")


def mark(name: str) -> Speech:
    """A named point in the speech: the voice reports when its audio reaches it."""
    return _checked("", f'<mark name="{escape(name)}"/>')


def prosody(text: Any, *, rate: str | None = None, pitch: str | None = None,  # noqa: A002
            volume: str | None = None) -> Speech:
    """Say `text` at another pace, pitch or volume.

    `rate` is a name ("slow") or a percentage ("90%"); `pitch` a name ("high"), semitones ("+2st")
    or a percentage ("-10%"); `volume` a name ("soft") or a dB change ("-6dB").
    """
    attributes = "".join(f' {name}="{escape(value)}"'
                         for name, value in (("rate", rate), ("pitch", pitch), ("volume", volume))
                         if value is not None)
    if not attributes:
        raise ValueError("prosody needs a rate, a pitch or a volume")
    plain, fragment = _part(text)
    return _checked(plain, f"<prosody{attributes}>{fragment}</prosody>")


def pitch(text: Any, value: str) -> Speech:
    """Say `text` higher or lower: `pitch("Really?", "+2st")`. Keep it modest."""
    return prosody(text, pitch=value)


def _effect(text: Any, attributes: str) -> Speech:
    plain, fragment = _part(text)
    return _checked(plain, f"<amazon:effect {attributes}>{fragment}</amazon:effect>")


def whisper(text: Any) -> Speech:
    """Say `text` whispered (the words with the voicing removed; an approximation)."""
    return _effect(text, 'name="whispered"')


def soft(text: Any) -> Speech:
    """Say `text` in a soft, quieter, breathier voice."""
    return _effect(text, 'phonation="soft"')


def compress(text: Any) -> Speech:
    """Say `text` with its loudness evened out (dynamic range compression)."""
    return _effect(text, 'name="drc"')


def vocal_tract(text: Any, percent: str) -> Speech:
    """Say `text` with a longer ("+20%") or shorter ("-15%") vocal tract: lower or higher."""
    return _effect(text, f'vocal-tract-length="{escape(percent)}"')


def breath(duration: str | None = None, volume: str | None = None) -> Speech:
    """A breath at this point. `duration` is "short", "medium" or "long"; `volume` a name or dB."""
    attributes = "".join(f' {name}="{escape(value)}"'
                         for name, value in (("duration", duration), ("volume", volume))
                         if value is not None)
    return _checked("", f"<amazon:breath{attributes}/>")


def auto_breaths(text: Any, frequency: str = "medium", duration: str | None = None,
                 volume: str | None = None) -> Speech:
    """Say `text` with a breath between sentences, as often as `frequency` ("low" to "x-high")."""
    attributes = f' frequency="{escape(frequency)}"' + "".join(
        f' {name}="{escape(value)}"' for name, value in (("duration", duration), ("volume", volume))
        if value is not None)
    plain, fragment = _part(text)
    return _checked(plain, f"<amazon:auto-breaths{attributes}>{fragment}</amazon:auto-breaths>")


class _SSMLFormatter(Formatter):
    """`str.format` for SSML: data is escaped, a Speech brings its markup."""

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, Speech) and not format_spec:
            return value.fragment
        return escape(format(value, format_spec))


_FORMATTER = _SSMLFormatter()


def markup(template: str, /, **values: Any) -> Speech:
    """SSML written in the skill's code, with `{placeholders}` filled safely.

    The template is trusted markup; the values are data and are escaped, so
    `markup('<say-as interpret-as="characters">{code}</say-as>', code=user_code)`
    cannot be turned into other tags by what the user said. A Speech value
    brings its own markup. Never pass text from a user or a service as the
    template. Raises ValueError when the result is not markup a voice reads.
    """
    fragment = _FORMATTER.vformat(template, (), values)
    problems = validate(fragment)
    if problems:
        raise ValueError(f"markup {template!r}: " + "; ".join(problems))
    return Speech(None, fragment)


# -- dialogs -----------------------------------------------------------------

def render_line(plain_template: str, ssml_template: str | None = None,
                data: Mapping[str, Any] | None = None) -> str:
    """One dialog line and its SSML twin, rendered from the same data.

    Returns a plain `str` when there is no markup to send, which is always
    the case without a twin unless a value is a Speech with markup: then the
    SSML is the plain line, escaped, with that value's markup in its place.
    A twin that cannot be filled in or does not parse is dropped (and logged
    once), and the plain line is said alone. Formatting errors in the plain
    line are raised, exactly as `str.format` raises them.
    """
    values = dict(data or {})
    plain = plain_template.format(**values)
    source = ssml_template
    if source is None:
        if not carries_markup(values):
            return plain
        source = _escape_text(plain_template)
    try:
        fragment = _FORMATTER.vformat(source, (), values)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError) as failure:
        warn_once(f"twin:{source}", f"an SSML line could not be filled in ({failure!r}); "
                                    f"saying the plain line alone: {source!r}")
        return plain
    if not _well_formed(fragment):
        warn_once(f"twin:{source}", f"an SSML line is not well-formed once filled in; "
                                    f"saying the plain line alone: {source!r}")
        return plain
    speech = Speech(plain, fragment)
    return speech if speech.ssml else plain


# -- a skill's way of speaking -------------------------------------------------

@dataclass(frozen=True)
class SpeechStyle:
    """How a skill's replies are paced, declared once instead of in every twin.

    Set it on the skill class, `SPEECH_STYLE = SpeechStyle(sentence_break="350ms")`,
    and every `speak_dialog` line is sent with markup derived from the line's
    own words: a pause after each sentence, a slower pace, and so on. There is
    no `.ssml` file to keep beside each `.dialog`, in every language, in step
    with it. A `.ssml` twin still wins for the one line that needs more than a
    rule can say (a spelled code, a word in another language).

    Each field is None (off) or a value the voices read: `rate` is a
    `<prosody rate>` such as "95%" or "slow"; the others are `<break time>`
    durations such as "350ms". The rules read only the dialog's own words,
    never what a `{placeholder}` is later filled with, so a value that holds a
    full stop is not cut in two.
    """

    rate: str | None = None
    pitch: str | None = None
    breaths: str | None = None
    sentence_break: str | None = None
    colon_break: str | None = None
    dash_break: str | None = None
    comma_break: str | None = None
    say_as: bool = True

    def __post_init__(self) -> None:
        problems = []
        if self.rate is not None:
            problems += validate(f'<prosody rate="{escape(self.rate)}">x</prosody>')
        if self.pitch is not None:
            problems += validate(f'<prosody pitch="{escape(self.pitch)}">x</prosody>')
        if self.breaths is not None:
            problems += validate(
                f'<amazon:auto-breaths frequency="{escape(self.breaths)}">x</amazon:auto-breaths>')
        for name in ("sentence_break", "colon_break", "dash_break", "comma_break"):
            value = getattr(self, name)
            if value is not None:
                problems += validate(f'<break time="{escape(value)}"/>')
        if problems:
            raise ValueError("SpeechStyle: " + "; ".join(problems))


_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_STOP = "\x01"
_OPEN, _CLOSE = "\x02", "\x03"
_SPAN_OPEN, _SPAN_CLOSE = "\x04", "\x05"

# What ends a sentence, a clause or a phrase, in the scripts the skills ship. Latin marks
# need a space and more words after them ("3.5" and "e.g." are not ends); the marks of
# scripts that do not put a space after a full stop (Japanese, Chinese, Thai-less Indic and
# Arabic text) are marks wherever they stand, as long as more words follow.
_CLOSERS = "\"')»”」』）】》〉"
_SENTENCE_SPACED = "[.!?…]+"
_SENTENCE_BARE = ("[。！？｡؟۔।॥։።။។"
                  "‼⁇-⁉]+")
_COMMA_BARE = "[，、､،၊]"
_COLON_BARE = "[：]"
_SEMI_BARE = "[；؛]"
# A mark followed by more words. The mark decides the pause; text that ends the line has
# nothing after it to pause for.
_MARK = re.compile(
    rf"(?P<sentence>{_SENTENCE_SPACED}[{_CLOSERS}]?)(?=\s+\S)|"
    rf"(?P<sentence_bare>{_SENTENCE_BARE}[{_CLOSERS}]?)(?=\s*\S)|"
    r"(?P<colon>:)(?=\s+\S)|(?P<semi>;)(?=\s+\S)|"
    r"(?P<dash>\s[—–])(?=\s+\S)|(?P<comma>,)(?=\s+\S)|"
    rf"(?P<colon_bare>{_COLON_BARE})(?=\s*\S)|(?P<semi_bare>{_SEMI_BARE})(?=\s*\S)|"
    rf"(?P<comma_bare>{_COMMA_BARE})(?=\s*\S)"
)

# A full stop after these is part of the word, not the end of the sentence. Titles and
# honorifics never end one; the others do only when a capital letter follows ("Nov. 9" and
# "9 a.m. on Monday" go on, "It was 9 a.m. Then" stops).
_ALWAYS_ABBREVIATION = frozenset({
    "mr", "mrs", "ms", "mx", "dr", "prof", "mme", "mmes", "mlle", "mlles", "mgr", "st", "ste",
    "mt", "sr", "sra", "sres", "srta", "dra", "hr", "dipl", "ing", "noº"})
_SOMETIMES_ABBREVIATION = frozenset({
    "jr", "vs", "etc", "approx", "ca", "cf", "ex", "no", "nr", "env", "av", "bd", "bld", "ave",
    "blvd", "rd", "apt", "dept", "inc", "ltd", "co", "corp", "fig", "vol", "ch", "pp", "tel",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "janv", "févr", "avr", "juil", "déc", "mon", "tue", "wed", "thu", "fri", "sat",
    "sun", "lun", "mer", "jeu", "ven", "sam", "dim", "ene", "abr", "ago", "dic", "bzw",
    "usw", "evtl", "ggf", "inkl", "max", "min"})
# "9. November": a number and a full stop is an ordinal in these languages.
_ORDINAL_DOT = frozenset({"de", "cs", "sk", "da", "nb", "nn", "no", "fi", "hu", "sl", "hr", "bs",
                          "sr", "is", "et", "lv", "tr", "fo", "mk", "sq"})
_LAST_WORD = re.compile(r"([^\s(\[{\"'«“]+)$")
_DOTTED = re.compile(r"^(?:\w\.)+\w$")


def _primary(lang: str | None) -> str:
    return (lang or "").replace("_", "-").split("-")[0].lower()


def _stops_here(before: str, after: str, lang: str | None, spans: list[str]) -> bool:
    """Whether the full stop that follows `before` ends a sentence (False: an abbreviation)."""
    found = _LAST_WORD.search(before)
    word = found.group(1) if found else ""
    if word.startswith(_SPAN_OPEN):  # a quantity: "9 a.m" keeps its dots, "9 pm" does not
        word = _span_text(spans, int(word.strip(_SPAN_OPEN + _SPAN_CLOSE))).rsplit(" ", 1)[-1]
        if not _DOTTED.match(word):
            return True
    word = word.strip(".")
    follows = after.lstrip()[:1]
    if not word:
        return True
    bare = word.lower()
    if bare in _ALWAYS_ABBREVIATION:
        return False
    if len(word) == 1 and word.isalpha():
        # An initial ("J. Smith", "M. Dupont") or a unit/page letter ("p. 5"); the words
        # "I" and "a" end sentences as often as they start them.
        if word.isupper():
            return word in ("I", "A")
        return not (follows.isdigit() or follows.islower())
    if bare in _SOMETIMES_ABBREVIATION or _DOTTED.match(word):
        return follows.isupper() and not follows.isdigit()
    if word.isdigit() and _primary(lang) in _ORDINAL_DOT:
        return not follows.isalpha()
    return True


# -- numbers, times, dates and units the voice should read as such --------------------------
#
# A literal "14 h 30", "3,50 €" or "23 °C" in a dialog is read by a voice's own text
# normalizer, which is weak where it matters: phoonnx says "quatorze h trente", "trois virgule
# cinq euros", "un deux cents" for "1 200" and "7:30 P M". Wrapped in `<say-as>` the voice reads
# it with the language's own number, date and unit rules. Only languages phoonnx's say-as has
# word tables for are wrapped; in the others the voice's own reading is left alone.
SAY_AS_LANGUAGES = frozenset({"en", "fr", "de", "es", "it", "pt", "nl"})
_UNIT_SYMBOL = r"(?:°\s?[CFK]|℃|℉|%|km/h|km|cm|kg)(?![\w°])"
_MONEY_SYMBOL = r"(?:US\$|CA\$|C\$|R\$|[$€£¥])"
_MONEY_CODE = r"(?:EUR|USD|GBP|CAD|CHF|JPY)"
_AMOUNT = r"\d(?:[\d.,  ]*\d)?"
_QUANTITY = re.compile(
    r"(?P<date>(?<![\w/.:-])(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{4})(?![\w/-]))|"
    r"(?P<time>(?<![\w:.,])(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp]\.?[Mm])?"
    r"|\d{1,2}\s?h\s?\d{2})(?![\w:]))|"
    rf"(?P<currency>(?<![\w.,])(?:{_MONEY_SYMBOL}\s?{_AMOUNT}|{_AMOUNT}\s?"
    rf"(?:{_MONEY_SYMBOL}|{_MONEY_CODE}\b)|\x01\s?{_MONEY_SYMBOL}|{_MONEY_SYMBOL}\s?\x01))|"
    rf"(?P<unit>(?:(?<![\w.,])-?\d+(?:[.,]\d+)?|\x01)\s?{_UNIT_SYMBOL})|"
    r"(?P<ordinal>(?<![\w])\d+(?:st|nd|rd|th|er|re|ere|e|ème|è|nd|nde)(?![\w]))|"
    r"(?P<cardinal>(?<![\d.,])\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?(?![\d,]))"
)
_ORDINAL_SUFFIX = {
    "en": re.compile(r"^\d+(?:st|nd|rd|th)$"),
    "fr": re.compile(r"^\d+(?:er|re|ere|e|ème|è|nd|nde)$"),
}


def _quantities(body: str, lang: str | None, spans: list[str]) -> str:
    """`body` with each quantity the voice should read as such held back as a numbered span."""
    short = _primary(lang)
    if short not in SAY_AS_LANGUAGES:
        return body

    def hold(match: re.Match[str]) -> str:
        kind, text = match.lastgroup or "", match.group(0)
        if kind == "ordinal":
            pattern = _ORDINAL_SUFFIX.get(short)
            if pattern is None or not pattern.match(text):
                return text
        if kind == "cardinal" and "," in text and short != "en":
            return text  # a comma is the decimal mark there: "1,200" is one and a fifth
        if kind == "unit" and text.startswith(_STOP) and "%" not in text and "°" not in text:
            return text
        spans.append(f"{kind}\x00{text}")
        return f"{_SPAN_OPEN}{len(spans) - 1}{_SPAN_CLOSE}"

    return _QUANTITY.sub(hold, body)


def _span_text(spans: list[str], index: int) -> str:
    return spans[index].split("\x00", 1)[1]


@lru_cache(maxsize=2048)
def auto_twin(template: str, style: SpeechStyle, lang: str | None = None) -> str | None:
    """The SSML for a dialog line under `style`, or None when it adds nothing.

    `template` is one dialog line with `{placeholders}`, as `str.format` takes
    it. The result is a template in turn, to be filled by `render_line` with
    the values escaped. None means the line would be sent as plain words.

    `lang` is the language of the line. It lets the rules know that "9. November"
    is a date in German and not the end of a sentence, and, with `style.say_as`,
    wraps the literal times, dates, amounts, units, ordinals and thousands in the
    line in `<say-as>` (see `SAY_AS_LANGUAGES`). Without it only the pauses and the
    pace are derived.
    """
    if "{{" in template or "}}" in template:
        return None
    holes: list[str] = []

    def hide(match: re.Match[str]) -> str:
        holes.append(match.group(0))
        return _STOP

    body = _PLACEHOLDER.sub(hide, _XML_ILLEGAL.sub("", template))
    spans: list[str] = []
    if style.say_as and lang:
        body = _quantities(body, lang, spans)
    breaks = {"sentence": style.sentence_break, "sentence_bare": style.sentence_break,
              "colon": style.colon_break, "colon_bare": style.colon_break,
              "semi": style.colon_break, "semi_bare": style.colon_break,
              "dash": style.dash_break, "comma": style.comma_break,
              "comma_bare": style.comma_break}
    added = 0

    def mark(match: re.Match[str]) -> str:
        nonlocal added
        kind = match.lastgroup or ""
        duration = breaks[kind]
        if not duration:
            return match.group(0)
        text = match.group(0)
        if kind == "sentence" and text == "." and not _stops_here(
                match.string[:match.start()], match.string[match.end():], lang, spans):
            return text
        if kind == "dash" and match.string[match.end():].lstrip()[:1].isdigit() \
                and match.string[:match.start()][-1:].isdigit():
            return text  # "9 – 5" is a range
        added += 1
        spaced = match.string[match.end():match.end() + 1].isspace()
        return f"{text}{' ' if spaced else ''}{_OPEN}{escape(duration)}{_CLOSE}"

    # Marks are found in the words as written and escaped afterwards: the ';'
    # that ends '&amp;' is not a mark.
    spoken = _entities(_MARK.sub(mark, body))
    if not added and not spans and not (style.rate or style.pitch or style.breaths):
        return None
    spoken = re.sub(f"{_OPEN}(.*?){_CLOSE}", lambda m: f'<break time="{m.group(1)}"/>', spoken)
    spoken = re.sub(f"{_SPAN_OPEN}(\\d+){_SPAN_CLOSE}", lambda m: _wrapped(spans, int(m.group(1))),
                    spoken)
    parts = iter(holes)
    spoken = re.sub(_STOP, lambda _m: next(parts), spoken)
    # "words. <break/>  More" -> one space either side of the break.
    spoken = re.sub(r"(<break [^>]*/>)\s+", r"\1 ", spoken)
    attributes = "".join(f' {name}="{escape(value)}"' for name, value in
                         (("rate", style.rate), ("pitch", style.pitch)) if value)
    if attributes:
        spoken = f"<prosody{attributes}>{spoken}</prosody>"
    if style.breaths:
        spoken = (f'<amazon:auto-breaths frequency="{escape(style.breaths)}">'
                  f"{spoken}</amazon:auto-breaths>")
    return spoken


def _wrapped(spans: list[str], index: int) -> str:
    kind = spans[index].split("\x00", 1)[0]
    return f'<say-as interpret-as="{kind}">{_entities(_span_text(spans, index))}</say-as>'


# -- what goes on the bus ----------------------------------------------------

_WARNED: set[tuple[str, str]] = set()
_WARNED_LOCK = threading.Lock()


def warn_once(kind: str, text: str, owner: str | None = None) -> None:
    """Log a markup problem once per owner and kind, not once per sentence."""
    key = (owner or "", kind)
    with _WARNED_LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    LOG.warning("%s%s", f"{owner}: " if owner else "", text)


def speech_parts(text: Any, owner: str | None = None) -> tuple[Any, str | None]:
    """(utterance, utterance_ssml) for something a skill asked to say.

    A Speech gives its words and its `<speak>` document. A plain string that
    holds SSML tags is a skill writing markup where the words go: the kit
    moves it to the SSML, says its words as the plain text, and logs it once.
    If that markup does not parse, the tags are dropped and only the words
    are sent. The plain text never carries a tag. Anything else passes
    through unchanged, so a plain string is sent exactly as it was.
    """
    if isinstance(text, Speech):
        plain, document = text.plain, text.document
        if document is not None and not _well_formed(text.fragment):
            warn_once("malformed", "SSML that does not parse was dropped; "
                                   "the plain words were sent", owner)
            document = None
        if looks_like_ssml(plain):
            warn_once("plain", "the plain text of a Speech held SSML tags; "
                               "they were taken out", owner)
            plain = strip_tags(plain)
        return plain, document
    if looks_like_ssml(text):
        fragment = _inner(text)
        if _well_formed(fragment):
            warn_once("plain", "SSML was passed as plain text; it was sent as "
                               "utterance_ssml and its words as the utterance. Use "
                               "thalovant_skillkit.ssml or a .ssml dialog twin", owner)
            return to_plain(fragment), f"<speak>{fragment}</speak>"
        warn_once("plain", "text with SSML tags that do not parse was passed as plain "
                           "text; the tags were taken out", owner)
        return strip_tags(text), None
    return text, None
