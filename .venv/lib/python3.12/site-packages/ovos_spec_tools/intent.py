"""Plugin-agnostic intent-definition primitives for the OVOS-INTENT-4 keyword model.

This module is a clean, dependency-light ``IntentBuilder`` / ``Intent`` pair —
the plugin-agnostic form of the intent-definition classes ``ovos-workshop``
exposes to skills. It carries **no** ``adapt`` dependency: it is pure data
describing the **structure** of a keyword intent —
which vocabularies are *required*, *optional*, *one_of*, or *excluded* — exactly
as OVOS-INTENT-4 §5 defines the ``ovos.intent.register.keyword`` payload.

The split of responsibility, per OVOS-INTENT-4 §5.1, is:

- the **builder** captures the intent *structure* (vocabulary **names** under
  each role) — that is all a skill expresses when it writes
  ``IntentBuilder("Foo").require("Set").one_of("Up", "Down").build()``;
- a **producer** (the skill loader) later inlines each vocabulary's expanded
  ``samples`` to form the wire :meth:`Intent.to_keyword_payload` descriptors —
  file paths never cross the bus (§5.1).

Because samples are inlined downstream, the descriptors this module emits carry
``name`` only by default. A producer that already has the expanded samples may
supply them through the ``samples`` argument of :meth:`Intent.to_keyword_payload`.

The public API is **source-compatible** with the ``ovos-workshop`` classes it
replaces, so skills and intent engines can re-point their imports here without
code changes:

- ``IntentBuilder(name).require(t, attribute_name=None, optional=False)``,
  ``.optionally(t, attribute_name=None)``, ``.one_of(*args)``,
  ``.exclude(t)``, ``.build()``, ``.name``;
- ``Intent(name, requires, at_least_one, optional, excludes)`` exposing
  ``.name``, ``.requires``, ``.at_least_one``, ``.optional``, ``.excludes``;
- :func:`open_intent_envelope` reconstructing an :class:`Intent` from a Message.
"""
from __future__ import annotations

import logging
import math
import re
from numbers import Real
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ovos_spec_tools.expansion import REGISTERED_TYPES

_log = logging.getLogger(__name__)

__all__ = [
    "Intent",
    "IntentBuilder",
    "MalformedIntent",
    "MalformedTypedSlots",
    "drop_unregistered_typed_slots",
    "open_intent_envelope",
    "validate_typed_slots",
    "voc_match",
]

# RFC 3339 timestamp, as OVOS-INTENT-1 §5.6 fixes for the `date` type: a
# calendar date and time, offset either as `Z` or `+HH:MM` / `-HH:MM`. RFC 3339
# is an ABNF grammar and ABNF string literals are case-insensitive, so the date
# and time separator and the UTC offset are accepted in either case:
# `2026-04-12t00:00:00z` is a conforming timestamp.
_RFC3339_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})\Z")
# `color`'s `hex` field (§5.6): a lowercase `#rrggbb` string.
_HEX_COLOR_RE = re.compile(r"\A#[0-9a-f]{6}\Z")
# `location`'s `kind` field (§5.6): a place is a city, a country or a region.
_LOCATION_KINDS = ("city", "country", "region")
# `language`'s `code` field (§5.6): a BCP-47 language tag in lowercase. This
# checks the tag is well formed (subtags of 1-8 alphanumerics, the primary
# subtag alphabetic, or a private-use `x-` tag), never that a registry lists
# it: a registry check would reject a tag the producer's registry has and this
# consumer's does not.
_BCP47_RE = re.compile(r"\A([a-z]{2,8}|x)(-[a-z0-9]{1,8})*\Z")
# `timezone`'s `tz` field (§5.6): an IANA time zone name. This checks the name
# shape only — `/`-separated components, each starting with a capital letter.
# Every name in the 2026a database matches it (`localtime`, which is a local
# symlink rather than a database name, does not), and it rejects strings that
# cannot be a zone name at all. The full check needs the zone table, and a
# table check belongs to a consumer that resolves the zone: this validator
# rejecting a zone that the producer's tzdata has and this one's does not
# would break the interoperation the value exists for.
_IANA_TZ_RE = re.compile(r"\A[A-Z][A-Za-z0-9_+-]*(?:/[A-Z][A-Za-z0-9._+-]*)*\Z")


