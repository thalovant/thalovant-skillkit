"""Deciding whether an utterance contains a vocabulary term.

This is the function that was wrong in five skills at once. Each matched its
`.voc` files with `term in text` -- plain substring containment -- so a short
line claimed any longer word that spelled it anywhere. ops-copilot's `logs.voc`
holds the line `log`, "technology" spells it at position six, and in a real
ovos-core the ops copilot answered

    what's the latest news about technology  ->  "Paste events or logs."

and did it again in French for "technologie". `log` also sits inside "apology"
and "catalog", `pod` inside "podcast", `clair` inside "eclair", `quoi` inside
"pourquoi". No skill's own tests caught it, because each skill was correct when
considered alone.

How a term may match is a fact about a language, not about this code, so it
lives in `locale/<lang>/matching.json` beside everything else the fleet keeps
per language. A language with no file of its own inherits en-US, the same way a
skill's locale does.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"
DEFAULT_LANG = "en-US"

# Used only when the bundled locale files are missing entirely -- a broken
# install rather than an unknown language, which the fallback below covers.
_FALLBACK_RULES = {"word_separated": True, "inflection_max": 3}


@lru_cache(maxsize=1)
def available_langs() -> tuple[str, ...]:
    if not LOCALE_DIR.is_dir():
        return ()
    return tuple(sorted(p.name for p in LOCALE_DIR.iterdir() if p.is_dir()))


@lru_cache(maxsize=256)
def _rules_lang(lang: str | None) -> str:
    """The bundled locale closest to `lang`: exact, then language, then en-US."""
    from .message import standardize

    normalized = standardize(lang or DEFAULT_LANG)
    langs = available_langs()
    if normalized in langs:
        return normalized
    primary = normalized.split("-", 1)[0].casefold()
    for candidate in langs:
        if candidate.split("-", 1)[0].casefold() == primary:
            return candidate
    return DEFAULT_LANG


@lru_cache(maxsize=256)
def matching_rules(lang: str | None) -> tuple[bool, int]:
    """(word_separated, inflection_max) for this language.

    `word_separated` is false for languages that do not put spaces between
    words -- a word boundary means nothing there, so a term is matched by plain
    containment. `inflection_max` is how many letters a term may pick up and
    still be the same word: three covers "logs" and "expliquer" without letting
    `pod` reach "podcast", and agglutinative languages say a larger number,
    because a word there takes several suffixes in a row.
    """
    path = LOCALE_DIR / _rules_lang(lang) / "matching.json"
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rules = _FALLBACK_RULES
    separated = bool(rules.get("word_separated", _FALLBACK_RULES["word_separated"]))
    try:
        inflection = int(rules.get("inflection_max", _FALLBACK_RULES["inflection_max"]))
    except (TypeError, ValueError):
        inflection = _FALLBACK_RULES["inflection_max"]
    return separated, max(0, inflection)


@lru_cache(maxsize=8192)
def term_pattern(term: str, inflection_max: int = 3) -> re.Pattern:
    """A term as it may appear in speech: beginning a word, plus an inflection."""
    return re.compile(rf"(?<!\w){re.escape(term)}\w{{0,{inflection_max}}}(?!\w)")


def is_wordless(lang: str | None) -> bool:
    """Whether this language writes without spaces between words."""
    separated, _ = matching_rules(lang)
    return not separated


def contains_term(text: str, term: str, lang: str = DEFAULT_LANG) -> bool:
    """Whether a word in `text` begins with `term`.

    Anchoring both ends of the term is the obvious fix and it is wrong: these
    vocabularies list `log`, `pod`, `incident`, `message`, `clair` in the
    singular and rely on them catching "logs", "pods", "incidents", "messages",
    "clairs", and `explique` on catching "expliquer". Requiring an exact word
    broke every one of those. Allowing a bounded inflection keeps them and
    still stops `pod` reaching "podcast".
    """
    if not term or not text:
        return False
    separated, inflection = matching_rules(lang)
    if not separated:
        return term in text
    return bool(term_pattern(term, inflection).search(text))


def matches_any(text: str, terms, lang: str = DEFAULT_LANG) -> bool:
    return any(contains_term(text, term, lang) for term in terms if term)


def first_match(text: str, terms, lang: str = DEFAULT_LANG) -> str:
    """The first term that matches, longest first so the most specific wins."""
    for term in sorted((t for t in terms if t), key=len, reverse=True):
        if contains_term(text, term, lang):
            return term
    return ""
