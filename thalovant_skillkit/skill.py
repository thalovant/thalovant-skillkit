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
            return self.mentions(self.utterance(message), "WeatherKeyword",
                                 self.lang_of(message))

        def reply(self, utterance, lang, context):
            return self.dialog("forecast", lang)

The locale directory is found from the module the class is defined in, the
fallback is registered once at a priority an operator can override, and every
helper the skill used to hand-roll is a method.

Importing this module needs `ovos-workshop`; the rest of the library does not,
which is why it is not imported by the package root.
"""
from __future__ import annotations

import inspect
import random
import re
from pathlib import Path
from typing import Any

from ovos_bus_client.message import dig_for_message
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import skill_api_method
from ovos_workshop.skills import OVOSSkill
from ovos_workshop.skills.fallback import FallbackSkill

try:
    # ovos-workshop 9 factored converse out of OVOSSkill. A skill that keeps a
    # conversation going -- a game, a multi-turn question -- needs this base,
    # and every such skill was carrying this same try/except itself.
    from ovos_workshop.skills.converse import ConversationalSkill as _ConversationalBase
except ImportError:  # pragma: no cover - ovos-workshop 8 has converse built in
    _ConversationalBase = OVOSSkill

try:
    # The common-play framework brings its own base, and a skill that answers
    # OCP searches must keep it. Absent when this workshop ships no OCP.
    from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill as _CommonPlayBase
except ImportError:  # pragma: no cover - a workshop without OCP
    _CommonPlayBase = None

from .fallback import register_once, resolve_priority
from .locale import SkillResources
from .message import context_of, message_lang, utterance
from .message import location as _location
from .selection import ShuffleBagPool
from .speech import emit_speech
from .speech import speak_to as _speak_to
from .ssml import carries_markup, render_line, speech_parts
from .text import fold

# OVOS's renderer turns `{{name}}` into `{name}` before formatting a dialog.
_MUSTACHE = re.compile(r"\{\{+\s*(.*?)\s*\}\}+")
# `(a|b)` and `[optional]`: OVOS expands these after formatting and picks one
# expansion at random. The same choice cannot be made in an SSML twin, so a
# dialog written this way is left to OVOS and speaks without markup.
_ALTERNATIVES = re.compile(r"\([^()]*\|[^()]*\)|\[[^\[\]]*\]")


def _twin_speech(skill: Any, key: str, data: dict | None, framework_lines, draw):
    """The dialog line and its SSML twin, rendered from one variant, or None.

    None means "let OVOS speak it exactly as it always has": no twin and no
    marked-up value, a dialog OVOS would render from different lines (a user
    override, another language), alternatives OVOS expands at random, or any
    failure at all. Markup is an addition to a reply and must never cost one.

    `framework_lines()` returns the lines OVOS would render from; `draw(lines,
    lang)` picks one of them.
    """
    try:
        values = data or {}
        resources = skill.locale_resources
        if not carries_markup(values) and not resources.has_ssml(key):
            return None  # the common case, answered before asking for a language
        lang = skill.lang
        lines, twins = resources.dialog_twins(key, lang)
        if not lines or (twins is None and not carries_markup(values)):
            return None
        if any(_ALTERNATIVES.search(line) for line in lines):
            return None
        lines = tuple(_MUSTACHE.sub(r"{\1}", line) for line in lines)
        framework = framework_lines()
        if framework is None or tuple(framework) != lines:
            return None
        index = lines.index(draw(lines, lang))
        twin = _MUSTACHE.sub(r"{\1}", twins[index]) if twins else None
        return render_line(lines[index], twin, values)
    except Exception:  # noqa: BLE001 - OVOS's own path is the fallback
        return None


class _SkillPlumbing:
    """Shared helpers for SkillKit's OVOS base classes. Not used directly."""

    #: Where this skill's `locale/` tree lives. Found from the module the class
    #: is defined in, so a skill laid out like every other one sets nothing.
    LOCALE_DIR: Path | str | None = None

    #: Whether this skill needs the network to be up before it can load. Most
    #: do not, and the thirteen-line RuntimeRequirements block every skill was
    #: copying said so thirteen times.
    REQUIRES_NETWORK: bool = False
    REQUIRES_INTERNET: bool = False
    REQUIRES_GUI: bool = False

    # None preserves the historical behavior derived from REQUIRES_*. A skill
    # can need internet during playback yet load and offer a packaged fallback.
    NETWORK_BEFORE_LOAD: bool | None = None
    INTERNET_BEFORE_LOAD: bool | None = None
    GUI_BEFORE_LOAD: bool | None = None
    NO_NETWORK_FALLBACK: bool | None = None
    NO_INTERNET_FALLBACK: bool | None = None
    NO_GUI_FALLBACK: bool | None = None

    _resources: SkillResources | None = None

    # -- what the skill is made of --------------------------------------------

    @classproperty
    def runtime_requirements(self):
        """Declared from three class attributes instead of thirteen lines.

        A skill that needs something unusual still overrides this outright.
        """
        def configured(value, default):
            return default if value is None else value

        return RuntimeRequirements(
            network_before_load=configured(self.NETWORK_BEFORE_LOAD, self.REQUIRES_NETWORK),
            internet_before_load=configured(self.INTERNET_BEFORE_LOAD, self.REQUIRES_INTERNET),
            gui_before_load=configured(self.GUI_BEFORE_LOAD, self.REQUIRES_GUI),
            requires_network=self.REQUIRES_NETWORK,
            requires_internet=self.REQUIRES_INTERNET,
            requires_gui=self.REQUIRES_GUI,
            no_network_fallback=configured(self.NO_NETWORK_FALLBACK, not self.REQUIRES_NETWORK),
            no_internet_fallback=configured(self.NO_INTERNET_FALLBACK, not self.REQUIRES_INTERNET),
            no_gui_fallback=configured(self.NO_GUI_FALLBACK, not self.REQUIRES_GUI),
        )

    @property
    def locale_resources(self) -> SkillResources:
        """This skill's `locale/` tree, bound once.

        Deliberately not called `resources`: `OVOSSkill.resources` is the
        framework's own per-language resource object and several of its methods
        go through it. Shadowing it with a different class would break them
        quietly.
        """
        if self._resources is None:
            self._resources = SkillResources(self.locale_dir())
        return self._resources

    @classmethod
    def locale_dir(cls) -> Path:
        """`locale/` beside the module the skill is defined in.

        Walks the class hierarchy from the most derived class up and takes the
        first one that actually has a `locale/` beside it. Reading only the
        leaf class broke the moment anything subclassed a skill -- a test
        harness in `test/`, or one skill extending another -- because the
        subclass's module has no locale tree and the skill answered with dialog
        names instead of dialog.
        """
        if cls.LOCALE_DIR is not None:
            return Path(cls.LOCALE_DIR)
        fallback: Path | None = None
        for klass in cls.__mro__:
            if klass.__module__.startswith("thalovant_skillkit") or klass is object:
                continue
            try:
                candidate = Path(inspect.getfile(klass)).resolve().parent / "locale"
            except (TypeError, OSError):
                continue
            fallback = fallback or candidate
            if candidate.is_dir():
                return candidate
        # Nothing has one: name the leaf class's location, so the error points
        # at the skill rather than at the library.
        return fallback or Path(inspect.getfile(cls)).resolve().parent / "locale"

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
        """A location dictionary from message context, then data, or None.

        This helper does not read session location or supply a default city.
        The skill decides how to handle an absent location.
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

    def mentions(self, utterance: str, voc_name: str, lang: str | None = None) -> bool:
        """Whether the utterance mentions a term from this vocabulary.

        Not `voc_match`: that name belongs to `OVOSSkill`, and taking it with a
        different argument order would silently swap the arguments of any call
        the framework makes.

        The difference from `self.voc_match` is inflection. OVOS matches whole
        words -- `re.match(r'.*\b' + term + r'\b.*')` -- so a `logs.voc`
        listing `log` does not match "logs", which is why skills wrote their own
        containment version and inherited the bug where `log` claimed
        "technology". This matches a term at the start of a word plus a short
        ending, so "logs" counts and "technology" does not.

        Reach for `self.voc_match(utt, voc)` when whole words are what you mean.
        """
        return self.locale_resources.voc_match(voc_name, utterance, lang or self._own_lang())

    def mentioned_term(self, utterance: str, voc_name: str, lang: str | None = None) -> str:
        """The vocabulary term the utterance mentioned, longest first, or ""."""
        return self.locale_resources.voc_term(voc_name, utterance, lang or self._own_lang())

    def dialog(self, name: str, lang: str | None = None, data: dict | None = None) -> str:
        """One rendered line from `locale/<lang>/dialog/<name>.dialog`.

        Picked at random when the file offers several; repeats are possible.
        Uses the locale resource fallback chain and returns the name itself
        if no dialog is found. Missing formatting values leave the template
        visible instead of raising during an answer.

        When `<name>.ssml` sits beside the dialog, or a value in `data` is an
        `ssml.Speech` with markup, the result is a `Speech`: the same line,
        plus its SSML rendered from the same variant and the same data.
        Speaking it sends both; anything else sees the plain line.
        """
        lines, twins = self.locale_resources.dialog_twins(name, lang or self._own_lang())
        if not lines:
            return name
        index = random.randrange(len(lines))  # noqa: S311 - variety, not secrecy
        template = lines[index]
        values = data or {}
        if twins is None and not carries_markup(values):
            try:
                return template.format(**values).replace("\\n", "\n")
            except (KeyError, IndexError, ValueError):
                # KeyError and IndexError are a placeholder the caller did not
                # supply; ValueError is a malformed template, which `str.format`
                # raises for something as small as an unmatched brace. All three
                # are a translation that needs fixing, and none of them is worth
                # crashing a spoken reply over -- the skill says the raw line and
                # the mistake is audible.
                return template.replace("\\n", "\n")
        twin = twins[index].replace("\\n", "\n") if twins else None
        try:
            return render_line(template.replace("\\n", "\n"), twin, values)
        except (KeyError, IndexError, ValueError):
            return template.replace("\\n", "\n")

    @staticmethod
    def context_of(message: Any) -> dict:
        """The message context, or {}."""
        return context_of(message)

    def speak_varied_dialog(self, key: str, data: dict | None = None, *,
                            expect_response: bool = False, wait: bool = False):
        """Speak curated lines without repeats, preserving OVOS rendering hooks.

        Framework resource overrides win over packaged lines. Selection history
        is local to this skill instance and bounded; reloaded choices replace
        their old bag. Ordinary ``speak_dialog`` remains unchanged. A `.ssml`
        twin is sent with the line drawn, as `speak_dialog` does.
        """
        # OVOS initializes settings before a skill handles messages. setdefault
        # also makes lazy initialization safe for concurrent first turns.
        bags = self.__dict__.get("_varied_dialog_bags")
        if bags is None:
            bags = self.__dict__.setdefault("_varied_dialog_bags", ShuffleBagPool[str]())

        speech = _twin_speech(
            self, key, data, lambda: self.resources.load_dialog_file(key),
            lambda lines, lang: bags.draw(lines, key=(lang, key))[0],
        )
        if speech is not None:
            return self.speak(speech, expect_response, wait,
                              meta={"dialog": key, "data": data or {}})

        def choose_line(rendered, lang):
            lines = (self.resources.load_dialog_file(key)
                     or self.locale_resources.dialog_lines(key, lang))
            if not lines:
                return rendered
            template = bags.draw(lines, key=(lang, key))[0]
            return template.format(**(data or {}))

        return self.speak_dialog(key, data, expect_response=expect_response, wait=wait,
                                 render_callback=choose_line)

    # -- speaking, with markup beside the words ---------------------------------
    #
    # These two keep OVOSSkill's names and signatures on purpose: every skill
    # already calls them, so a skill gets SSML by adding a `.ssml` twin and
    # changes no code. Without markup they hand the call to OVOS unchanged.

    def speak(self, utterance: str, expect_response: bool = False,
              wait: bool | int = False, meta: dict | None = None):
        """OVOS's `speak`, which also sends the markup of an `ssml.Speech`.

        Plain text goes to OVOS exactly as before. A Speech with markup is
        sent the way OVOS sends a sentence -- the message being answered,
        forwarded; the skill's language; `meta`; `wait` -- with
        `utterance_ssml` beside the words. A plain string holding SSML tags
        is moved into `utterance_ssml` and logged once, so a tag never
        reaches a client that shows or says `utterance` as written.
        """
        text, ssml = speech_parts(utterance, getattr(self, "skill_id", None))
        if ssml is None:
            return super().speak(text, expect_response, wait, meta)
        return emit_speech(self, dig_for_message(), text, lang=self.lang,
                           expect_response=expect_response, meta=meta, wait=wait, ssml=ssml)

    def speak_dialog(self, key: str, data: dict | None = None,
                     expect_response: bool = False, wait: bool | int = False,
                     render_callback=None):
        """OVOS's `speak_dialog`, which also sends the dialog's `.ssml` twin.

        With a twin, or a value in `data` that is an `ssml.Speech` with
        markup, one variant is drawn and both forms are rendered from it
        with the same data; the SSML's values are escaped. Otherwise --
        including when OVOS would render from other lines than the skill's
        own, such as an operator's override -- OVOS renders and speaks the
        dialog exactly as before. A `render_callback` that changes the line
        drops the markup, since it no longer says the same words.
        """
        speech = _twin_speech(
            self, key, data, lambda: self._framework_dialog_lines(key),
            self._draw_dialog_line,
        )
        if speech is None:
            return super().speak_dialog(key, data, expect_response, wait, render_callback)
        if render_callback is not None:
            rendered = render_callback(str(speech), self.lang)
            if rendered != str(speech):
                speech = rendered
        return self.speak(speech, expect_response, wait,
                          meta={"dialog": key, "data": data or {}})

    def _framework_dialog_lines(self, key: str):
        """The lines OVOS's renderer holds for `key`, or None if it cannot say."""
        templates = getattr(self.dialog_renderer, "templates", None)
        if not isinstance(templates, dict):
            return None
        return tuple(templates.get(key) or ())

    def _draw_dialog_line(self, lines: tuple[str, ...], lang: str) -> str:
        """A line not said last time, as OVOS's renderer avoids repeats."""
        bags = self.__dict__.get("_dialog_twin_bags")
        if bags is None:
            bags = self.__dict__.setdefault("_dialog_twin_bags", ShuffleBagPool[str]())
        return bags.draw(lines, key=(lang, lines))[0]

    def speak_to(self, message: Any, text: str, *, lang: str | None = None,
                 expect_response: bool = False, written: str | None = None,
                 meta: dict | None = None, wait: bool | int = False):
        """Say `text` to whoever sent `message`, in their language.

        `self.speak` finds the message it answers by walking the call stack and
        speaks in `self.lang`, which is wrong for a converse turn or a stop
        hook, and wrong on a hub answering two rooms in two languages. This
        forwards the message you were given, so the reply keeps its session
        and reaches the room that asked. `text` may be an `ssml.Speech`, whose
        markup is sent beside the words. `wait` blocks as `speak(wait=...)`
        does. Returns the emitted message, or None for empty text.
        """
        return _speak_to(self, message, text, lang=lang or self.lang_of(message),
                         expect_response=expect_response, written=written, meta=meta,
                         wait=wait)

    # -- the answer -----------------------------------------------------------

    def reply(self, utterance: str, lang: str, context: dict) -> str | None:
        """The skill's answer as text, or None when it has none.

        The fallback base calls this after can_answer and speaks a nonempty
        result. Other bases require their own handlers to invoke it. A preview
        calls the same logic independently, so random or changing results can
        differ between calls.
        """
        raise NotImplementedError

    @skill_api_method
    def preview_reply(
        self, utterance: str = "", lang: str | None = None, context: dict | None = None
    ) -> str:
        """Expose reply text through the skill API without speaking or routing.

        A configured preview integration can call this method. It returns an
        empty string for an absent reply or an unimplemented reply hook; other
        exceptions propagate. Side effects inside reply still execute.
        """
        try:
            return self.reply(utterance or "", lang or self._own_lang(), context or {}) or ""
        except NotImplementedError:
            return ""

    # -- settings -------------------------------------------------------------

    def setting(self, key: str, default: Any = None) -> Any:
        """One skill setting, with the default when it is absent or unreadable."""
        try:
            value = self.settings.get(key, default)
        except Exception:  # noqa: BLE001 - settings are absent before binding
            return default
        return default if value is None else value


