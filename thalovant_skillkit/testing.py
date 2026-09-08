"""Message doubles for skill tests, so every skill stops inventing its own.

Thirteen skills hand-roll a fake message in their tests, and no two agree:
some are `type("Msg", (), {"data": ..., "context": ...})()`, some a `message()`
function, some set a language and some do not. That matters more than it looks.
A skill whose tests only ever build `{"utterance": ...}` with no language is
tested against a message the satellite never sends -- and reading the language
from the wrong place is exactly the bug that had skills answering in English
when asked in French.

The builder here produces what the satellite actually sends: the utterance in
`data`, the language and session in `context`, and the house's location when
one is given. It returns a real `ovos_bus_client.Message` when that is
installed, so a test exercises the same object production does, and a faithful
stand-in when it is not.
"""
from __future__ import annotations

from typing import Any

try:  # pragma: no cover - depends on the installed stack
    from ovos_bus_client.message import Message as _Message
except ImportError:  # pragma: no cover
    _Message = None


class _PlainMessage:
    """What a Message looks like to a skill, for environments without the bus."""

    def __init__(self, msg_type: str, data: dict, context: dict):
        self.msg_type = msg_type
        self.data = data
        self.context = context

    def __repr__(self) -> str:
        return f"<Message {self.msg_type} {self.data!r}>"


def message(
    utterance: str = "",
    *,
    lang: str | None = "en-US",
    session: dict | None = None,
    location: dict | None = None,
    site_id: str | None = None,
    msg_type: str = "recognizer_loop:utterance",
    context: dict | None = None,
    **data: Any,
):
    """A message shaped the way the satellite sends one.

    `lang` defaults to en-US rather than being left out, because a skill tested
    only against language-less messages is tested against something that never
    arrives.
    """
    payload: dict[str, Any] = {"utterance": utterance, "utterances": [utterance]}
    payload.update(data)
    if not utterance:
        payload.pop("utterances", None)

    ctx: dict[str, Any] = dict(context or {})
    if lang is not None:
        ctx.setdefault("lang", lang)
    if session is not None:
        ctx.setdefault("session", session)
    if location is not None:
        ctx.setdefault("location", location)
    if site_id is not None:
        ctx.setdefault("site_id", site_id)

    if _Message is not None:
        return _Message(msg_type, payload, ctx)
    return _PlainMessage(msg_type, payload, ctx)


#: Montreal, as the satellite attaches it. Without a location OVOS answers from
#: its own default -- Lawrence, Kansas -- so a skill that reports a time or a
#: forecast is tested an hour out and a continent away unless one is supplied.
MONTREAL = {
    "city": {
        "name": "Montreal",
        "state": {"name": "Quebec", "country": {"name": "Canada", "code": "CA"}},
    },
    "coordinate": {"latitude": 45.5019, "longitude": -73.5674},
    "timezone": {"code": "America/Toronto", "offset": -18000000, "dstOffset": 3600000},
}


class FakeBus:
    """A bus that records instead of sending.

    Enough for the two things skill tests do with one: register a fallback and
    check what the skill emitted.
    """

    def __init__(self):
        self.emitted: list[Any] = []
        self.handlers: dict[str, list] = {}

    def emit(self, msg: Any) -> None:
        self.emitted.append(msg)

    def on(self, msg_type: str, handler) -> None:
        self.handlers.setdefault(msg_type, []).append(handler)

    def remove(self, msg_type: str, handler) -> None:
        if handler in self.handlers.get(msg_type, []):
            self.handlers[msg_type].remove(handler)

    def once(self, msg_type: str, handler) -> None:
        self.on(msg_type, handler)

    def wait_for_response(self, msg: Any, *args, **kwargs):
        self.emit(msg)
        return None

    def of_type(self, msg_type: str) -> list[Any]:
        """Everything emitted of one type, in order."""
        return [m for m in self.emitted if getattr(m, "msg_type", None) == msg_type]

    def spoken(self) -> list[str]:
        """Every sentence the skill said."""
        return [
            str((getattr(m, "data", None) or {}).get("utterance") or "")
            for m in self.emitted
            if getattr(m, "msg_type", None) == "speak"
        ]
