import re
from datetime import datetime
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_gl import pronounce_number_gl
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

WEEKDAYS_GL = {
    0: "luns",
    1: "martes",
    2: "mércores",
    3: "xoves",
    4: "venres",
    5: "sábado",
    6: "domingo"
}
MONTHS_GL = {
    1: "xaneiro",
    2: "febreiro",
    3: "marzo",
    4: "abril",
    5: "maio",
    6: "xuño",
    7: "xullo",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "decembro"
}


def nice_year_gl(dt, bc=False):
    """
        Formatea un ano nunha forma pronunciable.

        Por exemplo, xera 'mil novecentos oitenta e catro' para o ano 1984.

        Args:
            dt (datetime): data a formatar (asúmise que xa está na zona horaria local)
            bc (bool): engade a.C. despois do ano (Python non soporta datas a.C. en datetime)
        Returns:
            (str): O ano formatado como cadea
    """
    year = pronounce_number_gl(dt.year)
    if bc:
        return f"{year} a.C."
    return year


def nice_weekday_gl(dt):
    weekday = WEEKDAYS_GL[dt.weekday()]
    return weekday.capitalize()


def nice_month_gl(dt):
    month = MONTHS_GL[dt.month]
    return month.capitalize()


def nice_day_gl(dt, date_format='DMY', include_month=True):
    if include_month:
        month = nice_month_gl(dt)
        if date_format == 'MDY':
            return "{} {}".format(month, dt.strftime("%d").lstrip("0"))
        else:
            return "{} {}".format(dt.strftime("%d").lstrip("0"), month)
    return dt.strftime("%d").lstrip("0")


def nice_date_time_gl(dt, now=None, use_24hour=False, use_ampm=False):
    """
        Formatea unha data e hora de maneira pronunciable.

        Por exemplo, xera 'martes, cinco de xuño de 2018 ás cinco e media'.

        Args:
            dt (datetime): data a formatar (asúmise que xa está na zona horaria local)
            now (datetime): Data actual. Se se proporciona, a data devolta acurtarase en consecuencia:
                Non se devolve o ano se now está no mesmo ano que `dt`, non se devolve o mes
                se now está no mesmo mes que `dt`. Se `now` e `dt` son o mesmo día, devélvese 'hoxe'.
            use_24hour (bool): saída en formato de 24 horas/militar ou 12 horas
            use_ampm (bool): incluír o am/pm en formato de 12 horas
        Returns:
            (str): A cadea de data e hora formatada
    """
    now = now or now_local()
    return f"{nice_date_gl(dt, now)} ás {nice_time_gl(dt, use_24hour=use_24hour, use_ampm=use_ampm)}"


def nice_date_gl(dt: datetime, now: datetime = None, include_weekday=True):
    """
    Formatea unha data nunha forma pronunciable.

    Por exemplo, xera 'martes, cinco de xuño de 2018'.

    Args:
        dt (datetime): data a formatar (asúmise que xa está na zona horaria local)
        now (datetime): Data actual. Se se proporciona, a data devolta acurtarase en consecuencia:
            Non se devolve o ano se now está no mesmo ano que `dt`, non se devolve o mes
            se now está no mesmo mes que `dt`. Se `now` e `dt` son o mesmo día, devélvese 'hoxe'.
        include_weekday (bool, optional): Whether to prepend the weekday name to the formatted date. Defaults to True.

    Returns:
        (str): A cadea de data formatada
    """
    day = pronounce_number_gl(dt.day)
    if now is not None:
        nice = day
        if dt.day == now.day:
            return "hoxe"
        if dt.day == now.day + 1:
            return "mañá"
        if dt.day == now.day - 1:
            return "onte"
        if dt.month != now.month:
            nice = nice + " de " + nice_month_gl(dt)
        if dt.year != now.year:
            nice = nice + ", " + nice_year_gl(dt)
    else:
        nice = f"{day} de {nice_month_gl(dt)}, {nice_year_gl(dt)}"

    if include_weekday:
        weekday = nice_weekday_gl(dt)
        nice = f"{weekday}, {nice}"
    return nice