class _ConverseEligibility:
    """A `can_converse` that answers instead of raising.

    ovos-workshop 9 made `can_converse` an abstractmethod whose body is
    `raise NotImplementedError`. Nothing enforces it -- `OVOSSkill` is not an
    ABC, so a subclass without it instantiates and loads perfectly -- and the
    only thing that ever calls it is the `<skill_id>.converse.ping` handler.
    So a skill that overrode `converse()` and not `can_converse()` loaded
    fine, answered no ping, and its `converse()` was never called. It read as
    a skill ignoring the answer to its own question.

    That is not hypothetical twice over: `thalovant-skill-alarm` 0.1.17
    shipped a `converse()` that never ran, and `thalovant-skill-reminder`
    inherits this base today with the abstract method still in place.

    **True is the honest default**, and it is what ovos-workshop 8 did: there
    was no ping, `converse()` was simply called for every active skill and
    decided for itself. Every skill here is written that way -- each one
    opens `converse()` with its own guards and returns False when the turn is
    not its own -- so answering the ping with True restores exactly the
    behaviour the code was written against.

    A subclass should still override this with a cheap, **pure** probe where
    it can: the ping is put to every candidate in a round, including rounds
    the skill will not win, so a real `converse()` dispatch is more work than
    a question needs. It must have no side effects and must not raise; a
    probe that throws takes the whole converse round with it.
    """

    def can_converse(self, message) -> bool:
        return True


