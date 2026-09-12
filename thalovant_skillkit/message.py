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
def _canonical(lang: str) -> str:
    """The shape a locale directory is named in: "fr_fr" -> "fr-FR", "fr" -> "fr".

    Applied to whatever the OVOS normaliser returns, because what it returns
    depends on which version is installed. ovos-utils 0.8.5 -- the floor the
    skills themselves declare -- strips the region ("en-us" -> "en",
    "FR-fr" -> "fr") and leaves an underscore alone ("fr_fr" -> "fr_fr"), while
    0.14 returns "en-US" and "fr-FR". A skill resolving "fr_fr" against the
    older one found no `fr_fr` directory, split on "-" to get a primary of
    "fr_fr", matched nothing, and served French in English.

    Canonicalising here makes the answer the same on every version.
    """
    parts = [part for part in str(lang).replace("_", "-").split("-") if part]
    if not parts:
        return ""
    # A tag is language-[script]-[region]-[variant...], and each part has its
    # own casing: "zh-Hant-TW". Upper-casing the second part regardless turned
    # that into "zh-HANT" and dropped the region entirely, which the
    # source-scout locale test caught.
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            canonical.append(part.title())          # script: Hant
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())          # region: TW, 419
        else:
            canonical.append(part.lower())          # variant
    return "-".join(canonical)


try:  # pragma: no cover - which import wins depends on the installed stack
    from ovos_spec_tools import standardize_lang as _standardize
except ImportError:  # pragma: no cover
    try:
        from ovos_utils.lang import standardize_lang as _standardize
    except ImportError:
        try:
            from ovos_utils.lang import standardize_lang_tag as _standardize
        except ImportError:
            _standardize = _canonical

# The keys a message may carry its text under. `utterance` is what the intent
# pipeline sends; the others arrive from OCP search, converse and the showroom
# preview, and two skills already read them. A skill that reads only the first
# goes silent on the other three paths.
_TEXT_KEYS = ("utterance", "phrase", "text", "query")


def _has_region(tag: str) -> bool:
    """Whether the tag already names a region, which is the part that gets lost."""
    return any((len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit())
               for part in tag.split("-")[1:])


def standardize(lang: str | None) -> str:
    """A BCP-47 tag in the shape a locale directory uses.

    The region comes from the tag as given, never from the OVOS normaliser,
    because older versions throw it away: ovos-utils 0.8.5 -- the floor the
    skills themselves declare -- turns "en-us" into "en" and "FR-fr" into "fr".
    Nothing downstream can recover a region that has already been discarded, so
    a caller asking for "FR-fr" has to be answered from its own text.

    The normaliser is still consulted for a bare language, where there is no
    region to lose and its language knowledge is worth having.
    """
    raw = lang or "en-US"
    canonical = _canonical(raw)
    if _has_region(canonical):
        return canonical
    return _canonical(_standardize(raw)) or canonical


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
    """Read location from message context, then data, when it is a dictionary.

    Return None for a missing or non-dictionary selected value. This helper
    does not consult the session or supply a geographic or timezone default.
    """
    value = context_value(message, "location")
    return value if isinstance(value, dict) else None
