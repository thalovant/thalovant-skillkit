from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_sv import pronounce_number_sv, _find_numbers_in_text, _combine_adjacent_numbers
from ovos_number_parser.util import tokenize
from ovos_utils.time import now_local


def nice_time_sv(dt, speech=True, use_24hour=False, use_ampm=False):
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
            speak += "ett"  # 01:00 is "ett" not "en"
        else:
            speak += pronounce_number_sv(dt.hour)
        if not dt.minute == 0:
            if dt.minute < 10:
                speak += ' noll'

            if dt.minute == 1:
                speak += ' ett'
            else:
                speak += " " + pronounce_number_sv(dt.minute)

        return speak  # ampm is ignored when use_24hour is true
    else:
        hour = dt.hour

        if not dt.minute == 0:
            if dt.minute < 30:
                if dt.minute != 15:
                    speak += pronounce_number_sv(dt.minute)
                else:
                    speak += 'kvart'

                if dt.minute == 1:
                    speak += ' minut över '
                elif dt.minute != 10 and dt.minute != 5 and dt.minute != 15:
                    speak += ' minuter över '
                else:
                    speak += ' över '
            elif dt.minute > 30:
                if dt.minute != 45:
                    speak += pronounce_number_sv((60 - dt.minute))
                else:
                    speak += 'kvart'

                if dt.minute == 1:
                    speak += ' minut i '
                elif dt.minute != 50 and dt.minute != 55 and dt.minute != 45:
                    speak += ' minuter i '
                else:
                    speak += ' i '

                hour = (hour + 1) % 12
            elif dt.minute == 30:
                speak += 'halv '
                hour = (hour + 1) % 12

        if hour == 0 and dt.minute == 0:
            return "midnatt"
        if hour == 12 and dt.minute == 0:
            return "middag"
        # TODO: "half past 3", "a quarter of 4" and other idiomatic times

        if hour == 0:
            speak += pronounce_number_sv(12)
        elif hour <= 13:
            if hour == 1 or hour == 13:  # 01:00 and 13:00 is "ett"
                speak += 'ett'
            else:
                speak += pronounce_number_sv(hour)
        else:
            speak += pronounce_number_sv(hour - 12)

        if use_ampm:
            if dt.hour > 11:
                if dt.hour < 18:
                    # 12:01 - 17:59 nachmittags/afternoon
                    speak += " på eftermiddagen"
                elif dt.hour < 22:
                    # 18:00 - 21:59 abends/evening
                    speak += " på kvällen"
                else:
                    # 22:00 - 23:59 nachts/at night
                    speak += " på natten"
            elif dt.hour < 3:
                # 00:01 - 02:59 nachts/at night
                speak += " på natten"
            else:
                # 03:00 - 11:59 morgens/in the morning
                speak += " på morgonen"

        return speak


