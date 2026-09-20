import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser import numbers_to_digits
from ovos_number_parser.numbers_sl import pronounce_number_sl
from ovos_utils.time import DAYS_IN_1_MONTH, DAYS_IN_1_YEAR, now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def nice_time_sl(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format
    For example, generate 'pet trideset' for speech or '5:30' for
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

    def _hour_declension(hour):
        speak = pronounce_number_sl(hour)

        if hour == 1:
            return speak[:-1] + "ih"
        elif hour == 2 or hour == 4:
            return speak + "h"
        elif hour == 3:
            return speak[:-1] + "eh"
        elif hour == 7 or hour == 8:
            return speak[:-2] + "mih"
        else:
            return speak + "ih"

    # Generate a speakable version of the time
    if use_24hour:
        # "13 nič nič"
        speak = pronounce_number_sl(int(string[0:2]))

        speak += " "
        if string[3:5] == '00':
            speak += "nič nič"
        else:
            if string[3] == '0':
                speak += pronounce_number_sl(0) + " "
                speak += pronounce_number_sl(int(string[4]))
            else:
                speak += pronounce_number_sl(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "polnoč"
        elif dt.hour == 12 and dt.minute == 0:
            return "poldne"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        if dt.minute == 0:
            speak = pronounce_number_sl(hour)
        elif dt.minute < 30:
            speak = pronounce_number_sl(
                dt.minute) + " čez " + pronounce_number_sl(hour)
        elif dt.minute == 30:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = "pol " + _hour_declension(next_hour)
        elif dt.minute > 30:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = pronounce_number_sl(
                60 - dt.minute) + " do " + _hour_declension(next_hour)

        if use_ampm:
            if dt.hour > 11:
                speak += " p.m."
            else:
                speak += " a.m."

        return speak


def extract_duration_sl(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["sl"],
                                    resolution, replace_token)


_MONTHS_SL = ['januar', 'februar', 'marec', 'april', 'maj', 'junij',
              'julij', 'avgust', 'september', 'oktober', 'november',
              'december']

_MONTHS_EN = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november',
              'december']

# genitive ("3. junija") and locative ("v juniju") month forms
_MONTH_VARIANTS_SL = {
    'januarja': 'januar', 'januarju': 'januar',
    'februarja': 'februar', 'februarju': 'februar',
    'marca': 'marec', 'marcu': 'marec',
    'aprila': 'april', 'aprilu': 'april',
    'maja': 'maj', 'maju': 'maj',
    'junija': 'junij', 'juniju': 'junij',
    'julija': 'julij', 'juliju': 'julij',
    'avgusta': 'avgust', 'avgustu': 'avgust',
    'septembra': 'september', 'septembru': 'september',
    'oktobra': 'oktober', 'oktobru': 'oktober',
    'novembra': 'november', 'novembru': 'november',
    'decembra': 'december', 'decembru': 'december',
}

_DAYS_SL = ['ponedeljek', 'torek', 'sreda', 'četrtek', 'petek', 'sobota',
            'nedelja']

# accusative/locative weekday forms ("v sredo", "v soboto", "v nedeljo")
_DAY_VARIANTS_SL = {
    'sredo': 'sreda', 'sredi': 'sreda',
    'soboto': 'sobota', 'soboti': 'sobota',
    'nedeljo': 'nedelja', 'nedelji': 'nedelja',
    'ponedeljku': 'ponedeljek', 'torku': 'torek',
    'četrtku': 'četrtek', 'petku': 'petek',
}

# unit words normalized to a canonical form
_UNIT_VARIANTS_SL = {
    'dni': 'dan', 'dneva': 'dan', 'dnevi': 'dan', 'dnevih': 'dan',
    'dnevov': 'dan', 'dnevu': 'dan',
    'tedna': 'teden', 'tedne': 'teden', 'tedni': 'teden',
    'tednih': 'teden', 'tednov': 'teden', 'tednu': 'teden',
    'meseca': 'mesec', 'mesece': 'mesec', 'meseci': 'mesec',
    'mesecih': 'mesec', 'mesecev': 'mesec', 'mesecu': 'mesec',
    'leta': 'leto', 'leti': 'leto', 'letih': 'leto', 'let': 'leto',
    'letu': 'leto',
    'minuto': 'minut', 'minute': 'minut', 'minuti': 'minut',
    'minutah': 'minut',
    'uro': 'ur', 'ure': 'ur', 'uri': 'ur', 'urah': 'ur', 'ura': 'ur',
    'sekundo': 'sekund', 'sekunde': 'sekund', 'sekundi': 'sekund',
    'sekundah': 'sekund',
}

# hour names in the locative plural, as used after "ob" ("ob osmih")
_HOURS_LOCATIVE_SL = {
    'enih': 1, 'dveh': 2, 'treh': 3, 'štirih': 4, 'petih': 5,
    'šestih': 6, 'sedmih': 7, 'osmih': 8, 'devetih': 9, 'desetih': 10,
    'enajstih': 11, 'dvanajstih': 12,
}

_NEXT_WORDS_SL = ('naslednji', 'naslednja', 'naslednjo', 'naslednje',
                  'naslednjem', 'prihodnji', 'prihodnja', 'prihodnjo',
                  'prihodnje', 'prihodnjem')
_LAST_WORDS_SL = ('prejšnji', 'prejšnja', 'prejšnjo', 'prejšnje',
                  'prejšnjem', 'zadnji', 'zadnja', 'zadnjo')

_MARKERS_SL = ['v', 'ob', 'na', 'za', 'čez', 'ta', 'to', 'do']


def extract_datetime_sl(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "danes"
        "jutri popoldne"
        "v sredo ob štirih popoldne"
        "3. junija"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "jutri", etc
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
        word = _DAY_VARIANTS_SL.get(word, word)
        word = _MONTH_VARIANTS_SL.get(word, word)
        word = _UNIT_VARIANTS_SL.get(word, word)
        return word

    s = text.lower().replace(',', ' ').replace('?', ' ')
    words = []
    for w in s.split():
        # strip the ordinal dot: "3. junija" -> "3 junija"
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

    timeQualifiersAM = ['zjutraj', 'dopoldne', 'dopoldan']
    timeQualifiersPM = ['popoldne', 'popoldan', 'zvečer', 'ponoči']

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
        elif word == "danes":
            dayOffset = 0
            used = 1
        elif word == "jutri":
            dayOffset = 1
            used = 1
        elif word == "pojutrišnjem":
            dayOffset = 2
            used = 1
        elif word == "včeraj":
            dayOffset = -1
            used = 1
        elif word in ("predvčerajšnjim", "predvčeraj"):
            dayOffset = -2
            used = 1
        # parse "čez 5 dni", "pred 5 dnevi"
        elif word == "dan" and wordPrev and wordPrev[0].isdigit():
            dayOffset = (dayOffset or 0) + int(wordPrev)
            start -= 1
            used = 2
            if wordPrevPrev == "pred":
                dayOffset = -dayOffset
                start -= 1
                used += 1
        # parse "naslednji teden", "prejšnji teden", "čez 2 tedna"
        elif word == "teden":
            if wordPrev and wordPrev[0].isdigit():
                dayOffset = (dayOffset or 0) + int(wordPrev) * 7
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    dayOffset = -dayOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SL:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SL:
                dayOffset = -7
                start -= 1
                used = 2
        # parse "naslednji mesec", "čez 3 mesece"
        elif word == "mesec" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    monthOffset = -monthOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SL:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SL:
                monthOffset = -1
                start -= 1
                used = 2
        # parse "naslednje leto", "čez 2 leti"
        elif word == "leto" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    yearOffset = -yearOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SL:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SL:
                yearOffset = -1
                start -= 1
                used = 2
        # parse weekdays: "v ponedeljek", "naslednjo sredo"
        elif word in _DAYS_SL:
            d = _DAYS_SL.index(word)
            dayOffset = (d - anchorDate.weekday()) % 7
            used = 1
            if wordPrev in _NEXT_WORDS_SL:
                if dayOffset <= 2:
                    dayOffset += 7
                start -= 1
                used += 1
            elif wordPrev in _LAST_WORDS_SL:
                dayOffset -= 7
                start -= 1
                used += 1
        # parse "3. junija", "junij 2027", "5. maja 2030"
        elif word in _MONTHS_SL:
            m = _MONTHS_SL.index(word)
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
            if start - 1 >= 0 and words[start - 1] in _MARKERS_SL:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None

    def _apply_time_qualifier(hour):
        # "ponoči" (in the night) keeps the small hours in the AM: "ob enih
        # ponoči" is 1:00, while "ob enajstih ponoči" is 23:00.
        if timeQualifier == "ponoči":
            return hour + 12 if 5 < hour < 12 else hour
        if timeQualifier in timeQualifiersPM and 0 < hour < 12:
            return hour + 12
        if timeQualifier in timeQualifiersAM and hour >= 12:
            return hour - 12
        return hour

    for idx, word in enumerate(words):
        if word == "":
            continue
        word = normalize(word)
        wordPrev = normalize(words[idx - 1]) if idx > 0 else ""
        wordPrevPrev = normalize(words[idx - 2]) if idx > 1 else ""
        wordNext = normalize(words[idx + 1]) if idx + 1 < len(words) else ""
        start = idx
        used = 0

        if word in ("opoldne", "opoldan", "poldne"):
            hrAbs = 12
            minAbs = 0
            used = 1
        elif word in ("opolnoči", "polnoč", "polnoči"):
            hrAbs = 0
            minAbs = 0
            used = 1
        elif word == "zjutraj":
            if hrAbs is None:
                hrAbs = 8
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("dopoldne", "dopoldan"):
            if hrAbs is None:
                hrAbs = 10
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("popoldne", "popoldan"):
            if hrAbs is None:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word == "zvečer":
            if hrAbs is None:
                hrAbs = 19
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word == "ponoči":
            if hrAbs is None:
                hrAbs = 22
            elif 5 < hrAbs < 12:
                hrAbs += 12
            used = 1
        # parse spoken hours: "ob osmih", "ob pol devetih" (= 8:30,
        # "pol" counts towards the NEXT hour)
        elif word in _HOURS_LOCATIVE_SL:
            hrAbs = _HOURS_LOCATIVE_SL[word]
            minAbs = 0
            used = 1
            if wordPrev == "pol":
                hrAbs -= 1
                minAbs = 30
                start -= 1
                used += 1
            hrAbs = _apply_time_qualifier(hrAbs)
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
                # parse "čez 5 minut", "čez 3 ure", "čez 30 sekund"
                if wordNext in ("minut", "ur", "sekund") and \
                        wordPrev in ("čez", "za"):
                    value = int(word)
                    if wordNext == "minut":
                        minOffset = value
                    elif wordNext == "ur":
                        hrOffset = value
                    else:
                        secOffset = value
                    hrAbs = -1
                    minAbs = -1
                    start -= 1
                    used = 3
                elif int(word) <= 24 and \
                        (wordPrev == "ob" or wordNext == "ur"):
                    # "ob 8", "ob 17h"
                    strHH = word
                    used = 1
                    if wordNext == "ur":
                        used += 1
            if strHH:
                HH = int(strHH)
                MM = int(strMM) if strMM else 0
                if HH <= 24 and MM <= 59:
                    HH = _apply_time_qualifier(HH)
                    hrAbs = HH % 24
                    minAbs = MM
                else:
                    used = 0

        if used > 0:
            for i in range(used):
                if 0 <= start + i < len(words):
                    words[start + i] = ""
            if start - 1 >= 0 and words[start - 1] in _MARKERS_SL:
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
        temp = None
        for fmt in ("%B %d %Y", "%B %d", "%B %Y", "%B"):
            try:
                temp = datetime.strptime(datestr, fmt)
                break
            except ValueError:
                continue
        if temp is None:
            # a leap day like "29. februarja" has no valid date in the
            # default year 1900; parse it against a known leap year
            try:
                temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
            except ValueError:
                # an impossible calendar date like "30. februarja"; report
                # nothing rather than a wrong guess
                return None
        month = temp.month
        day = temp.day
        extractedDate = extractedDate.replace(hour=0, minute=0, second=0)

        def _on_or_after(year):
            # roll forward to the next year the day exists in, so that
            # "29. februarja" lands on the next actual 29 February
            while True:
                try:
                    return extractedDate.replace(year=year, month=month,
                                                 day=day,
                                                 tzinfo=extractedDate.tzinfo)
                except ValueError:
                    year += 1

        if not hasYear:
            thisYear = _on_or_after(int(currentYear))
            if extractedDate < thisYear:
                extractedDate = thisYear
            else:
                extractedDate = _on_or_after(int(currentYear) + 1)
        else:
            extractedDate = _on_or_after(temp.year)
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
