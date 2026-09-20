"""Reference implementation of OVOS-SESSION-1 — the session carrier.

This module defines the **wire shape** of the JSON object that travels
inside ``Message.context.session``, and the rules consumers follow when
reading and propagating it. It is the canonical reference implementation
of the field set OVOS-SESSION-1 §3 claims, carrying every registered
field with spec-correct serialize / deserialize and the recency / cap /
prune helpers the field owners (OVOS-PIPELINE-1 §7.1, OVOS-CONVERSE-1
§2.1 / §2.2) describe.

Scope per OVOS-SESSION-1 §1:

- the JSON shape (§2), including the *omissible-but-never-nullable*
  rule (§2 / §2.1);
- the closed set of fields claimed in this version (§3), each carried
  as a first-class attribute;
- the reserved ``"default"`` ``session_id`` value (§3.1);
- propagation across the OVOS-MSG-1 §5 derivations (§4) — modelled
  here as round-trip equality;
- serialization per OVOS-MSG-1 §6 (§5).

Design constraints — this is **pure data + stdlib only**. It does not
import ``ovos-bus-client``, ``ovos-config``, the bus, or any heavy
``ovos-utils`` machinery. Deployment defaults (the pipeline ordering,
the converse-handler cap, the configured language) are **injected** by
the caller, never read from a config singleton here. The lifecycle
surface that bus-client layers on top — ``SessionManager``,
``dig_for_message``, the ``active_skills`` / ``utterance_states``
back-compat projections — lives in bus-client's subclass, not here.

Out of scope (§1 non-goals): session lifecycle, a session store,
authentication / authorization, encryption, and the *semantics* of any
field whose owner is not OVOS-SESSION-1 — those are owned by the citing
specification. This module fixes only the wire contract, the §3.1 /
§3.2 / §3.3 fields whose meaning OVOS-SESSION-1 itself owns, and the
mechanical recency / cap / prune behaviour the owners describe for the
handler-list fields.

``SessionManager`` here holds exactly one session — the reserved
``"default"`` id, which OVOS-SESSION-2 §2.3 / §5 makes the orchestrator's
own. A named session never enters the registry: §2.2 keeps the orchestrator
stateless for it, its whole state arrives on every Message, and the working
session for an in-flight utterance belongs to the utterance flow that has an
end to discard it at.

**Clearing a field is not expressible on the carrier.** The §2.1
omissible-but-never-nullable rule means an omitted field, an explicit
``null``, an empty list (§3.4) and an empty object all serialize
identically — as absence. On the pathways that read absence as "no
opinion", chiefly the OVOS-SESSION-2 §5.1 default-session store write,
a component therefore cannot clear a stored field by clearing it
locally and re-serializing: the store keeps its last value. The same
holds one level down for ``intent_context``, where OVOS-CONTEXT-1 §5.3
gives removal a wire form — an explicit ``null`` entry — that
:meth:`Session.to_dict` has no way to emit. A component that shares a
process with the store clears through the live object and is
unaffected; one that is out of process must send the ``null`` entry
itself, which means composing the payload rather than re-serializing a
Session.
"""
from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from threading import RLock
from typing import Any, Dict, List, Optional, Union

from ovos_spec_tools.message import DEFAULT_SESSION_ID, _freeze

__all__ = [
    "Session",
    "carried_fields",
    "resolve_session_id",
    "merge_carrier",
    "SessionManager",
    "MalformedSession",
    "DEFAULT_SESSION_ID",
    "DEFAULT_CONVERSE_HANDLERS_CAP",
    "SESSION1_OWNED_FIELDS",
    "SESSION1_REGISTERED_FIELDS",
    "parse_session_payload",
]


_log = logging.getLogger(__name__)


#: OVOS-CONVERSE-1 §2.1 default cap for the converse-handler recency
#: stack. A deployment MAY raise, lower, or set it to "unbounded"
#: (a value ``<= 0``). The cap is **not** session state: it is a
#: deployment value the orchestrator applies at insertion time, passed
#: as the ``cap`` argument to :meth:`Session.add_converse_handler`. This
#: constant is the spec's documented §2.1 default for that argument.
DEFAULT_CONVERSE_HANDLERS_CAP = 64


#: The field names whose semantics OVOS-SESSION-1 itself owns
#: (§3.1 ``session_id`` + §3.2 language signals + §3.3 ``site_id`` +
#: §3.5 ``location``).
SESSION1_OWNED_FIELDS = frozenset({
    "session_id", "site_id", "lang",
    "secondary_langs", "output_lang",
    "stt_lang", "request_lang", "detected_lang",
    "location",
})


#: The six OVOS-TRANSFORM-1 §5 transformer-chain fields, each an ordered
#: array of plugin ids.
_TRANSFORMER_FIELDS = (
    "audio_transformers", "utterance_transformers",
    "metadata_transformers", "intent_transformers",
    "dialog_transformers", "tts_transformers",
)

#: The list-valued denylist / override fields claimed by other specs
#: (OVOS-PIPELINE-1 §5, OVOS-TRANSFORM-1 §5.2, OVOS-FALLBACK-1 §4). All are
#: arrays of string for which an empty array is wire-equivalent to omission
#: (§3.4). ``fallback_handlers`` is registered here per the SESSION-1 §3
#: field table (owner OVOS-FALLBACK-1 §4); see the constructor docstring.
_LIST_OVERRIDE_FIELDS = (
    "pipeline",
    "blacklisted_skills", "blacklisted_intents", "blacklisted_pipelines",
    "blacklisted_audio_transformers", "blacklisted_utterance_transformers",
    "blacklisted_metadata_transformers", "blacklisted_intent_transformers",
    "blacklisted_dialog_transformers", "blacklisted_tts_transformers",
    "fallback_handlers",
) + _TRANSFORMER_FIELDS

#: The object-valued override field (OVOS-CONTEXT-1 §2 ``intent_context``).
_OBJECT_OVERRIDE_FIELDS = ("intent_context",)

#: The handler-list / response-mode fields whose recency / cap / prune
#: behaviour this module reproduces (OVOS-PIPELINE-1 §7.1,
#: OVOS-CONVERSE-1 §2.1 / §2.2).
_HANDLER_FIELDS = ("active_handlers", "converse_handlers", "response_mode")

#: String fields claimed by other specs. ``persona_id`` is registered by
#: OVOS-PERSONA-1 and recognized here per the OVOS-SESSION-1 §2.2 field
#: registry; OVOS-SESSION-1 carries it opaquely (its semantics are owned
#: by OVOS-PERSONA-1). An empty / unset value is wire-equivalent to
#: omission (§2.1).
_STRING_OVERRIDE_FIELDS = ("persona_id",)


#: The full closed set of fields OVOS-SESSION-1 §3 recognizes in this
#: version. A consumer that recognizes any of these interprets it per
#: its owner specification; everything else is an unknown field. Per
#: §2.4 a consumer MUST NOT reject an unknown key: :meth:`Session.from_dict`
#: silently drops it from the in-process object (this module carries no
#: catch-all attribute for it), while §4 propagation is satisfied at the
#: Message level — ``Message.forward`` / ``Message.reply`` deep-copy the
#: raw wire ``context`` (including any unknown session keys) rather than
#: reconstructing it from a ``Session`` object, so an unknown key rides
#: through untouched on the wire even though this class does not model it.
SESSION1_REGISTERED_FIELDS = frozenset(SESSION1_OWNED_FIELDS).union(
    _LIST_OVERRIDE_FIELDS, _OBJECT_OVERRIDE_FIELDS, _HANDLER_FIELDS,
    _STRING_OVERRIDE_FIELDS)


