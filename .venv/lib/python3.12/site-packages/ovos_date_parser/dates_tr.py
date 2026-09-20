# Copyright OpenVoiceOS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Turkish (``tr``) date and time tools.

Turkish reads clock times as "saat <hour> <minute>" (literally "hour
<h> <m>"), the form used in broadcast and announcement speech. The
idiomatic case-marked forms ("üçü on geçiyor" = "ten past three")
require the accusative/ablative declension of the numeral and are left
out rather than approximated.

Weekday and month names use standard orthography. Turkish nouns stay
singular after a numeral (iki saat = "two hour"), so the duration units
are the bare stems; "decade" is the phrase "on yıl" ("ten years"), not
a single word, and is omitted.
"""
import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser import pronounce_number, numbers_to_digits

from ovos_date_parser.duration import DurationLexicon, register_duration_lexicon

register_duration_lexicon(DurationLexicon(
    lang="tr",
    units={
        "microseconds": r"mikrosaniye",
        "milliseconds": r"milisaniye",
        "seconds": r"saniye",
        "minutes": r"dakika",
        "hours": r"saat",
        "days": r"gün",
        "weeks": r"hafta",
        "months": r"ay",
        "years": r"yıl|sene",
        "centuries": r"yüzyıl|asır",
        "millenniums": r"binyıl|milenyum",
    }))

WEEKDAYS_TR = {"pazartesi": 0, "salı": 1, "çarşamba": 2, "perşembe": 3,
               "cuma": 4, "cumartesi": 5, "pazar": 6}
MONTHS_TR = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5,
             "haziran": 6, "temmuz": 7, "ağustos": 8, "eylül": 9,
             "ekim": 10, "kasım": 11, "aralık": 12}

_RELATIVE_DAYS_TR = {"bugün": 0, "yarın": 1, "dün": -1, "öbür gün": 2,
                     "evvelki gün": -2, "önceki gün": -2}
_OFFSET_UNITS_TR = {"saniye": "seconds", "dakika": "minutes", "saat": "hours",
                    "gün": "days", "hafta": "weeks", "ay": "months",
                    "yıl": "years", "sene": "years"}
_PERIOD_NOUNS_TR = {"hafta": "week", "ay": "month", "yıl": "year",
                    "sene": "year"}
_NEXT_TR = {"gelecek", "önümüzdeki"}
_LAST_TR = {"geçen", "geçtiğimiz"}
_AGO_TR = {"önce"}
_FUTURE_TR = {"sonra"}
_CLOCK_PREFIX_TR = {"saat"}

_TIME_UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}


def _apply_offset(result, unit, value, backward):
    """Shift ``result`` by ``value`` of ``unit``; return (dt, is_time)."""
    sign = -1 if backward else 1
    if unit in _TIME_UNIT_SECONDS:
        return result + timedelta(
            seconds=sign * value * _TIME_UNIT_SECONDS[unit]), True
    if unit == "days":
        return result + timedelta(days=sign * value), False
    if unit == "weeks":
        return result + timedelta(weeks=sign * value), False
    if unit == "months":
        return result + relativedelta(months=sign * value), False
    return result + relativedelta(years=sign * value), False


def _weekday_delta(cur, target, backward):
    if backward:
        return -((cur - target) % 7 or 7)
    return (target - cur) % 7 or 7


def extract_datetime_tr(text, anchorDate=None, default_time=None):
    """Extract a datetime from Turkish text.

    Understands the relative day words (bugün, yarın, dün, öbür gün),
    weekday and month names with optional gelecek/geçen (next/last),
    "<n> <birim> önce/sonra" offsets and clock times ("saat 3", "15:30").
    Returns the resolved datetime and the leftover text, or ``None`` when
    nothing date/time related is found.
    """
    if not text:
        return None
    anchor = anchorDate or datetime.now()
    # Turkish dotted/dotless casing: I->ı and İ->i before lowercasing
    text = text.replace("İ", "i").replace("I", "ı").lower()
    # fold spelled numbers to digits; drop surrounding punctuation, a
    # number's apostrophe suffix (locative "saat 3'te") and the trailing
    # ".0" the number parser can leave on an integer fused with a stop
    tokens = [re.sub(r"^(\d+)\.0$", r"\1",
                     re.sub(r"(?<=\d)'\w*$", "", t.strip(".,!?;:")))
              for t in numbers_to_digits(text, "tr").split()]
    n = len(tokens)
    result = anchor
    consumed = set()
    date_found = False
    time_found = False

    def free(i):
        return 0 <= i < n and i not in consumed

    # 1. "<n> <unit> önce/sonra"
    for i in range(n):
        if not (free(i) and re.fullmatch(r"\d+", tokens[i]) and free(i + 1)):
            continue
        unit = _OFFSET_UNITS_TR.get(tokens[i + 1])
        if not unit:
            continue
        backward, dir_idx = None, None
        for j in (i + 2, i + 3):
            if free(j) and tokens[j] in _AGO_TR:
                backward, dir_idx = True, j
                break
            if free(j) and tokens[j] in _FUTURE_TR:
                backward, dir_idx = False, j
                break
        if backward is None:
            continue
        result, is_time = _apply_offset(result, unit, int(tokens[i]), backward)
        date_found = True
        time_found = time_found or is_time
        consumed.update({i, i + 1, dir_idx})

    # 2. next/last <weekday|period>
    for i in range(n):
        if i in consumed or tokens[i] not in (_NEXT_TR | _LAST_TR):
            continue
        backward = tokens[i] in _LAST_TR
        for j in (i + 1, i - 1):
            if not free(j):
                continue
            if tokens[j] in _PERIOD_NOUNS_TR:
                unit = {"week": "weeks", "month": "months",
                        "year": "years"}[_PERIOD_NOUNS_TR[tokens[j]]]
                result, _ = _apply_offset(result, unit, 1, backward)
                date_found = True
                consumed.update({i, j})
                break
            if tokens[j] in WEEKDAYS_TR:
                result += timedelta(days=_weekday_delta(
                    anchor.weekday(), WEEKDAYS_TR[tokens[j]], backward))
                date_found = True
                consumed.update({i, j})
                break

    # 3. relative day words (longest phrase first)
    for phrase in sorted(_RELATIVE_DAYS_TR, key=lambda p: -len(p.split())):
        parts = phrase.split()
        w = len(parts)
        for i in range(n - w + 1):
            if any((i + k) in consumed for k in range(w)):
                continue
            if tokens[i:i + w] == parts:
                result = anchor + timedelta(days=_RELATIVE_DAYS_TR[phrase])
                date_found = True
                consumed.update(range(i, i + w))

    # 4. bare weekday -> next occurrence
    for i in range(n):
        if free(i) and tokens[i] in WEEKDAYS_TR:
            result += timedelta(days=_weekday_delta(
                anchor.weekday(), WEEKDAYS_TR[tokens[i]], False))
            date_found = True
            consumed.add(i)

    # 5. month-name date: <day>? <month> <year>?
    for i in range(n):
        if i in consumed or tokens[i] not in MONTHS_TR:
            continue
        month = MONTHS_TR[tokens[i]]
        day = year = None
        for j in (i - 1, i + 1):
            if day is None and free(j) and re.fullmatch(r"\d{1,2}", tokens[j]) \
                    and 1 <= int(tokens[j]) <= 31:
                day = int(tokens[j])
                consumed.add(j)
        for j in (i + 1, i + 2):
            if free(j) and re.fullmatch(r"\d{4}", tokens[j]):
                year = int(tokens[j])
                consumed.add(j)
                break
        try:
            if year is None:
                year = anchor.year
                if datetime(year, month, day or 1).date() < anchor.date():
                    year += 1
            result = result.replace(year=year, month=month, day=day or 1)
        except ValueError:
            # an impossible calendar date like "30 februari"; report nothing
            # rather than a wrong guess
            return None
        date_found = True
        consumed.add(i)

    # 6. clock times: HH:MM, or "saat <hour>"
    for i in range(n):
        if i in consumed:
            continue
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", tokens[i])
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            result = result.replace(hour=int(m.group(1)),
                                    minute=int(m.group(2)), second=0,
                                    microsecond=0)
            time_found = True
            consumed.add(i)
            continue
        if tokens[i] in _CLOCK_PREFIX_TR and free(i + 1):
            hm = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", tokens[i + 1])
            if hm and int(hm.group(1)) < 24:
                minute = int(hm.group(2)) if hm.group(2) else 0
                if minute < 60:
                    result = result.replace(hour=int(hm.group(1)),
                                            minute=minute, second=0,
                                            microsecond=0)
                    time_found = True
                    consumed.update({i, i + 1})

    if not date_found and not time_found:
        return None
    if not time_found:
        if default_time:
            result = result.replace(hour=default_time.hour,
                                    minute=default_time.minute,
                                    second=default_time.second, microsecond=0)
        else:
            result = result.replace(hour=0, minute=0, second=0, microsecond=0)
    remainder = " ".join(t for idx, t in enumerate(tokens)
                         if idx not in consumed)
    return [result, remainder.strip()]


def _period_tr(hour):
    if hour < 6:
        return "gece"
    if hour < 12:
        return "sabah"
    if hour < 18:
        return "öğleden sonra"
    if hour < 22:
        return "akşam"
    return "gece"


def nice_time_tr(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time to a comfortable Turkish human format.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (True) or display (False)
        use_24hour (bool): output in 24-hour or 12-hour format
        use_ampm (bool): append the part of day for 12-hour format
    Returns:
        (str): The formatted time string
    """
    if use_24hour:
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            string = dt.strftime("%I:%M %p")
        else:
            string = dt.strftime("%I:%M")

    if not speech:
        return string

    if use_24hour:
        speak = "saat " + pronounce_number(dt.hour, lang="tr")
        if dt.minute:
            if dt.minute < 10:
                speak += " sıfır"
            speak += " " + pronounce_number(dt.minute, lang="tr")
        return speak

    if dt.hour == 0 and dt.minute == 0:
        return "gece yarısı"
    if dt.hour == 12 and dt.minute == 0:
        return "öğle"

    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    speak = "saat " + pronounce_number(hour, lang="tr")
    if dt.minute:
        if dt.minute < 10:
            speak += " sıfır"
        speak += " " + pronounce_number(dt.minute, lang="tr")
    if use_ampm:
        speak += " " + _period_tr(dt.hour)
    return speak
