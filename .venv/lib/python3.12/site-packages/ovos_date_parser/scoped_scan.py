"""Language-agnostic scanning of calendar-scoped ordinals and seasons.

The natural-language layer over ``ranges.py``'s scope arithmetic: "the
third week of june", "the 100th day of the year", "the first decade of
the 21st century", "summer of 1969", "next winter".  Like the era layer
(:mod:`ovos_date_parser.eras_scan`), the surface forms are translatable
resources in ``ovos_date_parser/locale/<lang>/*.voc`` loaded through
ovos-spec-tools; the grammar, the calls into
:func:`~ovos_date_parser.ranges.get_date_ordinal` and the season helpers
live here.

Grammar (all forms optional-article, case-insensitive):

* ``[the] Nth {century|millennium|decade}`` — absolute-axis periods:
  "the 21st century" is the century starting 2000 (the floor-division
  bucket convention of ``get_date_ordinal``, documented there).
* ``[the] {Nth|last} {day|week|month} of {month-name} [YYYY]`` — scoped
  into a month: "the 3rd week of june".
* ``[the] {Nth|last} {day|week|month} of the year [YYYY]`` — scoped into
  a year: "the 100th day of the year".
* ``[the] {Nth|last} {year|decade|century} of the Mth
  {century|millennium}`` — one nesting level: "the first decade of the
  21st century".
* ``[{next|last|this}] {season}`` and ``{season} of YYYY`` — resolved
  with the hemisphere-aware meteorological season tables of ``ranges.py``.

Word-form numbers must already be digits — callers pass the language's
normaliser output (the same convention as the era layer).
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from ovos_spec_tools import LocaleResources

from ovos_date_parser.eras_scan import LOCALE_DIR, _alt, _resolve_locale_dir
from ovos_date_parser.ranges import (DateTimeResolution, Hemisphere, Season,
                                     get_date_ordinal, last_season_date,
                                     next_season_date, season_to_date)

#: unit name -> the {unit}_OF_{scope} resolutions it participates in
_UNIT_OF_MONTH = {"day": DateTimeResolution.DAY_OF_MONTH,
                  "week": DateTimeResolution.WEEK_OF_MONTH}
_UNIT_OF_YEAR = {"day": DateTimeResolution.DAY_OF_YEAR,
                 "week": DateTimeResolution.WEEK_OF_YEAR,
                 "month": DateTimeResolution.MONTH_OF_YEAR}
_UNIT_OF_CENTURY = {"year": DateTimeResolution.YEAR_OF_CENTURY,
                    "decade": DateTimeResolution.DECADE_OF_CENTURY}
_UNIT_OF_MILLENNIUM = {"year": DateTimeResolution.YEAR_OF_MILLENNIUM,
                       "decade": DateTimeResolution.DECADE_OF_MILLENNIUM,
                       "century": DateTimeResolution.CENTURY_OF_MILLENNIUM}
_ABSOLUTE = {"decade": DateTimeResolution.DECADE,
             "century": DateTimeResolution.CENTURY,
             "millennium": DateTimeResolution.MILLENNIUM}


@dataclass(frozen=True)
class ScopedVocabulary:
    """A language's surface forms, as regex alternations built from its
    ``.voc`` phrase sets by :func:`load_scoped_vocabulary`.

    Every fragment is used inside a larger, case-insensitively compiled
    pattern; fragments must not contain capturing groups (the builder
    escapes all phrases, so this holds by construction).
    """
    #: canonical unit -> alternation of surface forms
    units: Dict[str, str]
    #: month name alternations, January first
    months: List[str]
    #: Season -> alternation of names
    seasons: Dict[Season, str]
    #: ordinal number: exposes ONE capturing group with the digits
    ordinal: str
    #: "the Nth ... OF ..." connector
    of: str
    #: optional article before ordinals/periods
    article: str
    #: "the year" literal used for year-scoped ordinals
    year_word: str
    #: word selecting the final unit in a scope ("the last week of june")
    last_word: str
    #: season qualifiers
    next_word: str
    this_word: str


def load_scoped_vocabulary(lang: str,
                           locale_dir: str = LOCALE_DIR
                           ) -> ScopedVocabulary:
    """Build a language's scoped vocabulary from its ``.voc`` phrase sets.

    Files consumed (under ``<locale_dir>/<lang>/``): ``unit_day.voc``,
    ``unit_week.voc``, ``unit_month.voc``, ``unit_year.voc``,
    ``unit_decade.voc``, ``unit_century.voc``, ``unit_millennium.voc``,
    ``months.voc`` (12 lines, January first), ``season_spring.voc``,
    ``season_summer.voc``, ``season_fall.voc``, ``season_winter.voc``,
    ``ordinal_suffixes.voc``, ``marker_of.voc``, ``marker_article.voc``,
    ``marker_year_word.voc``, ``marker_last.voc``, ``marker_next.voc``,
    ``marker_this.voc``.
    """
    res = LocaleResources(_resolve_locale_dir(lang, locale_dir))

    def voc(name):
        try:
            phrases = res.load_vocabulary(name, lang)
        except FileNotFoundError:
            return None
        return _alt(phrases) if phrases else None

    months = res.load_vocabulary("months", lang)
    ord_suf = voc("ordinal_suffixes")
    return ScopedVocabulary(
        units={u: voc(f"unit_{u}") for u in
               ("day", "week", "month", "year", "decade", "century",
                "millennium") if voc(f"unit_{u}")},
        months=[re.escape(m) for m in months],
        seasons={s: voc(f"season_{n}") for s, n in
                 ((Season.SPRING, "spring"), (Season.SUMMER, "summer"),
                  (Season.FALL, "fall"), (Season.WINTER, "winter"))
                 if voc(f"season_{n}")},
        ordinal=rf"(\d+)\s*(?:{ord_suf})?" if ord_suf else r"(\d+)",
        of=voc("marker_of") or "of",
        article=voc("marker_article") or "the",
        year_word=voc("marker_year_word") or "year",
        last_word=voc("marker_last") or "last",
        next_word=voc("marker_next") or "next",
        this_word=voc("marker_this") or "this",
    )


def _art(vocab):
    return rf"(?:{vocab.article}\s+)?"


def extract_scoped_date(text: str, vocab: ScopedVocabulary,
                        ref_date: Optional[date] = None,
                        hemisphere: Hemisphere = Hemisphere.NORTH
                        ) -> Optional[Tuple[date, str,
                                            DateTimeResolution]]:
    """Extract a calendar-scoped ordinal or season reference.

    Args:
        text: normalised (digits, lowercase-insensitive) phrase.
        vocab: the language's surface forms.
        ref_date: anchor for relative scopes (default: today via the
            underlying range helpers).
        hemisphere: season table to use.

    Returns:
        ``(date, remainder, resolution)`` or ``None`` when no scoped
        phrasing is present.
    """
    if not text:
        return None

    def _finish(match, value, resolution):
        remainder = (text[:match.start()] + text[match.end():]).strip()
        return value, re.sub(r"\s{2,}", " ", remainder), resolution

    art, of = _art(vocab), vocab.of
    ordinal_or_last = rf"(?:{vocab.ordinal}|({vocab.last_word}))"

    # -- "the Nth unit of the Mth century/millennium" (one nesting level)
    for scope_name, unit_map in (("century", _UNIT_OF_CENTURY),
                                 ("millennium", _UNIT_OF_MILLENNIUM)):
        if scope_name not in vocab.units:
            continue
        units = {u: r for u, r in unit_map.items() if u in vocab.units}
        if not units:
            continue
        unit_alt = "|".join(f"(?P<u_{u}>{vocab.units[u]})" for u in units)
        pattern = re.compile(
            rf"\b{art}{ordinal_or_last}\s+(?:{unit_alt})\s+(?:{of})\s+"
            rf"{art}{vocab.ordinal}\s+(?:{vocab.units[scope_name]})(?=\W|$)",
            re.IGNORECASE)
        match = pattern.search(text)
        if match:
            groups = match.groups()
            n = -1 if groups[1] else int(groups[0])
            scope_n = int(groups[-1])
            scope_ref = get_date_ordinal(scope_n,
                                         resolution=_ABSOLUTE[scope_name])
            unit = next(u for u in units if match.group(f"u_{u}"))
            resolution = units[unit]
            return _finish(match, get_date_ordinal(n, scope_ref, resolution),
                           resolution)

    # -- "the Nth day/week of june [1969]" and "... of the year [1969]"
    month_units = {u: r for u, r in _UNIT_OF_MONTH.items()
                   if u in vocab.units}
    year_units = {u: r for u, r in _UNIT_OF_YEAR.items() if u in vocab.units}
    if month_units and vocab.months:
        unit_alt = "|".join(f"(?P<u_{u}>{vocab.units[u]})"
                            for u in month_units)
        month_alt = "|".join(f"(?P<m_{i}>{m})"
                             for i, m in enumerate(vocab.months))
        pattern = re.compile(
            rf"\b{art}{ordinal_or_last}\s+(?:{unit_alt})\s+(?:{of})\s+"
            rf"(?:{month_alt})(?:\s+(\d{{4}}))?(?=\W|$)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            groups = match.groups()
            n = -1 if groups[1] else int(groups[0])
            month = next(i for i in range(12) if match.group(f"m_{i}")) + 1
            year = int(groups[-1]) if groups[-1] else \
                (ref_date.year if ref_date else date.today().year)
            unit = next(u for u in month_units if match.group(f"u_{u}"))
            resolution = month_units[unit]
            scope_ref = date(year, month, 1)
            return _finish(match, get_date_ordinal(n, scope_ref, resolution),
                           resolution)
    if year_units:
        unit_alt = "|".join(f"(?P<u_{u}>{vocab.units[u]})" for u in year_units)
        pattern = re.compile(
            rf"\b{art}{ordinal_or_last}\s+(?:{unit_alt})\s+(?:{of})\s+"
            rf"{art}(?:{vocab.year_word})(?:\s+(\d{{4}}))?(?=\W|$)",
            re.IGNORECASE)
        match = pattern.search(text)
        if match:
            groups = match.groups()
            n = -1 if groups[1] else int(groups[0])
            year = int(groups[-1]) if groups[-1] else \
                (ref_date.year if ref_date else date.today().year)
            unit = next(u for u in year_units if match.group(f"u_{u}"))
            resolution = year_units[unit]
            return _finish(match, get_date_ordinal(n, date(year, 1, 1),
                                                   resolution), resolution)

    # -- absolute periods: "the 21st century", "the 3rd millennium"
    for unit, resolution in _ABSOLUTE.items():
        if unit not in vocab.units:
            continue
        pattern = re.compile(
            rf"\b{art}{vocab.ordinal}\s+(?:{vocab.units[unit]})(?=\W|$)",
            re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return _finish(match,
                           get_date_ordinal(int(match.group(1)),
                                            resolution=resolution),
                           resolution)

    # -- seasons: "summer of 1969", "next summer", "last winter", "summer"
    if vocab.seasons:
        season_alt = "|".join(f"(?P<s_{s.name}>{alt})"
                              for s, alt in vocab.seasons.items())
        pattern = re.compile(
            rf"\b(?:({vocab.next_word})|({vocab.last_word})|"
            rf"({vocab.this_word}))?\s*(?:{season_alt})"
            rf"(?:\s+(?:{of})\s+(\d{{4}}))?(?=\W|$)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            season = next(s for s in vocab.seasons
                          if match.group(f"s_{s.name}"))
            year = match.groups()[-1]
            if year:
                value = season_to_date(season, int(year), hemisphere)
            elif match.group(2):  # last
                value = last_season_date(season, ref_date, hemisphere)
            elif match.group(1):  # next
                value = next_season_date(season, ref_date, hemisphere)
            else:  # this / bare: the season's start in the anchor year
                value = season_to_date(season, ref_date, hemisphere)
            return _finish(match, value, DateTimeResolution.MONTH)
    return None
