"""Whose items these are: the client the hub says sent the message.

A HiveMind client writes every field of a message itself except the few the
hub stamps on the way in, so nothing it says may decide whose items it
reaches. The owner used to be the first of `client_id`, `site_id`,
`session.site_id`... the device sent. A phone's `site_id` is the short name it
was paired under ("galaxy-s24"), so any other device on the same hub could say
that name and list, cancel, snooze or stop that person's alarms, reminders,
timers and stopwatches.

This module is the one copy: the alarm, reminder, timer, stopwatch and lists
skills each carried their own until skillkit 0.40.0. Import it as
`from thalovant_skillkit import owner as owners`.

What the hub sets, and the device cannot, is the connection label
hivemind-core stamps on `context["peer"]` after every policy and transformer
(HiveMind-core 5.3.3a1 `protocol.py`, `handle_inject_agent_msg`):

    <name the software announces>::<hub database number>::<hub database name>::<declared session>

The listener builds the first three fields (`f"{useragent}::{user.client_id}::
{user.name}"` in the WebSocket and HTTP protocols, the access key first on
MQTT) and refuses an announced name with a colon in it, so the third field is
always the hub's own database name for the client. On a Thalovant hub that is
`client-<the API's client uuid>`, written by the operator from the API's own
record. That is the owner: one per client, the same across reconnects, hub
restarts and a lost hub database, and never handed to another client (a client
deleted and created again gets a new uuid).

The session id's prefix is also the hub's, but not used here: it hashes the
hub database *number*, which the operator hands out again once a hub's last
client is removed (the id sequence is deleted with it), and it falls back to
a per-connection random value whenever the hub cannot read its database.
"""
from __future__ import annotations

import re
from typing import Any

#: Everything said on the device the runtime itself runs on. A message that
#: never crossed HiveMind carries no connection label at all; hivemind-core
#: stamps one on every message a client sends, so no client can reach these.
LOCAL = "default"

#: The rule an item's `owner` was decided by. An item stored under an older
#: rule, or none, is decided again once from what it recorded (`migrate`).
SCHEME = 2

_LABEL = re.compile(r"[^:]*::\d+::([^:]+)::")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: The public preview bridge: one hub client that every visitor of a hub's web
#: preview talks through. Its visitors are told apart by the conversation the
#: bridge declares for each, behind the hub's prefix.
_PREVIEW_BRIDGE = re.compile(rf"hub-{_UUID}-preview-bridge")


def hub_client(label: Any) -> str | None:
    """The hub's database name for the client in a connection label, or None."""
    if not isinstance(label, str):
        return None
    match = _LABEL.match(label)
    return match.group(1) if match else None


def owner_of(context: dict) -> str | None:
    """Whose items a message reaches, or None when nobody can be named.

    Read from `context["peer"]` and, for the preview bridge only,
    `context["session"]["session_id"]`: the two things hivemind-core rewrites
    on every message before a skill sees it. Nothing else in the context is
    read. A message with no label at all never crossed HiveMind and is
    `LOCAL`; one whose label does not read as the hub's is nobody's.
    """
    if "peer" not in context:
        return LOCAL
    name = hub_client(context["peer"])
    if name is None or not _PREVIEW_BRIDGE.fullmatch(name):
        return name
    session = context.get("session")
    session_id = session.get("session_id") if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not session_id:
        return None
    return f"{name}|{session_id}"


def limit_group(owner: str | None) -> str | None:
    """Whose limit an item counts against: its owner, except a preview visitor.

    Every visitor of the web preview counts against one limit, the bridge's,
    as when they all shared one list: a visitor can open as many
    conversations as they like, and a limit per conversation would be none.
    """
    if owner is None:
        return None
    name, separator, _ = owner.partition("|")
    return name if separator and _PREVIEW_BRIDGE.fullmatch(name) else owner


def owns(item: dict, owner: str | None) -> bool:
    """Whether `item` is `owner`'s. An item that is nobody's is never anybody's."""
    return owner is not None and item.get("owner") == owner


def asked_by(context: dict, message: Any) -> dict:
    """`context`, with who is asking taken from `message` and nowhere else.

    A skill API call (`preview_reply`) carries the context it wants used in
    its data, where its caller can write anything, a connection label
    included. Only the bus message around it went through the hub, so the
    label and the session id (which tells the preview bridge's visitors
    apart) are that message's. A bus message with no label, or none at all,
    never crossed HiveMind: the call came from this runtime and is `LOCAL`.
    """
    trusted = {key: value for key, value in context.items() if key != "peer"}
    stamped = message.context if message is not None else {}
    if "peer" not in stamped:
        return trusted
    trusted["peer"] = stamped["peer"]
    session = context.get("session")
    session = dict(session) if isinstance(session, dict) else {}
    session.pop("session_id", None)
    stamped_session = stamped.get("session")
    if isinstance(stamped_session, dict) and "session_id" in stamped_session:
        session["session_id"] = stamped_session["session_id"]
    trusted["session"] = session
    return trusted


def recorded_owner(item: dict) -> str | None:
    """The owner an item's own stored routing names, never its old `owner`.

    An item set by voice since September 2026 (alarm 0.1.9, reminder 0.1.7,
    timer 0.1.8) keeps the context it is announced in, and the hub's label is
    in it: `destination` once ovos-core has replied to the utterance, `source`
    on a message the client sent directly. The hub wrote both, so this names
    the client that really set it, whatever name it claimed. An item set
    through `preview_reply` kept the context its caller wrote instead; on a
    public hub only the platform's preview bridge may call that, and it
    writes no label. An item with no label belongs to nobody, unless it was
    already the local device's (`LOCAL`).
    """
    context = item.get("context")
    context = context if isinstance(context, dict) else {}
    labels = []
    for key in ("source", "destination"):
        value = context.get(key)
        for candidate in value if isinstance(value, list) else [value]:
            if hub_client(candidate) is not None and candidate not in labels:
                labels.append(candidate)
    if not labels:
        return LOCAL if item.get("owner") in (None, "", LOCAL) else None
    if len(labels) > 1:
        return None
    return owner_of({"peer": labels[0], "session": context.get("session")})


def migrate(items: list) -> bool:
    """Decide again the owner of every item stored under an older rule.

    Returns whether anything changed, so the caller saves once. The old
    `owner` value is never carried over: it is what a device claimed.
    """
    changed = False
    for item in items:
        if not isinstance(item, dict) or item.get("owner_scheme") == SCHEME:
            continue
        item["owner"] = recorded_owner(item)
        item["owner_scheme"] = SCHEME
        changed = True
    return changed
