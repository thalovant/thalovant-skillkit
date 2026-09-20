import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_eu import pronounce_number_eu
from ovos_utils.time import DAYS_IN_1_MONTH, DAYS_IN_1_YEAR
from ovos_number_parser import numbers_to_digits
from ovos_date_parser.common import _translate_word
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

HOUR_STRING_EU = {
    1: 'ordubata',
    2: 'ordubiak',
    3: 'hirurak',
    4: 'laurak',
    5: 'bostak',
    6: 'seirak',
    7: 'zazpirak',
    8: 'zortzirak',
    9: 'bederatziak',
    10: 'hamarrak',
    11: 'hamaikak',
    12: 'hamabiak'
}


def nice_time_eu(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format

    For example, generate 'cinco treinta' for speech or '5:30' for
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
        # Tenemos que tener en cuenta que cuando hablamos en formato
        # 24h, no hay que especificar ninguna precisión adicional
        # como "la noche", "la tarde" o "la mañana"
        # http://lema.rae.es/dpd/srv/search?id=YNoTWNJnAD6bhhVBf9
        speak += pronounce_number_eu(dt.hour) + 'ak'

        # las 14:04 son "las catorce cero cuatro"

        if dt.minute < 10:
            speak += " zero " + pronounce_number_eu(dt.minute)
        else:
            speak += " " + pronounce_number_eu(dt.minute)

    else:
        minute = dt.minute
        hour = dt.hour

        _hour = hour
        if _hour == 0:
            _hour = 12
        if _hour > 12:
            _hour -= 12

        if (minute > 30):
            _hour += 1

        speak = HOUR_STRING_EU[_hour]

        if minute != 0:
            if minute <= 30:
                if minute == 15:
                    speak += " eta laurden"
                elif minute == 30:
                    speak += " eta erdi"
                else:
                    speak += " eta " + pronounce_number_eu(minute)
            else:
                if minute == 45:
                    speak += " laurden gutxi"
                else:
                    speak += " " + pronounce_number_eu(60 - minute) + " gutxi"

        # si no especificamos de la tarde, noche, mañana, etc
        if minute == 0 and not use_ampm:
            # 3:00
            speak += " puntuan"

        if use_ampm:
            # "de la noche" es desde que anochece hasta medianoche
            # así que decir que es desde las 21h es algo subjetivo
            # en España a las 20h se dice "de la tarde"
            # en castellano, las 12h es de la mañana o mediodía
            # así que diremos "de la tarde" a partir de las 13h.
            # http://lema.rae.es/dpd/srv/search?id=YNoTWNJnAD6bhhVBf9
            if hour >= 6 and hour < 13:
                speak = "goizeko " + speak
            elif hour >= 13 and hour < 20:
                speak = "arratsaldeko " + speak
            else:
                speak = "gaueko " + speak
    return speak
    # hemen dago tranpa
    # return str(dt.hour) + ":" + str(dt.minute)


def nice_relative_time_eu(when, relative_to):
    """Create a relative phrase to roughly describe a datetime

    Examples are "25 seconds", "tomorrow", "7 days".

    Args:
        when (datetime): Local timezone
        relative_to (datetime): Baseline for relative time
    Returns:
        str: Relative description of the given time
    """
    delta = when - relative_to

    seconds = delta.total_seconds()
    if seconds < 1:
        try:
            return _translate_word("now", "eu")
        except NotImplementedError:
            nice = pronounce_number_eu(0)
            return f"{nice} " + _translate_word("seconds", "eu")

    if seconds < 90:
        nice = pronounce_number_eu(seconds)
        s = _translate_word("second", "eu")
        if seconds == 1:
            return f"{s} bat"
        else:
            return f"{nice} {s}"

    minutes = int((delta.total_seconds() + 30) // 60)  # +30 to round minutes
    if minutes < 90:
        nice = pronounce_number_eu(minutes)
        s = _translate_word("minute", "eu")
        if minutes == 1:
            return f"{s} bat"
        else:
            return f"{nice} {s}"

    hours = int((minutes + 30) // 60)  # +30 to round hours
    if hours < 36:
        nice = pronounce_number_eu(hours)
        s = _translate_word("hour", "eu")
        if hours == 1:
            return f"{s} bat"
        else:
            return f"{nice} {s}"

    # TODO: "2 weeks", "3 months", "4 years", etc
    days = int((hours + 12) // 24)  # +12 to round days
    nice = pronounce_number_eu(days)
    s = _translate_word("day", "eu")
    if days == 1:
        return f"{s} bat"
    else:
        return f"{nice} {s}"


def extract_datetime_eu(input_str, anchorDate=None, default_time=None):
    def clean_string(s):
        # cleans the input string of unneeded punctuation and capitalization
        # among other things
        symbols = [".", ",", ";", "?", "!", "."]
        # noise_words = ["entre", "la", "del", "al", "el", "de",
        #                "para", "una", "cualquier", "a",
        #                "e'", "esta", "este"]
        # TODO
        noise_words = ["artean", "tartean", "edozein", "hau", "hontan", "honetan",
                       "para", "una", "cualquier", "a",
                       "e'", "esta", "este"]

        for word in symbols:
            s = s.replace(word, "")
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")
        s = s.lower().replace(
            "-",
            " ").replace(
            "_",
            "")
        # handle synonyms and equivalents, "tomorrow early = tomorrow morning
        synonyms = {"goiza": ["egunsentia", "goiz", "oso goiz"],
                    "arratsaldea": ["arratsa", "bazkalostea", "arratsalde", "arrats"],
                    "gaua": ["iluntzea", "berandu", "gau", "gaba"]}
        for syn in synonyms:
            for word in synonyms[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")
        # relevant plurals
        wordlist = ["goizak", "arratsaldeak", "gauak", "egunak", "asteak",
                    "urteak", "minutuak", "segunduak", "hurrengoak",
                    "datozenak", "orduak", "hilabeteak"]
        for _, word in enumerate(wordlist):
            s = s.replace(word, word.rstrip('ak'))
        # s = s.replace("meses", "mes").replace("anteriores", "anterior")
        return s

    def date_found():
        return found or \
            (
                    datestr != "" or
                    yearOffset != 0 or monthOffset != 0 or
                    dayOffset is True or hrOffset != 0 or
                    hrAbs or minOffset != 0 or
                    minAbs or secOffset != 0
            )

    if input_str == "":
        return None
    if anchorDate is None:
        anchorDate = datetime.now()

    def is_numeric_day(tok):
        # a bare day number ("25"), not a clock ("15:00"), a
        # case-inflected number ("3etan") or a 4 digit year
        return bool(tok) and tok.isdigit() and 1 <= len(tok) <= 2

    def is_numeric_year(tok):
        # only a 4 digit token is treated as a year, so a trailing
        # clock time or inflected number is never swallowed as one
        return bool(tok) and tok.isdigit() and len(tok) == 4

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

    words = clean_string(input_str).split(" ")
    timeQualifiersList = ['goiza', 'arratsaldea', 'gaua']
    time_indicators = ["en", "la", "al", "por", "pasados",
                       "pasadas", "día", "hora"]
    days = ['astelehena', 'asteartea', 'asteazkena',
            'osteguna', 'ostirala', 'larunbata', 'igandea']
    months = ['urtarrila', 'otsaila', 'martxoa', 'apirila', 'maiatza', 'ekaina',
              'uztaila', 'abuztua', 'iraila', 'urria', 'azaroa',
              'abendua']
    monthsShort = ['urt', 'ots', 'mar', 'api', 'mai', 'eka', 'uzt', 'abu',
                   'ira', 'urr', 'aza', 'abe']
    nexts = ["hurrengo", "datorren", "ondorengo"]
    suffix_nexts = ["barru"]
    lasts = ["azken", "duela"]
    suffix_lasts = ["aurreko"]
    nxts = ["ondorengo", "hurrengo", "datorren"]
    prevs = ["aurreko", "duela", "previo", "anterior"]
    #  TODO
    froms = ["desde", "en", "para", "después de", "por", "próximo",
             "próxima", "de"]
    thises = ["hau"]
    froms += thises
    lists = nxts + prevs + froms + time_indicators

    # --- normalize Basque case-inflected date tokens to their bare forms ---
    # Basque marks the date word, not a preposition: months take the
    # genitive ("ekainaren 5a" = the 5th of June) or, with a day, the
    # absolutive/inessive; the day carries the inessive ("5ean" = on the
    # 5th); years take the relational -ko ("2027ko ekaina").  The scanner
    # below only knows the bare stems, so fold the natural suffixed forms
    # back onto them first.  See Euskaltzaindia EGLU-I declension tables
    # and the Hiztegia month entries (papers/linguistics/eu/).
    def _stem(base):
        return base[:-1] if base.endswith("a") else base

    _month_infl = {}
    for _m in months:
        _s = _stem(_m)
        for _v in (_m + "k", _m + "ren", _s + "ean", _s + "an", _s + "ko"):
            _month_infl.setdefault(_v, _m)
    _day_infl = {}
    for _d in days:
        _s = _stem(_d)
        for _v in (_s + "ean", _s + "an", _d + "ren", _s + "ko"):
            _day_infl.setdefault(_v, _d)

    for _i, _w in enumerate(words):
        if not _w:
            continue
        if _w in months or _w in days:
            continue
        if _w in _month_infl:
            words[_i] = _month_infl[_w]
        elif _w in _day_infl:
            words[_i] = _day_infl[_w]
        elif re.match(r"^\d{4}ko$", _w):
            # year with the relational suffix: "2027ko" -> "2027"
            words[_i] = _w[:-2]
        elif re.match(r"^\d{1,2}(?:an|ean|garren|garrena|garrenean)$", _w):
            # day in the inessive: "5ean" -> "5", "20an" -> "20"
            words[_i] = re.match(r"^(\d{1,2})", _w).group(1)

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
        if word in timeQualifiersList:
            timeQualifier = word

        # parse today, tomorrow, yesterday
        elif (word == "gaur" or word == "gaurko") and not fromFlag:
            dayOffset = 0
            used += 1
        elif (word == "bihar" or word == "biharko") and not fromFlag:
            dayOffset = 1
            used += 1
        elif (word == "atzo" or word == "atzoko") and not fromFlag:
            dayOffset -= 1
            used += 1
        # before yesterday
        elif (word == "herenegun" or word == "herenegungo") and not fromFlag:
            dayOffset -= 2
            used += 1
            # if wordNext == "ayer":
            #     used += 1
        # elif word == "ante" and wordNext == "ante" and wordNextNext == \
        #         "ayer" and not fromFlag:
        #     dayOffset -= 3
        #     used += 3
        # elif word == "ante anteayer" and not fromFlag:
        #     dayOffset -= 3
        #     used += 1
        # day after tomorrow
        elif (word == "etzi" or word == "etziko") and not fromFlag:
            dayOffset += 2
            used = 1
        elif (word == "etzidamu" or word == "etzidamuko") and not fromFlag:
            dayOffset += 3
            used = 1
        # parse 5 days, 10 weeks, last week, next week, week after
        elif word == "egun" or word == "eguna" or word == "eguneko":
            if wordPrevPrev and wordPrevPrev == "duela":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset -= int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                dayOffset += int(wordPrev)
                start -= 1
                used += 2
            elif wordNext and wordNext[0].isdigit() and wordNextNext not in \
                    months and wordNextNext not in monthsShort:
                dayOffset += int(wordNext)
                start -= 1
                used += 2

        elif word == "aste" or word == "astea" or word == "asteko" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
            for w in nexts:
                if wordPrev == w:
                    dayOffset = 7
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    dayOffset = 7
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
        # parse 10 months, next month, last month
        elif word == "hilabete" or word == "hilabetea" or word == "hilabeteko" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
            for w in nexts:
                if wordPrev == w:
                    monthOffset = 7
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    monthOffset = -7
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    monthOffset = 7
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    monthOffset = -7
                    start -= 1
                    used = 2
        # parse 5 years, next year, last year
        elif word == "urte" or word == "urtea" or word == "urteko" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
            for w in nexts:
                if wordPrev == w:
                    yearOffset = 1
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    yearOffset = -1
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    yearOffset = 1
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
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
            if wordPrev in nexts:
                # "datorren / hurrengo / ondorengo ostirala" = next Friday
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev in prevs:
                # "aurreko / duela ... ostirala" = last Friday
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext == "hurrengo":
                # dayOffset += 7
                used += 1
            elif wordNext == "aurreko":
                # dayOffset -= 7
                used += 1
        # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in monthsShort:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            month_name = months[m]
            day_tok = ""
            year_tok = ""
            # a day sits right before or after the month:
            # "ekainaren 5a" / "5 ekaina" / "ekaina 5"
            if is_numeric_day(wordPrev):
                day_tok = wordPrev
                start -= 1
                used += 1
            elif is_numeric_day(wordNext):
                day_tok = wordNext
                used += 1
            # a 4 digit year can flank the month on either side; the
            # natural Basque order is "<year> <month> <day>"
            # ("2027ko ekainaren 5ean" -> "2027 ekaina 5")
            if is_numeric_year(wordPrev) and wordPrev != day_tok:
                year_tok = wordPrev
                start -= 1
                used += 1
            elif is_numeric_year(wordNext) and wordNext != day_tok:
                year_tok = wordNext
                used += 1
            elif is_numeric_year(wordNextNext) and day_tok == wordNext:
                year_tok = wordNextNext
                used += 1

            if day_tok:
                datestr = month_name + " " + day_tok
                if year_tok:
                    datestr += " " + year_tok
                    hasYear = True
                else:
                    hasYear = False
            elif year_tok:
                # month + year with no day ("2027ko ekainean"): the
                # first of the month stands in for the missing day
                datestr = month_name + " 1 " + year_tok
                hasYear = True
            else:
                datestr = month_name

            if datestr in months:
                datestr = ""

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("gaur")
        validFollowups.append("bihar")
        validFollowups.append("atzo")
        # validFollowups.append("atzoko")
        validFollowups.append("herenegun")
        validFollowups.append("orain")
        validFollowups.append("oraintxe")
        # validFollowups.append("ante")

        # TODO
        if word in froms and wordNext in validFollowups:

            if not (word == "bihar" or word == "herenegun" or word == "atzo"):
                used = 1
                fromFlag = True
            if wordNext == "bihar":
                dayOffset += 1
            elif wordNext == "atzo" or wordNext == "atzoko":
                dayOffset -= 1
            elif wordNext == "herenegun":
                dayOffset -= 2
            # elif (wordNext == "ante" and wordNext == "ante" and
            #       wordNextNextNext == "ayer"):
            #     dayOffset -= 3
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                # if wordNextNext == "feira":
                #     used += 1
                if tmpOffset < 0:
                    tmpOffset += 7
                if wordNextNext:
                    if wordNextNext in nxts:
                        tmpOffset += 7
                        used += 1
                    elif wordNextNext in prevs:
                        tmpOffset -= 7
                        used += 1
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = days.index(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNextNextNext:
                    if wordNextNextNext in nxts:
                        tmpOffset += 7
                        used += 1
                    elif wordNextNextNext in prevs:
                        tmpOffset -= 7
                        used += 1
                dayOffset += tmpOffset
                # if wordNextNextNext == "feira":
                #     used += 1
        if wordNext in months:
            used -= 1
        if used > 0:
            if start - 1 > 0 and words[start - 1] in lists:
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in lists:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
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
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "eguerdi" or word == "eguerdia" or word == "eguerdian":
            hrAbs = 12
            used += 2
        elif word == "gauerdi" or word == "gauerdia" or word == "gauerdian":
            hrAbs = 0
            used += 2
        elif word == "goiza":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "arratsaldea" or word == "arratsa" or word == "arratsean" or word == "arratsaldean":
            if not hrAbs:
                hrAbs = 15
            used += 1
        # TODO
        # elif word == "media" and wordNext == "tarde":
        #     if not hrAbs:
        #         hrAbs = 17
        #     used += 2
        elif word == "iluntze" or word == "iluntzea" or word == "iluntzean":
            if not hrAbs:
                hrAbs = 20
            used += 2
        # TODO
        # elif word == "media" and wordNext == "mañana":
        #     if not hrAbs:
        #         hrAbs = 10
        #     used += 2
        # elif word == "fim" and wordNext == "tarde":
        #     if not hrAbs:
        #         hrAbs = 19
        #     used += 2
        elif word == "egunsentia" or word == "egunsentian" or word == "egunsenti":
            if not hrAbs:
                hrAbs = 6
            used += 1
        # elif word == "madrugada":
        #     if not hrAbs:
        #         hrAbs = 1
        #     used += 2
        elif word == "gaua" or word == "gauean" or word == "gau":
            if not hrAbs:
                hrAbs = 21
            used += 1
        # parse half an hour, quarter hour
        # TODO
        elif (word == "hora" and
              (wordPrev in time_indicators or wordPrevPrev in
               time_indicators)):
            if wordPrev == "media":
                minOffset = 30
            elif wordPrev == "cuarto":
                minOffset = 15
            elif wordPrevPrev == "cuarto":
                minOffset = 15
                if idx > 2 and words[idx - 3] in time_indicators:
                    words[idx - 3] = ""
                words[idx - 2] = ""
            else:
                hrOffset = 1
            if wordPrevPrev in time_indicators:
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
                    elif wordNext == "goiza" or wordNext == "egunsentia" or wordNext == "goizeko" or wordNext == "egunsentiko":
                        remainder = "am"
                        used += 1
                    elif wordPrev == "arratsaldeko" or wordPrev == "arratsaldea" or wordPrev == "arratsaldean":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "gaua" or wordNext == "gauean" or wordNext == "gaueko":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif wordNext in thises and (
                            wordNextNext == "goiza" or wordNextNext == "goizean" or wordNextNext == "goizeko"):
                        remainder = "am"
                        used = 2
                    elif wordNext in thises and \
                            (
                                    wordNextNext == "arratsaldea" or wordNextNext == "arratsaldean" or wordNextNext == "arratsaldeko"):
                        remainder = "pm"
                        used = 2
                    elif wordNext in thises and (
                            wordNextNext == "gaua" or wordNextNext == "gauean" or wordNextNext == "gaueko"):
                        remainder = "pm"
                        used = 2
                    else:
                        if timeQualifier == "arratsaldea" and \
                                strHH and int(strHH) < 12:
                            strHH = int(strHH) + 12

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
                    if (wordNext == "pm" or
                            wordNext == "p.m." or
                            wordPrev == "arratsaldeko"):
                        strHH = strNum
                        remainder = "pm"
                        used = 0
                    elif (wordNext == "am" or
                          wordNext == "a.m." or
                          wordPrev == "goizeko"):
                        strHH = strNum
                        remainder = "am"
                        used = 0
                    elif (int(strNum) > 100 and
                          (
                                  # wordPrev == "o" or
                                  # wordPrev == "oh" or
                                  wordPrev == "zero"
                          )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = int(strNum) / 100
                        strMM = int(strNum) - strHH * 100
                        if wordNext == "orduak":
                            used += 1
                    elif (wordNext == "ordu" or wordNext == "orduak") \
                            and word[0] != '0' and int(strNum) < 100:
                        # "3 ordu barru" -> in 3 hours
                        hrOffset = int(strNum)
                        used = 2
                        if wordNextNext in suffix_nexts:
                            used = 3
                        isTime = False
                        hrAbs = -1
                        minAbs = -1

                    elif wordNext == "minutu" or wordNext == "minutuak":
                        # "10 minutu barru" -> in 10 minutes
                        minOffset = int(strNum)
                        used = 2
                        if wordNextNext in suffix_nexts:
                            used = 3
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segundo" or wordNext == "segundu" \
                            or wordNext == "segunduak":
                        # "5 segundo barru" -> in 5 seconds
                        secOffset = int(strNum)
                        used = 2
                        if wordNextNext in suffix_nexts:
                            used = 3
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif int(strNum) > 100:
                        strHH = int(strNum) / 100
                        strMM = int(strNum) - strHH * 100
                        if wordNext == "ordu":
                            used += 1

                    elif wordNext == "" or (
                            wordNext == "puntuan"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "puntuan":
                            used += 2
                            if wordNextNextNext == "arratsaldea":
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "goiza":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "gaua":
                                if 0 > strHH > 6:
                                    remainder = "am"
                                else:
                                    remainder = "pm"
                                used += 1

                    elif wordNext and wordNext.isdigit():
                        strHH = strNum
                        strMM = wordNext
                        used += 1
                        if wordNextNext == "orduak":
                            used += 1
                    else:
                        isTime = False

            strHH = int(strHH) if strHH else 0
            strMM = int(strMM) if strMM else 0
            strHH = strHH + 12 if (remainder == "pm" and
                                   0 < strHH < 12) else strHH
            strHH = strHH - 12 if (remainder == "am" and
                                   0 < strHH >= 12) else strHH
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

            if wordPrev == "puntuan":
                words[words.index(wordPrev)] = ""

            if idx > 0 and wordPrev in time_indicators:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in time_indicators:
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
        # a purely relative hour/minute/second offset keeps the
        # anchor time of day instead of resetting to midnight
        extractedDate = extractedDate.replace(microsecond=0, second=0)
    else:
        extractedDate = extractedDate.replace(microsecond=0, second=0,
                                              minute=0, hour=0)
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
                # 2000 is a leap year, so Feb 29 parses; the year is
                # replaced below anyway
                temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
            temp = temp.replace(tzinfo=None)
            if not hasYear:
                if extractedDate.replace(year=extractedDate.year) < \
                        temp.replace(year=extractedDate.year):
                    chosen_year = int(currentYear)
                else:
                    chosen_year = int(currentYear) + 1
                extractedDate = extractedDate.replace(
                    year=chosen_year,
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")))
            else:
                extractedDate = extractedDate.replace(
                    year=int(temp.strftime("%Y")),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")))
        except ValueError:
            # impossible date (e.g. an out-of-range day, or Feb 29 in a
            # non-leap target year): treat it as no valid date found
            return None

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

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    # resultStr = pt_pruning(resultStr)
    return [extractedDate, resultStr]


def extract_duration_eu(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["eu"],
                                    resolution, replace_token)
