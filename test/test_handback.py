"""Handing a sentence back to the other skills: silently, once, and remembered in the process only
(thalovant_skillkit.handback)."""

from __future__ import annotations

import pytest

from thalovant_skillkit import handback
from thalovant_skillkit.handback import UTTERANCE_TOPIC, HandBackMemory, hand_back
from thalovant_skillkit.testing import FakeBus, message

SKILL_ID = "thalovant-skill-demo.thalovant"


class _Skill:
    skill_id = SKILL_ID
    lang = "en-US"

    def __init__(self):
        self._bus = FakeBus()


def said(text="play a quiz", device="1999", session="sess-1", lang="en-US", **context):
    who = {"device": device, "device_name": f"client-{device}"} if device else {}
    return message(
        text,
        lang=lang,
        session={"session_id": session, "lang": lang},
        context={"thalovant_home": {"link": "none", **who}, "peer": "ua::1::x::s", **context},
    )


def test_the_sentence_goes_back_without_this_skill_and_nothing_else_is_written():
    """The recheck's proof of concept read `context["thalovant_music_passed_on"] is True` off the
    re-emitted utterance: a marker the client then saw on every answer. Nothing is marked now; the
    one thing written is the session's own `blacklisted_skills`, which is what leaves the skill
    out of the turn."""
    skill = _Skill()
    incoming = said()
    before = dict(incoming.context)

    assert hand_back(skill, incoming) is True

    (again,) = skill._bus.emitted
    assert again.msg_type == UTTERANCE_TOPIC
    assert again.data == {"utterances": ["play a quiz"], "lang": "en-US"}
    assert again.context["session"]["blacklisted_skills"] == [SKILL_ID]
    assert again.context["session"]["session_id"] == "sess-1"
    assert again.context["thalovant_home"]["device"] == "1999"  # still the same device
    added = set(again.context) - set(before)
    assert added == set(), added  # no marker key, of any name
    assert not [key for key in again.context if "passed" in key or "handback" in key.lower()]
    # the message that was handed over is not changed either
    assert incoming.context == before and "blacklisted_skills" not in incoming.context["session"]


@pytest.mark.parametrize(
    "marker", ["thalovant_music_passed_on", "thalovant_media_passed_on", "thalovant_passed_on"]
)
def test_a_marker_the_client_sends_does_not_buy_silence(marker):
    """The one-message probe: with the key pre-set the old code handed nothing back, so silence
    meant "the skill is here" and an answer meant "it is not". The key is not read any more."""
    skill = _Skill()
    assert hand_back(skill, said(**{marker: True})) is True
    assert len(skill._bus.emitted) == 1
    assert skill._bus.emitted[0].context[marker] is True  # carried on, like any unknown key


def test_the_same_sentence_coming_back_is_dropped_once_and_the_memory_is_the_process():
    skill = _Skill()
    assert hand_back(skill, said()) is True
    again = skill._bus.emitted[0]
    # a pipeline stage that ignored the blacklist brings it back to the same handler
    assert hand_back(skill, again) is False
    assert len(skill._bus.emitted) == 1  # no loop
    # the entry is spent: the same words said again are handed back again
    assert hand_back(skill, said()) is True
    assert len(skill._bus.emitted) == 2
    assert isinstance(skill.__dict__["_hand_back_memory"], HandBackMemory)


def test_the_same_words_said_again_a_moment_later_are_handed_back_again():
    """Found in review. Another skill answered the copy that was handed back, so nothing ever
    spent the entry; the same words said again within five seconds were then taken for that copy
    coming back and dropped: silence for a sentence another skill answers (and, for a stranger, a
    sign that a skill had stepped aside). A sentence said again does not leave this skill out of
    its session; the copy that comes back does. Only that one is dropped."""
    skill = _Skill()
    assert hand_back(skill, said()) is True
    assert hand_back(skill, said()) is True  # said again: the other skills get it again
    assert [m.context["session"]["blacklisted_skills"] for m in skill._bus.emitted] == [
        [SKILL_ID],
        [SKILL_ID],
    ]
    # and the copy that comes round again is still dropped, once
    assert hand_back(skill, skill._bus.emitted[1]) is False
    assert len(skill._bus.emitted) == 2


