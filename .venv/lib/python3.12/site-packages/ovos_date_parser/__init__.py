import json
import os
import re
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Callable, List, Optional, Tuple, Union

import dateparser # fallback parser
from dateparser.search import search_dates
from ovos_config import Configuration
from ovos_utils.log import LOG
from ovos_utils.time import now_local

from ovos_date_parser.common import nice_duration_generic, nice_relative_time_generic
from ovos_date_parser.dates_ar import (
    extract_datetime_ar, extract_duration_ar, nice_time_ar, nice_duration_ar,
)
from ovos_date_parser.ranges import (
    Hemisphere, Season, DateTimeResolution, BEFORE_PRESENT_EPOCH,
    get_week_range, get_weekend_range, get_month_range, get_year_range,
    get_decade_range, get_century_range, get_millennium_range,
    get_season_range, get_week_number, get_date_ordinal,
    date_to_season, season_to_date, next_season_date, last_season_date,
)
from ovos_date_parser.eras_scan import extract_era_date, load_era_patterns
from ovos_date_parser.scoped_scan import (ScopedVocabulary, extract_scoped_date,
                                          load_scoped_vocabulary)
from ovos_date_parser.scoped_en import extract_scoped_date_en, SCOPED_VOCAB_EN
from ovos_date_parser.eras_en import extract_era_date_en, ERA_PATTERNS_EN
from ovos_date_parser.eras_pt import extract_era_date_pt, ERA_PATTERNS_PT
from ovos_date_parser.eras_es import extract_era_date_es, ERA_PATTERNS_ES
from ovos_date_parser.eras_fr import extract_era_date_fr, ERA_PATTERNS_FR
from ovos_date_parser.eras_de import extract_era_date_de, ERA_PATTERNS_DE
from ovos_date_parser.eras_it import extract_era_date_it, ERA_PATTERNS_IT
from ovos_date_parser.astrodate import (AstroDate, DateSpan, civil_add,
                                        resolve_wall_clock)
from ovos_date_parser.eras import (
    Era, EraCounting, ERAS, astro_year_range, is_leap_year,
    julian_day_to_date, resolve_bp, resolve_era,
)
# Newer reckoning-core surface, re-exported so downstream code can reach the
# timeline, named-period and radiocarbon-calibration facilities alongside the
# established date-parsing API.
from chronologia import TIMELINES, PERIODS, calibrate_c14
from ovos_date_parser.duration import (
    DurationResolution, DurationLexicon, DURATION_LEXICONS, extract_duration_generic
)
from ovos_date_parser.dates_ast import (
    extract_duration_ast, extract_datetime_ast, nice_year_ast, nice_weekday_ast, nice_month_ast,
    nice_day_ast, nice_date_time_ast, nice_date_ast, nice_time_ast
)
from ovos_date_parser.dates_an import (
    nice_year_an, nice_weekday_an, nice_month_an, nice_day_an, nice_date_an,
    nice_time_an, nice_date_time_an, extract_datetime_an, extract_duration_an
)
from ovos_date_parser.dates_fy import (
    nice_year_fy, nice_weekday_fy, nice_month_fy, nice_day_fy,
    nice_date_time_fy, nice_date_fy, nice_time_fy, nice_part_of_day_fy,
    extract_datetime_fy, extract_duration_fy
)
from ovos_date_parser.dates_az import (
    extract_datetime_az, extract_duration_az, nice_duration_az, nice_time_az,
)
from ovos_date_parser.dates_ca import (
    TimeVariantCA, extract_datetime_ca, nice_time_ca, extract_duration_ca
)
from ovos_date_parser.dates_cs import (
    extract_duration_cs, extract_datetime_cs, nice_time_cs
)
from ovos_date_parser.dates_sk import (
    extract_duration_sk, extract_datetime_sk, nice_time_sk
)
from ovos_date_parser.dates_hr import (
    extract_duration_hr, extract_datetime_hr, nice_time_hr
)
from ovos_date_parser.dates_bg import (
    extract_duration_bg, extract_datetime_bg, nice_time_bg
)
from ovos_date_parser.dates_da import (
    extract_datetime_da, extract_duration_da, nice_time_da,
)
from ovos_date_parser.dates_de import (
    extract_datetime_de, extract_duration_de, nice_time_de,
)
from ovos_date_parser.dates_nb import (
    extract_datetime_nb, extract_duration_nb, nice_time_nb,
)
from ovos_date_parser.dates_nn import (
    extract_datetime_nn, extract_duration_nn, nice_time_nn,
)
from ovos_date_parser.dates_en import (
    extract_datetime_en, extract_date_en, extract_time_en,
    extract_duration_en, nice_time_en
)
from ovos_date_parser.dates_es import (
    extract_datetime_es, extract_duration_es, nice_time_es, nice_date_time_es, nice_date_es,
    nice_weekday_es, nice_day_es, nice_year_es, nice_month_es
)
from ovos_date_parser.dates_eu import (
    extract_datetime_eu, nice_time_eu, nice_relative_time_eu, extract_duration_eu,
)
from ovos_date_parser.dates_et import (
    extract_datetime_et, extract_duration_et, nice_time_et, nice_year_et,
)
from ovos_date_parser.dates_fa import (
    extract_datetime_fa, nice_time_fa, extract_duration_fa,
)
from ovos_date_parser.dates_fi import (
    extract_datetime_fi, extract_duration_fi, nice_time_fi, nice_year_fi,
)
from ovos_date_parser.dates_fr import (
    extract_duration_fr,
    extract_datetime_fr, nice_time_fr
)
from ovos_date_parser.dates_gl import (
    extract_duration_gl, extract_datetime_gl, nice_year_gl, nice_weekday_gl, nice_month_gl,
    nice_day_gl, nice_date_time_gl, nice_date_gl, nice_time_gl
)
from ovos_date_parser.dates_el import (
    extract_duration_el, extract_datetime_el, nice_year_el, nice_weekday_el, nice_month_el,
    nice_day_el, nice_date_time_el, nice_date_el, nice_time_el
)
from ovos_date_parser.dates_he import (
    extract_duration_he, extract_datetime_he, nice_year_he, nice_weekday_he, nice_month_he,
    nice_day_he, nice_date_time_he, nice_date_he, nice_time_he
)
from ovos_date_parser.dates_ro import (
    extract_duration_ro, extract_datetime_ro, nice_year_ro, nice_weekday_ro, nice_month_ro,
    nice_day_ro, nice_date_time_ro, nice_date_ro, nice_time_ro
)
from ovos_date_parser.dates_oc import (
    extract_datetime_oc, nice_year_oc, nice_weekday_oc, nice_month_oc,
    nice_day_oc, nice_date_time_oc, nice_date_oc, nice_time_oc
)
from ovos_date_parser.dates_hu import nice_time_hu, extract_duration_hu, extract_datetime_hu
from ovos_date_parser.dates_kab import (
    extract_datetime_kab, extract_duration_kab, nice_time_kab,
)
from ovos_date_parser.dates_it import (
    extract_datetime_it, nice_time_it, extract_duration_it
)
from ovos_date_parser.dates_nl import (
    extract_datetime_nl, nice_part_of_day_nl, extract_duration_nl, nice_time_nl
)
from ovos_date_parser.dates_pl import (
    extract_datetime_pl, extract_duration_pl, nice_time_pl, nice_duration_pl
)
from ovos_date_parser.dates_pt import (
    extract_datetime_pt, extract_duration_pt, nice_time_pt, nice_date_pt, nice_year_pt, nice_date_time_pt,
    nice_month_pt, nice_weekday_pt, nice_day_pt
)
from ovos_date_parser.dates_ru import (
    extract_datetime_ru, extract_duration_ru, nice_time_ru, nice_duration_ru
)
from ovos_date_parser.dates_sl import (
    nice_time_sl, extract_duration_sl, extract_datetime_sl
)
from ovos_date_parser.dates_sv import (
    extract_datetime_sv, extract_duration_sv, nice_time_sv
)
from ovos_date_parser.dates_uk import (
    extract_datetime_uk, extract_duration_uk, nice_time_uk, nice_duration_uk
)
from ovos_date_parser.dates_ms import nice_time_ms, extract_datetime_ms
from ovos_date_parser.dates_id import nice_time_id, extract_datetime_id
from ovos_date_parser.dates_tr import nice_time_tr, extract_datetime_tr


