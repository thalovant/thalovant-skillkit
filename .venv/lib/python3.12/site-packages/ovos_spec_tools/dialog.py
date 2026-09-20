"""Reference dialog renderer for OVOS-INTENT-2 §4.2.

This is the reference implementation of the **Dialog renderer** conformance
role of OVOS-INTENT-1 §7. Rendering a dialog means: verify all phrases declare
the same slot set (§5.5), select one phrase from a loaded ``.dialog``, expand
its ``(a|b)`` / ``[x]`` variety to a single variant, and fill every ``{name}``
slot with a value. The §7 role MUST "verify that all phrases in a dialog
definition declare the same slot set (§5.5)"; :func:`verify_slot_consistency`
performs that check and both render paths call it before rendering.

Two interfaces are provided:

- :func:`render` — a stateless one-shot function over explicit phrases;
- :class:`DialogRenderer` — a stateful, **multilingual** object backed by a
  :class:`~ovos_spec_tools.resources.LocaleResources`: the language is given
  per :meth:`DialogRenderer.render` call, and the renderer avoids repeating
  the phrase it chose last (independently per language).

A slot may be written in either equivalent spelling — single-brace ``{name}``
or double-brace ``{{name}}`` (OVOS-INTENT-1 §3.4). The two are folded to the
same canonical ``{name}`` slot by :func:`~ovos_spec_tools.expansion.expand`
during expansion, so this renderer fills both transparently. A slot with no
value raises :class:`UnfilledSlot`.
"""
from __future__ import annotations

import random as _random
import re
from typing import Dict, Optional, Protocol, Sequence

from ovos_spec_tools.expansion import MalformedTemplate, expand

__all__ = [
    "render",
    "DialogRenderer",
    "Chooser",
    "UnfilledSlot",
    "verify_slot_consistency",
]

_SLOT_TOKEN_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def verify_slot_consistency(phrases: Sequence[str]) -> None:
    """Verify every phrase of a dialog declares the identical slot set (§5.5).

    OVOS-INTENT-1 §7 makes this a **MUST** for the *Dialog renderer* role: it
    "verify[s] that all phrases in a dialog definition declare the same slot
    set (§5.5)". A definition MUST NOT mix templates that declare different
    slots, so the caller supplies the same values whichever phrase is chosen
    (§5.1, OVOS-INTENT-2 §4.2).

    A phrase *declares* a slot name if that name appears anywhere in it;
    optionality does not change this (§5.5), so ``say [{x}]`` and ``say {x}``
    declare the same slot set ``{x}`` and may coexist.

    Args:
        phrases: the phrase strings of one ``.dialog`` definition.

    Raises:
        MalformedTemplate: two phrases declare different slot sets (§5.5).
    """
    slot_sets = {frozenset(_SLOT_TOKEN_RE.findall(phrase)) for phrase in phrases}
    if len(slot_sets) > 1:
        rendered = sorted(
            "{" + ", ".join(sorted(s)) + "}" for s in slot_sets)
        raise MalformedTemplate(
            "dialog phrases declare different slot sets "
            f"({', '.join(rendered)}): every phrase in one dialog definition "
            "MUST declare the same {slots} (OVOS-INTENT-1 §5.5); a phrasing "
            "that needs different slots belongs in a separate dialog")


class Chooser(Protocol):
    """A source of random selection: anything with a ``choice`` method.

    The :mod:`random` module and a :class:`random.Random` instance both
    satisfy it. Inject a seeded ``random.Random`` for deterministic output.
    """

    def choice(self, seq: Sequence[str]) -> str:
        ...


class UnfilledSlot(ValueError):
    """A chosen dialog phrase has a named slot with no value.

    Per OVOS-INTENT-1 §5.1 the caller must supply a value for every slot in the
    chosen phrase; a phrase with an unfilled slot must not be sent to TTS.
    """


def render(phrases: Sequence[str],
           slots: Optional[Dict[str, object]] = None,
           vocabularies: Optional[Dict[str, Sequence[str]]] = None,
           rng: Optional[Chooser] = None) -> str:
    """Render one phrase from a list of dialog phrases (stateless).

    This is the language-agnostic primitive: the caller has already chosen and
    loaded the phrases. For a multilingual, resource-backed renderer use
    :class:`DialogRenderer`.

    Args:
        phrases: the phrase strings of a ``.dialog``.
        slots: caller-supplied values for the phrase's named slots, keyed by
            slot name. Values are converted to text.
        vocabularies: vocabularies for any ``<name>`` references in the phrase.
        rng: an object with a ``choice`` method, for phrase and variant
            selection; defaults to the :mod:`random` module.

    Returns:
        One rendered phrase, ready for text-to-speech.

    Raises:
        UnfilledSlot: a slot in the chosen phrase has no value.
        ValueError: ``phrases`` is empty.
        MalformedTemplate: the chosen phrase is not a valid template, or the
            phrases declare divergent slot sets (OVOS-INTENT-1 §5.5).
    """
    if not phrases:
        raise ValueError("no dialog phrases to render")
    # §7 Dialog-renderer MUST: all phrases in a dialog declare the same slot
    # set (§5.5). Enforce before choosing, so a divergent definition is
    # rejected regardless of which phrase the chooser would pick.
    verify_slot_consistency(phrases)
    chooser = rng if rng is not None else _random
    phrase = chooser.choice(list(phrases))
    return _render_phrase(phrase, slots or {}, vocabularies, chooser)


