"""Estonian date and time parsing and formatting.

Estonian, like Finnish, is agglutinative and case-rich: numerals below a
hundred that are not round agglutinate ("kaksteist" = 12, "kakskümmend" = 20)
and the noun after a numeral greater than one takes the partitive singular
("kaks tundi", "viis minutit"). The spoken clock keeps the "kell" marker
("kell kaksteist") and the year is read as a plain cardinal number.

References:
    * Eesti Keele Instituut (EKI), Eesti keele käsiraamat,
      "Arvsõnad" and kellaaja/kuupäeva usage
    * https://et.wikipedia.org/wiki/Kellaaeg
"""
from datetime import timedelta

from ovos_number_parser.numbers_et import (
    pronounce_number_et, extract_number_et,
)
from ovos_utils.time import now_local

from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic,
)

# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------

_PART_OF_DAY_ET = (
    (5, 11, "hommikul"),   # morning
    (12, 17, "päeval"),    # daytime
    (18, 22, "õhtul"),     # evening
)


def _part_of_day_et(hour):
    for start, end, word in _PART_OF_DAY_ET:
        if start <= hour <= end:
            return word
    return "öösel"  # night, 23..4


def nice_year_et(dt, bc=False):
    """Speak a year as an Estonian cardinal number.

    Estonian reads years as whole cardinals ("tuhat üheksasada
    kaheksakümmend neli" for 1984), not as decade pairs.
    """
    year = pronounce_number_et(dt.year)
    if bc:
        return year + " enne Kristust"
    return year


def _speak_minutes_et(minute):
    if minute < 10:
        return " null " + pronounce_number_et(minute)
    return " " + pronounce_number_et(minute)


def nice_time_et(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a natural Estonian way.

    For example, generate "kell viisteist kolmkümmend" for 15:30.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default) or display (False)
        use_24hour (bool): output in 24-hour format
        use_ampm (bool): include a part-of-day adverb for 12-hour format
    Returns:
        (str): The formatted time string
    """
    if use_24hour:
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            string = dt.strftime("%I:%M %p")
        else:
            string = dt.strftime("%I:%M")
        if string[0] == "0":
            string = string[1:]

    if not speech:
        return string

    if use_24hour:
        speak = "kell " + pronounce_number_et(dt.hour)
        if dt.minute:
            speak += _speak_minutes_et(dt.minute)
        return speak

    if dt.hour == 0 and dt.minute == 0:
        return "kesköö"
    if dt.hour == 12 and dt.minute == 0:
        return "keskpäev"

    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    speak = "kell " + pronounce_number_et(hour)
    if dt.minute:
        speak += _speak_minutes_et(dt.minute)
    if use_ampm:
        speak += " " + _part_of_day_et(dt.hour)
    return speak


# ---------------------------------------------------------------------------
# duration
# ---------------------------------------------------------------------------

def extract_duration_et(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """Convert an Estonian phrase into a duration.

    Handles "kaks tundi", "kolmkümmend minutit" and similar; numerals are
    read by the shared number parser and matched against the declined unit
    nouns.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["et"],
                                    resolution, replace_token)


# ---------------------------------------------------------------------------
# datetime extraction
# ---------------------------------------------------------------------------

_WEEKDAYS_ET = {
    "esmaspäev": 0, "teisipäev": 1, "kolmapäev": 2, "neljapäev": 3,
    "reede": 4, "laupäev": 5, "pühapäev": 6,
}
# weekday adessive ("esmaspäeval") also appears
_WEEKDAY_STEMS_ET = {name: num for name, num in _WEEKDAYS_ET.items()}

_MONTHS_ET = {
    "jaanuar": 1, "veebruar": 2, "märts": 3, "aprill": 4, "mai": 5,
    "juuni": 6, "juuli": 7, "august": 8, "september": 9, "oktoober": 10,
    "november": 11, "detsember": 12,
}
# month genitive endings that appear in dates ("jaanuaril", "jaanuaris")
_MONTH_STEMS_ET = {name: num for name, num in _MONTHS_ET.items()}

