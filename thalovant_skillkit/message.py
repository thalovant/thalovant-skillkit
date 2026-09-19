"""Read utterances, languages and context consistently across OVOS messages."""
from __future__ import annotations

from typing import Any

from langcodes import standardize_tag


def _canonical(lang: str) -> str:
    """Normalize BCP-47 casing and aliases, tolerating legacy malformed tags."""
    try:
        # BCP-47 extensions have their own casing: the `ca` in
        # en-GB-u-ca-gregory is a calendar key, not the Canadian region.
        return standardize_tag(str(lang).strip())
    except ValueError:
        pass
    parts = [part for part in str(lang).replace("_", "-").split("-") if part]
    if not parts:
        return ""
    # Best-effort casing for malformed legacy input that langcodes rejects.
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


def standardize(lang: str | None) -> str:
    """Preserve explicit region/script/extension tags; expand bare languages via OVOS.

    Older OVOS normalizers discard regions. Canonicalize structured tags directly
    so a Canadian French session remains ``fr-CA`` on every supported stack.
    """
    raw = lang or "en-US"
    canonical = _canonical(raw)
    if "-" in canonical:
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
