"""Multilingual language-name parsing.

Maps between spoken language names (e.g. "Portuguese", "Portugiesisch",
"Português") and IETF language codes (e.g. "pt"), in both directions,
using per-language wordlists bundled under ``res/``.

BCP-47 tag resolution — standardizing a tag, and picking the closest wordlist
for a requested language — is delegated to the OVOS-spec reference matcher
(``ovos_spec_tools.language``: ``standardize_lang``, ``closest_lang``,
``lang_distance``), so this library ranks dialects identically to the rest of
the stack (OVOS-INTENT-2 §2.2). Matching a spoken *name* against the wordlist
(fuzzy, order-insensitive) is a separate concern and stays with ``match_one``.

Region and private-use dialect subtags
---------------------------------------
A code may carry a region (``ar-EG``, ``pt-AO``) or a private-use dialect
subtag (``an-x-ansotano``, ``pt-BR-x-caipira``, ``ar-IQ-x-qeltu``). The
wordlists name languages and, for a handful of cases, specific regional
varieties — they do not name every dialect. The contract is explicit:

- Standardization **preserves** region and ``-x-`` private-use subtags; a tag
  is never silently collapsed to its base language, and a private-use tag
  never raises.
- :func:`pronounce_lang` returns the most specific spoken name it has: the full
  tag's name when one exists, otherwise an explicit, documented fall back to
  the **base-language** name (``ar-EG`` -> the name of ``ar``). This is a
  lossy-but-safe fallback, not a failure — the base name is an acceptable
  answer when no dialect-specific name is bundled.
"""
import json
import os.path
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import langcodes
from ovos_spec_tools.language import closest_lang, lang_distance, standardize_lang
from ovos_utils.parse import match_one, fuzzy_match, MatchStrategy

RES_DIR = f"{os.path.dirname(__file__)}/res"

# A ``langcodes`` name->code guess is only trusted when the resolved code's own
# display name (in the query language, in English, or its autonym) matches the
# text this closely. ``langcodes.find`` is greedy and will otherwise resolve
# ordinary words ("banana" -> bcw, "music" -> mos) to obscure languages.
_LANGCODES_NAME_FLOOR = 0.9

# languages with a bundled wordlist
LANGS = sorted(entry for entry in os.listdir(RES_DIR)
               if os.path.isfile(f"{RES_DIR}/{entry}/langs.json"))


def _expand(template: str) -> List[str]:
    """Expand ``(a|b)`` alternations in a template into all variants."""
    match = re.search(r"\(([^()]*)\)", template)
    if not match:
        text = " ".join(template.split())
        return [text] if text else []
    variants = []
    for option in match.group(1).split("|"):
        expanded = template[:match.start()] + option + template[match.end():]
        for variant in _expand(expanded):
            if variant not in variants:
                variants.append(variant)
    return variants


def _normalize_code(lang_code: str) -> str:
    """Normalize a language code to its modern lowercase IETF form.

    Legacy tags are updated (e.g. ``iw`` -> ``he``, ``jw`` -> ``jv``,
    ``mo`` -> ``ro``) so the same code is returned regardless of which
    alias a wordlist (or caller) uses. Region and ``-x-`` private-use
    subtags are preserved (``an-x-ansotano`` stays ``an-x-ansotano``);
    tag comparison is case-insensitive, so the result is lowercased.

    Standardization is the OVOS-spec matcher (:func:`standardize_lang`),
    which never raises — a malformed tag is returned in a best-effort
    normalized form rather than aborting.
    """
    return standardize_lang(lang_code).lower()


@lru_cache(maxsize=None)
def _load_wordlist(lang: str) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """Load the wordlist for ``lang`` as (code, spoken names) pairs.

    ``lang`` must be one of ``LANGS``; codes are normalized and the order
    of spoken names from the resource file is preserved (first name is
    the canonical one).
    """
    resource_file = f"{RES_DIR}/{lang}/langs.json"
    with open(resource_file, encoding="utf-8") as f:
        data = json.load(f)
    entries = {}
    for code, names in data.items():
        if isinstance(names, str):
            names = _expand(names)
        code = _normalize_code(code)
        entries.setdefault(code, [])
        entries[code] += [n for n in names if n not in entries[code]]
    return tuple((code, tuple(names)) for code, names in entries.items())


def _closest_wordlist(lang: str) -> str:
    """Match ``lang`` against the languages with a bundled wordlist.

    Uses the OVOS-spec §2.2 fallback (:func:`closest_lang`) so a regional
    request resolves to its base wordlist (``pt-br`` -> ``pt``). Raises
    ValueError when nothing is close enough.
    """
    match = closest_lang(lang, LANGS)
    if match is None:
        raise ValueError(f"Unsupported language '{lang}' not in {LANGS}")
    return match


