from datetime import datetime, timedelta

import re
from ovos_number_parser.numbers_fa import pronounce_number_fa, _parse_sentence
from ovos_utils.time import now_local

_time_units = {
    'ثانیه': timedelta(seconds=1),
    'دقیقه': timedelta(minutes=1),
    'ساعت': timedelta(hours=1),
}

_date_units = {
    'روز': timedelta(days=1),
    'هفته': timedelta(weeks=1),
}


def extract_duration_fa(text):
    """
    Convert an english phrase into a number of seconds

    Convert things like:
        "10 minute"
        "2 and a half hours"
        "3 days 8 hours 10 minutes and 49 seconds"
    into an int, representing the total number of seconds.

    The words used in the duration will be consumed, and
    the remainder returned.

    As an example, "set a timer for 5 minutes" would return
    (300, "set a timer for").

    Args:
        text (str): string containing a duration

    Returns:
        (timedelta, str):
                    A tuple containing the duration and the remaining text
                    not consumed in the parsing. The first value will
                    be None if no duration is found. The text returned
                    will have whitespace stripped from the ends.
    """
    remainder = []
    ar = _parse_sentence(text)
    current_number = None
    result = None
    for x in ar:
        if x == "و":
            continue
        elif type(x) == tuple:
            current_number = x
        elif x in _time_units and current_number:
            result = (result or timedelta(0)) + _time_units[x] * current_number[0]
            current_number = None
        elif x in _date_units and current_number:
            result = (result or timedelta(0)) + _date_units[x] * current_number[0]
            current_number = None
        else:
            if current_number:
                remainder.extend(current_number[1])
            remainder.append(x)
            current_number = None
    if result is None:
        return None, text
    return result, " ".join(remainder)


def extract_datetime_fa(text, anchorDate=None, default_time=None):
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
        anchorDate (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """
    if not text:
        return None
    text = text.lower().replace('‌', ' ').replace('.', '').replace('،', '') \
        .replace('?', '').replace("پس فردا", "پسفردا") \
        .replace('یک شنبه', 'یکشنبه') \
        .replace('دو شنبه', 'دوشنبه') \
        .replace('سه شنبه', 'سهشنبه') \
        .replace('چهار شنبه', 'چهارشنبه') \
        .replace('پنج شنبه', 'پنجشنبه') \
        .replace('بعد از ظهر', 'بعدازظهر')

    if not anchorDate:
        anchorDate = now_local()
    today = anchorDate.replace(hour=0, minute=0, second=0, microsecond=0)
    today_weekday = int(anchorDate.strftime("%w"))
    weekday_names = [
        'دوشنبه',
        'سهشنبه',
        'چهارشنبه',
        'پنجشنبه',
        'جمعه',
        'شنبه',
        'یکشنبه',
    ]
    daysDict = {
        'پریروز': today + timedelta(days=-2),
        'دیروز': today + timedelta(days=-1),
        'امروز': today,
        'فردا': today + timedelta(days=1),
        'پسفردا': today + timedelta(days=2),
    }
    timesDict = {
        'صبح': timedelta(hours=8),
        'بعدازظهر': timedelta(hours=15),
    }
    exactDict = {
        'الان': anchorDate,
    }
    nextWords = ["بعد", "دیگه"]
    prevWords = ["پیش", "قبل"]
    ar = _parse_sentence(text)
    mode = 'none'
    number_seen = None
    delta_seen = timedelta(0)
    remainder = []
    result = None
    for x in ar:
        handled = 1
        if mode == 'finished':
            remainder.append(x)
        elif x == 'و' and mode[:5] == 'delta':
            pass
        elif type(x) == tuple:
            number_seen = x
        elif x in weekday_names:
            dayOffset = (weekday_names.index(x) + 1) - today_weekday
            if dayOffset < 0:
                dayOffset += 7
            result = today + timedelta(days=dayOffset)
            mode = 'time'
        elif x in exactDict:
            result = exactDict[x]
            mode = 'finished'
        elif x in daysDict:
            result = daysDict[x]
            mode = 'time'
        elif x in timesDict and mode == 'time':
            result += timesDict[x]
            mode = 'finish'
        elif x in _date_units:
            k = 1
            if (number_seen):
                k = number_seen[0]
                number_seen = None
            delta_seen += _date_units[x] * k
            if mode != 'delta_time':
                mode = 'delta_date'
        elif x in _time_units:
            k = 1
            if (number_seen):
                k = number_seen[0]
                number_seen = None
            delta_seen += _time_units[x] * k
            mode = 'delta_time'
        elif isinstance(x, str) and re.match(r'^\d{1,2}:\d{2}$', x):
            h, m = map(int, x.split(':'))
            if 0 <= h < 24 and 0 <= m < 60:
                base = result if result is not None else today
                result = base.replace(hour=h, minute=m)
                mode = 'finished'
            else:
                handled = 0
        elif x in nextWords or x in prevWords:
            # Give up instead of incorrect result
            if mode == 'time':
                return None
            sign = 1 if x in nextWords else -1
            if mode == 'delta_date':
                result = today + sign * delta_seen
                mode = 'time'
            elif mode == 'delta_time':
                result = anchorDate + sign * delta_seen
                mode = 'finished'
            else:
                handled = 0
        else:
            handled = 0
        if handled == 1:
            continue
        if number_seen:
            remainder.extend(number_seen[1])
            number_seen = None
        remainder.append(x)
    if result is None and mode == 'delta_date' and delta_seen:
        result = today + delta_seen
    elif result is None and mode == 'delta_time' and delta_seen:
        result = anchorDate + delta_seen
    if result is None:
        return None
    return [result, " ".join(remainder)]


def nice_time_fa(dt, speech=True, use_24hour=False, use_ampm=False):
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
            string = dt.strftime("%I:%M %p")
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
            speak += pronounce_number_fa(int(string[1]))
        else:
            speak = pronounce_number_fa(int(string[0:2]))
        if not string[3:5] == '00':
            speak += " و "
            if string[3] == '0':
                speak += pronounce_number_fa(int(string[4]))
            else:
                speak += pronounce_number_fa(int(string[3:5]))
            speak += ' دقیقه'
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "نیمه شب"
        elif dt.hour == 12 and dt.minute == 0:
            return "ظهر"

        hour = dt.hour % 12 or 12  # 12 hour clock and 0 is spoken as 12
        if dt.minute == 15:
            speak = pronounce_number_fa(hour) + " و ربع"
        elif dt.minute == 30:
            speak = pronounce_number_fa(hour) + " و نیم"
        elif dt.minute == 45:
            next_hour = (dt.hour + 1) % 12 or 12
            speak = "یه ربع به " + pronounce_number_fa(next_hour)
        else:
            speak = pronounce_number_fa(hour)

            if dt.minute == 0:
                if not use_ampm:
                    return speak
            else:
                speak += " و " + pronounce_number_fa(dt.minute) + ' دقیقه'

        if use_ampm:
            if dt.hour > 11:
                speak += " بعد از ظهر"
            else:
                speak += " قبل از ظهر"

        return speak