class ThalovantSkill(_SkillPlumbing, OVOSSkill):
    """A skill that answers its own intents."""


class ThalovantConversationalSkill(_SkillPlumbing, _ConverseEligibility, _ConversationalBase):
    """A skill that keeps a conversation going after its first answer.

    `converse()` receives the next thing the person says while the skill is
    active, which is how a game asks its next question or a skill takes a
    follow-up. On ovos-workshop 8 this is the same as `ThalovantSkill`.
    """


if _CommonPlayBase is not None:

    class ThalovantCommonPlaySkill(_SkillPlumbing, _CommonPlayBase):
        """A skill that answers OCP searches, with the plumbing carried.

        The common-play framework brings its own base, so this is the
        ordinary `ThalovantSkill` treatment applied to that one instead:
        the same helpers, the same locale handling, no OCP behaviour of its
        own. Without it a common-play skill has to reach for the private
        mixin, which is how the news skill found this gap.
        """

    if _ConversationalBase is OVOSSkill:  # pragma: no cover - Workshop 8
        _ConversationalPlayBases = (_ConverseEligibility, ThalovantCommonPlaySkill)
    else:
        _ConversationalPlayBases = (
            _ConverseEligibility, _ConversationalBase, ThalovantCommonPlaySkill,
        )

    class ThalovantConversationalCommonPlaySkill(*_ConversationalPlayBases):
        """OCP search/playback with Workshop 8/9 conversation registration."""

