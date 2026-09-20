# Copyright OpenVoiceOS
"""Hebrew date and time formatting and extraction.

Grammatical gender scope
------------------------
Hebrew cardinal numerals are gendered. This module fixes one consistent
convention per grammatical context:

* Years and day-of-month counts are rendered with masculine cardinals,
  the form produced by ``pronounce_number_he``. This matches how a
  numeric year or calendar day is read aloud.
* Clock hours and whole-minute counts are rendered with feminine
  cardinals, because the counted noun "שעה" (hour) is feminine and
  Hebrew tells the time in the feminine. A small feminine numeral table
  (0-59) is built from the standard cardinal paradigm for this purpose.

Time-telling register
---------------------
Modern Hebrew tells the clock one way: feminine hour cardinals with the
half/quarter idioms (שלוש וחצי, רבע לארבע). There is no second colloquial
register comparable to Catalan "quarts", so no register parameter is
offered; ``nice_time_he`` keeps this single sensible default.

Extraction scope
----------------
``extract_datetime_he`` recognises relative day words, weekday names
(with or without a ב/ל proclitic), "in N <unit>" / "N <unit> ago"
offsets in both masculine and feminine spoken forms (routed through the
number normaliser), the dual nouns יומיים/שבועיים/חודשיים/שנתיים/שעתיים,
relative hour/minute/second offsets (בעוד N שעות/דקות) including "וחצי"
/"ורבע" fractions of an hour, explicit "N of <month> [year]" dates (a
month with a year but no day resolves to the first of the month), and
clock times given as ``HH:MM``, "בשעה N", or "רבע ל<hour>". A part-of-day
word (בבוקר/אחר הצהריים/בערב/בלילה) shifts a spoken or absolute hour into
the right half of the day. Spoken minute compounds beyond half and
quarter are out of scope: an unrecognised time is left in the returned
remainder rather than guessed at.
"""
import re
from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser import numbers_to_digits
from ovos_number_parser.numbers_he import pronounce_number_he
from ovos_utils.time import now_local

from ovos_date_parser.duration import (
    register_duration_lexicon, DurationLexicon, DurationResolution,
    DURATION_LEXICONS, extract_duration_generic
)

# Python weekday(): 0=Monday .. 6=Sunday
WEEKDAYS_HE = {
    0: "יום שני",
    1: "יום שלישי",
    2: "יום רביעי",
    3: "יום חמישי",
    4: "יום שישי",
    5: "שבת",
    6: "יום ראשון",
}
MONTHS_HE = {
    1: "ינואר",
    2: "פברואר",
    3: "מרץ",
    4: "אפריל",
    5: "מאי",
    6: "יוני",
    7: "יולי",
    8: "אוגוסט",
    9: "ספטמבר",
    10: "אוקטובר",
    11: "נובמבר",
    12: "דצמבר",
}

# feminine cardinal paradigm, used for clock counting
_FEM_ONES = {
    0: "אפס",
    1: "אחת",
    2: "שתיים",
    3: "שלוש",
    4: "ארבע",
    5: "חמש",
    6: "שש",
    7: "שבע",
    8: "שמונה",
    9: "תשע",
    10: "עשר",
}
_FEM_TEEN = {
    11: "אחת עשרה",
    12: "שתים עשרה",
    13: "שלוש עשרה",
    14: "ארבע עשרה",
    15: "חמש עשרה",
    16: "שש עשרה",
    17: "שבע עשרה",
    18: "שמונה עשרה",
    19: "תשע עשרה",
}
# tens are gender neutral in Hebrew
_TENS = {
    20: "עשרים",
    30: "שלושים",
    40: "ארבעים",
    50: "חמישים",
}


