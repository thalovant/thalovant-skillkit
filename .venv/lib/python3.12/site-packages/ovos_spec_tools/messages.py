"""Canonical OVOS-spec bus-message topics and the legacy↔``ovos.*`` bridge.

Specs implemented
-----------------
This module is the vocabulary and migration map for the OVOS bus-namespace
move from the Mycroft topics to the ``ovos.*`` namespace. Each
:class:`SpecMessage` member names a topic an OVOS specification defines, and
is tied to its owning spec section in the per-member comments below:

- **OVOS-PIPELINE-1** — §8 handler-lifecycle trio
  (``ovos.intent.handler.{start,complete,error}``) and §9 utterance-layer
  topics (``ovos.utterance.{handle,speak,handled,cancelled}``,
  ``ovos.intent.{matched,unmatched}``);
- **OVOS-INTENT-4** — registration / deregistration / enable-disable /
  introspection topics (§§5–8, §10);
- **OVOS-STOP-1** — §4.2 ping/pong and §5 global-stop broadcast
  (``ovos.stop.*``);
- **OVOS-AUDIO-IN-1** — listener lifecycle signals (``ovos.listener.*``).
  AUDIO-IN-1 §6.1–§6.4 mandates ``ovos.listener.record.started`` /
  ``.record.ended`` / ``ovos.listener.sleep`` / ``ovos.listener.awoken``;
- **OVOS-SESSION-2** — §2.7 defines no bus topic; session state converges
  only by start-up derivation and runtime adoption, both already carried by
  the OVOS-MSG-1 arrival machinery;
- **OVOS-CONVERSE-1** — the active-handler introspection pair
  (``ovos.converse.active.list`` / ``.response`` §6.1) and the §6.2 poll pair
  (``ovos.converse.ping`` / ``ovos.converse.pong``);
- **OVOS-PERSONA-1** — the §11 bus surface (``ovos.persona.{query,answer,list,
  list.response,register,deregister,activated,dismissed}``);
- **OVOS-FALLBACK-1** — fallback registry topics (``ovos.fallback.{register,
  deregister}`` §3) and the §6.1/§9 poll pair (``ovos.fallback.ping`` /
  ``ovos.fallback.pong``);
- **OVOS-COMMON-QUERY-1** — the wants-to-answer poll
  (``ovos.common_query.{ping,pong}`` §6);
- **OVOS-TRANSFORM-1** — §6 introspection: six static query/response pairs
  ``ovos.transformer.<chain>.list`` / ``.response`` (audio/utterance/metadata/
  intent/dialog/tts), plus the cancellation terminal ``ovos.utterance.cancelled``
  (§8.2, "defined here");
- **OVOS-OCP-1** — the §4 Virtual Media Player bus surface under the reserved
  ``ovos.common_play.*`` prefix (play/search, the transport controls, and the
  player/media/track state reports);
- **OVOS-AUDIO-1** — the audio **output** service bus surface (§7),
  mandated. Two rendering modes (``ovos.utterance.speak.b64``
  §3.4 → ``ovos.audio.speech`` §4.3 for remote clients); the playback model
  (``ovos.audio.queue`` §4.1 scheduled sounds, ``ovos.audio.play_sound`` §4.2
  instant sounds); the output-lifecycle signals (``ovos.audio.output.started``
  / ``.output.ended`` §5.1/§5.2); the speaking-status query
  (``ovos.audio.is_speaking`` §5.3); stop integration (``ovos.audio.stop``
  §6); and the listen-flag mic re-open (``ovos.mic.listen`` §4.4).

Why an enum
-----------
Referencing ``SpecMessage.SPEAK`` instead of the raw
``"ovos.utterance.speak"`` makes downstream code self-documenting: a
``SpecMessage`` member is provably spec-defined, while a bare string is
visibly legacy or implementation-specific. The enum is the *vocabulary* half
of the migration; :data:`MIGRATION_MAP` is the *rename* half.

The legacy↔``ovos.*`` bridge (``MIGRATION_MAP`` / :class:`NamespaceTranslator`)
-------------------------------------------------------------------------------
``MIGRATION_MAP`` maps each legacy topic to the ``SpecMessage`` that replaces
it. The bus dual-emit (``ovos-bus-client``'s ``MessageBusClient`` and
``ovos_utils.fakebus.FakeBus``, both driven by :class:`NamespaceTranslator`)
mirrors an emission onto its counterpart topic so a consumer still subscribed
to the legacy name during the migration window keeps receiving the event. The
receive side deduplicates the mirror (see
:meth:`NamespaceTranslator.new_mirror_guard`) so a handler subscribed to both
names runs once.

Payload translation, not verbatim mirroring. Some renames are *payload
compatible* (the legacy and spec topics carry the same ``data`` shape) and the
mirror forwards the payload unchanged. Others are *shape-changing* renames
(the handler trio, the INTENT-4 management topics): for those, forwarding the
producer's payload verbatim would hand a legacy-only consumer spec-shaped
``data`` it cannot read. :data:`MIGRATION_PAYLOAD_TRANSFORMS` therefore pairs
each shape-changing topic with two pure functions and
:meth:`NamespaceTranslator.translate_payload` applies the right one per
direction, so the mirrored payload is in the **recipient's** shape. Several
transforms are **best-effort / lossy** (a field that does not exist in the
other shape is synthesized or dropped); each lossy case is documented at
:data:`MIGRATION_PAYLOAD_TRANSFORMS`. The "legacy consumers keep working
without code changes" guarantee is therefore scoped: it holds outright for
payload-compatible renames, and holds *best-effort* (with documented loss) for
the shape-changing ones.

Two renames stay out of the map entirely because no per-topic payload
transform can bridge them: the OVOS-INTENT-4 *registration* consolidation (an
N→1 restructure the stateless bus cannot synthesize) and the per-skill
placeholder ``ovos.stop.*`` ping topics (not static strings). Both are
documented at :data:`MIGRATION_MAP`.

Note on dual-emit and MSG-1 §5.4. The dual-emit/mirror-window behaviour is a
non-normative **implementation policy** of this migration tooling, not a
spec-mandated mechanism. No OVOS specification mandates dual-emit, and
OVOS-MSG-1 §5.4 explicitly disavows any host-side correlation/bookkeeping of
the kind a mirror window resembles; the window here is a pragmatic dedup
heuristic for the migration period, scoped to :class:`NamespaceTranslator`.

Out of enum / map scope (OVOS-MSG-1 §2.1.1 runtime-assembled topics)
--------------------------------------------------------------------
Topics whose ``type`` is assembled at runtime from identifiers are neither
enum members nor static-mappable: ``ovos.pipeline.<pipeline_id>.intents.list``
(PIPELINE-1 §10), the ``<skill_id>:<intent_name>`` dispatch topic
(PIPELINE-1 §7), the per-skill ``<skill_id>.stop.ping`` / ``<skill_id>.stop``
placeholders (STOP-1), the CONVERSE-1 §6.3
``<skill_id>:{converse,response}`` dispatch, the FALLBACK-1 §7
``<skill_id>:fallback`` dispatch, and the COMMON-QUERY-1 §7/§3
``<skill_id>:common_query`` / ``<skill_id>.common_query.response`` /
``<pipeline_id>:common_query``.

Spec-referenced but NOT spec-defined (kept OUT of the enum)
----------------------------------------------------------
``ovos.session.update_default`` and ``ovos.session.start`` are used by
``ovos-bus-client`` but no specification defines them — SESSION-2 §1 explicitly
defers session-lifecycle observability topics — so they are implementation
internals and legitimately remain bare strings in the bus client.
``ovos.context.set`` / ``.unset`` / ``.clear`` appear only as a stray reference
in OVOS-TRANSFORM-1 (mis-citing "OVOS-CONTEXT-1 §5"); OVOS-CONTEXT-1 §5 in fact
defines exactly three mutation pathways, none of them a bus topic (§7: "This
specification defines no bus topic"), so no ``ovos.context.*`` topic is
spec-defined.
"""
import json as _json
import re as _re
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from ovos_spec_tools.intent_topics import intent_topic_counterpart


