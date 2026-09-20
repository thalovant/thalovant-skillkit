# Copyright 2020 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""An intent parsing service using the Adapt parser."""
import re
import time
from functools import lru_cache, wraps
from threading import Lock
from typing import List, Optional, Iterable, Union, Dict

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch, ConfidenceMatcherPipeline
from ovos_spec_tools import closest_lang, standardize_lang, SpecMessage, gate_satisfied, is_live
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_adapt.intent import open_intent_envelope, IntentBuilder
from ovos_adapt.engine import (IntentDeterminationEngine,
                                DomainIntentDeterminationEngine,
                                HierarchicalIntentDeterminationEngine)


def _entity_skill_id(skill_id):
    """Helper converting a skill id to the format used in entities.

    Normalizes a skill_id into the namespace prefix used for adapt
    entity_types: ``.`` and ``-`` (illegal/ambiguous in that namespace)
    are replaced with ``_``. This is byte-identical to the spelling
    ovos-workshop's ``alphanumeric_skill_id`` produces for realistic
    skill_ids, which is why every caller that registers, matches, or
    detaches skill-owned entities/regexes goes through this helper --
    it keeps the wire encoding consistent with the producer side.

    The transform is NOT injective: distinct skill_ids can normalize to
    the same string (``"foo-bar"`` and ``"foo.bar"`` both become
    ``"foo_bar"``), and even when they don't collide outright, one
    normalized id can be a prefix of another (``"foo_bar"`` / ``"foo_barz"``).
    ``detach_skill`` therefore does NOT rely on this helper being
    collision-free: it scopes detachment to the entity_types/regex groups
    actually recorded as owned by the skill (ownership tracked at
    registration time), falling back to a prefix match only for entries
    whose owner was never recorded (e.g. registered before ownership
    tracking existed, or via a bus message with no ``skill_id`` in its
    context).

    Arguments:
        skill_id (str): skill identifier

    Returns:
        (str) skill id on the format used by skill entities
    """
    skill_id = skill_id.replace('.', '_')
    skill_id = skill_id.replace('-', '_')
    return skill_id


def _legacy_skill_id(message, handler: str) -> Optional[str]:
    """Resolve the skill id of a legacy-wire message.

    The legacy topics carry no required payload identity, so
    ``message.context["skill_id"]`` is the attribution of the producing
    component.

    Args:
        message: the incoming bus message
        handler: name of the calling handler, for the warning message

    Returns:
        The skill id from the context, or ``None`` if it is missing.
    """
    skill_id = message.context.get("skill_id") if message.context else None
    payload_skill_id = message.data.get("skill_id")
    if payload_skill_id and skill_id and payload_skill_id != skill_id:
        LOG.warning(f"[{handler}] message.data['skill_id']={payload_skill_id!r} "
                    f"differs from message.context['skill_id']={skill_id!r}; "
                    f"using the context value on the legacy wire")
    return skill_id


def _spec_skill_id(message, handler: str) -> Optional[str]:
    """Resolve the skill an OVOS-INTENT-4 §§5-8 message acts on.

    The payload ``skill_id`` names the target: the skill whose registration
    is created, removed, suppressed or re-armed. ``context.skill_id`` names
    the source that emitted the message and is provenance only, so it is
    never substituted for the target. The two differ legitimately when a
    provisioning tool or a conflict-resolving skill acts on another skill's
    behalf, and that is never grounds for rejection (§3.2).

    Args:
        message: the incoming bus message
        handler: name of the calling handler, for the debug message

    Returns:
        The skill id from the payload, or ``None`` if it is missing.
    """
    skill_id = message.data.get("skill_id")
    source_id = message.context.get("skill_id") if message.context else None
    if skill_id and source_id and source_id != skill_id:
        LOG.debug(f"[{handler}] cross-skill control: source={source_id!r} "
                  f"target={skill_id!r} (OVOS-INTENT-4 §3.2)")
    return skill_id


class _InjectedContextManager:
    """Adapt context source backed by ``session.intent_context`` (CONTEXT-1 §7).

    Presents pre-match context candidates through the same ``get_context``
    surface the legacy frame-stack :class:`~ovos_adapt.context.ContextManager`
    exposes, so the adapt matcher consumes them exactly as it consumed legacy
    ``from_context`` tags -- but sourced from the canonical intent-context map
    rather than the frame stack. Each candidate is an entity dict of the shape
    the parser and :meth:`Intent.validate_with_tags` expect.
    """

    def __init__(self, entities):
        self._entities = entities

    def get_context(self, *args, **kwargs):
        # copies: the parser sorts and mutates the returned list in place.
        return [dict(entity) for entity in self._entities]


