import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_de import pronounce_number_de, _get_ordinal_index, is_number_de, is_numeric_de, \
    numbers_to_digits_de
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def nice_time_de(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format
    For example, generate 'ein uhr eins' for speech or '01:01 Uhr' for
    text display.
    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)=Fal
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
    Returns:
        (str): The formatted time string
    """
    string = ""
    if not speech:
        if use_24hour:
            string = f"{dt.strftime('%H:%M')} uhr"
        else:
            string = f"{dt.strftime('%I:%M')} uhr"

    # Generate a speakable version of the time"
    elif use_24hour:
        if dt.hour == 1:
            string += "ein"  # 01:00 is "ein Uhr" not "eins Uhr"
        else:
            string += pronounce_number_de(dt.hour)
        string += " uhr"
        if not dt.minute == 0:  # zero minutes are not pronounced
            string += " " + pronounce_number_de(dt.minute)
    else:
        next_hour = (dt.hour + 1) % 12 or 12
        if dt.hour == 0 and dt.minute == 0:
            return "mitternacht"
        elif dt.hour == 12 and dt.minute == 0:
            return "mittag"
        elif dt.minute == 15:
            string = "viertel " + pronounce_number_de(next_hour)
        elif dt.minute == 30:
            string = "halb " + pronounce_number_de(next_hour)
        elif dt.minute == 45:
            string = "dreiviertel " + pronounce_number_de(next_hour)
        else:
            hour = dt.hour % 12
            if hour == 1:  # 01:00 and 13:00 is "ein Uhr" not "eins Uhr"
                string += 'ein'
            else:
                string += pronounce_number_de(hour)
            string += " uhr"

            if not dt.minute == 0:
                string += " " + pronounce_number_de(dt.minute)

    if use_ampm:
        if 3 <= dt.hour < 12:
            string += " morgens"  # 03:00 - 11:59 morgens/in the morning
        elif 12 <= dt.hour < 18:
            string += " nachmittags"  # 12:01 - 17:59 nachmittags/afternoon
        elif 18 <= dt.hour < 22:
            string += " abends"  # 18:00 - 21:59 abends/evening
        else:
            string += " nachts"  # 22:00 - 02:59 nachts/at night

    return string


def extract_duration_de(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["de"],
                                    resolution, replace_token)


def extract_datetime_de(text, anchorDate=None, default_time=None):
    def clean_string(s):
        """
            cleans the input string of unneeded punctuation
            and capitalization among other things.

            'am' is a preposition, so cannot currently be used
            for 12 hour date format
        """

        s = numbers_to_digits_de(s)
        s = s.lower().replace('?', '').replace(' der ', ' ').replace(' den ', ' ') \
            .replace(' an ', ' ').replace(' am ', ' ').replace(' auf ', ' ') \
            .replace(' um ', ' ')
        wordList = s.split()

        for idx, word in enumerate(wordList):
            ordinal = _get_ordinal_index(word)
            if ordinal:
                wordList[idx] = ordinal

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

    timeQualifiersList = ['früh', 'morgens', 'vormittag', 'vormittags',
                          'mittag', 'mittags', 'nachmittag', 'nachmittags',
                          'abend', 'abends', 'nacht', 'nachts', 'pm', 'p.m.']
    eveningQualifiers = ['nachmittag', 'nachmittags', 'abend', 'abends', 'nacht',
                         'nachts', 'pm', 'p.m.']
    markers = ['in', 'am', 'gegen', 'bis', 'für']
    days = ['montag', 'dienstag', 'mittwoch',
            'donnerstag', 'freitag', 'samstag', 'sonntag']
    months = ['januar', 'februar', 'märz', 'april', 'mai', 'juni',
              'juli', 'august', 'september', 'oktober', 'november',
              'dezember']
    monthsShort = ['jan', 'feb', 'mär', 'apr', 'mai', 'juni', 'juli', 'aug',
                   'sept', 'oct', 'nov', 'dez']

    validFollowups = days + months + monthsShort
    validFollowups.append("heute")
    validFollowups.append("morgen")
    validFollowups.append("nächste")
    validFollowups.append("nächster")
    validFollowups.append("nächstes")
    validFollowups.append("nächsten")
    validFollowups.append("nächstem")
    validFollowups.append("letzte")
    validFollowups.append("letzter")
    validFollowups.append("letztes")
    validFollowups.append("letzten")
    validFollowups.append("letztem")
    validFollowups.append("jetzt")

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
        if word in timeQualifiersList:
            timeQualifier = word
            # parse today, tomorrow, day after tomorrow
        # "gestern": an dem Tag, der dem heutigen unmittelbar
        # vorausgegangen ist (Duden,
        # papers/linguistics/german/duden_gestern.html)
        elif word == "vorgestern" and not fromFlag:
            dayOffset = -2
            used += 1
        elif word == "gestern" and not fromFlag:
            dayOffset = -1
            used += 1
        elif word == "heute" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "morgen" and not fromFlag and wordPrev != "am" and \
                wordPrev not in days:  # morgen means tomorrow if not "am
            # Morgen" and not [day of the week] morgen
            dayOffset = 1
            used += 1
        elif word == "übermorgen" and not fromFlag:
            dayOffset = 2
            used += 1
            # parse 5 days, 10 weeks, last week, next week
        elif word[:3] == "tag" and len(word) <= 5:
            num = is_number_de(wordPrev)
            if num:
                # "vor N <Zeitraum>" = N periods in the past (Duden, vor + Dativ)
                if wordPrevPrev == "vor":
                    dayOffset -= num
                    start -= 2
                    used = 3
                else:
                    dayOffset += num
                    start -= 1
                    used = 2
        elif word[:5] == "woche" and len(word) <= 7 and not fromFlag:
            num = is_number_de(wordPrev)
            if num:
                # "vor N <Zeitraum>" = N periods in the past (Duden, vor + Dativ)
                if wordPrevPrev == "vor":
                    dayOffset -= num * 7
                    start -= 2
                    used = 3
                else:
                    dayOffset += num * 7
                    start -= 1
                    used = 2
            elif wordPrev[:6] == "nächst":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev[:5] == "letzt":
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif word[:5] == "monat" and len(word) <= 7 and not fromFlag:
            num = is_number_de(wordPrev)
            if num:
                # "vor N <Zeitraum>" = N periods in the past (Duden, vor + Dativ)
                if wordPrevPrev == "vor":
                    monthOffset = -num
                    start -= 2
                    used = 3
                else:
                    monthOffset = num
                    start -= 1
                    used = 2
            elif wordPrev[:6] == "nächst":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:5] == "letzt":
                monthOffset = -1
                start -= 1
                used = 2
                # parse 5 years, next year, last year
        elif word[:4] == "jahr" and len(word) <= 6 and not fromFlag:
            num = is_number_de(wordPrev)
            if num:
                # "vor N <Zeitraum>" = N periods in the past (Duden, vor + Dativ)
                if wordPrevPrev == "vor":
                    yearOffset = -num
                    start -= 2
                    used = 3
                else:
                    yearOffset = num
                    start -= 1
                    used = 2
            elif wordPrev[:6] == "nächst":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev[:5] == "letzt":
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
            if wordNext == "morgen":  # morgen means morning if preceded by
                # the day of the week
                words[idx + 1] = "früh"
            if wordPrev[:6] == "nächst":
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev[:5] == "letzt":
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
                if wordNext and wordNext.isdigit() and len(wordNext) == 4:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext.isdigit() and \
                        len(wordNextNext) == 4:
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False
        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July

        if (
                word == "von" or word == "nach" or word == "ab") and wordNext \
                in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "morgen" and wordPrev != "am" and \
                    wordPrev not in days:  # morgen means tomorrow if not "am
                #  Morgen" and not [day of the week] morgen:
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
                if wordNext[:6] == "nächst":
                    tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext[:5] == "letzt":
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1].startswith("diese"):
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
        wordNextNextNextNextNext = words[idx + 5] if idx + 5 < len(words) else ""

        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word[:6] == "mittag":
            hrAbs = 12
            used += 1
        elif word[:11] == "mitternacht":
            hrAbs = 0
            used += 1
        elif word == "morgens" or (
                wordPrev == "am" and word == "morgen") or word == "früh":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word[:10] == "nachmittag":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word[:5] == "abend":
            if not hrAbs:
                hrAbs = 19
            used += 1
            # parse half an hour, quarter hour
        elif word[:5] == "nacht":
            if not hrAbs:
                hrAbs = 23
            used += 1
        elif word[:6] == "stunde" and \
                (wordPrev in markers or wordPrevPrev in markers):
            factor = is_number_de(word) or 1
            minOffset = 60 * factor
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
            timeQualifier = ""
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
                    if nextWord in eveningQualifiers:
                        used += 1
                        timeQualifier = "pm"
                    elif nextWord in timeQualifiersList:
                        used += 1
                        timeQualifier = "am"
                    elif nextWord == "uhr":
                        used += 1
                        if wordNextNext in eveningQualifiers:
                            used += 1
                            timeQualifier = "pm"
                        elif wordNextNext in timeQualifiersList:
                            used += 1
                            timeQualifier = "am"
                        elif strHH.isdigit():
                            if int(strHH) > 12:
                                timeQualifier = "pm"
                            else:
                                timeQualifier = "am"
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

                if (
                        remainder == "pm" or
                        wordNext == "pm" or
                        remainder == "p.m." or
                        wordNext == "p.m."):
                    strHH = strNum
                    timeQualifier = "pm"
                    used = 1
                elif (
                        remainder == "am" or
                        wordNext == "am" or
                        remainder == "a.m." or
                        wordNext == "a.m."):
                    strHH = strNum
                    timeQualifier = "am"
                    used = 1
                else:
                    if wordNext[:6] == "stunde" and len(wordNext) <= 7:
                        # "in 3 hours"
                        hrOffset = is_number_de(word) or 1
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext[:6] == "minute" and len(wordNext) <= 7:
                        # "in 10 minutes"
                        minOffset = is_number_de(word) or 1
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext[:7] == "sekunde" and len(wordNext) <= 8:
                        # in 5 seconds
                        secOffset = is_number_de(word) or 1
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1

                    elif wordNext == "uhr":
                        strHH = word
                        used += 1
                        isTime = True
                        if wordNextNext in timeQualifiersList or \
                                wordNextNextNext in timeQualifiersList \
                                and not is_number_de(wordNextNext):
                            strMM = ""
                            if wordNextNext[:10] == "nachmittag":
                                used += 1
                                timeQualifier = "pm"
                            elif wordNextNext == "am" and wordNextNextNext == \
                                    "nachmittag":
                                used += 2
                                timeQualifier = "pm"
                            elif wordNextNext[:6] == "mittag":
                                used += 1
                                timeQualifier = "am"
                            elif wordNextNext == "am" and wordNextNextNext == \
                                    "mittag":
                                used += 2
                                timeQualifier = "am"
                            elif wordNextNext[:5] == "abend":
                                used += 1
                                timeQualifier = "pm"
                            elif wordNextNext == "am" and wordNextNextNext == \
                                    "abend":
                                used += 2
                                timeQualifier = "pm"
                            elif wordNextNext[:7] == "morgens":
                                used += 1
                                timeQualifier = "am"
                            elif wordNextNext == "am" and wordNextNextNext == \
                                    "morgen":
                                used += 2
                                timeQualifier = "am"
                            elif wordNextNext[:5] == "nacht":
                                used += 1
                                if 8 <= int(word) <= 12:
                                    timeQualifier = "pm"
                                else:
                                    timeQualifier = "am"

                        elif is_numeric_de(wordNextNext):
                            strMM = wordNextNext
                            used += 1
                            # TTS failure "16 Uhr 30 Uhr" (common with google)
                            if wordNextNextNext == "uhr":
                                used += 1
                                wordNextNextNext = wordNextNextNextNext
                                wordNextNextNextNext = wordNextNextNextNextNext
                            if wordNextNextNext in timeQualifiersList or \
                                    wordNextNextNextNext in timeQualifiersList:
                                if wordNextNextNext[:10] == "nachmittag":
                                    used += 1
                                    timeQualifier = "pm"
                                elif wordNextNextNext == "am" and \
                                        wordNextNextNextNext == "nachmittag":
                                    used += 2
                                    timeQualifier = "pm"
                                elif wordNextNext[:6] == "mittag":
                                    used += 1
                                    timeQualifier = "am"
                                elif wordNextNext == "am" and wordNextNextNext == \
                                        "mittag":
                                    used += 2
                                    timeQualifier = "am"
                                elif wordNextNextNext[:5] == "abend":
                                    used += 1
                                    timeQualifier = "pm"
                                elif wordNextNextNext == "am" and \
                                        wordNextNextNextNext == "abend":
                                    used += 2
                                    timeQualifier = "pm"
                                elif wordNextNextNext[:7] == "morgens":
                                    used += 1
                                    timeQualifier = "am"
                                elif wordNextNextNext == "am" and \
                                        wordNextNextNextNext == "morgen":
                                    used += 2
                                    timeQualifier = "am"
                                elif wordNextNextNext == "nachts":
                                    used += 1
                                    if 8 <= int(word) <= 12:
                                        timeQualifier = "pm"
                                    else:
                                        timeQualifier = "am"
                            elif strHH.isdigit():
                                if int(strHH) > 12:
                                    timeQualifier = "pm"
                                else:
                                    timeQualifier = "am"
                        elif strHH.isdigit():
                            if int(strHH) > 12:
                                timeQualifier = "pm"
                            else:
                                timeQualifier = "am"

                    elif wordNext in timeQualifiersList or \
                            wordNextNext in timeQualifiersList:
                        strHH = word
                        strMM = 00
                        isTime = True
                        if wordNext[:10] == "nachmittag":
                            used += 1
                            timeQualifier = "pm"
                        elif wordNext == "am" and wordNextNext == "nachmittag":
                            used += 2
                            timeQualifier = "pm"
                        elif wordNextNext[:6] == "mittag":
                            used += 1
                            timeQualifier = "am"
                        elif wordNextNext == "am" and wordNextNextNext == \
                                "mittag":
                            used += 2
                            timeQualifier = "am"
                        elif wordNext[:5] == "abend":
                            used += 1
                            timeQualifier = "pm"
                        elif wordNext == "am" and wordNextNext == "abend":
                            used += 2
                            timeQualifier = "pm"
                        elif wordNext[:7] == "morgens":
                            used += 1
                            timeQualifier = "am"
                        elif wordNext == "am" and wordNextNext == "morgen":
                            used += 2
                            timeQualifier = "am"
                        elif wordNext == "nachts":
                            used += 1
                            if 8 <= int(word) <= 12:
                                timeQualifier = "pm"
                            else:
                                timeQualifier = "am"

                if timeQualifier == "":
                    isTime = False

            strHH = int(strHH) if strHH else 0
            strMM = int(strMM) if strMM else 0
            if timeQualifier != "":
                if strHH <= 12 and timeQualifier == "pm" and not \
                        (strHH == 12 and any([q in words for q in ("pm", "p.m.")])):
                    if strHH == 12:
                        strHH = 0
                        dayOffset += 1
                    else:
                        strHH += 12
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

            if wordPrev == "Uhr":
                words[words.index(wordPrev)] = ""

            if wordPrev == "früh":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "spät":
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
                # parse against a leap year so "29. februar" is a valid reference
                temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
        except ValueError:
            # impossible calendar date (e.g. "31. juni", "0. januar",
            # "29. februar 2021") - null beats a wrong guess
            return None

        if extractedDate.tzinfo:
            temp = temp.replace(tzinfo=extractedDate.tzinfo)

        if not hasYear:
            month = temp.month
            day = temp.day

            def _valid_date(year):
                # a calendar day may be missing in a given year (e.g. 29 Feb)
                try:
                    return extractedDate.replace(year=year, month=month, day=day)
                except ValueError:
                    return None

            candidate = _valid_date(extractedDate.year)
            if candidate is not None and extractedDate < candidate:
                extractedDate = candidate
            else:
                # search a bounded span of years for the next valid occurrence
                candidate = None
                for year in range(extractedDate.year + 1,
                                  extractedDate.year + 9):
                    candidate = _valid_date(year)
                    if candidate is not None:
                        break
                if candidate is None:
                    return None
                extractedDate = candidate
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
        if word == "und" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())

    return [extractedDate, resultStr]
