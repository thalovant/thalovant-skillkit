import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_az import pronounce_number_az, extract_number_az, numbers_to_digits_az
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

_HARD_VOWELS = ['a', 'ı', 'o', 'u']
_SOFT_VOWELS = ['e', 'ə', 'i', 'ö', 'ü']
_VOWELS = _HARD_VOWELS + _SOFT_VOWELS


def _get_full_time_ak(hour):
    if hour in [1, 3, 4, 5, 8, 11]:
        return "ə"
    if hour in [2, 7, 12]:
        return "yə"
    if hour in [9, 10]:
        return "a"
    return "ya"


def _get_half_time_ak(hour):
    if hour in [1, 5, 8, 11]:
        return "in"
    if hour in [2, 7, 12]:
        return "nin"
    if hour in [3, 4]:
        return "ün"
    if hour in [9, 10]:
        return "un"
    return "nın"


def _get_daytime(hour):
    if hour < 6:
        return "gecə"
    if hour < 12:
        return "səhər"
    if hour < 18:
        return "gündüz"
    return "axşam"


def _get_last_vowel(word):
    is_last = True
    for char in word[::-1]:
        if char in _VOWELS:
            return char, is_last
        is_last = False

    return "", is_last


def _last_vowel_type(word):
    return _get_last_vowel(word)[0] in _HARD_VOWELS


def _generate_plurals_az(originals):
    """
    Return a new set or dict containing the plural form of the original values,

    In Azerbaijani this means appending 'lar' or 'lər' to them according to the last vowel in word.

    Args:
        originals set(str) or dict(str, any): values to pluralize

    Returns:
        set(str) or dict(str, any)

    """

    if isinstance(originals, dict):
        return {key + ('lar' if _last_vowel_type(key) else 'lər'): value for key, value in originals.items()}
    return {value + ('lar' if _last_vowel_type(value) else 'lər') for value in originals}


