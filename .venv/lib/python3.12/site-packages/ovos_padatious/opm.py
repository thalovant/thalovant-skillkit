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
"""Intent service wrapping padatious."""
import fnmatch
import re
import string
import time
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from os.path import expanduser, isfile
from threading import Event, RLock, Thread, current_thread
from typing import Optional, Dict, List, Union, Type

import snowballstemmer
from ovos_config.config import Configuration
from ovos_config.meta import get_xdg_base

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_padatious import IntentContainer
from ovos_padatious.domain_container import DomainIntentContainer
from ovos_padatious.match_data import MatchData as PadatiousIntent
from ovos_padatious.util import expand_or_skip
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_spec_tools import closest_lang, expand as expand_template, standardize_lang
from ovos_spec_tools import SpecMessage
from ovos_spec_tools import gate_satisfied, context_slot_candidates
from ovos_spec_tools import (REGISTERED_TYPES, MalformedTypedSlots,
                             declared_slot_types,
                             drop_unregistered_typed_slots,
                             validate_typed_slots)
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.list_utils import deduplicate_list
from ovos_utils.log import LOG, deprecated, log_deprecation
from ovos_utils.text_utils import remove_accents_and_punct
from ovos_utils.xdg_utils import xdg_data_home
import faulthandler

PadatiousIntentContainer = IntentContainer  # backwards compat

# for easy typing
PadatiousEngine = Union[Type[IntentContainer], Type[DomainIntentContainer]]


# OVOS-INTENT-1: a template slot is written ``{entity_name}`` in a sample; the
# padaos parser recognises the same lowercase/underscore/colon name form.
_SLOT_RE = re.compile(r"{([a-z_:]+)}")



def normalize_utterances(utterances: List[str], lang: str, cast_to_ascii: bool = True,
                         keep_order: bool = True, stemmer: Optional['Stemmer'] = None) -> List[str]:
    """
    Normalize a list of utterances by collapsing whitespaces, removing accents and punctuation,
    and optionally stemming and deduplicating.

    Args:
        utterances (List[str]): The list of utterances to normalize.
        lang (str): The language code for stemming support.
        cast_to_ascii (bool): Whether to remove accented characters and punctuation. Default is True.
        keep_order (bool): Whether to preserve the order of utterances. Default is True.
        stemmer (Optional[Stemmer]): A stemmer object to stem the utterances (default is None).

    Returns:
        List[str]: The normalized list of utterances.
    """
    # Flatten the list if it's in old style tuple format
    utterances = flatten_list(utterances)  # Assuming flatten_list is defined elsewhere
    # Normalize case: OVOS-INTENT-1 §2 normalizes input to lowercase for matching,
    # so training samples and extracted slot values stay case-insensitive
    # (ovos_spec_tools.expand preserves case; the prior expander lowercased).
    utterances = [u.lower() for u in utterances]
    # Collapse multiple whitespaces into a single space
    utterances = [re.sub(r'\s+', ' ', u) for u in utterances]
    # Replace accented characters and punctuation if needed
    if cast_to_ascii:
        utterances = [remove_accents_and_punct(u) for u in utterances]
    # strip trailing punctuation, that just causes duplicate training data —
    # but preserve the slot/vocabulary metacharacters {} <> so a template
    # ending in a slot ({name}) keeps its closing brace (OVOS-INTENT-1 §3)
    _trailing_punct = ''.join(c for c in string.punctuation if c not in '{}<>')
    utterances = [u.rstrip(_trailing_punct) for u in utterances]
    # Stem words if stemmer is provided
    if stemmer is not None:
        utterances = stemmer.stem_sentences(utterances)
    # Deduplicate the list
    utterances = deduplicate_list(utterances, keep_order=keep_order)
    return utterances


class Stemmer:
    """
    A simple wrapper around the Snowball stemmer for various languages.

    Attributes:
        LANGS (dict): A dictionary mapping language codes to Snowball stemmer language names.
    """
    LANGS = {'ar': 'arabic', 'eu': 'basque', 'ca': 'catalan', 'da': 'danish', 'nl': 'dutch', 'en': 'english',
             'fi': 'finnish', 'fr': 'french', 'de': 'german', 'el': 'greek', 'hi': 'hindi', 'hu': 'hungarian',
             'id': 'indonesian', 'ga': 'irish', 'it': 'italian', 'lt': 'lithuanian', 'ne': 'nepali',
             'no': 'norwegian', 'pt': 'portuguese', 'ro': 'romanian', 'ru': 'russian', 'sr': 'serbian',
             'es': 'spanish', 'sv': 'swedish', 'ta': 'tamil', 'tr': 'turkish'}

    def __init__(self, lang: str):
        """
        Initialize the stemmer for a given language.

        Args:
            lang (str): The language code for stemming.

        Raises:
            ValueError: If the language is unsupported.
        """
        lang2 = closest_lang(lang, list(self.LANGS))
        if lang2 is None:
            raise ValueError(f"unsupported language: {lang}")
        self.snowball = snowballstemmer.stemmer(self.LANGS[lang2])

    @classmethod
    def supports_lang(cls, lang: str) -> bool:
        """
        Check if the given language is supported by the stemmer.

        Args:
            lang (str): The language code to check.

        Returns:
            bool: True if the language is supported, False otherwise.
        """
        return closest_lang(lang, list(cls.LANGS)) is not None

    def stem_sentence(self, sentence: str) -> str:
        """
        Stem a single sentence.

        Args:
            sentence (str): The sentence to stem.

        Returns:
            str: The stemmed sentence.
        """
        return _cached_stem_sentence(self.snowball, sentence)

    def stem_sentences(self, sentences: List[str]) -> List[str]:
        """
        Stem a list of sentences.

        Args:
            sentences (List[str]): The list of sentences to stem.

        Returns:
            List[str]: The list of stemmed sentences.
        """
        return [self.stem_sentence(s) for s in sentences]


@lru_cache()
def _cached_stem_sentence(stemmer, sentence: str) -> str:
    """
    Cache the stemming of a single sentence to optimize repeated calls.

    Args:
        stemmer: The stemmer instance to use.
        sentence (str): The sentence to stem.

    Returns:
        str: The stemmed sentence.
    """
    stems = stemmer.stemWords(sentence.split())
    return " ".join(stems)


def _legacy_skill_id(message: Message, handler: str) -> Optional[str]:
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
    skill_id = message.context.get("skill_id")
    payload_skill_id = message.data.get("skill_id")
    if payload_skill_id and skill_id and payload_skill_id != skill_id:
        LOG.warning(f"[{handler}] message.data['skill_id']={payload_skill_id!r} "
                    f"differs from message.context['skill_id']={skill_id!r}; "
                    f"using the context value on the legacy wire")
    return skill_id


def _spec_skill_id(message: Message, handler: str) -> Optional[str]:
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
    source_id = message.context.get("skill_id")
    if skill_id and source_id and skill_id != source_id:
        LOG.debug(f"[{handler}] source={source_id!r} acting on "
                  f"target={skill_id!r} (OVOS-INTENT-4 §3.2)")
    return skill_id


def _closest_typed_entry(entries, utterance, bound, used=None):
    """The listed entry that best covers what the template bound.

    Overlap, not equality: the template's guess and the parser's span usually
    share most of their characters and disagree at an edge, which is the case
    worth correcting. With nothing bound, or nothing overlapping, no entry
    applies -- the map states readings in the order they occur and states no
    preference between them (OVOS-INTENT-1 §5.6).

    Args:
        entries: candidate entries for the slot's declared type.
        utterance: the utterance the spans were computed on.
        bound: the surface text the template already bound.
        used: optional set of entry ids already assigned to another slot of
            the same type; those entries are skipped so two slots of one type
            never collapse onto one entry.

    Returns:
        The best matching entry, or ``None`` when none applies.
    """
    ordered = sorted(entries, key=lambda e: (e["span"][0], e["span"][1]))
    used = used or set()
    if not bound:
        return None
    best, best_overlap = None, 0
    # The bound surface comes from lowercased text, but the spans count code
    # points of the original utterance. ``str.lower`` does not keep length
    # ("\u0130" lowercases to two code points), so search the lowered string
    # and map every hit back to original offsets before comparing spans.
    lower, origin = [], []
    for i, ch in enumerate(utterance):
        folded = ch.lower()
        lower.append(folded)
        origin.extend([i] * len(folded))
    lower = "".join(lower)
    token = bound.lower()
    pos = lower.find(token)
    while pos != -1:
        start = origin[pos]
        end = origin[pos + len(token) - 1] + 1
        for entry in ordered:
            if id(entry) in used:
                continue
            lo, hi = entry["span"]
            overlap = min(end, hi) - max(start, lo)
            if overlap > best_overlap:
                best, best_overlap = entry, overlap
        pos = lower.find(token, pos + 1)
    return best


