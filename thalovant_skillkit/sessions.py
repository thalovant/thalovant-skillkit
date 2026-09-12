"""Opt-in, bounded storage for a skill's volatile per-session state.

OVOS still owns session identity, activation and transport. This mapping only
holds application state keyed by the session ID the skill already resolved.
It starts no threads and invokes no lifecycle callbacks. Expiry is lazy; reads
never extend it. Values are not copied: hold ``store.lock`` around compound
read/modify/write operations, and keep blocking I/O and playback waits outside it.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar, cast

T = TypeVar("T")
_UNSET = object()


@dataclass
class _Entry(Generic[T]):
    value: T
    expires: float | None


def _duration(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < 0:
        raise ValueError("TTL must be finite and nonnegative, or None")
    return float(value)


class SessionStateStore(MutableMapping[str, T]):
    """A thread-safe mapping with optional TTL and oldest-write eviction.

    ``max_entries`` must be positive. Setting an existing key refreshes its
    expiry and moves it to the newest eviction position; getting it does
    neither. ``default_ttl=None`` preserves entries until explicitly removed
    or evicted. The injected ``clock`` must return monotonic seconds.

    Iteration, keys, values and items are independent snapshots of live entries.
    They remain safe if another handler replaces or removes an entry. Use
    ``remove(key, expected=value)`` when cleanup depends on such a snapshot:
    it cannot delete a different value subsequently stored under the same key.
    """

    def __init__(
        self,
        max_entries: int,
        default_ttl: float | None = None,
        clock: Callable[[], float] = monotonic,
    ):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries must be a positive integer")
        if max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self.default_ttl = _duration(default_ttl)
        self._clock = clock
        self._entries: dict[str, _Entry[T]] = {}
        self.lock = threading.RLock()

    def _prune(self, now: float) -> dict[str, T]:
        removed = {}
        for key, entry in tuple(self._entries.items()):
            if entry.expires is not None and entry.expires <= now:
                removed[key] = self._entries.pop(key).value
        return removed

    def prune(self) -> dict[str, T]:
        """Remove expired entries atomically and return their keys and values."""
        with self.lock:
            return self._prune(self._clock())

    def set(
        self,
        key: str,
        value: T,
        *,
        ttl: float | None | object = _UNSET,
        expires: float | object = _UNSET,
    ) -> None:
        """Store a value, optionally overriding its relative or absolute TTL.

        ``ttl=None`` disables expiry for this write. ``expires`` is an absolute
        deadline in the injected clock's time domain. Passing both is an error.
        An already expired write removes the previous value without evicting
        another live session. Validation happens before changing any entries.
        """
        if ttl is not _UNSET and expires is not _UNSET:
            raise ValueError("pass either ttl or expires, not both")
        duration = self.default_ttl if ttl is _UNSET else _duration(cast(float | None, ttl))
        if expires is not _UNSET and not math.isfinite(cast(float, expires)):
            raise ValueError("expires must be finite")
        with self.lock:
            now = self._clock()
            deadline = (
                cast(float, expires) if expires is not _UNSET
                else now + duration if duration is not None else None
            )
            self._prune(now)
            self._entries.pop(key, None)
            if deadline is not None and deadline <= now:
                return
            if len(self._entries) >= self.max_entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = _Entry(value, deadline)

    def remove(self, key: str, *, expected: T | object = _UNSET) -> bool:
        """Remove a live value, optionally only if it is the expected object."""
        with self.lock:
            self._prune(self._clock())
            entry = self._entries.get(key)
            if entry is None or (expected is not _UNSET and entry.value is not expected):
                return False
            del self._entries[key]
            return True

    def __getitem__(self, key: str) -> T:
        with self.lock:
            self._prune(self._clock())
            return self._entries[key].value

    def __setitem__(self, key: str, value: T) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        with self.lock:
            self._prune(self._clock())
            del self._entries[key]

    def __len__(self) -> int:
        with self.lock:
            self._prune(self._clock())
            return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> tuple[str, ...]:
        with self.lock:
            self._prune(self._clock())
            return tuple(self._entries)

    def values(self) -> tuple[T, ...]:
        return tuple(value for _, value in self.items())

    def items(self) -> tuple[tuple[str, T], ...]:
        with self.lock:
            self._prune(self._clock())
            return tuple((key, entry.value) for key, entry in self._entries.items())

    def pop(self, key: str, default: T | object = _UNSET) -> T:
        with self.lock:
            self._prune(self._clock())
            if key in self._entries:
                return self._entries.pop(key).value
            if default is _UNSET:
                raise KeyError(key)
            return cast(T, default)

    def popitem(self) -> tuple[str, T]:
        with self.lock:
            self._prune(self._clock())
            key, entry = self._entries.popitem()
            return key, entry.value

    def setdefault(self, key: str, default: T = None) -> T:
        with self.lock:
            self._prune(self._clock())
            if key in self._entries:
                return self._entries[key].value
            self.set(key, default)
            return default

    def clear(self) -> None:
        with self.lock:
            self._entries.clear()