_DAY_UNITS_ET = ("päev", "päeva", "päevad")
_WEEK_UNITS_ET = ("nädal", "nädala", "nädalat")
_MONTH_UNITS_ET = ("kuu", "kuud")
_YEAR_UNITS_ET = ("aasta", "aastat")
_HOUR_UNITS_ET = ("tund", "tunni", "tundi")
_MINUTE_UNITS_ET = ("minut", "minuti", "minutit")
_SECOND_UNITS_ET = ("sekund", "sekundi", "sekundit")
_AFTER_MARKERS_ET = ("pärast", "järel", "möödudes")
_NEXT_ET = ("järgmine", "järgmisel", "tulev", "tuleval")
_LAST_ET = ("eelmine", "eelmisel", "möödunud")

# genitive cardinals, the case that "N <unit> pärast" actually uses in
# speech ("kolme nädala", "kahe tunni"); plus the fraction words used here
_GENITIVE_NUMBERS_ET = {
    "ühe": 1, "kahe": 2, "kolme": 3, "nelja": 4, "viie": 5, "kuue": 6,
    "seitsme": 7, "kaheksa": 8, "üheksa": 9, "kümne": 10,
    "poole": 0.5, "pooleteist": 1.5,
}


def _offset_number_et(token):
    """Resolve the numeral in a relative-offset slot, nominative or genitive.

    Returns an int/float value or None. Fractions (0.5, 1.5) stay floats so
    "poole/pooleteist tunni" can express half hours.
    """
    if token in _GENITIVE_NUMBERS_ET:
        return _GENITIVE_NUMBERS_ET[token]
    if token.isdigit():
        return int(token)
    val = extract_number_et(token)
    if val is not False and val is not None:
        return val
    return None


def _clean_tokens_et(text):
    out = []
    for tok in text.lower().replace(",", " ").split():
        # keep internal separators (15.30, 15:30) but drop edge punctuation,
        # so an ordinal "15." becomes "15"
        tok = tok.strip("?!;:.")
        if tok:
            out.append(tok)
    return out


# idiomatic spoken clock, traditional "counting toward the coming hour":
# "veerand kaks" = 1:15, "pool kaks" = 1:30, "kolmveerand kaks" = 1:45
_QUARTER_MINUTES_ET = {"veerand": 15, "pool": 30, "kolmveerand": 45}


def _num_et(token):
    if token is None:
        return None
    if token.isdigit():
        return int(token)
    val = extract_number_et(token)
    if val is not False and val is not None and val == int(val):
        return int(val)
    return None


def _scan_clock_idiom_et(words):
    """Match an idiomatic spoken clock ("pool kaks" = 1:30).

    Returns (hour, minute, consumed_indices) or None. The hour named is the
    *coming* hour: "pool kaks" is half an hour before two, i.e. 1:30, and
    "veerand kaks" is a quarter into that hour, i.e. 1:15.
    """
    n = len(words)
    for i, w in enumerate(words):
        if w in _QUARTER_MINUTES_ET and i + 1 < n:
            h = _num_et(words[i + 1])
            if h and 1 <= h <= 12:
                cons = {i, i + 1}
                if i > 0 and words[i - 1] == "kell":
                    cons.add(i - 1)
                return (h - 1) or 12, _QUARTER_MINUTES_ET[w], cons
    return None


def _weekday_from_word_et(word):
    if word in _WEEKDAYS_ET:
        return _WEEKDAYS_ET[word]
    for stem, num in _WEEKDAY_STEMS_ET.items():
        if word.startswith(stem):  # adessive "esmaspäeval"
            return num
    return None


def _month_from_word_et(word):
    if word in _MONTHS_ET:
        return _MONTHS_ET[word]
    for stem, num in _MONTH_STEMS_ET.items():
        if word.startswith(stem):
            return num
    return None