def extract_datetime_sv(text, anchorDate=None, default_time=None):
    def clean_string(s):
        """
            cleans the input string of unneeded punctuation and capitalization
            among other things.
        """
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace(' den ', ' ').replace(' en ', ' ')
        wordList = s.split()
        for idx, word in enumerate(wordList):
            word = word.replace("'s", "")

            ordinals = ["rd", "st", "nd", "th"]
            if word and word[0].isdigit():
                for ordinal in ordinals:
                    if ordinal in word:
                        word = word.replace(ordinal, "")
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

    timeQualifiersList = ['morgon', 'förmiddag', 'eftermiddag', 'kväll']
    markers = ['på', 'i', 'den här', 'kring', 'efter', 'om']
    days = ['måndag', 'tisdag', 'onsdag', 'torsdag',
            'fredag', 'lördag', 'söndag']
    months = ['januari', 'februari', 'mars', 'april', 'maj', 'juni',
              'juli', 'augusti', 'september', 'oktober', 'november',
              'december']
    monthsShort = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july', 'aug',
                   'sept', 'oct', 'nov', 'dec']

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        word = word.rstrip('s')
        start = idx
        used = 0
        # save timequalifier for later
        if word in timeQualifiersList:
            timeQualifier = word
            # parse today, tomorrow, day after tomorrow
        elif word == "idag" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "imorgon" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "morgondagen" or word == "morgondagens" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "övermorgon" and not fromFlag:
            dayOffset = 2
            used += 1
        # parse 5 days, 10 weeks, last week, next week
        elif word == "dag" or word == "dagar":
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sedan" = N periods in the past (SAOL)
                if wordNext == "sedan":
                    dayOffset -= int(wordPrev)
                    used += 1
                else:
                    dayOffset += int(wordPrev)
                start -= 1
                used += 2
        elif word == "vecka" or word == "veckor" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sedan" = N periods in the past (SAOL)
                if wordNext == "sedan":
                    dayOffset -= int(wordPrev) * 7
                    used += 1
                else:
                    dayOffset += int(wordPrev) * 7
                start -= 1
                used += 2
            elif wordPrev == "nästa":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev == "förra":
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif (word == "månad" or word == "månader") and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sedan" = N periods in the past (SAOL)
                if wordNext == "sedan":
                    monthOffset = -int(wordPrev)
                    used += 1
                else:
                    monthOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev == "nästa":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "förra":
                monthOffset = -1
                start -= 1
                used = 2
                # parse 5 years, next year, last year
        elif word == "år" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "N ... sedan" = N periods in the past (SAOL)
                if wordNext == "sedan":
                    yearOffset = -int(wordPrev)
                    used += 1
                else:
                    yearOffset = int(wordPrev)
                start -= 1
                used += 2
            elif wordPrev == "nästa":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "förra":
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
            if wordPrev == "nästa":
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "förra":
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
                    # a four digit number after a month is its year, not a
                    # day of month: "juni 2027"
                    hasYear = len(wordNext) == 4
        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("idag")
        validFollowups.append("imorgon")
        validFollowups.append("nästa")
        validFollowups.append("förra")
        validFollowups.append("nu")
        if (word == "från" or word == "efter") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "imorgon":
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
                if wordNext == "nästa":
                    tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext == "förra":
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] == "denna":
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
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "middag":
            hrAbs = 12
            used += 1
        elif word == "midnatt":
            hrAbs = 0
            used += 1
        elif word == "morgon":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "förmiddag":
            if not hrAbs:
                hrAbs = 10
            used += 1
        elif word == "eftermiddag":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word == "kväll":
            if not hrAbs:
                hrAbs = 19
            used += 1
            # parse half an hour, quarter hour
        elif word in ("halvtimme", "halvtimma", "kvart", "timme", "timma",
                      "minut", "sekund") \
                and (wordPrev in markers or wordPrevPrev in markers):
            if word == "halvtimme" or word == "halvtimma":
                minOffset = 30
            elif word == "kvart":
                minOffset = 15
            elif word == "timme" or word == "timma":
                hrOffset = 1
            elif word == "minut":
                minOffset = 1
            elif word == "sekund":
                secOffset = 1
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
                    elif nextWord == "tonight":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "morning":
                        remainder = "am"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "afternoon":
                        remainder = "pm"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "evening":
                        remainder = "pm"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "morning":
                        remainder = "am"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "afternoon":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "evening":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "this" and wordNextNext == "morning":
                        remainder = "am"
                        used = 2
                    elif wordNext == "this" and wordNextNext == "afternoon":
                        remainder = "pm"
                        used = 2
                    elif wordNext == "this" and wordNextNext == "evening":
                        remainder = "pm"
                        used = 2
                    elif wordNext == "at" and wordNextNext == "night":
                        if strHH > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 2
                    else:
                        if timeQualifier != "":
                            if strHH <= 12 and \
                                    (timeQualifier == "evening" or
                                     timeQualifier == "afternoon"):
                                strHH += 12
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
                    if wordNext == "pm" or wordNext == "p.m.":
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif wordNext == "am" or wordNext == "a.m.":
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif (
                            int(strNum) > 100 and
                            (
                                    wordPrev == "o" or
                                    wordPrev == "oh"
                            )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = int(strNum) / 100
                        strMM = int(strNum) - strHH * 100
                        if wordNext == "hours":
                            used += 1
                    elif wordNext in ("timme", "timma", "timmar") and \
                            int(strNum) < 100:
                        # "om 3 timmar" = "in 3 hours"
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1

                    elif wordNext in ("minut", "minuter"):
                        # "om 10 minuter" = "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext in ("sekund", "sekunder"):
                        # "om 5 sekunder" = "in 5 seconds"
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif int(strNum) > 100:
                        strHH = int(strNum) / 100
                        strMM = int(strNum) - strHH * 100
                        if wordNext == "hours":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        used += 1
                        if wordNextNext == "hours":
                            used += 1
                    elif (
                            wordNext == "" or wordNext == "o'clock" or
                            (
                                    wordNext == "in" and
                                    (
                                            wordNextNext == "the" or
                                            wordNextNext == timeQualifier
                                    )
                            )):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "o'clock":
                            used += 1
                        if wordNext == "in" or wordNextNext == "in":
                            used += (1 if wordNext == "in" else 2)
                            if (wordNextNext and
                                    wordNextNext in timeQualifier or
                                    (words[words.index(wordNextNext) + 1] and
                                     words[words.index(wordNextNext) + 1] in
                                     timeQualifier)):
                                if (wordNextNext == "afternoon" or
                                        (len(words) >
                                         words.index(wordNextNext) + 1 and
                                         words[words.index(
                                             wordNextNext) + 1] == "afternoon")):
                                    remainder = "pm"
                                if (wordNextNext == "evening" or
                                        (len(words) >
                                         (words.index(wordNextNext) + 1) and
                                         words[words.index(
                                             wordNextNext) + 1] == "evening")):
                                    remainder = "pm"
                                if (wordNextNext == "morning" or
                                        (len(words) >
                                         words.index(wordNextNext) + 1 and
                                         words[words.index(
                                             wordNextNext) + 1] == "morning")):
                                    remainder = "am"
                    else:
                        isTime = False

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

            if wordPrev == "o" or wordPrev == "oh":
                words[words.index(wordPrev)] = ""

            if wordPrev == "early":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "late":
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
        # purely relative time ("om 2 timmar") keeps the anchor time of day
        extractedDate = extractedDate.replace(microsecond=0, second=0)
    else:
        extractedDate = extractedDate.replace(microsecond=0,
                                              second=0,
                                              minute=0,
                                              hour=0)
    if datestr != "":
        # datestr is built from Swedish month names (e.g. "juni 15"),
        # which strptime("%B") cannot parse, so map the month directly.
        dateparts = datestr.split()
        month_num = months.index(dateparts[0]) + 1
        year_num = int(dateparts.pop()) if hasYear else None
        # a month named without a day ("i juni") means its first day
        day_num = int(dateparts[1]) if len(dateparts) > 1 else 1
        if hasYear:
            try:
                temp = datetime(year_num, month_num, day_num)
            except ValueError:
                # impossible date such as "31 april 2020"
                return None
            extractedDate = extractedDate.replace(
                year=temp.year, month=temp.month, day=temp.day)
        else:
            # find the soonest year in which this day/month exists (handles
            # "29 februari" when the current year is not a leap year) and
            # keep the existing "next occurrence" semantics
            base_year = extractedDate.year
            try:
                this_year = datetime(base_year, month_num, day_num,
                                     tzinfo=extractedDate.tzinfo)
                use_this_year = extractedDate < this_year
            except ValueError:
                use_this_year = False
            if use_this_year:
                year = base_year
            else:
                # search a bounded window (any leap cycle resolves within a
                # few years); an impossible day/month such as "31 april" never
                # resolves, so give up and report no date instead of looping
                year = None
                for candidate in range(base_year + 1, base_year + 9):
                    try:
                        datetime(candidate, month_num, day_num)
                        year = candidate
                        break
                    except ValueError:
                        continue
                if year is None:
                    return None
            extractedDate = extractedDate.replace(
                year=year, month=month_num, day=day_num)

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
        if word == "and" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def extract_duration_sv(text):
    """
    Convert a swedish phrase into a number of seconds.

    The function handles durations from seconds up to days.

    Convert things like:
        "10 minute"
        "2 and a half hours"
        "3 days 8 hours 10 minutes and 49 seconds"
    into an int, representing the total number of seconds.

    The words used in the duration will be consumed, and
    the remainder returned.

    As an example, "set a timer for 5 minutes" would return
    (300, "set a timer for").

    Args:
        text (str): string containing a duration

    Returns:
        (timedelta, str):
                    A tuple containing the duration and the remaining text
                    not consumed in the parsing. The first value will
                    be None if no duration is found. The text returned
                    will have whitespace stripped from the ends.
    """
    tokens = tokenize(text)
    number_tok_map = _find_numbers_in_text(tokens)
    if not number_tok_map:
        # No numbers means no duration; also avoids indexing an empty
        # token list downstream when the input is empty or whitespace.
        return None, text
    # Combine adjacent numbers
    simplified = _combine_adjacent_numbers(number_tok_map)

    states = {
        'days': 0,
        'hours': 0,
        'minutes': 0,
        'seconds': 0
    }

    # Parser state, mapping words that should set the parser to collect
    # numbers to a specific time "size"
    state_words = {
        'days': ('dygn', 'dag', 'dagar', 'dags'),
        'hours': ('timmar', 'timme', 'timma', 'timmes', 'timmas'),
        'minutes': ('minuter', 'minuters', 'minut', 'minuts'),
        'seconds': ('sekunder', 'sekunders', 'sekund', 'sekunds')
    }
    binding_words = ('och')

    consumed = []
    state = None
    valid = False

    for num, toks in simplified:
        if state and num:
            states[state] += num
            consumed.extend(toks)
            valid = True  # If a state field got set this is valid duration
        elif num is None:
            for s in state_words:
                if toks[0].word in state_words[s]:
                    state = s
                    consumed.extend(toks)
                    break
            else:
                if toks[0].word not in binding_words:
                    state = None

    td = timedelta(**states)
    remainder = ' '.join([t.word for t in tokens if t not in consumed])
    return (td, remainder) if valid else (None, text)
