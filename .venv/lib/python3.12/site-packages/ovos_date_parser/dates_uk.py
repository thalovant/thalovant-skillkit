import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_uk import extract_number_uk, numbers_to_digits_uk, _ORDINAL_BASE_UK, pronounce_number_uk, \
    _NUM_STRING_UK
from ovos_number_parser.util import invert_dict, is_numeric
from ovos_utils.time import now_local
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)

# hours
HOURS_UK = {
    1: 'перша',
    2: 'друга',
    3: 'третя',
    4: 'четверта',
    5: "п'ята",
    6: 'шоста',
    7: 'сьома',
    8: 'восьма',
    9: "дев'ята",
    10: 'десята',
    11: 'одинадцята',
    12: 'дванадцята'
}
# Months

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

_MONTHS_UK = ["січень", "лютий", "березень", "квітень", "травень", "червень",
              "липень", "серпень", "вересень", "жовтень", "листопад",
              "грудень"]

# Time
_TIME_UNITS_CONVERSION = {
    "мікросекунд": "microseconds",
    "мілісекунд": "milliseconds",
    "секунда": "seconds",
    "секунди": "seconds",
    "секунд": "seconds",
    "секунду": "seconds",
    "хвилина": "minutes",
    "хвилини": "minutes",
    "хвилин": "minutes",
    "хвилину": "minutes",
    "година": "hours",
    "годин": "hours",
    "години": "hours",
    "годину": "hours",
    "годинами": "hours",
    "годиною": "hours",
    "днів": "days",
    "день": "days",
    "дні": "days",
    "дня": "days",
    "тиждень": "weeks",
    "тижня": "weeks",
    "тижні": "weeks",
    "тижнів": "weeks"
}

_WORDS_NEXT_UK = [
    "майбутня", "майбутнє", "майбутній", "майбутньому", "майбутнім", "майбутньої", "майбутнього",
    "нова", "нове", "новий", "нового", "нової", "новим", "новою", "через",
    "наступна", "наступне", "наступний", "наступній", "наступному", "наступним", "наступною",
]
_WORDS_PREV_UK = [
    "попередня", "попередній", "попереднім", "попередньої",
    "попередню", "попереднього", "попередне", "тому",
    "минула", "минулий", "минуле", "минулу", "минулого", "минулій", "минулому",
    "минулої", "минулою", "минулим",
    "та", "той", "ті", "те", "того",
]
_WORDS_CURRENT_UK = [
    "теперішній", "теперішня", "теперішні", "теперішній", "теперішньому",
    "теперішньою", "теперішнім", "теперішнього", "теперішньої",
    "дана", "даний", "дане", "даним", "даною", "даного", "даної", "даному", "даній",
    "поточний", "поточна", "поточні", "поточне", "поточного", "поточної",
    "поточному", "поточній", "поточним", "поточною",
    "нинішній", "нинішня", "нинішнє", "нинішньому", "нинішній",
    "нинішнього", "нинішньої", "нинішнім", "нинішньою",
    "цей", "ця", "це", "цим", "цією", "цьому", "цій"
]
_WORDS_NOW_UK = [
    "тепер",
    "зараз",
]
_WORDS_MORNING_UK = ["ранок", "зранку", "вранці", "ранку"]
_WORDS_DAY_UK = ["вдень", "опівдні"]
_WORDS_EVENING_UK = ["вечер", "ввечері", "увечері", "вечором"]
_WORDS_NIGHT_UK = ["ніч", "вночі"]
_PLURALS = {
    'двох': 2, 'двум': 2, 'двома': 2, 'дві': 2, "двоє": 2, "двійка": 2,
    'обидва': 2, 'обидвох': 2, 'обидві': 2, 'обох': 2, 'обома': 2, 'обом': 2,
    'пара': 2, 'пари': 2, 'парою': 2, 'парами': 2, 'парі': 2, 'парах': 2, 'пару': 2,
    'трьох': 3, 'трьома': 3, 'трьом': 3,
    'чотирьох': 4, 'чотирьом': 4, 'чотирма': 4,
    "п'ятьох": 5, "п'ятьом": 5, "п'ятьома": 5,
    "шістьом": 6, "шести": 6, "шістьох": 6, "шістьма": 6, "шістьома": 6,
    "семи": 7, "сімом": 7, "сімох": 7, "сімома": 7, "сьома": 7,
    "восьми": 8, "вісьмох": 8, "вісьмом": 8, "вісьма": 8, "вісьмома": 8,
    "дев'яти": 9, "дев'ятьох": 9, "дев'ятьом": 9, "дев'ятьма": 9,
    "десяти": 10, "десятьох": 10, "десятьма": 10, "десятьома": 10,
    "сорока": 40,
    "сот": 100, "сотень": 100, "сотні": 100, "сотня": 100,
    "двохсот": 200, "двомстам": 200, "двомастами": 200, "двохстах": 200,
    "тисяч": 1000, "тисячі": 1000, "тисячу": 1000, "тисячах": 1000,
    "тисячами": 1000, "тисячею": 1000
}