def _feminine_number_he(n):
    """Feminine cardinal for 0-59, used to count hours and minutes."""
    if n < 0 or n > 59:
        raise ValueError("feminine clock numeral out of range")
    if n <= 10:
        return _FEM_ONES[n]
    if n < 20:
        return _FEM_TEEN[n]
    tens = (n // 10) * 10
    unit = n % 10
    if unit == 0:
        return _TENS[tens]
    return _TENS[tens] + " ו" + _FEM_ONES[unit]


def nice_year_he(dt, bc=False):
    """Format a year as spoken Hebrew (masculine cardinals).

    Produces e.g. 'אלף תשע מאות שמונים וארבעה' for 1984.

    Args:
        dt (datetime): date to format (assumed already in local time)
        bc (bool): append the "before common era" marker
    Returns:
        (str): the formatted year
    """
    # Hebrew date fields keep the masculine forms this formatter has always
    # produced; the number parser now defaults to the feminine abstract
    # counting form, so the gender is requested explicitly here. Whether a
    # year (שנה, feminine) or day-of-month should instead be feminine is a
    # separate Hebrew-dates question, deliberately not changed here.
    year = pronounce_number_he(dt.year, feminine=False)
    if bc:
        return f"{year} לפני הספירה"
    return year


def nice_weekday_he(dt):
    return WEEKDAYS_HE[dt.weekday()]


def nice_month_he(dt):
    return MONTHS_HE[dt.month]


def nice_day_he(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_he(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_he(dt: datetime, now: datetime = None, include_weekday=True):
    """Format a date as spoken Hebrew.

    Produces e.g. 'יום שלישי, חמישה ביוני 2018'.

    Args:
        dt (datetime): date to format (assumed already in local time)
        now (datetime): reference date. When given, the result is
            shortened: the year is dropped when it matches ``now``, the
            month is dropped when it matches ``now``, and same-day dates
            return 'היום' / 'מחר' / 'אתמול'.
        include_weekday (bool): prepend the weekday name.
    Returns:
        (str): the formatted date
    """
    day = pronounce_number_he(dt.day, feminine=False)
    if now is not None:
        if dt.year == now.year and dt.month == now.month:
            if dt.day == now.day:
                return "היום"
            if dt.day == now.day + 1:
                return "מחר"
            if dt.day == now.day - 1:
                return "אתמול"
        nice = day
        if dt.month != now.month or dt.year != now.year:
            nice = nice + " ב" + nice_month_he(dt)
        if dt.year != now.year:
            nice = nice + " " + nice_year_he(dt)
    else:
        nice = f"{day} ב{nice_month_he(dt)} {nice_year_he(dt)}"

    if include_weekday:
        nice = f"{nice_weekday_he(dt)}, {nice}"
    return nice


def nice_date_time_he(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time as spoken Hebrew.

    Produces e.g. 'יום שלישי, חמישה ביוני 2018 בשעה חמש וחצי'.
    """
    now = now or now_local()
    date_str = nice_date_he(dt, now)
    time_str = nice_time_he(dt, use_24hour=use_24hour, use_ampm=use_ampm)
    return f"{date_str} בשעה {time_str}"


def nice_time_he(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a human friendly way.

    Produces e.g. 'שלוש וחצי' for speech or '3:30' for display.

    Args:
        dt (datetime): date to format (assumed already in local time)
        speech (bool): spoken form (True) or display form (False)
        use_24hour (bool): 24 hour output instead of 12 hour
        use_ampm (bool): add a part-of-day marker in 12 hour output
    Returns:
        (str): the formatted time
    """
    if use_24hour:
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            string = dt.strftime("%I:%M %p")
        else:
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]

    if not speech:
        return string

    if use_24hour:
        speak = _feminine_number_he(dt.hour)
        if dt.minute > 0:
            if dt.minute < 10:
                speak += " אפס " + _feminine_number_he(dt.minute)
            else:
                speak += " " + _feminine_number_he(dt.minute)
        return speak

    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    speak = _feminine_number_he(hour)

    minute = dt.minute
    if minute == 15:
        speak += " ורבע"
    elif minute == 30:
        speak += " וחצי"
    elif minute == 45:
        nxt = (hour % 12) + 1
        speak = "רבע ל" + _feminine_number_he(nxt)
    elif minute != 0:
        speak += " ו" + _feminine_number_he(minute)

    if use_ampm:
        if dt.hour < 5:
            speak += " בלילה"
        elif dt.hour < 12:
            speak += " בבוקר"
        elif dt.hour < 18:
            speak += " אחר הצהריים"
        else:
            speak += " בערב"
    return speak


# weekday ordinal words, ordered Sunday..Saturday to match strftime("%w")
_WEEKDAY_WORDS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
_MONTH_WORDS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
                "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
_EN_MONTHS = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november",
              "december"]
# dual-number nouns ("two X"), a single word carrying its own count of two
_DUALS = {
    "יומיים": "day",
    "שבועיים": "week",
    "חודשיים": "month",
    "שנתיים": "year",
    "שעתיים": "hour",
}


def extract_datetime_he(text, anchorDate=None, default_time=None):
    """Extract date and time information from a Hebrew phrase.

    Args:
        text (str): text to interpret
        anchorDate (datetime): reference date for relative expressions
        default_time (time): time to use when none is found in the text

    Returns:
        [datetime, str] | None: the extracted date and the remaining
        text, or None when no date or time is found.
    """
    if not text:
        return None
    if anchorDate is None:
        anchorDate = now_local()

    def clean_string(s):
        for ch in [".", ",", ";", "?", "!"]:
            s = s.replace(ch, " ")
        # keep the two-word weekday phrases together so the number
        # normaliser does not read "שני" as the numeral two, etc.; a
        # leading ב/ל proclitic ("ביום שלישי", "ליום חמישי") is folded in
        for w in _WEEKDAY_WORDS[:-1]:
            s = re.sub(r"\b[בל]?יום " + w + r"\b", "יום_" + w, s)
        # Saturday carries no "יום" prefix; strip a ב/ל proclitic
        s = re.sub(r"\b[בל]?שבת\b", "שבת", s)
        # shield half/quarter as whole words from the number normaliser
        s = re.sub(r"\bוחצי\b", " @half", s)
        s = re.sub(r"\bחצי\b", "@half", s)
        s = re.sub(r"\bורבע\b", " @quarter", s)
        s = re.sub(r"\bרבע\b", "@quarter", s)
        # "רבע ל<hour>" (quarter to) — mark it and detach the ל proclitic
        # so the hour word normalises to a digit
        s = re.sub(r"@quarter ל", "@quarterto ", s)
        # a ב/ל proclitic on a digit token ("ב15", "ל20")
        s = re.sub(r"\b[בל](?=\d)", "", s)
        s = numbers_to_digits(s, "he")
        return s

    def date_found():
        return found or datestr != "" or \
            yearOffset != 0 or monthOffset != 0 or \
            dayOffset is not False or hrAbs is not None or \
            minAbs is not None or hrOffset != 0 or \
            minOffset != 0 or secOffset != 0

    dateNow = anchorDate
    today_w = dateNow.strftime("%w")
    currentYear = dateNow.year

    found = False
    daySpecified = False
    dayOffset = False
    monthOffset = 0
    yearOffset = 0
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None
    datestr = ""
    hasYear = False

    words = [w for w in clean_string(text).split(" ") if w != ""]

    nexts = ["הבא", "הבאה"]
    lasts = ["שעבר", "הקודם", "הקודמת", "האחרון", "האחרונה"]

    def is_digit(w):
        return w != "" and (w[0].isdigit() or
                            (w[0] == "-" and len(w) > 1 and w[1].isdigit()))

    idx = 0
    while idx < len(words):
        word = words[idx]
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        used = 0
        start = idx

        if word == "היום":
            dayOffset = 0
            used = 1
        elif word == "מחר":
            dayOffset = 1
            used = 1
        elif word == "מחרתיים":
            dayOffset = 2
            used = 1
        elif word == "אתמול":
            dayOffset = -1
            used = 1
        elif word == "שלשום":
            dayOffset = -2
            used = 1
        # weekday: יום_ראשון .. or שבת
        elif word.startswith("יום_") or word == "שבת":
            wd = "שבת" if word == "שבת" else word.split("_", 1)[1]
            d = _WEEKDAY_WORDS.index(wd)
            offset = (d) - int(today_w)
            if offset < 0:
                offset += 7
            used = 1
            # the bare weekday already resolves to its next occurrence;
            # "הבא" only confirms it, while "שעבר" moves a week back
            if wordNext in nexts:
                used += 1
            elif wordNext in lasts:
                offset -= 7
                used += 1
            dayOffset = offset
        # relative offsets: בעוד N ימים / לפני N ימים / N ימים
        elif word in ("יום", "ימים") and is_digit(wordPrev):
            n = int(wordPrev)
            sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
            dayOffset = (dayOffset if dayOffset else 0) + sign * n
            start = idx - 1
            used = 2
        elif word in ("שבוע", "שבועות"):
            if is_digit(wordPrev):
                n = int(wordPrev)
                sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
                dayOffset = (dayOffset if dayOffset else 0) + sign * n * 7
                start = idx - 1
                used = 2
            elif wordNext in nexts:
                dayOffset = 7
                used = 2
            elif wordNext in lasts:
                dayOffset = -7
                used = 2
        elif word in ("חודש", "חודשים"):
            if is_digit(wordPrev):
                n = int(wordPrev)
                sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
                monthOffset = sign * n
                start = idx - 1
                used = 2
            elif wordNext in nexts:
                monthOffset = 1
                used = 2
            elif wordNext in lasts:
                monthOffset = -1
                used = 2
        elif word in ("שנה", "שנים", "שנת"):
            if is_digit(wordPrev):
                n = int(wordPrev)
                sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
                yearOffset = sign * n
                start = idx - 1
                used = 2
            elif wordNext in nexts:
                yearOffset = 1
                used = 2
            elif wordNext in lasts:
                yearOffset = -1
                used = 2
        # dual forms ("two X"): single words, negated by a preceding "לפני"
        elif word in _DUALS:
            kind = _DUALS[word]
            sign = -1 if wordPrev == "לפני" else 1
            if kind == "day":
                dayOffset = (dayOffset if dayOffset else 0) + sign * 2
            elif kind == "week":
                dayOffset = (dayOffset if dayOffset else 0) + sign * 14
            elif kind == "month":
                monthOffset = sign * 2
            elif kind == "year":
                yearOffset = sign * 2
            elif kind == "hour":
                hrOffset = sign * 2
            used = 1
            if kind == "hour" and wordNext in ("@half", "@quarter"):
                minOffset += sign * (30 if wordNext == "@half" else 15)
                used += 1
        # relative clock offsets: "בעוד N שעות/דקות/שניות"
        elif word in ("שעה", "שעות"):
            sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
            matched = True
            if is_digit(wordPrev):
                hrOffset = sign * int(wordPrev)
                start = idx - 1
                used = 2
            elif wordPrev in ("בעוד", "עוד"):
                hrOffset = 1
                used = 1
            else:
                matched = False
            # "שעה וחצי" / "שעה ורבע" -> add half/quarter of an hour
            if matched and wordNext in ("@half", "@quarter"):
                minOffset += sign * (30 if wordNext == "@half" else 15)
                used += 1
        elif word in ("דקה", "דקות"):
            if is_digit(wordPrev):
                n = int(wordPrev)
                sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
                minOffset = sign * n
                start = idx - 1
                used = 2
            elif wordPrev in ("בעוד", "עוד"):
                minOffset = 1
                used = 1
        elif word in ("שנייה", "שניות") and is_digit(wordPrev):
            n = int(wordPrev)
            sign = -1 if words[idx - 2:idx - 1] == ["לפני"] else 1
            secOffset = sign * n
            start = idx - 1
            used = 2
        # explicit date: N ב<month> [year]  or  <month> N [year]
        else:
            month_token = word
            if month_token.startswith("ב"):
                month_token = month_token[1:]
            if month_token in _MONTH_WORDS:
                m = _MONTH_WORDS.index(month_token)
                used = 1
                day = None
                year = None
                # a token counts as a day of month when 1..31, otherwise
                # a 4-digit-ish value (>=100) is read as a year — so that
                # "ביולי 2019" (month + year, no day) never mistakes the
                # year for a day
                if is_digit(wordPrev) and 1 <= int(wordPrev) <= 31:
                    day = int(wordPrev)
                    start = idx - 1
                    used += 1
                    if is_digit(wordNext) and int(wordNext) >= 100:
                        year = int(wordNext)
                        used += 1
                elif is_digit(wordNext):
                    if int(wordNext) >= 100:
                        year = int(wordNext)
                        used += 1
                    elif 1 <= int(wordNext) <= 31:
                        day = int(wordNext)
                        used += 1
                        if is_digit(wordNextNext) and \
                                int(wordNextNext) >= 100:
                            year = int(wordNextNext)
                            used += 1
                if day is None and year is None:
                    # a bare month word on its own is not a date
                    used = 0
                else:
                    # month + year with no day resolves to the first
                    datestr = f"{_EN_MONTHS[m]} {day if day else 1}"
                    hasYear = year is not None
                    if year is not None:
                        datestr += f" {year}"

        if used > 0:
            # drop a leading "בעוד"/"עוד"/"לפני" linker
            if start - 1 >= 0 and words[start - 1] in ("בעוד", "עוד", "לפני"):
                start -= 1
                used += 1
            for i in range(start, start + used):
                words[i] = ""
            found = True
            daySpecified = True
        idx += 1

    words = [w for w in words if w != ""]

    # ---- time ----
    idx = 0
    while idx < len(words):
        word = words[idx]
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        used = 0

        if word in ("בבוקר", "בוקר"):
            if hrAbs is None:
                hrAbs = 8
            elif hrAbs == 12:
                hrAbs = 0
            used = 1
        elif word in ("בצהריים", "צהריים"):
            if hrAbs is None:
                hrAbs = 12
            used = 1
        elif word == "אחר" and wordNext in ("הצהריים", "צהריים"):
            if hrAbs is None:
                hrAbs = 15
            elif hrAbs < 12:
                hrAbs += 12
            used = 2
        elif word in ("בערב", "ערב"):
            if hrAbs is None:
                hrAbs = 20
            elif hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word in ("בלילה", "לילה"):
            if hrAbs is None:
                hrAbs = 23
            elif hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word == "@quarterto" and is_digit(wordNext):
            hrAbs = (int(wordNext) - 1) % 24
            minAbs = 45
            used = 2
            if wordPrev == "בשעה":
                words[idx - 1] = ""
        elif word == "בשעה" and is_digit(wordNext):
            hh, mm, used_inner = _parse_clock_token(wordNext, wordNextNext)
            if hh is not None:
                hrAbs, minAbs = hh, mm
                used = 2 + used_inner
        elif is_digit(word):
            hh, mm, used_inner = _parse_clock_token(word, wordNext)
            if hh is not None:
                hrAbs, minAbs = hh, mm
                used = 1 + used_inner

        if used > 0:
            for i in range(idx, idx + used):
                if i < len(words):
                    words[i] = ""
            found = True
        idx += 1

    words = [w for w in words if w != "" and not w.startswith("@")]

    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    extractedDate = dateNow.replace(microsecond=0, second=0, minute=0, hour=0)

    if datestr != "":
        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                temp = datetime.strptime(datestr, "%B %d")
                temp = temp.replace(year=extractedDate.year)
        except ValueError:
            # an impossible calendar date like "30 בפברואר"; report nothing
            # rather than a wrong guess
            return None
        if extractedDate.tzinfo:
            temp = temp.replace(tzinfo=extractedDate.tzinfo)
        if not hasYear and extractedDate.replace(
                month=temp.month, day=temp.day) < extractedDate:
            temp = temp.replace(year=currentYear + 1)
        extractedDate = extractedDate.replace(year=temp.year,
                                              month=temp.month,
                                              day=temp.day)

    if yearOffset != 0:
        extractedDate = extractedDate + relativedelta(years=yearOffset)
    if monthOffset != 0:
        extractedDate = extractedDate + relativedelta(months=monthOffset)
    if dayOffset != 0:
        extractedDate = extractedDate + relativedelta(days=dayOffset)

    # a bare clock offset ("in three hours") counts from the anchor's
    # current time, not from midnight
    if (hrOffset or minOffset or secOffset) and \
            hrAbs is None and minAbs is None:
        extractedDate = extractedDate + relativedelta(
            hours=dateNow.hour, minutes=dateNow.minute,
            seconds=dateNow.second)

    if hrAbs is None and minAbs is None and default_time is not None:
        hrAbs = default_time.hour
        minAbs = default_time.minute

    if hrAbs is not None or minAbs is not None:
        extractedDate = extractedDate + relativedelta(hours=hrAbs or 0,
                                                      minutes=minAbs or 0)
        if (hrAbs or minAbs) and datestr == "":
            if not daySpecified and dateNow > extractedDate:
                extractedDate = extractedDate + relativedelta(days=1)
    if hrOffset != 0:
        extractedDate = extractedDate + relativedelta(hours=hrOffset)
    if minOffset != 0:
        extractedDate = extractedDate + relativedelta(minutes=minOffset)
    if secOffset != 0:
        extractedDate = extractedDate + relativedelta(seconds=secOffset)

    resultStr = " ".join(w for w in words if w != "")
    resultStr = " ".join(resultStr.split())
    return [extractedDate, resultStr]


def _parse_clock_token(word, wordNext):
    """Interpret a numeric clock token.

    Handles ``HH:MM``, a bare hour, and a bare hour followed by a shielded
    half/quarter marker. Returns ``(hour, minute, extra_words_used)``;
    ``hour`` is None when the token is not a valid time.
    """
    extra = 0
    if ":" in word:
        parts = word.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or \
                not (parts[1] == "" or parts[1].isdigit()):
            return None, None, 0
        strHH = parts[0]
        strMM = parts[1] or "0"
    else:
        if not word.isdigit():
            return None, None, 0
        strHH = word
        strMM = "0"
        if wordNext == "@half":
            strMM = "30"
            extra = 1
        elif wordNext == "@quarter":
            strMM = "15"
            extra = 1

    hh = int(strHH)
    mm = int(strMM)
    if hh > 23 or mm > 59:
        return None, None, 0
    return hh, mm, extra


register_duration_lexicon(DurationLexicon(
    lang="he",
    normalize=lambda text: numbers_to_digits(text, "he"),
    joiner=r"(?:\s+|-)",
    units={
        "microseconds": r"מיקרו[ ]?שני[ה]?|מיקרו[ ]?שניות",
        "milliseconds": r"מילי[ ]?שני[ה]?|מילי[ ]?שניות|אלפית[ ]?השנייה",
        "seconds": r"שנייה|שני[ה]?|שניות",
        "minutes": r"דקה|דקות",
        "hours": r"שעה|שעות|שעתיים",
        "days": r"יום|ימים|יומיים",
        "weeks": r"שבוע|שבועות|שבועיים",
        "months": r"חודש|חודשים|חודשיים",
        "years": r"שנה|שנים|שנתיים",
        "decades": r"עשור|עשורים",
        "centuries": r"מאה|מאות",
        "millenniums": r"אלף שנה|אלפי שנים|מילניום",
    }))


def extract_duration_he(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """Convert a Hebrew phrase into a duration and return the remainder.

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration and the remaining unconsumed text.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["he"],
                                    resolution, replace_token)