class DialogRenderer:
    """A stateful, multilingual renderer for one named ``.dialog``.

    Backed by a :class:`~ovos_spec_tools.resources.LocaleResources`: the dialog
    name is fixed at construction, but the **language is given per**
    :meth:`render` **call**, so one renderer serves every language the dialog
    is shipped in. Each call loads that language's phrases, vocabularies, and
    ``.entity`` value sets afresh.

    Unlike the bare :func:`render`, it **avoids repeating the phrase it chose
    on the previous call** — tracked independently per language — so a
    repeatedly-spoken response does not sound mechanical. Repetition avoidance
    is an implementation choice the spec explicitly allows (§4.2).
    """

    def __init__(self, resources, name: str,
                 rng: Optional[Chooser] = None,
                 slots: Optional[Dict[str, object]] = None):
        """
        Args:
            resources: a :class:`~ovos_spec_tools.resources.LocaleResources`
                (or anything with ``load_dialog``, ``vocabularies`` and
                ``entities`` methods taking a language).
            name: the base name of the ``.dialog`` to render.
            rng: an object with a ``choice`` method; defaults to :mod:`random`.
            slots: **default** slot values, held for the renderer's lifetime
                and reused on every :meth:`render` call. A per-call value
                overrides a default.
        """
        self.resources = resources
        self.name = name
        self.rng = rng if rng is not None else _random
        self.default_slots: Dict[str, object] = dict(slots or {})
        self._last: Dict[str, str] = {}  # last phrase chosen, per language

    def render(self, lang: str,
               slots: Optional[Dict[str, object]] = None) -> str:
        """Render one phrase of the dialog in ``lang``.

        A slot is filled, in order of precedence, from: the per-call ``slots``;
        then the renderer's default slots; then a random value from the slot's
        ``.entity`` set for ``lang``. A slot none of these supply raises
        :class:`UnfilledSlot`.

        The phrase chosen on the previous call **for the same language** is
        avoided when the dialog has more than one phrase.

        Args:
            lang: the BCP-47 language tag to render in.
            slots: per-call slot values; each overrides a default.

        Returns:
            One rendered phrase, ready for text-to-speech.

        Raises:
            UnfilledSlot: a slot in the chosen phrase has no value.
            FileNotFoundError: the dialog does not exist for ``lang``.
            MalformedTemplate: the chosen phrase is not a valid template, or
                the dialog's phrases declare divergent slot sets
                (OVOS-INTENT-1 §5.5).
        """
        phrases = self.resources.load_dialog(self.name, lang)
        # §7 Dialog-renderer MUST verify all phrases declare the same slot set
        # (§5.5) before rendering.
        verify_slot_consistency(phrases)
        effective = dict(self.default_slots)
        if slots:
            effective.update(slots)

        last = self._last.get(lang)
        choices = [p for p in phrases if p != last] or phrases
        phrase = self.rng.choice(choices)
        self._last[lang] = phrase

        return _render_phrase(phrase, effective,
                              self.resources.vocabularies(lang), self.rng,
                              self.resources.entities(lang))


def _render_phrase(phrase: str,
                   slots: Dict[str, object],
                   vocabularies: Optional[Dict[str, Sequence[str]]],
                   chooser: Chooser,
                   entities: Optional[Dict[str, Sequence[str]]] = None) -> str:
    """Expand one phrase to a variant, then fill its slots.

    Expansion keeps slots opaque (OVOS-INTENT-1 §4), so it runs first and a
    slot value can never be parsed as grammar.
    """
    variant = chooser.choice(expand(phrase, vocabularies))
    return _fill_slots(variant, slots, entities, chooser)


def _fill_slots(variant: str,
                slots: Dict[str, object],
                entities: Optional[Dict[str, Sequence[str]]],
                chooser: Chooser) -> str:
    """Replace every ``{name}`` in ``variant`` with a value.

    A value is taken from ``slots``; failing that, a random valid value from
    the slot's ``.entity`` set in ``entities``; failing that, the slot has no
    value and :class:`UnfilledSlot` is raised.
    """

    def replace(match: "re.Match") -> str:
        name = match.group(1)
        if name in slots:
            return str(slots[name])
        if entities and entities.get(name):
            return str(chooser.choice(list(entities[name])))
        raise UnfilledSlot(
            f"dialog slot {{{name}}} has no value: it was not filled by the "
            f"caller and has no .entity fallback")

    return _SLOT_TOKEN_RE.sub(replace, variant)
