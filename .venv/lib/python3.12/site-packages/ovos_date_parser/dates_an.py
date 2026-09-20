from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_an import AN
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

# Standard written Aragonese weekday names.
# Sources: Biquipedia "Nombre d'os días d'a semana" and "Semana"
# (https://an.wikipedia.org/wiki/Nombre_d'os_d%C3%ADas_d'a_semana),
# Aragonese Wiktionary entry "luns".
WEEKDAYS_AN = {
    0: "luns",
    1: "martes",
    2: "miercres",
    3: "chueves",
    4: "viernes",
    5: "sabado",
    6: "dominche"
}
# Aragonese month names.
# Source: Biquipedia "Mes" (https://an.wikipedia.org/wiki/Mes).
MONTHS_AN = {
    1: "chinero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "chunyo",
    7: "chuliol",
    8: "agosto",
    9: "setiembre",
    10: "octubre",
    11: "noviembre",
    12: "deciembre"
}

# Feminine cardinal hour words for the spoken clock (1-12).
# The number engine emits a few masculine or variant forms (un, cuatre,
# siet), so the clock forms are pinned here.
HOURS_AN = {
    1: "una",
    2: "dos",
    3: "tres",
    4: "cuatro",
    5: "cinco",
    6: "seis",
    7: "siete",
    8: "ueito",
    9: "nueu",
    10: "diez",
    11: "once",
    12: "doce"
}

_VOWELS_AN = "aeiou"


def pronounce_number_an(number, **kwargs):
    return AN.pronounce_number(number, **kwargs)


def _starts_with_vowel_an(word):
    """Whether an Aragonese word starts with a vowel sound (accents ignored)."""
    first = word[:1].lower()
    first = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}.get(first, first)
    return first in _VOWELS_AN


def _de_connector_an(word):
    """The 'de' connector, elided to "d'" before a vowel-initial word."""
    if _starts_with_vowel_an(word):
        return f"d'{word}"
    return f"de {word}"


def nice_year_an(dt, bc=False):
    """Format a year in a pronounceable Aragonese form.

    Args:
        dt (datetime): date to format (assumed already in the local timezone)
        bc (bool): append "a.C." after the year
    Returns:
        (str): the year formatted as a string
    """
    year = pronounce_number_an(dt.year)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_an(dt):
    weekday = WEEKDAYS_AN[dt.weekday()]
    return weekday.capitalize()


def nice_month_an(dt):
    month = MONTHS_AN[dt.month]
    return month.capitalize()


