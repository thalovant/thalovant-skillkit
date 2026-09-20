"""Norwegian Nynorsk (nn) date and time parsing.

Ported from the Danish (da) module — the nearest Scandinavian relative —
and adapted to Nynorsk orthography and the modern tens-first counting
reform ("tjueein" = 21). Number and ordinal words come from
:mod:`ovos_number_parser.numbers_nn`; month, weekday, article and
time-of-day vocabulary follow Nynorskordboka / Språkrådet. Nynorsk
differs from Bokmål in weekday names (tysdag, laurdag), "i morgon"
vs "i morgen", veke/månad noun forms, and neuter "eitt".
"""
import re
from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_nn import (pronounce_ordinal_nn,
                                           pronounce_number_nn, is_ordinal_nn,
                                           numbers_to_digits_nn)
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


_MONTHS_NN = ['januar', 'februar', 'mars', 'april', 'mai', 'juni',
              'juli', 'august', 'september', 'oktober', 'november',
              'desember']


def nice_time_nn(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format

    For example, generate 'fem tretti' for speech or '5:30' for
    text display.

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

    if not speech:
        return string

    speak = ""
    if use_24hour:
        if dt.hour == 1:
            speak += "eitt"  # klokka 01:00 is "eitt"
        else:
            speak += pronounce_number_nn(dt.hour)
        if not dt.minute == 0:
            if dt.minute < 10:
                speak += ' null'
            speak += " " + pronounce_number_nn(dt.minute)

        return speak  # ampm is ignored when use_24hour is true
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "midnatt"
        if dt.hour == 12 and dt.minute == 0:
            return "middag"

        if dt.hour == 0:
            speak += pronounce_number_nn(12)
        elif dt.hour <= 13:
            if dt.hour == 1 or dt.hour == 13:  # 01:00 and 13:00 is "eitt"
                speak += 'eitt'
            else:
                speak += pronounce_number_nn(dt.hour)
        else:
            speak += pronounce_number_nn(dt.hour - 12)

        if not dt.minute == 0:
            if dt.minute < 10:
                speak += ' null'
            speak += " " + pronounce_number_nn(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                if dt.hour < 18:
                    speak += " om ettermiddagen"
                elif dt.hour < 22:
                    speak += " om kvelden"
                else:
                    speak += " om natta"
            elif dt.hour < 3:
                speak += " om natta"
            else:
                speak += " om morgonen"

        return speak


def _nice_ordinal_nn(text, speech=True):
    # inflect ordinals that precede a month name (e.g. "den 3. mai")
    normalized_text = text
    words = text.split()

    for idx, word in enumerate(words):
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        if word[-1:] == ".":
            if word[:-1].isdecimal():
                if wordNext.lower() in _MONTHS_NN:
                    word = pronounce_ordinal_nn(int(word[:-1]))
                    words[idx] = word
            normalized_text = " ".join(words)
    return normalized_text


def extract_datetime_nn(text, anchorDate=None, default_time=None):
    def clean_string(s):
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace(' den ', ' ').replace(' det ', ' ') \
            .replace(' om ', ' ').replace(' på ', ' ')
        wordList = s.split()

        for idx, word in enumerate(wordList):
            if is_ordinal_nn(word) is not False:
                word = str(is_ordinal_nn(word))
                wordList[idx] = word

        return wordList

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

    anchorDate = anchorDate or now_local()
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

    timeQualifiersList = ['tidleg',
                          'morgon',
                          'morgonen',
                          'formiddag',
                          'formiddagen',
                          'ettermiddag',
                          'ettermiddagen',
                          'kveld',
                          'kvelden',
                          'natt',
                          'natta']
    markers = ['i', 'om', 'på', 'klokka', 'klokken', 'ved']
    days = ['måndag', 'tysdag', 'onsdag',
            'torsdag', 'fredag', 'laurdag', 'søndag']
    months = _MONTHS_NN
    monthsShort = ['jan', 'feb', 'mar', 'apr', 'mai', 'jun', 'jul', 'aug',
                   'sep', 'okt', 'nov', 'des']

    validFollowups = days + months + monthsShort
    validFollowups.append("i dag")
    validFollowups.append("morgon")
    validFollowups.append("neste")
    validFollowups.append("førre")
    validFollowups.append("no")

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
        if word == "morgon" and wordPrev == "i" and not fromFlag:
            # "i morgon" = tomorrow, bare "morgon" = morning
            dayOffset = 1
            used += 1
        elif word == "overmorgon" and not fromFlag:
            dayOffset = 2
            used += 1
        elif word in timeQualifiersList:
            timeQualifier = word
        elif word == "dag" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "morgon" and not fromFlag and wordPrev != "om" and \
                wordPrev not in days:  # "morgon" alone means tomorrow
            dayOffset = 1
            used += 1
        elif word == "dag" or word == "dagar":
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sidan" = N periods in the past (Nynorskordboka)
                if wordNext == "sidan":
                    dayOffset -= int(wordPrev)
                    used += 1
                else:
                    dayOffset += int(wordPrev)
                start -= 1
                used += 2
        elif (word == "veke" or word == "veker") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sidan" = N periods in the past (Nynorskordboka)
                if wordNext == "sidan":
                    dayOffset -= int(wordPrev) * 7
                    used += 1
                else:
                    dayOffset += int(wordPrev) * 7
                start -= 1
                used += 2
            elif wordPrev[:5] == "neste":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev[:5] == "førre":
                dayOffset = -7
                start -= 1
                used = 2
        elif (word == "månad" or word == "månader") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sidan" = N periods in the past (Nynorskordboka)
                if wordNext == "sidan":
                    monthOffset = -int(wordPrev)
                    used += 1
                else:
                    monthOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev[:5] == "neste":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:5] == "førre":
                monthOffset = -1
                start -= 1
                used = 2
        elif word == "år" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sidan" = N periods in the past (Nynorskordboka)
                if wordNext == "sidan":
                    yearOffset = -int(wordPrev)
                    used += 1
                else:
                    yearOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev[:5] == "neste":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:5] == "førre":
                yearOffset = -1
                start -= 1
                used = 2
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordNext == "morgon":
                words[idx + 1] = "tidleg"
            if wordPrev[:5] == "neste":
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev[:5] == "førre":
                dayOffset -= 7
                used += 1
                start -= 1
        elif word in months or word in monthsShort and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
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
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

        if (word == "frå" or word == "til" or word == "om") and wordNext \
                in validFollowups:
            used = 2
            fromFlag = True
            if wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                if tmpOffset < 0:
                    tmpOffset += 7
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = days.index(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNext[:5] == "neste":
                    tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext[:5] == "førre":
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1].startswith("denne"):
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
    timeStr = ""
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

        used = 0
        if word[:6] == "middag":
            hrAbs = 12
            used += 1
        elif word[:7] == "midnatt":
            hrAbs = 0
            used += 1
        elif word == "morgonen" or word == "tidleg":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word[:11] == "ettermiddag":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word[:5] == "kveld":
            if not hrAbs:
                hrAbs = 19
            used += 1
        elif word == "time" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev[:4] == "halv":
                minOffset = 30
            elif wordPrev == "kvarter" or wordPrev == "kvart":
                minOffset = 15
            elif wordPrev == "trekvarter":
                minOffset = 45
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
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
                    elif wordNext == "morgon" or wordNext == "morgonen":
                        remainder = "am"
                        used += 1
                    elif wordNext == "ettermiddag" or \
                            wordNext == "ettermiddagen":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "kveld" or wordNext == "kvelden":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "natta":
                        if strHH and int(strHH) > 4:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 1
                    else:
                        if timeQualifier != "":
                            if strHH and int(strHH) <= 12 and \
                                    (timeQualifier == "kvelden" or
                                     timeQualifier == "ettermiddagen"):
                                strHH = str(int(strHH) + 12)
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
                    remainder = wordNext.replace(".", "").strip()

                if remainder in ("pm", "p.m."):
                    strHH = strNum
                    remainder = "pm"
                    used = 1
                elif remainder in ("am", "a.m."):
                    strHH = strNum
                    remainder = "am"
                    used = 1
                else:
                    if wordNext in ("time", "timar", "timer") and \
                            int(word) < 100:
                        hrOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext in ("minutt", "minuttar", "minutter"):
                        minOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext in ("sekund", "sekundar", "sekunder"):
                        secOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "time":
                        strHH = strNum
                        used += 1
                        isTime = True
                        if is_numeric(wordNextNext):
                            strMM = wordNextNext
                            used += 1
                    elif wordNext == timeQualifier:
                        strHH = strNum
                        strMM = "00"
                        isTime = True
                        if wordNext[:11] == "ettermiddag":
                            used += 1
                            remainder = "pm"
                        elif wordNext[:5] == "kveld":
                            used += 1
                            remainder = "pm"
                        elif wordNext[:6] == "morgon":
                            used += 1
                            remainder = "am"
                        elif wordNext == "natta":
                            used += 1
                            if 8 <= int(word) <= 12:
                                remainder = "pm"
                            else:
                                remainder = "am"

            strHH = int(strHH) if strHH else 0
            strMM = int(strMM) if strMM else 0
            strHH = strHH + 12 if remainder == "pm" and strHH < 12 else strHH
            strHH = strHH - 12 if remainder == "am" and strHH >= 12 else strHH
            if strHH > 24 or strMM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = strHH * 1
                minAbs = strMM * 1
                used += 1
        if used > 0:
            for i in range(used):
                words[idx + i] = ""

            if wordPrev == "tidleg":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "sein":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # purely relative time keeps the anchor time of day
        extractedDate = extractedDate.replace(microsecond=0, second=0)
    else:
        extractedDate = extractedDate.replace(microsecond=0,
                                              second=0,
                                              minute=0,
                                              hour=0)
    if datestr != "":
        en_months = ['january', 'february', 'march', 'april', 'may', 'june',
                     'july', 'august', 'september', 'october', 'november',
                     'december']
        en_monthsShort = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july',
                          'aug', 'sept', 'oct', 'nov', 'dec']
        for idx, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months[idx]) + r"\b",
                             en_month, datestr)
        for idx, en_month in enumerate(en_monthsShort):
            datestr = re.sub(r"\b" + re.escape(monthsShort[idx]) + r"\b",
                             en_month, datestr)

        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # an impossible calendar date like "30 februar"; report nothing
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
    for idx, word in enumerate(words):
        if words[idx] == "og" and idx > 0 and words[idx - 1] == "" \
                and idx + 1 < len(words) and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())

    return [extractedDate, resultStr]


def extract_duration_nn(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """
    Convert a phrase into a duration and return the remainder text.

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration and the remaining unconsumed text.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["nn"],
                                    resolution, replace_token)
