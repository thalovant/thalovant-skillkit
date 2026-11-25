"""Tell a connection's other open screens what changed, and nobody else.

One connection can be open on several screens at once: the Thalovant Board
copies its connection to a second browser, so an alarm set on a laptop belongs
on the board at home too. The hub sends a skill's reply only to the session
that asked (HIVEMIND-AGENT-1 §3.2: a response goes to the peers its
`destination` names), so the other screens would hear of the change at their
next question, and of a ring never.

This module keeps that rule and works inside it. It remembers, per owner, the
connection labels of the sessions that have spoken to this skill, and after a
reply that changed something, or a ring, the skill sends one
`thalovant.sync` message to each of that owner's OTHER sessions, naming that
one session in `destination`. The hub delivers it exactly as it delivers any
reply. Nothing in HiveMind changes.

Isolation rests on where a label comes from. `context["peer"]` is stamped by
hivemind-core on every message after every policy and transformer, and a
client cannot write it (see `owner.py`). A label is remembered only under the
owner read from that same stamp, so a session can only ever be sent another
session's news when the hub itself says both are the same client. Nothing a
client writes -- `site_id`, a session id, a claimed name -- picks a receiver.

A session is remembered only when it asked to be: its own message says
`"thalovant_sync": true` in its context (the Board does). That is a choice
about what IT receives and nothing else; it cannot add any other session. It
keeps clients that carry many people on one connection -- the chat bridges --
out entirely: they never ask, so one bridge user is never sent another's news.

Never shared:

* a message with no hub label (`LOCAL`, the runtime's own device): there is
  no other session to tell;
* the public preview bridge: one hub client that carries every visitor of a
  hub's web preview, told apart only by a session id the bridge declares, so
  a fan-out over its sessions would cross visitors;
* anything older than `TTL_SECONDS`, or beyond `MAX_PEERS` per owner (the
  oldest goes first): a session that left is dropped by the hub with a log
  line, and the list stays short.

Use (the alarm, reminder, timer and lists skills do):

    from thalovant_skillkit import sync

    peers = sync.Peers()                     # one per skill instance
    peers.seen(message.context)              # on every message a person sends
    sync.send(bus, peers, owner, exclude=[context.get("peer"), *sync.labels_in(context)],
              kind="alarm", meta={"schedule": [...]}, source=self.skill_id)

The message carries `meta` only -- the `schedule` the reply carried -- never
the spoken words: a screen redraws or rings from it, a client that does not
know the type ignores it.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from threading import Lock
from time import monotonic

from thalovant_skillkit import owner as owners

#: The bus type a connection's other sessions receive.
TYPE = "thalovant.sync"

#: The context key a session sets, on its own messages, to receive `TYPE`.
OPT_IN = "thalovant_sync"

#: How many sessions of one owner are remembered.
MAX_PEERS = 8

#: How long a session that has not spoken stays remembered. A board reads its
#: schedules every 30 minutes, so a live screen is never close to this.
TTL_SECONDS = 24 * 3600


class Peers:
    """The sessions each owner has spoken to this skill from, recently."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._by_owner: dict[str, OrderedDict[str, float]] = {}

    def seen(self, context: dict) -> None:
        """Remember the session `context` came from, under its owner.

        Only a session that asked (`OPT_IN`), on a message the hub stamped
        with a label, for an owner that is a single client (not `LOCAL`, not
        a preview visitor).
        """
        if not isinstance(context, dict) or context.get(OPT_IN) is not True:
            return
        label = context.get("peer")
        owner = owners.owner_of(context)
        if not shareable(owner) or owners.hub_client(label) is None:
            return
        now = self._clock()
        with self._lock:
            sessions = self._by_owner.setdefault(owner, OrderedDict())
            sessions.pop(label, None)
            sessions[label] = now
            while len(sessions) > MAX_PEERS:
                sessions.popitem(last=False)
            self._expire(now)

    def others(self, owner: str | None, exclude: Iterable[str] = ()) -> list[str]:
        """`owner`'s remembered sessions, except `exclude`, newest last."""
        if not shareable(owner):
            return []
        skip = set(exclude)
        now = self._clock()
        with self._lock:
            self._expire(now)
            sessions = self._by_owner.get(owner) or {}
            return [label for label in sessions if label not in skip]

    def _expire(self, now: float) -> None:
        for owner in list(self._by_owner):
            sessions = self._by_owner[owner]
            for label in [label for label, at in sessions.items() if now - at > TTL_SECONDS]:
                del sessions[label]
            if not sessions:
                del self._by_owner[owner]


def send(bus, peers: Peers, owner: str | None, *, exclude: Iterable[str] = (),
         kind: str, meta: dict, source: str) -> int:
    """Send `{kind, meta}` as `TYPE` to each of `owner`'s other sessions.

    One message per session, naming only that session in `destination`, so
    the hub delivers it as it delivers a reply and no session ever sees
    another's label. Returns how many were sent. Nothing for an owner that
    may not be shared, an empty `meta`, or no bus.
    """
    if bus is None or not meta:
        return 0
    from ovos_bus_client.message import Message

    sent = 0
    for peer in peers.others(owner, exclude=[item for item in exclude if item]):
        bus.emit(Message(TYPE, {"kind": kind, "meta": dict(meta)},
                         {"destination": [peer], "source": source, "skill_id": source}))
        sent += 1
    return sent


def shareable(owner: str | None) -> bool:
    """Whether an owner's news may go to its other sessions at all."""
    return bool(owner) and owner != owners.LOCAL and "|" not in owner


def labels_in(context: dict) -> list[str]:
    """The hub labels a message is already going to (its `destination`)."""
    value = context.get("destination") if isinstance(context, dict) else None
    values = value if isinstance(value, list) else [value]
    return [item for item in values if owners.hub_client(item) is not None]
