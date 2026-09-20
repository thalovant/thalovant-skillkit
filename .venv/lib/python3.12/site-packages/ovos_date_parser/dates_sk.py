import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_sk import pronounce_number_sk, extract_number_sk
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def _int_token_sk(word):
    """Return the integer a single spelled/digit token denotes, else None.

    Ordinals ("siedmej") and fractions ("pol") are rejected so they keep
    their clock-idiom meaning.
    """
    if not word:
        return None
    if word.isdigit():
        return int(word)
    n = extract_number_sk(word)
    if n is False or n is None or isinstance(n, bool):
        return None
    if isinstance(n, float) and not n.is_integer():
        return None
    return int(n)


# feminine genitive ordinals, used by the traditional "pol" idiom
# ("pol deviatej" = 8:30, literally "half of the ninth")
_ORDINAL_FEM_GEN_SK = {
    1: "jednej", 2: "druhej", 3: "tretej", 4: "štvrtej", 5: "piatej",
    6: "šiestej", 7: "siedmej", 8: "ôsmej", 9: "deviatej", 10: "desiatej",
    11: "jedenástej", 12: "dvanástej",
}


def nice_time_sk(dt, speech=True, use_24hour=True, use_ampm=False,
                 variant=None):
    """
    Format a time to a comfortable human format

    For example, generate 'osem pätnásť' (default) or 'štvrť na deväť'
    (traditional) for speech, or '8:15' for text display.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
        variant (str): spoken register for the 12-hour clock. The default
            (None / "default") reads the digits plainly. "traditional"
            uses the analog counting-to-the-next-hour idiom
            ("štvrť na deväť" = 8:15, "pol deviatej" = 8:30,
            "trištvrte na deväť" = 8:45), the register still common in
            everyday Slovak speech.
    Returns:
        (str): The formatted time string
    """
    traditional = variant in ("traditional", "analog")
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
        # Either "0 8 sto" or "13 sto"
        if string[0] == '0':
            speak += pronounce_number_sk(int(string[0])) + " "
            speak += pronounce_number_sk(int(string[1]))
        else:
            speak = pronounce_number_sk(int(string[0:2]))

        speak += " "
        if string[3:5] == '00':
            speak += "sto"
        else:
            if string[3] == '0':
                speak += pronounce_number_sk(0) + " "
                speak += pronounce_number_sk(int(string[4]))
            else:
                speak += pronounce_number_sk(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "polnoc"
        elif dt.hour == 12 and dt.minute == 0:
            return "poludnie"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        next_hour = (dt.hour + 1) % 12 or 12
        if traditional and dt.minute == 15:
            speak = "štvrť na " + pronounce_number_sk(next_hour)
        elif traditional and dt.minute == 30:
            speak = "pol " + _ORDINAL_FEM_GEN_SK[next_hour]
        elif traditional and dt.minute == 45:
            speak = "trištvrte na " + pronounce_number_sk(next_hour)
        else:
            speak = pronounce_number_sk(hour)

            if dt.minute == 0:
                if not use_ampm:
                    return speak + " hodín"
            else:
                if dt.minute < 10:
                    speak += " nula"
                speak += " " + pronounce_number_sk(dt.minute)

        if use_ampm:
            if dt.hour > 11:
                speak += " p.m."
            else:
                speak += " a.m."

        return speak


def extract_duration_sk(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["sk"],
                                    resolution, replace_token)


_MONTHS_SK = ['január', 'február', 'marec', 'apríl', 'máj', 'jún',
              'júl', 'august', 'september', 'október', 'november',
              'december']

_MONTHS_EN = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november',
              'december']

