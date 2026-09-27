"""The example skill in test/fixtures, spoken through the real OVOS skill base.

Punchline has one dialog with an English `.ssml` twin and no French one, one
whose markup comes from its value, and one with neither. Each test drives it
on the upstream FakeBus -- the one that mirrors `ovos.utterance.speak` onto
the legacy `speak` when asked -- and reads what a client would receive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from thalovant_skillkit.checks import check_all
from thalovant_skillkit.speech import speech_topic
from thalovant_skillkit.ssml import Speech, pause, say, validate
from thalovant_skillkit.testing_ovos import skill_harness

FIXTURE = Path(__file__).parent / "fixtures" / "thalovant-skill-punchline"
DIALOG = FIXTURE / "thalovant_skill_punchline" / "locale" / "en-US" / "dialog"
SPEECH = ("ovos.utterance.speak", "speak")
ALICE = {"session_id": "alice", "lang": "en-US"}
BOB = {"session_id": "bob", "lang": "fr-FR"}


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


@pytest.fixture(scope="module")
def punchline():
    sys.path.insert(0, str(FIXTURE))
    try:
        from thalovant_skill_punchline import PunchlineSkill

        yield PunchlineSkill
    finally:
        sys.path.remove(str(FIXTURE))
        sys.modules.pop("thalovant_skill_punchline", None)


def _live(skill_type, *, emit_legacy=False):
    return skill_harness(skill_type, skill_id="punchline.test", scheduler=False,
                         bus_options={"emit_legacy": emit_legacy})


def _said(harness, topics=SPEECH):
    heard = []
    for topic in topics:
        # One listener per topic: the bus delivers a mirrored message once to
        # a listener subscribed to both names, and both copies are the point.
        harness.bus.on(topic, lambda message: heard.append(message))
    return heard


def _turn(harness, action, session=ALICE, utterance="tell me a joke"):
    """Run `action(message)` as a bus handler, as an intent handler runs."""
    from ovos_bus_client.message import Message

    harness.skill.add_event("test.turn", lambda message: action(message))
    harness.bus.emit(Message("test.turn", {"utterance": utterance}, {"session": dict(session)}))
    harness.skill.remove_event("test.turn")


def test_the_example_skill_keeps_every_contract():
    """Twins pass the check, and a French locale without one is not a gap."""
    assert check_all(FIXTURE) == []


def test_a_twin_is_sent_with_the_line_it_belongs_to(punchline):
    """Whichever variant is drawn, its SSML is the same variant's."""
    plain, twins = _lines(DIALOG / "joke.dialog"), _lines(DIALOG / "joke.ssml")
    with _live(punchline) as harness:
        heard = _said(harness)
        for _ in range(8):
            _turn(harness, lambda message: harness.skill.speak_dialog("joke"))

    assert {m.data["utterance"] for m in heard} == set(plain)
    for message in heard:
        index = plain.index(message.data["utterance"])
        assert message.data["utterance_ssml"] == f"<speak>{twins[index]}</speak>"
        # The spec topic on workshop 9, legacy `speak` on workshop 8: the
        # topic the workshop's own speak() uses, whichever that is.
        assert message.msg_type == speech_topic()
        assert message.context["session"]["session_id"] == "alice"
        assert message.context["skill_id"] == "punchline.test"
        assert message.data["meta"] == {"dialog": "joke", "data": {}, "skill": "punchline.test"}
        assert message.data["lang"] == "en-US"


def test_a_language_without_a_twin_hears_its_own_plain_line(punchline):
    """French has no joke.ssml: no English markup is borrowed for it."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak_dialog("joke"), session=BOB)

    [message] = heard
    assert "utterance_ssml" not in message.data
    assert message.data["utterance"] in _lines(DIALOG.parents[1] / "fr-FR/dialog/joke.dialog")
    assert message.data["lang"] == "fr-FR"


def test_a_marked_up_value_needs_no_twin_in_any_language(punchline):
    """`code` has no .ssml anywhere; spell() is enough, in both languages."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.tell_code("XK7"))
        _turn(harness, lambda message: harness.skill.tell_code("XK7"), session=BOB)

    assert [(m.data["utterance"], m.data["utterance_ssml"]) for m in heard] == [
        ("Your code is XK7.",
         '<speak>Your code is <say-as interpret-as="characters">XK7</say-as>.</speak>'),
        ("Votre code est XK7.",
         '<speak>Votre code est <say-as interpret-as="characters">XK7</say-as>.</speak>'),
    ]


