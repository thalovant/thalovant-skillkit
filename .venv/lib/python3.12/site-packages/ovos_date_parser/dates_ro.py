import re
from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_ro import RO
from ovos_number_parser.util import GrammaticalGender
from ovos_utils.time import now_local

from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

WEEKDAYS_RO = {
    0: "luni",
    1: "marți",
    2: "miercuri",
    3: "joi",
    4: "vineri",
    5: "sâmbătă",
    6: "duminică",
}
MONTHS_RO = {
    1: "ianuarie",
    2: "februarie",
    3: "martie",
    4: "aprilie",
    5: "mai",
    6: "iunie",
    7: "iulie",
    8: "august",
    9: "septembrie",
    10: "octombrie",
    11: "noiembrie",
    12: "decembrie",
}

# spoken number phrases -> digits, longest first so compounds win
# ("douăzeci și unu" before "douăzeci")
_NUM_WORDS = {}
for _n in range(1, 60):
    _NUM_WORDS[RO.pronounce_number(_n)] = _n
    _NUM_WORDS[RO.pronounce_number(_n, gender=GrammaticalGender.FEMININE)] = _n
_NUM_RX = re.compile(
    r"\b(" + "|".join(sorted((re.escape(w) for w in _NUM_WORDS),
                             key=len, reverse=True)) + r")\b")


def _words_to_digits(s: str) -> str:
    """Replace standalone spoken number phrases with digits."""
    return _NUM_RX.sub(lambda m: str(_NUM_WORDS[m.group(1)]), s)


def _spoken_hour_ro(hour: int) -> str:
    """Hours are counted with feminine numerals ("ora două",
    "ora douăsprezece") except for "unu" ("ora unu", "ora douăzeci și unu").
    """
    word = RO.pronounce_number(hour, gender=GrammaticalGender.FEMININE)
    if word == "una":
        return "unu"
    if word.endswith(" una"):
        return word[:-4] + " unu"
    return word


def nice_year_ro(dt, bc=False):
    """Format a year into a pronounceable Romanian form.

    Years are read as full numbers: 1984 is
    "o mie nouă sute optzeci și patru".
    """
    year = RO.pronounce_number(dt.year)
    if bc:
        return f"{year} î.Hr."
    return year


def nice_weekday_ro(dt):
    weekday = WEEKDAYS_RO[dt.weekday()]
    return weekday.capitalize()


def nice_month_ro(dt):
    month = MONTHS_RO[dt.month]
    return month.capitalize()


def _nice_day_of_month_ro(day: int) -> str:
    # the first of the month is "întâi" ("întâi mai"), other days
    # are read as cardinals
    if day == 1:
        return "întâi"
    return RO.pronounce_number(day)