class SpecMessage(str, Enum):
    """Canonical ``ovos.*`` bus topics defined by the OVOS specifications.

    Every member's value is a literal topic string a specification assigns to
    the ``ovos.*`` namespace; the per-member comments cite the owning spec
    section. Members subclass ``str`` (OVOS-MSG-1 §2.1 topics are strings) so
    they can be used directly as topics::

        bus.on(SpecMessage.SPEAK, handler)
        bus.emit(Message(SpecMessage.UTTERANCE, {...}))

    Absence of a topic here does not imply it is not spec-defined; topics from
    specs not yet catalogued are flagged *provisional* in the comments.
    """

    def __str__(self) -> str:
        # Behave like py3.11 ``StrEnum``: ``str()`` / f-string yield the bare
        # topic ("ovos.utterance.speak"), not "SpecMessage.SPEAK", so a member
        # is interchangeable with the OVOS-MSG-1 §2.1 wire ``type`` string.
        return self.value

    # --- OVOS-PIPELINE-1 §9 utterance-layer topics ---
    #: §9.1 — utterance-layer entry point; producer→orchestrator (also the
    #: AUDIO-IN-1 §5 emission target).
    UTTERANCE = "ovos.utterance.handle"
    #: §9.6 — natural-language output exit point; handler→output layer.
    SPEAK = "ovos.utterance.speak"
    #: §9.5 — universal end-marker, exactly one per entry Message.
    UTTERANCE_HANDLED = "ovos.utterance.handled"
    #: OVOS-TRANSFORM-1 §8.2 — terminal event, utterance cancelled by a
    #: transformer ("new; defined here"); MUST be followed by UTTERANCE_HANDLED.
    #: PIPELINE-1 §6.4 references it as a terminal outcome but does not own it.
    UTTERANCE_CANCELLED = "ovos.utterance.cancelled"
    #: §9.2 — match notification (NOT a dispatch), broadcast.
    INTENT_MATCHED = "ovos.intent.matched"
    #: §9.3 — emitted when pipeline iteration claimed no match, broadcast.
    INTENT_UNMATCHED = "ovos.intent.unmatched"
    # §8 handler-lifecycle trio — orchestrator-emitted around each dispatch,
    # each ``forward``-derived from the dispatch Message (§8, MSG-1 §5.1).
    INTENT_HANDLER_START = "ovos.intent.handler.start"      # §8.1 before invoke
    INTENT_HANDLER_COMPLETE = "ovos.intent.handler.complete"  # §8.1 normal return
    INTENT_HANDLER_ERROR = "ovos.intent.handler.error"       # §8.1 raised/timeout

    # --- OVOS-INTENT-4 registration / management / introspection topics ---
    #: §5 — register a keyword intent (vocab descriptors inlined, §5.1/§5.2).
    INTENT_REGISTER_KEYWORD = "ovos.intent.register.keyword"
    #: §6 — register a template intent.
    INTENT_REGISTER_TEMPLATE = "ovos.intent.register.template"
    #: §8.2 — remove one intent (the (skill_id, intent_name[, lang]) triple).
    INTENT_DEREGISTER = "ovos.intent.deregister"
    #: §8.5 — re-arm a previously disabled intent.
    INTENT_ENABLE = "ovos.intent.enable"
    #: §8.5 — suppress an intent without removing its definition.
    INTENT_DISABLE = "ovos.intent.disable"
    #: §7 — register an ``.entity`` value-set hint.
    ENTITY_REGISTER = "ovos.entity.register"
    #: §8.3 — remove one entity.
    ENTITY_DEREGISTER = "ovos.entity.deregister"
    #: §8.4 — remove everything owned by a skill_id.
    SKILL_DEREGISTER = "ovos.skill.deregister"
    #: §10.1 — query the orchestrator-owned manifest (observer→orchestrator).
    INTENT_LIST = "ovos.intent.list"
    #: §10.1 — the ``.response`` reply to ``ovos.intent.list`` (MSG-1 §5.3).
    INTENT_LIST_RESPONSE = "ovos.intent.list.response"
    #: §10.2 — query the full definition of one intent.
    INTENT_DESCRIBE = "ovos.intent.describe"
    #: §10.2 — the ``.response`` reply to ``ovos.intent.describe`` (MSG-1 §5.3).
    INTENT_DESCRIBE_RESPONSE = "ovos.intent.describe.response"

    # --- OVOS-STOP-1 stop cascade topics ---
    #: §4.2 — broadcast stoppability query. The per-skill ``<skill_id>.stop.ping``
    #: placeholder form is NOT static-mappable (see MIGRATION_MAP).
    STOP_PING = "ovos.stop.ping"
    #: §4.2 — shared stoppability reply topic; pong is ``reply``-derived (MSG-1 §5.2).
    STOP_PONG = "ovos.stop.pong"
    #: §5.3 — universal stop broadcast; ``ovos.stop.*`` namespace is reserved by STOP-1.
    STOP = "ovos.stop"

    # --- OVOS-AUDIO-1 audio-OUTPUT service bus surface (§7, mandated) ---
    # Defined by OVOS-AUDIO-1 (audio-out.md), NOT by AUDIO-IN-1.
    #: §3.4 — remote-client rendering mode; same TTS pipeline as ``SPEAK`` but
    #: emits ``ovos.audio.speech`` (b64) instead of enqueueing local playback.
    SPEAK_B64 = "ovos.utterance.speak.b64"
    #: §4.3 — synthesised audio (base64) emitted for a ``SPEAK_B64`` Message; a
    #: bridge relays it to the remote client; audio-output → broadcast.
    AUDIO_SPEECH = "ovos.audio.speech"
    #: §4.1 — queue a sound for sequential (FIFO) scheduled playback; any → audio.
    AUDIO_QUEUE = "ovos.audio.queue"
    #: §4.2 — fire-and-forget instant sound, played immediately over the queue;
    #: any → audio.
    AUDIO_PLAY_SOUND = "ovos.audio.play_sound"
    #: §6 — stop audio output: clear the scheduled queue and terminate playback;
    #: any → audio.
    AUDIO_STOP = "ovos.audio.stop"
    #: §5.3 — query whether the audio output service is currently speaking; the
    #: service answers ``{"speaking": bool}`` (§7 names no distinct response
    #: topic, so the reply is ``reply``-derived, MSG-1 §5.2); any → audio.
    AUDIO_IS_SPEAKING = "ovos.audio.is_speaking"
    #: §5.1 — playback session started (idle→active); audio-output → broadcast.
    AUDIO_OUTPUT_STARTED = "ovos.audio.output.started"
    #: §5.2 — playback session ended (queue empty, last item done); audio-output
    #: → broadcast.
    AUDIO_OUTPUT_ENDED = "ovos.audio.output.ended"
    #: §4.4 — re-open the mic after a ``listen: true`` item; audio-output →
    #: broadcast.
    MIC_LISTEN = "ovos.mic.listen"

    # --- OVOS-AUDIO-IN-1 listener lifecycle signals (§6, mandated) ---
    #: §6.1 — voice-command capture began; audio-input → broadcast.
    LISTENER_RECORD_STARTED = "ovos.listener.record.started"
    #: §6.2 — voice-command capture ended; audio-input → broadcast.
    LISTENER_RECORD_ENDED = "ovos.listener.record.ended"
    #: §6.3 — controller → audio-input: enter sleep mode and suspend capture.
    LISTENER_SLEEP = "ovos.listener.sleep"
    #: §6.4 — left sleep mode (sleep→awake transition); audio-input → broadcast.
    LISTENER_AWOKEN = "ovos.listener.awoken"

    # --- OVOS-SESSION-1/SESSION-2 session lifecycle topics ---
    # SESSION-2 §2.7 defines no topic on which any participant pushes a
    # session at another; convergence is by start-up derivation and runtime
    # adoption only, both already covered by the arrival/derivation topics
    # elsewhere in this enum. (``ovos.session.update_default`` and
    # ``ovos.session.start`` are NOT spec-defined — see module note — and
    # stay out of this enum; SESSION-2 §1 explicitly defers lifecycle topics.)
    #: SESSION-1 §2.5 — consumer drops a Message due to malformed carrier
    #: (context.session is not a JSON object); data carries msg_type and reason.
    SESSION_REJECTED = "ovos.session.rejected"

    # --- OVOS-CONVERSE-1 §6.1 active-handler introspection ---
    # The §6.2 poll pair below is static dotted, non-dispatch (§6.2 table);
    # only the §6.3 ``<skill_id>:{converse,response}`` dispatches are
    # runtime-templated (MSG-1 §2.1.1) and so are NOT static enum members.
    #: §6.1 — observer→orchestrator: snapshot ``session.converse_handlers``.
    CONVERSE_ACTIVE_LIST = "ovos.converse.active.list"
    #: §6.1 — the ``.response`` reply carrying ``{converse_handlers}`` (MSG-1 §5.3).
    CONVERSE_ACTIVE_LIST_RESPONSE = "ovos.converse.active.list.response"
    #: §6.2 — converse plugin's broadcast poll for the round; candidacy is
    #: decided by ``session.converse_handlers`` membership, not by topic.
    CONVERSE_PING = "ovos.converse.ping"
    #: §6.2 — candidate's poll reply ``{skill_id, result, error_code?}``.
    CONVERSE_PONG = "ovos.converse.pong"

    # --- OVOS-PERSONA-1 §11 bus surface ---
    #: §8.5 — out-of-band query to the active persona; any → persona.
    PERSONA_QUERY = "ovos.persona.query"
    #: §8.5 — the query response; persona → any component.
    PERSONA_ANSWER = "ovos.persona.answer"
    #: §8.7 — enumerate supported persona identities; any → persona.
    PERSONA_LIST = "ovos.persona.list"
    #: §8.7 — the ``.response`` supported-identity listing (MSG-1 §5.3).
    PERSONA_LIST_RESPONSE = "ovos.persona.list.response"
    #: §9 — register a persona at runtime; any → persona.
    PERSONA_REGISTER = "ovos.persona.register"
    #: §9 — deregister a persona at runtime; any → persona.
    PERSONA_DEREGISTER = "ovos.persona.deregister"
    #: §11 — a persona became active for a session (best-effort); persona → broadcast.
    PERSONA_ACTIVATED = "ovos.persona.activated"
    #: §11 — a persona was dismissed from a session (best-effort); persona → broadcast.
    PERSONA_DISMISSED = "ovos.persona.dismissed"

    # --- OVOS-FALLBACK-1 §9 bus surface ---
    # The §9 poll pair below is static dotted, broadcast/shared-reply; only
    # the §7 ``<skill_id>:fallback`` dispatch is runtime-templated
    # (MSG-1 §2.1.1) and so is NOT a static enum member.
    #: §3.1 — a skill registers itself as a fallback handler; skill → broadcast.
    FALLBACK_REGISTER = "ovos.fallback.register"
    #: §3.2 — a skill removes itself from the fallback registry; skill → broadcast.
    FALLBACK_DEREGISTER = "ovos.fallback.deregister"
    #: §6.1/§9 — one willingness query per round; fallback → all fallback skills.
    FALLBACK_PING = "ovos.fallback.ping"
    #: §6.1/§9 — claim or explicit decline, via ``reply``; skill → fallback.
    FALLBACK_PONG = "ovos.fallback.pong"

    # --- OVOS-COMMON-QUERY-1 §13 bus surface ---
    # The §7.1 ``<skill_id>:common_query`` / ``<skill_id>.common_query.response``
    # and the §3/§10 ``<pipeline_id>:common_query`` dispatch are runtime-templated
    # (MSG-1 §2.1.1) and so are NOT static enum members.
    #: §6.1 — the wants-to-answer poll broadcast; plugin → all skills.
    COMMON_QUERY_PING = "ovos.common_query.ping"
    #: §6.2 — a skill claims it can answer, ``reply``-derived (MSG-1 §5.2);
    #: skill → plugin.
    COMMON_QUERY_PONG = "ovos.common_query.pong"

    # --- OVOS-TRANSFORM-1 §6 introspection (broadcast query / scatter response) ---
    # Six concrete static query/response pairs (one per §3 transformer chain);
    # the spec enumerates them, it does NOT define a templated
    # ``ovos.transformer.<type>.list`` pattern.
    #: §6/§3.1 — list loaded audio transformers; any → broadcast.
    TRANSFORMER_AUDIO_LIST = "ovos.transformer.audio.list"
    #: §6/§3.1 — scatter ``.response`` of loaded audio transformers (MSG-1 §5.3).
    TRANSFORMER_AUDIO_LIST_RESPONSE = "ovos.transformer.audio.list.response"
    #: §6/§3.2 — list loaded utterance transformers; any → broadcast.
    TRANSFORMER_UTTERANCE_LIST = "ovos.transformer.utterance.list"
    #: §6/§3.2 — scatter ``.response`` of loaded utterance transformers.
    TRANSFORMER_UTTERANCE_LIST_RESPONSE = "ovos.transformer.utterance.list.response"
    #: §6/§3.3 — list loaded metadata transformers; any → broadcast.
    TRANSFORMER_METADATA_LIST = "ovos.transformer.metadata.list"
    #: §6/§3.3 — scatter ``.response`` of loaded metadata transformers.
    TRANSFORMER_METADATA_LIST_RESPONSE = "ovos.transformer.metadata.list.response"
    #: §6/§3.4 — list loaded intent transformers; any → broadcast.
    TRANSFORMER_INTENT_LIST = "ovos.transformer.intent.list"
    #: §6/§3.4 — scatter ``.response`` of loaded intent transformers.
    TRANSFORMER_INTENT_LIST_RESPONSE = "ovos.transformer.intent.list.response"
    #: §6/§3.5 — list loaded dialog transformers; any → broadcast.
    TRANSFORMER_DIALOG_LIST = "ovos.transformer.dialog.list"
    #: §6/§3.5 — scatter ``.response`` of loaded dialog transformers.
    TRANSFORMER_DIALOG_LIST_RESPONSE = "ovos.transformer.dialog.list.response"
    #: §6/§3.6 — list loaded TTS transformers; any → broadcast.
    TRANSFORMER_TTS_LIST = "ovos.transformer.tts.list"
    #: §6/§3.6 — scatter ``.response`` of loaded TTS transformers.
    TRANSFORMER_TTS_LIST_RESPONSE = "ovos.transformer.tts.list.response"

    # --- OVOS-OCP-1 §4 Virtual Media Player bus surface ---
    # The ``ovos.common_play.*`` prefix is reserved by OCP-1 §4.1. The inline
    # ``…search.start`` / ``…search.end`` brackets (§4.2 prose) are not given
    # their own normative Message rows, so they are flagged, not enumerated.
    #: §4.2 — begin playback of a resolved result / queue.
    COMMON_PLAY_PLAY = "ovos.common_play.play"
    #: §4.2 — acquire candidate media for a phrase (pipeline discovery step).
    COMMON_PLAY_SEARCH = "ovos.common_play.search"
    #: §4.3 — now-playing → PAUSED.
    COMMON_PLAY_PAUSE = "ovos.common_play.pause"
    #: §4.3 — now-playing → PLAYING.
    COMMON_PLAY_RESUME = "ovos.common_play.resume"
    #: §4.3 — now-playing → STOPPED (an OVOS-STOP-1 subscriber, §7).
    COMMON_PLAY_STOP = "ovos.common_play.stop"
    #: §4.3 — advance the queue.
    COMMON_PLAY_NEXT = "ovos.common_play.next"
    #: §4.3 — retreat the queue.
    COMMON_PLAY_PREVIOUS = "ovos.common_play.previous"
    #: §4.3 — move the position within now-playing.
    COMMON_PLAY_SEEK = "ovos.common_play.seek"
    #: §4.4 — announce the §3.1 player-state value; player → broadcast.
    COMMON_PLAY_PLAYER_STATE = "ovos.common_play.player.state"
    #: §4.4 — announce the §3.2 media-state value; player → broadcast.
    COMMON_PLAY_MEDIA_STATE = "ovos.common_play.media.state"
    #: §4.4 — announce now-playing track transitions; player → broadcast.
    COMMON_PLAY_TRACK_STATE = "ovos.common_play.track.state"

    # --- SCHEDULER-1 §4 event-scheduling bus surface ---
    #: §4.1 — schedule a future/recurring event; client → scheduler.
    SCHEDULER_SCHEDULE = "ovos.scheduler.schedule"
    #: §4.1 — acknowledge/report a scheduled event; scheduler → client.
    SCHEDULER_SCHEDULE_RESPONSE = "ovos.scheduler.schedule.response"
    #: §4.1 — cancel a previously scheduled event; client → scheduler.
    SCHEDULER_CANCEL = "ovos.scheduler.cancel"
    #: §4.1 — acknowledge event cancellation; scheduler → client.
    SCHEDULER_CANCEL_RESPONSE = "ovos.scheduler.cancel.response"
    #: §4.1 — query a single scheduled event; client → scheduler.
    SCHEDULER_GET = "ovos.scheduler.get"
    #: §4.1 — return the queried scheduled event; scheduler → client.
    SCHEDULER_GET_RESPONSE = "ovos.scheduler.get.response"
    #: §4.1 — list all scheduled events; client → scheduler.
    SCHEDULER_LIST = "ovos.scheduler.list"
    #: §4.1 — return the scheduled-event list; scheduler → client.
    SCHEDULER_LIST_RESPONSE = "ovos.scheduler.list.response"
    #: §5.4 — signal the scheduler is initialized and ready; scheduler →
    #: broadcast.
    SCHEDULER_READY = "ovos.scheduler.ready"
    #: §4.3 — report a scheduled event that fired late/was missed; scheduler
    #: → broadcast.
    SCHEDULER_MISSED = "ovos.scheduler.missed"