def generate_plurals_uk(originals):
    """
    Return a new set or dict containing the plural form of the original values,
    Generate different cases of values

    In English this means all with 's' appended to them.

    Args:
        originals set(str) or dict(str, any): values to pluralize

    Returns:
        set(str) or dict(str, any)

    """
    suffixes = ["а", "ах", "их", "ам", "ами", "ів",
                "ям", "ох", "и", "на", "ни", "і", "ні",
                "ий", "ний", 'ьох', 'ьома', 'ьом', 'ох',
                'ум', 'ма', 'ом']
    if isinstance(originals, dict):
        thousand = {"тисяч": 1000, "тисячі": 1000, "тисячу": 1000, "тисячах": 1000}
        hundred = {"сотня": 100, "сотні": 100, "сотень": 100}
        result_dict = {key + suffix: value for key, value in originals.items() for suffix in suffixes}
        result_dict.update(thousand)
        result_dict.update(hundred)
        return result_dict
    thousand = ["тисяч", "тисячі", "тисячу", "тисячах"]
    result_dict = {value + suffix for value in originals for suffix in suffixes}
    result_dict.update(thousand)
    return {value + suffix for value in originals for suffix in suffixes}


_STRING_NUM_UK = invert_dict(_NUM_STRING_UK)

_STRING_NUM_UK.update(generate_plurals_uk(_STRING_NUM_UK))
_STRING_NUM_UK.update(_PLURALS)
_STRING_NUM_UK.update({
    "трильйон": 1e18,
    "половина": 0.5, "половиною": 0.5, "половини": 0.5, "половин": 0.5, "половинами": 0.5, "пів": 0.5,
    "одна": 1, "одної": 1, "одній": 1, "одну": 1
})