class MalformedTypedSlots(ValueError):
    """A ``data.typed_slots`` map that violates OVOS-INTENT-1 §5.6.

    Raised for a type key outside :data:`~ovos_spec_tools.expansion.REGISTERED_TYPES`,
    an entry missing or adding to its three keys (``span``, ``surface``,
    ``value``), a malformed ``span``, or a ``value`` that does not fit the
    normalized form §5.6 fixes for its type.
    """

# A keyword role entry as the legacy adapt/workshop classes stored it:
# ``(entity_type, attribute_name)`` for required/optional, a bare entity type
# for excludes, and a tuple of entity types for each one_of group.
RoleEntry = Tuple[str, str]


class MalformedIntent(ValueError):
    """A keyword intent that violates an OVOS-INTENT-3 §4.2 structural MUST.

    Raised when a built / emitted intent breaks one of the two §4.2
    well-formedness MUSTs:

    - it declares **no** ``required`` and **no** ``one-of`` constraint, so
      nothing must be present for it to match ("an intent with only optional
      and excluded constraints has nothing that must be present and is
      malformed");
    - it lists the **same vocabulary under two different roles** ("a vocabulary
      MUST appear under at most one role within a single intent. Listing the
      same vocabulary under two roles … is contradictory and malformed").

    These are the data-model counterparts of the checks the locale linter
    already performs; raising at build/emit time means an invalid keyword
    intent is rejected before it can be registered on the bus.
    """


