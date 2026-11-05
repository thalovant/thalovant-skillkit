"""What a skill shows on a screen: the cards the helpers build, the sizes they
refuse, how a card rides on every way of speaking, and what comes back when
a card is tapped."""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

import pytest

from thalovant_skillkit import display
from thalovant_skillkit.testing_ovos import skill_harness

FIXTURE = Path(__file__).parent / "fixtures" / "thalovant-skill-punchline"
SPEECH = ("ovos.utterance.speak", "speak")
ALICE = {"session_id": "alice", "lang": "en-US"}
PNG = b"\x89PNG\r\n\x1a\n" + bytes(24)
LAYOUT = "import thalovant.widgets;\nwidget root = Title(text: data.place);\n"


@pytest.fixture(scope="module")
def punchline():
    sys.path.insert(0, str(FIXTURE))
    try:
        from thalovant_skill_punchline import PunchlineSkill

        yield PunchlineSkill
    finally:
        sys.path.remove(str(FIXTURE))
        sys.modules.pop("thalovant_skill_punchline", None)


@pytest.fixture(autouse=True)
def _layouts_sent_fresh():
    display.forget_sent_layouts()
    yield
    display.forget_sent_layouts()


def _live(skill_type):
    return skill_harness(skill_type, skill_id="punchline.test", scheduler=False,
                         bus_options={"emit_legacy": False})


def _said(harness):
    heard = []
    for topic in SPEECH:
        harness.bus.on(topic, lambda message: heard.append(message))
    return heard


def _turn(harness, action, session=ALICE):
    from ovos_bus_client.message import Message

    harness.skill.add_event("test.turn", lambda message: action(message))
    harness.bus.emit(Message("test.turn", {"utterance": "x"}, {"session": dict(session)}))
    harness.skill.remove_event("test.turn")


# -- the cards ------------------------------------------------------------------------


def test_a_text_card_is_a_title_and_a_body():
    card = display.text("Cloudy with a high of eleven.", title="Toronto",
                        actions=[display.action("tomorrow", "Tomorrow")], ttl=60)
    assert card.as_dict() == {
        "kind": "text", "title": "Toronto", "body": "Cloudy with a high of eleven.",
        "actions": [{"id": "tomorrow", "label": "Tomorrow"}], "ttl": 60.0,
    }
    assert display.text("x", ttl=None).as_dict()["ttl"] is None
    assert "ttl" not in display.text("x").as_dict()


def test_a_list_card_takes_rows_or_bare_labels():
    card = display.list_card(["milk", display.item("eggs", 12, icon="check", identifier="e")],
                             title="Groceries", identifier="groceries")
    assert card.as_dict()["items"] == [{"label": "milk"},
                                       {"label": "eggs", "value": "12", "icon": "check", "id": "e"}]
    assert card.as_dict()["id"] == "groceries"


def test_a_weather_card_prints_its_figures_as_given():
    card = display.weather("Toronto", condition="Cloudy", icon="cloudy", temperature=11,
                           high=12.5, low=-3.0, unit="°", wind="west 20 km/h",
                           days=[display.item("Wed", "9°", icon="rain")])
    entry = card.as_dict()
    assert entry["title"] == "Toronto" and entry["body"] == "Cloudy" and entry["icon"] == "cloudy"
    assert entry["figures"] == {"temperature": "11", "high": "12.5", "low": "-3", "unit": "°",
                                "wind": "west 20 km/h"}
    assert entry["items"] == [{"label": "Wed", "value": "9°", "icon": "rain"}]


def test_a_media_card_embeds_its_bytes():
    card = display.media(PNG, "image/png", title="Front door")
    assert card.as_dict()["image"] == {"mime": "image/png",
                                       "data": base64.b64encode(PNG).decode("ascii")}


