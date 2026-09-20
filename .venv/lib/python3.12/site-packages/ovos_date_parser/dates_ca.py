import re
from datetime import datetime, timedelta
from enum import IntEnum

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_ca import pronounce_number_ca, numbers_to_digits_ca
from ovos_utils.time import now_local, DAYS_IN_1_YEAR, DAYS_IN_1_MONTH
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


class TimeVariantCA(IntEnum):
    DEFAULT = 0
    BELL = 1
    FULL_BELL = 2
    SPANISH_LIKE = 3


# Human-friendly aliases so callers can pick a time-telling register by name
# instead of importing the enum. Catalan has two well-known ways to tell time:
#   - the "standard"/central register: "les quatre i quart", "les quatre i
#     mitja", "les cinc menys quart" (mapped to SPANISH_LIKE)
#   - the traditional "quarts" register: quarters counted toward the *next*
#     hour, "un quart de cinc" (4:15), "dos quarts de cinc" (4:30), "tres
#     quarts de cinc" (4:45), with the finer "mig quart" / "un quart i mig"
#     refinements (mapped to BELL, or FULL_BELL for the exhaustive gradation)
_TIME_VARIANT_ALIASES_CA = {
    "default": TimeVariantCA.DEFAULT,
    "watch": TimeVariantCA.DEFAULT,
    "standard": TimeVariantCA.SPANISH_LIKE,
    "central": TimeVariantCA.SPANISH_LIKE,
    "spanish_like": TimeVariantCA.SPANISH_LIKE,
    "quarts": TimeVariantCA.BELL,
    "bell": TimeVariantCA.BELL,
    "quarts_full": TimeVariantCA.FULL_BELL,
    "full_bell": TimeVariantCA.FULL_BELL,
}


def _resolve_time_variant_ca(variant):
    """Resolve a variant given as an enum member, an enum name, or a
    human-friendly alias string into a ``TimeVariantCA``.

    Anything unrecognised (including ``None``) falls back to
    ``TimeVariantCA.DEFAULT`` so existing callers keep the current behaviour.
    """
    if isinstance(variant, TimeVariantCA):
        return variant
    if isinstance(variant, str):
        key = variant.strip().lower()
        if key in _TIME_VARIANT_ALIASES_CA:
            return _TIME_VARIANT_ALIASES_CA[key]
        # also accept the exact enum member name, e.g. "FULL_BELL"
        try:
            return TimeVariantCA[variant.strip().upper()]
        except KeyError:
            return TimeVariantCA.DEFAULT
    if isinstance(variant, int):
        try:
            return TimeVariantCA(variant)
        except ValueError:
            return TimeVariantCA.DEFAULT
    return TimeVariantCA.DEFAULT


def extract_duration_ca(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["ca"],
                                    resolution, replace_token)


