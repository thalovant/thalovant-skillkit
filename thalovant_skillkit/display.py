"""What a skill shows on a satellite with a screen.

A satellite with a display (the Mark II, a tablet on the wall) draws a
**card** the skill puts on its reply, in the speak message's `meta["display"]`,
beside the `dialog`, `data` and `skill` keys OVOS and the kit set there. The
card is data, never code: a kind the screen lays out itself (`text`, `list`,
`weather`, `media`) or a `layout`, a small Remote Flutter Widgets file the
skill ships as `gui/thalovant/<name>.rfwtxt` and the screen renders with its
own widget library. The satellite checks and bounds every card
(thalovant-voice, `display.py`); a card over the sizes below is not shown,
so they are enforced here first, where the skill author sees the error.

    from thalovant_skillkit import display

    card = display.weather("Toronto", condition="Cloudy", icon="cloudy",
                           temperature=11, high=12, low=4, unit="°",
                           actions=[display.action("tomorrow", "Tomorrow")])
    self.speak_dialog("weather.answer", {"summary": summary}, display=card)

A layout card binds the card's `data` to the skill's own layout:

    layout = display.layout_file(self, "weather.day")   # gui/thalovant/weather.day.rfwtxt
    self.speak(summary, display=display.layout(layout, data={...}, actions=[...]))

The layout's text travels once per hub process and by hash afterwards; the
satellite keeps it by hash. A tap on one of the card's `actions` comes back
to the skill as a `thalovant.display.action` bus message with
`{"card", "action", "skill", "at"}`; `on_display_action` in the skill base
delivers it to a handler registered with `add_display_action_handler`.

Nothing here reaches a screen that is not there: a client without a display
ignores `meta["display"]`, as a client without alarms ignores `meta["schedule"]`.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import math
import os
import re
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = ("text", "list", "weather", "media", "layout")
#: The bus message a satellite reports a tap on a card's action in.
ACTION_EVENT = "thalovant.display.action"

#: The satellite's own bounds, mirrored so a card that will not be shown
#: fails here, with a reason, rather than quietly on the device.
TITLE_LIMIT = 120
TEXT_LIMIT = 1000
ITEM_LIMIT = 12
ITEM_TEXT_LIMIT = 160
ACTION_LIMIT = 4
LABEL_LIMIT = 40
FIGURE_LIMIT = 24
MAX_IMAGE_BYTES = 512 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_LAYOUT_BYTES = 64 * 1024
MAX_DATA_BYTES = 16 * 1024
MAX_TTL_SECONDS = 24 * 3600
WEATHER_ICONS = ("clear", "clear-night", "partly", "cloudy", "fog", "drizzle", "rain",
                 "showers", "snow", "sleet", "storm", "wind")
LAYOUT_DIR = ("gui", "thalovant")
LAYOUT_SUFFIX = ".rfwtxt"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_LAYOUT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CardError(ValueError):
    """A card the satellite would not show, and why."""


def _text(value: Any, limit: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    if len(value) > limit:
        raise CardError(f"{what} is longer than {limit} characters")
    return value


def _ident(value: str, what: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise CardError(f"{what} {value!r} is not a plain id (letters, digits, . _ : -)")
    return value


def _figure(value: Any) -> str:
    if isinstance(value, bool):
        raise CardError("a figure is a number or text, not a boolean")
    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise CardError("a figure must be finite")
        return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
    return _text(value, FIGURE_LIMIT, "a figure")


@dataclass(frozen=True)
class Action:
    """One button on a card; `id` comes back in the tap report."""

    id: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}


def action(identifier: str, label: str) -> Action:
    """A button: `identifier` is what the tap reports, `label` what it says."""
    return Action(_ident(identifier, "an action id"), _text(label, LABEL_LIMIT, "an action label"))


@dataclass(frozen=True)
class Item:
    """One row of a list card, or one day of a weather card."""

    label: str
    value: str = ""
    icon: str = ""
    id: str = ""

    def as_dict(self) -> dict[str, str]:
        entry = {"label": self.label}
        if self.value:
            entry["value"] = self.value
        if self.icon:
            entry["icon"] = self.icon
        if self.id:
            entry["id"] = self.id
        return entry


def item(label: str, value: Any = "", *, icon: str = "", identifier: str = "") -> Item:
    """A row: a label, an optional value (a number is printed as given), an
    icon name the screen knows, and an id a layout or a tap may name."""
    return Item(_text(label, ITEM_TEXT_LIMIT, "an item label"),
                _figure(value) if isinstance(value, int | float) and not isinstance(value, bool)
                else _text(value, ITEM_TEXT_LIMIT, "an item value"),
                _text(icon, LABEL_LIMIT, "an item icon"),
                _ident(identifier, "an item id") if identifier else "")


@dataclass(frozen=True)
class Layout:
    """A layout file, as `layout_file` reads it: its name, text and hash."""

    name: str
    text: str
    sha256: str


_sent_layouts: set[str] = set()
_sent_lock = threading.Lock()


def layout_file(skill: Any, name: str, *, root: str | os.PathLike | None = None) -> Layout:
    """The skill's `gui/thalovant/<name>.rfwtxt`, read and hashed.

    `root` is the skill's directory; by default the directory of the module
    the skill's class is defined in (`skill.root_dir` when OVOS set it).
    """
    if not _LAYOUT_NAME.match(name or ""):
        raise CardError(f"layout name {name!r} is not a plain name (a-z, digits, . _ -)")
    base = Path(root) if root is not None else _skill_root(skill)
    path = base.joinpath(*LAYOUT_DIR, f"{name}{LAYOUT_SUFFIX}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CardError(f"layout {name!r} not found at {path}") from error
    encoded = text.encode("utf-8")
    if not text.strip():
        raise CardError(f"layout {name!r} is empty")
    if len(encoded) > MAX_LAYOUT_BYTES:
        raise CardError(f"layout {name!r} is over {MAX_LAYOUT_BYTES} bytes")
    return Layout(name, text, hashlib.sha256(encoded).hexdigest())


def _skill_root(skill: Any) -> Path:
    root = getattr(skill, "root_dir", None)
    if isinstance(root, str | os.PathLike) and str(root):
        return Path(root)
    import inspect

    try:
        return Path(inspect.getfile(type(skill))).resolve().parent
    except (TypeError, OSError) as error:
        raise CardError("cannot find the skill's directory; pass root=") from error


def forget_sent_layouts() -> None:
    """Send every layout inline again: for tests, and after a satellite says
    it does not have one."""
    with _sent_lock:
        _sent_layouts.clear()


@dataclass
class Card:
    """A card, as `meta["display"]` carries it. Build one with the helpers."""

    kind: str
    id: str = ""
    title: str = ""
    subtitle: str = ""
    body: str = ""
    icon: str = ""
    items: list[Item] = field(default_factory=list)
    figures: dict[str, str] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    image: tuple[bytes, str] | None = None
    layout: Layout | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ttl: float | None | bool = True
    lang: str = ""
    #: The whole screen, edge to edge, with no frame and no time along the top:
    #: for a card that is a scene of its own, such as a thank-you mosaic.
    fullscreen: bool = False

    def as_dict(self) -> dict[str, Any]:
        """The `meta["display"]` entry. A layout's text goes inline the
        first time this process sends it, and by hash afterwards."""
        entry: dict[str, Any] = {"kind": self.kind}
        if self.id:
            entry["id"] = self.id
        for key in ("title", "subtitle", "body", "icon", "lang"):
            value = getattr(self, key)
            if value:
                entry[key] = value
        if self.items:
            entry["items"] = [i.as_dict() for i in self.items]
        if self.figures:
            entry["figures"] = dict(self.figures)
        if self.actions:
            entry["actions"] = [a.as_dict() for a in self.actions]
        if self.image is not None:
            data, mime = self.image
            entry["image"] = {"mime": mime, "data": base64.b64encode(data).decode("ascii")}
        if self.layout is not None:
            layout = {"name": self.layout.name, "sha256": self.layout.sha256}
            with _sent_lock:
                if self.layout.sha256 not in _sent_layouts:
                    layout["rfw"] = self.layout.text
                    _sent_layouts.add(self.layout.sha256)
            entry["layout"] = layout
            entry["data"] = dict(self.data)
        if self.ttl is not True:
            entry["ttl"] = None if self.ttl in (None, False) else float(self.ttl)
        if self.fullscreen:
            entry["fullscreen"] = True
        return entry


def _common(card: Card, *, identifier: str, title: Any, subtitle: Any, body: Any,
            actions: Iterable[Action] | None, ttl: float | None | bool, lang: str) -> Card:
    card.id = _ident(identifier, "a card id") if identifier else ""
    card.title = _text(title, TITLE_LIMIT, "a title")
    card.subtitle = _text(subtitle, TITLE_LIMIT, "a subtitle")
    card.body = _text(body, TEXT_LIMIT, "a body")
    card.actions = list(actions or [])
    if len(card.actions) > ACTION_LIMIT:
        raise CardError(f"a card has at most {ACTION_LIMIT} actions")
    if len({a.id for a in card.actions}) != len(card.actions):
        raise CardError("two actions share an id")
    if ttl is not True and ttl is not None and ttl is not False:
        if (isinstance(ttl, bool) or not isinstance(ttl, int | float)
                or not 0 < ttl <= MAX_TTL_SECONDS):
            raise CardError(f"ttl is seconds, up to {MAX_TTL_SECONDS}; None keeps the card")
    card.ttl = ttl
    card.lang = lang or ""
    return card


def text(body: str, *, title: str = "", subtitle: str = "", identifier: str = "",
         actions: Iterable[Action] | None = None, ttl: float | None | bool = True,
         lang: str = "") -> Card:
    """A title and a body. `ttl` is seconds; None keeps the card until it is
    cleared, replaced or closed; the default leaves it to the satellite
    (two minutes)."""
    card = _common(Card("text"), identifier=identifier, title=title, subtitle=subtitle,
                   body=body, actions=actions, ttl=ttl, lang=lang)
    if not card.title and not card.body:
        raise CardError("a text card needs a title or a body")
    return card


def list_card(items: Iterable[Item | str], *, title: str = "", subtitle: str = "",
              identifier: str = "", actions: Iterable[Action] | None = None,
              ttl: float | None | bool = True, lang: str = "") -> Card:
    """Up to twelve rows."""
    rows = [item(i) if isinstance(i, str) else i for i in items]
    if not rows:
        raise CardError("a list card needs items")
    if len(rows) > ITEM_LIMIT:
        raise CardError(f"a list card has at most {ITEM_LIMIT} items")
    card = _common(Card("list"), identifier=identifier, title=title, subtitle=subtitle,
                   body="", actions=actions, ttl=ttl, lang=lang)
    card.items = rows
    return card


def weather(place: str, *, condition: str = "", icon: str = "", temperature: Any = None,
            high: Any = None, low: Any = None, feels_like: Any = None, unit: str = "",
            wind: Any = None, humidity: Any = None, precipitation: Any = None,
            days: Iterable[Item] | None = None, subtitle: str = "", identifier: str = "",
            actions: Iterable[Action] | None = None, ttl: float | None | bool = True,
            lang: str = "") -> Card:
    """The forecast: the place as the title, the condition as the body, the
    figures printed as given (a number loses needless decimals), the coming
    days as items."""
    if icon and icon not in WEATHER_ICONS:
        raise CardError(f"icon {icon!r} is not one of {', '.join(WEATHER_ICONS)}")
    card = _common(Card("weather"), identifier=identifier, title=place, subtitle=subtitle,
                   body=condition, actions=actions, ttl=ttl, lang=lang)
    card.icon = icon
    figures = {"temperature": temperature, "high": high, "low": low, "feels_like": feels_like,
               "unit": unit, "wind": wind, "humidity": humidity, "precipitation": precipitation}
    card.figures = {key: _figure(value) for key, value in figures.items()
                    if value is not None and value != ""}
    card.items = list(days or [])
    if len(card.items) > ITEM_LIMIT:
        raise CardError(f"a weather card has at most {ITEM_LIMIT} days")
    if not card.figures and not card.body and not card.items:
        raise CardError("a weather card needs figures, a condition or days")
    return card


def media(image: bytes, mime: str, *, title: str = "", body: str = "", identifier: str = "",
          actions: Iterable[Action] | None = None, ttl: float | None | bool = True,
          lang: str = "") -> Card:
    """A picture, embedded: PNG, JPEG or WebP under 512 kB. A path or a URL
    is never sent; read the file and pass its bytes."""
    if mime not in IMAGE_TYPES:
        raise CardError(f"image type {mime!r} is not one of {', '.join(IMAGE_TYPES)}")
    if not isinstance(image, bytes | bytearray) or not image:
        raise CardError("an image is bytes")
    if len(image) > MAX_IMAGE_BYTES:
        raise CardError(f"an image is at most {MAX_IMAGE_BYTES} bytes; resize it for a screen")
    card = _common(Card("media"), identifier=identifier, title=title, subtitle="", body=body,
                   actions=actions, ttl=ttl, lang=lang)
    card.image = (bytes(image), mime)
    return card


def layout(layout: Layout, *, data: dict[str, Any] | None = None, title: str = "",
           subtitle: str = "", body: str = "", identifier: str = "",
           actions: Iterable[Action] | None = None, image: tuple[bytes, str] | None = None,
           ttl: float | None | bool = True, lang: str = "", fullscreen: bool = False) -> Card:
    """The skill's own layout, bound to `data`. `body` is what a screen that
    cannot draw the layout shows; by default the words that were said. The
    `actions` are the ids the layout's buttons may send. `fullscreen` gives
    the layout the whole screen, with no frame and no time along the top."""
    import json

    card = _common(Card("layout"), identifier=identifier, title=title, subtitle=subtitle,
                   body=body, actions=actions, ttl=ttl, lang=lang)
    card.layout = layout
    card.fullscreen = bool(fullscreen)
    bound = dict(data or {})
    try:
        encoded = json.dumps(bound, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise CardError("layout data must be JSON: maps, lists, strings, numbers") from error
    if len(encoded.encode("utf-8")) > MAX_DATA_BYTES:
        raise CardError(f"layout data is at most {MAX_DATA_BYTES} bytes")
    card.data = json.loads(encoded)
    if image is not None:
        data_bytes, mime = image
        if mime not in IMAGE_TYPES or len(data_bytes) > MAX_IMAGE_BYTES:
            raise CardError("a layout's image is PNG, JPEG or WebP under 512 kB")
        card.image = (bytes(data_bytes), mime)
    return card


@dataclass(frozen=True)
class Clear:
    """Clear what is shown: every card, or one skill's."""

    skill: str = ""

    def as_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"kind": "clear"}
        if self.skill:
            entry["skill"] = self.skill
        return entry