class MalformedSession(ValueError):
    """A serialized session payload violates OVOS-SESSION-1 §2 / §5.

    Raised only for structural failures that the spec calls a hard
    error: the carrier is not a JSON object, or the JSON is unparsable.
    Per §2 an explicit ``null`` on a field is **not** a Message-level
    rejection — it is logged and treated as omitted; see
    :meth:`Session.from_dict`.
    """


def _wire_type(value: Any) -> str:
    """The JSON wire-type name of ``value``, for a §2 malformed-field warning.

    OVOS-SESSION-1 §2 asks the log to name "the wire type received", and §3
    fixes each field in JSON's vocabulary, so a JSON object is reported as
    ``object`` and not as Python's ``dict``. ``bool`` is tested before ``int``,
    because ``isinstance(True, int)`` holds.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_bcp47(value: Any) -> bool:
    """Cheap shape check: a BCP-47 tag is a non-empty string with no
    whitespace. The full grammar is owned by language tools; this
    module rejects only obvious type errors."""
    return isinstance(value, str) and bool(value) and not any(
        c.isspace() for c in value)


def _sanitize_location(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate the OVOS-SESSION-1 §3.5 ``location`` keys.

    ``location`` carries only ``lat``/``lon``/``tz`` (§3.5: "``location``
    carries only these three keys"). Per §2 a malformed key is dropped as
    if omitted rather than rejecting the whole object: a wrong-typed or
    out-of-range ``lat``/``lon``, or a non-string/empty ``tz``, is simply
    left out. An unlisted key is tolerated (§2.4) but not re-emitted, since
    this field defines no wire representation for it. A value that is not
    a non-empty object, or one whose three keys are all malformed/absent,
    normalizes to ``None`` — object-with-none-of-the-three is wire-equivalent
    to omission.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out: Dict[str, Any] = {}
    lat = raw.get("lat")
    if isinstance(lat, (int, float)) and not isinstance(lat, bool) and -90 <= lat <= 90:
        out["lat"] = float(lat)
    lon = raw.get("lon")
    if isinstance(lon, (int, float)) and not isinstance(lon, bool) and -180 <= lon <= 180:
        out["lon"] = float(lon)
    tz = raw.get("tz")
    if isinstance(tz, str) and tz:
        out["tz"] = tz
    return out or None


def parse_session_payload(
        payload: Union[str, bytes, bytearray, Dict[str, Any]]
) -> Dict[str, Any]:
    """Normalise a §5 session carrier to the dict it encodes.

    Raises :class:`MalformedSession` for the structural failures §5 calls
    hard errors: JSON that does not parse, and a root that is not an object.
    Field-level malformedness is left to the caller
    (:meth:`Session.from_dict` absorbs it per §2.1).
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MalformedSession(
                f"session payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MalformedSession(
            "session must be a JSON object (§2 / §5)")
    return payload


def carried_fields(carrier: Dict[str, Any]) -> Dict[str, Any]:
    """Return the fields a raw session carrier actually carries.

    A field counts as carried when it is registered by OVOS-SESSION-1 §3,
    is present in the carrier, and survives that spec's read-side rules.
    Everything else counts as *not carried*, which under the
    OVOS-SESSION-2 §5.1 merge means "leave the stored value alone":

    - an explicit ``null`` is malformed and reads as omitted (§2.1);
    - a value that fails its field's validation is malformed and reads as
      omitted too — §2.1 resolves malformedness field by field, and on the
      store side "as if omitted" means the stored value stands;
    - a value that normalizes to absence — an empty array on a list-valued
      override (§3.4), a handler list with no usable entry, a
      ``response_mode`` with no holder — is wire-equivalent to omission.

    Validation runs against :class:`Session` itself rather than any
    subclass: the rules being applied are OVOS-SESSION-1's, and a subclass
    that adds fields of its own has no say over whether a §3 field arrived.

    A key OVOS-SESSION-1 §3 does not register is carried verbatim. §2.4
    forbids a consumer from stripping one, and a downstream Session
    subclass may well model it; this module has no basis to judge its
    value, so presence is all it reads.

    ``intent_context`` is returned verbatim, ``null`` entries included:
    OVOS-CONTEXT-1 §5.3 gives a ``null`` entry the meaning *remove this
    key*, so it is content, not malformedness. The merge resolves it.
    """
    out: Dict[str, Any] = {}
    for name, value in carrier.items():
        if value is None:
            _log.warning(
                "OVOS-SESSION-1 §2.1: explicit null on `%s` is malformed; "
                "treating as not carried", name)
            continue
        if name not in SESSION1_REGISTERED_FIELDS:
            out[name] = value
            continue
        if name == "session_id":
            # :func:`resolve_session_id` is the one place that diagnoses
            # this field — it already logs a §2 WARN for a present,
            # non-null, wrong-typed value — so this probe carries a
            # well-formed string through without repeating that warning.
            if isinstance(value, str) and value:
                out[name] = value
            continue
        if name == "intent_context":
            if isinstance(value, dict) and value:
                out[name] = value
            continue
        try:
            normalized = Session(**{name: value}).to_dict().get(name)
        except (ValueError, TypeError):
            # Name the wire type here too: this is the line the deployed
            # consumer reaches (SessionManager.get resolves a carrier through
            # this function), so §2's "naming the field and the wire type
            # received" is met on the path a bus takes.
            _log.warning(
                "OVOS-SESSION-1 §2.1: malformed `%s` (got %s); treating as not "
                "carried", name, _wire_type(value))
            continue
        if normalized is not None:
            out[name] = normalized
    return out


def resolve_session_id(carrier: Dict[str, Any]) -> str:
    """The effective ``session_id`` a raw carrier names (SESSION-1 §2 / §3.1 / §6).

    §6 requires a non-empty string when ``session_id`` is set; a value that
    cannot serve as an identity — absent, ``None``, ``""``, or any
    non-string — is malformed and reads as omitted (§2.1), which resolves
    to the reserved ``"default"`` id (§3.1). A well-formed string, the
    literal ``"default"`` included, is returned as-is.

    A *present*, non-``null`` value that is not a string is a client bug —
    the wire sent a wrong type for the field — and SESSION-1 §2 asks a
    consumer to log that at WARN, naming the field and the type received,
    so the fallback to ``"default"`` does not hide it. Absence and an
    explicit ``null``/``""`` are the spec's own omission cases, not a wrong
    type, and stay silent.
    """
    session_id = carrier.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    if session_id is not None and not isinstance(session_id, str):
        _log.warning(
            "OVOS-SESSION-1 §2: wrong type for `session_id` (got %s); "
            "falling back to %r", _wire_type(session_id),
            DEFAULT_SESSION_ID)
    return DEFAULT_SESSION_ID


