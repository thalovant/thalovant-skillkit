"""Every word a Thalovant component's rule turns on, for every language it
supports, in one place and out of every codebase.

A voice satellite waits on "turn off the" because "the" is a continuation
word; an intent listing closes "quelle heure est-il" with a question mark
because "quelle" opens a question; a French synthesiser is told to say
"onze minutes" where it would swallow a consonant. Each of those is a fact
about a language, not about the program that needs it, and each used to be
a constant in whichever program needed it first. Here they are data, one
directory per language::

    languages/<tag>/language.yaml   the words and rules a language has (KEYS)
    languages/scripts.yaml          what a writing system does that no word list can

A language is found by the matcher the rest of OVOS uses
(``ovos_spec_tools.language``): ``fr-CA`` reads the French file, ``pt-BR``
the Portuguese one. A language nothing describes gets an empty mapping --
no rule, rather than another language's rule -- and adding one is adding a
directory here. ``THALOVANT_LANGUAGES_DIR`` names a checkout's
``languages/`` tree to read instead of the installed data, for trying a
language before it is released.
"""
from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from ovos_spec_tools.language import closest_lang

from . import _plural
from ._version import __version__

__all__ = [
    "KEYS", "ENV_OVERRIDE", "__version__", "asks", "check", "described", "language",
    "marks", "plural_category", "refresh", "root", "script_pattern", "scripts", "words",
]

DATA_ROOT = Path(__file__).resolve().parent / "languages"
ENV_OVERRIDE = "THALOVANT_LANGUAGES_DIR"

#: The keys a ``language.yaml`` may carry, and what a component does with each.
#: Every one is optional; ``check()`` refuses a file naming any other.
KEYS: dict[str, str] = {
    "continuation_words": "a partial transcript ending here is mid-thought; the endpoint waits",
    "trailing_words": "a registered phrase ending here is a prefix waiting for an entity, not a sentence",
    "question_openers": "a phrase opening here is a question",
    "question_words_anywhere": "a phrase holding one of these anywhere is a question",
    "question_patterns": "regular expressions (case-insensitive) that make a phrase a question",
    "written_forms": "words spelled their own way once a phrase is set as a sentence",
    "plural": "the language's CLDR plural rules, a category to its rule; 'other' is what remains",
    "slot_examples": "what a slot becomes when a pattern is read aloud",
    "lowercase_map": "applied to an all-capitals transcript, in order, before lower()",
    "speech_substitutions": "rewrites for what a synthesiser is known to mispronounce",
}
_LIST_KEYS = {"continuation_words", "trailing_words", "question_openers",
              "question_words_anywhere", "question_patterns"}
_MAP_KEYS = {"written_forms", "slot_examples", "lowercase_map"}
_PLURAL_CATEGORIES = {"zero", "one", "two", "few", "many"}
_SCRIPT_CLASSES = ("unspaced", "syllabic")
_MARK_KINDS = ("sentence_ends", "clause_breaks")