#: Legacy (Mycroft-era) topic -> the :class:`SpecMessage` that supersedes it.
#: This is the single source of truth for the legacy↔``ovos.*`` renames that
#: the bus bridges. ``NamespaceTranslator`` reads it (and its reverse,
#: :data:`SPEC_TO_LEGACY`) to pick the counterpart topic; it then translates the
#: payload into the recipient's shape via :data:`MIGRATION_PAYLOAD_TRANSFORMS`
#: (identity for payload-compatible renames), so a consumer still on the legacy
#: topic during the migration window receives ``data`` it can read.
#:
#: Two kinds of entry live here:
#:
#: * **Payload-compatible renames** — legacy and spec topics carry the same
#:   ``data`` shape; the mirror forwards the payload unchanged (identity
#:   transform). Most entries are of this kind.
#: * **Shape-changing renames** — the INTENT-4 management topics
#:   (``detach_intent``, ``enable_intent``/``disable_intent``) change the
#:   payload shape across the rename. For these the bridge does NOT forward the
#:   payload verbatim: :data:`MIGRATION_PAYLOAD_TRANSFORMS` carries a
#:   best-effort, sometimes lossy transform pair (documented there) that
#:   reshapes the payload per direction.
#:
#: Deliberate exclusions (registration consolidation, per-skill stop ping
#: placeholders) are documented at the bottom — no per-topic payload transform
#: can bridge them. The PIPELINE-1 §8 handler-lifecycle trio is also excluded:
#: it is orchestrator-owned (the orchestrator emits the spec topics directly;
#: the skill framework keeps the legacy ones as a private done-signal), so it is
#: deliberately NOT migrated.
MIGRATION_MAP: Dict[str, SpecMessage] = {
    # --- PIPELINE-1 §9 utterance layer (payload-compatible 1:1 renames) ---
    "recognizer_loop:utterance": SpecMessage.UTTERANCE,        # PIPELINE-1 §9.1
    "speak": SpecMessage.SPEAK,                                # PIPELINE-1 §9.6
    # --- AUDIO-1 §5.1/§5.2/§4.4 audio-output signals (payload-compatible
    #     1:1 renames) ---
    "recognizer_loop:audio_output_start": SpecMessage.AUDIO_OUTPUT_STARTED,  # AUDIO-1 §5.1
    "recognizer_loop:audio_output_end": SpecMessage.AUDIO_OUTPUT_ENDED,      # AUDIO-1 §5.2
    "mycroft.mic.listen": SpecMessage.MIC_LISTEN,             # AUDIO-1 §4.4
    # --- AUDIO-1 §3.4/§4.1/§4.2/§5.3/§6 audio-output bus surface
    #     (payload-compatible 1:1 renames; legacy handler names verified against
    #     ovos-audio register_handlers) ---
    "speak:b64_audio": SpecMessage.SPEAK_B64,                 # AUDIO-1 §3.4 {utterance, listen}
    "speak:b64_audio.response": SpecMessage.AUDIO_SPEECH,     # AUDIO-1 §4.3 {audio, listen, ...}
    "mycroft.audio.queue": SpecMessage.AUDIO_QUEUE,           # AUDIO-1 §4.1 {uri}
    "mycroft.audio.play_sound": SpecMessage.AUDIO_PLAY_SOUND,  # AUDIO-1 §4.2 {uri}
    "mycroft.audio.speak.status": SpecMessage.AUDIO_IS_SPEAKING,  # AUDIO-1 §5.3 (query, empty)
    "mycroft.audio.speech.stop": SpecMessage.AUDIO_STOP,     # AUDIO-1 §6 (empty)
    # --- AUDIO-IN-1 §6 listener lifecycle (payload-compatible renames) ---
    "recognizer_loop:record_begin": SpecMessage.LISTENER_RECORD_STARTED,  # AUDIO-IN-1 §6.1
    "recognizer_loop:record_end": SpecMessage.LISTENER_RECORD_ENDED,      # AUDIO-IN-1 §6.2
    "recognizer_loop:sleep": SpecMessage.LISTENER_SLEEP,     # AUDIO-IN-1 §6.3
    "mycroft.awoken": SpecMessage.LISTENER_AWOKEN,           # AUDIO-IN-1 §6.4
    # NOTE: the PIPELINE-1 §8 handler-lifecycle trio is intentionally NOT
    # migrated. It is orchestrator-owned — the orchestrator emits the spec
    # ``ovos.intent.handler.*`` directly, while the skill framework keeps
    # emitting the legacy ``mycroft.skill.handler.*`` as a private done-signal.
    # It is also a shape-changing (not payload-compatible) event, so bridging it
    # would both double-emit the spec trio and reshape the payload. The two
    # namespaces are kept separate by design (PIPELINE-1 §8 / §11).
    # --- STOP-1 (1:1 renames) ---
    "skill.stop.pong": SpecMessage.STOP_PONG,   # STOP-1 §4.2 stoppability reply
    "mycroft.stop": SpecMessage.STOP,           # STOP-1 §5.3 universal stop broadcast
    # --- FALLBACK-1 §3.1/§3.2/§6.1 (payload-compatible 1:1 renames) ---
    # The poll pair belongs here as much as the registry topics do. Every
    # shipped FallbackSkill subscribes to the legacy ping alone, so the day a
    # core emits the canonical ovos.fallback.ping the wire twin is the only
    # thing that still reaches them; without this entry there is no twin and
    # fallback stops answering with nothing in the logs to say so.
    #
    # The pong is the PIPELINE-1 §4.5 shape on both names -- ovos-workshop's
    # FallbackSkill already emits {skill_id, can_handle} -- so the mirror
    # forwards it unchanged. Duplicate delivery is harmless besides: the
    # fallback plugin collects responding skill_ids only to test membership
    # against a registry snapshot taken before the poll, so a repeated
    # skill_id collapses to one entry in the handler ordering and one
    # dispatch, and ordering comes from registered priority rather than
    # arrival order. The §6.1 round and session guards admit the mirror
    # because it carries the same utterance_id and session_id; a guard strict
    # enough to reject it would also reject the original wherever only the
    # legacy topic is subscribed.
    "ovos.skills.fallback.register": SpecMessage.FALLBACK_REGISTER,      # §3.1
    "ovos.skills.fallback.deregister": SpecMessage.FALLBACK_DEREGISTER,  # §3.2
    "ovos.skills.fallback.ping": SpecMessage.FALLBACK_PING,              # §6.1
    "ovos.skills.fallback.pong": SpecMessage.FALLBACK_PONG,              # §6.1
    # --- PIPELINE-1 §9.3 intent outcome (1:1 rename) ---
    "complete_intent_failure": SpecMessage.INTENT_UNMATCHED,
    # --- INTENT-4 §8 intent management ---
    # detach_intent / enable_intent / disable_intent are SHAPE-CHANGING renames
    # (legacy munged/partial payload vs spec {skill_id, intent_name, lang}) —
    # reshaped per direction by MIGRATION_PAYLOAD_TRANSFORMS (best-effort).
    "detach_intent": SpecMessage.INTENT_DEREGISTER,            # §8.2 (shape-changing)
    "detach_skill": SpecMessage.SKILL_DEREGISTER,              # §8.4 (payload-compatible: {skill_id})
    "mycroft.skill.enable_intent": SpecMessage.INTENT_ENABLE,  # §8.5 (shape-changing)
    "mycroft.skill.disable_intent": SpecMessage.INTENT_DISABLE,  # §8.5 (shape-changing)
    #
    # ---- DELIBERATE EXCLUSION 1: INTENT-4 §5–§7 *registration* ----
    # ovos.intent.register.keyword / .register.template / ovos.entity.register
    # are NOT mappable, because the rename is not 1:1. Adapt emits N legacy
    # `register_vocab` messages + one `register_intent` (the intent references
    # its vocab by name); INTENT-4 §5.2 consolidates all of that into ONE
    # register.keyword Message with the vocab descriptors INLINED (§5.1). A
    # transparent bus bridge cannot synthesize that N→1 consolidation — it would
    # have to buffer and join messages it has no schema for — so registration
    # requires INTENT-4 *adoption* in the producer (ovos_workshop/intents.py) and
    # consumers (the pipeline plugins), not a static topic rename here.
    #
    # ---- DELIBERATE EXCLUSION 2: STOP-1 per-skill ping placeholders ----
    # The legacy stoppability handshake used per-skill topics shaped
    # `{skill_id}.stop.ping` / `{skill_id}.stop` (OVOS-MSG-1 §2.1.1 runtime-
    # assembled topics). STOP-1 §4.2/§5.3 replace them with the single broadcast
    # topics ovos.stop.ping / ovos.stop. A `{skill_id}.*` placeholder is not a
    # static string, so it cannot be a dict key; the migration there is handled by
    # producers/consumers subscribing on both forms, not by this map.
}

