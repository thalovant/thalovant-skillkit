"""Language-tag utilities — standardization, distance, and closest match.

This module is the cross-spec implementation of OVOS's BCP-47 language-matching
and locale-resolution rules. It is referenced by — but not owned by — a single
spec; the rules it encodes are drawn from:

- **OVOS-INTENT-2 §2** — locale directories are named with BCP-47 tags and tag
  comparison is **case-insensitive** (``en-us`` and ``en-US`` denote the same
  language). :func:`standardize_lang` is the canonicalization that makes that
  comparison total, and :func:`lang_distance` returns ``0`` for tags that differ
  only in case.
- **OVOS-INTENT-2 §2.2** — the *language fallback* suggestion: a loader MAY fall
  back to the nearest available language, and the spec names ``langcodes``'
  ``tag_distance()`` with a "distance up to 10 is a usable regional match"
  threshold. :data:`DEFAULT_MAX_LANGUAGE_DISTANCE` is exactly that ``10``;
  :func:`closest_lang` is exactly that "nearest available" selection. §2.2 is
  explicitly **non-normative** ("an implementation choice, not a requirement"),
  so everything here is a reference policy, not a conformance obligation.
- the **SESSION-1 language family** — a session carries a ``lang`` tag; the same
  matching rules decide whether a session's language is served by an available
  resource/voice/model.

OVOS resolves "the closest available language for a request" in many places —
locale resources, TTS voices, STT models — and the logic has been
reimplemented repeatedly (``ovos_utils.lang.get_language_dir``,
``phoonnx.match_lang``, …) with subtle drift between the copies. This module is
intended to be the **single implementation** behind all of them.

It is built on one distance function, :func:`lang_distance`; :func:`closest_lang`
is simply "the candidate with the smallest distance". All the policy — tag
standardization, the norm-region preference, the behaviour when ``langcodes``
is absent — lives inside :func:`lang_distance`, not in branchy callers.

**Dialect-fallback semantics**, precisely. A request resolves to a candidate iff
their :func:`lang_distance` is at or below the threshold (an exact match —
distance ``0`` — always resolves). The distance ladder is, from nearest to
farthest:
identical tag (``0``) < a bare tag vs its own norm region (``0``, see
:func:`_with_norm_region`) < two regions of one language (a small regional
distance) < the bare/generic form vs a region of the same language < a member
language vs its macrolanguage tag (``10`` with ``langcodes`` — the threshold
itself) < a different primary language (``>= 100`` with the coarse measure —
never a usable match).

The norm-region preference is **non-normative implementation policy**, not a
spec rule: a bare ``pt`` is measured **from ``pt-PT``**, not from the
most-populous ``pt-BR``, so ``pt`` falls back to ``pt-PT`` before ``pt-BR``.
This deliberately *diverges* from ``langcodes``' population default — which
§2.2 endorses — and is a choice this package makes, not a requirement of any
spec (see :data:`_NORM_REGION`).

``langcodes`` is an optional dependency (OVOS-INTENT-2 §2.2 names it). Without
it, :func:`lang_distance` falls back to a coarse same-language /
different-language measure that still honours the same ordering for the cases
locale resolution actually depends on. That fallback, and its distance values,
are likewise this package's own implementation policy — §2.2 is silent on the
no-``langcodes`` case.
"""
from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "standardize_lang",
    "lang_distance",
    "lang_matches",
    "closest_lang",
    "DEFAULT_MAX_LANGUAGE_DISTANCE",
]

# A language distance of 10 or less is a usable regional match (OVOS-INTENT-2
# §2.2; see the langcodes distance-values documentation). The bound is
# inclusive, so 10 itself qualifies: `langcodes` gives exactly 10 to a specific
# language measured against its macrolanguage tag, such as "arz" against "ar".
DEFAULT_MAX_LANGUAGE_DISTANCE = 10

# NON-NORMATIVE IMPLEMENTATION POLICY (no spec backing). `langcodes` resolves a
# bare tag to its *most-populous* region — for "pt" that is "pt-BR". This map
# deliberately overrides that for languages whose unmarked form OVOS prefers to
# resolve to a reference variety instead: a bare "pt" is measured from "pt-PT".
# OVOS-INTENT-2 §2.2 endorses `langcodes`; this preference diverges from it on
# purpose and is this package's policy, not a requirement of any spec. Add a
# language here only when its bare tag has a clear reference region distinct
# from the populous one.
_NORM_REGION = {
    "pt": "PT",
}