def nice_day_ro(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_ro(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_time_ro(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time in a pronounceable way, for example
    "marți, cinci iunie, două mii optsprezece la ora cinci și jumătate".
    """
    now = now or now_local()
    return f"{nice_date_ro(dt, now)} la ora " \
           f"{nice_time_ro(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_ro(dt: datetime, now: datetime = None, include_weekday=True):
    """Format a date in a pronounceable way, for example
    "marți, cinci iunie, două mii optsprezece".
    """
    day = _nice_day_of_month_ro(dt.day)
    if now is not None:
        nice = day
        if dt.day == now.day and dt.month == now.month and dt.year == now.year:
            return "azi"
        if (dt.date() - now.date()).days == 1:
            return "mâine"
        if (dt.date() - now.date()).days == -1:
            return "ieri"
        if dt.month != now.month or dt.year != now.year:
            nice = nice + " " + nice_month_ro(dt).lower()
        if dt.year != now.year:
            nice = nice + ", " + nice_year_ro(dt)
    else:
        nice = f"{day} {nice_month_ro(dt).lower()}, {nice_year_ro(dt)}"

    if include_weekday:
        weekday = nice_weekday_ro(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_ro(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a human readable Romanian form.

    For example, "opt și jumătate" for 8:30, "nouă fără un sfert"
    for 8:45, "opt fix" for 8:00.
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

    speak = ""
    if use_24hour:
        speak = _spoken_hour_ro(dt.hour) if dt.hour else "zero"
        if dt.minute == 0:
            speak += " fix"
        elif dt.minute < 10:
            speak += " zero " + RO.pronounce_number(
                dt.minute, gender=GrammaticalGender.FEMININE)
        else:
            speak += " " + RO.pronounce_number(
                dt.minute, gender=GrammaticalGender.FEMININE)
    else:
        # quarter-to and minutes-to forms use "fără" against the next hour
        if dt.minute in (35, 40, 45, 50, 55):
            minute = dt.minute - 60
            hour = dt.hour + 1
        else:
            minute = dt.minute
            hour = dt.hour

        hour12 = hour % 12 or 12
        speak = _spoken_hour_ro(hour12)

        if minute != 0:
            if minute == 15:
                speak += " și un sfert"
            elif minute == 30:
                speak += " și jumătate"
            elif minute == -15:
                speak += " fără un sfert"
            elif minute > 0:
                speak += " și " + RO.pronounce_number(
                    minute, gender=GrammaticalGender.FEMININE)
            else:
                speak += " fără " + RO.pronounce_number(
                    -minute, gender=GrammaticalGender.FEMININE)

        if minute == 0 and not use_ampm:
            speak += " fix"

        if use_ampm:
            if hour < 6 or hour >= 22:
                speak += " noaptea"
            elif hour < 12:
                speak += " dimineața"
            elif hour < 18:
                speak += " după-amiaza"
            else:
                speak += " seara"
    return speak


def extract_datetime_ro(text, anchorDate=None, default_time=None):
    """Extract date and time information from a Romanian phrase.

    Args:
        text (str): text to parse
        anchorDate (datetime): reference date for relative dates
        default_time (time): time to use if none is found in the text

    Returns:
        [datetime, str] | None: the extracted date and the remaining text,
        or None if no date or time is found.
    """

    def clean_string(s):
        symbols = [".", ",", ";", "?", "!"]
        for word in symbols:
            s = s.replace(word, "")

        # cedilla forms of ș/ț -> comma-below (Romanian Academy orthography)
        s = s.lower().replace("ş", "ș").replace("ţ", "ț")
        s = s.replace("-", " ").replace("_", " ")

        # single-token time-of-day words
        s = re.sub(r"\bdupă (amiaza|amiază|masa|masă)\b", "dupăamiaza", s)
        s = re.sub(r"\bmiezul nopții\b", "miezulnopții", s)

        # articled forms -> base forms
        articled = {"lunea": "luni", "marțea": "marți",
                    "miercurea": "miercuri", "joia": "joi",
                    "vinerea": "vineri", "sâmbăta": "sâmbătă",
                    "duminica": "duminică", "săptămâna": "săptămână",
                    "anul": "an", "ziua": "zi", "dimineață": "dimineața",
                    "seară": "seara", "noapte": "noaptea",
                    "amiaza": "amiază", "prânzul": "prânz"}
        for k, v in articled.items():
            s = re.sub(rf"\b{k}\b", v, s)

        # spoken numbers -> digits
        s = _words_to_digits(s)

        # numbers link to counted nouns with "de" ("30 de secunde")
        s = re.sub(r"\b(\d+) de\b", r"\1", s)

        # "luni" is both Monday and the plural of "lună"; a numeric
        # context makes it the month unit
        s = re.sub(r"\b(\d+) luni\b", r"\1 lună", s)
        # "luna viitoare/trecută" is the month unit, not Monday
        s = re.sub(r"\bluna (viitoare|următoare|trecută)\b", r"lună \1", s)

        # plural units -> singular
        plurals = {"zile": "zi", "zilele": "zi", "ore": "oră",
                   "orele": "oră", "minute": "minut", "minutele": "minut",
                   "secunde": "secundă", "secundele": "secundă",
                   "săptămâni": "săptămână", "ani": "an", "lunile": "lună"}
        for k, v in plurals.items():
            s = re.sub(rf"\b{k}\b", v, s)
        return s

    def date_found():
        return found or \
            (
                    datestr != "" or
                    yearOffset != 0 or monthOffset != 0 or
                    dayOffset is True or hrOffset != 0 or
                    hrAbs or minOffset != 0 or
                    minAbs or secOffset != 0
            )

    if text == "":
        return None
    if anchorDate is None:
        anchorDate = now_local()

    found = False
    daySpecified = False
    dayOffset = False
    monthOffset = 0
    yearOffset = 0
    dateNow = anchorDate
    today = dateNow.strftime("%w")
    currentYear = dateNow.strftime("%Y")
    fromFlag = False
    datestr = ""
    hasYear = False
    timeQualifier = ""

    words = clean_string(text).split(" ")
    timeQualifiersList = ['dimineața', 'dupăamiaza', 'seara', 'noaptea']
    time_indicators = ["în", "la", "pe", "peste", "după", "ora", "zi",
                       "oră"]
    days = ['luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă',
            'duminică']
    months = ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie',
              'iulie', 'august', 'septembrie', 'octombrie', 'noiembrie',
              'decembrie']
    monthsShort = ['ian', 'feb', 'mar', 'apr', 'mai', 'iun', 'iul', 'aug',
                   'sep', 'oct', 'noi', 'dec']
    nexts = ["viitoare", "viitor", "următoare", "următorul", "următor"]
    suffix_nexts = nexts
    lasts = ["trecută", "trecut", "anterioară", "anterior"]
    suffix_lasts = lasts
    nxts = ["după", "viitoare", "viitor", "următoare", "următorul"]
    prevs = ["înainte", "anterioară", "anterior", "trecută", "trecut"]
    froms = ["de", "din", "peste", "după", "începând", "la", "pe"]
    thises = ["această", "acest", "asta"]
    froms += thises
    lists = nxts + prevs + froms + time_indicators
    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        wordNextNextNext = words[idx + 3] if idx + 3 < len(words) else ""

        start = idx
        used = 0
        # save the time qualifier for later
        if word in timeQualifiersList:
            timeQualifier = word

        # azi/astăzi, mâine, ieri, poimâine, alaltăieri
        elif word in ("azi", "astăzi") and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "mâine" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "ieri" and not fromFlag:
            dayOffset -= 1
            used += 1
        elif word == "alaltăieri" and not fromFlag:
            dayOffset -= 2
            used += 1
        elif word == "poimâine" and not fromFlag:
            dayOffset += 2
            used += 1
        elif word == "răspoimâine" and not fromFlag:
            dayOffset += 3
            used += 1
        # peste 5 zile etc
        elif word == "zi":
            if (wordPrev and wordPrev[0].isdigit() and
                    wordNext not in months and
                    wordNext not in monthsShort):
                # "acum N ..." = N periods in the past (DEX/dexonline)
                if wordPrevPrev == "acum":
                    dayOffset -= int(wordPrev)
                    start -= 2
                    used += 3
                else:
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 2
            elif (wordNext and wordNext[0].isdigit() and
                  wordNextNext not in months and
                  wordNextNext not in monthsShort):
                dayOffset += int(wordNext)
                start -= 1
                used += 2

        elif word == "săptămână" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "acum N ..." = N periods in the past (DEX/dexonline)
                if wordPrevPrev == "acum":
                    dayOffset -= int(wordPrev) * 7
                    start -= 2
                    used = 3
                else:
                    dayOffset += int(wordPrev) * 7
                    start -= 1
                    used = 2
            for w in nexts:
                if wordPrev == w:
                    dayOffset = 7
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    dayOffset = 7
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
        # 10 luni, luna viitoare, luna trecută
        elif word == "lună" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "acum N ..." = N periods in the past (DEX/dexonline)
                if wordPrevPrev == "acum":
                    monthOffset = -int(wordPrev)
                    start -= 2
                    used = 3
                else:
                    monthOffset = int(wordPrev)
                    start -= 1
                    used = 2
            for w in nexts:
                if wordPrev == w:
                    monthOffset = 1
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    monthOffset = -1
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    monthOffset = 1
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    monthOffset = -1
                    start -= 1
                    used = 2
        # 5 ani, anul viitor, anul trecut
        elif word == "an" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "acum N ..." = N periods in the past (DEX/dexonline)
                if wordPrevPrev == "acum":
                    yearOffset = -int(wordPrev)
                    start -= 2
                    used = 3
                else:
                    yearOffset = int(wordPrev)
                    start -= 1
                    used = 2
            for w in nexts:
                if wordPrev == w:
                    yearOffset = 1
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    yearOffset = -1
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    yearOffset = 1
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    yearOffset = -1
                    start -= 1
                    used = 2
        # weekdays: luni, marți...
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev in nexts:
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev in lasts:
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext in nexts:
                dayOffset += 7
                used += 1
            elif wordNext in lasts:
                dayOffset -= 7
                used += 1
        # 3 iunie, iunie 20, etc
        # "mai" is both the month of May and a very common adverb, so it
        # only counts as a month next to a day or year number
        elif (word in months or word in monthsShort) and not (
                word == "mai" and not any(
                    w and w[0].isdigit()
                    for w in (wordPrev, wordNext, wordPrevPrev,
                              wordNextNext))):
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
                # 13 mai
                datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                # mai 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 zi mai
                datestr += " " + wordPrevPrev
                start -= 2
                used += 2
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNextNext and wordNextNext[0].isdigit():
                # mai zi 13
                datestr += " " + wordNextNext
                used += 2
                if wordNextNextNext and wordNextNextNext[0].isdigit():
                    datestr += " " + wordNextNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            if datestr in months:
                datestr = ""

        # 5 zile de mâine, 2 săptămâni de joi, etc
        validFollowups = days + months + monthsShort
        validFollowups.append("azi")
        validFollowups.append("astăzi")
        validFollowups.append("mâine")
        validFollowups.append("ieri")
        validFollowups.append("alaltăieri")
        validFollowups.append("poimâine")
        validFollowups.append("acum")

        if word in froms and wordNext in validFollowups:

            if word not in ("trecut", "înainte"):
                used = 2
                fromFlag = True
            if wordNext == "mâine":
                dayOffset += 1
            elif wordNext == "poimâine":
                dayOffset += 2
            elif wordNext == "ieri":
                dayOffset -= 1
            elif wordNext == "alaltăieri":
                dayOffset -= 2
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if tmpOffset < 0:
                    tmpOffset += 7
                if wordNextNext:
                    if wordNextNext in nxts:
                        tmpOffset += 7
                        used += 1
                    elif wordNextNext in prevs:
                        tmpOffset -= 7
                        used += 1
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = days.index(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNextNextNext:
                    if wordNextNextNext in nxts:
                        tmpOffset += 7
                        used += 1
                    elif wordNextNextNext in prevs:
                        tmpOffset -= 7
                        used += 1
                dayOffset += tmpOffset
        if wordNext in months:
            used -= 1
        if used > 0:
            if start - 1 > 0 and words[start - 1] in lists:
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in lists:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse the time
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None

    for idx, word in enumerate(words):
        if word == "":
            continue

        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        wordNextNextNext = words[idx + 3] if idx + 3 < len(words) else ""
        # noon, midnight, morning, afternoon, evening, night
        used = 0
        if word in ("prânz", "amiază"):
            hrAbs = 12
            used += 1
        elif word == "miezulnopții":
            hrAbs = 0
            used += 1
        elif word == "dimineața":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "dupăamiaza":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word == "seara":
            if not hrAbs:
                hrAbs = 19
            used += 1
        elif word == "noaptea":
            if not hrAbs:
                hrAbs = 21
            used += 1
        # jumătate de oră, un sfert de oră
        elif word == "oră" and \
                (wordPrev in time_indicators or
                 wordPrevPrev in time_indicators or
                 wordPrev in ("jumătate", "sfert", "de")):
            if wordPrev == "jumătate" or wordPrevPrev == "jumătate":
                minOffset = 30
            elif wordPrev == "sfert" or wordPrevPrev == "sfert":
                minOffset = 15
                if idx > 2 and words[idx - 3] == "un":
                    words[idx - 3] = ""
            else:
                hrOffset = 1
            if wordPrevPrev in time_indicators or \
                    wordPrevPrev in ("jumătate", "sfert"):
                words[idx - 2] = ""
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
        # 5:00 am, 12:00 pm, la ora 8, etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
                # 17:30, 3:00 dimineața
                stage = 0
                length = len(word)
                for i in range(length):
                    if stage == 0:
                        if word[i].isdigit():
                            strHH += word[i]
                        elif word[i] == ":":
                            stage = 1
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 1:
                        if word[i].isdigit():
                            strMM += word[i]
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 2:
                        remainder = word[i:].replace(".", "")
                        break
                if remainder == "":
                    nextWord = wordNext.replace(".", "")
                    if nextWord == "am" or nextWord == "pm":
                        remainder = nextWord
                        used += 1
                    elif wordNext == "dimineața":
                        remainder = "am"
                        used += 1
                    elif wordNext in ("dupăamiaza", "seara"):
                        remainder = "pm"
                        used += 1
                    elif wordNext == "noaptea":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif timeQualifier != "":
                        if int(strHH) <= 12 and \
                                timeQualifier in ("dupăamiaza", "seara",
                                                  "noaptea"):
                            remainder = "pm"

            else:
                # numbers without colons: la ora 8, 8 și jumătate,
                # peste 5 minute, etc
                length = len(word)
                strNum = ""
                remainder = ""
                for i in range(length):
                    if word[i].isdigit():
                        strNum += word[i]
                    else:
                        remainder += word[i]

                if remainder == "":
                    remainder = wordNext.replace(".", "").lstrip().rstrip()

                if (
                        remainder == "pm" or
                        wordNext == "pm" or
                        remainder == "p.m." or
                        wordNext == "p.m."):
                    strHH = strNum
                    remainder = "pm"
                    used = 1
                elif (
                        remainder == "am" or
                        wordNext == "am" or
                        remainder == "a.m." or
                        wordNext == "a.m."):
                    strHH = strNum
                    remainder = "am"
                    used = 1
                # 8 și jumătate, 8 și un sfert, 8 și 10
                elif wordNext == "și" and wordNextNext in (
                        "jumătate", "sfert") or \
                        (wordNext == "și" and wordNextNext == "un" and
                         wordNextNextNext == "sfert"):
                    strHH = strNum
                    if wordNextNext == "jumătate":
                        strMM = 30
                        used = 2
                    elif wordNextNext == "sfert":
                        strMM = 15
                        used = 2
                    else:
                        strMM = 15
                        used = 3
                    period_idx = idx + used + 1
                    period = words[period_idx] if period_idx < len(words) \
                        else ""
                    if period == "dimineața":
                        remainder = "am"
                        used += 1
                    elif period in ("dupăamiaza", "seara"):
                        remainder = "pm"
                        used += 1
                    elif period == "noaptea":
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                elif wordNext == "și" and wordNextNext and \
                        wordNextNext[0].isdigit():
                    # 8 și 20
                    strHH = strNum
                    strMM = wordNextNext
                    used = 2
                # 9 fără un sfert, 9 fără 20
                elif wordNext == "fără" and (
                        wordNextNext == "sfert" or
                        (wordNextNext == "un" and
                         wordNextNextNext == "sfert")):
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 45
                    used = 2 if wordNextNext == "sfert" else 3
                elif wordNext == "fără" and wordNextNext and \
                        wordNextNext[0].isdigit():
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 60 - int(wordNextNext)
                    used = 2
                else:
                    if wordNext in ("dupăamiaza", "seara"):
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif wordNext == "dimineața":
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif wordNext == "noaptea":
                        strHH = strNum
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used = 1
                    elif (wordNext == "oră" and
                          word[0] != '0' and strNum and
                          int(strNum) < 100):
                        # peste 3 ore
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minut":
                        # peste 10 minute
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "secundă":
                        # peste 5 secunde
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif strNum and int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        if wordNext == "oră":
                            used += 1
                    elif wordNext == "fix" or wordNext == "" or \
                            wordPrev == "ora" or wordPrev == "la":
                        strHH = strNum
                        strMM = 00
                        if wordNext == "fix":
                            used += 1
                            period_idx = idx + 2
                            period = words[period_idx] \
                                if period_idx < len(words) else ""
                            if period == "dimineața":
                                remainder = "am"
                                used += 1
                            elif period in ("dupăamiaza", "seara"):
                                remainder = "pm"
                                used += 1
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        used += 1
                        if wordNextNext == "oră":
                            used += 1
                    else:
                        isTime = False

            strHH = int(strHH) if strHH else 0
            strMM = int(strMM) if strMM else 0
            strHH = strHH + 12 if (remainder == "pm" and
                                   0 < strHH < 12) else strHH
            strHH = strHH - 12 if (remainder == "am" and
                                   strHH >= 12) else strHH
            if strHH > 24 or strMM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = strHH * 1
                minAbs = strMM * 1
                used += 1

        if used > 0:
            # remove parsed words from the sentence
            for i in range(used):
                if idx + i < len(words):
                    words[idx + i] = ""

            if idx > 0 and wordPrev in time_indicators:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in time_indicators:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # check that a date was found
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # date manipulation
    extractedDate = dateNow.replace(microsecond=0, second=0)
    if hrOffset == 0 and minOffset == 0 and secOffset == 0:
        # pure duration offsets ("peste 10 minute") stay relative to the
        # anchor time; anything else counts from midnight
        extractedDate = extractedDate.replace(minute=0, hour=0)
    if datestr != "":
        en_months = ['january', 'february', 'march', 'april', 'may', 'june',
                     'july', 'august', 'september', 'october', 'november',
                     'december']
        en_monthsShort = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july',
                          'aug', 'sept', 'oct', 'nov', 'dec']
        months_ro = ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai',
                     'iunie', 'iulie', 'august', 'septembrie', 'octombrie',
                     'noiembrie', 'decembrie']
        monthsShort_ro = ['ian', 'feb', 'mar', 'apr', 'mai', 'iun', 'iul',
                          'aug', 'sep', 'oct', 'noi', 'dec']
        for idx, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months_ro[idx]) + r"\b",
                             en_month, datestr)
        for idx, en_month in enumerate(en_monthsShort):
            datestr = re.sub(r"\b" + re.escape(monthsShort_ro[idx]) + r"\b",
                             en_month, datestr)

        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # an impossible calendar date like "30 februarie"; report nothing
            # rather than a wrong guess
            return None
        if extractedDate.tzinfo:
            temp = temp.replace(tzinfo=extractedDate.tzinfo)

        if not hasYear:
            temp = temp.replace(year=extractedDate.year)

            if extractedDate < temp:
                extractedDate = extractedDate.replace(
                    year=int(currentYear),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")))
            else:
                extractedDate = extractedDate.replace(
                    year=int(currentYear) + 1,
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")))
        else:
            extractedDate = extractedDate.replace(
                year=int(temp.strftime("%Y")),
                month=int(temp.strftime("%m")),
                day=int(temp.strftime("%d")))

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
        if (hrAbs or minAbs) and datestr == "":
            if not daySpecified and dateNow > extractedDate:
                extractedDate = extractedDate + relativedelta(days=1)
    if hrOffset != 0:
        extractedDate = extractedDate + relativedelta(hours=hrOffset)
    if minOffset != 0:
        extractedDate = extractedDate + relativedelta(minutes=minOffset)
    if secOffset != 0:
        extractedDate = extractedDate + relativedelta(seconds=secOffset)

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def extract_duration_ro(text, resolution=DurationResolution.TIMEDELTA,
                         replace_token=""):
    """Convert a Romanian phrase into a number of seconds.

    Converts things like "10 minute" or
    "3 zile 8 ore 10 minute și 49 de secunde" into a timedelta.
    The words used in the duration are consumed and the remaining
    text is returned; for example "pornește un cronometru de 5 minute"
    returns (300, "pornește un cronometru de").

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration (timedelta, relativedelta or float
                         depending on resolution) and the remaining
                         unconsumed text.
    """
    if not text:
        return None, text
    return extract_duration_generic(text, DURATION_LEXICONS["ro"],
                                    resolution, replace_token)