class Intent:
    """A built keyword-intent **definition** — name plus the four role lists.

    This mirrors the attribute surface of the legacy ``ovos-workshop`` /
    ``adapt`` ``Intent`` so existing readers keep working:

    - ``name`` (str) — the intent name (skills munge it to
      ``<skill_id>:<name>`` before registration);
    - ``requires`` — ``list[(entity_type, attribute_name)]``; every entry MUST
      occur (OVOS-INTENT-4 §5.2 ``required``);
    - ``at_least_one`` — ``list[tuple[entity_type, ...]]``; each inner tuple is
      a group, one member of which MUST occur (§5.2 ``one_of``);
    - ``optional`` — ``list[(entity_type, attribute_name)]``; captured if
      present (§5.2 ``optional``);
    - ``excludes`` — ``list[entity_type]``; any occurrence suppresses the
      match (§5.2 ``excluded``).

    Unlike the legacy class this carries **no matching logic** — matching is a
    pipeline-plugin concern (OVOS-PIPELINE-1). It is pure data: the structural
    half of a ``ovos.intent.register.keyword`` registration, ready for a
    producer to inline vocabulary samples into (§5.1).
    """

    def __init__(self, name: str = "",
                 requires: Optional[Sequence] = None,
                 at_least_one: Optional[Sequence] = None,
                 optional: Optional[Sequence] = None,
                 excludes: Optional[Sequence] = None):
        """
        Args:
            name: the intent name.
            requires: required entries, each ``(entity_type, attribute_name)``
                or a bare ``entity_type`` (normalized to a pair).
            at_least_one: ``one_of`` groups, each a sequence of entity types.
            optional: optional entries, same shape as ``requires``.
            excludes: excluded entity types, each a bare ``entity_type`` (a
                ``(type, attr)`` pair is accepted and reduced to its type).
        """
        self.name = name
        self.requires: List[RoleEntry] = [self._as_pair(r)
                                          for r in (requires or [])]
        self.at_least_one: List[Tuple[str, ...]] = [tuple(self._as_name(e)
                                                          for e in group)
                                                    for group in
                                                    (at_least_one or [])]
        self.optional: List[RoleEntry] = [self._as_pair(o)
                                         for o in (optional or [])]
        self.excludes: List[str] = [self._as_name(e) for e in (excludes or [])]

    @staticmethod
    def _as_pair(entry) -> RoleEntry:
        """Normalize an entry to ``(entity_type, attribute_name)``.

        Accepts a bare string (attribute defaults to the type) or any 2-tuple.
        """
        if isinstance(entry, str):
            return (entry, entry)
        entity_type, attribute_name = entry[0], entry[1]
        return (entity_type, attribute_name or entity_type)

    @staticmethod
    def _as_name(entry) -> str:
        """Reduce an entry to its bare entity-type name."""
        if isinstance(entry, str):
            return entry
        return entry[0]

    # -- OVOS-INTENT-3 §4.2 well-formedness ----------------------------------

    def validate(self) -> "Intent":
        """Reject an intent that violates an OVOS-INTENT-3 §4.2 structural MUST.

        Enforces the two §4.2 well-formedness rules the spec calls ``MUST``:

        - **(a)** a keyword intent **MUST** declare at least one ``required``
          or ``one-of`` constraint — "an intent with only optional and
          excluded constraints has nothing that must be present and is
          malformed";
        - **(b)** a vocabulary **MUST** appear under at most one role — listing
          the same vocabulary under two roles (e.g. both required and excluded)
          "is contradictory and malformed".

        Returns ``self`` so it can be used inline (``Intent(...).validate()``).

        Raises:
            MalformedIntent: if either §4.2 rule is violated.
        """
        # (a) at least one required or one-of must be present.
        if not self.requires and not self.at_least_one:
            raise MalformedIntent(
                f"keyword intent {self.name!r} declares no required and no "
                "one-of constraint — it has nothing that must be present "
                "(OVOS-INTENT-3 §4.2)")

        # (b) a vocabulary appears under at most one role. Collect every
        # (vocabulary -> roles it appears in) and reject any vocabulary that
        # spans more than one role. one-of vocabularies count once per name
        # regardless of how many groups list them.
        roles: Dict[str, set] = {}
        for name, _ in self.requires:
            roles.setdefault(name, set()).add("required")
        for name, _ in self.optional:
            roles.setdefault(name, set()).add("optional")
        for group in self.at_least_one:
            for name in group:
                roles.setdefault(name, set()).add("one_of")
        for name in self.excludes:
            roles.setdefault(name, set()).add("excluded")
        clashes = {name: sorted(r) for name, r in roles.items() if len(r) > 1}
        if clashes:
            detail = "; ".join(f"{name!r} under {roles}"
                               for name, roles in sorted(clashes.items()))
            raise MalformedIntent(
                f"keyword intent {self.name!r} lists a vocabulary under more "
                f"than one role — {detail} (OVOS-INTENT-3 §4.2)")
        return self

    # -- OVOS-INTENT-4 §5 emission -------------------------------------------

    @staticmethod
    def _descriptor(name: str,
                    samples: Optional[Dict[str, List[str]]]) -> Dict[str, Any]:
        """Build one §5.1 vocabulary descriptor for ``name``.

        ``samples`` is an optional ``vocab_name -> samples`` map a producer may
        supply when it has already expanded the vocabularies. When absent — the
        usual builder-side case — only ``name`` is emitted and the producer is
        expected to inline ``samples`` before the payload crosses the bus
        (§5.1).
        """
        descriptor: Dict[str, Any] = {"name": name}
        if samples and name in samples:
            descriptor["samples"] = list(samples[name])
        return descriptor

    def to_keyword_payload(self, skill_id: Optional[str] = None,
                           lang: Optional[str] = None,
                           samples: Optional[Dict[str, List[str]]] = None
                           ) -> Dict[str, Any]:
        """Emit the OVOS-INTENT-4 §5.2 keyword-registration structure.

        Returns a dict with the four shape-stable role keys ``required``,
        ``optional``, ``one_of``, ``excluded`` (§5.2 mandates all four are
        present, even when empty), each a list of vocabulary descriptors (§5.1).
        ``one_of`` is a list of groups, each a list of descriptors.

        Identity fields (``skill_id``, ``intent_name``, ``lang``; §3.2) are
        included when provided — ``intent_name`` is always set from ``name``.
        Vocabulary ``samples`` are inlined per descriptor only when the
        ``samples`` map carries them; otherwise the producer inlines them
        before emission (§5.1).

        Args:
            skill_id: optional ``skill_id`` identity field (§3.2).
            lang: optional ``lang`` identity field (§3.2).
            samples: optional ``vocab_name -> expanded samples`` map; when a
                name is present its descriptor gains a ``samples`` entry.

        Returns:
            the §5.2 keyword payload structure.

        A malformed intent (OVOS-INTENT-3 §4.2 — no required/one-of
        constraint, or a vocabulary listed under two roles) is **logged as a
        warning** rather than raised, so emitting stays backward-compatible;
        call :meth:`validate` explicitly to reject before emit.
        """
        try:
            self.validate()
        except MalformedIntent as err:
            _log.warning("emitting register payload for malformed intent %r "
                         "(OVOS-INTENT-3 §4.2): %s", self.name, err)
        payload: Dict[str, Any] = {}
        if skill_id is not None:
            payload["skill_id"] = skill_id
        payload["intent_name"] = self.name
        if lang is not None:
            payload["lang"] = lang
        payload["required"] = [self._descriptor(t, samples)
                               for t, _ in self.requires]
        payload["optional"] = [self._descriptor(t, samples)
                               for t, _ in self.optional]
        payload["one_of"] = [[self._descriptor(t, samples) for t in group]
                             for group in self.at_least_one]
        payload["excluded"] = [self._descriptor(t, samples)
                               for t in self.excludes]
        return payload

    def __repr__(self) -> str:
        return (f"Intent(name={self.name!r}, requires={self.requires!r}, "
                f"at_least_one={self.at_least_one!r}, "
                f"optional={self.optional!r}, excludes={self.excludes!r})")

    def __eq__(self, other) -> bool:
        if not isinstance(other, Intent):
            return NotImplemented
        return (self.name == other.name and
                self.requires == other.requires and
                self.at_least_one == other.at_least_one and
                self.optional == other.optional and
                self.excludes == other.excludes)