def extract_duration_uk(text, resolution=DurationResolution.TIMEDELTA,
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
    return extract_duration_generic(text, DURATION_LEXICONS["uk"],
                                    resolution, replace_token)


def extract_datetime_uk(text, anchor_date=None, default_time=None):
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
        # Normalize Ukrainian inflection
        s = s.lower().replace('?', '').replace('.', '').replace(',', '')
        s = s.replace("сьогодні вечером|сьогодні ввечері|вечором", "ввечері")
        s = s.replace("сьогодні вночі", "вночі")
        word_list = s.split()

        for idx, word in enumerate(word_list):
            ##########
            # Ukrainian Day Ordinals - we do not use 1st,2nd format
            #   instead we use full ordinal number names with specific format(suffix)
            #   Example: двадцять третього - 23
            count_ordinals = 0
            if word == "третього":
                count_ordinals = 3
            #   Example: тридцять першого - 31
            elif word.endswith("ого"):
                tmp = word[:-3]
                tmp += "ий"
                for nr, name in _ORDINAL_BASE_UK.items():
                    if name == tmp:
                        count_ordinals = nr
            #   Example: тридцять перше > 31
            elif word.endswith("є") or word.endswith("е"):
                tmp = word[:-1]
                tmp += "ий"
                for nr, name in _ORDINAL_BASE_UK.items():
                    if name == tmp:
                        count_ordinals = nr
            # If number is bigger than 19 check if next word is also ordinal
            #  and count them together
            if count_ordinals > 19 and idx + 1 < len(word_list):
                if word_list[idx + 1] == "третього":
                    count_ordinals += 3
                elif word_list[idx + 1].endswith("ого"):
                    tmp = word_list[idx + 1][:-3]
                    tmp += "ий"
                    for nr, name in _ORDINAL_BASE_UK.items():
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
            # Remove inflection from Ukrainian months
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

    time_qualifiers_am = _WORDS_MORNING_UK
    time_qualifiers_pm = ['дня', 'вечора']
    time_qualifiers_pm.extend(_WORDS_DAY_UK)
    time_qualifiers_pm.extend(_WORDS_EVENING_UK)
    time_qualifiers_pm.extend(_WORDS_NIGHT_UK)
    time_qualifiers_list = set(time_qualifiers_am + time_qualifiers_pm)
    markers = ['на', 'у', 'в', 'о', 'до', 'це',
               'біля', 'цей', 'через', 'після', 'за', 'той']
    days = ["понеділок", "вівторок", "середа",
            "четвер", "п'ятниця", "субота", "неділя"]
    months = _MONTHS_UK
    recur_markers = days + ['вихідні', 'вікенд']
    months_short = ["січ", "лют", "бер", "квіт", "трав", "червень", "лип", "серп",
                    "верес", "жовт", "листоп", "груд"]
    year_multiples = ["десятиліття", "століття", "тисячоліття", "тисячоліть", "століть",
                      "сторіччя", "сторіч"]

    words = clean_string(text)
    preposition = ""

    for idx, word in enumerate(words):
        if word == "":
            continue

        if word in markers:
            preposition = word

        word = _text_uk_inflection_normalize(word, 2)
        word_prev_prev = _text_uk_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        word_prev = _text_uk_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        word_next = _text_uk_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        word_next_next = _text_uk_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        start = idx
        used = 0
        if word in _WORDS_NOW_UK and not date_string:
            result_str = " ".join(words[idx + 1:])
            result_str = ' '.join(result_str.split())
            extracted_date = anchor_date.replace(microsecond=0)
            return [extracted_date, result_str]
        elif word_next in year_multiples:
            multiplier = None
            if is_numeric(word):
                multiplier = extract_number_uk(word)
            multiplier = multiplier or 1
            multiplier = int(multiplier)
            used += 2
            if word_next == "десятиліття" or word_next == "декада":
                year_offset = multiplier * 10
            elif word_next == "століття" or word_next == "сторіччя":
                year_offset = multiplier * 100
            elif word_next in ["тисячоліття", "тисячоліть"]:
                year_offset = multiplier * 1000
            elif word_next in ["тисяча", "тисячі", "тисяч"]:
                year_offset = multiplier * 1000
        elif word in time_qualifiers_list and preposition != "через" and word_next != "тому":
            time_qualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "сьогодні" and not from_flag:
            day_offset = 0
            used += 1
        elif word == "завтра" and not from_flag:
            day_offset = 1
            used += 1
        elif word == "післязавтра" and not from_flag:
            day_offset = 2
            used += 1
        elif word == "після" and word_next == "завтра" and not from_flag:
            day_offset = 2
            used += 2
        elif word == "позавчора" and not from_flag:
            day_offset = -2
            used += 1
        elif word == "вчора" and not from_flag:
            day_offset = -1
            used += 1
        elif (word in ["день", "дня", "дні", "днів"] and
              word_next == "після" and
              word_next_next == "завтра" and
              not from_flag and
              (not word_prev or not word_prev[0].isdigit())):
            day_offset = 2
            used = 2
        elif word in ["день", "дня", "дні", "днів"] and is_numeric(word_prev) and preposition == "через":
            if word_prev and word_prev[0].isdigit():
                day_offset += int(word_prev)
                start -= 1
                used = 2
        elif word in ["день", "дня", "дні", "днів"] and is_numeric(word_prev) and word_next == "тому":
            if word_prev and word_prev[0].isdigit():
                day_offset += -int(word_prev)
                start -= 1
                used = 3
        elif word in ["день", "дня", "дні", "днів"] and is_numeric(word_prev) and word_prev_prev == "на":
            if word_prev and word_prev[0].isdigit():
                day_offset += int(word_prev)
                start -= 1
                used = 2
        elif word == "сьогодні" and not from_flag and word_prev:
            if word_prev and word_prev[0].isdigit():
                day_offset += int(word_prev) * 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_UK:
                day_offset = 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_UK:
                day_offset = -7
                start -= 1
                used = 2
                # parse 10 months, next month, last month
        elif word == "тиждень" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                day_offset = int(word_prev) * 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_UK:
                day_offset = 7
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_UK:
                day_offset = -7
                start -= 1
                used = 2
        elif word == "тиждень" and not from_flag and is_numeric(word_prev) and word_next == "тому":
            if word_prev and word_prev[0].isdigit():
                day_offset = -int(word_prev) * 7
                start -= 1
                used = 3
        elif word == "місяць" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                month_offset = int(word_prev)
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_UK:
                month_offset = 1
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_UK:
                month_offset = -1
                start -= 1
                used = 2
        elif word == "місяць" and not from_flag and is_numeric(word_prev) and word_next == "тому":
            if word_prev and word_prev[0].isdigit():
                month_offset = -int(word_prev)
                start -= 1
                used = 3
        # parse 5 years, next year, last year
        elif word == "рік" and not from_flag and preposition in ["через", "на"]:
            if word_prev and word_prev[0].isdigit():
                if word_prev_prev and word_prev_prev[0].isdigit():
                    year_offset = int(word_prev) * int(word_prev_prev)
                else:
                    year_offset = int(word_prev)
                start -= 1
                used = 2
            elif word_prev in _WORDS_NEXT_UK:
                year_offset = 1
                start -= 1
                used = 2
            elif word_prev in _WORDS_PREV_UK:
                year_offset = -1
                start -= 1
                used = 2
            elif word_prev == "через":
                year_offset = 1
                used = 1
        elif word == "рік" and not from_flag and is_numeric(word_prev) and word_next == "тому":
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
            if word_prev in _WORDS_NEXT_UK:
                if day_offset <= 2:
                    day_offset += 7
                used += 1
                start -= 1
            elif word_prev in _WORDS_PREV_UK:
                day_offset -= 7
                used += 1
                start -= 1
        elif word in months or word in months_short and not from_flag:
            try:
                m = months.index(word)
            except ValueError:
                m = months_short.index(word)
            used += 1
            # Convert Ukrainian months to english
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
                # only a full four-digit number is a year; a shorter trailing
                # number (e.g. a clock hour) is left for the time parser
                if word_next and word_next.isdigit() and len(word_next) == 4:
                    date_string += " " + word_next
                    used += 1
                    has_year = True
                else:
                    has_year = False

            elif word_next and word_next[0].isdigit():
                date_string += " " + word_next
                used += 1
                if word_next_next and word_next_next.isdigit() and len(word_next_next) == 4:
                    date_string += " " + word_next_next
                    used += 1
                    has_year = True
                else:
                    has_year = False

        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        valid_followups = days + months + months_short
        valid_followups.append("сьогодні")
        valid_followups.append("завтра")
        valid_followups.append("післязавтра")
        valid_followups.append("вчора")
        valid_followups.append("позавчора")
        for followup in _WORDS_NEXT_UK:
            valid_followups.append(followup)
        for followup in _WORDS_PREV_UK:
            valid_followups.append(followup)
        for followup in _WORDS_CURRENT_UK:
            valid_followups.append(followup)
        for followup in _WORDS_NOW_UK:
            valid_followups.append(followup)
        if (word in ["до", "по", "з"]) and word_next in valid_followups:
            used = 2
            from_flag = True
            if word_next == "завтра":
                day_offset += 1
            elif word_next == "післязавтра":
                day_offset += 2
            elif word_next == "вчора":
                day_offset -= 1
            elif word_next == "позавчора":
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
                if word_next in _WORDS_NEXT_UK:
                    if day_offset <= 2:
                        tmp_offset += 7
                    used += 1
                    start -= 1
                elif word_next in _WORDS_PREV_UK:
                    tmp_offset -= 7
                    used += 1
                    start -= 1
                day_offset += tmp_offset
        if used > 0:
            if start - 1 > 0 and (words[start - 1] in _WORDS_CURRENT_UK):
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
        word = _text_uk_inflection_normalize(word, 1)
        word_prev_prev = _text_uk_inflection_normalize(
            words[idx - 2], 2) if idx > 1 else ""
        word_prev = _text_uk_inflection_normalize(
            words[idx - 1], 2) if idx > 0 else ""
        word_next = _text_uk_inflection_normalize(
            words[idx + 1], 2) if idx + 1 < len(words) else ""
        word_next_next = _text_uk_inflection_normalize(
            words[idx + 2], 2) if idx + 2 < len(words) else ""

        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "опівдні":
            hr_abs = 12
            used += 1
        elif word == "північ":
            hr_abs = 0
            used += 1
        elif word in _STRING_NUM_UK:
            val = _STRING_NUM_UK.get(word)
        elif word in _WORDS_MORNING_UK:
            if hr_abs is None:
                hr_abs = 8
            used += 1
        elif word in _WORDS_DAY_UK:
            if hr_abs is None:
                hr_abs = 15
            used += 1
        elif word in _WORDS_EVENING_UK:
            if hr_abs is None:
                hr_abs = 19
            used += 1
            if word_next != "" and word_next[0].isdigit() and ":" in word_next:
                used -= 1
        elif word in _WORDS_NIGHT_UK:
            if hr_abs is None:
                hr_abs = 22
        # parse half an hour, quarter hour
        #  should be added different variations oh "hour forms"
        elif word in ["година", "годину", "години"] and \
                (word_prev in markers or word_prev_prev in markers):
            if word_prev in ["пів", "половина", "опів на", "опів"]:
                min_offset = 30
            elif word_prev == "чверть":
                min_offset = 15
            # parse in an hour
            elif word_prev == "через":
                hr_offset = 1
            else:
                hr_offset = 1
            if word_prev_prev in markers:
                words[idx - 2] = ""
                if word_prev_prev in _WORDS_CURRENT_UK:
                    day_specified = True
            words[idx - 1] = ""
            used += 1
            hr_abs = -1
            min_abs = -1
            # parse 5:00 am, 12:00 p.m., etc
        # parse in a minute
        elif word == "хвилину" and word_prev == "через":
            min_offset = 1
            words[idx - 1] = ""
            used += 1
        # parse in a second
        elif word == "секунду" and word_prev == "через":
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
            if word_next in _WORDS_EVENING_UK or word_next in _WORDS_NIGHT_UK or word_next_next in _WORDS_EVENING_UK \
                    or word_next_next in _WORDS_NIGHT_UK or word_prev in _WORDS_EVENING_UK \
                    or word_prev in _WORDS_NIGHT_UK or word_prev_prev in _WORDS_EVENING_UK \
                    or word_prev_prev in _WORDS_NIGHT_UK or word_next_next_next in _WORDS_EVENING_UK \
                    or word_next_next_next in _WORDS_NIGHT_UK:
                remainder = "pm"
                used += 1
                if word_prev in _WORDS_EVENING_UK or word_prev in _WORDS_NIGHT_UK:
                    words[idx - 1] = ""
                if word_prev_prev in _WORDS_EVENING_UK or word_prev_prev in _WORDS_NIGHT_UK:
                    words[idx - 2] = ""
                if word_next_next in _WORDS_EVENING_UK or word_next_next in _WORDS_NIGHT_UK:
                    used += 1
                if word_next_next_next in _WORDS_EVENING_UK or word_next_next_next in _WORDS_NIGHT_UK:
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
                    hour = ["година", "годині"]
                    next_word = word_next.replace(".", "")
                    if next_word in ["am", "pm", "ночі", "ранку", "дня", "вечора"]:
                        remainder = next_word
                        used += 1
                    # question with the case "година"
                    elif next_word in hour and word_next_next in ["am", "pm", "ночи", "утра", "дня", "вечера"]:
                        remainder = word_next_next
                        used += 2
                    elif word_next in _WORDS_MORNING_UK:
                        remainder = "am"
                        used += 2
                    elif word_next in _WORDS_DAY_UK:
                        remainder = "pm"
                        used += 2
                    elif word_next in _WORDS_EVENING_UK:
                        remainder = "pm"
                        used += 2
                    elif word_next == "цього" and word_next_next in _WORDS_MORNING_UK:
                        remainder = "am"
                        used = 2
                        day_specified = True
                    elif word_next == "на" and word_next_next in _WORDS_DAY_UK:
                        remainder = "pm"
                        used = 2
                        day_specified = True
                    elif word_next == "на" and word_next_next in _WORDS_EVENING_UK:
                        remainder = "pm"
                        used = 2
                        day_specified = True
                    elif word_next == "в" and word_next_next in _WORDS_NIGHT_UK:
                        if str_hh and int(str_hh) > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 2
                    elif word_next == "о" and word_next_next in _WORDS_NIGHT_UK:
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
                        remainder == "вечора" or
                        word_next == "вечора"):
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
                            remainder == "вечора" or
                            word_next == "вечора"):
                        str_hh = str_num
                        remainder = "pm"
                        used = 1
                elif (
                        remainder == "am" or
                        word_next == "am" or
                        remainder == "a.m." or
                        word_next == "a.m." or
                        remainder == "ночі" or
                        word_next == "ночі" or
                        remainder == "ранку" or
                        word_next == "ранку" or
                        # "ранку" is normalized to "вранці" before this point,
                        # so match the whole morning group, not just one form
                        remainder in _WORDS_MORNING_UK or
                        word_next in _WORDS_MORNING_UK):
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
                        if word_next == "година":
                            used += 1
                    elif (
                            (word_next == "година" or word_next == "годину" or
                             remainder == "година") and
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
                    elif word_next == "хвилина" or \
                            remainder == "хвилина":
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
                        if (word_next_next == "година" or
                                remainder == "час"):
                            used += 1
                    elif (
                            word_next == "" or word_next == "година" or
                            (
                                    (word_next == "в" or word_next == "на") and
                                    (
                                            word_next_next == time_qualifier
                                    )
                            ) or word_next in _WORDS_EVENING_UK or
                            word_next_next in _WORDS_EVENING_UK):

                        str_hh = str_num
                        str_mm = "00"
                        if word_next == "година":
                            used += 1
                        if (word_next == "о" or word_next == "на"
                                or word_next_next == "о" or word_next_next == "на"):
                            used += (1 if (word_next ==
                                           "о" or word_next == "на") else 2)
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
                        elif remainder == "година":
                            if word_next_next in ["ночі", "ранку"]:
                                remainder = "am"
                                used += 1
                            elif word_next_next in ["дня", "вечора"]:
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
                    remainder not in ['am', 'pm', 'година', 'хвилина', 'секунда'] and
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
            elif word_prev == "пізніше":
                hr_offset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and word_prev in markers:
                words[idx - 1] = ""
                if word_prev in _WORDS_CURRENT_UK:
                    day_specified = True
            if idx > 1 and word_prev_prev in markers:
                words[idx - 2] = ""
                if word_prev_prev in _WORDS_CURRENT_UK:
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
        try:
            temp = datetime.strptime(date_string, "%B %d")
        except ValueError:
            # Try again, allowing the year
            try:
                temp = datetime.strptime(date_string, "%B %d %Y")
            except ValueError:
                # an impossible calendar date like "30 лютий"; report nothing
                # rather than a wrong guess
                return None
        extracted_date = extracted_date.replace(hour=0, minute=0, second=0)
        if not has_year:
            temp = temp.replace(year=extracted_date.year,
                                tzinfo=extracted_date.tzinfo)
            if extracted_date < temp:
                extracted_date = extracted_date.replace(
                    year=int(current_year),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extracted_date.tzinfo)
            else:
                extracted_date = extracted_date.replace(
                    year=int(current_year) + 1,
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extracted_date.tzinfo)
        else:
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
        if word == "і" and 0 < idx < len(words) - 1 and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    result_str = " ".join(words)
    result_str = ' '.join(result_str.split())
    return [extracted_date, result_str]


def nice_time_uk(dt, speech=True, use_24hour=True, use_ampm=False):
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
                string += " ночі"
            elif dt.hour < 12:
                string += " ранку"
            elif dt.hour < 18:
                string += " дня"
            else:
                string += " вечора"
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
            speak = pronounce_hour_uk(int(string[0]))
            if not speak:
                speak = pronounce_number_uk(int(string[0])) + ' '
            speak += pronounce_number_uk(int(string[1]))
        else:
            speak = pronounce_hour_uk(int(string[0:2]))
            if speak is None:
                speak = pronounce_number_uk(int(string[0:2]))

        speak += " "
        if string[3:5] == '00':
            speak += "рівно"
        else:
            if string[3] == '0':
                speak += pronounce_number_uk(0) + " "
                speak += pronounce_number_uk(int(string[4]))
            else:
                speak += pronounce_number_uk(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "опівночі"
        elif dt.hour == 12 and dt.minute == 0:
            return "опівдні"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        if dt.minute == 15:
            speak = "чверть після " + pronounce_hour_genitive_uk(hour)
        elif dt.minute == 30:
            speak = "половина після " + pronounce_hour_genitive_uk(hour)
        elif dt.minute == 45:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = "без четверті " + pronounce_hour_uk(next_hour)
        else:
            speak = pronounce_hour_uk(hour)

            if use_ampm:
                if dt.hour < 4:
                    speak += " ночі"
                elif dt.hour < 12:
                    speak += " ранку"
                elif dt.hour < 18:
                    speak += " дня"
                else:
                    speak += " вечора"

            if dt.minute == 0:
                if not use_ampm:
                    if dt.hour % 12 == 1:
                        return speak
                    # TODO: the `one`/`few`/`many` structure doesn't cover
                    #   all cases in Ukrainian
                    return speak + " " + plural_uk(dt.hour % 12, one="година",
                                                   few="години", many="годин")
            else:
                if dt.minute < 10:
                    speak += " нуль"
                speak += " " + pronounce_number_uk(dt.minute)

        return speak


def nice_duration_uk(duration, speech=True):
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
        out += pronounce_number_uk(days)
        out += " " + plural_uk(days, "день", "дня", "днів")
    if hours > 0:
        if out:
            out += " "
        out += pronounce_number_feminine_uk(hours)
        if out == 'один':
            out = 'одна'
        out += " " + plural_uk(hours, "година", "години", "годин")
    if minutes > 0:
        if out:
            out += " "
        out += pronounce_number_feminine_uk(minutes)
        out += " " + plural_uk(minutes, "хвилина", "хвилини", "хвилин")
    if seconds > 0:
        if out:
            out += " "
        out += pronounce_number_feminine_uk(seconds)
        out += " " + plural_uk(seconds, "секунда", "секунди", "секунд")

    return out


def pronounce_hour_uk(num):
    if num in HOURS_UK.keys():
        return HOURS_UK[num] + ' година'


def pronounce_mins_uk(num):
    if num in _NUM_STRING_UK.keys():
        if num == 1:
            return 'одна хвилина'
        if num == 2:
            return 'дві хвилини'
        if num in [10, 20, 30, 40, 50, 60]:
            _NUM_STRING_UK[num] + 'хвилин'
        else:
            return


def pronounce_hour_genitive_uk(num):
    if num in HOURS_UK.keys():
        if num == 3:
            gen_hour = HOURS_UK[num][:-1] + 'ьої'
        else:
            gen_hour = HOURS_UK[num][:-1] + 'ої'
        return gen_hour + ' години'


def pronounce_number_feminine_uk(num):
    pronounced = pronounce_number_uk(num)

    num %= 100
    if num % 10 == 1 and num // 10 != 1:
        return pronounced[:-2] + "на"
    elif num % 10 == 2 and num // 10 != 1:
        return pronounced[:-1] + "і"

    return pronounced


def plural_uk(num: int, one: str, few: str, many: str):
    num %= 100
    if num // 10 == 1:
        return many
    if num % 10 == 1:
        return one
    if 2 <= num % 10 <= 4:
        return few
    return many


def _text_uk_inflection_normalize(word, arg):
    """
    Ukrainian Inflection normalizer.

    This try to normalize known inflection. This function is called
    from multiple places, each one is defined with arg.

    Args:
        word [Word]
        arg [Int]

    Returns:
        word [Word]

    """

    if arg == 1:  # _extract_whole_number_with_text_uk
        if word in ["одна", "одним", "одно", "одною", "одного", "одної", "одному", "одній", "одного", "одну"]:
            return "один"
        return _plurals_normalizer(word)

    elif arg == 2:  # extract_datetime_uk
        if word in ["година", "години", "годин", "годину", "годин", "годинами"]:
            return "година"
        if word in ["хвилина", "хвилини", "хвилину", "хвилин", "хвилька"]:
            return "хвилина"
        if word in ["секунд", "секунди", "секундами", "секунду", "секунд", "сек"]:
            return "секунда"
        if word in ["днів", "дні", "днями", "дню", "днем", "днями"]:
            return "день"
        if word in ["тижні", "тижнів", "тижнями", "тиждень", "тижня"]:
            return "тиждень"
        if word in ["місяцем", "місяці", "місяця", "місяцях", "місяцем", "місяцями", "місяців"]:
            return "місяць"
        if word in ["року", "роки", "році", "роках", "роком", "роками", "років"]:
            return "рік"
        if word in _WORDS_MORNING_UK:
            return "вранці"
        if word in ["опівдні", "півдня"]:
            return "південь"
        if word in _WORDS_EVENING_UK:
            return "ввечері"
        if word in _WORDS_NIGHT_UK:
            return "ніч"
        if word in ["вікенд", "вихідних", "вихідними"]:
            return "вихідні"
        if word in ["столітті", "століттях", "століть"]:
            return "століття"
        if word in ["десятиліття", "десятиліть", "десятиліттях"]:
            return "десятиліття"
        if word in ["столітті", "століттях", "століть"]:
            return "століття"

        # Week days
        if word in ["понеділка", "понеділки"]:
            return "понеділок"
        if word in ["вівторка", "вівторки"]:
            return "вівторок"
        if word in ["середу", "середи"]:
            return "среда"
        if word in ["четверга"]:
            return "четвер"
        if word in ["п'ятницю", "п'ятниці"]:
            return "п'ятниця"
        if word in ["суботу", "суботи"]:
            return "субота"
        if word in ["неділю", "неділі"]:
            return "неділя"

        # Months
        if word in ["лютому", "лютого", "лютим"]:
            return "лютий"
        if word in ["листопада", "листопаді", "листопадом"]:
            return "листопад"
        tmp = ''
        if word[-3:] in ["ого", "ому"]:
            tmp = word[:-3] + "ень"
        elif word[-2:] in ["ні", "ня"]:
            tmp = word[:-2] + "ень"
        for name in _MONTHS_UK:
            if name == tmp:
                return name
    return word


def _plurals_normalizer(word):
    """
    Ukrainian Plurals normalizer.

    This function normalizes plural endings of numerals
    including different case variations.
    Uses _PLURALS dictionary with exceptions that can not
    be covered by rules.
    Args:
        word [Word]

    Returns:
        word [Word]

    """
    if word not in _STRING_NUM_UK:
        # checking for plurals 2-10
        for key, value in _PLURALS.items():
            if word == key:
                return _NUM_STRING_UK[value]

        # checking for plurals 11-19
        case_endings = ['надцяти', 'надцятим', 'надцятими',
                        'надцятьох', 'надцятьма', 'надцятьома', 'надцятьом']
        plural_case = ''.join([case for case in case_endings if case in word])
        if plural_case:
            if 'один' in word:
                return "одинадцять"
            word = word.replace(plural_case, '') + 'надцять'
            return word

        # checking for plurals 20,30
        case_endings = ['дцяти', 'дцятим', 'дцятими',
                        'дцятьох', 'дцятьма', 'дцятьома', 'дцятьом']
        plural_case = ''.join([case for case in case_endings if case in word])
        if plural_case:
            word = word.replace(plural_case, '') + 'дцять'
            return word

        # checking for plurals 50, 60, 70, 80
        case_endings = ['десятьох', 'десяти', 'десятьом',
                        'десятьма', 'десятьома']
        plural_case = ''.join([case for case in case_endings if case in word])
        if plural_case:
            word = word.replace(plural_case, '') + 'десят'
            return word

        # checking for plurals 90, 100
        case_endings = ['стам', 'стами', 'стах',
                        'стами', 'ста', 'сот']
        plural_case = ''.join([case for case in case_endings if case in word])
        if plural_case:
            word = word.replace(plural_case, '')
            for key, value in _PLURALS.items():
                if word == key:
                    firs_part = _NUM_STRING_UK[value]
                    if value in [3, 4]:
                        word = firs_part + 'ста'
                    elif value in [5, 6, 9]:
                        word = firs_part[:-1] + 'сот'
                    elif value in [7, 8]:
                        word = firs_part + 'сот'
                    return word
            return word
    return word