def nice_day_an(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_an(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_an(dt: datetime, now: datetime = None, include_weekday=True):
    """Format a date in a pronounceable Aragonese form.

    For example, generates 'luns, cinco de chunyo de 2018'.

    Args:
        dt (datetime): date to format (assumed already in the local timezone)
        now (datetime): reference date. When provided the returned date is
            shortened: the year is dropped when ``now`` is in the same year as
            ``dt`` and the month is dropped when ``now`` is in the same month.
        include_weekday (bool): whether to prepend the weekday name.
    Returns:
        (str): the formatted date string
    """
    day = pronounce_number_an(dt.day)
    month = _de_connector_an(nice_month_an(dt))
    year = _de_connector_an(nice_year_an(dt))
    nice = f"{day} {month} {year}"
    if now is not None:
        nice = day
        if dt.month != now.month:
            nice = nice + " " + _de_connector_an(nice_month_an(dt))
        if dt.year != now.year:
            nice = nice + " " + _de_connector_an(nice_year_an(dt))

    if include_weekday:
        weekday = nice_weekday_an(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_an(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a pronounceable Aragonese form.

    For example, generates 'Ye la meya pa las cinco' for speech, or '4:30'
    for display.

    Args:
        dt (datetime): time to format (assumed already in the local timezone)
        speech (bool): format for speech (True) or display (False)
        use_24hour (bool): output in 24-hour rather than 12-hour format
        use_ampm (bool): include am/pm in the 12-hour display format
    Returns:
        (str): the formatted time string
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
        # Aragonese only fixes the 12-hour spoken idiom, so a 24-hour clock
        # is read out digit by digit rather than invented.
        hour = HOURS_AN[dt.hour] if dt.hour in HOURS_AN else pronounce_number_an(dt.hour)
        if dt.minute == 0:
            return f"{hour} en punto"
        if dt.minute < 10:
            return f"{hour} zero {pronounce_number_an(dt.minute)}"
        return f"{hour} {pronounce_number_an(dt.minute)}"

    minute = dt.minute
    # 12-hour clock: 0 -> 12, 13 -> 1, ...
    hour12 = dt.hour % 12
    if hour12 == 0:
        hour12 = 12
    next_hour = hour12 % 12 + 1

    def _on_hour(h):
        if h == 1:
            return "Ye la una"
        return f"Son las {HOURS_AN[h]}"

    if minute == 0:
        return _on_hour(hour12)
    if minute == 15:
        return f"Ye lo cuarto pa las {HOURS_AN[next_hour]}"
    if minute == 30:
        return f"Ye la meya pa las {HOURS_AN[next_hour]}"
    if minute == 45:
        return f"Son los tres cuartos pa las {HOURS_AN[next_hour]}"

    if minute < 30:
        mins = pronounce_number_an(minute)
        if hour12 == 1:
            return f"Ye la una y {mins}"
        return f"Son las {HOURS_AN[hour12]} y {mins}"
    # minute > 30 (and not 45): count toward the next hour
    mins = pronounce_number_an(60 - minute)
    if next_hour == 1:
        return f"Ye la una menos {mins}"
    return f"Son las {HOURS_AN[next_hour]} menos {mins}"


def nice_date_time_an(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time in a pronounceable Aragonese form.

    Args:
        dt (datetime): date and time to format (assumed already local)
        now (datetime): reference date; when provided the date is shortened
        use_24hour (bool): output the time in 24-hour rather than 12-hour form
        use_ampm (bool): include am/pm in the 12-hour time
    Returns:
        (str): the formatted date and time string
    """
    date_str = nice_date_an(dt, now)
    time_str = nice_time_an(dt, use_24hour=use_24hour, use_ampm=use_ampm)
    return f"{date_str} a las {time_str}"


# Aragonese relative-time vocabulary.
# Sources (downloaded, browser User-Agent):
#   ~/AgentWorkspaces/papers/linguistics/an/wiktionary_hue.html,
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_hoy.html
#     (hoy -> hue / güe / ue / uey)
#   ~/AgentWorkspaces/papers/linguistics/an/wiktionary_ahiere.html,
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_ayer.html
#     (ayer -> ahiere / aiere / ayere)
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_manana.html
#     (mañana -> demá/demán [future], maitín [morning])
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_semana.html
#     (semana -> semana / siemana)
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_proximo.html
#     (próximo -> vinient / benient)
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_pasado.html
#     (pasado -> pasau)
#   ~/AgentWorkspaces/papers/linguistics/an/glosbe_hace.html
#     (hace [temporal, "en el pasado"] -> fa; the ago-marker "fa dos
#      semanas" precedes and negates the numeric offset)
#   Biquipedia "Mes"/"Tiempo" (mes, anyo, día, hora, minuto, segundo, pasau)
_NEXTS_AN = ["venient", "vinient", "siguient", "proximo", "proxima"]
_LASTS_AN = ["pasau", "pasada", "pasato", "pasata", "zaguer", "zaguera"]


def extract_duration_an(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """Convert a phrase into a duration and return the remainder text.

    The words used in the duration are consumed and the remainder of the
    text is returned. Returns None for empty input; the duration is None
    when no duration was found.

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration and the remaining unconsumed text.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["an"],
                                    resolution, replace_token)


def extract_datetime_an(text, anchorDate=None, default_time=None):
    """Convert an Aragonese date reference into an exact datetime.

    Handles "hue" (today), "manyana" (tomorrow), "ahiere" (yesterday) and
    their compounds, numeric future offsets ("3 días", "2 semanas"),
    next/last week/month/year and weekday ("la semana vinient", "lo luns
    pasau"), month + day (+ year), a month with a bare year, and clock
    times ("a las cinco", "15:30"). Past markers ("ahiere", "pasau",
    "pasada") resolve backwards. Also consumes the words it used,
    returning the remaining string.

    Structurally modelled on the Catalan/Spanish extractors (Aragonese is
    a closely related Ibero-Romance variety); vocabulary is grounded in
    the sources cited above.

    Args:
        text (str): string containing date words
        anchorDate (datetime): reference date for "manyana", etc.
        default_time (time): time to set if none was found in the string

    Returns:
        [datetime, str]: the datetime and the remaining unconsumed text,
                         or None if no date/time text was found.
    """

    def clean_string(s):
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace('!', '').replace(';', '')
        # collapse multi-word relative expressions to single tokens before
        # the "de"/"d'" elision strips their connectors
        synonyms = {
            "vinient": ["que viene", "que vien"],
            "pasadoman": ["dimpués de manyana", "dimpués de mañana", "pasau manyana", "pasau mañana",
                          "dimpues de maitín", "despús demá",
                          "l'atro maitín"],
            "antesahiere": ["antes de ahiere", "antes d'ahiere", "antes d'ahier",
                            "antes ahiere", "antis d'ahier", "antiahier"],
        }
        s = " " + s + " "
        for canon, variants in synonyms.items():
            for variant in variants:
                s = s.replace(" " + variant + " ", " " + canon + " ")
        # elide the "de"/"d'" connector and the elided article "l'"
        s = s.replace(" de ", " ").replace(" d'", " ").replace(" l'", " ") \
            .replace("d'", " ").replace("l'", " ").replace("'", " ")
        # drop the standalone articles so a clock hour and its part-of-day
        # qualifier become adjacent ("a las 9 d'o maitín" -> "9 maitín")
        for article in (" o ", " a ", " os ", " as ",
                        " lo ", " la ", " los ", " las ", " es "):
            while article in s:
                s = s.replace(article, " ")
        return s.split()

    def date_found():
        return found or \
            (
                    datestr != "" or
                    yearOffset != 0 or monthOffset != 0 or
                    dayOffset is True or dayOffset != 0 or hrOffset != 0 or
                    hrAbs or minOffset != 0 or
                    minAbs or secOffset != 0
            )

    if text == "":
        return None

    anchorDate = anchorDate or now_local()
    found = False
    daySpecified = False
    dayOffset = False
    monthOffset = 0
    yearOffset = 0
    today = anchorDate.strftime("%w")
    currentYear = anchorDate.strftime("%Y")
    fromFlag = False
    datestr = ""
    hasYear = False
    timeQualifier = ""

    timeQualifiersAM = ['maitín', 'maitino']
    timeQualifiersPM = ['tardi', 'tarde', 'tardada',
                    'nueit', 'nuei', 'nuet', 'nit']
    timeQualifiersList = timeQualifiersAM + timeQualifiersPM
    markers = ['a', 'en', 'o', 'os', 'as', 'ta', 'pa', 'enta',
               'iste', 'ista', 'este', 'esta', 'ixe', 'ixa',
               'lo', 'la', 'los', 'las', 'es']
    days = ["luns", "martes", "miercres", "chueves", "viernes",
            "sabado", "dominche"]
    day_parts = [a + b for a in days for b in timeQualifiersList]
    months = ["chinero", "febrero", "marzo", "abril", "mayo", "chunyo",
              "chuliol", "agosto", "setiembre", "octubre", "noviembre",
              "deciembre"]
    months_short = ["chin", "feb", "mar", "abr", "may", "chun", "chul",
                    "ago", "set", "oct", "nov", "dec"]
    recur_markers = days
    day_multiples = ["días", "diyas", "semanas", "meses", "anyos"]
    time_units = ["hora", "horas", "minuto", "minutos", "segundo", "segundos"]

    words = clean_string(text)

    def _clear_suffix(i):
        # blank a next/last marker that trails the matched noun/weekday
        if i < len(words):
            words[i] = ""

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        start = idx
        used = 0
        suffixIdx = None

        if word in ("agora", "aora") and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif word in timeQualifiersList:
            timeQualifier = word
        # today, tomorrow, day after tomorrow
        elif word in ("hue", "güe", "ue", "uey", "hoi") and not fromFlag:
            dayOffset = 0
            used += 1
        elif word in ("manyana", "mañana", "demán", "demá", "deman", "dema") and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "pasadoman" and not fromFlag:
            dayOffset = 2
            used += 1
        # yesterday, day before yesterday
        elif word in ("ahiere", "ahier", "ayere", "ayer") and not fromFlag:
            dayOffset = -1
            used += 1
        elif word == "antesahiere" and not fromFlag:
            dayOffset = -2
            used += 1
        # 5 days
        elif word in ("día", "diya", "días", "diyas"):
            if wordPrev[0:1].isdigit():
                dayOffset += int(wordPrev)
                start -= 1
                used = 2
        # 2 weeks, next week, last week
        elif word in ("semana", "semanas") \
                and not fromFlag:
            if wordPrev[0:1].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_AN:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LASTS_AN:
                dayOffset = -7
                start -= 1
                used = 2
            elif wordNext in _NEXTS_AN:
                dayOffset = 7
                used = 1
                suffixIdx = idx + 1
            elif wordNext in _LASTS_AN:
                dayOffset = -7
                used = 1
                suffixIdx = idx + 1
        # 10 months, next month, last month
        elif word in ("mes", "meses") and not fromFlag:
            if wordPrev[0:1].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_AN:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LASTS_AN:
                monthOffset = -1
                start -= 1
                used = 2
            elif wordNext in _NEXTS_AN:
                monthOffset = 1
                used = 1
                suffixIdx = idx + 1
            elif wordNext in _LASTS_AN:
                monthOffset = -1
                used = 1
                suffixIdx = idx + 1
        # 5 years, next year, last year
        elif word in ("anyo", "anyos", "año", "años", "an", "ans") and not fromFlag:
            if wordPrev[0:1].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_AN:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LASTS_AN:
                yearOffset = -1
                start -= 1
                used = 2
            elif wordNext in _NEXTS_AN:
                yearOffset = 1
                used = 1
                suffixIdx = idx + 1
            elif wordNext in _LASTS_AN:
                yearOffset = -1
                used = 1
                suffixIdx = idx + 1
        # Monday, next Monday, last Tuesday, etc.
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev in _NEXTS_AN:
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev in _LASTS_AN:
                dayOffset -= 7
                used += 1
                start -= 1
            elif wordNext in _NEXTS_AN:
                if dayOffset <= 2:
                    dayOffset += 7
                suffixIdx = idx + 1
            elif wordNext in _LASTS_AN:
                dayOffset -= 7
                suffixIdx = idx + 1
        elif word in day_parts and not fromFlag:
            d = day_parts.index(word) / len(timeQualifiersList)
            dayOffset = (d + 1) - int(today)
            if dayOffset < 0:
                dayOffset += 7
        # 15 de chunyo, chunyo 20, chunyo 2017
        elif word in months or word in months_short and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = months_short.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0:1].isdigit():
                datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext[0].isdigit() and \
                        wordNextNext not in time_units:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False
            elif wordNext and wordNext[0].isdigit():
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNext + " " + wordNextNext
                    used += 2
                    hasYear = True
                elif int(wordNext) > 31:
                    # a bare year after the month ("chinero 2020"): keep the
                    # year and default the day to the 1st
                    datestr += " 1 " + wordNext
                    used += 1
                    hasYear = True
                else:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = False

        # 5 días dende manyana, 2 meses dende chuliol
        validFollowups = days + months + months_short
        validFollowups.append("hue")
        validFollowups.append("manyana")
        validFollowups.append("ahiere")
        validFollowups += _NEXTS_AN
        validFollowups += _LASTS_AN
        if (word == "dende" or word == "dispués" or word == "dimpues") \
                and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "manyana":
                dayOffset += 1
            elif wordNext == "ahiere":
                dayOffset -= 1
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if tmpOffset < 0:
                    tmpOffset += 7
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = days.index(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNext in _NEXTS_AN:
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext in _LASTS_AN:
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset

        if suffixIdx is not None:
            _clear_suffix(suffixIdx)
        if used > 0:
            if start - 1 > 0 and words[start - 1] in ("iste", "ista",
                                                      "este", "esta"):
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None
    military = False

    for idx, word in enumerate(words):
        if word == "":
            continue

        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        used = 0

        if word in ("meyodía", "mediodiya", "meidía", "michdía"):
            hrAbs = 12
            used += 1
        elif word in ("meyanueit", "medianueit", "medianuet", "medianit", "meyanuei", "meyanoche"):
            hrAbs = 0
            used += 1
        elif word in timeQualifiersAM:
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word in ("tardi", "tarde", "tardada"):
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word in ("nueit", "nuei", "nuet", "nit"):
            if hrAbs is None:
                hrAbs = 19
            used += 1
        # half an hour, quarter hour
        elif word == "hora" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev in ("meya", "media"):
                minOffset = 30
            elif wordPrev == "cuarto":
                minOffset = 15
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
        elif word == "minuto" and wordPrev in ("en", "dentro", "drento", "dintro"):
            minOffset = 1
            words[idx - 1] = ""
            used += 1
        elif word == "segundo" and wordPrev in ("en", "dentro", "drento", "dintro"):
            secOffset = 1
            words[idx - 1] = ""
            used += 1
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
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
                    elif wordNext in timeQualifiersAM:
                        remainder = "am"
                        used += 1
                    elif wordNext in ("tardi", "tarde", "tardada"):
                        remainder = "pm"
                        used += 1
                    elif wordNext in ("nueit", "nuei", "nuet", "nit"):
                        if strHH and int(strHH) > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 1
                    else:
                        if timeQualifier != "":
                            military = True
                            if strHH and int(strHH) <= 12 and \
                                    (timeQualifier in timeQualifiersPM):
                                strHH += str(int(strHH) + 12)
            else:
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
                elif (wordNext in ("tardi", "tarde")):
                    strHH = strNum
                    remainder = "pm"
                    used = 1
                elif wordNext in timeQualifiersAM:
                    strHH = strNum
                    remainder = "am"
                    used = 1
                elif (
                        remainder in recur_markers or
                        wordNext in recur_markers or
                        wordNextNext in recur_markers):
                    strHH = strNum
                    used = 1
                else:
                    _after = words[idx + 2] if idx + 2 < len(words) else ""
                    pod_follows = _after in timeQualifiersList
                    if (
                            not pod_follows and
                            wordPrev in ("en", "dentro", "dintro", "drento",
                                         "dende", "fa") and
                            (wordNext == "horas" or wordNext == "hora" or
                             remainder == "horas" or remainder == "hora") and
                            word[0] != '0' and
                            (
                                    int(strNum) < 100 or
                                    int(strNum) > 2400
                            )):
                        # only a duration marker ("en 3 horas") means "in N
                        # hours"; "a las 3 horas" is not idiomatic and "a las
                        # 3" is a clock time
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minutos" or wordNext == "minuto" or \
                            remainder == "minutos" or remainder == "minuto":
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segundos" or wordNext == "segundo" \
                            or remainder == "segundos" or \
                            remainder == "segundo":
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "hora" or remainder == "hora":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if wordNextNext == "hora" or remainder == "hora":
                            used += 1
                    elif (
                            wordNext == "" or wordNext == "hora" or
                            wordNext in timeQualifiersList):
                        strHH = strNum
                        strMM = "00"
                        if wordNext == "hora":
                            used += 1
                        _pod_i = idx + used + 1
                        if _pod_i < len(words) and \
                                words[_pod_i] in timeQualifiersList:
                            if words[_pod_i] in timeQualifiersPM:
                                remainder = "pm"
                            else:
                                remainder = "am"
                            used += 1
                        if timeQualifier != "":
                            if timeQualifier in timeQualifiersPM:
                                remainder = "pm"
                                used += 1
                            elif timeQualifier in timeQualifiersAM:
                                remainder = "am"
                                used += 1
                            else:
                                used += 1
                                military = True
                    else:
                        isTime = False
            HH = int(strHH) if strHH else 0
            MM = int(strMM) if strMM else 0
            HH = HH + 12 if remainder == "pm" and HH < 12 else HH
            HH = HH - 12 if remainder == "am" and HH >= 12 else HH

            if (isTime and not military and
                    remainder not in ['am', 'pm', 'horas', 'minutos',
                                      "segundo", "segundos",
                                      "hora", "minuto"] and
                    ((not daySpecified) or dayOffset < 1)):
                if anchorDate.hour < HH or (anchorDate.hour == HH and
                                            anchorDate.minute < MM):
                    pass
                elif anchorDate.hour < HH + 12:
                    HH += 12
                else:
                    dayOffset += 1

            if timeQualifier in timeQualifiersPM and HH < 12:
                HH += 12

            if HH > 23 or MM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = HH
                minAbs = MM
                used += 1

        if used > 0:
            for i in range(used):
                if idx + i >= len(words):
                    break
                words[idx + i] = ""

            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # "fa" is the Aragonese temporal ago-marker ("fa dos semanas" = two
    # weeks ago; cf. Spanish "hace"): it negates the numeric offset that
    # follows it.
    ago = False
    for _i, _w in enumerate(words):
        if _w == "fa":
            ago = True
            words[_i] = ""
    if ago:
        if dayOffset is not False:
            dayOffset = -dayOffset
        yearOffset = -yearOffset
        monthOffset = -monthOffset
        hrOffset = -hrOffset
        minOffset = -minOffset
        secOffset = -secOffset

    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    extractedDate = anchorDate.replace(microsecond=0)

    if datestr != "":
        # explicit date such as "chunyo 5" or "chunyo 2 2017"; parse against
        # the Aragonese month names directly (strptime's "%B" only knows the
        # C-locale English names and would reject "chunyo", "chinero", ...)
        date_parts = datestr.split()
        month_num = months.index(date_parts[0]) + 1
        day_num = int(date_parts[1]) if len(date_parts) > 1 else 1
        year_num = int(date_parts[2]) if len(date_parts) > 2 else 1900
        try:
            temp = datetime(year_num, month_num, day_num)
        except ValueError:
            # a spoken date that does not exist on the calendar
            # ("31 de febrero"); report nothing rather than a wrong guess
            return None
        extractedDate = extractedDate.replace(hour=0, minute=0, second=0)
        if not hasYear:
            temp = temp.replace(year=extractedDate.year,
                                tzinfo=extractedDate.tzinfo)
            if extractedDate < temp:
                extractedDate = extractedDate.replace(
                    year=int(currentYear),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extractedDate.tzinfo)
            else:
                extractedDate = extractedDate.replace(
                    year=int(currentYear) + 1,
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extractedDate.tzinfo)
        else:
            extractedDate = extractedDate.replace(
                year=int(temp.strftime("%Y")),
                month=int(temp.strftime("%m")),
                day=int(temp.strftime("%d")),
                tzinfo=extractedDate.tzinfo)
    else:
        if hrOffset == 0 and minOffset == 0 and secOffset == 0:
            extractedDate = extractedDate.replace(hour=0, minute=0, second=0)

    try:
        if yearOffset != 0:
            extractedDate = extractedDate + relativedelta(years=yearOffset)
        if monthOffset != 0:
            extractedDate = extractedDate + relativedelta(months=monthOffset)
        if dayOffset != 0:
            extractedDate = extractedDate + relativedelta(days=dayOffset)
    except (OverflowError, ValueError):
        return None
    if hrAbs != -1 and minAbs != -1:
        if hrAbs is None and minAbs is None and default_time is not None:
            hrAbs, minAbs = default_time.hour, default_time.minute
        else:
            hrAbs = hrAbs or 0
            minAbs = minAbs or 0

        extractedDate = extractedDate.replace(hour=hrAbs, minute=minAbs)
        if (hrAbs != 0 or minAbs != 0) and datestr == "":
            if not daySpecified and anchorDate > extractedDate:
                extractedDate = extractedDate + relativedelta(days=1)
    try:
        if hrOffset != 0:
            extractedDate = extractedDate + relativedelta(hours=hrOffset)
        if minOffset != 0:
            extractedDate = extractedDate + relativedelta(minutes=minOffset)
        if secOffset != 0:
            extractedDate = extractedDate + relativedelta(seconds=secOffset)
    except (OverflowError, ValueError):
        return None
    for idx, word in enumerate(words):
        if word == "y" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]
