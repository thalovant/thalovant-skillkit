"""Integration helpers retain upstream behavior and clean up failed scenarios."""
from __future__ import annotations

import gc
import importlib.util
import os
import subprocess
import sys
import wave
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from thalovant_skillkit import testing_ovos
from thalovant_skillkit.testing_ovos import (
    XDG_VARIABLES,
    CapturedTurn,
    capture_turn,
    deferred_capture_gc,
    isolated_xdg,
    managed_minicroft,
    skill_harness,
)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ovoscope") is None,
    reason="optional OVOS integration stack absent; install thalovant-skillkit[testing]",
)


@pytest.fixture
def integration_scope(tmp_path):
    with isolated_xdg(tmp_path), deferred_capture_gc():
        yield


def test_helper_import_does_not_load_ovos_before_xdg_can_be_isolated():
    subprocess.run([
        sys.executable, "-c",
        "import sys; import thalovant_skillkit.testing_ovos; "
        "assert not {'ovoscope', 'ovos_config', 'ovos_workshop', 'ovos_bus_client'}"
        ".intersection(sys.modules)",
    ], check=True, timeout=15)


def test_xdg_restores_present_and_absent_values_after_failure(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/original/config")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    previous = {name: os.environ.get(name) for name in XDG_VARIABLES}
    with pytest.raises(RuntimeError, match="scenario failed"), isolated_xdg() as directory:
        for name in XDG_VARIABLES:
            assert Path(os.environ[name]).is_dir()
            assert Path(os.environ[name]).is_relative_to(directory)
        raise RuntimeError("scenario failed")
    assert {name: os.environ.get(name) for name in XDG_VARIABLES} == previous
    assert not directory.exists()


def test_nested_xdg_scopes_restore_outer_paths_and_retain_caller_owned_root(tmp_path):
    with isolated_xdg(tmp_path) as outer:
        original = {name: os.environ[name] for name in XDG_VARIABLES}
        with isolated_xdg() as inner:
            assert inner != outer
            assert os.environ["XDG_CONFIG_HOME"] != original["XDG_CONFIG_HOME"]
        assert {name: os.environ[name] for name in XDG_VARIABLES} == original
    assert outer.exists()


def test_live_harness_dispatches_and_negotiates_scheduler_with_isolated_settings(
    integration_scope, tmp_path,
):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    from ovos_workshop.skills import OVOSSkill

    class ReplySkill(OVOSSkill):
        def initialize(self):
            self.initial_answer = self.settings["answer"]
            self.stopped = False
            self.add_event("test.skillkit.request", self.answer)

        def answer(self, message):
            self.bus.emit(message.reply("test.skillkit.response", {"answer": self.initial_answer}))

        def stop(self):
            self.stopped = True
            return True

    original_property = ReplySkill.settings_path
    with pytest.raises(RuntimeError, match="test failed"), skill_harness(
        ReplySkill, skill_id="skillkit-probe", settings={"answer": 42}, resources_dir=str(tmp_path),
    ) as harness:
        assert isinstance(harness.bus, FakeBus)
        assert harness.skill.is_fully_initialized
        settings_path = Path(harness.skill.settings_path)
        assert harness.skill.initial_answer == 42
        response = harness.bus.wait_for_response(
            Message("test.skillkit.request"), "test.skillkit.response", timeout=2,
        )
        assert response.data["answer"] == 42

        once = []
        harness.bus.once("test.skillkit.once", once.append)
        harness.bus.emit(Message("test.skillkit.once"))
        harness.bus.emit(Message("test.skillkit.once"))
        assert len(once) == 1

        assert harness.skill.event_scheduler.is_available()
        assert not harness.scheduler.is_alive()
        scheduled, cancelled = Event(), Event()
        harness.bus.on("ovos.scheduler.schedule.response", lambda message: scheduled.set())
        harness.bus.on("ovos.scheduler.cancel.response", lambda message: cancelled.set())
        harness.skill.schedule_event(lambda message: None, 3600, name="probe-event")
        assert scheduled.wait(2), "the real scheduler did not acknowledge the event"
        assert len(harness.scheduler.schedules) == 1
        harness.skill.cancel_scheduled_event("probe-event")
        assert cancelled.wait(2), "the real scheduler did not acknowledge cancellation"
        assert not harness.scheduler.schedules
        raise RuntimeError("test failed")
    assert harness.skill.stopped
    assert ReplySkill.settings_path is original_property
    assert not settings_path.exists()
    assert not harness.bus.ee.listeners("test.skillkit.request")
    assert not harness.bus.ee.listeners("ovos.scheduler.schedule")


def test_capture_propagates_only_the_originating_speakers_latest_session(integration_scope):
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus(modernize=False, emit_legacy=False)
    alice = Session("alice")
    alice.lang = "en-US"

    def reply(message):
        updated = Session.deserialize(message.context["session"])
        updated.lang = "fr-FR"
        bus.emit(Message("ovos.utterance.speak", {"utterance": "bonjour"},
                         {"session": updated.serialize()}))
        bus.emit(Message("background.update", {}, {"session": Session("bob").serialize()}))
        bus.emit(Message("test.turn.finished"))

    bus.on("test.turn", reply)
    before = len(bus.ee.listeners("message"))
    result = capture_turn(
        SimpleNamespace(bus=bus), Message("test.turn", {}, {"session": alice.serialize()}),
        eof_msgs=["test.turn.finished"], terminal_signals=False, timeout=1,
    )
    assert result.session.session_id == "alice"
    assert result.session.lang == "fr-FR"
    assert alice.lang == "en-US"
    assert result.spoken == ["bonjour"]
    assert len(result.of_type("background.update")) == 1
    assert len(bus.ee.listeners("message")) == before
    assert not bus.ee.listeners("test.turn.finished")


@pytest.mark.parametrize("topics", [
    ("speak",), ("ovos.utterance.speak",), ("speak", "ovos.utterance.speak"),
])
def test_session_view_selects_speech_without_namespace_twins(integration_scope, topics):
    """Filtering happens before namespace selection, and real repeats remain."""
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus(modernize=False, emit_legacy=False)
    alice = Session("alice")
    alice.lang = "fr-FR"
    bob = Session("bob")

    def reply(message):
        for _ in range(2):
            for topic in topics:
                bus.emit(Message(topic, {"utterance": "bonjour"},
                                 {"session": alice.serialize()}))
                audio_topic = "mycroft.audio.queue" if topic == "speak" else "ovos.audio.queue"
                bus.emit(Message(audio_topic, {"binary_data": b"alice".hex(), "audio_ext": "wav"},
                                 {"session": alice.serialize()}))
            # A canonical message from Bob must not hide Alice's legacy speech.
            bus.emit(Message("ovos.utterance.speak", {"utterance": "hello"},
                             {"session": bob.serialize()}))
            bus.emit(Message("ovos.audio.queue", {"binary_data": b"bob".hex(), "audio_ext": "wav"},
                             {"session": bob.serialize()}))
        bus.emit(Message("test.turn.finished"))

    bus.on("test.turn", reply)
    try:
        capture = capture_turn(
            SimpleNamespace(bus=bus), Message("test.turn", {}, {"session": alice.serialize()}),
            eof_msgs=["test.turn.finished"], terminal_signals=False, timeout=1,
        )
        alice_turn, bob_turn = capture.for_session("alice"), capture.for_session("bob")
        assert alice_turn.spoken == ["bonjour", "bonjour"]
        assert bob_turn.spoken == ["hello", "hello"]
        assert [audio.binary for audio in alice_turn.audio] == [b"alice", b"alice"]
        assert [audio.binary for audio in bob_turn.audio] == [b"bob", b"bob"]
        assert alice_turn.session.lang == "fr-FR"
        assert capture.session.session_id == "alice"
        assert len(capture.messages) > len(alice_turn.messages)
        assert capture.of_type("speak") == [m for m in capture.messages if m.msg_type == "speak"]
    finally:
        bus.close()


def test_session_view_excludes_unscoped_and_malformed_carriers(integration_scope):
    """An absent carrier is never inferred from the capture's originating session."""
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session

    alice = Session("alice")
    good = Message("speak", {"utterance": "mine"}, {"session": alice.serialize()})
    unscoped = Message("speak", {"utterance": "unscoped"})
    malformed = Message("speak", {"utterance": "bad"}, {"session": "alice"})
    capture = CapturedTurn([good, unscoped, malformed], alice)
    assert capture.spoken == ["mine", "unscoped", "bad"]  # Original behavior is unchanged.
    assert capture.for_session("alice").messages == [good]
    assert capture.for_session("alice").spoken == ["mine"]
    assert capture.for_session("unknown").messages == []
    assert capture.for_session("unknown").session is None
    for invalid in (None, "", "  ", 7):
        with pytest.raises(ValueError, match="session_id"):
            capture.for_session(invalid)


def test_native_audio_and_stop_keep_two_speakers_separate(integration_scope, tmp_path):
    """Inspect real OVOS play_audio bytes and Stop dispatch without starting a player."""
    from ovos_bus_client.message import Message, dig_for_message
    from ovos_bus_client.session import Session, SessionManager
    from ovos_workshop.skills import OVOSSkill

    sounds = {}
    for speaker, pcm in (("alice", b"\x01\x00\xff\xff"), ("bob", b"\x02\x00\xfe\xff")):
        path = tmp_path / f"{speaker}.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(pcm)
        sounds[speaker] = path

    class AudioSkill(OVOSSkill):
        def initialize(self):
            self.active_sessions = set()
            self.add_event("test.audio.play", self.play)

        def play(self, message):
            self.active_sessions.add(SessionManager.get(message).session_id)
            self.speak(message.data["text"])
            self.play_audio(message.data["sound"], instant=message.data.get("instant", False))

        def stop_session(self, session):
            self.active_sessions.discard(session.session_id)
            source = dig_for_message()
            self.bus.emit(source.forward("mycroft.audio.speech.stop", {"skill_id": self.skill_id}))
            return True

    sessions = {name: Session(name) for name in sounds}
    sessions["alice"].lang = "fr-FR"

    def source(speaker, topic="test.audio.play", *, instant=False):
        return Message(topic, {
            "text": "bonjour" if speaker == "alice" else "hello",
            "sound": str(sounds[speaker]), "instant": instant,
        }, {"session": sessions[speaker].serialize(), "source": f"speaker-{speaker}",
            "destination": "skills"})

    with skill_harness(
        AudioSkill, skill_id="skillkit-audio", scheduler=False, resources_dir=str(tmp_path),
    ) as harness:
        def interleave(message):
            harness.bus.emit(source("alice"))
            harness.bus.emit(source("bob"))
            harness.bus.emit(source("alice", "skillkit-audio.stop"))
            harness.bus.emit(source("bob", instant=True))
            harness.bus.emit(Message("test.turn.finished"))

        harness.bus.on("test.interleave", interleave)
        capture = capture_turn(
            SimpleNamespace(bus=harness.bus), Message("test.interleave"),
            eof_msgs=["test.turn.finished"], terminal_signals=False, timeout=2,
        )
        alice, bob = capture.for_session("alice"), capture.for_session("bob")
        assert alice.spoken == ["bonjour"]
        assert bob.spoken == ["hello", "hello"]
        for name, turn, count in (("alice", alice, 1), ("bob", bob, 2)):
            assert len(turn.audio) == count
            assert all(sound.binary == sounds[name].read_bytes() for sound in turn.audio)
            assert all(sound.extension == "wav" and sound.uri is None for sound in turn.audio)
            assert all(sound.message.context["source"] == f"speaker-{name}" for sound in turn.audio)
            assert all(sound.message.context["session"]["session_id"] == name
                       for sound in turn.audio)
        assert alice.session.lang == "fr-FR"
        assert len(alice.audio_stops) == 1
        assert alice.audio_stops[0].context["source"] == "speaker-alice"
        assert not bob.audio_stops
        response, = alice.of_type("skillkit-audio.stop.response")
        assert response.data["result"] is True
        assert response.context["destination"] == "speaker-alice"
        assert harness.skill.active_sessions == {"bob"}


def test_audio_inspection_prefers_namespace_twins_and_keeps_order(integration_scope):
    """Inspect URI and byte requests without fetching the URI or losing repeat queues."""
    from ovos_bus_client.message import Message

    payload = {"binary_data": b"example bytes".hex(), "audio_ext": "ogg"}
    queue = Message("ovos.audio.queue", payload)
    instant = Message("mycroft.audio.play_sound", {"uri": "https://invalid.test/cue.wav"})
    stop = Message("ovos.audio.stop")
    capture = CapturedTurn([
        Message("mycroft.audio.queue", payload), queue, instant,
        Message("mycroft.audio.queue", payload), queue,
        Message("mycroft.audio.speech.stop"), stop,
    ], None)
    assert [audio.message for audio in capture.audio] == [queue, instant, queue]
    assert capture.audio[0].binary == b"example bytes"
    assert capture.audio[0].extension == "ogg"
    assert capture.audio[1].uri == "https://invalid.test/cue.wav"
    assert capture.audio[1].binary is None
    assert capture.audio_stops == [stop]


@pytest.mark.parametrize("payload, error", [
    ({}, "expected either"),
    ({"uri": "cue.wav", "binary_data": "00"}, "expected either"),
    ({"uri": ""}, "uri must"),
    ({"binary_data": 12, "audio_ext": "wav"}, "hex text"),
    ({"binary_data": "not hex", "audio_ext": "wav"}, "invalid hexadecimal"),
    ({"binary_data": "00"}, "audio_ext"),
    ({"binary_data": "00", "audio_ext": ""}, "audio_ext"),
    ({"binary_data": "00", "audio_ext": 7}, "audio_ext"),
    ({"binary_data": "  ", "audio_ext": "wav"}, "no audio bytes"),
])
def test_audio_inspection_rejects_malformed_payloads(integration_scope, payload, error):
    """Bad transport data must fail an assertion rather than look like valid audio."""
    from ovos_bus_client.message import Message

    capture = CapturedTurn([Message("mycroft.audio.queue", payload)], None)
    with pytest.raises(AssertionError, match=error):
        _ = capture.audio


def test_timed_out_capture_fails_and_detaches_its_listeners(integration_scope):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus(modernize=False, emit_legacy=False)
    before = len(bus.ee.listeners("message"))
    with pytest.raises(AssertionError, match="timed out.*test.never.handled"):
        capture_turn(SimpleNamespace(bus=bus), Message("test.never.handled"), timeout=0.01)
    assert len(bus.ee.listeners("message")) == before
    assert not bus.ee.listeners("ovos.utterance.handled")


def test_capture_exception_detaches_its_listeners(integration_scope, monkeypatch):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus(modernize=False, emit_legacy=False)
    before = len(bus.ee.listeners("message"))

    def fail(_message):
        raise RuntimeError("bus unavailable")

    monkeypatch.setattr(bus, "emit", fail)
    with pytest.raises(RuntimeError, match="bus unavailable"):
        capture_turn(SimpleNamespace(bus=bus), Message("test.request"))
    assert len(bus.ee.listeners("message")) == before
    assert not bus.ee.listeners("ovos.utterance.handled")


def test_managed_minicroft_stops_after_a_scenario_failure(integration_scope):
    with pytest.raises(RuntimeError, match="test failed"), managed_minicroft(
        [], default_pipeline=[], wait_for_trained=False,
    ) as croft:
        assert croft.status.state.name == "READY"
        raise RuntimeError("test failed")
    # MiniCroft currently leaves ProcessStatus at STOPPING after stop() returns.
    # Assert the concrete resources were released, independent of that label.
    assert not croft.bus.ee.event_names()
    assert not croft.is_alive()


def test_gc_workaround_preserves_disabled_state_and_is_limited_to_known_versions(monkeypatch):
    known = {"ovoscope": "1.8.5a1", "pyee": "12.1.1"}
    monkeypatch.setattr(testing_ovos, "version", known.__getitem__)
    initially_enabled = gc.isenabled()
    try:
        gc.enable()
        with deferred_capture_gc():
            assert not gc.isenabled()
            with deferred_capture_gc():
                assert not gc.isenabled()
            assert not gc.isenabled()
        assert gc.isenabled()
        known["ovoscope"] = "999.0.0"
        with deferred_capture_gc():
            assert gc.isenabled()
    finally:
        if not initially_enabled:
            gc.disable()
