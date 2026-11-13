"""Who is speaking, as the HUB says it: the router's stamp, and nothing else.

A skill that serves one household's private thing (a media server, the lights) must know
which of the hub's devices asked, and refuse the others: a public hub has strangers on it. The one
place that knowledge is trustworthy is the stamp the hub's home router
writes into the context of every utterance it vouches for:

    context["thalovant_home"] = {"link": "online", "device": "1580", "device_name": "client-1"}
    context["thalovant_connector"] = {"link": {...}, "device": "1580", "device_name": "client-1"}

`device` is the database id of the connection's row and `device_name` its platform-assigned name;
the router writes both from the row and overwrites whatever a client put there, and writes neither
for a connection it will not vouch for (a preview or chat bridge, a connection without an account).
Everything else that looks like an identity is the client's own word and is NEVER read here:
`context["peer"]` is `<useragent>::<id>::<name>::<session>` where the user agent and the session are
client-supplied (a session called `x::1580::y` makes the tail read as another client's id), and
`source`, `site_id`, `client_id` and the session's own copies are no better. This module has no
function that reads any of them, so a skill cannot reintroduce the spoof by accident.

    from thalovant_skillkit.device import device_allowed

    if not device_allowed(message.context, self.allowed_devices):   # fails closed
        return self.pass_on(message)

No stamp, a stamp without a usable `device` or `device_name`, an empty allow-list, or any doubt: no
identity, and the gate says no. The retired per-service stamps of earlier routers
(`thalovant_music`) are not believed either: a client could write that key itself, and nothing but
the router's own keys is trusted.

`thalovant_home` DECIDES: every router since 0.4.1 overwrites it on every client utterance.
`thalovant_connector` (router 0.5.0) is believed only when it names the same device: before 0.5.0
nothing overwrote it, so a client of an older hub could write its own and the first stamp found
would have won. A stamp that is missing, names nobody, or disagrees with the other one means
nobody, whichever key it is under; one is never "skipped".

A skill whose kit floor is older than this module imports it behind a guard (`docs/reference.md`,
"Older kits"), and the guard's fallback is to deny everyone.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .text import fold

__all__ = ["STAMP_KEYS", "DeviceIdentity", "device_allowed", "device_identity"]

#: The context keys the router owns: `thalovant_home` (decides) and `thalovant_connector`
#: (must agree). Nothing else is believed.
STAMP_KEYS: tuple[str, ...] = ("thalovant_home", "thalovant_connector")

# : The prefix the platform gives a connection's row name (`client-<uuid>`); the console shows the
# name without it.
_ROW_PREFIX = "client-"


@dataclass(frozen=True)
class DeviceIdentity:
    """The speaking device as the hub vouches for it."""

    device_id: str | None
    name: str | None

    @property
    def keys(self) -> tuple[str, ...]:
        """Every name the hub gave this device: its database id, its row name, and the row name
        without the platform's `client-` prefix (so a device can be listed by the name the console
        shows)."""
        out: list[str] = []
        if self.device_id:
            out.append(self.device_id)
        if self.name:
            out.append(self.name)
            if self.name.lower().startswith(_ROW_PREFIX) and len(self.name) > len(_ROW_PREFIX):
                out.append(self.name[len(_ROW_PREFIX) :])
        return tuple(out)


def _read(stamp: Any) -> DeviceIdentity | None:
    if not isinstance(stamp, dict):
        return None
    device, name = stamp.get("device"), stamp.get("device_name")
    is_id = isinstance(device, str) and device.isascii() and device.isdigit()
    device = device if is_id else None
    name = name.strip() if isinstance(name, str) and name.strip() else None
    return DeviceIdentity(device, name) if (device or name) else None


def device_identity(context: Any) -> DeviceIdentity | None:
    """The speaking device from the router's stamps, or None.

    `thalovant_home` must be there and name the device; a `thalovant_connector` stamp, when the
    context has the key at all, must name the SAME device. Never raises, and never reads a
    client-supplied key.
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
    """True when the hub's name for the speaking device is exactly one of `allowed` (folded, whole).

    An empty allow-list is nobody: deny by default. Entries may be strings or integers (a device id
    typed as a number); anything else is ignored. A part of a name never matches ("kitchen" does not
    allow "Kitchen Display").
    """
    try:
        wanted = {
            fold(str(entry))
            for entry in allowed
            if isinstance(entry, (str, int)) and not isinstance(entry, bool)
        }
    except TypeError:
        return False
    wanted.discard("")
    identity = device_identity(context)
    if not wanted or identity is None:
        return False
    return any(fold(key) in wanted for key in identity.keys)
