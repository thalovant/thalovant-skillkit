"""Reading the things every skill reads out of a bus message.

Seventeen skills wrote their own `_utterance` and eighteen their own
`_message_lang`, in ten different shapes. The shapes were not alternatives --
they were the same function at different levels of thoroughness, and the thin
ones were simply wrong more often. `_message_lang` in five skills read only
`context["lang"]`, so an utterance carrying its language in `data` or in the
session was answered in the wrong language.

The versions here are the union: what the most careful skill did, which is what
all of them meant.
"""
from __future__ import annotations

from typing import Any

# ovos_utils.lang.standardize_lang_tag is deprecated in favour of
# ovos_spec_tools.standardize_lang, and six skills still call the old name and
# print a deprecation warning on every utterance. Importing it in one place
# means the next rename is one edit rather than nineteen.
def _plain_standardize(lang: str) -> str:
    """Enough of BCP-47 for a locale directory name: "fr_fr" -> "fr-FR".

    Only used when the OVOS stack is not importable -- which is how the tests
    run, so that checking this library does not mean installing ovos-core.
    """
    parts = str(lang).replace("_", "-").split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"


try:  # pragma: no cover - which import wins depends on the installed stack
    from ovos_spec_tools import standardize_lang as _standardize
except ImportError:  # pragma: no cover
    try:
        from ovos_utils.lang import standardize_lang as _standardize
    except ImportError:
        try:
            from ovos_utils.lang import standardize_lang_tag as _standardize
        except ImportError:
            _standardize = _plain_standardize

# The keys a message may carry its text under. `utterance` is what the intent
# pipeline sends; the others arrive from OCP search, converse and the showroom
# preview, and two skills already read them. A skill that reads only the first
# goes silent on the other three paths.
_TEXT_KEYS = ("utterance", "phrase", "text", "query")


def standardize(lang: str | None) -> str:
    """A BCP-47 tag, normalised, without the deprecated spelling."""
    return _standardize(lang or "en-US")


def data_of(message: Any) -> dict:
    data = getattr(message, "data", None)
    return data if isinstance(data, dict) else {}


def context_of(message: Any) -> dict:
    context = getattr(message, "context", None)
    return context if isinstance(context, dict) else {}


def utterance(message: Any) -> str:
    """The text of the message, or "" if it carries none."""
    data = data_of(message)
    for key in _TEXT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    candidates = data.get("utterances")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def utterances(message: Any) -> list[str]:
    """Every non-empty phrasing the message carries, best first."""
    data = data_of(message)
    found: list[str] = []
    for key in _TEXT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
    candidates = data.get("utterances")
    if isinstance(candidates, list):
        found.extend(c.strip() for c in candidates
                     if isinstance(c, str) and c.strip())
    return list(dict.fromkeys(found))


def session_of(message: Any) -> dict:
    session = context_of(message).get("session")
    return session if isinstance(session, dict) else {}


def message_lang(message: Any, fallback: str = "en-US") -> str:
    """The language this utterance is in.

    Looks in `data`, then `context`, then the session, then the skill's own
    language -- in that order, because the satellite sets `data["lang"]` per
    utterance while the session carries the hub's default. Reading only
    `context["lang"]`, as five skills did, misses both ends.
    """
    data, context = data_of(message), context_of(message)
    return standardize(
        data.get("lang") or context.get("lang") or session_of(message).get("lang")
        or fallback or "en-US"
    )


def context_value(message: Any, *keys: str, default: Any = None) -> Any:
    """The first of these keys present in the message context, then the data."""
    context, data = context_of(message), data_of(message)
    for key in keys:
        for source in (context, data):
            value = source.get(key)
            if value not in (None, "", {}, []):
                return value
    return default


def location(message: Any) -> dict | None:
    """The house's location, as the satellite attaches it to every utterance.

    Without it OVOS answers from its own default -- Lawrence, Kansas -- so the
    date-time skill reports the wrong hour and weather the wrong city. Three
    skills each had their own spelling of this lookup and they disagreed.
    """
    value = context_value(message, "location")
    return value if isinstance(value, dict) else None
