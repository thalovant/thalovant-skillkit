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
from functools import partial
from os.path import join, isfile, splitext
from typing import List, Type, Union

from ovos_utils.log import LOG

import ovos_padatious
from ovos_padatious.trainable import Trainable
from ovos_padatious.train_data import TrainData
from ovos_padatious.util import lines_hash


def _train_and_save(obj: Trainable, cache: str, data: TrainData, print_updates: bool) -> None:
    """
    Internal function to train objects sequentially and save them.

    Args:
        obj (Trainable): Object to train (Intent or Entity).
        cache (str): Path to the cache directory.
        data (TrainData): Training data.
        print_updates (bool): Whether to print updates during training.
    """
    obj.train(data)
    obj.save(cache)
    if print_updates:
        LOG.debug(f'Saving {obj.name} to cache ({cache})')


class TrainingManager:
    """
    Manages sequential training of either Intents or Entities.

    Args:
        cls (Type[Trainable]): Class to wrap (Intent or Entity).
        cache_dir (str): Path to the cache directory.
    """

    def __init__(self, cls: Type[Trainable], cache_dir: str) -> None:
        """
        Initializes the TrainingManager.

        Args:
            cls (Type[Trainable]): Class to be managed (Intent or Entity).
            cache_dir (str): Path where cache files are stored.
        """
        self.cls = cls
        self.cache = cache_dir
        self.objects: List[Trainable] = []
        self.objects_to_train: List[Trainable] = []
        self.train_data = TrainData()

    def add(self, name: str, lines: List[str], reload_cache: bool = False, must_train: bool = True) -> bool:
        """
        Adds a new intent or entity for training or loading from cache.

        Args:
            name (str): Name of the intent or entity.
            lines (List[str]): Lines of training data.
            reload_cache (bool): Whether to force reload of cache if it exists.
            must_train (bool): Whether training is required for the new intent/entity.

        Returns:
            bool: True if this registration actually requires (re)training -
            new content, a forced reload, or a cache load failure. False if
            an identical registration is being replayed and the existing
            cached/trained state already matches, so the caller has no
            reason to mark the container dirty (ovos-core's periodic skill
            registration reconciliation re-emits every intent unchanged on
            a fixed cadence; without this, every replay looked like new
            training work and the background trainer never went idle).
        """
        # Drop any previously queued-but-not-yet-trained duplicate for this
        # name (e.g. the legacy and OVOS-INTENT-4 wire contracts both
        # landing on the same canonical name, ovos-core#831) and any stale
        # queued training-data lines. The currently live, already-trained
        # object for this name (if any) is deliberately left untouched in
        # ``self.objects`` here - it keeps serving matches for the entire
        # compile window and is only swapped out atomically in ``train()``
        # once its freshly trained replacement actually exists. Evicting it
        # eagerly here (as this used to do via a blanket ``self.remove()``)
        # made every intent mid-retrain unmatchable for the whole pass, not
        # just newly registered ones - the "round 6" ser9 finding: a boot
        # drain of ~128 registrations left the previous, perfectly good
        # generation of intents unservable for minutes while the batch
        # compiled.
        self.objects_to_train = [i for i in self.objects_to_train if i.name != name]
        self.train_data.remove_lines(name)

        def _replace_live_object(new_obj) -> None:
            self.objects = [i for i in self.objects if i.name != name]
            self.objects.append(new_obj)

        if not must_train:
            LOG.debug(f"Loading {name} from intent cache")
            _replace_live_object(self.cls.from_file(name=name, folder=self.cache))
            return False
        # general case: load resource (entity or intent) to training queue
        # or if no change occurred to memory data structures
        else:
            hash_fn = join(self.cache, name + '.hash')
            old_hsh = None
            min_ver = splitext(ovos_padatious.__version__)[0]
            # cache format 2: entities persist their value set in a .samples
            # sidecar for the exact-match path; salting the hash retrains
            # pre-sidecar caches once so the sidecar exists everywhere
            new_hsh = lines_hash([min_ver, "format2"] + lines)

            if isfile(hash_fn):
                with open(hash_fn, 'rb') as g:
                    old_hsh = g.read()
                if old_hsh != new_hsh:
                    LOG.debug(f"{name} training data changed! retraining")
            else:
                LOG.debug(f"First time training '{name}")

            retrain = reload_cache or old_hsh != new_hsh
            if not retrain:
                try:
                    LOG.debug(f"Loading {name} from intent cache")
                    _replace_live_object(self.cls.from_file(name=name, folder=self.cache))
                except Exception as e:
                    LOG.error(f"Failed to load intent from cache: {name} - {str(e)}")
                    retrain = True
            if retrain:
                LOG.debug(f"Queuing {name} for training")
                self.objects_to_train.append(self.cls(name=name, hsh=new_hsh))
            self.train_data.add_lines(name, lines)
            return retrain

    def load(self, name: str, file_name: str, reload_cache: bool = False) -> None:
        """
        Loads an entity or intent from a file and adds it for training or caching.

        Args:
            name (str): Name of the intent or entity.
            file_name (str): Path to the file containing the training data.
            reload_cache (bool): Whether to reload the cache for this intent/entity.
        """
        with open(file_name) as f:
            self.add(name, f.read().split('\n'), reload_cache)

    def remove(self, name: str) -> None:
        """
        Removes an intent or entity from the training and cache.

        Args:
            name (str): Name of the intent or entity to remove.
        """
        self.objects = [i for i in self.objects if i.name != name]
        self.objects_to_train = [i for i in self.objects_to_train if i.name != name]
        self.train_data.remove_lines(name)

    def train(self, debug: bool = True, single_thread: Union[None, bool] = None,
              timeout: Union[None, int] = None) -> None:
        """
        Trains all intents and entities sequentially.

        Args:
            debug (bool): Whether to print debug messages.
            single_thread (bool): DEPRECATED
            timeout (float): DEPRECATED
        """
        if single_thread is not None:
            LOG.warning("'single_thread' argument is deprecated and will be ignored")
        if timeout is not None:
            LOG.warning("'timeout' argument is deprecated and will be ignored")

        train_data = self.train_data.copy()  # copy for thread safety
        train = partial(_train_and_save, cache=self.cache, data=train_data, print_updates=debug)

        objs = list(self.objects_to_train) # make a copy so its thread safe
        fails = []
        # Train objects sequentially. The previous, already-trained object
        # for each name (if any) is left serving matches in ``self.objects``
        # the entire time - each name's swap only happens right below, once
        # its own replacement is actually ready, one at a time. So a query
        # arriving mid-pass sees either the old or the new generation of
        # any given intent/entity, never a gap where it briefly vanishes.
        for obj in objs:
            try:
                train(obj)
                new_obj = self.cls.from_file(name=obj.name, folder=self.cache)
                self.objects = [i for i in self.objects if i.name != obj.name]
                self.objects.append(new_obj)
            except Exception as e:
                LOG.error(f"Error training {obj.name}: {e}")
                fails.append(obj)
        self.objects_to_train = [o for o in self.objects_to_train
                                 if o not in objs or o in fails]