def extract_datetime_et(text, anchorDate=None, default_time=None):
    """Extract date/time information from Estonian text.

    Supported constructs (each verified against everyday usage):
        * täna / homme / ülehomme / eile / üleeile
        * weekday names (nominative and adessive), with järgmine/eelmine
        * "N <unit> pärast" for day/week/month/year and also hour/minute
          offsets, with the numeral in the nominative or the genitive as it
          appears in speech ("kolme päeva pärast", "pooleteist tunni pärast")
        * "järgmine|eelmine nädal|kuu|aasta"
        * clock times: "kell 15:30", "kell 15", "15:30", "15.30"
        * dates with a month name: "15. jaanuar", "jaanuari 15."

    Returns a ``[datetime, leftover_text]`` pair, or ``None`` when nothing
    date related is found.
    """
    if not text:
        return None

    anchor = anchorDate or now_local()
    anchor = anchor.replace(microsecond=0)
    words = _clean_tokens_et(text)
    if not words:
        return None

    day_offset = None
    week_offset = 0
    month_offset = 0
    year_offset = 0
    abs_month = None
    abs_day = None
    hr_abs = None
    min_abs = None
    min_offset = 0  # relative "in N hours/minutes" offset, in minutes
    sec_offset = 0  # relative "in N seconds" offset, in seconds
    consumed = [False] * len(words)
    found = False

    idiom = _scan_clock_idiom_et(words)
    if idiom is not None:
        hr_abs, min_abs, cons = idiom
        for c in cons:
            consumed[c] = True
        found = True

    for idx, word in enumerate(words):
        if consumed[idx]:
            continue
        prev = words[idx - 1] if idx > 0 else ""
        nxt = words[idx + 1] if idx + 1 < len(words) else ""

        if word in ("täna", "praegu"):
            day_offset = 0
            consumed[idx] = True
            found = True
            continue
        if word == "homme":
            day_offset = 1
            consumed[idx] = True
            found = True
            continue
        if word == "ülehomme":
            day_offset = 2
            consumed[idx] = True
            found = True
            continue
        if word == "eile":
            day_offset = -1
            consumed[idx] = True
            found = True
            continue
        if word == "üleeile":
            day_offset = -2
            consumed[idx] = True
            found = True
            continue

        weekday = _weekday_from_word_et(word)
        if weekday is not None:
            diff = (weekday - anchor.weekday()) % 7
            if prev in _NEXT_ET:
                if diff == 0:
                    diff = 7
                consumed[idx - 1] = True
            elif prev in _LAST_ET:
                diff = diff - 7 if diff != 0 else -7
                consumed[idx - 1] = True
            day_offset = diff
            consumed[idx] = True
            found = True
            continue

        if word in ("nädal", "nädalal") and prev in _NEXT_ET + _LAST_ET:
            week_offset = 1 if prev in _NEXT_ET else -1
            consumed[idx] = consumed[idx - 1] = True
            found = True
            continue
        if word in ("kuu", "kuul") and prev in _NEXT_ET + _LAST_ET:
            month_offset = 1 if prev in _NEXT_ET else -1
            consumed[idx] = consumed[idx - 1] = True
            found = True
            continue
        if word in ("aasta", "aastal") and prev in _NEXT_ET + _LAST_ET:
            year_offset = 1 if prev in _NEXT_ET else -1
            consumed[idx] = consumed[idx - 1] = True
            found = True
            continue

        if word in _AFTER_MARKERS_ET and idx >= 2:
            unit = words[idx - 1]
            num = _offset_number_et(words[idx - 2])
            if num is not None:
                if unit in _DAY_UNITS_ET:
                    day_offset = (day_offset or 0) + int(num)
                elif unit in _WEEK_UNITS_ET:
                    week_offset += int(num)
                elif unit in _MONTH_UNITS_ET:
                    month_offset += int(num)
                elif unit in _YEAR_UNITS_ET:
                    year_offset += int(num)
                elif unit in _HOUR_UNITS_ET:
                    min_offset += num * 60
                elif unit in _MINUTE_UNITS_ET:
                    min_offset += num
                elif unit in _SECOND_UNITS_ET:
                    sec_offset += num
                else:
                    continue
                consumed[idx] = consumed[idx - 1] = consumed[idx - 2] = True
                found = True
                continue

        if word == "kell":
            if _parse_clock_et(nxt) is not None:
                hr_abs, min_abs = _parse_clock_et(nxt)
                consumed[idx] = consumed[idx + 1] = True
                found = True
                continue
            num = extract_number_et(nxt) if nxt else False
            if num is not False and num is not None and 0 <= num <= 23:
                hr_abs, min_abs = int(num), 0
                consumed[idx] = consumed[idx + 1] = True
                found = True
                continue

        clock = _parse_clock_et(word)
        if clock is not None:
            hr_abs, min_abs = clock
            consumed[idx] = True
            found = True
            continue

        month = _month_from_word_et(word)
        if month is not None:
            day = None
            if prev:
                d = _ordinal_day_et(prev)
                if d is not None:
                    day = d
                    consumed[idx - 1] = True
            if day is None and nxt:
                d = _ordinal_day_et(nxt)
                if d is not None:
                    day = d
                    consumed[idx + 1] = True
            abs_month = month
            abs_day = day if day is not None else 1
            consumed[idx] = True
            found = True
            continue

    if not found:
        return None

    has_date = (abs_month is not None or day_offset is not None or
                week_offset or month_offset or year_offset)

    if not has_date and hr_abs is None and (min_offset or sec_offset):
        # a pure "N tunni/minuti/sekundi pärast" offset is measured from the
        # anchor; a seconds offset keeps the anchor's seconds, mirroring how a
        # minutes offset keeps the anchor's minutes
        base = anchor.replace(microsecond=0)
        if not sec_offset:
            base = base.replace(second=0)
        extracted = base + timedelta(minutes=min_offset, seconds=sec_offset)
        leftover = " ".join(w for i, w in enumerate(words)
                            if not consumed[i] and w != ".")
        return [extracted, " ".join(leftover.split())]

    extracted = anchor.replace(hour=0, minute=0, second=0)

    if abs_month is not None:
        try:
            candidate = extracted.replace(month=abs_month, day=abs_day)
        except ValueError:
            return None
        if candidate.date() < anchor.date():
            candidate = candidate.replace(year=anchor.year + 1)
        extracted = candidate
    else:
        if day_offset is not None:
            extracted = extracted + timedelta(days=day_offset)
        if week_offset:
            extracted = extracted + timedelta(weeks=week_offset)
        if month_offset:
            extracted = _add_months(extracted, month_offset)
        if year_offset:
            try:
                extracted = extracted.replace(year=extracted.year + year_offset)
            except ValueError:
                extracted = extracted.replace(
                    year=extracted.year + year_offset, day=28)

    if hr_abs is None and default_time is not None:
        hr_abs = default_time.hour
        min_abs = default_time.minute
    if hr_abs is not None:
        extracted = extracted.replace(hour=hr_abs, minute=min_abs or 0)
    if min_offset or sec_offset:
        extracted = extracted + timedelta(minutes=min_offset,
                                          seconds=sec_offset)

    leftover = " ".join(w for i, w in enumerate(words)
                        if not consumed[i] and w != ".")
    leftover = " ".join(leftover.split())
    return [extracted, leftover]


def _add_months(dt, months):
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and
                       (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def _parse_clock_et(token):
    if not token:
        return None
    for sep in (":", "."):
        if sep in token:
            parts = token.split(sep)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hour, minute = int(parts[0]), int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return hour, minute
            return None
    return None


def _ordinal_day_et(token):
    stripped = token.rstrip(".")
    if stripped.isdigit():
        val = int(stripped)
        if 1 <= val <= 31:
            return val
    from ovos_number_parser.numbers_et import is_ordinal_et
    val = is_ordinal_et(stripped)
    if val is not False and 1 <= val <= 31:
        return val
    return None
