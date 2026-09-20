"""Date and time tools for Modern Standard Arabic.

Time is told with the feminine ordinal hour names after "الساعة"
(e.g. "الساعة الثالثة" = 3 o'clock) using half-past semantics:
"التاسعة والنصف" = 9:30, "التاسعة إلا ربعاً" = quarter to nine.
Extraction accepts both Western and Eastern Arabic-Indic digits and
tolerates unvocalized spelling variants.

Counted-noun agreement follows Wright, "A Grammar of the Arabic
Language" Vol. I: the dual endings -āni (nominative) / -aini (oblique)
give يومان/يومين = "two days" (§299), and cardinal numerals 3-10 take
the gender opposite the counted noun (§319-§321), so the feminine
nouns ساعة/دقيقة/ثانية take the bare numeral forms ثلاث/أربع/خمس while
the masculine يوم takes ثلاثة/أربعة/خمسة.
"""
import re
from datetime import timedelta

from ovos_number_parser.numbers_ar import (pronounce_number_ar,
                                           _normalize_ar, _tokenize_ar,
                                           _parse_number_span,
                                           _parse_ordinal_span,
                                           _ONES_FEM_AR, _TENS_AR)
from ovos_utils.time import now_local

# feminine cardinals for counting feminine nouns like دقيقة (gender polarity)
_FEM_TEENS_AR = {11: "إحدى عشرة", 12: "اثنتا عشرة"}

# feminine hour names, spoken with the definite article after "الساعة"
_HOUR_NAMES_AR = {1: "الواحدة", 2: "الثانية", 3: "الثالثة", 4: "الرابعة",
                  5: "الخامسة", 6: "السادسة", 7: "السابعة", 8: "الثامنة",
                  9: "التاسعة", 10: "العاشرة", 11: "الحادية عشرة",
                  12: "الثانية عشرة"}

# duration units; the dual forms encode both the count and the unit
_UNIT_SECONDS_AR = {
    "ثانية": 1, "ثوان": 1, "ثواني": 1,
    "دقيقة": 60, "دقائق": 60,
    "ساعة": 3600, "ساعات": 3600,
    "يوم": 86400, "أيام": 86400,
    "أسبوع": 604800, "أسابيع": 604800,
    "شهر": 2592000, "أشهر": 2592000, "شهور": 2592000,
    "سنة": 31536000, "سنوات": 31536000, "سنين": 31536000,
    "عام": 31536000, "أعوام": 31536000,
}
_DUAL_UNIT_SECONDS_AR = {
    "ثانيتان": 1, "ثانيتين": 1,
    "دقيقتان": 60, "دقيقتين": 60,
    "ساعتان": 3600, "ساعتين": 3600,
    "يومان": 86400, "يومين": 86400,
    "أسبوعان": 604800, "أسبوعين": 604800,
    "شهران": 2592000, "شهرين": 2592000,
    "سنتان": 31536000, "سنتين": 31536000,
    "عامان": 31536000, "عامين": 31536000,
}

_UNITS_LOOKUP_AR = {_normalize_ar(k): v for k, v in _UNIT_SECONDS_AR.items()}
_DUALS_LOOKUP_AR = {_normalize_ar(k): v
                    for k, v in _DUAL_UNIT_SECONDS_AR.items()}

_MONTHS_AR = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو",
              6: "يونيو", 7: "يوليو", 8: "أغسطس", 9: "سبتمبر",
              10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}
# python weekday(): 0 = Monday
_WEEKDAYS_AR = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس",
                4: "الجمعة", 5: "السبت", 6: "الأحد"}

_MONTHS_LOOKUP_AR = {_normalize_ar(v): k for k, v in _MONTHS_AR.items()}
_MONTHS_LOOKUP_AR[_normalize_ar("اثنين")] = None  # guard, see weekdays
del _MONTHS_LOOKUP_AR[_normalize_ar("اثنين")]
_WEEKDAYS_LOOKUP_AR = {}
for _i, _w in _WEEKDAYS_AR.items():
    _name = _normalize_ar(_w)  # e.g. "الجمعه" (article + bare noun)
    _bare = _name[2:]  # drop the "ال" article -> "جمعه"
    _WEEKDAYS_LOOKUP_AR[_name] = _i
    _WEEKDAYS_LOOKUP_AR[_bare] = _i  # without the article
    # ب/ل proclitics fused onto the article: "بالجمعة" (on Friday),
    # "للجمعة" (for/until Friday). With ل the article's alif elides
    # (li + al -> lil), so build it from the bare noun.
    _WEEKDAYS_LOOKUP_AR["ب" + _name] = _i
    _WEEKDAYS_LOOKUP_AR["لل" + _bare] = _i

