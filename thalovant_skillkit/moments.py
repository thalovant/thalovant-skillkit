"""Saying a date and writing one are two different jobs.

`ovos-date-parser` answers for a speaker with no screen, which is the right
default and the wrong output for a chat bubble. A reminder came back from
the app reading

    Repeating reminder set for monday, the twenty-eighth at zero zero
    hundred: check backups.

Every word of that is correct to hear. On a screen it is a sentence to
parse where a date and a clock belong, and the weekday arrives lowercase
into the middle of somebody else's sentence.

The answer is not to write digits into the spoken form -- TTS reads
"seven o'clock" better than "19:00", and a phone is not the only thing
listening. It is to carry both: `utterance` as it is said, and
`utterance_written` as it should be read. `thalovant-skill-date-time`
already did this and nothing else could, because the formatting lived
inside it.

So it lives here now. Four skills had written some of it -- alarm and
stopwatch a clock, date-time a date and a clock, reminder both again --
and each had picked slightly different rules about ordinals, relative
days and the 24-hour question.

Nothing here is imported at module load: `ovos-date-parser` and `babel`
between them carry resources for sixty-odd languages, and a skill that
never formats a date should not pay for that at boot.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

__all__ = [
    "WrittenForms",
    "tidy_sentence",
    "date_text",
    "date_time_text",
    "duration_text",
    "english_ordinal",
    "speak_with_written",
    "time_text",
    "uses_24_hour_clock",
]

#: Raised by the upstream formatters for a language whose resources are
#: missing or malformed. Every entry point here falls back rather than
#: letting one absent translation take the answer with it.
_FORMATTER_ERRORS = (KeyError, NotImplementedError, OSError, TypeError, ValueError)

_LOADED: dict[str, Any] = {}
_LOAD_LOCK = threading.Lock()


def _loaded(name: str, load: Callable[[], Any]) -> Any:
    """Import once, on the first call that needs it."""
    with _LOAD_LOCK:
        if name not in _LOADED:
            _LOADED[name] = load()
        return _LOADED[name]


def _babel_locale(lang: str) -> str:
    return str(lang or "en-US").replace("-", "_")


def _parser_lang(lang: str) -> str:
    return str(lang or "en-US").lower()


#: Two full stops where a sentence meant one. Three is an ellipsis and
#: belongs to whoever wrote it.
_DOUBLED_STOP = re.compile(r"(?<!\.)\.\.(?!\.)")


def tidy_sentence(text: str) -> str:
    """Collapse the full stop a spoken time brings into the one after it.

    "at seven a.m." dropped into a template that ends in a period of its
    own gives "at seven a.m.." -- which no amount of care in either half
    prevents, because neither knows about the other. Every skill that
    renders a time into a sentence hits it, so the rule lives here.
    """
    return _DOUBLED_STOP.sub(".", text or "")


def uses_24_hour_clock(lang: str) -> bool:
    """Whether this locale writes 19:30 or 7:30 PM.

    Forcing am/pm everywhere put "demain 7:30 AM" in front of French
    speakers; dropping it everywhere would put a bare "7:30" on an English
    alarm, which is the one place in the product where guessing the wrong
    half of the day actually costs somebody something.

    So it is neither. CLDR already records the convention for every locale
    and babel reads it straight out of the short time pattern -- `h:mm a`
    for English, `HH:mm` for most of Europe. Nothing is invented and no
    list of languages is maintained here.
    """
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import get_time_format
    except ImportError:  # pragma: no cover - babel is a declared dependency
        return False
    try:
        pattern = str(get_time_format("short", locale=_babel_locale(lang)))
    except (UnknownLocaleError, ValueError, KeyError, TypeError):
        return False
    return "H" in pattern or "k" in pattern


def english_ordinal(day: int) -> str:
    """1st, 2nd, 3rd, 4th -- and 11th, 12th, 13th, which break the pattern."""
    if 11 <= day % 100 <= 13:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


def time_text(value: datetime, lang: str, use_24hour: bool, *, written: bool = False) -> str:
    """A clock, said or written.

    Written is the same upstream function's other form: "00:00", "9:40 AM".
    Spoken is what it says by default -- "nine forty a.m.", "midnight" --
    which is what a voice should say and what TTS reads without stumbling.
    """
    try:
        nice_time = _loaded("nice_time", lambda: __import__(
            "ovos_date_parser", fromlist=["nice_time"]).nice_time)
        return str(
            nice_time(
                value,
                lang=_parser_lang(lang),
                speech=not written,
                use_24hour=use_24hour,
                use_ampm=not use_24hour,
            )
            or ""
        ).strip()
    except _FORMATTER_ERRORS:
        pass
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import format_time
        # `short` is the locale's own preference, which is not what was
        # asked: a caller that resolved `use_24hour` already has an answer
        # and the fallback must not quietly overrule it.
        pattern = "HH:mm" if use_24hour else "h:mm a"
        return str(format_time(value, format=pattern, locale=_babel_locale(lang)) or "").strip()
    except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
        return value.strftime("%H:%M" if use_24hour else "%I:%M %p").lstrip("0")


def _upstream_date(value: datetime, lang: str, now: datetime) -> str:
    """What `nice_date` says, or "" when it has nothing for this language."""
    try:
        nice_date = _loaded("nice_date", lambda: __import__(
            "ovos_date_parser", fromlist=["nice_date"]).nice_date)
        return str(nice_date(value, lang=_parser_lang(lang), now=now) or "").strip()
    except _FORMATTER_ERRORS:
        return ""


def date_text(value: datetime, lang: str, now: datetime, *, written: bool = False) -> str:
    """A day, said or written.

    Both forms keep "today" and "tomorrow" when the date is that near. It
    is the best thing either can say, and an early version of this replaced
    it with an absolute date -- "Sunday, May 24, 2026" for something due in
    four hours -- which is worse in both.

    Beyond a day either side the spoken form spells the number out, because
    that is what a voice should do. The written form keeps the same shape --
    weekday, then day -- through CLDR's own `EEEE, d`: "Monday, 28",
    "lundi, 28", "Montag, 28". No month and no year; anything wanting those
    is not a reminder and should ask for them.

    English reads wrong bare, so it takes the ordinal it would be read with
    anyway: "Monday, 28th". The other locales use a cardinal there already.
    """
    if written and abs((value.date() - now.date()).days) > 1:
        try:
            from babel.core import UnknownLocaleError
            from babel.dates import format_date
            locale = _babel_locale(lang)
            text = str(format_date(value.date(), "EEEE, d", locale=locale) or "").strip()
            if text and locale.split("_")[0].lower() == "en":
                text = re.sub(rf"\b{value.day}\b", english_ordinal(value.day), text, count=1)
            if text:
                return text
        except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
            pass
    try:
        nice_date = _loaded("nice_date", lambda: __import__(
            "ovos_date_parser", fromlist=["nice_date"]).nice_date)
        text = str(nice_date(value, lang=_parser_lang(lang), now=now) or "").strip()
        if text:
            return text
    except _FORMATTER_ERRORS:
        pass
    # Never the empty string: a caller drops this straight into a sentence,
    # and a formatter that failed would take the date out of the reply
    # rather than announce itself.
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import format_date
        text = str(
            format_date(value.date(), format="long", locale=_babel_locale(lang)) or ""
        ).strip()
        if text:
            return text
    except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
        pass
    return value.date().isoformat()


def date_time_text(
    value: datetime, lang: str, now: datetime, *, written: bool = False
) -> str:
    """A day and a clock together, in the language's own order.

    The written form composes the two through upstream's per-language
    template rather than joining them here, so nothing in this file has to
    know that German puts the day first or that Spanish takes a different
    path entirely.
    """
    day = date_text(value, lang, now, written=written)
    clock = time_text(value, lang, uses_24_hour_clock(lang), written=written)
    base = _parser_lang(lang).split("-")[0]
    # Only compose with upstream's template when upstream can actually phrase
    # the day. `date_text` now always answers -- it falls back to CLDR rather
    # than return the empty string -- so without this the template would join
    # a babel date for a language it has no resources for, and Japanese would
    # read "2026年5月24日の09:40" where CLDR writes "2026/05/24 9:40:00".
    upstream_day = day if written else _upstream_date(value, lang, now)
    # es/pt/gl take a different path upstream and never consult lang_config.
    if upstream_day and clock and base not in {"es", "pt", "gl"}:
        day = upstream_day
        try:
            composer = _loaded("date_time_format", lambda: __import__(
                "ovos_date_parser", fromlist=["date_time_format"]).date_time_format)
            composer.cache(base)
            template = composer.lang_config[base]["date_time_format"]["date_time"]
            if template:
                return template.format(formatted_date=day, formatted_time=clock)
        except (AttributeError, *_FORMATTER_ERRORS):
            pass
    # Before joining them with a space: a language upstream has no template
    # for still has a CLDR one, and it knows where the day goes. Japanese
    # writes "2026/05/24 9:40:00", not "2026-05-24 9:40".
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import format_datetime
        text = str(
            format_datetime(value, format="medium", locale=_babel_locale(lang)) or ""
        ).strip()
        if text:
            return text
    except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
        pass
    if day and clock:
        return f"{day} {clock}".strip()
    try:
        nice_date_time = _loaded("nice_date_time", lambda: __import__(
            "ovos_date_parser", fromlist=["nice_date_time"]).nice_date_time)
        text = str(nice_date_time(value, lang=_parser_lang(lang), now=now) or "").strip()
        if text:
            return text
    except _FORMATTER_ERRORS:
        pass
    # A language upstream has no resources for at all -- Japanese has no
    # date_time.json -- still has a CLDR date. Reaching the ISO string
    # instead would print "2026-05-24 09:40" at somebody who writes
    # "2026/05/24 9:40:00".
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import format_datetime
        return str(
            format_datetime(value, format="medium", locale=_babel_locale(lang)) or ""
        ).strip()
    except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
        return value.isoformat(sep=" ", timespec="minutes")


def duration_text(seconds: float, lang: str, *, written: bool = False) -> str:
    """How long, said or written: "five minutes" against "5:00"."""
    total = max(0, int(seconds))
    try:
        nice_duration = _loaded("nice_duration", lambda: __import__(
            "ovos_date_parser", fromlist=["nice_duration"]).nice_duration)
        return str(nice_duration(total, lang=_parser_lang(lang), speech=not written) or "").strip()
    except _FORMATTER_ERRORS:
        pass
    if written:
        # `format_timedelta` says "5 minutes", which is the spoken answer
        # under another name. What was asked for is a clock.
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    try:
        from babel.core import UnknownLocaleError
        from babel.dates import format_timedelta
        return str(
            format_timedelta(timedelta(seconds=total), locale=_babel_locale(lang)) or ""
        ).strip()
    except (ImportError, UnknownLocaleError, ValueError, KeyError, TypeError):
        return str(timedelta(seconds=total))


class WrittenForms:
    """The spoken fragments of one reply, and how each should be read.

    A skill that only answers questions can render its reply twice, once
    each way, and `thalovant-skill-date-time` does. A skill that creates,
    cancels or updates something cannot: the second pass would act on state
    the first one already moved.

    So the fragments are recorded as the spoken reply is composed, and the
    written reply is that same string with each one swapped. Thread-local,
    because a hub answers several rooms at once.
    """

    _state = threading.local()

    @classmethod
    def reset(cls) -> None:
        cls._state.pairs = []

    @classmethod
    def remember(cls, spoken: str, written: str) -> None:
        """Record one fragment. Identical or empty pairs are not worth a swap."""
        if not spoken or not written or spoken == written:
            return
        pairs = getattr(cls._state, "pairs", None)
        if pairs is None:
            pairs = []
            cls._state.pairs = pairs
        pairs.append((spoken, written))

    @classmethod
    def say(cls, spoken: str, written: str) -> str:
        """Record the pair and hand back the spoken half.

        The shape every caller wants: compose both, keep the one that goes
        into the sentence, and leave the other where `render` will find it.
        """
        cls.remember(spoken, written)
        return spoken

    @classmethod
    def render(cls, spoken_reply: str) -> str:
        """`spoken_reply` with every recorded fragment written out instead."""
        text = spoken_reply or ""
        # Longest first: a fragment that contains another must be swapped
        # before the shorter one rewrites its middle.
        for spoken, written in sorted(
            getattr(cls._state, "pairs", []) or [], key=lambda pair: len(pair[0]), reverse=True
        ):
            text = text.replace(spoken, written)
        # A spoken time ends in a full stop of its own -- "nine a.m." -- and
        # when it lands at the end of a sentence that period is the
        # sentence's. Swapping in "9:00 AM" takes it away, and the reply
        # arrives on a screen with no end to it.
        if spoken_reply.rstrip().endswith(".") and not text.rstrip().endswith("."):
            text = text.rstrip() + "."
        return text


def speak_with_written(
    skill: Any, reply: str, message: Any, lang: str, written: str | None = None
) -> None:
    """Say `reply`, and carry how it should be read beside it.

    `utterance_written` is additive: a device with no screen never looks at
    it, and the listener forwards the skill's data dict whole, so it reaches
    one that does without anything in between having to know.
    """
    data: dict[str, Any] = {
        "utterance": reply,
        "expect_response": False,
        "meta": {"skill": getattr(skill, "skill_id", "")},
        "lang": lang,
    }
    if written and written != reply:
        data["utterance_written"] = written
    try:
        from ovos_bus_client.message import Message
    except ImportError:  # pragma: no cover - the bus client is always present
        skill.speak(reply)
        return
    try:
        speak_message = message.forward("speak", data)
    except AttributeError:
        speak_message = Message("speak", data)
    speak_message.context["skill_id"] = getattr(skill, "skill_id", "")
    # The raw attribute, not the `bus` property: on a skill built for a test
    # without one, the property raises its way out of `getattr`'s default and
    # the reply is lost. `date-time` reads it the same way.
    bus = getattr(skill, "_bus", None) or getattr(skill, "bus", None)
    if bus is None:
        skill.speak(reply)
        return
    bus.emit(speak_message)