#: Reverse index: spec topic (plain ``str``) -> the legacy topic it replaces.
#: Derived from :data:`MIGRATION_MAP`; keys are ``SpecMessage.value`` strings so
#: lookups work with either an enum member (via its ``str`` value) or a raw topic.
SPEC_TO_LEGACY: Dict[str, str] = {v.value: k for k, v in MIGRATION_MAP.items()}


# ---------------------------------------------------------------------------
# Per-topic payload translation
# ---------------------------------------------------------------------------
# A migrating topic that is a *payload-compatible* rename carries the same
# ``data`` shape on both names, so the mirror forwards the payload unchanged.
# A *shape-changing* rename does not: the legacy and spec topics describe the
# same event with different fields, so forwarding the producer's payload
# verbatim would hand the recipient ``data`` in the wrong shape. For those, the
# bridge reshapes the payload with a pair of pure functions.

#: One ``(legacy_to_spec, spec_to_legacy)`` transform pair. Each function takes
#: a payload ``dict`` and returns a NEW payload ``dict`` in the other shape; it
#: must never mutate its input. The pair is keyed by the **legacy** topic in
#: :data:`MIGRATION_PAYLOAD_TRANSFORMS`.
PayloadTransform = Callable[[Dict[str, Any]], Dict[str, Any]]


