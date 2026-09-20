import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_pt import pronounce_number_pt, numbers_to_digits_pt
from ovos_number_parser.util import GrammaticalGender
from ovos_utils.time import now_local, DAYS_IN_1_YEAR, DAYS_IN_1_MONTH
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

WEEKDAYS_PT = {
    0: "segunda-feira",
    1: "terça-feira",
    2: "quarta-feira",
    3: "quinta-feira",
    4: "sexta-feira",
    5: "sábado",
    6: "domingo"
}
MONTHS_PT = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro"
}


def nice_year_pt(dt, bc=False):
    """
        Format a datetime to a pronounceable year

        For example, generate 'nineteen-hundred and eighty-four' for year 1984

        Args:
            dt (datetime): date to format (assumes already in local timezone)
            bc (bool) pust B.C. after the year (python does not support dates
                B.C. in datetime)
        Returns:
            (str): The formatted year string
    """
    year = pronounce_number_pt(dt.year, gender=GrammaticalGender.MASCULINE)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_pt(dt):
    weekday = WEEKDAYS_PT[dt.weekday()]
    return weekday.capitalize()


def nice_month_pt(dt):
    month = MONTHS_PT[dt.month]
    return month.capitalize()


def nice_day_pt(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_pt(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d"))
        else:
            return "{} {}".format(dt.strftime("%d"), month)
    return dt.strftime("%d")


def nice_date_time_pt(dt, now=None, use_24hour=False,
                      use_ampm=False):
    """
        Format a datetime to a pronounceable date and time

        For example, generate 'tuesday, june the fifth, 2018 at five thirty'

        Args:
            dt (datetime): date to format (assumes already in local timezone)
            now (datetime): Current date. If provided, the returned date for
                speech will be shortened accordingly: No year is returned if
                now is in the same year as td, no month is returned if now is
                in the same month as td. If now and td is the same day, 'today'
                is returned.
            use_24hour (bool): output in 24-hour/military or 12-hour format
            use_ampm (bool): include the am/pm for 12-hour format
        Returns:
            (str): The formatted date time string
    """
    now = now or now_local()
    return f"{nice_date_pt(dt, now)} ás {nice_time_pt(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_pt(dt: datetime, now: datetime = None, include_weekday=True):
    """
    Format a datetime to a pronounceable date

    For example, generates 'tuesday, june the fifth, 2018'

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        now (datetime): Current date. If provided, the returned date for speech
            will be shortened accordingly: No year is returned if now is in the
            same year as td, no month is returned if now is in the same month
            as td. If now and td is the same day, 'today' is returned.
        include_weekday (bool, optional): Whether to include the weekday name in the output. Defaults to True.

    Returns:
        (str): The formatted date string
    """
    day = pronounce_number_pt(dt.day, gender=GrammaticalGender.MASCULINE)
    if now is not None:
        nice = day
        if dt.date() == now.date():
            return "hoje"
        if dt.date() == now.date() + timedelta(days=1):
            return "amanhã"
        if dt.date() == now.date() - timedelta(days=1):
            return "ontem"
        if dt.month != now.month or dt.year != now.year:
            nice = nice + " de " + nice_month_pt(dt)
        if dt.year != now.year:
            nice = nice + ", " + nice_year_pt(dt)
    else:
        nice = f"{day} de {nice_month_pt(dt)}, {nice_year_pt(dt)}"

    if include_weekday:
        weekday = nice_weekday_pt(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_pt(dt, speech=True, use_24hour=False, use_ampm=False):
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
        # simply speak the number
        speak += pronounce_number_pt(dt.hour, gender=GrammaticalGender.FEMININE)

        # equivalent to "quarter past ten"
        if dt.minute > 0:
            speak += " e " + pronounce_number_pt(dt.minute, gender=GrammaticalGender.MASCULINE)

    else:
        # speak number and add daytime identifier
        # (equivalent to "in the morning")
        if dt.minute == 35:
            minute = -25
            hour = dt.hour + 1
        elif dt.minute == 40:
            minute = -20
            hour = dt.hour + 1
        elif dt.minute == 45:
            minute = -15
            hour = dt.hour + 1
        elif dt.minute == 50:
            minute = -10
            hour = dt.hour + 1
        elif dt.minute == 55:
            minute = -5
            hour = dt.hour + 1
        else:
            minute = dt.minute
            hour = dt.hour

        if hour == 0:
            speak += "meia noite"
        elif hour == 12:
            speak += "meio dia"
        elif hour < 13:
            speak = pronounce_number_pt(hour, gender=GrammaticalGender.FEMININE)
        else:
            speak = pronounce_number_pt(hour - 12, gender=GrammaticalGender.FEMININE)

        if minute != 0:
            if minute == 15:
                speak += " e um quarto"
            elif minute == 30:
                speak += " e meia"
            elif minute == -15:
                speak += " menos um quarto"
            else:
                if minute > 0:
                    speak += " e " + pronounce_number_pt(minute, gender=GrammaticalGender.MASCULINE)
                else:
                    speak += " " + pronounce_number_pt(minute, gender=GrammaticalGender.MASCULINE)

        # exact time
        if minute == 0 and not use_ampm:
            # 3:00
            speak += " em ponto"

        if use_ampm:
            if hour > 0 and hour < 6:
                speak += " da madrugada"
            elif hour >= 6 and hour < 12:
                speak += " da manhã"
            elif hour >= 13 and hour < 21:
                speak += " da tarde"
            elif hour != 0 and hour != 12:
                speak += " da noite"
    return speak


def extract_datetime_pt(text, anchorDate=None, default_time=None):
    def clean_string(s):
        # cleans the input string of unneeded punctuation and capitalization
        # among other things
        symbols = [".", ",", ";", "?", "!", "º", "ª"]
        noise_words = ["o", "os", "a", "as", "do", "da", "dos", "das", "de",
                       "ao", "aos"]

        for word in symbols:
            s = s.replace(word, "")
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")
        s = s.lower().replace(
            "á",
            "a").replace(
            "ç",
            "c").replace(
            "à",
            "a").replace(
            "ã",
            "a").replace(
            "é",
            "e").replace(
            "è",
            "e").replace(
            "ê",
            "e").replace(
            "ó",
            "o").replace(
            "ò",
            "o").replace(
            "-",
            " ").replace(
            "_",
            "")
        # handle synonims and equivalents, "tomorrow early = tomorrow morning
        synonims = {"manha": ["manhazinha", "cedo", "cedinho"],
                    "tarde": ["tardinha", "tarde"],
                    "noite": ["noitinha", "anoitecer"],
                    "todos": ["ao", "aos"],
                    "em": ["do", "da", "dos", "das", "de"]}
        for syn in synonims:
            for word in synonims[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")
        # relevant plurals, cant just extract all s in pt
        wordlist = ["manhas", "noites", "tardes", "dias", "semanas", "anos",
                    "minutos", "segundos", "nas", "nos", "proximas",
                    "seguintes", "horas"]
        for _, word in enumerate(wordlist):
            s = s.replace(word, word.rstrip('s'))
        s = s.replace("meses", "mes").replace("anteriores", "anterior")
        return s

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

    words = clean_string(text).split(" ")
    timeQualifiersList = ['manha', 'tarde', 'noite']
    time_indicators = ["em", "as", "nas", "pelas", "volta", "depois", "estas",
                       "no", "dia", "hora"]
    days = ['segunda', 'terca', 'quarta',
            'quinta', 'sexta', 'sabado', 'domingo']
    months = ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho',
              'julho', 'agosto', 'setembro', 'outubro', 'novembro',
              'dezembro']
    monthsShort = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago',
                   'set', 'out', 'nov', 'dez']
    nexts = ["proximo", "proxima"]
    suffix_nexts = ["seguinte", "subsequente", "seguir"]
    lasts = ["ultimo", "ultima"]
    suffix_lasts = ["passada", "passado", "anterior", "antes"]
    nxts = ["depois", "seguir", "seguida", "seguinte", "proxima", "proximo"]
    prevs = ["antes", "ante", "previa", "previamente", "anterior"]
    froms = ["partir", "em", "para", "na", "no", "daqui", "seguir",
             "depois", "por", "proxima", "proximo", "da", "do", "de"]
    thises = ["este", "esta", "deste", "desta", "neste", "nesta", "nesse",
              "nessa"]
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
        # save timequalifier for later
        if word in timeQualifiersList:
            timeQualifier = word

        # parse today, tomorrow, yesterday
        elif word == "hoje" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "amanha" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "ontem" and not fromFlag:
            dayOffset -= 1
            used += 1
        # "before yesterday" and "before before yesterday"
        elif (word == "anteontem" or
              (word == "ante" and wordNext == "ontem")) and not fromFlag:
            dayOffset -= 2
            used += 1
            if wordNext == "ontem":
                used += 1
        elif word == "ante" and wordNext == "ante" and wordNextNext == \
                "ontem" and not fromFlag:
            dayOffset -= 3
            used += 3
        elif word == "anteanteontem" and not fromFlag:
            dayOffset -= 3
            used += 1
        # day after tomorrow
        elif word == "depois" and wordNext == "amanha" and not fromFlag:
            dayOffset += 2
            used = 2
        # day before yesterday
        elif word == "antes" and wordNext == "ontem" and not fromFlag:
            dayOffset -= 2
            used = 2
        # parse 5 days, 10 weeks, last week, next week, week after
        elif word == "dia":
            if wordNext == "depois" or wordNext == "antes":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "há N / N ... atrás" = N periods elapsed in the past (Priberam)
                if wordPrevPrev == "ha" or wordNext == "atras":
                    dayOffset -= int(wordPrev)
                    start -= 2 if wordPrevPrev == "ha" else 1
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

        elif word == "semana" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "há N / N ... atrás" = N periods elapsed in the past (Priberam)
                if wordPrevPrev == "ha" or wordNext == "atras":
                    dayOffset -= int(wordPrev) * 7
                    start -= 2 if wordPrevPrev == "ha" else 1
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
        # parse 10 months, next month, last month
        elif word == "mes" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "há N / N ... atrás" = N periods elapsed in the past (Priberam)
                if wordPrevPrev == "ha" or wordNext == "atras":
                    monthOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev == "ha" else 1
                    used = 3
                else:
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
        elif word == "ano" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "há N / N ... atrás" = N periods elapsed in the past (Priberam)
                if wordPrevPrev == "ha" or wordNext == "atras":
                    yearOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev == "ha" else 1
                    used = 3
                else:
                    yearOffset = int(wordPrev)
                    start -= 1
                    used = 2
            for w in nexts:
                if wordPrev == w:
                    yearOffset = 7
                    start -= 1
                    used = 2
            for w in lasts:
                if wordPrev == w:
                    yearOffset = -7
                    start -= 1
                    used = 2
            for w in suffix_nexts:
                if wordNext == w:
                    yearOffset = 7
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    yearOffset = -7
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
            for w in nexts:
                if wordPrev == w:
                    dayOffset += 7
                    used += 1
                    start -= 1
            for w in lasts:
                if wordPrev == w:
                    dayOffset -= 7
                    used += 1
                    start -= 1
            for w in suffix_nexts:
                if wordNext == w:
                    dayOffset += 7
                    used += 1
                    start -= 1
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset -= 7
                    used += 1
                    start -= 1
            if wordNext == "feira":
                used += 1
        # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in monthsShort:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
                # 13 maio
                datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext.isdigit() and len(wordNext) == 4:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                # maio 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext.isdigit() and len(wordNextNext) == 4:
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 dia maio
                datestr += " " + wordPrevPrev

                start -= 2
                used += 2
                if wordNext.isdigit() and len(wordNext) == 4:
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNextNext and wordNextNext[0].isdigit():
                # maio dia 13
                datestr += " " + wordNextNext
                used += 2
                if wordNextNextNext.isdigit() and len(wordNextNextNext) == 4:
                    datestr += " " + wordNextNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            if datestr in months:
                datestr = ""

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("hoje")
        validFollowups.append("amanha")
        validFollowups.append("ontem")
        validFollowups.append("anteontem")
        validFollowups.append("agora")
        validFollowups.append("ja")
        validFollowups.append("ante")

        # TODO debug word "depois" that one is failing for some reason
        if word in froms and wordNext in validFollowups:

            if not (wordNext == "amanha" and wordNext == "ontem") and not (
                    word == "depois" or word == "antes" or word == "em"):
                used = 2
                fromFlag = True
            if wordNext == "amanha" and word != "depois":
                dayOffset += 1
            elif wordNext == "ontem":
                dayOffset -= 1
            elif wordNext == "anteontem":
                dayOffset -= 2
            elif wordNext == "ante" and wordNextNext == "ontem":
                dayOffset -= 2
            elif (wordNext == "ante" and wordNextNext == "ante" and
                  wordNextNextNext == "ontem"):
                dayOffset -= 3
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if wordNextNext == "feira":
                    used += 1
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
                if wordNextNextNext == "feira":
                    used += 1
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
    timeStr = ""
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
        wordNextNextNext = words[idx + 3] if idx + 3 < len(words) else ""
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "meio" and wordNext == "dia":
            hrAbs = 12
            used += 2
        elif word == "meia" and wordNext == "noite":
            hrAbs = 0
            used += 2
        elif word == "manha":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tarde":
            if not hrAbs:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used += 1
        elif word == "meio" and wordNext == "tarde":
            if not hrAbs:
                hrAbs = 17
            used += 2
        elif word == "meio" and wordNext == "manha":
            if not hrAbs:
                hrAbs = 10
            used += 2
        elif word == "fim" and wordNext == "tarde":
            if not hrAbs:
                hrAbs = 19
            used += 2
        elif word == "fim" and wordNext == "manha":
            if not hrAbs:
                hrAbs = 11
            used += 2
        elif word == "tantas" and wordNext == "manha":
            if not hrAbs:
                hrAbs = 4
            used += 2
        elif word == "noite":
            if not hrAbs:
                hrAbs = 22
            elif hrAbs == 12:
                hrAbs = 0
            used += 1
        # parse half an hour, quarter hour
        elif word == "hora" and \
                (wordPrev in time_indicators or wordPrevPrev in
                 time_indicators):
            if wordPrev == "meia":
                minOffset = 30
            elif wordPrev == "quarto":
                minOffset = 15
            elif wordPrevPrev == "quarto":
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
                    elif wordNext == "manha":
                        remainder = "am"
                        used += 1
                    elif wordNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "noite":
                        if 0 < int(word[0]) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif wordNext in thises and wordNextNext == "manha":
                        remainder = "am"
                        used = 2
                    elif wordNext in thises and wordNextNext == "tarde":
                        remainder = "pm"
                        used = 2
                    elif wordNext in thises and wordNextNext == "noite":
                        remainder = "pm"
                        used = 2
                    else:
                        if timeQualifier != "":
                            military = True
                            if strHH <= 12 and \
                                    (timeQualifier == "manha" or
                                     timeQualifier == "tarde"):
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

                # "15h30", "14h30min" style times
                hour_minute = re.match(r"^(\d{1,2})h(\d{1,2})(?:min)?$", word)
                if hour_minute:
                    strHH = hour_minute.group(1)
                    strMM = hour_minute.group(2)
                    military = True
                    if wordNext == "hora":
                        used += 1
                elif (
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
                            wordNext == "tarde"):
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif (wordNext == "am" or
                          wordNext == "a.m." or
                          wordNext == "manha"):
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif (strNum and int(strNum) > 100 and
                          (
                                  wordPrev == "o" or
                                  wordPrev == "oh" or
                                  wordPrev == "zero"
                          )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = int(strNum) // 100
                        strMM = int(strNum) - strHH * 100
                        military = True
                        if wordNext == "hora":
                            used += 1
                    elif (
                            wordNext == "hora" and strNum and
                            wordPrev in ["as", "nas", "pelas", "volta"] and
                            0 <= int(strNum) <= 24):
                        # "às 14 horas" / "pelas 9 horas" -> absolute clock
                        # time, unlike "em 14 horas" which is an offset
                        strHH = strNum
                        strMM = 0
                        used += 1
                        if timeQualifier in ["tarde", "noite"]:
                            remainder = "pm"
                        elif timeQualifier == "manha":
                            remainder = "am"
                    elif (
                            wordNext == "hora" and
                            word[0] != '0' and strNum and
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

                    elif wordNext == "minuto":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segundo":
                        # in 5 seconds
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif strNum and int(strNum) > 100:
                        strHH = int(strNum) // 100
                        strMM = int(strNum) - strHH * 100
                        military = True
                        if wordNext == "hora":
                            used += 1

                    elif wordNext == "" or (
                            wordNext == "em" and wordNextNext == "ponto"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "em" and wordNextNext == "ponto":
                            used += 2
                            if wordNextNextNext == "tarde":
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "manha":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "noite":
                                if 0 > int(strHH) > 6:
                                    remainder = "am"
                                else:
                                    remainder = "pm"
                                used += 1

                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if wordNextNext == "hora":
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

            if wordPrev == "em" or wordPrev == "ponto":
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
        # purely relative time ("em 2 horas") keeps the anchor time of day
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
            # impossible dates ("31 de abril") should not crash the parser
            temp = None
        if temp is None:
            datestr = ""
        else:
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
    if (hrAbs or 0) != -1 and (minAbs or 0) != -1:
        if hrAbs is None and minAbs is None and default_time:
            hrAbs = default_time.hour
            minAbs = default_time.minute
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


def extract_duration_pt(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["pt"],
                                    resolution, replace_token)
