"""Integration helpers retain upstream behavior and clean up failed scenarios."""
from __future__ import annotations

import gc
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from thalovant_skillkit import testing_ovos
from thalovant_skillkit.testing_ovos import (
    XDG_VARIABLES,
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