def _as_datetime(dt):
    """Coerce an :class:`AstroDate` to a real ``datetime`` when it fits one.

    The legacy ``nice_*`` formatters were written against ``datetime`` and lean
    on clock-and-locale ``strftime`` directives (``%I``, ``%A``, ``%B``) that
    the unbounded :class:`~chronologia.AstroDate` deliberately refuses. Any
    ``AstroDate`` inside the proleptic-Gregorian ``datetime`` range is
    byte-identical to its ``.datetime()`` projection, so we hand that through
    transparently. A ``datetime`` (or anything already outside AstroDate) is
    returned untouched; an out-of-range ``AstroDate`` (a BC or far-future point
    a ``datetime`` cannot hold) is left as-is so year-only formatters that only
    need ``%Y`` still work and clock formatters fail loudly instead of lying.
    """
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, AstroDate) and dt.in_datetime_range:
        return dt.datetime()
    return dt


def nice_time(
        dt: datetime,
        lang: str,
        speech: bool = True,
        use_24hour: bool = False,
        use_ampm: bool = False,
        variant: Optional[Union[TimeVariantCA, str]] = None,
) -> str:
    """
    Format a time to a comfortable human format.

    Args:
        dt: date to format (assumes already in local timezone).
        lang: A BCP-47 language code.
        speech: Format for speech (default is True) or display (False).
        use_24hour: Output in 24-hour/military or 12-hour format.
        use_ampm: Include the am/pm for 12-hour format.
        variant: Optional time-telling register for Catalan (ca). Accepts a
            TimeVariantCA member or a friendly alias string such as
            "standard"/"central" (les quatre i quart) or "quarts" (un quart
            de cinc). Ignored for other languages.

    Returns:
        The formatted time string.
    """
    dt = _as_datetime(dt)
    if lang.startswith("ar"):
        return nice_time_ar(dt, speech, use_24hour, use_ampm)
    if lang.startswith("ast"):
        return nice_time_ast(dt, speech, use_24hour, use_ampm)
    if lang.startswith("an"):
        return nice_time_an(dt, speech, use_24hour, use_ampm)
    if lang.startswith("az"):
        return nice_time_az(dt, speech, use_24hour, use_ampm)
    if lang.startswith("gl"):
        return nice_time_gl(dt, speech, use_24hour, use_ampm)
    if lang.startswith("el"):
        return nice_time_el(dt, speech, use_24hour, use_ampm)
    if lang.startswith("he"):
        return nice_time_he(dt, speech, use_24hour, use_ampm)
    if lang.startswith("oc"):
        return nice_time_oc(dt, speech, use_24hour, use_ampm)
    if lang.startswith("ro"):
        return nice_time_ro(dt, speech, use_24hour, use_ampm)
    if lang.startswith("ca"):
        return nice_time_ca(dt, speech, use_24hour, use_ampm, variant=variant)
    if lang.startswith("cs"):
        return nice_time_cs(dt, speech, use_24hour, use_ampm)
    if lang.startswith("sk"):
        return nice_time_sk(dt, speech, use_24hour, use_ampm, variant=variant)
    if lang.startswith("hr"):
        return nice_time_hr(dt, speech, use_24hour, use_ampm, variant=variant)
    if lang.startswith("bg"):
        return nice_time_bg(dt, speech, use_24hour, use_ampm, variant=variant)
    if lang.startswith("da"):
        return nice_time_da(dt, speech, use_24hour, use_ampm)
    if lang.startswith("de"):
        return nice_time_de(dt, speech, use_24hour, use_ampm)
    if lang.startswith("en"):
        return nice_time_en(dt, speech, use_24hour, use_ampm)
    if lang.startswith("es"):
        return nice_time_es(dt, speech, use_24hour, use_ampm)
    if lang.startswith("et"):
        return nice_time_et(dt, speech, use_24hour, use_ampm)
    if lang.startswith("eu"):
        return nice_time_eu(dt, speech, use_24hour, use_ampm)
    if lang.startswith("fa"):
        return nice_time_fa(dt, speech, use_24hour, use_ampm)
    if lang.startswith("fi"):
        return nice_time_fi(dt, speech, use_24hour, use_ampm)
    if lang.startswith("fr"):
        return nice_time_fr(dt, speech, use_24hour, use_ampm)
    if lang.startswith("hu"):
        return nice_time_hu(dt, speech, use_24hour, use_ampm)
    if lang.startswith("it"):
        return nice_time_it(dt, speech, use_24hour, use_ampm)
    if lang.startswith("kab"):
        return nice_time_kab(dt, speech, use_24hour, use_ampm)
    if lang.startswith("fy"):
        return nice_time_fy(dt, speech, use_24hour, use_ampm)
    if lang.startswith("nl"):
        return nice_time_nl(dt, speech, use_24hour, use_ampm)
    if lang.startswith("nn"):
        return nice_time_nn(dt, speech, use_24hour, use_ampm)
    if lang.startswith("nb") or lang.startswith("no"):
        return nice_time_nb(dt, speech, use_24hour, use_ampm)
    if lang.startswith("pl"):
        return nice_time_pl(dt, speech, use_24hour, use_ampm)
    if lang.startswith("pt"):
        return nice_time_pt(dt, speech, use_24hour, use_ampm)
    if lang.startswith("ru"):
        return nice_time_ru(dt, speech, use_24hour, use_ampm)
    if lang.startswith("sv"):
        return nice_time_sv(dt, speech, use_24hour, use_ampm)
    if lang.startswith("sl"):
        return nice_time_sl(dt, speech, use_24hour, use_ampm)
    if lang.startswith("uk"):
        return nice_time_uk(dt, speech, use_24hour, use_ampm)
    if lang.startswith("ms"):
        return nice_time_ms(dt, speech, use_24hour, use_ampm)
    if lang.startswith("id"):
        return nice_time_id(dt, speech, use_24hour, use_ampm)
    if lang.startswith("tr"):
        return nice_time_tr(dt, speech, use_24hour, use_ampm)
    raise NotImplementedError(f"Unsupported language: {lang}")


def nice_relative_time(when, relative_to=None, lang="en-us"):
    """Create a relative phrase to roughly describe a datetime

    Examples are "25 seconds", "tomorrow", "7 days".

    Args:
        when (datetime): Local timezone
        relative_to (datetime): Baseline for relative time, default is now()
        lang (str, optional): Defaults to "en-us".
    Returns:
        str: Relative description of the given time
    """
    when = _as_datetime(when)
    relative_to = _as_datetime(relative_to) if relative_to is not None else now_local()
    if lang.startswith("eu"):
        return nice_relative_time_eu(when, relative_to)
    return nice_relative_time_generic(lang, when, relative_to)


def nice_duration(
        duration: Union[int, float], lang: str, speech: bool = True
) -> str:
    """
    Convert duration in seconds to a nice spoken timespan.

    Args:
        duration: Time in seconds.
        lang: A BCP-47 language code.
        speech: Format for speech (True) or display (False).

    Returns:
        Timespan as a string.
    """
    if lang.startswith("ar"):
        return nice_duration_ar(duration, speech)
    if lang.startswith("az"):
        return nice_duration_az(duration, speech)
    if lang.startswith("pl"):
        return nice_duration_pl(duration, speech)
    if lang.startswith("ru"):
        return nice_duration_ru(duration, speech)
    if lang.startswith("uk"):
        return nice_duration_uk(duration, speech)
    return nice_duration_generic(lang, duration, speech)


