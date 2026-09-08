"""Padatious intent files, and the sentences they stand for.

Padatious trains one classifier per language on every skill's `.intent` files
together, so a sentence two skills both publish has one owner the authors never
chose. This module turns a skill's intent files into the plain sentences the
classifier sees -- alternations expanded, slots neutralised -- and reads or
writes the fleet corpus that lets a skill compare itself with every other one
without cloning them.

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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

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


# -- padatious syntax ---------------------------------------------------------

def _split_top_level(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def expand(line: str) -> list[str]:
    """Every sentence a padatious line stands for.

    `(a|b)` is a choice, `(a|)` makes `a` optional, groups nest. Unbalanced
    parentheses are passed through: padatious would not read them either.
    """
    start = line.find("(")
    if start < 0:
        return [line]
    depth, end = 0, -1
    for i in range(start, len(line)):
        if line[i] == "(":
            depth += 1
        elif line[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return [line]
    head, choices, tail = line[:start], line[start + 1:end], line[end + 1:]
    out: list[str] = []
    for choice in _split_top_level(choices, "|"):
        for inner in expand(choice):
            for rest in expand(tail):
                out.append(head + inner + rest)
                if len(out) >= EXPANSIONS_PER_LINE:
                    return out
    return out


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
    """Every sentence the skill publishes for `lang`, with file and line."""
    out: list[IntentLine] = []
    for path in intent_files(locale_dir, lang):
        relative = str(path.relative_to(skill_root))
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            seen: set[str] = set()
            for sentence in expand(raw):
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

def _now() -> str:
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace("+00:00", "Z")


def build_corpus(skills: list[tuple[str, Path, Path, dict]], lang: str) -> dict:
    """One language of the fleet corpus.

    `skills` holds `(skill_id, skill_root, locale_dir, metadata)`; metadata is
    whatever the builder knows (`repo`, `sha`) and is carried verbatim so a
    reader can say which commit a sentence came from.
    """
    lines: list[IntentLine] = []
    meta: dict[str, dict] = {}
    for skill_id, root, locale_dir, metadata in skills:
        found = intent_lines(root, locale_dir, lang, skill_id)
        if not found:
            continue
        lines.extend(found)
        meta[skill_id] = dict(metadata)
    return {
        "version": CORPUS_VERSION,
        "lang": lang,
        "built": _now(),
        "skills": meta,
        "lines": [{k: v for k, v in asdict(line).items() if k != "lang"} for line in lines],
    }


def write_corpus(directory: Path, corpus: dict) -> Path:
    if not valid_lang(corpus.get("lang")):
        raise ValueError(f"not a language tag: {corpus.get('lang')!r}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{corpus['lang']}.json"
    path.write_text(json.dumps(corpus, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return path


def load_corpus(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != CORPUS_VERSION:
        raise ValueError(f"{path}: corpus version {data.get('version')!r}, "
                         f"this kit reads {CORPUS_VERSION}")
    return data


def corpus_lines(corpus: dict) -> list[IntentLine]:
    lang = corpus["lang"]
    return [IntentLine(lang=lang, **entry) for entry in corpus["lines"]]