def merge_carrier(stored: "Session", carrier: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a raw session carrier onto a stored session, per OVOS-SESSION-2 §5.1.

    Returns the merged wire dict. A field the carrier carries replaces the
    stored value; a field it omits leaves the stored value unchanged. That
    asymmetry is §5.1's deliberate deviation from OVOS-SESSION-1 §2.1 and
    belongs to the default-session store alone: there the orchestrator, not
    a client, is the authoritative holder, so it fills an omission from its
    own last value instead of from deployment defaults. Named sessions never
    reach here — §2.2 keeps the orchestrator stateless for them and each of
    their messages carries a whole snapshot.

    Presence is read off the **carrier dict**, never off a deserialized
    object. A Session cannot tell an omitted field from a field sent at its
    constructor default, so any presence rule derived from an object is a
    guess; the carrier states it outright.

    ``intent_context`` merges entry by entry per OVOS-CONTEXT-1 §5.3: an
    entry sets or replaces its key, a ``null`` entry removes it, an absent
    key is left alone. Disjoint writers therefore do not overwrite each
    other.

    ``session_id`` is fixed to the stored identity: the store is keyed on
    it (§3.1) and a merge is a write into that key, never a rename.

    The stored side is read through ``serialize`` so that a subclass which
    models fields beyond §3 (ovos-bus-client's ``Session`` and its legacy
    projections) merges those fields too instead of losing them.
    """
    data = stored.serialize()
    merged = (json.loads(data) if isinstance(data, (str, bytes, bytearray))
              else dict(data))
    carried = carried_fields(carrier)

    entries = dict(merged.get("intent_context") or {})
    for key, entry in carried.pop("intent_context", {}).items():
        if entry is None:
            entries.pop(key, None)
        else:
            entries[key] = entry
    merged.update(carried)
    if entries:
        merged["intent_context"] = entries
    else:
        merged.pop("intent_context", None)

    # A merge pairs stored fields with carried ones, which can produce a
    # combination the constructor forbids even though each side was legal on
    # its own. OVOS-SESSION-1 §3.2.2 is the one cross-field rule in this
    # version: `secondary_langs` is the complement of `lang` and must not
    # contain it. The merged pair has to satisfy that, and the way to get
    # there is to drop the colliding entry from the complement — `lang` is
    # the primary signal and stands whichever side it came from. Every other
    # constructor check is single-field and was already validated on the side
    # it came from.
    if merged.get("lang") and merged.get("secondary_langs"):
        merged["secondary_langs"] = [tag for tag in merged["secondary_langs"]
                                     if tag != merged["lang"]]
        if not merged["secondary_langs"]:
            merged.pop("secondary_langs")

    merged["session_id"] = stored.resolved_session_id()
    return merged


class Session:
    """OVOS-SESSION-1 carrier — the canonical reference implementation.

    Every field is **optional** on the wire (§2). The constructor and
    :meth:`to_dict` honour the omissible-but-never-nullable rule: a
    field whose value is ``None`` / empty is **absent** from the
    serialized object, never emitted as ``null`` (§2.1, §3.4). Unknown
    fields are not rejected (§2.4) but are not modelled by this class
    either — see :data:`SESSION1_REGISTERED_FIELDS` for how §4
    propagation still holds without a catch-all attribute.

    The Python-level default for ``session_id`` is ``None`` (omitted on
    the wire). :meth:`resolved_session_id` returns the value a consumer
    would fill in — ``"default"`` when omitted (§3.1, §2.1).

    :param session_id: §3.1 — opaque identity string. ``None`` ⇒ omitted
        ⇒ resolves to ``"default"`` at consumption.
    :param lang: §3.2.1 — user's preferred language (BCP-47).
    :param secondary_langs: §3.2.2 — additional BCP-47 tags, ordered.
        Empty list and ``None`` are equivalent on the wire (both omitted).
    :param output_lang: §3.2.3 — preferred response language (BCP-47).
    :param stt_lang: §3.2.4 — language STT actually transcribed in.
    :param request_lang: §3.2.5 — language the emitter reported (hint).
    :param detected_lang: §3.2.6 — language a detector classified.
    :param site_id: §3.3 — opaque group / location identifier.
    :param location: §3.5 — an object carrying zero or more of ``lat``
        (number, [-90, 90]), ``lon`` (number, [-180, 180]) and ``tz`` (a
        non-empty IANA zone string). All three are optional; a key that
        fails its own check is dropped as if omitted, an unlisted key is
        tolerated but not re-emitted, and a value with none of the three
        set is wire-equivalent to omission. This field is a resolution-class
        preference (OVOS-SESSION-2 §2.5) that the client owns; per §4.1 a
        consumer MUST NOT materialize the deployment-configured location
        default into it.
    :param pipeline: OVOS-PIPELINE-1 §5 — ordered pipeline-plugin ids.
    :param intent_context: OVOS-CONTEXT-1 §2 — the declarative intent
        context object (opaque to this module).
    :param blacklisted_skills: OVOS-PIPELINE-1 §5 — skill ids to ignore.
    :param blacklisted_intents: OVOS-PIPELINE-1 §5 — intent ids to ignore.
    :param blacklisted_pipelines: OVOS-PIPELINE-1 §5 — pipeline ids to skip.
    :param audio_transformers ... tts_transformers: OVOS-TRANSFORM-1 §5 —
        the six ordered transformer chains.
    :param blacklisted_*_transformers: OVOS-TRANSFORM-1 §5.2 — per-chain
        denylists.
    :param fallback_handlers: OVOS-FALLBACK-1 §4 — an ordered array of
        skill-id strings registered as a session field by the SESSION-1 §3
        field table (owner OVOS-FALLBACK-1 §4). Carried opaquely here; its
        semantics are owned by OVOS-FALLBACK-1. Empty list and ``None`` are
        wire-equivalent (both omitted, §3.4 / §2.1). Like
        ``converse_handlers``, OVOS-FALLBACK-1 is a **forward reference**
        (it cites this field but is not yet merged); the field is carried
        regardless, on the strength of the SESSION-1 §3 registration.
    :param active_handlers: OVOS-PIPELINE-1 §7.1 dispatch-recency record —
        a head-first, deduplicated list of ``{skill_id, activated_at}``.
    :param converse_handlers: OVOS-CONVERSE-1 §2.1 converse-eligibility
        list — head-first, deduplicated, tail-dropped at the
        orchestrator-supplied cap. The cap itself is **not** a session
        field (not serialized, not in :data:`SESSION1_REGISTERED_FIELDS`);
        it is a deployment value the orchestrator applies at insertion
        time via the ``cap`` argument to :meth:`add_converse_handler`.
    :param response_mode: OVOS-CONVERSE-1 §2.2 pending-response window —
        a single ``{skill_id, expires_at}`` object, or ``None``.
    :param persona_id: OVOS-PERSONA-1 — opaque identifier of the persona
        bound to this session. Registered as a session field by
        OVOS-PERSONA-1 (recognized here per the OVOS-SESSION-1 §2.2 field
        registry); ``None`` ⇒ omitted on the wire (§2.1).
    """

    def __init__(self,
                 session_id: Optional[str] = None,
                 lang: Optional[str] = None,
                 secondary_langs: Optional[List[str]] = None,
                 output_lang: Optional[str] = None,
                 stt_lang: Optional[str] = None,
                 request_lang: Optional[str] = None,
                 detected_lang: Optional[str] = None,
                 site_id: Optional[str] = None,
                 location: Optional[Dict[str, Any]] = None,
                 pipeline: Optional[List[str]] = None,
                 intent_context: Optional[Dict[str, Any]] = None,
                 blacklisted_skills: Optional[List[str]] = None,
                 blacklisted_intents: Optional[List[str]] = None,
                 blacklisted_pipelines: Optional[List[str]] = None,
                 audio_transformers: Optional[List[str]] = None,
                 utterance_transformers: Optional[List[str]] = None,
                 metadata_transformers: Optional[List[str]] = None,
                 intent_transformers: Optional[List[str]] = None,
                 dialog_transformers: Optional[List[str]] = None,
                 tts_transformers: Optional[List[str]] = None,
                 blacklisted_audio_transformers: Optional[List[str]] = None,
                 blacklisted_utterance_transformers: Optional[List[str]] = None,
                 blacklisted_metadata_transformers: Optional[List[str]] = None,
                 blacklisted_intent_transformers: Optional[List[str]] = None,
                 blacklisted_dialog_transformers: Optional[List[str]] = None,
                 blacklisted_tts_transformers: Optional[List[str]] = None,
                 fallback_handlers: Optional[List[str]] = None,
                 active_handlers: Optional[List[Dict[str, Any]]] = None,
                 converse_handlers: Optional[List[Dict[str, Any]]] = None,
                 response_mode: Optional[Dict[str, Any]] = None,
                 persona_id: Optional[str] = None):
        if session_id is not None and (not isinstance(session_id, str)
                                       or not session_id):
            # §6 producer: non-empty string when set.
            raise MalformedSession(
                "session_id must be a non-empty string when set (§6)")
        if site_id is not None and (not isinstance(site_id, str)
                                    or not site_id):
            raise MalformedSession(
                "site_id must be a non-empty string when set (§3.3)")
        if persona_id is not None and (not isinstance(persona_id, str)
                                       or not persona_id):
            # OVOS-PERSONA-1 registered field: non-empty string when set.
            raise MalformedSession(
                "persona_id must be a non-empty string when set "
                "(OVOS-PERSONA-1)")
        for name, value in (("lang", lang), ("output_lang", output_lang),
                            ("stt_lang", stt_lang),
                            ("request_lang", request_lang),
                            ("detected_lang", detected_lang)):
            if value is not None and not _is_bcp47(value):
                raise MalformedSession(
                    f"{name} must be a non-empty BCP-47 string (§3.2)")
        if secondary_langs is not None:
            if not isinstance(secondary_langs, list):
                raise MalformedSession(
                    "secondary_langs must be an array (§3.2.2)")
            seen = set()
            for tag in secondary_langs:
                if not _is_bcp47(tag):
                    raise MalformedSession(
                        "secondary_langs entries must be BCP-47 strings "
                        "(§3.2.2)")
                if tag in seen:
                    raise MalformedSession(
                        "secondary_langs MUST NOT contain duplicates "
                        "(§3.2.2)")
                seen.add(tag)
            # §3.2.2: MUST NOT contain `lang`.
            if lang is not None and lang in seen:
                raise MalformedSession(
                    "secondary_langs MUST NOT contain `lang` (§3.2.2)")
        # --- §3.1 / §3.2 / §3.3 owned scalars and lists ---------------------
        self.session_id = session_id
        self.lang = lang
        self.secondary_langs = list(secondary_langs) if secondary_langs else None
        self.output_lang = output_lang
        self.stt_lang = stt_lang
        self.request_lang = request_lang
        self.detected_lang = detected_lang
        self.site_id = site_id
        # §3.5: key-wise validated, malformed keys dropped, never a hard
        # error — see :func:`_sanitize_location`.
        self.location = _sanitize_location(location)

        # --- other-spec list/object override fields (carried opaquely) ------
        self.pipeline = self._as_str_list(pipeline)
        if intent_context is not None and not isinstance(intent_context, dict):
            raise MalformedSession(
                "intent_context must be an object (OVOS-CONTEXT-1 §2)")
        self.intent_context = dict(intent_context) if intent_context else None
        # OVOS-PERSONA-1 registered scalar (carried opaquely)
        self.persona_id = persona_id
        self.blacklisted_skills = self._as_str_list(blacklisted_skills)
        self.blacklisted_intents = self._as_str_list(blacklisted_intents)
        self.blacklisted_pipelines = self._as_str_list(blacklisted_pipelines)
        self.audio_transformers = self._as_str_list(audio_transformers)
        self.utterance_transformers = self._as_str_list(utterance_transformers)
        self.metadata_transformers = self._as_str_list(metadata_transformers)
        self.intent_transformers = self._as_str_list(intent_transformers)
        self.dialog_transformers = self._as_str_list(dialog_transformers)
        self.tts_transformers = self._as_str_list(tts_transformers)
        self.blacklisted_audio_transformers = self._as_str_list(
            blacklisted_audio_transformers)
        self.blacklisted_utterance_transformers = self._as_str_list(
            blacklisted_utterance_transformers)
        self.blacklisted_metadata_transformers = self._as_str_list(
            blacklisted_metadata_transformers)
        self.blacklisted_intent_transformers = self._as_str_list(
            blacklisted_intent_transformers)
        self.blacklisted_dialog_transformers = self._as_str_list(
            blacklisted_dialog_transformers)
        self.blacklisted_tts_transformers = self._as_str_list(
            blacklisted_tts_transformers)
        # OVOS-FALLBACK-1 §4 registered array-of-string (carried opaquely)
        self.fallback_handlers = self._as_str_list(fallback_handlers)

        # --- PIPELINE-1 §7.1 / CONVERSE-1 §2.1 / §2.2 handler state ---------
        # The §2.1 converse-handler cap is NOT session state: a constructed
        # or deserialized session is never capped on load. The cap is a
        # deployment value the orchestrator supplies at insertion time
        # (see :meth:`add_converse_handler`).
        self.active_handlers: List[Dict[str, Any]] = self._coerce_handlers(
            active_handlers)
        self.converse_handlers: List[Dict[str, Any]] = self._coerce_handlers(
            converse_handlers)
        self.response_mode: Optional[Dict[str, Any]] = self._coerce_response_mode(
            response_mode)

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _as_str_list(value: Optional[List[str]]) -> Optional[List[str]]:
        """Normalize a list-valued override into a copied list, or
        ``None`` when empty / unset. An empty array is wire-equivalent
        to omission (§3.4), so both collapse to ``None``."""
        if value is None or value == []:
            return None
        if not isinstance(value, list) or not all(
                isinstance(entry, str) and entry for entry in value):
            # §2.5: a wrong-typed value has no reading. Raising here is what
            # lets the read side treat it as omitted field-by-field; silently
            # coercing it (a string iterates into its characters) would put
            # nonsense into a stored list that nothing later can distinguish
            # from an intentional one.
            raise MalformedSession(
                "expected an array of non-empty string (§3)")
        return list(value)

    # --- §3.1 reserved-default resolution -----------------------------------

    @property
    def is_default(self) -> bool:
        """``True`` when this session resolves to the reserved
        ``"default"`` identity (§3.1): an omitted, empty, or explicit
        ``"default"`` ``session_id`` all map here."""
        return self.session_id in (None, DEFAULT_SESSION_ID)

    def resolved_session_id(self) -> str:
        """The ``session_id`` a consumer would key per-session state on
        — ``"default"`` when omitted (§3.1 + §2.1)."""
        return self.session_id or DEFAULT_SESSION_ID

    # ------------------------------------------------------------------
    # OVOS-PIPELINE-1 §7.1 / OVOS-CONVERSE-1 §2.1 / §2.2 handler helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_handlers(
            handlers: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Normalize a handler list into the spec ``{skill_id,
        activated_at}`` object shape (PIPELINE-1 §7.1 / CONVERSE-1 §2.1).

        Accepts either the spec object shape (list of dicts) or the
        legacy ``[skill_id, activated_at]`` pair shape (tolerated on
        deserialization). Entries are deduplicated by ``skill_id``
        (head wins) and kept head-first by recency."""
        out: List[Dict[str, Any]] = []
        seen = set()
        for entry in handlers or []:
            if isinstance(entry, dict):
                skill_id = entry.get("skill_id")
                activated_at = entry.get("activated_at", time.time())
            elif isinstance(entry, (list, tuple)) and entry:
                skill_id = entry[0]
                activated_at = entry[1] if len(entry) > 1 else time.time()
            else:
                continue
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            out.append({"skill_id": skill_id, "activated_at": activated_at})
        return out

    @staticmethod
    def _coerce_response_mode(
            response_mode: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Normalize a ``response_mode`` value into the spec
        ``{skill_id, expires_at}`` shape, or ``None`` when there is no
        holder. Malformed values resolve to ``None`` (SESSION-1 §2.1,
        CONVERSE-1 §2.2)."""
        if not isinstance(response_mode, dict):
            return None
        skill_id = response_mode.get("skill_id")
        if not skill_id:
            return None
        return {"skill_id": skill_id,
                "expires_at": response_mode.get("expires_at", -1)}

    @staticmethod
    def _promote_handler(handlers: List[Dict[str, Any]], skill_id: str,
                         activated_at: Optional[float] = None
                         ) -> List[Dict[str, Any]]:
        """Dedup-and-promote ``skill_id`` to the head of ``handlers``
        (in place).

        Removes any existing entry with the same ``skill_id`` then
        inserts a fresh ``{skill_id, activated_at}`` at index 0 — the
        recency-stack rule shared by OVOS-PIPELINE-1 §7.1 and
        OVOS-CONVERSE-1 §3.1."""
        if activated_at is None:
            activated_at = time.time()
        handlers[:] = [h for h in handlers if h.get("skill_id") != skill_id]
        handlers.insert(0, {"skill_id": skill_id, "activated_at": activated_at})
        return handlers

    @staticmethod
    def _cap_handlers(handlers: List[Dict[str, Any]],
                      cap: Optional[int]) -> List[Dict[str, Any]]:
        """Tail-drop ``handlers`` down to ``cap`` entries (in place).

        ``cap`` is the orchestrator-supplied per-insertion limit
        (OVOS-CONVERSE-1 §2.1), not session state. A ``cap`` of ``None``
        or ``<= 0`` means "unbounded". The least-recent surviving owners
        (the tail) are dropped."""
        if cap and cap > 0 and len(handlers) > cap:
            del handlers[cap:]
        return handlers

    @property
    def active(self) -> bool:
        """``True`` when any handler is active in ``active_handlers``
        (OVOS-PIPELINE-1 §7.1)."""
        return len(self.active_handlers) > 0

    # active_handlers (OVOS-PIPELINE-1 §7.1)
    def add_active_handler(self, skill_id: str,
                           activated_at: Optional[float] = None):
        """Push a handler onto ``active_handlers``, dedup-and-promoting
        it to the head (OVOS-PIPELINE-1 §7.1). The list is head-first by
        recency; any prior entry with the same ``skill_id`` is evicted."""
        self._promote_handler(self.active_handlers, skill_id, activated_at)

    def remove_active_handler(self, skill_id: str):
        """Remove ``skill_id`` from ``active_handlers`` (e.g. a STOP-1
        drain)."""
        self.active_handlers[:] = [h for h in self.active_handlers
                                   if h.get("skill_id") != skill_id]

    # converse_handlers (OVOS-CONVERSE-1 §2.1 / §3.1)
    def add_converse_handler(self, skill_id: str,
                             activated_at: Optional[float] = None,
                             cap: Optional[int] = DEFAULT_CONVERSE_HANDLERS_CAP):
        """Stamp a handler onto ``converse_handlers``: dedup-promote to
        head, then tail-drop at ``cap`` (OVOS-CONVERSE-1 §2.1 / §3.1).

        ``cap`` is the orchestrator-supplied per-insertion limit — a
        deployment value applied here, never stored on the session. It
        defaults to the spec's documented §2.1 default
        (:data:`DEFAULT_CONVERSE_HANDLERS_CAP`); ``None`` or ``<= 0``
        means "unbounded"."""
        self._promote_handler(self.converse_handlers, skill_id, activated_at)
        self._cap_handlers(self.converse_handlers, cap)

    def remove_converse_handler(self, skill_id: str):
        """Remove ``skill_id`` from ``converse_handlers``."""
        self.converse_handlers[:] = [h for h in self.converse_handlers
                                     if h.get("skill_id") != skill_id]

    def prune_converse_handlers(self, ttl: float,
                                now: Optional[float] = None):
        """Drop ``converse_handlers`` entries older than ``ttl`` seconds
        (OVOS-CONVERSE-1 §3.2).

        ``now - activated_at > ttl`` is dropped. A non-positive ``ttl``
        disables time-based pruning. The caller (the orchestrator)
        invokes this at the pre-converse and pre-list-emission
        boundaries."""
        if not ttl or ttl <= 0:
            return
        now = now if now is not None else time.time()
        self.converse_handlers[:] = [
            h for h in self.converse_handlers
            if now - h.get("activated_at", now) <= ttl
        ]

    # response_mode (OVOS-CONVERSE-1 §2.2) — single-holder
    def set_response_mode(self, skill_id: str, expires_at: float):
        """Set the single-holder response window (OVOS-CONVERSE-1 §2.2).

        Overwrites any existing holder silently (single-holder
        invariant)."""
        self.response_mode = {"skill_id": skill_id, "expires_at": expires_at}

    def clear_response_mode(self, skill_id: Optional[str] = None):
        """Clear the response window.

        When ``skill_id`` is given, clears it only if that skill
        currently holds the window (a skill MUST NOT clear another's
        hold); otherwise clears unconditionally."""
        if self.response_mode is None:
            return
        if skill_id is None or self.response_mode.get("skill_id") == skill_id:
            self.response_mode = None

    # --- §2 / §5 wire shape -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Render the session as a JSON-friendly dict per §2 + §5.

        Fields whose Python value is ``None`` / empty are **omitted**,
        never emitted as ``null`` (§2.1). An empty list-valued override
        is wire-equivalent to omission and is dropped (§3.4). Unknown
        fields are not modelled by this class (see
        :data:`SESSION1_REGISTERED_FIELDS`) so they are not re-emitted
        here; §4 propagation of unknown keys instead relies on
        ``Message.forward`` / ``Message.reply`` deep-copying the raw wire
        ``context`` rather than reconstructing it through this method."""
        out: Dict[str, Any] = {}

        # §3.1 / §3.2 / §3.3 owned scalars
        if self.session_id is not None:
            out["session_id"] = self.session_id
        if self.lang is not None:
            out["lang"] = self.lang
        if self.secondary_langs:
            out["secondary_langs"] = list(self.secondary_langs)
        if self.output_lang is not None:
            out["output_lang"] = self.output_lang
        if self.stt_lang is not None:
            out["stt_lang"] = self.stt_lang
        if self.request_lang is not None:
            out["request_lang"] = self.request_lang
        if self.detected_lang is not None:
            out["detected_lang"] = self.detected_lang
        if self.site_id is not None:
            out["site_id"] = self.site_id
        if self.location:
            out["location"] = dict(self.location)

        # other-spec list/object override fields (omit-when-empty, §3.4)
        for name in _LIST_OVERRIDE_FIELDS:
            value = getattr(self, name)
            if value:
                out[name] = list(value)
        for name in _OBJECT_OVERRIDE_FIELDS:
            value = getattr(self, name)
            if value:
                out[name] = deepcopy(value)

        # OVOS-PERSONA-1 registered scalar(s) (omit-when-empty, §2.1)
        for name in _STRING_OVERRIDE_FIELDS:
            value = getattr(self, name)
            if value is not None:
                out[name] = value

        # PIPELINE-1 §7.1 / CONVERSE-1 §2.1 / §2.2 — omit-when-empty
        if self.active_handlers:
            out["active_handlers"] = deepcopy(self.active_handlers)
        if self.converse_handlers:
            out["converse_handlers"] = deepcopy(self.converse_handlers)
        if self.response_mode:
            out["response_mode"] = dict(self.response_mode)

        return out

    def serialize(self) -> str:
        """Emit a JSON string per §5 (no NaN, UTF-8, single object)."""
        return json.dumps(self.to_dict(), ensure_ascii=False,
                          allow_nan=False)

    # --- construction from the wire -----------------------------------------

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "Session":
        """Construct a Session from a JSON-decoded dict per §2.

        Tolerant of the §2.1 deferral surface: an explicit ``null`` on
        any registered field is logged and treated as omitted, not as a
        rejection. Unknown fields are silently dropped from the
        in-process object — this class does not reject them (§2.4) but
        also does not model them; §4 propagation of unknown keys is
        instead handled at the Message level (``Message.forward`` /
        ``Message.reply`` deep-copy the raw wire ``context`` rather than
        reconstructing it through this method). Passing ``None`` (no
        ``session`` key in ``context``) yields the same well-formed empty
        session as ``{}`` (§2.1).

        A wrong-typed field is malformed too, and §2.5 resolves malformedness
        field-by-field: "the offending field is treated as omitted and the
        rest of the session is consumed normally." A single bad field
        therefore does not cost the whole session — only :class:`Session`
        itself validates cross-field rules (e.g. §3.2.2's ``secondary_langs``
        collision), so a combination that only the constructor rejects still
        raises."""
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise MalformedSession(
                "session must be a JSON object (§2 / §5)")

        kwargs: Dict[str, Any] = {}
        for key, value in payload.items():
            if key not in SESSION1_REGISTERED_FIELDS:
                # §2.4: unknown fields are not rejected, just not modelled.
                continue
            if value is None:
                # §2.1: explicit null is malformed — log, treat as omitted.
                _log.warning(
                    "OVOS-SESSION-1 §2.1: explicit null on `%s` is "
                    "malformed; treating as omitted", key)
                continue
            kwargs[key] = value
        try:
            return cls(**kwargs)
        except MalformedSession:
            pass

        # §2.5: probe each field on its own so a malformed one is dropped
        # without rejecting fields that validate fine by themselves.
        valid: Dict[str, Any] = {}
        for key, value in kwargs.items():
            try:
                cls(**{key: value})
            except MalformedSession as exc:
                # name the wire type, so the producer that sent it can be found
                # (§2). The prefix is §2 and not §2.5: §2.5 is the malformed
                # *carrier*, which makes a consumer drop the Message, and this
                # line reports a malformed field, which is dropped alone.
                _log.warning(
                    "OVOS-SESSION-1 §2: `%s` is malformed (%s; got %s); "
                    "treating as omitted", key, exc, _wire_type(value))
                continue
            valid[key] = value
        return cls(**valid)

    @classmethod
    def deserialize(cls,
                    payload: Union[str, bytes, bytearray,
                                   Dict[str, Any], None]) -> "Session":
        """Parse a serialized session per §5 and §2.

        Accepts bytes/str JSON, an already-parsed dict, or ``None``.
        Raises :class:`MalformedSession` only for the structural
        failures §5 calls hard errors (unparsable JSON, non-object
        root). Field-level malformedness (an explicit ``null``) is
        absorbed by :meth:`from_dict`."""
        if payload is None:
            return cls()
        return cls.from_dict(parse_session_payload(payload))

    # --- §4 propagation -----------------------------------------------------

    def propagate(self) -> "Session":
        """Return a deep copy suitable for attaching to a derived
        Message (§4). Every field this class models rides along
        unchanged. Unknown wire keys are not carried by this method (this
        class does not model them); when a derived Message is built via
        ``Message.forward`` / ``Message.reply`` the raw wire ``context``
        is deep-copied instead, which does preserve unknown session keys
        verbatim — that is the path real §4 propagation takes."""
        return Session.from_dict(self.to_dict())

    @classmethod
    def materialize_default(cls) -> "Session":
        """Materialize the default session per §4.1.

        Sets ``session_id`` to ``"default"`` and leaves every other
        field omitted; the §4.1 rule forbids populating per-component
        overrides on a materialized default."""
        return cls(session_id=DEFAULT_SESSION_ID)

    def update_from(self, other: "Session") -> "Session":
        """Replace this session's state with ``other``'s, in place.

        A whole-object replace, applied with full OVOS-SESSION-1 §2 deserialization rather than a raw
        ``__dict__`` merge: the incoming state is round-tripped through
        :meth:`serialize` / :meth:`deserialize`, so a key present on the wire
        overrides this session's value (even when empty) and a null / omitted
        key resolves to the spec default — exactly as a freshly received message
        would parse. Round-tripping also rebuilds nested state, so the live
        object never aliases ``other``'s mutable sub-objects.

        ``deserialize`` is resolved through ``type(self)`` so a subclass (e.g.
        the ovos-bus-client ``Session`` with its legacy projections) rebuilds as
        itself. The ``session_id`` is preserved — it is the key this session
        is registered under in :class:`SessionManager` and must not drift even
        if ``other`` carries a different one.
        """
        if other is self:
            return self
        rebuilt = type(self).deserialize(other.serialize())
        rebuilt.session_id = self.session_id
        self.__dict__ = rebuilt.__dict__
        return self

    # --- value semantics ----------------------------------------------------

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Session)
                and self.to_dict() == other.to_dict())

    def __hash__(self) -> int:
        # Hash over the same canonical ``to_dict()`` view ``__eq__``
        # compares, frozen into a deterministic hashable form so equal
        # Sessions always hash equal (the hash/eq contract). NOTE: a
        # Session is mutable, so this is a *point-in-time snapshot* — safe
        # for ``functools.lru_cache`` keys and short-lived set/dict
        # membership, but do not mutate a Session while it is live as a
        # dict key.
        return hash(_freeze(self.to_dict()))

    def __repr__(self) -> str:
        return f"Session({self.to_dict()!r})"


