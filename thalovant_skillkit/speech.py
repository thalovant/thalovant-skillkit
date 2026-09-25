"""Say something to the person who asked, from any skill.

`OVOSSkill.speak` finds the message it is answering by walking the call stack
(`dig_for_message`) and speaks in `self.lang`. That is right for a handler
answering the message it was handed, and wrong twice for a game: `converse()`
and the stop hooks run with a message that is not the one being answered, and
a hub serving a French room and an English one has a single `self.lang`.

So every game in the fleet, and the quiz tutorial, built the speak message by
hand -- a dozen lines that had to know the spec topic, forward the caller's
context and stamp the skill id, and that a first-time author was shown as
"how a skill speaks". This is that message, once. It forwards the incoming
message so the reply keeps its session, source and destination, speaks in
that message's language unless told otherwise, and uses the topic the
installed workshop's own `speak` uses.
"""
from __future__ import annotations

from typing import Any

from .message import message_lang


def speech_topic() -> str:
    """The topic the installed OVOS speaks on: the spec's, or the legacy one."""
    try:
        from ovos_spec_tools.messages import SpecMessage
    except Exception:  # noqa: BLE001 - older stacks predate the spec package
        return "speak"
    return str(getattr(SpecMessage.SPEAK, "value", SpecMessage.SPEAK))


def bus_of(skill: Any):
    """The bus a skill is bound to, or None.

    The raw attribute first: on a skill built for a test without a bus, the
    `bus` property raises its way out of `getattr`'s default.
    """
    bus = getattr(skill, "_bus", None)
    if bus is not None:
        return bus
    try:
        return skill.bus
    except Exception:  # noqa: BLE001 - unbound skills raise, and mean None
        return None


def speak_to(
    skill: Any,
    message: Any,
    text: str,
    *,
    lang: str | None = None,
    expect_response: bool = False,
    written: str | None = None,
    meta: dict | None = None,
):
    """Emit `text` as speech for whoever sent `message`, and return that message.

    `lang` defaults to the incoming message's language. `expect_response=True`
    asks the device to listen again, as OVOS's own `speak` does. `written` is
    an optional form for a screen (see `moments`); it travels beside the
    spoken text and a speaker without a screen never looks at it.

    Empty text emits nothing and returns None. A skill with no bus cannot
    speak; that raises rather than losing the reply quietly, because the only
    place it happens is a test that forgot to bind one.
    """
    if not text:
        return None
    skill_id = getattr(skill, "skill_id", "") or ""
    data: dict[str, Any] = {
        "utterance": text,
        "expect_response": bool(expect_response),
        "meta": {**(meta or {}), "skill": skill_id},
        "lang": lang or message_lang(message),
    }
    if written and written != text:
        data["utterance_written"] = written
    topic = speech_topic()
    forward = getattr(message, "forward", None)
    if callable(forward):
        speech = forward(topic, data)
    else:
        # A test double without `forward`: build the message ourselves and
        # carry the context across, which is the whole point of forwarding.
        from ovos_bus_client.message import Message

        speech = Message(topic, data, dict(getattr(message, "context", None) or {}))
    speech.context["skill_id"] = skill_id
    bus = bus_of(skill)
    if bus is None:
        raise RuntimeError("speak_to needs a bus: this skill is not bound to one")
    bus.emit(speech)
    return speech
