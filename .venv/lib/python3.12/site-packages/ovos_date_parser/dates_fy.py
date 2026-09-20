from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_fy import pronounce_number_fy, extract_number_fy
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

# West Frisian (Frysk) weekday names.
# Sources: West Frisian phrasebook (Wikivoyage) and West Frisian language
# (Wikipedia). "Sneon" is the standard form for Saturday; "Saterdei" also
# occurs regionally.
WEEKDAYS_FY = {
    0: "moandei",
    1: "tiisdei",
    2: "woansdei",
    3: "tongersdei",
    4: "freed",
    5: "sneon",
    6: "snein"
}
# West Frisian month names.
# Source: West Frisian phrasebook (Wikivoyage).
MONTHS_FY = {
    1: "jannewaris",
    2: "febrewaris",
    3: "maart",
    4: "april",
    5: "maaie",
    6: "juny",
    7: "july",
    8: "augustus",
    9: "septimber",
    10: "oktober",
    11: "novimber",
    12: "desimber"
}
# Inflected hour forms used after "healwei", "kertier oer/foar" and the
# "minutes oer/foar" constructions when telling the time.
# Source: "Telling Time in West Frisian"
# (funwithfrisian.blogspot.com/2016/04/telling-time-in-west-frisian.html).
HOURS_FY = {
    1: "ienen",
    2: "twaen",
    3: "trijen",
    4: "fjouweren",
    5: "fiven",
    6: "seizen",
    7: "sânen",
    8: "achten",
    9: "njoggenen",
    10: "tsienen",
    11: "alven",
    12: "tolven"
}


def _fix_hour_fy(hour):
    hour = hour % 12
    if hour == 0:
        hour = 12
    return hour


def nice_year_fy(dt, bc=False):
    """Format a year in a pronounceable West Frisian form.

    Args:
        dt (datetime): date to format (assumed already in the local timezone)
        bc (bool): append "f.Kr." after the year
    Returns:
        (str): the year formatted as a string
    """
    year = pronounce_number_fy(dt.year)
    if bc:
        return f"{year} f.Kr."
    return year


def nice_weekday_fy(dt):
    weekday = WEEKDAYS_FY[dt.weekday()]
    return weekday.capitalize()


def nice_month_fy(dt):
    month = MONTHS_FY[dt.month]
    return month.capitalize()


