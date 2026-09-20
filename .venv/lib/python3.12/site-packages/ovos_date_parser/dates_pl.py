import calendar
import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_pl import pronounce_number_pl, extract_number_pl, numbers_to_digits_pl
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

_TIME_UNITS_CONVERSION = {
    'mikrosekund': 'microseconds',
    'mikrosekundy': 'microseconds',
    'milisekund': 'milliseconds',
    'milisekundy': 'milliseconds',
    'sekunda': 'seconds',
    'sekundy': 'seconds',
    'sekund': 'seconds',
    'minuta': 'minutes',
    'minuty': 'minutes',
    'minut': 'minutes',
    'godzina': 'hours',
    'godziny': 'hours',
    'godzin': 'hours',
    'dzień': 'days',
    'dni': 'days',
    'tydzień': 'weeks',
    'tygodni': 'weeks',
    'tygodnie': 'weeks',
    'tygodniu': 'weeks',
}

_TIME_UNITS_NORMALIZATION = {
    'mikrosekunda': 'mikrosekunda',
    'mikrosekundę': 'mikrosekunda',
    'mikrosekund': 'mikrosekunda',
    'mikrosekundy': 'mikrosekunda',
    'milisekunda': 'milisekunda',
    'milisekundę': 'milisekunda',
    'milisekund': 'milisekunda',
    'milisekundy': 'milisekunda',
    'sekunda': 'sekunda',
    'sekundę': 'sekunda',
    'sekundy': 'sekunda',
    'sekund': 'sekunda',
    'minuta': 'minuta',
    'minutę': 'minuta',
    'minut': 'minuta',
    'minuty': 'minuta',
    'godzina': 'godzina',
    'godzinę': 'godzina',
    'godzin': 'godzina',
    'godziny': 'godzina',
    'dzień': 'dzień',
    'dni': 'dzień',
    'tydzień': 'tydzień',
    'tygodni': 'tydzień',
    'tygodnie': 'tydzień',
    'tygodniu': 'tydzień',
    'miesiąc': 'miesiąc',
    'miesiące': 'miesiąc',
    'miesięcy': 'miesiąc',
    'rok': 'rok',
    'lata': 'rok',
    'lat': 'rok',
    'dekada': 'dekada',
    'dekad': 'dekada',
    'dekady': 'dekada',
    'dekadę': 'dekada',
    'wiek': 'wiek',
    'wieki': 'wiek',
    'milenia': 'milenia',
    'milenium': 'milenia',
}

_MONTHS_TO_EN = {
    'styczeń': 'January',
    'stycznia': 'January',
    'luty': 'February',
    'lutego': 'February',
    'marzec': 'March',
    'marca': 'March',
    'kwiecień': 'April',
    'kwietnia': 'April',
    'maj': 'May',
    'maja': 'May',
    'czerwiec': 'June',
    'czerwca': 'June',
    'lipiec': 'July',
    'lipca': 'July',
    'sierpień': 'August',
    'sierpnia': 'August',
    'wrzesień': 'September',
    'września': 'September',
    'październik': 'October',
    'października': 'October',
    'listopad': 'November',
    'listopada': 'November',
    'grudzień': 'December',
    'grudnia': 'December',
}

