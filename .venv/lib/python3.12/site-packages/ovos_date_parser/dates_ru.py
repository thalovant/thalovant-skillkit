import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_ru import pronounce_number_ru, _ORDINAL_BASE_RU, extract_number_ru, \
    numbers_to_digits_ru
from ovos_number_parser.util import is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

_MONTHS_CONVERSION = {
    0: "january",
    1: "february",
    2: "march",
    3: "april",
    4: "may",
    5: "june",
    6: "july",
    7: "august",
    8: "september",
    9: "october",
    10: "november",
    11: "december"
}

_MONTHS_RU = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
              'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь',
              'декабрь']

_TIME_UNITS_CONVERSION = {
    'микросекунд': 'microseconds',
    'милисекунд': 'milliseconds',
    'секунда': 'seconds',
    'секунды': 'seconds',
    'секунд': 'seconds',
    'минута': 'minutes',
    'минуты': 'minutes',
    'минут': 'minutes',
    'година': 'hours',
    'годин': 'hours',
    'години': 'hours',
    'годиною': 'hours',
    'годинами': 'hours',
    'годині': 'hours',
    'час': 'hours',
    'часа': 'hours',
    'часов': 'hours',
    'день': 'days',
    'дня': 'days',
    'дней': 'days',
    'неделя': 'weeks',
    'недели': 'weeks',
    'недель': 'weeks'
}
_WORDS_NEXT_RU = [
    "будущая", "будущее", "будущей", "будущий", "будущим", "будущую",
    "новая", "новое", "новой", "новый", "новым",
    "следующая", "следующее", "следующей", "следующем", "следующий", "следующую",
]
_WORDS_PREV_RU = [
    "предыдущая", "предыдущем", "предыдущей", "предыдущий", "предыдущим", "предыдущую",
    "прошедшая", "прошедшем", "прошедшей", "прошедший", "прошедшим", "прошедшую",
    "прошлая", "прошлой", "прошлом", "прошлую", "прошлый", "прошлым",
    "том", "тот",
]
_WORDS_CURRENT_RU = [
    "данная", "данное", "данном", "данный",
    "настойщая", "настоящее", "настойщем", "настойщем", "настойщий",
    "нынешняя", "нынешнее", "нынешней", "нынешнем", "нынешний",
    "текущая", "текущее", "текущей", "текущем", "текущий",
    "это", "этим", "этой", "этом", "этот", "эту",
]
_WORDS_NOW_RU = [
    "теперь",
    "сейчас",
]
_WORDS_MORNING_RU = ["утро", "утром"]
_WORDS_DAY_RU = ["днём"]
_WORDS_EVENING_RU = ["вечер", "вечером"]
_WORDS_NIGHT_RU = ["ночь", "ночью"]