def test_a_dialog_with_neither_is_exactly_what_ovos_sends(punchline):
    """No twin and plain values: the framework's own speak_dialog, untouched."""
    from ovos_workshop.skills import OVOSSkill

    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.greet("Ada & Bob"))
        _turn(harness, lambda message: OVOSSkill.speak_dialog(
            harness.skill, "greeting", {"name": "Ada & Bob"}))

    ours, theirs = heard
    assert ours.msg_type == theirs.msg_type
    assert ours.data == theirs.data == {
        "utterance": "Hello Ada & Bob.", "expect_response": False, "lang": "en-US",
        "meta": {"dialog": "greeting", "data": {"name": "Ada & Bob"}, "skill": "punchline.test"},
    }
    assert ours.context == theirs.context


def test_the_fallback_reply_carries_the_twin(punchline):
    """`reply()` returns `self.dialog(...)`; the base speaks it with its markup."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, harness.skill.handle_fallback)
        preview = harness.skill.preview_reply("tell me a joke", "en-US")

    [message] = heard
    assert message.data["utterance_ssml"].startswith("<speak>")
    assert '<break time="700ms"/>' in message.data["utterance_ssml"]
    assert message.data["meta"] == {"skill": "punchline.test"}
    assert preview in _lines(DIALOG / "joke.dialog")


def test_a_built_sentence_reaches_the_room_that_asked(punchline):
    """speak_to forwards the message it was given, in that message's language."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, harness.skill.order_coffee, session={"session_id": "kitchen"})

    [message] = heard
    assert message.data["utterance"] == "One café au lait coming up. Enjoy."
    assert message.data["utterance_ssml"] == (
        '<speak>One <lang xml:lang="fr-FR">café au lait</lang> coming up. '
        '<break time="500ms"/> Enjoy.</speak>')
    assert message.context["session"]["session_id"] == "kitchen"


def test_the_legacy_mirror_carries_the_markup_too(punchline):
    """With OVOS_BUS_EMIT_LEGACY on, `speak` listeners get the same SSML."""
    with _live(punchline, emit_legacy=True) as harness:
        if getattr(harness.bus, "_translator", None) is None:
            pytest.skip("this ovos-utils FakeBus does not mirror the two namespaces")
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.tell_code("A1"))

    assert sorted(m.msg_type for m in heard) == ["ovos.utterance.speak", "speak"]
    assert len({m.data["utterance_ssml"] for m in heard}) == 1


def test_an_operator_override_is_spoken_without_the_packaged_markup(punchline):
    """When OVOS would render other lines than the skill's, OVOS renders them."""
    with _live(punchline) as harness:
        harness.skill.dialog_renderer.templates["joke"] = ["A joke of our own."]
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak_dialog("joke"))

    [message] = heard
    assert message.data["utterance"] == "A joke of our own."
    assert "utterance_ssml" not in message.data


def test_a_render_callback_that_changes_the_words_drops_the_markup(punchline):
    """The SSML no longer says the same thing, so it is not sent."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak_dialog(
            "joke", render_callback=lambda text, lang: text.upper()))
        _turn(harness, lambda message: harness.skill.speak_dialog(
            "joke", render_callback=lambda text, lang: text))

    changed, kept = heard
    assert changed.data["utterance"].isupper() and "utterance_ssml" not in changed.data
    assert "utterance_ssml" in kept.data


def test_varied_dialog_sends_the_twin_of_the_line_it_drew(punchline):
    """Two lines, two turns: both are heard once, each with its own markup."""
    plain, twins = _lines(DIALOG / "joke.dialog"), _lines(DIALOG / "joke.ssml")
    with _live(punchline) as harness:
        heard = _said(harness)
        for _ in range(2):
            _turn(harness, lambda message: harness.skill.speak_varied_dialog("joke"))

    assert sorted(m.data["utterance"] for m in heard) == sorted(plain)
    for message in heard:
        index = plain.index(message.data["utterance"])
        assert message.data["utterance_ssml"] == f"<speak>{twins[index]}</speak>"


def test_markup_written_where_the_words_go_is_moved(punchline):
    """`self.speak` with tags in a plain string: the tags never reach a phone."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak("Wait <break time='1s'/> for it."))

    [message] = heard
    assert message.data["utterance"] == "Wait for it."
    assert message.data["utterance_ssml"] == "<speak>Wait <break time='1s'/> for it.</speak>"
    assert message.context["session"]["session_id"] == "alice"