_DAYS_TO_EN = {
    'poniedziałek': 0,
    'poniedziałkach': 0,
    'poniedziałkami': 0,
    'poniedziałki': 0,
    'poniedziałkiem': 0,
    'poniedziałkom': 0,
    'poniedziałkowa': 0,
    'poniedziałkową': 0,
    'poniedziałkowe': 0,
    'poniedziałkowego': 0,
    'poniedziałkowej': 0,
    'poniedziałkowemu': 0,
    'poniedziałkowi': 0,
    'poniedziałkowy': 0,
    'poniedziałkowych': 0,
    'poniedziałkowym': 0,
    'poniedziałkowymi': 0,
    'poniedziałków': 0,
    'poniedziałku': 0,
    'wtorek': 1,
    'wtorkach': 1,
    'wtorkami': 1,
    'wtorki': 1,
    'wtorkiem': 1,
    'wtorkom': 1,
    'wtorkowa': 1,
    'wtorkową': 1,
    'wtorkowe': 1,
    'wtorkowego': 1,
    'wtorkowej': 1,
    'wtorkowemu': 1,
    'wtorkowi': 1,
    'wtorkowy': 1,
    'wtorkowych': 1,
    'wtorkowym': 1,
    'wtorkowymi': 1,
    'wtorków': 1,
    'wtorku': 1,
    'środa': 2,
    'środach': 2,
    'środami': 2,
    'środą': 2,
    'środę': 2,
    'środo': 2,
    'środom': 2,
    'środowa': 2,
    'środową': 2,
    'środowe': 2,
    'środowego': 2,
    'środowej': 2,
    'środowemu': 2,
    'środowi': 2,
    'środowy': 2,
    'środowych': 2,
    'środowym': 2,
    'środowymi': 2,
    'środy': 2,
    'środzie': 2,
    'śród': 2,
    'czwartek': 3,
    'czwartkach': 3,
    'czwartkami': 3,
    'czwartki': 3,
    'czwartkiem': 3,
    'czwartkom': 3,
    'czwartkowa': 3,
    'czwartkową': 3,
    'czwartkowe': 3,
    'czwartkowego': 3,
    'czwartkowej': 3,
    'czwartkowemu': 3,
    'czwartkowi': 3,
    'czwartkowy': 3,
    'czwartkowych': 3,
    'czwartkowym': 3,
    'czwartkowymi': 3,
    'czwartków': 3,
    'czwartku': 3,
    'piątek': 4,
    'piątkach': 4,
    'piątkami': 4,
    'piątki': 4,
    'piątkiem': 4,
    'piątkom': 4,
    'piątkowa': 4,
    'piątkową': 4,
    'piątkowe': 4,
    'piątkowego': 4,
    'piątkowej': 4,
    'piątkowemu': 4,
    'piątkowi': 4,
    'piątkowy': 4,
    'piątkowych': 4,
    'piątkowym': 4,
    'piątkowymi': 4,
    'piątków': 4,
    'piątku': 4,
    'sobocie': 5,
    'sobota': 5,
    'sobotach': 5,
    'sobotami': 5,
    'sobotą': 5,
    'sobotę': 5,
    'sobotni': 5,
    'sobotnia': 5,
    'sobotnią': 5,
    'sobotnich': 5,
    'sobotnie': 5,
    'sobotniego': 5,
    'sobotniej': 5,
    'sobotniemu': 5,
    'sobotnim': 5,
    'sobotnimi': 5,
    'soboto': 5,
    'sobotom': 5,
    'soboty': 5,
    'sobót': 5,
    'niedziel': 6,
    'niedziela': 6,
    'niedzielach': 6,
    'niedzielami': 6,
    'niedzielą': 6,
    'niedziele': 6,
    'niedzielę': 6,
    'niedzieli': 6,
    'niedzielna': 6,
    'niedzielną': 6,
    'niedzielne': 6,
    'niedzielnego': 6,
    'niedzielnej': 6,
    'niedzielnemu': 6,
    'niedzielni': 6,
    'niedzielny': 6,
    'niedzielnych': 6,
    'niedzielnym': 6,
    'niedzielnymi': 6,
    'niedzielo': 6,
    'niedzielom': 6
}


def nice_time_pl(dt, speech=True, use_24hour=True, use_ampm=False):
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
    string = dt.strftime("%H:%M")
    if not speech:
        return string

    # Generate a speakable version of the time
    speak = ""

    # Either "0 8 hundred" or "13 hundred"
    if string[0:2] == '00':
        speak = ""
    elif string[0] == '0':
        speak += pronounce_number_pl(int(string[1]), ordinals=True)
        speak = speak[:-1] + 'a'
    else:
        speak = pronounce_number_pl(int(string[0:2]), ordinals=True)
        speak = speak[:-1] + 'a'

    speak += ' ' if string[0:2] != '00' else ''
    if string[3:5] == '00':
        speak += 'zero zero'
    else:
        if string[3] == '0':
            speak += pronounce_number_pl(int(string[4]))
        else:
            speak += pronounce_number_pl(int(string[3:5]))

    if string[0:2] == '00':
        speak += " po północy"
    return speak


