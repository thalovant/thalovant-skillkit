import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_bg import pronounce_number_bg, extract_number_bg
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def _int_token_bg(word):
    """Return the integer a single spelled/digit token denotes, else None."""
    if not word:
        return None
    if word.isdigit():
        return int(word)
    n = extract_number_bg(word)
    if n is False or n is None or isinstance(n, bool):
        return None
    if isinstance(n, float) and not n.is_integer():
        return None
    return int(n)


def nice_time_bg(dt, speech=True, use_24hour=True, use_ampm=False,
                 variant=None):
    """
    Format a time to a comfortable human format

    For example, generate 'осем и тридесет' (default) or 'осем и
    половина' (traditional) for speech, or '8:30' for text display.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
        variant (str): spoken register for the 12-hour clock. The default
            (None / "default") reads "<hour> и <minutes>". "traditional"
            uses the analog idiom ("осем и четвърт" = 8:15, "осем и
            половина" = 8:30, "девет без четвърт" = 8:45).
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
        # "тринадесет двадесет и две"
        speak = pronounce_number_bg(int(string[0:2]))
        speak += " "
        if string[3:5] == '00':
            speak += "нула нула"
        else:
            if string[3] == '0':
                speak += pronounce_number_bg(0) + " "
                speak += pronounce_number_bg(int(string[4]))
            else:
                speak += pronounce_number_bg(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "полунощ"
        elif dt.hour == 12 and dt.minute == 0:
            return "обед"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        next_hour = (dt.hour + 1) % 12 or 12
        if dt.minute == 0:
            unit = "час" if hour == 1 else "часа"
            speak = pronounce_number_bg(hour) + " " + unit
        elif traditional and dt.minute == 15:
            speak = pronounce_number_bg(hour) + " и четвърт"
        elif traditional and dt.minute == 30:
            speak = pronounce_number_bg(hour) + " и половина"
        elif traditional and dt.minute == 45:
            speak = pronounce_number_bg(next_hour) + " без четвърт"
        else:
            speak = pronounce_number_bg(hour) + " и " + \
                pronounce_number_bg(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                speak += " p.m."
            else:
                speak += " a.m."

        return speak


def extract_duration_bg(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["bg"],
                                    resolution, replace_token)


# Bulgarian month names are indeclinable loanwords
_MONTHS_BG = ['януари', 'февруари', 'март', 'април', 'май', 'юни',
              'юли', 'август', 'септември', 'октомври', 'ноември',
              'декември']

_MONTHS_EN = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november',
              'december']

_DAYS_BG = ['понеделник', 'вторник', 'сряда', 'четвъртък', 'петък', 'събота',
            'неделя']

# Bulgarian has lost the case system; the only inflection carried by these
# nouns is the definite-article suffix, folded back to the bare form here so
# it never leaks into a parsed value
_DAY_VARIANTS_BG = {
    'понеделникът': 'понеделник', 'понеделника': 'понеделник',
    'вторникът': 'вторник', 'вторника': 'вторник',
    'срядата': 'сряда',
    'четвъртъкът': 'четвъртък', 'четвъртъка': 'четвъртък',
    'петъкът': 'петък', 'петъка': 'петък',
    'съботата': 'събота',
    'неделята': 'неделя',
}

# canonical unit + its plural and definite-article surface forms
_UNIT_VARIANTS_BG = {
    'дни': 'ден', 'денят': 'ден', 'деня': 'ден',
    'седмици': 'седмица', 'седмицата': 'седмица',
    'месеца': 'месец', 'месеци': 'месец', 'месецът': 'месец',
    'години': 'година', 'годината': 'година',
    'минути': 'минута', 'минутата': 'минута',
    'часа': 'час', 'часове': 'час', 'часът': 'час',
    'секунди': 'секунда', 'секундата': 'секунда',
}

_NEXT_WORDS_BG = ('следващ', 'следваща', 'следващата', 'следващия',
                  'следващият', 'идния', 'идната', 'идващата', 'другата')
_LAST_WORDS_BG = ('миналия', 'миналият', 'миналата', 'минал', 'минала',
                  'предишния', 'предишната')

_MARKERS_BG = ['в', 'във', 'на', 'за', 'до', 'около', 'през', 'по', 'този',
               'тази']

# preposition introducing a future offset ("след 5 минути"). "в" is
# excluded: it marks a clock time ("в три часа" = at three), not a delay
_FUTURE_PREPS_BG = ('след',)

# cardinal hour words used in spoken clock times ("в осем",
# "осем и половина", "девет без четвърт")
_HOURS_CARDINAL_BG = {
    'един': 1, 'една': 1, 'два': 2, 'две': 2, 'три': 3, 'четири': 4,
    'пет': 5, 'шест': 6, 'седем': 7, 'осем': 8, 'девет': 9, 'десет': 10,
    'единадесет': 11, 'единайсет': 11, 'дванадесет': 12, 'дванайсет': 12,
}


def extract_datetime_bg(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "днес"
        "утре следобед"
        "в сряда в осем вечерта"
        "3 януари"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "утре", etc
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
        word = _DAY_VARIANTS_BG.get(word, word)
        word = _UNIT_VARIANTS_BG.get(word, word)
        return word

    s = text.lower().replace(',', ' ').replace('?', ' ')
    words = []
    for w in s.split():
        # strip the ordinal dot: "3. януари" -> "3 януари"
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

    timeQualifiersAM = ['сутрин', 'сутринта', 'предиобед']
    timeQualifiersPM = ['следобед', 'следобяд', 'вечер', 'вечерта', 'нощ',
                        'нощта']

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
        elif word == "днес":
            dayOffset = 0
            used = 1
        elif word == "утре":
            dayOffset = 1
            used = 1
        elif word == "вдругиден":
            dayOffset = 2
            used = 1
        elif word == "вчера":
            dayOffset = -1
            used = 1
        elif word == "завчера":
            dayOffset = -2
            used = 1
        # parse "след 5 дни", "преди 5 дни"
        elif word == "ден" and wordPrev and wordPrev[0].isdigit():
            dayOffset = (dayOffset or 0) + int(wordPrev)
            start -= 1
            used = 2
            if wordPrevPrev == "преди":
                dayOffset = -dayOffset
                start -= 1
                used += 1
        # parse "следващата седмица", "миналата седмица", "след 2 седмици"
        elif word == "седмица":
            if wordPrev and wordPrev[0].isdigit():
                dayOffset = (dayOffset or 0) + int(wordPrev) * 7
                start -= 1
                used = 2
                if wordPrevPrev == "преди":
                    dayOffset = -dayOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_BG:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_BG:
                dayOffset = -7
                start -= 1
                used = 2
        # parse "следващия месец", "след 3 месеца"
        elif word == "месец" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "преди":
                    monthOffset = -monthOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_BG:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_BG:
                monthOffset = -1
                start -= 1
                used = 2
        # parse "следващата година", "след 2 години"
        elif word == "година" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "преди":
                    yearOffset = -yearOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_BG:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_BG:
                yearOffset = -1
                start -= 1
                used = 2
        # parse weekdays: "в понеделник", "следващата сряда"
        elif word in _DAYS_BG:
            d = _DAYS_BG.index(word)
            dayOffset = (d - anchorDate.weekday()) % 7
            used = 1
            if wordPrev in _NEXT_WORDS_BG:
                if dayOffset <= 2:
                    dayOffset += 7
                start -= 1
                used += 1
            elif wordPrev in _LAST_WORDS_BG:
                dayOffset -= 7
                start -= 1
                used += 1
        # parse "3 януари", "януари 2027", "5 май 2030"
        elif word in _MONTHS_BG:
            m = _MONTHS_BG.index(word)
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
            if start - 1 >= 0 and words[start - 1] in _MARKERS_BG:
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

        if word in ("обед", "пладне", "обяд"):
            hrAbs = 12
            minAbs = 0
            used = 1
        elif word in ("полунощ",):
            hrAbs = 0
            minAbs = 0
            used = 1
        elif word in ("сутрин", "сутринта"):
            if hrAbs is None:
                hrAbs = 8
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word == "предиобед":
            if hrAbs is None:
                hrAbs = 10
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("следобед", "следобяд"):
            if hrAbs is None:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word in ("вечер", "вечерта"):
            if hrAbs is None:
                hrAbs = 19
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word in ("нощ", "нощта"):
            if hrAbs is None:
                hrAbs = 22
            elif 5 < hrAbs < 12:
                hrAbs += 12
            used = 1
        # spoken clock times: "в осем", "осем и половина" (8:30), "осем и
        # четвърт" (8:15), "девет без четвърт" (8:45)
        elif word in _HOURS_CARDINAL_BG and not (
                wordPrev in _FUTURE_PREPS_BG and
                wordNext in ("минута", "час", "секунда")):
            value = _HOURS_CARDINAL_BG[word]
            used = 1
            wordNextNext = normalize(words[idx + 2]) \
                if idx + 2 < len(words) else ""
            if wordNext == "и" and wordNextNext == "половина":
                hrAbs = value
                minAbs = 30
                used += 2
            elif wordNext == "и" and wordNextNext in ("четвърт", "петнадесет",
                                                      "петнайсет"):
                hrAbs = value
                minAbs = 15
                used += 2
            elif wordNext == "без" and wordNextNext in ("четвърт",
                                                        "петнадесет",
                                                        "петнайсет"):
                hrAbs = value - 1
                minAbs = 45
                used += 2
            elif wordPrev in ("в", "във", "около"):
                hrAbs = value
                minAbs = 0
                if wordNext == "час":
                    used += 1
            else:
                used = 0
            if used:
                if timeQualifier in timeQualifiersPM and 0 <= hrAbs < 12:
                    hrAbs += 12
                elif timeQualifier in timeQualifiersAM and hrAbs >= 12:
                    hrAbs -= 12
        # spelled future offsets: "след десет минути", "след три часа"
        elif wordPrev in _FUTURE_PREPS_BG and \
                wordNext in ("минута", "час", "секунда") and \
                not word[0].isdigit() and _int_token_bg(word) is not None:
            value = _int_token_bg(word)
            if wordNext == "минута":
                minOffset = value
            elif wordNext == "час":
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
                # parse "след 5 минути", "след 3 часа", "след 30 секунди"
                if wordNext in ("минута", "час", "секунда") and \
                        wordPrev in _FUTURE_PREPS_BG:
                    value = int(word)
                    if wordNext == "минута":
                        minOffset = value
                    elif wordNext == "час":
                        hrOffset = value
                    else:
                        secOffset = value
                    hrAbs = -1
                    minAbs = -1
                    start -= 1
                    used = 3
                elif int(word) <= 24 and \
                        (wordPrev in ("в", "във", "около") or
                         wordNext == "час"):
                    # "в 8", "в 17 часа"
                    strHH = word
                    used = 1
                    if wordNext == "час":
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
            if start - 1 >= 0 and words[start - 1] in _MARKERS_BG:
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