def extract_duration(
        text: str, lang: str, *,
        resolution: DurationResolution = DurationResolution.TIMEDELTA,
        replace_token: str = ""
) -> Tuple[Optional[timedelta], str]:
    """
    Convert a phrase into a duration and return the remainder text.

    Args:
        text: String containing a duration.
        lang: A BCP-47 language code.
        resolution: Format to return the duration in — timedelta
            (default), calendar-accurate relativedelta, or a total in a
            single unit. Only supported for languages on the shared
            duration engine.
        replace_token: String each consumed duration is replaced with in
            the remainder, marking where it was found. Only supported
            for languages on the shared duration engine.

    Returns:
        A tuple containing the duration (timedelta, relativedelta or
        float depending on resolution) and the remaining text.
    """
    code = lang.split("-")[0].lower()
    if code in DURATION_LEXICONS:
        return extract_duration_generic(text, DURATION_LEXICONS[code],
                                        resolution, replace_token)
    if resolution != DurationResolution.TIMEDELTA or replace_token:
        raise NotImplementedError(
            f"resolution/replace_token not supported for language: {lang}")
    if lang.startswith("ar"):
        return extract_duration_ar(text)
    if lang.startswith("ast"):
        return extract_duration_ast(text)
    if lang.startswith("kab"):
        return extract_duration_kab(text)
    if lang.startswith("fa"):
        return extract_duration_fa(text)
    if lang.startswith("sv"):
        return extract_duration_sv(text)
    # no native extractor for this language, report no duration found
    return None, text