# genitive ("3. januára") and locative ("v januári") month forms
_MONTH_VARIANTS_SK = {
    'januára': 'január', 'januári': 'január',
    'februára': 'február', 'februári': 'február',
    'marca': 'marec', 'marci': 'marec',
    'apríla': 'apríl', 'apríli': 'apríl',
    'mája': 'máj', 'máji': 'máj',
    'júna': 'jún', 'júni': 'jún',
    'júla': 'júl', 'júli': 'júl',
    'augusta': 'august', 'auguste': 'august',
    'septembra': 'september', 'septembri': 'september',
    'októbra': 'október', 'októbri': 'október',
    'novembra': 'november', 'novembri': 'november',
    'decembra': 'december', 'decembri': 'december',
}

_DAYS_SK = ['pondelok', 'utorok', 'streda', 'štvrtok', 'piatok', 'sobota',
            'nedeľa']

# accusative/locative weekday forms ("v stredu", "v sobotu", "v nedeľu")
_DAY_VARIANTS_SK = {
    'stredu': 'streda', 'stredou': 'streda',
    'sobotu': 'sobota', 'sobotou': 'sobota',
    'nedeľu': 'nedeľa', 'nedeľou': 'nedeľa',
    'pondelkom': 'pondelok', 'utorkom': 'utorok',
    'štvrtkom': 'štvrtok', 'piatkom': 'piatok',
}

# unit words normalized to a canonical form
_UNIT_VARIANTS_SK = {
    'dni': 'deň', 'dní': 'deň', 'dňa': 'deň', 'dňom': 'deň', 'dňoch': 'deň',
    'dňami': 'deň',
    'týždne': 'týždeň', 'týždňa': 'týždeň', 'týždňov': 'týždeň',
    'týždni': 'týždeň', 'týždňoch': 'týždeň', 'týždňami': 'týždeň',
    'mesiace': 'mesiac', 'mesiaca': 'mesiac', 'mesiacov': 'mesiac',
    'mesiaci': 'mesiac', 'mesiacoch': 'mesiac', 'mesiacmi': 'mesiac',
    'mesiacami': 'mesiac',
    'roky': 'rok', 'roka': 'rok', 'rokov': 'rok', 'rokoch': 'rok',
    'rokmi': 'rok', 'rokami': 'rok',
    'minúta': 'minút', 'minúty': 'minút', 'minútu': 'minút',
    'minútach': 'minút', 'minúit': 'minút',
    'hodina': 'hodín', 'hodiny': 'hodín', 'hodinu': 'hodín',
    'hodinách': 'hodín', 'hodín': 'hodín',
    'sekunda': 'sekúnd', 'sekundy': 'sekúnd', 'sekundu': 'sekúnd',
    'sekundách': 'sekúnd', 'sekúnd': 'sekúnd',
}

# hour names in the locative feminine, as used after "o" ("o ôsmej")
_HOURS_LOCATIVE_SK = {
    'prvej': 1, 'druhej': 2, 'tretej': 3, 'štvrtej': 4, 'piatej': 5,
    'šiestej': 6, 'siedmej': 7, 'ôsmej': 8, 'deviatej': 9, 'desiatej': 10,
    'jedenástej': 11, 'dvanástej': 12,
}

# cardinal hour words, as they appear after "na" in the traditional
# quarter idiom ("štvrť na deväť" = 8:15)
_HOURS_CARDINAL_SK = {
    'jednu': 1, 'jedna': 1, 'dve': 2, 'dva': 2, 'tri': 3, 'štyri': 4,
    'päť': 5, 'šesť': 6, 'sedem': 7, 'osem': 8, 'deväť': 9, 'desať': 10,
    'jedenásť': 11, 'dvanásť': 12,
}

_NEXT_WORDS_SK = ('budúci', 'budúca', 'budúcu', 'budúce', 'budúcom',
                  'nasledujúci', 'nasledujúca', 'nasledujúcu',
                  'nasledujúce', 'budúcej')
_LAST_WORDS_SK = ('minulý', 'minulá', 'minulú', 'minulé', 'minulom',
                  'minulej', 'posledný', 'posledná', 'poslednú')