def _langcodes_names(code: str, lang: str) -> List[str]:
    """Names ``langcodes`` knows for ``code``: display name in ``lang``, in
    English, and the autonym. Empty when the code is unknown to CLDR (the
    "Unknown language [xxx]" sentinel is treated as no name)."""
    try:
        language = langcodes.Language.get(code)
    except (langcodes.tag_parser.LanguageTagError, ValueError):
        return []
    names = []
    for display in (lang, "en"):
        try:
            name = language.display_name(display)
        except Exception:
            continue
        if name and not name.lower().startswith("unknown language"):
            names.append(name)
    try:
        autonym = language.autonym()
    except Exception:
        autonym = ""
    if autonym and not autonym.lower().startswith("unknown language"):
        names.append(autonym)
    # de-dup, preserve order
    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def _langcodes_name(lang_code: str, lang: str) -> str:
    """CLDR display name for ``lang_code`` in ``lang``, or ``""``.

    Mirrors the wordlist base-fallback contract: a regioned or private-use tag
    with no name of its own resolves to its base-language name, so
    ``pt-BR-x-caipira`` is named as Portuguese rather than crashing or leaking
    the region into the name. The base subtag is tried first so a regioned tag
    resolves to the plain base-language name (``mwl-PT`` -> "Mirandese", not
    "Mirandese (Portugal)"), matching the wordlist base-fallback contract.
    """
    base = lang_code.split("-")[0]
    for candidate in (base, lang_code) if base != lang_code else (lang_code,):
        names = _langcodes_names(candidate, lang)
        if names:
            return names[0]
    return ""


def _langcodes_find(text: str, lang: str) -> Tuple[str, float]:
    """Resolve a spoken language *name* to a code via CLDR, guarding against
    ``langcodes.find`` greedily matching ordinary words.

    Returns ``(code, confidence)`` only when the resolved code's own display
    name matches ``text`` at or above :data:`_LANGCODES_NAME_FLOOR`; otherwise
    ``("", 0.0)``.
    """
    try:
        code = str(langcodes.find(text, language=lang))
    except LookupError:
        try:
            code = str(langcodes.find(text))
        except LookupError:
            return "", 0.0
    query = text.casefold()
    names = _langcodes_names(code, lang)
    if not names:
        return "", 0.0
    conf = max(fuzzy_match(query, name.casefold(),
                           strategy=MatchStrategy.TOKEN_SORT_RATIO)
               for name in names)
    if conf < _LANGCODES_NAME_FLOOR:
        return "", 0.0
    return _normalize_code(code), conf


def get_lang_data(lang: str) -> Dict[str, str]:
    """Map spoken language names in ``lang`` to language codes.

    Multiple valid spellings may exist for the same code; every known
    spelling appears as a key. Raises ValueError if ``lang`` has no
    bundled wordlist.
    """
    return {name: code
            for code, names in _load_wordlist(_closest_wordlist(lang))
            for name in names}


def extract_langcode(text: str, lang: str) -> Tuple[str, float]:
    """Extract the language code best matching a language name in ``text``.

    ``lang`` is the language the utterance is spoken in. Returns a
    ``(langcode, confidence)`` tuple; confidence is between 0 and 1.
    A non-string or blank ``text`` yields ``("", 0.0)`` rather than raising.
    """
    langs = get_lang_data(lang)
    if not isinstance(text, str) or not text.strip():
        return "", 0.0
    tokens = text.casefold().split()
    query = " ".join(tokens)
    # An exact name match always wins over fuzzy matching. A name that
    # appears verbatim as a run of whole words in a longer utterance
    # ("quiero aprender japonés") counts as exact too; the most specific
    # (longest) such name wins, so "American English" beats "English".
    best = None  # (span, -start, code)
    for name, code in langs.items():
        name_tokens = name.casefold().split()
        span = len(name_tokens)
        for i in range(len(tokens) - span + 1) if span else ():
            if tokens[i:i + span] == name_tokens:
                key = (span, -i, code)
                if best is None or key[:2] > best[:2]:
                    best = key
                break
    if best is not None:
        return best[2], 1.0
    code, conf = match_one(query, langs, strategy=MatchStrategy.TOKEN_SET_RATIO)
    # A strong wordlist match is authoritative and keeps its curated code.
    # Only when the wordlist is unsure do we consult CLDR names (which cover
    # languages no wordlist bundles), and never below the guarded floor.
    if conf < _LANGCODES_NAME_FLOOR:
        lc_code, lc_conf = _langcodes_find(query, lang)
        if lc_conf and lc_conf > conf:
            return lc_code, lc_conf
    # a zero-confidence "match" is no match at all; don't return an
    # arbitrary code for it
    if not conf:
        return "", 0.0
    return code, conf