def root() -> Path:
    """Where the data is read from: the override tree when set, else the
    installed data."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    return Path(override).expanduser() if override else DATA_ROOT


def refresh() -> None:
    """Forget everything read so far, after changing the override."""
    for cached in (_described, _language, _scripts, _script_pattern, _question_patterns):
        cached.cache_clear()


@lru_cache(maxsize=4)
def _described(where: str) -> tuple[str, ...]:
    base = Path(where)
    if not base.is_dir():
        return ()
    return tuple(sorted(p.name for p in base.iterdir() if (p / "language.yaml").is_file()))


def described() -> tuple[str, ...]:
    """Every language with a file, by directory name."""
    return _described(str(root()))


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=64)
def _language(where: str, tag: str) -> dict[str, Any]:
    languages = _described(where)
    match = closest_lang(tag, list(languages)) if languages else None
    if match is None:
        return {}
    data = _load(Path(where) / match / "language.yaml")
    # A regional file says only what differs from the language: CLDR gives
    # `pt-PT` its own plural rule and nothing else, so the words come from
    # `pt`. The region's keys win where both say something.
    parent = match.split("-")[0]
    if parent != match and parent in languages:
        data = {**_load(Path(where) / parent / "language.yaml"), **data}
    return data


def language(tag: str | None) -> dict[str, Any]:
    """What is known about a language: its file, by the closest tag, with
    its parent language's file underneath a regional one. An empty mapping
    for a language nothing describes, or for none at all."""
    if not tag:
        return {}
    return _language(str(root()), str(tag).strip())


def plural_category(tag: str | None, n: int) -> str:
    """Which plural form a count takes in the language, by its CLDR rules:
    "one", "few", "many"... or "other". With no rules known, one is "one"
    and everything else "other", the least surprising guess."""
    return _plural.category(language(tag).get("plural"), n)


def words(tag: str | None, key: str) -> frozenset[str]:
    """One word list of a language, lower-cased. With no language at all,
    every described language's list together: a listing with no language
    still ranks phrases it cannot place, and a trailing word in any language
    still marks a prefix rather than a sentence."""
    tags = (tag,) if tag else described()
    return frozenset(str(word).lower() for t in tags for word in language(t).get(key) or ())


@lru_cache(maxsize=64)
def _question_patterns(where: str, tag: str | None) -> tuple[re.Pattern[str], ...]:
    tags = (tag,) if tag else described()
    return tuple(re.compile(str(pattern), re.IGNORECASE)
                 for t in tags for pattern in language(t).get("question_patterns") or ())


def asks(text: str, tag: str | None) -> bool:
    """Whether ``text`` asks something, by the language's own words: it opens
    on one of its ``question_openers``, holds one of its
    ``question_words_anywhere``, or matches one of its ``question_patterns``.
    A closing question mark of any script counts in any language. With no
    language, every described language's words are tried. A language nothing
    describes gets nothing but the question mark."""
    text = text.strip()
    if not text:
        return False
    if "QUESTION MARK" in unicodedata.name(text[-1], ""):
        return True
    if any(pattern.search(text) for pattern in _question_patterns(str(root()), tag)):
        return True
    found = [word.strip(",;:!?.\u2019'\"()").lower() for word in text.split()]
    found = [word for word in found if word]
    if not found:
        return False
    if found[0] in words(tag, "question_openers"):
        return True
    anywhere = words(tag, "question_words_anywhere")
    if anywhere.intersection(found):
        return True
    # Chinese and other unspaced scripts do not put a space after a word.
    # Limit substring matching to words wholly in those scripts: English
    # "is" must never claim "island", even in a mixed-language sentence.
    unspaced = script_pattern("unspaced")
    if not unspaced.search(text):
        return False
    normalized = " ".join(found)

    def is_unspaced(word: str) -> bool:
        return bool(word) and all(unspaced.fullmatch(char) for char in word)

    return (
        any(found[0].startswith(word) for word in words(tag, "question_openers") if is_unspaced(word))
        or any(word in normalized for word in anywhere if is_unspaced(word))
    )


@lru_cache(maxsize=4)
def _scripts(where: str) -> dict[str, Any]:
    path = Path(where) / "scripts.yaml"
    return _load(path) if path.is_file() else {}


def scripts() -> dict[str, Any]:
    """What is known about writing systems: ``scripts.yaml``."""
    return _scripts(str(root()))


def marks(kind: str, spacing: str) -> str:
    """The punctuation listed under ``kind`` (``sentence_ends``,
    ``clause_breaks``) for ``spaced`` or ``unspaced`` scripts, as one string."""
    return str((scripts().get(kind) or {}).get(spacing) or "")


def _code_point(value: object) -> int:
    text = str(value).strip()
    return int(text[2:] if text.upper().startswith("U+") else text, 16)


@lru_cache(maxsize=8)
def _script_pattern(where: str, kind: str) -> re.Pattern[str]:
    ranges = (_scripts(where).get(kind) or {}).get("ranges") or ()
    if not ranges:
        return re.compile(r"(?!)")
    classes = "".join(
        re.escape(chr(_code_point(block["first"]))) + "-" + re.escape(chr(_code_point(block["last"])))
        for block in ranges)
    return re.compile(f"[{classes}]")


def script_pattern(kind: str) -> re.Pattern[str]:
    """One character of any block listed under ``kind`` in ``scripts.yaml``
    (``unspaced``, ``syllabic``). With no blocks it matches nothing."""
    return _script_pattern(str(root()), kind)


# -- the gate ---------------------------------------------------------------------

def check(where: Path | None = None) -> list[str]:
    """Every problem with the data tree, as one line each; empty when it is
    sound. The tests run this on the shipped tree and the CLI on a checkout,
    so a misspelt key, a pattern that does not compile or a bare ``on`` that
    YAML read as a boolean fails here rather than on the first utterance."""
    base = Path(where) if where is not None else root()
    problems: list[str] = []
    if not base.is_dir():
        return [f"{base}: not a directory"]
    seen = False
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        path = directory / "language.yaml"
        if not path.is_file():
            continue
        seen = True
        problems.extend(f"{directory.name}: {problem}" for problem in _check_language(path))
    if not seen:
        problems.append(f"{base}: no <tag>/language.yaml at all")
    scripts_path = base / "scripts.yaml"
    if scripts_path.is_file():
        problems.extend(f"scripts.yaml: {problem}" for problem in _check_scripts(scripts_path))
    else:
        problems.append("scripts.yaml: missing")
    return problems


def _check_language(path: Path) -> list[str]:
    out: list[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as failure:
        return [f"not YAML: {failure}"]
    if not isinstance(data, dict) or not data:
        return ["not a mapping, or empty"]
    for key in sorted(set(data) - set(KEYS)):
        out.append(f"{key}: not a key any component reads (see KEYS)")
    for key in _LIST_KEYS & set(data):
        value = data[key]
        if not isinstance(value, list) or not value:
            out.append(f"{key}: must be a non-empty list")
            continue
        odd = [w for w in value if not isinstance(w, str) or not w.strip()]
        if odd:
            out.append(f"{key}: {odd!r} -- quote a word YAML reads as something else (on, off, yes, no)")
        if len(set(value)) != len(value):
            out.append(f"{key}: repeats a word")
    for key in _MAP_KEYS & set(data):
        value = data[key]
        if not isinstance(value, dict) or not value:
            out.append(f"{key}: must be a non-empty mapping")
            continue
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            out.append(f"{key}: every entry must map a word to a word")
    for upper, lower in (data.get("lowercase_map") or {}).items():
        if isinstance(upper, str) and isinstance(lower, str) and (upper == lower or lower != lower.lower()):
            out.append(f"lowercase_map: {upper!r} -> {lower!r} is not upper to lower")
    for pattern in data.get("question_patterns") or ():
        if isinstance(pattern, str):
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as failure:
                out.append(f"question_patterns: {pattern!r} does not compile: {failure}")
    plural = data.get("plural")
    if plural is not None:
        if not isinstance(plural, dict):
            out.append("plural: must map a category to its CLDR rule (an empty mapping: every count is 'other')")
        else:
            for category, rule in plural.items():
                if category not in _PLURAL_CATEGORIES:
                    out.append(f"plural: {category!r} is not a category (zero, one, two, few, many)")
                try:
                    _plural.parse(str(rule))
                except _plural.PluralRuleError as failure:
                    out.append(f"plural: {failure}")
    for rule in data.get("speech_substitutions") or ():
        if not isinstance(rule, dict) or not {"pattern", "replace"} <= set(rule):
            out.append(f"speech_substitutions: {rule!r} needs pattern and replace")
            continue
        extra = sorted(set(rule) - {"pattern", "replace", "why"})
        if extra:
            out.append(f"speech_substitutions: {extra} are not rule fields")
        try:
            re.compile(str(rule["pattern"]), re.IGNORECASE)
        except re.error as failure:
            out.append(f"speech_substitutions: {rule['pattern']!r} does not compile: {failure}")
    return out


def _check_scripts(path: Path) -> list[str]:
    out: list[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as failure:
        return [f"not YAML: {failure}"]
    if not isinstance(data, dict):
        return ["not a mapping"]
    for kind in _SCRIPT_CLASSES:
        section = data.get(kind)
        if not isinstance(section, dict) or not section.get("ranges"):
            out.append(f"{kind}: needs a list of ranges")
            continue
        for block in section["ranges"]:
            if not isinstance(block, dict) or not {"name", "first", "last"} <= set(block):
                out.append(f"{kind}: {block!r} needs name, first and last")
                continue
            try:
                if _code_point(block["first"]) > _code_point(block["last"]):
                    out.append(f"{kind}: {block['name']} ends before it starts")
            except ValueError:
                out.append(f"{kind}: {block['name']} has a code point that is not U+XXXX")
    for kind in _MARK_KINDS:
        section = data.get(kind)
        if not isinstance(section, dict):
            out.append(f"{kind}: needs spaced and unspaced marks")
            continue
        for spacing in ("spaced", "unspaced"):
            if not isinstance(section.get(spacing), str) or not section[spacing]:
                out.append(f"{kind}: {spacing} marks missing")
    return out
