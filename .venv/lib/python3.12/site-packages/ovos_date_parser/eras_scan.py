"""Language-agnostic era-phrase scanning machinery.

Surface forms are **translatable resources**: they live in ``.voc`` phrase
sets under ``ovos_date_parser/locale/<lang>/`` and are loaded through
``ovos-spec-tools`` (the OVOS-wide convention for localisable files), so
adding or improving a language's era phrasing is a translation task, not a
code change.  :func:`load_era_patterns` composes those phrase sets into
the ordered pattern table the scanner consumes; a language module
contributes only its spelled-number normaliser and any genuinely
non-translatable guard patterns (e.g. English bare "HE" needing a 5+
digit year so the pronoun never matches).

Recognised phrase-set files (all optional — a missing file just disables
that form for the language):

* ``era_bc_suffix.voc`` — "44 <form>" and "<year-ref> 44 <form>" -> BC
* ``era_ad_prefix.voc`` / ``era_ad_suffix.voc`` — "<form> 500" / "500
  <form>" -> common era
* ``era_bp_suffix.voc`` — "2000 <form>" -> radiocarbon Before Present
* ``era_unix_prefix.voc`` / ``era_julian_prefix.voc`` — fixed-epoch
  counts ("unix time N", "julian day N")
* ``era_holocene_prefix.voc`` / ``era_holocene_suffix.voc`` and
  ``era_anno_mundi_prefix.voc`` / ``era_anno_mundi_suffix.voc``
* ``era_year_ref.voc`` — "in the year"-style lead-ins, used both for
  "<year-ref> N <bc>" and for out-of-range bare years ("in the year
  12000")
* ``unit_century.voc`` / ``unit_millennium.voc`` +
  ``ordinal_suffixes.voc`` + ``marker_article.voc`` — BC-axis scoped
  ordinals ("the 3rd century BC")

Pattern contract (also for language-module extras):

* exactly one capturing group must match, holding the digits of the value
  (multiple alternative groups are fine as long as a single one matches);
* patterns are tried in order, first match wins — the builder orders
  longer, more specific phrasing first;
* the era key is a key into :data:`ovos_date_parser.eras.ERAS` or a
  pseudo-key handled structurally for every language:

  - ``__bare_year__`` — "in the year N": claimed only when N is outside
    the ``datetime`` range (representable years belong to the ordinary
    scanner);
  - ``__century_bc__`` / ``__millennium_bc__`` — ordinal periods on the
    BC axis; the earliest year of the period is returned, mirroring
    ``get_date_ordinal`` on the AD axis.
"""
import os
import re
from datetime import date, datetime
from typing import Callable, List, Optional, Pattern, Tuple, Union

from ovos_spec_tools import LocaleResources

from ovos_date_parser.eras import AstroDate, resolve_era
from ovos_date_parser.ranges import DateTimeResolution

EraPatterns = List[Tuple[str, Pattern]]

#: root of the package's translatable resources -- the legacy era/scoped
#: layers keep their own ``.voc`` phrase sets here (de/es/fr/it/pt). The
#: engine-native languages (en/ar/he) now ship their locale from the
#: reckoning core, so those folders are resolved against chronologia's
#: packaged locale instead (see :func:`_resolve_locale_dir`).
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")

_NUM = r"(\d+)"


def _resolve_locale_dir(lang: str, locale_dir: str = LOCALE_DIR) -> str:
    """Locate the resource root that actually holds ``lang``'s phrase sets.

    A language kept in the parser's own ``locale/`` (the legacy era-scan
    languages) resolves there; one whose folder has moved to the reckoning
    core (``en``/``ar``/``he``) falls back to chronologia's packaged locale
    so the legacy pre-passes keep loading the same phrase sets they always
    did without duplicating them here."""
    if os.path.isdir(os.path.join(locale_dir, lang.split("-")[0])):
        return locale_dir
    from chronologia.extract.loader import LOCALE_DIR as CHRONOLOGIA_LOCALE_DIR
    return CHRONOLOGIA_LOCALE_DIR


def _alt(phrases: List[str]) -> str:
    """Alternation of literal phrases, longest first so no phrase is
    shadowed by one of its own prefixes; internal spaces match any
    whitespace run."""
    escaped = [re.escape(p).replace(r"\ ", r"\s+")
               for p in sorted(phrases, key=len, reverse=True)]
    return "|".join(escaped)