def standardize_lang(tag: str) -> str:
    """Normalize a BCP-47 language tag for comparison.

    Implements the canonicalization presupposed by OVOS-INTENT-2 §2's
    "tag comparison is case-insensitive" rule: it folds underscores to hyphens,
    lowercases the primary subtag, uppercases the region, and (via ``langcodes``)
    resolves canonical script/region forms — so that two on-disk spellings of
    one language (``en_us``, ``en-US``) reduce to a single comparable string.

    Args:
        tag: a BCP-47-ish language tag, possibly underscore-separated or
            mixed-case (as locale directory names and config values often are).

    Returns:
        The standardized tag. With ``langcodes`` installed this is
        ``langcodes.standardize_tag``'s output; without it, a primary-lowercase,
        region-uppercase normalization.

    Uses ``langcodes.standardize_tag`` when available — handling underscores,
    case, and script/region forms — and falls back to a simple normalization
    otherwise.
    """
    if tag.lower() in ("tl", "tgl"):
        # NON-NORMATIVE IMPLEMENTATION POLICY (no spec backing). langcodes folds
        # Tagalog into the `fil` macrolanguage; OVOS keeps `tl` distinct, so
        # this one tag is normalized by hand. This is a deliberate divergence
        # from langcodes (which §2.2 endorses), not a spec requirement.
        return "tl"
    try:
        from langcodes import standardize_tag
        return str(standardize_tag(tag))
    except Exception:
        normalized = tag.replace("_", "-")
        if "-" in normalized:
            primary, rest = normalized.split("-", 1)
            return f"{primary.lower()}-{rest.upper()}"
        return normalized.lower()


def _with_norm_region(tag: str) -> str:
    """Give a bare language tag its norm region (``pt`` -> ``pt-PT``).

    A regioned tag, or a language with no norm region, is returned unchanged.
    The norm-region map is non-normative implementation policy (see
    :data:`_NORM_REGION`); it diverges from ``langcodes`` on purpose.
    """
    if "-" in tag:
        return tag
    region = _NORM_REGION.get(tag.lower())
    return f"{tag.lower()}-{region.upper()}" if region else tag


def _langcodes_distance(desired: str, supported: str) -> Optional[int]:
    """``langcodes.tag_distance``, retried on the primary subtag if the full
    tag is unparseable. ``None`` if no distance can be computed — including
    when ``langcodes`` is not installed."""
    try:
        from langcodes import tag_distance
    except ImportError:
        return None
    for candidate in (supported, supported.split("-")[0]):
        try:
            return int(tag_distance(desired, candidate))
        except Exception:
            continue
    return None


def _coarse_distance(desired: str, supported: str) -> int:
    """A ``langcodes``-free distance.

    The two tags are already standardized and norm-expanded. A shared primary
    subtag is near, a differing one is far; the generic (region-less) form of
    a language counts as nearer than a sibling region of it.

    The values 3 / 5 / 100 are **arbitrary, ordering-only** numbers with no
    spec basis: OVOS-INTENT-2 §2.2 names ``langcodes``' ``tag_distance`` and is
    silent on the no-``langcodes`` case, so this fallback exists purely to
    preserve the same nearest-to-farthest *ordering* that locale resolution
    depends on. Only the relative order (and being at/above the threshold of
    10) is meaningful; the magnitudes are not.
    """
    if desired.split("-")[0].lower() != supported.split("-")[0].lower():
        return 100  # a different language — beyond any usable threshold
    if "-" not in desired or "-" not in supported:
        return 3  # one side is the generic language tag
    return 5  # two different regions of the same language