def _identity(data: Dict[str, Any]) -> Dict[str, Any]:
    """Payload-compatible default: copy the payload through unchanged."""
    return dict(data)


# --- detach_intent ↔ ovos.intent.deregister (INTENT-4 §8.2) ---
# Legacy: {"intent_name": "<skill_id>:<name>"} (the munged form — see
#   ovos_workshop/intents.py::detach_intent).
# Spec:   {"skill_id", "intent_name", "lang"?}  (§8.2; lang optional).
# CLEANLY BIDIRECTIONAL on skill_id/intent_name:
#   spec->legacy joins "<skill_id>:<intent_name>"; legacy->spec splits on the
#   FIRST ":" (MSG-1 §2.1.1: skill_id must not contain ":").
# LOSSY: legacy carries no ``lang`` -> legacy->spec omits it (spec §8.2 allows
#   an omitted lang = "all languages"); spec->legacy drops ``lang``.

def _detach_legacy_to_spec(data: Dict[str, Any]) -> Dict[str, Any]:
    munged = data.get("intent_name", "")
    if ":" in munged:
        skill_id, intent_name = munged.split(":", 1)
        return {"skill_id": skill_id, "intent_name": intent_name}
    # No separator -> cannot split; best-effort pass the whole as intent_name.
    return {"intent_name": munged} if munged else {}


