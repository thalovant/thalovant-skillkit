"""A skill's bundled `locale/` directory: which language to serve, and what it says.

Nineteen skills wrote `_resource_lang` and sixteen `_resource_lines`, and the
bodies barely differ -- thirteen of the nineteen are the *same algorithm*,
split only by whether they call `standardize_lang` or the deprecated
`standardize_lang_tag`. What kept them apart was not disagreement but a module
constant: each reads its own `LOCALE_DIR`, so the function could not be lifted
out without something to bind it to.

`SkillResources` is that something. A skill makes one, pointed at its own
locale directory, and gets the lookup, the caching and the vocabulary matching
that every skill was reimplementing.

    RESOURCES = SkillResources(Path(__file__).parent / "locale")
    ...
    if RESOURCES.voc_match("OpsCopilotKeyword", utterance, lang): ...
"""
from __future__ import annotations

from pathlib import Path

from .message import standardize
from .text import fold
from .vocab import contains_term, first_match

DEFAULT_LANG = "en-US"


class SkillResources:
    """The `locale/` tree of one skill."""

    def __init__(self, locale_dir: Path | str, default_lang: str = DEFAULT_LANG):
        self.root = Path(locale_dir)
        self.default_lang = default_lang
        # Cached per instance, because two skills have different locale trees
        # and a cache keyed only on the language would hand one skill the
        # other's answer. Plain dicts rather than lru_cache over a bound
        # method: that holds a reference to the instance through the cache, so
        # the instance outlives every reference to it. The keys here are a
        # handful of language tags and resource filenames, so the caches are
        # small and do not need eviction.
        self._lang_cache: dict[str | None, str] = {}
        self._lines_cache: dict[tuple[str, str, str], tuple[str, ...]] = {}
        # Vocabulary folded once per language and file rather than on every
        # match. A skill asks `mentions()` on the utterance path, so this runs
        # for every word someone says.
        self._folded_cache: dict[tuple[str, str], tuple[str, ...]] = {}

    # -- which language this skill can actually serve -------------------------

    def available_langs(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(sorted(p.name for p in self.root.iterdir() if p.is_dir()))

    def _resolve_lang(self, lang: str | None) -> str:
        """The bundled locale closest to `lang`: exact, then language, then en-US."""
        normalized = standardize(lang or self.default_lang)
        if (self.root / normalized).is_dir():
            return normalized
        primary = normalized.split("-", 1)[0].casefold()
        for candidate in self.available_langs():
            if candidate.split("-", 1)[0].casefold() == primary:
                return candidate
        return self.default_lang

    def lang(self, lang: str | None) -> str:
        if lang not in self._lang_cache:
            self._lang_cache[lang] = self._resolve_lang(lang)
        return self._lang_cache[lang]

    def candidate_langs(self, lang: str | None) -> tuple[str, ...]:
        """The languages to try in order: the requested one, then English.

        Falling back to English matters for vocabularies a translation has not
        reached yet -- without it the skill goes silent rather than answering
        in the wrong language, which is the worse of the two.
        """
        return tuple(dict.fromkeys((self.lang(lang), self.default_lang)))

    # -- what it says ---------------------------------------------------------

    def _lines(self, lang: str, folder: str, filename: str) -> tuple[str, ...]:
        key = (lang, folder, filename)
        if key not in self._lines_cache:
            self._lines_cache[key] = self._read_lines(lang, folder, filename)
        return self._lines_cache[key]

    def _read_lines(self, lang: str, folder: str, filename: str) -> tuple[str, ...]:
        path = self.root / lang / folder / filename
        if not path.exists():
            return ()
        return tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    def lines(self, lang: str | None, folder: str, filename: str,
              *, fallback: bool = False) -> tuple[str, ...]:
        """The lines of one resource file, comments and blanks dropped.

        Reads exactly the language asked for, because that is what every
        skill's `_resource_lines` did and because the language fallback belongs
        one level up, in the vocabulary match: a skill that loops candidates
        itself would otherwise fall back twice. Pass `fallback=True` for
        resources where an English answer beats no answer.
        """
        langs = self.candidate_langs(lang) if fallback else (self.lang(lang),)
        for candidate in langs:
            found = self._lines(candidate, folder, filename)
            if found:
                return found
        return ()

    def vocab(self, voc_name: str, lang: str | None) -> tuple[str, ...]:
        return self.lines(lang, "vocab", f"{voc_name}.voc")

    def _folded_vocab(self, lang: str, voc_name: str) -> tuple[str, ...]:
        """This vocabulary, folded once and kept."""
        key = (lang, voc_name)
        cached = self._folded_cache.get(key)
        if cached is None:
            cached = tuple(
                folded
                for folded in (fold(term) for term in self._lines(lang, "vocab", f"{voc_name}.voc"))
                if folded
            )
            self._folded_cache[key] = cached
        return cached

    def dialog_lines(self, name: str, lang: str | None) -> tuple[str, ...]:
        """Read the selected locale's dialog, falling back to the configured
        default locale if the file has no usable lines."""
        return self.lines(lang, "dialog", f"{name}.dialog", fallback=True)

    def dialog(self, name: str, lang: str | None, data: dict | None = None) -> str:
        """One rendered dialog line, or the name itself if the file is missing.

        Returning the name rather than raising is deliberate: a missing
        translation should sound wrong, not crash the skill mid-answer.
        """
        lines = self.dialog_lines(name, lang)
        if not lines:
            return name
        try:
            return lines[0].format(**(data or {}))
        except (KeyError, IndexError):
            return lines[0]

    # -- matching -------------------------------------------------------------

    def voc_match(self, voc_name: str, utterance: str, lang: str | None = None) -> bool:
        """Whether the utterance contains any term from this vocabulary.

        Uses the word-start rule from `vocab`, which is what five skills each
        got wrong on their own.
        """
        text = fold(utterance)
        if not text:
            return False
        resolved = self.lang(lang)
        for candidate in self.candidate_langs(lang):
            if any(contains_term(text, term, resolved)
                   for term in self._folded_vocab(candidate, voc_name)):
                return True
        return False

    def voc_term(self, voc_name: str, utterance: str, lang: str | None = None) -> str:
        """The matching term itself, longest first, or ""."""
        text = fold(utterance)
        if not text:
            return ""
        resolved = self.lang(lang)
        for candidate in self.candidate_langs(lang):
            found = first_match(text, self._folded_vocab(candidate, voc_name), resolved)
            if found:
                return found
        return ""

    def voc_match_lang(self, voc_name: str, utterance: str, lang: str | None = None) -> str:
        """Which language's vocabulary matched, or "" -- for skills that answer
        in the language the prompt was written in rather than the session's."""
        text = fold(utterance)
        if not text:
            return ""
        resolved = self.lang(lang)
        for candidate in self.candidate_langs(lang):
            if any(contains_term(text, term, resolved)
                   for term in self._folded_vocab(candidate, voc_name)):
                return candidate
        return ""