def test_the_same_words_said_many_times_are_every_one_handled():
    """Another skill answers the copy that was handed back, so nothing consumes the entry, and a
    bound on repeats dropped the fourth genuine "play a quiz" within five seconds (review of the
    pull request). Nothing the hub produces per turn reaches this code, so only the marker the
    copy carries may drop one."""
    skill = _Skill()
    memory = HandBackMemory()
    assert [hand_back(skill, said(), memory) for _ in range(8)] == [True] * 8
    assert len(skill._bus.emitted) == 8


def test_a_real_loop_still_ends_at_the_first_return():
    """A stage that ignores the blacklist but keeps the session brings the copy back WITH the
    marker: dropped, the entry is spent, and the loop is over after one round."""
    skill = _Skill()
    memory = HandBackMemory()
    for _ in range(4):
        assert hand_back(skill, said(), memory) is True
    assert hand_back(skill, skill._bus.emitted[-1], memory) is False  # the copy coming round
    assert len(skill._bus.emitted) == 4
    assert hand_back(skill, said(), memory) is True  # the next genuine one is handled


def test_a_blacklist_the_client_sends_buys_nothing_without_an_entry():
    """The session is the client's to write. With no entry in the memory, a message that already
    leaves this skill out is handed back like any other: the sign only narrows what the memory
    decided, it never decides."""
    skill = _Skill()
    forged = said()
    forged.context["session"]["blacklisted_skills"] = [SKILL_ID]
    assert hand_back(skill, forged) is True
    assert len(skill._bus.emitted) == 1


def test_a_sentence_the_bus_refused_is_not_remembered_as_handed_back(monkeypatch):
    """Found in review: when `emit` raised, the entry stayed, and the next try within five seconds
    was dropped as "coming back" though nothing had been sent."""
    skill = _Skill()
    memory = HandBackMemory()
    emit = skill._bus.emit

    def boom(*args, **kwargs):
        raise RuntimeError("bus down")

    monkeypatch.setattr(skill._bus, "emit", boom)
    assert hand_back(skill, said(), memory) is False
    assert len(memory) == 0
    monkeypatch.setattr(skill._bus, "emit", emit)
    assert hand_back(skill, said(), memory) is True  # the bus is back: handed back, not dropped
    again = skill._bus.emitted[0]
    # one failed try among good ones takes back its own count only
    assert hand_back(skill, said(), memory) is True
    monkeypatch.setattr(skill._bus, "emit", boom)
    assert hand_back(skill, said(), memory) is False
    monkeypatch.setattr(skill._bus, "emit", emit)
    assert len(memory) == 1 and hand_back(skill, said(), memory) is True  # still handled
    assert hand_back(skill, again, memory) is False  # the returning copy: dropped, entry forgotten
    assert len(memory) == 0
    memory.release(("never", "seen"))  # nothing to take back is not an error


def test_the_memory_is_per_device_session_sentence_and_skill():
    skill = _Skill()
    memory = HandBackMemory()
    assert hand_back(skill, said(), memory) is True
    assert hand_back(skill, said(device="2000"), memory) is True  # another device, same words
    assert hand_back(skill, said(session="sess-2"), memory) is True  # another session
    assert hand_back(skill, said("play a game"), memory) is True  # another sentence
    other = _Skill()
    other.skill_id = "another.skill"
    assert hand_back(other, said(), memory) is True  # another skill's own hand-back
    assert len(memory) == 5
    back = said("Play a QUIZ")  # the same words, folded: the first entry's copy coming back
    back.context["session"]["blacklisted_skills"] = [SKILL_ID]
    assert hand_back(skill, back, memory) is False
    assert len(skill._bus.emitted) == 4 and len(other._bus.emitted) == 1 and len(memory) == 4


