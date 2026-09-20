# Copyright 2017 Mycroft AI, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import inspect
import re
import os
import threading
import time
from functools import wraps
from typing import List, Dict, Any, Optional

from ovos_config.meta import get_xdg_base
from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home

from ovos_padatious import padaos
from ovos_padatious.entity import Entity
from ovos_padatious.entity_manager import EntityManager
from ovos_padatious.intent_manager import IntentManager
from ovos_padatious.match_data import MatchData
from ovos_padatious.util import tokenize
import collections

def _save_args(func):
    """
    Decorator that saves the arguments passed to the function in the serialized_args attribute of the class.

    Args:
        func (function): The function to be decorated.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        func(*args, **kwargs)
        bound_args = inspect.signature(func).bind(*args, **kwargs)
        bound_args.apply_defaults()
        kwargs = bound_args.arguments
        kwargs['__name__'] = func.__name__
        kwargs.pop('self').serialized_args.append(kwargs)

    return wrapper


class IntentContainer:
    """
    Creates an IntentContainer object used to load and match intents

    Args:
        cache_dir (str): Directory for caching the neural network models and intent/entity files.
        disable_padaos (bool): Disable exact-pattern matching when true.
        inference_workers (int): Maximum reusable neural inference workers.
    """

    #: how long shutdown() waits for an in-flight training pass to finish
    #: before closing the managers underneath it.
    SHUTDOWN_TRAIN_JOIN_S = 10.0

    def __init__(self, cache_dir: Optional[str] = None,
                 disable_padaos: bool = False,
                 inference_workers: Optional[int] = None) -> None:
        cache_dir = cache_dir or f"{xdg_data_home()}/{get_xdg_base()}/intent_cache"
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_dir: str = cache_dir
        self.must_train: bool = False
        self.inference_workers = inference_workers
        self.intents: IntentManager = IntentManager(
            cache_dir, max_workers=inference_workers)
        self.entities: EntityManager = EntityManager(cache_dir)
        self.disable_padaos = disable_padaos
        if self.disable_padaos:
            self.padaos = None
        else:
            self.padaos: padaos.IntentContainer = padaos.IntentContainer()
        self.train_thread: Optional[Any] = None  # deprecated
        self.serialized_args: List[Dict[str, Any]] = []  # Serialized calls for training intents/entities
        self.blacklisted_words: Dict[str, List[str]] = collections.defaultdict(list)
        # training must never block the query/utterance thread: a
        # registration burst followed immediately by an utterance would
        # otherwise pay the full compile+train cost inline (see train()).
        # A single background worker retrains while queries keep answering
        # against the previously trained state. ``_train_generation`` is a
        # lost-update guard: it is bumped on every registration that dirties
        # the container, and a training pass only clears ``must_train`` if
        # the generation is still the one it started with - otherwise a
        # registration landed mid-train and the worker loops immediately
        # instead of clobbering that registration's dirty flag.
        self._train_lock = threading.Lock()
        self._spawn_lock = threading.Lock()
        self._background_trainer: Optional[threading.Thread] = None
        # Set by shutdown(). The background trainer reads and publishes
        # self.intents/self.entities/self.padaos, so once the container is
        # retired no further pass may start: otherwise the worker trains
        # into, and writes cache files for, a manager whose executor
        # shutdown() has already closed.
        self._shutdown = threading.Event()
        self._ever_trained = False
        # Set once a training pass has published compiled state. Until then
        # this container has nothing to answer with, so calc_intents waits
        # on it rather than serving a guaranteed empty result (see
        # FIRST_COMPILE_WAIT_S). After the first pass it stays set forever
        # and the match path never touches it again.
        self._first_compile_done = threading.Event()
        self._train_generation = 0
        # last time a registration dirtied this container; used by the
        # background worker to debounce a burst of registrations into one
        # retrain (see _wait_for_quiet).
        self._last_dirty_at = 0.0
        # Bumped every time a real compile pass actually runs (see train()).
        # opm.py's _calc_padatious_intent lru_cache includes this in its key
        # so a query answered "no match" before this container ever
        # compiled - training triggered from calc_intents' own
        # _train_in_background, which opm.py's cache-clearing _train_sync
        # never sees - is not served that stale cached miss forever after
        # the pass lands.
        self.compiled_generation = 0

    @property
    def intent_names(self):
        return self.intents.intent_names

    @property
    def needs_compile(self) -> bool:
        """
        True if either the hash-cache-aware retrain is pending
        (``must_train``) or padaos itself is dirty from a registration that
        never set ``must_train`` (see add_intent/add_entity: a no-op replay
        of an already-cached intent/entity is never allowed to dirty or
        clear ``must_train``, but ``padaos.add_intent``/``add_entity`` have
        no cache-aware skip of their own and always mark the regex
        container dirty). Callers that gate background/foreground training
        solely on ``must_train`` (as the ser9 field trace showed opm.py's
        ``train()`` doing) leave ``padaos.must_compile`` stuck True after a
        boot that replays only cache hits, with nothing left to clear it
        until the first live query forces a synchronous compile on the bus
        thread.
        """
        return self.must_train or (self.padaos is not None and self.padaos.must_compile)

    def _set_must_train(self, value: bool) -> None:
        """
        Sets the dirty flag, bumping ``_train_generation`` whenever it is
        set True so an in-flight background train can detect that a fresh
        registration arrived after its snapshot was taken.
        """
        if value:
            self._train_generation += 1
            self._last_dirty_at = time.monotonic()
        self.must_train = value

    def clear(self) -> None:
        """
        Clears the current intent and entity managers and resets the container.
        """
        os.makedirs(self.cache_dir, exist_ok=True)
        self.must_train = False
        # A pass in flight reads self.intents/self.entities/self.padaos and
        # sets _first_compile_done when it lands. Left running across the
        # swap it would compile the OLD state and then mark the REPLACEMENT
        # container ready, so a query could skip its first-compile wait and
        # match against nothing. Stop and join it before replacing anything.
        self._stop_background_trainer()
        old_intents = self.intents
        self.intents = IntentManager(
            self.cache_dir, max_workers=self.inference_workers)
        old_intents.shutdown(wait=False)
        self.entities = EntityManager(self.cache_dir)
        if self.disable_padaos:
            self.padaos = None
        else:
            self.padaos: padaos.IntentContainer = padaos.IntentContainer()
        self.serialized_args = []
        self._ever_trained = False
        self._first_compile_done.clear()
        self._background_trainer = None
        self._train_generation = 0
        # clear() resets the container for reuse, unlike shutdown()
        self._shutdown.clear()

    def _stop_background_trainer(self) -> None:
        """Stop the background trainer and wait for it to leave train()."""
        self._shutdown.set()
        with self._spawn_lock:
            trainer = self._background_trainer
        if trainer is not None and trainer.is_alive():
            trainer.join(timeout=self.SHUTDOWN_TRAIN_JOIN_S)
            if trainer.is_alive():
                LOG.warning("padatious background trainer did not stop in time")

    def shutdown(self, wait: bool = True) -> None:
        """Retire the container: stop training, then release the workers.

        The background trainer mutates self.intents and writes cache files,
        so it has to be stopped and joined BEFORE the manager it is training
        into is closed -- otherwise a pass in flight keeps compiling into a
        retired container and can publish state after shutdown returned. The
        join is bounded and applies to wait=False too: a caller that does not
        want to block on the executor still must not be handed a container
        with a live writer inside it.
        """
        self._stop_background_trainer()
        self.intents.shutdown(wait=wait)

    def instantiate_from_disk(self) -> None:
        """
        Instantiates the necessary (internal) data structures when loading persisted model from disk.
        This is done via injecting entities and intents back from cached file versions.
        """
        entity_traindata: Dict[str, List[str]] = {}
        intent_traindata: Dict[str, List[str]] = {}

        # workaround: load training data for both entities and intents since
        # padaos regex needs it for (re)compilation until TODO is cleared
        for f in os.listdir(self.cache_dir):
            if f.endswith('.entity'):
                entity_name = f[0:f.find('.entity')]
                with open(os.path.join(self.cache_dir, f), 'r') as d:
                    entity_traindata[entity_name] = [line.strip()
                                                     for line in d]

            elif f.endswith('.intent'):
                intent_name = f[0:f.find('.intent')]
                with open(os.path.join(self.cache_dir, f), 'r') as d:
                    intent_traindata[intent_name] = [line.strip()
                                                     for line in d]

        # TODO: padaos.compile (regex compilation) is redone when loading: find
        # a way to persist regex, as well!
        for f in os.listdir(self.cache_dir):
            if f.startswith('{') and f.endswith('}.hash'):
                entity_name = f[1:f.find('}.hash')]
                if entity_name in entity_traindata:
                    self.add_entity(
                        name=entity_name,
                        lines=entity_traindata[entity_name],
                        reload_cache=False,
                        must_train=False
                    )
            elif not f.startswith('{') and f.endswith('.hash'):
                intent_name = f[0:f.find('.hash')]
                if intent_name in intent_traindata:
                    self.add_intent(
                        name=intent_name,
                        lines=intent_traindata[intent_name],
                        reload_cache=False,
                        must_train=False
                    )

    @_save_args
    def add_intent(self, name: str, lines: List[str], reload_cache: bool = False, must_train: bool = True,
                   blacklisted_words: Optional[List[str]] = None) -> None:
        """
        Creates a new intent, optionally checking the cache first

        Args:
            name (str): Name of the intent.
            lines (List[str]): Sentences that will activate the intent.
            reload_cache (bool): Whether to ignore cached intent.
            must_train (bool): Whether the model needs training after adding the intent.
        """
        self.blacklisted_words[name] = blacklisted_words or []
        changed = self.intents.add(name, lines, reload_cache, must_train)
        if self.padaos is not None:
            self.padaos.add_intent(name, lines)
        # Only dirty the container when the registration actually changed
        # something; a no-op replay (see TrainingManager.add) must never
        # touch ``must_train``, including never clearing it, since a
        # concurrent unrelated registration may already have a genuine
        # pending training need this call knows nothing about.
        if changed:
            self._set_must_train(True)
        elif self.padaos is not None:
            # padaos.add_intent above always marks padaos dirty regardless
            # of the cache hit (it has no hash-aware skip of its own), so
            # the debounce window (_wait_for_quiet) still needs to see this
            # as activity, or a burst of pure no-op replays never settles
            # and padaos.must_compile is left stuck until a live query.
            self._last_dirty_at = time.monotonic()

    @_save_args
    def add_entity(self, name: str, lines: List[str], reload_cache: bool = False, must_train: bool = True) -> None:
        """
        Adds an entity that matches the given lines.

        Example:
            self.add_intent('weather', ['will it rain on {weekday}?'])
            self.add_entity('weekday', ['monday', 'tuesday', 'wednesday'])  # ...

        Args:
            name (str): Name of the entity.
            lines (List[str]): Example extracted entities.
            reload_cache (bool): Whether to refresh the cache.
            must_train (bool): Whether the model needs training after adding the entity.
        """
        Entity.verify_name(name)
        changed = self.entities.add(
            Entity.wrap_name(name),
            lines,
            reload_cache,
            must_train)
        if self.padaos is not None:
            self.padaos.add_entity(name, lines)
        # see add_intent: never dirty (and never clear) on a no-op replay
        if changed:
            self._set_must_train(True)
        elif self.padaos is not None:
            self._last_dirty_at = time.monotonic()

    @_save_args
    def load_entity(self, name: str, file_name: str, reload_cache: bool = False, must_train: bool = True) -> None:
        """
       Loads an entity, optionally checking the cache first

       Args:
           name (str): The associated name of the entity
           file_name (str): The location of the entity file
           reload_cache (bool): Whether to refresh all of cache
            must_train (bool): Whether the model needs training after loading the entity.
        """
        Entity.verify_name(name)
        self.entities.load(Entity.wrap_name(name), file_name, reload_cache)
        if self.padaos is not None:
            with open(file_name) as f:
                self.padaos.add_entity(name, f.read().split('\n'))
        self._set_must_train(must_train)

    @_save_args
    def load_file(self, *args, **kwargs):
        """Legacy. Use load_intent instead"""
        self.load_intent(*args, **kwargs)

    @_save_args
    def load_intent(self, name: str, file_name: str, reload_cache: bool = False, must_train: bool = True) -> None:
        """
        Loads an intent, optionally checking the cache first

        Args:
            name (str): The associated name of the intent
            file_name (str): The location of the intent file
            reload_cache (bool): Whether to refresh all of cache
            must_train (bool): Whether the model needs training after loading the intent.
        """
        self.intents.load(name, file_name, reload_cache)
        if self.padaos is not None:
            with open(file_name) as f:
                self.padaos.add_intent(name, f.read().split('\n'))
        self._set_must_train(must_train)

    @_save_args
    def remove_intent(self, name: str) -> None:
        """
        Removes an intent by its name.

        Args:
            name (str): Name of the intent to remove.
        """
        self.intents.remove(name)
        if self.padaos is not None:
            self.padaos.remove_intent(name)
        self._set_must_train(True)

    @_save_args
    def remove_entity(self, name: str) -> None:
        """
        Removes an entity by its name.

        Args:
            name (str): Name of the entity to remove.
        """
        self.entities.remove(name)
        if self.padaos is not None:
            self.padaos.remove_entity(name)

    def train(self, debug: bool = True, force: bool = False, single_thread: Optional[bool] = None,
              timeout: Optional[float] = None) -> bool:
        """
        Trains all the loaded intents that need to be updated
        If a cache file exists with the same hash as the intent file,
        the intent will not be trained and just loaded from file

        Args:
            debug (bool): Whether to print a message to stdout each time a new intent is trained
            force (bool): Whether to force training if already finished
            single_thread (bool): DEPRECATED
            timeout (float): DEPRECATED
        Returns:
            bool: True if training succeeded
        """
        if single_thread is not None:
            LOG.warning("'single_thread' argument is deprecated and will be ignored")
        if timeout is not None:
            LOG.warning("'timeout' argument is deprecated and will be ignored")
        # The very first call must always run the full finalize step (padaos
        # compile + entity_dict build) even when every registration so far
        # was an unchanged cache hit and never dirtied ``must_train`` - a
        # fresh container whose cache is 100% up to date still needs its
        # lookup structures populated once before it can answer anything.
        if not self.needs_compile and not force and self._ever_trained:
            return True

        with self._train_lock:
            # re-check under the lock: another thread (the background
            # worker, or a concurrent forced caller) may have just trained
            if not self.needs_compile and not force and self._ever_trained:
                return True

            # snapshot the generation before doing any work; if a
            # registration bumps it before we finish, that registration's
            # objects were not necessarily part of this pass, so we must
            # not claim the container is clean when we're done
            start_gen = self._train_generation

            try:
                if self.padaos is not None:
                    self.padaos.compile()

                # Train intents and entities
                self.intents.train(debug=debug)
                self.entities.train(debug=debug)

                self.entities.calc_ent_dict()

                if self._train_generation == start_gen:
                    self.must_train = False
                self._ever_trained = True
                self.compiled_generation += 1
            finally:
                # Released even when the pass raised: a waiter must never
                # be parked behind a compile that will never publish.
                # Retries are opm's _train_sync backoff to schedule, not a
                # query's to wait out.
                self._first_compile_done.set()
        return True

    def _train_in_background(self) -> None:
        """
        Ensures training NEVER happens on the calling (query/utterance)
        thread, including the very first pass.

        A container that has never trained - even one that is 100% hash
        cache hits and would compile trivially fast - still has zero
        previously-trained state to answer with; queries against it are
        served empty (no match) until the background worker's first pass
        actually swaps in compiled state, exactly like every other "serve
        the stale/empty generation while a pass is in flight" rule in this
        file. Round-8 field trace: a boot whose registrations were all
        hash-cache hits never called ``train()`` through any of opm.py's
        own gates (nothing ever dirtied ``must_train``), so the very first
        live query reached here with ``_ever_trained`` False and used to
        call ``self.train()`` synchronously - paying the full padaos
        compile on the bus thread, the same defect this file already fixed
        one call frame lower (padaos.calc_intents). The worker loops
        internally (instead of piling up threads) whenever a registration
        lands after its train() pass already started, so a registration
        can never be silently stranded by a train() call that began before
        it arrived.
        """
        if not self.needs_compile:
            return
        if self._shutdown.is_set():
            return
        with self._spawn_lock:
            if self._shutdown.is_set():
                return
            if self._background_trainer is not None and self._background_trainer.is_alive():
                return
            self._background_trainer = threading.Thread(
                target=self._background_train_loop, daemon=True
            )
            self._background_trainer.start()

    # Debounced coalescing: a boot-time registration wave can trickle in
    # over minutes (ser9 field trace: ~128 registrations spread across a
    # slow, serialized boot), so a fixed short settle barely helps - most
    # registrations still land just outside a 2s window and each one still
    # gets its own pass. Instead, wait for a quiet window with NO new
    # registration before retraining, resetting the timer on every arrival,
    # capped so a slow-but-steady trickle still trains within a bounded time
    # instead of deferring forever.
    _TRAIN_DEBOUNCE_S = 2.0
    _TRAIN_MAX_DEFER_S = 60.0

    # How long a query may wait for the very first compile to publish:
    # the debounce window plus slack for the pass itself. A registration
    # storm that never settles re-arms _wait_for_quiet indefinitely, so
    # this deliberately expires quickly and answers empty rather than
    # making every query pay a long cap for an answer it will not get.
    FIRST_COMPILE_WAIT_S = 3.0

    def _wait_for_quiet(self) -> None:
        """Block until no registration has dirtied this container for
        ``_TRAIN_DEBOUNCE_S``, or until ``_TRAIN_MAX_DEFER_S`` total has
        elapsed since this wait started - whichever comes first."""
        deadline = time.monotonic() + self._TRAIN_MAX_DEFER_S
        while True:
            snapshot = self._last_dirty_at
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            # wait on the shutdown flag rather than sleeping blindly, so a
            # retiring container does not hold shutdown() for a whole
            # debounce interval before the worker notices
            if self._shutdown.wait(min(self._TRAIN_DEBOUNCE_S, remaining)):
                return
            if self._last_dirty_at == snapshot:
                return

    def _background_train_loop(self) -> None:
        # a single worker keeps retraining until a pass completes without
        # must_train being re-armed by a registration that arrived mid-pass
        while self.needs_compile and not self._shutdown.is_set():
            self._wait_for_quiet()
            if self._shutdown.is_set():
                return
            self.train()

    def calc_intents(self, query: str) -> List[MatchData]:
        """
        Tests all the intents against the query and returns
        data on how well each one matched against the query

        Args:
            query (str): Input sentence to test against intents.

        Returns:
            List[MatchData]: A list of all intent matches with confidence scores.
        """
        self._train_in_background()
        if not self._first_compile_done.is_set() and self.needs_compile \
                and self.intent_names:
            # Nothing has ever compiled and there IS something to
            # compile, so every structure this method reads below is empty
            # and the answer is a guaranteed "no match" - not a
            # stale-but-usable previous generation. A container with
            # nothing pending, and one with no intents registered at all
            # (an unregistered language), has nothing a query could ever
            # match and must not wait. Waiting
            # for the first pass to publish is what makes an intent
            # matchable as soon as it is registered, without a caller
            # having to drive training itself. This is an Event wait, not a
            # lock and not a compile: the pass still runs on the background
            # worker's thread, and once any generation exists this branch
            # is never taken again - matching stays lock-free against the
            # last published state.
            self._first_compile_done.wait(self.FIRST_COMPILE_WAIT_S)

        # post-processing: discard any matches that contain blacklisted words
        intents = {i.name: i
                   for i in self.intents.calc_intents(query, self.entities)
                   if not self._suppressed(i.name, query)}

        for perfect_match in self._calc_exact_intents(query):
            intents[perfect_match.name] = perfect_match
        return list(intents.values())

    def _suppressed(self, intent_name: str, query: str) -> bool:
        # blacklisted words match at word boundaries: "install" suppresses
        # "install firefox" but not "what is an installment loan"
        q = query.lower()
        return any(re.search(rf"\b{re.escape(k.lower())}\b", q)
                   for k in self.blacklisted_words[intent_name])

    def calc_exact_intents(self, query: str) -> List[MatchData]:
        """Return the deterministic padaos matches, skipping neural inference.

        Same result as the exact tier inside :meth:`calc_intents`, but
        without paying for the neural pass a caller does not need when an
        exact template already answers with conf=1.0.
        """
        self._train_in_background()
        return self._calc_exact_intents(query)

    def _calc_exact_intents(self, query: str) -> List[MatchData]:
        """The exact tier itself, with no training side effects."""
        if self.padaos is None:
            return []
        sent = tokenize(query)
        matches = []
        # exact template matches honor the same suppression - a perfect
        # match must not bypass the blacklist the neural tier enforces
        for perfect_match in self.padaos.calc_intents(query):
            name = perfect_match['name']
            if self._suppressed(name, query):
                continue
            if not self._padaos_entities_verified(name, perfect_match['entities']):
                # a slot backed by an over-cap entity matched through
                # the unverified wildcard fallback (see
                # padaos.PADAOS_ENTITY_INLINE_CAP); padaos conf=1.0
                # would grant in-list exactness never actually checked,
                # so let the neural tier's own scoring stand instead
                continue
            matches.append(MatchData(name, sent,
                                     matches=perfect_match['entities'], conf=1.0))
        return matches

    def _padaos_entities_verified(self, intent_name: str, matched_entities: Dict[str, str]) -> bool:
        """
        True unless a matched slot is backed by an entity padaos skipped
        inlining (too many values); those slots match via a generic
        wildcard and must be independently confirmed against the entity's
        known values before their padaos conf=1.0 can be trusted.
        """
        namespace = intent_name.split(':')[0] + ':'
        for ent_name, value in matched_entities.items():
            if ent_name not in self.padaos.capped_entities and \
                    (namespace + ent_name) not in self.padaos.capped_entities:
                continue
            entity = self.entities.find(intent_name, '{' + ent_name + '}')
            if entity is None or entity.match(tokenize(value)) != 1.0:
                return False
        return True

    def calc_intent(self, query: str) -> MatchData:
        """
        Returns the best intent match for the given query.

        Args:
            query (str): Input sentence to test against intents.

        Returns:
            MatchData: The best matching intent.
        """
        matches = self.calc_intents(query)
        if not matches:
            return MatchData('', '')
        best_match = max(matches, key=lambda x: x.conf)
        best_matches = [match for match in matches if match.conf == best_match.conf]
        return min(best_matches, key=lambda x: sum(map(len, x.matches.values())))

    def get_training_args(self) -> List[Dict[str, Any]]:
        """
        Returns all serialized arguments used for training intents and entities.

        Returns:
            List[Dict[str, Any]]: List of serialized arguments for training.
        """
        return self.serialized_args

    def apply_training_args(self, data):
        for params in data:
            func_name = params.pop('__name__')
            getattr(self, func_name)(**params)