def nice_time_ca(dt, speech=True, use_24hour=False, use_ampm=False,
                 variant=TimeVariantCA.DEFAULT):
    """
    Format a time to a comfortable human format
     For example, generate 'cinc trenta' for speech or '5:30' for
    text display.
     Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)=Fal
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
        variant (TimeVariantCA|str): time-telling register. Accepts a
            TimeVariantCA member or a friendly alias string. Notable aliases:
            "standard"/"central" (i quart / i mitja / menys quart),
            "quarts" (traditional quarters-toward-next-hour: "un quart de
            cinc"), "quarts_full" (fine-grained quarts gradation) and
            "default" (plain watch time). Unknown values fall back to the
            default watch-time register, preserving existing behaviour.
    Returns:
        (str): The formatted time string
    """
    variant = _resolve_time_variant_ca(variant)

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
    if variant == TimeVariantCA.BELL:
        # Bell Catalan Time System
        # https://en.wikipedia.org/wiki/Catalan_time_system

        if dt.minute < 7:
            next_hour = False
        elif dt.minute == 7 or dt.minute == 8:
            speak += "mig quart"
            next_hour = True
        elif dt.minute < 15:
            next_hour = False
        elif dt.minute == 15:
            speak += "un quart"
            next_hour = True
        elif dt.minute == 16:
            speak += "un quart i un minut"
            next_hour = True
        elif dt.minute < 21:
            speak += "un quart i " + pronounce_number_ca(
                dt.minute - 15) + " minuts"
            next_hour = True
        elif dt.minute == 22 or dt.minute == 23:
            speak += "un quart i mig"
            next_hour = True
        elif dt.minute < 30:
            speak += "un quart i " + pronounce_number_ca(
                dt.minute - 15) + " minuts"
            next_hour = True
        elif dt.minute == 30:
            speak += "dos quarts"
            next_hour = True
        elif dt.minute == 31:
            speak += "dos quarts i un minut"
            next_hour = True
        elif dt.minute < 37:
            speak += "dos quarts i " + pronounce_number_ca(
                dt.minute - 30) + " minuts"
            next_hour = True
        elif dt.minute == 37 or dt.minute == 38:
            speak += "dos quarts i mig"
            next_hour = True
        elif dt.minute < 45:
            speak += "dos quarts i " + pronounce_number_ca(
                dt.minute - 30) + " minuts"
            next_hour = True
        elif dt.minute == 45:
            speak += "tres quarts"
            next_hour = True
        elif dt.minute == 46:
            speak += "tres quarts i un minut"
            next_hour = True
        elif dt.minute < 52:
            speak += "tres quarts i " + pronounce_number_ca(
                dt.minute - 45) + " minuts"
            next_hour = True
        elif dt.minute == 52 or dt.minute == 53:
            speak += "tres quarts i mig"
            next_hour = True
        elif dt.minute > 53:
            speak += "tres quarts i " + pronounce_number_ca(
                dt.minute - 45) + " minuts"
            next_hour = True

        if next_hour == True:
            next_hour = (dt.hour + 1) % 12
            if next_hour == 0:
                speak += " de dotze"
                if dt.hour == 11:
                    speak += " del migdia"
                else:
                    speak += " de la nit"

            elif next_hour == 1:
                speak += " d'una"
                if dt.hour == 12:
                    speak += " de la tarda"
                else:
                    speak += " de la matinada"
            elif next_hour == 2:
                speak += " de dues"
                if dt.hour == 13:
                    speak += " de la tarda"
                else:
                    speak += " de la nit"

            elif next_hour == 11:
                speak += " d'onze"
                if dt.hour == 22:
                    speak += " de la nit"
                else:
                    speak += " del matí"
            else:
                speak += " de " + pronounce_number_ca(next_hour)
                if dt.hour == 0 and dt.hour < 5:
                    speak += " de la matinada"
                elif dt.hour >= 5 and dt.hour < 11:
                    speak += " del matí"
                elif dt.hour == 11:
                    speak += " del migdia"
                elif dt.hour >= 12 and dt.hour <= 17:
                    speak += " de la tarda"
                elif dt.hour >= 18 and dt.hour < 20:
                    speak += " del vespre"
                elif dt.hour >= 21 and dt.hour <= 23:
                    speak += " de la nit"


        else:
            hour = dt.hour % 12
            if hour == 0:
                speak += "les dotze"
            elif hour == 1:
                speak += "la una"
            elif hour == 2:
                speak += "les dues"
            else:
                speak += "les " + pronounce_number_ca(hour)

            if dt.minute == 0:
                speak += " en punt"
            elif dt.minute == 1:
                speak += " i un minut"
            else:
                speak += " i " + pronounce_number_ca(dt.minute) + " minuts"

            if dt.hour == 0:
                speak += " de la nit"
            elif dt.hour >= 1 and dt.hour < 6:
                speak += " de la matinada"
            elif dt.hour >= 6 and dt.hour < 11:
                speak += " del matí"
            elif dt.hour == 12:
                speak += " del migdia"
            elif dt.hour >= 13 and dt.hour < 19:
                speak += " de la tarda"
            elif dt.hour >= 19 and dt.hour < 21:
                speak += " del vespre"
            elif dt.hour >= 21 and dt.hour <= 23:
                speak += " de la nit"

    elif variant == TimeVariantCA.FULL_BELL:
        # Full Bell Catalan Time System
        # https://en.wikipedia.org/wiki/Catalan_time_system

        if dt.minute < 2:
            # en punt
            next_hour = False
        if dt.minute < 5:
            # tocades
            next_hour = False
        elif dt.minute < 7:
            # ben tocades
            next_hour = False
        elif dt.minute < 9:
            # mig quart
            speak += "mig quart"
            next_hour = True
        elif dt.minute < 12:
            # mig quart passat
            speak += "mig quart passat"
            next_hour = True
        elif dt.minute < 14:
            # mig quart passat
            speak += "mig quart ben passat"
            next_hour = True
        elif dt.minute < 17:
            speak += "un quart"
            next_hour = True
        elif dt.minute < 20:
            speak += "un quart tocat"
            next_hour = True
        elif dt.minute < 22:
            speak += "un quart ben tocat"
            next_hour = True
        elif dt.minute < 24:
            speak += "un quart i mig"
            next_hour = True
        elif dt.minute < 27:
            speak += "un quart i mig passat"
            next_hour = True
        elif dt.minute < 29:
            speak += "un quart i mig ben passat"
            next_hour = True
        elif dt.minute < 32:
            speak += "dos quarts"
            next_hour = True
        elif dt.minute < 35:
            speak += "dos quarts tocats"
            next_hour = True
        elif dt.minute < 37:
            speak += "dos quarts ben tocats"
            next_hour = True
        elif dt.minute < 39:
            speak += "dos quarts i mig"
            next_hour = True
        elif dt.minute < 42:
            speak += "dos quarts i mig passats"
            next_hour = True
        elif dt.minute < 44:
            speak += "dos quarts i mig ben passats"
            next_hour = True
        elif dt.minute < 47:
            speak += "tres quarts"
            next_hour = True
        elif dt.minute < 50:
            speak += "tres quarts tocats"
            next_hour = True
        elif dt.minute < 52:
            speak += "tres quarts ben tocats"
            next_hour = True
        elif dt.minute < 54:
            speak += "tres quarts i mig"
            next_hour = True
        elif dt.minute < 57:
            speak += "tres quarts i mig passats"
            next_hour = True
        elif dt.minute < 59:
            speak += "tres quarts i mig ben passats"
            next_hour = True
        elif dt.minute == 59:
            next_hour = False

        if next_hour == True:
            next_hour = (dt.hour + 1) % 12
            if next_hour == 0:
                speak += " de dotze"
                if dt.hour == 11:
                    speak += " del migdia"
                else:
                    speak += " de la nit"

            elif next_hour == 1:
                speak += " d'una"
                if dt.hour == 12:
                    speak += " de la tarda"
                else:
                    speak += " de la matinada"
            elif next_hour == 2:
                speak += " de dues"
                if dt.hour == 13:
                    speak += " de la tarda"
                else:
                    speak += " de la nit"

            elif next_hour == 11:
                speak += " d'onze"
                if dt.hour == 22:
                    speak += " de la nit"
                else:
                    speak += " del matí"
            else:
                speak += " de " + pronounce_number_ca(next_hour)
                if dt.hour == 0 and dt.hour < 5:
                    speak += " de la matinada"
                elif dt.hour >= 5 and dt.hour < 11:
                    speak += " del matí"
                elif dt.hour == 11:
                    speak += " del migdia"
                elif dt.hour >= 12 and dt.hour <= 17:
                    speak += " de la tarda"
                elif dt.hour >= 18 and dt.hour < 20:
                    speak += " del vespre"
                elif dt.hour >= 21 and dt.hour <= 23:
                    speak += " de la nit"

        else:
            hour = dt.hour % 12
            if dt.minute == 59:
                hour = (hour + 1) % 12
            if hour == 0:
                speak += "les dotze"
            elif hour == 1:
                speak += "la una"
            elif hour == 2:
                speak += "les dues"
            else:
                speak += "les " + pronounce_number_ca(hour)

            if dt.minute == 0:
                speak += " en punt"
            elif dt.minute > 1 and dt.minute < 5:
                if hour == 1:
                    speak += " tocada"
                else:
                    speak += " tocades"
            elif dt.minute < 7:
                if hour == 1:
                    speak += " ben tocada"
                else:
                    speak += " ben tocades"

            if dt.hour == 0:
                if hour == 1:
                    speak += " de la matinada"
                else:
                    speak += " de la nit"
            elif dt.hour < 6:
                if hour == 6:
                    speak += " del matí"
                else:
                    speak += " de la matinada"
            elif dt.hour < 12:
                if hour == 12:
                    speak += " del migdia"
                else:
                    speak += " del matí"
            elif dt.hour == 12:
                if hour == 1:
                    speak += " de la tarda"
                else:
                    speak += " del migdia"
            elif dt.hour < 19:
                if hour == 7:
                    speak += " del vespre"
                else:
                    speak += " de la tarda"
            elif dt.hour < 21:
                if hour == 9:
                    speak += " de la nit"
                else:
                    speak += " del vespre"
            elif dt.hour <= 23:
                speak += " de la nit"

    elif variant == TimeVariantCA.SPANISH_LIKE:
        # Prepare for "tres menys quart" ??
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
            speak += "les dotze"
        elif hour == 1 or hour == 13:
            speak += "la una"
        elif hour < 13:
            speak = "les " + pronounce_number_ca(hour)
        else:
            speak = "les " + pronounce_number_ca(hour - 12)

        if minute != 0:
            # les hores especials
            if minute == 15:
                speak += " i quart"
            elif minute == 30:
                speak += " i mitja"
            elif minute == -15:
                speak += " menys quart"
            else:  # sis i nou. set i veint-i-cinc
                if minute > 0:
                    speak += " i " + pronounce_number_ca(minute)
                else:  # si son las set menys vint, no posem la "i"
                    speak += " " + pronounce_number_ca(minute)

    # Default Watch Time Sytem
    else:
        if use_24hour:
            # simply speak the number
            if dt.hour == 1:
                speak += "la una"
            elif dt.hour == 2:
                speak += "les dues"
            elif dt.hour == 21:
                speak += "les vint-i-una"
            elif dt.hour == 22:
                speak += "les vint-i-dues"
            else:
                speak += "les " + pronounce_number_ca(dt.hour)

            if dt.minute > 0:
                speak += " i " + pronounce_number_ca(dt.minute)

        else:
            # speak number and add daytime identifier
            # (equivalent to "in the morning")
            if dt.hour == 0:
                speak += "les dotze"
            # 1 and 2 are pronounced in female form when talking about hours
            elif dt.hour == 1 or dt.hour == 13:
                speak += "la una"
            elif dt.hour == 2 or dt.hour == 14:
                speak += "les dues"
            elif dt.hour < 13:
                speak = "les " + pronounce_number_ca(dt.hour)
            else:
                speak = "les " + pronounce_number_ca(dt.hour - 12)

            # exact time
            if dt.minute == 0:
                # 3:00
                speak += " en punt"
            # else
            else:
                speak += " i " + pronounce_number_ca(dt.minute)

            # TODO: review day-periods
            if use_ampm:
                if dt.hour == 0:
                    speak += " de la nit"
                elif dt.hour >= 1 and dt.hour < 6:
                    speak += " de la matinada"
                elif dt.hour >= 6 and dt.hour < 12:
                    speak += " del matí"
                elif dt.hour == 12:
                    speak += " del migdia"
                elif dt.hour >= 13 and dt.hour <= 18:
                    speak += " de la tarda"
                elif dt.hour >= 19 and dt.hour < 21:
                    speak += " del vespre"
                elif dt.hour != 0 and dt.hour != 12:
                    speak += " de la nit"
    return speak