_HOUR_LOOKUP_AR = {}
for _n, _name in _HOUR_NAMES_AR.items():
    if _n <= 10:
        _HOUR_LOOKUP_AR[_normalize_ar(_name)] = _n

_MINUTE_WORDS_AR = {_normalize_ar(w) for w in
                    ("دقيقة", "دقائق", "دقيقتان", "دقيقتين")}


def _fem_cardinal_ar(number):
    """1-99 in the feminine forms used for counting feminine nouns."""
    if number <= 10:
        return _ONES_FEM_AR[number]
    if number in _FEM_TEENS_AR:
        return _FEM_TEENS_AR[number]
    if number < 20:
        return _ONES_FEM_AR[number - 10] + " عشرة"
    tens, unit = divmod(number, 10)
    if unit == 0:
        return _TENS_AR[tens * 10]
    return _ONES_FEM_AR[unit] + " و" + _TENS_AR[tens * 10]


def _nice_minutes_ar(minutes):
    """Minutes with the gender-polarity agreement of دقيقة (feminine)."""
    if minutes == 1:
        return "دقيقة"
    if minutes == 2:
        return "دقيقتان"
    if minutes <= 10:
        return _fem_cardinal_ar(minutes) + " دقائق"
    return _fem_cardinal_ar(minutes) + " دقيقة"


