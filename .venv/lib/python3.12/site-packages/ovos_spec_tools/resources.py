"""Reference loader for OVOS-INTENT-2 — Locale Resource Formats.

This module is the reference implementation of the loader of OVOS-INTENT-2: it
discovers a skill's locale resource files, reads them with the common reader
(§3), and loads each of the six resource roles per its format (§4).

The six roles, by extension:

- ``.intent`` — slot-bearing intent training samples;
- ``.dialog`` — slot-bearing spoken-response phrases;
- ``.entity`` — slot-free example values for a slot;
- ``.voc`` — slot-free vocabulary;
- ``.blacklist`` — slot-free intent-suppression phrases;
- ``.prompt`` — a whole-file plain-text language-model prompt (§4.4).

The user-data path of the override precedence (§2.1) is **assistant-defined**;
this module takes it as a parameter and imports no configuration.

The **language is given per query**, not fixed at construction: a locale
folder is the multilingual unit of a skill, so one :class:`LocaleResources`
serves every language the skill ships.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from ovos_spec_tools.expansion import expand
from ovos_spec_tools.language import (
    DEFAULT_MAX_LANGUAGE_DISTANCE,
    closest_lang,
    standardize_lang,
)

__all__ = [
    "LocaleResources",
    "MalformedResource",
    "find_lang_dir",
    "iter_locale_dirs",
    "keyword_form",
    "normalize_for_match",
    "read_resource_file",
    "read_prompt_file",
    "strip_samples",
    "utterance_contains",
    "SLOT_BEARING_ROLES",
    "SLOT_FREE_ROLES",
    "PROMPT_ROLE",
]

# Resource roles, by file extension (OVOS-INTENT-2 §1). The five template
# roles are line-oriented; `.prompt` is a single whole-file document (§4.4).
SLOT_BEARING_ROLES = (".intent", ".dialog")
SLOT_FREE_ROLES = (".entity", ".voc", ".blacklist")
PROMPT_ROLE = ".prompt"

# A resolver maps a requested language and the available language tags to the
# best one, or None — the signature of `ovos_spec_tools.language.closest_lang`.
LanguageResolver = Callable[[str, Sequence[str], int], Optional[str]]


class MalformedResource(ValueError):
    """A resource file or skill layout that violates OVOS-INTENT-2.

    Raised for an empty resource file (§5), a duplicate ``(role, base name)``
    within one language tree (§2), and a named slot in a slot-free role (§4.3).
    """


def read_resource_file(path: Path) -> List[str]:
    """Apply the OVOS-INTENT-2 §3 common reader to one file.

    The file is read as UTF-8 (§3: "the file is UTF-8 … a reader that encounters
    [a BOM] MUST discard it"), a leading byte-order mark is discarded, and both
    ``LF`` and ``CRLF`` line endings are accepted (§3: "a reader MUST accept
    both"). Each line is stripped; blank lines and ``#``-comment lines are
    dropped (§3: "a blank line is skipped … a line whose first character is
    ``#`` is a comment"). There are no inline comments — a ``#`` mid-line is
    literal — so only a line *beginning* with ``#`` is dropped. The surviving
    lines — each one template (OVOS-INTENT-1) — are returned in order.

    Args:
        path: the resource file to read (a line-oriented role, not ``.prompt``;
            see :func:`read_prompt_file` for the whole-file role).

    Returns:
        The template lines, in file order, with blanks and comments removed. An
        all-blank/all-comment file yields ``[]`` — the caller treats that as the
        §5 "empty file" fault.
    """
    text = path.read_text(encoding="utf-8-sig")  # utf-8-sig discards a BOM
    templates: List[str] = []
    for raw_line in text.splitlines():  # splitlines() accepts LF and CRLF
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        templates.append(line)
    return templates


def iter_locale_dirs(root: Path,
                     native_langs: Optional[Sequence[str]] = None,
                     max_distance: int = DEFAULT_MAX_LANGUAGE_DISTANCE
                     ) -> Iterator[Tuple[str, Path]]:
    """Iterate ``<root>/locale/<lang>/`` subdirs as ``(lang, path)`` pairs.

    Implements the "discover languages" loader step (OVOS-INTENT-2 §5 step 1,
    §2 layout): each immediate subdirectory of ``<root>/locale/`` is one
    language tree, named with a BCP-47 tag.

    Each immediate subdirectory of ``<root>/locale/`` is treated as a locale
    tree; its name is normalized with :func:`standardize_lang` and yielded as
    the first item of the pair. The second item is the directory ``Path``.

    When ``native_langs`` is given, each subdir is matched against the natives
    via :func:`closest_lang` and yielded only when its closest native is within
    ``max_distance`` — useful for "a skill declares ``en``, the locale tree has
    ``en-US``, accept it" without forcing the caller to repeat that walk.

    Resource loaders (``.rx``, ``.dialog``, ``.voc``, ``.intent``, ``.json``)
    reinvent this walk by hand and disagree on the macro/full-tag policy. Use
    this and the disagreement goes away — locales are always discovered as
    full-tag directories, ``closest_lang`` reconciles at query time.

    Args:
        root: the skill root containing a ``locale/`` directory.
        native_langs: if given, only locales whose closest native is within
            ``max_distance`` are yielded (§2.2 nearness, applied as a filter).
        max_distance: the §2.2 distance threshold for that filter.

    Yields:
        ``(standardized_lang, dir_path)`` for each accepted locale directory,
        in sorted directory order. A non-tag or unparseable subdir name is
        skipped. ``root`` without a ``locale/`` child yields nothing.
    """
    root = Path(root)
    locales_root = root / "locale"
    if not locales_root.is_dir():
        return
    natives_norm = ([standardize_lang(lang) for lang in native_langs]
                    if native_langs is not None else None)
    for entry in sorted(locales_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            lang_norm = standardize_lang(entry.name)
        except Exception:
            continue
        if natives_norm is not None:
            if closest_lang(lang_norm, natives_norm,
                            max_distance=max_distance) is None:
                continue
        yield lang_norm, entry


def find_lang_dir(base_path: Union[str, Path], lang: str,
                  lang_resolver: Optional["LanguageResolver"] = None,
                  max_distance: int = DEFAULT_MAX_LANGUAGE_DISTANCE
                  ) -> Optional[Path]:
    """Resolve the best ``<base_path>/<lang>/`` subdirectory for *lang*.

    The immediate subdirectories of ``base_path`` are taken as the set of
    available languages. A standardized exact match wins first; otherwise the
    resolver (default :func:`closest_lang`) picks the closest match within
    ``max_distance`` (OVOS-INTENT-2 §2.2 smart fallback). This preserves a
    regional directory such as ``eu-ES`` when a macro-language ``eu`` tree is
    also installed.

    Returns the resolved :class:`Path`, or ``None`` if ``base_path`` is
    not a directory or no available subdir is close enough.

    This is the standalone primitive backing
    :meth:`LocaleResources._lang_dir` — use this when you want one
    language-aware directory lookup without constructing a full
    :class:`LocaleResources`. Skills typically use ``LocaleResources``
    (which wires the override-precedence search); tools that walk a
    single locale tree (``locate this lang's resource root``) call this.
    """
    base = Path(base_path)
    if not base.is_dir():
        return None
    names = [c.name for c in base.iterdir() if c.is_dir()]
    if lang_resolver is None:
        target = standardize_lang(lang)
        for name in names:
            if standardize_lang(name) == target:
                return base / name
    resolver = lang_resolver if lang_resolver is not None else closest_lang
    match = resolver(lang, names, max_distance)
    if match is None:
        return None
    # `match` is one of the candidate names normalized by the resolver;
    # find the original directory entry that standardizes to it so we
    # return the on-disk casing.
    for name in names:
        if standardize_lang(name) == standardize_lang(match):
            return base / name
    return None


def keyword_form(template_line: str,
                 vocabularies: Optional[Dict[str, List[str]]] = None
                 ) -> Tuple[str, List[str]]:
    """Split one slot-free template line into ``(entity, aliases)``.

    The line is expanded via :func:`expand` (with ``vocabularies`` available
    for ``<name>`` references), lowercased, deduplicated and sorted. The
    first item is the canonical **entity**; the rest are **aliases** that
    canonicalize to it.

    A ``.voc`` line like ``(hi|hello|hey)`` becomes one keyword whose entity
    value is ``"hi"`` and whose aliases are ``["hello", "hey"]`` — any
    consumer that distinguishes a canonical form from synonyms can use this
    grouping directly (OVOS-INTENT-2 §4.3 slot-free roles).

    The canonical/alias split is a tooling convention layered *on top of* the
    spec's unordered sample set (OVOS-INTENT-1 §4): the spec defines no
    "canonical" member, so "first after case-fold + sort" is chosen here purely
    to be deterministic.

    Args:
        template_line: one slot-free template line (a ``.voc``/``.entity`` line).
        vocabularies: vocabularies for any ``<name>`` reference in the line
            (OVOS-INTENT-1 §3.7).

    Returns:
        ``(entity, aliases)`` — the canonical form and its synonyms. An empty or
        whitespace-only line, or a line that fails to expand, yields
        ``("", [])`` (a malformed line is dropped, not raised, so one bad line
        does not poison a batch keyword load).

    This leniency is **deliberate and confined to this low-level helper**: it
    serves only the best-effort keyword extractors (:meth:`vocabulary_keywords`,
    :meth:`entity_keywords`), which group ``.voc``/``.entity`` lines into
    canonical/alias pairs and skip a line that will not expand. It is **not** a
    conformant load path — the conformant loaders (:meth:`_load_expanded` and
    everything built on it: :meth:`load_intent`, :meth:`load_vocabulary`, …)
    call :func:`expand` directly and **raise** on a malformed template or a
    slot in a slot-free role per OVOS-INTENT-2 §5 / OVOS-INTENT-1 §3.6. No
    conformant load relies on this function's silent drop.
    """
    if not template_line.strip():
        return "", []
    try:
        samples = expand(template_line, vocabularies)
    except Exception:
        # A malformed line yields no keyword rather than poisoning the batch.
        # Lenient by design — see the note in the docstring; conformant loaders
        # call expand() directly and raise instead.
        return "", []
    options = sorted({s.lower() for s in samples})
    if not options:
        return "", []
    return options[0], options[1:]


def normalize_for_match(text: str, *,
                        strip_diacritics: bool = True,
                        strip_punct: bool = True) -> str:
    """Lowercase, strip, and optionally fold diacritics / ASCII punctuation.

    Used as the comparison normalization for :func:`utterance_contains` and
    :func:`strip_samples`. The two folding steps are independent:

    - ``strip_diacritics=True`` (default) decomposes combining marks (NFD)
      and drops them — ``"olá"`` becomes ``"ola"``, ``"über"`` becomes
      ``"uber"`` — so the comparison is accent-insensitive.
    - ``strip_punct=True`` (default) removes ASCII punctuation outside
      ``{slot}`` spans. A whole ``{...}`` span, including its interior, is
      preserved verbatim so a slot marker survives a pre-render pass intact.
      This matters because the slot-name charset (OVOS-INTENT-1 §3.4,
      ``[a-z][a-z0-9_]*``) includes ``_``, which is itself ASCII punctuation
      (in ``string.punctuation``) — stripping it out of ``{requested_color}``
      would silently rename the slot to ``requestedcolor``.

    Set either flag to ``False`` for languages where the distinction is
    semantic (e.g. French ``ou``/``où``).

    This is a *match-time* normalization the resource consumers apply, distinct
    from the upstream ASR normalization OVOS-INTENT-1 §2 presumes; it exists
    because real utterances and authored ``.voc`` lines drift in accent and
    punctuation. ``{...}`` spans are preserved whole so a slot marker survives
    a pre-render pass.

    Args:
        text: the string to normalize.
        strip_diacritics: fold combining marks via NFD decomposition.
        strip_punct: drop ASCII punctuation outside ``{...}`` spans.

    Returns:
        The normalized, lowercased, whitespace-trimmed string.
    """
    import re
    import unicodedata
    text = text.strip().lower()
    if strip_diacritics:
        # Shield {...} spans from diacritic folding too, for consistency with
        # strip_punct below — a slot name is ASCII-only per §3.4 so this is a
        # no-op for well-formed templates, but keeps both folding steps using
        # the same "spans are opaque" rule rather than diverging behaviors.
        parts = re.split(r"(\{[^{}]*\})", text)
        text = "".join(
            part if part.startswith("{") and part.endswith("}") else
            "".join(
                c for c in unicodedata.normalize("NFD", part)
                if not unicodedata.combining(c)
            )
            for part in parts
        )
    if strip_punct:
        import string
        rm_chars = set(string.punctuation)
        parts = re.split(r"(\{[^{}]*\})", text)
        text = "".join(
            part if part.startswith("{") and part.endswith("}") else
            "".join(c for c in part if c not in rm_chars)
            for part in parts
        )
    return text


def utterance_contains(utterance: str, samples: Sequence[str],
                       *,
                       exact: bool = False,
                       strip_diacritics: bool = True,
                       strip_punct: bool = True) -> bool:
    """True iff ``utterance`` matches any item in ``samples``.

    With ``exact=True`` the utterance must equal a sample after
    normalization. With ``exact=False`` (the default) a sample is found
    when it appears in the utterance as a whole-word substring — so a
    sample ``yes`` matches ``"yes, please"`` but not ``"yesterday"``.

    Both sides are normalized via :func:`normalize_for_match`. The
    ``strip_diacritics`` and ``strip_punct`` flags are independent —
    forward each one as required by the target language.

    The default whole-word (non-``exact``) mode implements the
    OVOS-INTENT-2 §4.3 occurrence rule used for ``.voc``/``.blacklist`` testing:
    a phrase "occurs" when its words appear "as a contiguous sequence of whole
    words … not a raw substring" — which is why ``art`` does not match within
    ``start``.

    Args:
        utterance: the (ASR-normalized) text to test.
        samples: the phrase set to look for, e.g. an expanded ``.voc``.
        exact: require equality after normalization rather than substring.
        strip_diacritics: forwarded to :func:`normalize_for_match`.
        strip_punct: forwarded to :func:`normalize_for_match`.

    Returns:
        ``True`` iff any sample matches. An empty utterance or empty sample set
        returns ``False``.
    """
    if not utterance or not samples:
        return False
    def norm(value: str) -> str:
        return normalize_for_match(
            value,
            strip_diacritics=strip_diacritics,
            strip_punct=strip_punct,
        )
    utt = norm(utterance)
    norm_samples = [norm(s) for s in samples]
    if exact:
        return any(s and s == utt for s in norm_samples)
    import re
    # `(?<!\w)...(?!\w)` is whole-word like `\b...\b` but also matches
    # samples that begin or end in non-word characters (e.g. ``c++``).
    return any(
        s and re.search(
            r"(?<!\w)" + re.escape(s) + r"(?!\w)", utt) is not None
        for s in norm_samples
    )


def strip_samples(utterance: str, samples: Sequence[str]) -> str:
    """Return ``utterance`` with every whole-word occurrence of any sample
    removed.

    Samples are stripped longest first so that a composite match is
    consumed before any of its shorter constituents (``"give up"`` before
    ``"up"``). The match is whole-word and case-insensitive; the utterance
    is otherwise returned with original casing and punctuation. The whole-word
    anchoring is the same OVOS-INTENT-2 §4.3 "contiguous whole words" rule as
    :func:`utterance_contains`.

    Args:
        utterance: the text to strip from.
        samples: phrases to remove (e.g. an expanded ``.voc`` of filler words).

    Returns:
        ``utterance`` with every whole-word sample occurrence removed; double
        spaces left behind are **not** collapsed (the caller normalizes if it
        needs to).
    """
    import re
    for s in sorted({s for s in samples if s and s.strip()},
                    key=len, reverse=True):
        # `(?<!\w)...(?!\w)` rather than `\b...\b` so samples ending in
        # non-word characters (``c++``, ``yes!``) still strip cleanly.
        utterance = re.sub(
            r"(?<!\w)" + re.escape(s) + r"(?!\w)",
            "", utterance, flags=re.IGNORECASE)
    return utterance


def read_prompt_file(path: Path) -> str:
    """Read a ``.prompt`` whole and verbatim (OVOS-INTENT-2 §3, §4.4).

    A ``.prompt`` is **not** line-oriented: it is read whole, with no line
    stripping and no blank- or ``#``-comment-line filtering, because §4.4 states
    "every character is part of the prompt" (``#`` lines are ordinary prompt
    text, unlike in the line-oriented roles of §3). The file is UTF-8 and a
    leading byte-order mark is discarded (§3's "a reader … MUST discard" a BOM).

    Args:
        path: the resolved ``.prompt`` file.

    A ``.prompt`` has **no** special syntax beyond ``{{name}}`` substitution
    (OVOS-INTENT-2 §4.4): a single ``{name}``, any lone brace, and an
    ``<!-- … -->`` HTML comment are all **literal pass-through text** — they
    reach the model unchanged. The whole file is returned verbatim.

    Args:
        path: the resolved ``.prompt`` file.

    Returns:
        The file's whole content as a single string, byte-for-byte except the
        stripped BOM and Python's universal-newline decoding.
    """
    return path.read_text(encoding="utf-8-sig")  # utf-8-sig discards a BOM (§3)


class LocaleResources:
    """Loads OVOS-INTENT-2 resource files for one skill, across languages.

    One instance serves **every language** a skill ships: the language is a
    parameter of each load call, not of the constructor, because a locale
    folder is the multilingual unit of a skill.

    A resource is resolved through the override precedence of §2.1 — user
    overrides, then skill resources, then core resources — searching each
    source's ``<lang>/`` directory and all its subdirectories recursively.

    Skill and core resources are installed with their owning packages and are
    therefore snapshotted at construction. Their file contents, resource
    index, dialogs, and prompts remain in memory for the lifetime of this
    instance. Valid expanded results are also precomputed when no user tree is
    configured. With a user tree, expansion is repeated against its live files
    on each call. Recreate the instance after changing installed resources;
    package-owned data intentionally has no refresh operation. An optional
    user resource tree stays live, so creating, editing, or removing a user
    override takes effect without restarting the process.

    When the requested language has no directory, a **smart language fallback**
    (OVOS-INTENT-2 §2.2, non-normative) selects the nearest available language.
    Resolution is done by :func:`ovos_spec_tools.language.closest_lang` and is
    cached per static source and requested language, so one instance serves
    different languages — and different fallbacks — without repeating static
    directory discovery. The fallback needs the optional ``langcodes``
    dependency; without it, only exact tags resolve.
    """

    def __init__(self, skill_locale: str,
                 core_locale: Optional[str] = None,
                 user_locale: Optional[str] = None,
                 lang_resolver: Optional[LanguageResolver] = None,
                 max_language_distance: int = DEFAULT_MAX_LANGUAGE_DISTANCE):
        """
        Args:
            skill_locale: path to the skill's ``locale/`` directory.
            core_locale: path to the assistant's core ``locale/`` directory.
            user_locale: path to the user-override ``locale/`` directory
                (its root is assistant-defined, §2.1).
            lang_resolver: ``(target, available, max_distance) -> best | None``;
                resolves a requested language against the available ones.
                Defaults to :func:`ovos_spec_tools.language.closest_lang`.
            max_language_distance: passed to the resolver — the fallback
                accepts a language whose tag distance is **below** this
                (default 10, §2.2). ``0`` disables the fallback.
        """
        self._user_source = Path(user_locale) if user_locale is not None else None
        # Highest static precedence first (§2.1): skill, core.
        self._static_sources: List[Path] = [
            Path(p) for p in (skill_locale, core_locale) if p is not None
        ]
        # Retained for the source-ordered keyword iterators: user, skill, core.
        self._sources: List[Path] = ([self._user_source]
                                     if self._user_source is not None else [])
        self._sources.extend(self._static_sources)
        self._uses_default_lang_resolver = lang_resolver is None
        self._lang_resolver: LanguageResolver = (
            lang_resolver if lang_resolver is not None else closest_lang)
        self.max_language_distance = max_language_distance

        # source -> original language directory name ->
        # (base name, extension) -> every matching path. Multiple paths are
        # retained so the duplicate-resource error remains local to access.
        self._static_index: Dict[
            Path, Dict[str, Dict[Tuple[str, str], Tuple[Path, ...]]]
        ] = {}
        self._static_lines: Dict[Path, Tuple[str, ...]] = {}
        self._static_prompts: Dict[Path, str] = {}
        #: read failures from the snapshot, deferred to first access
        self._static_errors: Dict[Path, Exception] = {}
        self._static_language_cache: Dict[
            Tuple[Path, str], Optional[str]
        ] = {}
        self._expanded_resources: Dict[
            Tuple[str, str, str], Tuple[str, ...]
        ] = {}
        self._snapshot_static_sources()
        if self._user_source is None:
            self._preload_expanded_resources()

    def _snapshot_static_sources(self) -> None:
        """Eagerly read and index installed skill/core resource files once.

        Installed locale trees are package-owned and static for the instance
        lifetime. Keeping their small contents in memory removes filesystem
        reads from later intent matching; the live user tree is excluded.
        """
        line_roles = set(SLOT_BEARING_ROLES + SLOT_FREE_ROLES)
        lines_by_target: Dict[Path, Tuple[str, ...]] = {}
        prompts_by_target: Dict[Path, str] = {}
        for source in self._static_sources:
            language_index: Dict[
                str, Dict[Tuple[str, str], Tuple[Path, ...]]
            ] = {}
            indexes_by_target: Dict[
                Path, Dict[Tuple[str, str], Tuple[Path, ...]]
            ] = {}
            if source.is_dir():
                for lang_dir in sorted(source.iterdir()):
                    if not lang_dir.is_dir():
                        continue
                    lang_target = lang_dir.resolve()
                    if lang_target in indexes_by_target:
                        language_index[lang_dir.name] = indexes_by_target[
                            lang_target
                        ]
                        continue
                    mutable: Dict[Tuple[str, str], List[Path]] = {}
                    for path in sorted(lang_target.rglob("*")):
                        if not path.is_file():
                            continue
                        key = (path.stem, path.suffix)
                        mutable.setdefault(key, []).append(path)
                        # A file this instance may never be asked for must
                        # not be able to fail construction: one installed
                        # resource with, say, invalid UTF-8 in an unused
                        # language would otherwise take down every language.
                        # The failure is kept and re-raised from the accessor,
                        # which is where a lazy reader would have raised it.
                        if path.suffix in line_roles:
                            target = path.resolve()
                            if target not in lines_by_target:
                                try:
                                    lines_by_target[target] = tuple(
                                        read_resource_file(path)
                                    )
                                except Exception as error:
                                    self._static_errors[path] = error
                                    continue
                            self._static_lines[path] = lines_by_target[target]
                        elif path.suffix == PROMPT_ROLE:
                            target = path.resolve()
                            if target not in prompts_by_target:
                                try:
                                    prompts_by_target[target] = read_prompt_file(path)
                                except Exception as error:
                                    self._static_errors[path] = error
                                    continue
                            self._static_prompts[path] = prompts_by_target[target]
                    resource_index = {
                        key: tuple(paths) for key, paths in mutable.items()
                    }
                    indexes_by_target[lang_target] = resource_index
                    language_index[lang_dir.name] = resource_index
            self._static_index[source] = language_index

    def _preload_expanded_resources(self) -> None:
        """Expand valid installed resources without making unused faults fatal."""
        requests = set()
        expanded_roles = {".intent", ".entity", ".voc", ".blacklist"}
        for language_index in self._static_index.values():
            for lang, resources in language_index.items():
                for base_name, extension in resources:
                    if extension in expanded_roles:
                        requests.add((base_name, extension, lang))
        for base_name, extension, lang in sorted(requests):
            try:
                self._load_expanded(base_name, extension, lang)
            except (FileNotFoundError, ValueError):
                # Construction must not turn an unused malformed locale into a
                # process-wide startup failure. Access still raises the fault.
                continue

    def _static_lang_name(self, source: Path, lang: str) -> Optional[str]:
        """Resolve a requested language against one immutable source index."""
        cache_key = (source, lang)
        if cache_key in self._static_language_cache:
            return self._static_language_cache[cache_key]
        names = list(self._static_index[source])
        resolved = None
        if self._uses_default_lang_resolver:
            target = standardize_lang(lang)
            for name in names:
                if standardize_lang(name) == target:
                    resolved = name
                    break
        if resolved is None:
            match = self._lang_resolver(
                lang, names, self.max_language_distance
            )
            if match is not None:
                if match in names:
                    resolved = match
                else:
                    match = standardize_lang(match)
                    for name in names:
                        if standardize_lang(name) == match:
                            resolved = name
                            break
        self._static_language_cache[cache_key] = resolved
        return resolved

    def _static_paths(self, source: Path, base_name: str, extension: str,
                      lang: str) -> Tuple[Path, ...]:
        """Return snapshotted paths for one resource lookup."""
        lang_name = self._static_lang_name(source, lang)
        if lang_name is None:
            return ()
        return self._static_index[source][lang_name].get(
            (base_name, extension), ()
        )

    def _iter_source_paths(self, source: Path, extension: str,
                           lang: str) -> Iterator[Path]:
        """Yield role paths from a live user source or a static snapshot."""
        if self._user_source is not None and source == self._user_source:
            lang_dir = self._lang_dir(source, lang)
            if lang_dir is not None:
                yield from (path for path in sorted(lang_dir.rglob(
                    f"*{extension}")) if path.is_file())
            return
        lang_name = self._static_lang_name(source, lang)
        if lang_name is None:
            return
        resources = self._static_index[source][lang_name]
        for (_, resource_extension), paths in resources.items():
            if resource_extension == extension:
                yield from paths

    def _resource_lines(self, path: Path) -> Tuple[str, ...]:
        """Return cached static lines or freshly read user-override lines."""
        if path in self._static_lines:
            return self._static_lines[path]
        if path in self._static_errors:
            raise self._static_errors[path]
        return tuple(read_resource_file(path))

    def _prompt_text(self, path: Path) -> str:
        """Return cached static prompt text or a live user override."""
        if path in self._static_prompts:
            return self._static_prompts[path]
        if path in self._static_errors:
            raise self._static_errors[path]
        return read_prompt_file(path)

    def _lang_dir(self, source: Path, lang: str) -> Optional[Path]:
        """The ``<lang>/`` directory for ``lang`` under one source.

        The language is resolved against the available subdirectories by the
        ``lang_resolver`` — an exact tag, or the smart fallback of §2.2.
        """
        resolver = (None if self._uses_default_lang_resolver
                    else self._lang_resolver)
        return find_lang_dir(source, lang,
                             lang_resolver=resolver,
                             max_distance=self.max_language_distance)

    def find(self, base_name: str, extension: str,
             lang: str) -> Optional[Path]:
        """Locate a resource file by ``(base name, extension)`` in ``lang``.

        Walks the override precedence (§2.1) — live user tree, then the skill
        and core snapshots — looking for ``<base_name><extension>``. The first
        match wins.

        ``lang`` is resolved against each source's available subdirectories
        via the language resolver, so a request for ``en`` matches an
        ``en-US/`` tree (and vice versa) within the configured distance.

        Raises :class:`MalformedResource` if more than one file with the
        same ``(role, base name)`` exists within one language tree —
        OVOS-INTENT-2 §2 requires uniqueness.

        Returns the resolved path, or ``None`` if no source has it.
        """
        filename = base_name + extension
        if self._user_source is not None:
            lang_dir = self._lang_dir(self._user_source, lang)
            matches = (sorted(p for p in lang_dir.rglob(filename)
                              if p.is_file()) if lang_dir is not None else [])
            if len(matches) > 1:
                raise MalformedResource(
                    f"duplicate resource {filename!r} within {lang_dir} — "
                    f"a (role, base name) must be unique per language tree")
            if matches:
                return matches[0]
        for source in self._static_sources:
            matches = self._static_paths(source, base_name, extension, lang)
            if len(matches) > 1:
                lang_name = self._static_lang_name(source, lang)
                raise MalformedResource(
                    f"duplicate resource {filename!r} within "
                    f"{source / (lang_name or lang)} — a (role, base name) "
                    "must be "
                    "unique per language tree")
            if matches:
                return matches[0]
        return None

    def vocabularies(self, lang: str) -> Dict[str, List[str]]:
        """Every ``.voc`` reachable for ``lang``, as a name→templates map
        suitable for resolving ``<name>`` references during expansion."""
        vocs: Dict[str, List[str]] = {}
        # Lowest precedence first, so a higher-precedence file overrides.
        for source in reversed(self._sources):
            for path in self._iter_source_paths(source, ".voc", lang):
                vocs[path.stem] = list(self._resource_lines(path))
        return vocs

    def entities(self, lang: str) -> Dict[str, List[str]]:
        """Every ``.entity`` reachable for ``lang``, as a name→value-set map —
        each value set expanded, with override precedence applied."""
        names = set()
        for source in self._sources:
            for path in self._iter_source_paths(source, ".entity", lang):
                names.add(path.stem)
        return {name: self.load_entity(name, lang) for name in sorted(names)}

    def _keywords_for(self, extension: str, lang: str
                      ) -> Iterator[Tuple[str, str, List[str]]]:
        """Walk every slot-free resource of one role and group expansions
        line-by-line. Yields ``(resource_name, entity, aliases)`` triples
        — one yield per non-empty template line, with the OVOS-INTENT-2
        §4.3 ``(entity, aliases)`` convention applied via
        :func:`keyword_form`."""
        vocabularies = self.vocabularies(lang)
        for source in self._sources:
            for path in self._iter_source_paths(source, extension, lang):
                for template in self._resource_lines(path):
                    entity, aliases = keyword_form(template, vocabularies)
                    if entity:
                        yield path.stem, entity, aliases

    def vocabulary_keywords(self, lang: str
                            ) -> Iterator[Tuple[str, str, List[str]]]:
        """Yield ``(voc_name, entity, aliases)`` for every line of every
        ``.voc`` reachable for ``lang``.

        One yield per template line: the line's expansion is split into a
        canonical entity (first sorted alternative) and its aliases via
        :func:`keyword_form`. Suits any consumer that registers keyword
        sets with a primary/alias distinction (OVOS-INTENT-2 §4.3).
        """
        return self._keywords_for(".voc", lang)

    def entity_keywords(self, lang: str
                        ) -> Iterator[Tuple[str, str, List[str]]]:
        """Yield ``(entity_name, entity, aliases)`` for every line of every
        ``.entity`` reachable for ``lang``. Same shape as
        :meth:`vocabulary_keywords`; ``.entity`` and ``.voc`` share the
        slot-free template format (§4.3)."""
        return self._keywords_for(".entity", lang)

    def voc_list(self, base_name: str, lang: str) -> List[str]:
        """Load a ``.voc`` as its flat sample list — the same content
        :meth:`load_vocabulary` returns, named consistently with
        :meth:`voc_match` and :meth:`remove_voc` for callers that want
        to inspect or cache the phrase set independently.

        Returns ``[]`` when the resource does not exist for the language.
        """
        try:
            return self.load_vocabulary(base_name, lang)
        except FileNotFoundError:
            return []

    def voc_match(self, utterance: str, base_name: str, lang: str, *,
                  exact: bool = False,
                  strip_diacritics: bool = True,
                  strip_punct: bool = True) -> bool:
        """Convenience: load a ``.voc`` for ``lang`` and check whether
        ``utterance`` matches any of its samples.

        Equivalent to ``utterance_contains(utterance,
        self.load_vocabulary(base_name, lang), ...)`` with the same flag
        semantics, including the ``(?<!\\w)...(?!\\w)`` whole-word anchor
        (so a sample ``yes`` matches ``"yes, please"`` but not
        ``"yesterday"``). Returns ``False`` when the resource does not
        exist for the language.
        """
        try:
            samples = self.load_vocabulary(base_name, lang)
        except FileNotFoundError:
            return False
        return utterance_contains(
            utterance, samples, exact=exact,
            strip_diacritics=strip_diacritics, strip_punct=strip_punct)

    def remove_voc(self, utterance: str, base_name: str,
                   lang: str) -> str:
        """Convenience: load a ``.voc`` for ``lang`` and strip every
        whole-word occurrence of any sample from ``utterance``.

        Equivalent to ``strip_samples(utterance,
        self.load_vocabulary(base_name, lang))``; samples are stripped
        longest-first so a composite phrase consumes its parts before
        any shorter fallback. Returns ``utterance`` unchanged if the
        resource does not exist for the language.
        """
        if not utterance:
            return utterance
        try:
            samples = self.load_vocabulary(base_name, lang)
        except FileNotFoundError:
            return utterance
        return strip_samples(utterance, samples)

    def _load_expanded_uncached(self, base_name: str, extension: str,
                                lang: str) -> Tuple[str, ...]:
        """Load and expand one resource into an immutable snapshot value."""
        path = self.find(base_name, extension, lang)
        if path is None:
            raise FileNotFoundError(
                f"no {extension} resource named {base_name!r} for "
                f"language {lang!r}")
        templates = self._resource_lines(path)
        if not templates:
            raise MalformedResource(
                f"empty resource file {path} — every file must contribute at "
                f"least one template (§5)")
        vocabularies = self.vocabularies(lang)
        slot_free = extension in SLOT_FREE_ROLES
        samples: List[str] = []
        for template in templates:
            for sample in expand(template, vocabularies):
                if slot_free and "{" in sample:
                    raise MalformedResource(
                        f"{extension} resource {path} is slot-free but "
                        f"template {template!r} contains a named slot")
                if sample not in samples:
                    samples.append(sample)
        return tuple(samples)

    def _load_expanded(self, base_name: str, extension: str,
                       lang: str) -> List[str]:
        """Return a mutable copy of static or live expanded resource data."""
        if self._user_source is not None:
            return list(self._load_expanded_uncached(
                base_name, extension, lang
            ))
        cache_key = (base_name, extension, standardize_lang(lang))
        if cache_key not in self._expanded_resources:
            self._expanded_resources[cache_key] = self._load_expanded_uncached(
                base_name, extension, lang
            )
        return list(self._expanded_resources[cache_key])

    def load_intent(self, base_name: str, lang: str) -> List[str]:
        """Load an ``.intent`` as its sample set, named slots intact (§4.1)."""
        return self._load_expanded(base_name, ".intent", lang)

    def load_entity(self, base_name: str, lang: str) -> List[str]:
        """Load an ``.entity`` value set (§4.3)."""
        return self._load_expanded(base_name, ".entity", lang)

    def load_vocabulary(self, base_name: str, lang: str) -> List[str]:
        """Load a ``.voc`` phrase set (§4.3)."""
        return self._load_expanded(base_name, ".voc", lang)

    def load_blacklist(self, base_name: str, lang: str) -> List[str]:
        """Load a ``.blacklist`` phrase set (§4.3)."""
        return self._load_expanded(base_name, ".blacklist", lang)

    def load_dialog(self, base_name: str, lang: str) -> List[str]:
        """Load a ``.dialog`` as its list of phrase strings.

        Unlike the other roles a ``.dialog`` is **not** expanded at load time —
        expansion happens per render, on the one phrase chosen (§4.2). The
        phrase strings are returned verbatim, for a dialog renderer to consume.
        """
        path = self.find(base_name, ".dialog", lang)
        if path is None:
            raise FileNotFoundError(
                f"no .dialog resource named {base_name!r} for "
                f"language {lang!r}")
        phrases = self._resource_lines(path)
        if not phrases:
            raise MalformedResource(
                f"empty resource file {path} — every file must contribute at "
                f"least one template (§5)")
        return list(phrases)

    def load_prompt(self, base_name: str, lang: str) -> str:
        """Load a ``.prompt`` as its whole-file string (§4.4).

        A ``.prompt`` is read whole and verbatim — not split into templates,
        not line-filtered — and is returned for a prompt renderer to fill. See
        :class:`ovos_spec_tools.prompt.PromptRenderer`.

        Raises:
            FileNotFoundError: no such ``.prompt`` for ``lang``.
            MalformedResource: the file is empty or only whitespace (§5).
        """
        path = self.find(base_name, PROMPT_ROLE, lang)
        if path is None:
            raise FileNotFoundError(
                f"no .prompt resource named {base_name!r} for "
                f"language {lang!r}")
        text = self._prompt_text(path)
        if not text.strip():
            raise MalformedResource(
                f"empty resource file {path} — every file must contribute "
                f"content (§5)")
        return text
