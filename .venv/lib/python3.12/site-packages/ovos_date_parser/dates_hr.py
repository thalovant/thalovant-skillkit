import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_hr import pronounce_number_hr, extract_number_hr
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def _int_token_hr(word):
    """Return the integer a single spelled/digit token denotes, else None."""
    if not word:
        return None
    if word.isdigit():
        return int(word)
    n = extract_number_hr(word)
    if n is False or n is None or isinstance(n, bool):
        return None
    if isinstance(n, float) and not n.is_integer():
        return None
    return int(n)


def _plural_sat_hr(hour):
    """Return the correct declension of 'sat' (hour) for a cardinal count."""
    if hour == 1:
        return "sat"
    if 2 <= hour <= 4:
        return "sata"
    return "sati"


def nice_time_hr(dt, speech=True, use_24hour=False, use_ampm=False,
                 variant=None):
    """
    Format a time to a comfortable human format

    For example, generate 'osam i trideset' (default) or 'pola devet'
    (traditional) for speech, or '8:30' for text display.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
        variant (str): spoken register for the 12-hour clock. The default
            (None / "default") reads "<hour> i <minutes>". "traditional"
            uses the analog idiom ("osam i petnaest" = 8:15,
            "pola devet" = 8:30, "petnaest do devet" = 8:45).
    Returns:
        (str): The formatted time string
    """
    traditional = variant in ("traditional", "analog")
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
    if use_24hour:
        # "trinaest dvadeset dva"
        speak = pronounce_number_hr(int(string[0:2]))
        speak += " "
        if string[3:5] == '00':
            speak += "nula nula"
        else:
            if string[3] == '0':
                speak += pronounce_number_hr(0) + " "
                speak += pronounce_number_hr(int(string[4]))
            else:
                speak += pronounce_number_hr(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "ponoć"
        elif dt.hour == 12 and dt.minute == 0:
            return "podne"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        next_hour = (dt.hour + 1) % 12 or 12
        if dt.minute == 0:
            speak = pronounce_number_hr(hour) + " " + _plural_sat_hr(hour)
        elif traditional and dt.minute == 30:
            speak = "pola " + pronounce_number_hr(next_hour)
        elif traditional and dt.minute == 45:
            speak = "petnaest do " + pronounce_number_hr(next_hour)
        else:
            speak = pronounce_number_hr(hour) + " i " + \
                pronounce_number_hr(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                speak += " p.m."
            else:
                speak += " a.m."

        return speak


def extract_duration_hr(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["hr"],
                                    resolution, replace_token)


_MONTHS_HR = ['siječanj', 'veljača', 'ožujak', 'travanj', 'svibanj', 'lipanj',
              'srpanj', 'kolovoz', 'rujan', 'listopad', 'studeni',
              'prosinac']

_MONTHS_EN = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november',
              'december']

# genitive month forms ("3. siječnja")
_MONTH_VARIANTS_HR = {
    'siječnja': 'siječanj', 'siječnju': 'siječanj',
    'veljače': 'veljača', 'veljači': 'veljača',
    'ožujka': 'ožujak', 'ožujku': 'ožujak',
    'travnja': 'travanj', 'travnju': 'travanj',
    'svibnja': 'svibanj', 'svibnju': 'svibanj',
    'lipnja': 'lipanj', 'lipnju': 'lipanj',
    'srpnja': 'srpanj', 'srpnju': 'srpanj',
    'kolovoza': 'kolovoz', 'kolovozu': 'kolovoz',
    'rujna': 'rujan', 'rujnu': 'rujan',
    'listopada': 'listopad', 'listopadu': 'listopad',
    'studenog': 'studeni', 'studenoga': 'studeni', 'studenom': 'studeni',
    'prosinca': 'prosinac', 'prosincu': 'prosinac',
}

_DAYS_HR = ['ponedjeljak', 'utorak', 'srijeda', 'četvrtak', 'petak', 'subota',
            'nedjelja']

# accusative weekday forms ("u srijedu", "u subotu", "u nedjelju")
_DAY_VARIANTS_HR = {
    'srijedu': 'srijeda', 'srijedi': 'srijeda',
    'subotu': 'subota', 'suboti': 'subota',
    'nedjelju': 'nedjelja', 'nedjelji': 'nedjelja',
    'ponedjeljkom': 'ponedjeljak', 'utorkom': 'utorak',
    'četvrtkom': 'četvrtak', 'petkom': 'petak',
}

# unit words normalized to a canonical form
_UNIT_VARIANTS_HR = {
    'dana': 'dan', 'dani': 'dan', 'danu': 'dan', 'danom': 'dan',
    'tjedna': 'tjedan', 'tjedni': 'tjedan', 'tjednu': 'tjedan',
    'tjedana': 'tjedan',
    'mjeseca': 'mjesec', 'mjeseci': 'mjesec', 'mjesecu': 'mjesec',
    'mjeseca': 'mjesec',
    'godine': 'godina', 'godinu': 'godina', 'godina': 'godina',
    'godini': 'godina', 'godinama': 'godina',
    'minute': 'minuta', 'minutu': 'minuta', 'minuta': 'minuta',
    'minuti': 'minuta',
    'sata': 'sat', 'sati': 'sat', 'satu': 'sat',
    'sekunde': 'sekunda', 'sekundu': 'sekunda', 'sekundi': 'sekunda',
}

_NEXT_WORDS_HR = ('sljedeći', 'sljedeća', 'sljedeću', 'sljedeće',
                  'idući', 'iduća', 'iduću', 'iduće', 'naredni', 'naredna',
                  'narednu')
_LAST_WORDS_HR = ('prošli', 'prošla', 'prošlu', 'prošle', 'prethodni',
                  'prethodna', 'prethodnu')

_MARKERS_HR = ['u', 'na', 'za', 'do', 'o', 'oko', 'ovaj', 'ovu', 'kroz']

# prepositions introducing a future offset ("za 5 minuta", "kroz 5 minuta")
_FUTURE_PREPS_HR = ('za', 'kroz')

# cardinal hour words used in spoken clock times ("u osam", "pola devet")
_HOURS_CARDINAL_HR = {
    'jedan': 1, 'jedne': 1, 'dva': 2, 'dvije': 2, 'tri': 3, 'četiri': 4,
    'pet': 5, 'šest': 6, 'sedam': 7, 'osam': 8, 'devet': 9, 'deset': 10,
    'jedanaest': 11, 'dvanaest': 12,
}


def extract_datetime_hr(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "danas"
        "sutra poslijepodne"
        "u srijedu u osam navečer"
        "3. siječnja"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "sutra", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """
    if not text:
        return None

    anchorDate = anchorDate or now_local()
    currentYear = anchorDate.strftime("%Y")

    def normalize(word):
        word = _DAY_VARIANTS_HR.get(word, word)
        word = _MONTH_VARIANTS_HR.get(word, word)
        word = _UNIT_VARIANTS_HR.get(word, word)
        return word

    s = text.lower().replace(',', ' ').replace('?', ' ')
    words = []
    for w in s.split():
        # strip the ordinal dot: "3. siječnja" -> "3 siječnja"
        if w.endswith('.') and w[:-1].isdigit():
            w = w[:-1]
        words.append(w)

    found = False
    daySpecified = False
    dayOffset = False
    monthOffset = 0
    yearOffset = 0
    datestr = ""
    hasYear = False
    timeQualifier = ""

    timeQualifiersAM = ['ujutro', 'prijepodne', 'prijepodnevu']
    timeQualifiersPM = ['poslijepodne', 'popodne', 'navečer', 'uvečer',
                        'noću']

    # parse date references
    for idx, word in enumerate(words):
        if word == "":
            continue
        word = normalize(word)
        wordPrev = normalize(words[idx - 1]) if idx > 0 else ""
        wordPrevPrev = normalize(words[idx - 2]) if idx > 1 else ""
        wordNext = normalize(words[idx + 1]) if idx + 1 < len(words) else ""
        wordNextNext = normalize(words[idx + 2]) if idx + 2 < len(words) else ""
        start = idx
        used = 0

        if word in timeQualifiersAM or word in timeQualifiersPM:
            timeQualifier = word
        elif word == "danas":
            dayOffset = 0
            used = 1
        elif word == "sutra":
            dayOffset = 1
            used = 1
        elif word == "prekosutra":
            dayOffset = 2
            used = 1
        elif word == "jučer":
            dayOffset = -1
            used = 1
        elif word == "prekjučer":
            dayOffset = -2
            used = 1
        # parse "za 5 dana", "prije 5 dana"
        elif word == "dan" and wordPrev and wordPrev[0].isdigit():
            dayOffset = (dayOffset or 0) + int(wordPrev)
            start -= 1
            used = 2
            if wordPrevPrev == "prije":
                dayOffset = -dayOffset
                start -= 1
                used += 1
        # parse "sljedeći tjedan", "prošli tjedan", "za 2 tjedna"
        elif word == "tjedan":
            if wordPrev and wordPrev[0].isdigit():
                dayOffset = (dayOffset or 0) + int(wordPrev) * 7
                start -= 1
                used = 2
                if wordPrevPrev == "prije":
                    dayOffset = -dayOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_HR:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_HR:
                dayOffset = -7
                start -= 1
                used = 2
        # parse "sljedeći mjesec", "za 3 mjeseca"
        elif word == "mjesec" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "prije":
                    monthOffset = -monthOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_HR:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_HR:
                monthOffset = -1
                start -= 1
                used = 2
        # parse "sljedeća godina", "za 2 godine"
        elif word == "godina" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "prije":
                    yearOffset = -yearOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_HR:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_HR:
                yearOffset = -1
                start -= 1
                used = 2
        # parse weekdays: "u ponedjeljak", "sljedeću srijedu"
        elif word in _DAYS_HR:
            d = _DAYS_HR.index(word)
            dayOffset = (d - anchorDate.weekday()) % 7
            used = 1
            if wordPrev in _NEXT_WORDS_HR:
                if dayOffset <= 2:
                    dayOffset += 7
                start -= 1
                used += 1
            elif wordPrev in _LAST_WORDS_HR:
                dayOffset -= 7
                start -= 1
                used += 1
        # parse "3. siječnja", "siječanj 2027", "5. svibnja 2030"
        elif word in _MONTHS_HR:
            m = _MONTHS_HR.index(word)
            datestr = _MONTHS_EN[m]
            used = 1
            if wordPrev and wordPrev[0].isdigit():
                datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext.isdigit() and len(wordNext) == 4:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
            elif wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext.isdigit() and \
                        len(wordNextNext) == 4:
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True

        if used > 0:
            for i in range(used):
                if 0 <= start + i < len(words):
                    words[start + i] = ""
            if start - 1 >= 0 and words[start - 1] in _MARKERS_HR:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None

    for idx, word in enumerate(words):
        if word == "":
            continue
        word = normalize(word)
        wordPrev = normalize(words[idx - 1]) if idx > 0 else ""
        wordPrevPrev = normalize(words[idx - 2]) if idx > 1 else ""
        wordNext = normalize(words[idx + 1]) if idx + 1 < len(words) else ""
        start = idx
        used = 0

        if word in ("podne", "podnevu"):
            hrAbs = 12
            minAbs = 0
            used = 1
        elif word in ("ponoć", "ponoći"):
            hrAbs = 0
            minAbs = 0
            used = 1
        elif word == "ujutro":
            if hrAbs is None:
                hrAbs = 8
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("prijepodne",):
            if hrAbs is None:
                hrAbs = 10
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("poslijepodne", "popodne"):
            if hrAbs is None:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word in ("navečer", "uvečer"):
            if hrAbs is None:
                hrAbs = 19
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word == "noću":
            if hrAbs is None:
                hrAbs = 22
            elif 5 < hrAbs < 12:
                hrAbs += 12
            used = 1
        # spoken clock times: "u osam", "pola devet" (8:30, "pola" counts
        # to the next hour), "petnaest do devet" (8:45), "osam i petnaest"
        elif word in _HOURS_CARDINAL_HR and not (
                wordPrev in _FUTURE_PREPS_HR and
                wordNext in ("minuta", "sat", "sekunda")):
            value = _HOURS_CARDINAL_HR[word]
            used = 1
            if wordPrev == "pola":
                hrAbs = value - 1
                minAbs = 30
                start -= 1
                used += 1
            elif wordPrev == "do" and wordPrevPrev in ("petnaest", "četvrt"):
                hrAbs = value - 1
                minAbs = 45
                start -= 2
                used += 2
            elif wordPrev in ("u", "oko"):
                hrAbs = value
                minAbs = 0
                if wordNext == "i" and \
                        normalize(words[idx + 2] if idx + 2 < len(words)
                                  else "") in ("petnaest", "četvrt"):
                    minAbs = 15
                    used += 2
                elif wordNext in ("i", "sat", "sati"):
                    used += 1
            else:
                used = 0
            if used:
                if timeQualifier in timeQualifiersPM and 0 <= hrAbs < 12:
                    hrAbs += 12
                elif timeQualifier in timeQualifiersAM and hrAbs >= 12:
                    hrAbs -= 12
        # spelled future offsets: "za deset minuta", "za tri sata"
        elif wordPrev in _FUTURE_PREPS_HR and \
                wordNext in ("minuta", "sat", "sekunda") and \
                not word[0].isdigit() and _int_token_hr(word) is not None:
            value = _int_token_hr(word)
            if wordNext == "minuta":
                minOffset = value
            elif wordNext == "sat":
                hrOffset = value
            else:
                secOffset = value
            hrAbs = -1
            minAbs = -1
            start -= 1
            used = 3
        elif word and word[0].isdigit():
            strHH = ""
            strMM = ""
            if ':' in word:
                components = word.replace('.', '').split(':')
                if len(components) == 2 and components[0].isdigit() and \
                        components[1].isdigit():
                    strHH, strMM = components
                    used = 1
            elif word.isdigit():
                # parse "za 5 minuta", "kroz 3 sata", "za 30 sekundi"
                if wordNext in ("minuta", "sat", "sekunda") and \
                        wordPrev in _FUTURE_PREPS_HR:
                    value = int(word)
                    if wordNext == "minuta":
                        minOffset = value
                    elif wordNext == "sat":
                        hrOffset = value
                    else:
                        secOffset = value
                    hrAbs = -1
                    minAbs = -1
                    start -= 1
                    used = 3
                elif int(word) <= 24 and \
                        (wordPrev in ("u", "oko") or wordNext == "sat"):
                    # "u 8", "u 17 sati"
                    strHH = word
                    used = 1
                    if wordNext == "sat":
                        used += 1
            if strHH:
                HH = int(strHH)
                MM = int(strMM) if strMM else 0
                if HH <= 24 and MM <= 59:
                    if timeQualifier in timeQualifiersPM and 0 < HH < 12:
                        HH += 12
                    elif timeQualifier in timeQualifiersAM and HH >= 12:
                        HH -= 12
                    hrAbs = HH % 24
                    minAbs = MM
                else:
                    used = 0

        if used > 0:
            for i in range(used):
                if 0 <= start + i < len(words):
                    words[start + i] = ""
            if start - 1 >= 0 and words[start - 1] in _MARKERS_HR:
                words[start - 1] = ""
            found = True

    # check that we found a date
    if not found and not datestr:
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation
    extractedDate = anchorDate.replace(microsecond=0)
    if datestr != "":
        try:
            temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                try:
                    temp = datetime.strptime(datestr + " 1", "%B %d")
                except ValueError:
                    # an impossible calendar date; report nothing
                    # rather than a wrong guess
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
        # ignore the current HH:MM:SS if relative using days or greater
        if hrOffset == 0 and minOffset == 0 and secOffset == 0:
            extractedDate = extractedDate.replace(hour=0, minute=0, second=0)

    if yearOffset != 0:
        extractedDate = extractedDate + relativedelta(years=yearOffset)
    if monthOffset != 0:
        extractedDate = extractedDate + relativedelta(months=monthOffset)
    if dayOffset != 0:
        extractedDate = extractedDate + relativedelta(days=dayOffset)
    if hrAbs != -1 and minAbs != -1:
        # If no time was supplied in the string set the time to default
        # time if it's available
        if hrAbs is None and minAbs is None and default_time is not None:
            hrAbs, minAbs = default_time.hour, default_time.minute
        else:
            hrAbs = hrAbs or 0
            minAbs = minAbs or 0

        extractedDate = extractedDate + relativedelta(hours=hrAbs,
                                                      minutes=minAbs)
        if (hrAbs != 0 or minAbs != 0) and datestr == "":
            if not daySpecified and anchorDate > extractedDate:
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
