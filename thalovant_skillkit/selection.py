"""Small, independent shuffle bags for sounds, questions, or dialog lines."""
from __future__ import annotations

import random
from collections.abc import Iterable
from threading import RLock
from typing import Generic, TypeVar

T = TypeVar("T")
_UNSET = object()


class ShuffleBag(Generic[T]):
    """Draw every distinct item before reshuffling, avoiding immediate repeats.

    Equal items are kept once, in input order. An empty input raises ValueError.
    Pass a seeded ``random.Random`` to reproduce a sequence in a test. Each bag
    owns its state and lock; there is no process-wide history or session lookup.
    """

    def __init__(self, items: Iterable[T], *, rng: random.Random | None = None):
        unique: list[T] = []
        for item in items:
            if item not in unique:
                unique.append(item)
        if not unique:
            raise ValueError("A shuffle bag needs at least one item")
        self._items = tuple(unique)
        self._remaining: list[T] = []
        self._previous: T | object = _UNSET
        self._rng = rng if rng is not None else random
        self._lock = RLock()

    def draw(self, *, avoid: T | object = _UNSET) -> T:
        """Return one item, avoiding the previous draw when there is a choice.

        ``avoid`` replaces that default with an item the caller last delivered
        (for example, to this speaker). If it is the only item left in a larger
        pool, start a fresh cycle. A one-item pool always returns its item.
        The caller owns any broader session or playback lock.
        """
        with self._lock:
            previous = self._previous if avoid is _UNSET else avoid
            if len(self._items) > 1 and self._remaining == [previous]:
                self._remaining.clear()
            if not self._remaining:
                self._remaining.extend(self._items)
                self._rng.shuffle(self._remaining)
            if len(self._remaining) > 1 and self._remaining[-1] == previous:
                # Duplicate values were removed, so the first item differs.
                self._remaining[0], self._remaining[-1] = self._remaining[-1], self._remaining[0]
            choice = self._remaining.pop()
            self._previous = choice
            return choice