def test_a_layout_travels_inline_with_every_card(tmp_path):
    """0.29.0 sent the text once per process: the Mark II, asking after another
    client had, got a hash it did not have and drew the words (2026-11-05)."""
    (tmp_path / "gui" / "thalovant").mkdir(parents=True)
    (tmp_path / "gui" / "thalovant" / "weather.day.rfwtxt").write_text(LAYOUT, encoding="utf-8")
    layout = display.layout_file(object(), "weather.day", root=tmp_path)
    assert layout.sha256 == hashlib.sha256(LAYOUT.encode("utf-8")).hexdigest()
    first = display.layout(layout, data={"place": "Toronto"}, body="Cloudy.",
                           actions=[display.action("refresh", "Refresh")]).as_dict()
    assert first["layout"] == {"name": "weather.day", "sha256": layout.sha256, "rfw": LAYOUT}
    assert first["data"] == {"place": "Toronto"} and first["body"] == "Cloudy."
    again = display.layout(layout, data={"place": "Ottawa"}).as_dict()
    assert again["layout"] == {"name": "weather.day", "sha256": layout.sha256, "rfw": LAYOUT}, (
        "a second satellite asking after the first still gets the text")
    display.forget_sent_layouts()  # kept for 0.29.0 callers
    assert display.layout(layout).as_dict()["layout"]["rfw"] == LAYOUT


def test_the_layout_is_read_beside_the_skills_module(punchline, tmp_path):
    with pytest.raises(display.CardError, match="not found"):
        display.layout_file(punchline, "weather.day")
    with pytest.raises(display.CardError, match="plain name"):
        display.layout_file(punchline, "Weather Day", root=tmp_path)


def test_the_layout_is_found_in_the_directory_of_the_skills_own_module(tmp_path, monkeypatch):
    """Without `root=` and without OVOS's `root_dir`, the directory searched is
    the one holding the module that defines the skill's class: a layout
    planted beside such a module is read, and its text is what was planted."""
    import importlib.util
    import sys

    module = tmp_path / "planted_skill.py"
    module.write_text("class PlantedSkill:\n    pass\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("planted_skill", module)
    loaded = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "planted_skill", loaded)  # as an import does
    spec.loader.exec_module(loaded)
    layout_dir = tmp_path.joinpath(*display.LAYOUT_DIR)
    layout_dir.mkdir(parents=True)
    (layout_dir / "score.rfwtxt").write_text("widget root = Text(text: data.score);\n",
                                             encoding="utf-8")

    layout = display.layout_file(loaded.PlantedSkill(), "score")

    assert layout.name == "score"
    assert layout.text == "widget root = Text(text: data.score);\n"
    assert display.layout_file(loaded.PlantedSkill, "score") == layout


def test_a_clear_takes_the_cards_down():
    assert display.clear().as_dict() == {"kind": "clear"}
    assert display.clear("punchline").as_dict() == {"kind": "clear", "skill": "punchline"}


@pytest.mark.parametrize("build, why", [
    (lambda: display.text(""), "title or a body"),
    (lambda: display.text("x", identifier="../etc"), "plain id"),
    (lambda: display.text("x", title="t" * 121), "longer than 120"),
    (lambda: display.text("b" * 1001), "longer than 1000"),
    (lambda: display.text("x", ttl=0), "ttl is seconds"),
    (lambda: display.text("x", ttl=10 ** 9), "ttl is seconds"),
    (lambda: display.text("x", actions=[display.action(f"a{i}", "A") for i in range(5)]),
     "at most 4 actions"),
    (lambda: display.text("x", actions=[display.action("a", "A"), display.action("a", "B")]),
     "share an id"),
    (lambda: display.action("bad id", "x"), "plain id"),
    (lambda: display.action("ok", "l" * 41), "longer than 40"),
    (lambda: display.list_card([]), "needs items"),
    (lambda: display.list_card([str(i) for i in range(13)]), "at most 12"),
    (lambda: display.weather("Toronto"), "needs figures"),
    (lambda: display.weather("Toronto", icon="volcano", temperature=1), "not one of"),
    (lambda: display.weather("Toronto", temperature=float("nan")), "finite"),
    (lambda: display.media(PNG, "image/gif"), "not one of"),
    (lambda: display.media(b"", "image/png"), "is bytes"),
    (lambda: display.media(bytes(display.MAX_IMAGE_BYTES + 1), "image/png"), "at most"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64),
                            data={"big": "x" * display.MAX_DATA_BYTES}), "at most"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), data={"f": object()}),
     "must be JSON"),
    # Review follow-ups on #47: what the satellite's strict JSON reader and its
    # image check would refuse is refused here, with a reason, not a traceback.
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), data={"t": float("nan")}),
     "finite numbers"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), data={"t": float("inf")}),
     "finite numbers"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), image=("a path", "image/png")),
     "is bytes"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), image=(b"", "image/png")),
     "is bytes"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), image=(PNG, "image/gif")),
     "not one of"),
    (lambda: display.layout(display.Layout("w", LAYOUT, "f" * 64), image=PNG), "(bytes, mime)"),
    (lambda: display.weather("Toronto", temperature=10 ** 400), "a screen can print"),
    (lambda: display.item("x", 10 ** 400), "a screen can print"),
])
def test_what_the_satellite_would_not_show_fails_here(build, why):
    with pytest.raises(display.CardError, match=why):
        build()


