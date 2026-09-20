import datetime
import json
import os.path

from ovos_number_parser import pronounce_number


def _translate_word(keyword: str, lang: str) -> str:
    lang = lang.split("-")[0]
    p = f"{os.path.dirname(__file__)}/res/{lang}/date_words.json"
    if not os.path.isfile(p):
        raise NotImplementedError(f"Unsupported language: {lang} - please translate {p}")
    with open(p) as f:
        words = json.load(f)
    return words[keyword]


def nice_relative_time_generic(lang, when, relative_to):
    """Create a relative phrase to roughly describe a datetime

    Examples are "25 seconds", "tomorrow", "7 days".

    Args:
        lang (str): BCP-47 language code
        when (datetime): Local timezone
        relative_to (datetime): Baseline for relative time
    Returns:
        str: Relative description of the given time
    """
    delta = when - relative_to

    seconds = delta.total_seconds()
    if seconds < 1:
        try:
            return _translate_word("now", lang)
        except NotImplementedError:
            nice = pronounce_number(0, lang=lang)
            return f"{nice} " + _translate_word("seconds", lang)

    if seconds < 90:
        nice = pronounce_number(seconds, lang=lang)
        if seconds == 1:
            return f"{nice} " + _translate_word("second", lang)
        else:
            return f"{nice} " + _translate_word("seconds", lang)

    minutes = int((delta.total_seconds() + 30) // 60)  # +30 to round minutes
    if minutes < 90:
        nice = pronounce_number(minutes, lang=lang)
        if minutes == 1:
            return f"{nice} " + _translate_word("minute", lang)
        else:
            return f"{nice} " + _translate_word("minutes", lang)

    hours = int((minutes + 30) // 60)  # +30 to round hours
    if hours < 36:
        nice = pronounce_number(hours, lang=lang)
        if hours == 1:
            return f"{nice} " + _translate_word("hour", lang)
        else:
            return f"{nice} " + _translate_word("hours", lang)

    # TODO: "2 weeks", "3 months", "4 years", etc
    days = int((hours + 12) // 24)  # +12 to round days
    nice = pronounce_number(days, lang=lang)
    if days == 1:
        return f"{nice} " + _translate_word("day", lang)
    else:
        return f"{nice} " + _translate_word("days", lang)


def nice_duration_generic(lang, duration, speech=True):
    """ Convert duration in seconds to a nice spoken timespan

    Examples:
       duration = 60  ->  "1:00" or "one minute"
       duration = 163  ->  "2:43" or "two minutes forty three seconds"

    Args:
        lang (str): BCP-47 language code
        duration: time, in seconds
        speech (bool): format for speech (True) or display (False)

    Returns:
        str: timespan as a string
    """
    if isinstance(duration, datetime.timedelta):
        duration = duration.total_seconds()

    # Do traditional rounding: 2.5->3, 3.5->4, plus this
    # helps in a few cases of where calculations generate
    # times like 2:59:59.9 instead of 3:00.
    duration += 0.5

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    if speech:
        out = ""
        if days > 0:
            out += pronounce_number(days, lang) + " "
            if days == 1:
                out += _translate_word("day", lang)
            else:
                out += _translate_word("days", lang)
            out += " "
        if hours > 0:
            if out:
                out += " "
            out += pronounce_number(hours, lang) + " "
            if hours == 1:
                out += _translate_word("hour", lang)
            else:
                out += _translate_word("hours", lang)
        if minutes > 0:
            if out:
                out += " "
            out += pronounce_number(minutes, lang) + " "
            if minutes == 1:
                out += _translate_word("minute", lang)
            else:
                out += _translate_word("minutes", lang)
        if seconds > 0:
            if out:
                out += " "
            out += pronounce_number(seconds, lang) + " "
            if seconds == 1:
                out += _translate_word("second", lang)
            else:
                out += _translate_word("seconds", lang)
    else:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        out = ""
        if days > 0:
            out = str(days) + "d "
        if hours > 0 or days > 0:
            out += str(hours) + ":"
        if minutes < 10 and (hours > 0 or days > 0):
            out += "0"
        out += str(minutes) + ":"
        if seconds < 10:
            out += "0"
        out += str(seconds)

    return out
