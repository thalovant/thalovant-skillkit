from threading import Event

from thalovant_skillkit.workers import PeriodicWorker


def test_worker_stops_during_idle_wait_without_waiting_for_interval():
    entered = Event()
    worker = PeriodicWorker(lambda stop: entered.set(), interval=3600, name="test-worker")
    try:
        assert worker.start()
        assert entered.wait(5)
        assert not worker.start()
        assert worker.stop(timeout=1)
    finally:
        worker.stop()


def test_blocked_callback_prevents_duplicate_worker_after_stop():
    entered, release = Event(), Event()

    def callback(stop):
        entered.set()
        release.wait(5)

    worker = PeriodicWorker(callback, interval=3600, name="test-blocked-worker")
    try:
        assert worker.start()
        assert entered.wait(5)
        assert not worker.stop(timeout=0)
        assert not worker.start()
    finally:
        release.set()
        assert worker.stop(timeout=5)


def test_failed_pass_does_not_kill_worker():
    recovered = Event()
    calls = []

    def callback(stop):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("bad feed")
        recovered.set()

    worker = PeriodicWorker(callback, interval=0.01, name="test-recovery")
    try:
        worker.start()
        assert recovered.wait(5)
    finally:
        assert worker.stop()
