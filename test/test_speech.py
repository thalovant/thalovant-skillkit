"""`speak_to`: the reply keeps the caller's context and language.

Every game in the fleet hand-built this message; what it had to get right is
what is tested here -- the spec topic, the forwarded session, the message's
language rather than the skill's, and the skill id in the context.
"""
from __future__ import annotations

import pytest

from thalovant_skillkit.speech import speak_to, speech_topic
from thalovant_skillkit.testing import FakeBus, message


class _Skill:
    skill_id = "thalovant-skill-demo"

    def __init__(self):
        self._bus = FakeBus()


def test_it_speaks_on_the_topic_the_installed_ovos_listens_on():
    skill = _Skill()

    sent = speak_to(skill, message("bonjour", lang="fr-FR"), "Salut")

    assert sent is skill._bus.emitted[0]
    assert sent.msg_type == speech_topic()
    assert speech_topic() in ("ovos.utterance.speak", "speak")


def test_the_reply_keeps_the_callers_session_and_language():
    skill = _Skill()
    incoming = message("bonjour", lang="fr-FR", session={"session_id": "alice"})

    sent = speak_to(skill, incoming, "Salut", expect_response=True)

    assert sent.data == {
        "utterance": "Salut",
        "expect_response": True,
        "meta": {"skill": "thalovant-skill-demo"},
        "lang": "fr-FR",
    }
    assert sent.context["session"]["session_id"] == "alice"
    assert sent.context["skill_id"] == "thalovant-skill-demo"


def test_an_explicit_language_and_written_form_travel_with_it():
    skill = _Skill()

    sent = speak_to(skill, message("hi"), "nine forty a.m.", lang="en-GB", written="9:40 AM",
                    meta={"origin": "test"})

    assert sent.data["lang"] == "en-GB"
    assert sent.data["utterance_written"] == "9:40 AM"
    assert sent.data["meta"] == {"origin": "test", "skill": "thalovant-skill-demo"}


def test_an_identical_written_form_is_not_sent_twice():
    skill = _Skill()

    sent = speak_to(skill, message("hi"), "same", written="same")

    assert "utterance_written" not in sent.data


def test_empty_text_says_nothing():
    skill = _Skill()

    assert speak_to(skill, message("hi"), "") is None
    assert skill._bus.emitted == []


def test_a_skill_without_a_bus_is_told_so_instead_of_losing_the_reply():
    class Unbound:
        skill_id = "unbound"

    with pytest.raises(RuntimeError, match="bus"):
        speak_to(Unbound(), message("hi"), "lost?")
