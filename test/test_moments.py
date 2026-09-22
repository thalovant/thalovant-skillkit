"""Saying a date and writing one are two different jobs."""
from datetime import datetime

import pytest

from thalovant_skillkit.moments import (
    WrittenForms,
    date_text,
    date_time_text,
    duration_text,
    english_ordinal,
    speak_with_written,
    time_text,
    uses_24_hour_clock,
)

DUE = datetime(2026, 9, 28, 0, 0)
NOW = datetime(2026, 9, 22, 18, 59)
SPELLED = ("twenty-eighth", "the twenty", "zero zero", "hundred", "o'clock")


@pytest.mark.parametrize("lang,expected", [("en-US", False), ("en-CA", False), ("fr-FR", True), ("de-DE", True)])
def test_the_locale_decides_the_clock(lang, expected):
    """CLDR records it; no list of languages is kept here."""
    assert uses_24_hour_clock(lang) is expected


@pytest.mark.parametrize(
    "day,expected",
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
     (11, "11th"), (12, "12th"), (13, "13th"),
     (21, "21st"), (22, "22nd"), (23, "23rd"), (31, "31st")],
)
def test_the_ordinal_handles_the_teens(day, expected):
    assert english_ordinal(day) == expected


@pytest.mark.parametrize("lang", ["en-US", "en-CA", "fr-FR", "de-DE", "es-ES"])
def test_a_written_day_is_a_number(lang):
    text = date_text(DUE, lang, NOW, written=True)

    assert "28" in text, f"{lang}: not a number -- {text!r}"
    assert "2026" not in text, f"{lang}: the year is noise -- {text!r}"
    for spelled in SPELLED:
        assert spelled not in text.lower(), f"{lang}: spelled out -- {text!r}"


def test_english_reads_the_day_as_an_ordinal():
    assert date_text(DUE, "en-US", NOW, written=True) == "Monday, 28th"


def test_a_spoken_day_is_still_spoken():
    """The written form is the new one; the spoken form is upstream's."""
    assert date_text(DUE, "en-US", NOW) == "monday, the twenty-eighth"


@pytest.mark.parametrize("lang", ["en-US", "fr-FR", "de-DE"])
@pytest.mark.parametrize("use_24hour", [True, False])
def test_a_written_clock_is_a_clock(lang, use_24hour):
    text = time_text(DUE, lang, use_24hour, written=True)

    assert ":" in text, f"{lang}: not a clock -- {text!r}"
    for spelled in SPELLED:
        assert spelled not in text.lower(), f"{lang}: spelled out -- {text!r}"


def test_near_days_stay_relative_in_both_forms():
    """"today" beats any date, however it is rendered."""
    today = datetime(2026, 9, 22, 9, 40)
    assert date_text(today, "en-US", NOW) == "today"
    assert date_text(today, "en-US", NOW, written=True) == "today"


def test_a_written_duration_is_a_clock():
    assert duration_text(300, "en-US", written=True) == "5:00"
    assert "minute" in duration_text(300, "en-US")


def test_the_day_and_the_clock_compose_in_the_locales_order():
    text = date_time_text(DUE, "en-US", NOW, written=True)

    assert "Monday, 28th" in text and ":" in text, text


class _Recorder:
    skill_id = "test.skill"

    def __init__(self):
        self.sent = []
        self.spoken = []
        self.bus = type("Bus", (), {"emit": lambda _s, m: self.sent.append(m)})()

    def speak(self, text):
        self.spoken.append(text)


def test_the_written_reply_is_built_by_substitution():
    """One render, then a swap -- a second render would repeat side effects."""
    WrittenForms.reset()
    WrittenForms.remember("nine forty a.m.", "9:40 AM")
    WrittenForms.remember("today", "today")  # identical: not worth a swap

    assert WrittenForms.render("Reminder set for today at nine forty a.m.: call mom.") == (
        "Reminder set for today at 9:40 AM: call mom."
    )


def test_a_longer_fragment_is_swapped_first():
    """A fragment inside another must not have its middle rewritten."""
    WrittenForms.reset()
    WrittenForms.remember("nine", "9:00")
    WrittenForms.remember("nine forty", "9:40")

    assert WrittenForms.render("at nine forty") == "at 9:40"


def test_speak_carries_the_written_form():
    skill = _Recorder()

    speak_with_written(skill, "said", None, "en-US", written="written")

    assert skill.sent, "nothing emitted"
    assert skill.sent[0].data["utterance"] == "said"
    assert skill.sent[0].data["utterance_written"] == "written"


def test_an_identical_written_form_is_not_sent():
    """A device with no screen should not be handed a duplicate."""
    skill = _Recorder()

    speak_with_written(skill, "same", None, "en-US", written="same")

    assert "utterance_written" not in skill.sent[0].data
