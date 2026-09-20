# Copyright 2024, OpenVoiceOS
# Apache 2.0

import os
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

from langcodes import tag_distance
from ovos_plugin_manager.templates.agents import OptionMatcherEngine
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.parse import match_one

_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")

_ORDINAL_NAMES = ["first", "second", "third", "fourth", "fifth",
                  "sixth", "seventh", "eighth", "ninth", "tenth"]
_CARDINAL_NAMES = ["one", "two", "three", "four", "five",
                   "six", "seven", "eight", "nine", "ten"]


def _read_voc(path: str) -> Set[str]:
    """Read a .voc file into a set of lowercase stripped strings."""
    with open(path, encoding="utf-8") as fh:
        return {line.strip().lower() for line in fh if line.strip()}


@lru_cache(maxsize=1)
def _available_langs() -> List[str]:
    """Return canonical BCP-47 tags for all locale directories present on disk."""
    try:
        return [standardize_lang_tag(d) for d in os.listdir(_LOCALE_DIR)
                if os.path.isdir(os.path.join(_LOCALE_DIR, d))]
    except OSError:
        return ["en-US"]


def _best_lang(lang: str) -> str:
    """Return the closest available locale directory tag for *lang*.

    Uses :func:`langcodes.tag_distance` to find the best match among the
    locale directories shipped with this plugin, falling back to ``en-US``.
    """
    lang = standardize_lang_tag(lang)
    available = _available_langs()
    if lang in available:
        return lang
    best, best_dist = None, 100000
    for candidate in available:
        dist = tag_distance(lang, candidate)
        if dist < best_dist:
            best, best_dist = candidate, dist
    if best is None or best_dist > 10:
        raise ValueError(f"Unsupported language: {lang!r}. Available: {available}")
    return best


@lru_cache(maxsize=32)
def _load_last_vocab(lang: str) -> Set[str]:
    """Load last.voc for the locale closest to *lang*.

    Args:
        lang: BCP-47 language tag (any casing).

    Returns:
        Set of lowercase words/phrases meaning "last" in that language.
    """
    resolved = _best_lang(lang)
    path = os.path.join(_LOCALE_DIR, resolved, "last.voc")
    if os.path.isfile(path):
        return _read_voc(path)
    return {"last", "latest", "final"}


@lru_cache(maxsize=32)
def _load_position_vocab(lang: str) -> Dict[int, Set[str]]:
    """Load ordinal and cardinal .voc files into a 0-based position map.

    Both ``first.voc``/``one.voc`` … ``tenth.voc``/``ten.voc`` are merged per
    position.  Multi-word entries (e.g. "second one") are included verbatim so
    they win over shorter single-word entries during longest-match selection.

    Args:
        lang: BCP-47 language tag (any casing).

    Returns:
        Dict mapping 0-based index to a set of trigger words/phrases.
    """
    resolved = _best_lang(lang)
    result: Dict[int, Set[str]] = {}
    for i, (ord_name, card_name) in enumerate(zip(_ORDINAL_NAMES, _CARDINAL_NAMES)):
        words: Set[str] = set()
        for voc_name in (ord_name, card_name):
            path = os.path.join(_LOCALE_DIR, resolved, f"{voc_name}.voc")
            if os.path.isfile(path):
                words |= _read_voc(path)
        result[i] = words
    return result


class FuzzyOptionMatcherPlugin(OptionMatcherEngine):
    """OptionMatcherEngine that resolves a user utterance to a predefined slot.

    Resolution order (first match wins):

    1. Fuzzy match via rapidfuzz WRatio — if score >= min_conf.
    2. Locale-aware ``last.voc`` keyword — returns the final option.
    3. Ordinal/cardinal vocab (``first.voc`` … ``tenth.voc``, ``one.voc`` …
       ``ten.voc``).  Multi-word entries (e.g. "second one") are included in
       the vocab files and win over shorter single-word entries through
       longest-match selection, eliminating greedy false positives.
    4. Numeric fallback via ovos-number-parser (optional dependency).
    5. None if nothing matches.

    Config keys (under skill settings or mycroft.conf skills block):
        min_conf (float): minimum fuzzy-match confidence (default 0.65).
    """

    def match_option(self, utterance: str, options: List[str],
                     lang: Optional[str] = None) -> Optional[str]:
        """Resolve *utterance* to the best matching entry in *options*.

        Args:
            utterance: The raw user response.
            options: The predefined slots the skill offered.
            lang: BCP-47 language code for vocab and ordinal parsing.

        Returns:
            The matched option string, or None if no match.
        """
        lang = lang or "en-US"
        min_conf: float = self.config.get("min_conf", 0.65)
        utterance_lower = utterance.lower()

        # 1. Fuzzy match
        match, score = match_one(utterance, options)
        if score >= min_conf:
            return match

        # 2. Last-option vocab
        if any(w in utterance_lower for w in _load_last_vocab(lang)):
            return options[-1]

        # 3. Ordinal/cardinal vocab — longest matching entry wins.
        # Multi-word .voc entries (e.g. "second one") beat shorter single
        # words ("one") naturally, since we pick the longest matched phrase.
        position_vocab = _load_position_vocab(lang)
        best: Optional[Tuple[int, int]] = None  # (idx, matched_word_len)
        for idx in range(min(len(options), len(_ORDINAL_NAMES))):
            for phrase in position_vocab.get(idx, ()):
                if phrase in utterance_lower:
                    if best is None or len(phrase) > best[1]:
                        best = (idx, len(phrase))
        if best is not None:
            return options[best[0]]

        # 4. Numeric fallback via ovos-number-parser (optional)
        try:
            from ovos_number_parser import extract_number
            num = extract_number(utterance, ordinals=True, lang=lang)
            if num and 1 <= num <= len(options):
                return options[int(num) - 1]
        except ImportError:
            pass

        return None
