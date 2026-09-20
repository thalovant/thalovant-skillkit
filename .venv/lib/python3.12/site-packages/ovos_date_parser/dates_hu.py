import re
from datetime import datetime, timedelta

from ovos_number_parser import numbers_to_digits
from ovos_number_parser.numbers_hu import pronounce_number_hu, _NUM_STRING_HU, extract_number_hu
from ovos_utils.time import DAYS_IN_1_MONTH, DAYS_IN_1_YEAR
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def nice_time_hu(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format

    For example, generate 'five thirty' for speech or '5:30' for
    text display.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)=Fal
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
    Returns:
        (str): The formatted time string
    """
    if use_24hour:
        # e.g. "03:01" or "14:22"
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            # e.g. "3:01 AM" or "2:22 PM"
            string = dt.strftime("%I:%M %p")
        else:
            # e.g. "3:01" or "2:22"
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # strip leading zeros

    if not speech:
        return string

    # Generate a speakable version of the time
    speak = ""
    if use_24hour:
        speak += pronounce_number_hu(dt.hour)
        speak = speak.replace(_NUM_STRING_HU[2], 'két')
        speak += " óra"
        if not dt.minute == 0:  # zero minutes are not pronounced
            speak += " " + pronounce_number_hu(dt.minute)

        return speak  # ampm is ignored when use_24hour is true
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "éjfél"
        if dt.hour == 12 and dt.minute == 0:
            return "dél"
        # TODO: "half past 3", "a quarter of 4" and other idiomatic times

        if dt.hour == 0:
            speak += pronounce_number_hu(12)
        elif dt.hour < 13:
            speak = pronounce_number_hu(dt.hour)
        else:
            speak = pronounce_number_hu(dt.hour - 12)

        speak = speak.replace(_NUM_STRING_HU[2], 'két')
        speak += " óra"

        if not dt.minute == 0:
            speak += " " + pronounce_number_hu(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                if dt.hour < 18:
                    speak = "délután " + speak  # 12:01 - 17:59
                elif dt.hour < 22:
                    speak = "este " + speak  # 18:00 - 21:59 este/evening
                else:
                    speak = "éjjel " + speak  # 22:00 - 23:59 éjjel/at night
            elif dt.hour < 3:
                speak = "éjjel " + speak  # 00:01 - 02:59 éjjel/at night
            else:
                speak = "reggel " + speak  # 03:00 - 11:59 reggel/in t. morning

        return speak


def extract_duration_hu(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """
    Convert a phrase into a duration and return the remainder text.

    The words used in the duration are consumed, the remainder of the
    text is returned. Returns None for empty input; the duration is
    None if no duration was found.

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration (timedelta, relativedelta or float
                         depending on resolution) and the remaining
                         unconsumed text.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["hu"],
                                    resolution, replace_token)


_WEEKDAYS_HU = {
    "hétfő": 0, "hétfőn": 0,
    "kedd": 1, "kedden": 1,
    "szerda": 2, "szerdán": 2,
    "csütörtök": 3, "csütörtökön": 3,
    "péntek": 4, "pénteken": 4,
    "szombat": 5, "szombaton": 5,
    "vasárnap": 6, "vasárnapon": 6,
}

_MONTHS_HU = ["január", "február", "március", "április", "május", "június",
              "július", "augusztus", "szeptember", "október", "november",
              "december"]