class IntentBuilder:
    """Fluent builder for a keyword :class:`Intent` — adapt-free.

    Source-compatible with the ``ovos-workshop`` / ``adapt`` ``IntentBuilder``:
    it accumulates vocabulary **names** under the four OVOS-INTENT-4 §5 roles
    and :meth:`build` freezes them into an :class:`Intent`. It captures only the
    intent *structure* (§5.1) — no samples, no matching.

    Example:
        >>> intent = (IntentBuilder("SetBrightness")
        ...           .require("Set")
        ...           .require("Brightness")
        ...           .one_of("Up", "Down")
        ...           .optionally("Politely")
        ...           .exclude("Question")
        ...           .build())
        >>> intent.to_keyword_payload()["required"]
        [{'name': 'Set'}, {'name': 'Brightness'}]
    """

    def __init__(self, intent_name: str):
        """
        Args:
            intent_name: the name of the intent being built.
        """
        self.name = intent_name
        self.requires: List[RoleEntry] = []
        self.at_least_one: List[Tuple[str, ...]] = []
        self.optional: List[RoleEntry] = []
        self.excludes: List[str] = []

    def require(self, entity_type: str, attribute_name: Optional[str] = None,
                optional: bool = False) -> "IntentBuilder":
        """Require (or, with ``optional=True``, optionally capture) a vocabulary.

        Args:
            entity_type: the vocabulary name.
            attribute_name: name of the captured attribute on the match result;
                defaults to ``entity_type``.
            optional: when True, behaves like :meth:`optionally` — kept for
                source-compatibility with the legacy signature.

        Returns:
            self, for chaining.
        """
        if not attribute_name:
            attribute_name = entity_type
        if optional:
            self.optional.append((entity_type, attribute_name))
        else:
            self.requires.append((entity_type, attribute_name))
        return self

    def optionally(self, entity_type: str,
                   attribute_name: Optional[str] = None) -> "IntentBuilder":
        """Optionally capture a vocabulary (OVOS-INTENT-4 §5.2 ``optional``).

        Args:
            entity_type: the vocabulary name.
            attribute_name: captured-attribute name; defaults to ``entity_type``.

        Returns:
            self, for chaining.
        """
        if not attribute_name:
            attribute_name = entity_type
        self.optional.append((entity_type, attribute_name))
        return self

    def one_of(self, *args: str) -> "IntentBuilder":
        """Require at least one of the given vocabularies (§5.2 ``one_of``).

        Each call adds one **group**; at least one member of each group must
        occur. Separate calls express ``one_of(A, B)`` *and* ``one_of(C, D)``.

        Args:
            *args: vocabulary names forming one group.

        Returns:
            self, for chaining.
        """
        self.at_least_one.append(tuple(args))
        return self

    def exclude(self, entity_type: str) -> "IntentBuilder":
        """Forbid a vocabulary (§5.2 ``excluded``): its presence suppresses the
        match.

        Args:
            entity_type: the vocabulary name to exclude.

        Returns:
            self, for chaining.
        """
        self.excludes.append(entity_type)
        return self

    def build(self) -> Intent:
        """Freeze the accumulated roles into an :class:`Intent`.

        A built intent should satisfy the OVOS-INTENT-3 §4.2 well-formedness
        MUSTs (:meth:`Intent.validate`): declare at least one required or
        one-of constraint, and not list a vocabulary under two roles. A
        malformed builder state is **logged as a warning** rather than raised,
        so ``build()`` stays backward-compatible — call :meth:`Intent.validate`
        explicitly (or rely on the locale linter) to enforce §4.2 where you
        want to reject.
        """
        intent = Intent(self.name, self.requires, self.at_least_one,
                        self.optional, self.excludes)
        try:
            intent.validate()
        except MalformedIntent as err:
            _log.warning("built intent %r is malformed per OVOS-INTENT-3 "
                         "§4.2: %s", self.name, err)
        return intent


