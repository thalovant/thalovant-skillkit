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
"""Malay (``ms``) date and time tools.

Malay names a clock time as "pukul <hour>" and adds minutes with
"lebih" (more/past): "pukul tiga lebih lima belas" = "quarter past
three". This mirrors Indonesian but uses the Malay connector "lebih"
rather than Indonesian "lewat". The half-to idiom ("pukul setengah
empat") shifts the named hour and is left out to keep the reading
unambiguous.

Malay shares most numerals with Indonesian but the time units differ:
"second" is saat (Indonesian detik) and "minute" is minit (Indonesian
menit). Weekday names (Isnin, Khamis, Jumaat, Ahad) and several months
(Mac, Ogos, Disember) also diverge. Nouns are not inflected for number.
"""
import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser import pronounce_number, numbers_to_digits

from ovos_date_parser.duration import DurationLexicon, register_duration_lexicon

register_duration_lexicon(DurationLexicon(
    lang="ms",
    units={
        "microseconds": r"mikrosaat",
        "milliseconds": r"milisaat",
        "seconds": r"saat|detik",
        "minutes": r"minit",
        "hours": r"jam",
        "days": r"hari",
        "weeks": r"minggu",
        "months": r"bulan",
        "years": r"tahun",
        "decades": r"dekad",
        "centuries": r"abad",
        "millenniums": r"milenium|alaf",
    }))

WEEKDAYS_MS = {"isnin": 0, "selasa": 1, "rabu": 2, "khamis": 3, "jumaat": 4,
               "sabtu": 5, "ahad": 6}
MONTHS_MS = {"januari": 1, "februari": 2, "mac": 3, "april": 4, "mei": 5,
             "jun": 6, "julai": 7, "ogos": 8, "september": 9,
             "oktober": 10, "november": 11, "disember": 12}

_RELATIVE_DAYS_MS = {"hari ini": 0, "esok": 1, "besok": 1, "semalam": -1,
                     "kelmarin": -1, "lusa": 2}
_OFFSET_UNITS_MS = {"saat": "seconds", "minit": "minutes", "jam": "hours",
                    "hari": "days", "minggu": "weeks", "bulan": "months",
                    "tahun": "years"}
_PERIOD_NOUNS_MS = {"minggu": "week", "bulan": "month", "tahun": "year"}
_NEXT_MS = {"depan", "hadapan"}
_LAST_MS = {"lepas", "lalu"}
_AGO_MS = {"lepas", "lalu"}
_FUTURE_MS = {"lagi"}
_CLOCK_PREFIX_MS = {"pukul", "jam"}

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


def extract_datetime_ms(text, anchorDate=None, default_time=None):
    """Extract a datetime from Malay text.

    Understands the relative day words (hari ini, esok, semalam, lusa),
    weekday and month names with depan/lepas (next/last), "<n> <unit>
    lepas/lagi" offsets and clock times ("pukul 3", "15:30"). Returns the
    resolved datetime and the leftover text, or ``None`` when nothing
    date/time related is found.
    """
    if not text:
        return None
    anchor = anchorDate or datetime.now()
    text = text.lower()
    # fold spelled numbers to digits; drop surrounding punctuation, a
    # number's apostrophe suffix (locative "saat 3'te") and the trailing
    # ".0" the number parser can leave on an integer fused with a stop
    tokens = [re.sub(r"^(\d+)\.0$", r"\1",
                     re.sub(r"(?<=\d)'\w*$", "", t.strip(".,!?;:")))
              for t in numbers_to_digits(text, "ms").split()]
    n = len(tokens)
    result = anchor
    consumed = set()
    date_found = False
    time_found = False

    def free(i):
        return 0 <= i < n and i not in consumed

    # 1. "<n> <unit> lepas/lagi"
    for i in range(n):
        if not (free(i) and re.fullmatch(r"\d+", tokens[i]) and free(i + 1)):
            continue
        unit = _OFFSET_UNITS_MS.get(tokens[i + 1])
        if not unit:
            continue
        backward, dir_idx = None, None
        for j in (i + 2, i + 3):
            if free(j) and tokens[j] in _AGO_MS:
                backward, dir_idx = True, j
                break
            if free(j) and tokens[j] in _FUTURE_MS:
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
        if i in consumed or tokens[i] not in (_NEXT_MS | _LAST_MS):
            continue
        backward = tokens[i] in _LAST_MS
        for j in (i + 1, i - 1):
            if not free(j):
                continue
            if tokens[j] in _PERIOD_NOUNS_MS:
                unit = {"week": "weeks", "month": "months",
                        "year": "years"}[_PERIOD_NOUNS_MS[tokens[j]]]
                result, _ = _apply_offset(result, unit, 1, backward)
                date_found = True
                consumed.update({i, j})
                break
            if tokens[j] in WEEKDAYS_MS:
                result += timedelta(days=_weekday_delta(
                    anchor.weekday(), WEEKDAYS_MS[tokens[j]], backward))
                date_found = True
                consumed.update({i, j})
                break

    # 3. relative day words (longest phrase first)
    for phrase in sorted(_RELATIVE_DAYS_MS, key=lambda p: -len(p.split())):
        parts = phrase.split()
        w = len(parts)
        for i in range(n - w + 1):
            if any((i + k) in consumed for k in range(w)):
                continue
            if tokens[i:i + w] == parts:
                result = anchor + timedelta(days=_RELATIVE_DAYS_MS[phrase])
                date_found = True
                consumed.update(range(i, i + w))

    # 4. bare weekday -> next occurrence
    for i in range(n):
        if free(i) and tokens[i] in WEEKDAYS_MS:
            result += timedelta(days=_weekday_delta(
                anchor.weekday(), WEEKDAYS_MS[tokens[i]], False))
            date_found = True
            consumed.add(i)

    # 5. month-name date: <day>? <month> <year>?
    for i in range(n):
        if i in consumed or tokens[i] not in MONTHS_MS:
            continue
        month = MONTHS_MS[tokens[i]]
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

    # 6. clock times: HH:MM, or "<pukul|jam> <hour>"
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
        if tokens[i] in _CLOCK_PREFIX_MS and free(i + 1):
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


def _period_ms(hour):
    if hour < 12:
        return "pagi"
    if hour < 14:
        return "tengah hari"
    if hour < 19:
        return "petang"
    return "malam"


def nice_time_ms(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time to a comfortable Malay human format.

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
        hour = dt.hour
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "tengah malam"
        if dt.hour == 12 and dt.minute == 0:
            return "tengah hari"
        hour = dt.hour % 12
        if hour == 0:
            hour = 12

    speak = "pukul " + pronounce_number(hour, lang="ms")
    if dt.minute:
        speak += " lebih " + pronounce_number(dt.minute, lang="ms")
    if use_ampm and not use_24hour:
        speak += " " + _period_ms(dt.hour)
    return speak
