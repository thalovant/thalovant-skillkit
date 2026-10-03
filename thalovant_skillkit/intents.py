"""Padatious intent files, and the sentences they stand for.

Padatious trains one classifier per language on every skill's `.intent` files
together, so a sentence two skills both publish has one owner the authors never
chose. This module turns a skill's intent files into the plain sentences the
classifier sees -- expanded the way OVOS expands them, slots neutralised --
and reads the fleet corpus. The corpus itself is built by `thalovant/intent-corpus`, which
imports these same functions, so the two cannot drift.

The corpus is one JSON file per language::

    {"version": 1, "lang": "en-US", "built": "2026-09-08T14:00:00Z",
     "skills": {"thalovant-skill-weather.thalovant": {"repo": "...", "sha": "..."}},
     "lines": [{"skill": ..., "intent": ..., "file": ..., "line": 3,
                "raw": "will it (rain|snow)", "text": "will it rain"}, ...]}
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from ovos_spec_tools import MalformedTemplate, iter_expand

CORPUS_VERSION = 1

# A line can stand for thousands of sentences. Exact matching wants all of
# them; the cap only guards against a pathological file.
EXPANSIONS_PER_LINE = 4096
_SLOT = re.compile(r"\{[^{}]+\}")
# A language tag as the locale tree names it: `en-US`, `zh-Hant-TW`, `pt`.
# Tags come from `supported.json`, and they become file names, so anything
# else is dropped rather than turned into a path.
_LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
# What a slot becomes. The classifier sees a wildcard; a generic noun is the
# closest thing a sentence can carry, and two skills' `{city}` and `{place}`
# rightly become the same sentence.
SLOT_WORD = "something"


@dataclass(frozen=True)
class IntentLine:
    """One sentence a padatious line stands for, and where it came from."""

    skill: str
    intent: str
    lang: str
    file: str
    line: int
    raw: str
    text: str


# -- the template grammar ------------------------------------------------------
#
# OVOS reads an intent line as an OVOS-INTENT-1 template: `(a|b)` is a choice,
# `[x]` is optional, `<name>` is the vocabulary in `<name>.voc`, `{name}` is a
# slot. ovos-spec-tools is the reference expander, and the engines call it, so
# the kit calls it too instead of keeping a second grammar that can disagree.


def _bare_pipe(line: str) -> bool:
    """A `|` inside no `(...)` or `[...]`, and not inside a `{slot}` or a
    `<name>`: OVOS-INTENT-1 section 3.6 calls it malformed. ovos-spec-tools
    raises for it from 1.14 only; checked here so a 1.13 install (what the
    hubs pin) reads the same lines as a newer one."""
    depth = in_name = 0
    for char in line:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(depth - 1, 0)
        elif char in "{<":
            in_name += 1
        elif char in "}>":
            in_name = max(in_name - 1, 0)
        elif char == "|" and depth == 0 and in_name == 0:
            return True
    return False


def expand(line: str, vocabularies: Mapping[str, Sequence[str]] | None = None) -> list[str]:
    """Every sentence an intent line stands for, as OVOS expands it.

    `(a|b)` is a choice, `[x]` and `(x|)` are optional, groups nest, and
    `<name>` stands for every line of `vocabularies[name]`. `{slot}` is kept.
    A line OVOS refuses -- unbalanced brackets, a line that is only a slot, a
    `<name>` with no vocabulary, a pipe outside a group, and the rest of
    OVOS-INTENT-1 section 3.6 -- raises `MalformedTemplate`: OVOS logs it and
    trains nothing from it.
    """
    if _bare_pipe(line):
        raise MalformedTemplate(
            f"{line!r}: a pipe outside a group is not a branch separator and "
            f"cannot be literal input")
    return list(islice(iter_expand(line, dict(vocabularies or {})), EXPANSIONS_PER_LINE))


def vocabularies(locale_dir: Path, lang: str) -> dict[str, list[str]]:
    """The vocabularies a `<name>` in this language's intent files reads.

    What ovos-workshop gives the engine: every `.voc` anywhere under
    `locale/<lang>/`, keyed by its lower-cased file name, the first one found
    winning, each line lower-cased, blank and `#` lines dropped. The lines
    stay templates; `expand` expands them where they are used.
    """
    found: dict[str, list[str]] = {}
    root = Path(locale_dir) / lang
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*.voc")):
        name = path.stem.lower()
        if name in found:
            continue
        members = [line.strip().lower()
                   for line in path.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        if members:
            found[name] = members
    return found


def clean(text: str) -> str:
    """The sentence as the classifier compares it: slots neutralised, one
    space between words, lower case. Accents stay; they are part of the word."""
    return " ".join(_SLOT.sub(SLOT_WORD, text).split()).lower()


# -- a skill's own files --------------------------------------------------------

def intent_files(locale_dir: Path, lang: str) -> list[Path]:
    """Both layouts the fleet uses: `locale/<lang>/intents/*.intent` and the
    flat `locale/<lang>/*.intent`. Reading one layout silently loses skills."""
    return sorted((locale_dir / lang).glob("*.intent")) + sorted(
        (locale_dir / lang / "intents").glob("*.intent"))


def intent_lines(skill_root: Path, locale_dir: Path, lang: str, skill: str) -> list[IntentLine]:
    """Every sentence the skill publishes for `lang`, with file and line.

    A line OVOS refuses publishes nothing: the engine skips it, so the fleet
    does not hear it either. `checks.check_intent_templates` reports it.
    """
    out: list[IntentLine] = []
    vocab = vocabularies(locale_dir, lang)
    for path in intent_files(locale_dir, lang):
        relative = str(path.relative_to(skill_root))
        for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                sentences = expand(raw, vocab)
            except MalformedTemplate:
                continue
            seen: set[str] = set()
            for sentence in sentences:
                text = clean(sentence)
                if text and text not in seen:
                    seen.add(text)
                    out.append(IntentLine(skill, path.stem, lang, relative, number, raw, text))
    return out


def valid_lang(tag: object) -> bool:
    return isinstance(tag, str) and bool(_LANG_TAG.match(tag))


def locale_langs(locale_dir: Path) -> list[str]:
    """The languages a locale tree carries: `supported.json` when present,
    otherwise the directories that exist. Only well-formed tags; a locale
    tree with no directory at all carries no languages."""
    if not locale_dir.is_dir():
        return []
    supported = locale_dir / "supported.json"
    if supported.is_file():
        try:
            data = json.loads(supported.read_text(encoding="utf-8"))
            langs = data.get("locales") if isinstance(data, dict) else data
            if isinstance(langs, list):
                return [lang for lang in langs if valid_lang(lang)]
        except (OSError, ValueError):
            pass
    return sorted(p.name for p in locale_dir.iterdir() if p.is_dir() and valid_lang(p.name))


def sentence_key(lang: str, text: str) -> str:
    """How a sentence is named in the published index: a digest of language
    and text, so a skill can learn that a sentence is already someone's
    without the fleet's sentences leaving the private corpus."""
    return hashlib.sha256(f"{lang}\n{text}".encode()).hexdigest()


# -- the corpus ---------------------------------------------------------------

def load_corpus(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != CORPUS_VERSION:
        raise ValueError(f"{path}: corpus version {data.get('version')!r}, "
                         f"this kit reads {CORPUS_VERSION}")
    return data


def corpus_lines(corpus: dict) -> list[IntentLine]:
    lang = corpus["lang"]
    return [IntentLine(lang=lang, **entry) for entry in corpus["lines"]]
