"""Base classes that carry a skill's plumbing so the skill does not have to.

Before this, the smallest skill in the fleet was 369 lines and about 120 of
them were plumbing: a locale-directory constant, `_resource_lang`,
`_available_langs`, `_candidate_langs`, `_fold`, `_resource_file_lines`,
`_message_lang`, `_utterance`, a `_dialog` helper, thirteen lines of
`runtime_requirements`, and the fallback registration. None of that is the
skill. All of it had to be right before the skill could answer anything, and
when it was subtly wrong -- a `_message_lang` that read only the context, a
registration with no guard against running twice -- the failure showed up as a
skill that answered in the wrong language or answered twice.

A skill built on these classes writes its own behaviour and nothing else:

    from thalovant_skillkit.skill import ThalovantFallbackSkill

    class WeatherSkill(ThalovantFallbackSkill):
        FALLBACK_PRIORITY = 95

        def can_answer(self, message) -> bool:
            return self.voc_match("WeatherKeyword", self.utterance(message),
                                  self.lang_of(message))

        def handle_fallback(self, message) -> bool:
            self.speak(self.dialog("forecast", self.lang_of(message)))
            return True

The locale directory is found from the module the class is defined in, the
fallback is registered once at a priority an operator can override, and every
helper the skill used to hand-roll is a method.

Importing this module needs `ovos-workshop`; the rest of the library does not,
which is why it is not imported by the package root.
"""
from __future__ import annotations

import inspect
import random
from pathlib import Path
from typing import Any

from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.skills import OVOSSkill
from ovos_workshop.skills.fallback import FallbackSkill

from .fallback import register_once, resolve_priority
from .locale import SkillResources
from .message import location as _location
from .message import message_lang, utterance
from .text import fold