def _invalidates_match_cache(method):
    """Clear the ``match_intent`` cache after a method changes the engines.

    The cache lets the high, medium and low tiers share one engine run per
    round. It is keyed on the utterances, the lang and the serialized
    message, not on the registrations, so any change to the engines makes
    every entry stale. A detached skill kept matching a repeated
    ``intent.service.intent.get`` probe on a live core until this cleared
    it. The clear runs after the change, so a match that runs during the
    change cannot cache the old state past it.
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            self._invalidate_match_cache()
    return wrapper


class AdaptPipeline(ConfidenceMatcherPipeline):
    """Intent service wrapping the Adapt intent Parser."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        core_config = Configuration()
        intent_config = core_config.get('intents', {})
        config = config or intent_config.get("ovos-adapt-pipeline-plugin") or intent_config.get("adapt") or dict()
        super().__init__(bus, config)
        self.lang = standardize_lang(core_config.get("lang", "en-US"))
        langs = core_config.get('secondary_langs') or []
        if self.lang not in langs:
            langs.append(self.lang)
        langs = [standardize_lang(l) for l in langs]
        self.engines = {lang: IntentDeterminationEngine()
                        for lang in langs}

        self.lock = Lock()
        self.registered_vocab = []
        self.max_words = 50  # if an utterance contains more words than this, don't attempt to match

        # Ownership tracking for detach_skill (see _entity_skill_id docstring):
        # skill_id -> set of entity_types / regex group names it registered.
        # Populated at registration time from message.context["skill_id"];
        # entries with no recorded owner fall back to a prefix match on
        # detach, preserving pre-existing behaviour for those callers.
        self._entity_owners: Dict[str, set] = {}
        self._regex_owners: Dict[str, set] = {}

        # TODO sanitize config option
        self.conf_high = self.config.get("conf_high") or 0.65
        self.conf_med = self.config.get("conf_med") or 0.45
        self.conf_low = self.config.get("conf_low") or 0.25

        self.bus.on('register_vocab', self.handle_register_vocab)
        self.bus.on('register_intent', self.handle_register_intent)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)

        self.bus.on('intent.service.adapt.get', self.handle_get_adapt)
        self.bus.on('intent.service.adapt.manifest.get', self.handle_adapt_manifest)
        self.bus.on('intent.service.adapt.vocab.manifest.get', self.handle_vocab_manifest)

        # OVOS-CONTEXT-1 gate declarations, keyed by adapt intent label
        # (``skill_id:intent_name``): {'requires': [...], 'excludes': [...]}.
        self._context_gates: Dict[str, Dict] = {}

        # OVOS-CONTEXT-1 §7 injection index, keyed by adapt intent label:
        # {'skill_id': str, 'keywords': {vocab_name: adapt_entity_type}}. Maps
        # each intent's declared keyword names to the entity_type its matcher
        # requires, so a live context entry of that name can be injected as a
        # candidate keyword before matching.
        self._intent_keywords: Dict[str, Dict] = {}

        self._register_spec_handlers()

    def update_context(self, intent):
        """Updates context with keyword from the intent.

        NOTE: This method currently won't handle one_of intent keywords
              since it's not using quite the same format as other intent
              keywords. This is under investigation in adapt, PR pending.

        Args:
            intent: Intent to scan for keywords
        """
        LOG.warning("update_context has been deprecated, use Session.context.update_context instead")
        sess = SessionManager.get()
        ents = [tag['entities'][0] for tag in intent['__tags__'] if 'entities' in tag]
        sess.context.update_context(ents)

    def _invalidate_match_cache(self):
        """Drop every cached ``match_intent`` result (see
        ``_invalidates_match_cache``)."""
        self.match_intent.cache_clear()

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.match_data.get("confidence", 0.0) >= self.conf_high:
            return match
        return None

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.match_data.get("confidence", 0.0) >= self.conf_med:
            return match
        return None

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.match_data.get("confidence", 0.0) >= self.conf_low:
            return match
        return None

    @lru_cache(maxsize=3)  # NOTE - message is a string because of this
    def match_intent(self, utterances: Iterable[str],
                     lang: Optional[str] = None,
                     message: Optional[str] = None):
        """Run the Adapt engine to search for an matching intent.

        Args:
            utterances (iterable): utterances for consideration in intent 
                    matching. As a practical matter, a single utterance will 
                    be passed in most cases. But there are instances, such as
                    streaming STT that could pass multiple. Each utterance is 
                    represented as a tuple containing the raw, normalized, and
                    possibly other variations of the utterance.
            limit (float): confidence threshold for intent matching
            lang (str): language to use for intent matching
            message (Message): message to use for context

        Returns:
            Intent structure, or None if no match was found.
        """

        if message:
            message = Message.deserialize(message)
        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)

        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping adapt match")
            return None

        lang = self._get_closest_lang(lang)
        if lang is None:  # no intents registered for this lang
            return None

        best_intent = {}

        def take_best(intent, utt):
            nonlocal best_intent
            best = best_intent.get('confidence', 0.0) if best_intent else 0.0
            conf = intent.get('confidence', 0.0)
            skill = intent['intent_type'].split(":")[0]
            if best < conf and intent["intent_type"] not in (sess.blacklisted_intents or []) \
                    and skill not in (sess.blacklisted_skills or []):
                best_intent = intent
                # TODO - Shouldn't Adapt do this?
                best_intent['utterance'] = utt

        for utt in utterances:
            try:
                intents = [i for i in self.engines[lang].determine_intent(
                    utt, 100,
                    include_tags=True,
                    context_manager=self._context_manager(sess))
                    if self._context_gate_ok(i, sess)]
                if intents:
                    utt_best = max(
                        intents, key=lambda x: x.get('confidence', 0.0)
                    )
                    take_best(utt_best, utt)

            except Exception as err:
                LOG.exception(err)

        if best_intent:
            ents = [tag['entities'][0] for tag in best_intent['__tags__'] if 'entities' in tag]

            sess.context.update_context(ents)

            skill_id = best_intent['intent_type'].split(":")[0]
            ret = IntentHandlerMatch(
                match_type=best_intent['intent_type'],
                match_data=best_intent, skill_id=skill_id,
                utterance=best_intent['utterance']
            )
        else:
            ret = None
        return ret

    def _get_closest_lang(self, lang: str) -> Optional[str]:
        if self.engines:
            return closest_lang(lang, list(self.engines.keys()))
        return None

    def _store_context_gate(self, intent_type: str, requires, excludes):
        """Record OVOS-CONTEXT-1 gate declarations for an intent.

        ``requires`` / ``excludes`` are ``requires_context`` /
        ``excludes_context`` lists (bare-string or ``{key, scope}`` items).
        A registration carrying neither leaves no entry, so ungated intents
        keep their prior match behaviour unchanged.
        """
        if requires or excludes:
            self._context_gates[intent_type] = {
                "requires": requires or [],
                "excludes": excludes or [],
            }

    def _context_gate_ok(self, intent: Dict, sess) -> bool:
        """Evaluate the OVOS-CONTEXT-1 gate for a candidate match.

        A candidate is admissible iff its stored ``requires_context`` keys
        are all live in ``session.intent_context`` and none of its
        ``excludes_context`` keys are (OVOS-CONTEXT-1 §6/§6.1). Intents
        without a stored gate always pass. Live/scope/decay semantics live
        entirely inside :func:`gate_satisfied`.
        """
        intent_type = intent.get('intent_type')
        gate = self._context_gates.get(intent_type)
        if not gate:
            return True
        skill_id = intent_type.split(':')[0]
        return gate_satisfied(sess.intent_context or {},
                              gate['requires'], gate['excludes'],
                              owner_id=skill_id)

    @staticmethod
    def _unmunge_keyword_name(entity_type: str, skill_id: str) -> str:
        """Recover the plain vocabulary name from a legacy-munged entity_type.

        ``ovos-workshop``'s ``_AdaptIntentApi.munge_intent_parser`` prefixes
        legacy ``require``/``optional``/``at_least_one`` entity_types with
        ``to_alnum(skill_id)`` (non-alphanumeric characters replaced by
        ``_``). This mirrors that transform in reverse, used only to build
        an *additional* fallback probe in :meth:`_live_context_value` --
        some call sites write the session's ``intent_context`` key with the
        raw plain name (e.g. ``SessionManager.get(msg).set_intent_context
        ("prev_dialog", ...)``) instead of going through
        ``OVOSSkill.set_context`` (which munges). Returns the entity_type
        unchanged when it does not carry the prefix, or when stripping the
        prefix would leave an empty string (an empty lookup key can never
        usefully match).
        """
        prefix = ''.join(c if c.isalnum() else '_' for c in str(skill_id))
        if prefix and entity_type.startswith(prefix):
            stripped = entity_type[len(prefix):]
            if stripped:
                return stripped
        return entity_type

    @classmethod
    def _live_context_value(cls, entries: Dict, name: str, skill_id: str,
                            now: float) -> Optional[str]:
        """Resolve a live string context value for a keyword name.

        Two producers write ``session.intent_context`` under different key
        shapes for the same keyword, so both are probed:

        - ``OVOSSkill.set_context``/legacy ``add_context`` munges the key
          (``to_alnum(skill_id) + name``), matching the keyword's
          (already-munged) ``entity_type`` directly.
        - Raw ``SessionManager.get(msg).set_intent_context(name, ...)``
          writes the plain, un-munged ``name`` -- used e.g. by
          days-in-history's context-only keywords.

        For each shape, scope is read from the key (OVOS-CONTEXT-1 §3): the
        owner's private entry ``<skill_id>:<key>`` is consulted before the
        shared bare ``<key>``. The plain-name probes are skipped when
        unmunging is a no-op (nothing to strip), to avoid a redundant
        duplicate lookup. Null-valued (``value=None``) and empty-string
        (``value=""``) entries are ignored as non-injectable flags -- the
        ``requires_context``/``excludes_context`` gating contract -- along
        with any other non-string entry: they gate only, never inject.

        Trade-off accepted by the plain-name fallback: a shared-scope entry
        written under the un-munged plain name fills ANY legacy skill's
        private keyword of that same name, so generic names (``prev_dialog``,
        ``date``, ``person``, ``sleeping_state``) are effectively global
        across skills rather than namespaced -- acceptable because it only
        ever adds a probe, never replaces the primary (munged, per-skill)
        lookup.
        """
        plain_name = cls._unmunge_keyword_name(name, skill_id)
        probes = [f"{skill_id}:{name}", name]
        if plain_name != name:
            probes += [f"{skill_id}:{plain_name}", plain_name]
        for key in probes:
            entry = entries.get(key)
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if not isinstance(value, str) or not value:
                continue
            if not is_live(entry, now):
                continue
            return value
        return None

    def _context_candidate_entities(self, sess) -> List[Dict]:
        """Build OVOS-CONTEXT-1 §7 pre-match candidate entities.

        For every registered intent keyword that has a live non-null string
        entry in ``session.intent_context`` (scope-resolved from the key),
        emit an adapt context entity of that keyword's ``entity_type`` carrying
        the entry value. The matcher then treats the value as it would a
        keyword the utterance produced; an entity the utterance itself yields
        for the same type is found first by ``_find_first_tag`` and wins.
        """
        entries = getattr(sess, "intent_context", None) or {}
        if not entries or not self._intent_keywords:
            return []
        now = time.time()
        seen = set()
        candidates = []
        for meta in self._intent_keywords.values():
            skill_id = meta["skill_id"]
            for name, entity_type in meta["keywords"].items():
                value = self._live_context_value(entries, name, skill_id, now)
                if value is None:
                    continue
                dedup = (entity_type, value)
                if dedup in seen:
                    continue
                seen.add(dedup)
                candidates.append({"key": value, "match": value,
                                   "confidence": 1.0,
                                   "data": [(value, entity_type)]})
        return candidates

    def _context_manager(self, sess) -> _InjectedContextManager:
        """Context source for a match, sourced from ``session.intent_context``."""
        return _InjectedContextManager(self._context_candidate_entities(sess))

    def _record_intent_keywords(self, intent):
        """Index an intent's declared keyword names for §7 injection.

        Records every ``require`` / ``optional`` / ``one_of`` entity_type keyed
        by the label's ``skill_id``. For legacy and in-process registrations
        the keyword name is the entity_type itself; the OVOS-INTENT-4 keyword
        handler overrides this with the un-namespaced vocabulary names.
        """
        name = getattr(intent, "name", None)
        if not name:
            return
        keywords = {}
        for entity_type, _attr in (list(getattr(intent, "requires", []) or []) +
                                   list(getattr(intent, "optional", []) or [])):
            keywords[entity_type] = entity_type
        for group in getattr(intent, "at_least_one", []) or []:
            for entity_type in group:
                keywords[entity_type] = entity_type
        skill_id = name.split(":", 1)[0] if ":" in name else name
        self._intent_keywords[name] = {"skill_id": skill_id,
                                       "keywords": keywords}

    def _forget_intent_keywords(self, skill_id: str):
        """Drop the §7 injection index entries owned by a detached skill."""
        for label in [l for l, m in self._intent_keywords.items()
                      if m["skill_id"] == skill_id]:
            self._intent_keywords.pop(label, None)

    @_invalidates_match_cache
    def register_vocabulary(self, entity_value: str, entity_type: str,
                            alias_of: str, regex_str: str, lang: str,
                            skill_id: Optional[str] = None):
        """Register skill vocabulary as adapt entity.

        This will handle both regex registration and registration of normal
        keywords. if the "regex_str" argument is set all other arguments will
        be ignored.

        Argument:
            entity_value: the natural langauge word
            entity_type: the type/tag of an entity instance
            alias_of: entity this is an alternative for
            skill_id: owning skill, when known, used to scope
                ``detach_skill`` to exactly this registration instead of a
                collision-prone prefix match (see ``_entity_skill_id``).
        """
        lang = self._get_closest_lang(lang)
        if lang is not None:
            with self.lock:
                if regex_str:
                    self.engines[lang].register_regex_entity(regex_str)
                    if skill_id:
                        # findall (not search): a regex can carry more than
                        # one named group, and every group needs to be
                        # recorded or the un-recorded ones fall through to
                        # the collision-prone prefix-match fallback on
                        # detach (see _should_detach).
                        names = re.findall(r"\(\?P<([^>]+)>", regex_str)
                        if names:
                            self._warn_ownership_collision(
                                self._regex_owners, skill_id, names)
                            self._regex_owners.setdefault(skill_id, set()).update(
                                names)
                else:
                    self.engines[lang].register_entity(
                        entity_value, entity_type, alias_of=alias_of)
                    if skill_id and entity_type:
                        self._warn_ownership_collision(
                            self._entity_owners, skill_id, [entity_type])
                        self._entity_owners.setdefault(skill_id, set()).add(
                            entity_type)

    @_invalidates_match_cache
    def register_intent(self, intent):
        """Register new intent with adapt engine.

        Args:
            intent (IntentParser): IntentParser to register
        """
        for lang in self.engines:
            with self.lock:
                self.engines[lang].register_intent_parser(intent)
        # OVOS-CONTEXT-1 §7 — index declared keywords for candidate injection.
        self._record_intent_keywords(intent)

    @_invalidates_match_cache
    def detach_skill(self, skill_id):
        """Remove all intents for skill.

        Args:
            skill_id (str): skill to process
        """
        with self.lock:
            for lang in self.engines:
                skill_parsers = [
                    p.name for p in self.engines[lang].intent_parsers if
                    p.name.startswith(skill_id + ':')
                ]
                self.engines[lang].drop_intent_parser(skill_parsers)
            self._detach_skill_keywords(skill_id)
            self._detach_skill_regexes(skill_id)
        self._forget_intent_keywords(skill_id)

    @staticmethod
    def _warn_ownership_collision(owners, skill_id, names):
        """Log when ``skill_id`` registers a name already owned by a
        DIFFERENT skill_id.

        Two skill ids that normalize to the same string after
        ``_entity_skill_id`` (e.g. ``foo-bar`` and ``foo.bar``), or two
        skills that simply pick the same entity_type/regex-group name, can
        both claim the same entity in the shared engine. The engine has no
        way to disambiguate which skill genuinely owns it, so this is
        surfaced as a warning (visibility) rather than silently resolved.
        """
        names = set(names)
        for other_skill, owned in owners.items():
            if other_skill == skill_id:
                continue
            collision = owned & names
            if collision:
                LOG.warning(
                    f"skill '{skill_id}' is registering entity name(s) "
                    f"{sorted(collision)} already owned by skill "
                    f"'{other_skill}' - these skill ids collide (possibly "
                    f"after normalization) and the engine cannot "
                    f"disambiguate which skill owns the shared entity")

    @staticmethod
    def _should_detach(name, owned, foreign, prefix):
        """Ownership decision for detach_skill, three cases in order:
        recorded as this skill's but NOT also recorded as another skill's
        -> drop; recorded as this skill's AND still recorded as another
        skill's (collision) -> survive, the other skill still needs it;
        recorded only as another skill's -> never touch; unrecorded
        (pre-ownership registrations) -> legacy prefix match."""
        if owned is not None and name in owned:
            return name not in foreign
        if name in foreign:
            return False
        return name.startswith(prefix)

    def _ownership_snapshot(self, owners, skill_id):
        """Pop ``skill_id``'s recorded set out of ``owners`` and return it
        alongside the union of every other skill's recorded names (never
        including ``skill_id``'s own) and the legacy prefix for
        ``skill_id``. Feeds ``_should_detach``.
        """
        owned = owners.pop(skill_id, None)
        foreign = set()
        for names in owners.values():
            foreign |= names
        prefix = _entity_skill_id(skill_id)
        return owned, foreign, prefix

    def _detach_skill_keywords(self, skill_id):
        """Detach all keywords registered with ``skill_id``. See
        ``_should_detach`` for the ownership decision.
        """
        owned, foreign, prefix = self._ownership_snapshot(self._entity_owners, skill_id)
        match_func = lambda data: bool(data) and self._should_detach(
            data[1], owned, foreign, prefix)
        for lang in self.engines:
            self.engines[lang].drop_entity(match_func=match_func)

    def _detach_skill_regexes(self, skill_id):
        """Detach all regexes registered with ``skill_id``. See
        ``_should_detach`` for the ownership decision.
        """
        owned, foreign, prefix = self._ownership_snapshot(self._regex_owners, skill_id)
        match_func = lambda regexp: any(
            self._should_detach(name, owned, foreign, prefix)
            for name in regexp.groupindex)
        for lang in self.engines:
            self.engines[lang].drop_regex_entity(match_func=match_func)

    @_invalidates_match_cache
    def detach_intent(self, intent_name):
        """Detatch a single intent

        Args:
            intent_name (str): Identifier for intent to remove.
        """
        for lang in self.engines:
            new_parsers = [
                p for p in self.engines[lang].intent_parsers if p.name != intent_name
            ]
            self.engines[lang].intent_parsers = new_parsers
        self._intent_keywords.pop(intent_name, None)

    @_invalidates_match_cache
    def shutdown(self):
        for lang in self.engines:
            # drop_intent_parser takes names, not parser objects
            names = [p.name for p in self.engines[lang].intent_parsers]
            self.engines[lang].drop_intent_parser(names)

    @property
    def registered_intents(self):
        lang = self._get_closest_lang(get_message_lang())
        if lang is None:
            return []
        return [parser.__dict__ for parser in self.engines[lang].intent_parsers]

    def handle_register_vocab(self, message):
        """Register adapt vocabulary.

        Args:
            message (Message): message containing vocab info
        """
        entity_value = message.data.get('entity_value')
        entity_type = message.data.get('entity_type')
        regex_str = message.data.get('regex')
        alias_of = message.data.get('alias_of')
        lang = get_message_lang(message)
        # OVOS-INTENT-4 §3.1/§3.2 — a registration without an owning
        # skill_id in the context is malformed: registering it anyway
        # with owner None means detach_skill can never remove it, so a
        # word a skill registered outlives that skill's detach and can be
        # matched by an unrelated later intent that happens to require
        # the same entity_type/keyword.
        skill_id = _legacy_skill_id(message, "handle_register_vocab")
        if not skill_id:
            LOG.warning(f"[handle_register_vocab] rejected: missing "
                        f"message.context['skill_id']")
            return
        # OVOS-INTENT-4 §6.3 — skip unusable registrations with a warning
        # instead of crashing the executor: a payload must carry either a
        # regex or a complete entity_value/entity_type keyword pair.
        if not regex_str and (not entity_value or not entity_type):
            LOG.warning(f"skipping malformed vocab registration "
                        f"(topic={message.msg_type}, lang={lang}, "
                        f"entity_type={entity_type}, entity_value={entity_value}): "
                        f"missing entity_value/entity_type and no regex")
            return
        self.register_vocabulary(entity_value, entity_type,
                                 alias_of, regex_str, lang, skill_id=skill_id)
        self.registered_vocab.append(message.data)

    def handle_register_intent(self, message):
        """Register adapt intent.

        Args:
            message (Message): message containing intent info
        """
        intent = open_intent_envelope(message)
        self.register_intent(intent)
        # OVOS-CONTEXT-1 §6 — accept gate declarations on the legacy payload.
        self._store_context_gate(
            intent.name,
            message.data.get("requires_context"),
            message.data.get("excludes_context"))

    def handle_detach_intent(self, message):
        """Remover adapt intent.

        Args:
            message (Message): message containing intent info
        """
        intent_name = message.data.get('intent_name')
        self.detach_intent(intent_name)

    def handle_detach_skill(self, message):
        """Remove all intents registered for a specific skill.

        Args:
            message (Message): message containing intent info
        """
        skill_id = _legacy_skill_id(message, "handle_detach_skill")
        if not skill_id:
            LOG.warning("[handle_detach_skill] rejected: missing "
                        "message.context['skill_id']")
            return
        self.detach_skill(skill_id)

    def handle_get_adapt(self, message: Message):
        """handler getting the adapt response for an utterance.

        Args:
            message (Message): message containing utterance
        """
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        intent = self.match_intent((utterance,), lang, message.serialize())
        intent_data = intent.match_data if intent else None
        self.bus.emit(message.reply("intent.service.adapt.reply",
                                    {"intent": intent_data}))

    def handle_adapt_manifest(self, message):
        """Send adapt intent manifest to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.adapt.manifest",
                                    {"intents": self.registered_intents}))

    def handle_vocab_manifest(self, message):
        """Send adapt vocabulary manifest to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.adapt.vocab.manifest",
                                    {"vocab": self.registered_vocab}))

    # ------------------------------------------------------------------
    # OVOS-INTENT-4 spec registration topics (consumed alongside legacy)
    # ------------------------------------------------------------------
    def _register_spec_handlers(self):
        """Subscribe to the OVOS-INTENT-4 registration topics.

        These run *in addition* to the legacy ``register_vocab`` /
        ``register_intent`` / ``detach_*`` handlers — un-migrated skills keep
        working unchanged. The spec consolidates vocab + intent into one
        ``ovos.intent.register.keyword`` payload (INTENT-4 §5), so this
        handler builds the adapt IntentBuilder *and* registers the inline
        vocabularies in a single pass.
        """
        self.bus.on(SpecMessage.INTENT_REGISTER_KEYWORD,
                    self.handle_spec_register_keyword)
        self.bus.on(SpecMessage.ENTITY_REGISTER,
                    self.handle_spec_register_entity)
        self.bus.on(SpecMessage.INTENT_DEREGISTER,
                    self.handle_spec_deregister_intent)
        self.bus.on(SpecMessage.ENTITY_DEREGISTER,
                    self.handle_spec_deregister_entity)
        self.bus.on(SpecMessage.SKILL_DEREGISTER,
                    self.handle_spec_deregister_skill)
        self.bus.on(SpecMessage.INTENT_ENABLE,
                    self.handle_spec_enable_intent)
        self.bus.on(SpecMessage.INTENT_DISABLE,
                    self.handle_spec_disable_intent)

    @staticmethod
    def _spec_entity_type(skill_id: str, name: str) -> str:
        """Namespace a spec vocabulary ``name`` to an adapt entity_type.

        INTENT-4 vocabulary ``name`` is unique within a skill (§5.1); adapt
        entity_types are a global namespace. We prefix with the same
        normalized skill_id form the legacy detach helpers key off
        (:func:`_entity_skill_id`) so ``detach_skill`` reaches these too.
        """
        return f"{_entity_skill_id(skill_id)}{name}"

    @staticmethod
    def _spec_intent_name(skill_id: str, intent_name: str) -> str:
        """Build the adapt intent label (``skill_id:intent_name``).

        Mirrors the legacy convention: skills emit IntentBuilder names of the
        form ``<skill_id>:<intent_name>`` so detach-by-skill and the
        match-result ``intent_type`` carry the owning skill.
        """
        if ":" in intent_name:
            return intent_name
        return f"{skill_id}:{intent_name}"

    def _register_spec_vocab(self, descriptor: dict, skill_id: str,
                             lang: str) -> Optional[str]:
        """Register one INTENT-4 vocabulary descriptor (§5.1) into adapt.

        Each ``samples`` entry is a slot-free INTENT-1 template; adapt's
        ``register_entity`` expands ``(a|b)`` / ``[opt]`` syntax itself, so
        samples are passed through verbatim. Returns the namespaced
        entity_type, or ``None`` if the descriptor is malformed.
        """
        name = descriptor.get("name")
        samples = descriptor.get("samples") or []
        if not name or not samples:
            return None
        entity_type = self._spec_entity_type(skill_id, name)
        for sample in samples:
            if not sample:
                continue
            self.register_vocabulary(sample, entity_type, None, None, lang,
                                     skill_id=skill_id)
            self.registered_vocab.append({"entity_value": sample,
                                          "entity_type": entity_type})
        return entity_type

    def handle_spec_register_keyword(self, message):
        """Consume ``ovos.intent.register.keyword`` (INTENT-4 §5).

        Translates the consolidated keyword payload into adapt's split
        vocab + IntentBuilder model:

        - ``required[]``  -> register_entity(name) + IntentBuilder.require(name)
        - ``optional[]``  -> register_entity(name) + .optionally(name)
        - ``one_of[][]``  -> register every member + .one_of(*group)
        - ``excluded[]``  -> register_entity(name) + .exclude(name)
        """
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_register_keyword")
        intent_name = data.get("intent_name")
        lang = standardize_lang(data.get("lang") or get_message_lang(message))

        required = data.get("required") or []
        optional = data.get("optional") or []
        one_of = data.get("one_of") or []
        excluded = data.get("excluded") or []

        if not skill_id or not intent_name:
            LOG.warning(f"ignoring malformed {SpecMessage.INTENT_REGISTER_KEYWORD} "
                        f"registration (lang={lang}): missing skill_id/intent_name")
            return
        # INTENT-3 §4.2 / INTENT-4 §5.3: required and one_of MUST NOT both be empty
        if not required and not one_of:
            LOG.warning(f"ignoring malformed keyword intent "
                        f"{skill_id}:{intent_name} (lang={lang}, topic="
                        f"{SpecMessage.INTENT_REGISTER_KEYWORD}): required and "
                        f"one_of are both empty")
            return

        builder = IntentBuilder(self._spec_intent_name(skill_id, intent_name))

        for descriptor in required:
            entity_type = self._register_spec_vocab(descriptor, skill_id, lang)
            if entity_type is None:
                LOG.warning(f"ignoring malformed keyword intent "
                            f"{skill_id}:{intent_name} (lang={lang}): a required "
                            f"vocabulary descriptor lacks name/samples")
                return
            builder.require(entity_type)

        for descriptor in optional:
            entity_type = self._register_spec_vocab(descriptor, skill_id, lang)
            if entity_type is not None:
                builder.optionally(entity_type)

        for group in one_of:
            members = []
            for descriptor in group:
                entity_type = self._register_spec_vocab(descriptor, skill_id, lang)
                if entity_type is not None:
                    members.append(entity_type)
            if members:
                builder.one_of(*members)

        for descriptor in excluded:
            entity_type = self._register_spec_vocab(descriptor, skill_id, lang)
            if entity_type is not None:
                builder.exclude(entity_type)

        self.register_intent(builder.build())
        label = self._spec_intent_name(skill_id, intent_name)
        # OVOS-CONTEXT-1 §7 — map the un-namespaced vocabulary names to the
        # namespaced adapt entity_types so a context entry keyed by the bare
        # name (e.g. ``person``) injects a candidate for this intent's keyword.
        keyword_types = {}
        for descriptor in list(required) + list(optional):
            n = descriptor.get("name")
            if n:
                keyword_types[n] = self._spec_entity_type(skill_id, n)
        for group in one_of:
            for descriptor in group:
                n = descriptor.get("name")
                if n:
                    keyword_types[n] = self._spec_entity_type(skill_id, n)
        self._intent_keywords[label] = {"skill_id": skill_id,
                                        "keywords": keyword_types}
        # OVOS-CONTEXT-1 §6 — the register payload MAY declare context gates.
        self._store_context_gate(
            label,
            data.get("requires_context"), data.get("excludes_context"))

    def handle_spec_register_entity(self, message):
        """Consume ``ovos.entity.register`` (INTENT-4 §7).

        Registers an ``.entity`` value-set into the adapt trie. Each
        ``samples`` entry is a slot-free value (INTENT-1 §5.4).
        """
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_register_entity")
        entity_name = data.get("entity_name")
        lang = standardize_lang(data.get("lang") or get_message_lang(message))
        samples = data.get("samples") or []
        if not skill_id or not entity_name or not samples:
            LOG.warning(f"ignoring malformed {SpecMessage.ENTITY_REGISTER} "
                        f"registration (entity_name={entity_name}, lang={lang}): "
                        f"missing skill_id/entity_name/samples")
            return
        self._register_spec_vocab({"name": entity_name, "samples": samples},
                                  skill_id, lang)

    def handle_spec_deregister_intent(self, message):
        """Consume ``ovos.intent.deregister`` (INTENT-4 §8.2)."""
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_deregister_intent")
        intent_name = data.get("intent_name")
        if not skill_id or not intent_name:
            LOG.warning(f"ignoring malformed {SpecMessage.INTENT_DEREGISTER} "
                        f"(intent_name={intent_name}): missing skill_id/intent_name")
            return
        self.detach_intent(self._spec_intent_name(skill_id, intent_name))

    @_invalidates_match_cache
    def handle_spec_deregister_entity(self, message):
        """Consume ``ovos.entity.deregister`` (INTENT-4 §8.3)."""
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_deregister_entity")
        entity_name = data.get("entity_name")
        if not skill_id or not entity_name:
            LOG.warning(f"ignoring malformed {SpecMessage.ENTITY_DEREGISTER} "
                        f"(entity_name={entity_name}): missing skill_id/entity_name")
            return
        entity_type = self._spec_entity_type(skill_id, entity_name)

        def match_entity(d):
            return d and d[1] == entity_type

        with self.lock:
            for lang in self.engines:
                self.engines[lang].drop_entity(match_func=match_entity)

    def handle_spec_deregister_skill(self, message):
        """Consume ``ovos.skill.deregister`` (INTENT-4 §8.4)."""
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_deregister_skill")
        if not skill_id:
            LOG.warning(f"ignoring malformed {SpecMessage.SKILL_DEREGISTER}: "
                        "missing skill_id")
            return
        self.detach_skill(skill_id)

    def handle_spec_disable_intent(self, message):
        """Consume ``ovos.intent.disable`` (INTENT-4 §8.5).

        Adds the intent to the session blacklist so it is excluded from match
        candidacy without losing its registration.
        """
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_disable_intent")
        intent_name = data.get("intent_name")
        if not skill_id or not intent_name:
            return
        intent_type = self._spec_intent_name(skill_id, intent_name)
        sess = SessionManager.get(message)
        if sess.blacklisted_intents is None:
            sess.blacklisted_intents = []
        if intent_type not in sess.blacklisted_intents:
            sess.blacklisted_intents.append(intent_type)

    def handle_spec_enable_intent(self, message):
        """Consume ``ovos.intent.enable`` (INTENT-4 §8.5)."""
        data = message.data
        skill_id = _spec_skill_id(message, "handle_spec_enable_intent")
        intent_name = data.get("intent_name")
        if not skill_id or not intent_name:
            return
        intent_type = self._spec_intent_name(skill_id, intent_name)
        sess = SessionManager.get(message)
        if intent_type in (sess.blacklisted_intents or []):
            sess.blacklisted_intents.remove(intent_type)


