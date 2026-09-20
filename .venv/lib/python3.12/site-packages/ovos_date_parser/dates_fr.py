import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_fr import _number_ordinal_fr, pronounce_number_fr, _get_ordinal_fr, \
    _number_parse_fr
from ovos_utils.time import now_local, DAYS_IN_1_MONTH, DAYS_IN_1_YEAR
from ovos_number_parser import numbers_to_digits
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

_ARTICLES_FR = ["le", "la", "du", "de", "les", "des"]


def nice_time_fr(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format

    For example, generate 'cinq heures trente' for speech or '5:30' for
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

        # "13 heures trente"
        if dt.hour == 0:
            speak += "minuit"
        elif dt.hour == 12:
            speak += "midi"
        elif dt.hour == 1:
            speak += "une heure"
        else:
            speak += pronounce_number_fr(dt.hour) + " heures"

        if dt.minute != 0:
            speak += " " + pronounce_number_fr(dt.minute)

    else:
        # Prepare for "trois heures moins le quart"
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
            speak += "minuit"
        elif hour == 12:
            speak += "midi"
        elif hour == 1 or hour == 13:
            speak += "une heure"
        elif hour < 13:
            speak = pronounce_number_fr(hour) + " heures"
        else:
            speak = pronounce_number_fr(hour - 12) + " heures"

        if minute != 0:
            if minute == 15:
                speak += " et quart"
            elif minute == 30:
                speak += " et demi"
            elif minute == -15:
                speak += " moins le quart"
            else:
                speak += " " + pronounce_number_fr(minute)

        if use_ampm:
            if hour > 17:
                speak += " du soir"
            elif hour > 12:
                speak += " de l'après-midi"
            elif hour > 0 and hour < 12:
                speak += " du matin"

    return speak


def extract_datetime_fr(text, anchorDate=None, default_time=None):
    def clean_string(s):
        """
            cleans the input string of unneeded punctuation and capitalization
            among other things.
        """
        s = normalize_fr(s, True)
        wordList = s.split()
        for idx, word in enumerate(wordList):
            # remove comma and dot if it's not a number
            if word[-1] in [",", "."]:
                word = word[:-1]
            wordList[idx] = word

        return wordList

    def date_found():
        return found or \
            (
                    datestr != "" or
                    yearOffset != 0 or monthOffset != 0 or dayOffset or
                    (isTime and (hrAbs or minAbs)) or
                    hrOffset != 0 or minOffset != 0 or secOffset != 0
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

    timeQualifiersList = ["matin", "après-midi", "soir", "nuit"]
    words_in = ["dans", "après"]
    markers = ["à", "dès", "autour", "vers", "environs", "ce",
               "cette"] + words_in
    days = ["lundi", "mardi", "mercredi",
            "jeudi", "vendredi", "samedi", "dimanche"]
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre",
              "décembre"]
    monthsShort = ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "aoû",
                   "sept", "oct", "nov", "déc"]
    # needed for format functions
    months_en = ['january', 'february', 'march', 'april', 'may', 'june',
                 'july', 'august', 'september', 'october', 'november',
                 'december']

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrevPrev = words[idx - 3] if idx > 2 else ""
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        start = idx
        used = 0
        # save timequalifier for later
        if word in timeQualifiersList:
            timeQualifier = word
            used = 1
            if wordPrev in ["ce", "cet", "cette"]:
                used = 2
                start -= 1
        # parse avant-hier, hier, aujourd'hui, demain, après-demain
        # "hier": jour qui précède immédiatement celui où l'on est
        # (Larousse, papers/linguistics/french/larousse_hier.html)
        elif word == "avant-hier" and not fromFlag:
            dayOffset = -2
            used += 1
        elif word == "hier" and not fromFlag:
            dayOffset = -1
            used += 1
        elif word == "aujourd'hui" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "demain" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "après-demain" and not fromFlag:
            dayOffset = 2
            used += 1
        # parse 5 jours, 10 semaines, semaine dernière, semaine prochaine
        elif word in ["jour", "jours"]:
            if wordPrev.isdigit():
                # "il y a N ..." = N periods in the past (Larousse)
                if wordPrevPrev == "a" and wordPrevPrevPrev == "y":
                    dayOffset -= int(wordPrev)
                    start -= 4
                    used = 5
                else:
                    dayOffset += int(wordPrev)
                    start -= 1
                    used = 2
            # "3e jour"
            elif _get_ordinal_fr(wordPrev) is not None:
                dayOffset += _get_ordinal_fr(wordPrev) - 1
                start -= 1
                used = 2
        elif word in ["semaine", "semaines"] and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "il y a N ..." = N periods in the past (Larousse)
                if wordPrevPrev == "a" and wordPrevPrevPrev == "y":
                    dayOffset -= int(wordPrev) * 7
                    start -= 4
                    used = 5
                else:
                    dayOffset += int(wordPrev) * 7
                    start -= 1
                    used = 2
            elif wordNext in ["prochaine", "suivante"]:
                dayOffset = 7
                used = 2
            elif wordNext in ["dernière", "précédente"]:
                dayOffset = -7
                used = 2
        # parse 10 mois, mois prochain, mois dernier
        elif word == "mois" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "il y a N ..." = N periods in the past (Larousse)
                if wordPrevPrev == "a" and wordPrevPrevPrev == "y":
                    monthOffset = -int(wordPrev)
                    start -= 4
                    used = 5
                else:
                    monthOffset = int(wordPrev)
                    start -= 1
                    used = 2
            elif wordNext in ["prochain", "suivant"]:
                monthOffset = 1
                used = 2
            elif wordNext in ["dernier", "précédent"]:
                monthOffset = -1
                used = 2
        # parse 5 ans, an prochain, année dernière
        elif word in ["an", "ans", "année", "années"] and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "il y a N ..." = N periods in the past (Larousse)
                if wordPrevPrev == "a" and wordPrevPrevPrev == "y":
                    yearOffset = -int(wordPrev)
                    start -= 4
                    used = 5
                else:
                    yearOffset = int(wordPrev)
                    start -= 1
                    used = 2
            elif wordNext in ["prochain", "prochaine", "suivant", "suivante"]:
                yearOffset = 1
                used = 2
            elif wordNext in ["dernier", "dernière", "précédent",
                              "précédente"]:
                yearOffset = -1
                used = 2
        # parse lundi, mardi etc., and lundi prochain, mardi dernier, etc.
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordNext in ["prochain", "suivant"]:
                dayOffset += 7
                used += 1
            elif wordNext in ["dernier", "précédent"]:
                dayOffset -= 7
                used += 1
        # parse 15 juillet, 15 juil
        elif word in months or word in monthsShort and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months_en[m]
            if wordPrev and (wordPrev and wordPrev[0].isdigit()):
                # keep only the leading digits so ordinals like "1er"
                # ("1er janvier") do not leak letters into strptime
                datestr += " " + re.match(r"\d+", wordPrev).group()
                start -= 1
                used += 1
            else:
                datestr += " 1"
            if wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                hasYear = True
            else:
                hasYear = False
        # parse 5 jours après demain, 10 semaines après jeudi prochain,
        # 2 mois après juillet
        validFollowups = days + months + monthsShort
        validFollowups.append("aujourd'hui")
        validFollowups.append("demain")
        validFollowups.append("prochain")
        validFollowups.append("prochaine")
        validFollowups.append("suivant")
        validFollowups.append("suivante")
        validFollowups.append("dernier")
        validFollowups.append("dernière")
        validFollowups.append("précédent")
        validFollowups.append("précédente")
        validFollowups.append("maintenant")
        if word in ["après", "depuis"] and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "demain":
                dayOffset += 1
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if wordNextNext == "prochain":
                    tmpOffset += 7
                    used += 1
                elif wordNextNext == "dernier":
                    tmpOffset -= 7
                    used += 1
                elif tmpOffset < 0:
                    tmpOffset += 7
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] in ["ce", "cette"]:
                start -= 1
                used += 1

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
    ampm = ""
    isTime = False

    for idx, word in enumerate(words):
        if word == "":
            continue

        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        used = 0
        start = idx

        # parse midi et quart, minuit et demi, midi 10, minuit moins 20
        if word in ["midi", "minuit"]:
            isTime = True
            if word == "midi":
                hrAbs = 12
                used += 1
            elif word == "minuit":
                hrAbs = 0
                used += 1
            if wordNext.isdigit():
                minAbs = int(wordNext)
                used += 1
            elif wordNext == "et":
                if wordNextNext == "quart":
                    minAbs = 15
                    used += 2
                elif wordNextNext in ["demi", "demie"]:
                    minAbs = 30
                    used += 2
            elif wordNext == "moins":
                if wordNextNext.isdigit():
                    minAbs = 60 - int(wordNextNext)
                    if not hrAbs:
                        hrAbs = 23
                    else:
                        hrAbs -= 1
                    used += 2
                if wordNextNext == "quart":
                    minAbs = 45
                    if not hrAbs:
                        hrAbs = 23
                    else:
                        hrAbs -= 1
                    used += 2
        # parse une demi-heure, un quart d'heure
        elif word == "demi-heure" or word == "heure" and \
                (wordPrevPrev in markers or wordPrevPrevPrev in markers):
            used = 1
            isTime = True
            if word == "demi-heure":
                minOffset = 30
            elif wordPrev == "quart":
                minOffset = 15
                used += 1
                start -= 1
            elif wordPrev == "quarts" and wordPrevPrev.isdigit():
                minOffset = int(wordPrevPrev) * 15
                used += 1
                start -= 1
            if wordPrev.isdigit() or wordPrevPrev.isdigit():
                start -= 1
                used += 1
        # parse 5:00 du matin, 12:00, etc
        elif word and word[0].isdigit() and _get_ordinal_fr(word) is None:
            isTime = True
            if ":" in word or "h" in word or "min" in word:
                # parse hours on short format
                # "3:00 du matin", "4h14", "3h15min"
                strHH = ""
                strMM = ""
                stage = 0
                length = len(word)
                for i in range(length):
                    if stage == 0:
                        if word[i].isdigit():
                            strHH += word[i]
                            used = 1
                        elif word[i] in [":", "h", "m"]:
                            stage = 1
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 1:
                        if word[i].isdigit():
                            strMM += word[i]
                            used = 1
                        else:
                            stage = 2
                            if word[i:i + 3] == "min":
                                i += 1
                    elif stage == 2:
                        break
                if wordPrev in words_in:
                    hrOffset = int(strHH) if strHH else 0
                    minOffset = int(strMM) if strMM else 0
                else:
                    hrAbs = int(strHH) if strHH else 0
                    minAbs = int(strMM) if strMM else 0
            else:
                # try to parse time without colons
                # 5 hours, 10 minutes etc.
                length = len(word)
                ampm = ""
                if (
                        word.isdigit() and
                        wordNext in ["heures", "heure"] and word != "0" and
                        (
                                int(word) < 100 or
                                int(word) > 2400
                        )):
                    # "dans 3 heures", "à 3 heures"
                    if wordPrev in words_in:
                        hrOffset = int(word)
                    else:
                        hrAbs = int(word)
                    used = 2
                    idxHr = idx + 2
                    # "dans 1 heure 40", "à 1 heure 40"
                    if idxHr < len(words):
                        # "3 heures 45"
                        if words[idxHr].isdigit():
                            if wordPrev in words_in:
                                minOffset = int(words[idxHr])
                            else:
                                minAbs = int(words[idxHr])
                            used += 1
                            idxHr += 1
                        # "3 heures et quart", "4 heures et demi"
                        elif words[idxHr] == "et" and idxHr + 1 < len(words):
                            if words[idxHr + 1] == "quart":
                                if wordPrev in words_in:
                                    minOffset = 15
                                else:
                                    minAbs = 15
                                used += 2
                                idxHr += 2
                            elif words[idxHr + 1] in ["demi", "demie"]:
                                if wordPrev in words_in:
                                    minOffset = 30
                                else:
                                    minAbs = 30
                                used += 2
                                idxHr += 2
                        # "5 heures moins 20", "6 heures moins le quart"
                        elif words[idxHr] == "moins" and \
                                idxHr + 1 < len(words):
                            if words[idxHr + 1].isdigit():
                                if wordPrev in words_in:
                                    hrOffset -= 1
                                    minOffset = 60 - int(words[idxHr + 1])
                                else:
                                    hrAbs = hrAbs - 1
                                    minAbs = 60 - int(words[idxHr + 1])
                                used += 2
                                idxHr += 2
                            elif words[idxHr + 1] == "quart":
                                if wordPrev in words_in:
                                    hrOffset -= 1
                                    minOffset = 45
                                else:
                                    hrAbs = hrAbs - 1
                                    minAbs = 45
                                used += 2
                                idxHr += 2
                        # remove word minutes if present
                        if idxHr < len(words) and \
                                words[idxHr] in ["minutes", "minute"]:
                            used += 1
                            idxHr += 1
                elif word.isdigit() and wordNext == "minutes":
                    # "dans 10 minutes"
                    if wordPrev in words_in:
                        minOffset = int(word)
                    else:
                        minAbs = int(word)
                    used = 2
                elif word.isdigit() and wordNext == "secondes":
                    # "dans 5 secondes"
                    secOffset = int(word)
                    used = 2
                elif word.isdigit() and int(word) > 100:
                    # format militaire
                    hrAbs = int(word) / 100
                    minAbs = int(word) - hrAbs * 100
                    used = 1
                    if wordNext == "heures":
                        used += 1

            # handle am/pm
            if timeQualifier:
                if timeQualifier == "matin":
                    ampm = "am"
                elif timeQualifier == "après-midi":
                    ampm = "pm"
                elif timeQualifier == "soir":
                    ampm = "pm"
                elif timeQualifier == "nuit":
                    if (hrAbs or 0) > 8:
                        ampm = "pm"
                    else:
                        ampm = "am"
            hrAbs = ((hrAbs or 0) + 12 if ampm == "pm" and (hrAbs or 0) < 12
                     else hrAbs)
            hrAbs = ((hrAbs or 0) - 12 if ampm == "am" and (hrAbs or 0) >= 12
                     else hrAbs)
            if (hrAbs or 0) > 24 or ((minAbs or 0) > 59):
                isTime = False
                used = 0
            elif wordPrev in words_in:
                isTime = False
            else:
                isTime = True

        elif not hrAbs and timeQualifier:
            if timeQualifier == "matin":
                hrAbs = 8
            elif timeQualifier == "après-midi":
                hrAbs = 15
            elif timeQualifier == "soir":
                hrAbs = 19
            elif timeQualifier == "nuit":
                hrAbs = 2
            isTime = True

        if used > 0:
            # removed parsed words from the sentence
            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ""

            idx += used - 1
            found = True

    # a bare part-of-day qualifier ("cet après-midi", "ce soir") is consumed
    # while scanning for dates, so apply its default hour once no explicit
    # time was given
    if hrAbs is None and minAbs is None and timeQualifier and \
            not (hrOffset or minOffset or secOffset):
        if timeQualifier == "matin":
            hrAbs = 8
        elif timeQualifier == "après-midi":
            hrAbs = 15
        elif timeQualifier == "soir":
            hrAbs = 19
        elif timeQualifier == "nuit":
            hrAbs = 2

    # check that we found a date
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation
    extractedDate = dateNow
    if hrOffset != 0 or minOffset != 0 or secOffset != 0:
        # purely relative time ("dans deux heures") keeps the anchor time of day
        extractedDate = extractedDate.replace(microsecond=0, second=0)
    else:
        extractedDate = extractedDate.replace(microsecond=0,
                                              second=0,
                                              minute=0,
                                              hour=0)
    if datestr != "":
        try:
            temp = datetime.strptime(datestr,
                                     "%B %d %Y" if hasYear else "%B %d")
        except ValueError:
            # an impossible calendar date like "30 février"; report nothing
            # rather than a wrong guess
            return None
        if not hasYear:
            if extractedDate.tzinfo:
                temp = temp.replace(tzinfo=extractedDate.tzinfo)
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
    for idx, word in enumerate(words):
        if word == "et" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def normalize_fr(text, remove_articles=True):
    """ French string normalization """
    text = text.lower()
    words = text.split()  # this also removed extra spaces
    normalized = ""
    i = 0
    while i < len(words):
        # remove articles
        if remove_articles and words[i] in _ARTICLES_FR:
            i += 1
            continue
        if remove_articles and words[i][:2] in ["l'", "d'"]:
            words[i] = words[i][2:]
        # remove useless punctuation signs
        if words[i] in ["?", "!", ";", "…"]:
            i += 1
            continue
        # Normalize ordinal numbers
        if i > 0 and words[i - 1] in _ARTICLES_FR:
            result = _number_ordinal_fr(words, i)
            if result is not None:
                val, i = result
                normalized += " " + str(val)
                continue
        # Convert numbers into digits
        result = _number_parse_fr(words, i)
        if result is not None:
            val, i = result
            normalized += " " + str(val)
            continue

        normalized += " " + words[i]
        i += 1

    return normalized[1:]  # strip the initial space


def extract_duration_fr(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["fr"],
                                    resolution, replace_token)