def _autonym(code: str) -> Optional[str]:
    """The name of ``code`` in its own language, or ``None`` when unknown.

    Tries the curated wordlist first (``pronounce_lang(code, code)``), then
    falls back to the CLDR autonym for a code no wordlist bundles. Never
    raises: an unresolvable code (unsupported wordlist, unknown to CLDR)
    yields ``None`` rather than the bare code, so a caller never mistakes the
    code itself for a name.
    """
    try:
        name = pronounce_lang(code, code)
        if name and name != code:
            return name
    except ValueError:
        pass
    try:
        autonym = langcodes.Language.get(code).autonym()
    except Exception:
        return None
    if autonym and not autonym.lower().startswith("unknown language"):
        return autonym
    return None


def extract_language(text: str, lang: str) -> List[Dict]:
    """Extract OVOS-INTENT-1 §5.6 ``language`` typed-slot entries from ``text``.

    ``lang`` is the language the utterance is spoken in. Returns a list of
    entries, each ``{"span": [start, end], "surface": <text>, "value":
    {"code": <BCP-47 tag>, "name": <autonym or None>}}``; ``span`` is a
    half-open Unicode-code-point range into ``text`` and ``surface`` is
    ``text[start:end]`` (the invariant §5.6 requires). ``name`` is the
    autonym of the primary language subtag only, per §5.6: for "Brazilian
    Portuguese" (-> ``pt-br``) ``name`` is ``"Português"``, not a Brazilian
    variant. A non-string or blank ``text``, or unmatched text, yields ``[]``.

    Only names that occur verbatim as a run of whole words are recognized
    (the same exact-match rule :func:`extract_langcode` applies before its
    fuzzy fallback); a fuzzy-only reading has no reliable span and is not
    reported here. The longest name wins at a given position ("American
    English" over "English"), and matches do not overlap.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    langs = get_lang_data(lang)
    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    tokens_cf = [t[0].casefold() for t in tokens]
    # longest name first, so "American English" claims its span before "English" can
    names_by_len = sorted(langs.items(), key=lambda kv: -len(kv[0].split()))
    claimed: List[Tuple[int, int]] = []
    entries = []
    for name, code in names_by_len:
        name_tokens = name.casefold().split()
        span = len(name_tokens)
        if not span:
            continue
        i = 0
        while i <= len(tokens_cf) - span:
            if tokens_cf[i:i + span] == name_tokens and not any(
                    i < end and start < i + span for start, end in claimed):
                char_start = tokens[i][1]
                char_end = tokens[i + span - 1][2]
                base = code.split("-")[0]
                entries.append({
                    "span": [char_start, char_end],
                    "surface": text[char_start:char_end],
                    "value": {"code": code, "name": _autonym(base)},
                })
                claimed.append((i, i + span))
                i += span
                continue
            i += 1
    entries.sort(key=lambda e: e["span"][0])
    return entries


def pronounce_lang(lang_code: str, lang: str) -> str:
    """Get the spoken name of ``lang_code`` in ``lang``.

    Resolution is most-specific-first: the full tag's dedicated name when
    the wordlist has one, otherwise an explicit fall back to the
    **base-language** name. A region (``ar-EG`` -> the name of ``ar``) or a
    private-use dialect subtag (``pt-BR-x-caipira`` -> the name of ``pt``,
    ``ar-IQ-x-qeltu`` -> the name of ``ar``) that has no dedicated wordlist
    name resolves to the base-language name — a documented, lossy-but-safe
    fallback, never a crash. When the wordlist has no name for the base
    language either, ``lang_code`` is returned unchanged.
    """
    if not isinstance(lang_code, str):
        return lang_code
    names = {code: spoken[0]
             for code, spoken in _load_wordlist(_closest_wordlist(lang))
             if spoken}
    full_code = _normalize_code(lang_code)
    # base language of a regioned / private-use tag: "pt-br" -> "pt",
    # "an-x-ansotano" -> "an". The "-x-" subtag carries no base name of its
    # own, so the primary subtag is the fallback lookup key.
    base_code = full_code.split("-")[0]
    curated = names.get(full_code) or names.get(base_code)
    if curated:
        return curated
    # No curated name: fall back to the CLDR display name in the requested
    # language, which covers the long tail of ISO-639 codes no wordlist bundles
    # (mwl -> "Mirandese", lij -> "Ligurian"). Only truly unknown or private-use
    # codes fall through to the code returned unchanged.
    return _langcodes_name(full_code, lang) or lang_code
