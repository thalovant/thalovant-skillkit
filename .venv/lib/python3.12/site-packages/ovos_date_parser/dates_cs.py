import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_cs import pronounce_number_cs, _ORDINAL_BASE_CS, extract_number_cs, \
    numbers_to_digits_cs
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

_MONTHS_CONVERSION = {
    0: "january",
    1: "february",
    2: "march",
    3: "april",
    4: "may",
    5: "june",
    6: "july",
    7: "august",
    8: "september",
    9: "october",
    10: "november",
    11: "december"
}

_MONTHS_CZECH = ['leden', 'únor', 'březen', 'duben', 'květen', 'červen',
                 'červenec', 'srpen', 'září', 'říjen', 'listopad',
                 'prosinec']

# Time
_TIME_UNITS_CONVERSION = {
    'mikrosekund': 'microseconds',
    'milisekund': 'milliseconds',
    'sekundu': 'seconds',
    'sekundy': 'seconds',
    'sekund': 'seconds',
    'minutu': 'minutes',
    'minuty': 'minutes',
    'minut': 'minutes',
    'hodin': 'hours',
    'den': 'days',  # 1 day
    'dny': 'days',  # 2-4 days
    'dnů': 'days',  # 5+ days
    'dní': 'days',  # 5+ days - different inflection
    'dne': 'days',  # a half day
    'týden': 'weeks',
    'týdny': 'weeks',
    'týdnů': 'weeks'
}


