from datetime import datetime, timedelta
import re

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_nl import pronounce_number_nl, extract_number_nl, numbers_to_digits_nl
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def extract_duration_nl(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["nl"],
                                    resolution, replace_token)


def extract_datetime_nl(text, anchorDate=None, default_time=None):
    """Convert a human date reference into an exact datetime

    Convert things like
        "today"
        "tomorrow afternoon"
        "next Tuesday at 4pm"
        "August 3rd"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.  For example, the string
       "what is Tuesday's weather forecast"
    returns the date for the forthcoming Tuesday relative to the reference
    date and the remainder string
       "what is weather forecast".

    The "next" instance of a day or weekend is considered to be no earlier than
    48 hours in the future. On Friday, "next Monday" would be in 3 days.
    On Saturday, "next Monday" would be in 9 days.

    Args:
        text (str): string containing date words
        dateNow (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s):
        # clean unneeded punctuation and capitalization among other things.
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace(' de ', ' ').replace(' het ', ' ').replace(' het ', ' ') \
            .replace("paar", "2").replace("eeuwen", "eeuw") \
            .replace("decennia", "decennium") \
            .replace("millennia", "millennium")

        wordList = s.split()
        for idx, word in enumerate(wordList):
            ordinals = ["ste", "de"]
            if word and word[0].isdigit():
                for ordinal in ordinals:
                    # "second" is the only case we should not do this
                    if ordinal in word and "second" not in word:
                        word = word.replace(ordinal, "")
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
    today = anchorDate.strftime("%w")
    currentYear = anchorDate.strftime("%Y")
    fromFlag = False
    datestr = ""
    hasYear = False
    timeQualifier = ""

    timeQualifiersAM = ['ochtend']
    timeQualifiersPM = ['middag', 'avond', 'nacht']
    timeQualifiersList = timeQualifiersAM + timeQualifiersPM
    timeQualifierOffsets = [8, 15, 19, 0]
    markers = ['op', 'in', 'om', 'tegen', 'over',
               'deze', 'rond', 'voor', 'van', "binnen"]
    days = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag",
            "zaterdag", "zondag"]
    day_parts = [a + b for a in days for b in timeQualifiersList]
    months = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
              'juli', 'augustus', 'september', 'oktober', 'november',
              'december']
    recur_markers = days + [d + 'en' for d in days] + ['weekeinde', 'werkdag',
                                                       'weekeinden', 'werkdagen']
    months_short = ['jan', 'feb', 'mar', 'apr', 'mei', 'jun', 'jul', 'aug',
                    'sep', 'okt', 'nov', 'dec']
    year_multiples = ["decennium", "eeuw", "millennium"]
    day_multiples = ["dagen", "weken", "maanden", "jaren"]
    time_units = ["uur", "uren", "minuut", "minuten", "seconde", "seconden"]

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
        # save timequalifier for later

        if word == "nu" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_nl(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if wordNext == "decennium":
                yearOffset = multiplier * 10
            elif wordNext == "eeuw":
                yearOffset = multiplier * 100
            elif wordNext == "millennium":
                yearOffset = multiplier * 1000
        # paar
        elif word == "2" and \
                wordNextNext in year_multiples:
            multiplier = 2
            used += 2
            if wordNextNext == "decennia":
                yearOffset = multiplier * 10
            elif wordNextNext == "eeuwen":
                yearOffset = multiplier * 100
            elif wordNextNext == "millennia":
                yearOffset = multiplier * 1000
        elif word == "2" and \
                wordNextNext in day_multiples:
            multiplier = 2
            used += 2
            if wordNextNext == "jaren":
                yearOffset = multiplier
            elif wordNextNext == "maanden":
                monthOffset = multiplier
            elif wordNextNext == "weken":
                dayOffset = multiplier * 7
        elif word in timeQualifiersList:
            timeQualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "vandaag" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "morgen" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "overmorgen" and not fromFlag:
            dayOffset = 2
            used += 1
            # parse 5 days, 10 weeks, last week, next week
        elif word == "dag" or word == "dagen":
            if wordPrev and wordPrev[0].isdigit():
                # "N ... geleden" = N periods in the past (Van Dale)
                if wordNext == "geleden":
                    dayOffset -= int(wordPrev)
                    used += 1
                else:
                    dayOffset += int(wordPrev)
                start -= 1
                used += 2
        elif word == "week" or word == "weken" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... geleden" = N periods in the past (Van Dale)
                if wordNext == "geleden":
                    dayOffset -= int(wordPrev) * 7
                    used += 1
                else:
                    dayOffset += int(wordPrev) * 7
                start -= 1
                used += 2
            elif wordPrev == "volgende":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev == "vorige":
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif (word == "maand" or word == "maanden") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... geleden" = N periods in the past (Van Dale)
                if wordNext == "geleden":
                    monthOffset = -int(wordPrev)
                    used += 1
                else:
                    monthOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev == "volgende":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "vorige":
                monthOffset = -1
                start -= 1
                used = 2
        # parse 5 years, next year, last year
        elif (word == "jaar" or word == "jaren") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... geleden" = N periods in the past (Van Dale)
                if wordNext == "geleden":
                    yearOffset = -int(wordPrev)
                    used += 1
                else:
                    yearOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev == "volgend":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "vorig":
                yearOffset = -1
                start -= 1
                used = 2
        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev == "volgende":
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "vorige":
                dayOffset -= 7
                used += 1
                start -= 1
        elif word in day_parts and not fromFlag:
            d = day_parts.index(word) / len(timeQualifiersList)
            dayOffset = (d + 1) - int(today)
            if dayOffset < 0:
                dayOffset += 7
                # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in months_short and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = months_short.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and \
                    (wordPrev and wordPrev[0].isdigit() or (wordPrev == "van" and
                                               wordPrevPrev and wordPrevPrev[0].isdigit())):
                if wordPrev == "van" and wordPrevPrev and wordPrevPrev[0].isdigit():
                    datestr += " " + words[idx - 2]
                    used += 1
                    start -= 1
                else:
                    datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext[0].isdigit() and \
                        wordNextNext not in time_units:
                    # a bare clock hour following the date ("15 juni 3 uur")
                    # must not be swallowed as the year
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

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + months_short
        validFollowups.append("vandaag")
        validFollowups.append("morgen")
        validFollowups.append("volgende")
        validFollowups.append("vorige")
        validFollowups.append("nu")
        if (word == "van" or word == "na") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "morgen":
                dayOffset += 1
            elif wordNext == "overmorgen":
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
                if wordNext == "volgende":
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext == "vorige":
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] == "deze":
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
        # parse nacht ochtend, middag, avond
        used = 0
        if word.startswith("gister"):
            dayOffset = -1
        elif word.startswith("morgen"):
            dayOffset = 1

        if word.endswith("nacht"):
            if hrAbs is None:
                hrAbs = 0
            used += 1
        elif word.endswith("ochtend"):
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word.endswith("middag"):
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word.endswith("avond"):
            if hrAbs is None:
                hrAbs = 19
            used += 1

        # "paar" time_unit
        elif word == "2" and \
                wordNextNext in ["uur", "minuten", "seconden"]:
            used += 2
            if wordNextNext == "uur":
                hrOffset = 2
            elif wordNextNext == "minuten":
                minOffset = 2
            elif wordNextNext == "seconden":
                secOffset = 2
        # parse half an hour, quarter hour
        elif word == "uur" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev == "half":
                minOffset = 30
            elif wordPrev == "kwartier":
                minOffset = 15
            elif wordPrevPrev == "kwartier":
                minOffset = 15
                if idx > 2 and words[idx - 3] in markers:
                    words[idx - 3] = ""
                    if words[idx - 3] == "deze":
                        daySpecified = True
                words[idx - 2] = ""
            elif wordPrev == "binnen":
                hrOffset = 1
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "deze":
                    daySpecified = True
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
            # parse 5:00 am, 12:00 p.m., etc
        # parse "over een minuut"
        elif word == "minuut" and wordPrev == "over":
            minOffset = 1
            words[idx - 1] = ""
            used += 1
        # parse "over een seconde"
        elif word == "seconde" and wordPrev == "over":
            secOffset = 1
            words[idx - 1] = ""
            used += 1
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            wordNextNextNext = words[idx + 3] \
                if idx + 3 < len(words) else ""
            if wordNext == "vannacht" or wordNextNext == "vannacht" or \
                    wordPrev == "vannacht" or wordPrevPrev == "vannacht" or \
                    wordNextNextNext == "vannacht":
                remainder = "pm"
                used += 1
                if wordPrev == "vannacht":
                    words[idx - 1] = ""
                if wordPrevPrev == "vannacht":
                    words[idx - 2] = ""
                if wordNextNext == "vannacht":
                    used += 1
                if wordNextNextNext == "vannacht":
                    used += 1

            if ':' in word:
                # parse colons
                # "3:00 in the morning"
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

                    elif wordNext == "in" and wordNextNext == "ochtend":
                        remainder = "am"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "middag":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "avond":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "'s" and wordNextNext == "ochtends":
                        remainder = "am"
                        used += 2
                    elif wordNext == "'s" and wordNextNext == "middags":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "'s" and wordNextNext == "avonds":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "deze" and wordNextNext == "ochtend":
                        remainder = "am"
                        used = 2
                        daySpecified = True
                    elif wordNext == "deze" and wordNextNext == "middag":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "deze" and wordNextNext == "avond":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "'s" and wordNextNext == "nachts":
                        if strHH and int(strHH) > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 2

                    else:
                        if timeQualifier != "":
                            military = True
                            if strHH and int(strHH) <= 12 and \
                                    (timeQualifier in timeQualifiersPM):
                                strHH += str(int(strHH) + 12)

            else:
                # try to parse numbers without colons
                # 5 hours, 10 minutes etc.
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
                    # Ex: "7 on mondays" or "3 this friday"
                    # Set strHH so that isTime == True
                    # when am or pm is not specified
                    strHH = strNum
                    used = 1
                else:
                    # "3 uur 's middags" is a clock time, not "in 3 hours";
                    # a part-of-day right after the hour disambiguates it
                    _after_uur = words[idx + 2] if idx + 2 < len(words) else ""
                    _after_uur2 = words[idx + 3] if idx + 3 < len(words) else ""
                    pod_follows = (
                        (_after_uur == "'s" and _after_uur2 in
                         ("ochtends", "middags", "avonds", "nachts")) or
                        _after_uur in timeQualifiersList)
                    if (
                            not pod_follows and
                            (wordNext == "uren" or wordNext == "uur" or
                             remainder == "uren" or remainder == "uur") and
                            word[0] != '0' and
                            (
                                    int(strNum) < 100 or
                                    int(strNum) > 2400
                            )):
                        # ignores military time
                        # "in 3 hours"
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1

                    elif wordNext == "minuten" or wordNext == "minuut" or \
                            remainder == "minuten" or remainder == "minuut":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "seconden" or wordNext == "seconde" \
                            or remainder == "seconden" or \
                            remainder == "seconde":
                        # in 5 seconds
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif int(strNum) > 100:
                        # military time, eg. "3300 hours"
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "uur" or remainder == "uur":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        # military time, e.g. "04 38 hours"
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if (wordNextNext == "uur" or remainder == "uur"):
                            used += 1
                    elif (
                            wordNext == "" or wordNext == "uur" or
                            (
                                    wordNext == "in" and
                                    (
                                            wordNextNext == "de" or
                                            wordNextNext == timeQualifier
                                    )
                            ) or wordNext == 'vannacht' or
                            wordNextNext == 'vannacht'):

                        strHH = strNum
                        strMM = "00"
                        if wordNext == "uur":
                            used += 1

                        # part of day expressed genitively after the hour:
                        # "3 uur 's middags" -> pm, "8 uur 's avonds" -> pm
                        genitive_pod = {"ochtends": "am", "middags": "pm",
                                        "avonds": "pm", "nachts": "am"}
                        _pod_i = idx + used + 1
                        _pod_next = words[_pod_i + 1] \
                            if _pod_i + 1 < len(words) else ""
                        if _pod_i < len(words) and words[_pod_i] == "'s" \
                                and _pod_next in genitive_pod:
                            remainder = genitive_pod[_pod_next]
                            used += 2

                        if wordNext == "in" or wordNextNext == "in":
                            used += (1 if wordNext == "in" else 2)
                            wordNextNextNext = words[idx + 3] \
                                if idx + 3 < len(words) else ""

                            if (wordNextNext and
                                    (wordNextNext in timeQualifier or
                                     wordNextNextNext in timeQualifier)):
                                if (wordNextNext in timeQualifiersPM or
                                        wordNextNextNext in timeQualifiersPM):
                                    remainder = "pm"
                                    used += 1
                                if (wordNextNext in timeQualifiersAM or
                                        wordNextNextNext in timeQualifiersAM):
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
                                # TODO: Unsure if this is 100% accurate
                                used += 1
                                military = True
                    else:
                        isTime = False
            HH = int(strHH) if strHH else 0
            MM = int(strMM) if strMM else 0
            HH = HH + 12 if remainder == "pm" and HH < 12 else HH
            HH = HH - 12 if remainder == "am" and HH >= 12 else HH

            if (not military and
                    remainder not in ['am', 'pm', 'uren', 'minuten',
                                      "seconde", "seconden",
                                      "uur", "minuut"] and
                    ((not daySpecified) or dayOffset < 1)):
                # ambiguous time, detect whether they mean this evening or
                # the next morning based on whether it has already passed
                if anchorDate.hour < HH or (anchorDate.hour == HH and
                                            anchorDate.minute < MM):
                    pass  # No modification needed
                elif anchorDate.hour < HH + 12:
                    HH += 12
                else:
                    # has passed, assume the next morning
                    dayOffset += 1

            if timeQualifier in timeQualifiersPM and HH < 12:
                HH += 12

            if HH > 23 or MM > 59:
                # a clock value like "24:00" or "25:30" is not a real time;
                # reject it rather than building an out-of-range datetime
                isTime = False
                used = 0
            if isTime:
                hrAbs = HH
                minAbs = MM
                used += 1

        if used > 0:
            # removed parsed words from the sentence
            for i in range(used):
                if idx + i >= len(words):
                    break
                words[idx + i] = ""

            if wordPrev == "vroeg":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "laat":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
                if wordPrev == "deze":
                    daySpecified = True
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "deze":
                    daySpecified = True

            idx += used - 1
            found = True
    # check that we found a date
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation

    extractedDate = anchorDate.replace(microsecond=0)

    if datestr != "":
        # date included an explicit date, e.g. "juni 5" or "juni 2 2017".
        # parse against the Dutch month names directly; strptime's "%B"
        # only knows C-locale English names and would reject "juni",
        # "maart", "augustus", etc.
        date_parts = datestr.split()
        month_num = months.index(date_parts[0]) + 1
        day_num = int(date_parts[1]) if len(date_parts) > 1 else 1
        year_num = int(date_parts[2]) if len(date_parts) > 2 else 1900
        try:
            temp = datetime(year_num, month_num, day_num)
        except ValueError:
            # an explicit date was spoken but it does not exist on the
            # calendar (e.g. "30 februari" or "29 februari 2019"); report
            # nothing rather than a wrong guess
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

    try:
        if yearOffset != 0:
            extractedDate = extractedDate + relativedelta(years=yearOffset)
        if monthOffset != 0:
            extractedDate = extractedDate + relativedelta(months=monthOffset)
        if dayOffset != 0:
            extractedDate = extractedDate + relativedelta(days=dayOffset)
    except (OverflowError, ValueError):
        # an absurd offset like "999999999999 uur" overflows the datetime
        # range; report nothing rather than crashing
        return None
    if hrAbs != -1 and minAbs != -1:
        # If no time was supplied in the string set the time to default
        # time if it's available
        if hrAbs is None and minAbs is None and default_time is not None:
            hrAbs, minAbs = default_time.hour, default_time.minute
        else:
            hrAbs = hrAbs or 0
            minAbs = minAbs or 0

        extractedDate = extractedDate.replace(hour=hrAbs,
                                              minute=minAbs)
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
        # an absurd offset like "999999999999 uur" overflows the datetime
        # range; report nothing rather than crashing
        return None
    for idx, word in enumerate(words):
        if word == "en" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def nice_time_nl(dt, speech=True, use_24hour=False, use_ampm=False):
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
        speak += pronounce_number_nl(dt.hour)
        speak += " uur"
        if not dt.minute == 0:  # zero minutes are not pronounced, 13:00 is
            # "13 uur" not "13 hundred hours"
            speak += " " + pronounce_number_nl(dt.minute)
        return speak  # ampm is ignored when use_24hour is true
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "Middernacht"
        hour = dt.hour % 12
        if dt.minute == 0:
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)
            speak += " uur"
        elif dt.minute == 30:
            speak += "half "
            hour += 1
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)
        elif dt.minute == 15:
            speak += "kwart over "
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)
        elif dt.minute == 45:
            speak += "kwart voor "
            hour += 1
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)
        elif dt.minute > 30:
            speak += pronounce_number_nl(60 - dt.minute)
            speak += " voor "
            hour += 1
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)
        else:
            speak += pronounce_number_nl(dt.minute)
            speak += " over "
            hour = _fix_hour_nl(hour)
            speak += pronounce_number_nl(hour)

        if use_ampm:
            speak += nice_part_of_day_nl(dt)

        return speak


def _fix_hour_nl(hour):
    hour = hour % 12
    if hour == 0:
        hour = 12
    return hour


def nice_part_of_day_nl(dt, speech=True):
    if dt.hour < 6:
        return " 's nachts"
    if dt.hour < 12:
        return " 's ochtends"
    if dt.hour < 18:
        return " 's middags"
    if dt.hour < 24:
        return " 's avonds"
    raise ValueError('dt.hour is bigger than 24')
