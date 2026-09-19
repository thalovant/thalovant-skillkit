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

from langcodes import Language
from ovos_spec_tools.language import lang_distance, lang_matches

from .message import standardize
from .text import fold, fold_words
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
        self._matching_langs_cache: dict[str | None, tuple[str, ...]] = {}
        self._candidate_langs_cache: dict[str | None, tuple[str, ...]] = {}
        self._lines_cache: dict[tuple[str, str, str], tuple[str, ...]] = {}
        # Vocabulary folded once per language and file rather than on every
        # match. A skill asks `mentions()` on the utterance path, so this runs
        # for every word someone says.
        self._folded_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self._literal_intent_cache: dict[tuple[tuple[str, ...], str], frozenset[str]] = {}

    # -- which language this skill can actually serve -------------------------

    def available_langs(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(sorted(p.name for p in self.root.iterdir() if p.is_dir()))

    def _resolve_lang(self, lang: str | None) -> str:
        """An exact regional override, the language's reference locale, or the default."""
        candidates = self.matching_langs(lang) or self.matching_langs(self.default_lang)
        return candidates[0] if candidates else self.default_lang

    def matching_langs(self, lang: str | None) -> tuple[str, ...]:
        """Bundled, script-compatible locales, without the unrelated default.

        Prefer an exact tag, then a parent tag, then the language's reference
        variety (en-US, fr-FR, pt-PT, ...), then other usable regional resources.
        OVOS's language-distance policy supplies compatibility and reference
        regions; no table of country aliases or copied locale trees is needed.
        Directory names are returned unchanged, including legacy casing.
        """
        if lang not in self._matching_langs_cache:
            normalized = standardize(lang or self.default_lang)
            try:
                parsed = Language.get(normalized)
            except ValueError:
                self._matching_langs_cache[lang] = ()
                return ()
            reference = Language.make(language=parsed.language, script=parsed.script).to_tag()

            def rank(candidate: str) -> tuple:
                tag = standardize(candidate)
                # A region/script parent remains first when the request adds
                # a variant, Unicode extension or private-use suffix.
                parent = normalized == tag or normalized.startswith(tag + "-")
                return (not parent, -len(tag) if parent else 0,
                        tag != standardize(self.default_lang), lang_distance(reference, tag),
                        lang_distance(normalized, tag), tag, candidate)

            self._matching_langs_cache[lang] = tuple(sorted(
                (candidate for candidate in self.available_langs()
                 if lang_matches(normalized, standardize(candidate))), key=rank,
            ))
        return self._matching_langs_cache[lang]

    def lang(self, lang: str | None) -> str:
        if lang not in self._lang_cache:
            self._lang_cache[lang] = self._resolve_lang(lang)
        return self._lang_cache[lang]

    def candidate_langs(self, lang: str | None) -> tuple[str, ...]:
        """Regional overrides, compatible language resources, then the default.

        A partial fr-CA folder inherits missing files from fr-FR before English.
        The configured default is a last resort, never a substitute for an
        available same-language translation. This does not change session/TTS
        language or claim that a fallback text is a regional translation.
        """
        if lang not in self._candidate_langs_cache:
            defaults = self.matching_langs(self.default_lang)
            default = defaults[0] if defaults else self.default_lang
            self._candidate_langs_cache[lang] = tuple(dict.fromkeys(
                (*self.matching_langs(lang), default),
            ))
        return self._candidate_langs_cache[lang]

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

    def matches_literal_intent(self, utterance: str, name: str,
                               lang: str | None = None) -> bool:
        """Match an entire concrete line of a packaged ``.intent`` resource.

        Useful before a fallback's narrower vocabulary gate: a published phrase
        must still work when the intent classifier falls below its threshold.
        Case, accents, punctuation and whitespace follow ``fold_words``. Only
        compatible regional resources are checked; English is not merged into a
        supported non-English locale. Regional/unsupported locale resolution
        follows ``lang()`` as for other resources.

        ``name`` accepts an optional ``.intent`` suffix. Both conventional root
        and ``intents/`` locations are read. Lines containing slot, alternative,
        or optional-group syntax are excluded, never interpreted as literals.
        This does not parse or replace OVOS's intent engines.
        """
        text = fold_words(utterance)
        if not text:
            return False
        candidates = self.matching_langs(lang) or (self.lang(lang),)
        filename = name if name.endswith(".intent") else f"{name}.intent"
        key = (candidates, filename)
        if key not in self._literal_intent_cache:
            self._literal_intent_cache[key] = frozenset(
                folded
                for candidate in candidates
                for folder in ("", "intents")
                for line in self._lines(candidate, folder, filename)
                if not any(character in line for character in "{}[]()|")
                if (folded := fold_words(line))
            )
        return text in self._literal_intent_cache[key]

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
