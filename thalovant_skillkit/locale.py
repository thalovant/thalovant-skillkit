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

from functools import lru_cache
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
        # Bound per instance: two skills have different locale trees, and a
        # cache keyed only on the language would hand one skill the other's
        # answer.
        self._lang = lru_cache(maxsize=128)(self._resolve_lang)
        self._lines = lru_cache(maxsize=4096)(self._read_lines)

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
        return self._lang(lang)

    def candidate_langs(self, lang: str | None) -> tuple[str, ...]:
        """The languages to try in order: the requested one, then English.

        Falling back to English matters for vocabularies a translation has not
        reached yet -- without it the skill goes silent rather than answering
        in the wrong language, which is the worse of the two.
        """
        return tuple(dict.fromkeys((self.lang(lang), self.default_lang)))

    # -- what it says ---------------------------------------------------------

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

    def dialog_lines(self, name: str, lang: str | None) -> tuple[str, ...]:
        """Falls back to English: a translation that has not landed yet should
        sound wrong rather than leave the skill silent mid-answer."""
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
            terms = self._lines(candidate, "vocab", f"{voc_name}.voc")
            if any(contains_term(text, fold(term), resolved) for term in terms):
                return True
        return False

    def voc_term(self, voc_name: str, utterance: str, lang: str | None = None) -> str:
        """The matching term itself, longest first, or ""."""
        text = fold(utterance)
        if not text:
            return ""
        resolved = self.lang(lang)
        for candidate in self.candidate_langs(lang):
            terms = [fold(t) for t in self._lines(candidate, "vocab", f"{voc_name}.voc")]
            found = first_match(text, terms, resolved)
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
            terms = self._lines(candidate, "vocab", f"{voc_name}.voc")
            if any(contains_term(text, fold(term), resolved) for term in terms):
                return candidate
        return ""
