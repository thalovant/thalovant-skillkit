"""Cooperative background work with one owner and interruptible idle waits."""
from __future__ import annotations

import logging
import math
from threading import Event, Lock, Thread, current_thread

LOG = logging.getLogger(__name__)


class PeriodicWorker:
    """Run ``callback(stop_event)`` immediately, then wait after each pass.

    The callback must honor cancellation and bound its own I/O. ``stop`` cannot
    kill Python threads. A still-running callback prevents a second start, and
    failed passes are logged and retried only after the ordinary interval.
    """

    def __init__(self, callback, *, interval: float, name: str):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be positive and finite")
        self.callback, self.interval, self.name = callback, interval, name
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    @property
    def running(self) -> bool:
        """Whether the thread is still alive, including cancellation in progress."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop = Event()
            self._thread = Thread(target=self._run, args=(self._stop,),
                                  name=self.name, daemon=True)
            self._thread.start()
            return True

    def _run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.callback(stop)
            except Exception:  # noqa: BLE001 - a bad pass must not kill the worker
                LOG.exception("Background task %s failed", self.name)
            stop.wait(self.interval)

    def stop(self, *, timeout: float = 1.0) -> bool:
        """Signal cancellation, wait at most timeout, return whether it stopped."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("join timeout must be nonnegative and finite")
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is None:
            return True
        if thread is current_thread():
            return False
        thread.join(timeout)
        return not thread.is_alive()