def extract_datetime_hu(text, anchorDate=None, default_time=None):
    """
    Extract a datetime from a Hungarian phrase.

    Handles relative days (ma, holnap, tegnap, holnapután, tegnapelőtt),
    weekdays with the -n suffix (hétfőn), jövő/múlt (next/last),
    "X <unit> múlva" offsets, explicit dates (június 3) and times.
    The Hungarian fractional-hour system counts *towards* the next hour:
    "fél kilenc" is 8:30, "negyed kilenc" is 8:15 and "háromnegyed
    kilenc" is 8:45.

    Args:
        text (str): the text to parse.
        anchorDate (datetime): the date the input is relative to,
                               defaults to now.
        default_time (time): time to use if none was found in the input.
    Returns:
        [datetime, str]: the extracted datetime and the leftover text,
                         or None if no date or time was found.
    """
    from dateutil.relativedelta import relativedelta
    from ovos_utils.time import now_local

    if not text:
        return None

    anchorDate = anchorDate or now_local()
    dateNow = anchorDate

    # tokenize; normalize the "-kor" (at) suffix, remembering where it was
    raw = text.lower().replace(",", " ").replace("?", " ").replace("!", " ")
    tokens = []
    kor = []
    for tok in raw.split():
        tok = tok.strip(".;:") if ":" not in tok else tok.strip(".;")
        had_kor = False
        if tok.endswith("-kor"):
            tok = tok[:-4]
            had_kor = True
        elif tok == "órakor":
            tok = "óra"
            had_kor = True
        elif tok == "éjfélkor":
            tok = "éjfél"
            had_kor = True
        elif tok in ("délkor", "délben"):
            tok = "dél"
            had_kor = True
        elif tok in ("órára", "óráig", "órától"):
            tok = "óra"
        elif tok.endswith("kor") and extract_number_hu(tok[:-3]) is not False:
            # a spelled-out hour carries "-kor" attached, without a hyphen
            # ("nyolckor" = at eight); only strip it when the remainder is
            # itself a number word, so "akkor"/"amikor" are left untouched
            tok = tok[:-3]
            had_kor = True
        tokens.append(tok)
        kor.append(had_kor)

    found = False
    daySpecified = False
    dayOffset = 0
    monthOffset = 0
    yearOffset = 0
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None
    datestrMonth = None
    datestrDay = None
    datestrYear = None
    timeQualifier = ""
    qualifierDefaultHr = None

    def _num(tok):
        if not tok:
            return None
        if re.fullmatch(r"\d+(?:[.,]\d+)?", tok):
            return float(tok.replace(",", "."))
        val = extract_number_hu(tok)
        return val if val is not False else None

    # pass 1: "X <unit> múlva" (in X units)
    for idx, tok in enumerate(tokens):
        if tok != "múlva" or idx == 0:
            continue
        unit = tokens[idx - 1]
        num = _num(tokens[idx - 2]) if idx > 1 else None
        used_num = num is not None
        if num is None:
            num = 1
        consumed = 0
        if unit.startswith("másodperc"):
            secOffset += num
        elif unit.startswith("perc"):
            minOffset += num
        elif unit.startswith("óra") or unit.startswith("órá"):
            hrOffset += num
        elif unit == "nap":
            dayOffset += int(num)
        elif unit == "hét":
            # "hét múlva" = in a week; "két hét múlva" = in two weeks
            # (a number before "hét" marks it as the unit, cf.
            # extract_duration_hu)
            dayOffset += int(num) * 7
        elif unit == "hónap":
            monthOffset += int(num)
        elif unit == "év":
            yearOffset += int(num)
        else:
            continue
        if unit.startswith("óra") or unit.startswith("órá") or \
                unit.startswith("perc") or unit.startswith("másodperc"):
            hrAbs = -1
            minAbs = -1
        tokens[idx] = ""
        tokens[idx - 1] = ""
        if used_num:
            tokens[idx - 2] = ""
        found = True
        daySpecified = daySpecified or unit in ("nap", "hét", "hónap", "év")

    # pass 2: dates
    for idx, tok in enumerate(tokens):
        if tok == "":
            continue
        prev = tokens[idx - 1] if idx > 0 else ""
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        nxtnxt = tokens[idx + 2] if idx + 2 < len(tokens) else ""
        used = 0
        start = idx
        if tok == "ma":
            dayOffset += 0
            used = 1
        elif tok == "holnapután":
            dayOffset += 2
            used = 1
        elif tok == "holnap":
            dayOffset += 1
            used = 1
        elif tok == "tegnapelőtt":
            dayOffset += -2
            used = 1
        elif tok == "tegnap":
            dayOffset += -1
            used = 1
        elif tok in _WEEKDAYS_HU:
            d = _WEEKDAYS_HU[tok]
            offset = d - dateNow.weekday()
            if offset < 0:
                offset += 7
            if prev == "jövő":
                # weekday of the next calendar week
                offset = (7 - dateNow.weekday()) + d
                start -= 1
                used += 1
            elif prev == "múlt":
                # weekday of the previous calendar week
                offset = d - dateNow.weekday() - 7
                start -= 1
                used += 1
            dayOffset += offset
            used += 1
        elif tok in ("héten", "hétre", "hétig", "héttől") or \
                (tok == "hét" and prev in ("jövő", "múlt")):
            if prev == "jövő":
                dayOffset += 7
                start -= 1
                used = 2
            elif prev == "múlt":
                dayOffset += -7
                start -= 1
                used = 2
        elif any(tok.startswith(m) for m in _MONTHS_HU):
            datestrMonth = next(i + 1 for i, m in enumerate(_MONTHS_HU)
                                if tok.startswith(m))
            used = 1
            m_day = re.fullmatch(r"(\d{1,2})(?:-j?[aáeé]n?|\.)?", nxt)
            if m_day:
                datestrDay = int(m_day.group(1))
                used += 1
                if re.fullmatch(r"\d{4}", nxtnxt):
                    datestrYear = int(nxtnxt)
                    used += 1
            else:
                datestrDay = 1
        if used > 0:
            for i in range(used):
                tokens[start + i] = ""
            found = True
            daySpecified = True

    # pass 3: times
    for idx, tok in enumerate(tokens):
        if tok == "":
            continue
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        used = 0
        if tok == "dél":
            hrAbs = 12
            minAbs = 0
            used = 1
        elif tok in ("éjfél", "éjfélig", "éjfélre"):
            hrAbs = 0
            minAbs = 0
            used = 1
        elif tok == "reggel":
            timeQualifier = "am"
            qualifierDefaultHr = 8
            used = 1
        elif tok == "délelőtt":
            timeQualifier = "am"
            qualifierDefaultHr = 10
            used = 1
        elif tok == "délután":
            timeQualifier = "pm"
            qualifierDefaultHr = 15
            used = 1
        elif tok == "este":
            timeQualifier = "pm"
            qualifierDefaultHr = 19
            used = 1
        elif tok in ("éjjel", "éjszaka"):
            timeQualifier = "night"
            qualifierDefaultHr = 23
            used = 1
        elif tok in ("fél", "negyed", "háromnegyed"):
            # Hungarian counts fractions towards the NEXT hour:
            # "fél kilenc" = 8:30, "negyed kilenc" = 8:15,
            # "háromnegyed kilenc" = 8:45
            n = _num(nxt)
            if n is not None and float(n).is_integer() and 1 <= n <= 12:
                hrAbs = int(n) - 1
                minAbs = {"fél": 30, "negyed": 15, "háromnegyed": 45}[tok]
                used = 2
        elif ":" in tok and re.fullmatch(r"\d{1,2}:\d{2}", tok):
            hh, mm = tok.split(":")
            if int(hh) < 24 and int(mm) < 60:
                hrAbs = int(hh)
                minAbs = int(mm)
                used = 1
        elif re.fullmatch(r"\d{1,2}", tok):
            if nxt == "óra" or kor[idx]:
                hrAbs = int(tok)
                minAbs = 0
                used = 2 if nxt == "óra" else 1
                m_min = tokens[idx + 2] if nxt == "óra" and \
                    idx + 2 < len(tokens) else ""
                if nxt == "óra" and re.fullmatch(r"\d{1,2}", m_min) and \
                        int(m_min) < 60:
                    minAbs = int(m_min)
                    used += 1
        elif nxt == "óra" or kor[idx]:
            # a spelled-out hour, either before "óra" or carrying "-kor"
            # ("nyolckor" = at eight)
            n = _num(tok)
            if n is not None and float(n).is_integer() and 0 <= n <= 24:
                hrAbs = int(n)
                minAbs = 0
                used = 2 if nxt == "óra" else 1
        if used > 0:
            for i in range(used):
                tokens[idx + i] = ""
            found = True

    if hrAbs is not None and hrAbs not in (-1,) and timeQualifier:
        if timeQualifier == "pm" and hrAbs < 12:
            hrAbs += 12
        elif timeQualifier == "night":
            if 8 <= hrAbs <= 11:
                hrAbs += 12
            elif hrAbs == 12:
                hrAbs = 0
                dayOffset += 1
    elif hrAbs is None and qualifierDefaultHr is not None:
        hrAbs = qualifierDefaultHr
        minAbs = 0

    if not found and hrAbs is None and datestrMonth is None:
        return None

    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # a purely relative offset ("15 perc múlva") keeps the anchor time of day
        extractedDate = dateNow.replace(microsecond=0, second=0)
    else:
        extractedDate = dateNow.replace(microsecond=0, second=0, minute=0, hour=0)

    if datestrMonth is not None:
        day = datestrDay or 1
        if datestrYear:
            candidate_years = [datestrYear]
        else:
            # walk forward to the soonest year where the date exists and is
            # not already past (handles "február 29" -> next leap year)
            candidate_years = range(extractedDate.year,
                                    extractedDate.year + 9)
        temp = None
        for y in candidate_years:
            try:
                cand = extractedDate.replace(year=y, month=datestrMonth,
                                             day=day)
            except ValueError:
                continue  # e.g. Feb 29 in a common year
            if datestrYear or cand >= extractedDate:
                temp = cand
                break
        if temp is None:
            # a date that never exists ("április 31") or an invalid
            # explicit year ("február 29 2019"): drop the bad date rather
            # than raising, and give up entirely if nothing else was found
            datestrMonth = None
            if not (hrAbs is not None or hrOffset or minOffset or secOffset
                    or dayOffset or monthOffset or yearOffset):
                return None
        else:
            extractedDate = temp

    if yearOffset != 0:
        extractedDate = extractedDate + relativedelta(years=yearOffset)
    if monthOffset != 0:
        extractedDate = extractedDate + relativedelta(months=monthOffset)
    if dayOffset != 0:
        extractedDate = extractedDate + relativedelta(days=dayOffset)

    if hrAbs is None and minAbs is None and default_time:
        hrAbs = default_time.hour
        minAbs = default_time.minute

    if hrAbs != -1 and minAbs != -1:
        extractedDate = extractedDate + relativedelta(hours=hrAbs or 0,
                                                      minutes=minAbs or 0)
        if (hrAbs or minAbs) and datestrMonth is None:
            if not daySpecified and dateNow > extractedDate:
                extractedDate = extractedDate + relativedelta(days=1)
    if hrOffset != 0:
        extractedDate = extractedDate + relativedelta(hours=hrOffset)
    if minOffset != 0:
        extractedDate = extractedDate + relativedelta(minutes=minOffset)
    if secOffset != 0:
        extractedDate = extractedDate + relativedelta(seconds=secOffset)

    resultStr = " ".join(t for t in tokens if t)
    resultStr = " ".join(resultStr.split())

    return [extractedDate, resultStr]
