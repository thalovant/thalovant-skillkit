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

The same message carries speech markup: `utterance_ssml` beside the plain
`utterance` when the text is an `ssml.Speech` with markup. See `ssml`.
"""
from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from .message import message_lang
from .ssml import SSML_KEY, speech_parts


def speech_topic() -> str:
    """The topic the installed workshop's own `speak()` emits on.

    ovos-workshop 9 speaks on the spec topic (`ovos.utterance.speak`);
    workshop 8 speaks on the legacy `speak`, whether or not the spec package
    is installed beside it, and hubs run with `OVOS_BUS_EMIT_LEGACY=false`,
    so nothing mirrors one onto the other. A reply on a topic the installed
    listeners do not hear is a reply nobody hears.

    So the installed `OVOSSkill.speak` is asked: it is called once, on a
    stand-in skill whose bus only records, and the topic it emitted is the
    answer for the life of the process. No version number is compared, and
    nothing reaches a real bus. If that call cannot be made, the module that
    owns `speak()` is read instead -- workshop 9 imports `SpecMessage` into
    it, workshop 8 does not -- and without a workshop, the spec package.
    """
    try:
        from ovos_workshop.skills import ovos as workshop
    except Exception:  # noqa: BLE001 - no workshop: fall through to the spec package
        workshop = None
    if workshop is not None:
        skill_class = getattr(workshop, "OVOSSkill", None)
        speak = getattr(skill_class, "speak", None)
        observed = _observed_topic(speak) if callable(speak) else None
        if observed:
            return observed
        spec = getattr(workshop, "SpecMessage", None)
        if spec is None:
            return "speak"
        return str(getattr(spec.SPEAK, "value", spec.SPEAK))
    try:
        from ovos_spec_tools.messages import SpecMessage
    except Exception:  # noqa: BLE001 - older stacks predate the spec package
        return "speak"
    return str(getattr(SpecMessage.SPEAK, "value", SpecMessage.SPEAK))


class _RecordingBus:
    def __init__(self):
        self.emitted: list[Any] = []

    def emit(self, message: Any) -> None:
        self.emitted.append(message)


@lru_cache(maxsize=4)
def _observed_topic(speak) -> str | None:
    """The topic `speak` emits on, seen by calling it once, or None."""
    bus = _RecordingBus()
    stand_in = SimpleNamespace(skill_id="thalovant-skillkit.topic-probe", lang="en-US", bus=bus)
    try:
        speak(stand_in, "topic probe")
    except Exception:  # noqa: BLE001 - an unexpected workshop: read its module instead
        return None
    if len(bus.emitted) != 1:
        return None
    topic = getattr(bus.emitted[0], "msg_type", None)
    topic = getattr(topic, "value", topic)
    return str(topic) if topic else None


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


def emit_speech(
    skill: Any,
    message: Any,
    text: str,
    *,
    lang: str,
    expect_response: bool = False,
    written: str | None = None,
    meta: dict | None = None,
    wait: bool | int = False,
    ssml: str | None = None,
):
    """Build one speak message, emit it, and wait on it if asked; return it.

    The message `OVOSSkill.speak` builds, with room for the forms a client may
    use beside the words: `utterance_written` for a screen and
    `utterance_ssml` for a voice that reads markup. `message` is the message
    being answered, forwarded so the reply keeps its session; None sends a
    fresh one, as `speak` does when it finds nothing to answer. `wait` is
    `speak`'s: True waits up to 15 seconds for the words to be heard, a
    number that many seconds.
    """
    bus = bus_of(skill)
    if bus is None:
        raise RuntimeError("this skill is not bound to a bus, so it cannot speak")
    skill_id = getattr(skill, "skill_id", "") or ""
    meta = {**(meta or {}), "skill": skill_id}
    data: dict[str, Any] = {
        "utterance": text,
        "expect_response": bool(expect_response),
        "meta": meta,
        "lang": lang,
    }
    if written and written != text:
        data["utterance_written"] = written
    if ssml:
        data[SSML_KEY] = ssml
    topic = speech_topic()
    forward = getattr(message, "forward", None)
    if callable(forward):
        speech = forward(topic, data)
    else:
        # No message, or a test double without `forward`: build the message
        # ourselves and carry any context across, which is the whole point.
        from ovos_bus_client.message import Message

        speech = Message(topic, data, dict(getattr(message, "context", None) or {}))
    speech.context["skill_id"] = skill_id
    if "translation_data" in meta:
        # As `speak` does: auto-translation metadata rides on the context.
        from ovos_utils.json_helper import merge_dict

        speech.context["translation_data"] = merge_dict(
            speech.context.get("translation_data", {}), meta["translation_data"])
    bus.emit(speech)
    if wait:
        from ovos_bus_client.session import SessionManager

        session = SessionManager.get(speech)
        session.is_speaking = True
        SessionManager.wait_while_speaking(15 if isinstance(wait, bool) else wait, session)
    return speech


def speak_to(
    skill: Any,
    message: Any,
    text: str,
    *,
    lang: str | None = None,
    expect_response: bool = False,
    written: str | None = None,
    meta: dict | None = None,
    wait: bool | int = False,
):
    """Emit `text` as speech for whoever sent `message`, and return that message.

    `lang` defaults to the incoming message's language. `expect_response=True`
    asks the device to listen again, as OVOS's own `speak` does, and `wait`
    blocks until it has been heard, as `speak(wait=...)` does. `written` is
    an optional form for a screen (see `moments`); it travels beside the
    spoken text and a speaker without a screen never looks at it.

    `text` may be a `ssml.Speech`: its words are the utterance and its markup
    travels as `utterance_ssml`. A plain string holding SSML tags is moved
    the same way, so the tags never reach a client that shows `utterance`.

    Empty text emits nothing and returns None. A skill with no bus cannot
    speak; that raises rather than losing the reply quietly, because the only
    place it happens is a test that forgot to bind one.
    """
    text, ssml = speech_parts(text, getattr(skill, "skill_id", None))
    if not text:
        return None
    # Fail before building anything: a reply that cannot be sent should not
    # cost a message, and the reason should be the first thing reported.
    if bus_of(skill) is None:
        raise RuntimeError("speak_to needs a bus: this skill is not bound to one")
    return emit_speech(skill, message, text, lang=lang or message_lang(message),
                       expect_response=expect_response, written=written, meta=meta,
                       wait=wait, ssml=ssml)