def nice_duration_pl(duration, speech=True):
    """ Convert duration to a nice spoken timespan

    Args:
        seconds: number of seconds
        minutes: number of minutes
        hours: number of hours
        days: number of days
    Returns:
        str: timespan as a string
    """
    if not speech:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        _days = int(duration // 86400)
        _hours = int(duration // 3600 % 24)
        _minutes = int(duration // 60 % 60)
        _seconds = int(duration % 60)
        out = ""
        if _days > 0:
            out = str(_days) + "d "
        if _hours > 0 or _days > 0:
            out += str(_hours) + ":"
        if _minutes < 10 and (_hours > 0 or _days > 0):
            out += "0"
        out += str(_minutes) + ":"
        if _seconds < 10:
            out += "0"
        out += str(_seconds)
        return out

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    out = ''
    sec_main, sec_div = divmod(seconds, 10)
    min_main, min_div = divmod(minutes, 10)
    hour_main, hour_div = divmod(hours, 10)

    if days > 0:
        out += pronounce_number_pl(days) + " "
        if days == 1:
            out += 'dzień'
        else:
            out += 'dni'
    if hours > 0:
        if out:
            out += " "
        out += get_pronounce_number_for_duration(hours) + " "
        if hours == 1:
            out += 'godzina'
        elif hour_main == 1 or hour_div > 4:
            out += 'godzin'
        else:
            out += 'godziny'
    if minutes > 0:
        if out:
            out += " "
        out += get_pronounce_number_for_duration(minutes) + " "
        if minutes == 1:
            out += 'minuta'
        elif min_main == 1 or min_div > 4:
            out += 'minut'
        else:
            out += 'minuty'
    if seconds > 0:
        if out:
            out += " "
        out += get_pronounce_number_for_duration(seconds) + " "
        if sec_div == 0:
            out += 'sekund'
        elif seconds == 1:
            out += 'sekunda'
        elif sec_main == 1 or sec_div > 4:
            out += 'sekund'
        else:
            out += 'sekundy'

    return out


def get_pronounce_number_for_duration(num):
    pronounced = pronounce_number_pl(num)

    return 'jedna' if pronounced == 'jeden' else pronounced


def extract_duration_pl(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["pl"],
                                    resolution, replace_token)


# Ordinal day-of-month words in the genitive case Polish uses for dates,
# e.g. "piętnastego stycznia" -> 15 January. Mapped to the day number so the
# date parser can treat them like a numeric day.
_ORDINAL_DAY_UNITS_PL = {
    1: 'pierwszego', 2: 'drugiego', 3: 'trzeciego', 4: 'czwartego',
    5: 'piątego', 6: 'szóstego', 7: 'siódmego', 8: 'ósmego',
    9: 'dziewiątego', 10: 'dziesiątego', 11: 'jedenastego', 12: 'dwunastego',
    13: 'trzynastego', 14: 'czternastego', 15: 'piętnastego',
    16: 'szesnastego', 17: 'siedemnastego', 18: 'osiemnastego',
    19: 'dziewiętnastego', 20: 'dwudziestego', 30: 'trzydziestego',
}


def _build_ordinal_days_pl():
    phrases = {}
    for day in range(1, 32):
        if day in _ORDINAL_DAY_UNITS_PL:
            phrase = _ORDINAL_DAY_UNITS_PL[day]
        elif 21 <= day <= 29:
            phrase = _ORDINAL_DAY_UNITS_PL[20] + ' ' \
                + _ORDINAL_DAY_UNITS_PL[day - 20]
        else:  # 31
            phrase = _ORDINAL_DAY_UNITS_PL[30] + ' ' + _ORDINAL_DAY_UNITS_PL[1]
        phrases[phrase] = day
    return phrases


_ORDINAL_DAYS_PL = _build_ordinal_days_pl()


def extract_datetime_pl(string, anchorDate=None, default_time=None):
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
        string (str): string containing date words
        anchorDate (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s):
        # clean unneeded punctuation and capitalization among other things.
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace("para", "2")

        # spoken ordinal day-of-month ("piętnastego stycznia") -> "15 stycznia"
        # longest phrase first so "dwudziestego pierwszego" wins over "dwudziestego"
        for phrase in sorted(_ORDINAL_DAYS_PL, key=len, reverse=True):
            s = re.sub(r'\b' + phrase + r'\b',
                       str(_ORDINAL_DAYS_PL[phrase]), s)

        wordList = s.split()
        for idx, word in enumerate(wordList):
            ordinals = ["ci", "szy", "gi"]
            if word and word[0].isdigit():
                for ordinal in ordinals:
                    if ordinal in word:
                        word = word.replace(ordinal, "")
            wordList[idx] = _TIME_UNITS_NORMALIZATION.get(word, word)

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

    if string == "":
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

    timeQualifiersAM = ['rano']
    timeQualifiersPM = ['wieczór', 'w nocy']
    timeQualifiersList = set(timeQualifiersAM + timeQualifiersPM)
    markers = ['na', 'w', 'we', 'na', 'przez', 'ten', 'około', 'dla', 'o', "pomiędzy", 'za', 'do']
    days = list(_DAYS_TO_EN.keys())
    recur_markers = days + ['weekend', 'weekendy']
    monthsShort = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie',
                   'wrz', 'paź', 'lis', 'gru']
    year_multiples = ['dekada', 'wiek', 'milenia']

    words = clean_string(string)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        start = idx
        used = 0
        # save timequalifier for later
        if word == 'w' and wordNext == 'tę':
            used += 2
        if word == "temu" and dayOffset:
            dayOffset = - dayOffset
            used += 1
        elif word == "temu" and monthOffset:
            monthOffset = - monthOffset
            used += 1
        elif word == "temu" and yearOffset:
            yearOffset = - yearOffset
            used += 1
        if word == "teraz" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_pl(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if _TIME_UNITS_NORMALIZATION.get(wordNext) == "dekada":
                yearOffset = multiplier * 10
            elif _TIME_UNITS_NORMALIZATION.get(wordNext) == "wiek":
                yearOffset = multiplier * 100
            elif _TIME_UNITS_NORMALIZATION.get(wordNext) == "milenia":
                yearOffset = multiplier * 1000
        elif word in timeQualifiersList:
            timeQualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "dzisiaj" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "jutro" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "przedwczoraj" and not fromFlag:
            dayOffset = -2
            used += 1
        elif word == "wczoraj" and not fromFlag:
            dayOffset = -1
            used += 1
        elif word == "pojutrze" and not fromFlag:
            dayOffset = 2
            used = 1
        elif word == "dzień" and wordNext != 'robocze':
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev)
                start -= 1
                used = 2
        elif word == "tydzień" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
            elif wordPrev == "następny":
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev == "poprzedni" or wordPrev == 'ostatni':
                dayOffset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif word == "miesiąc" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev == "następny":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "poprzedni" or wordPrev == 'ostatni':
                monthOffset = -1
                start -= 1
                used = 2
        # parse 5 years, next year, last year
        elif word == "rok" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
            elif wordPrev == "następny":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "poprzedni" or wordPrev == 'ostatni':
                yearOffset = -1
                start -= 1
                used = 2
        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not fromFlag:
            d = _DAYS_TO_EN.get(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev == "następny":
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "poprzedni" or wordPrev == 'ostatni':
                dayOffset -= 7
                used += 1
                start -= 1
                # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in _MONTHS_TO_EN or word in monthsShort and not fromFlag:
            used += 1
            datestr = _MONTHS_TO_EN[word]
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

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + list(_MONTHS_TO_EN.keys()) + monthsShort
        validFollowups.append("dzisiaj")
        validFollowups.append("jutro")
        validFollowups.append("wczoraj")
        validFollowups.append("następny")
        validFollowups.append("poprzedni")
        validFollowups.append('ostatni')
        validFollowups.append("teraz")
        validFollowups.append("tego")
        if (word == "od" or word == "po") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "jutro":
                dayOffset += 1
            elif wordNext == "wczoraj":
                dayOffset -= 1
            elif wordNext in days:
                d = _DAYS_TO_EN.get(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if tmpOffset < 0:
                    tmpOffset += 7
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = _DAYS_TO_EN.get(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNext == "następny":
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext == "poprzedni" or wordNext == 'ostatni':
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] == "ten":  # this
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
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "południe":
            hrAbs = 12
            used += 1
        elif word == "północ" or word == 'północy':
            hrAbs = 0
            used += 1
        elif word == "rano":
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word == "po" and wordNext == "południu":
            if hrAbs is None:
                hrAbs = 15
            used += 2
        elif word == "wieczór" or word == 'wieczorem':
            if hrAbs is None:
                hrAbs = 19
            used += 1
        elif word == "nocy":
            if hrAbs is None:
                hrAbs = 22
            used += 1
        # parse half an hour, quarter hour
        elif word == "godzina" and (wordPrev.isdigit() or wordPrev in markers or wordPrevPrev in markers):
            if wordPrev == "pół":
                minOffset = 30
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "dzisiaj":
                    daySpecified = True
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
            # parse 5:00 am, 12:00 p.m., etc
        # parse in a minute
        elif word == "minuta" and (wordPrev.isdigit() or wordPrev in markers):
            minOffset = 1
            words[idx - 1] = ""
            used += 1
        # parse in a second
        elif word == "sekunda" and (wordPrev.isdigit() or wordPrev in markers):
            secOffset = 1
            words[idx - 1] = ""
            used += 1
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if wordNext == "wieczorem" or wordPrev == "wieczorem" or \
                    wordNext == 'wieczór' or wordPrev == 'wieczór' or \
                    (wordNext == 'po' and wordNextNext == 'południu'):
                remainder = "pm"
                used += 2 if wordNext == 'po' else 1
                if wordPrev == "wieczorem" or wordPrev == 'wieczór':
                    words[idx - 1] = ""

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
                    if wordNext == "rano":
                        remainder = "am"
                        used += 1
                    elif wordNext == "po" and wordNextNext == "południu":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "wieczorem":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "rano":
                        remainder = "am"
                        used += 1
                    elif wordNext == "w" and wordNextNext == "nocy":
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
                wordNextNextNext = words[idx + 3] \
                    if idx + 3 < len(words) else ""
                for i in range(length):
                    if word[i].isdigit():
                        strNum += word[i]
                    else:
                        remainder += word[i]

                if remainder == "":
                    remainder = wordNext.replace(".", "").lstrip().rstrip()
                if (
                        remainder == "pm" or
                        (word and word[0].isdigit() and (wordNext == 'wieczorem' or wordNext == 'wieczór')) or
                        (word and word[0].isdigit() and wordNext == 'po' and wordNextNext == 'południu') or
                        (word and word[0].isdigit() and wordNext == 'w' and wordNextNext == 'nocy')):
                    strHH = strNum
                    remainder = "pm"
                    used = 2 if wordNext in ['po', 'w'] else 1
                elif (
                        remainder == "am" or
                        (word and word[0].isdigit() and wordNext == 'rano')):
                    strHH = strNum
                    remainder = "am"
                    used = 1
                elif (
                        remainder in recur_markers or
                        wordNext in recur_markers or
                        wordNextNext in recur_markers or (
                                wordNext == 'w' and wordNextNext == 'dzień' and
                                wordNextNextNext == 'robocze'
                        )):
                    # Ex: "7 on mondays" or "3 this friday"
                    # Set strHH so that isTime == True
                    # when am or pm is not specified
                    strHH = strNum
                    used = 1
                else:
                    if _TIME_UNITS_NORMALIZATION.get(wordNext) == "godzina" or \
                            _TIME_UNITS_NORMALIZATION.get(remainder) == "godzina":
                        # "in 10 hours"
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif _TIME_UNITS_NORMALIZATION.get(wordNext) == "minuta" or \
                            _TIME_UNITS_NORMALIZATION.get(remainder) == "minuta":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif _TIME_UNITS_NORMALIZATION.get(wordNext) == "sekunda" \
                            or _TIME_UNITS_NORMALIZATION.get(remainder) == "sekunda":
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
                        if _TIME_UNITS_NORMALIZATION.get(wordNext) == "godzina" or \
                                _TIME_UNITS_NORMALIZATION.get(remainder) == "godzina":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        # military time, e.g. "04 38 hours"
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                    elif (
                            wordNext == "" or wordNext == "w" or wordNext == 'nocy' or
                            wordNextNext == 'nocy'):
                        strHH = strNum
                        strMM = "00"

                        if wordNext == "za" or wordNextNext == "za":
                            used += (1 if wordNext == "za" else 2)
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
                    remainder not in ['am', 'pm'] and
                    remainder not in _TIME_UNITS_NORMALIZATION and
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

            if wordPrev == "rano":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "wieczorem":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
                if wordPrev == "najbliższą":
                    daySpecified = True
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "najbliższą":
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
            # Try again, allowing the year, then a leap-safe day, then a
            # bare month. "February 29" has no valid date in the default
            # year 1900, so parse the day against a known leap year.
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                try:
                    temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
                except ValueError:
                    try:
                        temp = datetime.strptime(datestr, "%B %Y")
                    except ValueError:
                        try:
                            temp = datetime.strptime(datestr, "%B")
                        except ValueError:
                            # an impossible calendar date like "30 luty";
                            # report nothing rather than a wrong guess
                            return None
        extractedDate = extractedDate.replace(hour=0, minute=0, second=0)
        month = temp.month
        day = temp.day
        if hasYear:
            year = temp.year
        elif month == 2 and day == 29:
            # 29 February only exists in leap years: pick the next leap
            # year on or after the reference date
            year = int(currentYear)
            while not (calendar.isleap(year) and
                       datetime(year, 2, 29, tzinfo=extractedDate.tzinfo)
                       >= extractedDate):
                year += 1
        else:
            year = int(currentYear)
            candidate = extractedDate.replace(year=year, month=month, day=day)
            if not extractedDate < candidate:
                year += 1
        extractedDate = extractedDate.replace(
            year=year, month=month, day=day, tzinfo=extractedDate.tzinfo)
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
        if word == "i" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]