def open_intent_envelope(message) -> Intent:
    """Reconstruct an :class:`Intent` from a Message payload.

    Mirrors the legacy ``ovos-workshop`` helper: it reads an intent definition
    out of ``message.data``. Both the legacy serialization keys
    (``name`` / ``requires`` / ``at_least_one`` / ``optional`` / ``excludes``,
    as produced by ``Intent.__dict__``) and the OVOS-INTENT-4 §5.2 wire keys
    (``intent_name`` / ``required`` / ``one_of`` / ``optional`` / ``excluded``,
    whose role entries are vocabulary descriptors) are accepted, so the helper
    round-trips a definition serialized by either generation.

    For §5.2 descriptors only the ``name`` is read into the role list — the
    inlined ``samples`` are not part of the structural :class:`Intent`.

    Args:
        message: a Message-like object exposing a ``data`` mapping.

    Returns:
        the reconstructed :class:`Intent`.
    """
    data = getattr(message, "data", None)
    if data is None:
        data = message  # tolerate being handed a raw dict

    name = data.get("name") or data.get("intent_name") or ""

    def _names(role) -> List[str]:
        # Accept §5.2 descriptors ({"name": ...}), bare strings, or legacy
        # (type, attr) pairs — reduce each to its vocabulary name.
        out = []
        for entry in role or []:
            if isinstance(entry, dict):
                out.append(entry.get("name"))
            elif isinstance(entry, str):
                out.append(entry)
            else:  # (entity_type, attribute_name)
                out.append(entry[0])
        return out

    requires = data.get("requires")
    if requires is None:
        requires = _names(data.get("required"))

    optional = data.get("optional")
    # legacy `optional` is already pairs; §5.2 `optional` is descriptors
    if optional and isinstance(optional[0], dict):
        optional = _names(optional)

    excludes = data.get("excludes")
    if excludes is None:
        excludes = _names(data.get("excluded"))

    at_least_one = data.get("at_least_one")
    if at_least_one is None:
        # §5.2 `one_of`: list of groups, each a list of descriptors.
        at_least_one = [_names(group) for group in data.get("one_of") or []]

    return Intent(name, requires, at_least_one, optional, excludes)


