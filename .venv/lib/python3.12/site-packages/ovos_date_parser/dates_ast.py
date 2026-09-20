import re
from datetime import datetime
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_ast import AST
from ovos_utils.time import now_local

WEEKDAYS_AST = {
    0: "llunes",
    1: "martes",
    2: "miércoles",
    3: "xueves",
    4: "vienres",
    5: "sábadu",
    6: "domingu"
}
MONTHS_AST = {
    1: "xineru",
    2: "febreru",
    3: "marzu",
    4: "abril",
    5: "mayu",
    6: "xunu",
    7: "xunetu",
    8: "agostu",
    9: "setiembre",
    10: "ochobre",
    11: "payares",
    12: "avientu"
}


def pronounce_number_ast(number, **kwargs):
    return AST.pronounce_number(number, **kwargs)


def nice_year_ast(dt, bc=False):
    """
        Formatea un añu nuna forma pronunciable.

        Args:
            dt (datetime): data a formatear (asúmese que yá ta na zona horaria llocal)
            bc (bool): amiesta a.C. dempués del añu
        Returns:
            (str): L'añu formateáu como cadena
    """
    year = pronounce_number_ast(dt.year)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_ast(dt):
    weekday = WEEKDAYS_AST[dt.weekday()]
    return weekday.capitalize()


def nice_month_ast(dt):
    month = MONTHS_AST[dt.month]
    return month.capitalize()


