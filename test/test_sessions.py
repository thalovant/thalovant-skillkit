"""Session expiry and capacity stay correct across concurrent bus handlers."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread, current_thread

import pytest

from thalovant_skillkit.sessions import SessionStateStore


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_default_retention_does_not_expire_or_refresh_on_read():
    clock = Clock()
    store = SessionStateStore[str](max_entries=2, clock=clock)
    store["kitchen"] = "incidents"
    store["office"] = "weather"
    clock.now += 100000
    assert store.get("kitchen") == "incidents"
    store["bedroom"] = "music"
    assert store.items() == (("office", "weather"), ("bedroom", "music"))


def test_replacement_refreshes_recency_and_ttl_without_consuming_capacity():
    clock = Clock()
    store = SessionStateStore[str](2, default_ttl=10, clock=clock)
    store["kitchen"] = "old"
    store["office"] = "weather"
    clock.now += 5
    store["kitchen"] = "new"
    store["bedroom"] = "music"
    assert "office" not in store
    clock.now += 5
    assert store["kitchen"] == "new"
    clock.now += 5
    assert store.prune() == {"kitchen": "new", "bedroom": "music"}
    assert store.prune() == {}


def test_relative_absolute_and_disabled_expiry_share_one_monotonic_clock():
    clock = Clock()
    store = SessionStateStore[str](4, default_ttl=5, clock=clock)
    store.set("default", "a")
    store.set("relative", "b", ttl=10)
    store.set("absolute", "c", expires=120)
    store.set("forever", "d", ttl=None)
    clock.now = 105
    assert store.get("default") is None
    assert store.keys() == ("relative", "absolute", "forever")
    clock.now = 110
    assert store.prune() == {"relative": "b"}
    clock.now = 120
    assert store.values() == ("d",)


def test_reads_do_not_extend_expiry():
    clock = Clock()
    store = SessionStateStore[str](1, default_ttl=10, clock=clock)
    store["room"] = "game"
    clock.now = 109
    assert store.get("room") == "game"
    clock.now = 110
    assert store.get("room", "expired") == "expired"


def test_expired_entries_are_removed_before_evicting_a_live_session():
    clock = Clock()
    store = SessionStateStore[str](2, clock=clock)
    store["old-live"] = "a"
    store.set("new-expiring", "b", ttl=1)
    clock.now += 1
    store["new-live"] = "c"
    assert dict(store.items()) == {"old-live": "a", "new-live": "c"}


def test_immediately_expired_write_removes_only_its_own_previous_value():
    store = SessionStateStore[str](2)
    store["other"] = "keep"
    store["room"] = "old"
    store.set("room", "already over", ttl=0)
    store.set("new", "already over", expires=0)
    assert store.items() == (("other", "keep"),)


@pytest.mark.parametrize("ttl", [-1, float("nan"), float("inf")])
def test_invalid_expiry_cannot_mutate_existing_state(ttl):
    store = SessionStateStore[str](1)
    store["room"] = "keep"
    with pytest.raises(ValueError):
        store.set("room", "replace", ttl=ttl)
    assert store["room"] == "keep"
    with pytest.raises(ValueError):
        SessionStateStore(1, default_ttl=ttl)


def test_conflicting_or_nonfinite_deadlines_are_rejected():
    store = SessionStateStore[str](1)
    with pytest.raises(ValueError):
        store.set("room", "value", ttl=None, expires=100)
    with pytest.raises(ValueError):
        store.set("room", "value", expires=float("nan"))


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_capacity_must_be_a_positive_integer(capacity):
    with pytest.raises((TypeError, ValueError)):
        SessionStateStore(capacity)


def test_delayed_cleanup_does_not_remove_an_equal_but_new_state():
    @dataclass
    class State:
        mode: str

    old, new = State("detective"), State("detective")
    store = SessionStateStore[State](2)
    store["room"] = old
    snapshot = store.items()
    store["room"] = new
    assert snapshot == (("room", old),)
    assert not store.remove("room", expected=old)
    assert store["room"] is new
    assert store.remove("room", expected=new)
    assert not store.remove("room")


def test_mapping_helpers_operate_on_live_values_and_preserve_snapshots():
    clock = Clock()
    store = SessionStateStore[str](2, default_ttl=5, clock=clock)
    assert store.setdefault("room", "first") == "first"
    assert store.setdefault("room", "second") == "first"
    keys, items, iterator = store.keys(), store.items(), iter(store)
    store["other"] = "next"
    assert keys == ("room",)
    assert items == (("room", "first"),)
    assert tuple(iterator) == ("room",)
    clock.now += 5
    assert store.pop("room", "expired") == "expired"
    with pytest.raises(KeyError):
        store.pop("other")
    assert store.setdefault("room", "new") == "new"
    assert store.popitem() == ("room", "new")
    store.update({"a": "a", "b": "b"})
    del store["a"]
    assert store.pop("b") == "b"
    store["c"] = "c"
    store.clear()
    assert len(store) == 0


def test_pruning_cannot_delete_a_concurrent_replacement():
    """Pause after an expiry snapshot; another handler replaces the same ID.

    An unlocked snapshot/pop implementation can then delete the fresh value.
    The store must keep inspection and removal in one critical section.
    """
    clock = Clock()
    store = SessionStateStore[object](1, default_ttl=10, clock=clock)
    old, new = object(), object()
    store["room"] = old
    clock.now += 10
    snapshot_taken, replacement_started, replacement_done = Event(), Event(), Event()
    resume = Event()
    failures, removed = [], []

    class GatedEntries(dict):
        def items(self):
            snapshot = tuple(super().items())
            if current_thread().name == "expiry-cleanup":
                snapshot_taken.set()
                if not resume.wait(2):
                    raise AssertionError("test did not release the expiry snapshot")
            return snapshot

    store._entries = GatedEntries(store._entries)

    def prune():
        try:
            removed.append(store.prune())
        except BaseException as error:
            failures.append(error)

    def replace():
        try:
            replacement_started.set()
            store["room"] = new
        except BaseException as error:
            failures.append(error)
        finally:
            replacement_done.set()

    cleaner = Thread(target=prune, name="expiry-cleanup", daemon=True)
    writer = Thread(target=replace, name="replacement", daemon=True)
    cleaner.start()
    try:
        assert snapshot_taken.wait(2)
        writer.start()
        assert replacement_started.wait(2)
        # A correct implementation keeps the writer waiting for cleanup's
        # lock. An unlocked cleanup lets it replace the snapshotted entry.
        replacement_done.wait(0.1)
    finally:
        resume.set()
        cleaner.join(2)
        if writer.ident is not None:
            writer.join(2)
    assert not cleaner.is_alive() and not writer.is_alive()
    assert failures == []
    assert removed == [{"room": old}]
    assert store["room"] is new


def test_external_lock_supports_atomic_updates_without_blocking_other_stores():
    first, second = SessionStateStore[int](1), SessionStateStore[int](1)
    entered, finished = Event(), Event()
    failures = []
    first["room"] = 1

    def update():
        try:
            second["other"] = 2
            entered.set()
            with first.lock:
                first["room"] = first["room"] + 1
            finished.set()
        except BaseException as error:
            failures.append(error)

    with first.lock:
        worker = Thread(target=update, daemon=True)
        worker.start()
        assert entered.wait(2), "an unrelated store was blocked"
        assert not finished.is_set()
        first["room"] += 10
    worker.join(2)
    assert not worker.is_alive()
    assert failures == []
    assert finished.is_set() and first["room"] == 12
    assert second["other"] == 2
