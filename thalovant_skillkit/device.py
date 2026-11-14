"""Who is speaking and what their household has linked, as the HUB says it: the router's stamp.

A skill that serves one household's private thing (a media server, the lights) must know
which of the hub's devices asked, and refuse the others: a public hub has strangers on it. The one
place that knowledge is trustworthy is the stamp the hub's home router
writes into the context of every utterance it vouches for:

    context["thalovant_home"] = {"link": "online", "device": "1580", "device_name": "client-1"}
    context["thalovant_connector"] = {"link": {"music_assistant": "online"},
                                      "device": "1580", "device_name": "client-1"}

`device` is the database id of the connection's row and `device_name` its platform-assigned name;
the router writes both from the row and overwrites whatever a client put there, and writes neither
for a connection it will not vouch for (a preview or chat bridge, a connection without an account).
`link` says whether the device's OWN household has a link to a service at home, and whether it is
up. Everything else that looks like an identity is the client's own word and is NEVER read here:
`context["peer"]` is `<useragent>::<id>::<name>::<session>` where the user agent and the session are
client-supplied (a session called `x::1580::y` makes the tail read as another client's id), and
`source`, `site_id`, `client_id` and the session's own copies are no better. This module has no
function that reads any of them, so a skill cannot reintroduce the spoof by accident.

This is the ONE gate. Two questions, two answers:

    from thalovant_skillkit.device import device_allowed, link_allowed

    # A route through the household's own link (a home bridge, Home Assistant): the router
    # confines every household to its own, so the gate is "does this household have one".
    if not link_allowed(message.context, "music_assistant"):
        return self.pass_on(message)

    # A route with ONE server for the whole hub (a URL and a token in the skill's settings):
    # deny by default, the hub's owner lists the devices.
    if not device_allowed(message.context, self.allowed_devices):
        return self.pass_on(message)

The identity is the `device` id, a string of ASCII digits. A stamp without one names nobody: a
stamp that carries only `device_name` is ignored (the name is a label the platform assigns, and a
label is not an identity). An allow-list compares ids with ids and names with names: an entry made
of digits is a device id and is never compared with a name, so a row NAMED `1580` does not pass a
list that holds the id `1580`.

No stamp, a stamp without a usable `device`, an empty allow-list, or any doubt: no identity, and
the gate says no. The retired per-service stamps of earlier routers (`thalovant_music`) are not
believed either: a client could write that key itself, and nothing but the router's own keys is
trusted.

`thalovant_home` DECIDES: every router since 0.4.1 overwrites it on every client utterance.
`thalovant_connector` (router 0.5.0) is believed only when it names the same device: before 0.5.0
nothing overwrote it, so a client of an older hub could write its own and the first stamp found
would have won. A stamp that is missing, names nobody, or disagrees with the other one means
nobody, whichever key it is under; one is never "skipped".

The limit, said plainly: the gate cannot tell WHO wrote the keys. On a hub whose listener does not
load the home router nothing overwrites them, so a client can send its own stamp and be believed.
The stamp is an identity only on a hub that runs the router; a route with one server for the whole
hub (`device_allowed`) must stay off on a hub that is shared and does not.

A skill whose kit floor is older than this module imports it behind a guard (`docs/reference.md`,
"Older kits"), and the guard's fallback is to deny everyone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from .text import fold

__all__ = [
    "LINKED",
    "LINK_STATES",
    "STAMP_KEYS",
    "DeviceIdentity",
    "device_allowed",
    "device_identity",
    "device_value",
    "link_allowed",
    "link_state",
]

#: The context keys the router owns: `thalovant_home` (decides) and `thalovant_connector`
#: (must agree). Nothing else is believed.
STAMP_KEYS: tuple[str, ...] = ("thalovant_home", "thalovant_connector")

#: What the router says about a household's link to a service at home.
LINK_STATES: tuple[str, ...] = ("online", "offline", "none", "unavailable")
#: The states that mean "this household has that link" (whether or not it is up right now).
LINKED: frozenset[str] = frozenset({"online", "offline"})

#: The prefix the platform gives a connection's row name (`client-<uuid>`); the console shows the
#: name without it.
_ROW_PREFIX = "client-"

_V = TypeVar("_V")


def _is_id(text: Any) -> bool:
    return isinstance(text, str) and bool(text) and text.isascii() and text.isdigit()


def _entry(entry: Any) -> tuple[str, str] | None:
    """An allow-list entry as `("id", "1580")` or `("name", <folded>)`, or None when it is neither.

    Digits are an id, typed as a string or as a number. Anything else is a name. An entry that only
    LOOKS like digits once folded (fullwidth `１５８０`) is neither: it is not an id as the router
    writes one, and as a name it could only ever match a row named after somebody's id.
    """
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int):
        return ("id", str(entry)) if entry >= 0 else None
    if not isinstance(entry, str):
        return None
    text = entry.strip()
    if _is_id(text):
        return "id", text
    folded = fold(text)
    if not folded or folded.isdigit():
        return None
    return "name", folded


@dataclass(frozen=True)
class DeviceIdentity:
    """The speaking device as the hub vouches for it: its id, and the label beside it."""

    device_id: str
    name: str | None = None

    @property
    def names(self) -> tuple[str, ...]:
        """The labels the hub gave this device: its row name, and the row name without the
        platform's `client-` prefix (so a device can be listed by the name the console shows)."""
        if not self.name:
            return ()
        if self.name.lower().startswith(_ROW_PREFIX) and len(self.name) > len(_ROW_PREFIX):
            return self.name, self.name[len(_ROW_PREFIX) :]
        return (self.name,)

    @property
    def keys(self) -> tuple[str, ...]:
        """The id, then the labels. For a log line or a cache key; to compare with what an owner
        typed, use `matches` or `device_value`, which never read a label as an id."""
        return (self.device_id, *self.names)

    def matches(self, entry: Any) -> bool:
        """Whether `entry` (one line of an allow-list or a mapping) names this device: an id with
        the id, exactly; a name with a label, folded and whole. Never one with the other, and a
        label made of digits matches nothing."""
        kind = _entry(entry)
        if kind is None:
            return False
        if kind[0] == "id":
            return kind[1] == self.device_id
        return any(fold(name) == kind[1] for name in self.names if not fold(name).isdigit())

    def value_in(self, mapping: Mapping[Any, _V] | None) -> _V | None:
        """What a per-device mapping says for this device, or None: the entry keyed by its id
        first, then the first one keyed by a label. A mapping that raises maps nobody."""
        if not isinstance(mapping, Mapping):
            return None
        try:
            items = list(mapping.items())
        except Exception:  # noqa: BLE001 - a mapping that raises maps nobody
            return None
        by_name: _V | None = None
        for key, value in items:
            kind = _entry(key)
            if kind is None or not self.matches(key):
                continue
            if kind[0] == "id":
                return value
            if by_name is None:
                by_name = value
        return by_name