def _domain_from_intent_name(intent_name: str) -> str:
    """Extract skill_id domain from an intent label.

    Intent labels follow the ``skill_id:intent_name`` convention. If no
    ``:`` is present the full label is used as the domain.
    """
    if not intent_name:
        return ""
    return intent_name.split(":", 1)[0] if ":" in intent_name else intent_name


class DomainAdaptPipeline(AdaptPipeline):
    """Adapt pipeline backed by ``DomainIntentDeterminationEngine``.

    Unlike :class:`AdaptPipeline`, this variant maintains a dedicated
    per-skill ``IntentDeterminationEngine`` (a "domain"). At match time,
    every domain is scored in parallel and a global ``nlargest`` selects
    the winner — no top-level router is involved.

    Intent registrations are routed to the right domain based on the
    ``skill_id`` prefix of the intent label (``skill_id:intent_name``).
    """

    #: per-domain engine class; overridden by HierarchicalAdaptPipeline.
    _engine_class = DomainIntentDeterminationEngine
    #: config section under ``intents``; overridden by subclasses.
    _config_key = "ovos_adapt_domain_pipeline"

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        core_config = Configuration()
        # Use dedicated config section so users can tune this pipeline
        # independently from the flat AdaptPipeline.
        config = config or core_config.get("intents", {}).get(
            self._config_key, {})
        # Skip AdaptPipeline.__init__ to avoid building a flat engine; call
        # the grandparent initializer directly.
        ConfidenceMatcherPipeline.__init__(self, bus, config)
        self.lang = standardize_lang(core_config.get("lang", "en-US"))
        langs = core_config.get('secondary_langs') or []
        if self.lang not in langs:
            langs.append(self.lang)
        langs = [standardize_lang(l) for l in langs]
        self.engines = {lang: self._engine_class()
                        for lang in langs}

        self.lock = Lock()
        self.registered_vocab = []
        self.max_words = 50

        self.conf_high = self.config.get("conf_high") or 0.65
        self.conf_med = self.config.get("conf_med") or 0.45
        self.conf_low = self.config.get("conf_low") or 0.25

        # Maps lang -> entity_type_prefix -> domain (skill_id). Allows the
        # vocab/regex registration handlers, which only see entity_type, to
        # route to the correct domain.
        self._entity_domain_index: Dict[str, Dict[str, str]] = {
            lang: {} for lang in langs
        }

        # OVOS-CONTEXT-1 gate declarations, keyed by adapt intent label.
        self._context_gates: Dict[str, Dict] = {}
        # OVOS-CONTEXT-1 §7 injection index (see AdaptPipeline.__init__).
        self._intent_keywords: Dict[str, Dict] = {}

        self.bus.on('register_vocab', self.handle_register_vocab)
        self.bus.on('register_intent', self.handle_register_intent)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)

        self.bus.on('intent.service.adapt.get', self.handle_get_adapt)
        self.bus.on('intent.service.adapt.manifest.get', self.handle_adapt_manifest)
        self.bus.on('intent.service.adapt.vocab.manifest.get', self.handle_vocab_manifest)

        self._register_spec_handlers()

    def _resolve_entity_domain(self, lang: str, entity_type: str) -> str:
        """Best-effort lookup of the domain that owns an entity_type.

        Vocab/regex registrations don't carry ``skill_id`` directly; we map
        them by entity_type prefix populated when intents are registered.
        Falls back to the entity_type itself if no match is found.
        """
        index = self._entity_domain_index.get(lang, {})
        if not entity_type:
            # nothing to route by (e.g. a regex with no named group);
            # fall back to the shared default domain
            return 0
        # exact match first
        if entity_type in index:
            return index[entity_type]
        # longest-prefix match (entity_type often == "<skill_id_norm><Name>")
        best = ""
        for prefix, domain in index.items():
            if entity_type.startswith(prefix) and len(prefix) > len(best):
                best = prefix
        if best:
            return index[best]
        return entity_type

    def _gather_candidates(self, engine, utt, sess):
        """Collect intent candidates for an utterance.

        Scores every domain sub-engine in parallel. Overridden by
        :class:`HierarchicalAdaptPipeline` to score a single routed domain.
        """
        with self.lock:
            sub_engines = list(engine.domains.values())
        candidates = []
        for sub in sub_engines:
            for it in sub.determine_intent(
                    utterance=utt, num_results=1, include_tags=True,
                    context_manager=self._context_manager(sess)):
                if self._context_gate_ok(it, sess):
                    candidates.append(it)
        return candidates

    @lru_cache(maxsize=3)
    def match_intent(self, utterances: Iterable[str],
                     lang: Optional[str] = None,
                     message: Optional[str] = None):
        """Run all per-domain engines in parallel, take the global argmax.

        ``DomainIntentDeterminationEngine.determine_intent`` does not
        propagate ``include_tags``/``context_manager`` to its sub-engines,
        so we iterate sub-engines manually to preserve adapt's contextual
        scoring behaviour.
        """
        if message:
            message = Message.deserialize(message)
        sess = SessionManager.get(message)

        utterances = flatten_list(utterances)
        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping adapt match")
            return None

        lang = self._get_closest_lang(lang)
        if lang is None:
            return None

        best_intent = {}

        def take_best(intent, utt):
            nonlocal best_intent
            best = best_intent.get('confidence', 0.0) if best_intent else 0.0
            conf = intent.get('confidence', 0.0)
            skill = intent['intent_type'].split(":")[0]
            if best < conf and intent["intent_type"] not in (sess.blacklisted_intents or []) \
                    and skill not in (sess.blacklisted_skills or []):
                best_intent = intent
                best_intent['utterance'] = utt

        engine = self.engines[lang]
        for utt in utterances:
            try:
                candidates = self._gather_candidates(engine, utt, sess)
                if candidates:
                    utt_best = max(candidates,
                                   key=lambda x: x.get('confidence', 0.0))
                    take_best(utt_best, utt)
            except Exception as err:
                LOG.exception(err)

        if best_intent:
            ents = [tag['entities'][0] for tag in best_intent['__tags__']
                    if 'entities' in tag]
            sess.context.update_context(ents)
            skill_id = best_intent['intent_type'].split(":")[0]
            return IntentHandlerMatch(
                match_type=best_intent['intent_type'],
                match_data=best_intent, skill_id=skill_id,
                utterance=best_intent['utterance']
            )
        return None

    @_invalidates_match_cache
    def register_intent(self, intent):
        """Register a new intent with the per-domain engine."""
        domain = _domain_from_intent_name(intent.name)
        # Track entity_type prefix -> domain so vocab registrations can
        # be routed to the same engine.
        norm = _entity_skill_id(domain)
        for lang in self.engines:
            with self.lock:
                self.engines[lang].register_intent_parser(intent, domain=domain)
                self._entity_domain_index[lang][norm] = domain
        # OVOS-CONTEXT-1 §7 — index declared keywords for candidate injection.
        self._record_intent_keywords(intent)

    @_invalidates_match_cache
    def register_vocabulary(self, entity_value: str, entity_type: str,
                            alias_of: str, regex_str: str, lang: str,
                            skill_id: Optional[str] = None):
        """Register skill vocabulary, routed to a domain.

        When ``skill_id`` is provided the vocab goes to that skill's
        domain: the domain is the skill_id (``_domain_from_intent_name``),
        and the engine creates it on first use. This holds when the vocab
        arrives before the skill's first intent, which is the order
        ``handle_spec_register_keyword`` uses. ``_resolve_entity_domain``,
        the entity_type prefix guess, is only used when ``skill_id`` is
        absent.
        """
        lang = self._get_closest_lang(lang)
        if lang is not None:
            if regex_str and not entity_type:
                # legacy regex payloads carry no entity_type; the named
                # group is the entity_type (skill-id prefixed by the
                # emitter), so route the regex to its owning domain by it
                group = re.search(r"\(\?P<([^>]+)>", regex_str)
                entity_type = group.group(1) if group else None
            with self.lock:
                if skill_id:
                    domain = skill_id
                    # record the prefix so a later vocab without skill_id
                    # for the same entity family routes here too
                    self._entity_domain_index[lang][_entity_skill_id(skill_id)] = domain
                else:
                    domain = self._resolve_entity_domain(lang, entity_type)
                if regex_str:
                    self.engines[lang].register_regex_entity(
                        regex_str, domain=domain)
                else:
                    self.engines[lang].register_entity(
                        entity_value, entity_type, alias_of=alias_of,
                        domain=domain)

    @_invalidates_match_cache
    def detach_skill(self, skill_id):
        """Drop the whole domain for a skill."""
        with self.lock:
            for lang in self.engines:
                if skill_id in self.engines[lang].domains:
                    del self.engines[lang].domains[skill_id]
                # also drop any entity prefix index entries pointing here
                idx = self._entity_domain_index.get(lang, {})
                for prefix in [p for p, d in idx.items() if d == skill_id]:
                    idx.pop(prefix, None)
        self._forget_intent_keywords(skill_id)

    @_invalidates_match_cache
    def detach_intent(self, intent_name):
        """Detach a single intent from its owning domain."""
        domain = _domain_from_intent_name(intent_name)
        with self.lock:
            for lang in self.engines:
                engine = self.engines[lang]
                if domain in engine.domains:
                    sub = engine.domains[domain]
                    sub.intent_parsers = [p for p in sub.intent_parsers
                                          if p.name != intent_name]
        self._intent_keywords.pop(intent_name, None)

    @_invalidates_match_cache
    def shutdown(self):
        with self.lock:
            for lang in self.engines:
                self.engines[lang].domains = {}

    @property
    def registered_intents(self):
        lang = self._get_closest_lang(get_message_lang())
        if lang is None:
            return []
        out = []
        for sub in self.engines[lang].domains.values():
            out.extend(parser.__dict__ for parser in sub.intent_parsers)
        return out


class HierarchicalAdaptPipeline(DomainAdaptPipeline):
    """Adapt pipeline backed by ``HierarchicalIntentDeterminationEngine``.

    Shares the per-skill domain model and registration routing of
    :class:`DomainAdaptPipeline`. Unlike that pipeline, which scores every
    domain in parallel, this variant classifies the domain first and
    evaluates only that domain's sub-engine. A misclassified domain cannot
    be recovered.
    """

    _engine_class = HierarchicalIntentDeterminationEngine
    _config_key = "ovos_adapt_hierarchical_pipeline"

    def _gather_candidates(self, engine, utt, sess):
        """Collect intent candidates from the single routed domain."""
        with self.lock:
            candidates = list(engine.determine_intent(
                utterance=utt, num_results=1, include_tags=True,
                context_manager=self._context_manager(sess)))
        return [it for it in candidates if self._context_gate_ok(it, sess)]