def nice_time_cs(dt, speech=True, use_24hour=True, use_ampm=False):
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
    if use_24hour:
        speak = ""

        # Either "0 8 hundred" or "13 hundred"
        if string[0] == '0':
            speak += pronounce_number_cs(int(string[0])) + " "
            speak += pronounce_number_cs(int(string[1]))
        else:
            speak = pronounce_number_cs(int(string[0:2]))

        speak += " "
        if string[3:5] == '00':
            speak += "sto"
        else:
            if string[3] == '0':
                speak += pronounce_number_cs(0) + " "
                speak += pronounce_number_cs(int(string[4]))
            else:
                speak += pronounce_number_cs(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "půlnoc"
        elif dt.hour == 12 and dt.minute == 0:
            return "poledne"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        if dt.minute == 15:
            speak = "čtvrt po " + pronounce_number_cs(hour)
        elif dt.minute == 30:
            speak = "půl po " + pronounce_number_cs(hour)
        elif dt.minute == 45:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = "třičtvrtě na " + pronounce_number_cs(next_hour)
        else:
            speak = pronounce_number_cs(hour)

            if dt.minute == 0:
                if not use_ampm:
                    return speak + " hodin"
            else:
                if dt.minute < 10:
                    speak += " oh"
                speak += " " + pronounce_number_cs(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                speak += " p.m."
            else:
                speak += " a.m."

        return speak


def extract_duration_cs(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["cs"],
                                    resolution, replace_token)


def extract_datetime_cs(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

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
        anchorDate (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s):
        # clean unneeded punctuation and capitalization among other things.
        # Normalize czech inflection
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace("dvoje", "2").replace("dvojice", "2") \
            .replace("dnes večer", "večer").replace("dnes v noci", "noci")  # \
        # .replace("tento večer", "večer")
        # .replace(' the ', ' ').replace(' a ', ' ').replace(' an ', ' ') \
        # .replace("o' clock", "o'clock").replace("o clock", "o'clock") \
        # .replace("o ' clock", "o'clock").replace("o 'clock", "o'clock") \
        # .replace("decades", "decade") \
        # .replace("tisíciletí", "milénium")
        # .replace("oclock", "o'clock")
        wordList = s.split()

        for idx, word in enumerate(wordList):
            # word = word.replace("'s", "")
            ##########
            # Czech Day Ordinals - we do not use 1st,2nd format
            #    instead we use full ordinal number names with specific format(suffix)
            #   Example: třicátého prvního > 31
            count_ordinals = 0
            if word == "prvního":
                count_ordinals = 1  # These two have different format
            elif word == "třetího":
                count_ordinals = 3
            elif word.endswith("ého"):
                tmp = word[:-3]
                tmp += ("ý")
                for nr, name in _ORDINAL_BASE_CS.items():
                    if name == tmp:
                        count_ordinals = nr

            # If number is bigger than 19 chceck if next word is also ordinal
            #  and count them together
            if count_ordinals > 19:
                if wordList[idx + 1] == "prvního":
                    count_ordinals += 1  # These two have different format
                elif wordList[idx + 1] == "třetího":
                    count_ordinals += 3
                elif wordList[idx + 1].endswith("ého"):
                    tmp = wordList[idx + 1][:-3]
                    tmp += ("ý")
                    for nr, name in _ORDINAL_BASE_CS.items():
                        if name == tmp and nr < 10:
                            # write only if sum makes acceptable count of days in month
                            if (count_ordinals + nr) <= 31:
                                count_ordinals += nr

            if count_ordinals > 0:
                word = str(count_ordinals)  # Write normalized valu into word
            if count_ordinals > 20:
                # If counted number is grather than 20, clear next word so it is not used again
                wordList[idx + 1] = ""
            ##########
            # Remove inflection from czech months

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

    timeQualifiersAM = ['ráno', 'dopoledne']
    timeQualifiersPM = ['odpoledne', 'večer', 'noc', 'noci']
    timeQualifiersList = set(timeQualifiersAM + timeQualifiersPM)
    markers = ['na', 'v', 've', 'do', 'na', 'tento',
               'okolo', 'toto', 'během', 'za', 'této']
    days = ['pondělí', 'úterý', 'středa',
            'čtvrtek', 'pátek', 'sobota', 'neděle']
    months = _MONTHS_CZECH
    recur_markers = days + [d + 'ho' for d in days] + \
                    ['víkend', 'všední']  # Check this
    monthsShort = ['led', 'úno', 'bře', 'dub', 'kvě', 'čvn', 'čvc', 'srp',
                   'zář', 'říj', 'lis', 'pro']
    year_multiples = ["desetiletí", "století", "tisíciletí"]
    day_multiples = ["týden", "měsíc", "rok"]

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == "":
            continue

        word = _text_cs_inflection_normalize(word, 2)
        wordPrevPrev = _text_cs_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        wordPrev = _text_cs_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        wordNext = _text_cs_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        wordNextNext = _text_cs_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        # word = word.rstrip('s')
        start = idx
        used = 0
        # save timequalifier for later
        # if word == "před" and dayOffset:
        #    dayOffset = - dayOffset
        #    used += 1
        if word == "nyní" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_cs(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if wordNext == "desetiletí":
                yearOffset = multiplier * 10
            elif wordNext == "století":
                yearOffset = multiplier * 100
            elif wordNext == "tisíciletí":
                yearOffset = multiplier * 1000
        # couple of
        elif word == "2" and wordNext == "krát" and \
                wordNextNext in year_multiples:
            multiplier = 2
            used += 3
            if wordNextNext == "desetiletí":
                yearOffset = multiplier * 10
            elif wordNextNext == "století":
                yearOffset = multiplier * 100
            elif wordNextNext == "tisíciletí":
                yearOffset = multiplier * 1000
        elif word == "2" and wordNext == "krát" and \
                wordNextNext in day_multiples:
            multiplier = 2
            used += 3
            if wordNextNext == "rok":
                yearOffset = multiplier
            elif wordNextNext == "měsíc":
                monthOffset = multiplier
            elif wordNextNext == "týden":
                dayOffset = multiplier * 7
        elif word in timeQualifiersList:
            timeQualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "dnes" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "zítra" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "den" and wordNext == "před" and wordNextNext == "včera" and not fromFlag:
            dayOffset = -2
            used += 3
        elif word == "před" and wordNext == "včera" and not fromFlag:
            dayOffset = -2
            used += 2
        elif word == "včera" and not fromFlag:
            dayOffset = -1
            used += 1
        elif (word == "den" and
              wordNext == "po" and
              wordNextNext == "zítra" and
              not fromFlag and
              (not wordPrev or not wordPrev[0].isdigit())):
            dayOffset = 2
            used = 3
            if wordPrev == "ten":
                start -= 1
                used += 1
                # parse 5 days, 10 weeks, last week, next week
        elif word == "den":
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "před":
                    dayOffset = -dayOffset
                    used += 1
                    start -= 1

        elif word == "týden" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
                # "před N ..." = N periods in the past (SSJČ/IJP)
                if wordPrevPrev == "před":
                    dayOffset = -dayOffset
                    used += 1
                    start -= 1
            elif wordPrev == "další" or wordPrev == "příští":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev == "poslední":
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif word == "měsíc" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                # "před N ..." = N periods in the past (SSJČ/IJP)
                if wordPrevPrev == "před":
                    monthOffset = -monthOffset
                    used += 1
                    start -= 1
            elif wordPrev == "další" or wordPrev == "příští":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "poslední":
                monthOffset = -1
                start -= 1
                used = 2
        # parse 5 years, next year, last year
        elif word == "rok" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                # "před N ..." = N periods in the past (SSJČ/IJP)
                if wordPrevPrev == "před":
                    yearOffset = -yearOffset
                    used += 1
                    start -= 1
            elif wordPrev == "další" or wordPrev == "příští":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "poslední":
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
            if wordPrev == "další" or wordPrev == "příští":
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "poslední":
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
            # Convert czech months to english
            datestr = _MONTHS_CONVERSION.get(m)
            if wordPrev and (wordPrev and wordPrev[0].isdigit() or
                             (wordPrev == " " and wordPrevPrev and wordPrevPrev[0].isdigit())):
                if wordPrev == " " and wordPrevPrev and wordPrevPrev[0].isdigit():
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

            # if no date indicators found, it may not be the month of May
            # may "i/we" ...
            # "... may be"
            # elif word == 'may' and wordNext in ['i', 'we', 'be']:
            #    datestr = ""

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("dnes")
        validFollowups.append("zítra")
        validFollowups.append("včera")
        validFollowups.append("další")
        validFollowups.append("příští")
        validFollowups.append("poslední")
        validFollowups.append("teď")
        validFollowups.append("toto")
        validFollowups.append("této")
        validFollowups.append("tento")
        if (word == "od" or word == "po" or word == "do") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "zítra":
                dayOffset += 1
            elif wordNext == "včera":
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
                if wordNext == "další" or wordPrev == "příští":
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext == "poslední":
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and (
                    words[start - 1] == "toto" or words[start - 1] == "této" or words[start - 1] == "tento"):
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

        word = _text_cs_inflection_normalize(word, 2)
        wordPrevPrev = _text_cs_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        wordPrev = _text_cs_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        wordNext = _text_cs_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        wordNextNext = _text_cs_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "poledne":
            hrAbs = 12
            used += 1
        elif word == "půlnoc":
            hrAbs = 0
            used += 1
        elif word == "ráno":
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word == "odpoledne":
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word == "večer":
            if hrAbs is None:
                hrAbs = 19
            used += 1
            if (wordNext != "" and wordNext[0].isdigit() and ":" in wordNext):
                used -= 1
        elif word == "noci" or word == "noc":
            if hrAbs is None:
                hrAbs = 22
            # used += 1
            # if ((wordNext !='' and not wordNext[0].isdigit()) or wordNext =='') and \
            #    ((wordNextNext !='' and not wordNextNext[0].isdigit())or wordNextNext =='')  :
            #    used += 1
            # used += 1 ## NOTE this breaks other tests, TODO refactor me!

        # couple of time_unit
        elif word == "2" and wordNext == "krát" and \
                wordNextNext in ["hodin", "minut", "sekund"]:
            used += 3
            if wordNextNext == "hodin":
                hrOffset = 2
            elif wordNextNext == "minut":
                minOffset = 2
            elif wordNextNext == "sekund":
                secOffset = 2
        # parse half an hour, quarter hour
        elif word == "hodin" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev == "půl":
                minOffset = 30
            elif wordPrev == "čtvrt":
                minOffset = 15
            elif wordPrevPrev == "třičtvrtě":
                minOffset = 15
                if idx > 2 and words[idx - 3] in markers:
                    words[idx - 3] = ""
                words[idx - 2] = ""
            elif wordPrev == "během":
                hrOffset = 1
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "tato" or wordPrevPrev == "této":
                    daySpecified = True
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
            # parse 5:00 am, 12:00 p.m., etc
        # parse in a minute
        elif word == "minut" and wordPrev == "za":
            minOffset = 1
            words[idx - 1] = ""
            used += 1
        # parse in a second
        elif word == "sekund" and wordPrev == "za":
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
            if wordNext == "večer" or wordNext == "noci" or wordNextNext == "večer" \
                    or wordNextNext == "noci" or wordPrev == "večer" \
                    or wordPrev == "noci" or wordPrevPrev == "večer" \
                    or wordPrevPrev == "noci" or wordNextNextNext == "večer" \
                    or wordNextNextNext == "noci":
                remainder = "pm"
                used += 1
                if wordPrev == "večer" or wordPrev == "noci":
                    words[idx - 1] = ""
                if wordPrevPrev == "večer" or wordPrevPrev == "noci":
                    words[idx - 2] = ""
                if wordNextNext == "večer" or wordNextNext == "noci":
                    used += 1
                if wordNextNextNext == "večer" or wordNextNextNext == "noci":
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

                    # elif wordNext == "in" and wordNextNext == "the" and \
                    #        words[idx + 3] == "ráno":
                    #    remainder = "am"
                    #    used += 3
                    # elif wordNext == "in" and wordNextNext == "the" and \
                    #        words[idx + 3] == "odpoledne":
                    #    remainder = "pm"
                    #    used += 3
                    # elif wordNext == "in" and wordNextNext == "the" and \
                    #        words[idx + 3] == "večer":
                    #    remainder = "pm"
                    #    used += 3
                    elif wordNext == "ráno":
                        remainder = "am"
                        used += 2
                    elif wordNext == "odpoledne":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "večer":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "toto" and wordNextNext == "ráno":
                        remainder = "am"
                        used = 2
                        daySpecified = True
                    elif wordNext == "na" and wordNextNext == "odpoledne":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "na" and wordNextNext == "večer":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "v" and wordNextNext == "noci":
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
                    if (int(strNum) > 100):  # and  #Check this
                        # (
                        #    wordPrev == "o" or
                        #    wordPrev == "oh"
                        # )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "hodin":
                            used += 1
                    elif (
                            (wordNext == "hodin" or
                             remainder == "hodin") and
                            word[0] != '0' and
                            # (wordPrev != "v" and wordPrev != "na")
                            wordPrev == "za"
                            and
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
                    elif wordNext == "minut" or \
                            remainder == "minut":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "sekund" \
                            or remainder == "sekund":
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
                        if wordNext == "hodin" or \
                                remainder == "hodin":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        # military time, e.g. "04 38 hours"
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if (wordNextNext == "hodin" or
                                remainder == "hodin"):
                            used += 1
                    elif (
                            wordNext == "" or wordNext == "hodin" or
                            (
                                    (wordNext == "v" or wordNext == "na") and
                                    (
                                            wordNextNext == timeQualifier
                                    )
                            ) or wordNext == 'večer' or
                            wordNextNext == 'večer'):

                        strHH = strNum
                        strMM = "00"
                        if wordNext == "hodin":
                            used += 1
                        if (wordNext == "v" or wordNext == "na"
                                or wordNextNext == "v" or wordNextNext == "na"):
                            used += (1 if (wordNext ==
                                           "v" or wordNext == "na") else 2)
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
                        elif remainder == "hodin":
                            remainder = ""

                    else:
                        isTime = False
            HH = int(strHH) if strHH else 0
            MM = int(strMM) if strMM else 0
            HH = HH + 12 if remainder == "pm" and HH < 12 else HH
            HH = HH - 12 if remainder == "am" and HH >= 12 else HH
            if (not military and
                    remainder not in ['am', 'pm', 'hodin', 'minut', 'sekund'] and
                    ((not daySpecified) or 0 <= dayOffset < 1)):

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

            if HH > 24 or MM > 59:
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

            # if wordPrev == "o" or wordPrev == "oh":
            #    words[words.index(wordPrev)] = ""

            if wordPrev == "brzy":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "pozdě":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
                if wordPrev == "toto" or wordPrev == "této":
                    daySpecified = True
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "toto" or wordPrev == "této":
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
        # date included an explicit date, e.g. "june 5" or "june 2, 2017"
        try:
            temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # Try again, allowing the year
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                # an impossible calendar date like "30 únor"; report nothing
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
    for idx, word in enumerate(words):
        if word == "a" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def _text_cs_inflection_normalize(word, arg):
    """
    Czech Inflection normalizer.

    This try to normalize known inflection. This function is called
    from multiple places, each one is defined with arg.

    Args:
        word [Word]
        arg [Int]

    Returns:
        word [Word]

    """
    if arg == 1:  # _extract_whole_number_with_text_cs
        # Number one (jedna)
        if len(word) == 5 and word.startswith("jed"):
            suffix = 'en', 'no', 'ny'
            if word.endswith(suffix, 3):
                word = "jedna"

        # Number two (dva)
        elif word == "dvě":
            word = "dva"

    elif arg == 2:  # extract_datetime_cs  TODO: This is ugly
        if word == "hodina":
            word = "hodin"
        if word == "hodiny":
            word = "hodin"
        if word == "hodinu":
            word = "hodin"
        if word == "minuta":
            word = "minut"
        if word == "minuty":
            word = "minut"
        if word == "minutu":
            word = "minut"
        if word == "minutu":
            word = "minut"
        if word == "sekunda":
            word = "sekund"
        if word == "sekundy":
            word = "sekund"
        if word == "sekundu":
            word = "sekund"
        if word == "dní":
            word = "den"
        if word == "dnů":
            word = "den"
        if word == "dny":
            word = "den"
        if word == "dnech":
            word = "den"
        if word == "týdny":
            word = "týden"
        if word == "týdnů":
            word = "týden"
        if word == "měsíců":
            word = "měsíc"
        if word == "měsíce":
            word = "měsíc"
        if word == "měsíci":
            word = "měsíc"
        if word == "roky":
            word = "rok"
        if word == "roků":
            word = "rok"
        if word == "let":
            word = "rok"
        if word == "lety":
            word = "rok"
        if word == "včerejšku":
            word = "včera"
        if word == "zítřku":
            word = "zítra"
        if word == "zítřejší":
            word = "zítra"
        if word == "ranní":
            word = "ráno"
        if word == "dopolední":
            word = "dopoledne"
        if word == "polední":
            word = "poledne"
        if word == "odpolední":
            word = "odpoledne"
        if word == "večerní":
            word = "večer"
        if word == "noční":
            word = "noc"
        # Accusative weekday forms ("v neděli", "v sobotu", "ve středu")
        if word == "neděli":
            word = "neděle"
        if word == "sobotu":
            word = "sobota"
        if word == "středu":
            word = "středa"

        if word == "víkendech":
            word = "víkend"
        if word == "víkendu":
            word = "víkend"
        if word == "všedních":
            word = "všední"
        if word == "všedním":
            word = "všední"

        # Months
        if word == "únoru":
            word = "únor"
        elif word == "února":
            word = "únor"
        elif word == "červenci":
            word = "červenec"
        elif word == "července":
            word = "červenec"
        elif word == "listopadu":
            word = "listopad"
        elif word == "prosinci":
            word = "prosinec"

        elif word.endswith("nu") or word.endswith("na"):
            tmp = word[:-2]
            tmp += ("en")
            for name in _MONTHS_CZECH:
                if name == tmp:
                    word = name

    return word
