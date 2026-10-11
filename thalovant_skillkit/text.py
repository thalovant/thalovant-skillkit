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

# A combining mark is an accent in some scripts and a letter in others.
#
# On Latin, Greek and Cyrillic it is a diacritic ("é", "ά", "й"), and Arabic
# harakat and Hebrew niqqud are vowel points nobody types: dropping those is
# what lets "cafe" match "café". In the Brahmic and South-East Asian scripts
# the mark is the spelling: Devanagari "ि" or "्", the Thai tone marks, the
# Tamil pulli. Dropping the virama turned "क्रिकेट" into "करिकेट", and the
# vowel signs, which `\w` does not match, split every Hindi word into
# consonants ("खेल" -> "ख ल"), so no Hindi topic ever matched. The kana
# voicing marks are the same case: "が" is not "か".
#
# These blocks keep their marks, except the nukta. A mark anywhere else folds
# as it always has.
_KEPT_MARK_BLOCKS = (
    (0x0900, 0x0DFF),  # Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil,
                       # Telugu, Kannada, Malayalam, Sinhala
    (0x0E00, 0x0EFF),  # Thai, Lao
    (0x0F00, 0x0FFF),  # Tibetan
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
    (0x1A20, 0x1AAF),  # Tai Tham
    (0x1B00, 0x1BFF),  # Balinese, Sundanese, Batak
    (0x1CD0, 0x1CFF),  # Vedic Extensions
    (0x3099, 0x309A),  # combining kana voiced and semi-voiced sound marks
    (0xA8E0, 0xA8FF),  # Devanagari Extended
    (0xA980, 0xA9FF),  # Javanese, Myanmar Extended-B
    (0xAA60, 0xAA7F),  # Myanmar Extended-A
)
# The nukta still folds. It is the dot that turns "ज" into "ज़" for a borrowed
# sound, and Hindi writes the same word with and without it: the fleet's own
# vocabulary lists "दरवाज़ा" and "दरवाजा" side by side, and every Hindi line the
# old fold made identical to another (60 of them) differed only by a nukta.
KEPT_MARKS = frozenset(
    chr(point)
    for start, end in _KEPT_MARK_BLOCKS
    for point in range(start, end + 1)
    if unicodedata.category(chr(point)).startswith("M")
    and not unicodedata.name(chr(point), "").endswith("SIGN NUKTA")
)
_KEPT_MARK_CLASS = "".join(sorted(KEPT_MARKS))
#: One character of a word: what `\w` matches, plus a mark that is part of a
#: letter. Use it where a pattern would say `\w` about folded text.
WORD_CHAR = rf"[\w{_KEPT_MARK_CLASS}]"

_WHITESPACE = re.compile(r"\s+")
_NOT_WORD = re.compile(rf"[^\w\s{_KEPT_MARK_CLASS}]")
_NOT_ALNUM = re.compile(r"[^0-9a-z]+")
# Every dash a keyboard or a transcript can produce, plus the typographic
# apostrophe, which French text is full of and voice never sends.
_HYPHENS = re.compile(r"[-‐-―−]")


def strip_accents(text: str) -> str:
    """"café" -> "cafe", leaving case and punctuation alone.

    Only accents: a mark that spells a letter, as in Hindi or Thai, stays.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if c in KEPT_MARKS or not unicodedata.combining(c))


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