def nice_day_fy(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_fy(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_fy(dt: datetime, now: datetime = None, include_weekday=True):
    """Format a date in a pronounceable West Frisian form.

    For example, generates 'moandei 5 maaie 2018'. West Frisian keeps the
    Germanic day-month-year order.

    Args:
        dt (datetime): date to format (assumed already in the local timezone)
        now (datetime): reference date. When provided the returned date is
            shortened: the year is dropped when ``now`` is in the same year as
            ``dt`` and the month is dropped when ``now`` is in the same month.
        include_weekday (bool): whether to prepend the weekday name.
    Returns:
        (str): the formatted date string
    """
    day = pronounce_number_fy(dt.day)
    nice = f"{day} {nice_month_fy(dt)} {nice_year_fy(dt)}"
    if now is not None:
        nice = day
        if dt.month != now.month:
            nice = nice + " " + nice_month_fy(dt)
        if dt.year != now.year:
            nice = nice + " " + nice_year_fy(dt)

    if include_weekday:
        weekday = nice_weekday_fy(dt)
        nice = f"{weekday} {nice}"
    return nice


def nice_date_time_fy(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time in a pronounceable West Frisian form.

    For example, generates 'moandei 5 maaie 2018 om fjouwer oere'.
    """
    return f"{nice_date_fy(dt, now)} om " \
           f"{nice_time_fy(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_part_of_day_fy(dt, speech=True):
    """Return the West Frisian adverbial name for the part of the day.

    Source: Taalportaal / West Frisian phrasebook — the genitive "-s" adverbs
    moarns, middeis, jûns, nachts.
    """
    if dt.hour < 6:
        return " nachts"
    if dt.hour < 12:
        return " moarns"
    if dt.hour < 18:
        return " middeis"
    return " jûns"


def nice_time_fy(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a comfortable West Frisian human format.

    For example, generates 'healwei fiven' for speech or '4:30' for text.

    West Frisian, like Dutch, looks ahead to the coming hour for the half and
    the quarter-to: 'healwei fiven' is 4:30 (literally "halfway to five") and
    'kertier foar fiven' is 4:45. The hour word is "oere".

    Args:
        dt (datetime): date to format (assumed already in the local timezone)
        speech (bool): format for speech (default/True) or display (False)
        use_24hour (bool): output in 24-hour format
        use_ampm (bool): include the part of day for 12-hour format
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
        if string[0] == '0':
            string = string[1:]  # strip leading zeros

    if not speech:
        return string

    speak = ""
    if use_24hour:
        speak += pronounce_number_fy(dt.hour)
        speak += " oere"
        if dt.minute != 0:
            speak += " " + pronounce_number_fy(dt.minute)
        return speak  # ampm is ignored when use_24hour is true

    hour = dt.hour % 12
    if dt.minute == 0:
        hour = _fix_hour_fy(hour)
        speak += pronounce_number_fy(hour)
        speak += " oere"
    elif dt.minute == 15:
        hour = _fix_hour_fy(hour)
        speak += "kertier oer " + HOURS_FY[hour]
    elif dt.minute == 30:
        hour = _fix_hour_fy(hour + 1)
        speak += "healwei " + HOURS_FY[hour]
    elif dt.minute == 45:
        hour = _fix_hour_fy(hour + 1)
        speak += "kertier foar " + HOURS_FY[hour]
    elif dt.minute < 30:
        hour = _fix_hour_fy(hour)
        speak += pronounce_number_fy(dt.minute) + " oer " + HOURS_FY[hour]
    else:
        hour = _fix_hour_fy(hour + 1)
        speak += pronounce_number_fy(60 - dt.minute) + " foar " + HOURS_FY[hour]

    if use_ampm:
        speak += nice_part_of_day_fy(dt)

    return speak


# West Frisian relative-time vocabulary.
# Sources (downloaded, browser User-Agent):
#   ~/AgentWorkspaces/papers/linguistics/fy/wikivoyage_phrasebook.html
#     (Wikivoyage "West Frisian phrasebook" — hjoed=today, moarn=tomorrow,
#      juster=yesterday, wike=week, moanne=month, jier=year, dei=day,
#      "dizze wike"=this week, "ôfrûne/foarige wike"=last week,
#      "oare wike"=next week, no=now, morning/afternoon/evening/night)
#   ~/AgentWorkspaces/papers/linguistics/fy/wiktionary_juster.html
#     (Wiktionary "juster" — West Frisian adverb "yesterday")
#   ~/AgentWorkspaces/papers/linguistics/fy/wiktionary_hjoed.html,
#   ~/AgentWorkspaces/papers/linguistics/fy/wiktionary_moarn.html
#   ~/AgentWorkspaces/papers/linguistics/fy/wiktionary_lyn.html
#     (Wiktionary "lyn" — West Frisian adverb "ago", "twa jier lyn" = two
#      years ago; the ago-postposition negates numeric offsets)
_NEXTS_FY = ["oare", "oar", "folgjende", "kommende"]
_LASTS_FY = ["foarige", "foarich", "ôfrûne", "lêste", "ferline", "ferrûne"]


def extract_duration_fy(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["fy"],
                                    resolution, replace_token)


def extract_datetime_fy(text, anchorDate=None, default_time=None):
    """Convert a West Frisian date reference into an exact datetime.

    Handles "hjoed" (today), "moarn" (tomorrow), "juster" (yesterday) and
    their compounds, numeric future offsets ("3 dagen", "2 wiken"),
    next/last week/month/year and weekday ("oare tiisdei", "foarige
    freed"), month + day (+ year), a month with a bare year, and clock
    times. Past markers ("juster", "foarige", "ôfrûne") resolve backwards.
    Also consumes the words it used, returning the remaining string.

    Ported from :func:`extract_datetime_nl` (West Frisian is closely
    related to Dutch); vocabulary is grounded in the sources cited above.

    Args:
        text (str): string containing date words
        anchorDate (datetime): reference date for "moarn", etc.
        default_time (time): time to set if none was found in the string

    Returns:
        [datetime, str]: the datetime and the remaining unconsumed text,
                         or None if no date/time text was found.
    """

    def clean_string(s):
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace(" de ", " ").replace(" it ", " ").replace(" 'e ", " ") \
            .replace("pear", "2")

        wordList = s.split()
        for idx, word in enumerate(wordList):
            ordinals = ["ste", "de"]
            if word and word[0].isdigit():
                for ordinal in ordinals:
                    if ordinal in word:
                        word = word.replace(ordinal, "")
            wordList[idx] = word
        return wordList

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

    timeQualifiersAM = ['moarns']
    timeQualifiersPM = ['middeis', 'jûns', 'nachts']
    timeQualifiersList = timeQualifiersAM + timeQualifiersPM
    markers = ['op', 'yn', 'om', 'tsjin', 'oer',
               'dizze', 'rûn', 'foar', 'fan', "binnen"]
    days = ["moandei", "tiisdei", "woansdei", "tongersdei", "freed",
            "sneon", "snein"]
    day_parts = [a + b for a in days for b in timeQualifiersList]
    months = ['jannewaris', 'febrewaris', 'maart', 'april', 'maaie', 'juny',
              'july', 'augustus', 'septimber', 'oktober', 'novimber',
              'desimber']
    recur_markers = days + ['wykein', 'wurkdei', 'wykeinen', 'wurkdagen']
    months_short = ['jan', 'feb', 'mrt', 'apr', 'mai', 'jun', 'jul', 'aug',
                    'sep', 'okt', 'nov', 'des']
    year_multiples = ["desennium", "ieu", "millennium"]
    day_multiples = ["dagen", "wiken", "moannen", "jierren"]
    time_units = ["oere", "oeren", "minút", "minuten", "sekonde", "sekonden"]

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        start = idx
        used = 0

        if word == "no" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_fy(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if wordNext == "desennium":
                yearOffset = multiplier * 10
            elif wordNext == "ieu":
                yearOffset = multiplier * 100
            elif wordNext == "millennium":
                yearOffset = multiplier * 1000
        elif word in timeQualifiersList:
            timeQualifier = word
        # today, tomorrow, day after tomorrow
        elif word == "hjoed" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "moarn" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word in ("oaremoarn", "oaremoarns") and not fromFlag:
            dayOffset = 2
            used += 1
        # yesterday, day before yesterday
        elif word == "juster" and not fromFlag:
            dayOffset = -1
            used += 1
        elif word in ("eargister", "eergister") and not fromFlag:
            dayOffset = -2
            used += 1
        # 5 days, 10 weeks, last week, next week
        elif word == "dei" or word == "dagen":
            if wordPrev[0:1].isdigit():
                dayOffset += int(wordPrev)
                start -= 1
                used = 2
        elif word == "wike" or word == "wiken" and not fromFlag:
            if wordPrev[0:1].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_FY:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LASTS_FY:
                dayOffset = -7
                start -= 1
                used = 2
        # 10 months, next month, last month
        elif word in ("moanne", "moannen") and not fromFlag:
            if wordPrev[0:1].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_FY:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LASTS_FY:
                monthOffset = -1
                start -= 1
                used = 2
        # 5 years, next year, last year
        elif (word == "jier" or word == "jierren") and not fromFlag:
            if wordPrev[0:1].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev in _NEXTS_FY:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LASTS_FY:
                yearOffset = -1
                start -= 1
                used = 2
        # Monday, next Monday, last Tuesday, etc.
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev in _NEXTS_FY:
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev in _LASTS_FY:
                dayOffset -= 7
                used += 1
                start -= 1
        elif word in day_parts and not fromFlag:
            d = day_parts.index(word) / len(timeQualifiersList)
            dayOffset = (d + 1) - int(today)
            if dayOffset < 0:
                dayOffset += 7
        # 15 of July, June 20th, Feb 18
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
                    # a bare year after the month ("juny 2020"): keep the
                    # year and default the day to the 1st
                    datestr += " 1 " + wordNext
                    used += 1
                    hasYear = True
                else:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = False

        # 5 days from tomorrow, 2 months from July
        validFollowups = days + months + months_short
        validFollowups.append("hjoed")
        validFollowups.append("moarn")
        validFollowups += _NEXTS_FY
        validFollowups += _LASTS_FY
        validFollowups.append("no")
        if (word == "fan" or word == "nei") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "moarn":
                dayOffset += 1
            elif wordNext in ("oaremoarn", "oaremoarns"):
                dayOffset += 2
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
                if wordNext in _NEXTS_FY:
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext in _LASTS_FY:
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] == "dizze":
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
        if word.startswith("juster"):
            dayOffset = -1

        if word.endswith("nachts"):
            if hrAbs is None:
                hrAbs = 0
            used += 1
        elif word.endswith("moarns"):
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word.endswith("middeis"):
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word.endswith("jûns"):
            if hrAbs is None:
                hrAbs = 19
            used += 1
        elif word == "2" and \
                wordNextNext in ["oere", "minuten", "sekonden"]:
            used += 2
            if wordNextNext == "oere":
                hrOffset = 2
            elif wordNextNext == "minuten":
                minOffset = 2
            elif wordNextNext == "sekonden":
                secOffset = 2
        # half an hour, quarter hour
        elif word == "oere" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev == "heal":
                minOffset = 30
            elif wordPrev == "kertier":
                minOffset = 15
            elif wordPrevPrev == "kertier":
                minOffset = 15
                if idx > 2 and words[idx - 3] in markers:
                    words[idx - 3] = ""
                words[idx - 2] = ""
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
        elif word == "minút" and wordPrev == "oer":
            minOffset = 1
            words[idx - 1] = ""
            used += 1
        elif word == "sekonde" and wordPrev == "oer":
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
                    elif wordNext == "moarns":
                        remainder = "am"
                        used += 1
                    elif wordNext in ("middeis", "jûns"):
                        remainder = "pm"
                        used += 1
                    elif wordNext == "nachts":
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
                            wordPrev in ("oer", "binnen", "yn") and
                            (wordNext == "oeren" or wordNext == "oere" or
                             remainder == "oeren" or remainder == "oere") and
                            word[0] != '0' and
                            (
                                    int(strNum) < 100 or
                                    int(strNum) > 2400
                            )):
                        # only a duration marker ("oer/binnen/yn 3 oere")
                        # means "in N hours"; "om 5 oere" is a clock time
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minuten" or wordNext == "minút" or \
                            remainder == "minuten" or remainder == "minút":
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "sekonden" or wordNext == "sekonde" \
                            or remainder == "sekonden" or \
                            remainder == "sekonde":
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "oere" or remainder == "oere":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if wordNextNext == "oere" or remainder == "oere":
                            used += 1
                    elif (
                            wordNext == "" or wordNext == "oere" or
                            wordNext in timeQualifiersList):
                        strHH = strNum
                        strMM = "00"
                        if wordNext == "oere":
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
                    remainder not in ['am', 'pm', 'oeren', 'minuten',
                                      "sekonde", "sekonden",
                                      "oere", "minút"] and
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

            if wordPrev == "betiid":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "let":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # "lyn" is the West Frisian ago-postposition ("twa wiken lyn" = two
    # weeks ago): it negates the numeric offset it trails.
    ago = False
    for _i, _w in enumerate(words):
        if _w == "lyn":
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
        # explicit date such as "juny 5" or "juny 2 2017"; parse against the
        # West Frisian month names directly (strptime's "%B" only knows the
        # C-locale English names and would reject "juny", "maart", ...)
        date_parts = datestr.split()
        month_num = months.index(date_parts[0]) + 1
        day_num = int(date_parts[1]) if len(date_parts) > 1 else 1
        year_num = int(date_parts[2]) if len(date_parts) > 2 else 1900
        try:
            temp = datetime(year_num, month_num, day_num)
        except ValueError:
            # a spoken date that does not exist on the calendar
            # ("30 febrewaris"); report nothing rather than a wrong guess
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
        if word == "en" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]