def extract_datetime_ca(text, anchorDate=None, default_time=None):
    def clean_string(s):
        # cleans the input string of unneeded punctuation and capitalization
        # among other things
        symbols = [".", ",", ";", "?", "!", "º", "ª"]
        hyphens = ["'", "_"]
        noise_words = ["el", "l", "els", "la", "les", "es", "sa", "ses",
                       "d", "de", "del", "dels"]
        # add final space
        s = s + " "

        s = s.lower()

        for word in symbols:
            s = s.replace(word, "")

        for word in hyphens:
            s = s.replace(word, " ")

        for word in noise_words:
            s = s.replace(" " + word + " ", " ")

        # handle synonims, plurals and equivalents, "demà ben d'hora" = "demà de matí"
        synonims = {"abans": ["abans-d"],
                    "vinent": ["que vé", "que ve", "que bé", "que be"],
                    "migdia": ["mig dia"],
                    "mitjanit": ["mitja nit"],
                    "matinada": ["matinades", "ben hora ben hora"],
                    "matí": ["matins", "dematí", "dematins", "ben hora"],
                    "tarda": ["tardes", "vesprada", "vesprades", "vespraes"],
                    "nit": ["nits", "vespre", "vespres", "horabaixa", "capvespre"],
                    "demà": ["endemà"],
                    "diàriament": ["diària", "diàries", "cada dia", "tots dies"],
                    "setmanalment": ["setmanal", "setmanals", "cada setmana", "totes setmanes"],
                    "quinzenalment": ["quinzenal", "quinzenals", "cada quinzena", "totes quinzenes"],
                    "mensualment": ["mensual", "mensuals", "cada mes", "tots mesos"],
                    "anualment": ["anual", "anuals", "cada any", "tots anys"],
                    "demàpassat": ["demà-passat", "demà passat", "passat demà", "despús-demà", "despús demà"],
                    "demàpassatpassat": ["demàpassat passat", "passat demàpassat",
                                         "demàpassat no altre", "demàpassat altre"],
                    "abansahir": ["abans ahir", "despús ahir", "despús-ahir"],
                    "abansabansahir": ["abans abansahir", "abansahir no altre", "abansahir altre",
                                       "abansahir no altre", "abansahir altre"],
                    "segon": ["segons"],
                    "minut": ["minuts"],
                    "quart": ["quarts"],
                    "hora": ["hores"],
                    "dia": ["dies"],
                    "setmana": ["setmanes"],
                    "quinzena": ["quinzenes"],
                    "mes": ["mesos"],
                    "any": ["anys"],
                    "tocat": ["tocats"],
                    "a": ["al", "als"]
                    }
        for syn in synonims:
            for word in synonims[syn]:
                s = s.replace(" " + word + " ", " " + syn + " ")

        # remove final space
        if s[-1] == " ":
            s = s[:-1]

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
    timeQualifiersList = ['matí', 'tarda', 'nit']
    time_indicators = ["em", "a", "a les", "cap a", "vora", "després", "estas",
                       "no", "dia", "hora"]
    days = ['dilluns', 'dimarts', 'dimecres',
            'dijous', 'divendres', 'dissabte', 'diumenge']
    months = ['gener', 'febrer', 'març', 'abril', 'maig', 'juny',
              'juliol', 'agost', 'setembre', 'octubre', 'novembre',
              'desembre']
    monthsShort = ['gen', 'feb', 'març', 'abr', 'maig', 'juny', 'jul', 'ag',
                   'set', 'oct', 'nov', 'des']
    nexts = ["pròxim", "pròxima", "vinent"]
    suffix_nexts = ["següent", "després"]
    lasts = ["últim", "última", "darrer", "darrera", "passat", "passada"]
    suffix_lasts = ["passada", "passat", "anterior", "abans"]
    nxts = ["passat", "després", "segueix", "seguit", "seguida", "següent", "pròxim", "pròxima"]
    prevs = ["abans", "prèvia", "previamente", "anterior"]
    froms = ["partir", "dins", "des", "a",
             "després", "pròxima", "pròxim", "del", "de"]
    thises = ["aquest", "aquesta", "aqueix", "aqueixa", "este", "esta"]
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
        elif word == "avui" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "demà" and not fromFlag:
            dayOffset += 1
            used += 1
        elif word == "ahir" and not fromFlag:
            dayOffset -= 1
            used += 1
        # "before yesterday" and "before before yesterday"
        elif (word == "abansahir") and not fromFlag:
            dayOffset -= 2
            used += 1
        elif word == "abansabansahir" and not fromFlag:
            dayOffset -= 3
            used += 1
        # day after tomorrow and after after tomorrow
        elif word == "demàpassat" and not fromFlag:
            dayOffset += 2
            used = 1
        elif word == "demàpassatpassat" and not fromFlag:
            dayOffset += 3
            used = 1
        # parse 5 days, 10 weeks, last week, next week, week after
        elif word == "dia":
            if wordNext == "després" or wordNext == "abans":
                used += 1
                if wordPrev and wordPrev[0].isdigit():
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 1
            elif (wordPrev and wordPrev[0].isdigit() and
                  wordNext not in months and
                  wordNext not in monthsShort):
                # "fa N dies" = N periods in the past (DIEC2/GDLC)
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
                # "fa N ..." = N periods in the past (DIEC2/GDLC)
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
                # "fa N ..." = N periods in the past (DIEC2/GDLC)
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
        elif word == "any" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "fa N ..." = N periods in the past (DIEC2/GDLC)
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
                # 13 maig
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
                # maig 13
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordPrevPrev and wordPrevPrev[0].isdigit():
                # 13 dia maig
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
                # maig dia 13
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
        validFollowups.append("avui")
        validFollowups.append("demà")
        validFollowups.append("ahir")
        validFollowups.append("abansahir")
        validFollowups.append("abansabansahir")
        validFollowups.append("demàpassat")
        validFollowups.append("ara")
        validFollowups.append("ja")
        validFollowups.append("abans")

        # TODO debug word "passat" that one is failing for some reason
        if word in froms and wordNext in validFollowups:

            if not (wordNext == "demà" and wordNext == "ahir") and not (
                    word == "passat" or word == "abans" or word == "em"):
                used = 2
                fromFlag = True
            if wordNext == "demà":
                dayOffset += 1
            elif wordNext == "ahir":
                dayOffset -= 1
            elif wordNext == "abansahir":
                dayOffset -= 2
            elif wordNext == "abansabansahir":
                dayOffset -= 3
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if wordNextNext == "dia":
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
                if wordNextNextNext == "dia":
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
        if word == "migdia":
            hrAbs = 12
            used += 1
        elif word == "mijanit":
            hrAbs = 0
            used += 1
        elif word == "matí":
            if not hrAbs:
                hrAbs = 8
            used += 1
        elif word == "tarda":
            if not hrAbs:
                hrAbs = 15
            used += 1
        elif word == "mitja" and wordNext == "tarda":
            if not hrAbs:
                hrAbs = 17
            used += 2
        elif word == "mig" and wordNext == "matí":
            if not hrAbs:
                hrAbs = 10
            used += 2
        elif word == "vespre" or (word == "final" and wordNext == "tarda"):
            if not hrAbs:
                hrAbs = 19
            used += 2
        elif word == "final" and wordNext == "matí":
            if not hrAbs:
                hrAbs = 11
            used += 2
        elif word == "matinada":
            if not hrAbs:
                hrAbs = 4
            used += 1
        elif word == "nit":
            if not hrAbs:
                hrAbs = 22
            used += 1
        # parse half an hour, quarter hour
        elif word == "hora" and \
                (wordPrev in time_indicators or wordPrevPrev in
                 time_indicators):
            if wordPrev == "mitja":
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
                    elif wordNext == "matí":
                        remainder = "am"
                        used += 1
                    elif (wordNext == "tarda" or wordNext == "vespre"):
                        remainder = "pm"
                        used += 1
                    elif wordNext == "nit":
                        if 0 < int(word[0]) < 6:
                            remainder = "am"
                        else:
                            remainder = "pm"
                        used += 1
                    elif wordNext in thises and wordNextNext == "matí":
                        remainder = "am"
                        used = 2
                    elif wordNext in thises and (wordNextNext == "tarda" or wordNextNext == "vespre"):
                        remainder = "pm"
                        used = 2
                    elif wordNext in thises and wordNextNext == "nit":
                        remainder = "pm"
                        used = 2
                    else:
                        if timeQualifier != "":
                            military = True
                            if strHH <= 12 and \
                                    (timeQualifier == "matí" or
                                     timeQualifier == "tarda"):
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
                            wordNext == "tarda" or
                            wordNext == "vespre"):
                        strHH = strNum
                        remainder = "pm"
                        used = 1
                    elif (wordNext == "am" or
                          wordNext == "a.m." or
                          wordNext == "matí"):
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

                    elif wordNext == "minut":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "segon":
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
                            wordNext == "en" and wordNextNext == "punt"):
                        strHH = strNum
                        strMM = 00
                        if wordNext == "en" and wordNextNext == "punt":
                            used += 2
                            if (wordNextNextNext == "tarda" or wordNextNextNext == "vespre"):
                                remainder = "pm"
                                used += 1
                            elif wordNextNextNext == "matí":
                                remainder = "am"
                                used += 1
                            elif wordNextNextNext == "nit":
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

            if wordPrev == "en" or wordPrev == "punt":
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
        # purely relative time ("d'aquí a dues hores") keeps the anchor time of day
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
            # impossible calendar date ("el 31 de febrer") -> not a valid date
            return None
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
    resultStr = _ca_pruning(resultStr)
    return [extractedDate, resultStr]


