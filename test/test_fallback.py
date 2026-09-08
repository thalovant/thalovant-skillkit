"""The ladder rung, and registering on it once."""
from __future__ import annotations

import pytest

from thalovant_skillkit import register_once, resolve_priority


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"fallback_priority": 96}, 96),        # an operator moving it within the band
        ({"fallback_priority": "96"}, 96),      # settings files hold strings
        ({}, 98),                               # nothing configured
        ({"fallback_priority": None}, 98),
        ({"fallback_priority": "high"}, 98),    # not a number at all
        ({"fallback_priority": 5}, 98),         # outside the low band
        ({"fallback_priority": 101}, 98),
        ({"fallback_priority": 90}, 98),        # 90 is the medium band's last rung
        # 100 is a real rung -- custos-fallback sits on it as the last voice in
        # the house -- so it has to be accepted, which the skills' own
        # `90 < priority < 100` guard would have refused.
        ({"fallback_priority": 100}, 100),
    ],
)
def test_an_override_is_honoured_only_inside_the_low_band(override, expected):
    """Refused rather than clamped: a 5 in a settings file is far likelier to
    be a mistake than a request to outrank the stop pipeline, and quietly
    moving it to 90 would hide that."""
    assert resolve_priority(override, 98) == expected


def test_settings_that_are_not_a_mapping_do_not_break_registration():
    assert resolve_priority(None, 98) == 98
    assert resolve_priority(object(), 98) == 98


class FakeSkill:
    def __init__(self):
        self._fallback_handlers = []

    def register_fallback(self, handler, priority):
        self._fallback_handlers.append((priority, handler))


def test_a_handler_is_registered_once_however_often_registration_runs():
    """Skills re-run registration on reload and on settings changes, and
    ovos-core will happily hold the same handler twice -- which then answers
    twice."""
    skill = FakeSkill()

    def handler(message):
        return True

    assert register_once(skill, handler, 98) is True
    assert register_once(skill, handler, 98) is False
    assert skill._fallback_handlers == [(98, handler)]
