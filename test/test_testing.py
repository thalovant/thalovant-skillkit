"""The message double, which every skill was inventing for itself."""
from __future__ import annotations

from thalovant_skillkit import location, message_lang, utterance
from thalovant_skillkit.testing import MONTREAL, FakeBus, message


def test_it_is_shaped_the_way_the_satellite_sends_one():
    msg = message("what time is it")

    assert utterance(msg) == "what time is it"
    assert message_lang(msg, "en-US") == "en-US"


def test_a_language_is_set_unless_it_is_explicitly_removed():
    """A skill tested only against language-less messages is tested against
    something that never arrives."""
    assert message_lang(message("bonjour", lang="fr-FR"), "en-US") == "fr-FR"
    # ...and the escape hatch, for tests that need the absence.
    assert message_lang(message("hello", lang=None), "fr-FR") == "fr-FR"


def test_the_session_language_is_reachable():
    msg = message("bonjour", lang=None, session={"lang": "fr-FR"})

    assert message_lang(msg, "en-US") == "fr-FR"


def test_a_location_can_be_attached_and_is_read_back():
    """Without one, a skill reporting a time or a forecast is tested an hour
    out and a continent away."""
    msg = message("what time is it", location=MONTREAL)

    assert location(msg) == MONTREAL
    assert location(message("what time is it")) is None


def test_extra_data_keys_reach_the_skill():
    msg = message("play it", site_id="kitchen", confidence=0.9)

    assert msg.data["confidence"] == 0.9
    assert msg.context["site_id"] == "kitchen"


def test_an_empty_utterance_does_not_pretend_to_carry_one():
    assert utterance(message("")) == ""


def test_the_bus_records_what_a_skill_said():
    bus = FakeBus()
    bus.emit(message("hello", msg_type="speak"))
    bus.emit(message("ignored", msg_type="mycroft.skill.handler.start"))

    assert bus.spoken() == ["hello"]
    assert len(bus.of_type("mycroft.skill.handler.start")) == 1


def test_the_bus_holds_handlers_so_registration_can_be_checked():
    bus = FakeBus()

    def handler(msg):
        return True

    bus.on("some.event", handler)
    assert bus.handlers["some.event"] == [handler]
    bus.remove("some.event", handler)
    assert bus.handlers["some.event"] == []


def test_the_bus_hears_what_a_current_core_actually_emits():
    """The real core emits `ovos.utterance.speak`, not `speak`. A double that
    knew only the old name reported silence from a skill the hub heard fine --
    which is exactly how a first end-to-end check of a working skill read."""
    bus = FakeBus()
    bus.emit(message("old style", msg_type="speak"))
    bus.emit(message("new style", msg_type="ovos.utterance.speak"))

    assert bus.spoken() == ["old style", "new style"]