def extract_datetime(
        text: str,
        lang: str,
        anchorDate: Optional[datetime] = None,
        default_time: Optional[time] = None,
) -> Optional[Tuple[datetime, str]]:
    """
    Extract date and time information from a sentence.

    Args:
        text: The text to be interpreted.
        lang: The BCP-47 code for the language to use.
        anchorDate: Date to use for relative dating.
        default_time: Time to use if none was found in the input string.

    Returns:
        A tuple with the extracted date as datetime and the leftover string,
        or None if no date or time related text is found.
    """
    if lang.startswith("an"):
        return extract_datetime_an(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("ar"):
        return extract_datetime_ar(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("ast"):
        return extract_datetime_ast(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("az"):
        return extract_datetime_az(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("ca"):
        return extract_datetime_ca(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("cs"):
        return extract_datetime_cs(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("sk"):
        return extract_datetime_sk(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("hr"):
        return extract_datetime_hr(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("bg"):
        return extract_datetime_bg(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("da"):
        return extract_datetime_da(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("de"):
        return extract_datetime_de(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("en"):
        return extract_datetime_en(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("es"):
        return extract_datetime_es(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("et"):
        return extract_datetime_et(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("eu"):
        return extract_datetime_eu(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("fa"):
        return extract_datetime_fa(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("fi"):
        return extract_datetime_fi(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("fr"):
        return extract_datetime_fr(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("fy"):
        return extract_datetime_fy(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("gl"):
        return extract_datetime_gl(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("el"):
        return extract_datetime_el(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("he"):
        return extract_datetime_he(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("oc"):
        return extract_datetime_oc(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("ro"):
        return extract_datetime_ro(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("hu"):
        return extract_datetime_hu(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("it"):
        return extract_datetime_it(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("kab"):
        return extract_datetime_kab(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("nl"):
        return extract_datetime_nl(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("nn"):
        return extract_datetime_nn(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("nb") or lang.startswith("no"):
        return extract_datetime_nb(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("pl"):
        return extract_datetime_pl(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("pt"):
        return extract_datetime_pt(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("ru"):
        return extract_datetime_ru(text, anchor_date=anchorDate, default_time=default_time)
    if lang.startswith("sl"):
        return extract_datetime_sl(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("sv"):
        return extract_datetime_sv(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("uk"):
        return extract_datetime_uk(text, anchor_date=anchorDate, default_time=default_time)
    if lang.startswith("ms"):
        return extract_datetime_ms(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("id"):
        return extract_datetime_id(text, anchorDate=anchorDate, default_time=default_time)
    if lang.startswith("tr"):
        return extract_datetime_tr(text, anchorDate=anchorDate, default_time=default_time)

    # fallback parser
    LOG.warning(f"{lang} is not implemented! attempting to use fallback date parser")

    tzstr = Configuration()["location"]["timezone"]["code"]
    fmt = Configuration().get("date_format", 'DMY')
    settings = {'RELATIVE_BASE': anchorDate or now_local(),
                'TIMEZONE': tzstr,
                'RETURN_AS_TIMEZONE_AWARE': True,
                'TO_TIMEZONE': tzstr,
                'DATE_ORDER': fmt}

    try:  # assume full text is a date with no leftover
        date = dateparser.parse(text,
                                languages=[lang.split("-")[0]],
                                settings=settings)
        if date:
            return date, ""
    except Exception as e:
        pass

    # less accurate substring search
    try:
        dates = search_dates(text,
                             languages=[lang.split("-")[0]],
                             settings=settings)
        if dates:
            date_txt, date = dates[0]
            return date, text.replace(date_txt, "")
    except:
        pass

    # fallback found nothing, report no date/time found
    return None


@dataclass(frozen=True)
class DateTimeSpan:
    """A date or time expression, together with where it was written.

    ``start`` and ``end`` are half-open code-point offsets into the utterance
    the span was extracted from, so ``utterance[start:end] == surface`` holds.
    """
    start: int
    end: int
    surface: str
    value: datetime


@dataclass(frozen=True)
class DurationSpan:
    """A length of time, together with where it was written.

    Offsets follow the same convention as :class:`DateTimeSpan`.
    """
    start: int
    end: int
    surface: str
    value: timedelta


#: characters that punctuate a word without belonging to it; a leading or
#: trailing run of these is not part of an expression's surface
_SPAN_PUNCTUATION = "\"'`´.,;:!?¡¿…()[]{}<>«»“”‘’"

#: longest expression the window search considers, in words; long enough for
#: spoken phrases such as "the day after tomorrow at half past seven in the
#: evening", and the knob that decides how much the scan costs
_MAX_SPAN_WORDS = 20

#: how many words the extractor may make nothing of - reading no value, or
#: leaving them behind - before a window is abandoned: an expression that has
#: not started or not resumed by then is over. Words it keeps reading do not
#: count, however long they leave the value unchanged, as in the persian
#: "یک ساعت و پنجاه و هفت و نیم دقیقه" where only the last word moves it
_MAX_SPAN_DRIFT = 10

#: an expression's reading, as the extractors report it: the value and the
#: words they did not consume
Reading = Tuple[Optional[object], Tuple[str, ...]]


def _word_spans(text: str) -> List[Tuple[int, int]]:
    """Offsets of the whitespace separated words, stripped of edge punctuation."""
    spans = []
    for match in re.finditer(r"\S+", text):
        start, end = match.span()
        while start < end and text[end - 1] in _SPAN_PUNCTUATION:
            # a full stop after digits is an ordinal marker in several
            # languages ("15. juni"), not punctuation around the word
            if text[end - 1] == "." and text[start:end - 1].isdigit():
                break
            end -= 1
        while start < end and text[start] in _SPAN_PUNCTUATION:
            start += 1
        if start < end:
            spans.append((start, end))
    return spans


def _joined(text: str, words: List[Tuple[int, int]], first: int, last: int) -> bool:
    """Whether two neighbouring words can belong to the same expression.

    Punctuation between them is no boundary on its own: the apostrophe in the
    dutch "3 uur 's middags" and the commas in "2 hours, 30 minutes, and 10
    seconds" sit inside one expression, and the extractor reads the slice
    whole. What decides is whether it consumes the words, not the character
    between them.
    """
    gap = text[words[first][1]:words[last][0]].strip()
    return not gap or all(char in _SPAN_PUNCTUATION for char in gap)


def _read_expression(text: str, words: List[Tuple[int, int]], index: int,
                     read: Callable[[str], Reading], additive: bool):
    """The longest window from ``index`` that reads as a single expression.

    A window is one expression when the extractor consumed all of it, or when
    a single word it left behind bridges two halves that need each other, as
    in the swedish "om 8 veckor och 2 dagar" and the portuguese "duas horas e
    trinta minutos". A bridge is told from a boundary by what follows it: in
    "monday to friday" the reading of "to friday" is the reading of the whole,
    so "to" ends monday's span rather than bridging it.
    """
    start = words[index][0]
    found = None
    shorter = None
    lost = None
    core = index
    for cursor in range(index, min(index + _MAX_SPAN_WORDS, len(words))):
        if cursor > index and not _joined(text, words, cursor - 1, cursor):
            break
        end = words[cursor][1]
        value, leftover = read(text[start:end])
        if value is None:
            if found is not None and lost is None:
                lost = cursor
        elif value != shorter:
            bridged = len(leftover) == 1 and all(
                read(text[words[inner][0]:end])[0] != value
                for inner in range(core + 1, cursor + 1))
            if (not leftover or bridged) and (
                    lost is None or not additive or
                    _reads_as_one(text, words, lost, cursor, value, read)):
                found = (cursor, value, len(leftover))
        if value is not None and not leftover:
            core = cursor
        if cursor - core >= _MAX_SPAN_DRIFT:
            break
        shorter = value
    return found


def _reads_as_one(text: str, words: List[Tuple[int, int]], lost: int,
                  cursor: int, value: object, read: Callable[[str], Reading]) -> bool:
    """Whether nothing inside a window reads as an expression of its own.

    Asked where the extractor lost the thread inside the window - it read an
    expression, then nothing for a longer window, then a value again for a
    longer one still, which is what a run-on of two expressions looks like.
    "in ten minutes and again in half an hour" reads as ten and a half hours,
    a length nobody said, so such a window counts as one expression only when
    every reading starting where the thread was lost agrees with the whole.
    """
    end = words[cursor][1]
    return all(read(text[words[inner][0]:end])[0] in (None, value)
               for inner in range(lost, cursor + 1))


def _widen_expression(text: str, words: List[Tuple[int, int]], first: int,
                      last: int, value: object, slack: int,
                      read: Callable[[str], Reading], floor: int) -> Tuple[int, int]:
    """Pull in the neighbouring words the extractor also consumes.

    The window search finds the value; it does not find the whole expression,
    because a word that does not move the value never joins by that test.
    Widening recovers those words - "next", "this", "at", "pm" - by growing
    outward while the value stays put and the added words are consumed, which
    is what keeps "from" and "to" out: they survive in the leftover. A word
    that carries nothing on its own is stepped over rather than stopping the
    widening, so "da" joins on the way to "manhã".
    """
    probe = first
    while probe > floor and probe > last - _MAX_SPAN_WORDS + 1 and \
            _joined(text, words, probe - 1, probe):
        probe -= 1
        grown, leftover = read(text[words[probe][0]:words[last][1]])
        if grown == value and len(leftover) <= slack:
            first = probe
    probe = last
    while probe + 1 < min(len(words), first + _MAX_SPAN_WORDS) and \
            _joined(text, words, probe, probe + 1):
        probe += 1
        grown, leftover = read(text[words[first][0]:words[probe][1]])
        if grown == value and len(leftover) <= slack:
            last = probe
    return first, last


def _core_expression(text: str, words: List[Tuple[int, int]], first: int,
                     last: int, value: object,
                     read: Callable[[str], Reading]) -> int:
    """Where the expression starts once its framing words are dropped.

    "at 5 pm" reads as "5 pm" and "from monday" as "monday": the leading words
    frame the expression without carrying it. The last word that can be
    dropped while the value holds and the extractor still consumes everything
    marks the core.
    """
    while first < last:
        grown, leftover = read(text[words[first + 1][0]:words[last][1]])
        if grown != value or leftover:
            break
        first += 1
    return first


def _expression_spans(text: str, read: Callable[[str], Reading],
                      additive: bool = False) -> List[Tuple[int, int, object]]:
    """Find the expressions ``read`` recognises, as ``(start, end, value)``.

    Words are grown into an expression from each starting word in turn, the
    window is widened over the words around it, and the search resumes after
    it, so two expressions in one utterance never merge into a value nobody
    said. An expression whose framing words can be dropped without changing
    the reading is reported twice, as the written phrase and as its core, so
    a consumer holding either text finds it. The window handed to ``read`` is
    always the raw slice ``text[start:end]``, and windows are bounded in
    length, so the scan stays linear in the length of the text.
    """
    words = _word_spans(text)
    spans = []
    index = floor = 0
    while index < len(words):
        found = _read_expression(text, words, index, read, additive)
        if found is None:
            index += 1
            continue
        last, value, slack = found
        first, last = _widen_expression(text, words, index, last, value, slack,
                                        read, floor)
        end = words[last][1]
        core = _core_expression(text, words, first, last, value, read)
        spans.append((words[first][0], end, value))
        if core != first:
            spans.append((words[core][0], end, value))
        index = floor = last + 1
    return spans


def extract_datetime_spans(
        text: str,
        lang: str,
        anchor_date: Optional[datetime] = None,
        default_time: Optional[time] = None,
) -> List[DateTimeSpan]:
    """Extract every date or time expression in a text with its offsets.

    Each span covers a whole expression, so "next friday at 5 pm" is one and
    "from monday to friday" is two. An expression written with framing words
    also comes back as its core, so "next friday" is reported both whole and
    as "friday", with the same value. Spans come back sorted by ``start``.

    Args:
        text: the utterance to scan.
        lang: the BCP-47 code for the language to use.
        anchor_date: the "now" relative expressions resolve against, the wall
            clock by default. Passed to the extractor as given; a value that
            comes back without a zone is read in the anchor's zone, or in the
            local one when the anchor carries none.
        default_time: time to use for expressions that name no time of day.

    Returns:
        The expressions found, in the order they are written.
    """
    if not isinstance(text, str):
        return []
    zone = anchor_date.tzinfo if anchor_date else None

    def read(fragment: str) -> Reading:
        found = extract_datetime(fragment, lang, anchorDate=anchor_date,
                                 default_time=default_time)
        if not found or found[0] is None:
            return None, ()
        value, leftover = found
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone) if zone else value.astimezone()
        return value, tuple(leftover.split())

    return [DateTimeSpan(start, end, text[start:end], value)
            for start, end, value in _expression_spans(text, read)]


def extract_duration_spans(text: str, lang: str) -> List[DurationSpan]:
    """Extract every duration in a text with its offsets.

    Each span covers a whole duration, so "in two hours and thirty minutes"
    is one span, reported both whole and as its core when the two differ.
    Spans come back sorted by ``start``.

    Args:
        text: the utterance to scan.
        lang: the BCP-47 code for the language to use.

    Returns:
        The durations found, in the order they are written.
    """
    if not isinstance(text, str):
        return []

    def read(fragment: str) -> Reading:
        value, leftover = extract_duration(fragment, lang)
        return value, tuple(leftover.split())

    return [DurationSpan(start, end, text[start:end], value)
            for start, end, value in _expression_spans(text, read, additive=True)]


#: Span-native natural-language extraction (text -> DateSpan) is owned by
#: the reckoning core. ``extract_timespan`` and ``explain`` are re-exported
#: here unchanged so the parser keeps its public surface; the legacy
#: ``extract_datetime`` / ``extract_date_xx`` paths are untouched by this.
from chronologia import extract_timespan, explain


NUMBER_TUPLE = namedtuple(
    'number',
    ('x, xx, x0, x_in_x0, xxx, x00, x_in_x00, xx00, xx_in_xx00, x000, ' +
     'x_in_x000, x0_in_x000, x_in_0x00'))


class DateTimeFormat:
    """resource file based regex date formatter
    NOTE: this is optional, can be implemented as code if desired"""

    def __init__(self, config_path):
        self.lang_config = {}
        self.config_path = config_path

    def cache(self, lang):
        lang = lang.split("-")[0]
        # "no" is a common alias for Norwegian Bokmål (nb); the dedicated
        # nice_time/extract_datetime/extract_duration functions already
        # special-case it, but this generic JSON-driven engine (used by
        # nice_year/nice_date/nice_date_time) didn't have its own resource
        # directory for it - load Bokmål's data under the "no" key instead.
        resource_lang = "nb" if lang == "no" else lang
        # TODO - find closest lang code
        if lang not in self.lang_config:
            path = self.config_path + '/' + resource_lang + '/date_time.json'
            if not os.path.isfile(path):
                LOG.warning(f"could not find '{path}'")
                return
            with open(path, 'r', encoding='utf8') as lang_config_file:
                self.lang_config[lang] = json.loads(
                    lang_config_file.read())

            for x in ['decade_format', 'hundreds_format', 'thousand_format',
                      'year_format']:
                i = 1
                while self.lang_config[lang][x].get(str(i)):
                    self.lang_config[lang][x][str(i)]['re'] = (
                        re.compile(self.lang_config[lang][x][str(i)]['match']
                                   ))
                    i = i + 1

    def _number_strings(self, number, lang):
        lang = lang.split("-")[0]
        x = (self.lang_config[lang]['number'].get(str(number % 10)) or
             str(number % 10))
        xx = (self.lang_config[lang]['number'].get(str(number % 100)) or
              str(number % 100))
        x_in_x0 = self.lang_config[lang]['number'].get(
            str(int(number % 100 / 10))) or str(int(number % 100 / 10))
        x0 = (self.lang_config[lang]['number'].get(
            str(int(number % 100 / 10) * 10)) or
              str(int(number % 100 / 10) * 10))
        xxx = (self.lang_config[lang]['number'].get(str(number % 1000)) or
               str(number % 1000))
        x00 = (self.lang_config[lang]['number'].get(str(int(
            number % 1000 / 100) * 100)) or
               str(int(number % 1000 / 100) * 100))
        x_in_x00 = self.lang_config[lang]['number'].get(str(int(
            number % 1000 / 100))) or str(int(number % 1000 / 100))
        xx00 = self.lang_config[lang]['number'].get(str(int(
            number % 10000 / 100) * 100)) or str(int(number % 10000 / 100) *
                                                 100)
        xx_in_xx00 = self.lang_config[lang]['number'].get(str(int(
            number % 10000 / 100))) or str(int(number % 10000 / 100))
        x000 = (self.lang_config[lang]['number'].get(str(int(
            number % 10000 / 1000) * 1000)) or
                str(int(number % 10000 / 1000) * 1000))
        x_in_x000 = self.lang_config[lang]['number'].get(str(int(
            number % 10000 / 1000))) or str(int(number % 10000 / 1000))
        x0_in_x000 = self.lang_config[lang]['number'].get(str(int(
            number % 10000 / 1000) * 10)) or str(int(number % 10000 / 1000) * 10)
        x_in_0x00 = self.lang_config[lang]['number'].get(str(int(
            number % 1000 / 100)) or str(int(number % 1000 / 100)))

        return NUMBER_TUPLE(
            x, xx, x0, x_in_x0, xxx, x00, x_in_x00, xx00, xx_in_xx00, x000,
            x_in_x000, x0_in_x000, x_in_0x00)

    def _format_string(self, number, format_section, lang):
        lang = lang.split("-")[0]
        s = self.lang_config[lang][format_section]['default']
        i = 1
        while self.lang_config[lang][format_section].get(str(i)):
            e = self.lang_config[lang][format_section][str(i)]
            if e['re'].match(str(number)):
                return e['format']
            i = i + 1
        return s

    def _decade_format(self, number, number_tuple, lang):
        s = self._format_string(number % 100, 'decade_format', lang)
        return s.format(x=number_tuple.x, xx=number_tuple.xx,
                        x0=number_tuple.x0, x_in_x0=number_tuple.x_in_x0,
                        number=str(number % 100))

    def _number_format_hundreds(self, number, number_tuple, lang,
                                formatted_decade):
        s = self._format_string(number % 1000, 'hundreds_format', lang)
        return s.format(xxx=number_tuple.xxx, x00=number_tuple.x00,
                        x_in_x00=number_tuple.x_in_x00,
                        formatted_decade=formatted_decade,
                        number=str(number % 1000))

    def _number_format_thousand(self, number, number_tuple, lang,
                                formatted_decade, formatted_hundreds):
        """
        Format the thousands part of a year using language-specific templates.

        Parameters:
            number (int): The year value to format.
            number_tuple: A named tuple containing precomputed string representations of number components.
            lang (str): Language code for localization.
            formatted_decade (str): Preformatted decade string.
            formatted_hundreds (str): Preformatted hundreds string.

        Returns:
            str: The formatted thousands part of the year as a localized string.
        """
        s = self._format_string(number % 10000, 'thousand_format', lang)
        return s.format(x_in_x00=number_tuple.x_in_x00,
                        xx00=number_tuple.xx00,
                        xx_in_xx00=number_tuple.xx_in_xx00,
                        x000=number_tuple.x000,
                        x_in_x000=number_tuple.x_in_x000,
                        x0_in_x000=number_tuple.x0_in_x000,
                        x_in_0x00=number_tuple.x_in_0x00,
                        formatted_decade=formatted_decade,
                        formatted_hundreds=formatted_hundreds,
                        number=str(number % 10000))

    def date_format(self, dt, lang, now, include_weekday=True):
        """
        Format a datetime object as a localized date string according to language-specific templates.
        
        Parameters:
            dt (datetime): The date to format.
            lang (str): Language code for localization.
            now (datetime): Reference date for relative formatting (e.g., today, tomorrow).
            include_weekday (bool): If True, includes the weekday name in the output.
        
        Returns:
            str: The formatted date string, localized and optionally including the weekday.
        """
        format_str = 'date_full'
        lang = lang.split("-")[0]
        if now:
            if dt.year == now.year:
                format_str = 'date_full_no_year'
                if dt.month == now.month and dt.day > now.day:
                    format_str = 'date_full_no_year_month'

            tomorrow = now + timedelta(days=1)
            yesterday = now - timedelta(days=1)
            if tomorrow.date() == dt.date():
                format_str = 'tomorrow'
            elif now.date() == dt.date():
                format_str = 'today'
            elif yesterday.date() == dt.date():
                format_str = 'yesterday'

        unformatted = self.lang_config[lang]['date_format'][format_str]
        args = dict(
                month=self.lang_config[lang]['month'][str(dt.month)],
                day=self.lang_config[lang]['date'][str(dt.day)],
                formatted_year=self.year_format(dt, lang, False)
        )
        if include_weekday:
            args["weekday"] = self.lang_config[lang]['weekday'][str(dt.weekday())]
        else:
            unformatted = re.sub(r"{weekday}\s*,?\s*", "", unformatted).strip(", ")
        return unformatted.format(**args)

    def date_time_format(self, dt, lang, now, use_24hour, use_ampm):
        lang = lang.split("-")[0]
        date_str = self.date_format(dt, lang, now)
        time_str = nice_time(dt, lang, use_24hour=use_24hour,
                             use_ampm=use_ampm)
        return self.lang_config[lang]['date_time_format']['date_time'].format(
            formatted_date=date_str, formatted_time=time_str)

    def year_format(self, dt, lang, bc, ad=False):
        lang = lang.split("-")[0]
        number_tuple = self._number_strings(dt.year, lang)
        formatted_bc = (
            self.lang_config[lang]['year_format']['bc'] if bc else '')
        formatted_decade = self._decade_format(
            dt.year, number_tuple, lang)
        formatted_hundreds = self._number_format_hundreds(
            dt.year, number_tuple, lang, formatted_decade)
        formatted_thousand = self._number_format_thousand(
            dt.year, number_tuple, lang, formatted_decade, formatted_hundreds)

        s = self._format_string(dt.year, 'year_format', lang)
        result = re.sub(' +', ' ',
                      s.format(
                          year=str(dt.year),
                          century=str(int(dt.year / 100)),
                          decade=str(dt.year % 100),
                          formatted_hundreds=formatted_hundreds,
                          formatted_decade=formatted_decade,
                          formatted_thousand=formatted_thousand,
                          bc=formatted_bc)).strip()
        # explicit AD/CE marker, mutually exclusive with bc.
        # only applied for locales that define an "ad" suffix in their
        # year_format resource (e.g. "e.Kr." in Danish); a no-op elsewhere
        # so existing languages/callers are unaffected.
        if ad and not bc:
            formatted_ad = self.lang_config[lang]['year_format'].get('ad', '')
            if formatted_ad:
                result = f"{result} {formatted_ad}"
        return result


date_time_format = DateTimeFormat(os.path.join(os.path.dirname(__file__), 'res'))


def nice_date(dt, lang, now=None, include_weekday=True):
    """
    Format a datetime to a pronounceable date

    For example, generates 'tuesday, june the fifth, 2018'

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        lang (str, optional): an optional BCP-47 language code, if omitted
                              the default language will be used.
        now (datetime): Current date. If provided, the returned date for speech
            will be shortened accordingly: No year is returned if now is in the
            same year as td, no month is returned if now is in the same month
            as td. If now and td is the same day, 'today' is returned.
        include_weekday (bool, optional): Whether to include the weekday name in the output. Defaults to True.

    Returns:
        (str): The formatted date string
    """
    dt = _as_datetime(dt)
    now = _as_datetime(now) if now is not None else None
    lang = lang.lower().split("-")[0]
    if lang.startswith("pt"):
        return nice_date_pt(dt, now, include_weekday)
    if lang.startswith("es"):
        return nice_date_es(dt, now, include_weekday)
    if lang.startswith("gl"):
        return nice_date_gl(dt, now, include_weekday)
    if lang.startswith("el"):
        return nice_date_el(dt, now, include_weekday)
    if lang.startswith("he"):
        return nice_date_he(dt, now, include_weekday)
    if lang.startswith("oc"):
        return nice_date_oc(dt, now, include_weekday)
    if lang.startswith("ro"):
        return nice_date_ro(dt, now, include_weekday)
    if lang.startswith("ast"):
        return nice_date_ast(dt, now, include_weekday)
    if lang.startswith("an"):
        return nice_date_an(dt, now, include_weekday)
    if lang.startswith("fy"):
        return nice_date_fy(dt, now, include_weekday)
    date_time_format.cache(lang)
    return date_time_format.date_format(dt, lang, now, include_weekday)


def nice_date_time(dt, lang, now=None, use_24hour=False,
                   use_ampm=False):
    """
        Format a datetime to a pronounceable date and time

        For example, generate 'tuesday, june the fifth, 2018 at five thirty'

        Args:
            dt (datetime): date to format (assumes already in local timezone)
            lang (str, optional): an optional BCP-47 language code, if omitted
                                  the default language will be used.
            now (datetime): Current date. If provided, the returned date for
                speech will be shortened accordingly: No year is returned if
                now is in the same year as td, no month is returned if now is
                in the same month as td. If now and td is the same day, 'today'
                is returned.
            use_24hour (bool): output in 24-hour/military or 12-hour format
            use_ampm (bool): include the am/pm for 12-hour format
        Returns:
            (str): The formatted date time string
    """
    dt = _as_datetime(dt)
    now = _as_datetime(now) if now is not None else None
    lang = lang.lower().split("-")[0]
    if lang.startswith("pt"):
        return nice_date_time_pt(dt, now, use_24hour, use_ampm)
    if lang.startswith("es"):
        return nice_date_time_es(dt, now, use_24hour, use_ampm)
    if lang.startswith("gl"):
        return nice_date_time_gl(dt, now, use_24hour, use_ampm)
    if lang.startswith("el"):
        return nice_date_time_el(dt, now, use_24hour, use_ampm)
    if lang.startswith("he"):
        return nice_date_time_he(dt, now, use_24hour, use_ampm)
    if lang.startswith("oc"):
        return nice_date_time_oc(dt, now, use_24hour, use_ampm)
    if lang.startswith("ro"):
        return nice_date_time_ro(dt, now, use_24hour, use_ampm)
    if lang.startswith("ast"):
        return nice_date_time_ast(dt, now, use_24hour, use_ampm)
    if lang.startswith("an"):
        return nice_date_time_an(dt, now, use_24hour, use_ampm)
    if lang.startswith("fy"):
        return nice_date_time_fy(dt, now, use_24hour, use_ampm)
    date_time_format.cache(lang)
    return date_time_format.date_time_format(dt, lang, now, use_24hour, use_ampm)


def nice_day(dt, lang, date_format='DMY', include_month=True):
    dt = _as_datetime(dt)
    if lang.startswith("pt"):
        return nice_day_pt(dt, date_format, include_month)
    if lang.startswith("es"):
        return nice_day_es(dt, date_format, include_month)
    if lang.startswith("gl"):
        return nice_day_gl(dt, date_format, include_month)
    if lang.startswith("el"):
        return nice_day_el(dt, date_format, include_month)
    if lang.startswith("he"):
        return nice_day_he(dt, date_format, include_month)
    if lang.startswith("oc"):
        return nice_day_oc(dt, date_format, include_month)
    if lang.startswith("ro"):
        return nice_day_ro(dt, date_format, include_month)
    if lang.startswith("ast"):
        return nice_day_ast(dt, date_format, include_month)
    if lang.startswith("an"):
        return nice_day_an(dt, date_format, include_month)
    if lang.startswith("fy"):
        return nice_day_fy(dt, date_format, include_month)
    if include_month:
        month = nice_month(dt, lang, date_format)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d"))
        else:
            return "{} {}".format(dt.strftime("%d"), month)
    return dt.strftime("%d")


def nice_weekday(dt, lang):
    dt = _as_datetime(dt)
    lang = lang.lower().split("-")[0]
    if lang.startswith("pt"):
        return nice_weekday_pt(dt)
    if lang.startswith("es"):
        return nice_weekday_es(dt)
    if lang.startswith("gl"):
        return nice_weekday_gl(dt)
    if lang.startswith("el"):
        return nice_weekday_el(dt)
    if lang.startswith("he"):
        return nice_weekday_he(dt)
    if lang.startswith("oc"):
        return nice_weekday_oc(dt)
    if lang.startswith("ro"):
        return nice_weekday_ro(dt)
    if lang.startswith("ast"):
        return nice_weekday_ast(dt)
    if lang.startswith("an"):
        return nice_weekday_an(dt)
    if lang.startswith("fy"):
        return nice_weekday_fy(dt)
    date_time_format.cache(lang)

    if lang in date_time_format.lang_config.keys():
        localized_day_names = list(
            date_time_format.lang_config[lang]['weekday'].values())
        weekday = localized_day_names[dt.weekday()]
    else:
        weekday = dt.strftime("%A")
    return weekday.capitalize()


def nice_month(dt, lang, date_format='MDY'):
    dt = _as_datetime(dt)
    lang = lang.lower().split("-")[0]
    if lang.startswith("pt"):
        return nice_month_pt(dt)
    if lang.startswith("es"):
        return nice_month_es(dt)
    if lang.startswith("gl"):
        return nice_month_gl(dt)
    if lang.startswith("el"):
        return nice_month_el(dt)
    if lang.startswith("he"):
        return nice_month_he(dt)
    if lang.startswith("oc"):
        return nice_month_oc(dt)
    if lang.startswith("ro"):
        return nice_month_ro(dt)
    if lang.startswith("ast"):
        return nice_month_ast(dt)
    if lang.startswith("an"):
        return nice_month_an(dt)
    if lang.startswith("fy"):
        return nice_month_fy(dt)
    date_time_format.cache(lang)
    if lang in date_time_format.lang_config.keys():
        localized_month_names = date_time_format.lang_config[lang]['month']
        month = localized_month_names[str(int(dt.strftime("%m")))]
    else:
        month = dt.strftime("%B")
    return month.capitalize()


def nice_year(dt, lang, bc=False, ad=False):
    """
        Format a datetime to a pronounceable year

        For example, generate 'nineteen-hundred and eighty-four' for year 1984

        Args:
            dt (datetime): date to format (assumes already in local timezone)
            lang (str, optional): an optional BCP-47 language code, if omitted
                                  the default language will be used.
            bc (bool) pust B.C. after the year (python does not support dates
                B.C. in datetime)
            ad (bool) append an explicit AD/CE marker after the year (e.g.
                "e.Kr." in Danish). Mutually exclusive with bc. Only has an
                effect for locales that define an "ad" suffix in their
                year_format resource; a no-op otherwise.
        Returns:
            (str): The formatted year string
    """
    dt = _as_datetime(dt)
    if bc and dt.year <= 0:
        # AstroDate counts years astronomically (1 BC is year 0, 300 BC is
        # -299); what is spoken is the era year, so hand the formatters that.
        dt = datetime(1 - dt.year, 1, 1)
    lang = lang.lower().split("-")[0]
    if lang.startswith("pt"):
        return nice_year_pt(dt, bc)
    if lang.startswith("es"):
        return nice_year_es(dt, bc)
    if lang.startswith("gl"):
        return nice_year_gl(dt, bc)
    if lang.startswith("el"):
        return nice_year_el(dt, bc)
    if lang.startswith("he"):
        return nice_year_he(dt, bc)
    if lang.startswith("oc"):
        return nice_year_oc(dt, bc)
    if lang.startswith("ro"):
        return nice_year_ro(dt, bc)
    if lang.startswith("ast"):
        return nice_year_ast(dt, bc)
    if lang.startswith("an"):
        return nice_year_an(dt, bc)
    if lang.startswith("fi"):
        return nice_year_fi(dt, bc)
    if lang.startswith("fy"):
        return nice_year_fy(dt, bc)
    if lang.startswith("et"):
        return nice_year_et(dt, bc)
    date_time_format.cache(lang)
    return date_time_format.year_format(dt, lang, bc, ad)


#: English month names, indexed 1..12. The unbounded :class:`AstroDate`
#: refuses locale ``strftime`` directives (``%B``), and a span may sit in a
#: year no ``datetime`` can hold, so span labels read the month straight off
#: the integer field instead of formatting a projected ``datetime``.
_EN_MONTHS = [None, "January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]


#: Gregorian-Arabic month names, indexed 1..12, matching chronologia's
#: ``ar`` ``month_N.voc`` first entries (the forms its extractor's
#: ``calendar_date`` construction reads in "DAY MONTH YEAR" / "MONTH YEAR").
_AR_MONTHS = [None, "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
              "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

#: Hebrew month names, indexed 1..12, matching chronologia's ``he``
#: ``month_N.voc``. In a full date the month takes a ``ב`` ("in") prefix
#: ("15 בינואר 2020"); in a month-year it stands bare ("ינואר 2020") -- both
#: forms are listed in the extractor's vocab, so day-scale labels prepend ``ב``.
_HE_MONTHS = [None, "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
              "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

#: Decade words keyed by the tens digit (2 -> "twenties"), from the ``ar``/``he``
#: ``decade_word_N0.voc``. chronologia's ``decade_ref`` resolves a bare decade
#: word into the **20th century** (e.g. "الثמانينات"/"שנות השמונים" -> 1980s),
#: so only 1900s decades round-trip; other centuries and the 1900s/1910s (no
#: word) have no native construction and fall through to the best-effort path.
_SEMITIC_DECADE_WORD = {
    "ar": {2: "العشرينات", 3: "الثلاثينات", 4: "الأربعينات", 5: "الخمسينات",
           6: "الستينات", 7: "السبعينات", 8: "الثمانينات", 9: "التسعينات"},
    "he": {2: "שנות העשרים", 3: "שנות השלושים", 4: "שנות הארבעים",
           5: "שנות החמישים", 6: "שנות השישים", 7: "שנות השבעים",
           8: "שנות השמונים", 9: "שנות התשעים"},
}

#: BC era marker each extractor's ``era_bc`` ("NUM bc") construction reads.
#: ``ar`` folds "ق.م" and "ق م" alike; ``he`` uses the gershayim (U+05F4) form
#: "לפנה״ס" the ``he`` era corpus asserts.
_SEMITIC_BC_MARKER = {"ar": "ق.م", "he": "לפנה״ס"}


def _ordinal(n: int) -> str:
    """English ordinal for a positive integer: 1 -> '1st', 22 -> '22nd'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _span_scale(span: "DateSpan") -> str:
    """Classify a span into the coarsest calendar unit its width represents.

    The width *is* the precision: a one-day span is a day, a ~30-day span a
    month, a ~3652-day span a decade, and so on (see chronologia's
    ``DateSpan.resolution``). Sub-day widths split off as ``"time"`` so an
    instant formats as a clock reading rather than a bare date.
    """
    name = span.resolution.name
    if name == "DAY":
        # resolution collapses everything <= 1 day to DAY; separate a
        # clock-precision instant from a whole calendar day by real width.
        width = span.width
        seconds = getattr(width, "total_seconds", lambda: 0.0)()
        return "day" if seconds >= 43200 else "time"
    if name in ("WEEK", "WEEK_OF_MONTH", "WEEK_OF_YEAR"):
        return "week"
    if name.startswith("MONTH"):
        return "month"
    if name.startswith("YEAR"):
        return "year"
    if name.startswith("DECADE"):
        return "decade"
    if name.startswith("CENTURY"):
        return "century"
    if name.startswith("MILLENNIUM"):
        return "millennium"
    return "era"


def _nice_span_en(span: "DateSpan", scale: str) -> str:
    """English span label, chosen to round-trip through ``extract_timespan``.

    A label from a day up is the canonical written form the chronologia English
    extractor re-parses to the same span, so
    ``extract_timespan(nice_span(span, "en"), "en")`` recovers ``span`` for
    years from 1000 AD onward and from 32 BC back. Nearer the era boundary the
    year numeral is ambiguous -- a one- or two-digit year reads as a
    day-of-month and a bare three-digit year does not read as a year at all --
    and a sub-day span reads as a spoken date and time. Those are labelled but
    not round-trip gated.
    """
    start = span.start
    bc = start.is_bc
    year = start.bc_year if bc else start.year
    if scale == "time":
        return nice_date_time(start, "en")
    if scale in ("day", "week"):
        day = f"{_EN_MONTHS[start.month]} {_ordinal(start.day)}, {year}"
        if bc:
            day = f"{day} BC"
        # A week is named by the day it opens on; extraction snaps "the week
        # of <date>" back to the week containing that day.
        return f"the week of {day}" if scale == "week" else day
    if scale == "month":
        month = f"{_EN_MONTHS[start.month]} {year}"
        return f"{month} BC" if bc else month
    if scale == "year":
        return f"{start.bc_year} BC" if bc else str(start.year)
    if scale == "decade":
        if bc:
            decade = (start.bc_year // 10) * 10
            return f"the {decade}s BC"
        return f"the {(start.year // 10) * 10}s"
    if scale == "century":
        if bc:
            n = (start.bc_year + 99) // 100
            return f"the {_ordinal(n)} century BC"
        return f"the {_ordinal(start.year // 100 + 1)} century"
    if scale == "millennium":
        if bc:
            n = (start.bc_year + 999) // 1000
            return f"the {_ordinal(n)} millennium BC"
        return f"the {_ordinal(start.year // 1000 + 1)} millennium"
    # era / geological scale: no compact spoken construct, name it by its
    # opening year. Not round-trip gated.
    return f"{start.bc_year} BC" if bc else str(start.year)


def _bc_day_label(start: "AstroDate", lang: str) -> str:
    """Day label for a BC point, naming the era year rather than the astronomical one.

    ``nice_date`` speaks whatever year the point carries, and a BC point carries
    an astronomical year (300 BC is -299), so a plain call reads "-299" into the
    sentence. The year-wide label already asks ``nice_year`` for the era form;
    this substitutes that form into the day label so both widths name the same
    year in the same words.
    """
    label = nice_date(start, lang)
    astronomical = nice_year(start, lang)
    if astronomical not in label:
        raise NotImplementedError(
            f"nice_span cannot place a BC era year in a '{lang}' day label")
    return label.replace(astronomical, nice_year(start, lang, bc=True))


def _nice_span_generic(span: "DateSpan", scale: str, lang: str) -> str:
    """Span label built from the locale's own ``nice_*`` formatters.

    The day, week, month and year widths read out of the language's own word
    tables, so the label is written in that language. The coarse widths --
    decade, century, millennium and era -- have no localised construction
    outside English, and an English numeral idiom dropped into another
    language's sentence is worse than nothing, so those widths are refused.
    """
    start = span.start
    if scale == "time":
        return nice_date_time(start, lang)
    if scale in ("day", "week"):
        if start.is_bc:
            return _bc_day_label(start, lang)
        return nice_date(start, lang)
    if scale == "month":
        return f"{nice_month(start, lang)} {nice_year(start, lang, bc=start.is_bc)}"
    if scale == "year":
        return nice_year(start, lang, bc=start.is_bc)
    raise NotImplementedError(f"nice_span has no {scale} label for '{lang}'")


def _nice_span_semitic(span: "DateSpan", scale: str, code: str) -> str:
    """Native-script span label for Arabic (``ar``) and Hebrew (``he``).

    Emits the exact native calendar phrasing chronologia's ``ar``/``he``
    extractors re-parse, so ``extract_timespan(nice_span(span, code), code)``
    recovers the span for every width those scanners construct: day
    ("21 يوليو 2026" / "20 ביולי 1969"), month ("يوليو 2026" / "יולי 2026"),
    year ("2026"), year-BC ("300 ق.م" / "300 לפנה״ס") and 20th-century decades
    ("الثمانينات" / "שנות השמונים"). Western digits are used throughout -- the
    numeral form both extractors' corpora assert. The remaining widths (week,
    century, millennium, BC decade/century/millennium, non-1900s decades) have
    no native construction in these locales and fall through to the best-effort
    label, which is not round-trip gated.
    """
    start = span.start
    bc = start.is_bc
    year = start.bc_year if bc else start.year
    months = _AR_MONTHS if code == "ar" else _HE_MONTHS
    if scale == "day":
        month = months[start.month]
        if code == "he":
            month = f"ב{month}"
        # Logical token order (day month year) is what the RTL extractor reads;
        # no bidi controls are needed -- the round-trip gate proves it parses.
        day = f"{start.day} {month} {year}"
        # BC day has no native construction; label it but leave it ungated.
        return f"{day} {_SEMITIC_BC_MARKER[code]}" if bc else day
    if scale == "month":
        month = f"{months[start.month]} {year}"
        return f"{month} {_SEMITIC_BC_MARKER[code]}" if bc else month
    if scale == "year":
        if bc:
            return f"{start.bc_year} {_SEMITIC_BC_MARKER[code]}"
        return str(start.year)
    if scale == "decade" and not bc and start.year // 100 == 19:
        # The bare decade word is century-relative: chronologia resolves it
        # into the 20th century, so it can only name a 1900s decade. Any other
        # century falls through and is refused rather than named wrongly.
        word = _SEMITIC_DECADE_WORD[code].get((start.year // 10) % 10)
        if word is not None:
            return word
    # No native construction for this width: best-effort, not round-trip gated.
    return _nice_span_generic(span, scale, code)


def nice_span(span: "DateSpan", lang: str = "en-us") -> str:
    """Format a :class:`~chronologia.DateSpan` at the granularity it carries.

    A span's *width* is its precision, so the label is chosen from the width
    rather than from a fixed template: a one-day span reads as a date
    ("July 21st, 2026"), a month-wide span as a month ("July 2026"), a
    year-wide span as a year ("2026"), a decade as "the 1980s", a century as
    "the 19th century", and so on symmetrically down to BC eras, which are
    named by their era year ("300 BC") rather than the astronomical one.

    This is the inverse of :func:`extract_timespan`. In English a label from a
    day up re-parses to the same span for years from 1000 AD onward and from
    32 BC back; nearer the era boundary the year numeral is ambiguous with a
    day-of-month, and a sub-day span reads as a spoken date and time, which
    extraction cannot take back.

    Args:
        span: The half-open ``[start, end)`` interval to describe.
        lang: A BCP-47 language code.

    Returns:
        A human-readable label for the span.

    Raises:
        NotImplementedError: The language has no label for this width. Outside
            English the decade, century, millennium and era widths have no
            localised construction (Arabic and Hebrew label 20th-century
            decades natively), and a width is refused rather than answered in
            another language.
    """
    if not isinstance(span, DateSpan):
        raise TypeError(f"nice_span expects a DateSpan, got {type(span).__name__}")
    scale = _span_scale(span)
    code = lang.lower().split("-")[0]
    if code == "en":
        return _nice_span_en(span, scale)
    if code in ("ar", "he"):
        return _nice_span_semitic(span, scale, code)
    return _nice_span_generic(span, scale, lang)


def get_date_strings(dt, lang, date_format=None, time_format="full"):
    date_format = date_format or Configuration().get("date_format", 'DMY')
    lang = lang.lower().split("-")[0]
    timestr = nice_time(dt, lang, speech=False,
                        use_24hour=time_format == "full")
    monthstr = nice_month(dt, lang, date_format)
    weekdaystr = nice_weekday(dt, lang)
    yearstr = dt.strftime("%Y")
    daystr = nice_day(dt, date_format=date_format, include_month=False, lang=lang)
    if date_format == 'MDY':
        dtstr = dt.strftime("%-m/%-d/%Y")
    elif date_format == 'DMY':
        dtstr = dt.strftime("%d/%-m/%-Y")
    elif date_format == 'YMD':
        dtstr = dt.strftime("%Y/%-m/%-d")
    else:
        raise ValueError("invalid date_format")
    return {
        "date_string": dtstr,
        "time_string": timestr,
        "month_string": monthstr,
        "day_string": daystr,
        'year_string': yearstr,
        "weekday_string": weekdaystr
    }
