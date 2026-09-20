"""Modern Greek (el) date and time formatting and extraction.

Gender and case scope
----------------------
Greek inflects a handful of low numerals for grammatical gender and marks
month names for case. This module commits to the following consistent
conventions and stays inside them:

* Spoken **clock hours** agree with the feminine noun ``ώρα`` ("hour"), so
  the hours 1/3/4 use their feminine forms ``μία``/``τρεις``/``τέσσερις``
  (and the feminine teens/twenties in 24-hour mode). The leading article
  (``η``/``οι``) is intentionally omitted — "τρεις και μισή" rather than
  "οι τρεις και μισή" — which is idiomatic and sidesteps article agreement.
* Spoken **minutes**, **day-of-month** and **years** use the neuter cardinal
  emitted by ``pronounce_number_el`` (``ένα``/``τρία``/``τέσσερα``), the
  citation counting form.
* Month names are rendered in the **genitive** inside date phrases ("5
  Ιουνίου"), the case Greek uses when a day precedes the month, and in the
  **nominative** by :func:`nice_month_el`.

Modern Greek clock-telling has a single colloquial standard (the hour
followed by ``και``/``παρά`` with ``μισή``/``τέταρτο`` or a minute count);
there is no second legitimate register comparable to the Catalan "quarts"
system, so :func:`nice_time_el` exposes no register parameter. The
extraction side accepts every verifiable spoken variant: numerals spelled
out in words (routed through the number parser), the gendered hour forms
μία/τρεις/τέσσερις, and the ``και``/``παρά`` + ``μισή``/``τέταρτο`` idioms.

Copyright: OpenVoiceOS
"""
import re
import unicodedata
from datetime import datetime

from dateutil.relativedelta import relativedelta
from ovos_number_parser import numbers_to_digits
from ovos_number_parser.numbers_el import pronounce_number_el
from ovos_utils.time import now_local

from ovos_date_parser.duration import (
    register_duration_lexicon, DurationLexicon, DurationResolution,
    DURATION_LEXICONS, extract_duration_generic
)

# 0=Monday .. 6=Sunday, matching datetime.weekday()
WEEKDAYS_EL = {
    0: "Δευτέρα",
    1: "Τρίτη",
    2: "Τετάρτη",
    3: "Πέμπτη",
    4: "Παρασκευή",
    5: "Σάββατο",
    6: "Κυριακή",
}

# nominative month names
MONTHS_EL = {
    1: "Ιανουάριος",
    2: "Φεβρουάριος",
    3: "Μάρτιος",
    4: "Απρίλιος",
    5: "Μάιος",
    6: "Ιούνιος",
    7: "Ιούλιος",
    8: "Αύγουστος",
    9: "Σεπτέμβριος",
    10: "Οκτώβριος",
    11: "Νοέμβριος",
    12: "Δεκέμβριος",
}

# genitive month names, used inside "<day> <month> <year>" phrases
MONTHS_GEN_EL = {
    1: "Ιανουαρίου",
    2: "Φεβρουαρίου",
    3: "Μαρτίου",
    4: "Απριλίου",
    5: "Μαΐου",
    6: "Ιουνίου",
    7: "Ιουλίου",
    8: "Αυγούστου",
    9: "Σεπτεμβρίου",
    10: "Οκτωβρίου",
    11: "Νοεμβρίου",
    12: "Δεκεμβρίου",
}

# feminine clock-hour forms (agree with "ώρα"); differ from the neuter
# cardinals only for 1, 3 and 4
_FEM_HOURS = {
    0: "δώδεκα", 1: "μία", 2: "δύο", 3: "τρεις", 4: "τέσσερις",
    5: "πέντε", 6: "έξι", 7: "επτά", 8: "οκτώ", 9: "εννέα",
    10: "δέκα", 11: "έντεκα", 12: "δώδεκα",
    13: "δεκατρείς", 14: "δεκατέσσερις", 15: "δεκαπέντε",
    16: "δεκαέξι", 17: "δεκαεπτά", 18: "δεκαοκτώ", 19: "δεκαεννέα",
    20: "είκοσι", 21: "είκοσι μία", 22: "είκοσι δύο", 23: "είκοσι τρεις",
}


def _fem_hour(hour):
    """Feminine spoken form of an hour value (0-23)."""
    return _FEM_HOURS.get(hour, pronounce_number_el(hour))