class PadatiousPipeline(ConfidenceMatcherPipeline):
    """Service class for padatious intent matching."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None,
                 engine_class: Optional[PadatiousEngine] = None):
        intent_config = Configuration().get('intents', {})
        config = config or intent_config.get("ovos-padatious-pipeline-plugin") or intent_config.get("padatious") or dict()
        super().__init__(bus, config)
        try:
            faulthandler.enable()  # Enables crash logging
        except Exception:
            pass # happens in unittests and such
        self.lock = RLock()
        self._train_spawn_lock = RLock()
        self._background_trainer: Optional[Thread] = None
        core_config = Configuration()
        self.lang = standardize_lang(core_config.get("lang", "en-US"))
        langs = core_config.get('secondary_langs') or []
        langs = [standardize_lang(l) for l in langs]
        if self.lang not in langs:
            langs.append(self.lang)

        self.conf_high = self.config.get("conf_high") or 0.95
        self.conf_med = self.config.get("conf_med") or 0.8
        self.conf_low = self.config.get("conf_low") or 0.5

        engine_class = engine_class or DomainIntentContainer if self.config.get("domain_engine") else IntentContainer
        LOG.info(f"Padatious class: {engine_class.__name__}")

        self.remove_punct = self.config.get("cast_to_ascii", False)
        use_stemmer = self.config.get("stem", False)
        self.engine_class = engine_class or IntentContainer
        intent_cache = expanduser(self.config.get('intent_cache') or
                                  f"{xdg_data_home()}/{get_xdg_base()}/intent_cache")
        if self.engine_class == DomainIntentContainer:
            # allow user to switch back and forth without retraining
            # cache is cheap, training isn't
            intent_cache += "_domain"
        if use_stemmer:
            intent_cache += "_stemmer"
        if self.remove_punct:
            intent_cache += "_normalized"
        self.containers = {lang: self.engine_class(cache_dir=f"{intent_cache}/{lang}",
                                                   disable_padaos=self.config.get("disable_padaos", False),
                                                   inference_workers=self.config.get("inference_workers"))
                           for lang in langs}

        # pre-load any cached intents
        for container in self.containers.values():
            try:
                container.instantiate_from_disk()
            except Exception as e:
                LOG.error(f"Failed to pre-load cached intents: {str(e)}")

        if use_stemmer:
            self.stemmers = {lang: Stemmer(lang)
                             for lang in langs if Stemmer.supports_lang(lang)}
        else:
            self.stemmers = {}

        self.first_train = Event()
        self.finished_training_event = Event()
        self.finished_training_event.set()  # is cleared when training starts

        # Per-lang consecutive compile-failure tracking for the background
        # worker's backoff (see _train_sync/_train_worker): a persistently
        # raising compile must not retry at the worker's tight poll rate
        # forever, spamming an ERROR traceback and a spurious
        # ``mycroft.skills.trained`` on every pass.
        self._compile_fail_counts: Dict[str, int] = defaultdict(int)
        self._compile_backoff_until: Dict[str, float] = {}
        self._compile_giveup: set = set()

        # ``blacklisted_labels``: intent labels this plugin must never train
        # or match, e.g. so a neural (m2v) tier can front the default skills'
        # label set and padatious only handles user-installed skills it owns.
        # Entries are matched against the SAME canonical ``<skill_id>:<name>``
        # form registration collapses onto (see ``_dealias_intent_name``), and
        # may be an exact id or an fnmatch glob (``<skill_id>:*`` blacklists
        # a whole skill). Defaults to empty: shipped behaviour is unchanged.
        # Routed through the same canonicalization as session
        # blacklisted_intents so a legacy ``.intent``-suffixed entry (or a
        # glob ending in ``.intent``) still matches the canonical
        # registration instead of silently matching nothing.
        self._label_blacklist = tuple(_canonicalize_blacklist(
            frozenset(self.config.get("blacklisted_labels") or []),
            context="blacklisted_labels config"))

        self.registered_intents = []
        self.registered_entities = []
        self._skill2intent = defaultdict(list)
        self.max_words = 50  # if an utterance contains more words than this, don't attempt to match

        # OVOS-INTENT-4 §8.5 enable/disable: disable is session-scoped
        # (§11.3) and never touches the shared padatious container, which
        # has no per-session notion of registration. _intent_definitions
        # retains the register Message of every registered intent (full
        # name -> Message), used to answer §8 introspection queries.
        # _disabled_intents holds the runtime gate as a set of
        # (session_id, full_intent_name) pairs; calc_intent folds in only
        # the pairs matching the requesting message's session.
        self._intent_definitions = {}
        self._disabled_intents = set()

        # OVOS-CONTEXT-1 §6/§6.1 requires_context / excludes_context gating.
        # Registration MAY carry these declarations; they are stored per
        # registered intent (keyed by the internal ``<skill_id>:<name>``) and
        # evaluated at match time via the shared ``gate_satisfied`` helper.
        # Retained across the disable/enable lifecycle (mirrors
        # _intent_definitions); dropped only on deregister.
        self._intent_context_gates = {}

        # OVOS-CONTEXT-1 §7 uniform slot fill: the declared template slots of
        # each registered intent, keyed by the internal ``<skill_id>:<name>``.
        # Any declared slot the utterance leaves unresolved is filled from a
        # live ``session.intent_context`` entry, independent of requires_context.
        self._intent_slots = {}

        # INTENT-2 §4.3 per-slot value blacklist: ``{slot: [values]}`` carried
        # in the registration payload. A slot the utterance binds to a
        # blacklisted value (whole-word-sequence) is treated as UNRESOLVED so
        # the §7 context candidate fills it. Anaphoric pronouns are supplied
        # here as a locale resource rather than hardcoded.
        self._intent_slot_blacklists = {}
        self._intent_slot_types = {}

        # legacy registration contract (kept for back-compat)
        self.bus.on('padatious:register_intent', self.register_intent)
        self.bus.on('padatious:register_entity', self.register_entity)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)
        self.bus.on('intent.service.padatious.get', self.handle_get_padatious)
        self.bus.on('intent.service.padatious.manifest.get', self.handle_padatious_manifest)
        self.bus.on('intent.service.padatious.entities.manifest.get', self.handle_entity_manifest)
        self.bus.on('mycroft.skills.train', self.train)

        # OVOS-INTENT-4 spec registration contract (in addition to legacy).
        # Padatious is a TEMPLATE engine, so register.template is its primary
        # consumed topic; keyword registrations are ignored by design (§11).
        self.bus.on(SpecMessage.INTENT_REGISTER_TEMPLATE, self.handle_register_template)
        self.bus.on(SpecMessage.ENTITY_REGISTER, self.handle_register_entity_spec)
        self.bus.on(SpecMessage.INTENT_DEREGISTER, self.handle_deregister_intent_spec)
        self.bus.on(SpecMessage.ENTITY_DEREGISTER, self.handle_deregister_entity_spec)
        self.bus.on(SpecMessage.SKILL_DEREGISTER, self.handle_deregister_skill_spec)
        self.bus.on(SpecMessage.INTENT_ENABLE, self.handle_enable_intent_spec)
        self.bus.on(SpecMessage.INTENT_DISABLE, self.handle_disable_intent_spec)

        LOG.debug('Loaded Padatious intent pipeline')

    @property
    def padatious_config(self) -> Dict:
        log_deprecation("self.padatious_config is deprecated, access self.config directly instead", "2.0.0")
        return self.config

    @padatious_config.setter
    def padatious_config(self, val):
        log_deprecation("self.padatious_config is deprecated, access self.config directly instead", "2.0.0")
        self.config = val

    def _is_blacklisted_label(self, name: str) -> bool:
        """Check a canonical ``<skill_id>:<name>`` label against the
        ``blacklisted_labels`` config (exact ids and fnmatch globs, e.g.
        ``some-skill.openvoiceos:*`` blacklists a whole skill)."""
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self._label_blacklist)

    def _normalize_for_match(self, utterances, lang: str) -> List[str]:
        """Normalize candidates exactly as ``_match_level`` does before matching."""
        lang = standardize_lang(lang)
        return normalize_utterances(utterances, lang,
                                    stemmer=self.stemmers.get(lang),
                                    keep_order=True,
                                    cast_to_ascii=self.remove_punct)

    def _match_level(self, utterances, limit, lang=None, message: Optional[Message] = None) -> Optional[
        IntentHandlerMatch]:
        """Match intent and make sure a certain level of confidence is reached.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
            limit (float): required confidence level.
        """
        LOG.debug(f'Padatious Matching confidence > {limit}')
        lang = standardize_lang(lang or self.lang)

        utterances = self._normalize_for_match(utterances, lang)
        padatious_intent = self.calc_intent(utterances, lang, message)
        if padatious_intent is not None and padatious_intent.conf > limit:
            skill_id = padatious_intent.name.split(':')[0]
            return IntentHandlerMatch(
                match_type=padatious_intent.name,
                match_data=padatious_intent.matches,
                skill_id=skill_id,
                utterance=padatious_intent.sent)

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_high, lang, message)

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_med, lang, message)

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_low, lang, message)

    def train(self, message=None):
        """Perform padatious training.

        Training NEVER runs on the calling thread, including a pipeline's
        very first pass ever - the ``mycroft.skills.train`` handler (this
        method) and every registration handler (``register_intent`` et al)
        all pump messages synchronously on the same bus-connection thread
        (see ``MessageBusClient.on_message``), so blocking here for the
        full compile+train duration - tens of seconds to minutes on a large
        skill set, per the ser9 field trace - would stall every other bus
        message (including the ``intent.service.padatious.*`` getters,
        which must answer immediately) right along with it. The one
        exception is ``instant_train`` mode, which explicitly promises the
        model reflects a registration by the time the call returns; that
        mode is an opt-in trade-off the caller accepts. Everywhere else,
        training is handed to a single background worker and this call
        returns immediately; queries keep being served against whatever the
        neural tier's own cache-hit-loaded state already provides (see
        ``IntentContainer._train_in_background``) until the pass lands.
        Readiness is reported via the ``mycroft.skills.trained`` bus event,
        which ovos-core (and other completion-waiters) block on instead.

        Args:
            message (Message): optional triggering message
        """
        # ``needs_compile`` also catches a padaos-only dirty container: a
        # hash-cache-hit registration replay never sets ``must_train`` (see
        # IntentContainer.add_intent), but padaos.add_intent/add_entity have
        # no cache-aware skip of their own and always leave
        # ``padaos.must_compile`` True. Gating solely on ``must_train`` here
        # left that padaos compile stuck pending until the first live query
        # forced it synchronously on the bus thread (ser9 field trace).
        if not any(engine.needs_compile for engine in self.containers.values()):
            self.bus.emit(Message('mycroft.skills.trained'))
            return

        if self.config.get("instant_train", False):
            self._train_sync()
            return

        self._spawn_background_trainer()

    def _spawn_background_trainer(self) -> None:
        """Ensure the single background training worker is running.

        Never blocks and never trains on the calling thread itself - it
        only starts (or confirms already-running) ``_train_worker`` on its
        own daemon thread. Shared by ``train()``'s own background branch
        and by ``wait_until_trained()``, which must be able to make sure a
        pass is actually scheduled without ever calling ``_train_sync``
        (that trains on whichever thread calls it) itself.
        """
        with self._train_spawn_lock:
            if self._background_trainer is not None and self._background_trainer.is_alive():
                return
            self._background_trainer = Thread(target=self._guarded_train_worker, daemon=True)
            self._background_trainer.start()

    def _retire(self) -> None:
        """Drop the worker handle so the next ``_spawn_background_trainer``
        starts a fresh thread. Callers must hold ``_train_spawn_lock``."""
        self._background_trainer = None

    def _guarded_train_worker(self) -> None:
        """Run the worker, releasing its handle however it ends.

        ``_train_worker`` retires itself under the spawn lock on its normal
        exit, which is what keeps that exit atomic against a registration
        arriving at the same moment. An unexpected raise would otherwise
        leave a dead thread recorded as the current worker for as long as
        ``is_alive()`` takes to catch up, so the handle is dropped here too.
        """
        try:
            self._train_worker()
        finally:
            with self._train_spawn_lock:
                if self._background_trainer is current_thread():
                    self._retire()

    # Backoff schedule for a lang container whose compile keeps raising:
    # 2s, 4s, 8s, ... capped at 5 minutes, so a persistently broken compile
    # settles at one attempt every 5 minutes instead of retrying at
    # ``_wait_for_quiet``'s tight cadence forever.
    _COMPILE_BACKOFF_BASE_S = 2.0
    _COMPILE_BACKOFF_CAP_S = 300.0
    _COMPILE_MAX_CONSECUTIVE_FAILURES = 5

    def _rearm_training(self, lang: str) -> None:
        """Reset a lang's compile-failure backoff state and make sure a
        compile is actually scheduled for the registration that just landed.

        A registration/entity change is new information the failed compile
        never saw, so a container that had been given up on (see
        ``_train_sync``/``_train_worker``) deserves a fresh run of attempts
        rather than staying parked until process restart.

        Clearing the backoff only decides *how* a pass would be retried; it
        does not schedule one. During boot ``first_train`` is still unset
        and ``instant_train`` is off by default, so ``register_intent``
        trains on neither path and the dirty container had nothing left to
        compile it until some later live query happened to drive training
        itself - leaving every intent registered at boot unmatchable in the
        meantime. Arming the worker here ties the compile to the
        registration that caused it. The worker still debounces the boot
        wave into as few passes as possible (see
        ``IntentContainer._wait_for_quiet``) and still runs entirely off
        the calling thread.
        """
        self._compile_fail_counts.pop(lang, None)
        self._compile_backoff_until.pop(lang, None)
        self._compile_giveup.discard(lang)
        self._spawn_background_trainer()

    def _train_worker(self) -> None:
        """Background-thread entry point for ``train()``: waits for a quiet
        window (see ``IntentContainer._wait_for_quiet``) before each pass so
        a registration wave that trickles in over time - e.g. a slow,
        serialized skill boot, or ovos-core's periodic registration
        reconciliation - coalesces into as few full retrains as possible,
        then keeps going until nothing is left dirty.

        A lang whose compile keeps raising is retried with exponential
        backoff (see ``_train_sync``) and, after
        ``_COMPILE_MAX_CONSECUTIVE_FAILURES`` in a row, is dropped from this
        loop entirely (``_compile_giveup``) until a registration touching
        that lang resets its failure count - otherwise this loop would spin
        forever at ``_wait_for_quiet``'s cadence on a container that can
        never succeed.
        """
        while True:
            pending = [lang for lang, engine in self.containers.items()
                      if engine.needs_compile and lang not in self._compile_giveup]
            if not pending:
                # Retiring the worker has to be atomic against
                # _spawn_background_trainer, which is now the only thing
                # that schedules a pass: a registration landing between
                # this check and the thread actually dying would otherwise
                # find is_alive() still True, spawn nothing, and strand
                # that container dirty until some later registration.
                # Clearing the handle under the spawn lock makes the next
                # spawn start a fresh worker instead.
                with self._train_spawn_lock:
                    if any(engine.needs_compile and lang not in self._compile_giveup
                           for lang, engine in self.containers.items()):
                        continue
                    self._retire()
                    return
            now = time.monotonic()
            due = [lang for lang in pending if self._compile_backoff_until.get(lang, 0) <= now]
            if not due:
                time.sleep(max(0.05, min(self._compile_backoff_until[lang] - now for lang in pending)))
                continue
            for lang in due:
                self.containers[lang]._wait_for_quiet()
            self._train_sync(only_langs=set(due))

    def _train_sync(self, only_langs: Optional[set] = None) -> None:
        """Blocking training pass - called either from the background
        worker's own thread (the normal case) or directly on the calling
        thread under ``instant_train`` (an explicit, opt-in exception -
        see ``train``).

        @param only_langs: restrict this pass to these langs (used by the
            background worker to skip langs still in their backoff window);
            ``None`` (the default, used by ``instant_train`` and any direct
            caller) attempts every dirty lang.
        """
        # wait for any already ongoing training
        # padatious doesnt like threads
        if not self.finished_training_event.is_set():
            self.finished_training_event.wait()
        with self.lock:
            target_langs = [lang for lang in self.containers
                            if self.containers[lang].needs_compile
                            and (only_langs is None or lang in only_langs)]
            if not target_langs:
                # LOG.debug(f"Nothing new to train for padatious")
                # inform the rest of the system to not wait for training finish
                self.bus.emit(Message('mycroft.skills.trained'))
                self.finished_training_event.set()
                return
            self.finished_training_event.clear()
            any_success = False
            for lang in target_langs:
                try:
                    #LOG.debug(f"Training padatious for lang '{lang}'")
                    self.containers[lang].train()
                except Exception as e:
                    # a raising _compile()/train() must never leave
                    # finished_training_event cleared - every later
                    # _train_sync call (including from wait_until_trained's
                    # own polling, which never trains itself) would then
                    # block forever on its untimed wait() above.
                    # needs_compile stays True for whichever container
                    # never finished, so the background worker's own retry
                    # loop (_train_worker) picks it back up - with backoff -
                    # on a later pass instead of silently giving up.
                    self._compile_fail_counts[lang] += 1
                    n = self._compile_fail_counts[lang]
                    backoff = min(self._COMPILE_BACKOFF_BASE_S * (2 ** (n - 1)), self._COMPILE_BACKOFF_CAP_S)
                    self._compile_backoff_until[lang] = time.monotonic() + backoff
                    LOG.exception(f"padatious training pass failed for lang {lang!r}: {e}")
                    if n >= self._COMPILE_MAX_CONSECUTIVE_FAILURES and lang not in self._compile_giveup:
                        self._compile_giveup.add(lang)
                        LOG.error(
                            f"padatious training for lang {lang!r} failed {n} times in a "
                            f"row; giving up until the next registration change for that lang")
                else:
                    self._compile_fail_counts[lang] = 0
                    self._compile_backoff_until.pop(lang, None)
                    any_success = True
            # ``mycroft.skills.trained`` promises the model reflects the
            # latest registrations; emitting it on a pass that trained
            # nothing successfully would be a false "ready" signal (dev's
            # pre-#124 behaviour never reached its own emit on a raising
            # compile either, since the exception was uncaught there).
            #
            # ``train()`` returning without raising is not the same as the
            # container being clean: a registration can land after its
            # snapshot was taken but before it returns (see
            # ``IntentContainer._train_generation``/padaos'
            # ``_mutation_gen``), in which case ``must_train``/
            # ``padaos.must_compile`` are correctly left set for the next
            # pass to pick up - but ``any_success`` alone does not see
            # that. padaos is the far likelier of the two to still be
            # dirty here: every ``padaos.add_intent``/``add_entity`` call
            # marks it unconditionally, with no cache-aware skip of its
            # own, so a registration trickling in during a compile leaves
            # it as a second, independent "not actually done yet" signal
            # this check used to ignore. Only announce readiness for a
            # container this pass touched once it is ACTUALLY clean.
            still_dirty = any(self.containers[lang].needs_compile for lang in target_langs)
            if any_success and not still_dirty:
                self.bus.emit(Message('mycroft.skills.trained'))
            self.finished_training_event.set()

        if any_success:
            # Training changes the model; stale LRU cache entries must be
            # evicted so that the next call to calc_intent reflects the
            # updated state.
            _calc_padatious_intent.cache_clear()

        if not self.first_train.is_set():
            self.first_train.set()

    def wait_until_trained(self, timeout: Optional[float] = None) -> bool:
        """Block until every language container is fully compiled/trained.

        This is a **test/tooling synchronization helper**, not something a
        skill or a production caller needs: registration is deliberately
        asynchronous (see ``train()``/``IntentContainer._train_in_background``,
        which never trains on the calling thread even for a container that
        has never trained at all) so a query is never blocked behind a
        compile, and readiness is normally observed via the
        ``mycroft.skills.trained`` bus event. A test harness that registers
        an intent and then immediately wants to query it deterministically
        - without polling ``needs_compile`` on internal containers itself -
        should call this instead.

        This method JOINS the background worker (ensuring one is actually
        running via ``_spawn_background_trainer``, then polling
        ``needs_compile`` against the deadline); it never calls
        ``_train_sync``/``train()`` itself and so never trains ON THE
        CALLING THREAD, and the timeout is honoured even while a pass is
        already in flight - an earlier version of this method called
        ``_train_sync`` in a loop, whose untimed
        ``finished_training_event.wait()`` made the ``timeout`` argument a
        no-op whenever a pass was in progress.

        @param timeout: seconds to wait before giving up, or ``None`` to
            wait forever.
        @return: True once every container reports ``needs_compile`` False,
            False if ``timeout`` elapsed first.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        if not any(engine.needs_compile for engine in self.containers.values()):
            return True
        self._spawn_background_trainer()
        poll_interval = 0.05
        while any(engine.needs_compile for engine in self.containers.values()):
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                time.sleep(min(poll_interval, remaining))
            else:
                time.sleep(poll_interval)
        return True

    @deprecated("'wait_and_train' has been deprecated, use 'train' directly", "2.0.0")
    def wait_and_train(self):
        """Wait for minimum time between training and start training."""
        self.train()

    def __detach_intent(self, intent_name):
        """ Remove an intent if it has been registered.

        Args:
            intent_name (str): intent identifier
        """
        # Detach/removal must key off the same canonical name registration
        # collapsed onto, so unregistering by either the legacy `.intent`
        # alias or the OVOS-INTENT-4 canonical id works (ovos-core#831).
        intent_name = _dealias_intent_name(intent_name)
        if intent_name in self.registered_intents:
            self.registered_intents.remove(intent_name)
            for lang in self.containers:
                for skill_id, intents in self._skill2intent.items():
                    if intent_name in intents:
                        try:
                            if isinstance(self.containers[lang], DomainIntentContainer):
                                self.containers[lang].remove_domain_intent(skill_id, intent_name)
                            else:
                                self.containers[lang].remove_intent(intent_name)
                        except Exception as e:
                            LOG.error(f"Failed to remove intent {intent_name} for skill {skill_id}: {str(e)}")

    def handle_detach_intent(self, message):
        """Messagebus handler for detaching padatious intent.

        Args:
            message (Message): message triggering action
        """
        self.__detach_intent(message.data.get('intent_name'))
        # Intent roster changed; evict stale cache so next match reflects removal.
        _calc_padatious_intent.cache_clear()
        # In instant_train mode, retrain immediately so the model also
        # forgets the intent — otherwise the cleared cache repopulates from
        # the still-trained model on the next match.
        if self.config.get("instant_train", False):
            self.train(message)

    def handle_detach_skill(self, message):
        """Messagebus handler for detaching all intents for skill.

        Args:
            message (Message): message triggering action
        """
        skill_id = _legacy_skill_id(message, "handle_detach_skill")
        if not skill_id:
            LOG.warning("[handle_detach_skill] rejected: missing "
                        "message.context['skill_id']")
            return
        for i in self._skill2intent[skill_id]:
            self.__detach_intent(i)
        # Intent roster changed; evict stale cache so next match reflects removal.
        _calc_padatious_intent.cache_clear()
        # See handle_detach_intent — retrain in instant_train mode so the
        # underlying model state matches the registered_intents list.
        if self.config.get("instant_train", False):
            self.train(message)

    def _unpack_object(self, message):
        """convert message to training data"""
        skill_id = _legacy_skill_id(message, "_unpack_object")
        if not skill_id:
            LOG.warning("[_unpack_object] rejected: missing "
                        "message.context['skill_id']")
            return
        file_name = message.data.get('file_name')
        samples = message.data.get("samples")
        name = message.data['name']
        lang = message.data.get('lang', self.lang)
        lang = standardize_lang(lang)
        blacklisted_words = message.data.get('blacklisted_words', [])
        if (not file_name or not isfile(file_name)) and not samples:
            LOG.error('Could not find file ' + file_name)
            return

        if not samples and isfile(file_name):
            with open(file_name) as f:
                samples = [line.strip() for line in f.readlines()]

        samples = deduplicate_list(flatten_list([
            expand_or_skip(s, f"intent/entity {name!r} (skill {skill_id!r})")
            for s in samples
        ]))
        if not samples:
            # every line was malformed and skipped: registering with zero
            # samples would silently create a dead intent/entity that can
            # never match (conf 0.0 forever) instead of surfacing the
            # problem, so refuse the registration outright.
            # OVOS-INTENT-4 §5.3: the rejecting plugin logs at WARN.
            LOG.warning(
                "intent/entity %r (skill %r, lang %r, topic %r) has no valid "
                "samples after skipping malformed template lines - not "
                "registering",
                name, skill_id, lang, message.msg_type,
            )
            return
        if lang in self.stemmers:
            stemmer = self.stemmers[lang]
        else:
            stemmer = None
        samples = normalize_utterances(samples, lang,
                                       stemmer=stemmer,
                                       keep_order=False,
                                       cast_to_ascii=self.remove_punct)
        return lang, skill_id, name, samples, blacklisted_words

    def register_intent(self, message):
        """Messagebus handler for registering intents.

        Args:
            message (Message): message triggering action
        """
        skill_id = _legacy_skill_id(message, "register_intent")
        if not skill_id:
            LOG.warning("[register_intent] rejected: missing "
                        "message.context['skill_id']")
            return
        message.data["skill_id"] = skill_id

        # ovos-workshop >= 9.3 dual-registers one logical intent under both
        # the legacy ``padatious:register_intent`` contract (name suffixed
        # ``.intent``) and the OVOS-INTENT-4 spec contract (suffix-less,
        # routed here via handle_register_template). Collapse the alias to
        # the canonical name HERE, at registration time, so both wire
        # messages index a single engine entry instead of two matchable
        # duplicates (ovos-core#831). This plugin owns its own back-compat.
        message.data['name'] = _dealias_intent_name(message.data['name'])

        if self._is_blacklisted_label(message.data['name']):
            LOG.debug(f"Padatious intent '{message.data['name']}' matches "
                      f"'blacklisted_labels' config; registration ignored")
            return

        if message.data['name'] not in self._skill2intent[skill_id]:
            self._skill2intent[skill_id].append(message.data['name'])
        # retain the registration so an INTENT-4 enable (§8.5) can re-train
        # the intent after a disable detached it
        self._intent_definitions[message.data['name']] = message

        # OVOS-CONTEXT-1 §6: retain any requires/excludes gating declarations
        # keyed by the internal intent name. Only stored when present so
        # intents without a gate keep unchanged (ungated) behavior.
        requires = message.data.get("requires_context")
        excludes = message.data.get("excludes_context")
        if requires or excludes:
            self._intent_context_gates[message.data['name']] = (requires, excludes)

        lang = message.data.get('lang', self.lang)
        lang = standardize_lang(lang)

        # OVOS-CONTEXT-1 §7: record the declared template slots so an
        # unresolved slot can be filled from context at match time.
        # Registration is per language (a multi-lang skill's native_langs
        # loop registers the same intent name once per lang), so this is
        # keyed by (lang, name) rather than name alone.
        samples = message.data.get('samples', [])
        # INTENT-4 6.1: every slot name in a payload is the BARE name, so a
        # `{duration:length}` placeholder declares `length`. Padatious binds
        # the bare name too, and recording the prefixed one here left the
        # context fill looking up a key nothing ever binds.
        slots = {name.split(":", 1)[-1]
                 for sample in samples
                 for name in _SLOT_RE.findall(sample)}
        if slots:
            self._intent_slots[(lang, message.data['name'])] = frozenset(slots)

        # INTENT-1 5.6: the types a template declares, so a typed placeholder
        # can be bound where the typed-slot map says it may. The payload
        # carries them (INTENT-4 6.1) and the templates state them; the
        # payload wins and the templates fill the gap.
        declared = dict(declared_slot_types(samples) if samples else {})
        payload_types = message.data.get('slot_types')
        if isinstance(payload_types, dict):
            declared.update({str(k): str(v) for k, v in payload_types.items()})
        declared = {k: v for k, v in declared.items() if v in REGISTERED_TYPES}
        if declared:
            self._intent_slot_types[(lang, message.data['name'])] = declared

        # INTENT-2 §4.3: a per-slot value blacklist rides in the payload keyed
        # by slot name. Accept ``slot_blacklist`` or a dict-valued ``blacklist``
        # (a list-valued ``blacklist`` is the template-method suppression
        # vocabulary and is left untouched). Keyed by (lang, name): each
        # language's registration carries its own blacklisted words and must
        # not clobber another language's entry for the same intent name.
        slot_blacklist = message.data.get('slot_blacklist')
        if slot_blacklist is None and isinstance(message.data.get('blacklist'), dict):
            slot_blacklist = message.data.get('blacklist')
        if slot_blacklist:
            self._intent_slot_blacklists[(lang, message.data['name'])] = {
                slot: [str(v) for v in values]
                for slot, values in slot_blacklist.items()}

        if lang in self.containers:
            if message.data['name'] not in self.registered_intents:
                self.registered_intents.append(message.data['name'])
            LOG.debug('Registering Padatious intent: ' + message.data['name'])
            unpacked = self._unpack_object(message)
            if unpacked is None:
                return
            lang, skill_id, name, samples, blacklisted_words = unpacked
            if self.engine_class == DomainIntentContainer:
                self.containers[lang].add_domain_intent(skill_id, name, samples,
                                                        blacklisted_words=blacklisted_words)
            else:
                self.containers[lang].add_intent(name, samples,
                                                 blacklisted_words=blacklisted_words)
            self._rearm_training(lang)
            # A re-registration (e.g. new samples replacing an existing
            # intent's) must retire the old regex/model answer immediately,
            # not only once the next compile lands - otherwise a query
            # served between this call and that compile keeps matching the
            # stale definition at conf 1.0 from the lru_cache.
            _calc_padatious_intent.cache_clear()

        if self.config.get("instant_train", False) or self.first_train.is_set():
            self.train(message)

    def register_entity(self, message):
        """Messagebus handler for registering entities.

        Args:
            message (Message): message triggering action
        """
        lang = message.data.get('lang', self.lang)
        lang = standardize_lang(lang)
        # ovos-workshop's register_entity_file() munges the entity name with a
        # trailing ``_<md5>``; match-time slot lookup uses the raw slot token,
        # so an un-collapsed name yields an unconstrained wildcard slot. Fold
        # it here, at registration time - this plugin owns its lookup contract
        # and this repairs every emitter vintage at once.
        message.data['name'] = _dealias_entity_name(message.data['name'])

        if lang in self.containers:
            # a dual-emitting emitter (>= 9.3) sends the same entity twice,
            # once per wire contract; both collapse to one canonical name, so
            # the manifest must hold exactly one entry for it
            self.registered_entities = [
                e for e in self.registered_entities
                if e.get("name") != message.data['name']
                or standardize_lang(e.get("lang") or self.lang) != lang]
            self.registered_entities.append(message.data)
            unpacked = self._unpack_object(message)
            if unpacked is None:
                return
            lang, skill_id, name, samples, _ = unpacked
            LOG.debug('Registering Padatious entity: ' + message.data['name'])
            if self.engine_class == DomainIntentContainer:
                self.containers[lang].add_domain_entity(skill_id, name, samples)
            else:
                self.containers[lang].add_entity(name, samples)
            self._rearm_training(lang)
            # See register_intent: a replaced entity's slot values must stop
            # matching immediately, not only after the next compile.
            _calc_padatious_intent.cache_clear()

    # ------------------------------------------------------------------ #
    # OVOS-INTENT-4 spec registration handlers                           #
    #                                                                    #
    # These translate the spec payloads (§§6-8) into the same internal   #
    # padatious registration calls the legacy handlers use, so both wire #
    # contracts feed one container. The internal padatious intent/entity #
    # name is the colon-joined ``<skill_id>:<name>`` the legacy contract #
    # already used as ``data['name']``.                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _spec_identity(message, name_field):
        """Pull (skill_id, name) from a §3.2 spec payload.

        Returns (skill_id, name, full_name) where ``full_name`` is the
        ``<skill_id>:<name>`` key padatious uses internally, or
        (None, None, None) when identity is missing.
        """
        skill_id = _spec_skill_id(message, "_spec_identity")
        name = message.data.get(name_field)
        if not skill_id or not name:
            return None, None, None
        # already-namespaced names are passed through unchanged
        full = name if name.startswith(f"{skill_id}:") else f"{skill_id}:{name}"
        return skill_id, name, full

    def handle_register_template(self, message):
        """Consume ``ovos.intent.register.template`` (OVOS-INTENT-4 §6).

        Maps the spec payload (skill_id, intent_name, lang, samples,
        blacklist) onto the legacy padatious registration via
        :meth:`register_intent`.
        """
        skill_id, intent_name, full = self._spec_identity(message, "intent_name")
        if full is None:
            LOG.warning(f"[{SpecMessage.INTENT_REGISTER_TEMPLATE}] rejected: "
                        f"missing skill_id/intent_name")
            return
        samples = message.data.get("samples")
        if not samples:  # §6.3 malformed: samples missing/empty
            LOG.warning(f"[{SpecMessage.INTENT_REGISTER_TEMPLATE}] rejected "
                        f"skill_id={skill_id} intent_name={intent_name} "
                        f"lang={message.data.get('lang')}: empty samples")
            return
        lang = standardize_lang(message.data.get("lang", self.lang))
        # §6 'blacklist' is the template-method suppression vocabulary;
        # padatious calls this 'blacklisted_words'.
        legacy = Message(
            "padatious:register_intent",
            data={"name": full, "samples": list(samples), "lang": lang,
                  "skill_id": skill_id,
                  "blacklisted_words": message.data.get("blacklist", []),
                  # OVOS-CONTEXT-1 §6: forward the optional gating declarations
                  # onto the internal registration so they are stored per intent.
                  "requires_context": message.data.get("requires_context"),
                  "excludes_context": message.data.get("excludes_context"),
                  # INTENT-2 §4.3: per-slot value blacklist keyed by slot name.
                  "slot_blacklist": message.data.get("slot_blacklist"),
                  # INTENT-4 §6.1 / INTENT-1 §5.6: the producer strips the
                  # type prefix from the samples and declares the types here,
                  # so this is the only place the engine can read them from.
                  "slot_types": message.data.get("slot_types")},
            context=dict(message.context, skill_id=skill_id))
        self.register_intent(legacy)

    def handle_register_entity_spec(self, message):
        """Consume ``ovos.entity.register`` (OVOS-INTENT-4 §7)."""
        skill_id, entity_name, full = self._spec_identity(message, "entity_name")
        if full is None:
            LOG.warning(f"[{SpecMessage.ENTITY_REGISTER}] rejected: "
                        f"missing skill_id/entity_name")
            return
        samples = message.data.get("samples")
        if not samples:  # §7.2 malformed: samples missing/empty
            LOG.warning(f"[{SpecMessage.ENTITY_REGISTER}] rejected "
                        f"skill_id={skill_id} entity_name={entity_name} "
                        f"lang={message.data.get('lang')}: empty samples")
            return
        lang = standardize_lang(message.data.get("lang", self.lang))
        legacy = Message(
            "padatious:register_entity",
            data={"name": full, "samples": list(samples), "lang": lang,
                  "skill_id": skill_id},
            context=dict(message.context, skill_id=skill_id))
        self.register_entity(legacy)

    def _spec_intent_names(self, message):
        """Resolve the full padatious intent name(s) targeted by a §8 payload.

        Returns the list of ``<skill_id>:<intent_name>`` keys to act on
        (``lang`` is ignored: padatious keys intents by name, training data
        is shared across the per-lang containers).
        """
        skill_id, intent_name, full = self._spec_identity(message, "intent_name")
        if full is None:
            return []
        return [full]

    def _spec_target_intent_names(self, message):
        """Resolve the full padatious intent name(s) targeted by
        ``ovos.intent.enable``/``ovos.intent.disable`` (OVOS-INTENT-4 §8.5).

        Unlike :meth:`_spec_intent_names`, these two topics are control
        messages, not ownership claims (§3.2): the payload ``skill_id``
        names the **target** skill whose intent is enabled/disabled, while
        ``context.skill_id`` names the **source** issuing the control and
        MAY legitimately differ (cross-skill control). The label is built
        from the payload's ``skill_id``.
        """
        skill_id = message.data.get("skill_id")
        intent_name = message.data.get("intent_name")
        if not skill_id or not intent_name:
            return []
        source_id = message.context.get("skill_id") if message.context else None
        if source_id and source_id != skill_id:
            LOG.debug(f"cross-skill control: source={source_id!r} "
                      f"target={skill_id!r} (OVOS-INTENT-4 §3.2)")
        full = intent_name if intent_name.startswith(f"{skill_id}:") else f"{skill_id}:{intent_name}"
        return [full]

    def handle_deregister_intent_spec(self, message):
        """Consume ``ovos.intent.deregister`` (OVOS-INTENT-4 §8.2)."""
        for full in self._spec_intent_names(message):
            self.__detach_intent(full)
            self._disabled_intents = {p for p in self._disabled_intents if p[1] != full}
            self._intent_context_gates.pop(full, None)
            # deregister targets every configured language, so drop the
            # (lang, name) keyed entries for each of them
            for lang in self.containers:
                self._intent_slots.pop((lang, full), None)
                self._intent_slot_blacklists.pop((lang, full), None)
                self._intent_slot_types.pop((lang, full), None)
        _calc_padatious_intent.cache_clear()
        if self.config.get("instant_train", False):
            self.train(message)

    def handle_deregister_entity_spec(self, message):
        """Consume ``ovos.entity.deregister`` (OVOS-INTENT-4 §8.3)."""
        skill_id, entity_name, full = self._spec_identity(message, "entity_name")
        if full is None:
            return
        for lang in self.containers:
            try:
                self.containers[lang].remove_entity(full)
            except Exception as e:
                LOG.debug(f"entity {full} not present in {lang}: {e}")
        self.registered_entities = [e for e in self.registered_entities
                                    if e.get("name") != full]
        _calc_padatious_intent.cache_clear()
        if self.config.get("instant_train", False):
            self.train(message)

    def handle_deregister_skill_spec(self, message):
        """Consume ``ovos.skill.deregister`` (OVOS-INTENT-4 §8.4).

        Removes every intent and entity owned by the skill.
        """
        skill_id = _spec_skill_id(message, "handle_deregister_skill_spec")
        if not skill_id:
            LOG.warning(f"[{SpecMessage.SKILL_DEREGISTER}] rejected: missing "
                        f"skill_id")
            return
        for full in list(self._skill2intent.get(skill_id, [])):
            self.__detach_intent(full)
            self._disabled_intents = {p for p in self._disabled_intents if p[1] != full}
            self._intent_context_gates.pop(full, None)
            # deregister targets every configured language, so drop the
            # (lang, name) keyed entries for each of them
            for lang in self.containers:
                self._intent_slots.pop((lang, full), None)
                self._intent_slot_blacklists.pop((lang, full), None)
                self._intent_slot_types.pop((lang, full), None)
        # drop the skill's entities too
        prefix = f"{skill_id}:"
        for lang in self.containers:
            for ent in [e.get("name") for e in self.registered_entities
                        if str(e.get("name", "")).startswith(prefix)]:
                try:
                    self.containers[lang].remove_entity(ent)
                except Exception as e:
                    LOG.debug(f"entity {ent} not present in {lang}: {e}")
        self.registered_entities = [e for e in self.registered_entities
                                    if not str(e.get("name", "")).startswith(prefix)]
        _calc_padatious_intent.cache_clear()
        if self.config.get("instant_train", False):
            self.train(message)

    def handle_disable_intent_spec(self, message):
        """Consume ``ovos.intent.disable`` (OVOS-INTENT-4 §8.5).

        Disable is session-scoped (§11.3): it never touches the shared
        padatious container, only records ``(session_id, full_name)`` so
        ``calc_intent`` excludes the intent from match candidacy for that
        session only. The registration itself is untouched, so other
        sessions keep matching it.
        """
        session_id = SessionManager.get(message).session_id
        for full in self._spec_target_intent_names(message):
            if full not in self._intent_definitions:
                LOG.warning(f"[{SpecMessage.INTENT_DISABLE}] no registered "
                            f"definition for {full}; nothing to disable")
                continue
            self._disabled_intents.add((session_id, full))  # no-op if already disabled
        _calc_padatious_intent.cache_clear()

    def handle_enable_intent_spec(self, message):
        """Consume ``ovos.intent.enable`` (OVOS-INTENT-4 §8.5).

        Discards the session's disable gate for the intent; the
        registration was never removed so there is nothing to re-register.
        """
        session_id = SessionManager.get(message).session_id
        for full in self._spec_target_intent_names(message):
            self._disabled_intents.discard((session_id, full))  # no-op if not disabled
        _calc_padatious_intent.cache_clear()

    def calc_intent(self, utterances: Union[str, List[str]], lang: Optional[str] = None,
                    message: Optional[Message] = None) -> Optional[PadatiousIntent]:
        """
        Get the best intent match for the given list of utterances. Utilizes a
        thread pool for overall faster execution. Note that this method is NOT
        compatible with Padatious, but is compatible with Padacioso.
        @param utterances: list of string utterances to get an intent for
        @param lang: language of utterances
        @return:
        """
        if isinstance(utterances, str):
            utterances = [utterances]  # backwards compat when arg was a single string
        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping padatious match")
            return None

        lang = lang or self.lang

        lang = self._get_closest_lang(lang)
        if lang is None:  # no intents registered for this lang
            return None

        sess = SessionManager.get(message)
        # Session is unhashable under ovos-bus-client 2.x, so it cannot be an
        # lru_cache key; pass the blacklists it carries as frozensets instead.
        # OVOS-INTENT-4 §8.5/§11.3: disable is session-scoped and must stop
        # matching THE INSTANT it is disabled, without touching the shared
        # padatious container - disable/enable are pure runtime gates keyed
        # by (session_id, full_name), not compile products. Only the pairs
        # matching this message's session are folded into the blacklist.
        disabled_here = frozenset(full for (sid, full) in self._disabled_intents
                                   if sid == sess.session_id)
        blacklisted_intents = frozenset(sess.blacklisted_intents or []) | disabled_here
        blacklisted_skills = frozenset(sess.blacklisted_skills or [])

        intent_container = self.containers.get(lang)
        # See _calc_padatious_intent's compiled_generation param: a query
        # answered before this container ever compiled must not keep
        # returning that cached "no match" forever once a (background)
        # pass actually lands.
        compiled_generation = getattr(intent_container, "compiled_generation", 0)
        intents = [_calc_padatious_intent(utt, intent_container, compiled_generation,
                                          blacklisted_intents, blacklisted_skills)
                   for utt in utterances]
        # blacklisted_labels is applied here, AFTER the cached call, rather
        # than as part of _calc_padatious_intent's lru_cache key (see that
        # function's docstring for why). A blacklisted label only ever
        # surfaces as the cached best match when a container trained it
        # before it was blacklisted (registration already refuses to train
        # one - see _is_blacklisted_label), so this only runs on that rare
        # hit, not on every query: it calls the SAME selection code via
        # ``.__wrapped__`` (lru_cache's cache-bypassing raw function),
        # widening blacklisted_intents with every blacklisted label seen so
        # far until the next-best surviving candidate comes back.
        if self._label_blacklist:
            widened = []
            for utt, i in zip(utterances, intents):
                seen = set()
                while i is not None and self._is_blacklisted_label(i.name):
                    seen.add(i.name)
                    i = _calc_padatious_intent.__wrapped__(
                        utt, intent_container, compiled_generation,
                        blacklisted_intents | frozenset(seen), blacklisted_skills)
                widened.append(i)
            intents = widened
        intents = [i for i in intents if i is not None]
        # OVOS-CONTEXT-1 §6/§6.1: drop any candidate whose requires/excludes
        # gating is not satisfied against the session's intent_context. The
        # shared helper handles liveness/scope/decay; owner_id is the intent's
        # skill_id (the private-scope default owner). Ungated intents pass.
        if intents and self._intent_context_gates:
            intent_context = getattr(sess, "intent_context", None) or {}
            kept = []
            for i in intents:
                gate = self._intent_context_gates.get(i.name)
                if gate is not None:
                    requires, excludes = gate
                    owner_id = i.name.split(":")[0]
                    if not gate_satisfied(intent_context, requires, excludes,
                                          owner_id=owner_id):
                        LOG.debug(f"Padatious intent '{i.name}' dropped: "
                                  f"OVOS-CONTEXT-1 gating not satisfied")
                        continue
                kept.append(i)
            intents = kept
        # select best
        if intents:
            best = max(intents, key=lambda k: k.conf)
            self._bind_typed_slots(best, message, lang)
            self._fill_context_slots(best, sess, lang)
            return best

    def _bind_typed_slots(self, intent: PadatiousIntent,
                          message: Optional[Message], lang: str) -> None:
        """OVOS-INTENT-1 5.6 -- bind a typed placeholder where the map allows.

        The map is a hint, not a vocabulary: it says where a datum of a kind
        was found and what it normalizes to, and an engine MAY use it to
        constrain where ``{type:name}`` matches. This engine prefers a listed
        span over the template's own guess, because a template counts words
        and a parser reads the datum -- "set a timer for twenty five minutes"
        gives the template no reason to stop before "minutes".

        An entry applies only to a candidate satisfying the span invariant
        ``utterance[start:end] == surface``, since the entries are computed
        over every candidate and share one map. Absent or malformed map,
        unknown type, or no entry that fits: the binding is left exactly as
        the template made it, which is the 3.4 degrade this engine already
        shipped.

        ``Match.slots[name]`` stays the surface string (PIPELINE-1 4.3); only
        which surface is bound changes.
        """
        declared = self._intent_slot_types.get((lang, intent.name))
        if not declared or message is None:
            return
        raw = message.data.get("typed_slots")
        if not isinstance(raw, dict) or not raw:
            return
        try:
            typed = drop_unregistered_typed_slots(raw)
            validate_typed_slots(typed)
        except MalformedTypedSlots as exc:
            LOG.warning(f"ignoring a malformed typed_slots map "
                        f"(INTENT-1 5.6): {exc}")
            return
        # OVOS-INTENT-1 §5.6: the map is shared by every candidate, and an
        # entry applies only to a candidate that satisfies the invariant. The
        # candidate that counts is the one this match was made from. Matching
        # ran on normalized text (``intent.sent``), and normalization changes
        # case, spacing and punctuation and drops duplicates, so no index
        # maps back. Select every raw candidate whose own normalized form is
        # the matched text. A candidate list that names none leaves the
        # template binding as it is.
        raw_candidates = message.data.get("utterances")
        if isinstance(raw_candidates, str):
            raw_candidates = [raw_candidates]
        if not isinstance(raw_candidates, list):
            return
        sent = intent.sent or ""
        candidates = [u for u in raw_candidates if isinstance(u, str) and
                      (u == sent or self._normalize_for_match([u], lang) == [sent])]
        if not candidates:
            return

        def holds(entry, utt):
            start, end = entry["span"]
            return utt[start:end] == entry["surface"]

        # the first matched candidate that any listed entry holds on
        utterance = next((u for u in candidates
                          if any(holds(e, u) for t in set(declared.values())
                                 for e in typed.get(t, []))),
                         candidates[0])
        matches = dict(intent.matches or {})
        used_entries: Dict[str, set] = defaultdict(set)
        for slot, type_name in declared.items():
            entries = [e for e in typed.get(type_name, [])
                       if holds(e, utterance)]
            if not entries:
                continue
            bound = matches.get(slot)
            chosen = _closest_typed_entry(entries, utterance, bound,
                                          used=used_entries[type_name])
            if chosen is None:
                continue
            used_entries[type_name].add(id(chosen))
            if chosen["surface"] == bound:
                continue
            LOG.debug(f"Padatious slot '{slot}' bound to the {type_name} span "
                      f"{chosen['surface']!r} rather than {bound!r} "
                      f"(INTENT-1 5.6)")
            matches[slot] = chosen["surface"]
        intent.matches = matches

    def _fill_context_slots(self, intent: PadatiousIntent, sess: Session, lang: str) -> None:
        """OVOS-CONTEXT-1 §7 — uniform context slot fill.

        For EVERY declared template slot of the matched intent, if a live
        non-null ``session.intent_context`` entry exists (private
        ``<skill_id>:name`` precedence over shared bare ``name``), fill the
        slot when the utterance left it unresolved. This is independent of
        requires_context, which gates only the presence flags.

        INTENT-2 §4.3: before the fill, a slot the utterance bound to a value
        listed in that slot's blacklist (e.g. an anaphoric pronoun) is dropped
        so it counts as unresolved and the context candidate takes over.
        """
        slot_names = self._intent_slots.get((lang, intent.name))
        if not slot_names:
            return
        matches = dict(intent.matches or {})

        # INTENT-2 §4.3: unresolve blacklisted slot values. The blacklist
        # matches by WHOLE-VALUE equality (normalized): a bare anaphoric
        # "it" is dropped, but a multi-word value that merely contains a
        # blacklisted word ("the it crowd", "her majesty") is a legitimate
        # binding and must survive.
        for slot, values in self._intent_slot_blacklists.get((lang, intent.name), {}).items():
            bound = matches.get(slot)
            if bound is not None and any(
                    v.lower().split() == bound.lower().split() for v in values):
                LOG.debug(f"Padatious slot '{slot}'='{bound}' blacklisted "
                          f"(INTENT-2 §4.3): treating as unresolved")
                matches.pop(slot, None)

        intent_context = getattr(sess, "intent_context", None) or {}
        owner_id = intent.name.split(":")[0]
        candidates = context_slot_candidates(intent_context, list(slot_names),
                                             owner_id)
        for slot, value in candidates.items():
            # a value the utterance itself produced wins over the candidate
            if not matches.get(slot):
                LOG.debug(f"Padatious slot '{slot}' filled from context "
                          f"(OVOS-CONTEXT-1 §7): '{value}'")
                matches[slot] = value
        intent.matches = matches

    def _get_closest_lang(self, lang: str) -> Optional[str]:
        if self.containers:
            return closest_lang(standardize_lang(lang), list(self.containers.keys()))
        return None

    def shutdown(self):
        for container in self.containers.values():
            container.shutdown(wait=False)
        self.bus.remove('padatious:register_intent', self.register_intent)
        self.bus.remove('padatious:register_entity', self.register_entity)
        self.bus.remove('intent.service.padatious.get', self.handle_get_padatious)
        self.bus.remove('intent.service.padatious.manifest.get', self.handle_padatious_manifest)
        self.bus.remove('intent.service.padatious.entities.manifest.get', self.handle_entity_manifest)
        self.bus.remove('detach_intent', self.handle_detach_intent)
        self.bus.remove('detach_skill', self.handle_detach_skill)
        self.bus.remove(SpecMessage.INTENT_REGISTER_TEMPLATE, self.handle_register_template)
        self.bus.remove(SpecMessage.ENTITY_REGISTER, self.handle_register_entity_spec)
        self.bus.remove(SpecMessage.INTENT_DEREGISTER, self.handle_deregister_intent_spec)
        self.bus.remove(SpecMessage.ENTITY_DEREGISTER, self.handle_deregister_entity_spec)
        self.bus.remove(SpecMessage.SKILL_DEREGISTER, self.handle_deregister_skill_spec)
        self.bus.remove(SpecMessage.INTENT_ENABLE, self.handle_enable_intent_spec)
        self.bus.remove(SpecMessage.INTENT_DISABLE, self.handle_disable_intent_spec)

    def handle_get_padatious(self, message):
        """messagebus handler for perfoming padatious parsing.

        Args:
            message (Message): message triggering the method
        """
        utterance = message.data["utterance"]
        lang = message.data.get("lang", self.lang)
        intent = self.calc_intent(utterance, lang=lang)
        if intent:
            intent = intent.__dict__
        self.bus.emit(message.reply("intent.service.padatious.reply",
                                    {"intent": intent}))

    def handle_padatious_manifest(self, message):
        """Messagebus handler returning the registered padatious intents.

        Args:
            message (Message): message triggering the method
        """
        self.bus.emit(message.reply(
            "intent.service.padatious.manifest",
            {"intents": self.registered_intents}))

    def handle_entity_manifest(self, message):
        """Messagebus handler returning the registered padatious entities.

        Args:
            message (Message): message triggering the method
        """
        self.bus.emit(message.reply(
            "intent.service.padatious.entities.manifest",
            {"entities": self.registered_entities}))


