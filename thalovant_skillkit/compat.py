"""Use a kit name a skill may find missing, without making the skill unloadable.

A skill is installed on a hub with `pip`, and the running `ovos-core` keeps the kit it imported
at boot in memory. A skill that does `from thalovant_skillkit.ssml import SpeechStyle` and meets
a kit from before `SpeechStyle` raises `ImportError` while it loads, and the whole skill is gone
until the pod restarts: the weather skill was unloadable for twelve hours that way. The name was
only a nicety (pacing); the skill itself could have spoken without it.

This module is the supported way to ask for a nicety. Nothing here imports a name that may be
missing: each function looks it up when called, at the kit that is *loaded*, and answers with
what that kit can do.

    from thalovant_skillkit.compat import speech_style_or_none, ssml_helper

    cardinal = ssml_helper("cardinal")             # the kit's helper, or plain words
    SPEECH_STYLE = speech_style_or_none(rate="95%", sentence_break="350ms")

It works on a kit that is newer on disk than in memory, which is what a hub in-place upgrade
leaves behind: this file is read from disk, and it asks the loaded modules. A kit older than this
module has no `compat` at all, so a skill whose floor is lower still guards the import itself:

    try:
        from thalovant_skillkit.ssml import SpeechStyle
    except ImportError:  # a kit before 0.34, still loaded on a hub that upgraded in place
        SpeechStyle = None

and passes `SPEECH_STYLE = SpeechStyle(...) if SpeechStyle is not None else None`.
"""
from __future__ import annotations

import dataclasses
import html
import importlib
import logging
import re
import sys
from collections.abc import Callable
from typing import Any

__all__ = [
    "PLAIN_HELPERS",
    "kit_at_least",
    "kit_attr",
    "kit_version",
    "speech_style_or_none",
    "ssml_helper",
]

LOG = logging.getLogger(__name__)

_TAGS = re.compile(r"<[^<>]*>")
_NUMBER = re.compile(r"\d+")


def kit_version() -> tuple[int, ...]:
    """The version of the kit that is *loaded*, as `(0, 35, 0)`; `()` when it cannot be read.

    The package already in memory answers, not the files on disk: after an in-place upgrade
    those are different, and what the running skill can call is what is loaded.
    """
    package = sys.modules.get("thalovant_skillkit")
    text = getattr(package, "__version__", "") if package is not None else ""
    return tuple(int(part) for part in _NUMBER.findall(str(text).split("+")[0])[:3])


def kit_at_least(version: str) -> bool:
    """Whether the loaded kit is `version` or newer: `kit_at_least("0.34")`."""
    wanted = tuple(int(part) for part in _NUMBER.findall(version)[:3])
    have = kit_version()
    return bool(have) and have + (0,) * (len(wanted) - len(have)) >= wanted


def kit_attr(module: str, name: str, default: Any = None) -> Any:
    """`thalovant_skillkit.<module>.<name>`, or `default` when this kit does not have it.

    `kit_attr("ssml", "SpeechStyle")` is what `from thalovant_skillkit.ssml import SpeechStyle`
    would be, answered with None instead of an `ImportError`.
    """
    try:
        found = importlib.import_module(f"thalovant_skillkit.{module}")
    except ImportError:
        return default
    return getattr(found, name, default)


def speech_style_or_none(**fields: Any) -> Any:
    """`ssml.SpeechStyle(**fields)`, or None when the loaded kit has no `SpeechStyle`.

    A field the loaded kit does not know is left out (a style from kit 0.36 asked of kit 0.34
    paces what it can), and logged once at debug level. A value no voice reads is still a
    `ValueError`, as it is from `SpeechStyle` itself: that is a mistake in the skill, not a kit
    that is too old.

        SPEECH_STYLE = speech_style_or_none(rate="95%", sentence_break="350ms")
    """
    style = kit_attr("ssml", "SpeechStyle")
    if style is None:
        return None
    known = {field.name for field in dataclasses.fields(style)}
    unknown = sorted(set(fields) - known)
    if unknown:
        LOG.debug("the loaded thalovant_skillkit has no SpeechStyle field %s; left out", unknown)
    return style(**{name: value for name, value in fields.items() if name in known})


def _words(text: Any, *_ignored: Any, **_named: Any) -> str:
    return "" if text is None else str(text)


def _nothing(*_ignored: Any, **_named: Any) -> str:
    return ""


def _spoken(written: Any, spoken: Any) -> str:
    return _words(spoken)


def _say(*parts: Any, sep: str = " ") -> str:
    return sep.join(str(part) for part in parts if part not in (None, ""))


def _markup(template: str, /, **values: Any) -> str:
    # The tags go, the words stay: what a client without SSML would say.
    return " ".join(html.unescape(_TAGS.sub(" ", template.format(**values))).split())


#: What each `ssml` helper comes to without SSML: the words it would have carried.
PLAIN_HELPERS: dict[str, Callable[..., str]] = {
    "say": _say,
    "pause": _nothing,
    "mark": _nothing,
    "breath": _nothing,
    "sub": _spoken,
    "markup": _markup,
    **{name: _words for name in (
        "spell", "digits", "telephone", "foreign", "emphasis", "cardinal", "ordinal", "fraction",
        "unit", "currency", "address", "interjection", "expletive", "as_date", "as_time",
        "phoneme", "prosody", "pitch", "whisper", "soft", "compress", "vocal_tract",
        "auto_breaths")},
}


def ssml_helper(name: str) -> Callable[..., Any]:
    """The kit's `ssml.<name>` helper, or its plain-words stand-in when the kit lacks it.

    The stand-in takes the helper's own arguments and returns an ordinary `str` of the words it
    would have said (nothing, for a `pause`, `mark` or `breath`), so a skill that passes it to
    `speak_dialog` or `say` speaks the same sentence, just without the markup, on a kit that
    does not have the helper.

        cardinal = ssml_helper("cardinal")
        self.speak_dialog("members", {"count": cardinal(f"{count:,}")})

    Raises `ValueError` for a name that is not a helper of `thalovant_skillkit.ssml` at all, so
    a typo is not mistaken for an old kit.
    """
    if name not in PLAIN_HELPERS:
        raise ValueError(f"{name!r} is not a thalovant_skillkit.ssml helper; "
                         f"they are {', '.join(sorted(PLAIN_HELPERS))}")
    return kit_attr("ssml", name) or PLAIN_HELPERS[name]
