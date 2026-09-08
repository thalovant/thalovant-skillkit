"""Folding text so that a vocabulary line and a spoken phrase can be compared.

Fifteen skills wrote `_fold` in nine shapes. Most of the difference was not
disagreement but scope: seven wanted "casefold and drop accents", and the rest
wanted that plus one more thing -- hyphens treated as spaces because the
showroom types "Donne-moi" where voice sends "donne moi", or punctuation
removed entirely, or the whole string reduced to letters and digits.

So this is not one function. It is the base, plus the named variants the skills
actually needed, so that a skill picks the one it means instead of writing a
tenth.
"""
from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[^\w\s]")
_NOT_ALNUM = re.compile(r"[^0-9a-z]+")
# Every dash a keyboard or a transcript can produce, plus the typographic
# apostrophe, which French text is full of and voice never sends.
_HYPHENS = re.compile(r"[-‐-―−]")


def strip_accents(text: str) -> str:
    """"café" -> "cafe", leaving case and punctuation alone."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Casefolded and accent-free. The default, and what seven skills meant."""
    return strip_accents((text or "").casefold())


def fold_spaces(text: str) -> str:
    """`fold`, with hyphens and typographic apostrophes normalised to plain ones
    and runs of whitespace collapsed -- so one vocabulary line matches both
    "Donne-moi" as typed and "donne moi" as spoken."""
    folded = _HYPHENS.sub(" ", fold(text)).replace("’", "'")
    return _WHITESPACE.sub(" ", folded).strip()


def fold_words(text: str) -> str:
    """`fold_spaces`, with punctuation dropped: "what's up!" -> "what s up"."""
    return _WHITESPACE.sub(" ", _NOT_WORD.sub(" ", fold_spaces(text))).strip()


def fold_tight(text: str) -> str:
    """Letters and digits only: "Test-Value" -> "testvalue".

    For comparing identifiers -- a city name typed against the same name
    spelled with accents -- not for matching what someone said.
    """
    return _NOT_ALNUM.sub("", fold(text))