def nice_time_az(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format
    For example, generate 'altının yarısı' for speech or '5:30' for
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
            string = dt.strftime("%I:%M")
            if string[0] == '0':
                string = string[1:]  # strip leading zeros
            string = _get_daytime(dt.hour) + " " + string
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

        # Either "0 8" or "13"
        if string[0] == '0':
            speak += pronounce_number_az(int(string[0])) + " "
            speak += pronounce_number_az(int(string[1]))
        else:
            speak = pronounce_number_az(int(string[0:2]))

        speak += " "
        if string[3] == '0':
            speak += pronounce_number_az(0) + " "
            speak += pronounce_number_az(int(string[4]))
        else:
            speak += pronounce_number_az(int(string[3:5]))
        return speak
    else:

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        next_hour = (dt.hour + 1) % 12 or 12
        speak = ""
        if use_ampm:
            speak += _get_daytime(dt.hour) + " "

        if dt.minute == 0:
            speak += "{} tamamdır".format(pronounce_number_az(hour))
        elif dt.minute < 30:
            speak += "{}{} {} dəqiqə işləyib".format(pronounce_number_az(next_hour), _get_full_time_ak(next_hour),
                                                     pronounce_number_az(dt.minute))
        elif dt.minute == 30:
            speak += "{}{} yarısı".format(pronounce_number_az(next_hour), _get_half_time_ak(next_hour))
        else:
            speak += "{}{} {} dəqiqə qalıb".format(pronounce_number_az(next_hour), _get_full_time_ak(next_hour),
                                                   pronounce_number_az(dt.minute - 30))

        return speak


def nice_duration_az(duration, speech=True):
    """ Convert duration in seconds to a nice spoken timespan

    Examples:
       duration = 60  ->  "1:00" or "bir dəqiqə"
       duration = 163  ->  "2:43" or "iki deqiqe qırx üç saniyə"

    Args:
        duration: time, in seconds
        speech (bool): format for speech (True) or display (False)

    Returns:
        str: timespan as a string
    """

    if isinstance(duration, timedelta):
        duration = duration.total_seconds()

    # Do traditional rounding: 2.5->3, 3.5->4, plus this
    # helps in a few cases of where calculations generate
    # times like 2:59:59.9 instead of 3:00.
    duration += 0.5

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    if speech:
        out = ""
        if days > 0:
            out += pronounce_number_az(days) + " "
            out += "gün"
        if hours > 0:
            if out:
                out += " "
            out += pronounce_number_az(hours) + " "
            out += "saat"
        if minutes > 0:
            if out:
                out += " "
            out += pronounce_number_az(minutes) + " "
            out += "dəqiqə"
        if seconds > 0:
            if out:
                out += " "
            out += pronounce_number_az(seconds) + " "
            out += "saniyə"
    else:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        out = ""
        if days > 0:
            out = str(days) + "g "
        if hours > 0 or days > 0:
            out += str(hours) + ":"
        if minutes < 10 and (hours > 0 or days > 0):
            out += "0"
        out += str(minutes) + ":"
        if seconds < 10:
            out += "0"
        out += str(seconds)

    return out


def extract_duration_az(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["az"],
                                    resolution, replace_token)


def extract_datetime_az(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "bu gün"
        "sabah günortadan sonra"
        "gələn çərşənbə axşamı günorta 4 də"
        "3 avqust"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.  For example, the string
       "çərşənbə axşamı hava necədir"
    returns the date for the forthcoming çərşənbə axşamı relative to the reference
    date and the remainder string
       "hava necədir".

    The "gələn" instance of a day or weekend is considered to be no earlier than
    48 hours in the future. On Friday, "gələn Bazar ertəsi" would be in 3 days.
    On Saturday, "gələn Bazar ertəsi" would be in 9 days.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "sabah", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s, word_list):
        # normalize and lowercase utt  (replaces words with numbers)
        s = numbers_to_digits_az(s, ordinals=None)
        # clean unneeded punctuation and capitalization among other things.
        s = s.lower().replace('?', '').replace('.', '').replace(',', '')

        wordList = s.split()
        skip_next_word = False
        new_words = []
        for idx, word in enumerate(wordList):
            if skip_next_word:
                skip_next_word = False
                continue
            wordNext = wordList[idx + 1] if idx + 1 < len(wordList) else ""
            ordinals = ["ci", "cü", "cı", "cu"]
            if word and word[0].isdigit():
                for ordinal in ordinals:
                    if ordinal in wordNext:
                        skip_next_word = True
            if ((word == "bu" and wordNext == "gün") or
                    (word in ['cümə', 'çərşənbə'] and 'axşamı ' in wordNext) or
                    (word == 'bazar' and 'ertəsi' in wordNext) or
                    (word == 'günortadan' and wordNext == 'sonra') or
                    (word == 'gecə' and 'yarısı' in wordNext)):
                word = word + ' ' + wordNext
                skip_next_word = True

            for orig_word in word_list:
                if word.startswith(orig_word):
                    word = orig_word
                    break

            new_words.append(word)

        return new_words

    def date_found():
        return found or \
            (
                    datestr != "" or
                    yearOffset != 0 or monthOffset != 0 or
                    dayOffset is True or hrOffset != 0 or
                    hrAbs or minOffset != 0 or
                    minAbs or secOffset != 0
            )

    if not anchorDate:
        anchorDate = now_local()

    if text == "":
        return None

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
    word_list = []
    timeQualifiersAM = ['səhər', 'gecə']
    timeQualifiersPM = ['günorta', 'axşam', 'nahar']
    word_list += timeQualifiersAM + timeQualifiersPM
    timeQualifiersList = set(timeQualifiersAM + timeQualifiersPM)
    markers = ['da', 'də', 'sonra', "ərzində", "günündən", "günü", "gündən", "gün"]
    days = ['bazar ertəsi', 'çərşənbə axşamı', 'çərşənbə',
            'cümə axşamı', 'cümə', 'şənbə', 'bazar']
    months = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
              'iyul', 'avqust', 'sentyabr', 'oktyabr', 'moyabr',
              'dekabr']
    eng_months = ['january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november',
                  'december']
    word_list += days + months
    recur_markers = days + [_generate_plurals_az(d) for d in days] + ['həftə sonu', 'iş günü',
                                                                      'həftə sonları', 'iş günləri']
    monthsShort = ['yan', 'fev', 'mar', 'apr', 'may', 'ıyn', 'ıyl', 'avq',
                   'sen', 'okt', 'noy', 'dek']
    year_multiples = ["onillik", "yüzillik", "minillik"]
    day_multiples = ["həftə", "ay", "il"]
    word_list += year_multiples + day_multiples + ['saat', 'dəqiqə', 'saniyə', 'sonra', 'gecə yarısı',
                                                   'günortadan sonra', 'gün']
    word_list.sort(key=lambda x: len(x), reverse=True)
    words = clean_string(text, word_list)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        wordNextNextNext = words[idx + 3] if idx + 3 < len(words) else ""

        start = idx
        used = 0
        # save timequalifier for later
        if word == "indi" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_az(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if "onillik" in wordNext:
                yearOffset = multiplier * 10
            elif "yüzillik" in wordNext:
                yearOffset = multiplier * 100
            elif "minillik" in wordNext:
                yearOffset = multiplier * 1000
        elif word in timeQualifiersList:
            timeQualifier = word
        # parse bu qün, sabah, srağagün, dünən, birigün
        elif word == "bu gün" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "sabah" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "srağagün" and not fromFlag:
            dayOffset = -2
            used += 1
        elif word == "dünən" and not fromFlag:
            dayOffset = -1
            used += 1
        elif word == "birigün" and not fromFlag:
            dayOffset = 2
            used = 1
        # parse 5 gün, 10 həftə, keçən həftə, gələn həftə
        elif word == "gün":
            if wordPrev and wordPrev[0].isdigit():
                # "N gün əvvəl/qabaq" = N days in the past (İzahlı lüğət)
                if wordNext in ("əvvəl", "qabaq"):
                    dayOffset -= int(wordPrev)
                    start -= 1
                    used = 3
                else:
                    dayOffset += int(wordPrev)
                    start -= 1
                    used = 2
                    if wordNext == "sonra":
                        used += 1
        elif word == "həftə" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                # "N həftə əvvəl/qabaq" = N weeks in the past (İzahlı lüğət)
                if wordNext in ("əvvəl", "qabaq"):
                    dayOffset -= int(wordPrev) * 7
                    start -= 1
                    used = 3
                else:
                    dayOffset += int(wordPrev) * 7
                    start -= 1
                    used = 2
                    if wordNext == "sonra":
                        used += 1
            elif wordPrev == "gələn":
                dayOffset = 7
                start -= 1
                used = 2
                if wordNext == "sonra":
                    used += 1
            elif wordPrev == "keçən":
                dayOffset = -7
                start -= 1
                used = 2
        # parse 10 months, next month, last month
        elif word == "ay" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                # "N ay əvvəl/qabaq" = N months in the past (İzahlı lüğət)
                if wordNext in ("əvvəl", "qabaq"):
                    monthOffset = -int(wordPrev)
                    start -= 1
                    used = 3
                else:
                    monthOffset = int(wordPrev)
                    start -= 1
                    used = 2
            elif wordPrev == "gələn":
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "keçən":
                monthOffset = -1
                start -= 1
                used = 2
        # parse 5 il, gələn il, keçən il
        elif word == "il" and not fromFlag and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                # "N il əvvəl/qabaq" = N years in the past (İzahlı lüğət)
                if wordNext in ("əvvəl", "qabaq"):
                    yearOffset = -int(wordPrev)
                    start -= 1
                    used = 3
                else:
                    yearOffset = int(wordPrev)
                    start -= 1
                    used = 2
            elif wordPrev == "gələn":
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev == "keçən":
                yearOffset = -1
                start -= 1
                used = 2
            if wordNext in markers:
                used += 1
        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not fromFlag:
            if wordNext in markers:
                used += 1
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used += 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev == "gələn":
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "keçən":
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
            datestr = eng_months[m]
            if wordPrev and wordPrev[0].isdigit():
                datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext[0].isdigit() and len(wordNext) == 4:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                    if (wordNextNext and wordNextNext in markers) or wordNextNext == 'il':
                        used += 1
                else:
                    if wordNext and wordNext in markers:
                        used += 1
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit() and len(wordNextNext) == 4:
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                    if wordNextNextNext and wordNextNextNext in markers:
                        used += 1
                else:
                    if wordNextNext and wordNextNext in markers:
                        used += 1
                    hasYear = False

        elif word == "bu":
            used += 1
            dayOffset = 0
            if wordNext in markers:
                used += 1

        if used > 0:
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
        # parse günorta, gecə yarısı, səhər, günortadan sonra, axşam, gecə
        used = 0
        if word == "günorta":
            hrAbs = 12
            used += 1
        elif word == "gecə yarısı":
            hrAbs = 0
            used += 1
        elif word == "səhər":
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word == "günortadan sonra":
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word == "axşam":
            if hrAbs is None:
                hrAbs = 19
            used += 1
        elif word == "gecə":
            if hrAbs is None:
                hrAbs = 21
            used += 1
        # parse yarım saat
        elif word == "saat":
            if wordPrev == "yarım":
                minOffset = 30
                words[idx - 1] = ""
                hrAbs = -1
                minAbs = -1
                used += 1
                if wordNext in markers:
                    used += 1
            elif wordNext and wordNext[0].isdigit() and ":" not in wordNext:
                # explicit clock hour, e.g. "saat 8" or "axşam saat 8"
                digits = "".join(c for c in wordNext if c.isdigit())
                hh = int(digits)
                if timeQualifier in timeQualifiersPM and hh < 12:
                    hh += 12
                if hh <= 24:
                    hrAbs = hh
                    minAbs = 0
                used += 2
                if wordNextNext in markers:
                    used += 1
            else:
                hrAbs = -1
                minAbs = -1
                used += 1
                if wordNext in markers:
                    used += 1
        # parse 5:00 am, 12:00 p.m., etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            wordNextNextNext = words[idx + 3] \
                if idx + 3 < len(words) else ""

            if ':' in word:
                # parse colons
                # "gecə 3:00"
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
                    if (
                            ("saat" in wordNext or "saat" in remainder) and
                            word[0] != '0' and
                            (
                                    int(strNum) < 100 or
                                    int(strNum) > 2400
                            )):
                        # "3 saat"
                        hrOffset = int(strNum)
                        used = 1
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif "dəqiqə" in wordNext or "dəqiqə" in wordNext:
                        # "10 dəqiqə"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                        if wordNextNext in markers:
                            used += 1
                    elif "saniyə" in wordNext or "saniyə" in remainder:
                        # 5 saniyə
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext and wordNext.isdigit():
                        # military time, e.g. "04 38 hours"
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if (wordNextNext and wordNextNext == "da" or
                                wordNextNext == "də" or
                                remainder == "da" or remainder == "də"):
                            used += 1
                    elif wordNext in markers:
                        strHH = strNum

            HH = int(strHH) if strHH else 0
            MM = int(strMM) if strMM else 0
            if timeQualifier in timeQualifiersPM and HH < 12:
                HH += 12

            if HH > 24 or MM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = HH
                minAbs = MM
                used += 1

            if wordNext in markers or word in markers:
                used += 1
        if used > 0:
            # removed parsed words from the sentence
            for i in range(used):
                if idx + i >= len(words):
                    break
                words[idx + i] = ""
    # check that we found a date
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation

    extractedDate = anchorDate.replace(microsecond=0)

    if datestr != "":
        # date included an explicit date, e.g. "iyun 5" or "iyun 2, 2017"
        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                # anchor to a leap year so "29 fevral" parses; the real
                # year is applied below
                temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
        except ValueError:
            # an impossible calendar date like "30 fevral"; report nothing
            # rather than a wrong guess
            return None
        extractedDate = extractedDate.replace(hour=0, minute=0, second=0)
        if not hasYear:
            try:
                temp = temp.replace(year=extractedDate.year,
                                    tzinfo=extractedDate.tzinfo)
            except ValueError:
                # a day that does not exist in this year, "29 fevral" outside
                # a leap year; report nothing rather than a wrong guess
                return None
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
        if word == "və" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]