def _ca_pruning(text, symbols=True, accents=False, agressive=True):
    # agressive ca word pruning
    words = ["l", "la", "el", "els", "les", "de", "dels", "d", "aquí",
             "ell", "ells", "me", "és", "som", "al", "a", "dins", "per",
             "aquest", "aquesta", "això", "aixina", "en", "aquell", "aquella",
             "va", "vam", "vaig", "quin", "quina"]
    if symbols:
        symbols = [".", ",", ";", ":", "!", "?", "¡", "¿"]
        for symbol in symbols:
            text = text.replace(symbol, "")
        text = text.replace("'", " ").replace("_", " ")
    # accents=False
    if accents:
        accents = {"a": ["á", "à", "ã", "â"],
                   "e": ["ê", "è", "é"],
                   "i": ["í", "ï"],
                   "o": ["ò", "ó"],
                   "u": ["ú", "ü"],
                   "c": ["ç"],
                   "ll": ["l·l"],
                   "n": ["ñ"]}
        for char in accents:
            for acc in accents[char]:
                text = text.replace(acc, char)
    if agressive:
        text_words = text.split(" ")
        for idx, word in enumerate(text_words):
            if word in words:
                text_words[idx] = ""
        text = " ".join(text_words)
        text = ' '.join(text.split())
    return text