class SessionManager:
    """Orchestrator-side session state, per OVOS-SESSION-2.

    ``SessionManager`` is an implementation detail, not part of any spec.
    Exactly one session is authoritative here — the reserved ``"default"``
    id (§3.1), held as the default-session store (§2.3 / §5). Every other
    session is client-owned (§2.5) and the orchestrator is stateless for
    it (§2.2): its state arrives whole on each inbound Message and leaves
    on the derived ones, so ``sessions`` only ever holds the default entry.

    State enters through :meth:`fold_inbound` (arrival, §5.1 first bullet)
    and :meth:`update` (derivation-chain writes, §2.6 / §5.1 third bullet).
    §2.7 defines no push topic a participant sends another; session state
    converges only by start-up derivation and runtime adoption, both of
    which are §5.1 arrivals :meth:`fold_inbound` already handles. :meth:`get`
    is a pure read; see OVOS-SESSION-2 §2.2 / §5.1 for the full
    read/write/propagation model, and ``session_cls`` lets a downstream
    layer (e.g. ovos-bus-client) point the registry at a ``Session``
    subclass.
    """

    #: Session class the registry builds; override downstream to a subclass.
    session_cls = Session
    #: id -> the one live Session object for that id.
    sessions: Dict[str, "Session"] = {}
    #: Kept for readers of the pre-spec attribute; the registry (``sessions``)
    #: is authoritative and this is only ever written to mirror it, never
    #: read internally. Removed in 2.0.0.
    default_session: Optional["Session"] = None
    #: Unrecognised top-level keys most recently carried onto the default
    #: session. §2.4 forbids stripping them and SESSION-2 §5.1 requires the
    #: store to carry them on the sessions it derives; :class:`Session`
    #: itself only models the §3 field set (§2.4's own carve-out), so the
    #: store keeps what it does not model here instead.
    _extras: Dict[str, Any] = {}
    # Reentrant: a write into the default-session store runs update_from
    # while holding this lock, and update_from runs full deserialization
    # (Session.__init__ -> config load, subclass projections, and any
    # finalizer that fires during that allocation) which can re-enter the
    # registry on the same thread — e.g. a garbage-collected skill whose
    # __del__ emits a deregister message that folds back through
    # SessionManager.update. A non-reentrant lock self-deadlocks that thread.
    _lock = RLock()

    @classmethod
    def _wire_dict(cls, sess: "Session") -> Dict[str, Any]:
        """Return ``sess`` as a wire dict.

        ``Session.serialize`` returns a JSON string here, but a subclass
        (ovos-bus-client) overrides it to return a dict carrying extra legacy
        projection keys. Normalise both to a dict so the richer shape, when
        present, survives onto ``message.context["session"]``.

        For the default store, the top-level keys no registered field
        models are re-emitted alongside it too: SESSION-2 §5.1 "Field
        tolerance applies at store-write ... it MUST carry them on the
        sessions it subsequently derives from the store." A named session
        has no store to hold them in, so :meth:`_session_from_carrier`
        stashes the same unrecognised keys on the object itself
        (``_carrier_extras``) and they are re-emitted here the same way —
        §2.4's MUST-NOT-strip applies to it too.
        """
        data = sess.serialize()
        if isinstance(data, (str, bytes, bytearray)):
            data = json.loads(data)
        if sess is cls.sessions.get(DEFAULT_SESSION_ID):
            data = {**cls._extras, **data}
        elif getattr(sess, "_carrier_extras", None):
            data = {**sess._carrier_extras, **data}
        return data

    @classmethod
    def get_default_session(cls) -> "Session":
        """Return (materializing once) the singleton for the reserved default id.

        The shared ``sessions`` dict is the single source of truth — keyed off
        ``sessions[DEFAULT_SESSION_ID]``. This matters when a subclass
        (ovos-bus-client) and this base both reach the registry: a
        class-attribute mirror would shadow per class and diverge, whereas the
        dict is one shared object.
        """
        sess = cls.sessions.get(DEFAULT_SESSION_ID)
        if sess is None:
            sess = cls.session_cls.deserialize({"session_id": DEFAULT_SESSION_ID})
            cls.sessions[DEFAULT_SESSION_ID] = sess
        cls.default_session = sess
        return sess

    @classmethod
    def fold_inbound(cls, message: "object") -> "Session":
        """Take an inbound Message into session state and return the session to run it on.

        This is the arrival point of the utterance lifecycle (PIPELINE-1
        §6) and the single place OVOS-SESSION-2 §5.1's first bullet
        happens: *every inbound Message bearing the default session is
        merged into the store*. The orchestrator calls it once per inbound
        utterance; nothing else writes an arrival.

        The carrier is read raw off ``message.context["session"]``, never
        through a Session object, because the merge turns on **which fields
        the Message carried** and an object cannot distinguish an omitted
        field from one sent at its default (see :func:`merge_carrier`).

        For the default session — an absent carrier, ``{}``, a carrier
        naming no id, or an explicit ``"default"``, all equivalent per
        SESSION-1 §3.1 and permitted of the local device by SESSION-2 §6.5
        — the carrier merges into the store field by field and the live
        store object is returned, so a reference held across the utterance
        stays current.

        For a named session the orchestrator holds nothing (§2.2): the
        carrier is the whole snapshot, so the returned session is built from
        it alone and nothing is kept. §2.2 permits a transient per-utterance
        cache but forbids anything from relying on one as durable, and a
        registry keyed on ``session_id`` alone has no end-of-utterance to
        evict at — a cached named session would outlive its utterance and
        be stamped onto the next one.
        """
        carrier = cls._carrier(message)
        if resolve_session_id(carrier) == DEFAULT_SESSION_ID:
            return cls._merge_into_default(carrier)
        return cls._session_from_carrier(carrier)

    @classmethod
    def _merge_into_default(cls, carrier: Dict[str, Any]) -> "Session":
        """Merge ``carrier`` into the default store per OVOS-SESSION-2 §5.1.

        Splits the merged wire dict into the §3 fields :class:`Session`
        models and the unrecognised top-level keys it does not (§2.4). The
        fields go through the deserializer as before; the unrecognised keys
        are field-tolerant the same way — a carried one replaces, an omitted
        one leaves the last stored value alone, per §5.1's "Field tolerance
        applies at store-write" — and are kept in :attr:`_extras` so
        :meth:`_wire_dict` can carry them onto the sessions this store
        subsequently derives.
        """
        with cls._lock:
            stored = cls.get_default_session()
            merged = merge_carrier(stored, carrier)
            cls._extras.update(
                (key, value) for key, value in merged.items()
                if key not in SESSION1_REGISTERED_FIELDS)
            return stored.update_from(cls.session_cls.deserialize(merged))

    @classmethod
    def update(cls, sess: "Session") -> "Session":
        """Write a session produced by the derivation chain back into state.

        This is the OVOS-SESSION-2 §2.6 write: a transformer mutated the
        session, a pipeline plugin returned a ``Match.updated_session``, or
        a handler changed it in place, and §5.1's third bullet says those
        mutations propagate into the store. Unlike an arrival this one is
        object-shaped and authoritative — the caller holds the whole
        session and means all of it — so it replaces rather than merges.

        The default store keeps its identity across the replace: components
        hold references to it and the ``sessions`` entry is the store. A
        named session is returned unchanged and nothing is recorded — §2.2
        leaves the orchestrator stateless for it, and the working session
        travels through the utterance flow that holds it.
        """
        if not sess:
            raise ValueError("Expected Session and got None")
        if not sess.is_default:
            # §2.2: no state for a named id, not even briefly. The working
            # session lives in the utterance flow that holds it; the caller
            # already has the object and passes it along.
            return sess
        with cls._lock:
            stored = cls.get_default_session()
            return stored if stored is sess else stored.update_from(sess)

    @classmethod
    def bind(cls, message: "object", session: "Session") -> "Session":
        """Bind ``session`` as the session of ``message``, replacing any prior binding.

        Lets an orchestrator hold one round session end to end: every later
        :meth:`get` and :meth:`stamp_derived` in the round sees this exact
        object, mutations included. See OVOS-SESSION-2 §2.2 / §5.1 for the
        full write model.
        """
        if session.is_default and session is not cls.get_default_session():
            # A default-shaped Session that isn't the registry's own store
            # would make get() (returns the binding) and stamp_derived()
            # (reads the store directly) disagree about the same Message.
            raise ValueError(
                "bind() refuses a default-shaped Session that is not the "
                "registry's own default store, or stamp_derived would "
                "disagree with get() about the same Message; obtain it via "
                "SessionManager.get_default_session() and bind that object")
        carrier = cls._carrier(message)
        if carrier:
            carrier_id = resolve_session_id(carrier)
            session_id = session.resolved_session_id()
            if carrier_id != session_id:
                # A carrier naming one id and a binding for another are two
                # conflicting claims about the Message's session; a
                # carrier-less Message makes no claim to contradict.
                raise ValueError(
                    f"bind() session id {session_id!r} does not match "
                    f"the message's own carrier id {carrier_id!r}")
        message._bound_session = session
        return session

    @classmethod
    def bound(cls, message: "object") -> Optional["Session"]:
        """The session currently bound to ``message``, or ``None`` if none is.

        A read-only peek at the same attribute :meth:`get` and :meth:`bind`
        use, for callers that need to tell "nothing bound yet" apart from
        triggering :meth:`get`'s side effect of binding one.
        """
        return getattr(message, "_bound_session", None)

    @classmethod
    def get(cls, message: Optional["object"] = None) -> "Session":
        """Return the session a Message refers to, without writing anything.

        A pure read: a Message naming the default session (or none)
        resolves to the store (§5); one naming another id resolves to the
        session built from its own carrier (§2.2). The result is bound to
        the Message and reused on later calls, so a component that reads,
        mutates and derives has its mutation picked up by
        :meth:`stamp_derived`. See OVOS-SESSION-2 §2.2 / §5.1 for the
        binding and propagation rules.
        """
        if message is None:
            return cls.get_default_session()
        carrier = cls._carrier(message)
        session_id = resolve_session_id(carrier)
        bound = cls.bound(message)
        if bound is not None and (
                not carrier or bound.resolved_session_id() == session_id):
            return bound
        sess = (cls.get_default_session() if session_id == DEFAULT_SESSION_ID
                else cls._session_from_carrier(carrier))
        message._bound_session = sess
        return sess

    @classmethod
    def _session_from_carrier(cls, carrier: Dict[str, Any]) -> "Session":
        """Build the session a named carrier describes, per OVOS-SESSION-2 §2.2.

        A named session is whatever its carrier says and nothing else — the
        orchestrator holds no state to fill the gaps from.

        The carrier is read through :func:`carried_fields` so that a
        wrong-typed field is tolerated the same way it is on the default
        session: SESSION-1 §2.5 resolves field-level malformedness
        field-by-field for every consumer, so one bad `lang` must not cost
        the Message its session. ``intent_context`` sheds its ``null``
        entries here: OVOS-CONTEXT-1 §5.3 gives them the meaning *remove
        this key*, and there is nothing to remove from a snapshot that
        stands alone.

        The unrecognised top-level keys ``carried_fields`` passes through
        verbatim (§2.4) are stashed on the built object as
        ``_carrier_extras`` so :meth:`_wire_dict` can carry them onto the
        Messages this session is stamped on — the same MUST-NOT-strip rule
        the default store honours, applied to a session that has no store
        of its own to keep them in.
        """
        fields = carried_fields(carrier)
        entries = {key: entry
                   for key, entry in (fields.get("intent_context") or {}).items()
                   if entry is not None}
        if entries:
            fields["intent_context"] = entries
        else:
            fields.pop("intent_context", None)
        extras = {key: value for key, value in fields.items()
                 if key not in SESSION1_REGISTERED_FIELDS}
        sess = cls.session_cls.deserialize(fields)
        if extras:
            sess._carrier_extras = extras
        return sess

    @staticmethod
    def _carrier(message: "object") -> Dict[str, Any]:
        """The raw session carrier off a Message.

        An absent ``session``, an explicit ``null``, and ``{}`` are all the
        same thing per SESSION-1 §2.1 — they resolve to the default session
        — so all three come back as the empty carrier. A carrier that is
        present but not an object is a malformed carrier (§2.5) and raises;
        substituting the default for it would route the Message into the
        wrong session.
        """
        ctx = getattr(message, "context", None) or {}
        carrier = ctx.get("session")
        if carrier is None:
            return {}
        if not isinstance(carrier, dict):
            raise MalformedSession(
                "session must be a JSON object (§2.5)")
        return carrier

    @classmethod
    def stamp_derived(cls, message: "object", source: "object") -> "object":
        """Stamp a message derived from ``source`` with the live session.

        The derivations of MSG-1 §5 deep-copy the source's carrier, which is
        the session as it stood when the source Message was built. When a
        component asked :meth:`get` about the source and mutated what it got
        — the handler write of OVOS-CONTEXT-1 §5.3 — that snapshot is stale
        and the bound session is the live one, so it is what goes on the
        derived message. The check on the id keeps a derivation addressed at
        a different session from inheriting the source's.

        The bound session takes precedence over the source's carrier dict
        whenever the two name the same id: once a component has read the
        session off a Message, an edit written straight into
        ``message.context["session"]`` does not reach the derivation. The
        session object is the thing to write to. A derived Message with no
        session snapshot of its own has made no competing claim either —
        :meth:`bind` allows binding a named session onto a carrier-less
        Message for exactly this reason — so an absent snapshot also
        inherits the binding rather than being routed through the
        default-store fallback below.

        With no binding, or a binding for another id, this falls back to
        :meth:`sync_message_session`: the default store still stamps and a
        named carrier still travels verbatim.
        """
        bound = cls.bound(source)
        if bound is not None and not bound.is_default:
            snap = message.context.get("session")
            if snap is None or (isinstance(snap, dict)
                    and resolve_session_id(snap) == bound.resolved_session_id()):
                message.context["session"] = cls._wire_dict(bound)
                return message
        return cls.sync_message_session(message)

    @classmethod
    def sync_message_session(cls, message: "object") -> "object":
        """Stamp a derived message with the live default-session store.

        A named carrier travels verbatim (§2.2 / §2.5, client-owned); a
        message with no session, or one naming the default id, gets the
        store's current state (§4.3).
        """
        ctx = message.context
        snap = ctx.get("session")
        if snap is None:
            # §4.3: a Message without a session implies the default session —
            # stamp it (also the emit inject-when-missing path).
            ctx["session"] = cls._wire_dict(cls.get_default_session())
            return message
        if isinstance(snap, dict) and resolve_session_id(snap) == DEFAULT_SESSION_ID:
            ctx["session"] = cls._wire_dict(cls.get_default_session())
        return message

    @classmethod
    def reset_default_session(cls) -> "Session":
        """Replace the default session with a fresh empty one and return it."""
        with cls._lock:
            sess = cls.session_cls.deserialize({"session_id": DEFAULT_SESSION_ID})
            cls.sessions[DEFAULT_SESSION_ID] = sess
            cls.default_session = sess
            cls._extras = {}
        return sess