def nice_time_ru(dt, speech=True, use_24hour=True, use_ampm=False):
    """
    Format a time to a comfortable human format
    For example, generate 'five thirty' for speech or '5:30' for
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
            string = dt.strftime("%I:%M")
            if dt.hour < 4:
                string += " ночи"
            elif dt.hour < 12:
                string += " утра"
            elif dt.hour < 18:
                string += " дня"
            else:
                string += " вечера"
        else:
            # e.g. "3:01" or "2:22"
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # strip leading zeros

    if not speech:
        return string

    # Generate a speakable version of the time
    if use_24hour:
        speak = ""

        # Either "0 8 hundred" or "13 hundred"
        if string[0] == '0':
            speak += pronounce_hour_ru(int(string[0])) + " "
            speak += pronounce_number_ru(int(string[1]))
        else:
            speak = pronounce_hour_ru(int(string[0:2]))

        speak += " "
        if string[3:5] == '00':
            speak += "ровно"
        else:
            if string[3] == '0':
                speak += pronounce_number_ru(0) + " "
                speak += pronounce_number_ru(int(string[4]))
            else:
                speak += pronounce_number_ru(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "полночь"
        elif dt.hour == 12 and dt.minute == 0:
            return "полдень"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        if dt.minute == 15:
            speak = pronounce_hour_ru(hour) + " с четвертью"
        elif dt.minute == 30:
            speak = pronounce_hour_ru(hour) + " с половиной"
        elif dt.minute == 45:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = "без четверти " + pronounce_hour_ru(next_hour)
        else:
            speak = pronounce_hour_ru(hour)

            if dt.minute == 0:
                if not use_ampm:
                    if dt.hour % 12 == 1:
                        return speak
                    return speak + " " + plural_ru(dt.hour % 12, "час", "часа", "часов")
            else:
                if dt.minute < 10:
                    speak += " ноль"
                speak += " " + pronounce_number_ru(dt.minute)

        if use_ampm:
            if dt.hour < 4:
                speak += " ночи"
            elif dt.hour < 12:
                speak += " утра"
            elif dt.hour < 18:
                speak += " дня"
            else:
                speak += " вечера"

        return speak


def nice_duration_ru(duration, speech=True):
    """ Convert duration to a nice spoken timespan

    Args:
        seconds: number of seconds
        minutes: number of minutes
        hours: number of hours
        days: number of days
    Returns:
        str: timespan as a string
    """

    if not speech:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        _days = int(duration // 86400)
        _hours = int(duration // 3600 % 24)
        _minutes = int(duration // 60 % 60)
        _seconds = int(duration % 60)
        out = ""
        if _days > 0:
            out = str(_days) + "d "
        if _hours > 0 or _days > 0:
            out += str(_hours) + ":"
        if _minutes < 10 and (_hours > 0 or _days > 0):
            out += "0"
        out += str(_minutes) + ":"
        if _seconds < 10:
            out += "0"
        out += str(_seconds)
        return out

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    out = ''

    if days > 0:
        out += pronounce_number_ru(days)
        out += " " + plural_ru(days, "день", "дня", "дней")
    if hours > 0:
        if out:
            out += " "
        out += pronounce_number_ru(hours)
        out += " " + plural_ru(hours, "час", "часа", "часов")
    if minutes > 0:
        if out:
            out += " "
        out += pronounce_number_feminine_ru(minutes)
        out += " " + plural_ru(minutes, "минута", "минуты", "минут")
    if seconds > 0:
        if out:
            out += " "
        out += pronounce_number_feminine_ru(seconds)
        out += " " + plural_ru(seconds, "секунда", "секунды", "секунд")

    return out


def pronounce_hour_ru(num):
    if num == 1:
        return "час"
    return pronounce_number_ru(num)


def extract_duration_ru(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["ru"],
                                    resolution, replace_token)


def extract_datetime_ru(text, anchor_date=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "today"
        "tomorrow afternoon"
        "next Tuesday at 4pm"
        "August 3rd"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.  For example, the string
       "what is Tuesday's weather forecast"
    returns the date for the forthcoming Tuesday relative to the reference
    date and the remainder string
       "what is weather forecast".

    The "next" instance of a day or weekend is considered to be no earlier than
    48 hours in the future. On Friday, "next Monday" would be in 3 days.
    On Saturday, "next Monday" would be in 9 days.

    Args:
        text (str): string containing date words
        anchor_date (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s):
        # clean unneeded punctuation and capitalization among other things.
        # Normalize Russian inflection
        s = s.lower().replace('?', '').replace('.', '').replace(',', '') \
            .replace("сегодня вечером", "вечером") \
            .replace("сегодня ночью", "ночью")
        word_list = s.split()

        for idx, word in enumerate(word_list):
            # word = word.replace("'s", "")
            ##########
            # Russian Day Ordinals - we do not use 1st,2nd format
            #    instead we use full ordinal number names with specific format(suffix)
            #   Example: тридцать первого > 31
            count_ordinals = 0
            if word == "первого":
                count_ordinals = 1  # These two have different format
            elif word == "третьего":
                count_ordinals = 3
            elif word.endswith("ого"):
                tmp = word[:-3]
                tmp += "ый"
                for nr, name in _ORDINAL_BASE_RU.items():
                    if name == tmp:
                        count_ordinals = nr

            # If number is bigger than 19 check if next word is also ordinal
            #  and count them together
            if count_ordinals > 19:
                if word_list[idx + 1] == "первого":
                    count_ordinals += 1  # These two have different format
                elif word_list[idx + 1] == "третьего":
                    count_ordinals += 3
                elif word_list[idx + 1].endswith("ого"):
                    tmp = word_list[idx + 1][:-3]
                    tmp += "ый"
                    for nr, name in _ORDINAL_BASE_RU.items():
                        if name == tmp and nr < 10:
                            # write only if sum makes acceptable count of days in month
                            if (count_ordinals + nr) <= 31:
                                count_ordinals += nr

            if count_ordinals > 0:
                word = str(count_ordinals)  # Write normalized value into word
            if count_ordinals > 20:
                # If counted number is greater than 20, clear next word so it is not used again
                word_list[idx + 1] = ""
            ##########
            # Remove inflection from Russian months

            word_list[idx] = word

        return word_list

    def date_found():
        return found or \
            (
                    date_string != "" or
                    year_offset != 0 or month_offset != 0 or
                    day_offset is True or hr_offset != 0 or
                    hr_abs or min_offset != 0 or
                    min_abs or sec_offset != 0
            )

    if text == "":
        return None

    anchor_date = anchor_date or now_local()
    found = False
    day_specified = False
    day_offset = False
    month_offset = 0
    year_offset = 0
    today = anchor_date.strftime("%w")
    current_year = anchor_date.strftime("%Y")
    from_flag = False
    date_string = ""
    has_year = False
    time_qualifier = ""

    time_qualifiers_am = _WORDS_MORNING_RU
    time_qualifiers_pm = ['дня', 'вечера']
    time_qualifiers_pm.extend(_WORDS_DAY_RU)
    time_qualifiers_pm.extend(_WORDS_EVENING_RU)
    time_qualifiers_pm.extend(_WORDS_NIGHT_RU)
    time_qualifiers_list = set(time_qualifiers_am + time_qualifiers_pm)
    markers = ['на', 'в', 'во', 'до', 'на', 'это',
               'около', 'этот', 'через', 'спустя', 'за', 'тот']
    days = ['понедельник', 'вторник', 'среда',
            'четверг', 'пятница', 'суббота', 'воскресенье']
    months = _MONTHS_RU
    recur_markers = days + ['выходные', 'викенд']
    months_short = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг',
                    'сен', 'окт', 'ноя', 'дек']
    year_multiples = ["десятилетие", "век", "тысячелетие"]

    words = clean_string(text)
    preposition = ""

    for idx, word in enumerate(words):
        if word == "":
            continue

        if word in markers:
            preposition = word

        word = _text_ru_inflection_normalize(word, 2)
        word_prev_prev = _text_ru_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        word_prev = _text_ru_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        word_next = _text_ru_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        word_next_next = _text_ru_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        start = idx
        used = 0
        if word in _WORDS_NOW_RU and not date_string:
            result_str = " ".join(words[idx + 1:])
            result_str = ' '.join(result_str.split())
            extracted_date = anchor_date.replace(microsecond=0)
            return [extracted_date, result_str]
        elif word_next in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_ru(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if word_next == "десятилетие":
                year_offset = multiplier * 10
            elif word_next == "век":
                year_offset = multiplier * 100
            elif word_next == "тысячелетие":
                year_offset = multiplier * 1000
        elif word in time_qualifiers_list and preposition != "через" and word_next != "назад":
            time_qualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "сегодня" and not from_flag:
            day_offset = 0
            used += 1
        elif word == "завтра" and not from_flag:
            day_offset = 1
            used += 1
        elif word == "послезавтра" and not from_flag:
            day_offset = 2
            used += 1
        elif word == "после" and word_next == "завтра" and not from_flag:
            day_offset = 2
            used += 2
        elif word == "позавчера" and not from_flag:
            day_offset = -2
            used += 1
        elif word == "вчера" and not from_flag:
            day_offset = -1
            used += 1
        elif (word in ["день", "дня"] and
              word_next == "после" and
              word_next_next == "завтра" and
              not from_flag and
              (not word_prev or not word_prev[0].isdigit())):
            day_offset = 2
            used = 2
        elif word in ["день", "дня"] and is_numeric(word_prev) and preposition == "через":
            if word_prev and word_prev[0].isdigit():
                day_offset += int(word_prev)
                start -= 1
                used = 2
        elif word in ["день", "дня"] and is_numeric(word_prev) and word_next == "назад":
            if word_prev and word_prev[0].isdigit():
                day_offset += -int(word_prev)
                start -= 1
                used = 3
        elif word == "сегодня" and not from_flag and word_prev:
            if word_prev and word_prev[0].isdigit():
                day_offset += int(word_prev) * 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_RU:
                day_offset = 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_RU:
                day_offset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif word == "неделя" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                day_offset = int(word_prev) * 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_RU:
                day_offset = 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_RU:
                day_offset = -7
                start -= 1
                used = 2
        elif word == "неделя" and not from_flag and is_numeric(word_prev) and word_next == "назад":
            if word_prev and word_prev[0].isdigit():
                day_offset = -int(word_prev) * 7
                start -= 1
                used = 3
        elif word == "месяц" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                month_offset = int(word_prev)
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_RU:
                month_offset = 1
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_RU:
                month_offset = -1
                start -= 1
                used = 2
        elif word == "месяц" and not from_flag and is_numeric(word_prev) and word_next == "назад":
            if word_prev and word_prev[0].isdigit():
                month_offset = -int(word_prev)
                start -= 1
                used = 3
        # parse 5 years, next year, last year
        elif word == "год" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                year_offset = int(word_prev)
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_RU:
                year_offset = 1
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_RU:
                year_offset = -1
                start -= 1
                used = 2
            elif word_prev == "через":
                year_offset = 1
                used = 1
        elif word == "год" and not from_flag and is_numeric(word_prev) and word_next == "назад":
            if word_prev and word_prev[0].isdigit():
                year_offset = -int(word_prev)
                start -= 1
                used = 3
        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not from_flag:
            d = days.index(word)
            day_offset = (d + 1) - int(today)
            used = 1
            if day_offset < 0:
                day_offset += 7
            if word_prev in _WORDS_NEXT_RU:
                if day_offset <= 2:
                    day_offset += 7
                used += 1
                start -= 1
            elif word_prev in _WORDS_PREV_RU:
                day_offset -= 7
                used += 1
                start -= 1
        elif word in months or word in months_short and not from_flag:
            try:
                m = months.index(word)
            except ValueError:
                m = months_short.index(word)
            used += 1
            # Convert Russian months to english
            date_string = _MONTHS_CONVERSION.get(m)
            if word_prev and (word_prev and word_prev[0].isdigit() or
                              (word_prev == " " and word_prev_prev and word_prev_prev[0].isdigit())):
                if word_prev == " " and word_prev_prev and word_prev_prev[0].isdigit():
                    date_string += " " + words[idx - 2]
                    used += 1
                    start -= 1
                else:
                    date_string += " " + word_prev
                start -= 1
                used += 1
                if word_next and word_next[0].isdigit():
                    date_string += " " + word_next
                    used += 1
                    has_year = True
                else:
                    has_year = False

            elif word_next and word_next[0].isdigit():
                date_string += " " + word_next
                used += 1
                if word_next_next and word_next_next[0].isdigit():
                    date_string += " " + word_next_next
                    used += 1
                    has_year = True
                else:
                    has_year = False

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        valid_followups = days + months + months_short
        valid_followups.append("сегодня")
        valid_followups.append("завтра")
        valid_followups.append("послезавтра")
        valid_followups.append("вчера")
        valid_followups.append("позавчера")
        for followup in _WORDS_NEXT_RU:
            valid_followups.append(followup)
        for followup in _WORDS_PREV_RU:
            valid_followups.append(followup)
        for followup in _WORDS_CURRENT_RU:
            valid_followups.append(followup)
        for followup in _WORDS_NOW_RU:
            valid_followups.append(followup)
        if (word in ["до", "по", "от", "с", "со"]) and word_next in valid_followups:
            used = 2
            from_flag = True
            if word_next == "завтра":
                day_offset += 1
            elif word_next == "послезавтра":
                day_offset += 2
            elif word_next == "вчера":
                day_offset -= 1
            elif word_next == "позавчера":
                day_offset -= 2
            elif word_next in days:
                d = days.index(word_next)
                tmp_offset = (d + 1) - int(today)
                used = 2
                if tmp_offset < 0:
                    tmp_offset += 7
                day_offset += tmp_offset
            elif word_next_next and word_next_next in days:
                d = days.index(word_next_next)
                tmp_offset = (d + 1) - int(today)
                used = 3
                if word_next in _WORDS_NEXT_RU:
                    if day_offset <= 2:
                        tmp_offset += 7
                    used += 1
                    start -= 1
                elif word_next in _WORDS_PREV_RU:
                    tmp_offset -= 7
                    used += 1
                    start -= 1
                day_offset += tmp_offset
        if used > 0:
            if start - 1 > 0 and (words[start - 1] in _WORDS_CURRENT_RU):
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ""
            found = True
            day_specified = True

    # parse time
    hr_offset = 0
    min_offset = 0
    sec_offset = 0
    hr_abs = None
    min_abs = None
    military = False
    preposition = ""

    for idx, word in enumerate(words):
        if word == "":
            continue

        if word in markers:
            preposition = word

        word = _text_ru_inflection_normalize(word, 2)
        word_prev_prev = _text_ru_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        word_prev = _text_ru_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        word_next = _text_ru_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        word_next_next = _text_ru_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "полдень":
            hr_abs = 12
            used += 1
        elif word == "полночь":
            hr_abs = 0
            used += 1
        elif word in _WORDS_MORNING_RU:
            if hr_abs is None:
                hr_abs = 8
            used += 1
        elif word in _WORDS_DAY_RU:
            if hr_abs is None:
                hr_abs = 15
            used += 1
        elif word in _WORDS_EVENING_RU:
            if hr_abs is None:
                hr_abs = 19
            used += 1
            if word_next != "" and word_next[0].isdigit() and ":" in word_next:
                used -= 1
        elif word in _WORDS_NIGHT_RU:
            if hr_abs is None:
                hr_abs = 22
        # parse half an hour, quarter hour
        elif word == "час" and \
                (word_prev in markers or word_prev_prev in markers):
            if word_prev in ["пол", "половина"]:
                min_offset = 30
            elif word_prev == "четверть":
                min_offset = 15
            elif word_prev == "через":
                hr_offset = 1
            else:
                hr_offset = 1
            if word_prev_prev in markers:
                words[idx - 2] = ""
                if word_prev_prev in _WORDS_CURRENT_RU:
                    day_specified = True
            words[idx - 1] = ""
            used += 1
            hr_abs = -1
            min_abs = -1
            # parse 5:00 am, 12:00 p.m., etc
        # parse in a minute
        elif word == "минута" and word_prev == "через":
            min_offset = 1
            words[idx - 1] = ""
            used += 1
        # parse in a second
        elif word == "секунда" and word_prev == "через":
            sec_offset = 1
            words[idx - 1] = ""
            used += 1
        elif word and word[0].isdigit():
            is_time = True
            str_hh = ""
            str_mm = ""
            remainder = ""
            word_next_next_next = words[idx + 3] \
                if idx + 3 < len(words) else ""
            if word_next in _WORDS_EVENING_RU or word_next in _WORDS_NIGHT_RU or word_next_next in _WORDS_EVENING_RU \
                    or word_next_next in _WORDS_NIGHT_RU or word_prev in _WORDS_EVENING_RU \
                    or word_prev in _WORDS_NIGHT_RU or word_prev_prev in _WORDS_EVENING_RU \
                    or word_prev_prev in _WORDS_NIGHT_RU or word_next_next_next in _WORDS_EVENING_RU \
                    or word_next_next_next in _WORDS_NIGHT_RU:
                remainder = "pm"
                used += 1
                if word_prev in _WORDS_EVENING_RU or word_prev in _WORDS_NIGHT_RU:
                    words[idx - 1] = ""
                if word_prev_prev in _WORDS_EVENING_RU or word_prev_prev in _WORDS_NIGHT_RU:
                    words[idx - 2] = ""
                if word_next_next in _WORDS_EVENING_RU or word_next_next in _WORDS_NIGHT_RU:
                    used += 1
                if word_next_next_next in _WORDS_EVENING_RU or word_next_next_next in _WORDS_NIGHT_RU:
                    used += 1

            if ':' in word:
                # parse colons
                # "3:00 in the morning"
                stage = 0
                length = len(word)
                for i in range(length):
                    if stage == 0:
                        if word[i].isdigit():
                            str_hh += word[i]
                        elif word[i] == ":":
                            stage = 1
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 1:
                        if word[i].isdigit():
                            str_mm += word[i]
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 2:
                        remainder = word[i:].replace(".", "")
                        break
                if remainder == "":
                    next_word = word_next.replace(".", "")
                    if next_word in ["am", "pm", "ночи", "утра", "дня", "вечера"]:
                        remainder = next_word
                        used += 1
                    elif next_word == "часа" and word_next_next in ["am", "pm", "ночи", "утра", "дня", "вечера"]:
                        remainder = word_next_next
                        used += 2
                    elif word_next in _WORDS_MORNING_RU:
                        remainder = "am"
                        used += 2
                    elif word_next in _WORDS_DAY_RU:
                        remainder = "pm"
                        used += 2
                    elif word_next in _WORDS_EVENING_RU:
                        remainder = "pm"
                        used += 2
                    elif word_next == "этого" and word_next_next in _WORDS_MORNING_RU:
                        remainder = "am"
                        used = 2
                        day_specified = True
                    elif word_next == "на" and word_next_next in _WORDS_DAY_RU:
                        remainder = "pm"
                        used = 2
                        day_specified = True
                    elif word_next == "на" and word_next_next in _WORDS_EVENING_RU:
                        remainder = "pm"
                        used = 2
                        day_specified = True
                    elif word_next == "в" and word_next_next in _WORDS_NIGHT_RU:
                        if str_hh and int(str_hh) > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 2
                    elif hr_abs and hr_abs != -1:
                        if hr_abs >= 12:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 1
                    else:
                        if time_qualifier != "":
                            military = True
                            if str_hh and int(str_hh) <= 12 and \
                                    (time_qualifier in time_qualifiers_pm):
                                str_hh += str(int(str_hh) + 12)

            else:
                # try to parse numbers without colons
                # 5 hours, 10 minutes etc.
                length = len(word)
                str_num = ""
                remainder = ""
                for i in range(length):
                    if word[i].isdigit():
                        str_num += word[i]
                    else:
                        remainder += word[i]

                if remainder == "":
                    remainder = word_next.replace(".", "").lstrip().rstrip()
                if (
                        remainder == "pm" or
                        word_next == "pm" or
                        remainder == "p.m." or
                        word_next == "p.m." or
                        (remainder == "дня" and preposition != 'через') or
                        (word_next == "дня" and preposition != 'через') or
                        remainder == "вечера" or
                        word_next == "вечера"):
                    str_hh = str_num
                    remainder = "pm"
                    used = 1
                    if (
                            remainder == "pm" or
                            word_next == "pm" or
                            remainder == "p.m." or
                            word_next == "p.m." or
                            (remainder == "дня" and preposition != 'через') or
                            (word_next == "дня" and preposition != 'через') or
                            remainder == "вечера" or
                            word_next == "вечера"):
                        str_hh = str_num
                        remainder = "pm"
                        used = 1
                elif (
                        remainder == "am" or
                        word_next == "am" or
                        remainder == "a.m." or
                        word_next == "a.m." or
                        remainder == "ночи" or
                        word_next == "ночи" or
                        remainder == "утра" or
                        word_next == "утра"):
                    str_hh = str_num
                    remainder = "am"
                    used = 1
                elif (
                        remainder in recur_markers or
                        word_next in recur_markers or
                        word_next_next in recur_markers):
                    # Ex: "7 on mondays" or "3 this friday"
                    # Set str_hh so that is_time == True
                    # when am or pm is not specified
                    str_hh = str_num
                    used = 1
                else:
                    if int(str_num) > 100:
                        str_hh = str(int(str_num) // 100)
                        str_mm = str(int(str_num) % 100)
                        military = True
                        if word_next == "час":
                            used += 1
                    elif (
                            (word_next == "час" or
                             remainder == "час") and
                            word[0] != '0' and
                            # (wordPrev != "в" and wordPrev != "на")
                            word_prev == "через"
                            and
                            (
                                    int(str_num) < 100 or
                                    int(str_num) > 2400
                            )):
                        # ignores military time
                        # "in 3 hours"
                        hr_offset = int(str_num)
                        used = 2
                        is_time = False
                        hr_abs = -1
                        min_abs = -1
                    elif word_next == "минута" or \
                            remainder == "минута":
                        # "in 10 minutes"
                        min_offset = int(str_num)
                        used = 2
                        is_time = False
                        hr_abs = -1
                        min_abs = -1
                    elif word_next == "секунда" \
                            or remainder == "секунда":
                        # in 5 seconds
                        sec_offset = int(str_num)
                        used = 2
                        is_time = False
                        hr_abs = -1
                        min_abs = -1
                    elif int(str_num) > 100:
                        # military time, eg. "3300 hours"
                        str_hh = str(int(str_num) // 100)
                        str_mm = str(int(str_num) % 100)
                        military = True
                        if word_next == "час" or \
                                remainder == "час":
                            used += 1
                    elif word_next and word_next[0].isdigit():
                        # military time, e.g. "04 38 hours"
                        str_hh = str_num
                        str_mm = word_next
                        military = True
                        used += 1
                        if (word_next_next == "час" or
                                remainder == "час"):
                            used += 1
                    elif (
                            word_next == "" or word_next == "час" or
                            (
                                    (word_next == "в" or word_next == "на") and
                                    (
                                            word_next_next == time_qualifier
                                    )
                            ) or word_next in _WORDS_EVENING_RU or
                            word_next_next in _WORDS_EVENING_RU):

                        str_hh = str_num
                        str_mm = "00"
                        if word_next == "час":
                            used += 1
                        if (word_next == "в" or word_next == "на"
                                or word_next_next == "в" or word_next_next == "на"):
                            used += (1 if (word_next ==
                                           "в" or word_next == "на") else 2)
                            word_next_next_next = words[idx + 3] \
                                if idx + 3 < len(words) else ""

                            if (word_next_next and
                                    (word_next_next in time_qualifier or
                                     word_next_next_next in time_qualifier)):
                                if (word_next_next in time_qualifiers_pm or
                                        word_next_next_next in time_qualifiers_pm):
                                    remainder = "pm"
                                    used += 1
                                if (word_next_next in time_qualifiers_am or
                                        word_next_next_next in time_qualifiers_am):
                                    remainder = "am"
                                    used += 1

                        if time_qualifier != "":
                            if time_qualifier in time_qualifiers_pm:
                                remainder = "pm"
                                used += 1

                            elif time_qualifier in time_qualifiers_am:
                                remainder = "am"
                                used += 1
                            else:
                                # TODO: Unsure if this is 100% accurate
                                used += 1
                                military = True
                        elif remainder == "час":
                            if word_next_next in ["ночи", "утра"]:
                                remainder = "am"
                                used += 1
                            elif word_next_next in ["дня", "вечера"]:
                                remainder = "pm"
                                used += 1
                            else:
                                remainder = ""

                    else:
                        is_time = False
            hh = int(str_hh) if str_hh else 0
            mm = int(str_mm) if str_mm else 0
            hh = hh + 12 if remainder == "pm" and hh < 12 else hh
            hh = hh - 12 if remainder == "am" and hh >= 12 else hh
            if (not military and
                    remainder not in ['am', 'pm', 'час', 'минута', 'секунда'] and
                    ((not day_specified) or 0 <= day_offset < 1)):

                # ambiguous time, detect whether they mean this evening or
                # the next morning based on whether it has already passed
                if anchor_date.hour < hh or (anchor_date.hour == hh and
                                             anchor_date.minute < mm):
                    pass  # No modification needed
                elif anchor_date.hour < hh + 12:
                    hh += 12
                else:
                    # has passed, assume the next morning
                    day_offset += 1
            if time_qualifier in time_qualifiers_pm and hh < 12:
                hh += 12

            if hh > 24 or mm > 59:
                is_time = False
                used = 0
            if is_time:
                hr_abs = hh
                min_abs = mm
                used += 1

        if used > 0:
            # removed parsed words from the sentence
            for i in range(used):
                if idx + i >= len(words):
                    break
                words[idx + i] = ""

            # if wordPrev == "o" or wordPrev == "oh":
            #    words[words.index(wordPrev)] = ""

            if word_prev == "скоро":
                hr_offset = -1
                words[idx - 1] = ""
                idx -= 1
            elif word_prev == "позже":
                hr_offset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and word_prev in markers:
                words[idx - 1] = ""
                if word_prev in _WORDS_CURRENT_RU:
                    day_specified = True
            if idx > 1 and word_prev_prev in markers:
                words[idx - 2] = ""
                if word_prev_prev in _WORDS_CURRENT_RU:
                    day_specified = True

            idx += used - 1
            found = True
    # check that we found a date
    if not date_found():
        return None

    if day_offset is False:
        day_offset = 0

    # perform date manipulation

    extracted_date = anchor_date.replace(microsecond=0)
    if date_string != "":
        # date included an explicit date, e.g. "june 5" or "june 2, 2017"
        extracted_date = extracted_date.replace(hour=0, minute=0, second=0)
        if not has_year:
            # Resolve the month/day against a real year rather than
            # strptime's default 1900, which is not a leap year and would
            # reject a valid "29 february". Pick the next year in which the
            # day exists, so "29 february" lands on the next leap year.
            def _resolve_year(base_year):
                # search a bounded window so an impossible day (e.g. "45
                # february") stops instead of looping forever
                for year in range(base_year, base_year + 9):
                    try:
                        return datetime.strptime(
                            "{} {}".format(date_string, year), "%B %d %Y")
                    except ValueError:
                        continue
                return None

            temp = _resolve_year(int(current_year))
            if temp is None:
                return None
            temp = temp.replace(tzinfo=extracted_date.tzinfo)
            if extracted_date >= temp:
                later = _resolve_year(int(current_year) + 1)
                if later is not None:
                    temp = later.replace(tzinfo=extracted_date.tzinfo)
            extracted_date = extracted_date.replace(
                year=temp.year,
                month=temp.month,
                day=temp.day,
                tzinfo=extracted_date.tzinfo)
        else:
            try:
                temp = datetime.strptime(date_string, "%B %d %Y")
            except ValueError:
                # an impossible calendar date like "30 февраля"; report
                # nothing rather than a wrong guess
                return None
            extracted_date = extracted_date.replace(
                year=int(temp.strftime("%Y")),
                month=int(temp.strftime("%m")),
                day=int(temp.strftime("%d")),
                tzinfo=extracted_date.tzinfo)
    else:
        # ignore the current HH:MM:SS if relative using days or greater
        if hr_offset == 0 and min_offset == 0 and sec_offset == 0:
            extracted_date = extracted_date.replace(hour=0, minute=0, second=0)

    if year_offset != 0:
        extracted_date = extracted_date + relativedelta(years=year_offset)
    if month_offset != 0:
        extracted_date = extracted_date + relativedelta(months=month_offset)
    if day_offset != 0:
        extracted_date = extracted_date + relativedelta(days=day_offset)
    if hr_abs != -1 and min_abs != -1:
        # If no time was supplied in the string set the time to default
        # time if it's available
        if hr_abs is None and min_abs is None and default_time is not None:
            hr_abs, min_abs = default_time.hour, default_time.minute
        else:
            hr_abs = hr_abs or 0
            min_abs = min_abs or 0

        extracted_date = extracted_date + relativedelta(hours=hr_abs,
                                                        minutes=min_abs)
        if (hr_abs != 0 or min_abs != 0) and date_string == "":
            if not day_specified and anchor_date > extracted_date:
                extracted_date = extracted_date + relativedelta(days=1)
    if hr_offset != 0:
        extracted_date = extracted_date + relativedelta(hours=hr_offset)
    if min_offset != 0:
        extracted_date = extracted_date + relativedelta(minutes=min_offset)
    if sec_offset != 0:
        extracted_date = extracted_date + relativedelta(seconds=sec_offset)
    for idx, word in enumerate(words):
        if word == "и" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    result_str = " ".join(words)
    result_str = ' '.join(result_str.split())
    return [extracted_date, result_str]


def _text_ru_inflection_normalize(word, arg):
    """
    Russian Inflection normalizer.

    This try to normalize known inflection. This function is called
    from multiple places, each one is defined with arg.

    Args:
        word [Word]
        arg [Int]

    Returns:
        word [Word]

    """
    if word in ["тысяч", "тысячи"]:
        return "тысяча"

    if arg == 1:  # _extract_whole_number_with_text_ru
        if word in ["одна", "одним", "одно", "одной"]:
            return "один"
        if word == "две":
            return "два"
        if word == "пару":
            return "пара"

    elif arg == 2:  # extract_datetime_ru
        if word in ["часа", "часам", "часами", "часов", "часу"]:
            return "час"
        if word in ["минут", "минутам", "минутами", "минуту", "минуты"]:
            return "минута"
        if word in ["секунд", "секундам", "секундами", "секунду", "секунды"]:
            return "секунда"
        if word in ["дней", "дни"]:
            return "день"
        if word in ["неделе", "недели", "недель"]:
            return "неделя"
        if word in ["месяца", "месяцев"]:
            return "месяц"
        if word in ["года", "лет"]:
            return "год"
        if word in _WORDS_MORNING_RU:
            return "утром"
        if word in ["полудне", "полудня"]:
            return "полдень"
        if word in _WORDS_EVENING_RU:
            return "вечером"
        if word in _WORDS_NIGHT_RU:
            return "ночь"
        if word in ["викенд", "выходным", "выходных"]:
            return "выходные"
        if word in ["столетие", "столетий", "столетия"]:
            return "век"

        # Week days
        if word in ["среду", "среды"]:
            return "среда"
        if word in ["пятницу", "пятницы"]:
            return "пятница"
        if word in ["субботу", "субботы"]:
            return "суббота"

        # Months
        if word in ["марта", "марте"]:
            return "март"
        if word in ["мае", "мая"]:
            return "май"
        if word in ["августа", "августе"]:
            return "август"

        if word[-2:] in ["ле", "ля", "не", "ня", "ре", "ря"]:
            tmp = word[:-1] + "ь"
            for name in _MONTHS_RU:
                if name == tmp:
                    return name

    return word


def pronounce_number_feminine_ru(num):
    pronounced = pronounce_number_ru(num)

    num %= 100
    if num % 10 == 1 and num // 10 != 1:
        return pronounced[:-2] + "на"
    elif num % 10 == 2 and num // 10 != 1:
        return pronounced[:-1] + "е"

    return pronounced


def plural_ru(num: int, one: str, few: str, many: str):
    num %= 100
    if num // 10 == 1:
        return many
    if num % 10 == 1:
        return one
    if 2 <= num % 10 <= 4:
        return few
    return many