def nice_time_gl(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Formatea unha hora nun formato humano comprensible

    Por exemplo, xera 'cinco e media' para fala ou '5:30' para visualización en texto.

    Args:
        dt (datetime): data a formatar (asume que xa está na zona horaria local)
        speech (bool): formato para fala (True, por defecto) ou para visualización en texto (False)
        use_24hour (bool): saída en formato de 24 horas/militar ou en formato de 12 horas
        use_ampm (bool): incluír am/pm para o formato de 12 horas
    Returns:
        (str): A cadea de texto coa hora formatada
    """
    if use_24hour:
        # ex.: "03:01" ou "14:22"
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            # ex.: "3:01 AM" ou "2:22 PM"
            string = dt.strftime("%I:%M %p")
        else:
            # ex.: "3:01" ou "2:22"
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # eliminar ceros á esquerda

    if not speech:
        return string

    # Xerar unha versión falada da hora
    speak = ""
    if use_24hour:
        if dt.hour == 1:
            speak += "a unha"
        else:
            speak += "as " + pronounce_number_gl(dt.hour)

        if dt.minute < 10:
            speak += " cero " + pronounce_number_gl(dt.minute)
        else:
            speak += " " + pronounce_number_gl(dt.minute)

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
            speak += "as doce"
        elif hour == 1 or hour == 13:
            speak += "a unha"
        elif hour < 13:
            speak = "as " + pronounce_number_gl(hour)
        else:
            speak = "as " + pronounce_number_gl(hour - 12)

        if minute != 0:
            if minute == 15:
                speak += " e cuarto"
            elif minute == 30:
                speak += " e media"
            elif minute == -15:
                speak += " menos cuarto"
            else:
                if minute > 0:
                    speak += " e " + pronounce_number_gl(minute)
                else:
                    speak += " " + pronounce_number_gl(minute)

        if minute == 0 and not use_ampm:
            speak += " en punto"

        if use_ampm:
            if hour >= 0 and hour < 6:
                speak += " da madrugada"
            elif hour >= 6 and hour < 13:
                speak += " da mañá"
            elif hour >= 13 and hour < 21:
                speak += " da tarde"
            else:
                speak += " da noite"
    return speak


def extract_datetime_gl(text, anchorDate=None, default_time=None):
    """
    Extrae información de data e hora dunha frase en galego.

    Args:
        text (str): texto a interpretar
        anchorDate (datetime): data de referencia para datas relativas
        default_time (time): hora a usar se non se atopa ningunha no texto

    Returns:
        [datetime, str] | None: a data extraída e o texto restante,
        ou None se non se atopa ningunha data ou hora.
    """

    def clean_string(s):
        # limpa o texto de puntuación e maiúsculas e normaliza vocabulario
        symbols = [".", ",", ";", "?", "!", "º", "ª"]

        for word in symbols:
            s = s.replace(word, "")

        s = s.lower().replace("á", "a").replace("é", "e").replace(
            "í", "i").replace("ó", "o").replace("ú", "u").replace(
            "-", " ").replace("_", "")

        # "que vén" == seguinte
        s = s.replace(" que ven", " seguinte")

        # horas faladas precedidas de artigo: "á unha", "ás dúas"
        spoken_hours = {"unha": "1", "duas": "2", "tres": "3", "catro": "4",
                        "cinco": "5", "seis": "6", "sete": "7", "oito": "8",
                        "nove": "9", "dez": "10", "once": "11", "doce": "12"}
        for k, v in spoken_hours.items():
            s = re.sub(r"\b(a|as) " + k + r"\b", r"\1 " + v, s)

        noise_words = ["entre", "a", "o", "do", "ao", "da", "na", "no",
                       "de", "para", "un", "unha", "calquera",
                       "este", "esta"]
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")

        # sinónimos e equivalentes
        synonyms = {"maña": ["amencer", "cedo", "moi cedo"],
                    "tarde": ["seran", "atardecer"],
                    "noite": ["anoitecer"]}
        for syn in synonyms:
            for word in synonyms[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")

        # plurais relevantes
        wordlist = ["mañas", "tardes", "noites", "dias", "semanas",
                    "anos", "minutos", "segundos", "seguintes",
                    "proximas", "proximos", "horas"]
        for word in wordlist:
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
    timeQualifiersList = ['maña', 'tarde', 'noite']
    time_indicators = ["en", "a", "as", "o", "os", "ao", "por", "pasados",
                       "pasadas", "dia", "hora"]
    days = ['luns', 'martes', 'mercores',
            'xoves', 'venres', 'sabado', 'domingo']
    months = ['xaneiro', 'febreiro', 'marzo', 'abril', 'maio', 'xuño',
              'xullo', 'agosto', 'setembro', 'outubro', 'novembro',
              'decembro']
    monthsShort = ['xan', 'feb', 'mar', 'abr', 'mai', 'xuñ', 'xul', 'ago',
                   'set', 'out', 'nov', 'dec']
    nexts = ["seguinte", "proximo", "proxima"]
    suffix_nexts = ["seguinte", "seguintes", "subsecuentes"]
    lasts = ["ultimo", "ultima"]
    suffix_lasts = ["pasada", "pasado", "anterior", "antes"]
    nxts = ["despois", "seguinte", "proximo", "proxima"]
    prevs = ["antes", "previa", "previo", "anterior"]
    froms = ["desde", "en", "para", "despois", "por", "proximo",
             "proxima", "de"]
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
        # gardar o cualificador de tempo para máis tarde
        if word in timeQualifiersList:
            timeQualifier = word

        # hoxe, mañá, onte
        elif word == "hoxe" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "maña" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "onte" and not fromFlag:
            dayOffset -= 1
            used += 1
        # antonte
        elif word == "antonte" and not fromFlag:
            dayOffset -= 2
            used += 1
        elif word == "ante" and wordNext == "onte" and not fromFlag:
            dayOffset -= 2
            used = 2
        # pasadomañá
        elif word == "pasadomaña" and not fromFlag:
            dayOffset += 2
            used += 1
        elif word == "pasado" and wordNext == "maña" and not fromFlag:
            dayOffset += 2
            used = 2
        # en 5 días, etc
        elif word == "dia":
            if wordNext == "pasado" or wordNext == "ante":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "hai N días" = N periods in the past (RAG/DRAG)
                if wordPrevPrev == "hai":
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

        elif word == "semana" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai N ..." = N periods in the past (RAG/DRAG)
                if wordPrevPrev == "hai":
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    dayOffset = -7
                    start -= 1
                    used = 2
        # 10 meses, mes seguinte, mes pasado
        elif word == "mes" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai N ..." = N periods in the past (RAG/DRAG)
                if wordPrevPrev == "hai":
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    monthOffset = -1
                    start -= 1
                    used = 2
        # 5 anos, ano seguinte, ano pasado
        elif word == "ano" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "hai N ..." = N periods in the past (RAG/DRAG)
                if wordPrevPrev == "hai":
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
                    start -= 1
                    used = 2
            for w in suffix_lasts:
                if wordNext == w:
                    yearOffset = -1
                    start -= 1
                    used = 2
        # días da semana: luns, martes...
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
            elif wordPrev == "pasado":
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext == "seguinte":
                used += 1
            elif wordNext == "pasado":
                used += 1
        # 3 de xuño, xuño 20, etc
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
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                # maio 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
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
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNextNext and wordNextNext[0].isdigit():
                # maio dia 13
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

        # 5 días desde mañá, 2 semanas desde o xoves, etc
        validFollowups = days + months + monthsShort
        validFollowups.append("hoxe")
        validFollowups.append("maña")
        validFollowups.append("onte")
        validFollowups.append("antonte")
        validFollowups.append("agora")
        validFollowups.append("xa")

        if word in froms and wordNext in validFollowups:

            if not (word == "pasado" or word == "antes"):
                used = 2
                fromFlag = True
            if wordNext == "maña" and word != "pasado":
                dayOffset += 1
            elif wordNext == "onte":
                dayOffset -= 1
            elif wordNext == "antonte":
                dayOffset -= 2
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

    # analizar a hora
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
        # mediodía, medianoite, mañá, tarde, noite
        used = 0
        if word == "mediodia" or (word == "medio" and wordNext == "dia"):
            hrAbs = 12
            used += 2 if word == "medio" else 1
        elif word == "medianoite" or (word == "media" and
                                      wordNext == "noite"):
            hrAbs = 0
            used += 2 if word == "media" else 1
        elif word == "media" and wordNext == "tarde":
            if not hrAbs:
                hrAbs = 17
            used += 2
        elif word == "media" and wordNext == "maña":
            if not hrAbs:
                hrAbs = 10
            used += 2
        elif word == "maña":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tarde" and wordNext == "noite":
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
        elif word == "noite":
            if not hrAbs:
                hrAbs = 21
            used += 1
        # media hora, cuarto de hora
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
        # 5:00 am, 12:00 pm, ás 8, etc
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
                # 17:30, 3:00 da maña
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
                    elif wordNext == "maña" or wordNext == "madrugada":
                        remainder = "am"
                        used += 1
                    elif wordNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNext == "noite":
                        if 0 < int(strHH) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif timeQualifier != "":
                        if int(strHH) <= 12 and \
                                timeQualifier in ["tarde", "noite"]:
                            remainder = "pm"

            else:
                # números sen dous puntos
                # ás 8 e media, en 5 minutos, etc
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
                # ás 8 e media, ás 8 e cuarto
                elif wordNext == "e" and wordNextNext in ["media", "cuarto"]:
                    strHH = strNum
                    strMM = 30 if wordNextNext == "media" else 15
                    used = 2
                    if wordNextNextNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "maña":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "noite":
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                # ás 8 menos cuarto
                elif wordNext == "menos" and wordNextNext == "cuarto":
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 45
                    used = 2
                    if wordNextNextNext == "tarde":
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext == "maña":
                        remainder = "am"
                        used += 1
                    elif wordNextNextNext == "noite":
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
                    elif wordNext == "maña" or wordNext == "madrugada":
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif wordNext == "noite":
                        strHH = strNum
                        if 0 < int(strNum) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used = 1
                    elif (wordNext == "hora" and
                          word[0] != '0' and strNum and
                          int(strNum) < 100):
                        # en 3 horas
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "minuto":
                        # en 10 minutos
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segundo":
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
                            wordNext == "en" and wordNextNext == "punto"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "en" and wordNextNext == "punto":
                            used += 2
                            if wordNextNextNext == "tarde":
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "maña":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "noite":
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
            # eliminar as palabras analizadas da frase
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

    # comprobar que se atopou unha data
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # manipulación da data

    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # purely relative time ("dentro de dúas horas") keeps the anchor time of day
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
            # an impossible calendar date like "30 de febreiro"; report nothing
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
    return [extractedDate, resultStr]


def extract_duration_gl(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["gl"],
                                    resolution, replace_token)
