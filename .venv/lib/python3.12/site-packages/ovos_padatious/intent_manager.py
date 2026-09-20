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
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import List

from ovos_utils.log import LOG

from ovos_padatious.intent import Intent
from ovos_padatious.match_data import MatchData
from ovos_padatious.training_manager import TrainingManager
from ovos_padatious.util import tokenize


class IntentManager(TrainingManager):
    """
    Manages intents and performs matching using the OVOS Padatious framework.

    Args:
        cache (str): Path to the cache directory for storing trained models.
    """
    def __init__(self, cache: str, debug: bool = False,
                 max_workers: int | None = None):
        super().__init__(Intent, cache)
        if max_workers is not None and (
                isinstance(max_workers, bool)
                or not isinstance(max_workers, int)
                or max_workers < 1):
            raise ValueError("max_workers must be a positive integer or None")
        self.debug = debug
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="padatious-inference"
        )
        self._executor_lock = Lock()
        self._executor_closed = False

    @property
    def intent_names(self):
        return [i.name for i in self.objects + self.objects_to_train]

    def calc_intents(self, query: str, entity_manager) -> List[MatchData]:
        """
        Calculate matches for the given query against all registered intents.

        Args:
            query (str): The input query to match.
            entity_manager: The entity manager for resolving entities in the query.

        Returns:
            List[MatchData]: A list of matches sorted by confidence.
        """
        sent = tokenize(query)

        def match_intent(intent):
            start_time = time.monotonic()
            try:
                match = intent.match(sent, entity_manager)
                match.detokenize()
                if self.debug:
                    LOG.debug(f"Inference for intent '{intent.name}' took {time.monotonic() - start_time} seconds")
                return match
            except Exception as e:
                LOG.error(f"Error processing intent '{intent.name}': {e}")
                return None

        # Reuse one bounded executor. Constructing a pool for every utterance
        # multiplies the worker count when several queries arrive together.
        # ThreadPoolExecutor.map submits its complete iterable before returning.
        # Protect only that submission step so shutdown cannot race it; result
        # consumption stays outside the lock and concurrent queries still run.
        with self._executor_lock:
            if self._executor_closed:
                LOG.debug("Skipping intent matching on a stopped manager")
                return []
            results = self._executor.map(match_intent, self.objects)
        matches = list(results)

        # Filter out None results from failed matches
        matches = [match for match in matches if match]

        return matches

    def shutdown(self, wait: bool = True) -> None:
        """Release inference workers owned by this manager."""
        with self._executor_lock:
            if self._executor_closed:
                return
            self._executor_closed = True
            executor = self._executor
        executor.shutdown(wait=wait)