# -- on a reply ------------------------------------------------------------------------


def test_a_card_rides_on_speak_speak_dialog_and_speak_to(punchline):
    """`speak` and `speak_dialog` keep OVOS's signatures, so the card goes
    around them in a `showing` block; the kit's own `speak_to` and
    `speak_varied_dialog` take it as an argument."""
    card = display.text("It is sunny.", title="Toronto")

    def spoken(message):
        with display.showing(card):
            harness.skill.speak("It is sunny.")

    def dialog(message):
        with display.showing(card):
            harness.skill.speak_dialog("joke")

    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, spoken)
        _turn(harness, dialog)
        _turn(harness, lambda message: harness.skill.speak_to(message, "Sunny.", display=card))
        _turn(harness, lambda message: harness.skill.speak_varied_dialog("joke", display=card))
    assert len(heard) == 4
    for message in heard:
        assert message.data["meta"]["display"] == card.as_dict()
        assert message.data["meta"]["skill"] == "punchline.test"
    assert heard[1].data["meta"]["dialog"] == "joke"


def test_a_showing_block_attaches_the_card_to_every_reply_inside(punchline):
    card = display.text("Both.", title="Twice")

    def answer(message):
        with display.showing(card):
            harness.skill.speak("One.")
            harness.skill.speak_dialog("joke")
        harness.skill.speak("Three.")

    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, answer)
    assert [m.data["meta"].get("display") is not None for m in heard] == [True, True, False]


def test_a_reply_without_a_card_is_unchanged(punchline):
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak_dialog("joke"))
    assert "display" not in heard[0].data["meta"]


# -- what comes back --------------------------------------------------------------------


def test_a_tap_on_this_skills_card_reaches_the_handler(punchline):
    from ovos_bus_client.message import Message

    taps = []
    mine = {"card": "punchline.test:text", "action": "again", "skill": "punchline.test"}
    with _live(punchline) as harness:
        handler = lambda tap, message: taps.append(tap)  # noqa: E731 - the same one twice
        harness.skill.add_display_action_handler(handler)
        harness.skill.add_display_action_handler(handler)
        for data in (
            {**mine, "at": 1.0},
            {"card": "weather:x", "action": "again", "skill": "weather", "at": 2.0},
            {"card": "punchline.test:other", "action": "again", "skill": "", "at": 3.0},
            {"card": "../x", "action": "again", "skill": "punchline.test", "at": 4.0},
            mine,
        ):
            harness.bus.emit(Message(display.ACTION_EVENT, data, {"session": dict(ALICE)}))
    assert [(t.card, t.at) for t in taps] == [("punchline.test:text", 1.0),
                                            ("punchline.test:other", 3.0)]
    assert taps[0] == display.Tap("punchline.test:text", "again", "punchline.test", 1.0)
    assert display.tap("not a report") is None
    assert display.tap({**mine, "at": float("inf")}) is None
    # An integer too large for a float is not a time; it used to raise
    # OverflowError out of the bus handler instead of being dropped.
    assert display.tap({**mine, "at": 10 ** 400}) is None
    assert display.tap({**mine, "at": 7}) == display.Tap("punchline.test:text", "again",
                                                          "punchline.test", 7.0)


def test_a_fullscreen_layout_says_so_and_an_ordinary_one_does_not(tmp_path):
    (tmp_path / "gui" / "thalovant").mkdir(parents=True)
    (tmp_path / "gui" / "thalovant" / "scene.rfwtxt").write_text(
        "import core.widgets;\nwidget root = Text(text: 'x');")
    display.forget_sent_layouts()
    file = display.layout_file(None, "scene", root=tmp_path)
    assert display.layout(file, fullscreen=True).as_dict()["fullscreen"] is True
    assert "fullscreen" not in display.layout(file).as_dict()