else:  # pragma: no cover - a workshop without OCP

    ThalovantCommonPlaySkill = None
    ThalovantConversationalCommonPlaySkill = None


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

    #: Claim only sentences that ask something. A keyword net that claims any
    #: sentence holding one of its words answers room chatter: measured on
    #: 2026-09-12, "C'est bruyant dehors avec les travaux" drew the weather and
    #: "Il fait beau aujourd'hui, on va se promener" a timezone complaint. The
    #: language's own question words decide (thalovant-languages), so a skill
    #: sets this and keeps its vocabulary as it is. Off by default: the last
    #: voice in the house (priority 100) must claim everything.
    QUESTIONS_ONLY: bool = False

    @staticmethod
    def asks(utterance: str, lang: str | None) -> bool:
        """Whether `utterance` asks something in `lang`, by the language's own words."""
        from thalovant_languages import asks

        return asks(utterance, lang)

    def claims(self, utterance: str, lang: str | None) -> bool:
        """Whether the fallback may consider `utterance` at all.

        The `QUESTIONS_ONLY` gate, applied before a subclass's own test: a
        subclass calls this from `can_answer` and `handle_fallback` and keeps
        its keyword test after it.
        """
        return not self.QUESTIONS_ONLY or self.asks(utterance, lang)

    def can_answer(self, message: Any) -> bool:
        """Whether this skill has something to say about `message`.

        Answering unconditionally here makes the number above the whole of the
        skill's politeness: everything behind it stops being asked.
        """
        raise NotImplementedError

    def handle_fallback(self, message: Any) -> bool:
        """Say what `reply` returns. Override only to do something other than speak.

        Returns True when the skill answered, which is what tells ovos-core to
        stop asking the skills behind it.
        """
        text = self.reply(self.utterance(message), self.lang_of(message), self.context_of(message))
        if not text:
            return False
        self.speak(text)
        return True


class ThalovantConversationalFallbackSkill(
    ThalovantFallbackSkill, _ConverseEligibility, _ConversationalBase
):
    """A fallback skill that can also finish what it started.

    A skill that asks a question needs `converse()`, and a skill that answers
    what no intent claimed needs the fallback ladder. Until this existed you
    had to pick one, and picking `ThalovantFallbackSkill` meant `converse()`
    was never called at all: the converse plumbing -- `activate()`,
    `deactivate()` and the `ovos.converse.ping` acknowledgement -- lives on
    ovos-workshop's `ConversationalSkill`, and a skill only answers that ping
    when its `skill_id` is in `session.converse_handlers`. A class without
    the plumbing can never get itself in there, so the method sat there
    looking correct and was dead.

    That is not a hypothetical: the reminder skill asked "What should I
    remind you about?", the answer went back through the pipeline as a fresh
    command, and the fart skill matched "fart".

    Both parents descend from `OVOSSkill`, so the fallback registration and
    the converse event handlers both run -- `_register_system_event_handlers`
    chains through the whole MRO.
    """
