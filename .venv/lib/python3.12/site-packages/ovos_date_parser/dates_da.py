import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_da import pronounce_ordinal_da, pronounce_number_da, is_ordinal_da, numbers_to_digits_da
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local, DAYS_IN_1_YEAR, DAYS_IN_1_MONTH
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


_MONTHS_DA = ['januar', 'februar', 'marts', 'april', 'maj', 'juni',
              'juli', 'august', 'september', 'oktober', 'november',
              'december']


def nice_time_da(dt, speech=True, use_24hour=False, use_ampm=False):
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

    if not speech:
        return string

    # Generate a speakable version of the time
    speak = ""
    if use_24hour:
        if dt.hour == 1:
            speak += "et"  # 01:00 is "et" not "en"
        else:
            speak += pronounce_number_da(dt.hour)
        if not dt.minute == 0:
            if dt.minute < 10:
                speak += ' nul'
            speak += " " + pronounce_number_da(dt.minute)

        return speak  # ampm is ignored when use_24hour is true
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "midnat"
        if dt.hour == 12 and dt.minute == 0:
            return "middag"

        # idiomatic quarter/half hours: "kvart over tre" (3:15), "halv fire"
        # (3:30 - counts towards the NEXT hour, not "half past three"),
        # "kvart i fire" (3:45). This is how these times are normally
        # spoken in Danish, not as two separate digits.
        hour12 = dt.hour % 12 or 12
        nextHour12 = (hour12 % 12) + 1

        def _speakHour(h):
            return 'et' if h == 1 else pronounce_number_da(h)

        if dt.minute == 15:
            speak += "kvart over " + _speakHour(hour12)
        elif dt.minute == 30:
            speak += "halv " + _speakHour(nextHour12)
        elif dt.minute == 45:
            speak += "kvart i " + _speakHour(nextHour12)
        else:
            if dt.hour == 0:
                speak += pronounce_number_da(12)
            elif dt.hour <= 13:
                if dt.hour == 1 or dt.hour == 13:  # 01:00 and 13:00 is "et"
                    speak += 'et'
                else:
                    speak += pronounce_number_da(dt.hour)
            else:
                speak += pronounce_number_da(dt.hour - 12)

            if not dt.minute == 0:
                if dt.minute < 10:
                    speak += ' nul'
                speak += " " + pronounce_number_da(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                if dt.hour < 18:
                    # 12:01 - 17:59 nachmittags/afternoon
                    speak += " om eftermiddagen"
                elif dt.hour < 22:
                    # 18:00 - 21:59 abends/evening
                    speak += " om aftenen"
                else:
                    # 22:00 - 23:59 nachts/at night
                    speak += " om natten"
            elif dt.hour < 3:
                # 00:01 - 02:59 nachts/at night
                speak += " om natten"
            else:
                # 03:00 - 11:59 morgens/in the morning
                speak += " om morgenen"

        return speak


def _nice_ordinal_da(text, speech=True):
    # check for months for declension of ordinals before months
    # depending on articles/prepositions
    normalized_text = text
    words = text.split()

    for idx, word in enumerate(words):
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        if word[-1:] == ".":
            if word[:-1].isdecimal():
                if wordNext.lower() in _MONTHS_DA:
                    word = pronounce_ordinal_da(int(word[:-1]))
                    if wordPrev.lower() in ["om", "den", "fra", "til",
                                            "(fra", "(om", "til"]:
                        word += "n"
                    elif wordPrev.lower() not in ["den"]:
                        word += "r"
                    words[idx] = word
            normalized_text = " ".join(words)
    return normalized_text


def extract_datetime_da(text, anchorDate=None, default_time=None):
    def clean_string(s):
        """
            cleans the input string of unneeded punctuation
            and capitalization among other things.

            'am' is a preposition, so cannot currently be used
            for 12 hour date format
        """

        s = numbers_to_digits_da(s)
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace(' den ', ' ').replace(' det ', ' ').replace(' om ',
                                                                 ' ').replace(
            ' om ', ' ') \
            .replace(' på ', ' ').replace(' om ', ' ')
        wordList = s.split()

        for idx, word in enumerate(wordList):
            if is_ordinal_da(word) is not False:
                word = str(is_ordinal_da(word))
                wordList[idx] = word

        return wordList

    def date_found():
        return found or \
            (
                    datestr != "" or timeStr != "" or
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

    timeQualifiersList = ['tidlig',
                          'morgen',
                          'morgenen',
                          'formidag',
                          'formiddagen',
                          'eftermiddag',
                          'eftermiddagen',
                          'aften',
                          'aftenen',
                          'nat',
                          'natten']
    markers = ['i', 'om', 'på', 'klokken', 'ved']
    days = ['mandag', 'tirsdag', 'onsdag',
            'torsdag', 'fredag', 'lørdag', 'søndag']
    months = ['januar', 'februar', 'marts', 'april', 'maj', 'juni',
              'juli', 'august', 'september', 'oktober', 'november',
              'december']
    monthsShort = ['jan', 'feb', 'mar', 'apr', 'maj', 'juni', 'juli', 'aug',
                   'sep', 'okt', 'nov', 'dec']

    validFollowups = days + months + monthsShort
    validFollowups.append("i dag")
    validFollowups.append("morgen")
    validFollowups.append("næste")
    validFollowups.append("forrige")
    validFollowups.append("nu")

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
        if word == "morgen" and wordPrev == "i" and not fromFlag:
            # "i morgen" = tomorrow, while bare "morgen" = morning
            dayOffset = 1
            used += 1
        elif word == "overmorgen" and wordPrev == "i" and not fromFlag:
            dayOffset = 2
            used += 1
        elif word in timeQualifiersList:
            timeQualifier = word
            # parse today, tomorrow, day after tomorrow
        elif word == "dag" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "morgen" and not fromFlag and wordPrev != "om" and \
                wordPrev not in days:  # morgen means tomorrow if not "am
            # Morgen" and not [day of the week] morgen
            dayOffset = 1
            used += 1
        elif word == "overmorgen" and not fromFlag:
            dayOffset = 2
            used += 1
            # parse 5 days, 10 weeks, last week, next week
        elif word == "dag" or word == "dage":
            if wordPrev and wordPrev[0].isdigit():
                # "N ... siden" = N periods in the past (DDO)
                if wordNext == "siden":
                    dayOffset -= int(wordPrev)
                    used += 1
                else:
                    dayOffset += int(wordPrev)
                start -= 1
                used += 2
        elif word == "uge" or word == "uger" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... siden" = N periods in the past (DDO)
                if wordNext == "siden":
                    dayOffset -= int(wordPrev) * 7
                    used += 1
                else:
                    dayOffset += int(wordPrev) * 7
                start -= 1
                used += 2
            elif wordPrev[:6] == "næste":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev[:7] == "forrige":
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif (word == "måned" or word == "måneder") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... siden" = N periods in the past (DDO)
                if wordNext == "siden":
                    monthOffset = -int(wordPrev)
                    used += 1
                else:
                    monthOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev[:6] == "næste":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:7] == "forrige":
                monthOffset = -1
                start -= 1
                used = 2
                # parse 5 years, next year, last year
        elif word == "år" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... siden" = N periods in the past (DDO)
                if wordNext == "siden":
                    yearOffset = -int(wordPrev)
                    used += 1
                else:
                    yearOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev[:6] == "næste":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:7] == "forrige":
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
            if wordNext == "morgen":
                # morgen means morning if preceded by
                # the day of the week
                words[idx + 1] = "tidlig"
            if wordPrev[:6] == "næste":
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev[:7] == "forrige":
                dayOffset -= 7
                used += 1
                start -= 1
                # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in monthsShort and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and (wordPrev and wordPrev[0].isdigit() or
                             (wordPrev == "of" and wordPrevPrev and wordPrevPrev[0].isdigit())):
                if wordPrev == "of" and wordPrevPrev and wordPrevPrev[0].isdigit():
                    datestr += " " + words[idx - 2]
                    used += 1
                    start -= 1
                else:
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
        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July

        if (
                word == "fra" or word == "til" or word == "om") and wordNext \
                in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "morgenen" and \
                    wordPrev != "om" and \
                    wordPrev not in days:
                # morgen means tomorrow if not "am Morgen" and not
                # [day of the week] morgen:
                dayOffset += 1
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
                if wordNext[:6] == "næste":
                    tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext[:7] == "forrige":
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
        wordNextNextNext = words[idx + 3] if idx + 3 < len(words) else ""
        wordNextNextNextNext = words[idx + 4] if idx + 4 < len(words) else ""

        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word[:6] == "middag":
            hrAbs = 12
            used += 1
        elif word[:11] == "midnat":
            hrAbs = 0
            used += 1
        elif word == "morgenen" or (
                wordPrev == "om" and word == "morgenen") or word == "tidlig":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word[:11] == "eftermiddag":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word[:5] == "aften":
            if not hrAbs:
                hrAbs = 19
            used += 1
            # parse half an hour, quarter hour
        elif word == "time" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev[:4] == "halv":
                minOffset = 30
            elif wordPrev == "kvarter":
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
            # parse 5:00 am, 12:00 p.m., etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
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
                    elif nextWord == "aften":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "om" and wordNextNext == "morgenen":
                        remainder = "am"
                        used += 2
                    elif wordNext == "om" and wordNextNext == "eftermiddagen":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "om" and wordNextNext == "aftenen":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "morgen":
                        remainder = "am"
                        used += 1
                    elif wordNext == "eftermiddag":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "aften":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "i" and wordNextNext == "morgen":
                        remainder = "am"
                        used = 2
                    elif wordNext == "i" and wordNextNext == "eftermiddag":
                        remainder = "pm"
                        used = 2
                    elif wordNext == "i" and wordNextNext == "aften":
                        remainder = "pm"
                        used = 2
                    elif wordNext == "natten":
                        if int(strHH) > 4:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 1
                    else:
                        if timeQualifier != "":
                            if int(strHH) <= 12 and \
                                    (timeQualifier == "aftenen" or
                                     timeQualifier == "eftermiddagen"):
                                strHH = str(int(strHH) + 12)  # what happens when strHH is 24?
            else:
                # try to parse # s without colons
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
                else:
                    if wordNext in ("time", "timer") and int(word) < 100:
                        # "in 3 hours"
                        hrOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext in ("minut", "minutter"):
                        # "in 10 minutes"
                        minOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext in ("sekund", "sekunder"):
                        # in 5 seconds
                        secOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1

                    elif wordNext == "time":
                        strHH = strNum
                        used += 1
                        isTime = True
                        if wordNextNext == timeQualifier:
                            strMM = ""
                            if wordNextNext[:11] == "eftermiddag":
                                used += 1
                                remainder = "pm"
                            elif wordNextNext == "om" and wordNextNextNext == \
                                    "eftermiddagen":
                                used += 2
                                remainder = "pm"
                            elif wordNextNext[:5] == "aften":
                                used += 1
                                remainder = "pm"
                            elif wordNextNext == "om" and wordNextNextNext == \
                                    "aftenen":
                                used += 2
                                remainder = "pm"
                            elif wordNextNext[:6] == "morgen":
                                used += 1
                                remainder = "am"
                            elif wordNextNext == "om" and wordNextNextNext == \
                                    "morgenen":
                                used += 2
                                remainder = "am"
                            elif wordNextNext == "natten":
                                used += 1
                                if 8 <= int(word) <= 12:
                                    remainder = "pm"
                                else:
                                    remainder = "am"

                        elif is_numeric(wordNextNext):
                            strMM = wordNextNext
                            used += 1
                            if wordNextNextNext == timeQualifier:
                                if wordNextNextNext[:11] == "eftermiddag":
                                    used += 1
                                    remainder = "pm"
                                elif wordNextNextNext == "om" and \
                                        wordNextNextNextNext == \
                                        "eftermiddagen":
                                    used += 2
                                    remainder = "pm"
                                elif wordNextNextNext[:6] == "natten":
                                    used += 1
                                    remainder = "pm"
                                elif wordNextNextNext == "am" and \
                                        wordNextNextNextNext == "natten":
                                    used += 2
                                    remainder = "pm"
                                elif wordNextNextNext[:7] == "morgenen":
                                    used += 1
                                    remainder = "am"
                                elif wordNextNextNext == "om" and \
                                        wordNextNextNextNext == "morgenen":
                                    used += 2
                                    remainder = "am"
                                elif wordNextNextNext == "natten":
                                    used += 1
                                    if 8 <= int(word) <= 12:
                                        remainder = "pm"
                                    else:
                                        remainder = "am"

                    elif wordNext == timeQualifier:
                        strHH = strNum
                        strMM = 00
                        isTime = True
                        if wordNext[:11] == "eftermiddag":
                            used += 1
                            remainder = "pm"
                        elif wordNext == "om" and \
                                wordNextNext == "eftermiddagen":
                            used += 2
                            remainder = "pm"
                        elif wordNext[:7] == "aftenen":
                            used += 1
                            remainder = "pm"
                        elif wordNext == "om" and wordNextNext == "aftenen":
                            used += 2
                            remainder = "pm"
                        elif wordNext[:7] == "morgenen":
                            used += 1
                            remainder = "am"
                        elif wordNext == "om" and wordNextNext == "morgenen":
                            used += 2
                            remainder = "am"
                        elif wordNext == "natten":
                            used += 1
                            if 8 <= int(word) <= 12:
                                remainder = "pm"
                            else:
                                remainder = "am"

                # if timeQualifier != "":
                #     military = True
                # else:
                #     isTime = False

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
            # removed parsed words from the sentence
            for i in range(used):
                words[idx + i] = ""

            if wordPrev == "tidlig":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "sen":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # check that we found a date
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation

    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # purely relative time ("om 2 timer") keeps the anchor time of day
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
                          'aug',
                          'sept', 'oct', 'nov', 'dec']
        for idx, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months[idx]) + r"\b", en_month, datestr)
        for idx, en_month in enumerate(en_monthsShort):
            datestr = re.sub(r"\b" + re.escape(monthsShort[idx]) + r"\b", en_month, datestr)

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
                extractedDate = extractedDate.replace(year=int(currentYear),
                                                      month=int(
                                                          temp.strftime(
                                                              "%m")),
                                                      day=int(temp.strftime(
                                                          "%d")))
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

    if timeStr != "":
        temp = datetime(timeStr)
        extractedDate = extractedDate.replace(hour=temp.strftime("%H"),
                                              minute=temp.strftime("%M"),
                                              second=temp.strftime("%S"))

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
        if word == "og" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())

    return [extractedDate, resultStr]

def extract_duration_da(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["da"],
                                    resolution, replace_token)
