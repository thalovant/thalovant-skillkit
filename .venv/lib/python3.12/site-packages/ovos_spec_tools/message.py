"""Reference implementation of OVOS-MSG-1 — the bus :class:`Message` envelope.

Spec implemented
----------------
**OVOS-MSG-1** (*Bus Message Specification*, Version 1, Draft). This module
is the reference implementation of every normative clause the spec assigns
to the Message *value* (as opposed to the transport): the JSON envelope of
§2, the routing keys of §3 (carried but never interpreted), the session
carrier of §4 (carried as an opaque dict), the three derivations of §5
(:meth:`Message.forward`, :meth:`Message.reply`, :meth:`Message.response`),
and the serialization/conformance rules of §6/§7.

Conformance surface
-------------------
This class is simultaneously a conformant **producer** and **consumer** in
the §7 sense:

- *producer* — :meth:`serialize` emits a single UTF-8 JSON object with only
  ``type`` / ``data`` / ``context`` (§7 producer MUSTs, §6 serialization);
  :meth:`forward` / :meth:`reply` / :meth:`response` follow §5 exactly.
- *consumer* — :meth:`deserialize` rejects every payload the §7 consumer
  rules call malformed, and treats absent ``data`` / ``context`` as ``{}``
  (§2). ``source`` / ``destination`` / ``session`` are treated as opaque
  and optional (§3.4, §4, §7 consumer MUSTs).

Non-goals (§7 / §1)
-------------------
This module deliberately does **not** own: transport (websocket, queue, …),
encryption, authentication, authorization, delivery/ordering guarantees,
retry, session lifecycle (start/end/expiry/resumption), the *internal* shape
of ``session`` (owned by OVOS-SESSION-1), identifier-assignment policy, and
multi-tenant routing semantics beyond the opaque layer-2 substrate of §3.4 /
§4.2. Those concerns live in the layers that consume this primitive —
``ovos-bus-client`` for the websocket transport, HiveMind for multi-tenant
routing, ``ovos-audio`` / ``ovos-core`` for the per-topic policy decisions
keyed on ``session_id`` (§4) and ``lang``.

The implementation has **no dependencies** outside the standard library;
it is the foundation other bus-layer code (notably ``ovos-bus-client``'s
transport-layer ``Message`` subclass) builds on.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Union

__all__ = ["Message", "MalformedMessage", "DEFAULT_SESSION_ID"]

#: The OVOS-MSG-1 §2.1 ``type`` syntax: a non-empty run of ASCII letters,
#: digits, and the four punctuation characters the spec permits — ``.`` ``:``
#: ``_`` ``-``. §2.1 forbids whitespace and any other character outright
#: ("ASCII letters, digits, ``.``, ``:``, ``_``, ``-``; no whitespace"), so
#: anything outside this set — an embedded space, a slash, a non-ASCII letter —
#: is a malformed topic the producer MUST NOT emit. Lowercase is only
#: RECOMMENDED (§2.1), so uppercase is accepted.
_TYPE_SYNTAX_RE = re.compile(r"[A-Za-z0-9.:_-]+")

#: A routing key value as it may appear on the wire (OVOS-MSG-1 §3): a single
#: opaque identifier string, or — for ``destination`` only — an array of them
#: (§3.3). ``None`` models the absent/broadcast case (§3.3). The envelope
#: never parses these beyond string equality (§3.4).
RoutingValue = Union[str, List[str], None]


#: The reserved ``session_id`` meaning "the Message originates from the
#: device itself" (OVOS-MSG-1 §4.1). Used by ``ovos-audio`` to decide
#: that synthesized TTS plays out of the device's own speakers, and as
#: the implicit value for any Message that arrives without a ``session``
#: in its context (§4.3).
DEFAULT_SESSION_ID = "default"


def _stamp_live_session(message: "Message", source: "Message") -> "Message":
    """Refresh a derived message's ``session`` to the live value for its id.

    ``forward`` / ``reply`` deep-copy the originating message's ``session``
    snapshot (§5.1/§5.2). That snapshot may predate the current handler's
    mutations, so this re-stamps the derived message with the live session
    via :meth:`SessionManager.stamp_derived` — either the default-session
    store, or the session bound to ``source`` when a component read one off
    it. See that class for why this is always a meaningful refresh or a
    no-op, never a discard.

    Best-effort and non-invasive: a message with **no** session and no
    binding on ``source`` is left as-is (§5 carries no session forward),
    and a session id the registry never folded is left untouched — so this
    is transparent to pure spec usage that never wires a registry (the
    session is carried over verbatim, as §5 mandates). A carrier-less
    derivation whose source has a bound *named* session is the one
    exception: ``SessionManager.bind`` allows binding a named session onto
    a carrier-less Message precisely so a derivation can pick it up, so the
    registry hook still runs in that case.
    """
    try:
        ctx = getattr(message, "context", None) or {}
        if not ctx.get("session") and getattr(source, "_bound_session", None) is None:
            return message
        from ovos_spec_tools.session import SessionManager
        return SessionManager.stamp_derived(message, source)
    except Exception:  # never let session bookkeeping break message derivation
        return message


def _freeze(value: Any) -> Any:
    """Recursively convert ``value`` into a deterministic, hashable form.

    Used to derive ``__hash__`` for :class:`Message` and
    :class:`~ovos_spec_tools.session.Session` from the same nested
    dict/list payloads their ``__eq__`` compares. The mapping preserves
    Python's value-equality invariant: anything that compares equal
    freezes to an equal (and therefore equally-hashing) form. In
    particular ``{"x": 1}`` and ``{"x": 1.0}`` freeze equal because the
    underlying ``int``/``float`` are themselves equal and hash equal —
    unlike a ``json.dumps`` digest, which would diverge on ``"1"`` vs
    ``"1.0"``.

    - ``dict`` → ``frozenset`` of ``(key, _freeze(val))`` pairs
      (order-independent, mirroring dict equality);
    - ``list`` / ``tuple`` → ``tuple`` of frozen items (order-preserving);
    - ``set`` / ``frozenset`` → ``frozenset`` of frozen items;
    - already-hashable scalars (``str``, ``int``, ``float``, ``bool``,
      ``None``, …) → returned unchanged;
    - any remaining exotic unhashable → its ``repr`` (deterministic
      last resort).
    """
    if isinstance(value, dict):
        return frozenset((k, _freeze(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(v) for v in value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


class MalformedMessage(ValueError, AssertionError):
    """A serialized payload that does not conform to OVOS-MSG-1 §2 / §6.

    Raised by :meth:`Message.deserialize` when the payload fails any
    structural rule the spec calls out as ``MUST``: unknown top-level
    keys (§2), missing ``type`` (§2), wrong value types, or unparsable
    JSON (§6).

    Inherits from both :class:`ValueError` (the correctly-typed
    exception class) **and** :class:`AssertionError` (the type raised by
    ``ovos_bus_client.Message``'s bare ``assert`` constructor checks), so
    ``except AssertionError`` handlers in downstream code also catch the
    same conditions.
    """


class Message:
    """OVOS-MSG-1 envelope.

    Three top-level fields per §2:

    - :attr:`msg_type` (the wire field ``type``) — non-empty topic string
      matching the §2.1 syntax (ASCII letters/digits/``.``/``:``/``_``/``-``,
      no whitespace);
    - :attr:`data` — JSON-object payload; shape fixed by whichever
      specification defines :attr:`msg_type`;
    - :attr:`context` — JSON-object metadata, carrying the §3 routing
      keys (``source`` / ``destination``), the §4 session carrier, and
      any layer-2 metadata higher systems attach.

    The :attr:`data` and :attr:`context` dicts are stored by reference;
    callers that mutate them after constructing a Message see those
    mutations reflected in the Message. :meth:`forward` / :meth:`reply`
    / :meth:`response` deep-copy the context before deriving so the
    derived Message is independent of the source.
    """

    def __init__(self, msg_type: str,
                 data: Optional[Dict[str, Any]] = None,
                 context: Optional[Dict[str, Any]] = None) -> None:
        """Construct a Message envelope (OVOS-MSG-1 §2).

        Args:
            msg_type: the wire ``type`` field — the topic string (§2.1).
                Stored as :attr:`msg_type`. May be empty at construction
                time (see the inline note); :meth:`serialize` is the §7
                conformance gate for emitted output.
            data: the §2.2 payload object, or ``None`` for the empty
                default (``{}``). Stored **by reference**.
            context: the §2.3 metadata object (routing keys §3, session
                carrier §4, layer-2 metadata), or ``None`` for ``{}``.
                Stored **by reference**.

        Raises:
            MalformedMessage: if ``msg_type`` is not a ``str`` (§2.1), or
                ``data`` / ``context`` are given but not ``dict`` (§2.2 /
                §2.3). These mirror the §7 consumer "wrong types" rule at
                the constructor boundary.
        """
        # §2.1 requires the wire ``type`` to be non-empty, but it is a
        # spec rule for **emitted** Messages — the construct-then-forward
        # pattern (``Message("").forward(real_type, data)``) is widely
        # used to build a routing scaffold before the real topic is
        # known, so the constructor accepts an empty string here and
        # :meth:`serialize` is the gate that *rejects* non-conformant wire
        # output (an empty ``type`` raises there, per §7 producer rules).
        if not isinstance(msg_type, str):
            raise MalformedMessage("msg_type must be a string (§2.1)")
        if data is not None and not isinstance(data, dict):
            raise MalformedMessage("data must be a dict (§2.2)")
        if context is not None and not isinstance(context, dict):
            raise MalformedMessage("context must be a dict (§2.3)")
        self.msg_type: str = msg_type
        # §2.2 / §2.3: absent data/context are equivalent to ``{}``. Stored
        # by reference per the class docstring (derivations deep-copy).
        self.data: Dict[str, Any] = data if data is not None else {}
        self.context: Dict[str, Any] = context if context is not None else {}

    def __eq__(self, other: object) -> bool:
        # Value equality over the full §2 envelope (type + data + context).
        # Two Messages are equal iff every wire field is equal; routing
        # keys and session live inside ``context`` so they participate.
        return (isinstance(other, Message)
                and other.msg_type == self.msg_type
                and other.data == self.data
                and other.context == self.context)

    def __hash__(self) -> int:
        # Hash over the same §2 fields ``__eq__`` compares (type + data +
        # context), frozen into a deterministic hashable form so equal
        # Messages always hash equal (the hash/eq contract). NOTE: ``data``
        # and ``context`` are mutable dicts stored by reference, so this is
        # a *point-in-time snapshot* — safe for ``functools.lru_cache`` keys
        # and short-lived set/dict membership, but do not mutate a Message
        # while it is live as a dict key.
        return hash((self.msg_type,
                     _freeze(self.data),
                     _freeze(self.context)))

    def __repr__(self) -> str:
        # Eval-friendly debug form; not the wire format (use serialize()).
        return (f"{self.__class__.__name__}("
                f"msg_type={self.msg_type!r}, "
                f"data={self.data!r}, context={self.context!r})")

    # --- §6 serialization ---------------------------------------------------

    @property
    def as_dict(self) -> Dict[str, Any]:
        """The Message as a JSON-decoded ``dict`` (OVOS-MSG-1 §2 envelope).

        Returns ``{"type": ..., "data": ..., "context": ...}`` — the §2
        envelope keyed by the **wire** field names (``type``, not
        ``msg_type``). Equivalent to ``json.loads(self.serialize())`` and
        round-trips through :meth:`deserialize`; offered as a property for
        callers that want a one-shot dict view without the JSON-string
        intermediate. Carriers exposing ``.serialize()`` are converted the
        same way they would be on the wire (see :meth:`_to_jsonable`).

        Returns:
            The §2 envelope as a plain JSON-decoded dictionary.
        """
        return json.loads(self.serialize())

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        """Convert ``value`` to a JSON-friendly form for §6 serialization.

        Recursively walks containers and converts any object exposing a
        ``.serialize()`` method (the duck-typed protocol used by OVOS
        carrier objects like the OVOS-SESSION-1 ``Session``) by calling it.
        Plain JSON types pass through unchanged.

        This keeps :class:`Message` an honest pure-envelope class — it
        doesn't know about ``Session`` or any other carrier type, honouring
        OVOS-MSG-1's separation of the envelope from the §4 session shape
        (owned by OVOS-SESSION-1) — while letting callers stuff such objects
        directly into ``data`` / ``context`` and serialize the result.

        Args:
            value: any value found inside ``data`` / ``context``.

        Returns:
            A JSON-encodable structure: the result of ``value.serialize()``
            for carrier objects, a recursively-converted ``dict`` / ``list``
            for containers, or ``value`` itself for plain JSON scalars.
        """
        # Direct .serialize() — Session, nested Message, etc.
        ser = getattr(value, "serialize", None)
        if callable(ser) and not isinstance(value, (dict, list, tuple)):
            try:
                value = ser()
            except Exception:
                pass
        if isinstance(value, dict):
            return {k: Message._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [Message._to_jsonable(v) for v in value]
        return value

    def serialize(self) -> str:
        """Render the Message as a single UTF-8 JSON object (OVOS-MSG-1 §6).

        The output is exactly one top-level JSON object — never an array or
        a stream (§6) — with the §2 wire keys ``type`` / ``data`` /
        ``context``. ``NaN`` / ``±Infinity`` are forbidden, so
        ``allow_nan=False`` makes a non-finite number raise rather than emit
        invalid JSON (§6: "Numbers MUST be finite"). ``ensure_ascii=False``
        emits valid UTF-8 directly (§6: Unicode strings). Object key order
        is **not** significant (§6), so no ordering is imposed. Nested
        objects in ``data`` / ``context`` exposing ``.serialize()`` (e.g.
        the OVOS-SESSION-1 ``Session`` carrier) are converted first via
        :meth:`_to_jsonable`.

        Subclasses MAY override to add the transport-layer concerns §6/§7
        leave out — framing, encryption, alternative encoders — without
        touching this envelope contract.

        This method is the §7 producer conformance gate: §2.1 requires
        ``type`` to be a **non-empty** string and §7 makes a non-empty
        ``type`` a producer ``MUST``. The constructor tolerates an empty
        ``msg_type`` to allow the construct-then-``forward`` scaffold
        pattern, but emitting such a Message would put a malformed
        envelope on the wire, so ``serialize`` **refuses** it.

        Returns:
            A single UTF-8 JSON object string conforming to §6.

        Raises:
            MalformedMessage: when ``msg_type`` is empty — §2.1/§7 require a
                producer to emit a non-empty ``type``; an empty-``type``
                scaffold Message must be ``forward``/``reply``-derived into
                a real topic before it can be serialized. Also when
                ``msg_type`` violates the §2.1 syntax (a character outside
                ASCII letters/digits/``.``/``:``/``_``/``-``, e.g. an embedded
                space): such a topic must not reach the wire.
            ValueError: from :func:`json.dumps` when ``data`` / ``context``
                contain a non-finite number (``allow_nan=False``), enforcing
                the §6 "Numbers MUST be finite" rule at emit time.
        """
        # §2.1 / §7 producer MUST: the emitted ``type`` must be a non-empty
        # string. The constructor accepts "" for the construct-then-forward
        # scaffold; this is the gate that refuses to put it on the wire.
        if not self.msg_type:
            raise MalformedMessage(
                "cannot serialize a Message with an empty 'type' — §2.1/§7 "
                "require a producer to emit a non-empty topic; derive a real "
                "topic via forward()/reply() before serializing")
        # §2.1 ``type`` syntax: ASCII letters, digits, ``.`` ``:`` ``_`` ``-``;
        # no whitespace. The non-emptiness check above is the §7 producer MUST
        # for an empty topic; this is the §2.1 producer MUST for the charset.
        # An embedded space (``Message("a b")``) or any other character must
        # not reach the wire, so ``serialize`` refuses it here.
        if not _TYPE_SYNTAX_RE.fullmatch(self.msg_type):
            raise MalformedMessage(
                f"'type' {self.msg_type!r} violates OVOS-MSG-1 §2.1 syntax — a "
                "topic may contain only ASCII letters, digits, '.', ':', '_', "
                "'-' and no whitespace")
        return json.dumps(
            {"type": self.msg_type,
             "data": self._to_jsonable(self.data),
             "context": self._to_jsonable(self.context)},
            ensure_ascii=False, allow_nan=False)

    @classmethod
    def deserialize(cls,
                    payload: Union[str, bytes, bytearray, Dict[str, Any]]
                    ) -> Message:
        """Construct a Message from a serialized JSON object (OVOS-MSG-1 §6).

        Args:
            payload: a UTF-8 ``bytes`` / ``bytearray`` (decoded first), a
                ``str`` (parsed as JSON), or an already-parsed ``dict``
                (the JSON step is skipped).

        Returns:
            An instance of ``cls`` — subclasses (e.g. ``ovos-bus-client``'s
            transport-layer Message) deserialize to their own type — with
            absent ``data`` / ``context`` defaulted to ``{}`` (§2).

        Raises :class:`MalformedMessage` per the §7 ``MUST reject``
        conformance rules: unparsable JSON, non-object root, unknown
        top-level keys, missing ``type``, or wrong value types — including
        a present-but-non-object ``data`` / ``context`` (``[]``, ``0``,
        ``false``, …), which §6 forbids silently coercing to ``{}``.
        """
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise MalformedMessage(
                    f"payload is not valid JSON: {exc}") from exc
        else:
            obj = payload
        if not isinstance(obj, dict):
            raise MalformedMessage(
                "Message payload must be a JSON object (§2)")
        # §2: "Other top-level keys MUST NOT appear; consumers MUST
        # reject any Message with unknown top-level keys."
        unknown = set(obj.keys()) - {"type", "data", "context"}
        if unknown:
            raise MalformedMessage(
                f"unknown top-level keys {sorted(unknown)!r} — §2 "
                "forbids any key other than 'type', 'data', 'context'")
        if "type" not in obj:
            raise MalformedMessage("missing required key 'type' (§2)")
        # §2.2/§2.3: when present, ``data`` and ``context`` MUST be JSON
        # objects. An ABSENT key defaults to ``{}`` ("MAY be empty"), but a
        # *present* wrong-typed value ([], 0, false, "", null) is malformed
        # and §6 forbids silently coercing it — reject per the §7 consumer
        # "wrong types" MUST instead of papering over it with ``or {}``.
        for key in ("data", "context"):
            if key in obj and obj[key] is not None \
                    and not isinstance(obj[key], dict):
                raise MalformedMessage(
                    f"'{key}' must be a JSON object when present, got "
                    f"{type(obj[key]).__name__} (§2.{2 if key == 'data' else 3}/§7)")
        # An absent (or explicit null) data/context defaults to {} per
        # §2.2/§2.3 ("an absent data/context is equivalent to {}").
        return cls(obj["type"],
                   obj["data"] if obj.get("data") is not None else {},
                   obj["context"] if obj.get("context") is not None else {})

    # --- §5 derivations -----------------------------------------------------

    def forward(self, msg_type: str,
                data: Optional[Dict[str, Any]] = None) -> Message:
        """Implement OVOS-MSG-1 §5.1 (``forward``) — relay under a new topic.

        Produces ``{type: msg_type, data: data, context: deepcopy(C)}``:
        ``context`` (the §3 routing keys **and** the §4 ``session``) is
        carried over **unchanged**, so the forwarder does **not** become
        the new ``source`` — the original producer stays named (§5.1, §3.2).
        This is the derivation the spec mandates for relay/notification
        topics that must preserve the asker's routing — e.g. the
        PIPELINE-1 §8 handler-lifecycle trio is required to be
        ``forward``-derived.

        The context is **deep-copied** so the derived Message is independent
        of the source (a §5.1 "MUST NOT modify a session already present"
        guarantee — mutating either Message's context cannot leak into the
        other).

        Args:
            msg_type: ``type`` of the relayed Message (``T'`` in §5.1).
            data: payload of the relayed Message (``D'``); ``None`` → ``{}``.

        Returns:
            A new Message of ``self``'s runtime class (subclasses propagate,
            see :ref:`Subclassing`).
        """
        derived = self.__class__(
            msg_type, data or {}, deepcopy(self.context))
        return _stamp_live_session(derived, self)

    def reply(self, msg_type: str,
              data: Optional[Dict[str, Any]] = None,
              context: Optional[Dict[str, Any]] = None) -> Message:
        """Implement OVOS-MSG-1 §5.2 (``reply``) — address back to the asker.

        Deep-copies :attr:`context` and **reverses** the §3 routing keys so
        the result is addressed back to the source Message's producer:

        - new ``destination`` := old ``source`` (§5.2 step 1, when set);
        - new ``source`` := old ``destination`` — if the old
          ``destination`` was an array, the **first** entry is chosen
          (§5.2 step 2: the choice is implementation-defined and consumers
          MUST NOT rely on a particular member);
        - every other context key, including ``session`` (§4), is preserved
          unchanged (§5.2 step 3).

        Any keys supplied via ``context`` are overlaid on the copied context
        **before** the swap, matching ``ovos_bus_client.Message.reply``
        behaviour: passing
        ``context={"source": "C", "destination": "D"}`` yields
        ``source=D, destination=C`` because the §5.2 swap is the final step.
        Non-routing keys overlaid this way (a custom ``session`` shape, a
        tracing identifier, …) pass through untouched — the envelope never
        ascribes meaning to them (§2.3).

        Args:
            msg_type: ``type`` of the reply Message (``T'`` in §5.2).
            data: payload of the reply (``D'``); ``None`` → ``{}``.
            context: optional context keys overlaid before the §5.2 swap.

        Returns:
            A new Message of ``self``'s runtime class with the §5.2 routing.

        Note:
            A producer that maintains no ``source`` / ``destination`` at all
            gets a context with neither key set — i.e. a broadcast (§3.3),
            which §5.2 names as the only well-defined behaviour absent
            addressing information.
        """
        new_context = deepcopy(self.context)
        # an explicit ``session`` in the caller-supplied ``context`` is an
        # author's choice — honour it and skip the live-session refresh, so a
        # deliberately-constructed session is never overwritten by the registry.
        explicit_session = bool(context) and "session" in context
        if context:
            new_context.update(context)
        # §5.2 swap. Read both sides BEFORE writing to avoid clobbering.
        src = new_context.get("source")
        dst = new_context.get("destination")
        if dst is not None:
            # array-of-strings form: producer chooses one; consumers
            # MUST NOT rely on a particular member being chosen (§5.2)
            new_context["source"] = (
                dst[0] if isinstance(dst, list) and dst else dst)
        if src is not None:
            new_context["destination"] = src
        derived = self.__class__(msg_type, data or {}, new_context)
        return derived if explicit_session else _stamp_live_session(derived, self)

    def response(self, data: Optional[Dict[str, Any]] = None,
                 context: Optional[Dict[str, Any]] = None) -> Message:
        """Implement OVOS-MSG-1 §5.3 (``response``) — a ``.response``-suffixed reply.

        Equivalent to ``reply(self.msg_type + ".response", data, context)``
        (§5.3). Topics defined in other specifications MAY rely on the
        ``.response`` suffix convention to mark a Message as the answer to a
        prior request — e.g. INTENT-4 §10's ``ovos.intent.list.response`` /
        ``ovos.intent.describe.response`` and PIPELINE-1 §10's
        ``ovos.pipeline.<pipeline_id>.intents.list.response``. Because it
        delegates to :meth:`reply`, the §5.2 routing reversal and the §4
        session preservation both apply, which is exactly what lets an asker
        correlate ``<request>.response`` against an outstanding request in
        the same ``session`` (§5.4).

        Args:
            data: payload of the response (``D'``); ``None`` → ``{}``.
            context: optional context keys overlaid before the §5.2 swap.

        Returns:
            A new Message whose ``type`` is ``self.msg_type + ".response"``.
        """
        return self.reply(self.msg_type + ".response", data, context)