def voc_match(utterance: str, voc_name: str, lang: str,
              locale, *,
              exact: bool = False,
              strip_diacritics: bool = True,
              strip_punct: bool = True) -> bool:
    """Load a named ``.voc`` and test whether ``utterance`` matches it.

    This is the plugin-agnostic equivalent of
    ``OVOSAbstractApplication.voc_match`` / the skill ``voc_match`` — the
    helper common-query, OCP, and other pipelines use without depending on
    ``ovos-workshop``. It loads the ``<voc_name>.voc`` for ``lang`` and
    matches with whole-word OVOS-INTENT-2 §4.3 semantics — identical to the
    skill helper (so pipelines behave the same): a sample ``yes`` matches
    ``"yes, please"`` but not ``"yesterday"``.

    Args:
        utterance: the (ASR-normalized) text to test.
        voc_name: the ``.voc`` base name (no extension).
        lang: BCP-47 language tag of the resource to load.
        locale: either a :class:`~ovos_spec_tools.resources.LocaleResources`
            instance, or a ``locale/`` directory path (``str`` / ``Path``), or
            a sequence of such paths searched in override-precedence order
            (user, skill, core — see
            :class:`~ovos_spec_tools.resources.LocaleResources`).
        exact: require equality after normalization rather than whole-word
            substring containment.
        strip_diacritics: forwarded to the matcher.
        strip_punct: forwarded to the matcher.

    Returns:
        ``True`` iff any ``.voc`` sample matches; ``False`` when the resource
        does not exist for the language.
    """
    from ovos_spec_tools.resources import LocaleResources

    if isinstance(locale, LocaleResources):
        resources = locale
    elif isinstance(locale, (str, bytes)) or hasattr(locale, "__fspath__"):
        resources = LocaleResources(str(locale))
    else:  # a sequence of locale dirs, highest precedence first
        dirs = [str(p) for p in locale]
        if not dirs:
            return False
        # Map the precedence-ordered dirs onto the user/skill/core slots, which
        # LocaleResources searches in that same order. A single dir is the
        # skill locale; the spare slots stay empty.
        if len(dirs) == 1:
            resources = LocaleResources(skill_locale=dirs[0])
        else:
            resources = LocaleResources(
                user_locale=dirs[0],
                skill_locale=dirs[1],
                core_locale=dirs[2] if len(dirs) > 2 else None)
    return resources.voc_match(
        utterance, voc_name, lang, exact=exact,
        strip_diacritics=strip_diacritics, strip_punct=strip_punct)