def _dealias_intent_name(name: Optional[str]) -> Optional[str]:
    """Fold the legacy ``<skill_id>:<file>.intent`` id onto the OVOS-INTENT-4
    canonical ``<skill_id>:<file>`` id.

    ovos-workshop >= 9.3 dual-registers one skill capability under both wire
    forms during the INTENT-4 migration (the legacy ``padatious:register_intent``
    contract and the spec ``ovos.intent.register.template`` contract, whose
    ``intent_name`` already has the ``.intent`` suffix stripped). This plugin
    folds that onto one canonical engine entry at REGISTRATION time (see
    ``PadatiousPipeline.register_intent`` / ``__detach_intent``), so engine
    matches (``m.name``) are canonical by construction.

    This helper is also used to canonicalize session ``blacklisted_intents``
    entries, since old sessions/configs may still carry the legacy
    ``.intent``-suffixed id (ovos-core#831; OVOS-PIPELINE-1 §5.4).
    """
    if name and name.endswith(".intent"):
        return name[:-len(".intent")]
    return name


# ovos-workshop's ``register_entity_file`` builds the entity name as
# ``<skill_id>:<basename>_<md5(entity_file)>``. That hash is emitter-internal
# bookkeeping, never part of the wire contract: the ``<skill_id>:`` prefix
# already namespaces the entity, and the hash is taken over the file name that
# is already in the key, so it adds no disambiguation at all.
_ENTITY_HASH_SUFFIX = re.compile(r"_[0-9a-f]{32}$")