def test_another_devices_session_id_cannot_spend_an_entry():
    """A session id is the client's own word. With the router's device id in the key, a stranger
    who copies somebody's session id and sentence neither gets nor causes silence."""
    skill = _Skill()
    memory = HandBackMemory()

    def back(device):
        copy = said(device=device, session="shared")
        copy.context["session"]["blacklisted_skills"] = [SKILL_ID]
        return copy

    assert hand_back(skill, said(device="1580", session="shared"), memory) is True
    assert hand_back(skill, back("1999"), memory) is True  # no entry of its own: nothing to spend
    assert hand_back(skill, back("1580"), memory) is False  # 1580's entry was still there
    assert hand_back(skill, back("1999"), memory) is False  # and so was the stranger's own


def test_an_entry_expires_and_the_memory_is_bounded():
    now = [100.0]
    memory = HandBackMemory(ttl=5.0, limit=3, clock=lambda: now[0])
    assert memory.first_time(("a",)) and not memory.first_time(("a",))  # spent by the second ask
    assert memory.first_time(("a",))
    now[0] += 5.0
    assert memory.first_time(("a",))  # expired: as if never seen
    for key in "bcd":
        assert memory.first_time((key,))
    assert len(memory) == 3  # ("a",) was the oldest and went
    assert memory.first_time(("a",))
    now[0] += 60.0
    assert memory.first_time(("z",)) and len(memory) == 1  # everything else expired
    assert HandBackMemory(limit=0).limit == 1


def test_an_existing_blacklist_is_kept_and_this_skill_is_listed_once():
    skill = _Skill()
    incoming = said()
    incoming.context["session"]["blacklisted_skills"] = ["other.skill", 7, SKILL_ID]
    assert hand_back(skill, incoming) is True
    assert skill._bus.emitted[0].context["session"]["blacklisted_skills"] == [
        "other.skill",
        SKILL_ID,
    ]
    odd = said("x")
    odd.context["session"] = "not a dict"
    assert hand_back(skill, odd) is True
    assert skill._bus.emitted[1].context["session"] == {"blacklisted_skills": [SKILL_ID]}


def test_the_reply_language_is_the_messages_own():
    skill = _Skill()
    hand_back(skill, said("joue un quiz", lang="fr-FR"))
    assert skill._bus.emitted[0].data["lang"] == "fr-FR"


def test_nothing_to_hand_back_is_a_no_and_never_an_error(monkeypatch):
    skill = _Skill()
    assert hand_back(skill, said("")) is False  # no words
    nameless = _Skill()
    nameless.skill_id = ""
    assert hand_back(nameless, said()) is False

    class Unbound:
        skill_id = SKILL_ID

        @property
        def bus(self):
            raise RuntimeError("not bound")

    assert hand_back(Unbound(), said()) is False

    def boom(*args, **kwargs):
        raise RuntimeError("bus down")

    monkeypatch.setattr(skill._bus, "emit", boom)
    assert hand_back(skill, said()) is False  # silence is the safe failure
    assert hand_back(skill, None) is False and hand_back(None, said()) is False


def test_the_module_reads_no_context_key_to_decide():
    """The decision is the memory's. Reading a key off the context to decide would be new code
    this test has to see."""
    import inspect

    code = inspect.getsource(handback.hand_back)
    assert "passed_on" not in code and "context.get(" in code
    decided_by = [line for line in code.splitlines() if "memory.admit(" in line]
    assert len(decided_by) == 1
    # what it reads off the session is the framework's own list, and only beside the memory
    assert code.count('session.get("blacklisted_skills")') == 1


def test_a_skill_hands_back_with_pass_on(monkeypatch):
    from thalovant_skillkit.skill import ThalovantSkill

    skill = ThalovantSkill.__new__(ThalovantSkill)
    bus = FakeBus()
    monkeypatch.setattr(ThalovantSkill, "bus", property(lambda self: bus), raising=False)
    monkeypatch.setattr(ThalovantSkill, "skill_id", SKILL_ID, raising=False)
    monkeypatch.setattr(ThalovantSkill, "lang", "en-US", raising=False)
    assert skill.pass_on(said()) is True
    assert bus.emitted[0].context["session"]["blacklisted_skills"] == [SKILL_ID]
    assert skill.pass_on(bus.emitted[0]) is False and len(bus.emitted) == 1