def _validate_typed_slot_value(slot_type: str, value: Any) -> None:
    """Check ``value`` against the §5.6 normalized-value form for ``slot_type``."""
    if slot_type in ("number", "duration"):
        # `math.isfinite` rejects NaN and the infinities: JSON has no such
        # numbers, but Python's own `json` parses `NaN`, `Infinity` and
        # `-Infinity` by default and gives floats, which are `Real`.
        if isinstance(value, bool) or not isinstance(value, Real) or \
                not math.isfinite(value):
            raise MalformedTypedSlots(
                f"{slot_type!r} entry value {value!r} is not a JSON number "
                f"(OVOS-INTENT-1 §5.6)")
    elif slot_type == "date":
        if not isinstance(value, str) or not _RFC3339_RE.match(value):
            raise MalformedTypedSlots(
                f"'date' entry value {value!r} is not an RFC 3339 timestamp "
                f"(OVOS-INTENT-1 §5.6)")
    elif slot_type == "color":
        if not isinstance(value, dict) or set(value) != {"hex", "name"}:
            raise MalformedTypedSlots(
                f"'color' entry value {value!r} must be an object with "
                f"exactly the keys 'hex' and 'name' (OVOS-INTENT-1 §5.6)")
        if not isinstance(value["hex"], str) or not _HEX_COLOR_RE.match(value["hex"]):
            raise MalformedTypedSlots(
                f"'color' entry hex {value['hex']!r} is not a lowercase "
                f"'#rrggbb' string (OVOS-INTENT-1 §5.6)")
        if value["name"] is not None and not isinstance(value["name"], str):
            raise MalformedTypedSlots(
                f"'color' entry name {value['name']!r} must be a string or "
                f"null (OVOS-INTENT-1 §5.6)")
    elif slot_type == "language":
        if not isinstance(value, dict) or set(value) != {"code", "name"}:
            raise MalformedTypedSlots(
                f"'language' entry value {value!r} must be an object with "
                f"exactly the keys 'code' and 'name' (OVOS-INTENT-1 §5.6)")
        if not isinstance(value["code"], str) or \
                not _BCP47_RE.match(value["code"]):
            raise MalformedTypedSlots(
                f"'language' entry code {value['code']!r} must be a "
                f"well-formed BCP-47 tag in lowercase (OVOS-INTENT-1 §5.6)")
        if value["name"] is not None and not isinstance(value["name"], str):
            raise MalformedTypedSlots(
                f"'language' entry name {value['name']!r} must be a string "
                f"or null (OVOS-INTENT-1 §5.6)")
    elif slot_type == "location":
        if not isinstance(value, dict) or set(value) != {"name", "kind"}:
            raise MalformedTypedSlots(
                f"'location' entry value {value!r} must be an object with "
                f"exactly the keys 'name' and 'kind' (OVOS-INTENT-1 §5.6)")
        if not isinstance(value["name"], str) or not value["name"]:
            raise MalformedTypedSlots(
                f"'location' entry name {value['name']!r} must be a "
                f"non-empty string (OVOS-INTENT-1 §5.6)")
        if value["kind"] is not None and value["kind"] not in _LOCATION_KINDS:
            raise MalformedTypedSlots(
                f"'location' entry kind {value['kind']!r} must be one of "
                f"{_LOCATION_KINDS} or null (OVOS-INTENT-1 §5.6)")
    elif slot_type == "timezone":
        if not isinstance(value, dict) or set(value) != {"tz"}:
            raise MalformedTypedSlots(
                f"'timezone' entry value {value!r} must be an object with "
                f"exactly the key 'tz' (OVOS-INTENT-1 §5.6)")
        if not isinstance(value["tz"], str) or not _IANA_TZ_RE.match(value["tz"]):
            raise MalformedTypedSlots(
                f"'timezone' entry tz {value['tz']!r} does not have the shape "
                f"of an IANA zone name (OVOS-INTENT-1 §5.6). The zone table "
                f"itself is not consulted here")