def _read(stamp: Any) -> DeviceIdentity | None:
    if not isinstance(stamp, dict):
        return None
    device, name = stamp.get("device"), stamp.get("device_name")
    if not _is_id(device):
        return None  # no id, no identity: a `device_name` alone is a label for nobody
    name = name.strip() if isinstance(name, str) and name.strip() else None
    return DeviceIdentity(device, name)


def device_identity(context: Any) -> DeviceIdentity | None:
    """The speaking device from the router's stamps, or None.

    `thalovant_home` must be there and carry a `device` made of ASCII digits; a
    `thalovant_connector` stamp, when the context has the key at all, must name the SAME device.
    Never raises, and never reads a client-supplied key.
    """
    if not isinstance(context, dict):
        return None
    home = _read(context.get("thalovant_home"))
    if home is None:
        return None
    if "thalovant_connector" in context and _read(context.get("thalovant_connector")) != home:
        return None
    return home


def device_allowed(context: Any, allowed: Iterable[Any]) -> bool:
    """True when the speaking device is exactly one of `allowed`: by id, or by label.

    For a route with ONE server for the whole hub. An empty allow-list is nobody: deny by default.
    A bare string or bytes is not a list and allows nobody; an allow-list that raises while it is
    read allows nobody. Entries may be strings or integers (a device id typed as a number);
    anything else is ignored. An entry made of digits is an id and is compared with the device's
    id only; any other entry is a name and is compared with its labels only (folded, whole: a part
    of a name never matches, "kitchen" does not allow "Kitchen Display").
    """
    if isinstance(allowed, (str, bytes)):
        return False  # a scalar is not a list: "1580" would allow the devices "1", "5", "8", "0"
    try:
        entries = list(allowed)  # read it all first: a list that raises half-way allows nobody
    except Exception:  # noqa: BLE001 - an allow-list that raises is a no, not an error in the skill
        return False
    identity = device_identity(context)
    if identity is None:
        return False
    return any(identity.matches(entry) for entry in entries)


def device_value(context: Any, mapping: Mapping[Any, _V] | None) -> _V | None:
    """What an owner's per-device mapping (`{"1580": "Kitchen", "mark2": "Den"}`) says for the
    speaking device, or None: the entry keyed by its id first, then one keyed by a label.

    The keys are read as an allow-list's entries are (ids with ids, names with names), so a device
    whose row is NAMED after another device's id never gets that device's entry.
    """
    identity = device_identity(context)
    return identity.value_in(mapping) if identity is not None else None


def link_state(context: Any, connector_id: str | None = None) -> str:
    """What the router says about the speaking device's household and one service at home.

    `connector_id` names a connector of the generic stamp (`"music_assistant"`:
    `context["thalovant_connector"]["link"][connector_id]`); None reads Home Assistant's own
    dialect (`context["thalovant_home"]["link"]`, a string). One of `LINK_STATES`:

    * `online`, `offline`: the household has that link (up, or down right now);
    * `none`: the household has not linked that service;
    * `unavailable`: the router says nothing (it is not there, or it will not vouch for this
      connection). Also the answer for a context that names no device (`device_identity`): a
      `link` nobody is behind is not believed.
    """
    if device_identity(context) is None:
        return "unavailable"
    if connector_id is None:
        link = context["thalovant_home"].get("link")
    else:
        stamp = context.get("thalovant_connector")
        links = stamp.get("link") if isinstance(stamp, dict) else None
        link = links.get(connector_id) if isinstance(links, dict) else None
    return link if isinstance(link, str) and link in LINK_STATES else "unavailable"


def link_allowed(context: Any, connector_id: str | None = None) -> bool:
    """True when the speaking device's own household has that link (`online` or `offline`).

    The gate for a route that goes through the household's link: the router confines every
    household to its own bridge, so nobody has to be listed, and a household switches the feature
    on for itself by linking. `none` and `unavailable` are a no: hand the sentence back, silently.
    """
    return link_state(context, connector_id) in LINKED
