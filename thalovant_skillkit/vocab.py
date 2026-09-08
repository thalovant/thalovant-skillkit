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

Fixing it meant the same edit in five repositories. It lives here now so that
the sixth skill inherits the fix instead of the bug.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Languages that do not put spaces between words. A word boundary means nothing
# in them, so terms there keep plain containment.
WORDLESS_SCRIPTS = frozenset({"ja", "ko", "th", "zh"})

# An inflection is a letter or three -- "pods", "logs", "incidents", "messages",
# "clairs", "expliquer". A fourth letter is a different word: "podcast".
_INFLECTION = r"\w{0,3}"


@lru_cache(maxsize=8192)
def term_pattern(term: str) -> re.Pattern:
    """A term as it may appear in speech: beginning a word, plus an inflection."""
    return re.compile(rf"(?<!\w){re.escape(term)}{_INFLECTION}(?!\w)")


def is_wordless(lang: str | None) -> bool:
    return (lang or "").lower().replace("_", "-").split("-", 1)[0] in WORDLESS_SCRIPTS


def contains_term(text: str, term: str, lang: str = "en-US") -> bool:
    """Whether a word in `text` begins with `term`.

    Anchoring both ends of the term is the obvious fix and it is wrong: these
    vocabularies list `log`, `pod`, `incident`, `message`, `clair` in the
    singular and rely on them catching "logs", "pods", "incidents", "messages",
    "clairs", and `explique` on catching "expliquer". Requiring an exact word
    broke every one of those. Allowing three trailing letters keeps them and
    still stops `pod` reaching "podcast".
    """
    if not term or not text:
        return False
    if is_wordless(lang):
        return term in text
    return bool(term_pattern(term).search(text))


def matches_any(text: str, terms, lang: str = "en-US") -> bool:
    return any(contains_term(text, term, lang) for term in terms if term)


def first_match(text: str, terms, lang: str = "en-US") -> str:
    """The first term that matches, longest first so the most specific wins."""
    for term in sorted((t for t in terms if t), key=len, reverse=True):
        if contains_term(text, term, lang):
            return term
    return ""
