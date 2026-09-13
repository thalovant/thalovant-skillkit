"""Exercise real event dispatch, including interleaved callers and cleanup."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from thalovant_skillkit.bus import wait_for_response


def request(bus, key, **kwargs):
    return wait_for_response(
        bus, Message("request", {"id": key}), "response",
        matches=lambda response: response.data.get("id") == key, **kwargs,
    )


def test_synchronous_reply_ignores_unrelated_and_keeps_first_match():
    bus = FakeBus()

    def provider(message):
        bus.emit(Message("response", {"id": "unrelated"}))
        bus.emit(Message("response", {"id": message.data["id"], "value": "first"}))
        bus.emit(Message("response", {"id": message.data["id"], "value": "duplicate"}))

    bus.on("request", provider)
    assert request(bus, "a").data["value"] == "first"
    assert not bus.ee.listeners("response")


def test_simultaneous_callers_receive_only_their_own_replies():
    bus = FakeBus()
    barrier = Barrier(2)

    def provider(message):
        barrier.wait(timeout=2)
        bus.emit(Message("response", message.data))

    bus.on("request", provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda key: request(bus, key), ["a", "b"]))
    assert [reply.data["id"] for reply in replies] == ["a", "b"]
    assert not bus.ee.listeners("response")


def test_timeout_removes_listener_and_late_reply_does_not_poison_next_call():
    bus = FakeBus()
    assert request(bus, "expired", timeout=0.001) is None
    assert not bus.ee.listeners("response")

    def provider(message):
        bus.emit(Message("response", {"id": "expired"}))
        bus.emit(Message("response", message.data))

    bus.on("request", provider)
    assert request(bus, "current").data["id"] == "current"
    assert not bus.ee.listeners("response")


def test_emit_failure_removes_listener(monkeypatch):
    bus = FakeBus()

    def fail(message):
        raise OSError("transport closed")

    monkeypatch.setattr(bus, "emit", fail)
    with pytest.raises(OSError, match="transport closed"):
        request(bus, "a")
    assert not bus.ee.listeners("response")


def test_emitting_does_not_start_a_second_timeout_window(monkeypatch):
    from thalovant_skillkit import bus as helpers

    clock = [0.0]
    monkeypatch.setattr(helpers, "monotonic", lambda: clock[0])
    bus = FakeBus()

    def slow_transport(message):
        clock[0] = 3.0
        bus.emit(Message("response", message.data))

    bus.on("request", slow_transport)
    assert request(bus, "expired-during-emit", timeout=2.0) is None
    assert not bus.ee.listeners("response")


def test_predicate_failure_returns_to_caller_and_removes_listener():
    bus = FakeBus()
    bus.on("request", lambda message: bus.emit(Message("response")))

    def invalid_predicate(response):
        raise ValueError("invalid matcher")

    with pytest.raises(ValueError, match="invalid matcher"):
        wait_for_response(bus, Message("request"), "response", matches=invalid_predicate)
    assert not bus.ee.listeners("response")


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_has_no_bus_side_effects(timeout):
    bus = FakeBus()
    with pytest.raises(ValueError, match="positive and finite"):
        request(bus, "a", timeout=timeout)
    assert not bus.ee.listeners("response")
