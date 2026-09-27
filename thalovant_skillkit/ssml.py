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
from string import Formatter
from typing import Any

__all__ = [
    "SSML_KEY",
    "SUPPORTED_TAGS",
    "Speech",
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
    "prosody": frozenset({"rate", "volume"}),
    "emphasis": frozenset({"level"}),
    "lang": frozenset({"xml:lang"}),
    "voice": frozenset({"xml:lang"}),
    "say-as": frozenset({"interpret-as"}),
    "sub": frozenset({"alias"}),
    "phoneme": frozenset({"alphabet", "ph"}),
}
SAY_AS = frozenset({"characters", "spell-out", "digits", "telephone"})
BREAK_STRENGTHS = frozenset({"none", "x-weak", "weak", "medium", "strong", "x-strong"})
RATES = frozenset({"x-slow", "slow", "medium", "fast", "x-fast", "default"})
VOLUMES = frozenset({"silent", "x-soft", "soft", "medium", "loud", "x-loud", "default"})
EMPHASIS_LEVELS = frozenset({"strong", "moderate", "reduced", "none"})
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
_SPEAK_ONLY = re.compile(r"^\s*<speak\s*>(.*)</speak>\s*$", re.DOTALL)
_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s)\s*$")
_PERCENT = re.compile(r"^[+-]?\d+(?:\.\d+)?%$")
_DECIBELS = re.compile(r"^[+-]?\d+(?:\.\d+)?dB$", re.IGNORECASE)
_LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")
_BOUNDARY = "\x00"


# -- escaping -----------------------------------------------------------------

def escape(value: Any) -> str:
    """`value` as text that is safe anywhere in SSML, attribute values included."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _escape_text(text: str) -> str:
    """Words for an element's text. Quotes stay readable there."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -- reading markup ----------------------------------------------------------

def looks_like_ssml(text: Any) -> bool:
    """Whether `text` holds an SSML tag, rather than a '<' in a sentence."""
    return isinstance(text, str) and bool(_TAG.search(text))


def _inner(ssml: str) -> str:
    """The markup without an XML declaration or a bare `<speak>` around it.

    A `<speak>` that carries attributes is kept: it is read as a container.
    """
    source = _DECLARATION.sub("", ssml or "").strip()
    match = _SPEAK_ONLY.match(source)
    return match.group(1) if match else source


def _parse(fragment: str) -> ET.Element | None:
    try:
        return ET.fromstring(f"<speak>{fragment}</speak>")
    except ET.ParseError:
        return None


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _normalize(text: str) -> str:
    return " ".join(text.replace(_BOUNDARY, " ").split())


def strip_tags(text: str) -> str:
    """`text` with anything shaped like a tag removed and entities read."""
    return _normalize(html.unescape(_ANY_TAG.sub(" ", text or "")))


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
                       if m.group(1).lower() != "xml"})
    if prefixed:
        return [f"<{name}> is not read by Thalovant voices" for name in prefixed]
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
            reason = ("pitch is not rendered by Thalovant voices" if name == "pitch"
                      else f"<{tag}> takes no {name!r} attribute")
            problems.append(reason)
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
                problems.append(f'<break time="{time}"> needs a unit, as in "500ms" or "1s"')
            elif ms > MAX_BREAK_MS:
                problems.append(f'<break time="{time}"> is longer than the 10s a voice allows')
        strength = given("strength")
        if strength is not None and strength not in BREAK_STRENGTHS:
            problems.append(f'<break strength="{strength}"> is not one of '
                            + ", ".join(sorted(BREAK_STRENGTHS)))
    elif tag == "prosody":
        rate, volume = given("rate"), given("volume")
        if rate is not None and rate not in RATES and not _PERCENT.match(rate):
            problems.append(f'<prosody rate="{rate}"> is not a named rate or a percentage')
        if volume is not None and volume not in VOLUMES and not _DECIBELS.match(volume):
            problems.append(f'<prosody volume="{volume}"> is not a named volume or dB change')
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
    elif tag == "sub":
        if "alias" not in attributes:
            problems.append("<sub> needs alias, the words to say instead")
        if len(element):
            problems.append("<sub> holds words, not other tags")
    elif tag == "phoneme":
        if "ph" not in attributes:
            problems.append("<phoneme> needs ph, the pronunciation in IPA")
        alphabet = given("alphabet")
        if alphabet is not None and alphabet.lower() != "ipa":
            problems.append(f'<phoneme alphabet="{alphabet}"> must be "ipa"')
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