def _detach_spec_to_legacy(data: Dict[str, Any]) -> Dict[str, Any]:
    skill_id = data.get("skill_id", "")
    intent_name = data.get("intent_name", "")
    if skill_id:
        return {"intent_name": f"{skill_id}:{intent_name}"}
    # No skill_id to join -> emit the bare intent_name (best-effort).
    return {"intent_name": intent_name}


# --- mycroft.skill.{enable,disable}_intent ↔ ovos.intent.{enable,disable}
#     (INTENT-4 §8.5) ---
# Legacy: {"intent_name": "<name>"}            (no skill_id, no lang)
# Spec:   {"skill_id", "intent_name", "lang"?}  (§8.5)
# LOSSY: legacy->spec CANNOT recover ``skill_id`` (absent in the legacy
#   payload) -> it is OMITTED, and ``lang`` likewise (spec treats an omitted
#   lang as "all languages", §8.5). This is the documented limitation: a
#   legacy-sourced enable/disable bridged to the spec topic targets the intent
#   name without a skill scope; a consumer that needs skill scoping must obtain
#   it elsewhere (e.g. Message.context["skill_id"]). spec->legacy drops
#   skill_id/lang, keeping only intent_name.

def _toggle_legacy_to_spec(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "intent_name" in data:
        out["intent_name"] = data["intent_name"]
    # skill_id / lang not recoverable from the legacy payload -> omitted.
    return out


def _toggle_spec_to_legacy(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "intent_name" in data:
        out["intent_name"] = data["intent_name"]
    # spec skill_id / lang have no legacy field -> dropped.
    return out


#: **legacy topic** -> ``(legacy_to_spec, spec_to_legacy)`` payload transforms.
#:
#: Only the SHAPE-CHANGING renames need an entry; every other migrating topic
#: is payload-compatible and uses the IDENTITY transform implicitly (see
#: :meth:`NamespaceTranslator.translate_payload`). Keyed by the legacy topic so
#: both :data:`MIGRATION_MAP` (legacy->spec) and :data:`SPEC_TO_LEGACY`
#: (spec->legacy) resolve to the same pair.
#:
#: Lossy cases (each documented at the transform above):
#:
#: * **detach_intent** — cleanly bidirectional on ``skill_id``/``intent_name``;
#:   ``lang`` is not present in the legacy payload.
#: * **enable/disable** — legacy carries neither ``skill_id`` nor ``lang``, so
#:   legacy->spec omits both (a legacy-sourced toggle has no skill scope in
#:   ``data``).
MIGRATION_PAYLOAD_TRANSFORMS: Dict[str, Tuple[PayloadTransform, PayloadTransform]] = {
    "detach_intent": (_detach_legacy_to_spec, _detach_spec_to_legacy),
    "mycroft.skill.enable_intent": (_toggle_legacy_to_spec, _toggle_spec_to_legacy),
    "mycroft.skill.disable_intent": (_toggle_legacy_to_spec, _toggle_spec_to_legacy),
}


#: OVOS-STOP-1 §2: a targeted stop is dispatched on the reserved intent_name
#: ``stop`` (the PIPELINE-1 ``<skill_id>:stop`` topic). ``stop`` is reserved —
#: no skill may register it (OVOS-INTENT-4 §5.3) — so ``<skill_id>:stop`` is
#: unambiguously that dispatch and bridges to the legacy ``<skill_id>.stop`` a
#: skill already honours. This is a *pattern* rename (per-skill), so it cannot
#: live in the static :data:`MIGRATION_MAP`; the counterpart is computed. The
#: bridge is one-directional (spec ``:stop`` → legacy ``.stop``): the reverse
#: ``<x>.stop`` form is ambiguous (``mycroft.stop`` etc.) and is covered by the
#: explicit :data:`MIGRATION_MAP` entries instead.
_STOP_DISPATCH_RE = _re.compile(r"^(?P<skill_id>[^:]+):stop$")


def _stop_dispatch_legacy(topic: str) -> Optional[str]:
    """Legacy ``<skill_id>.stop`` counterpart of a spec ``<skill_id>:stop``, else None."""
    m = _STOP_DISPATCH_RE.match(topic)
    return f"{m.group('skill_id')}.stop" if m else None


def migration_counterpart(topic: str) -> Optional[str]:
    """Return the other-namespace counterpart of a migrating topic, else ``None``.

    The bridge is symmetric: a legacy topic maps to its ``ovos.*`` replacement,
    and a spec topic maps back to the legacy name it replaces. This is the
    lookup the dual-emit (:meth:`NamespaceTranslator.counterpart_topics`) and
    the receive-side dedup (:meth:`NamespaceTranslator.new_mirror_guard`) both
    rest on.

    Args:
        topic: a bus topic string (legacy or ``ovos.*``).

    Returns:
        The counterpart topic as a plain ``str`` (a ``SpecMessage.value``, never
        the enum member itself), or ``None`` if ``topic`` does not migrate.
    """
    if topic in MIGRATION_MAP:
        # legacy -> spec; ``.value`` so the return is a plain str, not a member
        return MIGRATION_MAP[topic].value
    legacy = SPEC_TO_LEGACY.get(topic)  # spec -> legacy, or None when unmapped
    if legacy is not None:
        return legacy
    return _stop_dispatch_legacy(topic)  # spec <skill_id>:stop -> <skill_id>.stop


def mirror_counterpart(topic: str) -> Optional[str]:
    """Counterpart of ``topic`` for the receive-side mirror guard.

    A dual-emit pair reaches a subscriber on two topics, and the guard drops
    the second one. Two independent bridges produce such pairs:

    - the **namespace** bridge (legacy ↔ ``ovos.*``), whose pairing is
      :func:`migration_counterpart` — a static
      :data:`MIGRATION_MAP` lookup plus the computed ``<skill_id>:stop``
      pattern;
    - the **intent-topic** compat bridge (canonical ↔ ``.intent``-suffixed),
      whose pairing is
      :func:`~ovos_spec_tools.intent_topics.intent_topic_counterpart`.

    Intent dispatch topics are assembled at runtime from a ``skill_id`` and an
    ``intent_name``, so they cannot live in :data:`MIGRATION_MAP` — the pairing
    has to be computed. This function is the union, and the guard's single
    question.

    Args:
        topic: a bus topic string.

    Returns:
        The counterpart topic, or ``None`` when ``topic`` is in neither bridge.
    """
    counterpart = migration_counterpart(topic)
    if counterpart is not None:
        return counterpart
    return intent_topic_counterpart(topic)


class NamespaceTranslator:
    """Shared legacy↔``ovos.*`` bus-namespace migration logic (OVOS bus bridge).

    This is the shared **migration tooling** that ``ovos-bus-client``'s
    ``MessageBusClient`` and ``ovos_utils``' ``FakeBus`` both delegate to, so
    the real websocket bus and the test/satellite double behave identically. It
    carries no I/O and no config: the two direction flags are passed in (the
    caller reads env/config), keeping ``ovos-spec-tools`` dependency-free.

    .. note::

       **Non-normative implementation policy.** The dual-emit + mirror-window
       dedup behaviour described below is a pragmatic migration *policy* of
       this tooling, **not** a spec-mandated mechanism. No OVOS specification
       mandates dual-emit, and OVOS-MSG-1 §5.4 explicitly disavows any
       host-side correlation/bookkeeping of the kind a mirror window resembles.
       The window is a best-effort dedup heuristic scoped to the migration
       period and to this class; it is not part of any conformance surface.

    The bridge has two halves, matching the two halves of a dual-emit bus:

    - **send side** — :meth:`counterpart_topics` tells the bus which extra
      topic to mirror an emission onto, so a producer that emits only the spec
      topic still reaches legacy subscribers (and vice-versa); the bus calls
      :meth:`translate_payload` to reshape the mirrored payload into the
      recipient's shape (identity for payload-compatible renames, a best-effort
      transform for shape-changing ones — see
      :data:`MIGRATION_PAYLOAD_TRANSFORMS`).
    - **receive side** — :meth:`new_mirror_guard` lets a handler subscribed to
      *both* names run exactly once, by recognising the mirror re-delivery and
      dropping it. :meth:`has_mirror` is the cheap pre-check ("does this topic
      participate in *any* dual-emit bridge at all?"); :meth:`is_migrated`
      answers the narrower question of the **namespace** bridge only.

    Args:
        modernize: when ``True``, emitting a **legacy** topic also emits its
            ``ovos.*`` spec counterpart (carries the migration forward).
        emit_legacy: when ``True``, emitting an ``ovos.*`` **spec** topic also
            emits the legacy counterpart (keeps un-migrated consumers working).
        window: length, in ``clock`` seconds, of the **mirror window** — the
            interval within which a counterpart re-delivery of the same
            payload+context is treated as the mirror of a just-seen Message
            (and so suppressed) rather than a genuine second event.
    """

    def __init__(self, modernize: bool = True, emit_legacy: bool = True,
                 window: float = 1.0) -> None:
        self.modernize: bool = modernize
        self.emit_legacy: bool = emit_legacy
        self.window: float = window

    def counterpart_topics(self, msg_type: str) -> List[str]:
        """Extra topic(s) the bus should ALSO emit ``msg_type`` on (0 or 1).

        The result is the **send-side** half of the dual-emit: the bus emits the
        original Message, then re-emits — on each returned topic — the payload
        produced by :meth:`translate_payload` (reshaped into the counterpart
        topic's shape, identity for payload-compatible renames).

        Args:
            msg_type: the topic the producer asked to emit.

        Returns:
            ``[spec_topic]`` when ``msg_type`` is a legacy topic and
            ``modernize`` is set; ``[legacy_topic]`` when ``msg_type`` is a spec
            topic and ``emit_legacy`` is set; ``[]`` otherwise (non-migrating
            topic, or the relevant direction disabled). At most one entry — a
            topic has exactly one counterpart.
        """
        if self.modernize and msg_type in MIGRATION_MAP:
            return [MIGRATION_MAP[msg_type].value]
        if self.emit_legacy and msg_type in SPEC_TO_LEGACY:
            return [SPEC_TO_LEGACY[msg_type]]
        if self.emit_legacy:
            legacy = _stop_dispatch_legacy(msg_type)  # <skill_id>:stop -> <skill_id>.stop
            if legacy is not None:
                return [legacy]
        return []

    def translate_payload(self, from_topic: str, to_topic: str,
                          data: Dict[str, Any]) -> Dict[str, Any]:
        """Reshape ``data`` from ``from_topic``'s shape into ``to_topic``'s shape.

        This is the **payload half** of the bridge, the companion to
        :meth:`counterpart_topics`: when the bus mirrors an emission onto the
        counterpart topic, it calls this to translate the payload so a consumer
        on the counterpart topic receives ``data`` in *its* shape rather than
        the producer's.

        Direction is inferred from ``from_topic``:

        - ``from_topic`` is a **legacy** topic (in :data:`MIGRATION_MAP`) →
          apply the ``legacy_to_spec`` transform;
        - ``from_topic`` is a **spec** topic (in :data:`SPEC_TO_LEGACY`) →
          apply the ``spec_to_legacy`` transform.

        If the migrating topic has no entry in
        :data:`MIGRATION_PAYLOAD_TRANSFORMS` (a payload-compatible rename) the
        transform is the **identity** — a shallow copy of ``data`` unchanged.
        The same identity copy is returned when ``from_topic``/``to_topic`` are
        not a migrating pair at all, so the method is always safe to call.

        The transforms are pure: ``data`` is never mutated, and a NEW dict is
        always returned. Some transforms are **best-effort / lossy** — see
        :data:`MIGRATION_PAYLOAD_TRANSFORMS` for the per-topic loss notes.

        Args:
            from_topic: the topic the Message was emitted on (legacy or spec).
            to_topic: the counterpart topic the mirror is being emitted on. Used
                only to confirm direction; the transform is keyed off the legacy
                topic of the pair.
            data: the source Message's payload.

        Returns:
            A new payload ``dict`` in ``to_topic``'s shape.
        """
        data = data or {}
        # Resolve the legacy topic of this migrating pair (the transform key),
        # and which direction we are translating.
        if from_topic in MIGRATION_MAP:
            legacy_topic, direction = from_topic, 0  # legacy -> spec
        elif from_topic in SPEC_TO_LEGACY:
            legacy_topic, direction = SPEC_TO_LEGACY[from_topic], 1  # spec -> legacy
        else:
            # Not a migrating topic — nothing to translate, return a copy.
            return dict(data)
        transform = MIGRATION_PAYLOAD_TRANSFORMS.get(legacy_topic)
        if transform is None:
            # Payload-compatible rename: identity.
            return dict(data)
        return transform[direction](data)

    def is_migrated(self, topic: str) -> bool:
        """Whether ``topic`` participates in the **namespace** bridge.

        This is deliberately narrow: it covers ONLY the static legacy↔``ovos.*``
        namespace map (:data:`MIGRATION_MAP` / :data:`SPEC_TO_LEGACY`) plus the
        computed ``<skill_id>:stop`` dispatch pattern. It does **not** know
        about intent-topic pairs (canonical ↔ ``.intent``-suffixed), which are
        assembled at runtime and cannot live in a static map.

        Use it only when the narrow question is the one you mean — e.g. a bus
        keying a **per-handler** guard, which is the correct scope for the
        namespace bridge and the wrong scope for intent pairs (those need a
        per-topic-pair guard; see ``ovos-bus-client``'s ``_mirror_guard_for``).
        For the general "does this topic need :meth:`new_mirror_guard` at all?"
        question, use :meth:`has_mirror`.

        Args:
            topic: a bus topic string (legacy or ``ovos.*``).

        Returns:
            ``True`` if ``topic`` appears on either side of :data:`MIGRATION_MAP`
            — i.e. it has a namespace counterpart and a handler subscribed to
            both names should run it through :meth:`new_mirror_guard`.
        """
        return (topic in MIGRATION_MAP or topic in SPEC_TO_LEGACY
                or _stop_dispatch_legacy(topic) is not None)

    def has_mirror(self, topic: str) -> bool:
        """Whether ``topic`` participates in **any** dual-emit bridge.

        This is the general-purpose pre-check for :meth:`new_mirror_guard`: it
        is ``True`` exactly when :func:`mirror_counterpart` finds a counterpart,
        so it covers both bridges — the static **namespace** map
        (:meth:`is_migrated`) *and* the runtime **intent-topic** pairing
        (:func:`~ovos_spec_tools.intent_topics.intent_topic_counterpart`).

        A consumer that gates guard creation on :meth:`is_migrated` never
        engages the guard for a pure intent-topic pair, and a handler
        subscribed to both spellings runs twice. Gate on this method instead —
        but note the guard SCOPE differs per bridge (per-handler for the
        namespace bridge, per-topic-pair for intent topics), so a bus that
        keys guards must still branch on which bridge matched.

        Args:
            topic: a bus topic string.

        Returns:
            ``True`` if ``topic`` has a counterpart in either bridge.
        """
        return mirror_counterpart(topic) is not None

    def new_mirror_guard(self,
                         clock: Optional[Callable[[], float]] = None
                         ) -> Callable[[object], bool]:
        """Build a stateful ``is_mirror(message) -> bool`` for receive-side dedup.

        **Non-normative implementation policy** (migration tooling): the
        mirror-window dedup below is a pragmatic heuristic for the migration
        period, not a spec-mandated behaviour. OVOS-MSG-1 §5.4 disavows
        host-side correlation; this window is deliberately narrow and scoped to
        :class:`NamespaceTranslator` so it cannot be mistaken for one.

        Each call returns a **fresh closure with its own private ``seen`` state**,
        so one guard is created per handler (or per subscription) and guards do
        not cross-talk. The returned predicate answers: *is this Message the
        dual-emit mirror of one this guard already let through?* — and a bus
        that subscribes a handler to both namespaces calls it to run the handler
        exactly once.

        Mirror-window semantics:

        - A Message is a **mirror** iff a previously-seen Message had the same
          payload+context fingerprint, a **different** ``msg_type``, and that
          earlier type's :func:`mirror_counterpart` equals this one — i.e.
          it is the same event re-delivered on the counterpart topic. Mirrors
          return ``True`` (drop).
        - Two genuine events on the **same** topic are never suppressed
          (``prev[0] != mtype`` guards this): identical repeats on one topic
          are real repeats, not a mirror.
        - Entries older than ``window`` (per ``clock``) are evicted before each
          check, so a counterpart that arrives *after* the window is treated as
          a new event — the bridge only ever collapses a near-simultaneous
          dual-emit pair, never two deliberate emissions spaced apart.

        Args:
            clock: a monotonic seconds source; defaults to ``time.monotonic``,
                resolved **per call** so it stays monkeypatchable in tests.

        Returns:
            A predicate ``is_mirror(message) -> bool``. It is defensive: any
            message lacking ``msg_type`` / ``data`` / ``context``, or whose
            payload is not JSON-fingerprintable, returns ``False`` (never drop
            what we cannot prove is a mirror).
        """
        # Per-guard private state: fingerprint -> (msg_type, timestamp). Scoped
        # to this closure so distinct handlers never share dedup history.
        seen: Dict[str, Tuple[str, float]] = {}
        window = self.window

        def is_mirror(message: object) -> bool:
            try:
                mtype = message.msg_type  # type: ignore[attr-defined]
                # Fingerprint payload+context, order-independent (MSG-1 §6: key
                # order is not significant). ``default=str`` tolerates carrier
                # objects (e.g. Session) that are not natively JSON-encodable.
                fingerprint = _json.dumps([message.data, message.context],  # type: ignore[attr-defined]
                                          sort_keys=True, default=str)
            except Exception:
                # Not a Message-shaped object — cannot prove a mirror, so keep it.
                return False
            now = (clock or time.monotonic)()
            # Evict entries past the mirror window before matching.
            for key in [k for k, (_, ts) in seen.items() if now - ts >= window]:
                seen.pop(key, None)
            prev = seen.get(fingerprint)
            # Mirror iff same payload, DIFFERENT topic, and the topics are
            # registered counterparts of each other (a true dual-emit pair).
            if prev is not None and prev[0] != mtype \
                    and mirror_counterpart(prev[0]) == mtype:
                return True
            seen[fingerprint] = (mtype, now)
            return False

        return is_mirror