def load_era_patterns(lang: str,
                      locale_dir: str = LOCALE_DIR) -> EraPatterns:
    """Build a language's era pattern table from its ``.voc`` phrase sets.

    Args:
        lang: BCP-47 code matching a folder under ``locale_dir``.
        locale_dir: resource root (default: the package's own locale dir).

    Returns:
        The ordered ``(era_key, pattern)`` table for
        :func:`extract_era_date`.
    """
    res = LocaleResources(_resolve_locale_dir(lang, locale_dir))

    def voc(name):
        try:
            phrases = res.load_vocabulary(name, lang)
        except FileNotFoundError:
            # a missing phrase set just disables that form for the language
            return None
        return _alt(phrases) if phrases else None

    def rx(fragment):
        return re.compile(rf"(?<![\w.]){fragment}(?=\W|$)", re.IGNORECASE)

    bc = voc("era_bc_suffix")
    ad_prefix, ad_suffix = voc("era_ad_prefix"), voc("era_ad_suffix")
    bp = voc("era_bp_suffix")
    unix, julian = voc("era_unix_prefix"), voc("era_julian_prefix")
    holo_p, holo_s = voc("era_holocene_prefix"), voc("era_holocene_suffix")
    am_p, am_s = (voc("era_anno_mundi_prefix"),
                  voc("era_anno_mundi_suffix"))
    year_ref = voc("era_year_ref")
    century, millennium = voc("unit_century"), voc("unit_millennium")
    ord_suf = voc("ordinal_suffixes")
    article = voc("marker_article")

    art = rf"(?:(?:{article})\s+)?" if article else ""
    ordinal = rf"{_NUM}\s*(?:{ord_suf})?" if ord_suf else _NUM

    patterns: EraPatterns = []

    # BC-axis scoped ordinals first: "the 3rd century BC" must win over
    # the shorter "3 BC" reading.  Both word orders are accepted
    # ("3rd century BC" and "século 3 a.C.").
    if bc and century:
        patterns.append(("__century_bc__", rx(
            rf"{art}(?:{ordinal}\s+(?:{century})|(?:{century})\s+{ordinal})"
            rf"\s+(?:{bc})")))
    if bc and millennium:
        patterns.append(("__millennium_bc__", rx(
            rf"{art}(?:{ordinal}\s+(?:{millennium})|(?:{millennium})\s+"
            rf"{ordinal})\s+(?:{bc})")))
    # longer suffix phrasing before the plain forms
    if bp:
        patterns.append(("before_present", rx(rf"{_NUM}\s*(?:{bp})")))
    if unix:
        patterns.append(("unix", rx(rf"(?:{unix})\s+(-?\d+)")))
    if julian:
        patterns.append(("julian_day", rx(rf"(?:{julian})\s+(-?\d+)")))
    if holo_p:
        patterns.append(("holocene", rx(rf"(?:{holo_p})\s+{_NUM}")))
    if holo_s:
        patterns.append(("holocene", rx(rf"{_NUM}\s+(?:{holo_s})")))
    if am_p:
        patterns.append(("anno_mundi", rx(rf"(?:{am_p})\s+{_NUM}")))
    if am_s:
        patterns.append(("anno_mundi", rx(rf"{_NUM}\s+(?:{am_s})")))
    if bc:
        if year_ref:
            patterns.append(("before_christ",
                             rx(rf"(?:{year_ref})\s+{_NUM}\s*(?:{bc})")))
        patterns.append(("before_christ", rx(rf"{_NUM}\s*(?:{bc})")))
    if ad_prefix:
        patterns.append(("common_era", rx(rf"(?:{ad_prefix})\s+{_NUM}")))
    if ad_suffix:
        patterns.append(("common_era", rx(rf"{_NUM}\s*(?:{ad_suffix})")))
    if year_ref:
        patterns.append(("__bare_year__", rx(rf"(?:{year_ref})\s+{_NUM}")))
    return patterns


def extract_era_date(text: str, patterns: EraPatterns,
                     normalize: Optional[Callable[[str], str]] = None
                     ) -> Optional[Tuple[Union[date, datetime, AstroDate],
                                         str,
                                         DateTimeResolution]]:
    """Extract an era-qualified date from ``text`` using a language's
    pattern table.

    Args:
        text: phrase possibly containing an era-qualified year/count.
        patterns: the language's ordered ``(era_key, pattern)`` table,
            usually from :func:`load_era_patterns` (plus any language-
            module extras).
        normalize: optional text normaliser applied first (typically the
            language's spelled-number-to-digits function).

    Returns:
        ``(value, remainder, resolution)`` — ``value`` is a plain
        ``datetime.date`` (or aware UTC ``datetime`` for second-counted
        eras) when representable and an :class:`AstroDate` otherwise;
        ``remainder`` is the normalised text with the era phrase removed —
        or ``None`` when no era phrasing is present.
    """
    if not text:
        return None
    normalized = normalize(text) if normalize else text

    for key, pattern in patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        value = int(next(g for g in match.groups() if g is not None))

        if key == "__bare_year__":
            # representable years belong to the ordinary scanner
            if date.min.year <= value <= date.max.year:
                continue
            result = resolve_era("common_era", value)
            resolution = DateTimeResolution.YEAR
        elif key in ("__century_bc__", "__millennium_bc__"):
            if value < 1:
                continue
            span = 100 if key == "__century_bc__" else 1000
            # the Nth century BC spans 100N BC .. (100N-99) BC; the
            # earliest year is returned (astronomical 1 - span*N)
            resolution = DateTimeResolution.CENTURY if span == 100 \
                else DateTimeResolution.MILLENNIUM
            result = AstroDate(1 - span * value, 1, 1)
        else:
            # DateTimeResolution has no sub-day members; second-counted
            # eras return an aware datetime that carries the precision
            resolution = DateTimeResolution.DAY \
                if key in ("unix", "julian_day") else DateTimeResolution.YEAR
            result = resolve_era(key, value)

        remainder = (normalized[:match.start()] +
                     normalized[match.end():]).strip()
        remainder = re.sub(r"\s{2,}", " ", remainder)
        return result, remainder, resolution
    return None
