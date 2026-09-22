"""Bound service work for a spoken turn without sharing deadlines across speakers."""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from urllib.error import URLError
from urllib.request import Request, urlopen

from .service import request_headers


class RequestBudget:
    """A context-local deadline shared by all network calls in one reply.

    Checks between reads cannot interrupt a blocked socket operation. Always
    pass ``timeout()`` to the transport too; overshoot is bounded by that socket
    timeout, not a hard wall-clock cancellation guarantee.
    """

    def __init__(self, *, clock=monotonic):
        self.clock = clock
        self._deadline: ContextVar[float | None] = ContextVar("skillkit_deadline", default=None)

    @property
    def deadline(self) -> float | None:
        return self._deadline.get()

    @deadline.setter
    def deadline(self, value: float | None) -> None:
        self._deadline.set(value)

    @contextmanager
    def limit(self, seconds: float):
        """Restore the previous deadline on exit; nested limits never extend it."""
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("budget must be positive and finite")
        deadline = self.clock() + seconds
        previous = self.deadline
        token = self._deadline.set(min(previous, deadline) if previous is not None else deadline)
        try:
            yield self
        finally:
            self._deadline.reset(token)

    def remaining(self) -> float:
        return math.inf if self.deadline is None else self.deadline - self.clock()

    def timeout(self, preferred: float) -> float:
        if not math.isfinite(preferred) or preferred <= 0:
            raise ValueError("timeout must be positive and finite")
        return max(0.0, min(preferred, self.remaining()))

    def read(self, response, *, max_bytes: int = 2 * 1024 * 1024,
             chunk_bytes: int = 64 * 1024) -> bytes:
        """Read a complete body or raise; never return silently truncated data."""
        if max_bytes < 1 or chunk_bytes < 1:
            raise ValueError("response and chunk limits must be positive")
        chunks = []
        total = 0
        while True:
            if self.remaining() <= 0:
                raise TimeoutError("reply network budget exhausted")
            chunk = response.read(min(chunk_bytes, max_bytes - total + 1))
            if self.remaining() <= 0:
                raise TimeoutError("reply network budget exhausted")
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("response exceeds byte limit")
            chunks.append(chunk)


class JsonServiceClient:
    """One skill's identified, bounded JSON requests and per-URL failure cooldown.

    Calls are attempted once: replaying an unknown POST may repeat an action.
    Missing, oversized, malformed, non-object and failed responses return None;
    the skill decides the spoken fallback. A budget exhausted before a request
    does not mark a service unhealthy. No URL, payload, or credentials are logged.
    """

    def __init__(self, skill_name: str, skill_version: str, *,
                 budget: RequestBudget | None = None, cooldown: float = 30,
                 max_bytes: int = 2 * 1024 * 1024, clock=monotonic):
        if not math.isfinite(cooldown) or cooldown < 0 or max_bytes < 1:
            raise ValueError("invalid cooldown or response limit")
        self.skill_name, self.skill_version = skill_name, skill_version
        self.budget = budget or RequestBudget(clock=clock)
        self.cooldown, self.max_bytes, self.clock = cooldown, max_bytes, clock
        self._failures: dict[str, float] = {}
        self._lock = Lock()

    def post(self, url: str, payload: dict, *, timeout: float = 2.4, opener=None) -> dict | None:
        if not url:
            return None
        with self._lock:
            now = self.clock()
            self._failures = {key: until for key, until in self._failures.items() if until > now}
            if url in self._failures:
                return None
        timeout = self.budget.timeout(timeout)
        if timeout <= 0:
            return None
        headers = request_headers(self.skill_name, self.skill_version,
                                  f"{self.skill_name}/{self.skill_version}")
        headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        try:
            request = Request(url, data=json.dumps(payload).encode("utf-8"),
                              headers=headers, method="POST")
            with self.budget.limit(timeout):
                with (opener or urlopen)(request, timeout=timeout) as response:
                    value = json.loads(self.budget.read(response, max_bytes=self.max_bytes))
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object")
            return value
        except (OSError, URLError, ValueError, TypeError):
            with self._lock:
                if len(self._failures) >= 128:
                    self._failures.pop(next(iter(self._failures)))
                self._failures[url] = self.clock() + self.cooldown
            return None