def clear(skill: str = "") -> Clear:
    """Attach to a reply to take the cards down (this skill's, with its id)."""
    return Clear(skill)


# -- putting it on a reply ------------------------------------------------------------


def attach(meta: dict | None, card: Card | Clear | None) -> dict | None:
    """`meta` with the card in it; `meta` as given when there is no card."""
    if card is None:
        return meta
    entry = card.as_dict()
    return {**(meta or {}), "display": entry}


_pending = threading.local()


@contextlib.contextmanager
def showing(card: Card | Clear | None) -> Iterator[None]:
    """Attach `card` to every reply spoken inside the block, so a card rides
    on OVOS's own `speak_dialog` rendering path too."""
    previous = getattr(_pending, "card", None)
    _pending.card = card
    try:
        yield
    finally:
        _pending.card = previous


def pending() -> Card | Clear | None:
    """The card a `showing` block set, for the speak path to attach."""
    return getattr(_pending, "card", None)


# -- what comes back -------------------------------------------------------------------


@dataclass(frozen=True)
class Tap:
    """A tap on a card's action, as the satellite reports it."""

    card: str
    action: str
    skill: str
    at: float


def tap(data: Any) -> Tap | None:
    """The report in a `thalovant.display.action` message, or None when it
    is not one this skill can believe."""
    if not isinstance(data, dict):
        return None
    card = data.get("card")
    act = data.get("action")
    if (not isinstance(card, str) or not _ID.match(card)
            or not isinstance(act, str) or not _ID.match(act)):
        return None
    at = data.get("at")
    if isinstance(at, bool) or not isinstance(at, int | float) or not math.isfinite(at):
        return None
    skill = data.get("skill")
    return Tap(card, act, skill if isinstance(skill, str) else "", float(at))