def lang_distance(desired: str, supported: str) -> int:
    """The distance between two BCP-47 language tags.

    The numeric backbone of the OVOS-INTENT-2 §2.2 fallback: §2.2 names
    ``langcodes``' ``tag_distance()`` and its "up to 10 is a usable regional
    match" reading, which this function adopts (with the norm-region correction
    below) so every OVOS component ranks dialects identically.

    ``0`` is identical; a larger number is further apart; a value above 10 is
    not a usable match. Both tags are standardized, and a bare tag is
    measured **from its norm region** — so ``lang_distance("pt", "pt-PT")`` is
    ``0`` while ``lang_distance("pt", "pt-BR")`` is a regional difference. The
    norm-region step is non-normative implementation policy that diverges from
    ``langcodes``' population-based default on purpose (see :data:`_NORM_REGION`),
    not a §2.2 requirement.

    Args:
        desired: the requested BCP-47 tag.
        supported: the candidate BCP-47 tag to measure against.

    Returns:
        A non-negative distance: ``0`` for identical (after standardization and
        norm-region expansion), a small value for a regional difference, and a
        large value (``>= 100`` under the coarse measure) for a different
        primary language.

    Uses ``langcodes.tag_distance`` when available, and a coarse same-language
    measure otherwise.
    """
    a = standardize_lang(desired)
    b = standardize_lang(supported)
    if a.lower() == b.lower():
        return 0
    a, b = _with_norm_region(a), _with_norm_region(b)
    if a.lower() == b.lower():
        return 0
    distance = _langcodes_distance(a, b)
    return distance if distance is not None else _coarse_distance(a, b)


def lang_matches(a: str, b: str,
                 max_distance: int = DEFAULT_MAX_LANGUAGE_DISTANCE) -> bool:
    """Return ``True`` when two BCP-47 tags are close enough to interchange.

    Convenience wrapper around :func:`lang_distance` for the common
    ``if score <= threshold`` check that cross-component boundaries (intent
    engines, TTS/STT plugin routing, locale lookup) reimplement by hand. The
    default threshold matches :data:`DEFAULT_MAX_LANGUAGE_DISTANCE` — the
    OVOS-INTENT-2 §2.2 "a distance up to 10 is a usable regional match" line.

    Args:
        a: one BCP-47 tag.
        b: the other BCP-47 tag. The relation is symmetric.
        max_distance: the inclusive upper bound on an acceptable distance. A
            distance equal to ``max_distance`` matches. Pass ``max_distance=0``
            to require an exact match (OVOS-INTENT-2 §2.2's "SHOULD prefer an
            exact match", with fallback disabled).

    Returns:
        ``True`` iff the tags are identical or within ``max_distance``.
    """
    return lang_distance(a, b) <= max_distance


def closest_lang(target: str, available: Sequence[str],
                 max_distance: int = DEFAULT_MAX_LANGUAGE_DISTANCE
                 ) -> Optional[str]:
    """Return the entry of ``available`` closest to ``target``.

    This is the reference implementation of the OVOS-INTENT-2 §2.2 language
    fallback ("a loader MAY fall back to the nearest available language"). §2.2
    is non-normative, so this selection is the package's recommended policy, not
    a conformance requirement; a loader is free to disable it (``max_distance=0``,
    yielding §2.2's "SHOULD prefer an exact match" with no fallback).

    The candidate with the smallest :func:`lang_distance` wins. It resolves
    when its distance is ``max_distance`` **or less**, so ``max_distance=0``
    accepts exact matches only. ``None`` is returned when nothing qualifies.

    Args:
        target: the requested BCP-47 tag (e.g. a session/skill language).
        available: the tags actually on hand — locale directory names, voice
            ids, model languages. Iterated once; ties resolve to the first
            smallest-distance candidate in iteration order.
        max_distance: inclusive upper bound on an acceptable match
            (default :data:`DEFAULT_MAX_LANGUAGE_DISTANCE` == §2.2's ``10``).

    Returns:
        The original string from ``available`` that best matches ``target``, or
        ``None`` when nothing qualifies. The value is returned **verbatim** (not
        standardized) so a caller can map it straight back to a directory, a
        voice, a model, and so on.
    """
    best: Optional[str] = None
    best_distance: Optional[int] = None
    for candidate in available:
        distance = lang_distance(target, candidate)
        if best_distance is None or distance < best_distance:
            best, best_distance = candidate, distance

    if best is None:
        return None
    if best_distance <= max_distance:
        return best
    return None