def validate_typed_slots(typed_slots: Dict[str, List[Dict[str, Any]]]) -> None:
    """Validate a ``data.typed_slots`` map against OVOS-INTENT-1 §5.6.

    Every key MUST be a registered type
    (:data:`~ovos_spec_tools.expansion.REGISTERED_TYPES`) — an unregistered key
    is a producer bug, not a hint an orchestrator can act on; drop it with
    :func:`drop_unregistered_typed_slots` before this raises on it. Every entry
    MUST carry exactly the three §5.6 keys ``span``, ``surface``, ``value``:
    ``span`` a two-integer ``[start, end]`` pair with ``start <= end``,
    ``surface`` a string, and ``value`` the normalized form §5.6 fixes for the
    entry's type. A type's list MUST NOT be empty — §5.6: "a transformer that
    computes a type and finds nothing of that kind MUST omit the type rather
    than list it with an empty array, and an orchestrator that receives an
    empty list for a type MUST drop that type before carrying the map onward".
    A map with no types at all stays valid.

    Two ``timezone`` entries MUST NOT share a surface at one span, per §5.6:
    "One surface gives one entry with one zone, also when the surface names
    more than one zone." A surface is one occurrence of text, and §5.6 ties
    it to its span by ``utterance[start:end] == surface``, so the
    ``(span, surface)`` pair is the key. Two entries with the same surface at
    different spans are legal: the same abbreviation at two positions is two
    occurrences. Two entries with different surfaces at the same span are
    legal too: entries are computed over every candidate utterance and share
    one map, so two candidates can read two different zone names at the same
    offsets.

    Args:
        typed_slots: the ``data.typed_slots`` map to validate.

    Raises:
        MalformedTypedSlots: the map violates any of the above.
    """
    for slot_type, entries in typed_slots.items():
        if slot_type not in REGISTERED_TYPES:
            raise MalformedTypedSlots(
                f"typed_slots key {slot_type!r} is not a registered type; "
                f"registered types are {REGISTERED_TYPES} (OVOS-INTENT-1 §5.6)")
        if not entries:
            raise MalformedTypedSlots(
                f"typed_slots key {slot_type!r} has an empty list — no empty "
                f"typed slots allowed, either extraction succeeds or no slot "
                f"(OVOS-INTENT-1 §5.6)")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"span", "surface", "value"}:
                raise MalformedTypedSlots(
                    f"{slot_type!r} entry {entry!r} must be an object with "
                    f"exactly the keys 'span', 'surface', 'value' "
                    f"(OVOS-INTENT-1 §5.6)")
            span = entry["span"]
            if (not isinstance(span, (list, tuple)) or len(span) != 2
                    or not all(isinstance(n, int) and not isinstance(n, bool)
                              for n in span)
                    or span[0] > span[1]):
                raise MalformedTypedSlots(
                    f"{slot_type!r} entry span {span!r} must be a "
                    f"[start, end] pair of integers with start <= end "
                    f"(OVOS-INTENT-1 §5.6)")
            if not isinstance(entry["surface"], str):
                raise MalformedTypedSlots(
                    f"{slot_type!r} entry surface {entry['surface']!r} must "
                    f"be a string (OVOS-INTENT-1 §5.6)")
            _validate_typed_slot_value(slot_type, entry["value"])
        if slot_type == "timezone":
            seen_surfaces = set()
            for entry in entries:
                occurrence = (tuple(entry["span"]), entry["surface"])
                if occurrence in seen_surfaces:
                    raise MalformedTypedSlots(
                        f"'timezone' has more than one entry for surface "
                        f"{entry['surface']!r} at span {entry['span']!r} — "
                        f"one surface gives one entry with one zone "
                        f"(OVOS-INTENT-1 §5.6)")
                seen_surfaces.add(occurrence)


def drop_unregistered_typed_slots(
        typed_slots: Dict[str, List[Dict[str, Any]]]
        ) -> Dict[str, List[Dict[str, Any]]]:
    """Drop every unregistered key, and every type with no entries, from a
    ``data.typed_slots`` map.

    OVOS-INTENT-1 §5.6 registers a closed set of types
    (:data:`~ovos_spec_tools.expansion.REGISTERED_TYPES`); an orchestrator that
    receives a map with an unregistered key drops it rather than passing it on,
    exactly as an unregistered ``{type:name}`` prefix degrades to an untyped
    slot (§3.4, §3.6). Per the §5.6 amendment ("no empty typed slots allowed,
    either extraction succeeds or no slot") a type with an empty list carries
    no information either, so it is dropped alongside unregistered keys.
    Registered entries with at least one entry are returned unchanged.

    Args:
        typed_slots: the ``data.typed_slots`` map to filter.

    Returns:
        A new map containing only the registered-type keys of ``typed_slots``
        that have at least one entry.
    """
    kept = {slot_type: entries for slot_type, entries in typed_slots.items()
            if slot_type in REGISTERED_TYPES and entries}
    dropped = [slot_type for slot_type in typed_slots if slot_type not in kept]
    if dropped:
        _log.warning("dropping typed_slots keys %s (unregistered or with no "
                     "entries; OVOS-INTENT-1 §5.6)", dropped)
    return kept
