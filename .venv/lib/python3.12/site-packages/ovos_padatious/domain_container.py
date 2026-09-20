import threading
from collections import defaultdict
from typing import Dict, List, Optional
from ovos_utils.log import LOG
from ovos_padatious.intent_container import IntentContainer
from ovos_padatious.match_data import MatchData


class DomainIntentContainer:
    """
    A domain-aware intent recognition engine that organizes intents and entities
    into specific domains, providing flexible and hierarchical intent matching.
    """

    def __init__(self, cache_dir: Optional[str] = None,
                 disable_padaos: bool = False,
                 inference_workers: Optional[int] = None):
        """
        Initialize the DomainIntentEngine.

        Attributes:
            domain_engine (IntentContainer): A top-level intent container for cross-domain calculations.
            domains (Dict[str, IntentContainer]): A mapping of domain names to their respective intent containers.
            training_data (Dict[str, List[str]]): A mapping of domain names to their associated training samples.
        """
        self.cache_dir = cache_dir
        self.disable_padaos = disable_padaos
        self.inference_workers = inference_workers
        self.domain_engine = IntentContainer(cache_dir=cache_dir,
                                             disable_padaos=disable_padaos,
                                             inference_workers=inference_workers)
        self.domains: Dict[str, IntentContainer] = {}
        self.training_data: Dict[str, List[str]] = defaultdict(list)
        self.instantiate_from_disk()
        self.must_train = True
        # never train on the calling (query) thread - mirrors
        # IntentContainer._train_in_background, see _train_in_background
        # below.
        self._spawn_lock = threading.Lock()
        self._background_trainer: Optional[threading.Thread] = None
        # see IntentContainer.compiled_generation
        self.compiled_generation = 0

    @property
    def needs_compile(self) -> bool:
        """True if this container's own registration bookkeeping is dirty,
        OR either the cross-domain ``domain_engine`` or any per-domain
        sub-container is dirty. A domain/sub-intent registration replay
        that is a pure hash-cache hit never sets ``must_train`` here (see
        ``add_domain_intent``, which always sets it unconditionally
        anyway) but the same padaos-only-dirty scenario
        ``IntentContainer.needs_compile`` guards against can still occur
        one layer down, in ``domain_engine`` or a per-domain container -
        aggregating all three is what lets ``_train_in_background`` (and
        ``PadatiousPipeline.train``'s own gates, which check this
        property) notice that."""
        return (self.must_train
                or self.domain_engine.needs_compile
                or any(d.needs_compile for d in self.domains.values()))

    def _train_in_background(self) -> None:
        """Ensures training NEVER happens on the calling (query) thread.

        Mirrors ``IntentContainer._train_in_background`` exactly, including
        for the very-first-pass case: a ``DomainIntentContainer`` that has
        never trained is served empty (no domain/intent match) until the
        background worker's pass actually swaps in compiled state, rather
        than compiling ``domain_engine`` plus every per-domain container
        inline on the bus/query thread.
        """
        if not self.needs_compile:
            return
        with self._spawn_lock:
            if self._background_trainer is not None and self._background_trainer.is_alive():
                return
            self._background_trainer = threading.Thread(target=self.train, daemon=True)
            self._background_trainer.start()

    def _wait_for_quiet(self) -> None:
        """Delegates quiescence to ``domain_engine`` and every dirty
        per-domain sub-container - unlike ``IntentContainer``, this class
        has no debounce timer of its own; each underlying container
        already implements the correct wait-for-quiet/max-defer algorithm
        (see ``IntentContainer._wait_for_quiet``). Without this method,
        ``opm.py``'s ``_train_worker`` calling ``engine._wait_for_quiet()``
        on a ``DomainIntentContainer`` raised ``AttributeError`` and
        silently killed the background worker thread - so under
        ``domain_engine: true``, ``mycroft.skills.trained`` was never
        emitted and nothing ever trained outside of a query forcing it.
        """
        if self.domain_engine.needs_compile:
            self.domain_engine._wait_for_quiet()
        for engine in list(self.domains.values()):
            if engine.needs_compile:
                engine._wait_for_quiet()

    def instantiate_from_disk(self) -> None:
        """
        Instantiates the necessary (internal) data structures when loading persisted model from disk.
        This is done via injecting entities and intents back from cached file versions.
        """
        self.domain_engine.instantiate_from_disk()
        for engine in self.domains.values():
            engine.instantiate_from_disk()

    def remove_domain(self, domain_name: str):
        """
        Remove a domain and its associated intents and training data.

        Args:
            domain_name (str): The name of the domain to remove.
        """
        if domain_name in self.training_data:
            self.training_data.pop(domain_name)
        if domain_name in self.domains:
            self.domains.pop(domain_name).shutdown(wait=False)
        if domain_name in self.domain_engine.intent_names:
            self.domain_engine.remove_intent(domain_name)

    def add_domain_intent(self, domain_name: str, intent_name: str, intent_samples: List[str],
                          blacklisted_words: Optional[List[str]] = None):
        """
        Register an intent within a specific domain.

        Args:
            domain_name (str): The name of the domain.
            intent_name (str): The name of the intent to register.
            intent_samples (List[str]): A list of sample sentences for the intent.
        """
        if domain_name not in self.domains:
            self.domains[domain_name] = IntentContainer(cache_dir=self.cache_dir,
                                                        disable_padaos=self.disable_padaos,
                                                        inference_workers=self.inference_workers)
            self.domains[domain_name].instantiate_from_disk()

        self.domains[domain_name].add_intent(intent_name, intent_samples,
                                             blacklisted_words=blacklisted_words)
        self.training_data[domain_name] += intent_samples
        self.must_train = True

    def remove_domain_intent(self, domain_name: str, intent_name: str):
        """
        Remove a specific intent from a domain.

        Args:
            domain_name (str): The name of the domain.
            intent_name (str): The name of the intent to remove.
        """
        if domain_name in self.domains:
            self.domains[domain_name].remove_intent(intent_name)

    def add_domain_entity(self, domain_name: str, entity_name: str, entity_samples: List[str]):
        """
        Register an entity within a specific domain.

        Args:
            domain_name (str): The name of the domain.
            entity_name (str): The name of the entity to register.
            entity_samples (List[str]): A list of sample phrases for the entity.
        """
        if domain_name not in self.domains:
            self.domains[domain_name] = IntentContainer(cache_dir=self.cache_dir,
                                                        disable_padaos=self.disable_padaos,
                                                        inference_workers=self.inference_workers)
        self.domains[domain_name].add_entity(entity_name, entity_samples)

    def remove_domain_entity(self, domain_name: str, entity_name: str):
        """
        Remove a specific entity from a domain.

        Args:
            domain_name (str): The name of the domain.
            entity_name (str): The name of the entity to remove.
        """
        if domain_name in self.domains:
            self.domains[domain_name].remove_entity(entity_name)

    def calc_domains(self, query: str) -> List[MatchData]:
        """
        Calculate the matching domains for a query.

        Args:
            query (str): The input query.

        Returns:
            List[MatchData]: A list of MatchData objects representing matching domains.
        """
        self._train_in_background()

        return self.domain_engine.calc_intents(query)

    def calc_domain(self, query: str) -> MatchData:
        """
        Calculate the best matching domain for a query.

        Args:
            query (str): The input query.

        Returns:
            MatchData: The best matching domain.
        """
        self._train_in_background()
        return self.domain_engine.calc_intent(query)

    def calc_intent(self, query: str, domain: Optional[str] = None) -> MatchData:
        """
        Calculate the best matching intent for a query within a specific domain.

        Args:
            query (str): The input query.
            domain (Optional[str]): The domain to limit the search to. Defaults to None.

        Returns:
            MatchData: The best matching intent.
        """
        self._train_in_background()
        domain: str = domain or self.domain_engine.calc_intent(query).name
        if domain in self.domains:
            return self.domains[domain].calc_intent(query)
        return MatchData(name=None, sent=query, matches=None, conf=0.0)

    def calc_exact_intents(self, query: str, domain: Optional[str] = None,
                           top_k_domains: int = 2) -> List[MatchData]:
        """Return the deterministic padaos matches, skipping neural inference."""
        self._train_in_background()
        if domain:
            container = self.domains.get(domain)
            return container.calc_exact_intents(query) if container else []

        matches = []
        domains = self.domain_engine.calc_exact_intents(query)[:top_k_domains]
        for domain_match in domains:
            container = self.domains.get(domain_match.name)
            if container:
                matches.extend(container.calc_exact_intents(query))
        return sorted(matches, reverse=True, key=lambda match: match.conf)

    def calc_intents(self, query: str, domain: Optional[str] = None, top_k_domains: int = 2) -> List[MatchData]:
        """
        Calculate matching intents for a query across domains or within a specific domain.

        Args:
            query (str): The input query.
            domain (Optional[str]): The specific domain to search in. If None, searches across top-k domains.
            top_k_domains (int): The number of top domains to consider. Defaults to 2.

        Returns:
            List[MatchData]: A list of MatchData objects representing matching intents, sorted by confidence.
        """
        self._train_in_background()
        if domain:
            return self.domains[domain].calc_intents(query)
        matches = []
        domains = self.calc_domains(query)[:top_k_domains]
        for domain in domains:
            if domain.name in self.domains:
                matches += self.domains[domain.name].calc_intents(query)
        return sorted(matches, reverse=True, key=lambda k: k.conf)

    def train(self):
        for domain, samples in dict(self.training_data).items():  # copy for thread safety
            LOG.debug(f"Training domain: {domain}")
            self.domain_engine.add_intent(domain, samples)
        self.domain_engine.train()
        for domain in dict(self.domains): # copy for thread safety
            LOG.debug(f"Training domain sub-intents: {domain}")
            self.domains[domain].train()
        self.must_train = False
        self.compiled_generation += 1

    def shutdown(self, wait: bool = True) -> None:
        """Release inference workers owned by every domain container."""
        self.domain_engine.shutdown(wait=wait)
        for container in self.domains.values():
            container.shutdown(wait=wait)