def _dealias_entity_name(name: Optional[str]) -> Optional[str]:
    """Fold the legacy munged entity id onto the canonical
    ``<skill_id>:<entity>`` id.

    Slot lookup (:meth:`ovos_padatious.entity_manager.EntityManager.find`)
    builds its candidate key from the matching intent's skill_id plus the RAW
    slot token written in the template, so a hash-suffixed (or ``.entity``
    suffixed) registration can never be found and the slot degrades to an
    unconstrained wildcard.

    Collapsing at REGISTRATION time - where this plugin owns its own lookup
    contract - repairs every emitter vintage, including deployed ovos-workshop
    releases that will keep emitting the munged name. It also makes the legacy
    twin of an ovos-workshop >= 9.3 dual-emit land on the same canonical name
    as its OVOS-INTENT-4 ``ovos.entity.register`` twin.
    """
    if not name:
        return name
    if name.endswith(".entity"):
        name = name[:-len(".entity")]
    return _ENTITY_HASH_SUFFIX.sub("", name)


# Legacy `.intent`-suffixed blacklist entries are deprecated compat, not a
# stable contract. Warn once per distinct offending entry (not per utterance)
# so stale mycroft.conf/session config gets flagged without spamming the log.
_warned_legacy_blacklist_entries = set()


def _canonicalize_blacklist(blacklisted_intents: frozenset,
                             context: str = "Session blacklisted_intents") -> frozenset:
    """Canonicalize legacy `.intent`-suffixed blacklist entries.

    Sessions/config may still list intents (or, for ``blacklisted_labels``,
    fnmatch glob patterns) by the legacy ``<skill_id>:<file>.intent`` id.
    Engine matches are canonical by construction (registration-time alias
    collapse), so the blacklist must be normalized to compare correctly - a
    glob like ``some-skill:*.intent`` just loses its trailing suffix, same
    as an exact id, since ``_dealias_intent_name`` only strips a literal
    ``.intent`` tail. Logs a one-time deprecation warning per distinct
    legacy entry pointing at the canonical replacement.
    """
    canonical = set()
    for b in blacklisted_intents:
        c = _dealias_intent_name(b)
        canonical.add(c)
        if c != b and b not in _warned_legacy_blacklist_entries:
            _warned_legacy_blacklist_entries.add(b)
            LOG.warning(
                f"{context} entry '{b}' uses the deprecated "
                f"legacy '.intent'-suffixed id; support for this alias will "
                f"be removed. Update mycroft.conf / session config to use the "
                f"canonical id '{c}' instead.")
    return frozenset(canonical)


