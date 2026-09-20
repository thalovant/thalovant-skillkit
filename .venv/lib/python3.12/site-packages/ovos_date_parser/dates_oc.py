"""Occitan date/time parsing and formatting.

Classical orthography (norma classica), Lengadocian referential variety.

Sources:
- Lo Congrès permanent de la lenga occitana (dicod'Òc, dicodoc.eu)
- the Occitan date-fns locale authored by a native speaker
  (github.com/date-fns/date-fns, src/locale/oc)
- attested time expressions: "una ora un quart", "una ora e mièja",
  "doas oras manca un quart" (histo.cat, "Català i occità, diferents en
  13 punts"); day words uèi/deman/ièr, miègjorn/mièjanuèch
  (occitan-foss.blogspot.com, wordsrus.info/oci)
"""
import re
from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_oc import OC
from ovos_number_parser.util import GrammaticalGender
from ovos_utils.time import now_local

WEEKDAYS_OC = {
    0: "diluns",
    1: "dimars",
    2: "dimècres",
    3: "dijòus",
    4: "divendres",
    5: "dissabte",
    6: "dimenge"
}
MONTHS_OC = {
    1: "genièr",
    2: "febrièr",
    3: "març",
    4: "abril",
    5: "mai",
    6: "junh",
    7: "julhet",
    8: "agost",
    9: "setembre",
    10: "octòbre",
    11: "novembre",
    12: "decembre"
}


def _pronounce_oc(number, feminine=False):
    gender = GrammaticalGender.FEMININE if feminine \
        else GrammaticalGender.MASCULINE
    return OC.pronounce_number(number, gender=gender)


def nice_year_oc(dt, bc=False):
    """Format a year into a pronounceable form, e.g. 'dos mila vint e tres'."""
    # no "e" directly after "mila": "dos mila vint e tres", but
    # "mila cent e cinc" keeps its "e" (only hundreds join it)
    year = _pronounce_oc(dt.year).replace("mila e ", "mila ", 1)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_oc(dt):
    weekday = WEEKDAYS_OC[dt.weekday()]
    return weekday.capitalize()


def nice_month_oc(dt):
    month = MONTHS_OC[dt.month]
    return month.capitalize()


