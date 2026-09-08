"""Where a skill sits in the fallback ladder, and registering it there once.

ovos-core consults fallbacks in three bands -- high (0,5], medium (5,90], low
(90,101] -- and inside a band runs them in ascending priority, stopping at the
first skill whose `can_answer` says yes. A skill's number is therefore a claim
about how much it deserves to be asked before everyone else, and a broad
claimer with a low number silently deletes every narrower skill behind it.

That is not hypothetical. custos-fallback answered `can_answer` unconditionally
at 95 and silenced nine siblings; source-scout was moved to 98 on the
assumption it was specific, and answered "remember that the garage code is
1234" with advice about choosing PINs.

Every fallback skill wrote the same two helpers: read an operator override out
of settings and refuse it if it leaves the band, and guard against registering
the same handler twice on a reload.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

LOW_BAND = (90, 101)


def resolve_priority(settings: Any, default: int, band: tuple[int, int] = LOW_BAND) -> int:
    """An operator's `fallback_priority` override, or the skill's own default.

    An override outside the band is refused rather than clamped: a number like
    5 in a settings file is far more likely to be a mistake than a request to
    outrank the stop pipeline, and silently moving it to 90 would hide that.
    """
    try:
        raw = (settings or {}).get("fallback_priority", default)
    except AttributeError:
        return default
    try:
        priority = int(raw)
    except (TypeError, ValueError):
        return default
    low, high = band
    return priority if low < priority < high else default


def register_once(skill: Any, handler: Callable, priority: int) -> bool:
    """Register `handler` as a fallback unless it is already registered.

    Skills re-run their registration on reload and on settings changes, and
    ovos-core is happy to hold the same handler twice -- which then answers
    twice.  Returns whether the registration happened.
    """
    for _priority, registered in getattr(skill, "_fallback_handlers", ()) or ():
        if registered == handler:
            return False
    skill.register_fallback(handler, priority)
    return True