def test_plain_speech_is_handed_to_ovos(punchline, monkeypatch):
    """Without markup, `speak` is the framework's, with the same arguments."""
    from ovos_workshop.skills import OVOSSkill

    calls = []
    monkeypatch.setattr(OVOSSkill, "speak", lambda self, *args: calls.append(args))
    with _live(punchline) as harness:
        harness.skill.speak("plain words", True, 3, {"origin": "test"})
        harness.skill.speak(say("words", "only"))

    assert calls == [("plain words", True, 3, {"origin": "test"}),
                     ("words only", False, False, None)]
    assert type(calls[1][0]) is str


def test_marked_up_speech_keeps_meta_translation_data_and_wait(punchline, monkeypatch):
    """What `speak` does beside sending the words, it still does -- including
    waiting on the same session for as long as OVOS would."""
    from ovos_bus_client.session import SessionManager
    from ovos_workshop.skills import OVOSSkill

    waits = []
    monkeypatch.setattr(SessionManager, "wait_while_speaking", staticmethod(
        lambda timeout, session: waits.append((timeout, session.session_id, session.is_speaking))))
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.speak(
            say("Hold on.", pause("1s"), "Done."), expect_response=True, wait=7,
            meta={"translation_data": {"source_lang": "en-US"}}))
        _turn(harness, lambda message: OVOSSkill.speak(harness.skill, "Hold on.", wait=True))
        _turn(harness, lambda message: harness.skill.speak(say("Hi", pause()), wait=True))

    ours = heard[0]
    assert ours.data["expect_response"] is True
    assert ours.data["meta"]["skill"] == "punchline.test"
    assert ours.context["translation_data"] == {"source_lang": "en-US"}
    assert waits == [(7, "alice", True), (15, "alice", True), (15, "alice", True)]


def test_dialog_returns_a_speech_only_when_there_is_markup(punchline):
    """`self.dialog` stays a plain str for every dialog without markup."""
    with _live(punchline) as harness:
        skill = harness.skill
        joke = skill.dialog("joke", "en-US")
        french = skill.dialog("joke", "fr-FR")
        greeting = skill.dialog("greeting", "en-US", {"name": "Ada"})
        code = skill.dialog("code", "en-US", {"code": say("A", pause(), "B")})

    assert isinstance(joke, Speech) and joke.ssml
    assert type(french) is str
    assert type(greeting) is str and greeting == "Hello Ada."
    assert code.ssml == "Your code is A <break/> B."


def test_a_dialog_without_a_twin_anywhere_costs_one_lookup(punchline, monkeypatch):
    """Today's fleet has no twins: speaking must not resolve a language or
    read a locale tree to find that out."""
    from thalovant_skillkit.locale import SkillResources

    def unexpected(*args, **kwargs):
        raise AssertionError("dialog_twins was consulted for a dialog with no twin")

    monkeypatch.setattr(SkillResources, "dialog_twins", unexpected)
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.greet("Ada"))
        _turn(harness, lambda message: harness.skill.greet("Ada"))

    assert [m.data["utterance"] for m in heard] == ["Hello Ada.", "Hello Ada."]
    assert harness.skill.locale_resources._twin_cache == {"greeting": False}


def test_a_twin_written_as_a_whole_document_is_not_wrapped_twice(punchline):
    """`<speak xml:lang>` around a twin line: one root, the language kept."""
    with _live(punchline) as harness:
        heard = _said(harness)
        _turn(harness, lambda message: harness.skill.cheer())
        _turn(harness, lambda message: harness.skill.speak(
            "<speak xml:lang='fr-FR'>Bonjour <break/> toi.</speak>"))

    cheer, guarded = (m.data for m in heard)
    assert cheer["utterance"] == "Hooray, you did it!"
    assert cheer["utterance_ssml"] == ('<speak><lang xml:lang="en-US"><emphasis level="strong">'
                                       "Hooray</emphasis>, you did it!</lang></speak>")
    assert guarded["utterance"] == "Bonjour toi."
    assert guarded["utterance_ssml"] == (
        '<speak><lang xml:lang="fr-FR">Bonjour <break/> toi.</lang></speak>')
    for data in (cheer, guarded):
        assert data["utterance_ssml"].count("<speak") == 1
        assert validate(data["utterance_ssml"]) == []