def _is_year_token(token):
    """True when ``token`` is a plausible calendar year (a 4-digit number).

    Guards the date parser against swallowing a following clock hour — e.g.
    the "3" in "15 Ιουνίου στις τρεις" — as if it were a year.
    """
    return bool(token) and token.isdigit() and len(token) == 4


def _fold_el(text):
    """Lowercase Greek text, drop diacritics and normalize final sigma."""
    text = text.lower().replace("ς", "σ")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed
                       if unicodedata.combining(c) == 0)
    return unicodedata.normalize("NFC", stripped)


def nice_year_el(dt, bc=False):
    """Format a year as a pronounceable string.

    For example, generates 'χίλια εννιακόσια ογδόντα τέσσερα' for 1984.

    Args:
        dt (datetime): date to format (assumed already in local timezone)
        bc (bool): append the "before Christ" marker
    Returns:
        (str): the formatted year
    """
    year = pronounce_number_el(dt.year)
    if bc:
        return f"{year} π.Χ."
    return year


def nice_weekday_el(dt):
    return WEEKDAYS_EL[dt.weekday()]


def nice_month_el(dt):
    return MONTHS_EL[dt.month]


def nice_day_el(dt, date_format='DMY', include_month=True):
    day = dt.strftime("%d").lstrip("0")
    if include_month:
        month = MONTHS_GEN_EL[dt.month]
        if date_format == 'MDY':
            return "{} {}".format(month, day)
        return "{} {}".format(day, month)
    return day


def nice_date_time_el(dt, now=None, use_24hour=False, use_ampm=False):
    """Format a date and time in a pronounceable way.

    For example, generates 'Τρίτη, πέντε Ιουνίου δύο χιλιάδες δεκαοκτώ στις
    πέντε και μισή'.

    Args:
        dt (datetime): date to format (assumed already in local timezone)
        now (datetime): reference date; when supplied the returned date is
            shortened (the year is dropped when it matches ``now``'s year,
            the month when it matches ``now``'s month, and same-day dates
            collapse to 'σήμερα').
        use_24hour (bool): output 24-hour format
        use_ampm (bool): include the part-of-day marker in 12-hour format
    Returns:
        (str): the formatted date and time
    """
    now = now or now_local()
    return (f"{nice_date_el(dt, now)} στις "
            f"{nice_time_el(dt, use_24hour=use_24hour, use_ampm=use_ampm)}")


def nice_date_el(dt, now=None, include_weekday=True):
    """Format a date in a pronounceable way.

    For example, generates 'Τρίτη, πέντε Ιουνίου δύο χιλιάδες δεκαοκτώ'.

    Args:
        dt (datetime): date to format (assumed already in local timezone)
        now (datetime): reference date; when supplied the returned date is
            shortened (the year is dropped when it matches ``now``'s year,
            the month when it matches ``now``'s month, and same-day dates
            collapse to 'σήμερα').
        include_weekday (bool): prepend the weekday name. Defaults to True.
    Returns:
        (str): the formatted date
    """
    day = pronounce_number_el(dt.day)
    if now is not None:
        nice = day
        if dt.day == now.day:
            return "σήμερα"
        if dt.day == now.day + 1:
            return "αύριο"
        if dt.day == now.day - 1:
            return "χθες"
        if dt.month != now.month:
            nice = nice + " " + MONTHS_GEN_EL[dt.month]
        if dt.year != now.year:
            nice = nice + " " + nice_year_el(dt)
    else:
        nice = f"{day} {MONTHS_GEN_EL[dt.month]} {nice_year_el(dt)}"

    if include_weekday:
        nice = f"{nice_weekday_el(dt)}, {nice}"
    return nice