#: Must exceed the number of distinct (utterance, session) keys interleaved
#: across concurrent sessions, or a still-live result gets evicted before it
#: is reused.
_INTENT_CACHE_SIZE = 128


@lru_cache(maxsize=_INTENT_CACHE_SIZE)
def _calc_padatious_intent_cached(utt: str,
                           intent_container: Union[IntentContainer, DomainIntentContainer],
                           compiled_generation: int = 0,
                           blacklisted_intents: frozenset = frozenset(),
                           blacklisted_skills: frozenset = frozenset()) -> Optional[PadatiousIntent]:
    """
    Try to match an utterance to an intent in an intent_container
    @param utt: str - text to match intent against
    @param compiled_generation: the container's own compile-pass counter
        (``IntentContainer.compiled_generation``/
        ``DomainIntentContainer.compiled_generation``) at call time, folded
        into the cache key purely so it changes across a compile. A query
        answered before a container had ever compiled anything (served by
        the neural tier's own cache-hit state, or with no match at all -
        see ``IntentContainer._train_in_background``) is training triggered
        via ``calc_intents`` itself, off any bus-thread ``train()`` call
        this module's own explicit ``.cache_clear()`` calls would ever see;
        without this, that lru_cache entry never expires and the SAME
        utterance keeps returning the pre-compile answer forever, until
        three unrelated utterances happen to evict it (maxsize=3).

    The session blacklists are passed as hashable frozensets so this stays
    ``lru_cache``-able (Session is unhashable under ovos-bus-client>=2.4.0a1).
    ``blacklisted_labels`` (the ``blacklisted_labels`` config, exact ids and
    fnmatch globs) is deliberately NOT a parameter here: this function is
    cached on a MODULE-GLOBAL, maxsize=3 ``lru_cache`` shared by every
    ``PadatiousPipeline`` instance in the process, while ``blacklisted_labels``
    is a per-instance config value - folding it into the key would let one
    instance's blacklist evict or shadow another instance's cached answer for
    the same utterance/container/generation. See
    ``PadatiousPipeline.calc_intent`` for where that check is applied instead,
    against this function's already-cached result.
    @return: matched PadatiousIntent
    """
    try:
        blacklisted_intents = _canonicalize_blacklist(blacklisted_intents)
        # OVOS-INTENT-1 §2: match against the lowercase-normalized input so slot
        # values are case-insensitive, but report the original utterance as `sent`.
        # Matches are canonical by construction (registration-time alias
        # collapse, see PadatiousPipeline.register_intent), so only the
        # blacklist needs canonicalizing here.
        def allowed(candidates):
            return [m for m in candidates
                    if m.name not in blacklisted_intents
                    and m.name.split(":")[0] not in blacklisted_skills]

        # Padaos exact matches carry authoritative conf=1.0, so resolving them
        # first lets a deterministic utterance skip the CPU-heavy neural pass
        # entirely. If every exact match is blacklisted the neural tier still
        # runs, so behavior is unchanged for anything the exact tier cannot
        # answer.
        matches = allowed(intent_container.calc_exact_intents(utt.lower()))
        if not matches:
            matches = allowed(intent_container.calc_intents(utt.lower()))
        if len(matches) == 0:
            return None
        best_match = max(matches, key=lambda x: x.conf)
        best_matches = (
            match for match in matches if match.conf == best_match.conf)
        intent = min(best_matches, key=lambda x: sum(map(len, x.matches.values())))
        intent.sent = utt
        return intent
    except Exception as e:
        LOG.error(e)


