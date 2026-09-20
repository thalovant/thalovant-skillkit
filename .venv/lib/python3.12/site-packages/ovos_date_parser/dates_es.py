import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_es import pronounce_number_es, numbers_to_digits_es
from ovos_utils.time import now_local, DAYS_IN_1_YEAR, DAYS_IN_1_MONTH
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

WEEKDAYS_ES = {
    0: "lunes",
    1: "martes",
    2: "miércoles",
    3: "jueves",
    4: "viernes",
    5: "sábado",
    6: "domingo"
}
MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre"
}


def nice_year_es(dt, bc=False):
    """
        Formatea un año en una forma pronunciable.

        Por ejemplo, genera 'mil novecientos ochenta y cuatro' para el año 1984.

        Args:
            dt (datetime): fecha a formatear (se supone que ya está en la zona horaria local)
            bc (bool): añade a.C. después del año (Python no soporta fechas a.C. en datetime)
        Returns:
            (str): El año formateado como cadena
    """
    year = pronounce_number_es(dt.year)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_es(dt):
    weekday = WEEKDAYS_ES[dt.weekday()]
    return weekday.capitalize()


def nice_month_es(dt):
    month = MONTHS_ES[dt.month]
    return month.capitalize()


def nice_day_es(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_es(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d"))
        else:
            return "{} {}".format(dt.strftime("%d"), month)
    return dt.strftime("%d")


def nice_date_time_es(dt, now=None, use_24hour=False,
                      use_ampm=False):
    """
        Formatea una fecha y hora de manera pronunciable.

        Por ejemplo, genera 'martes, cinco de junio de 2018 a las cinco y media'.

        Args:
            dt (datetime): fecha a formatear (se supone que ya está en la zona horaria local)
            now (datetime): Fecha actual. Si se proporciona, la fecha devuelta se acortará en consecuencia:
                No se devuelve el año si ahora está en el mismo año que `dt`, no se devuelve el mes
                si ahora está en el mismo mes que `dt`. Si `now` y `dt` son el mismo día, se devuelve 'hoy'.
            use_24hour (bool): salida en formato de 24 horas/militar o 12 horas
            use_ampm (bool): incluir el am/pm en formato de 12 horas
        Returns:
            (str): La cadena de fecha y hora formateada
    """
    now = now or now_local()
    return f"{nice_date_es(dt, now)} a las {nice_time_es(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_es(dt: datetime, now: datetime = None, include_weekday=True):
    """
    Formatea una fecha en una forma pronunciable.

    Por ejemplo, genera 'martes, cinco de junio de 2018'.

    Args:
        dt (datetime): fecha a formatear (se supone que ya está en la zona horaria local)
        now (datetime): Fecha actual. Si se proporciona, la fecha devuelta se acortará en consecuencia:
            No se devuelve el año si ahora está en el mismo año que `dt`, no se devuelve el mes
            si ahora está en el mismo mes que `dt`. Si `now` y `dt` son el mismo día, se devuelve 'hoy'.
        include_weekday (bool, optional): Whether to include the weekday name in the output. Defaults to True.

    Returns:
        (str): La cadena de fecha formateada
    """
    day = pronounce_number_es(dt.day)
    if now is not None:
        nice = day
        if dt.day == now.day:
            return "hoy"
        if dt.day == now.day + 1:
            return "mañana"
        if dt.day == now.day - 1:
            return "ayer"
        if dt.month != now.month:
            nice = nice + " de " + nice_month_es(dt)
        if dt.year != now.year:
            nice = nice + ", " + nice_year_es(dt)
    else:
        nice = f"{day} de {nice_month_es(dt)}, {nice_year_es(dt)}"

    if include_weekday:
        weekday = nice_weekday_es(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_es(dt, speech=True, use_24hour=False, use_ampm=False):
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
        if dt.hour == 1:
            speak += "la una"
        else:
            speak += "las " + pronounce_number_es(dt.hour)

        # las 14:04 son "las catorce cero cuatro"
        if dt.minute < 10:
            speak += " cero " + pronounce_number_es(dt.minute)
        else:
            speak += " " + pronounce_number_es(dt.minute)

    else:
        # Prepare for "tres menos cuarto" ??
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

        if hour == 0 or hour == 12:
            speak += "las doce"
        elif hour == 1 or hour == 13:
            speak += "la una"
        elif hour < 13:
            speak = "las " + pronounce_number_es(hour)
        else:
            speak = "las " + pronounce_number_es(hour - 12)

        if minute != 0:
            # las horas especiales
            if minute == 15:
                speak += " y cuarto"
            elif minute == 30:
                speak += " y media"
            elif minute == -15:
                speak += " menos cuarto"
            else:  # seis y nueve. siete y veinticinco
                if minute > 0:
                    speak += " y " + pronounce_number_es(minute)
                else:  # si son las siete menos veinte, no ponemos la "y"
                    speak += " " + pronounce_number_es(minute)

        # si no especificamos de la tarde, noche, mañana, etc
        if minute == 0 and not use_ampm:
            # 3:00
            speak += " en punto"

        if use_ampm:
            # "de la noche" es desde que anochece hasta medianoche
            # así que decir que es desde las 21h es algo subjetivo
            # en España a las 20h se dice "de la tarde"
            # en castellano, las 12h es de la mañana o mediodía
            # así que diremos "de la tarde" a partir de las 13h.
            # http://lema.rae.es/dpd/srv/search?id=YNoTWNJnAD6bhhVBf9
            if hour >= 0 and hour < 6:
                speak += " de la madrugada"
            elif hour >= 6 and hour < 13:
                speak += " de la mañana"
            elif hour >= 13 and hour < 21:
                speak += " de la tarde"
            else:
                speak += " de la noche"
    return speak


def extract_datetime_es(text, anchorDate=None, default_time=None):
    def clean_string(s):
        # cleans the input string of unneeded punctuation and capitalization
        # among other things
        symbols = [".", ",", ";", "?", "!", "º", "ª"]
        noise_words = ["entre", "la", "del", "al", "el", "de",
                       "para", "una", "cualquier", "a",
                       "e'", "esta", "este"]

        s = s.lower()
        # "la una" is the canonical way to say one o'clock; "una" alone is an
        # article and must not be treated as a number elsewhere
        s = re.sub(r"\bla una\b", "la 1", s)
        # turn spelled-out numbers ("tres", "quince") into digits so the
        # numeric time/date parser below can consume them
        s = numbers_to_digits_es(s)
        for word in symbols:
            s = s.replace(word, "")
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")
        s = s.lower().replace(
            "á",
            "a").replace(
            "é",
            "e").replace(
            "ó",
            "o").replace(
            "-",
            " ").replace(
            "_",
            "")
        # handle synonyms and equivalents, "tomorrow early = tomorrow morning
        synonyms = {"mañana": ["amanecer", "temprano", "muy temprano"],
                    "tarde": ["media tarde", "atardecer"],
                    "noche": ["anochecer", "tarde"]}
        for syn in synonyms:
            for word in synonyms[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")
        # relevant plurals, cant just extract all s in pt
        wordlist = ["mañanas", "tardes", "noches", "días", "semanas",
                    "años", "minutos", "segundos", "las", "los", "siguientes",
                    "próximas", "próximos", "horas"]
        for _, word in enumerate(wordlist):
            s = s.replace(word, word.rstrip('s'))
        s = s.replace("meses", "mes").replace("anteriores", "anterior")
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

    if not text:
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
    timeQualifiersList = ['mañana', 'tarde', 'noche']
    time_indicators = ["en", "la", "al", "por", "pasados",
                       "pasadas", "día", "hora"]
    days = ['lunes', 'martes', 'miércoles',
            'jueves', 'viernes', 'sábado', 'domingo']
    months = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
              'julio', 'agosto', 'septiembre', 'octubre', 'noviembre',
              'diciembre']
    monthsShort = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago',
                   'sep', 'oct', 'nov', 'dic']
    nexts = ["siguiente", "próximo", "próxima"]
    suffix_nexts = ["siguientes", "subsecuentes"]
    lasts = ["último", "última"]
    suffix_lasts = ["pasada", "pasado", "anterior", "antes"]
    nxts = ["después", "siguiente", "próximo", "próxima"]
    prevs = ["antes", "previa", "previo", "anterior"]
    froms = ["desde", "en", "para", "después de", "por", "próximo",
             "próxima", "de"]
    thises = ["este", "esta"]
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
        elif word == "hoy" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "mañana" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "ayer" and not fromFlag:
            dayOffset -= 1
            used += 1
        # "before yesterday" and "before before yesterday"
        elif (word == "anteayer" or
              (word == "ante" and wordNext == "ayer")) and not fromFlag:
            dayOffset -= 2
            used += 1
            if wordNext == "ayer":
                used += 1
        elif word == "ante" and wordNext == "ante" and wordNextNext == \
                "ayer" and not fromFlag:
            dayOffset -= 3
            used += 3
        elif word == "ante anteayer" and not fromFlag:
            dayOffset -= 3
            used += 1
        # day after tomorrow
        elif word == "pasado" and wordNext == "mañana" and not fromFlag:
            dayOffset += 2
            used = 2
        # day before yesterday
        elif word == "ante" and wordNext == "ayer" and not fromFlag:
            dayOffset -= 2
            used = 2
        # parse 5 days, 10 weeks, last week, next week, week after
        elif word == "día":
            if wordNext == "pasado" or wordNext == "ante":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "hace N / N ... atrás" = N periods in the past (RAE/DPD)
                if wordPrevPrev == "hace" or wordNext == "atras":
                    dayOffset -= int(wordPrev)
                    start -= 2 if wordPrevPrev == "hace" else 1
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
                # "hace N / N ... atrás" = N periods in the past (RAE/DPD)
                if wordPrevPrev == "hace" or wordNext == "atras":
                    dayOffset -= int(wordPrev) * 7
                    start -= 2 if wordPrevPrev == "hace" else 1
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
                # "hace N / N ... atrás" = N periods in the past (RAE/DPD)
                if wordPrevPrev == "hace" or wordNext == "atras":
                    monthOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev == "hace" else 1
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
        elif word == "año" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hace N / N ... atrás" = N periods in the past (RAE/DPD)
                if wordPrevPrev == "hace" or wordNext == "atras":
                    yearOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev == "hace" else 1
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
            if wordPrev == "siguiente":
                dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev == "pasado":
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext == "siguiente":
                # dayOffset += 7
                used += 1
            elif wordNext == "pasado":
                # dayOffset -= 7
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
                # 13 mayo
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
                # mayo 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 dia mayo
                datestr += " " + wordPrevPrev

                start -= 2
                used += 2
                if wordNext and word and word[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNextNext and wordNextNext[0].isdigit():
                # mayo dia 13
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

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("hoy")
        validFollowups.append("mañana")
        validFollowups.append("ayer")
        validFollowups.append("anteayer")
        validFollowups.append("ahora")
        validFollowups.append("ya")
        validFollowups.append("ante")

        # TODO debug word "depois" that one is failing for some reason
        if word in froms and wordNext in validFollowups:

            if not (wordNext == "mañana" and wordNext == "ayer") and not (
                    word == "pasado" or word == "antes"):
                used = 2
                fromFlag = True
            if wordNext == "mañana" and word != "pasado":
                dayOffset += 1
            elif wordNext == "ayer":
                dayOffset -= 1
            elif wordNext == "anteayer":
                dayOffset -= 2
            elif wordNext == "ante" and wordNextNext == "ayer":
                dayOffset -= 2
            elif (wordNext == "ante" and wordNext == "ante" and
                  wordNextNextNext == "ayer"):
                dayOffset -= 3
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
        if word == "medio" and wordNext == "día":
            hrAbs = 12
            used += 2
        elif word == "media" and wordNext == "noche":
            hrAbs = 0
            used += 2
        elif word == "mañana":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tarde":
            if not hrAbs:
                hrAbs = 15
            elif 0 < hrAbs < 12:
                hrAbs += 12
            used += 1
        elif word == "media" and wordNext == "tarde":
            if not hrAbs:
                hrAbs = 17
            used += 2
        elif word == "tarde" and wordNext == "noche":
            if not hrAbs:
                hrAbs = 20
            used += 2
        elif word == "media" and wordNext == "mañana":
            if not hrAbs:
                hrAbs = 10
            used += 2
        # elif word == "fim" and wordNext == "tarde":
        #     if not hrAbs:
        #         hrAbs = 19
        #     used += 2
        # elif word == "fim" and wordNext == "manha":
        #     if not hrAbs:
        #         hrAbs = 11
        #     used += 2
        elif word == "madrugada":
            if not hrAbs:
                hrAbs = 1
            elif hrAbs == 12:
                hrAbs = 0
            used += 1
        elif word == "noche":
            if not hrAbs:
                hrAbs = 21
            elif hrAbs == 12:
                hrAbs = 0
            used += 1
        # parse half an hour, quarter hour
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
                    elif wordNext == "mañana" or wordNext == "madrugada":
                        remainder = "am"
                        used += 1
                    elif wordNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "noche":
                        if 0 < int(word[0]) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif wordNext in thises and wordNextNext == "mañana":
                        remainder = "am"
                        used = 2
                    elif wordNext in thises and wordNextNext == "tarde":
                        remainder = "pm"
                        used = 2
                    elif wordNext in thises and wordNextNext == "noche":
                        remainder = "pm"
                        used = 2
                    else:
                        if timeQualifier != "":
                            if strHH <= 12 and \
                                    (timeQualifier == "mañana" or
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
                            wordNext == "tarde"):
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif (wordNext == "am" or
                          wordNext == "a.m." or
                          wordNext == "mañana"):
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif (strNum and int(strNum) > 100 and
                          (
                                  # wordPrev == "o" or
                                  # wordPrev == "oh" or
                                  wordPrev == "cero"
                          )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = int(strNum) // 100
                        strMM = int(strNum) - strHH * 100
                        if wordNext == "hora":
                            used += 1
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
                        if wordNext == "hora":
                            used += 1

                    elif wordNext == "y" and (
                            wordNextNext in ("cuarto", "media") or
                            (wordNextNext and wordNextNext[0].isdigit())):
                        # "tres y cuarto", "tres y media", "tres y veinte"
                        strHH = strNum
                        if wordNextNext == "cuarto":
                            strMM = 15
                        elif wordNextNext == "media":
                            strMM = 30
                        else:
                            strMM = int(wordNextNext)
                        used += 2
                        # optional part-of-day right after the minutes
                        if wordNextNextNext == "tarde" or \
                                wordNextNextNext == "noche":
                            remainder = "pm"
                            used += 1
                        elif wordNextNextNext in ("mañana", "madrugada"):
                            remainder = "am"
                            used += 1

                    elif wordNext == "" or (
                            wordNext == "en" and wordNextNext == "punto"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "en" and wordNextNext == "punto":
                            used += 2
                            if wordNextNextNext == "tarde":
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "mañana":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "noche":
                                if 0 > int(strHH) > 6:
                                    remainder = "am"
                                else:
                                    remainder = "pm"
                                used += 1

                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
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

            if wordPrev == "en" or wordPrev == "punto":
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
        # purely relative time ("dentro de dos horas") keeps the anchor time of day
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
            # an impossible calendar date like "30 de febrero"; report nothing
            # rather than a wrong guess
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
    # resultStr = pt_pruning(resultStr)
    return [extractedDate, resultStr]


def extract_duration_es(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["es"],
                                    resolution, replace_token)