def nice_time_el(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time in a human understandable way.

    For example, generates 'πέντε και μισή' for speech or '5:30' for a
    text display.

    Args:
        dt (datetime): date to format (assumed already in local timezone)
        speech (bool): format for speech (True) or display (False)
        use_24hour (bool): output 24-hour format
        use_ampm (bool): include the part-of-day marker in 12-hour format
    Returns:
        (str): the formatted time string
    """
    if use_24hour:
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            string = dt.strftime("%I:%M %p")
        else:
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # strip leading zero

    if not speech:
        return string

    speak = ""
    if use_24hour:
        speak += "μηδέν" if dt.hour == 0 else _fem_hour(dt.hour)
        if dt.minute < 10:
            speak += " και μηδέν " + pronounce_number_el(dt.minute)
        else:
            speak += " και " + pronounce_number_el(dt.minute)
        return speak

    # 12-hour spoken form
    if dt.minute >= 35:
        minute = dt.minute - 60
        hour = dt.hour + 1
    else:
        minute = dt.minute
        hour = dt.hour

    if hour == 0 or hour == 12 or hour == 24:
        speak += "δώδεκα"
    elif hour < 13:
        speak += _fem_hour(hour)
    else:
        speak += _fem_hour(hour - 12)

    if minute != 0:
        if minute == 15:
            speak += " και τέταρτο"
        elif minute == 30:
            speak += " και μισή"
        elif minute == -15:
            speak += " παρά τέταρτο"
        elif minute > 0:
            speak += " και " + pronounce_number_el(minute)
        else:
            speak += " παρά " + pronounce_number_el(-minute)
    elif not use_ampm:
        speak += " ακριβώς"

    if use_ampm:
        if 0 <= hour < 6:
            speak += " τα ξημερώματα"
        elif 6 <= hour < 12:
            speak += " το πρωί"
        elif 12 <= hour < 18:
            speak += " το απόγευμα"
        else:
            speak += " το βράδυ"
    return speak


def extract_datetime_el(text, anchorDate=None, default_time=None):
    """Extract date and time information from a Greek phrase.

    Args:
        text (str): text to interpret
        anchorDate (datetime): reference date for relative dates
        default_time (time): time to use when none is found in the text

    Returns:
        [datetime, str] | None: the extracted date and the remaining text,
        or None when no date or time is found.
    """

    def clean_string(s):
        symbols = [".", ",", ";", "?", "!", "·", "º", "ª"]
        for word in symbols:
            s = s.replace(word, "")
        s = _fold_el(s).replace("-", " ").replace("_", "")

        # "που ερχεται" (coming) == next
        s = s.replace(" που ερχεται", " επομενη")

        # spell out numerals -> digits so every spoken cardinal (including
        # the gendered forms μία/τρεις/τέσσερις and their neuter variants)
        # is handled in every position. The clock-fraction idioms "μισή"
        # (half) and "τέταρτο" (quarter) are cardinal-adjacent and would be
        # read as 0.5/0.25 by the number parser, so they are shielded and
        # restored afterwards.
        shields = {"μιση": "\x00h\x00", "μισι": "\x00h\x00",
                   "τεταρτο": "\x00q\x00"}
        for form, token in shields.items():
            s = re.sub(r"\b" + form + r"\b", token, s)
        s = numbers_to_digits(s, "el")
        s = s.replace("\x00h\x00", "μιση").replace("\x00q\x00", "τεταρτο")

        # nominative month forms -> genitive, so downstream matching is
        # single-cased
        nom_to_gen = {
            "ιανουαριοσ": "ιανουαριου", "φεβρουαριοσ": "φεβρουαριου",
            "μαρτιοσ": "μαρτιου", "απριλιοσ": "απριλιου",
            "μαιοσ": "μαιου", "ιουνιοσ": "ιουνιου", "ιουλιοσ": "ιουλιου",
            "αυγουστοσ": "αυγουστου", "σεπτεμβριοσ": "σεπτεμβριου",
            "οκτωβριοσ": "οκτωβριου", "νοεμβριοσ": "νοεμβριου",
            "δεκεμβριοσ": "δεκεμβριου",
        }
        for nom, gen in nom_to_gen.items():
            s = re.sub(r"\b" + nom + r"\b", gen, s)

        # collapse unit plurals/variants to a single stem
        unit_forms = {
            "δευτερολεπτο": ["δευτερολεπτα"],
            "λεπτο": ["λεπτα"],
            "ωρα": ["ωρεσ"],
            "μερα": ["μερεσ", "ημερα", "ημερεσ"],
            "εβδομαδα": ["εβδομαδεσ"],
            "μηνα": ["μηνεσ", "μηνασ"],
            "χρονο": ["χρονια", "χρονοσ", "ετοσ", "ετη"],
        }
        for stem, forms in unit_forms.items():
            for form in forms:
                s = re.sub(r"\b" + form + r"\b", stem, s)

        # noise words: articles and prepositions that carry no date value
        noise_words = ["στισ", "στη", "στην", "στον", "στο", "σε", "του",
                       "τησ", "των", "τον", "την", "το", "τα", "οι", "η",
                       "ο", "ενασ", "μια", "ενα", "καποια", "καποιο"]
        for word in noise_words:
            s = s.replace(" " + word + " ", " ")

        # "πριν από N" and "πριν N" are the same past idiom; fold the
        # optional από so the marker sits directly before the number
        s = re.sub(r"\bπριν απο\b", "πριν", s)
        return s

    def date_found():
        return found or (
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
    timeQualifiersList = ['πρωι', 'μεσημερι', 'απογευμα', 'βραδυ', 'νυχτα',
                          'ξημερωματα']
    time_indicators = ["σε", "και", "παρα", "μερα", "ωρα"]
    days = ['δευτερα', 'τριτη', 'τεταρτη', 'πεμπτη', 'παρασκευη',
            'σαββατο', 'κυριακη']
    months = ['ιανουαριου', 'φεβρουαριου', 'μαρτιου', 'απριλιου', 'μαιου',
              'ιουνιου', 'ιουλιου', 'αυγουστου', 'σεπτεμβριου', 'οκτωβριου',
              'νοεμβριου', 'δεκεμβριου']
    monthsShort = ['ιαν', 'φεβ', 'μαρ', 'απρ', 'μαι', 'ιουν', 'ιουλ', 'αυγ',
                   'σεπ', 'οκτ', 'νοε', 'δεκ']
    nexts = ["επομενη", "επομενο", "επομενοσ"]
    lasts = ["προηγουμενη", "προηγουμενο", "προηγουμενοσ",
             "περασμενη", "περασμενο", "περασμενοσ"]
    suffix_nexts = ["επομενη", "επομενο"]
    suffix_lasts = ["περασμενη", "περασμενο", "προηγουμενη", "προηγουμενο"]
    nxts = ["επομενη", "επομενο", "επομενοσ"]
    prevs = ["προηγουμενη", "προηγουμενο", "περασμενη", "περασμενο"]
    froms = ["σε", "μετα", "απο"]
    thises = ["αυτη", "αυτο", "αυτον", "αυτην"]
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
        if word in timeQualifiersList:
            timeQualifier = word
        # σημερα, αυριο, χθες, μεθαυριο, προχθες
        elif word == "σημερα" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "αυριο" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word in ("χθεσ", "χτεσ") and not fromFlag:
            dayOffset -= 1
            used += 1
        elif word in ("προχθεσ", "προχτεσ") and not fromFlag:
            dayOffset -= 2
            used += 1
        elif word == "μεθαυριο" and not fromFlag:
            dayOffset += 2
            used += 1
        # σε 5 μερες
        elif word == "μερα":
            if wordPrev and wordPrev[0].isdigit() and \
                    wordNext not in months and wordNext not in monthsShort:
                # "πριν (από) N ..." = N periods in the past (Τριανταφυλλίδης)
                if wordPrevPrev == "πριν":
                    dayOffset -= int(wordPrev)
                    start -= 2
                    used += 3
                else:
                    dayOffset += int(wordPrev)
                    start -= 1
                    used += 2
            elif wordNext and wordNext[0].isdigit() and \
                    wordNextNext not in months and \
                    wordNextNext not in monthsShort:
                dayOffset += int(wordNext)
                start -= 1
                used += 2
        elif word == "εβδομαδα" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "πριν (από) N ..." = N periods in the past (Τριανταφυλλίδης)
                if wordPrevPrev == "πριν":
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
        elif word == "μηνα" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "πριν (από) N ..." = N periods in the past (Τριανταφυλλίδης)
                if wordPrevPrev == "πριν":
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
        elif word == "χρονο" and not fromFlag:
            if wordPrev and wordPrev[0].isdigit():
                # "πριν (από) N ..." = N periods in the past (Τριανταφυλλίδης)
                if wordPrevPrev == "πριν":
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
        # weekdays
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
            elif wordPrev in lasts:
                dayOffset -= 7
                used += 1
                start -= 1
            if wordNext in suffix_nexts:
                used += 1
            elif wordNext in suffix_lasts:
                used += 1
        # 5 Ιουνίου, Ιούνιος 20
        elif word in months or word in monthsShort:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and wordPrev[0].isdigit():
                datestr += " " + wordPrev
                start -= 1
                used += 1
                # only a 4-digit token is a year; a following clock number
                # ("15 Ιουνίου στις τρεις") must stay for the time parser
                if _is_year_token(wordNext):
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False
            elif wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                if _is_year_token(wordNextNext):
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False
            if datestr in months:
                datestr = ""

        validFollowups = days + months + monthsShort
        validFollowups.append("σημερα")
        validFollowups.append("αυριο")
        validFollowups.append("χθεσ")
        validFollowups.append("χτεσ")
        validFollowups.append("προχθεσ")
        validFollowups.append("μεθαυριο")
        validFollowups.append("τωρα")

        if word in froms and wordNext in validFollowups:
            if word not in lasts:
                used = 2
                fromFlag = True
            if wordNext == "αυριο":
                dayOffset += 1
            elif wordNext in ("χθεσ", "χτεσ"):
                dayOffset -= 1
            elif wordNext in ("προχθεσ", "προχτεσ"):
                dayOffset -= 2
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if tmpOffset < 0:
                    tmpOffset += 7
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
        used = 0
        if word == "μεσημερι":
            if hrAbs is None:
                hrAbs = 12
            used += 1
        elif word == "μεσανυχτα" or (word == "μεσα" and wordNext == "νυχτα"):
            hrAbs = 0
            used += 2 if word == "μεσα" else 1
        elif word == "ξημερωματα":
            if hrAbs is None:
                hrAbs = 3
            used += 1
        elif word == "πρωι":
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word == "απογευμα":
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word == "βραδυ" or word == "νυχτα":
            if hrAbs is None:
                hrAbs = 21
            used += 1
        # μιση ωρα, τεταρτο τησ ωρας
        elif word == "ωρα" and (wordPrev in time_indicators or
                                wordPrevPrev in time_indicators):
            if wordPrev == "μιση":
                minOffset = 30
            elif wordPrev == "τεταρτο":
                minOffset = 15
            else:
                hrOffset = 1
            if wordPrevPrev in time_indicators:
                words[idx - 2] = ""
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
        elif word and word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            if ':' in word:
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
                    if nextWord in ("πμ", "μμ"):
                        remainder = "am" if nextWord == "πμ" else "pm"
                        used += 1
                    elif wordNext in ("πρωι", "ξημερωματα"):
                        remainder = "am"
                        used += 1
                    elif wordNext in ("απογευμα", "βραδυ"):
                        remainder = "pm"
                        used += 1
                    elif wordNext == "νυχτα":
                        remainder = "am" if 0 < int(strHH) < 6 else "pm"
                        used += 1
                    elif timeQualifier != "":
                        if int(strHH) <= 12 and \
                                timeQualifier in ["απογευμα", "βραδυ",
                                                  "νυχτα"]:
                            remainder = "pm"
            else:
                length = len(word)
                strNum = ""
                remainder = ""
                for i in range(length):
                    if word[i].isdigit():
                        strNum += word[i]
                    else:
                        remainder += word[i]
                if remainder == "":
                    remainder = wordNext.replace(".", "").strip()

                if remainder in ("πμ", "μμ"):
                    strHH = strNum
                    remainder = "am" if remainder == "πμ" else "pm"
                    used = 1
                # 8 και μιση, 8 και τεταρτο
                elif wordNext == "και" and wordNextNext in ("μιση",
                                                            "τεταρτο"):
                    strHH = strNum
                    strMM = 30 if wordNextNext == "μιση" else 15
                    used = 2
                    if wordNextNextNext in ("απογευμα", "βραδυ"):
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext in ("πρωι", "ξημερωματα"):
                        remainder = "am"
                        used += 1
                # 8 παρα τεταρτο
                elif wordNext == "παρα" and wordNextNext == "τεταρτο":
                    strHH = str(int(strNum) - 1 if int(strNum) > 0 else 23)
                    strMM = 45
                    used = 2
                    if wordNextNextNext in ("απογευμα", "βραδυ"):
                        remainder = "pm"
                        used += 1
                    elif wordNextNextNext in ("πρωι", "ξημερωματα"):
                        remainder = "am"
                        used += 1
                else:
                    if wordNext in ("απογευμα", "βραδυ", "μεσημερι"):
                        strHH = strNum
                        # noon: 12 stays 12; 1-11 read as afternoon (pm)
                        remainder = "pm"
                        used = 1
                    elif wordNext in ("πρωι", "ξημερωματα"):
                        strHH = strNum
                        remainder = "am"
                        used = 1
                    elif wordNext == "νυχτα":
                        strHH = strNum
                        remainder = "am" if 0 < int(strNum) < 6 else "pm"
                        used = 1
                    elif wordNext == "ωρα" and word[0] != '0' and \
                            strNum and int(strNum) < 100:
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "λεπτο":
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif wordNext == "δευτερολεπτο":
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                    elif strNum and int(strNum) > 100:
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        if wordNext == "ωρα":
                            used += 1
                    elif wordNext == "" or wordNext == "ακριβωσ":
                        strHH = strNum
                        strMM = 0
                        if wordNext == "ακριβωσ":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        strHH = strNum
                        strMM = wordNext
                        used += 1
                        if wordNextNext == "ωρα":
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
            for i in range(used):
                words[idx + i] = ""
            if idx > 0 and wordPrev in time_indicators:
                words[idx - 1] = ""
            if idx > 1 and wordPrevPrev in time_indicators:
                words[idx - 2] = ""
            idx += used - 1
            found = True

    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    extractedDate = dateNow
    extractedDate = extractedDate.replace(microsecond=0, second=0,
                                          minute=0, hour=0)
    if datestr != "":
        en_months = ['january', 'february', 'march', 'april', 'may', 'june',
                     'july', 'august', 'september', 'october', 'november',
                     'december']
        en_monthsShort = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july',
                          'aug', 'sept', 'oct', 'nov', 'dec']
        for i, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months[i]) + r"\b",
                             en_month, datestr)
        for i, en_month in enumerate(en_monthsShort):
            datestr = re.sub(r"\b" + re.escape(monthsShort[i]) + r"\b",
                             en_month, datestr)
        try:
            if hasYear:
                temp = datetime.strptime(datestr, "%B %d %Y")
            else:
                temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # an impossible calendar date like "30 φεβρουαριου"; report nothing
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
    # a bare "in N hours/minutes/seconds" is an offset from the anchor's
    # actual time of day, not from midnight
    if (hrOffset != 0 or minOffset != 0 or secOffset != 0) and \
            (hrAbs is None or hrAbs == -1) and \
            (minAbs is None or minAbs == -1):
        extractedDate = extractedDate + relativedelta(
            hours=dateNow.hour, minutes=dateNow.minute,
            seconds=dateNow.second)
    if hrOffset != 0:
        extractedDate = extractedDate + relativedelta(hours=hrOffset)
    if minOffset != 0:
        extractedDate = extractedDate + relativedelta(minutes=minOffset)
    if secOffset != 0:
        extractedDate = extractedDate + relativedelta(seconds=secOffset)

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


# Greek number words are normalized to digits with accents folded, so the
# unit fragments below are written accent-free. Nouns take their plural
# nominative/accusative forms after a numeral.
register_duration_lexicon(DurationLexicon(
    lang="el",
    normalize=lambda text: numbers_to_digits(_fold_el(text), "el"),
    units={
        "microseconds": r"μικροδευτερολεπτ[οα]",
        "milliseconds": r"μιλιδευτερολεπτ[οα]|χιλιοστοδευτερολεπτ[οα]",
        "seconds": r"δευτερολεπτ[οα]",
        "minutes": r"λεπτ[οα]",
        "hours": r"ωρ[αεσ]+",
        "days": r"(?:η?μερ[αεσ]+)",
        "weeks": r"εβδομαδ[αεσ]+",
        "months": r"μην[αεσ]+|μηνασ",
        "years": r"χρον(?:ια|οσ|ο)|ετ(?:οσ|η)",
        "decades": r"δεκαετι[αεσ]+",
        "centuries": r"αιων[αεσ]+",
        "millenniums": r"χιλιετι[αεσ]+",
    }))


def extract_duration_el(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """Convert a phrase into a duration and return the remainder text.

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
    return extract_duration_generic(text, DURATION_LEXICONS["el"],
                                    resolution, replace_token)