class _SkillPlumbing:
    """What both base classes share. Not used directly."""

    #: Where this skill's `locale/` tree lives. Found from the module the class
    #: is defined in, so a skill laid out like every other one sets nothing.
    LOCALE_DIR: Path | str | None = None

    #: Whether this skill needs the network to be up before it can load. Most
    #: do not, and the thirteen-line RuntimeRequirements block every skill was
    #: copying said so thirteen times.
    REQUIRES_NETWORK: bool = False
    REQUIRES_INTERNET: bool = False
    REQUIRES_GUI: bool = False

    _resources: SkillResources | None = None

    # -- what the skill is made of --------------------------------------------

    @classproperty
    def runtime_requirements(self):
        """Declared from three class attributes instead of thirteen lines.

        A skill that needs something unusual still overrides this outright.
        """
        return RuntimeRequirements(
            network_before_load=self.REQUIRES_NETWORK,
            internet_before_load=self.REQUIRES_INTERNET,
            gui_before_load=self.REQUIRES_GUI,
            requires_network=self.REQUIRES_NETWORK,
            requires_internet=self.REQUIRES_INTERNET,
            requires_gui=self.REQUIRES_GUI,
            no_network_fallback=not self.REQUIRES_NETWORK,
            no_internet_fallback=not self.REQUIRES_INTERNET,
            no_gui_fallback=not self.REQUIRES_GUI,
        )

    @property
    def resources(self) -> SkillResources:
        """This skill's `locale/` tree, bound once."""
        if self._resources is None:
            self._resources = SkillResources(self.locale_dir())
        return self._resources

    @classmethod
    def locale_dir(cls) -> Path:
        """`locale/` beside the module this skill is defined in."""
        if cls.LOCALE_DIR is not None:
            return Path(cls.LOCALE_DIR)
        return Path(inspect.getfile(cls)).resolve().parent / "locale"

    # -- reading a message ----------------------------------------------------

    @staticmethod
    def utterance(message: Any) -> str:
        """What was said, from whichever key the message carries it under."""
        return utterance(message)

    def lang_of(self, message: Any) -> str:
        """The language of this utterance, falling back to the skill's own."""
        return message_lang(message, self._own_lang())

    @staticmethod
    def location_of(message: Any) -> dict | None:
        """The house's location, as the satellite attaches it.

        Without it OVOS answers from its own default, which is Lawrence,
        Kansas -- an hour out and a continent away from most listeners.
        """
        return _location(message)

    def _own_lang(self) -> str:
        # `lang` is a property on OVOSSkill and can raise before the skill is
        # bound to a bus, which is exactly when tests construct one.
        try:
            return self.lang or "en-US"
        except Exception:  # noqa: BLE001 - an unbound skill still has a language
            return "en-US"

    # -- matching and speaking ------------------------------------------------

    @staticmethod
    def fold(text: str) -> str:
        """Casefolded and accent-free, for comparing against a vocabulary."""
        return fold(text)

    def voc_match(self, voc_name: str, utterance: str, lang: str | None = None) -> bool:
        """Whether the utterance contains a term from this vocabulary.

        Word-start matching, so `log` does not claim "technology" -- the bug
        that had five skills answering for each other.
        """
        return self.resources.voc_match(voc_name, utterance, lang or self._own_lang())

    def voc_term(self, voc_name: str, utterance: str, lang: str | None = None) -> str:
        """The matching vocabulary term itself, longest first, or ""."""
        return self.resources.voc_term(voc_name, utterance, lang or self._own_lang())

    def dialog(self, name: str, lang: str | None = None, data: dict | None = None) -> str:
        """One rendered line from `locale/<lang>/dialog/<name>.dialog`.

        Picked at random when the file offers several, so a skill asked the
        same thing twice does not answer identically. Falls back to English,
        and to the name itself if nothing is found -- a missing translation
        should sound wrong rather than raise mid-answer.
        """
        lines = self.resources.dialog_lines(name, lang or self._own_lang())
        if not lines:
            return name
        template = random.choice(lines)  # noqa: S311 - variety, not secrecy
        try:
            return template.format(**(data or {})).replace("\\n", "\n")
        except (KeyError, IndexError, ValueError):
            # KeyError and IndexError are a placeholder the caller did not
            # supply; ValueError is a malformed template, which `str.format`
            # raises for something as small as an unmatched brace. All three
            # are a translation that needs fixing, and none of them is worth
            # crashing a spoken reply over -- the skill says the raw line and
            # the mistake is audible.
            return template.replace("\\n", "\n")

    # -- settings -------------------------------------------------------------

    def setting(self, key: str, default: Any = None) -> Any:
        """One skill setting, with the default when it is absent or unreadable."""
        try:
            value = self.settings.get(key, default)
        except Exception:  # noqa: BLE001 - settings are absent before binding
            return default
        return default if value is None else value


class ThalovantSkill(_SkillPlumbing, OVOSSkill):
    """A skill that answers its own intents."""


class ThalovantFallbackSkill(_SkillPlumbing, FallbackSkill):
    """A skill that answers what no intent claimed.

    The rung is a claim about how much this skill deserves to be asked before
    everyone else. ovos-core runs the low band in ascending order and stops at
    the first skill whose `can_answer` says yes, so a broad claimer with a low
    number silently deletes every narrower skill behind it.
    """

    #: Where this skill sits in the ladder. 100 is the last voice in the house.
    FALLBACK_PRIORITY: int = 100

    def initialize(self):
        super().initialize()
        self.register_thalovant_fallback()

    def register_thalovant_fallback(self) -> bool:
        """Register `handle_fallback` once, at the priority in effect.

        Once, because skills re-run registration on reload and on a settings
        change and ovos-core will happily hold the same handler twice, which
        then answers twice.
        """
        return register_once(self, self.handle_fallback, self.fallback_priority())

    def fallback_priority(self) -> int:
        """The rung, after any operator override in settings."""
        return resolve_priority(self._settings_mapping(), self.FALLBACK_PRIORITY)

    def _settings_mapping(self) -> Any:
        try:
            return self.settings
        except Exception:  # noqa: BLE001 - settings are absent before binding
            return {}

    def can_answer(self, message: Any) -> bool:
        """Whether this skill has something to say about `message`.

        Answering unconditionally here makes the number above the whole of the
        skill's politeness: everything behind it stops being asked.
        """
        raise NotImplementedError

    def handle_fallback(self, message: Any) -> bool:
        """Say it. Return True when the skill answered."""
        raise NotImplementedError