def nice_day_oc(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_oc(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_time_oc(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time in a pronounceable way,
    e.g. 'dimars, cinc de junh de 2018 a las cinc e mièja'."""
    now = now or None
    return f"{nice_date_oc(dt, now)} a las {nice_time_oc(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_oc(dt: datetime, now: datetime = None, include_weekday=True):
    """Format a date in a pronounceable way,
    e.g. 'dimars, cinc de junh de dos mila dètz-e-uèch'."""
    day = _pronounce_oc(dt.day)
    # months are lowercase in running text; vowel-initial months take "d'"
    # (abril, agost, octòbre), as in Catalan
    month = MONTHS_OC[dt.month]
    month_part = "d'" + month if month[0] in "aeiou" else "de " + month
    if now is not None:
        nice = day
        if dt.day == now.day:
            return "uèi"
        if dt.day == now.day + 1:
            return "deman"
        if dt.day == now.day - 1:
            return "ièr"
        if dt.month != now.month or dt.year != now.year:
            nice = nice + " " + month_part
        if dt.year != now.year:
            nice = nice + " de " + nice_year_oc(dt)
    else:
        nice = f"{day} {month_part} de {nice_year_oc(dt)}"

    if include_weekday:
        weekday = nice_weekday_oc(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_oc(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time into a human-comprehensible form.

    For example, generates 'cinc oras e mièja' for speech or '5:30' for
    text display. The quarter-to reading names the next hour:
    'doas oras manca un quart' for 1:45.
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
            string = string[1:]  # strip leading zero

    if not speech:
        return string

    def spoken_hour(hour):
        if hour == 1:
            return "una ora"
        return _pronounce_oc(hour, feminine=True) + " oras"

    speak = ""
    if use_24hour:
        if dt.hour == 0:
            speak += "mièjanuèch"
        elif dt.hour == 12:
            speak += "miègjorn"
        else:
            speak += spoken_hour(dt.hour)
        if dt.hour in (0, 12):
            # noon and midnight take the half-hour idiom, not digit minutes
            if dt.minute == 30:
                speak += " e mièg"
            elif dt.minute != 0:
                speak += " e " + _pronounce_oc(dt.minute)
        elif dt.minute < 10:
            speak += " zèro " + _pronounce_oc(dt.minute)
        else:
            speak += " " + _pronounce_oc(dt.minute)

    else:
        if dt.minute == 45:
            minute = -15
            hour = dt.hour + 1
        else:
            minute = dt.minute
            hour = dt.hour

        if hour == 0 or hour == 24:
            speak += "mièjanuèch"
        elif hour == 12:
            speak += "miègjorn"
        elif hour < 13:
            speak += spoken_hour(hour)
        else:
            speak += spoken_hour(hour - 12)

        if minute != 0:
            if minute == 15:
                speak += " e quart"
            elif minute == 30:
                # "mièjanuèch/miègjorn e mièg", but "cinc oras e mièja"
                speak += " e mièg" if hour in (0, 12) else " e mièja"
            elif minute == -15:
                speak += " manca un quart"
            else:
                speak += " e " + _pronounce_oc(minute)

        if use_ampm:
            if dt.hour == 0 or dt.hour == 12:
                pass  # mièjanuèch / miègjorn need no qualifier
            elif dt.hour < 13:
                speak += " del matin"
            elif dt.hour < 19:
                speak += " de l'aprèp-miègjorn"
            elif dt.hour < 22:
                speak += " del ser"
            else:
                speak += " de la nuèch"
    return speak


def extract_datetime_oc(text, anchorDate=None, default_time=None):
    """
    Extract date and time information from an Occitan phrase.

    Args:
        text (str): text to parse
        anchorDate (datetime): reference date for relative dates
        default_time (time): time to use if none is found in the text

    Returns:
        [datetime, str] | None: the extracted date and the remaining text,
        or None if no date or time is found.
    """

    def clean_string(s):
        # strip punctuation/case and normalize vocabulary
        symbols = [".", ",", ";", "?", "!", "º", "ª"]

        for word in symbols:
            s = s.replace(word, "")

        s = s.lower()
        for src, tgt in (("á", "a"), ("à", "a"), ("é", "e"), ("è", "e"),
                         ("í", "i"), ("ï", "i"), ("ó", "o"), ("ò", "o"),
                         ("ú", "u"), ("ü", "u")):
            s = s.replace(src, tgt)
        s = s.replace("-", " ").replace("'", " ").replace("_", "")
        s = " " + s + " "

        # "que ven" == seguent
        s = s.replace(" que ven", " seguent")
        # afternoon is a two-token compound after cleaning
        s = s.replace("aprep miegjorn", "tantost")
        # "aprèp dinnar" / "après dinnar" = early afternoon,
        # "aprèp merende" / "après merende" = mid-afternoon
        for meal in ("dinnar", "merende"):
            for prep in ("apres", "aprep"):
                s = s.replace(" " + prep + " " + meal + " ",
                              " " + meal + " ")

        # spoken hours preceded by an article: "a la una", "a las doas"
        spoken_hours = {"una": "1", "doas": "2", "tres": "3", "quatre": "4",
                        "cinc": "5", "sieis": "6", "set": "7", "uech": "8",
                        "ueit": "8", "uoch": "8",
                        "nou": "9", "detz": "10", "onze": "11", "dotze": "12"}
        for k, v in spoken_hours.items():
            s = re.sub(r"\b(a la|a las|la|las) " + k + r"\b", r"\1 " + v, s)

        noise_words = ["entre", "lo", "los", "la", "las", "del", "dels",
                       "de", "d", "l", "per", "a", "al", "en", "un", "una",
                       "aqueste", "aquesta", "que"]
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")

        # month variant spellings (abrial, julh) map to the reference form
        s = s.replace(" abrial ", " abril ").replace(" julh ", " julhet ")

        # synonyms and equivalents
        synonyms = {"matin": ["matinada", "alba"],
                    "vespre": ["ser", "serada"],
                    "nuech": ["anuech", "nueit", "neit", "net", "nech",
                              "nuoch", "aneit", "anet", "anech", "anuoch"]}
        for syn in synonyms:
            for word in synonyms[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")

        # relevant plurals
        wordlist = ["matins", "vespres", "nuechs", "jorns", "setmanas",
                    "ans", "minutas", "segondas", "seguents",
                    "oras"]
        for word in wordlist:
            s = re.sub(r"\b" + word + r"\b", word.rstrip('s'), s)
        s = s.replace("meses", "mes").replace("anteriors", "anterior")
        return s.strip()

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
    if anchorDate is None:
        anchorDate = now_local()

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

    words = clean_string(text).split(" ")
    timeQualifiersList = ['matin', 'tantost', 'vespre', 'nuech']
    time_indicators = ["en", "a", "la", "las", "lo", "los", "al", "per",
                       "passats", "passadas", "jorn", "ora", "aqui"]
    days = ['diluns', 'dimars', 'dimecres',
            'dijous', 'divendres', 'dissabte', 'dimenge']
    months = ['genier', 'febrier', 'març', 'abril', 'mai', 'junh',
              'julhet', 'agost', 'setembre', 'octobre', 'novembre',
              'decembre']
    monthsShort = ['gen', 'feb', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago',
                   'set', 'oct', 'nov', 'dec']
    nexts = ["seguent", "venent", "prochan", "prochana"]
    suffix_nexts = ["seguent", "seguents", "venent", "venents",
                    "seguenta", "seguentas", "venenta", "venentas",
                    "prochan", "prochans", "prochana", "prochanas"]
    lasts = ["darrier", "darriera", "ultim", "ultima",
             "darrer", "darrera", "darrieir", "darrieira"]
    # Occitan puts the adjective after the noun: "la setmana darrièra"
    suffix_lasts = ["passada", "passat", "anterior", "abans",
                    "precedent", "precedenta",
                    "darrier", "darriera", "darrer", "darrera",
                    "darrieir", "darrieira", "ultim", "ultima"]
    nxts = ["apres", "seguent", "venent", "prochan", "prochana"]
    prevs = ["abans", "previa", "previ", "anterior", "precedent"]
    froms = ["dempuei", "desde", "en", "per", "apres", "aqui",
             "seguent", "venent", "de"]
    thises = ["aqueste", "aquesta"]
    froms += thises
    lists = nxts + prevs + froms + time_indicators
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
        # save the time qualifier for later
        if word in timeQualifiersList:
            timeQualifier = word

        # uèi, deman, ièr
        elif word == "uei" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "deman" and wordNext == "passat" and not fromFlag:
            # deman passat = day after tomorrow
            dayOffset += 2
            used = 2
        elif word == "deman" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "ier" and not fromFlag:
            dayOffset -= 1
            used += 1
            # "ièr delà / ièr delai" = the day before yesterday
            if wordNext in ("dela", "delai"):
                dayOffset -= 1
                used += 1
            # "passat ièr" = the day before yesterday
            elif wordPrev == "passat":
                dayOffset -= 1
                start -= 1
                used += 1
        # abans-ièr / davant-ièr
        elif word in ("abans", "davant") and wordNext == "ier" and not fromFlag:
            dayOffset -= 2
            used = 2
        # "d'aquí 5 jorns", "en 5 jorns", etc
        elif word == "jorn":
            if wordNext == "passat" or wordNext == "abans":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "fa N ..." = N periods in the past (Lo Congrès / DGLO)
                if wordPrevPrev == "fa":
                    dayOffset -= int(wordPrev)
                    start -= 2
                    used += 3
                else:
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 2
            elif wordNext and wordNext[0].isdigit() and wordNextNext not in \
                    months and wordNextNext not in monthsShort:
                dayOffset += int(wordNext)
                start -= 1
                used += 2

        elif word == "setmana" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "fa N ..." = N periods in the past (Lo Congrès / DGLO)
                if wordPrevPrev == "fa":
                    dayOffset -= int(wordPrev) * 7
                    start -= 2
                    used = 3
                else:
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
                    # suffix marker: the unit word itself stays at start
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset = -7
                    # suffix marker: the unit word itself stays at start
                    used = 2
        # 10 meses, mes seguent, mes passat
        elif word == "mes" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "fa N ..." = N periods in the past (Lo Congrès / DGLO)
                if wordPrevPrev == "fa":
                    monthOffset = -int(wordPrev)
                    start -= 2
                    used = 3
                else:
                    monthOffset = int(wordPrev)
                    start -= 1
                    used = 2
            for w in nexts:
                if wordPrev == w:
                    monthOffset = 1
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    monthOffset = -1
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    monthOffset = 1
                    # suffix marker: the unit word itself stays at start
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    monthOffset = -1
                    # suffix marker: the unit word itself stays at start
                    used = 2
        # 5 ans, an seguent, an passat
        elif word == "an" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "fa N ..." = N periods in the past (Lo Congrès / DGLO)
                if wordPrevPrev == "fa":
                    yearOffset = -int(wordPrev)
                    start -= 2
                    used = 3
                else:
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
                    # suffix marker: the unit word itself stays at start
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    yearOffset = -1
                    # suffix marker: the unit word itself stays at start
                    used = 2
        # weekdays: diluns, dimars...
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev in nexts:
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "passat":
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext == "seguent":
                used += 1
            elif wordNext == "passat":
                used += 1
        # 3 de junh, junh 20, etc
        elif word in months or word in monthsShort:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
                # 13 de mai
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
                # mai 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 jorn de mai
                datestr += " " + wordPrevPrev
                start -= 2
                used += 2
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNextNext and wordNextNext[0].isdigit():
                # mai jorn 13
                datestr += " " + wordNextNext
                used += 2
                if wordNextNextNext and wordNextNextNext[0].isdigit():
                    datestr += " " + wordNextNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            if datestr in months:
                datestr = ""

        # "5 jorns dempuèi deman", "2 setmanas dempuèi dijòus", etc
        validFollowups = days + months + monthsShort
        validFollowups.append("uei")
        validFollowups.append("deman")
        validFollowups.append("ier")
        validFollowups.append("ara")
        validFollowups.append("ja")

        if word in froms and wordNext in validFollowups:

            if not (word == "passat" or word == "abans"):
                used = 2
                fromFlag = True
            if wordNext == "deman" and word != "passat":
                dayOffset += 1
            elif wordNext == "ier":
                dayOffset -= 1
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
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

    # parse the time
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
        # miègjorn, mièjanuèch, matin, tantòst, vèspre, nuèch
        used = 0
        if word == "miegjorn":
            hrAbs = 12
            used += 1
        elif word == "miejanuech":
            hrAbs = 0
            used += 1
        elif word == "matin":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tantost":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word == "vespre":
            if not hrAbs:
                hrAbs = 19
            used += 1
        elif word == "dinnar":
            # lunch-time meal; "aprèp dinnar" compacts to "dinnar"
            if not hrAbs:
                hrAbs = 14
            used += 1
        elif word == "merende":
            # afternoon snack; "aprèp merende" compacts to "merende"
            if not hrAbs:
                hrAbs = 16
            used += 1
        elif word == "vesprada":
            # late afternoon, before the evening proper
            if not hrAbs:
                hrAbs = 17
            used += 1
        elif word == "nuech":
            if not hrAbs:
                hrAbs = 21
            used += 1
        # mièja ora, quart d'ora
        elif (word == "ora" and
              (wordPrev in time_indicators or wordPrevPrev in
               time_indicators)):
            if wordPrev == "mieja":
                minOffset = 30
            elif wordPrev == "quart":
                minOffset = 15
            elif wordPrevPrev == "quart":
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
        # 5:00 am, 12:00 pm, a las 8, etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
                # 17:30, 3:00 del matin
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
                    elif wordNext == "matin":
                        remainder = "am"
                        used += 1
                    elif wordNext in ("tantost", "vespre"):
                        remainder = "pm"
                        used += 1
                    elif wordNext == "nuech":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif timeQualifier != "":
                        if int(strHH) <= 12 and \
                                timeQualifier in ["tantost", "vespre", "nuech"]:
                            remainder = "pm"

            else:
                # numbers without colons
                # a las 8 e mièja, en 5 minutas, etc
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
                # a las 8 e mièja, a las 8 e quart
                elif wordNext == "e" and wordNextNext in ["mieja", "quart"]:
                    strHH = strNum
                    strMM = 30 if wordNextNext == "mieja" else 15
                    used = 2
                    if wordNextNextNext in ("tantost", "vespre"):
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "matin":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "nuech":
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                # a las 8 manca un quart -> 7:45
                elif wordNext == "manca" and wordNextNext == "quart":
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 45
                    used = 2
                    if wordNextNextNext in ("tantost", "vespre"):
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "matin":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "nuech":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                else:
                    if wordNext in ("tantost", "vespre"):
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif wordNext == "matin":
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif wordNext == "nuech":
                        strHH = strNum
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used = 1
                    elif (wordNext == "ora" and
                          word[0] != '0' and
                          int(word) < 100):
                        # en 3 oras
                        hrOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minuta":
                        # en 10 minutas
                        minOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segonda":
                        # en 5 segondas
                        secOffset = int(word)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif strNum and int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        if wordNext == "ora":
                            used += 1
                    elif wordNext == "":
                        strHH = strNum
                        strMM = 00
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        used += 1
                        if wordNextNext == "ora":
                            used += 1
                    else:
                        isTime = False

            strHH = int(strHH) if strHH else 0
            strMM = int(strMM) if strMM else 0
            strHH = strHH + 12 if (remainder == "pm" and
                                   0 < strHH < 12) else strHH
            strHH = strHH - 12 if (remainder == "am" and
                                   strHH >= 12) else strHH
            if strHH > 24 or strMM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = strHH * 1
                minAbs = strMM * 1
                used += 1

        if used > 0:
            # remove parsed words from the phrase
            for i in range(used):
                words[idx + i] = ""

            if idx > 0 and wordPrev in time_indicators:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in time_indicators:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # check that a date was found
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # date manipulation

    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # purely relative time ("d'aquí doas oras") keeps the anchor time of day
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
                          'aug', 'sept', 'oct', 'nov', 'dec']
        for idx, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months[idx]) + r"\b",
                             en_month, datestr)
        for idx, en_month in enumerate(en_monthsShort):
            datestr = re.sub(r"\b" + re.escape(monthsShort[idx]) + r"\b",
                             en_month, datestr)

        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # impossible calendar date ("31 de abril", "30 de febrier")
            return None
        if extractedDate.tzinfo:
            temp = temp.replace(tzinfo=extractedDate.tzinfo)

        if not hasYear:
            temp = temp.replace(year=extractedDate.year)

            if extractedDate < temp:
                extractedDate = extractedDate.replace(
                    year=int(currentYear),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")))
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
    return [extractedDate, resultStr]
