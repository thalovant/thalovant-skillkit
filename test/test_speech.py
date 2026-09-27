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
    """The spec topic on workshop 9, legacy `speak` on workshop 8."""
    skill = _Skill()

    sent = speak_to(skill, message("bonjour", lang="fr-FR"), "Salut")

    assert sent is skill._bus.emitted[0]
    assert sent.msg_type == speech_topic()
    assert speech_topic() in ("ovos.utterance.speak", "speak")


def test_the_reply_keeps_the_callers_session_and_language():
    """Forwarded, not rebuilt: the session and the message's language travel."""
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
    """`lang`, `written` and `meta` are additive on the same message."""
    skill = _Skill()

    sent = speak_to(skill, message("hi"), "nine forty a.m.", lang="en-GB", written="9:40 AM",
                    meta={"origin": "test"})

    assert sent.data["lang"] == "en-GB"
    assert sent.data["utterance_written"] == "9:40 AM"
    assert sent.data["meta"] == {"origin": "test", "skill": "thalovant-skill-demo"}


def test_an_identical_written_form_is_not_sent_twice():
    """A screen gets nothing extra when the written form is the spoken one."""
    skill = _Skill()

    sent = speak_to(skill, message("hi"), "same", written="same")

    assert "utterance_written" not in sent.data


def test_empty_text_says_nothing():
    """No reply is not an empty reply."""
    skill = _Skill()

    assert speak_to(skill, message("hi"), "") is None
    assert skill._bus.emitted == []


def test_a_skill_without_a_bus_is_told_so_instead_of_losing_the_reply():
    """The one place this happens is a test that forgot to bind a bus."""
    class Unbound:
        skill_id = "unbound"

    with pytest.raises(RuntimeError, match="bus"):
        speak_to(Unbound(), message("hi"), "lost?")


def test_the_topic_follows_the_workshop_that_will_deliver_it(monkeypatch):
    """Workshop 8 forwards on `speak`; a spec package beside it changes nothing."""
    import sys
    import types

    legacy = types.ModuleType("ovos_workshop.skills.ovos")  # no SpecMessage attribute
    monkeypatch.setitem(sys.modules, "ovos_workshop", types.ModuleType("ovos_workshop"))
    skills = types.ModuleType("ovos_workshop.skills")
    monkeypatch.setitem(sys.modules, "ovos_workshop.skills", skills)
    monkeypatch.setitem(sys.modules, "ovos_workshop.skills.ovos", legacy)
    skills.ovos = legacy

    assert speech_topic() == "speak"

    class _Spec:
        SPEAK = "ovos.utterance.speak"

    legacy.SpecMessage = _Spec
    assert speech_topic() == "ovos.utterance.speak"


def test_a_failed_reply_leaves_the_question_untouched():
    """No bus means no message was built, so nothing was stamped anywhere."""
    class Unbound:
        skill_id = "unbound"

    incoming = message("hi", session={"session_id": "alice"})
    with pytest.raises(RuntimeError):
        speak_to(Unbound(), incoming, "lost?")

    assert "skill_id" not in incoming.context


def test_a_built_sentence_sends_its_words_and_its_markup():
    """The words are the utterance; the markup travels beside them."""
    from thalovant_skillkit.ssml import pause, say

    skill = _Skill()

    sent = speak_to(skill, message("joke", session={"session_id": "alice"}),
                    say("Why?", pause("1s"), "Because."))

    assert sent.data["utterance"] == "Why? Because."
    assert type(sent.data["utterance"]) is str
    assert sent.data["utterance_ssml"] == '<speak>Why? <break time="1s"/> Because.</speak>'
    assert sent.context["session"]["session_id"] == "alice"


def test_markup_in_the_text_never_reaches_the_utterance():
    """A tag in `utterance` is shown and said as a tag by the Android app."""
    skill = _Skill()

    sent = speak_to(skill, message("hi"), "Wait <break time='1s'/> for it.")

    assert sent.data["utterance"] == "Wait for it."
    assert sent.data["utterance_ssml"] == "<speak>Wait <break time='1s'/> for it.</speak>"


def test_a_pause_alone_says_nothing():
    """No words, no message: a pause is not a reply."""
    from thalovant_skillkit.ssml import pause

    skill = _Skill()

    assert speak_to(skill, message("hi"), pause("1s")) is None
    assert skill._bus.emitted == []


def test_the_written_form_and_the_markup_travel_together():
    """A screen reads `utterance_written`, a voice reads `utterance_ssml`."""
    from thalovant_skillkit.ssml import emphasis, say

    skill = _Skill()

    sent = speak_to(skill, message("when"), say("At", emphasis("nine forty"), "a.m."),
                    written="At 9:40 AM")

    assert sent.data["utterance"] == "At nine forty a.m."
    assert sent.data["utterance_written"] == "At 9:40 AM"
    assert sent.data["utterance_ssml"] == (
        '<speak>At <emphasis level="moderate">nine forty</emphasis> a.m.</speak>')


def test_the_topic_is_what_the_installed_speak_emits():
    """Asked of `OVOSSkill.speak` itself: workshop 8 says `speak` even with
    the spec package installed beside it, workshop 9 the spec topic."""
    from ovos_workshop.skills.ovos import OVOSSkill

    from thalovant_skillkit import speech

    assert speech.speech_topic() == speech._observed_topic(OVOSSkill.speak)


def test_what_speak_emits_beats_what_its_module_imports(monkeypatch):
    """A workshop that imports SpecMessage but still speaks on `speak` is heard
    on `speak`; one whose speak() cannot be called is read from its module."""
    import sys
    import types

    from ovos_bus_client.message import Message

    from thalovant_skillkit import speech

    class _Spec:
        SPEAK = "ovos.utterance.speak"

    class LegacySpeaker:
        def speak(self, utterance, expect_response=False, wait=False, meta=None):
            self.bus.emit(Message("speak", {"utterance": utterance}))

    class Unprobeable:
        def speak(self, utterance, expect_response=False, wait=False, meta=None):
            raise RuntimeError("needs a real skill")

    module = types.ModuleType("ovos_workshop.skills.ovos")
    module.SpecMessage = _Spec
    monkeypatch.setitem(sys.modules, "ovos_workshop", types.ModuleType("ovos_workshop"))
    skills = types.ModuleType("ovos_workshop.skills")
    skills.ovos = module
    monkeypatch.setitem(sys.modules, "ovos_workshop.skills", skills)
    monkeypatch.setitem(sys.modules, "ovos_workshop.skills.ovos", module)

    module.OVOSSkill = LegacySpeaker
    assert speech.speech_topic() == "speak"
    module.OVOSSkill = Unprobeable
    assert speech.speech_topic() == "ovos.utterance.speak"