_MARKERS_SK = ['v', 'vo', 'na', 'za', 'o', 'cez', 'do', 'po', 'tento', 'túto']

# prepositions introducing a future offset ("o 5 minút", "cez 5 minút")
_FUTURE_PREPS_SK = ('o', 'za', 'cez')


def extract_datetime_sk(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "dnes"
        "zajtra popoludní"
        "v stredu o ôsmej večer"
        "3. januára"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "zajtra", etc
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
        word = _DAY_VARIANTS_SK.get(word, word)
        word = _MONTH_VARIANTS_SK.get(word, word)
        word = _UNIT_VARIANTS_SK.get(word, word)
        return word

    s = text.lower().replace(',', ' ').replace('?', ' ')
    words = []
    for w in s.split():
        # strip the ordinal dot: "3. januára" -> "3 januára"
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

    timeQualifiersAM = ['ráno', 'doobeda', 'dopoludnia', 'nadránom']
    timeQualifiersPM = ['poobede', 'popoludní', 'večer', 'noc', 'noci']

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
        elif word == "dnes":
            dayOffset = 0
            used = 1
        elif word == "zajtra":
            dayOffset = 1
            used = 1
        elif word == "pozajtra":
            dayOffset = 2
            used = 1
        elif word == "včera":
            dayOffset = -1
            used = 1
        elif word in ("predvčerom", "predvčerajškom"):
            dayOffset = -2
            used = 1
        # parse "cez 5 dní", "pred 5 dňami"
        elif word == "deň" and wordPrev and wordPrev[0].isdigit():
            dayOffset = (dayOffset or 0) + int(wordPrev)
            start -= 1
            used = 2
            if wordPrevPrev == "pred":
                dayOffset = -dayOffset
                start -= 1
                used += 1
        # parse "budúci týždeň", "minulý týždeň", "cez 2 týždne"
        elif word == "týždeň":
            if wordPrev and wordPrev[0].isdigit():
                dayOffset = (dayOffset or 0) + int(wordPrev) * 7
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    dayOffset = -dayOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SK:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SK:
                dayOffset = -7
                start -= 1
                used = 2
        # parse "budúci mesiac", "cez 3 mesiace"
        elif word == "mesiac" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    monthOffset = -monthOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SK:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SK:
                monthOffset = -1
                start -= 1
                used = 2
        # parse "budúci rok", "cez 2 roky"
        elif word == "rok" and wordPrev:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev == "pred":
                    yearOffset = -yearOffset
                    start -= 1
                    used += 1
            elif wordPrev in _NEXT_WORDS_SK:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in _LAST_WORDS_SK:
                yearOffset = -1
                start -= 1
                used = 2
        # parse weekdays: "v pondelok", "budúcu stredu"
        elif word in _DAYS_SK:
            d = _DAYS_SK.index(word)
            dayOffset = (d - anchorDate.weekday()) % 7
            used = 1
            if wordPrev in _NEXT_WORDS_SK:
                if dayOffset <= 2:
                    dayOffset += 7
                start -= 1
                used += 1
            elif wordPrev in _LAST_WORDS_SK:
                dayOffset -= 7
                start -= 1
                used += 1
        # parse "3. januára", "január 2027", "5. mája 2030"
        elif word in _MONTHS_SK:
            m = _MONTHS_SK.index(word)
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
            if start - 1 >= 0 and words[start - 1] in _MARKERS_SK:
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
        word = normalize(word)
        wordPrev = normalize(words[idx - 1]) if idx > 0 else ""
        wordPrevPrev = normalize(words[idx - 2]) if idx > 1 else ""
        wordNext = normalize(words[idx + 1]) if idx + 1 < len(words) else ""
        start = idx
        used = 0

        if word in ("poludnie", "napoludnie"):
            hrAbs = 12
            minAbs = 0
            used = 1
        elif word in ("polnoc",):
            hrAbs = 0
            minAbs = 0
            used = 1
        elif word in ("ráno", "nadránom"):
            if hrAbs is None:
                hrAbs = 8
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("doobeda", "dopoludnia"):
            if hrAbs is None:
                hrAbs = 10
            elif hrAbs >= 12:
                hrAbs -= 12
            used = 1
        elif word in ("poobede", "popoludní"):
            if hrAbs is None:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word == "večer":
            if hrAbs is None:
                hrAbs = 19
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used = 1
        elif word in ("noc", "noci"):
            if hrAbs is None:
                hrAbs = 22
            elif 5 < hrAbs < 12:
                hrAbs += 12
            used = 1
        # parse spoken hours: "o ôsmej", "o pol deviatej" (= 8:30, "pol"
        # counts towards the NEXT hour)
        elif word in _HOURS_LOCATIVE_SK:
            hrAbs = _HOURS_LOCATIVE_SK[word]
            minAbs = 0
            used = 1
            if wordPrev == "pol":
                hrAbs -= 1
                minAbs = 30
                start -= 1
                used += 1
            if timeQualifier in timeQualifiersPM and 0 < hrAbs < 12:
                hrAbs += 12
            elif timeQualifier in timeQualifiersAM and hrAbs >= 12:
                hrAbs -= 12
        # traditional quarter idioms: "štvrť na deväť" (8:15),
        # "trištvrte na deväť" (8:45)
        elif word in _HOURS_CARDINAL_SK and wordPrev == "na" and \
                wordPrevPrev in ("štvrť", "trištvrte"):
            hrAbs = _HOURS_CARDINAL_SK[word] - 1
            minAbs = 15 if wordPrevPrev == "štvrť" else 45
            start -= 2
            used = 3
            if timeQualifier in timeQualifiersPM and 0 <= hrAbs < 12:
                hrAbs += 12
            elif timeQualifier in timeQualifiersAM and hrAbs >= 12:
                hrAbs -= 12
        # spelled future offsets: "o desať minút", "cez tri hodiny"
        elif wordPrev in _FUTURE_PREPS_SK and \
                wordNext in ("minút", "hodín", "sekúnd") and \
                not word[0].isdigit() and _int_token_sk(word) is not None:
            value = _int_token_sk(word)
            if wordNext == "minút":
                minOffset = value
            elif wordNext == "hodín":
                hrOffset = value
            else:
                secOffset = value
            hrAbs = -1
            minAbs = -1
            start -= 1
            used = 3
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
                # parse "o 5 minút", "cez 3 hodiny", "za 30 sekúnd"
                if wordNext in ("minút", "hodín", "sekúnd") and \
                        wordPrev in _FUTURE_PREPS_SK:
                    value = int(word)
                    if wordNext == "minút":
                        minOffset = value
                    elif wordNext == "hodín":
                        hrOffset = value
                    else:
                        secOffset = value
                    hrAbs = -1
                    minAbs = -1
                    start -= 1
                    used = 3
                elif int(word) <= 24 and \
                        (wordPrev in ("o", "na") or wordNext == "hodín"):
                    # "o 8", "o 17 hodín"
                    strHH = word
                    used = 1
                    if wordNext == "hodín":
                        used += 1
            if strHH:
                HH = int(strHH)
                MM = int(strMM) if strMM else 0
                if HH <= 24 and MM <= 59:
                    if timeQualifier in timeQualifiersPM and 0 < HH < 12:
                        HH += 12
                    elif timeQualifier in timeQualifiersAM and HH >= 12:
                        HH -= 12
                    hrAbs = HH % 24
                    minAbs = MM
                else:
                    used = 0

        if used > 0:
            for i in range(used):
                if 0 <= start + i < len(words):
                    words[start + i] = ""
            if start - 1 >= 0 and words[start - 1] in _MARKERS_SK:
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
        try:
            temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                try:
                    temp = datetime.strptime(datestr + " 1", "%B %d")
                except ValueError:
                    # an impossible calendar date; report nothing
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

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]