def _calc_padatious_intent(utt: str,
                           intent_container: Union[IntentContainer, DomainIntentContainer],
                           compiled_generation: int = 0,
                           blacklisted_intents: frozenset = frozenset(),
                           blacklisted_skills: frozenset = frozenset()) -> Optional[PadatiousIntent]:
    """Cached match, handed to the caller as its own copy.

    The cached MatchData is shared by every caller that asks the same
    question, and the caller mutates it: ``PadatiousPipeline.calc_intent``
    fills declared slots from the session's intent_context
    (``_fill_context_slots``). Returning the cached object directly means a
    slot one session filled is still filled when the next session matches
    the same utterance, so a context value leaks across sessions -- and two
    concurrent requests race on the same dict. The cache stores the match;
    each caller gets a copy of it.
    """
    cached = _calc_padatious_intent_cached(
        utt, intent_container, compiled_generation,
        blacklisted_intents, blacklisted_skills)
    return deepcopy(cached) if cached is not None else None


#: the lru_cache lives on the inner function; callers that manage the cache
#: (registration, deregistration, enable, disable, train) reach it through
#: the public name.
_calc_padatious_intent.cache_clear = _calc_padatious_intent_cached.cache_clear
_calc_padatious_intent.cache_info = _calc_padatious_intent_cached.cache_info
# the blacklist fall-through above re-runs selection uncached and needs the
# raw function; no deepcopy needed there, the value is freshly computed.
_calc_padatious_intent.__wrapped__ = _calc_padatious_intent_cached.__wrapped__