def nice_day_ast(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_ast(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_time_ast(dt, now=None, use_24hour=False, use_ampm=False):
    """
        Formatea una data y hora de manera pronunciable.

        Por exemplu, xenera 'martes, cinco de xunu de 2018 a les cinco y media'.

        Args:
            dt (datetime): data a formatear (asúmese que yá ta na zona horaria llocal)
            now (datetime): Data actual. Si se proporciona, la data devuelta acurtiaráse.
            use_24hour (bool): salida en formatu de 24 hores o 12 hores
            use_ampm (bool): incluyir el am/pm en formatu de 12 hores
        Returns:
            (str): La cadena de data y hora formateada
    """
    now = now or now_local()
    # nice_time_ast yá inclúi l'artículu ("la una", "les cinco")
    return f"{nice_date_ast(dt, now)} a {nice_time_ast(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_ast(dt: datetime, now: datetime = None, include_weekday=True):
    """
    Formatea una data nuna forma pronunciable.

    Por exemplu, xenera 'martes, cinco de xunu de 2018'.

    Args:
        dt (datetime): data a formatear (asúmese que yá ta na zona horaria llocal)
        now (datetime): Data actual. Si se proporciona, la data devuelta acurtiaráse:
            Nun se devuelve l'añu si now ta nel mesmu añu que `dt`, nun se devuelve'l mes
            si now ta nel mesmu mes que `dt`. Si `now` y `dt` son el mesmu día,
            devuélvese 'güei'.
        include_weekday (bool, optional): Whether to prepend the weekday name to the formatted date. Defaults to True.

    Returns:
        (str): La cadena de data formateada
    """
    day = pronounce_number_ast(dt.day)
    if now is not None:
        nice = day
        if dt.day == now.day:
            return "güei"
        if dt.day == now.day + 1:
            return "mañana"
        if dt.day == now.day - 1:
            return "ayeri"
        if dt.month != now.month:
            nice = nice + " de " + nice_month_ast(dt)
        if dt.year != now.year:
            nice = nice + ", " + nice_year_ast(dt)
    else:
        nice = f"{day} de {nice_month_ast(dt)}, {nice_year_ast(dt)}"

    if include_weekday:
        weekday = nice_weekday_ast(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_ast(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Formatea una hora nun formatu humanu comprensible

    Por exemplu, xenera 'les cinco y media' pa la fala o '5:30' pa testu.

    Args:
        dt (datetime): data a formatear (asúmese que yá ta na zona horaria llocal)
        speech (bool): formatu pa la fala (True, por defeutu) o pa testu (False)
        use_24hour (bool): salida en formatu de 24 hores o de 12 hores
        use_ampm (bool): incluyir am/pm pal formatu de 12 hores
    Returns:
        (str): La cadena de testu cola hora formateada
    """
    if use_24hour:
        # ex.: "03:01" o "14:22"
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            # ex.: "3:01 AM" o "2:22 PM"
            string = dt.strftime("%I:%M %p")
        else:
            # ex.: "3:01" o "2:22"
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # desaniciar ceros a la izquierda

    if not speech:
        return string

    # Xenerar una versión falada de la hora
    speak = ""
    if use_24hour:
        if dt.hour == 1:
            speak += "la una"
        else:
            speak += "les " + pronounce_number_ast(dt.hour)

        if dt.minute < 10:
            speak += " cero " + pronounce_number_ast(dt.minute)
        else:
            speak += " " + pronounce_number_ast(dt.minute)

    else:
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
            speak += "les doce"
        elif hour == 1 or hour == 13:
            speak += "la una"
        elif hour < 13:
            speak = "les " + pronounce_number_ast(hour)
        else:
            speak = "les " + pronounce_number_ast(hour - 12)

        if minute != 0:
            if minute == 15:
                speak += " y cuartu"
            elif minute == 30:
                speak += " y media"
            elif minute == -15:
                speak += " menos cuartu"
            else:
                if minute > 0:
                    speak += " y " + pronounce_number_ast(minute)
                else:
                    speak += " " + pronounce_number_ast(minute)

        if minute == 0 and not use_ampm:
            speak += " en puntu"

        if use_ampm:
            if hour >= 0 and hour < 6:
                speak += " de la madrugada"
            elif hour >= 6 and hour < 13:
                speak += " de la mañana"
            elif hour >= 13 and hour < 21:
                speak += " de la tarde"
            else:
                speak += " de la nueche"
    return speak


def extract_datetime_ast(text, anchorDate=None, default_time=None):
    """
    Estrái información de data y hora d'una frase n'asturianu.

    Args:
        text (str): testu a interpretar
        anchorDate (datetime): data de referencia pa dates relatives
        default_time (time): hora a usar si nun s'atopa nenguna nel testu

    Returns:
        [datetime, str] | None: la data estrayida y el testu restante,
        o None si nun s'atopa nenguna data o hora.
    """

    def clean_string(s):
        # llimpia'l testu de puntuación y mayúscules y normaliza vocabulariu
        symbols = [".", ",", ";", "?", "!", "º", "ª"]

        for word in symbols:
            s = s.replace(word, "")

        s = s.lower().replace("á", "a").replace("é", "e").replace(
            "í", "i").replace("ó", "o").replace("ú", "u").replace(
            "ü", "u").replace("-", " ").replace("_", "")

        # "que vien" == siguiente
        s = s.replace(" que vien", " siguiente")

        # hores falaes precedíes d'artículu: "a la una", "a les dos"
        spoken_hours = {"una": "1", "dos": "2", "tres": "3", "cuatro": "4",
                        "cinco": "5", "seis": "6", "siete": "7", "ocho": "8",
                        "nueve": "9", "diez": "10", "once": "11", "doce": "12"}
        for k, v in spoken_hours.items():
            s = re.sub(r"\b(la|les) " + k + r"\b", r"\1 " + v, s)

        noise_words = ["ente", "la", "les", "lo", "el", "del", "al",
                       "de", "pa", "por", "un", "una", "cualquier",
                       "esti", "esta"]
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")

        # sinónimos y equivalentes
        synonyms = {"mañana": ["amanecer", "ceo", "bien ceo"],
                    "tarde": ["atapecer"],
                    "nueche": ["anochecer"]}
        for syn in synonyms:
            for word in synonyms[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")

        # plurales relevantes (n'asturianu -a > -es, -u > -os)
        s = s.replace("mañanes", "mañana").replace("tardes", "tarde") \
            .replace("nueches", "nueche").replace("dies", "dia") \
            .replace("selmanes", "selmana").replace("años", "añu") \
            .replace("minutos", "minutu").replace("segundos", "segundu") \
            .replace("hores", "hora").replace("siguientes", "siguiente") \
            .replace("proximes", "proxima").replace("proximos", "proximu") \
            .replace("meses", "mes").replace("anteriores", "anterior")
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
    timeQualifiersList = ['mañana', 'tarde', 'nueche']
    time_indicators = ["en", "a", "la", "les", "el", "al", "por", "pasaos",
                       "pasaes", "dia", "hora"]
    days = ['llunes', 'martes', 'miercoles',
            'xueves', 'vienres', 'sabadu', 'domingu']
    months = ['xineru', 'febreru', 'marzu', 'abril', 'mayu', 'xunu',
              'xunetu', 'agostu', 'setiembre', 'ochobre', 'payares',
              'avientu']
    monthsShort = ['xin', 'feb', 'mar', 'abr', 'may', 'xun', 'xnt', 'ago',
                   'set', 'och', 'pay', 'avi']
    nexts = ["siguiente", "proximu", "proxima"]
    suffix_nexts = ["siguiente", "siguientes"]
    lasts = ["ultimu", "ultima"]
    suffix_lasts = ["pasada", "pasau", "anterior", "antes"]
    nxts = ["dempues", "siguiente", "proximu", "proxima"]
    prevs = ["antes", "previa", "previu", "anterior"]
    froms = ["dende", "en", "pa", "dempues", "por", "proximu",
             "proxima", "de"]
    thises = ["esti", "esta"]
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
        # guardar el cualificador de tiempu pa dempués
        if word in timeQualifiersList:
            timeQualifier = word

        # güei, mañana, ayeri
        elif word == "guei" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "mañana" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "ayeri" and not fromFlag:
            dayOffset -= 1
            used += 1
        # pasáu mañana
        elif word in ("pasau", "pasao") and wordNext == "mañana" \
                and not fromFlag:
            dayOffset += 2
            used = 2
        # en 5 díes, etc
        elif word == "dia":
            if wordNext == "pasau" or wordNext == "pasao":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "hai/fai N / N ... atras" = N periods in the past (DALLA)
                if wordPrevPrev in ("hai", "fai") or wordNext == "atras":
                    dayOffset -= int(wordPrev)
                    start -= 2 if wordPrevPrev in ("hai", "fai") else 1
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

        elif word == "selmana" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai/fai N / N ... atras" = N periods in the past (DALLA)
                if wordPrevPrev in ("hai", "fai") or wordNext == "atras":
                    dayOffset -= int(wordPrev) * 7
                    start -= 2 if wordPrevPrev in ("hai", "fai") else 1
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
        # 10 meses, mes siguiente, mes pasáu
        elif word == "mes" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai/fai N / N ... atras" = N periods in the past (DALLA)
                if wordPrevPrev in ("hai", "fai") or wordNext == "atras":
                    monthOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev in ("hai", "fai") else 1
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    monthOffset = -1
                    start -= 1
                    used = 2
        # 5 años, añu siguiente, añu pasáu
        elif word == "añu" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai/fai N / N ... atras" = N periods in the past (DALLA)
                if wordPrevPrev in ("hai", "fai") or wordNext == "atras":
                    yearOffset = -int(wordPrev)
                    start -= 2 if wordPrevPrev in ("hai", "fai") else 1
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    yearOffset = -1
                    start -= 1
                    used = 2
        # díes de la selmana: llunes, martes...
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
            elif wordPrev in ("pasau", "pasao"):
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext == "siguiente":
                used += 1
            elif wordNext in ("pasau", "pasao"):
                used += 1
        # 3 de xunu, xunu 20, etc
        elif word in months or word in monthsShort:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
                # 13 mayu
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
                # mayu 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 dia mayu
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
                # mayu dia 13
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

        # 5 díes dende mañana, 2 selmanes dende'l xueves, etc
        validFollowups = days + months + monthsShort
        validFollowups.append("guei")
        validFollowups.append("mañana")
        validFollowups.append("ayeri")
        validFollowups.append("agora")
        validFollowups.append("ya")

        if word in froms and wordNext in validFollowups:

            if not (word in ("pasau", "pasao") or word == "antes"):
                used = 2
                fromFlag = True
            if wordNext == "mañana" and word not in ("pasau", "pasao"):
                dayOffset += 1
            elif wordNext == "ayeri":
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

    # analizar la hora
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
        # mediudía, medianueche, mañana, tarde, nueche
        used = 0
        if word == "mediudia" or (word == "mediu" and wordNext == "dia"):
            hrAbs = 12
            used += 2 if word == "mediu" else 1
        elif word == "medianueche" or (word == "media" and
                                       wordNext == "nueche"):
            hrAbs = 0
            used += 2 if word == "media" else 1
        elif word == "media" and wordNext == "tarde":
            if not hrAbs:
                hrAbs = 17
            used += 2
        elif word == "media" and wordNext == "mañana":
            if not hrAbs:
                hrAbs = 10
            used += 2
        elif word == "mañana":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tarde" and wordNext == "nueche":
            if not hrAbs:
                hrAbs = 20
            used += 2
        elif word == "tarde":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word == "madrugada":
            if not hrAbs:
                hrAbs = 1
            used += 1
        elif word == "nueche":
            if not hrAbs:
                hrAbs = 21
            used += 1
        # media hora, cuartu d'hora
        elif (word == "hora" and
              (wordPrev in time_indicators or wordPrevPrev in
               time_indicators)):
            if wordPrev == "media":
                minOffset = 30
            elif wordPrev == "cuartu":
                minOffset = 15
            elif wordPrevPrev == "cuartu":
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
        # 5:00 am, 12:00 pm, a les 8, etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
                # 17:30, 3:00 de la mañana
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
                    elif wordNext == "nueche":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif timeQualifier != "":
                        if int(strHH) <= 12 and \
                                timeQualifier in ["tarde", "nueche"]:
                            remainder = "pm"

            else:
                # númberos ensin dos puntos
                # a les 8 y media, en 5 minutos, etc
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
                # a les 8 y media, a les 8 y cuartu
                elif wordNext == "y" and wordNextNext in ["media", "cuartu"]:
                    strHH = strNum
                    strMM = 30 if wordNextNext == "media" else 15
                    used = 2
                    if wordNextNextNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "mañana":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "nueche":
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                # a les 8 menos cuartu
                elif wordNext == "menos" and wordNextNext == "cuartu":
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 45
                    used = 2
                    if wordNextNextNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "mañana":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "nueche":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                else:
                    if wordNext == "tarde":
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif wordNext == "mañana" or wordNext == "madrugada":
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif wordNext == "nueche":
                        strHH = strNum
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used = 1
                    elif (wordNext == "hora" and
                          word[0] != '0' and
                          strNum and int(strNum) < 100):
                        # en 3 hores
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minutu":
                        # en 10 minutos
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segundu":
                        # en 5 segundos
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif strNum and int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        if wordNext == "hora":
                            used += 1
                    elif wordNext == "" or (
                            wordNext == "en" and wordNextNext == "puntu"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "en" and wordNextNext == "puntu":
                            used += 2
                            if wordNextNextNext == "tarde":
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "mañana":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "nueche":
                                if 0 < int(strHH) < 6:
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
                                   strHH >= 12) else strHH
            if strHH > 24 or strMM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = strHH * 1
                minAbs = strMM * 1
                used += 1

        if used > 0:
            # desaniciar les pallabres analizaes de la frase
            for i in range(used):
                words[idx + i] = ""

            if wordPrev == "en" or wordPrev == "puntu":
                words[words.index(wordPrev)] = ""

            if idx > 0 and wordPrev in time_indicators:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in time_indicators:
                words[idx - 2] = ""

            idx += used - 1
            found = True

    # comprobar que s'atopó una data
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # manipulación de la data

    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
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

        if hasYear:
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                # impossible date for the given year (e.g. 29 of february
                # in a non-leap year) -> no date to extract
                return None
            extractedDate = extractedDate.replace(
                year=temp.year, month=temp.month, day=temp.day)
        else:
            # parse against a leap year so 29 of february never raises here,
            # then resolve the actual year below
            try:
                temp = datetime.strptime(datestr + " 2000", "%B %d %Y")
            except ValueError:
                # impossible date that exists in no year (e.g. 31 of
                # february) -> no date to extract
                return None
            month, day = temp.month, temp.day
            year = int(currentYear)
            # advance to the next year where this day exists and is in the
            # future relative to the anchor (skips non-leap years for feb 29)
            while True:
                try:
                    candidate = extractedDate.replace(
                        year=year, month=month, day=day)
                except ValueError:
                    year += 1
                    continue
                if extractedDate < candidate:
                    break
                year += 1
            extractedDate = candidate

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


def extract_duration_ast(text):
    """
    Convierte una frase n'asturianu nun númberu de segundos.
    Convierte coses como:
        "10 minutos"
        "3 díes 8 hores 10 minutos y 49 segundos"
    nun númberu enteru que representa'l total de segundos.
    Les pallabres emplegaes na duración serán consumíes,
    devolviéndose'l testu restante.
    Por exemplu, "pon un temporizador de 5 minutos" devolvería
    (300, "pon un temporizador de").

    Args:
        text (str): cadena de testu que contién una duración

    Returns:
        (timedelta, str):
            Una tupla col tiempu total y el testu restante
            non consumíu nel análisis. El primer valor sedrá
            None si nun s'atopa nenguna duración.
    """
    if not text:
        return None, text

    text = text.lower().replace("í", "i").replace("é", "e")

    time_units = {
        'microseconds': 0,
        'milliseconds': 0,
        'seconds': 0,
        'minutes': 0,
        'hours': 0,
        'days': 0,
        'weeks': 0
    }

    # n'asturianu el plural femenín ye -es (hora > hores, selmana > selmanes)
    # y díes ye'l plural de día, polo que cada unidá lleva'l so propiu patrón
    unit_patterns = {
        'microseconds': r"microsegundos?",
        'milliseconds': r"milisegundos?",
        'seconds': r"segundos?|segundu",
        'minutes': r"minutos?|minutu",
        'hours': r"hores|hora",
        'days': r"dies|dias?",
        'weeks': r"selmanes|selmana"
    }

    non_std_patterns = {
        "months": r"meses|mes",
        "years": r"años?|añu",
        "decades": r"decades|decada",
        "centuries": r"sieglos?|sieglu",
        "millenniums": r"milenios?|mileniu"
    }

    pattern = r"(?P<value>\d+(?:\.?\d+)?)(?:\s+|\-)(?:{unit})\b"

    for unit_en, unit_ast in unit_patterns.items():
        unit_pattern = pattern.format(unit=unit_ast)

        def repl(match):
            time_units[unit_en] += float(match.group("value"))
            return ''

        text = re.sub(unit_pattern, repl, text)

    for unit_en, unit_ast in non_std_patterns.items():
        unit_pattern = pattern.format(unit=unit_ast)

        def repl_non_std(match):
            val = float(match.group("value"))
            if unit_en == "months":
                val = 30 * val  # aproximación d'un mes en díes
            elif unit_en == "years":
                val = 365 * val  # aproximación d'un añu en díes
            elif unit_en == "decades":
                val = 10 * 365 * val
            elif unit_en == "centuries":
                val = 100 * 365 * val
            elif unit_en == "millenniums":
                val = 1000 * 365 * val
            time_units["days"] += val
            return ''

        text = re.sub(unit_pattern, repl_non_std, text)

    text = text.strip()
    duration = timedelta(**time_units) if any(time_units.values()) else None

    return duration, text