def nice_time_ar(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format in Modern Standard Arabic.

    Uses the feminine hour names after "الساعة" with half-past semantics:
    9:30 is "الساعة التاسعة والنصف", 8:45 is "الساعة التاسعة إلا ربعاً".

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
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
        if string[0] == '0':
            string = string[1:]  # strip leading zeros

    if not speech:
        return string

    if use_24hour:
        speak = pronounce_number_ar(dt.hour)
        if dt.minute:
            speak += " و" + _nice_minutes_ar(dt.minute)
        return speak

    if dt.hour == 0 and dt.minute == 0:
        return "منتصف الليل"
    if dt.hour == 12 and dt.minute == 0:
        return "الظهر"

    hour = dt.hour % 12 or 12
    if dt.minute == 45:
        next_hour = (dt.hour + 1) % 12 or 12
        speak = "الساعة " + _HOUR_NAMES_AR[next_hour] + " إلا ربعاً"
    else:
        speak = "الساعة " + _HOUR_NAMES_AR[hour]
        if dt.minute == 15:
            speak += " والربع"
        elif dt.minute == 20:
            speak += " والثلث"
        elif dt.minute == 30:
            speak += " والنصف"
        elif dt.minute:
            speak += " و" + _nice_minutes_ar(dt.minute)

    if use_ampm:
        speak += " مساءً" if dt.hour >= 12 else " صباحاً"
    return speak


def _count_unit_ar(count, singular, dual, plural, feminine):
    """A counted noun with Arabic number agreement.

    1 and 2 use the bare singular/dual, 3-10 take the plural with the
    polarity-opposed numeral, 11+ take the singular. The reverse gender
    polarity of 3-10 follows Wright, "A Grammar of the Arabic Language"
    Vol. I §319: the numeral takes the gender opposite the counted noun."""
    if count == 1:
        return singular
    if count == 2:
        return dual
    number = _fem_cardinal_ar(count) if feminine \
        else pronounce_number_ar(count)
    if 3 <= count <= 10:
        return f"{number} {plural}"
    return f"{number} {singular}"


def nice_duration_ar(duration, speech=True):
    """Convert duration in seconds to a nice spoken timespan in Arabic.

    Examples:
       duration = 60  ->  "1:00" or "دقيقة"
       duration = 163  ->  "2:43" or "دقيقتان وثلاث وأربعون ثانية"

    Args:
        duration: time, in seconds, or a timedelta
        speech (bool): format for speech (True) or display (False)

    Returns:
        str: timespan as a string
    """
    if isinstance(duration, timedelta):
        duration = duration.total_seconds()
    duration += 0.5  # traditional rounding

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    if not speech:
        out = ""
        if days > 0:
            out = str(days) + "d "
        if hours > 0 or days > 0:
            out += str(hours) + ":"
        if minutes < 10 and (hours > 0 or days > 0):
            out += "0"
        out += str(minutes) + ":"
        if seconds < 10:
            out += "0"
        out += str(seconds)
        return out

    parts = []
    if days > 0:
        parts.append(_count_unit_ar(days, "يوم", "يومان", "أيام", False))
    if hours > 0:
        parts.append(_count_unit_ar(hours, "ساعة", "ساعتان", "ساعات", True))
    if minutes > 0:
        parts.append(_count_unit_ar(minutes, "دقيقة", "دقيقتان", "دقائق",
                                    True))
    if seconds > 0:
        # 3-10 seconds use the broken plural ثوان with a feminine numeral
        if seconds == 1:
            parts.append("ثانية")
        elif seconds == 2:
            parts.append("ثانيتان")
        elif seconds <= 10:
            parts.append(f"{_fem_cardinal_ar(seconds)} ثوان")
        else:
            parts.append(f"{_fem_cardinal_ar(seconds)} ثانية")
    return " و".join(parts)


def extract_duration_ar(text):
    """
    Convert an Arabic phrase into a number of seconds.

    Convert things like "عشر دقائق" (10 minutes), "ساعتان" (2 hours) or
    "ثلاثة أيام وخمس ساعات" into a timedelta. The words used in the
    duration are consumed and the remainder returned.

    Args:
        text (str): string containing a duration

    Returns:
        (timedelta, str):
                    A tuple containing the duration and the remaining text
                    not consumed in the parsing. The first value will
                    be None if no duration is found.
    """
    if not text:
        return None, text
    tokens = _tokenize_ar(text)
    total = timedelta(0)
    found = False
    remainder = []
    last_unit = None
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "و" and i + 1 < n and (
                tokens[i + 1] in _UNITS_LOOKUP_AR or
                tokens[i + 1] in _DUALS_LOOKUP_AR or
                _parse_number_span(tokens, i + 1)[0] is not None):
            i += 1
            continue
        if tok in _DUALS_LOOKUP_AR:
            total += timedelta(seconds=2 * _DUALS_LOOKUP_AR[tok])
            last_unit = _DUALS_LOOKUP_AR[tok]
            found = True
            i += 1
            continue
        if tok in _UNITS_LOOKUP_AR:
            # bare unit means one: "ساعة" = 1 hour
            total += timedelta(seconds=_UNITS_LOOKUP_AR[tok])
            last_unit = _UNITS_LOOKUP_AR[tok]
            found = True
            i += 1
            continue
        value, j = _parse_number_span(tokens, i)
        if value is not None:
            if j < n and tokens[j] in _UNITS_LOOKUP_AR:
                total += timedelta(seconds=value * _UNITS_LOOKUP_AR[tokens[j]])
                last_unit = _UNITS_LOOKUP_AR[tokens[j]]
                found = True
                i = j + 1
                continue
            if found and last_unit and 0 < value < 1 and j == i + 1:
                # trailing fraction of the last unit: "ساعة ونصف" = 1.5h
                total += timedelta(seconds=value * last_unit)
                i = j
                continue
        remainder.append(tok)
        last_unit = None
        i += 1
    if not found:
        return None, text
    return total, " ".join(remainder)


_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')

_TODAY_WORDS = {_normalize_ar("اليوم")}
_TOMORROW_WORDS = {_normalize_ar("غدا"), _normalize_ar("غد"),
                   _normalize_ar("الغد")}
_YESTERDAY_WORDS = {_normalize_ar("أمس"), _normalize_ar("البارحة")}
_AM_WORDS = {_normalize_ar("صباحا"), _normalize_ar("الصباح"),
             _normalize_ar("فجرا")}
_PM_WORDS = {_normalize_ar("مساء"), _normalize_ar("المساء"),
             _normalize_ar("عصرا"), _normalize_ar("العصر"),
             _normalize_ar("ليلا"), _normalize_ar("الليلة"),
             _normalize_ar("بعدالظهر")}
_NOON_WORDS = {_normalize_ar("ظهرا"), _normalize_ar("الظهر")}
_MIDNIGHT_WORD = _normalize_ar("منتصفالليل")
_NEXT_WORDS = {_normalize_ar("القادم"), _normalize_ar("القادمة"),
               _normalize_ar("المقبل"), _normalize_ar("المقبلة")}
_PREV_WORDS = {_normalize_ar("الماضي"), _normalize_ar("الماضية")}
# forward-looking relatives: بعد (after), خلال (within/during),
# غضون (the noun in "في غضون" = within); all place the offset in the future
_AFTER_WORDS = {_normalize_ar("بعد"), _normalize_ar("خلال"),
                _normalize_ar("غضون")}
_BEFORE_WORDS = {_normalize_ar("قبل"), _normalize_ar("منذ")}
_CLOCK_WORDS = {_normalize_ar("الساعة"), _normalize_ar("ساعة")}
_CALENDAR_UNITS = {
    _normalize_ar("الأسبوع"): timedelta(weeks=1),
    _normalize_ar("الشهر"): timedelta(days=30),
    _normalize_ar("السنة"): timedelta(days=365),
    _normalize_ar("العام"): timedelta(days=365),
}
_EXCEPT_WORD = _normalize_ar("إلا")
_QUARTER_WORDS = {_normalize_ar("ربع"), _normalize_ar("ربعا"),
                  _normalize_ar("الربع")}
_THIRD_WORDS = {_normalize_ar("ثلث"), _normalize_ar("ثلثا"),
                _normalize_ar("الثلث")}
_HALF_WORDS = {_normalize_ar("نصف"), _normalize_ar("النصف")}
_DAY_WORD = _normalize_ar("يوم")
_OF_WORD = _normalize_ar("من")
_IN_WORD = _normalize_ar("في")


def extract_datetime_ar(text, anchorDate=None, default_time=None):
    """Convert a human date reference in Arabic into an exact datetime.

    Handles relative days (اليوم, غداً, أمس, بعد غد), weekdays (including
    the ب/ل proclitics بالجمعة/للجمعة), Gregorian month names, relative
    offsets and clock times ("الساعة التاسعة والنصف مساءً", "5:30").

    Forward-looking markers بعد / خلال / في غضون ("after" / "within")
    place the offset in the future; قبل / منذ ("before" / "since") place
    it in the past. Dual offsets use the -āni/-aini forms يومين/ساعتين
    = "two days"/"two hours" (Wright, "A Grammar of the Arabic Language"
    Vol. I §299).

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "tomorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: The datetime and the remaining text not consumed,
                         or None if no date or time related text was found.
    """
    if not text:
        return None
    normalized = _normalize_ar(text)
    # fuse "بعد غد" (day after tomorrow) so بعد is not read as "in ..."
    normalized = normalized.replace("بعد غد", "بعدغد") \
        .replace("اول امس", "اولامس").replace("امس الاول", "اولامس") \
        .replace("منتصف الليل", "منتصفالليل") \
        .replace("بعد الظهر", "بعدالظهر") \
        .replace("في غضون", "غضون")  # "within" -> single forward marker
    tokens = _tokenize_ar(normalized)

    if not anchorDate:
        anchorDate = now_local()
    today = anchorDate.replace(hour=0, minute=0, second=0, microsecond=0)

    date_found = False
    result_date = None
    hour = None
    minute = 0
    ampm = None  # "am", "pm" or None
    noon_seen = False
    delta = timedelta(0)
    delta_sign = 0  # +1 for بعد, -1 for قبل/منذ
    delta_is_time = False
    remainder = []

    day_after = _normalize_ar("بعدغد")
    day_before = _normalize_ar("اولامس")

    def parse_clock(i):
        """Parse a clock expression at tokens[i]; returns next index."""
        nonlocal hour, minute, date_found
        n = len(tokens)
        if i >= n:
            return i
        tok = tokens[i]
        # digit times handled by the main loop
        matched = None
        if i + 1 < n and (tok + " " + tokens[i + 1]) in (
                _normalize_ar("الحادية عشرة"), _normalize_ar("الثانية عشرة")):
            matched = 11 if tok == _normalize_ar("الحادية") else 12
            i += 2
        elif tok in _HOUR_LOOKUP_AR:
            # "الثانية عشرة" starts like "الثانية"; checked above
            matched = _HOUR_LOOKUP_AR[tok]
            i += 1
        if matched is None:
            return i
        hour = matched
        minute = 0
        date_found = True
        # minute modifiers
        if i < n and tokens[i] == "و" and i + 1 < n:
            nxt = tokens[i + 1]
            if nxt in _HALF_WORDS:
                minute = 30
                i += 2
            elif nxt in _QUARTER_WORDS:
                minute = 15
                i += 2
            elif nxt in _THIRD_WORDS:
                minute = 20
                i += 2
            else:
                value, j = _parse_number_span(tokens, i + 1)
                if value is not None and j < n and \
                        tokens[j] in _MINUTE_WORDS_AR and 0 < value < 60:
                    minute = int(value)
                    i = j + 1
                elif nxt in _MINUTE_WORDS_AR and nxt in _DUALS_LOOKUP_AR:
                    minute = 2  # "ودقيقتان" = two minutes past
                    i += 2
        if i < n and tokens[i] == _EXCEPT_WORD and i + 1 < n:
            if tokens[i + 1] in _QUARTER_WORDS:
                hour -= 1
                minute = 45
                i += 2
            elif tokens[i + 1] in _THIRD_WORDS:
                hour -= 1
                minute = 40
                i += 2
            else:
                # "إلا خمس (دقائق)" = a count of minutes to the hour
                value, j = _parse_number_span(tokens, i + 1)
                if value is not None and 0 < value < 60 \
                        and float(value).is_integer():
                    if j < n and tokens[j] in _MINUTE_WORDS_AR:
                        j += 1
                    hour -= 1
                    minute = 60 - int(value)
                    i = j
            if hour == 0:
                hour = 12
        return i

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        m = _HHMM_RE.match(tok)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h < 24 and 0 <= mi < 60:
                hour, minute = h, mi
                ampm = ampm or ("h24" if h > 12 or h == 0 else None)
                date_found = True
                i += 1
                continue
        if tok in _TODAY_WORDS:
            result_date = today
            date_found = True
            i += 1
            continue
        if tok == day_after:
            result_date = today + timedelta(days=2)
            date_found = True
            i += 1
            continue
        if tok in _TOMORROW_WORDS:
            result_date = today + timedelta(days=1)
            date_found = True
            i += 1
            continue
        if tok == day_before:
            result_date = today - timedelta(days=2)
            date_found = True
            i += 1
            continue
        if tok in _YESTERDAY_WORDS:
            result_date = today - timedelta(days=1)
            date_found = True
            i += 1
            continue
        if tok == _DAY_WORD and i + 1 < n and \
                tokens[i + 1] in _WEEKDAYS_LOOKUP_AR:
            i += 1
            continue
        if tok in _WEEKDAYS_LOOKUP_AR:
            target = _WEEKDAYS_LOOKUP_AR[tok]
            offset = (target - today.weekday()) % 7
            if i + 1 < n and tokens[i + 1] in _NEXT_WORDS:
                if offset == 0:
                    offset = 7
                i += 1
            elif i + 1 < n and tokens[i + 1] in _PREV_WORDS:
                offset = offset - 7 if offset else -7
                i += 1
            result_date = today + timedelta(days=offset)
            date_found = True
            i += 1
            continue
        if tok in _MONTHS_LOOKUP_AR:
            month = _MONTHS_LOOKUP_AR[tok]
            day = 1
            # look back for a day number: "5 يناير" / "الخامس من يناير"
            back = len(remainder) - 1
            if back >= 0 and remainder[back] == _OF_WORD:
                back -= 1
            if back >= 0:
                val, j = _parse_number_span(remainder, back)
                if val is not None and j == back + 1 and 1 <= val <= 31 \
                        and float(val).is_integer():
                    day = int(val)
                    del remainder[back:]
                else:
                    # ordinal day: "الخامس من يناير", "الحادي والعشرين من.."
                    for start in range(max(0, back - 2), back + 1):
                        val, j = _parse_ordinal_span(remainder, start)
                        if val is not None and j == back + 1 \
                                and 1 <= val <= 31:
                            day = int(val)
                            del remainder[start:]
                            break
            year = today.year
            i += 1
            # a following number is the year: "يناير 2030"
            if i < n:
                val, j = _parse_number_span(tokens, i)
                if val is not None and 1000 <= val <= 9999 and \
                        float(val).is_integer():
                    year = int(val)
                    i = j
            try:
                result_date = today.replace(year=year, month=month, day=day)
            except ValueError:
                # impossible calendar date like "31 فبراير"; ignore it
                continue
            date_found = True
            continue
        if tok in _CALENDAR_UNITS and i + 1 < n and \
                tokens[i + 1] in (_NEXT_WORDS | _PREV_WORDS):
            sign = 1 if tokens[i + 1] in _NEXT_WORDS else -1
            result_date = (result_date or today) + sign * _CALENDAR_UNITS[tok]
            date_found = True
            i += 2
            continue
        if tok in _AFTER_WORDS or tok in _BEFORE_WORDS:
            sign = 1 if tok in _AFTER_WORDS else -1
            duration, j = _parse_duration_span(tokens, i + 1)
            if duration is not None:
                delta += sign * duration[0]
                delta_sign = sign
                delta_is_time = duration[1]
                date_found = True
                i = j
                continue
            remainder.append(tok)
            i += 1
            continue
        if tok in _HOUR_LOOKUP_AR or (
                tok in (_normalize_ar("الحادية"), _normalize_ar("الثانية"))
                and i + 1 < n and tokens[i + 1] in
                (_normalize_ar("عشرة"), _normalize_ar("عشره"))):
            # bare feminine hour name: "التاسعة إلا ربعاً"
            j = parse_clock(i)
            if j > i:
                i = j
                continue
        if tok in _CLOCK_WORDS:
            j = parse_clock(i + 1)
            if j > i + 1:
                i = j
                continue
            # "الساعة 5" or "الساعة 5:30"
            if i + 1 < n:
                m = _HHMM_RE.match(tokens[i + 1])
                if m and not (0 <= int(m.group(1)) < 24 and
                              0 <= int(m.group(2)) < 60):
                    m = None  # out-of-range clock like "5:70"; not a time
                val = None
                if not m:
                    val, jj = _parse_number_span(tokens, i + 1)
                if m or (val is not None and 0 <= val <= 24 and
                         float(val).is_integer()):
                    if m:
                        hour, minute = int(m.group(1)), int(m.group(2))
                        i += 2
                    else:
                        hour, minute = int(val), 0
                        i = jj
                    date_found = True
                    continue
            remainder.append(tok)
            i += 1
            continue
        if tok == _MIDNIGHT_WORD:
            hour, minute = 0, 0
            date_found = True
            i += 1
            continue
        if tok in _NOON_WORDS:
            ampm = "pm"
            noon_seen = True
            if hour is not None or result_date is not None:
                date_found = True
            i += 1
            continue
        if tok in _AM_WORDS:
            ampm = "am"
            if hour is not None or result_date is not None:
                date_found = True
            i += 1
            continue
        if tok in _PM_WORDS:
            ampm = "pm"
            if hour is not None or result_date is not None:
                date_found = True
            i += 1
            continue
        if tok == "و" and (hour is not None or delta_sign):
            i += 1
            continue
        if tok == _IN_WORD and i + 1 < n and (
                tokens[i + 1] in _CLOCK_WORDS or
                tokens[i + 1] in _MONTHS_LOOKUP_AR):
            i += 1
            continue
        if delta_sign and (tok in _UNITS_LOOKUP_AR or
                           tok in _DUALS_LOOKUP_AR or
                           _parse_number_span(tokens, i)[0] is not None):
            duration, j = _parse_duration_span(tokens, i)
            if duration is not None:
                delta += delta_sign * duration[0]
                delta_is_time = delta_is_time or duration[1]
                i = j
                continue
        remainder.append(tok)
        i += 1

    if hour is None and noon_seen:
        # a bare "الظهر"/"ظهراً" means noon itself
        hour, minute = 12, 0
        date_found = True

    if not date_found:
        return None

    if delta:
        base = anchorDate if delta_is_time else today
        result_date = (result_date or base) + delta

    if result_date is None:
        result_date = today

    if hour is not None:
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        result_date = result_date.replace(hour=hour % 24, minute=minute,
                                          second=0, microsecond=0)
    elif default_time:
        result_date = result_date.replace(hour=default_time.hour,
                                          minute=default_time.minute,
                                          second=default_time.second)

    return [result_date, " ".join(remainder).strip()]


def _parse_duration_span(tokens, i):
    """Parse "<number> <unit>" (or dual/bare unit) at tokens[i].

    Returns ((timedelta, is_time_unit), next_index) or (None, i)."""
    n = len(tokens)
    if i >= n:
        return None, i
    tok = tokens[i]
    if tok in _DUALS_LOOKUP_AR:
        unit = _DUALS_LOOKUP_AR[tok]
        secs, k = 2 * unit, i + 1
    elif tok in _UNITS_LOOKUP_AR:
        unit = _UNITS_LOOKUP_AR[tok]
        secs, k = unit, i + 1
    else:
        value, j = _parse_number_span(tokens, i)
        if value is None or j >= n or tokens[j] not in _UNITS_LOOKUP_AR:
            return None, i
        unit = _UNITS_LOOKUP_AR[tokens[j]]
        secs, k = value * unit, j + 1
    # trailing fraction of the unit: "ساعة ونصف", "ساعتين وربع"
    if k + 1 < n and tokens[k] == "و":
        frac, jf = _parse_number_span(tokens, k + 1)
        if frac is not None and 0 < frac < 1:
            secs += frac * unit
            k = jf
    return (timedelta(seconds=secs), unit < 86400), k
